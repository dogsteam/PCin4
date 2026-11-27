"""
database.py
Quản lý kết nối và thao tác CSDL SQLite cho hệ thống Quản lý Thiết bị Bệnh viện.
"""

import sqlite3
import os
import sys
import json
import re
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple

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

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS system_settings (
        key TEXT PRIMARY KEY,
        value TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS component_registry (
        component_type TEXT NOT NULL,
        serial_number TEXT NOT NULL,
        component_desc TEXT,
        mac_address TEXT NOT NULL,
        hostname TEXT,
        department TEXT,
        user_name TEXT,
        first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (component_type, serial_number)
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_comp_reg_mac ON component_registry(mac_address);")

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

    # Cách ly an toàn: hủy mọi lệnh 'update' còn tồn đọng cho các máy v1.3.0 cũ
    cursor.execute("""
    UPDATE pending_commands
    SET status = 'cancelled'
    WHERE status = 'pending' AND command_type = 'update'
      AND mac_address IN (
          SELECT mac_address FROM computers
          WHERE COALESCE(NULLIF(client_version, ''), '1.3.0') = '1.3.0'
      )
    """)

    # Dọn các cảnh báo giả màn hình do tắt/ngủ màn hình (hoặc RDP) & WMI timeout N/A
    _restore_and_clean_false_alerts(cursor)

    # Nâng target_client_version mặc định 1.3.1 -> 1.3.2 nếu admin chưa tự đặt bản cao hơn
    cursor.execute("""
    UPDATE system_settings
    SET value = '1.3.2'
    WHERE key = 'target_client_version' AND value = '1.3.1'
    """)

    # Đồng bộ component_registry từ dữ liệu máy tính hiện có (máy online/cập nhật mới nhất giữ quyền sở hữu serial)
    _backfill_component_registry(cursor)

    conn.commit()
    conn.close()


_INVALID_HW_SERIALS = {
    "UNKNOWN", "UNDEFINED", "NONE", "NULL", "NA", "EMPTY", "OEM",
    "SERIALNUM", "SERNUM00", "DEFAULTSTRING", "TOBEFILLEDBYOEM",
    "NOTSPECIFIED", "SYSTEMSERIALNUMBER", "01234567", "12345678",
    "0123456789", "123456789", "1234567890", "ABCDEF12", "1234ABCD",
    "2012062914345300",  # Generic SD/MMC card reader firmware SN
    "MV238FHMN20",       # Generic monitor panel model reported as SN
}


def _is_valid_hardware_serial(sn: str) -> bool:
    """Xác thực serial phần cứng có tính duy nhất để truy vết tráo linh kiện."""
    raw = str(sn or "").strip()
    if not raw:
        return False
    clean = re.sub(r'[^A-Za-z0-9]', '', raw).upper()
    if len(clean) < 6 or len(set(clean)) <= 1:
        return False
    if clean in _INVALID_HW_SERIALS:
        return False
    if re.match(r'^0+000[1-9]$', clean):
        return False
    return True


def _strip_ram_sn(ram_str: str) -> str:
    """Loại bỏ [SN: ...] và chuẩn hóa khoảng trắng để so sánh tương thích v1.3.0/1.3.1 -> v1.3.2."""
    return re.sub(r'\s+', ' ', re.sub(r'\s*\[SN:\s*[^\]]+\]', '', str(ram_str or ''))).strip()


def _is_empty_card_reader_item(seg: str) -> bool:
    u = seg.upper()
    return ("- 0 GB" in u) and ("SD/MMC" in u or "GENERIC-" in u or "READER" in u or "USB DEVICE" in u)


def _split_storage_items(disk_str: str) -> Tuple[List[str], List[str]]:
    """Tách ổ cứng nội bộ và ổ cứng di động / USB (>0 GB), bỏ qua đầu đọc thẻ 0 GB."""
    raw = str(disk_str or "").strip()
    if not raw or raw == "Ổ cứng cục bộ (N/A)":
        return [], []
    internal, usb = [], []
    for part in raw.split(";"):
        seg = part.strip()
        if not seg or seg == "Ổ cứng cục bộ (N/A)" or _is_empty_card_reader_item(seg):
            continue
        if seg.startswith("[USB Di động]"):
            usb.append(seg)
        else:
            internal.append(seg)
    return internal, usb


def _extract_component_serials(
    storage_details: str,
    monitors_details: str,
    ram_details: str
) -> List[Tuple[str, str, str]]:
    """Trích xuất các cặp (loại linh kiện, SERIAL_CHUẨN, mô tả) từ chuỗi cấu hình."""
    found: List[Tuple[str, str, str]] = []
    seen = set()

    # 1. Ổ cứng nội bộ & USB Di động
    internal_disks, usb_disks = _split_storage_items(storage_details)
    for comp_label, items in (("Ổ cứng", internal_disks), ("USB Di động", usb_disks)):
        for seg in items:
            m = re.search(r'\[SN:\s*([^\]]+)\]', seg)
            if m:
                sn_raw = m.group(1).strip()
                if _is_valid_hardware_serial(sn_raw):
                    key = (comp_label, sn_raw.upper())
                    if key not in seen:
                        seen.add(key)
                        found.append((comp_label, sn_raw.upper(), seg))

    # 2. Màn hình
    mon_raw = str(monitors_details or "").strip()
    if mon_raw and not mon_raw.startswith("Không phát hiện"):
        for seg in mon_raw.split(";"):
            seg = seg.strip()
            m = re.search(r'SN:\s*([^,\)\]]+)', seg)
            if m:
                sn_raw = m.group(1).strip()
                if _is_valid_hardware_serial(sn_raw):
                    key = ("Màn hình", sn_raw.upper())
                    if key not in seen:
                        seen.add(key)
                        found.append(("Màn hình", sn_raw.upper(), seg))

    # 3. RAM (với client >= v1.3.2 có [SN: ...])
    ram_raw = str(ram_details or "").strip()
    if "->" in ram_raw:
        sticks_part = ram_raw.split("->", 1)[1]
        for seg in sticks_part.split(";"):
            seg = seg.strip()
            m = re.search(r'\[SN:\s*([^\]]+)\]', seg)
            if m:
                sn_raw = m.group(1).strip()
                if _is_valid_hardware_serial(sn_raw):
                    key = ("RAM", sn_raw.upper())
                    if key not in seen:
                        seen.add(key)
                        found.append(("RAM", sn_raw.upper(), seg))

    return found


def _restore_and_clean_false_alerts(cursor: sqlite3.Cursor):
    """Khôi phục thông số thật bị N/A ghi đè trước đó và dọn cảnh báo giả khỏi hardware_history."""
    # Khôi phục Màn hình thật nếu bị "Không phát hiện..." ghi đè trước đây
    cursor.execute("""
    SELECT h.mac_address, h.old_value
    FROM hardware_history h
    JOIN computers c ON c.mac_address = h.mac_address
    WHERE h.component = 'Màn hình'
      AND h.new_value LIKE 'Không phát hiện%'
      AND h.old_value NOT LIKE 'Không phát hiện%'
      AND (c.monitors_details IS NULL OR c.monitors_details LIKE 'Không phát hiện%')
    ORDER BY h.detected_at DESC
    """)
    restored_mon = set()
    for row in cursor.fetchall():
        mac = row["mac_address"]
        if mac not in restored_mon:
            restored_mon.add(mac)
            cursor.execute("UPDATE computers SET monitors_details = ? WHERE mac_address = ?", (row["old_value"], mac))

    # Khôi phục Ổ cứng thật nếu bị WMI timeout "Ổ cứng cục bộ (N/A)" ghi đè
    cursor.execute("""
    SELECT h.mac_address, h.old_value
    FROM hardware_history h
    JOIN computers c ON c.mac_address = h.mac_address
    WHERE h.component = 'Ổ cứng'
      AND h.new_value = 'Ổ cứng cục bộ (N/A)'
      AND h.old_value != 'Ổ cứng cục bộ (N/A)'
      AND (c.storage_details IS NULL OR c.storage_details = 'Ổ cứng cục bộ (N/A)')
    ORDER BY h.detected_at DESC
    """)
    restored_disk = set()
    for row in cursor.fetchall():
        mac = row["mac_address"]
        if mac not in restored_disk:
            restored_disk.add(mac)
            cursor.execute("UPDATE computers SET storage_details = ? WHERE mac_address = ?", (row["old_value"], mac))

    # Khôi phục chi tiết thanh RAM nếu bị WMI timeout ("-> 1.9 GB") ghi đè
    cursor.execute("""
    SELECT h.mac_address, h.old_value
    FROM hardware_history h
    JOIN computers c ON c.mac_address = h.mac_address
    WHERE h.component = 'RAM'
      AND h.old_value LIKE '%-> Thanh %'
      AND h.new_value NOT LIKE '%-> Thanh %'
      AND (c.ram_details IS NULL OR c.ram_details NOT LIKE '%-> Thanh %')
    ORDER BY h.detected_at DESC
    """)
    restored_ram = set()
    for row in cursor.fetchall():
        mac = row["mac_address"]
        if mac not in restored_ram:
            m = re.match(r'^[\d.]+\s*GB\s*\((.+)\)$', str(row["old_value"] or "").strip())
            if m:
                restored_ram.add(mac)
                cursor.execute("UPDATE computers SET ram_details = ? WHERE mac_address = ?", (m.group(1).strip(), mac))

    # Xóa các cảnh báo giả đã phát sinh trước đây
    cursor.execute("""
    DELETE FROM hardware_history
    WHERE component = 'Màn hình'
      AND (old_value LIKE 'Không phát hiện%' OR new_value LIKE 'Không phát hiện%')
    """)
    cursor.execute("""
    DELETE FROM hardware_history
    WHERE component = 'Ổ cứng'
      AND (old_value = 'Ổ cứng cục bộ (N/A)' OR new_value = 'Ổ cứng cục bộ (N/A)')
    """)
    cursor.execute("""
    DELETE FROM hardware_history
    WHERE component = 'RAM'
      AND (
          (old_value LIKE '%-> Thanh %' AND new_value NOT LIKE '%-> Thanh %')
          OR (new_value LIKE '%-> Thanh %' AND old_value NOT LIKE '%-> Thanh %')
      )
    """)
    cursor.execute("""
    UPDATE computers
    SET hardware_tampered = 0, tamper_details = ''
    WHERE hardware_tampered = 1
      AND mac_address NOT IN (SELECT DISTINCT mac_address FROM hardware_history WHERE is_acknowledged = 0)
    """)


def _backfill_component_registry(cursor: sqlite3.Cursor):
    """Đồng bộ baseline serial linh kiện từ bảng computers sang component_registry."""
    cursor.execute("""
    SELECT mac_address, hostname, department, user_name, storage_details, monitors_details, ram_details,
           COALESCE(last_seen, updated_at, created_at) AS seen_ts
    FROM computers
    ORDER BY seen_ts ASC
    """)
    for row in cursor.fetchall():
        serials = _extract_component_serials(
            row["storage_details"], row["monitors_details"], row["ram_details"]
        )
        seen_ts = row["seen_ts"] or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for comp_type, sn_upper, desc in serials:
            cursor.execute("""
            INSERT INTO component_registry (
                component_type, serial_number, component_desc,
                mac_address, hostname, department, user_name, first_seen, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(component_type, serial_number) DO UPDATE SET
                component_desc = excluded.component_desc,
                mac_address = excluded.mac_address,
                hostname = excluded.hostname,
                department = excluded.department,
                user_name = excluded.user_name,
                updated_at = excluded.updated_at
            """, (
                comp_type, sn_upper, desc,
                row["mac_address"], row["hostname"], row["department"], row["user_name"],
                seen_ts, seen_ts
            ))


def _is_same_physical_machine_alias(
    cursor: sqlite3.Cursor,
    other_mac: str,
    hostname: str,
    mainboard: str,
    current_serials: List[Tuple[str, str, str]]
) -> bool:
    """Tránh báo nhầm khi 1 máy vật lý đổi qua card mạng khác (VD: LAN <-> Wi-Fi/USB tethering)."""
    h_cur = str(hostname or "").strip().upper()
    mb_cur = str(mainboard or "").strip().upper()
    if not h_cur or not mb_cur:
        return False

    cursor.execute("""
    SELECT hostname, mainboard_info, storage_details, monitors_details, ram_details
    FROM computers WHERE mac_address = ?
    """, (other_mac,))
    other = cursor.fetchone()
    if not other:
        return False

    if str(other["hostname"] or "").strip().upper() != h_cur:
        return False
    if str(other["mainboard_info"] or "").strip().upper() != mb_cur:
        return False

    other_serials = {
        (ct, sn)
        for ct, sn, _ in _extract_component_serials(
            other["storage_details"], other["monitors_details"], other["ram_details"]
        )
    }
    shared_types = {ct for ct, sn, _ in current_serials if (ct, sn) in other_serials}
    return len(shared_types) >= 2


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

        # So sánh RAM (bỏ qua nếu rớt WMI timeout mất chi tiết thanh RAM hoặc nâng cấp v1.3.2 thêm [SN:])
        old_ram = str(existing["ram_details"] or "").strip()
        new_ram = str(data.get("ram_details") or "").strip()
        old_ram_gb = float(existing["ram_total_gb"] or 0)
        new_ram_gb = float(data.get("ram_total_gb") or 0)
        old_has_sticks = "-> Thanh " in old_ram
        new_has_sticks = "-> Thanh " in new_ram
        same_gb = abs(old_ram_gb - new_ram_gb) < 0.8

        if old_has_sticks and not new_has_sticks and same_gb:
            # WMI timeout mất chi tiết thanh -> giữ nguyên dữ liệu cũ, không báo giả
            data["ram_details"] = old_ram
            if old_ram_gb > 0:
                data["ram_total_gb"] = old_ram_gb
        elif not old_has_sticks and new_has_sticks and same_gb:
            # Máy cũ trước đó bị thiếu chi tiết thanh, nay quét đủ -> cập nhật êm
            pass
        elif "[SN:" not in old_ram and "[SN:" in new_ram and _strip_ram_sn(old_ram) == _strip_ram_sn(new_ram) and same_gb:
            # Nâng cấp client lên v1.3.2 bổ sung Serial RAM lần đầu -> cập nhật êm
            pass
        elif (old_ram and new_ram and old_ram != new_ram) or (old_ram_gb > 0 and new_ram_gb > 0 and not same_gb):
            changes.append(("RAM", f"{old_ram_gb} GB ({old_ram})", f"{new_ram_gb} GB ({new_ram})"))

        # So sánh Ổ cứng nội bộ và Ổ cứng di động / USB tách biệt
        old_disk = str(existing["storage_details"] or "").strip()
        new_disk = str(data.get("storage_details") or "").strip()
        if (not new_disk or new_disk == "Ổ cứng cục bộ (N/A)") and old_disk and old_disk != "Ổ cứng cục bộ (N/A)":
            # WMI timeout trả về N/A -> giữ lại ổ cứng thật cũ, không báo giả
            data["storage_details"] = old_disk
        elif old_disk == "Ổ cứng cục bộ (N/A)" and new_disk and new_disk != "Ổ cứng cục bộ (N/A)":
            # Khôi phục từ N/A trước đó -> cập nhật êm
            pass
        elif old_disk and new_disk and old_disk != new_disk:
            old_internal, old_usb = _split_storage_items(old_disk)
            new_internal, new_usb = _split_storage_items(new_disk)
            if old_internal and new_internal and old_internal != new_internal:
                changes.append(("Ổ cứng", "; ".join(old_internal), "; ".join(new_internal)))
            if old_usb != new_usb:
                cursor.execute("""
                INSERT INTO hardware_history (mac_address, hostname, department, user_name, component, old_value, new_value, detected_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    mac_clean,
                    data.get("hostname", "") or existing["hostname"],
                    data.get("department", "") or existing["department"],
                    data.get("user_name", "") or existing["user_name"],
                    "Ổ cứng di động / USB",
                    "; ".join(old_usb) if old_usb else "Không gắn USB / Ổ di động",
                    "; ".join(new_usb) if new_usb else "Đã tháo USB / Ổ di động",
                    now_str
                ))

        # So sánh CPU
        old_cpu = str(existing["cpu_info"] or "").strip()
        new_cpu = str(data.get("cpu_info") or "").strip()
        if old_cpu and new_cpu and old_cpu != new_cpu:
            changes.append(("CPU", old_cpu, new_cpu))

        # So sánh Màn hình (bỏ qua nếu một trong hai vế là "Không phát hiện..." do tắt màn hình / ngủ / RDP)
        old_mon = str(existing["monitors_details"] or "").strip()
        new_mon = str(data.get("monitors_details") or "").strip()
        old_mon_real = bool(old_mon) and not old_mon.startswith("Không phát hiện")
        new_mon_real = bool(new_mon) and not new_mon.startswith("Không phát hiện")
        if old_mon_real and new_mon_real and old_mon != new_mon:
            changes.append(("Màn hình", old_mon, new_mon))
        elif old_mon_real and not new_mon_real:
            # Giữ lại thông tin màn hình thật cũ thay vì ghi đè bằng "Không phát hiện..."
            data["monitors_details"] = old_mon

    # 1b. Truy vết chéo Serial linh kiện giữa các máy tính (Bắt tận tay cắm từ máy A sang máy B)
    boot_time = data.get("boot_time", "")
    logged_in_user = data.get("logged_in_user", "")
    dept = data.get("department", "") or (existing["department"] if existing else "")
    u_name = data.get("user_name", "") or (existing["user_name"] if existing else "")
    h_name = data.get("hostname", "") or (existing["hostname"] if existing else "")
    mb_info = data.get("mainboard_info", "") or (existing["mainboard_info"] if existing else "")
    current_serials = _extract_component_serials(
        data.get("storage_details", ""),
        data.get("monitors_details", ""),
        data.get("ram_details", "")
    )
    for comp_type, sn_upper, desc in current_serials:
        cursor.execute("""
        SELECT mac_address, hostname, department, user_name, component_desc
        FROM component_registry
        WHERE component_type = ? AND serial_number = ?
        """, (comp_type, sn_upper))
        owner = cursor.fetchone()
        if owner and owner["mac_address"] != mac_clean:
            if not _is_same_physical_machine_alias(cursor, owner["mac_address"], h_name, mb_info, current_serials):
                prev_host = owner["hostname"] or owner["mac_address"]
                prev_dept = owner["department"] or "Chưa rõ khoa"
                prev_user = owner["user_name"] or owner["mac_address"]
                prev_desc = owner["component_desc"] or f"SN: {sn_upper}"
                changes.append((
                    f"Tráo chéo {comp_type}",
                    f"Từ máy {prev_host} [{prev_dept} - {prev_user}] | {prev_desc}",
                    f"Cắm sang {h_name or mac_clean} [{dept or 'Chưa rõ khoa'} - {u_name or mac_clean}] | {desc}"
                ))
        cursor.execute("""
        INSERT INTO component_registry (
            component_type, serial_number, component_desc,
            mac_address, hostname, department, user_name, first_seen, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(component_type, serial_number) DO UPDATE SET
            component_desc = excluded.component_desc,
            mac_address = excluded.mac_address,
            hostname = excluded.hostname,
            department = excluded.department,
            user_name = excluded.user_name,
            updated_at = excluded.updated_at
        """, (comp_type, sn_upper, desc, mac_clean, h_name, dept, u_name, now_str, now_str))

    if changes:
        hardware_tampered = 1
        tamper_details = "; ".join([f"{c[0]}: Cũ [{c[1]}] -> Mới [{c[2]}]" for c in changes])
        for comp, old_val, new_val in changes:
            cursor.execute("""
            INSERT INTO hardware_history (mac_address, hostname, department, user_name, component, old_value, new_value, detected_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                mac_clean,
                h_name,
                dept,
                u_name,
                comp,
                old_val,
                new_val,
                now_str
            ))

    # 2. Ghi nhận sự kiện khởi động máy vào power_logs

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

    cursor.execute("SELECT value FROM system_settings WHERE key = 'target_client_version'")
    trow = cursor.fetchone()
    latest_ver = (trow["value"] if trow and trow["value"] else "1.3.2").strip()

    cursor.execute("""
    SELECT COALESCE(NULLIF(client_version, ''), '1.3.0') AS version, COUNT(*) AS count
    FROM computers
    GROUP BY version
    ORDER BY version DESC
    """)
    version_summary = [dict(r) for r in cursor.fetchall()]
    latest_version_pcs = sum(v["count"] for v in version_summary if v["version"] == latest_ver)
    outdated_pcs = total - latest_version_pcs

    conn.close()

    standard_ratio = round((ssd_pcs / total * 100), 1) if total > 0 else 0

    return {
        "total_pcs": total,
        "online_pcs": online_pcs,
        "suspect_av_pcs": suspect_av_pcs,
        "offline_pcs": offline_pcs,
        "latest_client_version": latest_ver,
        "latest_version_pcs": latest_version_pcs,
        "outdated_pcs": outdated_pcs,
        "version_summary": version_summary,
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


def record_heartbeat(mac_address: str, ip_address: str, logged_in_user: str = "", uptime_hours: float = 0, boot_time: str = "", client_version: str = ""):
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
        client_version = COALESCE(NULLIF(:client_version, ''), client_version),
        ip_address = COALESCE(NULLIF(:ip_address, ''), ip_address),
        logged_in_user = COALESCE(NULLIF(:logged_in_user, ''), logged_in_user),
        boot_time = COALESCE(NULLIF(:boot_time, ''), boot_time)
    WHERE mac_address = :mac
    """, {
        "now_str": now_str,
        "client_version": client_version,
        "ip_address": ip_address,
        "logged_in_user": logged_in_user,
        "boot_time": boot_time,
        "mac": mac_address.upper()
    })
    conn.commit()
    conn.close()


def get_setting(key: str, default: str = "") -> str:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM system_settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row["value"] if row and row["value"] is not None else default


def set_setting(key: str, value: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
    INSERT INTO system_settings (key, value, updated_at)
    VALUES (?, ?, ?)
    ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
    """, (key, value, now_str))
    conn.commit()
    conn.close()


def is_auto_updatable_version(ver: str) -> bool:
    """Chỉ cho phép tự động update từ xa đối với client phiên bản >= 1.3.1 (cách ly v1.3.0)."""
    v = (ver or "").strip().lstrip("vV")
    if not v or v == "1.3.0":
        return False
    try:
        parts = tuple(int(x) for x in v.split(".")[:3])
        return parts >= (1, 3, 1)
    except Exception:
        return False


def get_outdated_computers(target_version: str) -> List[Dict[str, Any]]:
    """Lấy danh sách các máy >= 1.3.1 có client_version khác với phiên bản mục tiêu."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT mac_address, ip_address, hostname, client_agent_port, client_version, is_online
    FROM computers
    WHERE COALESCE(NULLIF(client_version, ''), '1.3.0') != ?
    """, (target_version,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return [r for r in rows if is_auto_updatable_version(r.get("client_version", ""))]


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
    """Xác nhận đã xử lý cảnh báo phần cứng và gỡ cờ đỏ trên máy nếu không còn cảnh báo mới."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT mac_address FROM hardware_history WHERE id = ?", (alert_id,))
    row = cursor.fetchone()
    cursor.execute("UPDATE hardware_history SET is_acknowledged = 1 WHERE id = ?", (alert_id,))
    if row:
        mac = row["mac_address"]
        cursor.execute("SELECT 1 FROM hardware_history WHERE mac_address = ? AND is_acknowledged = 0 LIMIT 1", (mac,))
        if not cursor.fetchone():
            cursor.execute("UPDATE computers SET hardware_tampered = 0, tamper_details = '' WHERE mac_address = ?", (mac,))
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

