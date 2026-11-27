"""
hot_deploy.py - Dịch vụ Hot-Deploy từ xa qua cổng mạng (Port 1994) cho PCin4Server.exe
Áp dụng theo spec build-deploy-xskill / node-sea-pack-and-update:
- Lắng nghe stream chunked 64KB trên port 1994
- Xác thực bằng Secret Key (HMAC-SHA256 hoặc X-Deploy-Secret)
- Kiểm tra toàn vẹn SHA256
- Sao lưu bản cũ (.old) + Rename-in-place + Tự khởi động lại không cần RDP
"""

import hashlib
import hmac
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_DEPLOY_PORT = 1994
DEFAULT_DEPLOY_SECRET = "PCin4-HotDeploy-2026"
CHUNK_SIZE = 65536


def _load_env_file(base_dir: str) -> dict:
    env_vars = {}
    env_path = os.path.join(base_dir, ".env")
    if not os.path.exists(env_path):
        return env_vars
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                env_vars[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        pass
    return env_vars


def get_deploy_config(base_dir: str) -> tuple:
    env_vars = _load_env_file(base_dir)
    port_str = os.environ.get("PCIN4_DEPLOY_PORT") or env_vars.get("PCIN4_DEPLOY_PORT") or str(DEFAULT_DEPLOY_PORT)
    secret = os.environ.get("PCIN4_DEPLOY_SECRET") or env_vars.get("PCIN4_DEPLOY_SECRET") or DEFAULT_DEPLOY_SECRET
    try:
        port = int(port_str)
    except ValueError:
        port = DEFAULT_DEPLOY_PORT
    return port, secret


def cleanup_old_server_files(base_dir: str):
    for fname in ("PCin4Server.old", "PCin4Server_new.tmp"):
        fpath = os.path.join(base_dir, fname)
        if os.path.exists(fpath):
            try:
                os.remove(fpath)
            except Exception:
                pass


def _verify_auth(headers, secret: str, file_sha256: str) -> bool:
    sig = headers.get("X-Deploy-Signature", "").strip().lower()
    ts_str = headers.get("X-Deploy-Timestamp", "").strip()
    if sig and ts_str:
        try:
            ts = int(ts_str)
            if abs(time.time() - ts) > 300:
                return False
            msg = f"{file_sha256.lower()}:{ts}".encode("utf-8")
            expected = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest().lower()
            return hmac.compare_digest(sig, expected)
        except Exception:
            return False

    direct_secret = headers.get("X-Deploy-Secret", "").strip()
    if direct_secret:
        return hmac.compare_digest(direct_secret, secret)
    return False


def _restart_server_later(target_exe: str, app_port: int):
    time.sleep(0.6)
    try:
        if getattr(sys, "frozen", False) and os.path.exists(target_exe):
            cmd = [target_exe, "--port", str(app_port), "--no-browser"]
        else:
            cmd = [sys.executable, os.path.abspath(sys.argv[0]), "--port", str(app_port), "--no-browser"]

        creationflags = 0
        if sys.platform == "win32":
            creationflags = 0x00000008 | 0x08000000  # DETACHED_PROCESS | CREATE_NO_WINDOW

        subprocess.Popen(cmd, creationflags=creationflags, close_fds=True)
    except Exception as e:
        print(f"[HOT-DEPLOY] Lỗi khởi động lại server: {e}")
    finally:
        os._exit(0)


def start_hot_deploy_server(base_dir: str, app_port: int = 8000):
    cleanup_old_server_files(base_dir)
    deploy_port, deploy_secret = get_deploy_config(base_dir)

    class HotDeployHandler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def _send_json(self, code: int, data: dict):
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/health":
                self._send_json(200, {
                    "status": "ok",
                    "service": "PCin4Server",
                    "deploy_port": deploy_port,
                    "app_port": app_port
                })
            else:
                self._send_json(404, {"error": "Not Found"})

        def do_POST(self):
            if self.path != "/deploy":
                self._send_json(404, {"error": "Not Found"})
                return

            expected_sha = self.headers.get("X-File-SHA256", "").strip().lower()
            if not expected_sha or not _verify_auth(self.headers, deploy_secret, expected_sha):
                self._send_json(401, {"status": "error", "message": "Xác thực Secret Key / HMAC thất bại!"})
                return

            content_len = int(self.headers.get("Content-Length", 0))
            if content_len <= 0:
                self._send_json(400, {"status": "error", "message": "Thiếu Content-Length hoặc file rỗng!"})
                return

            target_exe = os.path.join(base_dir, "PCin4Server.exe")
            old_exe = os.path.join(base_dir, "PCin4Server.old")
            temp_exe = os.path.join(base_dir, "PCin4Server_new.tmp")

            try:
                h = hashlib.sha256()
                remaining = content_len
                with open(temp_exe, "wb") as f:
                    while remaining > 0:
                        chunk = self.rfile.read(min(CHUNK_SIZE, remaining))
                        if not chunk:
                            break
                        f.write(chunk)
                        h.update(chunk)
                        remaining -= len(chunk)

                if remaining != 0:
                    if os.path.exists(temp_exe):
                        os.remove(temp_exe)
                    self._send_json(400, {"status": "error", "message": "Stream bị ngắt giữa chừng!"})
                    return

                actual_sha = h.hexdigest().lower()
                if actual_sha != expected_sha:
                    os.remove(temp_exe)
                    self._send_json(400, {"status": "error", "message": f"Sai SHA256! Thực tế: {actual_sha}"})
                    return

                if os.path.exists(old_exe):
                    try:
                        os.remove(old_exe)
                    except Exception:
                        pass

                renamed_old = False
                if os.path.exists(target_exe):
                    os.replace(target_exe, old_exe)
                    renamed_old = True

                try:
                    os.replace(temp_exe, target_exe)
                except Exception as swap_err:
                    if renamed_old and os.path.exists(old_exe) and not os.path.exists(target_exe):
                        try:
                            os.replace(old_exe, target_exe)
                        except Exception:
                            pass
                    raise swap_err

                self._send_json(200, {
                    "status": "success",
                    "message": "✓ Đã nhận PCin4Server.exe mới, đang khởi động lại dịch vụ...",
                    "sha256": actual_sha,
                    "bytes": content_len
                })
                threading.Thread(target=_restart_server_later, args=(target_exe, app_port), daemon=True).start()
            except Exception as e:
                if os.path.exists(temp_exe):
                    try:
                        os.remove(temp_exe)
                    except Exception:
                        pass
                self._send_json(500, {"status": "error", "message": f"Lỗi Hot-Deploy: {e}"})

    try:
        srv = ThreadingHTTPServer(("0.0.0.0", deploy_port), HotDeployHandler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        print(f"  Hot-Deploy Port:         {deploy_port} (Secret Auth + Chunked 64KB)")
    except Exception as e:
        print(f"  [!] Không thể mở cổng Hot-Deploy {deploy_port}: {e}")
