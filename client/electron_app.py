"""
electron_app.py
Giao diện chuẩn Electron (Chromium / Edge WebView2) phong cách Underground Hacker Cyberpunk:
- Vừa load lên là AUTO GET INFO VÀ VIEW LÊN MÀN HÌNH NGAY LẬP TỨC (Preloaded 0.00s delay).
- Lấy đầy đủ: Mainboard, CPU, Màn hình, Ổ cứng SSD/HDD, SỐ THANH RAM CẮM, BÀN PHÍM, CHUỘT, IP, MAC.
- Ô chọn KHOA/PHÒNG BAN: LOAD SẴN TOÀN BỘ 39 KHOA VIỆN RA MÀN HÌNH dạng danh sách chọn trực tiếp (kèm ô tìm kiếm gõ lọc siêu tốc không dấu / có dấu).
- Ô nhập MÃ VẠCH TÀI SẢN (Barcode) tự động focus sẵn sàng cho súng quét.
- Duy nhất 1 nút "SAVE" để import vào CSDL SQLite.
"""

import html
import json
import os
import sys
import threading
import urllib.request
import urllib.error
import sqlite3
import traceback
from datetime import datetime
import webview

import hardware_collector

# Đường dẫn thư mục chạy app (nếu đóng gói exe thì là thư mục chứa exe)
if getattr(sys, 'frozen', False):
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE = os.path.join(APP_DIR, "config.json")
LOCAL_DB_FILE = os.path.join(APP_DIR, "inventory_local.db")
LOG_FILE = os.path.join(APP_DIR, "in4_error.log")
DEFAULT_SERVER_URL = "http://10.10.12.188:8000"


def log_error(msg: str):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass


def excepthook(exc_type, exc_value, exc_tb):
    tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    log_error(f"UNHANDLED EXCEPTION:\n{tb_text}")
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, f"Đã xảy ra lỗi:\n{exc_value}\n\nXem chi tiết tại in4_error.log", "IN4.EXE ERROR", 0x10)
    except Exception:
        pass


sys.excepthook = excepthook

# Danh sách chuẩn Khoa / Phòng ban của Bệnh viện
OFFICIAL_DEPARTMENTS = [
    "Phòng CNTT",
    "Kho tổng",
    "Răng hàm mặt",
    "Tai mũi họng",
    "Mắt",
    "Khoa Huyết học và Truyền máu",
    "Khoa SHVS và Sinh học phân tử",
    "Trung tâm Sàng lọc trước sinh",
    "Khoa CDHA",
    "Khoa Dinh dưỡng",
    "Tự chọn Ngoại tổng hợp",
    "Tự chọn ngoại tiết niệu",
    "HSCC",
    "HSTC",
    "Thận NT",
    "Nhi",
    "GMHS",
    "HTSS",
    "Phòng Tổ chức Hành Chính",
    "Khoa Nội tim mạch",
    "Khoa Nội tổng hợp",
    "Khoa Nội Cơ xương khớp",
    "Khoa Nội bảo vệ sức khỏe",
    "Khoa Dược",
    "Phòng Vật tư",
    "Phòng kế toán tài chính",
    "Phòng Kế hoạch tổng hợp",
    "Phòng QLCL & CTXH",
    "Phòng Đào tạo chỉ đạo tuyến",
    "Khoa Ngoại tổng hợp",
    "Khoa Ngoại chấn thương",
    "Khoa Ngoại thận tiết niệu",
    "Khoa Truyền nhiễm",
    "Khoa Giải phẫu bệnh",
    "Khoa Khám Bệnh",
    "Chống nhiễm khuẩn",
    "Khoa Ung bướu",
    "Khoa Sản",
    "Khoa Phụ",
    "Khoa Đông Y",
    "Khoa Da liễu"
]


def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log_error(f"Lỗi đọc config.json: {e}")
    if getattr(sys, 'frozen', False):
        bundled_config = os.path.join(getattr(sys, '_MEIPASS', ''), "config.json")
        if os.path.exists(bundled_config):
            try:
                with open(bundled_config, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    return {"server_url": DEFAULT_SERVER_URL}


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>IN4 // SYSTEM RECON & HARVESTER</title>
    <link rel="icon" type="image/png" href="data:image/png;base64,__FAVICON_BASE64__">
    <style>
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            background-color: #07090e;
            color: #d1d5db;
            font-family: 'Consolas', 'Segoe UI', Tahoma, monospace;
            padding: 16px 20px 30px;
            overflow-x: hidden;
        }

        /* Matrix scanline effect */
        body::before {
            content: " ";
            display: block;
            position: fixed;
            top: 0; left: 0; bottom: 0; right: 0;
            background: linear-gradient(rgba(18, 16, 16, 0) 50%, rgba(0, 0, 0, 0.2) 50%), linear-gradient(90deg, rgba(0, 255, 102, 0.02), rgba(0, 240, 255, 0.01), rgba(0, 255, 102, 0.02));
            z-index: 99;
            background-size: 100% 3px, 6px 100%;
            pointer-events: none;
        }

        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid #1f293d;
            padding-bottom: 12px;
            margin-bottom: 16px;
        }

        .brand-title {
            font-size: 22px;
            font-weight: 900;
            letter-spacing: 2px;
            color: #00ff66;
            text-shadow: 0 0 10px rgba(0, 255, 102, 0.6);
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .brand-sub {
            font-size: 11px;
            color: #64748b;
            letter-spacing: 1px;
            margin-top: 3px;
        }

        .badge-status {
            background: #0d1e15;
            border: 1px solid #00ff66;
            color: #00ff66;
            padding: 6px 14px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: bold;
            display: flex;
            align-items: center;
            gap: 8px;
            box-shadow: 0 0 12px rgba(0, 255, 102, 0.2);
        }

        .pulse-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #00ff66;
            animation: pulse 1.5s infinite;
        }

        @keyframes pulse {
            0% { opacity: 1; transform: scale(1); }
            50% { opacity: 0.3; transform: scale(0.8); }
            100% { opacity: 1; transform: scale(1); }
        }

        .section-card {
            background: #0c111a;
            border: 1px solid #1e293b;
            border-radius: 6px;
            padding: 16px;
            margin-bottom: 16px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.4);
        }

        .section-header {
            color: #00f0ff;
            font-size: 12px;
            font-weight: bold;
            text-transform: uppercase;
            letter-spacing: 1.5px;
            margin-bottom: 14px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            border-bottom: 1px dashed #1e293b;
            padding-bottom: 8px;
        }

        .section-header .tag {
            background: #1e293b;
            color: #00ff66;
            font-size: 10px;
            padding: 2px 8px;
            border-radius: 3px;
        }

        /* Hardware Info Grid */
        .hw-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 10px;
        }

        .hw-item {
            background: #080c14;
            border-left: 3px solid #00ff66;
            padding: 9px 12px;
            border-radius: 0 4px 4px 0;
            display: flex;
            flex-direction: column;
            gap: 3px;
        }

        .hw-item.full-width {
            grid-column: span 2;
        }

        .hw-label {
            font-size: 10px;
            color: #64748b;
            font-weight: bold;
            letter-spacing: 0.5px;
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .hw-value {
            font-size: 13px;
            color: #00ff66;
            word-break: break-word;
            font-weight: 500;
        }

        .hw-value.cyan { color: #00f0ff; }
        .hw-value.yellow { color: #facc15; }
        .hw-value.white { color: #f8fafc; font-weight: 600; }

        /* Form Inputs */
        .form-grid-2 {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
        }

        .form-group {
            display: flex;
            flex-direction: column;
            gap: 5px;
            margin-bottom: 12px;
        }

        label {
            font-size: 11px;
            color: #94a3b8;
            font-weight: bold;
        }

        label span { color: #ff0055; margin-left: 2px; }

        input {
            background: #05070c;
            border: 1px solid #1e293b;
            color: #00ff66;
            padding: 10px 12px;
            font-family: inherit;
            font-size: 13px;
            border-radius: 4px;
            outline: none;
            transition: all 0.2s ease;
            width: 100%;
        }

        input:focus {
            border-color: #00ff66;
            box-shadow: 0 0 8px rgba(0, 255, 102, 0.3);
            background: #080c14;
        }

        input.barcode-input {
            border-color: #facc15;
            color: #facc15;
            font-weight: bold;
            font-size: 14px;
            letter-spacing: 1.5px;
        }

        input.barcode-input:focus {
            border-color: #00ff66;
            box-shadow: 0 0 10px rgba(250, 204, 21, 0.4);
        }

        /* KHU VỰC CHỌN KHOA / PHÒNG BAN: COMBOBOX AUTOCOMPLETE CHUYÊN NGHIỆP */
        .dept-input-wrap {
            position: relative;
            display: flex;
            align-items: center;
        }

        .dept-search-input {
            background: #05070c;
            border: 1px solid #1e293b;
            color: #00ff66;
            font-weight: bold;
            padding: 11px 40px 11px 14px;
            border-radius: 4px;
            font-size: 13px;
            width: 100%;
            transition: all 0.2s ease;
        }

        .dept-search-input:focus {
            border-color: #00f0ff;
            box-shadow: 0 0 10px rgba(0, 240, 255, 0.35);
            background: #080d18;
        }

        .dept-clear-btn {
            position: absolute;
            right: 14px;
            color: #64748b;
            font-size: 18px;
            font-weight: bold;
            cursor: pointer;
            display: none;
            user-select: none;
            transition: color 0.15s ease;
        }

        .dept-clear-btn:hover {
            color: #ff0055;
        }

        /* POPUP DROPDOWN XƯỢC RA KHI GÕ - TUYỆT ĐỐI KHÔNG HIỆN SẴN NGUYÊN ĐỐNG */
        .dept-dropdown-popup {
            display: none;
            position: absolute;
            top: 100%;
            left: 0;
            right: 0;
            max-height: 240px;
            overflow-y: auto;
            background: #080d18;
            border: 1px solid #00f0ff;
            border-top: none;
            border-radius: 0 0 6px 6px;
            padding: 6px;
            z-index: 1000;
            box-shadow: 0 12px 30px rgba(0, 0, 0, 0.9), 0 0 15px rgba(0, 240, 255, 0.2);
        }

        .dept-item {
            padding: 9px 12px;
            color: #f1f5f9;
            background: #0b1220;
            font-size: 13px;
            cursor: pointer;
            border-radius: 4px;
            margin-bottom: 4px;
            border: 1px solid #162032;
            display: flex;
            align-items: center;
            justify-content: space-between;
            transition: all 0.12s ease;
        }

        .dept-item:hover, .dept-item.focused {
            background: #0d2818;
            color: #00ff66;
            border-color: #00ff66;
            padding-left: 16px;
        }

        .dept-item.selected {
            background: #00ff66 !important;
            color: #000000 !important;
            font-weight: 900 !important;
            border-color: #00ff66 !important;
            box-shadow: 0 0 10px rgba(0, 255, 102, 0.6);
        }

        .dept-item .dept-idx {
            font-size: 11px;
            color: #64748b;
            margin-right: 8px;
        }

        .dept-item.selected .dept-idx {
            color: #000000 !important;
        }

        /* Server & Save Action */
        .server-bar {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 14px;
        }

        .server-bar label { white-space: nowrap; font-size: 11px; color: #00f0ff; }
        .server-bar input { flex: 1; padding: 7px 10px; font-size: 12px; }

        .btn-save {
            width: 100%;
            background: #0a2918;
            border: 2px solid #00ff66;
            color: #00ff66;
            padding: 15px;
            font-family: inherit;
            font-size: 15px;
            font-weight: 900;
            letter-spacing: 2px;
            text-transform: uppercase;
            border-radius: 6px;
            cursor: pointer;
            box-shadow: 0 0 20px rgba(0, 255, 102, 0.25);
            transition: all 0.2s ease;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
        }

        .btn-save:hover {
            background: #00ff66;
            color: #000000;
            box-shadow: 0 0 30px rgba(0, 255, 102, 0.7);
            transform: translateY(-2px);
        }

        .btn-save:active {
            transform: translateY(1px);
        }

        .btn-save:disabled {
            background: #111827;
            border-color: #374151;
            color: #6b7280;
            cursor: not-allowed;
            box-shadow: none;
            transform: none;
        }

        .status-msg {
            text-align: center;
            font-size: 11px;
            margin-top: 10px;
            color: #64748b;
        }

        .status-msg.success { color: #00ff66; font-weight: bold; }
        .status-msg.error { color: #ff3366; font-weight: bold; }

        ::-webkit-scrollbar { width: 8px; }
        ::-webkit-scrollbar-track { background: #07090e; }
        ::-webkit-scrollbar-thumb { background: #1e293b; border-radius: 4px; }
        ::-webkit-scrollbar-thumb:hover { background: #00ff66; }
    </style>
</head>
<body>
    <div class="header">
        <div>
            <div class="brand-title">
                <span>⚡ IN4.EXE</span>
                <span style="font-size: 13px; color: #64748b; font-weight: normal;">| HARDWARE RECON CORE</span>
            </div>
            <div class="brand-sub">// AUTO HARVEST TELEMETRY // HOSPITAL ASSET MANAGEMENT</div>
        </div>
        <div class="badge-status">
            <div class="pulse-dot"></div>
            <span id="badge-text">AUTO_DETECTED_OK</span>
        </div>
    </div>

    <!-- Section 1: Auto Hardware Info Display (Bake trực tiếp data vào DOM 0.00s delay) -->
    <div class="section-card">
        <div class="section-header">
            <span>[01] THÔNG SỐ PHẦN CỨNG THU THẬP TỰ ĐỘNG (AUTO-DETECTED INFO)</span>
            <span class="tag" id="detect-status" style="color: #00ff66;">✓ ĐÃ TỰ ĐỘNG QUÉT XONG</span>
        </div>

        <div class="hw-grid">
            <div class="hw-item">
                <div class="hw-label"><span>🖥️</span> TÊN MÁY TÍNH (HOSTNAME)</div>
                <div class="hw-value white" id="val-hostname">__VAL_HOSTNAME__</div>
            </div>
            <div class="hw-item">
                <div class="hw-label"><span>🌐</span> ĐỊA CHỈ IP LAN & MAC ADDRESS</div>
                <div class="hw-value yellow" id="val-net">__VAL_NET__</div>
            </div>
            <div class="hw-item full-width">
                <div class="hw-label"><span>🪟</span> HỆ ĐIỀU HÀNH (OPERATING SYSTEM)</div>
                <div class="hw-value white" id="val-os">__VAL_OS__</div>
            </div>
            <div class="hw-item full-width">
                <div class="hw-label"><span>🖲️</span> BO MẠCH CHỦ (MAINBOARD & NĂM SX/BIOS)</div>
                <div class="hw-value cyan" id="val-mainboard">__VAL_MAINBOARD__</div>
            </div>
            <div class="hw-item full-width">
                <div class="hw-label"><span>⚡</span> VI XỬ LÝ (CPU & NĂM RA MẮT THẾ HỆ)</div>
                <div class="hw-value white" id="val-cpu">__VAL_CPU__</div>
            </div>
            <div class="hw-item full-width">
                <div class="hw-label"><span>💾</span> SỐ THANH RAM ĐANG CẮM & CHI TIẾT KHE RAM</div>
                <div class="hw-value yellow" id="val-ram">__VAL_RAM__</div>
            </div>
            <div class="hw-item full-width">
                <div class="hw-label"><span>💿</span> Ổ ĐĨA LƯU TRỮ (PHÂN LOẠI SSD/HDD, DUNG LƯỢNG, SERIAL)</div>
                <div class="hw-value" id="val-storage">__VAL_STORAGE__</div>
            </div>
            <div class="hw-item full-width">
                <div class="hw-label"><span>📺</span> MÀN HÌNH (HÃNG, MODEL, KÍCH THƯỚC INCH, NĂM & TUẦN SX EDID)</div>
                <div class="hw-value cyan" id="val-monitors">__VAL_MONITORS__</div>
            </div>
            <div class="hw-item full-width">
                <div class="hw-label"><span>⌨️🖱️</span> BÀN PHÍM & CHUỘT (KEYBOARD & MOUSE)</div>
                <div class="hw-value white" id="val-periph">__VAL_PERIPH__</div>
            </div>
        </div>
    </div>

    <!-- Section 2: Hospital Metadata Input -->
    <div class="section-card">
        <div class="section-header">
            <span>[02] THÔNG TIN VỊ TRÍ, MÃ VẠCH & NGƯỜI SỬ DỤNG</span>
            <span class="tag">BẮT BUỘC</span>
        </div>

        <!-- Ô NHẬP MÃ VẠCH TÀI SẢN -->
        <div class="form-group">
            <label style="color: #facc15;">🏷️ MÃ VẠCH / MÃ QUẢN LÝ TÀI SẢN (BARCODE - DÙNG MÁY QUÉT HOẶC GÕ TAY) <span>*</span></label>
            <input type="text" id="barcode" class="barcode-input" value="__VAL_BARCODE__" placeholder="Quét mã vạch hoặc nhập mã tài sản (VD: BV-PC-2024-0102)..." autofocus>
        </div>

        <!-- Ô CHỌN KHOA / PHÒNG BAN: COMBOBOX AUTOCOMPLETE (CHỈ XƯỢC RA KHI GÕ/CLICK) -->
        <div class="form-group" style="position: relative;">
            <label style="display: flex; justify-content: space-between; align-items: center;">
                <span>🏢 KHOA / PHÒNG BAN / BỘ PHẬN <span>*</span></span>
                <span id="dept_status_tag" style="font-size: 11px; color: #64748b; font-weight: normal;">(Gõ để gợi ý tìm kiếm)</span>
            </label>
            <div class="dept-input-wrap">
                <input type="text" id="dept_search" class="dept-search-input" value="__VAL_DEPT__" placeholder="🔍 Nhấp vào hoặc gõ để tìm khoa (VD: kham, noi, nhi, cdha, duoc, tim mach...)..." autocomplete="off">
                <span class="dept-clear-btn" id="dept_clear" onclick="clearDept()" title="Xóa chọn lại">&times;</span>
            </div>
            <input type="hidden" id="department" value="__VAL_DEPT__">
            
            <!-- POPUP DROPDOWN XƯỢC RA KHI GÕ GỢI Ý - BÌNH THƯỜNG ẨN HOÀN TOÀN -->
            <div id="dept_list" class="dept-dropdown-popup">
                <!-- 39 Khoa gợi ý xược ra ở đây -->
            </div>
        </div>

        <div class="form-grid-2">
            <div class="form-group">
                <label>SỐ PHÒNG</label>
                <input type="text" id="room_number" value="__VAL_ROOM_NUM__" placeholder="VD: 101, 204B, 305...">
            </div>
            <div class="form-group">
                <label>TÊN PHÒNG</label>
                <input type="text" id="room_name" value="__VAL_ROOM_NAME__" placeholder="VD: Phòng Khám Nội 1, Quầy Tiếp Đón BHYT...">
            </div>
        </div>

        <div class="form-grid-2">
            <div class="form-group">
                <label>NGƯỜI SỬ DỤNG (BÁC SĨ / ĐIỀU DƯỠNG / NV)</label>
                <input type="text" id="user_name" value="__VAL_USER_NAME__" placeholder="VD: BS. Nguyễn Văn A, ĐD. Trần Thị B...">
            </div>
            <div class="form-group">
                <label>SỐ ĐIỆN THOẠI NGƯỜI DÙNG</label>
                <input type="text" id="user_phone" value="__VAL_USER_PHONE__" placeholder="VD: 0912345678 hoặc số máy lẻ 102...">
            </div>
        </div>

        <div class="form-group">
            <label>GHI CHÚ THÊM (MEMO)</label>
            <input type="text" id="notes" value="__VAL_NOTES__" placeholder="Tùy chọn: Máy hoạt động bình thường, màn hình hơi mờ...">
        </div>
    </div>

    <!-- Section 3: Save Action -->
    <div class="server-bar">
        <label>ĐỊA CHỈ MÁY CHỦ DATABASE:</label>
        <input type="text" id="server_url" value="__SERVER_URL__">
    </div>

    <button class="btn-save" id="btn-save" onclick="saveToDatabase()">
        <span>💾</span> SAVE // LƯU VÀO DATABASE
    </button>
    <div class="status-msg" id="status-msg">Sẵn sàng lưu thông tin vào CSDL SQLite</div>

    <script>
        // Dữ liệu phần cứng nhúng trực tiếp từ Python
        const PRELOADED_HW = __PRELOADED_HW_JSON__;
        let cachedHw = PRELOADED_HW;

        // Danh sách chuẩn 39 Khoa / Phòng ban bệnh viện
        const DEPARTMENTS = __DEPARTMENTS_JSON__;

        const deptSearch = document.getElementById('dept_search');
        const deptListEl = document.getElementById('dept_list');
        const deptHiddenInput = document.getElementById('department');
        const deptStatusTag = document.getElementById('dept_status_tag');
        const deptClearBtn = document.getElementById('dept_clear');
        let selectedDept = "";
        let currentFocusIdx = -1;

        // Bỏ dấu tiếng Việt toàn diện (hỗ trợ cả Unicode dựng sẵn và tổ hợp)
        function stripVietnamese(str) {
            if (!str) return '';
            let s = str.toLowerCase();
            s = s.replace(/[àáạảãâầấậẩẫăằắặẳẵ]/g, 'a')
                 .replace(/[èéẹẻẽêềếệểễ]/g, 'e')
                 .replace(/[ìíịỉĩ]/g, 'i')
                 .replace(/[òóọỏõôồốộổỗơờớợởỡ]/g, 'o')
                 .replace(/[ùúụủũưừứựửữ]/g, 'u')
                 .replace(/[ỳýỵỷỹ]/g, 'y')
                 .replace(/đ/g, 'd');
            try { s = s.normalize('NFD').replace(/[\u0300-\u036f]/g, ''); } catch(e) {}
            return s.trim();
        }

        // Render danh sách gợi ý khi gõ hoặc click (CHỈ XƯỢC RA KHI GÕ/CLICK)
        function renderSuggestions(query = "") {
            const cleanQuery = stripVietnamese(query);
            deptListEl.innerHTML = "";
            currentFocusIdx = -1;

            let count = 0;
            let firstMatchedName = "";

            DEPARTMENTS.forEach((name, idx) => {
                const cleanName = stripVietnamese(name);
                const isMatch = !cleanQuery || cleanName.includes(cleanQuery) || (cleanQuery === 'it' && cleanName.includes('cntt'));
                if (isMatch) {
                    if (!firstMatchedName) firstMatchedName = name;
                    const item = document.createElement('div');
                    item.className = 'dept-item' + (name === selectedDept ? ' selected' : '');
                    item.dataset.name = name;
                    item.innerHTML = `<span><span class="dept-idx">${idx + 1}.</span>${name}</span><span style="font-size:10px; color:#64748b;">${name === selectedDept ? '✓ ĐÃ CHỌN' : '[Chọn]'}</span>`;
                    
                    item.addEventListener('mousedown', (e) => {
                        e.preventDefault();
                        selectDept(name);
                    });
                    deptListEl.appendChild(item);
                    count++;
                }
            });

            if (count === 0) {
                const empty = document.createElement('div');
                empty.style.cssText = 'padding:12px; color:#94a3b8; font-size:12px; text-align:center;';
                empty.innerHTML = `Không có khoa nào khớp "<b>${query}</b>"`;
                deptListEl.appendChild(empty);
            }

            // Xược danh sách gợi ý ra
            deptListEl.style.display = 'block';
            return firstMatchedName;
        }

        function closeDropdown() {
            deptListEl.style.display = 'none';
            currentFocusIdx = -1;
        }

        function selectDept(name) {
            selectedDept = name;
            deptHiddenInput.value = name;
            deptSearch.value = name;
            deptSearch.style.borderColor = '#00ff66';
            deptClearBtn.style.display = 'block';

            deptStatusTag.innerHTML = `✓ ĐÃ CHỌN: <b style="color:#00ff66;">${name}</b>`;
            deptStatusTag.style.color = '#00ff66';

            closeDropdown();

            const roomInput = document.getElementById('room_number');
            if (roomInput) roomInput.focus();
        }

        function clearDept() {
            selectedDept = "";
            deptHiddenInput.value = "";
            deptSearch.value = "";
            deptSearch.style.borderColor = '#1e293b';
            deptClearBtn.style.display = 'none';
            deptStatusTag.innerHTML = `(Chưa chọn khoa)`;
            deptStatusTag.style.color = '#64748b';
            deptSearch.focus();
            renderSuggestions("");
        }

        // Khi người dùng gõ vào ô: xược danh sách gợi ý ra
        deptSearch.addEventListener('input', (e) => {
            const val = e.target.value;
            deptClearBtn.style.display = val ? 'block' : 'none';
            if (selectedDept && val !== selectedDept) {
                selectedDept = "";
                deptHiddenInput.value = "";
                deptStatusTag.innerHTML = `(Đang tìm kiếm...)`;
                deptStatusTag.style.color = '#00f0ff';
            }
            renderSuggestions(val);
        });

        // Khi click / focus vào ô tìm kiếm: xược ra danh sách gợi ý
        deptSearch.addEventListener('focus', () => {
            renderSuggestions(deptSearch.value === selectedDept ? "" : deptSearch.value);
        });

        // Phím mũi tên lên/xuống và Enter để chọn nhanh
        deptSearch.addEventListener('keydown', (e) => {
            const items = deptListEl.querySelectorAll('.dept-item');
            if (deptListEl.style.display === 'block' && items.length > 0) {
                if (e.key === 'ArrowDown') {
                    e.preventDefault();
                    currentFocusIdx = (currentFocusIdx + 1) % items.length;
                    updateItemFocus(items);
                } else if (e.key === 'ArrowUp') {
                    e.preventDefault();
                    currentFocusIdx = (currentFocusIdx - 1 + items.length) % items.length;
                    updateItemFocus(items);
                } else if (e.key === 'Enter') {
                    e.preventDefault();
                    if (currentFocusIdx >= 0 && currentFocusIdx < items.length) {
                        selectDept(items[currentFocusIdx].dataset.name);
                    } else if (items.length > 0) {
                        selectDept(items[0].dataset.name);
                    }
                } else if (e.key === 'Escape') {
                    closeDropdown();
                }
            }
        });

        function updateItemFocus(items) {
            items.forEach((item, idx) => {
                if (idx === currentFocusIdx) {
                    item.classList.add('focused');
                    item.scrollIntoView({ block: 'nearest' });
                } else {
                    item.classList.remove('focused');
                }
            });
        }

        // Đóng dropdown khi click ra ngoài
        document.addEventListener('click', (e) => {
            if (!deptSearch.contains(e.target) && !deptListEl.contains(e.target) && !deptClearBtn.contains(e.target)) {
                closeDropdown();
            }
        });

        // Khôi phục khoa đã lưu từ trước nếu có
        if (deptSearch.value) {
            selectDept(deptSearch.value);
        }

        // Tự động focus vào ô Mã Vạch khi vừa mở app
        setTimeout(() => {
            const b = document.getElementById('barcode');
            if (b) b.focus();
        }, 300);

        // Đồng bộ dữ liệu form sang Python ngầm (giúp lưu cấu hình khi bấm [X] mà không bị crash)
        function getFormData() {
            return {
                barcode: document.getElementById('barcode') ? document.getElementById('barcode').value.trim() : '',
                department: selectedDept || (document.getElementById('department') ? document.getElementById('department').value.trim() : '') || (deptSearch ? deptSearch.value.trim() : ''),
                room_number: document.getElementById('room_number') ? document.getElementById('room_number').value.trim() : '',
                room_name: document.getElementById('room_name') ? document.getElementById('room_name').value.trim() : '',
                user_name: document.getElementById('user_name') ? document.getElementById('user_name').value.trim() : '',
                user_phone: document.getElementById('user_phone') ? document.getElementById('user_phone').value.trim() : '',
                notes: document.getElementById('notes') ? document.getElementById('notes').value.trim() : '',
                server_url: document.getElementById('server_url') ? document.getElementById('server_url').value.trim() : ''
            };
        }

        function notifyFormChange() {
            try {
                if (window.pywebview && window.pywebview.api && window.pywebview.api.sync_form) {
                    window.pywebview.api.sync_form(getFormData());
                }
            } catch(e) {}
        }

        ['barcode', 'dept_search', 'room_number', 'room_name', 'user_name', 'user_phone', 'notes', 'server_url'].forEach(id => {
            const el = document.getElementById(id);
            if (el) {
                el.addEventListener('input', notifyFormChange);
                el.addEventListener('change', notifyFormChange);
            }
        });

        // Nút SAVE import vào CSDL
        async function saveToDatabase() {
            const barcode = document.getElementById('barcode').value.trim();
            const dept = selectedDept || deptHiddenInput.value || deptSearch.value.trim();
            const roomNum = document.getElementById('room_number').value.trim();
            const roomName = document.getElementById('room_name').value.trim();
            const userName = document.getElementById('user_name').value.trim();
            const phone = document.getElementById('user_phone').value.trim();
            const notes = document.getElementById('notes').value.trim();
            const serverUrl = document.getElementById('server_url').value.trim();

            const statusMsg = document.getElementById('status-msg');

            if (!barcode) {
                alert('Vui lòng quét hoặc nhập Mã vạch / Mã tài sản!');
                document.getElementById('barcode').focus();
                return;
            }
            if (!dept) {
                alert('Vui lòng nhấp chọn Khoa / Phòng ban trong danh mục!');
                deptSearch.focus();
                return;
            }

            const payload = {
                ...cachedHw,
                barcode: barcode,
                department: dept,
                room_number: roomNum,
                room_name: roomName,
                user_name: userName,
                user_phone: phone,
                notes: notes,
                server_url: serverUrl
            };

            const btn = document.getElementById('btn-save');
            btn.disabled = true;
            btn.innerHTML = '<span>⏳</span> ĐANG IMPORT VÀO DATABASE...';
            statusMsg.className = 'status-msg';
            statusMsg.innerText = 'Đang kết nối và lưu dữ liệu vào CSDL SQLite...';

            try {
                const res = await window.pywebview.api.save_record(payload);
                if (res.status === 'success') {
                    statusMsg.className = 'status-msg success';
                    statusMsg.innerText = '✓ ' + res.message;
                    document.getElementById('badge-text').innerText = 'SAVED_TO_DB';
                    alert(`✓ LƯU THÀNH CÔNG!\\nKhoa: ${dept}\\nMã vạch: ${res.barcode || barcode}\\nMAC: ${res.mac_address}`);
                } else {
                    statusMsg.className = 'status-msg error';
                    statusMsg.innerText = '✗ ' + res.message;
                    alert(`Lỗi lưu CSDL:\\n${res.message}`);
                }
            } catch (err) {
                statusMsg.className = 'status-msg error';
                statusMsg.innerText = '✗ Lỗi kết nối: ' + err;
                alert('Lỗi kết nối máy chủ: ' + err);
            } finally {
                btn.disabled = false;
                btn.innerHTML = '<span>💾</span> SAVE // LƯU VÀO DATABASE';
            }
        }
    </script>
</body>
</html>"""


class BridgeApi:
    def __init__(self, hw_data: dict):
        self.cached_hw = hw_data
        self.latest_form_data = {}

    def auto_get_info(self):
        return self.cached_hw

    def sync_form(self, form_data: dict):
        if isinstance(form_data, dict):
            self.latest_form_data.update(form_data)
        return True

    def save_record(self, payload: dict):
        server_url = payload.pop("server_url", DEFAULT_SERVER_URL).rstrip("/")
        api_url = f"{server_url}/api/inventory"
        barcode = payload.get("barcode", "")
        self.latest_form_data.update({**payload, "server_url": server_url})

        try:
            import service_manager
            boot_str, uptime_h = service_manager.get_boot_info()
            payload["logged_in_user"] = service_manager.get_logged_in_user()
            payload["boot_time"] = boot_str
            payload["client_agent_port"] = 8005
            payload["client_version"] = "1.3.1"
        except Exception:
            pass

        # 1. Thử gửi lên máy chủ trung tâm
        try:
            req_data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                api_url,
                data=req_data,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=2.5) as response:
                body = response.read().decode("utf-8")
                res = json.loads(body)
                
                # Cập nhật cấu hình lưu trữ
                try:
                    import service_manager
                    install_payload = {
                        **payload,
                        "server_url": server_url
                    }
                    service_manager.install_auto_start(install_payload)
                except Exception as inst_err:
                    log_error(f"Lỗi install_auto_start: {inst_err}")

                return {
                    "status": "success",
                    "message": f"Đã lưu thông tin máy tính lên Server ({server_url}) thành công!",
                    "barcode": barcode,
                    "mac_address": payload.get("mac_address"),
                    "server": server_url
                }
        except Exception as net_err:
            log_error(f"Lỗi gửi máy chủ trung tâm ({api_url}): {net_err}")
            # 2. Lưu dự phòng vào SQLite local
            try:
                self.save_to_local_sqlite(payload)
                try:
                    import service_manager
                    install_payload = {
                        **payload,
                        "server_url": server_url
                    }
                    service_manager.install_auto_start(install_payload)
                except Exception:
                    pass
                return {
                    "status": "success",
                    "message": f"Không kết nối được server {server_url}. Đã lưu dự phòng vào CSDL nội bộ!",
                    "barcode": barcode,
                    "mac_address": payload.get("mac_address"),
                    "local_fallback": True
                }
            except Exception as sql_err:
                log_error(f"Lỗi lưu SQLite local: {sql_err}\n{traceback.format_exc()}")
                return {
                    "status": "error",
                    "message": f"Lỗi kết nối máy chủ: {net_err}\nLỗi ghi SQLite local: {sql_err}"
                }

    def save_to_local_sqlite(self, data: dict):
        conn = sqlite3.connect(LOCAL_DB_FILE, timeout=10)
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
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("""
        INSERT INTO computers (
            barcode, mac_address, hostname, ip_address, os_name, mainboard_info, cpu_info,
            ram_total_gb, ram_details, storage_details, monitors_details, peripherals_details,
            room_number, room_name, department, user_name, user_phone, notes, updated_at
        ) VALUES (
            :barcode, :mac_address, :hostname, :ip_address, :os_name, :mainboard_info, :cpu_info,
            :ram_total_gb, :ram_details, :storage_details, :monitors_details, :peripherals_details,
            :room_number, :room_name, :department, :user_name, :user_phone, :notes, :now_str
        )
        ON CONFLICT(mac_address) DO UPDATE SET
            barcode = excluded.barcode,
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
            room_number = excluded.room_number,
            room_name = excluded.room_name,
            department = excluded.department,
            user_name = excluded.user_name,
            user_phone = excluded.user_phone,
            notes = excluded.notes,
            updated_at = excluded.updated_at
        """, {
            "barcode": data.get("barcode", "").strip(),
            "mac_address": data.get("mac_address", "").strip().upper(),
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
            "now_str": now_str
        })
        conn.commit()
        conn.close()


def main():
    is_silent = ("--silent" in sys.argv)
    exe_path = os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__)
    # Khi khởi động ngầm trong thư mục cài đặt IN4_Agent, luôn chạy ngầm 100% không bao giờ mở UI
    if "in4_agent" in exe_path.lower() and "--gui" not in sys.argv:
        is_silent = True

    if is_silent:
        try:
            import service_manager
            service_manager.run_silent_background_agent()
        except Exception as e:
            log_error(f"Lỗi silent agent: {e}\n{traceback.format_exc()}")
        sys.exit(0)

    try:
        import service_manager
        if service_manager.request_uac_elevation_if_needed():
            sys.exit(0)
        saved_meta = service_manager.load_saved_agent_config()

        # 1. Tự động quét cấu hình trước khi mở cửa sổ
        cfg = load_config()
        server_url = saved_meta.get("server_url") or cfg.get("server_url", DEFAULT_SERVER_URL)
        hw_data = hardware_collector.collect_all_hardware_info()
        api = BridgeApi(hw_data)

        # 2. Bake trực tiếp dữ liệu vào HTML thẻ <div> (0.00s delay)
        net_val = f"{hw_data.get('ip_address', 'N/A')} | MAC: {hw_data.get('mac_address', 'N/A')}"
        html_ready = HTML_TEMPLATE
        html_ready = html_ready.replace("__SERVER_URL__", html.escape(server_url))
        html_ready = html_ready.replace("__VAL_HOSTNAME__", html.escape(hw_data.get('hostname', 'Unknown')))
        html_ready = html_ready.replace("__VAL_NET__", html.escape(net_val))
        html_ready = html_ready.replace("__VAL_OS__", html.escape(hw_data.get('os_name', 'N/A')))
        html_ready = html_ready.replace("__VAL_MAINBOARD__", html.escape(hw_data.get('mainboard_info', 'N/A')))
        html_ready = html_ready.replace("__VAL_CPU__", html.escape(hw_data.get('cpu_info', 'N/A')))
        html_ready = html_ready.replace("__VAL_RAM__", html.escape(hw_data.get('ram_details', 'N/A')))
        html_ready = html_ready.replace("__VAL_STORAGE__", html.escape(hw_data.get('storage_details', 'N/A')))
        html_ready = html_ready.replace("__VAL_MONITORS__", html.escape(hw_data.get('monitors_details', 'N/A')))
        html_ready = html_ready.replace("__VAL_PERIPH__", html.escape(hw_data.get('peripherals_details', 'N/A')))
        html_ready = html_ready.replace("__PRELOADED_HW_JSON__", json.dumps(hw_data, ensure_ascii=False))
        html_ready = html_ready.replace("__DEPARTMENTS_JSON__", json.dumps(OFFICIAL_DEPARTMENTS, ensure_ascii=False))

        # Điền sẵn metadata đã lưu nếu máy này đã từng được khảo sát
        html_ready = html_ready.replace("__VAL_BARCODE__", html.escape(saved_meta.get("barcode", "")))
        html_ready = html_ready.replace("__VAL_DEPT__", html.escape(saved_meta.get("department", "")))
        html_ready = html_ready.replace("__VAL_ROOM_NUM__", html.escape(str(saved_meta.get("room_number", ""))))
        html_ready = html_ready.replace("__VAL_ROOM_NAME__", html.escape(saved_meta.get("room_name", "")))
        html_ready = html_ready.replace("__VAL_USER_NAME__", html.escape(saved_meta.get("user_name", "")))
        html_ready = html_ready.replace("__VAL_USER_PHONE__", html.escape(saved_meta.get("user_phone", "")))
        html_ready = html_ready.replace("__VAL_NOTES__", html.escape(saved_meta.get("notes", "")))

        # Favicon base64
        icon_b64 = ""
        b64_file = os.path.join(APP_DIR, "icon_b64.txt")
        if os.path.exists(b64_file):
            try:
                with open(b64_file, "r", encoding="utf-8") as f:
                    icon_b64 = f.read().strip()
            except Exception: pass
        if not icon_b64:
            icon_png = os.path.join(APP_DIR, "app_icon.png")
            if os.path.exists(icon_png):
                try:
                    import base64
                    with open(icon_png, "rb") as f:
                        icon_b64 = base64.b64encode(f.read()).decode("utf-8")
                except Exception: pass
        html_ready = html_ready.replace("__FAVICON_BASE64__", icon_b64)

        window = webview.create_window(
            title="IN4 // HARDWARE RECON & HOSPITAL ASSET SYSTEM",
            html=html_ready,
            js_api=api,
            width=940,
            height=900,
            resizable=True,
            background_color="#07090e"
        )

        webview.start()

        # Khi người dùng tắt cửa sổ [X]: cửa sổ đã đóng hoàn tất và giải phóng bộ nhớ
        # Tiến hành kích hoạt agent chạy ngầm một cách an toàn không bao giờ bị đơ/treo
        try:
            import service_manager
            final_data = getattr(api, "latest_form_data", {}) or {}
            service_manager.install_auto_start(final_data)
            service_manager.spawn_background_process()
        except Exception as post_close_err:
            log_error(f"Lỗi sau khi đóng cửa sổ: {post_close_err}")

    except Exception as e:
        log_error(f"Lỗi main(): {e}\n{traceback.format_exc()}")
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, f"Lỗi khởi chạy IN4.EXE:\n{e}", "IN4 Error", 0x10)
        except Exception:
            pass


if __name__ == "__main__":
    main()
