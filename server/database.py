"""
database.py
Quản lý kết nối và thao tác CSDL SQLite cho hệ thống Quản lý Thiết bị Bệnh viện.
"""

import sqlite3
import os
import sys
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DB_PATH = os.path.join(BASE_DIR, "inventory.db")


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def init_db():
    """Khởi tạo bảng computers, hardware_history, power_logs và index nếu chưa tồn tại."""
    conn = get_db_connection()
    conn.execute("PRAGMA journal_mode = WAL")
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS computers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        barcode TEXT,
        mac_address TEXT UNIQUE NOT NULL,
        hostname TEXT,
        ip_address TEXT,
        os_name TEXT,
        mainboard_info TEXT,
        cpu_info TEXT,
        ram_total_gb REAL,
        ram_details TEXT,
        storage_details TEXT,
        monitors_details TEXT,
        peripherals_details TEXT,
        room_number TEXT,
        room_name TEXT,
        department TEXT,
        user_name TEXT,
        user_phone TEXT,
        notes TEXT,
        logged_in_user TEXT,
        boot_time TEXT,
        last_seen TIMESTAMP,
        is_online INTEGER DEFAULT 1,
        hardware_tampered INTEGER DEFAULT 0,
        tamper_details TEXT,
        client_agent_port INTEGER DEFAULT 8005,
        client_version TEXT DEFAULT '1.3.0',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Bảng lưu vết thay đổi / tráo đổi phần cứng
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS hardware_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        mac_address TEXT NOT NULL,
        hostname TEXT,
        department TEXT,
        user_name TEXT,
        component TEXT NOT NULL,
        old_value TEXT,
        new_value TEXT,
        detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_acknowledged INTEGER DEFAULT 0
    );
    """)

    # Bảng nhật ký bật / tắt máy tính (Power Logs)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS power_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        mac_address TEXT NOT NULL,
        hostname TEXT,
        department TEXT,
        user_name TEXT,
        logged_in_user TEXT,
        event_type TEXT NOT NULL,
        event_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        uptime_hours REAL DEFAULT 0,
        notes TEXT
    );
    """)

    # Bảng hàng đợi lệnh gửi từ xa (Thông báo, Update - giải quyết 100% lỗi timeout / khác mạng / firewall)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS pending_commands (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        mac_address TEXT NOT NULL,
        command_type TEXT NOT NULL,
        payload TEXT NOT NULL,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        executed_at TIMESTAMP
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pending_mac_status ON pending_commands(mac_address, status);")

    # Migration thêm cột nếu bảng computers đã có từ trước
    migrations = [
        ("barcode", "TEXT"),
        ("peripherals_details", "TEXT"),
        ("mainboard_info", "TEXT"),
        ("logged_in_user", "TEXT"),
        ("boot_time", "TEXT"),
        ("last_seen", "TIMESTAMP"),
        ("is_online", "INTEGER DEFAULT 1"),
        ("hardware_tampered", "INTEGER DEFAULT 0"),
        ("tamper_details", "TEXT"),
        ("client_agent_port", "INTEGER DEFAULT 8005"),
        ("client_version", "TEXT DEFAULT '1.3.0'"),
        ("ping_ok", "INTEGER DEFAULT 0"),
        ("port_ok", "INTEGER DEFAULT 0"),
        ("agent_health", "TEXT DEFAULT 'ONLINE'"),
        ("last_probe_at", "TIMESTAMP")
    ]
    for col, ctype in migrations:
        try:
            cursor.execute(f"ALTER TABLE computers ADD COLUMN {col} {ctype};")
        except sqlite3.OperationalError:
            pass

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_computers_mac ON computers(mac_address);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_computers_barcode ON computers(barcode);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_computers_dept ON computers(department);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_power_mac ON power_logs(mac_address);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_hw_hist_mac ON hardware_history(mac_address);")
    conn.commit()
    conn.close()


def upsert_computer(data: Dict[str, Any]) -> int:
    """
    Thêm mới hoặc Cập nhật thông tin máy tính dựa vào MAC Address (Unique Key).
    Tự động:
    1. So sánh phần cứng và lưu vết cảnh báo nếu có linh kiện bị tráo đổi/thay đổi
    2. Ghi nhận sự kiện khởi động máy (STARTUP/BOOT) vào bảng power_logs
    3. Cập nhật trạng thái online và thời điểm cuối cùng nhận tin
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    mac_clean = str(data.get("mac_address", "")).strip().upper()

    # 1. Kiểm tra cấu hình cũ để phát hiện tráo đổi linh kiện
    cursor.execute("SELECT * FROM computers WHERE mac_address = ?", (mac_clean,))
    existing = cursor.fetchone()

    hardware_tampered = 0
    tamper_details = ""
    changes = []

    if existing:
        hardware_tampered = existing["hardware_tampered"] or 0
        tamper_details = existing["tamper_details"] or ""

        # So sánh RAM
        old_ram = str(existing["ram_details"] or "").strip()
        new_ram = str(data.get("ram_details") or "").strip()
        old_ram_gb = float(existing["ram_total_gb"] or 0)
        new_ram_gb = float(data.get("ram_total_gb") or 0)
        if (old_ram and new_ram and old_ram != new_ram) or (old_ram_gb > 0 and new_ram_gb > 0 and abs(old_ram_gb - new_ram_gb) >= 0.8):
            changes.append(("RAM", f"{old_ram_gb} GB ({old_ram})", f"{new_ram_gb} GB ({new_ram})"))

        # So sánh Ổ cứng
        old_disk = str(existing["storage_details"] or "").strip()
        new_disk = str(data.get("storage_details") or "").strip()
        if old_disk and new_disk and old_disk != new_disk:
            changes.append(("Ổ cứng", old_disk, new_disk))

        # So sánh CPU
        old_cpu = str(existing["cpu_info"] or "").strip()
        new_cpu = str(data.get("cpu_info") or "").strip()
        if old_cpu and new_cpu and old_cpu != new_cpu:
            changes.append(("CPU", old_cpu, new_cpu))

        # So sánh Màn hình
        old_mon = str(existing["monitors_details"] or "").strip()
        new_mon = str(data.get("monitors_details") or "").strip()
        if old_mon and new_mon and old_mon != new_mon:
            changes.append(("Màn hình", old_mon, new_mon))

        if changes:
            hardware_tampered = 1
            tamper_details = "; ".join([f"{c[0]}: Cũ [{c[1]}] -> Mới [{c[2]}]" for c in changes])
            for comp, old_val, new_val in changes:
                cursor.execute("""
                INSERT INTO hardware_history (mac_address, hostname, department, user_name, component, old_value, new_value, detected_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    mac_clean,
                    data.get("hostname", "") or existing["hostname"],
                    data.get("department", "") or existing["department"],
                    data.get("user_name", "") or existing["user_name"],
                    comp,
                    old_val,
                    new_val,
                    now_str
                ))

    # 2. Ghi nhận sự kiện khởi động máy vào power_logs
    boot_time = data.get("boot_time", "")
    logged_in_user = data.get("logged_in_user", "")
    dept = data.get("department", "") or (existing["department"] if existing else "")
    u_name = data.get("user_name", "") or (existing["user_name"] if existing else "")
    h_name = data.get("hostname", "") or (existing["hostname"] if existing else "")

    cursor.execute("""
    INSERT INTO power_logs (mac_address, hostname, department, user_name, logged_in_user, event_type, event_time, notes)
    VALUES (?, ?, ?, ?, ?, 'STARTUP', ?, ?)
    """, (
        mac_clean,
        h_name,
        dept,
        u_name,
        logged_in_user,
        now_str,
        f"Khởi động máy (Boot lúc {boot_time or now_str})"
    ))

    # 3. Upsert vào bảng computers
    cursor.execute("""
    INSERT INTO computers (
        barcode, mac_address, hostname, ip_address, os_name, mainboard_info, cpu_info,
        ram_total_gb, ram_details, storage_details, monitors_details, peripherals_details,
        room_number, room_name, department, user_name, user_phone, notes,
        logged_in_user, boot_time, last_seen, is_online, hardware_tampered, tamper_details,
        client_agent_port, client_version,
        created_at, updated_at
    ) VALUES (
        :barcode, :mac_address, :hostname, :ip_address, :os_name, :mainboard_info, :cpu_info,
        :ram_total_gb, :ram_details, :storage_details, :monitors_details, :peripherals_details,
        :room_number, :room_name, :department, :user_name, :user_phone, :notes,
        :logged_in_user, :boot_time, :now_str, 1, :hardware_tampered, :tamper_details,
        :client_agent_port, :client_version,
        :now_str, :now_str
    )
    ON CONFLICT(mac_address) DO UPDATE SET
        barcode = COALESCE(NULLIF(excluded.barcode, ''), computers.barcode),
        hostname = excluded.hostname,
        ip_address = excluded.ip_address,
        os_name = excluded.os_name,
        mainboard_info = excluded.mainboard_info,
        cpu_info = excluded.cpu_info,
        ram_total_gb = excluded.ram_total_gb,
        ram_details = excluded.ram_details,
        storage_details = excluded.storage_details,
        monitors_details = excluded.monitors_details,
        peripherals_details = excluded.peripherals_details,
        room_number = COALESCE(NULLIF(excluded.room_number, ''), computers.room_number),
        room_name = COALESCE(NULLIF(excluded.room_name, ''), computers.room_name),
        department = COALESCE(NULLIF(excluded.department, ''), computers.department),
        user_name = COALESCE(NULLIF(excluded.user_name, ''), computers.user_name),
        user_phone = COALESCE(NULLIF(excluded.user_phone, ''), computers.user_phone),
        notes = COALESCE(NULLIF(excluded.notes, ''), computers.notes),
        logged_in_user = COALESCE(NULLIF(excluded.logged_in_user, ''), computers.logged_in_user),
        boot_time = COALESCE(NULLIF(excluded.boot_time, ''), computers.boot_time),
        last_seen = excluded.last_seen,
        is_online = 1,
        hardware_tampered = :hardware_tampered,
        tamper_details = :tamper_details,
        client_agent_port = excluded.client_agent_port,
        client_version = excluded.client_version,
        updated_at = excluded.updated_at
    """, {
        "barcode": str(data.get("barcode", "")).strip(),
        "mac_address": mac_clean,
        "hostname": data.get("hostname", ""),
        "ip_address": data.get("ip_address", ""),
        "os_name": data.get("os_name", ""),
        "mainboard_info": data.get("mainboard_info", ""),
        "cpu_info": data.get("cpu_info", ""),
        "ram_total_gb": float(data.get("ram_total_gb", 0) or 0),
        "ram_details": data.get("ram_details", ""),
        "storage_details": data.get("storage_details", ""),
        "monitors_details": data.get("monitors_details", ""),
        "peripherals_details": data.get("peripherals_details", ""),
        "room_number": str(data.get("room_number", "")).strip(),
        "room_name": data.get("room_name", "").strip(),
        "department": data.get("department", "").strip(),
        "user_name": data.get("user_name", "").strip(),
        "user_phone": data.get("user_phone", "").strip(),
        "notes": data.get("notes", "").strip(),
        "logged_in_user": logged_in_user,
        "boot_time": boot_time,
        "hardware_tampered": hardware_tampered,
        "tamper_details": tamper_details,
        "client_agent_port": int(data.get("client_agent_port", 8005) or 8005),
        "client_version": data.get("client_version", "1.3.0"),
        "now_str": now_str
    })
    
    device_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return device_id


def format_relative_time(dt_str: Optional[str]) -> str:
    """Chuyển đổi thời gian thành dạng tương đối dễ hiểu (vd: 5 giây trước, 2 phút trước)."""
    if not dt_str:
        return "Chưa có tín hiệu"
    try:
        dt = datetime.strptime(str(dt_str)[:19], "%Y-%m-%d %H:%M:%S")
        secs = (datetime.now() - dt).total_seconds()
        if secs < 0:
            return "Vừa xong"
        if secs < 15:
            return "Vừa mới xong"
        if secs < 60:
            return f"{int(secs)} giây trước"
        if secs < 3600:
            return f"{int(secs // 60)} phút trước"
        if secs < 86400:
            return f"{int(secs // 3600)} giờ trước"
        return f"{int(secs // 86400)} ngày trước"
    except Exception:
        return str(dt_str)[:16]


def get_all_computers(search: Optional[str] = None, department: Optional[str] = None) -> List[Dict[str, Any]]:
    # Tự động cập nhật trạng thái online trước khi truy vấn (ngưỡng 45 giây)
    update_online_status_threshold()

    conn = get_db_connection()
    cursor = conn.cursor()

    query = "SELECT * FROM computers WHERE 1=1"
    params = []

    if department and department.strip() and department != "Tất cả":
        query += " AND department = ?"
        params.append(department.strip())

    if search and search.strip():
        term = f"%{search.strip()}%"
        query += """ AND (
            barcode LIKE ? OR
            hostname LIKE ? OR 
            ip_address LIKE ? OR 
            mac_address LIKE ? OR 
            user_name LIKE ? OR 
            room_name LIKE ? OR 
            room_number LIKE ? OR 
            mainboard_info LIKE ? OR
            cpu_info LIKE ? OR 
            storage_details LIKE ? OR
            monitors_details LIKE ? OR
            peripherals_details LIKE ?
        )"""
        params.extend([term] * 12)

    query += " ORDER BY updated_at DESC"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    results = [dict(r) for r in rows]
    conn.close()

    now = datetime.now()
    for d in results:
        d["last_seen_relative"] = format_relative_time(d.get("last_seen"))
        boot_str = str(d.get("boot_time") or "").strip()
        uptime_h = 0.0
        if boot_str and d.get("is_online"):
            try:
                b_dt = datetime.strptime(boot_str[:19], "%Y-%m-%d %H:%M:%S")
                uptime_h = round((now - b_dt).total_seconds() / 3600.0, 1)
            except Exception:
                pass
        d["uptime_hours"] = uptime_h

    return results


def get_departments() -> List[str]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT department FROM computers WHERE department IS NOT NULL AND department != '' ORDER BY department ASC")
    rows = cursor.fetchall()
    depts = [r["department"] for r in rows]
    conn.close()
    return depts


def get_statistics() -> Dict[str, Any]:
    update_online_status_threshold()
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) AS total FROM computers")
    total = cursor.fetchone()["total"]

    cursor.execute("SELECT COUNT(*) AS online_pcs FROM computers WHERE is_online = 1")
    online_pcs = cursor.fetchone()["online_pcs"]

    cursor.execute("SELECT COUNT(*) AS suspect_av_pcs FROM computers WHERE agent_health = 'NO_AGENT_SUSPECT_AV'")
    suspect_av_pcs = cursor.fetchone()["suspect_av_pcs"]

    cursor.execute("SELECT COUNT(*) AS offline_pcs FROM computers WHERE is_online = 0")
    offline_pcs = cursor.fetchone()["offline_pcs"]

    cursor.execute("SELECT COUNT(*) AS low_ram FROM computers WHERE ram_total_gb > 0 AND ram_total_gb <= 4.0")
    low_ram = cursor.fetchone()["low_ram"]

    cursor.execute("SELECT COUNT(*) AS ssd_pcs FROM computers WHERE storage_details LIKE '%SSD%'")
    ssd_pcs = cursor.fetchone()["ssd_pcs"]

    cursor.execute("SELECT COUNT(*) AS hdd_only FROM computers WHERE storage_details LIKE '%HDD%' AND storage_details NOT LIKE '%SSD%'")
    hdd_only = cursor.fetchone()["hdd_only"]

    cursor.execute("SELECT COUNT(DISTINCT department) AS dept_count FROM computers WHERE department IS NOT NULL AND department != ''")
    dept_count = cursor.fetchone()["dept_count"]

    # Thống kê chi tiết từng khoa phòng
    cursor.execute("""
    SELECT 
        COALESCE(NULLIF(department, ''), 'Chưa phân khoa') AS dept,
        COUNT(*) AS total_pcs,
        SUM(CASE WHEN storage_details LIKE '%SSD%' THEN 1 ELSE 0 END) AS ssd_pcs,
        SUM(CASE WHEN storage_details LIKE '%HDD%' AND storage_details NOT LIKE '%SSD%' THEN 1 ELSE 0 END) AS hdd_pcs,
        SUM(CASE WHEN ram_total_gb > 0 AND ram_total_gb <= 4.0 THEN 1 ELSE 0 END) AS low_ram_pcs
    FROM computers
    GROUP BY dept
    ORDER BY total_pcs DESC, dept ASC
    """)
    dept_summary = [dict(r) for r in cursor.fetchall()]

    # Thống kê loại ổ cứng
    cursor.execute("""
    SELECT 
        SUM(CASE WHEN storage_details LIKE '%NVMe%' THEN 1 ELSE 0 END) AS nvme,
        SUM(CASE WHEN storage_details LIKE '%SSD%' AND storage_details NOT LIKE '%NVMe%' THEN 1 ELSE 0 END) AS ssd_sata,
        SUM(CASE WHEN storage_details LIKE '%HDD%' AND storage_details NOT LIKE '%SSD%' THEN 1 ELSE 0 END) AS hdd_only
    FROM computers
    """)
    storage_row = cursor.fetchone()
    storage_summary = {
        "nvme": storage_row["nvme"] or 0,
        "ssd_sata": storage_row["ssd_sata"] or 0,
        "hdd_only": storage_row["hdd_only"] or 0
    }

    # Thống kê phân bổ RAM
    cursor.execute("""
    SELECT 
        SUM(CASE WHEN ram_total_gb > 0 AND ram_total_gb <= 4.0 THEN 1 ELSE 0 END) AS ram_4gb,
        SUM(CASE WHEN ram_total_gb > 4.0 AND ram_total_gb <= 8.5 THEN 1 ELSE 0 END) AS ram_8gb,
        SUM(CASE WHEN ram_total_gb > 8.5 AND ram_total_gb <= 16.5 THEN 1 ELSE 0 END) AS ram_16gb,
        SUM(CASE WHEN ram_total_gb > 16.5 THEN 1 ELSE 0 END) AS ram_32gb
    FROM computers
    """)
    ram_row = cursor.fetchone()
    ram_summary = {
        "ram_4gb": ram_row["ram_4gb"] or 0,
        "ram_8gb": ram_row["ram_8gb"] or 0,
        "ram_16gb": ram_row["ram_16gb"] or 0,
        "ram_32gb": ram_row["ram_32gb"] or 0
    }

    # Thống kê hệ điều hành
    cursor.execute("""
    SELECT 
        CASE 
            WHEN os_name LIKE '%Windows 11%' THEN 'Windows 11'
            WHEN os_name LIKE '%Windows 10%' THEN 'Windows 10'
            WHEN os_name LIKE '%Windows 7%' THEN 'Windows 7'
            WHEN os_name LIKE '%Server%' THEN 'Windows Server'
            ELSE 'Khác'
        END AS os_group,
        COUNT(*) AS count
    FROM computers
    GROUP BY os_group
    ORDER BY count DESC
    """)
    os_summary = [dict(r) for r in cursor.fetchall()]

    conn.close()

    standard_ratio = round((ssd_pcs / total * 100), 1) if total > 0 else 0

    return {
        "total_pcs": total,
        "online_pcs": online_pcs,
        "suspect_av_pcs": suspect_av_pcs,
        "offline_pcs": offline_pcs,
        "ssd_pcs": ssd_pcs,
        "low_ram_pcs": low_ram,
        "hdd_only_pcs": hdd_only,
        "departments_count": dept_count,
        "standard_ratio": standard_ratio,
        "dept_summary": dept_summary,
        "storage_summary": storage_summary,
        "ram_summary": ram_summary,
        "os_summary": os_summary
    }


def delete_computer(mac_address: str) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM computers WHERE mac_address = ?", (mac_address.upper(),))
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def record_heartbeat(mac_address: str, ip_address: str, logged_in_user: str = "", uptime_hours: float = 0, boot_time: str = ""):
    """Cập nhật tín hiệu sống (Heartbeat) định kỳ từ client."""
    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
    UPDATE computers SET 
        last_seen = :now_str,
        is_online = 1,
        agent_health = 'ONLINE',
        port_ok = 1,
        ip_address = COALESCE(NULLIF(:ip_address, ''), ip_address),
        logged_in_user = COALESCE(NULLIF(:logged_in_user, ''), logged_in_user),
        boot_time = COALESCE(NULLIF(:boot_time, ''), boot_time)
    WHERE mac_address = :mac
    """, {
        "now_str": now_str,
        "ip_address": ip_address,
        "logged_in_user": logged_in_user,
        "boot_time": boot_time,
        "mac": mac_address.upper()
    })
    conn.commit()
    conn.close()


def get_computer_by_mac(mac_address: str) -> Optional[Dict[str, Any]]:
    """Lấy thông tin chi tiết của 1 máy tính theo địa chỉ MAC."""
    if not mac_address:
        return None
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM computers WHERE mac_address = ?", (mac_address.upper(),))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def set_computer_online(mac_address: str, is_online: int):
    """Cập nhật trạng thái is_online thủ công sau khi ping."""
    if not mac_address:
        return
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE computers SET is_online = ? WHERE mac_address = ?", (is_online, mac_address.upper()))
    conn.commit()
    conn.close()


def record_power_event(mac_address: str, event_type: str, logged_in_user: str = "", uptime_hours: float = 0, notes: str = ""):
    """Ghi nhận sự kiện nguồn (STARTUP / SHUTDOWN / SLEEP / RESUME)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    mac_clean = mac_address.upper()

    cursor.execute("SELECT hostname, department, user_name FROM computers WHERE mac_address = ?", (mac_clean,))
    pc = cursor.fetchone()
    hostname = pc["hostname"] if pc else ""
    dept = pc["department"] if pc else ""
    user_name = pc["user_name"] if pc else ""

    if event_type == "SHUTDOWN":
        cursor.execute("UPDATE computers SET is_online = 0, last_seen = ? WHERE mac_address = ?", (now_str, mac_clean))

    cursor.execute("""
    INSERT INTO power_logs (mac_address, hostname, department, user_name, logged_in_user, event_type, event_time, uptime_hours, notes)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (mac_clean, hostname, dept, user_name, logged_in_user, event_type, now_str, uptime_hours, notes))
    conn.commit()
    conn.close()


def update_online_status_threshold(timeout_seconds: int = 720):
    """Tự động chuyển các máy không có tín hiệu trong 720 giây (12 phút) thành Offline (hoặc chờ Probe đối soát)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cutoff = (datetime.now() - timedelta(seconds=timeout_seconds)).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
    UPDATE computers 
    SET is_online = 0,
        agent_health = CASE WHEN agent_health = 'ONLINE' THEN 'OFFLINE' ELSE agent_health END
    WHERE (last_seen IS NULL OR last_seen < ?) AND is_online = 1
    """, (cutoff,))
    conn.commit()
    conn.close()


def get_stale_computers_for_probe(timeout_seconds: int = 720) -> List[Dict[str, Any]]:
    """Lấy danh sách các máy quá hạn Heartbeat để Server chủ động Ping & Check Port 8005."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cutoff = (datetime.now() - timedelta(seconds=timeout_seconds)).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
    SELECT mac_address, ip_address, hostname, client_agent_port, last_seen
    FROM computers
    WHERE last_seen IS NULL OR last_seen < ?
    """, (cutoff,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_probe_result(mac_address: str, is_online: int, ping_ok: int, port_ok: int, agent_health: str):
    """Lưu kết quả đối soát 2 chiều (Ping + Port 8005) vào DB."""
    if not mac_address:
        return
    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
    UPDATE computers
    SET is_online = ?,
        ping_ok = ?,
        port_ok = ?,
        agent_health = ?,
        last_probe_at = ?
    WHERE mac_address = ?
    """, (is_online, ping_ok, port_ok, agent_health, now_str, mac_address.upper()))
    conn.commit()
    conn.close()


def get_hardware_alerts(limit: int = 50) -> List[Dict[str, Any]]:
    """Lấy danh sách các cảnh báo thay đổi / tráo đổi phần cứng."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT * FROM hardware_history 
    ORDER BY detected_at DESC 
    LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def ack_hardware_alert(alert_id: int) -> bool:
    """Xác nhận đã xử lý cảnh báo phần cứng."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE hardware_history SET is_acknowledged = 1 WHERE id = ?", (alert_id,))
    conn.commit()
    conn.close()
    return True


def get_overnight_pcs() -> List[Dict[str, Any]]:
    """
    Phát hiện các máy tính bật ngoài giờ làm việc (sau 18h hoặc bật liên tục > 10 tiếng)
    để quản lý xem ai không tắt máy khi không làm việc.
    """
    update_online_status_threshold()
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT * FROM computers 
    WHERE is_online = 1 
    ORDER BY department ASC, hostname ASC
    """)
    rows = cursor.fetchall()
    conn.close()

    now = datetime.now()
    current_hour = now.hour
    is_after_hours = (current_hour >= 18 or current_hour < 7 or now.weekday() >= 5)

    overnight_list = []
    for r in rows:
        d = dict(r)
        boot_str = str(d.get("boot_time") or "").strip()
        uptime_hours = 0.0
        if boot_str:
            try:
                b_dt = datetime.strptime(boot_str[:19], "%Y-%m-%d %H:%M:%S")
                uptime_hours = round((now - b_dt).total_seconds() / 3600.0, 1)
            except Exception:
                pass
        
        d["uptime_hours"] = uptime_hours
        d["last_seen_relative"] = format_relative_time(d.get("last_seen"))
        # Tiêu chí cảnh báo:
        # 1. Đang bật sau 18h (hết giờ làm việc)
        # 2. Hoặc máy đã chạy liên tục >= 10 tiếng
        if is_after_hours or uptime_hours >= 10.0:
            if is_after_hours and uptime_hours >= 14.0:
                d["alert_level"] = "CRITICAL"
                d["reason"] = f"Bật qua đêm {uptime_hours}h liên tục (Sau giờ làm)"
            elif is_after_hours:
                d["alert_level"] = "WARNING"
                d["reason"] = "Chưa tắt máy sau giờ làm việc (Sau 18h)"
            else:
                d["alert_level"] = "INFO"
                d["reason"] = f"Máy chạy liên tục {uptime_hours}h chưa tắt"
            overnight_list.append(d)

    return overnight_list


def get_power_logs(mac_address: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """Lấy lịch sử sự kiện bật tắt máy tính."""
    conn = get_db_connection()
    cursor = conn.cursor()
    if mac_address:
        cursor.execute("SELECT * FROM power_logs WHERE mac_address = ? ORDER BY event_time DESC LIMIT ?", (mac_address.upper(), limit))
    else:
        cursor.execute("SELECT * FROM power_logs ORDER BY event_time DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def queue_command(mac_address: str, command_type: str, payload: dict) -> int:
    """Đưa lệnh (thông báo / update) vào hàng đợi cho máy trạm (MAC)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO pending_commands (mac_address, command_type, payload, status)
        VALUES (?, ?, ?, 'pending')
    """, (mac_address.upper(), command_type, json.dumps(payload, ensure_ascii=False)))
    cmd_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return cmd_id


def get_pending_commands(mac_address: str) -> list:
    """Lấy danh sách lệnh đang chờ thực thi của máy trạm."""
    if not mac_address:
        return []
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, command_type, payload FROM pending_commands
        WHERE mac_address = ? AND status = 'pending'
        ORDER BY id ASC
    """, (mac_address.upper(),))
    rows = cursor.fetchall()
    cmds = []
    for r in rows:
        try:
            pl = json.loads(r["payload"])
        except Exception:
            pl = {}
        cmds.append({
            "command_id": r["id"],
            "type": r["command_type"],
            "payload": pl
        })
    conn.close()
    return cmds


def ack_command(command_id: int):
    """Xác nhận máy trạm đã nhận và thực thi xong lệnh."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE pending_commands
        SET status = 'completed', executed_at = ?
        WHERE id = ?
    """, (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), command_id))
    conn.commit()
    conn.close()


def get_mac_by_ip(ip_address: str) -> str:
    """Tìm MAC address dựa trên IP address."""
    if not ip_address:
        return ""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT mac_address FROM computers WHERE ip_address = ? ORDER BY id DESC LIMIT 1", (ip_address,))
    row = cursor.fetchone()
    conn.close()
    return row["mac_address"] if row else ""

