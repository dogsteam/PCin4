"""
main.py
FastAPI Server tiếp nhận dữ liệu phần cứng từ PC client và cung cấp Web Dashboard quản trị cho phòng CNTT Bệnh viện.
"""

import io
import sys
import os

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

import database

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    database.init_db()
    import threading
    import time
    def _bg_status_updater():
        while True:
            try:
                database.update_online_status_threshold(OFFLINE_THRESHOLD_SECONDS)
            except Exception:
                pass
            time.sleep(60)
    threading.Thread(target=_bg_status_updater, daemon=True).start()
    yield


app = FastAPI(
    title="Hệ thống Quản lý Thiết bị & Phần cứng PC Bệnh viện",
    description="API tiếp nhận thông số phần cứng từ máy trạm và cung cấp Dashboard tra cứu",
    version="1.2.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class InventoryPayload(BaseModel):
    barcode: Optional[str] = Field("", description="Mã vạch / Mã quản lý tài sản bệnh viện")
    mac_address: str = Field(..., description="Địa chỉ MAC của máy (Khóa duy nhất)")
    hostname: Optional[str] = ""
    ip_address: Optional[str] = ""
    os_name: Optional[str] = ""
    mainboard_info: Optional[str] = ""
    cpu_info: Optional[str] = ""
    ram_total_gb: Optional[float] = 0.0
    ram_details: Optional[str] = ""
    storage_details: Optional[str] = ""
    monitors_details: Optional[str] = ""
    peripherals_details: Optional[str] = ""
    room_number: Optional[str] = ""
    room_name: Optional[str] = ""
    department: Optional[str] = ""
    user_name: Optional[str] = ""
    user_phone: Optional[str] = ""
    notes: Optional[str] = ""
    logged_in_user: Optional[str] = ""
    boot_time: Optional[str] = ""
    client_agent_port: Optional[int] = 8005
    client_version: Optional[str] = "1.3.0"


class HeartbeatPayload(BaseModel):
    mac_address: str
    ip_address: Optional[str] = ""
    logged_in_user: Optional[str] = ""
    boot_time: Optional[str] = ""
    uptime_hours: Optional[float] = 0.0
    client_agent_port: Optional[int] = 8005
    client_version: Optional[str] = "1.3.0"


class PowerEventPayload(BaseModel):
    mac_address: str
    event_type: str # 'STARTUP' | 'SHUTDOWN'
    logged_in_user: Optional[str] = ""
    uptime_hours: Optional[float] = 0.0
    notes: Optional[str] = ""


class RemoteNotifyPayload(BaseModel):
    mac_address: Optional[str] = ""
    ip_address: Optional[str] = ""
    port: Optional[int] = 8005
    title: Optional[str] = "THÔNG BÁO TỪ PHÒNG CNTT BỆNH VIỆN"
    message: str


class RemoteUpdatePayload(BaseModel):
    mac_address: Optional[str] = ""
    ip_address: Optional[str] = ""
    port: Optional[int] = 8005
    url: Optional[str] = ""


class RemoteUpdateAllPayload(BaseModel):
    target_version: str = "1.3.1"
    url: Optional[str] = ""


class RemoteUpdateBatchPayload(BaseModel):
    mac_addresses: List[str]
    target_version: Optional[str] = ""
    url: Optional[str] = ""


class RemotePingPayload(BaseModel):
    mac_address: Optional[str] = ""
    ip_address: Optional[str] = ""
    port: Optional[int] = 8005


@app.post("/api/inventory", tags=["Client API"])
def receive_inventory(data: InventoryPayload):
    if not data.mac_address or not data.mac_address.strip():
        raise HTTPException(status_code=400, detail="Thiếu địa chỉ MAC của thiết bị")

    try:
        record_id = database.upsert_computer(data.dict())
        return {
            "status": "success",
            "message": "Đã lưu thông tin máy tính thành công!",
            "mac_address": data.mac_address,
            "record_id": record_id
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi lưu CSDL: {str(e)}")


HEARTBEAT_INTERVAL_SECONDS = 300   # 5 phút/lần (tối ưu cho quy mô ~800 máy)
OFFLINE_THRESHOLD_SECONDS = 720    # 12 phút không có tín hiệu mới đánh dấu Offline


@app.post("/api/heartbeat", tags=["Client API"])
def receive_heartbeat(data: HeartbeatPayload):
    try:
        client_ver = (data.client_version or "").strip()
        database.record_heartbeat(
            data.mac_address,
            data.ip_address,
            data.logged_in_user or "",
            data.uptime_hours or 0.0,
            data.boot_time or "",
            client_ver
        )
        # Kiểm tra và trả về ngay các lệnh đang chờ (Thông báo / Cập nhật)
        pending_cmds = database.get_pending_commands(data.mac_address)
        if pending_cmds:
            print(f"[HEARTBEAT-CMD] Giao {len(pending_cmds)} lenh cho {data.mac_address} ({data.ip_address}) | ver={client_ver}")
        target_ver = database.get_setting("target_client_version", "").strip()
        resp_data = {
            "status": "success",
            "heartbeat_interval": HEARTBEAT_INTERVAL_SECONDS,
            "target_client_version": target_ver,
            "commands": pending_cmds
        }
        if target_ver and client_ver and client_ver != target_ver:
            resp_data["update_url"] = database.get_setting("target_client_url", "http://10.10.12.188:8000/in4.exe")
            sha = _get_local_in4_sha256()
            if sha:
                resp_data["update_sha256"] = sha
        return resp_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi heartbeat: {str(e)}")


@app.post("/api/command-ack/{command_id}", tags=["Client API"])
def ack_client_command(command_id: int):
    try:
        database.ack_command(command_id)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi ack command: {str(e)}")


@app.post("/api/power-event", tags=["Client API"])
def receive_power_event(data: PowerEventPayload):
    try:
        database.record_power_event(data.mac_address, data.event_type, data.logged_in_user or "", data.uptime_hours or 0.0, data.notes or "")
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi power-event: {str(e)}")


@app.get("/api/hardware-alerts", tags=["Cảnh báo Phần cứng"])
def get_hardware_alerts():
    return database.get_hardware_alerts()


@app.post("/api/hardware-alerts/ack/{alert_id}", tags=["Cảnh báo Phần cứng"])
def ack_alert(alert_id: int):
    database.ack_hardware_alert(alert_id)
    return {"status": "success"}


@app.get("/api/overnight-pcs", tags=["Giám sát Bật/Tắt"])
def get_overnight_pcs():
    return database.get_overnight_pcs()


@app.get("/api/power-logs", tags=["Giám sát Bật/Tắt"])
def get_power_logs(mac: Optional[str] = None):
    return database.get_power_logs(mac_address=mac)


@app.post("/api/remote/notify", tags=["Điều khiển từ xa"])
def remote_notify(req: RemoteNotifyPayload):
    import urllib.request
    import json

    mac = req.mac_address or database.get_mac_by_ip(req.ip_address)
    cmd_id = None
    if mac:
        cmd_id = database.queue_command(mac, "notify", {"title": req.title, "message": req.message})

    # Thử gửi trực tiếp qua port 8005 nếu cùng mạng (timeout ngắn 1.5s)
    direct_ok = False
    if req.ip_address:
        try:
            target_url = f"http://{req.ip_address}:{req.port or 8005}/notify"
            payload = json.dumps({"title": req.title, "message": req.message}).encode("utf-8")
            r = urllib.request.Request(target_url, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(r, timeout=1.5) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
                if res_data.get("status") == "success":
                    direct_ok = True
                    if cmd_id:
                        database.ack_command(cmd_id)
        except Exception:
            pass

    return {
        "status": "success",
        "message": "✓ Đã gửi thông báo tức thời thành công!" if direct_ok else "✓ Đã gửi thông báo vào hàng đợi máy trạm (sẽ hiển thị ngay trong vài giây khi máy kết nối)!",
        "direct_delivered": direct_ok,
        "queued": True
    }


def _find_in4_exe_path() -> Optional[str]:
    candidates = [
        os.path.join(BASE_DIR, "in4.exe"),
        os.path.join(os.getcwd(), "in4.exe"),
        os.path.join(BASE_DIR, "Client", "in4.exe"),
        os.path.join(BASE_DIR, "..", "in4.exe"),
        os.path.join(BASE_DIR, "..", "Client", "in4.exe")
    ]
    for p in candidates:
        if os.path.exists(p) and os.path.isfile(p):
            return p
    return None


def _get_local_in4_sha256() -> str:
    import hashlib
    exe_path = _find_in4_exe_path()
    if not exe_path:
        return ""
    try:
        h = hashlib.sha256()
        with open(exe_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest().lower()
    except Exception:
        return ""


@app.post("/api/remote/update", tags=["Điều khiển từ xa"])
def remote_update(req: RemoteUpdatePayload):
    import urllib.request
    import json

    mac = req.mac_address or database.get_mac_by_ip(req.ip_address)
    update_file_url = req.url or f"http://10.10.12.188:8000/in4.exe"
    sha256_hash = ""
    if not req.url or req.url.rstrip("/").endswith("/in4.exe"):
        sha256_hash = _get_local_in4_sha256()

    cmd_payload = {"url": update_file_url}
    if sha256_hash:
        cmd_payload["sha256"] = sha256_hash

    cmd_id = None
    if mac:
        cmd_id = database.queue_command(mac, "update", cmd_payload)

    pc_info = database.get_computer_by_mac(mac) if mac else None
    cur_ver = (pc_info.get("client_version") or "1.3.0").strip() if pc_info else "1.3.0"

    direct_ok = False
    # Chỉ đẩy trực tiếp qua port 8005 với client >= 1.3.1 (v1.3.0 phải nhận qua Heartbeat Main Thread để tránh taskkill /T)
    if req.ip_address and cur_ver != "1.3.0":
        try:
            target_url = f"http://{req.ip_address}:{req.port or 8005}/update"
            payload = json.dumps(cmd_payload).encode("utf-8")
            r = urllib.request.Request(target_url, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(r, timeout=1.5) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
                if res_data.get("status") == "success":
                    direct_ok = True
                    if cmd_id:
                        database.ack_command(cmd_id)
        except Exception as push_err:
            print(f"[UPDATE-PUSH] Khong goi duoc {req.ip_address}:{req.port or 8005} -> cho vao hang doi ({push_err})")

    if direct_ok:
        print(f"[UPDATE-PUSH] Da day lenh update truc tiep toi {req.ip_address}:{req.port or 8005} (MAC={mac})")
    elif mac:
        print(f"[UPDATE-QUEUE] Da xep lenh update vao hang doi cho MAC={mac} (cmd_id={cmd_id})")

    return {
        "status": "success",
        "message": "✓ Đã kích hoạt lệnh tự cập nhật tức thời!" if direct_ok else "✓ Đã gửi lệnh cập nhật vào hàng đợi máy trạm!",
        "direct_delivered": direct_ok,
        "queued": True,
        "sha256": sha256_hash
    }


def _dispatch_update_to_devices(devices: list, update_file_url: str, sha256_hash: str) -> int:
    """Xếp hàng lệnh update và đẩy song song qua Port 8005 cho một danh sách máy."""
    import urllib.request
    import json
    from concurrent.futures import ThreadPoolExecutor

    cmd_payload = {"url": update_file_url}
    if sha256_hash:
        cmd_payload["sha256"] = sha256_hash

    def _push_one(pc: dict) -> bool:
        mac = pc.get("mac_address", "")
        ip = pc.get("ip_address", "")
        port = int(pc.get("client_agent_port") or 8005)
        cur_ver = (pc.get("client_version") or "1.3.0").strip()
        cmd_id = database.queue_command(mac, "update", cmd_payload) if mac else None
        if ip and pc.get("is_online") and cur_ver != "1.3.0":
            try:
                target_url = f"http://{ip}:{port}/update"
                payload = json.dumps(cmd_payload).encode("utf-8")
                r = urllib.request.Request(target_url, data=payload, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(r, timeout=1.5) as resp:
                    res_data = json.loads(resp.read().decode("utf-8"))
                    if res_data.get("status") == "success":
                        if cmd_id:
                            database.ack_command(cmd_id)
                        return True
            except Exception:
                pass
        return False

    direct_ok_count = 0
    with ThreadPoolExecutor(max_workers=15) as executor:
        for ok in executor.map(_push_one, devices):
            if ok:
                direct_ok_count += 1
    return direct_ok_count


@app.post("/api/remote/update-all", tags=["Điều khiển từ xa"])
def remote_update_all(req: RemoteUpdateAllPayload):
    target_ver = (req.target_version or "1.3.1").strip()
    update_file_url = (req.url or "").strip() or "http://10.10.12.188:8000/in4.exe"
    sha256_hash = _get_local_in4_sha256() if update_file_url.rstrip("/").endswith("/in4.exe") else ""

    # Lưu phiên bản mục tiêu (Desired State) để các máy bật sau / tương lai tự đối chiếu
    database.set_setting("target_client_version", target_ver)
    database.set_setting("target_client_url", update_file_url)

    outdated = database.get_outdated_computers(target_ver)
    if not outdated:
        return {
            "status": "success",
            "target_version": target_ver,
            "outdated_count": 0,
            "direct_delivered": 0,
            "queued_count": 0,
            "message": f"✓ Toàn bộ máy trạm đã ở phiên bản {target_ver}!"
        }

    direct_ok_count = _dispatch_update_to_devices(outdated, update_file_url, sha256_hash)
    return {
        "status": "success",
        "target_version": target_ver,
        "outdated_count": len(outdated),
        "direct_delivered": direct_ok_count,
        "queued_count": len(outdated) - direct_ok_count,
        "message": (
            f"✓ Đã đặt phiên bản mục tiêu v{target_ver} cho {len(outdated)} máy chưa cập nhật "
            f"({direct_ok_count} máy nhận tức thì qua Port 8005, {len(outdated) - direct_ok_count} máy chờ nhận qua Heartbeat/khi bật máy)."
        )
    }


@app.post("/api/remote/update-batch", tags=["Điều khiển từ xa"])
def remote_update_batch(req: RemoteUpdateBatchPayload):
    """Chủ động đẩy lệnh update cho một nhóm máy cụ thể (theo danh sách MAC đang lọc)."""
    if not req.mac_addresses:
        raise HTTPException(status_code=400, detail="Danh sách máy trống!")

    update_file_url = (req.url or "").strip() or "http://10.10.12.188:8000/in4.exe"
    sha256_hash = _get_local_in4_sha256() if update_file_url.rstrip("/").endswith("/in4.exe") else ""
    if req.target_version and req.target_version.strip():
        database.set_setting("target_client_version", req.target_version.strip())
        database.set_setting("target_client_url", update_file_url)

    mac_set = {m.strip().upper() for m in req.mac_addresses if m and m.strip()}
    targets = [c for c in database.get_all_computers() if (c.get("mac_address") or "").upper() in mac_set]
    if not targets:
        raise HTTPException(status_code=404, detail="Không tìm thấy máy phù hợp trong CSDL!")

    direct_ok_count = _dispatch_update_to_devices(targets, update_file_url, sha256_hash)
    return {
        "status": "success",
        "total_targeted": len(targets),
        "direct_delivered": direct_ok_count,
        "queued_count": len(targets) - direct_ok_count,
        "message": (
            f"✓ Đã đẩy lệnh cập nhật cho nhóm {len(targets)} máy "
            f"({direct_ok_count} máy nhận tức thì qua Port 8005, {len(targets) - direct_ok_count} máy chờ nhận qua Heartbeat)."
        )
    }


def check_single_device_ping(mac: str, ip: str, port: int = 8005) -> dict:
    """Kiểm tra đối soát đa tầng trạng thái máy tính (Heartbeat, ICMP Ping, Port 8005)."""
    import subprocess
    import time
    from datetime import datetime

    pc = database.get_computer_by_mac(mac) if mac else None
    if not ip and pc:
        ip = pc.get("ip_address", "")
    if not mac and ip:
        mac = database.get_mac_by_ip(ip)
        if mac and not pc:
            pc = database.get_computer_by_mac(mac)

    hostname = pc.get("hostname", "") if pc else ""
    user_name = pc.get("user_name", "") if pc else ""
    logged_in_user = pc.get("logged_in_user", "") if pc else ""
    last_seen = pc.get("last_seen") if pc else None

    # 1. Tầng Heartbeat (Client chủ động ping lên Server qua Outbound HTTP)
    heartbeat_active = False
    heartbeat_seconds_ago = None
    if last_seen:
        try:
            ls_dt = datetime.strptime(str(last_seen)[:19], "%Y-%m-%d %H:%M:%S")
            heartbeat_seconds_ago = round((datetime.now() - ls_dt).total_seconds(), 1)
            if heartbeat_seconds_ago <= float(OFFLINE_THRESHOLD_SECONDS):
                heartbeat_active = True
        except Exception:
            pass

    # 2. Tầng ICMP Ping (Giao thức ping chuẩn Windows/Linux)
    icmp_success = False
    icmp_latency_ms = None
    if ip and ip != "127.0.0.1":
        try:
            t0 = time.time()
            creationflags = 0x08000000 if sys.platform == "win32" else 0
            res = subprocess.run(
                ["ping", "-n", "1", "-w", "800", ip],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=creationflags
            )
            dt_ms = round((time.time() - t0) * 1000, 1)
            if res.returncode == 0:
                icmp_success = True
                icmp_latency_ms = dt_ms
        except Exception:
            pass
    elif ip == "127.0.0.1":
        icmp_success = True
        icmp_latency_ms = 1.0

    # 3. Tầng HTTP Port 8005 (Port dịch vụ của Agent in4.exe)
    agent_port_active = False
    agent_info = {}
    target_port = port or (pc.get("client_agent_port") if pc else 8005) or 8005
    if ip:
        try:
            import urllib.request
            req_url = f"http://{ip}:{target_port}/ping"
            req_obj = urllib.request.Request(req_url)
            with urllib.request.urlopen(req_obj, timeout=0.8) as resp:
                if resp.status == 200:
                    agent_port_active = True
                    try:
                        agent_info = json.loads(resp.read().decode("utf-8"))
                    except Exception:
                        pass
        except Exception:
            pass

    # Đánh giá & kết luận tổng hợp
    agent_active = (heartbeat_active or agent_port_active)

    if agent_active and icmp_success:
        status_code = "ONLINE_PERFECT"
        status_label = "ONLINE HOÀN HẢO"
        badge = "success"
        desc = f"Máy tính đang BẬT, mạng thông suốt (ICMP Ping {icmp_latency_ms}ms) và phần mềm Agent IN4 đang chạy phản hồi thời gian thực."
    elif agent_active and not icmp_success:
        status_code = "ONLINE_HEARTBEAT"
        status_label = "ONLINE (QUA HEARTBEAT)"
        badge = "info"
        desc = f"Máy tính đang BẬT và Agent gửi dữ liệu tốt ({heartbeat_seconds_ago}s trước). Ping ICMP không phản hồi do Tường lửa (Firewall) máy trạm chặn chiều vào."
    elif not agent_active and icmp_success:
        status_code = "WARNING_NO_AGENT"
        status_label = "CẢNH BÁO: CHƯA CHẠY AGENT"
        badge = "warning"
        desc = f"Máy tính ĐANG BẬT NGUỒN (ICMP Ping {icmp_latency_ms}ms), nhưng không nhận được tín hiệu từ phần mềm IN4 (người dùng có thể đã tắt hoặc app bị đóng)."
    else:
        status_code = "OFFLINE"
        status_label = "OFFLINE (ĐÃ TẮT MÁY)"
        badge = "secondary"
        desc = "Cả ICMP Ping và Heartbeat đều không phản hồi. Máy tính đã tắt nguồn hoặc ngắt kết nối mạng hoàn toàn."

    is_online_final = 1 if (heartbeat_active or agent_port_active) else 0
    if is_online_final:
        db_health = "ONLINE"
    elif icmp_success:
        db_health = "NO_AGENT_SUSPECT_AV"
    else:
        db_health = "OFFLINE"

    if mac:
        database.update_probe_result(
            mac,
            is_online_final,
            1 if icmp_success else 0,
            1 if agent_port_active else 0,
            db_health
        )

    return {
        "status": "success",
        "mac_address": mac,
        "ip_address": ip,
        "hostname": hostname,
        "user_name": user_name,
        "logged_in_user": logged_in_user,
        "is_online": bool(is_online_final),
        "status_code": status_code,
        "status_label": status_label,
        "badge": badge,
        "description": desc,
        "heartbeat_active": heartbeat_active,
        "heartbeat_seconds_ago": heartbeat_seconds_ago,
        "icmp_success": icmp_success,
        "icmp_latency_ms": icmp_latency_ms,
        "agent_port_active": agent_port_active,
        "agent_info": agent_info,
        "db_client_version": (pc.get("client_version") or "1.3.0") if pc else "1.3.0"
    }


@app.post("/api/remote/ping", tags=["Điều khiển từ xa"])
def remote_ping(req: RemotePingPayload):
    return check_single_device_ping(req.mac_address or "", req.ip_address or "", req.port or 8005)


@app.post("/api/remote/ping-all", tags=["Điều khiển từ xa"])
def remote_ping_all():
    from concurrent.futures import ThreadPoolExecutor
    computers = database.get_all_computers()
    if not computers:
        return {"total": 0, "online_count": 0, "offline_count": 0, "results": []}

    results = []
    with ThreadPoolExecutor(max_workers=15) as executor:
        futures = [
            executor.submit(check_single_device_ping, c.get("mac_address", ""), c.get("ip_address", ""), c.get("client_agent_port", 8005))
            for c in computers
        ]
        for f in futures:
            try:
                results.append(f.result())
            except Exception:
                pass

    online_count = sum(1 for r in results if r.get("is_online"))
    offline_count = len(results) - online_count

    return {
        "status": "success",
        "total": len(results),
        "online_count": online_count,
        "offline_count": offline_count,
        "results": results
    }


@app.get("/api/inventory", tags=["Quản lý"])
def list_computers(search: Optional[str] = None, department: Optional[str] = None):
    return database.get_all_computers(search=search, department=department)


@app.get("/api/statistics", tags=["Quản lý"])
def get_stats():
    return database.get_statistics()


@app.get("/api/remote/pending", tags=["Điều khiển từ xa"])
def get_pending_queue():
    conn = database.get_db_connection()
    rows = conn.execute("SELECT id, mac_address, command_type, status, created_at, executed_at FROM pending_commands ORDER BY id DESC LIMIT 50").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/departments", tags=["Quản lý"])
def get_departments_list():
    return database.get_departments()


@app.delete("/api/inventory/{mac_address}", tags=["Quản lý"])
def delete_computer_record(mac_address: str):
    deleted = database.delete_computer(mac_address)
    if not deleted:
        raise HTTPException(status_code=404, detail="Không tìm thấy thiết bị")
    return {"status": "success", "message": f"Đã xóa thiết bị {mac_address}"}


@app.get("/api/export-excel", tags=["Báo cáo"])
def export_to_excel(department: Optional[str] = None, search: Optional[str] = None):
    computers = database.get_all_computers(search=search, department=department)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "DS May Tinh Benh Vien"

    headers = [
        "STT", "Mã vạch tài sản", "Khoa / Bộ phận", "Số phòng", "Tên phòng", "Người sử dụng", "Số ĐT",
        "Tên máy (Host)", "Địa chỉ IP", "Địa chỉ MAC", "Hệ điều hành",
        "Bo mạch chủ (Mainboard & Năm)", "CPU & Năm SX", "RAM (GB)", "Chi tiết RAM (Số thanh cắm & Khe)",
        "Ổ cứng (SSD/HDD)", "Màn hình (Hãng, Model, Inch, Năm SX)", "Bàn phím & Chuột",
        "Ghi chú", "Lần cập nhật cuối"
    ]

    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1B4F72", end_color="1B4F72", fill_type="solid")
    center_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left_align = Alignment(horizontal="left", vertical="center", wrap_text=True)
    thin_border = Border(
        left=Side(style='thin', color='BDC3C7'),
        right=Side(style='thin', color='BDC3C7'),
        top=Side(style='thin', color='BDC3C7'),
        bottom=Side(style='thin', color='BDC3C7')
    )

    ws.append(headers)
    for col_num in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_num)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center_align
        cell.border = thin_border
    ws.row_dimensions[1].height = 28

    for idx, c in enumerate(computers, 1):
        row_data = [
            idx,
            c.get("barcode", ""),
            c.get("department", ""),
            c.get("room_number", ""),
            c.get("room_name", ""),
            c.get("user_name", ""),
            c.get("user_phone", ""),
            c.get("hostname", ""),
            c.get("ip_address", ""),
            c.get("mac_address", ""),
            c.get("os_name", ""),
            c.get("mainboard_info", ""),
            c.get("cpu_info", ""),
            c.get("ram_total_gb", 0),
            c.get("ram_details", ""),
            c.get("storage_details", ""),
            c.get("monitors_details", ""),
            c.get("peripherals_details", ""),
            c.get("notes", ""),
            c.get("updated_at", "")
        ]
        ws.append(row_data)
        current_row = idx + 1
        ws.row_dimensions[current_row].height = 24
        for col_num in range(1, len(headers) + 1):
            cell = ws.cell(row=current_row, column=col_num)
            cell.border = thin_border
            cell.alignment = center_align if col_num in (1, 2, 4, 7, 9, 10, 14, 20) else left_align

    for col in ws.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = openpyxl.utils.get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = min(max(max_len + 3, 10), 45)

    stream = io.BytesIO()
    wb.save(stream)
    excel_bytes = stream.getvalue()

    filename = "Kiem_ke_May_tinh_Benh_vien.xlsx"
    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@app.get("/in4.exe", tags=["Tải Tool Client"])
@app.get("/download", tags=["Tải Tool Client"])
@app.get("/download/in4.exe", tags=["Tải Tool Client"])
def download_in4_client():
    candidates = [
        os.path.join(BASE_DIR, "in4.exe"),
        os.path.join(os.getcwd(), "in4.exe"),
        os.path.join(BASE_DIR, "Client", "in4.exe"),
        os.path.join(BASE_DIR, "..", "in4.exe"),
        os.path.join(BASE_DIR, "..", "Client", "in4.exe")
    ]
    for p in candidates:
        if os.path.exists(p) and os.path.isfile(p):
            return FileResponse(
                path=p,
                filename="in4.exe",
                media_type="application/vnd.microsoft.portable-executable"
            )
    raise HTTPException(
        status_code=404,
        detail=f"Chưa tìm thấy file in4.exe trong thư mục máy chủ ({BASE_DIR}). Vui lòng đặt file in4.exe cùng thư mục với PCin4Server.exe để cho phép tải trực tiếp qua trình duyệt web!"
    )


@app.get("/api/health", tags=["System"])
def health_check():
    return {"status": "ok", "service": "PCin4Server"}


@app.get("/", response_class=HTMLResponse, tags=["Dashboard"])
def web_dashboard():
    html_content = """
    <!DOCTYPE html>
    <html lang="vi">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Hệ Thống Thống Kê & Giám Sát PC Bệnh Viện (SQLite Server)</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css">
        <style>
            :root {
                --primary: #0f172a;
                --accent: #10b981;
                --warning: #f59e0b;
                --danger: #ef4444;
            }
            body { background-color: #f1f5f9; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; color: #1e293b; }
            .navbar { background: linear-gradient(135deg, #0f172a, #1e3a8a, #0369a1); box-shadow: 0 4px 15px rgba(0,0,0,0.15); }
            .card-stat { border: none; border-radius: 12px; transition: transform 0.2s, box-shadow 0.2s; box-shadow: 0 4px 12px rgba(0,0,0,0.05); }
            .card-stat:hover { transform: translateY(-3px); box-shadow: 0 8px 20px rgba(0,0,0,0.08); }
            .panel-box { background: white; border-radius: 12px; padding: 22px; box-shadow: 0 4px 12px rgba(0,0,0,0.05); margin-bottom: 24px; }
            .badge-ssd { background-color: #10b981; color: white; padding: 3px 7px; border-radius: 4px; font-weight: 600; font-size: 0.75rem; }
            .badge-hdd { background-color: #f97316; color: white; padding: 3px 7px; border-radius: 4px; font-weight: 600; font-size: 0.75rem; }
            .badge-barcode { background-color: #1e293b; color: #facc15; font-family: monospace; font-size: 0.85rem; padding: 3px 7px; border-radius: 4px; border: 1px solid #334155; }
            .table th { background-color: #f8fafc; color: #475569; font-size: 0.82rem; text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 2px solid #e2e8f0; }
            .device-row:hover { background-color: #f8fafc; }
            .nav-pills .nav-link { color: #475569; font-weight: 600; border-radius: 8px; padding: 10px 18px; transition: all 0.2s; }
            .nav-pills .nav-link.active { background: #1e3a8a; color: white; box-shadow: 0 4px 12px rgba(30,58,138,0.25); }
            .progress { height: 10px; border-radius: 6px; background-color: #e2e8f0; }
            .dept-stat-row { padding: 10px 0; border-bottom: 1px solid #f1f5f9; }
            .dept-stat-row:last-child { border-bottom: none; }
            .status-dot-on { width: 10px; height: 10px; background-color: #10b981; border-radius: 50%; display: inline-block; box-shadow: 0 0 8px #10b981; }
            .status-dot-off { width: 10px; height: 10px; background-color: #94a3b8; border-radius: 50%; display: inline-block; }
            .pulse-alert { animation: pulse 1.5s infinite; }
            @keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.4; } 100% { opacity: 1; } }
        </style>
    </head>
    <body>
        <!-- THANH HEADER ĐIỀU HƯỚNG -->
        <nav class="navbar navbar-dark py-3">
            <div class="container-fluid px-4">
                <span class="navbar-brand mb-0 h1 fs-4 fw-bold d-flex align-items-center">
                    <i class="bi bi-hospital me-2 text-info fs-3"></i>
                    <div>
                        <div>BỆNH VIỆN - TRUNG TÂM QUẢN LÝ, GIÁM SÁT & THỐNG KÊ MÁY TÍNH</div>
                        <div class="text-light text-opacity-75" style="font-size: 0.8rem; font-weight: normal;">
                            Hệ thống CSDL SQLite Server &middot; Giám sát Bật/Tắt &middot; Cảnh báo tráo linh kiện &middot; Điều khiển từ xa qua Port 8005
                        </div>
                    </div>
                </span>
                <div class="d-flex align-items-center gap-2">
                    <span class="badge bg-success bg-opacity-25 text-light border border-success border-opacity-50 px-3 py-2 me-2">
                        <i class="bi bi-database-check me-1 text-success"></i> SQLite Active
                    </span>
                    <a href="/in4.exe" class="btn btn-warning fw-bold text-dark shadow-sm">
                        <i class="bi bi-download me-1"></i> Tải Tool in4.exe
                    </a>
                    <a href="/api/export-excel" class="btn btn-light fw-bold text-primary shadow-sm">
                        <i class="bi bi-file-earmark-excel me-1 text-success"></i> Xuất File Excel
                    </a>
                    <button class="btn btn-outline-light shadow-sm" onclick="loadAll()" title="Làm mới toàn bộ dữ liệu">
                        <i class="bi bi-arrow-clockwise"></i>
                    </button>
                </div>
            </div>
        </nav>

        <div class="container-fluid px-4 py-4">
            <!-- 5 THẺ CHỈ SỐ KPI TOÀN VIỆN -->
            <div class="row g-3 mb-4">
                <div class="col-md-2" style="width: 20%;">
                    <div class="card card-stat bg-white p-3">
                        <div class="d-flex align-items-center">
                            <div class="p-3 bg-primary bg-opacity-10 text-primary rounded-circle me-3">
                                <i class="bi bi-pc-display fs-2"></i>
                            </div>
                            <div>
                                <div class="text-muted small fw-bold">TỔNG MÁY TÍNH</div>
                                <div class="fs-3 fw-bold text-dark" id="stat-total">0</div>
                                <div id="stat-version-sub" class="mt-1"></div>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="col-md-2" style="width: 20%;">
                    <div class="card card-stat bg-white p-3">
                        <div class="d-flex align-items-center">
                            <div class="p-3 bg-success bg-opacity-10 text-success rounded-circle me-3">
                                <i class="bi bi-broadcast fs-2"></i>
                            </div>
                            <div>
                                <div class="text-muted small fw-bold">ĐANG BẬT (ONLINE)</div>
                                <div class="fs-3 fw-bold text-success" id="stat-online">0</div>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="col-md-2" style="width: 20%;">
                    <div class="card card-stat bg-white p-3">
                        <div class="d-flex align-items-center">
                            <div class="p-3 bg-danger bg-opacity-10 text-danger rounded-circle me-3">
                                <i class="bi bi-moon-stars fs-2"></i>
                            </div>
                            <div>
                                <div class="text-muted small fw-bold">CHƯA TẮT NGOÀI GIỜ</div>
                                <div class="fs-3 fw-bold text-danger" id="stat-overnight">0</div>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="col-md-2" style="width: 20%;">
                    <div class="card card-stat bg-white p-3">
                        <div class="d-flex align-items-center">
                            <div class="p-3 bg-warning bg-opacity-10 text-warning rounded-circle me-3">
                                <i class="bi bi-shield-exclamation fs-2"></i>
                            </div>
                            <div>
                                <div class="text-muted small fw-bold">CẢNH BÁO PHẦN CỨNG</div>
                                <div class="fs-3 fw-bold text-warning" id="stat-hw-alerts">0</div>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="col-md-2" style="width: 20%;">
                    <div class="card card-stat bg-white p-3">
                        <div class="d-flex align-items-center">
                            <div class="p-3 bg-info bg-opacity-10 text-info rounded-circle me-3">
                                <i class="bi bi-buildings fs-2"></i>
                            </div>
                            <div>
                                <div class="text-muted small fw-bold">KHOA / PHÒNG</div>
                                <div class="fs-3 fw-bold text-info" id="stat-dept">0</div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- TAB ĐIỀU HƯỚNG 4 MỤC -->
            <ul class="nav nav-pills mb-3" id="mainTabs" role="tablist">
                <li class="nav-item" role="presentation">
                    <button class="nav-link active" id="tab-stat-btn" data-bs-toggle="pill" data-bs-target="#tab-stat" type="button" role="tab">
                        <i class="bi bi-bar-chart-fill me-1"></i> 1. BẢNG THỐNG KÊ TOÀN VIỆN
                    </button>
                </li>
                <li class="nav-item" role="presentation">
                    <button class="nav-link position-relative" id="tab-power-btn" data-bs-toggle="pill" data-bs-target="#tab-power" type="button" role="tab">
                        <i class="bi bi-moon-stars-fill me-1 text-warning"></i> 2. GIÁM SÁT BẬT / TẮT & USER CHƯA TẮT MÁY
                        <span class="badge rounded-pill bg-danger ms-1" id="badge-overnight" style="display:none;">0</span>
                    </button>
                </li>
                <li class="nav-item" role="presentation">
                    <button class="nav-link position-relative" id="tab-alert-btn" data-bs-toggle="pill" data-bs-target="#tab-alert" type="button" role="tab">
                        <i class="bi bi-shield-exclamation me-1 text-danger"></i> 3. CẢNH BÁO THAY ĐỔI PHẦN CỨNG
                        <span class="badge rounded-pill bg-danger ms-1" id="badge-hw-alert" style="display:none;">0</span>
                    </button>
                </li>
                <li class="nav-item" role="presentation">
                    <button class="nav-link" id="tab-list-btn" data-bs-toggle="pill" data-bs-target="#tab-list" type="button" role="tab">
                        <i class="bi bi-list-columns-reverse me-1"></i> 4. DANH SÁCH CHI TIẾT MÁY TÍNH & ĐIỀU KHIỂN
                    </button>
                </li>
            </ul>

            <div class="tab-content" id="mainTabsContent">
                <!-- TAB 1: THỐNG KÊ TOÀN VIỆN -->
                <div class="tab-pane fade show active" id="tab-stat" role="tabpanel">
                    <div class="row g-4">
                        <div class="col-lg-7">
                            <div class="panel-box">
                                <div class="d-flex justify-content-between align-items-center mb-3">
                                    <h5 class="fw-bold text-dark mb-0"><i class="bi bi-hospital me-2 text-primary"></i>Phân Bổ Máy Tính Theo Từng Khoa / Phòng</h5>
                                    <span class="badge bg-primary px-3 py-2" id="dept-badge-count">0 Khoa phòng</span>
                                </div>
                                <div id="dept-stats-container">
                                    <div class="text-center py-4 text-muted">Đang tính toán số liệu...</div>
                                </div>
                            </div>
                        </div>

                        <div class="col-lg-5">
                            <div class="panel-box mb-4">
                                <h5 class="fw-bold text-dark mb-3"><i class="bi bi-hdd-network me-2 text-success"></i>Cơ Cấu Ổ Cứng (Lưu Trữ)</h5>
                                <div id="storage-stats-container">
                                    <div class="text-muted small">Đang tải...</div>
                                </div>
                            </div>

                            <div class="panel-box mb-4">
                                <h5 class="fw-bold text-dark mb-3"><i class="bi bi-memory me-2 text-warning"></i>Phân Khúc Bộ Nhớ RAM</h5>
                                <div id="ram-stats-container">
                                    <div class="text-muted small">Đang tải...</div>
                                </div>
                            </div>

                            <div class="panel-box">
                                <h5 class="fw-bold text-dark mb-3"><i class="bi bi-windows me-2 text-info"></i>Hệ Điều Hành Sử Dụng</h5>
                                <div id="os-stats-container">
                                    <div class="text-muted small">Đang tải...</div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- TAB 2: GIÁM SÁT BẬT / TẮT & QUẢN LÝ USER KHÔNG TẮT MÁY -->
                <div class="tab-pane fade" id="tab-power" role="tabpanel">
                    <div class="panel-box border-start border-danger border-4">
                        <div class="d-flex justify-content-between align-items-center mb-3">
                            <div>
                                <h5 class="fw-bold text-danger mb-1">
                                    <i class="bi bi-exclamation-octagon-fill me-2"></i>DANH SÁCH MÁY TÍNH & USER KHÔNG TẮT MÁY KHI KHÔNG LÀM VIỆC
                                </h5>
                                <div class="text-muted small">
                                    Phát hiện các máy tính đang bật ngoài giờ hành chính (sau 18h00 hoặc thứ 7, CN) hoặc bật liên tục trên 10 tiếng chưa tắt.
                                </div>
                            </div>
                            <button class="btn btn-sm btn-outline-danger" onclick="loadOvernightPcs()">
                                <i class="bi bi-arrow-clockwise me-1"></i>Quét lại
                            </button>
                        </div>

                        <div class="table-responsive">
                            <table class="table table-hover align-middle mb-0">
                                <thead>
                                    <tr>
                                        <th>Khoa / Phòng</th>
                                        <th>Bác sĩ / Nhân viên khai báo</th>
                                        <th>Tài khoản Windows đăng nhập</th>
                                        <th>Tên Máy & IP</th>
                                        <th>Thời điểm bật (Boot)</th>
                                        <th>Đã chạy liên tục</th>
                                        <th>Mức độ cảnh báo</th>
                                        <th class="text-center">Thao tác</th>
                                    </tr>
                                </thead>
                                <tbody id="overnight-body">
                                    <tr><td colspan="8" class="text-center py-4 text-muted">Đang quét danh sách máy tính...</td></tr>
                                </tbody>
                            </table>
                        </div>
                    </div>

                    <!-- BẢNG NHẬT KÝ BẬT / TẮT MÁY (POWER LOGS) -->
                    <div class="panel-box">
                        <h5 class="fw-bold text-dark mb-3"><i class="bi bi-journal-text me-2 text-primary"></i>Nhật Ký Sự Kiện Bật / Tắt Máy Toàn Viện (Gần Nhất)</h5>
                        <div class="table-responsive">
                            <table class="table table-hover align-middle mb-0">
                                <thead>
                                    <tr>
                                        <th>Thời gian</th>
                                        <th>Sự kiện</th>
                                        <th>Khoa / Phòng</th>
                                        <th>Tên Máy & MAC</th>
                                        <th>User Windows</th>
                                        <th>Thời gian hoạt động</th>
                                        <th>Ghi chú</th>
                                    </tr>
                                </thead>
                                <tbody id="power-logs-body">
                                    <tr><td colspan="7" class="text-center py-4 text-muted">Đang tải nhật ký nguồn...</td></tr>
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>

                <!-- TAB 3: CẢNH BÁO THAY ĐỔI CẤU HÌNH PHẦN CỨNG -->
                <div class="tab-pane fade" id="tab-alert" role="tabpanel">
                    <div class="panel-box border-start border-warning border-4">
                        <div class="d-flex justify-content-between align-items-center mb-3">
                            <div>
                                <h5 class="fw-bold text-dark mb-1">
                                    <i class="bi bi-shield-exclamation text-danger me-2"></i>LỊCH SỬ THAY ĐỔI & CẢNH BÁO TRÁO ĐỔI PHẦN CỨNG
                                </h5>
                                <div class="text-muted small">
                                    Hệ thống tự động so sánh cấu hình phần cứng sau mỗi lần bật máy tính. Cảnh báo ngay khi phát hiện RAM bị tháo, ổ cứng bị đổi serial, CPU hoặc màn hình bị tráo.
                                </div>
                            </div>
                            <button class="btn btn-sm btn-outline-secondary" onclick="loadHardwareAlerts()">
                                <i class="bi bi-arrow-clockwise me-1"></i>Làm mới
                            </button>
                        </div>

                        <div class="table-responsive">
                            <table class="table table-hover align-middle mb-0">
                                <thead>
                                    <tr>
                                        <th>Thời gian phát hiện</th>
                                        <th>Máy Tính (Hostname / MAC)</th>
                                        <th>Khoa / Phòng</th>
                                        <th>Người sử dụng</th>
                                        <th>Linh kiện thay đổi</th>
                                        <th>Thông số cũ (Ban đầu)</th>
                                        <th>Thông số mới (Hiện tại)</th>
                                        <th class="text-center">Xử lý</th>
                                    </tr>
                                </thead>
                                <tbody id="hw-alerts-body">
                                    <tr><td colspan="8" class="text-center py-4 text-muted">Đang kiểm tra cảnh báo phần cứng...</td></tr>
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>

                <!-- TAB 4: DANH SÁCH CHI TIẾT MÁY TÍNH & ĐIỀU KHIỂN TỪ XA -->
                <div class="tab-pane fade" id="tab-list" role="tabpanel">
                    <div class="panel-box">
                        <div class="row g-2 mb-3 align-items-center">
                            <div class="col-md-3">
                                <div class="input-group input-group-sm">
                                    <span class="input-group-text bg-light border-end-0"><i class="bi bi-search text-muted"></i></span>
                                    <input type="text" id="search-input" class="form-control bg-light border-start-0" 
                                        placeholder="🔍 Mã vạch, Tên máy, IP, MAC, User...">
                                </div>
                            </div>
                            <div class="col-md-2">
                                <select id="dept-filter" class="form-select form-select-sm bg-light">
                                    <option value="Tất cả">-- Tất cả Khoa / Phòng --</option>
                                </select>
                            </div>
                            <div class="col-md-2">
                                <select id="health-filter" class="form-select form-select-sm bg-light">
                                    <option value="ALL">-- Tất cả trạng thái --</option>
                                    <option value="ONLINE">🟢 Client đang chạy</option>
                                    <option value="NO_AGENT_SUSPECT_AV">⚠️ Bật máy, mất IN4</option>
                                    <option value="OFFLINE">⚫ Offline (Tắt máy)</option>
                                </select>
                            </div>
                            <div class="col-md-2">
                                <select id="version-filter" class="form-select form-select-sm bg-light">
                                    <option value="ALL">-- Tất cả phiên bản --</option>
                                    <option value="OUTDATED">⚠ Bản cũ (cần update)</option>
                                </select>
                            </div>
                            <div class="col-md-3 text-end">
                                <button class="btn btn-sm btn-warning fw-bold text-dark me-1" onclick="updateFilteredDevices()" id="btn-update-filtered" title="Cập nhật đúng các máy đang lọc trên bảng (theo khoa / phiên bản)">
                                    <i class="bi bi-arrow-repeat me-1"></i>Update nhóm
                                </button>
                                <button class="btn btn-sm btn-outline-success fw-bold me-1" onclick="updateAllClients()" id="btn-update-all" title="Phát hành bản in4.exe mới cho toàn viện">
                                    <i class="bi bi-cloud-arrow-up me-1"></i>Update All
                                </button>
                                <button class="btn btn-sm btn-outline-primary fw-bold me-1" onclick="pingAllDevices()" id="btn-ping-all" title="Gửi gói kiểm tra và làm mới trạng thái toàn viện">
                                    <i class="bi bi-broadcast-pin"></i>
                                </button>
                                <span class="badge bg-secondary px-2 py-2" id="filtered-count">0 máy</span>
                            </div>
                        </div>

                        <div class="table-responsive">
                            <table class="table table-hover align-middle mb-0">
                                <thead>
                                    <tr>
                                        <th>Trạng thái</th>
                                        <th>Mã Vạch / Khoa Phòng</th>
                                        <th>Người sử dụng (User)</th>
                                        <th>Tên Máy & Mạng</th>
                                        <th>Bo Mạch & CPU</th>
                                        <th>RAM</th>
                                        <th>Ổ cứng & Phím chuột</th>
                                        <th>Màn hình</th>
                                        <th>Cập nhật</th>
                                        <th class="text-center">Điều khiển từ xa</th>
                                    </tr>
                                </thead>
                                <tbody id="devices-body">
                                    <tr><td colspan="10" class="text-center py-4 text-muted">Đang tải danh sách thiết bị...</td></tr>
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- MODAL GỬI THÔNG BÁO TỚI MÁY TRẠM (PORT 8005) -->
        <div class="modal fade" id="notifyModal" tabindex="-1">
            <div class="modal-dialog">
                <div class="modal-content">
                    <div class="modal-header bg-primary text-white">
                        <h5 class="modal-title"><i class="bi bi-bell-fill me-2"></i>Gửi Thông Báo Màn Hình Máy Trạm</h5>
                        <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <input type="hidden" id="modal-notify-ip">
                        <input type="hidden" id="modal-notify-mac">
                        <input type="hidden" id="modal-notify-port" value="8005">
                        <div class="mb-3">
                            <label class="form-label fw-bold">Máy đích tiếp nhận:</label>
                            <input type="text" id="modal-notify-target" class="form-control bg-light" readonly>
                        </div>
                        <div class="mb-3">
                            <label class="form-label fw-bold">Tiêu đề thông báo:</label>
                            <input type="text" id="modal-notify-title" class="form-control" value="THÔNG BÁO TỪ PHÒNG CNTT BỆNH VIỆN">
                        </div>
                        <div class="mb-3">
                            <label class="form-label fw-bold">Nội dung thông báo hiển thị cho người dùng:</label>
                            <textarea id="modal-notify-msg" class="form-control" rows="4" placeholder="Nhập lời nhắc... (VD: Đã hết giờ làm việc, vui lòng lưu hồ sơ bệnh án và tắt máy tính trước khi rời phòng!)"></textarea>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Đóng</button>
                        <button type="button" class="btn btn-primary fw-bold" onclick="executeRemoteNotify()">
                            <i class="bi bi-send-fill me-1"></i> Gửi Ngay
                        </button>
                    </div>
                </div>
            </div>
        </div>

        <!-- MODAL CẬP NHẬT CLIENT TỪ XA (PORT 8005) -->
        <div class="modal fade" id="updateModal" tabindex="-1">
            <div class="modal-dialog">
                <div class="modal-content">
                    <div class="modal-header bg-warning text-dark">
                        <h5 class="modal-title"><i class="bi bi-arrow-repeat me-2"></i>Cập Nhật Tool in4.exe Từ Xa</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <input type="hidden" id="modal-update-ip">
                        <input type="hidden" id="modal-update-mac">
                        <input type="hidden" id="modal-update-port" value="8005">
                        <div class="mb-3">
                            <label class="form-label fw-bold">Máy đích cập nhật:</label>
                            <input type="text" id="modal-update-target" class="form-control bg-light" readonly>
                        </div>
                        <div class="mb-3">
                            <label class="form-label fw-bold">Đường link tải file in4.exe:</label>
                            <input type="text" id="modal-update-url" class="form-control" value="http://10.10.12.188:8000/in4.exe">
                            <small class="text-muted">Máy trạm sẽ tự động tải file từ link này, ghi đè bản cũ và khởi động lại ngầm.</small>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Hủy</button>
                        <button type="button" class="btn btn-warning fw-bold text-dark" onclick="executeRemoteUpdate()">
                            <i class="bi bi-cloud-arrow-down-fill me-1"></i> Bắt Đầu Cập Nhật
                        </button>
                    </div>
                </div>
            </div>
        </div>

        <!-- MODAL KIỂM TRA KẾT NỐI (PING CHECK) -->
        <div class="modal fade" id="pingModal" tabindex="-1">
            <div class="modal-dialog modal-dialog-centered">
                <div class="modal-content">
                    <div class="modal-header bg-dark text-white">
                        <h5 class="modal-title"><i class="bi bi-activity me-2 text-warning"></i>Kiểm Tra Trạng Thái Kết Nối (Ping Live)</h5>
                        <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body" id="ping-modal-body">
                        <div class="text-center py-4">
                            <div class="spinner-border text-primary mb-3" role="status"></div>
                            <div class="fw-bold">Đang gửi gói tin Ping & kiểm tra Heartbeat...</div>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Đóng</button>
                        <button type="button" class="btn btn-primary" onclick="recheckCurrentPing()">
                            <i class="bi bi-arrow-clockwise me-1"></i> Kiểm tra lại
                        </button>
                    </div>
                </div>
            </div>
        </div>

        <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
        <script>
            let notifyModalObj = null;
            let updateModalObj = null;
            let pingModalObj = null;
            let currentPingTarget = null;
            let latestClientVersion = '1.3.1';
            let currentFilteredDevices = [];

            document.addEventListener('DOMContentLoaded', () => {
                notifyModalObj = new bootstrap.Modal(document.getElementById('notifyModal'));
                updateModalObj = new bootstrap.Modal(document.getElementById('updateModal'));
                pingModalObj = new bootstrap.Modal(document.getElementById('pingModal'));
            });

            async function loadStats() {
                try {
                    const res = await fetch('/api/statistics');
                    const data = await res.json();

                    if (data.latest_client_version) {
                        latestClientVersion = data.latest_client_version;
                    }
                    document.getElementById('stat-total').innerText = data.total_pcs;
                    const verSub = document.getElementById('stat-version-sub');
                    if (verSub && data.latest_version_pcs !== undefined) {
                        const outdated = data.outdated_pcs || 0;
                        verSub.innerHTML = outdated > 0
                            ? `<span class="badge bg-info text-dark" style="cursor:pointer;font-size:0.72rem;" onclick="filterOutdatedVersion()" title="Bấm để lọc các máy chưa lên v${escapeHtml(latestClientVersion)}">v${escapeHtml(latestClientVersion)}: ${data.latest_version_pcs}/${data.total_pcs} (${outdated} cũ)</span>`
                            : `<span class="badge bg-success" style="font-size:0.72rem;">✓ 100% lên v${escapeHtml(latestClientVersion)}</span>`;
                    }
                    document.getElementById('stat-dept').innerText = data.departments_count;
                    document.getElementById('dept-badge-count').innerText = `${data.departments_count} Khoa phòng`;
                    if (data.online_pcs !== undefined) {
                        const suspect = data.suspect_av_pcs || 0;
                        document.getElementById('stat-online').innerHTML = suspect > 0
                            ? `${data.online_pcs} / ${data.total_pcs} <div class="mt-1"><span class="badge bg-warning text-dark" style="cursor:pointer;font-size:0.75rem;" onclick="filterSuspectAV()" title="Bấm để xem các máy đang bật (Ping thông) nhưng không thấy phần mềm IN4">${suspect} máy bật / mất IN4</span></div>`
                            : `${data.online_pcs} / ${data.total_pcs}`;
                    }

                    renderDeptStats(data.dept_summary, data.total_pcs);
                    renderStorageStats(data.storage_summary, data.total_pcs);
                    renderRamStats(data.ram_summary, data.total_pcs);
                    renderOsStats(data.os_summary, data.total_pcs);
                } catch(e) { console.error("Lỗi loadStats:", e); }
            }

            async function loadOvernightPcs() {
                try {
                    const res = await fetch('/api/overnight-pcs');
                    const list = await res.json();
                    
                    document.getElementById('stat-overnight').innerText = list.length;
                    const badge = document.getElementById('badge-overnight');
                    if (list.length > 0) {
                        badge.innerText = list.length;
                        badge.style.display = 'inline-block';
                    } else {
                        badge.style.display = 'none';
                    }

                    const tbody = document.getElementById('overnight-body');
                    if (list.length === 0) {
                        tbody.innerHTML = '<tr><td colspan="8" class="text-center py-4 text-success"><i class="bi bi-check-circle-fill me-2 fs-5"></i>Tuyệt vời! Hiện tại không có máy tính nào quên tắt ngoài giờ làm việc.</td></tr>';
                        return;
                    }

                    tbody.innerHTML = list.map(pc => {
                        const levelBadge = pc.alert_level === 'CRITICAL' ? 
                            '<span class="badge bg-danger pulse-alert">NGUY CƠ CAO (QUẢ QUA ĐÊM)</span>' : 
                            '<span class="badge bg-warning text-dark">CHƯA TẮT NGOÀI GIỜ</span>';
                        
                        return `
                        <tr>
                            <td><span class="badge bg-light text-primary border">${escapeHtml(pc.department || 'Chưa phân khoa')}</span></td>
                            <td><div class="fw-bold text-dark">${escapeHtml(pc.user_name || 'N/A')}</div><small class="text-muted">${escapeHtml(pc.user_phone || '')}</small></td>
                            <td><span class="badge bg-secondary">${escapeHtml(pc.logged_in_user || 'Unknown')}</span></td>
                            <td><div class="fw-bold text-primary">${escapeHtml(pc.hostname)}</div><small class="text-muted">${escapeHtml(pc.ip_address)}</small></td>
                            <td><small>${escapeHtml(pc.boot_time || 'N/A')}</small></td>
                            <td><span class="badge bg-danger fs-6">${pc.uptime_hours} giờ</span></td>
                            <td>${levelBadge}<div class="small text-muted">${escapeHtml(pc.reason || '')}</div></td>
                            <td class="text-center">
                                <button class="btn btn-sm btn-outline-info me-1" onclick="pingDevice('${pc.ip_address}', '${pc.mac_address}', '${escapeHtml(pc.hostname)}', ${pc.client_agent_port || 8005})" title="Ping kiểm tra máy này">
                                    <i class="bi bi-activity"></i> Ping
                                </button>
                                <button class="btn btn-sm btn-outline-danger fw-bold shadow-sm" onclick="openNotifyModal('${pc.ip_address}', ${pc.client_agent_port || 8005}, '${escapeHtml(pc.hostname)} - ${escapeHtml(pc.user_name)}', '${pc.mac_address}')">
                                    <i class="bi bi-bell-fill me-1"></i>Nhắc Tắt Máy
                                </button>
                            </td>
                        </tr>
                        `;
                    }).join('');
                } catch(e) { console.error("Lỗi loadOvernightPcs:", e); }
            }

            async function loadHardwareAlerts() {
                try {
                    const res = await fetch('/api/hardware-alerts');
                    const alerts = await res.json();
                    
                    const unack = alerts.filter(a => !a.is_acknowledged);
                    document.getElementById('stat-hw-alerts').innerText = unack.length;
                    const badge = document.getElementById('badge-hw-alert');
                    if (unack.length > 0) {
                        badge.innerText = unack.length;
                        badge.style.display = 'inline-block';
                    } else {
                        badge.style.display = 'none';
                    }

                    const tbody = document.getElementById('hw-alerts-body');
                    if (alerts.length === 0) {
                        tbody.innerHTML = '<tr><td colspan="8" class="text-center py-4 text-success"><i class="bi bi-shield-check fs-4 d-block mb-1"></i>Không phát hiện bất kỳ dấu hiệu tráo đổi hay thay đổi phần cứng nào.</td></tr>';
                        return;
                    }

                    tbody.innerHTML = alerts.map(a => {
                        const statusBadge = a.is_acknowledged ? 
                            '<span class="badge bg-secondary">Đã xử lý</span>' : 
                            '<span class="badge bg-danger pulse-alert">CẢNH BÁO MỚI</span>';
                        
                        const actionBtn = a.is_acknowledged ? 
                            '<span class="text-muted small">✓ Đã xác nhận</span>' : 
                            `<button class="btn btn-sm btn-outline-success fw-bold" onclick="ackHardwareAlert(${a.id})"><i class="bi bi-check-lg me-1"></i>Xác nhận</button>`;

                        return `
                        <tr class="${a.is_acknowledged ? '' : 'table-warning'}">
                            <td><small>${escapeHtml(a.detected_at)}</small><br>${statusBadge}</td>
                            <td><div class="fw-bold text-primary">${escapeHtml(a.hostname)}</div><small class="text-muted">${escapeHtml(a.mac_address)}</small></td>
                            <td><span class="badge bg-light text-dark border">${escapeHtml(a.department || 'N/A')}</span></td>
                            <td><div class="fw-bold">${escapeHtml(a.user_name || 'N/A')}</div></td>
                            <td><span class="badge bg-dark text-warning fs-6">${escapeHtml(a.component)}</span></td>
                            <td><div class="small text-danger text-break" style="max-width:200px;">${escapeHtml(a.old_value)}</div></td>
                            <td><div class="small text-success text-break" style="max-width:200px;">${escapeHtml(a.new_value)}</div></td>
                            <td class="text-center">${actionBtn}</td>
                        </tr>
                        `;
                    }).join('');
                } catch(e) { console.error("Lỗi loadHardwareAlerts:", e); }
            }

            async function ackHardwareAlert(id) {
                try {
                    await fetch('/api/hardware-alerts/ack/' + id, { method: 'POST' });
                    loadHardwareAlerts();
                } catch(e) { alert('Lỗi xác nhận cảnh báo: ' + e); }
            }

            async function loadPowerLogs() {
                try {
                    const res = await fetch('/api/power-logs');
                    const logs = await res.json();
                    const tbody = document.getElementById('power-logs-body');
                    if (logs.length === 0) {
                        tbody.innerHTML = '<tr><td colspan="7" class="text-center py-4 text-muted">Chưa có nhật ký bật tắt.</td></tr>';
                        return;
                    }
                    tbody.innerHTML = logs.map(l => {
                        const evBadge = l.event_type === 'STARTUP' ? 
                            '<span class="badge bg-success"><i class="bi bi-power me-1"></i>BẬT MÁY</span>' : 
                            '<span class="badge bg-secondary"><i class="bi bi-moon me-1"></i>TẮT MÁY</span>';
                        return `
                        <tr>
                            <td><small class="text-muted">${escapeHtml(l.event_time)}</small></td>
                            <td>${evBadge}</td>
                            <td>${escapeHtml(l.department || 'N/A')}</td>
                            <td><div class="fw-bold text-dark">${escapeHtml(l.hostname)}</div><small class="text-muted">${escapeHtml(l.mac_address)}</small></td>
                            <td><span class="badge bg-light text-dark border">${escapeHtml(l.logged_in_user || 'Unknown')}</span></td>
                            <td>${l.uptime_hours > 0 ? `<span class="badge bg-info text-dark">${l.uptime_hours}h</span>` : ''}</td>
                            <td><small class="text-muted">${escapeHtml(l.notes || '')}</small></td>
                        </tr>
                        `;
                    }).join('');
                } catch(e) { console.error("Lỗi loadPowerLogs:", e); }
            }

            function renderDeptStats(depts, total) {
                const el = document.getElementById('dept-stats-container');
                if (!depts || depts.length === 0) {
                    el.innerHTML = '<div class="text-center py-4 text-muted"><i class="bi bi-inbox fs-2 d-block mb-2"></i>Chưa có máy tính nào được kiểm kê.</div>';
                    return;
                }

                el.innerHTML = depts.map((d, i) => {
                    const pct = total > 0 ? Math.round((d.total_pcs / total) * 100) : 0;
                    return `
                    <div class="dept-stat-row">
                        <div class="d-flex justify-content-between align-items-center mb-1">
                            <div>
                                <span class="badge bg-light text-dark border me-1">${i + 1}</span>
                                <span class="fw-bold text-dark cursor-pointer" onclick="filterByDept('${escapeHtml(d.dept)}')">${escapeHtml(d.dept)}</span>
                            </div>
                            <div class="d-flex align-items-center gap-2">
                                <span class="badge bg-success bg-opacity-10 text-success border border-success border-opacity-25" title="Máy dùng SSD">${d.ssd_pcs} SSD</span>
                                ${d.hdd_pcs > 0 ? `<span class="badge bg-danger bg-opacity-10 text-danger border border-danger border-opacity-25" title="Máy còn dùng HDD">${d.hdd_pcs} HDD</span>` : ''}
                                ${d.low_ram_pcs > 0 ? `<span class="badge bg-warning bg-opacity-10 text-dark border border-warning border-opacity-25" title="RAM yếu <= 4GB">${d.low_ram_pcs} RAM &le;4G</span>` : ''}
                                <span class="badge bg-primary px-2 py-1 fw-bold">${d.total_pcs} máy (${pct}%)</span>
                            </div>
                        </div>
                        <div class="progress">
                            <div class="progress-bar bg-primary" role="progressbar" style="width: ${pct}%"></div>
                        </div>
                    </div>
                    `;
                }).join('');
            }

            function renderStorageStats(s, total) {
                const el = document.getElementById('storage-stats-container');
                if (!s || total === 0) {
                    el.innerHTML = '<div class="text-muted small">Chưa có dữ liệu</div>';
                    return;
                }
                const nvmePct = Math.round((s.nvme / total) * 100);
                const sataPct = Math.round((s.ssd_sata / total) * 100);
                const hddPct = Math.round((s.hdd_only / total) * 100);

                el.innerHTML = `
                <div class="mb-3">
                    <div class="d-flex justify-content-between small mb-1">
                        <span class="text-success fw-bold"><i class="bi bi-lightning-charge me-1"></i>SSD NVMe (Tốc độ cao)</span>
                        <span class="fw-bold">${s.nvme} máy (${nvmePct}%)</span>
                    </div>
                    <div class="progress"><div class="progress-bar bg-success" style="width: ${nvmePct}%"></div></div>
                </div>
                <div class="mb-3">
                    <div class="d-flex justify-content-between small mb-1">
                        <span class="text-info fw-bold"><i class="bi bi-hdd-fill me-1"></i>SSD SATA (Chuẩn hóa)</span>
                        <span class="fw-bold">${s.ssd_sata} máy (${sataPct}%)</span>
                    </div>
                    <div class="progress"><div class="progress-bar bg-info" style="width: ${sataPct}%"></div></div>
                </div>
                <div>
                    <div class="d-flex justify-content-between small mb-1">
                        <span class="text-danger fw-bold"><i class="bi bi-exclamation-triangle me-1"></i>HDD Cơ (Chậm, khuyến nghị thay)</span>
                        <span class="fw-bold text-danger">${s.hdd_only} máy (${hddPct}%)</span>
                    </div>
                    <div class="progress"><div class="progress-bar bg-danger" style="width: ${hddPct}%"></div></div>
                </div>
                `;
            }

            function renderRamStats(r, total) {
                const el = document.getElementById('ram-stats-container');
                if (!r || total === 0) {
                    el.innerHTML = '<div class="text-muted small">Chưa có dữ liệu</div>';
                    return;
                }
                const p4 = Math.round((r.ram_4gb / total) * 100);
                const p8 = Math.round((r.ram_8gb / total) * 100);
                const p16 = Math.round((r.ram_16gb / total) * 100);
                const p32 = Math.round((r.ram_32gb / total) * 100);

                el.innerHTML = `
                <div class="mb-2">
                    <div class="d-flex justify-content-between small mb-1">
                        <span class="text-danger fw-bold">&le; 4 GB (Yếu, cần bổ sung)</span>
                        <span class="fw-bold text-danger">${r.ram_4gb} máy (${p4}%)</span>
                    </div>
                    <div class="progress"><div class="progress-bar bg-danger" style="width: ${p4}%"></div></div>
                </div>
                <div class="mb-2">
                    <div class="d-flex justify-content-between small mb-1">
                        <span class="text-primary fw-bold">8 GB (Chuẩn văn phòng BV)</span>
                        <span class="fw-bold">${r.ram_8gb} máy (${p8}%)</span>
                    </div>
                    <div class="progress"><div class="progress-bar bg-primary" style="width: ${p8}%"></div></div>
                </div>
                <div class="mb-2">
                    <div class="d-flex justify-content-between small mb-1">
                        <span class="text-success fw-bold">16 GB (Cấu hình mạnh)</span>
                        <span class="fw-bold">${r.ram_16gb} máy (${p16}%)</span>
                    </div>
                    <div class="progress"><div class="progress-bar bg-success" style="width: ${p16}%"></div></div>
                </div>
                <div>
                    <div class="d-flex justify-content-between small mb-1">
                        <span class="text-info fw-bold">&ge; 32 GB (Máy trạm / Server)</span>
                        <span class="fw-bold">${r.ram_32gb} máy (${p32}%)</span>
                    </div>
                    <div class="progress"><div class="progress-bar bg-info" style="width: ${p32}%"></div></div>
                </div>
                `;
            }

            function renderOsStats(list, total) {
                const el = document.getElementById('os-stats-container');
                if (!list || list.length === 0 || total === 0) {
                    el.innerHTML = '<div class="text-muted small">Chưa có dữ liệu</div>';
                    return;
                }
                el.innerHTML = list.map(item => {
                    const pct = Math.round((item.count / total) * 100);
                    return `
                    <div class="mb-2">
                        <div class="d-flex justify-content-between small mb-1">
                            <span class="fw-bold text-dark">${escapeHtml(item.os_group)}</span>
                            <span>${item.count} máy (${pct}%)</span>
                        </div>
                        <div class="progress"><div class="progress-bar bg-secondary" style="width: ${pct}%"></div></div>
                    </div>
                    `;
                }).join('');
            }

            function filterSuspectAV() {
                document.getElementById('search-input').value = '';
                document.getElementById('dept-filter').value = 'Tất cả';
                const hf = document.getElementById('health-filter');
                if (hf) hf.value = 'NO_AGENT_SUSPECT_AV';
                const vf = document.getElementById('version-filter');
                if (vf) vf.value = 'ALL';
                const tabBtn = document.getElementById('tab-list-btn');
                if (tabBtn) tabBtn.click();
                loadData();
            }

            function filterOutdatedVersion() {
                document.getElementById('search-input').value = '';
                document.getElementById('dept-filter').value = 'Tất cả';
                const hf = document.getElementById('health-filter');
                if (hf) hf.value = 'ALL';
                const vf = document.getElementById('version-filter');
                if (vf) vf.value = 'OUTDATED';
                const tabBtn = document.getElementById('tab-list-btn');
                if (tabBtn) tabBtn.click();
                loadData();
            }

            function filterByDept(deptName) {
                const tabListBtn = document.getElementById('tab-list-btn');
                const triggerTab = new bootstrap.Tab(tabListBtn);
                triggerTab.show();

                const sel = document.getElementById('dept-filter');
                sel.value = deptName;
                loadData();
            }

            async function loadDepartments() {
                try {
                    const res = await fetch('/api/departments');
                    const depts = await res.json();
                    const sel = document.getElementById('dept-filter');
                    sel.innerHTML = '<option value="Tất cả">-- Tất cả Khoa / Phòng ban --</option>';
                    depts.forEach(d => {
                        const opt = document.createElement('option');
                        opt.value = d;
                        opt.innerText = d;
                        sel.appendChild(opt);
                    });
                } catch(e) { console.error(e); }
            }

            async function loadData() {
                const search = document.getElementById('search-input').value.trim();
                const dept = document.getElementById('dept-filter').value;
                const healthFilter = document.getElementById('health-filter') ? document.getElementById('health-filter').value : 'ALL';
                const versionFilterEl = document.getElementById('version-filter');
                const versionFilter = versionFilterEl ? versionFilterEl.value : 'ALL';
                
                let url = '/api/inventory?';
                if (search) url += 'search=' + encodeURIComponent(search) + '&';
                if (dept && dept !== 'Tất cả') url += 'department=' + encodeURIComponent(dept);

                const tbody = document.getElementById('devices-body');
                try {
                    const res = await fetch(url);
                    let devices = await res.json();
                    if (!search && (!dept || dept === 'Tất cả')) {
                        const allOnline = devices.filter(d => d.is_online).length;
                        const allSuspect = devices.filter(d => d.agent_health === 'NO_AGENT_SUSPECT_AV').length;
                        document.getElementById('stat-online').innerHTML = allSuspect > 0
                            ? `${allOnline} / ${devices.length} <div class="mt-1"><span class="badge bg-warning text-dark" style="cursor:pointer;font-size:0.75rem;" onclick="filterSuspectAV()" title="Bấm để xem các máy đang bật (Ping thông) nhưng không thấy phần mềm IN4">${allSuspect} máy bật / mất IN4</span></div>`
                            : `${allOnline} / ${devices.length}`;
                    }

                    // Cập nhật danh sách phiên bản thực tế vào bộ lọc #version-filter
                    if (versionFilterEl) {
                        const verCounts = {};
                        devices.forEach(d => {
                            const v = (d.client_version || '1.3.0').trim();
                            verCounts[v] = (verCounts[v] || 0) + 1;
                        });
                        const prevVal = versionFilterEl.value;
                        const sortedVers = Object.keys(verCounts).sort().reverse();
                        let optsHtml = `<option value="ALL">-- Tất cả phiên bản --</option>`;
                        optsHtml += `<option value="OUTDATED">⚠ Bản cũ (chưa lên v${escapeHtml(latestClientVersion)})</option>`;
                        sortedVers.forEach(v => {
                            const tag = (v === latestClientVersion) ? ' (Mới nhất)' : '';
                            optsHtml += `<option value="${escapeHtml(v)}">v${escapeHtml(v)}${tag} [${verCounts[v]} máy]</option>`;
                        });
                        versionFilterEl.innerHTML = optsHtml;
                        versionFilterEl.value = prevVal;
                    }

                    if (healthFilter === 'ONLINE') {
                        devices = devices.filter(d => d.is_online);
                    } else if (healthFilter === 'NO_AGENT_SUSPECT_AV') {
                        devices = devices.filter(d => d.agent_health === 'NO_AGENT_SUSPECT_AV');
                    } else if (healthFilter === 'OFFLINE') {
                        devices = devices.filter(d => !d.is_online && d.agent_health !== 'NO_AGENT_SUSPECT_AV');
                    }

                    if (versionFilter === 'OUTDATED') {
                        devices = devices.filter(d => (d.client_version || '1.3.0').trim() !== latestClientVersion);
                    } else if (versionFilter && versionFilter !== 'ALL') {
                        devices = devices.filter(d => (d.client_version || '1.3.0').trim() === versionFilter);
                    }

                    currentFilteredDevices = devices;
                    document.getElementById('filtered-count').innerText = `${devices.length} máy`;

                    if (devices.length === 0) {
                        tbody.innerHTML = '<tr><td colspan="10" class="text-center py-5 text-muted"><i class="bi bi-inbox fs-1 d-block mb-2"></i>Chưa có máy tính nào phù hợp bộ lọc</td></tr>';
                        return;
                    }

                    tbody.innerHTML = devices.map(d => {
                        let diskBadge = '<span class="badge-ssd">SSD</span>';
                        if (d.storage_details && d.storage_details.includes('HDD') && !d.storage_details.includes('SSD')) {
                            diskBadge = '<span class="badge-hdd">HDD</span>';
                        }
                        const barcodeHtml = d.barcode ? `<div class="mb-1"><span class="badge-barcode"><i class="bi bi-upc-scan me-1"></i>${escapeHtml(d.barcode)}</span></div>` : '';
                        
                        let statusDot;
                        if (d.is_online) {
                            statusDot = '<span class="status-dot-on me-1" title="Client đang chạy OK"></span> <small class="text-success fw-bold">ONLINE</small>';
                        } else if (d.agent_health === 'NO_AGENT_SUSPECT_AV') {
                            statusDot = '<span class="badge bg-warning text-dark" title="Ping mạng thông nhưng Port 8005 đóng & mất Heartbeat (Nghi AV diệt hoặc app tắt)"><i class="bi bi-exclamation-triangle-fill me-1"></i>MẤT CLIENT</small></span>';
                        } else {
                            statusDot = '<span class="status-dot-off me-1" title="Đã Tắt (Offline)"></span> <small class="text-muted">OFFLINE</small>';
                        }

                        const ver = (d.client_version || '1.3.0').trim();
                        const isLatestVer = (ver === latestClientVersion);
                        const versionBadge = isLatestVer
                            ? `<div class="mt-1"><span class="badge bg-success bg-opacity-75" style="font-size:0.68rem;" title="Đã ở phiên bản mới nhất">v${escapeHtml(ver)} ✓</span></div>`
                            : `<div class="mt-1"><span class="badge bg-secondary" style="font-size:0.68rem;" title="Bản cũ — cần cập nhật lên v${escapeHtml(latestClientVersion)}">v${escapeHtml(ver)} (Cũ)</span></div>`;

                        const lastSeenInfo = d.last_seen_relative ? `<div class="text-muted" style="font-size:0.7rem;" title="Tín hiệu cuối: ${d.last_seen || ''}"><i class="bi bi-broadcast me-1"></i>${escapeHtml(d.last_seen_relative)}</div>` : '';
                        const uptimeInfo = (d.is_online && d.uptime_hours) ? `<div class="text-success fw-bold" style="font-size:0.7rem;"><i class="bi bi-clock-history me-1"></i>Bật: ${d.uptime_hours}h</div>` : '';

                        const tamperWarning = d.hardware_tampered ? 
                            `<div class="mt-1"><span class="badge bg-danger pulse-alert" title="${escapeHtml(d.tamper_details || '')}"><i class="bi bi-shield-slash me-1"></i>Phần cứng đổi!</span></div>` : '';

                        return `
                        <tr class="device-row">
                            <td>
                                <div>${statusDot}</div>
                                ${versionBadge}
                                ${uptimeInfo}
                                ${lastSeenInfo}
                                ${tamperWarning}
                            </td>
                            <td>
                                ${barcodeHtml}
                                <span class="badge bg-light text-primary border mb-1">${escapeHtml(d.department || 'Chưa phân loại')}</span>
                                <div class="fw-bold">${escapeHtml(d.room_name || 'Phòng N/A')} <small class="text-muted">(P.${escapeHtml(d.room_number || '')})</small></div>
                            </td>
                            <td>
                                <div class="fw-bold text-dark"><i class="bi bi-person me-1"></i>${escapeHtml(d.user_name || 'N/A')}</div>
                                <div><small class="badge bg-light text-dark border">Win User: ${escapeHtml(d.logged_in_user || 'Unknown')}</small></div>
                                <small class="text-muted"><i class="bi bi-telephone me-1"></i>${escapeHtml(d.user_phone || 'N/A')}</small>
                            </td>
                            <td>
                                <div class="fw-bold text-primary">${escapeHtml(d.hostname || 'Unknown')}</div>
                                <div><small class="badge bg-light text-dark border">${escapeHtml(d.ip_address || '')}</small></div>
                                <div class="text-muted" style="font-size:0.75rem;">MAC: ${escapeHtml(d.mac_address || '')}</div>
                            </td>
                            <td>
                                <div class="small fw-bold text-dark">${escapeHtml(d.mainboard_info || 'Mainboard N/A')}</div>
                                <div class="small text-muted text-truncate" style="max-width:210px;" title="${escapeHtml(d.cpu_info || '')}">${escapeHtml(d.cpu_info || 'Unknown')}</div>
                            </td>
                            <td>
                                <div class="small fw-bold text-dark">${escapeHtml(d.ram_details || '')}</div>
                            </td>
                            <td>
                                <div class="mb-1">${diskBadge}</div>
                                <div class="small text-muted" style="max-width:190px; font-size:0.75rem;">${escapeHtml(d.storage_details || '')}</div>
                                <div class="small text-secondary" style="font-size:0.72rem;"><i class="bi bi-keyboard me-1"></i>${escapeHtml(d.peripherals_details || '')}</div>
                            </td>
                            <td>
                                <div class="small text-dark" style="max-width:210px; font-size:0.8rem;"><i class="bi bi-display me-1 text-primary"></i>${escapeHtml(d.monitors_details || 'N/A')}</div>
                            </td>
                            <td>
                                <small class="text-muted">${d.updated_at ? d.updated_at.substring(0, 16) : ''}</small>
                            </td>
                            <td class="text-center">
                                <div class="btn-group btn-group-sm">
                                    <button class="btn btn-outline-info" onclick="pingDevice('${d.ip_address}', '${d.mac_address}', '${escapeHtml(d.hostname)}', ${d.client_agent_port || 8005})" title="Kiểm tra kết nối trực tiếp (Ping)">
                                        <i class="bi bi-activity"></i>
                                    </button>
                                    <button class="btn btn-outline-primary" onclick="openNotifyModal('${d.ip_address}', ${d.client_agent_port || 8005}, '${escapeHtml(d.hostname)} - ${escapeHtml(d.user_name)}', '${d.mac_address}')" title="Gửi thông báo màn hình">
                                        <i class="bi bi-bell-fill"></i>
                                    </button>
                                    <button class="btn btn-outline-warning text-dark" onclick="openUpdateModal('${d.ip_address}', ${d.client_agent_port || 8005}, '${escapeHtml(d.hostname)}', '${d.mac_address}')" title="Cập nhật client từ xa">
                                        <i class="bi bi-arrow-repeat"></i>
                                    </button>
                                    <button class="btn btn-outline-danger" onclick="deleteDevice('${d.mac_address}')" title="Xóa máy này">
                                        <i class="bi bi-trash"></i>
                                    </button>
                                </div>
                            </td>
                        </tr>
                        `;
                    }).join('');
                } catch(e) {
                    tbody.innerHTML = '<tr><td colspan="10" class="text-center py-4 text-danger">Lỗi kết nối máy chủ!</td></tr>';
                }
            }

            function openNotifyModal(ip, port, targetName, mac = '') {
                document.getElementById('modal-notify-ip').value = ip || '';
                document.getElementById('modal-notify-mac').value = mac || '';
                document.getElementById('modal-notify-port').value = port || 8005;
                document.getElementById('modal-notify-target').value = `${targetName} (${ip || 'Auto-MAC'}:${port})`;
                document.getElementById('modal-notify-msg').value = "Phòng CNTT thông báo: Vui lòng lưu hồ sơ bệnh án và tắt máy tính trước khi rời phòng làm việc!";
                notifyModalObj.show();
            }

            async function executeRemoteNotify() {
                const ip = document.getElementById('modal-notify-ip').value;
                const mac = document.getElementById('modal-notify-mac').value;
                const port = parseInt(document.getElementById('modal-notify-port').value || 8005);
                const title = document.getElementById('modal-notify-title').value.trim();
                const msg = document.getElementById('modal-notify-msg').value.trim();

                if (!msg) { alert('Vui lòng nhập nội dung thông báo!'); return; }

                try {
                    const res = await fetch('/api/remote/notify', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ mac_address: mac, ip_address: ip, port: port, title: title, message: msg })
                    });
                    const result = await res.json();
                    if (res.ok) {
                        alert(result.message || '✓ Đã gửi thông báo thành công!');
                        notifyModalObj.hide();
                    } else {
                        alert('✗ Lỗi gửi thông báo: ' + (result.detail || 'Không gửi được'));
                    }
                } catch(e) { alert('Lỗi kết nối máy chủ: ' + e); }
            }

            function openUpdateModal(ip, port, targetName, mac = '') {
                document.getElementById('modal-update-ip').value = ip || '';
                document.getElementById('modal-update-mac').value = mac || '';
                document.getElementById('modal-update-port').value = port || 8005;
                document.getElementById('modal-update-target').value = `${targetName} (${ip || 'Auto-MAC'}:${port})`;
                updateModalObj.show();
            }

            async function executeRemoteUpdate() {
                const ip = document.getElementById('modal-update-ip').value;
                const mac = document.getElementById('modal-update-mac').value;
                const port = parseInt(document.getElementById('modal-update-port').value || 8005);
                const url = document.getElementById('modal-update-url').value.trim();

                try {
                    const res = await fetch('/api/remote/update', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ mac_address: mac, ip_address: ip, port: port, url: url })
                    });
                    const result = await res.json();
                    if (res.ok) {
                        alert(result.message || '✓ Đã gửi lệnh cập nhật thành công!');
                        updateModalObj.hide();
                    } else {
                        alert('✗ Lỗi gửi lệnh cập nhật: ' + (result.detail || 'Không kết nối được'));
                    }
                } catch(e) { alert('Lỗi kết nối máy chủ: ' + e); }
            }

            async function updateFilteredDevices() {
                if (!currentFilteredDevices || currentFilteredDevices.length === 0) {
                    alert('Không có máy nào trong danh sách đang lọc!');
                    return;
                }
                const macs = currentFilteredDevices.map(d => d.mac_address).filter(Boolean);
                if (!confirm(`Đẩy lệnh cập nhật in4.exe cho đúng ${macs.length} máy đang hiển thị trong bộ lọc?`)) return;
                try {
                    const res = await fetch('/api/remote/update-batch', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ mac_addresses: macs, target_version: latestClientVersion })
                    });
                    const result = await res.json();
                    alert(result.message || '✓ Đã phát hành lệnh cập nhật cho nhóm đã lọc!');
                } catch(e) { alert('Lỗi kết nối máy chủ: ' + e); }
            }

            async function updateAllClients() {
                const targetVer = prompt('Nhập phiên bản Client mục tiêu (Desired State) muốn phát hành cho toàn viện:', '1.3.1');
                if (!targetVer || !targetVer.trim()) return;
                try {
                    const res = await fetch('/api/remote/update-all', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ target_version: targetVer.trim() })
                    });
                    const result = await res.json();
                    alert(result.message || '✓ Đã phát hành lệnh cập nhật toàn viện!');
                } catch(e) { alert('Lỗi kết nối máy chủ: ' + e); }
            }

            async function deleteDevice(mac) {
                if (!confirm(`Bạn có chắc muốn xóa thông tin máy có MAC [${mac}] khỏi hệ thống?`)) return;
                try {
                    const res = await fetch('/api/inventory/' + encodeURIComponent(mac), { method: 'DELETE' });
                    if (res.ok) {
                        loadAll();
                    } else {
                        alert('Không thể xóa thiết bị này!');
                    }
                } catch(e) { alert('Lỗi kết nối: ' + e); }
            }

            async function pingDevice(ip, mac, hostname, port = 8005) {
                currentPingTarget = { ip, mac, hostname, port };
                document.getElementById('ping-modal-body').innerHTML = `
                    <div class="text-center py-4">
                        <div class="spinner-border text-primary mb-3" role="status"></div>
                        <div class="fw-bold">Đang gửi gói tin Ping & kiểm tra máy [${escapeHtml(hostname || ip)}]...</div>
                        <div class="text-muted small mt-1">Đang kiểm tra: 1. Heartbeat Outbound | 2. Giao thức ICMP Ping | 3. Cổng Agent ${port}</div>
                    </div>
                `;
                pingModalObj.show();

                try {
                    const res = await fetch('/api/remote/ping', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ mac_address: mac, ip_address: ip, port: port })
                    });
                    const data = await res.json();
                    renderPingResult(data);
                    loadData();
                } catch (err) {
                    document.getElementById('ping-modal-body').innerHTML = `
                        <div class="alert alert-danger mb-0">
                            <i class="bi bi-exclamation-triangle-fill me-2"></i>Lỗi kết nối tới máy chủ khi ping: ${escapeHtml(err.message)}
                        </div>
                    `;
                }
            }

            function recheckCurrentPing() {
                if (currentPingTarget) {
                    pingDevice(currentPingTarget.ip, currentPingTarget.mac, currentPingTarget.hostname, currentPingTarget.port);
                }
            }

            function renderPingResult(data) {
                const badgeClass = `bg-${data.badge}`;
                const icmpBadge = data.icmp_success ? 
                    `<span class="badge bg-success"><i class="bi bi-check-circle-fill me-1"></i>Thành công (${data.icmp_latency_ms} ms)</span>` : 
                    `<span class="badge bg-secondary"><i class="bi bi-x-circle-fill me-1"></i>Timeout (Chặn ICMP / Tắt máy)</span>`;

                const liveVer = data.agent_info?.version || data.db_client_version || '1.3.0';
                const isLatest = (liveVer === latestClientVersion);
                const verBadgeHtml = isLatest
                    ? `<span class="badge bg-success ms-2">Client v${escapeHtml(liveVer)} (Mới nhất)</span>`
                    : `<span class="badge bg-warning text-dark ms-2">Client v${escapeHtml(liveVer)} (Bản cũ)</span>`;

                const hbBadge = data.heartbeat_active ? 
                    `<span class="badge bg-success"><i class="bi bi-check-circle-fill me-1"></i>Đang nhận tín hiệu (${data.heartbeat_seconds_ago}s trước) · v${escapeHtml(data.db_client_version || '1.3.0')}</span>` : 
                    `<span class="badge bg-danger"><i class="bi bi-x-circle-fill me-1"></i>Không có tín hiệu (${data.heartbeat_seconds_ago !== null ? data.heartbeat_seconds_ago + 's trước' : 'Chưa có'})</span>`;

                const agentBadge = data.agent_port_active ? 
                    `<span class="badge bg-success"><i class="bi bi-check-circle-fill me-1"></i>Cổng 8005 mở (Phiên bản: v${escapeHtml(data.agent_info?.version || '1.3.0')})</span>` : 
                    `<span class="badge bg-warning text-dark"><i class="bi bi-shield-lock me-1"></i>Không thể kết nối (Firewall chặn chiều vào)</span>`;

                document.getElementById('ping-modal-body').innerHTML = `
                    <div class="card mb-3 border-0 bg-light">
                        <div class="card-body">
                            <div class="d-flex align-items-center flex-wrap gap-1 mb-2">
                                <span class="badge ${badgeClass} fs-6 px-3 py-2 me-2">${data.status_label}</span>
                                <h6 class="fw-bold mb-0 text-dark">${escapeHtml(data.hostname || 'N/A')} <small class="text-muted">(${escapeHtml(data.ip_address || 'No IP')})</small></h6>
                                ${verBadgeHtml}
                            </div>
                            <div class="text-secondary small mt-2">${escapeHtml(data.description)}</div>
                        </div>
                    </div>

                    <ul class="list-group mb-3">
                        <li class="list-group-item d-flex justify-content-between align-items-center">
                            <div>
                                <div class="fw-bold"><i class="bi bi-heart-pulse-fill text-danger me-2"></i>1. Tín hiệu sống Heartbeat (Client -> Server)</div>
                                <small class="text-muted">Khẳng định phần mềm in4.exe có đang chạy và máy có kết nối mạng</small>
                            </div>
                            <div>${hbBadge}</div>
                        </li>
                        <li class="list-group-item d-flex justify-content-between align-items-center">
                            <div>
                                <div class="fw-bold"><i class="bi bi-hdd-network text-primary me-2"></i>2. Giao thức Ping mạng (ICMP Ping Echo)</div>
                                <small class="text-muted">Kiểm tra thông mạng ở tầng card mạng và thiết bị</small>
                            </div>
                            <div>${icmpBadge}</div>
                        </li>
                        <li class="list-group-item d-flex justify-content-between align-items-center">
                            <div>
                                <div class="fw-bold"><i class="bi bi-terminal-split text-info me-2"></i>3. Cổng điều khiển Agent (Port 8005)</div>
                                <small class="text-muted">Kiểm tra kết nối trực tiếp hai chiều</small>
                            </div>
                            <div>${agentBadge}</div>
                        </li>
                    </ul>
                    <div class="small text-muted fst-italic">
                        <i class="bi bi-info-circle me-1"></i>Mẹo: Nếu máy có Heartbeat nhưng ICMP Ping timeout, điều đó có nghĩa là Windows Defender Firewall trên máy trạm đang chặn ping chiều vào, nhưng máy vẫn đang hoạt động và nhận lệnh bình thường!
                    </div>
                `;
            }

            async function pingAllDevices() {
                const btn = document.getElementById('btn-ping-all');
                if (btn) {
                    btn.disabled = true;
                    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Đang ping toàn viện...';
                }

                try {
                    const res = await fetch('/api/remote/ping-all', { method: 'POST' });
                    const result = await res.json();
                    alert(`✓ ĐÃ KIỂM TRA XONG TOÀN VIỆN!\n- Tổng số máy tính: ${result.total}\n- Đang BẬT (Online): ${result.online_count}\n- Đã TẮT (Offline): ${result.offline_count}`);
                    loadAll();
                } catch (err) {
                    alert('Lỗi kiểm tra toàn viện: ' + err.message);
                } finally {
                    if (btn) {
                        btn.disabled = false;
                        btn.innerHTML = '<i class="bi bi-broadcast-pin me-1"></i>⚡ Ping toàn viện';
                    }
                }
            }

            function escapeHtml(text) {
                if (!text) return '';
                return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
            }

            function loadAll() {
                loadStats();
                loadOvernightPcs();
                loadHardwareAlerts();
                loadPowerLogs();
                loadData();
            }

            document.getElementById('search-input').addEventListener('input', () => {
                loadData();
            });
            document.getElementById('dept-filter').addEventListener('change', loadData);
            if (document.getElementById('health-filter')) {
                document.getElementById('health-filter').addEventListener('change', loadData);
            }
            if (document.getElementById('version-filter')) {
                document.getElementById('version-filter').addEventListener('change', loadData);
            }

            loadDepartments();
            loadAll();

            // Tự động làm mới số liệu mỗi 15 giây
            setInterval(loadAll, 15000);
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


def _probe_single_stale_device(pc: dict):
    """Kiểm tra 1 máy quá hạn Heartbeat: TCP Port 8005 + ICMP Ping."""
    import socket
    import subprocess
    mac = pc.get("mac_address", "")
    ip = pc.get("ip_address", "")
    port = int(pc.get("client_agent_port") or 8005)
    if not mac or not ip:
        return

    port_ok = False
    try:
        with socket.create_connection((ip, port), timeout=0.8):
            port_ok = True
    except Exception:
        pass

    ping_ok = False
    if ip == "127.0.0.1":
        ping_ok = True
    else:
        try:
            creationflags = 0x08000000 if sys.platform == "win32" else 0
            cmd = ["ping", "-n", "1", "-w", "600", ip] if sys.platform == "win32" else ["ping", "-c", "1", "-W", "1", ip]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=creationflags)
            ping_ok = (res.returncode == 0)
        except Exception:
            pass

    if port_ok:
        database.update_probe_result(mac, 1, 1 if ping_ok else 0, 1, "ONLINE")
    elif ping_ok:
        database.update_probe_result(mac, 0, 1, 0, "NO_AGENT_SUSPECT_AV")
    else:
        database.update_probe_result(mac, 0, 0, 0, "OFFLINE")


def _background_probe_loop():
    """Chỉ quét các máy quá hạn Heartbeat (>12 phút) mỗi 2 phút để phát hiện máy bật nhưng mất Client."""
    import time
    from concurrent.futures import ThreadPoolExecutor
    time.sleep(15)
    while True:
        try:
            stale = database.get_stale_computers_for_probe(OFFLINE_THRESHOLD_SECONDS)
            if stale:
                with ThreadPoolExecutor(max_workers=20) as ex:
                    list(ex.map(_probe_single_stale_device, stale))
        except Exception:
            pass
        time.sleep(120)


if __name__ == "__main__":
    import uvicorn
    import argparse

    parser = argparse.ArgumentParser(description="Hospital PC Inventory Server")
    parser.add_argument("--port", type=int, default=8000, help="Cổng máy chủ lắng nghe (mặc định 8000)")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Địa chỉ host (mặc định 0.0.0.0)")
    parser.add_argument("--no-browser", action="store_true", help="Không tự mở trình duyệt khi khởi động")
    args, unknown = parser.parse_known_args()

    # Hỗ trợ truyền port dạng tham số: PCin4Server.exe 8000 hoặc PCin4Server.exe 3000
    if unknown:
        for arg in unknown:
            if arg.isdigit():
                args.port = int(arg)
                break

    print("===================================================================")
    print("  PCin4Server - QUAN LY & THU THAP THIET BI PC BENH VIEN")
    print("===================================================================")
    print(f"  Cong lang nghe (Port):   {args.port}")
    print(f"  Web Dashboard:           http://localhost:{args.port} hoac http://10.10.12.188:{args.port}")
    print(f"  Link tai Tool in4.exe:   http://10.10.12.188:{args.port}/in4.exe")
    print(f"  API Documentation:       http://localhost:{args.port}/docs")

    try:
        import hot_deploy
        hot_deploy.start_hot_deploy_server(BASE_DIR, app_port=args.port)
    except Exception as hd_err:
        print(f"  [!] Khong the khoi dong Hot-Deploy: {hd_err}")

    print("===================================================================")

    # Tự động mở trình duyệt web khi khởi động máy chủ (trừ khi chạy lại sau hot-deploy)
    if not args.no_browser:
        import threading
        import webbrowser
        def auto_open_browser(p):
            import time
            time.sleep(1.2)
            try:
                webbrowser.open(f"http://localhost:{p}")
            except Exception:
                pass
        threading.Thread(target=auto_open_browser, args=(args.port,), daemon=True).start()

    import logging
    class _QuietHeartbeatFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            msg = record.getMessage()
            if "/api/heartbeat" in msg and " 200" in msg:
                return False
            return True

    logging.getLogger("uvicorn.access").addFilter(_QuietHeartbeatFilter())

    import threading
    threading.Thread(target=_background_probe_loop, daemon=True).start()

    try:
        uvicorn.run(app, host=args.host, port=args.port)
    except Exception as srv_err:
        import traceback
        from datetime import datetime
        err_text = traceback.format_exc()
        try:
            with open(os.path.join(BASE_DIR, "server_error.log"), "a", encoding="utf-8") as f:
                f.write(f"\n[{datetime.now()}] {err_text}\n")
        except Exception:
            pass
        print(f"\n[LOI KHOI DONG SERVER]: {srv_err}\n{err_text}")
        if not args.no_browser:
            try:
                input("Nhan Enter de thoat...")
            except Exception:
                pass
