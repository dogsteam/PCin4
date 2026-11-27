#!/usr/bin/env python3
"""
deploy_server.py - Hot-Deploy PCin4Server.exe qua cổng 1994 (chunked 64KB + HMAC-SHA256)
Cách dùng:
    python3 scripts/deploy_server.py [IP_SERVER] [PORT] [SECRET_KEY] [PATH_TO_EXE]
Mặc định:
    IP_SERVER   = 10.10.12.188
    PORT        = 1994
    SECRET_KEY  = PCin4-HotDeploy-2026 (hoặc biến môi trường PCIN4_DEPLOY_SECRET)
    PATH_TO_EXE = server/PCin4Server.exe (hoặc PCin4Server.exe ở thư mục gốc)
"""

import hashlib
import hmac
import http.client
import json
import os
import sys
import time
import urllib.request

CHUNK_SIZE = 65536


def find_exe(explicit_path: str = "") -> str:
    if explicit_path and os.path.isfile(explicit_path):
        return explicit_path
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for candidate in (
        os.path.join(root, "server", "PCin4Server.exe"),
        os.path.join(root, "server", "dist", "PCin4Server.exe"),
        os.path.join(root, "PCin4Server.exe"),
    ):
        if os.path.isfile(candidate):
            return candidate
    return ""


def calc_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK_SIZE), b""):
            h.update(chunk)
    return h.hexdigest().lower()


def main():
    ip = sys.argv[1] if len(sys.argv) > 1 else "10.10.12.188"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 1994
    secret = sys.argv[3] if len(sys.argv) > 3 else os.environ.get("PCIN4_DEPLOY_SECRET", "PCin4-HotDeploy-2026")
    exe_arg = sys.argv[4] if len(sys.argv) > 4 else ""

    exe_path = find_exe(exe_arg)
    if not exe_path:
        print("✗ Không tìm thấy PCin4Server.exe! Hãy build trên Windows bằng server\\build_server.bat trước.")
        sys.exit(1)

    file_size = os.path.getsize(exe_path)
    file_sha256 = calc_sha256(exe_path)
    ts = str(int(time.time()))
    sig = hmac.new(secret.encode("utf-8"), f"{file_sha256}:{ts}".encode("utf-8"), hashlib.sha256).hexdigest().lower()

    print(f">>> Bắt đầu Hot-Deploy: {exe_path} ({file_size / (1024*1024):.2f} MB)")
    print(f">>> Đích: http://{ip}:{port}/deploy | SHA256: {file_sha256[:16]}...")

    conn = http.client.HTTPConnection(ip, port, timeout=30)
    conn.putrequest("POST", "/deploy")
    conn.putheader("Content-Type", "application/octet-stream")
    conn.putheader("Content-Length", str(file_size))
    conn.putheader("X-File-SHA256", file_sha256)
    conn.putheader("X-Deploy-Timestamp", ts)
    conn.putheader("X-Deploy-Signature", sig)
    conn.endheaders()

    sent = 0
    with open(exe_path, "rb") as f:
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            conn.send(chunk)
            sent += len(chunk)

    resp = conn.getresponse()
    body = resp.read().decode("utf-8", errors="replace")
    conn.close()

    if resp.status != 200:
        print(f"✗ Hot-Deploy thất bại (HTTP {resp.status}): {body}")
        sys.exit(1)

    print(f"✓ Server phản hồi: {body}")
    print(">>> Đang chờ 3 giây để kiểm tra Health-Check (port 8000)...")
    time.sleep(3)

    try:
        with urllib.request.urlopen(f"http://{ip}:8000/api/health", timeout=5) as r:
            health = json.loads(r.read().decode("utf-8"))
            print(f"✓ HEALTH-CHECK PASS: {health}")
    except Exception as e:
        print(f"⚠ Chưa kết nối được /api/health sau 3s (server có thể đang khởi động): {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
