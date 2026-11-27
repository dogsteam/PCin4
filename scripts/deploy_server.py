#!/usr/bin/env python3
"""
deploy_server.py - Hot-Deploy PCin4Server.exe (và in4.exe) qua cổng 1994 (chunked 64KB + HMAC-SHA256)
Cách dùng:
    python3 scripts/deploy_server.py [IP_SERVER] [PORT] [SECRET_KEY] [--with-client]
Mặc định:
    IP_SERVER   = 10.10.12.188
    PORT        = 1994
    SECRET_KEY  = PCin4-HotDeploy-2026 (hoặc biến môi trường PCIN4_DEPLOY_SECRET)
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


def find_file(candidates) -> str:
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return ""


def calc_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK_SIZE), b""):
            h.update(chunk)
    return h.hexdigest().lower()


def push_binary(ip: str, port: int, secret: str, endpoint: str, file_path: str, label: str):
    file_size = os.path.getsize(file_path)
    file_sha256 = calc_sha256(file_path)
    ts = str(int(time.time()))
    sig = hmac.new(secret.encode("utf-8"), f"{file_sha256}:{ts}".encode("utf-8"), hashlib.sha256).hexdigest().lower()

    print(f">>> Đang đẩy {label}: {file_path} ({file_size / (1024*1024):.2f} MB)")
    print(f"    Đích: http://{ip}:{port}{endpoint} | SHA256: {file_sha256[:16]}...")

    conn = http.client.HTTPConnection(ip, port, timeout=60)
    conn.putrequest("POST", endpoint)
    conn.putheader("Content-Type", "application/octet-stream")
    conn.putheader("Content-Length", str(file_size))
    conn.putheader("X-File-SHA256", file_sha256)
    conn.putheader("X-Deploy-Timestamp", ts)
    conn.putheader("X-Deploy-Signature", sig)
    conn.endheaders()

    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            conn.send(chunk)

    resp = conn.getresponse()
    body = resp.read().decode("utf-8", errors="replace")
    conn.close()

    if resp.status != 200:
        print(f"✗ Đẩy {label} thất bại (HTTP {resp.status}): {body}")
        sys.exit(1)

    print(f"✓ Server phản hồi ({label}): {body}")


def main():
    args = [a for a in sys.argv[1:] if a not in ("--with-client", "--client-only")]
    with_client = ("--with-client" in sys.argv)
    client_only = ("--client-only" in sys.argv)

    ip = args[0] if len(args) > 0 else "10.10.12.188"
    port = int(args[1]) if len(args) > 1 else 1994
    secret = args[2] if len(args) > 2 else os.environ.get("PCIN4_DEPLOY_SECRET", "PCin4-HotDeploy-2026")
    exe_arg = args[3] if len(args) > 3 else ""

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    if with_client or client_only:
        client_exe = find_file([
            os.path.join(root, "server", "in4.exe"),
            os.path.join(root, "client", "dist", "in4.exe"),
            os.path.join(root, "in4.exe"),
        ])
        if not client_exe:
            print("✗ Không tìm thấy in4.exe để đẩy lên Server!")
            sys.exit(1)
        push_binary(ip, port, secret, "/deploy-client", client_exe, "in4.exe (Client)")
        if client_only:
            print("✓ Đã cập nhật xong in4.exe lên Server (không cần restart Server)!")
            return

    server_exe = find_file([
        exe_arg,
        os.path.join(root, "server", "PCin4Server.exe"),
        os.path.join(root, "server", "dist", "PCin4Server.exe"),
        os.path.join(root, "PCin4Server.exe"),
    ])
    if not server_exe:
        print("✗ Không tìm thấy PCin4Server.exe! Hãy build trên Windows bằng server\\build_server.bat trước.")
        sys.exit(1)

    push_binary(ip, port, secret, "/deploy", server_exe, "PCin4Server.exe (Server)")

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
