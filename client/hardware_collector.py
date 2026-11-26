import ctypes
from ctypes import wintypes
import math
import os
import platform
import re
import socket
import subprocess
import winreg
import json
import time
from typing import Dict, List, Any

# Bảng mã nhà sản xuất màn hình PNP ID
PNP_MANUFACTURERS = {
    'DEL': 'Dell', 'SAM': 'Samsung', 'LGD': 'LG Display', 'GSM': 'LG Electronics',
    'ACR': 'Acer', 'AOC': 'AOC', 'ASU': 'ASUS', 'BEN': 'BenQ', 'HPN': 'HP', 'HWP': 'HP',
    'LEN': 'Lenovo', 'PHL': 'Philips', 'SNY': 'Sony', 'VSC': 'ViewSonic',
    'AUO': 'AU Optronics', 'BOE': 'BOE', 'CMO': 'Chi Mei (Innolux)', 'IVM': 'Iiyama',
    'NEC': 'NEC', 'MSI': 'MSI', 'GGL': 'Google', 'SEC': 'Samsung', 'EIZ': 'EIZO',
    'HAY': 'Hikvision', 'DAH': 'Dahua'
}

# Bảng mã nhà sản xuất RAM chuẩn JEDEC
JEDEC_RAM_MANUFACTURERS = {
    '0198': 'Kingston', '02FE': 'Micron / Crucial', '00CE': 'Samsung', '014F': 'Transcend',
    '029E': 'Corsair', '04CB': 'A-DATA', '059B': 'Crucial', '04CD': 'G.Skill',
    '02C7': 'Team Group', '00AD': 'SK Hynix', '80AD': 'SK Hynix', '80CE': 'Samsung', '802C': 'Micron'
}


def estimate_cpu_launch_year(cpu_name: str) -> str:
    name_clean = cpu_name.strip()
    m = re.search(r'i[3579]-(\d{1,2})\d{2,3}', name_clean, re.IGNORECASE)
    if m:
        gen = int(m.group(1))
        intel_gen_years = {
            2: "2011", 3: "2012", 4: "2013-2014", 5: "2015", 6: "2015-2016",
            7: "2017", 8: "2017-2018", 9: "2018-2019", 10: "2020",
            11: "2020-2021", 12: "2021-2022", 13: "2022-2023", 14: "2023-2024"
        }
        return intel_gen_years.get(gen, f"Gen {gen}")

    if re.search(r'i[3579]-\d{3}\b', name_clean, re.IGNORECASE): return "2010"
    if "core(tm)2" in name_clean.lower(): return "2006-2009"
    if re.search(r'G20\d\d', name_clean, re.IGNORECASE): return "2013"
    if re.search(r'G32\d\d|G34\d\d', name_clean, re.IGNORECASE): return "2014"
    if re.search(r'G44\d\d|G45\d\d', name_clean, re.IGNORECASE): return "2015-2016"
    if re.search(r'G54\d\d|G55\d\d', name_clean, re.IGNORECASE): return "2018-2019"
    if re.search(r'G64\d\d', name_clean, re.IGNORECASE): return "2020"

    m_ryzen = re.search(r'Ryzen\s*\d\s*(\d)\d{3}', name_clean, re.IGNORECASE)
    if m_ryzen:
        series = int(m_ryzen.group(1))
        ryzen_years = {
            1: "2017", 2: "2018", 3: "2019", 4: "2020", 5: "2020-2021",
            7: "2022-2023", 8: "2024", 9: "2024"
        }
        return ryzen_years.get(series, f"Ryzen {series}000")

    return "N/A"


def get_cpu_info() -> str:
    cpu_name = "Unknown CPU"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
            val, _ = winreg.QueryValueEx(key, "ProcessorNameString")
            cpu_name = " ".join(val.split())
    except Exception:
        cpu_name = platform.processor() or "Unknown CPU"

    threads = os.cpu_count() or 1
    launch_year = estimate_cpu_launch_year(cpu_name)
    year_str = f", Năm SX/Ra mắt: {launch_year}" if launch_year != "N/A" else ""
    return f"{cpu_name} ({threads} Threads{year_str})"


def get_mainboard_info() -> str:
    vendor = "Unknown"
    product = "Unknown"
    bios_date = "Unknown"
    mfg_year = ""

    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\BIOS") as key:
            try:
                vendor, _ = winreg.QueryValueEx(key, "BaseBoardManufacturer")
                vendor = vendor.strip()
            except Exception: pass
            try:
                product, _ = winreg.QueryValueEx(key, "BaseBoardProduct")
                product = product.strip()
            except Exception: pass
            try:
                bios_date, _ = winreg.QueryValueEx(key, "BIOSReleaseDate")
                bios_date = bios_date.strip()
                m_year = re.search(r'20\d{2}|19\d{2}', bios_date)
                if m_year:
                    mfg_year = m_year.group(0)
            except Exception: pass
    except Exception: pass

    summary = f"{vendor} {product}"
    if mfg_year:
        summary += f" (Năm SX/BIOS: {mfg_year})"
    elif bios_date != "Unknown":
        summary += f" (BIOS: {bios_date})"
    return summary


def parse_edid(edid_bytes: bytes) -> Dict[str, Any]:
    if not edid_bytes or len(edid_bytes) < 128:
        return None

    b8, b9 = edid_bytes[8], edid_bytes[9]
    c1 = chr(((b8 >> 2) & 0x1F) + 64)
    c2 = chr((((b8 & 0x03) << 3) | ((b9 >> 5) & 0x07)) + 64)
    c3 = chr((b9 & 0x1F) + 64)
    pnp_id = f"{c1}{c2}{c3}"
    brand = PNP_MANUFACTURERS.get(pnp_id, pnp_id)

    mfg_week = edid_bytes[16]
    mfg_year = 1990 + edid_bytes[17] if edid_bytes[17] > 0 else 0

    w_cm = edid_bytes[21]
    h_cm = edid_bytes[22]
    size_inch = 0.0
    if w_cm > 0 and h_cm > 0:
        diag_cm = math.sqrt(w_cm ** 2 + h_cm ** 2)
        size_inch = round(diag_cm / 2.54, 1)

    model = ""
    serial = ""
    for offset in (54, 72, 90, 108):
        block = edid_bytes[offset:offset+18]
        if block[:3] == b'\x00\x00\x00':
            desc_type = block[3]
            if desc_type == 0xFC:
                model = block[5:].decode('ascii', errors='ignore').strip('\x00\r\n ')
            elif desc_type == 0xFF:
                serial = block[5:].decode('ascii', errors='ignore').strip('\x00\r\n ')

    return {
        "brand": brand,
        "model": model or pnp_id,
        "size_inch": size_inch,
        "mfg_year": mfg_year,
        "mfg_week": mfg_week,
        "serial": serial
    }


def get_monitors_info() -> str:
    class DISPLAY_DEVICE(ctypes.Structure):
        _fields_ = [
            ('cb', wintypes.DWORD),
            ('DeviceName', wintypes.WCHAR * 32),
            ('DeviceString', wintypes.WCHAR * 128),
            ('StateFlags', wintypes.DWORD),
            ('DeviceID', wintypes.WCHAR * 128),
            ('DeviceKey', wintypes.WCHAR * 128),
        ]

    user32 = ctypes.windll.user32
    dev = DISPLAY_DEVICE()
    dev.cb = ctypes.sizeof(DISPLAY_DEVICE)
    mon = DISPLAY_DEVICE()
    mon.cb = ctypes.sizeof(DISPLAY_DEVICE)

    monitors = []
    i = 0
    while user32.EnumDisplayDevicesW(None, i, ctypes.byref(dev), 0):
        if dev.StateFlags & 0x00000001:
            j = 0
            while user32.EnumDisplayDevicesW(dev.DeviceName, j, ctypes.byref(mon), 0):
                if mon.StateFlags & 0x00000001:
                    parts = mon.DeviceID.split('\\')
                    if len(parts) >= 2:
                        hw_id = parts[1]
                        try:
                            disp_path = f"SYSTEM\\CurrentControlSet\\Enum\\DISPLAY\\{hw_id}"
                            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, disp_path) as k:
                                for sub_idx in range(winreg.QueryInfoKey(k)[0]):
                                    sub_k_name = winreg.EnumKey(k, sub_idx)
                                    param_path = f"{disp_path}\\{sub_k_name}\\Device Parameters"
                                    try:
                                        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, param_path) as pk:
                                            edid, _ = winreg.QueryValueEx(pk, 'EDID')
                                            info = parse_edid(edid)
                                            if info:
                                                monitors.append(info)
                                                break
                                    except Exception: pass
                        except Exception: pass
                j += 1
        i += 1

    if not monitors:
        return "Không phát hiện màn hình ngoài (Hoặc dùng màn hình tích hợp)"

    items = []
    for idx, m in enumerate(monitors, 1):
        brand = m.get('brand', '')
        model = m.get('model', '')
        size = m.get('size_inch', 0)
        size_str = f"{size} inch" if size > 0 else "N/A"
        mfg_year = m.get('mfg_year', 0)
        year_str = f", Năm SX: {mfg_year}" if mfg_year > 1990 else ""
        serial = m.get('serial', '')
        sn_str = f", SN: {serial}" if serial else ""
        items.append(f"Màn {idx}: {brand} {model} ({size_str}{year_str}{sn_str})")

    return "; ".join(items)


def query_wmi_via_cmd() -> Dict[str, Any]:
    """Fallback dùng Command Prompt (wmic) hoàn toàn ẩn khi máy trạm không có hoặc bị cấm PowerShell."""
    CREATE_NO_WINDOW = 0x08000000
    data = {"Rams": [], "RamSlots": 2, "Disks": [], "Net": [], "Keyboards": [], "Mice": []}
    try:
        # 1. RAM qua WMIC
        res = subprocess.run(
            ["cmd.exe", "/c", "wmic memorychip get DeviceLocator,Capacity,Speed,Manufacturer,PartNumber /format:csv"],
            capture_output=True, text=True, timeout=5, creationflags=CREATE_NO_WINDOW
        )
        if res.returncode == 0 and res.stdout.strip():
            lines = [l.strip() for l in res.stdout.strip().splitlines() if l.strip()]
            if len(lines) > 1:
                headers = [h.strip() for h in lines[0].split(",")]
                for line in lines[1:]:
                    parts = line.split(",")
                    if len(parts) >= len(headers):
                        data["Rams"].append(dict(zip(headers, [p.strip() for p in parts])))

        # 2. Ổ cứng qua WMIC
        res_disk = subprocess.run(
            ["cmd.exe", "/c", "wmic diskdrive get Model,MediaType,InterfaceType,Size,SerialNumber /format:csv"],
            capture_output=True, text=True, timeout=5, creationflags=CREATE_NO_WINDOW
        )
        if res_disk.returncode == 0 and res_disk.stdout.strip():
            lines = [l.strip() for l in res_disk.stdout.strip().splitlines() if l.strip()]
            if len(lines) > 1:
                headers = [h.strip() for h in lines[0].split(",")]
                for line in lines[1:]:
                    parts = line.split(",")
                    if len(parts) >= len(headers):
                        data["Disks"].append(dict(zip(headers, [p.strip() for p in parts])))

        # 3. Card mạng qua WMIC
        res_net = subprocess.run(
            ["cmd.exe", "/c", "wmic nicconfig where IPEnabled=True get Description,IPAddress,MACAddress /format:csv"],
            capture_output=True, text=True, timeout=5, creationflags=CREATE_NO_WINDOW
        )
        if res_net.returncode == 0 and res_net.stdout.strip():
            lines = [l.strip() for l in res_net.stdout.strip().splitlines() if l.strip()]
            if len(lines) > 1:
                headers = [h.strip() for h in lines[0].split(",")]
                for line in lines[1:]:
                    parts = line.split(",")
                    if len(parts) >= len(headers):
                        data["Net"].append(dict(zip(headers, [p.strip() for p in parts])))
    except Exception:
        pass
    return data


def get_combined_wmi_data() -> Dict[str, Any]:
    """Truy vấn siêu tốc các thông số WMI bằng PowerShell ẩn 100%, tự động fallback Command Prompt."""
    CREATE_NO_WINDOW = 0x08000000
    ps_script = """
    $rams = @(Get-CimInstance Win32_PhysicalMemory -ErrorAction SilentlyContinue | Select-Object DeviceLocator, Capacity, Speed, Manufacturer, PartNumber)
    $ramSlots = (Get-CimInstance Win32_PhysicalMemoryArray -ErrorAction SilentlyContinue | Select-Object -First 1).MemoryDevices
    $disks = @(Get-CimInstance Win32_DiskDrive -ErrorAction SilentlyContinue | Select-Object Model, MediaType, InterfaceType, Size, SerialNumber)
    $net = @(Get-CimInstance Win32_NetworkAdapterConfiguration -Filter 'IPEnabled=True' -ErrorAction SilentlyContinue | Select-Object Description, IPAddress, MACAddress)
    $kbs = @(Get-CimInstance Win32_Keyboard -ErrorAction SilentlyContinue | ForEach-Object { if ($_.Description) { $_.Description } else { $_.Name } })
    $mice = @(Get-CimInstance Win32_PointingDevice -ErrorAction SilentlyContinue | ForEach-Object { if ($_.Description) { $_.Description } else { $_.Name } })

    [PSCustomObject]@{
        Rams = $rams
        RamSlots = $ramSlots
        Disks = $disks
        Net = $net
        Keyboards = $kbs
        Mice = $mice
    } | ConvertTo-Json -Depth 3
    """

    data = {}
    try:
        # Gọi PowerShell với WindowStyle Hidden và CREATE_NO_WINDOW (tuyệt đối không hiện cửa sổ)
        res = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
            capture_output=True, text=True, timeout=5,
            creationflags=CREATE_NO_WINDOW
        )
        if res.returncode == 0 and res.stdout.strip():
            data = json.loads(res.stdout)
    except Exception:
        pass

    # Nếu máy không có PowerShell hoặc PowerShell bị lỗi -> Gọi fallback Command Prompt (wmic)
    if not data or not data.get("Disks"):
        cmd_data = query_wmi_via_cmd()
        if cmd_data:
            if not data:
                data = cmd_data
            else:
                for k, v in cmd_data.items():
                    if not data.get(k):
                        data[k] = v

    return data


def format_ram_data(wmi_data: dict) -> Dict[str, Any]:
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ('dwLength', ctypes.c_ulong), ('dwMemoryLoad', ctypes.c_ulong),
            ('ullTotalPhys', ctypes.c_ulonglong), ('ullAvailPhys', ctypes.c_ulonglong),
            ('ullTotalPageFile', ctypes.c_ulonglong), ('ullAvailPageFile', ctypes.c_ulonglong),
            ('ullTotalVirtual', ctypes.c_ulonglong), ('ullAvailVirtual', ctypes.c_ulonglong),
            ('ullAvailExtendedVirtual', ctypes.c_ulonglong),
        ]
    stat = MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
    total_gb = round(stat.ullTotalPhys / (1024 ** 3), 1)

    rams = wmi_data.get("Rams", [])
    if isinstance(rams, dict):
        rams = [rams]
    ram_count = len(rams) if rams else 1
    ram_slots = wmi_data.get("RamSlots", 2) or 2

    stick_details = []
    for idx, r in enumerate(rams, 1):
        raw_mfg = str(r.get("Manufacturer", "")).strip()
        mfg = raw_mfg
        for code, brand_name in JEDEC_RAM_MANUFACTURERS.items():
            if raw_mfg.upper().startswith(code):
                mfg = brand_name
                break
        cap_gb = round(int(r.get("Capacity", 0) or 0) / (1024 ** 3))
        speed = r.get("Speed", "")
        speed_str = f" {speed}MHz" if speed else ""
        pn = str(r.get("PartNumber", "")).strip()
        pn_str = f" ({pn})" if pn else ""
        loc = r.get("DeviceLocator", f"DIMM {idx}")
        stick_details.append(f"Thanh {idx} [{loc}]: {mfg} {cap_gb}GB{speed_str}{pn_str}")

    slots_summary = f"ĐANG CẮM {ram_count} THANH (Tổng {total_gb} GB)"
    if ram_slots and ram_slots >= ram_count:
        slots_summary += f" / Tổng {ram_slots} khe cắm"
        empty_slots = ram_slots - ram_count
        if empty_slots > 0:
            slots_summary += f" (Còn trống {empty_slots} khe)"

    full_detail = f"{slots_summary} -> {'; '.join(stick_details) if stick_details else f'{total_gb} GB'}"
    return {
        "total_gb": total_gb,
        "ram_count": ram_count,
        "ram_slots": ram_slots,
        "detail": full_detail
    }


def format_disks_data(wmi_data: dict) -> str:
    disks = wmi_data.get("Disks", [])
    if isinstance(disks, dict):
        disks = [disks]
    if not disks:
        return "Ổ cứng cục bộ (N/A)"

    items = []
    for d in disks:
        model = str(d.get('Model') or d.get('FriendlyName') or '').strip()
        media = str(d.get('MediaType', '')).strip()
        bus = str(d.get('InterfaceType') or d.get('BusType') or '').strip()
        sn = str(d.get('SerialNumber', '')).strip()
        raw_size = int(d.get('Size', 0) or 0)
        size_gb = round(raw_size / (1000 ** 3))

        if 'NVME' in bus.upper() or 'NVME' in model.upper():
            type_label = 'SSD NVMe'
        elif 'SSD' in model.upper() or 'SOLID STATE' in media.upper():
            type_label = 'SSD'
        elif 'HDD' in model.upper() or 'HARD DISK' in media.upper():
            type_label = 'HDD'
        else:
            type_label = 'SSD/HDD'

        sn_str = f" [SN: {sn}]" if sn else ""
        items.append(f"[{type_label}] {model} - {size_gb} GB{sn_str}")

    return "; ".join(items)


def format_peripherals(wmi_data: dict) -> Dict[str, str]:
    kbs = wmi_data.get("Keyboards", [])
    if isinstance(kbs, str): kbs = [kbs]
    mice = wmi_data.get("Mice", [])
    if isinstance(mice, str): mice = [mice]

    clean_kbs = list(set([k.strip() for k in kbs if k and "terminal" not in k.lower()]))
    clean_mice = list(set([m.strip() for m in mice if m and "terminal" not in m.lower()]))

    kb_str = ", ".join(clean_kbs) if clean_kbs else "Bàn phím tiêu chuẩn (Standard Keyboard)"
    mouse_str = ", ".join(clean_mice) if clean_mice else "Chuột quang tiêu chuẩn (Optical Mouse)"

    return {
        "keyboard": kb_str,
        "mouse": mouse_str,
        "summary": f"Bàn phím: {kb_str} | Chuột: {mouse_str}"
    }


def get_network_info(wmi_data: dict) -> Dict[str, str]:
    net_list = wmi_data.get("Net", [])
    if isinstance(net_list, dict):
        net_list = [net_list]

    ip_address = ""
    mac_address = ""
    for net in net_list:
        ips = net.get("IPAddress") or []
        if isinstance(ips, str):
            ips = [ips]
        valid_ips = [ip for ip in ips if ":" not in ip and not ip.startswith("127.") and not ip.startswith("169.254.")]
        if valid_ips and not ip_address:
            ip_address = valid_ips[0]
            mac_address = net.get("MACAddress", "")
            break

    if not ip_address:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip_address = s.getsockname()[0]
            s.close()
        except Exception:
            ip_address = socket.gethostbyname(socket.gethostname()) or "127.0.0.1"

    if not mac_address:
        import uuid
        mac_num = uuid.getnode()
        mac_address = ':'.join(re.findall('..', '%012X' % mac_num))

    return {
        "ip_address": ip_address,
        "mac_address": mac_address
    }


def get_os_info() -> str:
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion") as key:
            prod_name, _ = winreg.QueryValueEx(key, "ProductName")
            display_version = ""
            try:
                display_version, _ = winreg.QueryValueEx(key, "DisplayVersion")
            except Exception: pass
            build_num, _ = winreg.QueryValueEx(key, "CurrentBuild")
            arch = "64-bit" if platform.machine().endswith('64') else "32-bit"
            ver_part = f" {display_version}" if display_version else ""
            return f"{prod_name}{ver_part} {arch} (Build {build_num})"
    except Exception:
        return f"{platform.system()} {platform.release()}"


def collect_all_hardware_info() -> Dict[str, Any]:
    hostname = socket.gethostname()
    os_info = get_os_info()
    mainboard_info = get_mainboard_info()
    cpu_info = get_cpu_info()
    monitors_info = get_monitors_info()

    wmi_data = get_combined_wmi_data()
    ram_data = format_ram_data(wmi_data)
    storage_info = format_disks_data(wmi_data)
    periph_data = format_peripherals(wmi_data)
    net_data = get_network_info(wmi_data)

    return {
        "hostname": hostname,
        "os_name": os_info,
        "mainboard_info": mainboard_info,
        "cpu_info": cpu_info,
        "ram_total_gb": ram_data["total_gb"],
        "ram_sticks_count": ram_data["ram_count"],
        "ram_slots_total": ram_data["ram_slots"],
        "ram_details": ram_data["detail"],
        "storage_details": storage_info,
        "monitors_details": monitors_info,
        "keyboard_info": periph_data["keyboard"],
        "mouse_info": periph_data["mouse"],
        "peripherals_details": periph_data["summary"],
        "ip_address": net_data["ip_address"],
        "mac_address": net_data["mac_address"],
    }


if __name__ == "__main__":
    t0 = time.time()
    info = collect_all_hardware_info()
    t1 = time.time()
    print(f"Total collect time: {t1 - t0:.2f} seconds")
    print(json.dumps(info, indent=2, ensure_ascii=False))
