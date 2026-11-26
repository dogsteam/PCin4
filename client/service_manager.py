"""
service_manager.py
Quản lý chế độ chạy nền (Background Service) và Tự khởi động cùng Windows cho IN4.EXE:
- Tự động copy vào C:\\ProgramData\\IN4_Agent\\in4.exe (hoặc AppData\\Local\\IN4_Agent nếu không có admin)
- Tự động đăng ký Windows Task Scheduler & Registry Run để chạy mỗi khi bật máy tính
- Chế độ --silent: Chạy ngầm 100%, chờ mạng ổn định rồi tự quét phần cứng và gửi cập nhật về DB Server 10.10.12.188
- Tự động chạy nền ngay khi tắt cửa sổ [X]
"""

import os
import sys
import json
import shutil
import subprocess
import winreg
import time
import urllib.request
import urllib.error
import urllib.parse
import threading
import getpass
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta

DEFAULT_SERVER_URL = "http://10.10.12.188:8000"
CLIENT_AGENT_PORT = 8005
CLIENT_VERSION = "1.3.0"

_MUTEX_HANDLE = None


def log_sync(msg: str):
    try:
        log_file = os.path.join(get_agent_dir(), "agent_service.log")
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


def is_already_running_mutex() -> bool:
    """Kiểm tra xem đã có tiến trình silent agent nào đang chạy chưa bằng Named Mutex."""
    global _MUTEX_HANDLE
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        mutex_name = "Local\\IN4_Hospital_Agent_Silent_Mutex"
        handle = kernel32.CreateMutexW(None, False, mutex_name)
        if not handle:
            return False
        last_error = kernel32.GetLastError()
        if last_error == 183:  # ERROR_ALREADY_EXISTS
            kernel32.CloseHandle(handle)
            return True
        _MUTEX_HANDLE = handle
        return False
    except Exception:
        return False


def spawn_background_process() -> bool:
    """Khởi động tiến trình in4.exe --silent chạy ngầm hoàn toàn tách biệt."""
    try:
        agent_dir = get_agent_dir()
        target_exe = os.path.join(agent_dir, "in4.exe")
        if not os.path.exists(target_exe):
            current_exe = os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__)
            if current_exe.lower().endswith(".exe") and os.path.exists(current_exe):
                target_exe = current_exe
            else:
                return False

        DETACHED_PROCESS = 0x00000008
        CREATE_NO_WINDOW = 0x08000000
        subprocess.Popen(
            [target_exe, "--silent"],
            creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW,
            close_fds=True
        )
        log_sync("✓ Đã spawn tiến trình chạy ngầm in4.exe --silent thành công.")
        return True
    except Exception as e:
        log_sync(f"Lỗi spawn_background_process: {e}")
        return False


def get_agent_dir() -> str:
    # 1. Thử ProgramData
    prog_data = os.environ.get("PROGRAMDATA", "C:\\ProgramData")
    candidate = os.path.join(prog_data, "IN4_Agent")
    try:
        os.makedirs(candidate, exist_ok=True)
        test_file = os.path.join(candidate, ".write_test")
        with open(test_file, "w") as f:
            f.write("ok")
        os.remove(test_file)
        return candidate
    except Exception:
        pass

    # 2. Dự phòng LocalAppData
    local_app = os.environ.get("LOCALAPPDATA", os.path.expanduser("~\\AppData\\Local"))
    candidate = os.path.join(local_app, "IN4_Agent")
    os.makedirs(candidate, exist_ok=True)
    return candidate


def get_agent_config_path() -> str:
    return os.path.join(get_agent_dir(), "agent_config.json")


def load_saved_agent_config() -> dict:
    cfg_path = get_agent_config_path()
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_agent_config(data: dict):
    cfg_path = get_agent_config_path()
    try:
        # Giữ lại server_url nếu không có trong data
        existing = load_saved_agent_config()
        existing.update({k: v for k, v in data.items() if v is not None and v != ""})
        if not existing.get("server_url"):
            existing["server_url"] = DEFAULT_SERVER_URL
        existing["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log_sync(f"Lỗi lưu agent_config.json: {e}")


def install_auto_start(metadata: dict = None) -> bool:
    """
    Cài đặt Agent tự khởi động cùng Windows:
    1. Sao chép in4.exe vào vị trí hệ thống cố định
    2. Lưu cấu hình vị trí / mã vạch / khoa phòng
    3. Đăng ký Windows Task Scheduler (OnLogon) và Registry Run
    """
    try:
        agent_dir = get_agent_dir()
        target_exe = os.path.join(agent_dir, "in4.exe")

        # 1. Sao chép in4.exe vào thư mục cố định
        current_exe = os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__)
        if current_exe.lower().endswith(".exe") and os.path.exists(current_exe):
            if current_exe.lower() != target_exe.lower():
                try:
                    shutil.copy2(current_exe, target_exe)
                except Exception as copy_err:
                    log_sync(f"Lỗi sao chép exe: {copy_err}")

        # 2. Lưu thông tin metadata
        if metadata:
            save_agent_config(metadata)

        # 3. Đăng ký Windows Registry Run (HKCU) - Tuyệt đối chạy ngầm với cờ --silent
        run_cmd = f'"{target_exe}" --silent'
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, "IN4_Hardware_Agent", 0, winreg.REG_SZ, run_cmd)
        except Exception as reg_err:
            log_sync(f"Lỗi đăng ký Registry Run: {reg_err}")

        # 4. Xóa Task Scheduler cũ nếu có (tránh lỗi Task Scheduler nuốt cờ --silent gây mở UI)
        CREATE_NO_WINDOW = 0x08000000
        try:
            subprocess.run(["schtasks", "/delete", "/tn", "IN4_Hardware_Agent", "/f"], capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
        except Exception:
            pass

        # 5. Mở port Windows Firewall cho kết nối cập nhật / nhận thông báo từ máy chủ
        try:
            subprocess.run([
                "netsh", "advfirewall", "firewall", "add", "rule",
                f"name=IN4_Client_Agent_{CLIENT_AGENT_PORT}",
                "dir=in", "action=allow", "protocol=TCP",
                f"localport={CLIENT_AGENT_PORT}"
            ], capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
        except Exception:
            pass

        log_sync("✓ Đã cài đặt tự khởi động cùng Windows thành công.")
        return True
    except Exception as e:
        log_sync(f"Lỗi install_auto_start: {e}")
        return False


def get_logged_in_user() -> str:
    """Xác định user Windows đang đăng nhập trên máy tính."""
    user = os.environ.get("USERNAME", "")
    if not user:
        try:
            user = getpass.getuser()
        except Exception:
            pass
    if not user:
        try:
            user = os.getlogin()
        except Exception:
            pass
    return user or "UnknownUser"


def get_boot_info() -> tuple:
    """Trả về (boot_time_str, uptime_hours)."""
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        if hasattr(kernel32, 'GetTickCount64'):
            uptime_ms = kernel32.GetTickCount64()
        else:
            uptime_ms = kernel32.GetTickCount()
        uptime_sec = uptime_ms / 1000.0
        uptime_hours = round(uptime_sec / 3600.0, 1)
        boot_dt = datetime.now() - timedelta(seconds=uptime_sec)
        return boot_dt.strftime("%Y-%m-%d %H:%M:%S"), uptime_hours
    except Exception:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 0.0


def perform_self_update(url: str) -> bool:
    """Tự động tải bản in4.exe mới từ máy chủ và cập nhật không cần kỹ thuật viên."""
    log_sync(f">>> Bắt đầu tự động cập nhật từ {url}...")
    agent_dir = get_agent_dir()
    target_exe = os.path.join(agent_dir, "in4.exe")
    temp_exe = os.path.join(agent_dir, "in4_new.tmp")
    updater_bat = os.path.join(agent_dir, "update_runner.bat")

    try:
        urllib.request.urlretrieve(url, temp_exe)
        if not os.path.exists(temp_exe) or os.path.getsize(temp_exe) < 4 * 1024 * 1024:
            log_sync("✗ File tải về không hợp lệ (< 4MB)!")
            return False

        bat_content = f"""@echo off
timeout /t 2 /nobreak >nul
taskkill /F /IM in4.exe /T 2>nul
move /y "{temp_exe}" "{target_exe}"
start "" "{target_exe}" --silent
del "%~f0"
"""
        with open(updater_bat, "w", encoding="utf-8") as f:
            f.write(bat_content)

        DETACHED_PROCESS = 0x00000008
        CREATE_NO_WINDOW = 0x08000000
        subprocess.Popen(
            ["cmd.exe", "/c", updater_bat],
            creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW,
            close_fds=True
        )
        log_sync("✓ Đã kích hoạt kịch bản tự cập nhật thành công!")
        sys.exit(0)
    except Exception as e:
        log_sync(f"Lỗi perform_self_update: {e}")
        return False


def show_client_notification(title: str, msg: str):
    """Hiển thị thông báo nổi bật lên màn hình người dùng bằng Win32 API."""
    def _popup():
        log_sync(f">>> Nhận thông báo từ xa: [{title}] {msg}")
        try:
            import ctypes
            # MB_OK (0x0) | MB_ICONINFORMATION (0x40) | MB_SYSTEMMODAL (0x1000) | MB_SETFOREGROUND (0x10000) | MB_TOPMOST (0x40000)
            flags = 0x0 | 0x40 | 0x1000 | 0x10000 | 0x40000
            ctypes.windll.user32.MessageBoxW(0, str(msg), str(title), flags)
            return
        except Exception as e:
            log_sync(f"MessageBoxW error: {e}")

        # Dự phòng bằng WTSSendMessageW nếu là remote desktop / session khác
        try:
            import ctypes
            response = ctypes.c_ulong()
            ctypes.windll.wtsapi32.WTSSendMessageW(
                0, -1,
                str(title), len(str(title)) * 2,
                str(msg), len(str(msg)) * 2,
                0x40 | 0x1000, 0,
                ctypes.byref(response), False
            )
        except Exception:
            pass

    threading.Thread(target=_popup, daemon=True).start()


class ClientRemoteHandler(BaseHTTPRequestHandler):
    """Xử lý các lệnh từ xa từ Máy chủ trung tâm (Port 8005): Ping, Thông báo, Update."""
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        params = urllib.parse.parse_qs(parsed.query)

        if path == "/ping":
            boot_str, uptime_h = get_boot_info()
            self.send_json_response(200, {
                "status": "ok",
                "agent": "IN4_Silent_Agent",
                "version": CLIENT_VERSION,
                "port": CLIENT_AGENT_PORT,
                "user": get_logged_in_user(),
                "boot_time": boot_str,
                "uptime_hours": uptime_h
            })

        elif path == "/notify":
            title = params.get("title", ["THÔNG BÁO TỪ PHÒNG CNTT BỆNH VIỆN"])[0]
            msg = params.get("msg", [""])[0] or params.get("message", [""])[0]
            if msg:
                show_client_notification(title, msg)
                self.send_json_response(200, {"status": "success", "message": "Đã hiển thị thông báo trên màn hình máy trạm."})
            else:
                self.send_json_response(400, {"status": "error", "message": "Thiếu nội dung thông báo (msg)"})

        elif path == "/update":
            update_url = params.get("url", [f"{DEFAULT_SERVER_URL}/in4.exe"])[0]
            threading.Thread(target=lambda: perform_self_update(update_url), daemon=True).start()
            self.send_json_response(200, {"status": "success", "message": f"Đã tiếp nhận lệnh tự cập nhật từ {update_url}."})

        else:
            self.send_json_response(404, {"error": "Not Found"})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        content_len = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_len).decode('utf-8') if content_len > 0 else ""
        data = {}
        try:
            if body: data = json.loads(body)
        except Exception: pass

        if path == "/notify":
            title = data.get("title", "THÔNG BÁO TỪ PHÒNG CNTT BỆNH VIỆN")
            msg = data.get("message") or data.get("msg", "")
            if msg:
                show_client_notification(title, msg)
                self.send_json_response(200, {"status": "success", "message": "Đã hiển thị thông báo trên màn hình máy trạm."})
            else:
                self.send_json_response(400, {"status": "error", "message": "Thiếu nội dung thông báo"})

        elif path == "/update":
            update_url = data.get("url", f"{DEFAULT_SERVER_URL}/in4.exe")
            threading.Thread(target=lambda: perform_self_update(update_url), daemon=True).start()
            self.send_json_response(200, {"status": "success", "message": f"Đã tiếp nhận lệnh tự cập nhật từ {update_url}."})
        else:
            self.send_json_response(404, {"error": "Not Found"})

    def send_json_response(self, code, data):
        try:
            body = json.dumps(data, ensure_ascii=False).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(body)
        except Exception: pass

    def log_message(self, format, *args):
        pass


def start_client_remote_server(agent_port: int = CLIENT_AGENT_PORT):
    """Khởi động cổng lắng nghe lệnh cập nhật và thông báo từ xa."""
    def run_server():
        try:
            server = HTTPServer(("0.0.0.0", agent_port), ClientRemoteHandler)
            log_sync(f"✓ Cổng điều khiển & cập nhật từ xa đã mở trên port {agent_port}")
            server.serve_forever()
        except Exception as e:
            log_sync(f"Không thể mở cổng điều khiển {agent_port}: {e}")
    t = threading.Thread(target=run_server, daemon=True)
    t.start()


_SHUTDOWN_HOOK = None

def register_shutdown_handler(mac: str, server_url: str):
    """Đăng ký hook bắt sự kiện Windows Tắt máy (Shutdown / Logoff)."""
    def send_shutdown_signal():
        try:
            api_url = f"{server_url.rstrip('/')}/api/power-event"
            boot_str, uptime_h = get_boot_info()
            payload = {
                "mac_address": mac,
                "event_type": "SHUTDOWN",
                "logged_in_user": get_logged_in_user(),
                "uptime_hours": uptime_h,
                "notes": f"Tắt máy lúc {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            }
            req_data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(api_url, data=req_data, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=2):
                pass
        except Exception:
            pass

    import atexit
    atexit.register(send_shutdown_signal)

    try:
        import ctypes
        from ctypes import wintypes
        HandlerRoutine = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)
        def ctrl_handler(ctrl_type):
            send_shutdown_signal()
            return False
        global _SHUTDOWN_HOOK
        _SHUTDOWN_HOOK = HandlerRoutine(ctrl_handler)
        ctypes.windll.kernel32.SetConsoleCtrlHandler(_SHUTDOWN_HOOK, True)
    except Exception:
        pass


def ack_server_command(cmd_id: int, server_url: str):
    """Báo cho server biết đã xử lý xong lệnh."""
    if not cmd_id:
        return
    try:
        ack_url = f"{server_url.rstrip('/')}/api/command-ack/{cmd_id}"
        req = urllib.request.Request(ack_url, data=b"{}", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=3):
            pass
    except Exception:
        pass


def send_heartbeat(mac: str, ip: str, server_url: str):
    """Gửi tín hiệu sống định kỳ (Heartbeat) & tiếp nhận lệnh điều khiển/thông báo từ Server."""
    try:
        api_url = f"{server_url.rstrip('/')}/api/heartbeat"
        boot_str, uptime_h = get_boot_info()
        payload = {
            "mac_address": mac,
            "ip_address": ip,
            "logged_in_user": get_logged_in_user(),
            "boot_time": boot_str,
            "uptime_hours": uptime_h,
            "client_agent_port": CLIENT_AGENT_PORT,
            "client_version": CLIENT_VERSION
        }
        req_data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(api_url, data=req_data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            body = resp.read().decode("utf-8")
            data = json.loads(body)
            # Xử lý các lệnh từ Server (thông báo / update)
            commands = data.get("commands", [])
            for cmd in commands:
                cmd_id = cmd.get("command_id")
                cmd_type = cmd.get("type")
                pl = cmd.get("payload", {})
                if cmd_type == "notify":
                    show_client_notification(pl.get("title", "THÔNG BÁO TỪ PHÒNG CNTT"), pl.get("message", ""))
                    ack_server_command(cmd_id, server_url)
                elif cmd_type == "update":
                    update_url = pl.get("url") or f"{server_url.rstrip('/')}/in4.exe"
                    ack_server_command(cmd_id, server_url)
                    perform_self_update(update_url)
    except Exception:
        pass


def send_telemetry(hw_data: dict, meta: dict, server_url: str) -> bool:
    api_url = f"{server_url.rstrip('/')}/api/inventory"
    boot_str, uptime_h = get_boot_info()
    payload = {
        **hw_data,
        "barcode": meta.get("barcode", ""),
        "department": meta.get("department", ""),
        "room_number": meta.get("room_number", ""),
        "room_name": meta.get("room_name", ""),
        "user_name": meta.get("user_name", ""),
        "user_phone": meta.get("user_phone", ""),
        "notes": meta.get("notes", ""),
        "logged_in_user": get_logged_in_user(),
        "boot_time": boot_str,
        "client_agent_port": CLIENT_AGENT_PORT,
        "client_version": CLIENT_VERSION
    }

    req_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        api_url,
        data=req_data,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=6) as response:
        body = response.read().decode("utf-8")
        res = json.loads(body)
        return res.get("status") == "success"


def run_silent_background_agent():
    """
    Tiến trình chạy nền hoàn toàn (--silent):
    - Khởi động ngầm cùng Windows khi bật máy tính
    - Mở cổng điều khiển & cập nhật từ xa (Port 8005)
    - Chờ mạng LAN kết nối và DHCP cấp IP ổn định (~10 giây)
    - Tự động quét telemetry phần cứng lúc khởi động và gửi về DB Server
    - Định kỳ gửi heartbeat (0% CPU) và phát hiện tắt máy
    """
    if is_already_running_mutex():
        sys.exit(0)

    log_sync("==================================================")
    log_sync(">>> IN4 Silent Agent đã khởi động cùng Windows...")

    # 1. Mở ngay cổng lắng nghe từ xa 8005 (cho phép nhận thông báo / update từ server)
    start_client_remote_server(CLIENT_AGENT_PORT)

    # 2. Chờ card mạng LAN và DHCP nhận IP
    time.sleep(10)

    try:
        import hardware_collector
    except ImportError:
        sys.path.append(os.path.dirname(os.path.abspath(__file__)))
        import hardware_collector

    meta = load_saved_agent_config()
    server_url = meta.get("server_url", DEFAULT_SERVER_URL)
    hw_data = hardware_collector.collect_all_hardware_info()
    mac = hw_data.get("mac_address", "")
    ip = hw_data.get("ip_address", "")

    # Đăng ký hook bắt sự kiện tắt máy tính
    if mac:
        register_shutdown_handler(mac, server_url)

    # Gửi telemetry ban đầu lúc khởi động máy tính
    for attempt in range(1, 4):
        try:
            synced = send_telemetry(hw_data, meta, server_url)
            if synced:
                log_sync(f"✓ CẬP NHẬT KHỞI ĐỘNG THÀNH CÔNG về Server {server_url} | User: {get_logged_in_user()} | Host: {hw_data.get('hostname')}")
                break
        except Exception as err:
            log_sync(f"[Lần thử {attempt}/3] Chưa thể gửi về {server_url}: {err}")
            time.sleep(15)

    # Vòng lặp duy trì: gửi heartbeat mỗi 5 giây (0% CPU, nhận lệnh từ server ngay tức thì)
    # và quét lại phần cứng mỗi 4 tiếng
    heartbeat_counter = 0
    while True:
        try:
            time.sleep(5) # 5 giây
            heartbeat_counter += 1
            meta = load_saved_agent_config()
            server_url = meta.get("server_url", DEFAULT_SERVER_URL)

            # Gửi heartbeat định kỳ để server biết máy đang BẬT và nhận lệnh chờ
            send_heartbeat(mac, ip, server_url)

            # Mỗi 4 tiếng (2880 chu kỳ x 5s) quét lại phần cứng toàn diện
            if heartbeat_counter >= 2880:
                heartbeat_counter = 0
                hw_data = hardware_collector.collect_all_hardware_info()
                mac = hw_data.get("mac_address", "")
                ip = hw_data.get("ip_address", "")
                send_telemetry(hw_data, meta, server_url)

        except Exception as loop_err:
            log_sync(f"Lỗi vòng lặp nền: {loop_err}")
