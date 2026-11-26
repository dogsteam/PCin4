"""
gui_app.py - IN4 // SYSTEM HARVESTER & HARDWARE RECON
Underground Hacker / Cyberpunk Dark Electron Style UI
"""

import json
import os
import sys
import threading
import urllib.request
import urllib.error
import tkinter as tk
from tkinter import ttk, messagebox

import hardware_collector

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
DEFAULT_SERVER_URL = "http://localhost:8000"

# Bảng màu Hacker Cyberpunk / Electron Dark Style
COLOR_BG_DARK = "#080C14"       # Nền tổng thể siêu đen
COLOR_PANEL_BG = "#0D1322"      # Nền panel
COLOR_CARD_BG = "#131C31"       # Nền card
COLOR_INPUT_BG = "#05080F"      # Nền ô nhập liệu
COLOR_NEON_GREEN = "#00FF66"    # Xanh neon Hacker Matrix
COLOR_NEON_CYAN = "#00F0FF"     # Xanh Cyan Cyberpunk
COLOR_TEXT_MAIN = "#E2E8F0"     # Trắng sáng
COLOR_TEXT_MUTED = "#64748B"    # Xám khói
COLOR_BORDER = "#1E293B"        # Viền tối
COLOR_BORDER_FOCUS = "#00FF66"  # Viền sáng neon khi click
COLOR_ACCENT_RED = "#FF0055"    # Đỏ neon cảnh báo

HOSPITAL_DEPARTMENTS = [
    "Khoa Khám Bệnh",
    "Khoa Cấp Cứu",
    "Khoa Hồi Sức Tích Cực (ICU)",
    "Khoa Chẩn Đoán Hình Ảnh (X-Quang, CT, MRI)",
    "Khoa Xét Nghiệm",
    "Khoa Dược",
    "Khoa Nội Tổng Hợp",
    "Khoa Ngoại Tổng Hợp",
    "Khoa Phẫu Thuật - Gây Mê",
    "Khoa Sản",
    "Khoa Nhi",
    "Khoa Mắt",
    "Khoa Tai Mũi Họng",
    "Khoa Răng Hàm Mặt",
    "Khoa Kiểm Soát Nhiễm Khuẩn",
    "Khoa Dinh Dưỡng",
    "Phòng Kế Hoạch Tổng Hợp",
    "Phòng Tài Chính Kế Toán",
    "Phòng Vật Tư - TBYT",
    "Phòng Công Nghệ Thông Tin",
    "Phòng Tổ Chức Cán Bộ",
    "Phòng Điều Dưỡng",
    "Ban Giám Đốc"
]


def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    cfg = {"server_url": DEFAULT_SERVER_URL}
    save_config(cfg)
    return cfg


def save_config(cfg: dict):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4, ensure_ascii=False)
    except Exception:
        pass


class In4HackerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("IN4 // HARDWARE RECON & HOSPITAL ASSET HARVESTER")
        self.geometry("860x860")
        self.minsize(800, 780)
        self.configure(bg=COLOR_BG_DARK)

        self.config_data = load_config()
        self.hw_info = {}

        self.setup_theme()
        self.create_hacker_widgets()

        # Quét cấu hình ngầm ngay khi bật tool
        threading.Thread(target=self.scan_hardware_stream, daemon=True).start()

    def setup_theme(self):
        style = ttk.Style(self)
        style.theme_use("clam")

        # Cấu hình Combobox chuẩn Hacker Dark
        style.configure("Hacker.TCombobox", 
                        fieldbackground=COLOR_INPUT_BG,
                        background=COLOR_PANEL_BG,
                        foreground=COLOR_NEON_GREEN,
                        darkcolor=COLOR_BORDER,
                        lightcolor=COLOR_BORDER,
                        arrowcolor=COLOR_NEON_GREEN,
                        bordercolor=COLOR_BORDER)
        style.map("Hacker.TCombobox", 
                  fieldbackground=[("readonly", COLOR_INPUT_BG), ("focus", COLOR_INPUT_BG)],
                  foreground=[("readonly", COLOR_NEON_GREEN), ("focus", COLOR_NEON_GREEN)])

    def create_hacker_widgets(self):
        # 1. Top Cyberpunk Terminal Header
        top_bar = tk.Frame(self, bg=COLOR_PANEL_BG, height=65, highlightbackground=COLOR_BORDER, highlightthickness=1)
        top_bar.pack(fill="x", padx=14, pady=(14, 10))

        # Logo / Title ASCII
        lbl_brand = tk.Label(top_bar, text="IN4.EXE", font=("Consolas", 18, "bold"), fg=COLOR_NEON_GREEN, bg=COLOR_PANEL_BG)
        lbl_brand.pack(side="left", padx=(16, 10), pady=12)

        lbl_sub = tk.Label(top_bar, text="// UNDERGROUND HARDWARE INTEL RECON\n// HOSPITAL IT ASSET SYSTEM", 
                           font=("Consolas", 9, "bold"), fg=COLOR_NEON_CYAN, bg=COLOR_PANEL_BG, justify="left")
        lbl_sub.pack(side="left", pady=12)

        # Status Badge góc phải
        self.lbl_badge = tk.Label(top_bar, text="[ STATUS: RECON_IDLE ]", font=("Consolas", 9, "bold"), 
                                  fg=COLOR_NEON_GREEN, bg="#0A2416", padx=10, pady=5, relief="flat", highlightbackground=COLOR_NEON_GREEN, highlightthickness=1)
        self.lbl_badge.pack(side="right", padx=16, pady=16)

        # Container chính
        container = tk.Frame(self, bg=COLOR_BG_DARK)
        container.pack(fill="both", expand=True, padx=14, pady=0)

        # 2. Section: Vị trí & Người dùng (Cyberpunk Form)
        sec_user = tk.LabelFrame(container, text=" [01] METADATA // PHÒNG BAN & NHÂN VIÊN SỬ DỤNG ", 
                                 font=("Consolas", 10, "bold"), fg=COLOR_NEON_CYAN, bg=COLOR_PANEL_BG, 
                                 highlightbackground=COLOR_BORDER, highlightthickness=1, bd=0, padx=14, pady=12)
        sec_user.pack(fill="x", pady=(0, 10))

        # Grid form
        # Row 0: Khoa
        tk.Label(sec_user, text="KHOA / PHÒNG BAN:", font=("Consolas", 9, "bold"), fg=COLOR_TEXT_MUTED, bg=COLOR_PANEL_BG).grid(row=0, column=0, sticky="w", pady=4)
        self.cbo_dept = ttk.Combobox(sec_user, values=HOSPITAL_DEPARTMENTS, font=("Consolas", 10), style="Hacker.TCombobox")
        self.cbo_dept.grid(row=0, column=1, columnspan=3, sticky="ew", padx=(8, 0), pady=4)
        if HOSPITAL_DEPARTMENTS:
            self.cbo_dept.set(HOSPITAL_DEPARTMENTS[0])

        # Row 1: Số phòng & Tên phòng
        tk.Label(sec_user, text="SỐ PHÒNG (*):", font=("Consolas", 9, "bold"), fg=COLOR_TEXT_MUTED, bg=COLOR_PANEL_BG).grid(row=1, column=0, sticky="w", pady=4)
        self.ent_room_num = self.create_hacker_entry(sec_user)
        self.ent_room_num.grid(row=1, column=1, sticky="ew", padx=(8, 14), pady=4)

        tk.Label(sec_user, text="TÊN PHÒNG (*):", font=("Consolas", 9, "bold"), fg=COLOR_TEXT_MUTED, bg=COLOR_PANEL_BG).grid(row=1, column=2, sticky="w", pady=4)
        self.ent_room_name = self.create_hacker_entry(sec_user)
        self.ent_room_name.grid(row=1, column=3, sticky="ew", padx=(8, 0), pady=4)

        # Row 2: Bác sĩ/Người dùng & SĐT
        tk.Label(sec_user, text="NGƯỜI DÙNG (*):", font=("Consolas", 9, "bold"), fg=COLOR_TEXT_MUTED, bg=COLOR_PANEL_BG).grid(row=2, column=0, sticky="w", pady=4)
        self.ent_user = self.create_hacker_entry(sec_user)
        self.ent_user.grid(row=2, column=1, sticky="ew", padx=(8, 14), pady=4)

        tk.Label(sec_user, text="SỐ ĐIỆN THOẠI (*):", font=("Consolas", 9, "bold"), fg=COLOR_TEXT_MUTED, bg=COLOR_PANEL_BG).grid(row=2, column=2, sticky="w", pady=4)
        self.ent_phone = self.create_hacker_entry(sec_user)
        self.ent_phone.grid(row=2, column=3, sticky="ew", padx=(8, 0), pady=4)

        # Row 3: Ghi chú
        tk.Label(sec_user, text="GHI CHÚ / MEMO:", font=("Consolas", 9, "bold"), fg=COLOR_TEXT_MUTED, bg=COLOR_PANEL_BG).grid(row=3, column=0, sticky="w", pady=4)
        self.ent_notes = self.create_hacker_entry(sec_user)
        self.ent_notes.grid(row=3, column=1, columnspan=3, sticky="ew", padx=(8, 0), pady=4)

        sec_user.columnconfigure(1, weight=1)
        sec_user.columnconfigure(3, weight=1)

        # 3. Section: Terminal Logs & Hardware Intel (Matrix Console)
        sec_term = tk.LabelFrame(container, text=" [02] TELEMETRY // PHẦN CỨNG & NĂM SẢN XUẤT PHÁT HIỆN ", 
                                 font=("Consolas", 10, "bold"), fg=COLOR_NEON_GREEN, bg=COLOR_PANEL_BG, 
                                 highlightbackground=COLOR_BORDER, highlightthickness=1, bd=0, padx=12, pady=10)
        sec_term.pack(fill="both", expand=True, pady=(0, 10))

        # Terminal Text Box
        self.txt_term = tk.Text(sec_term, font=("Consolas", 9), bg=COLOR_INPUT_BG, fg=COLOR_NEON_GREEN, 
                                insertbackground=COLOR_NEON_GREEN, relief="flat", wrap="word", 
                                highlightbackground=COLOR_BORDER, highlightthickness=1, padx=10, pady=8)
        self.txt_term.pack(fill="both", expand=True)

        # Định dạng màu cho các dòng terminal
        self.txt_term.tag_config("cyan", foreground=COLOR_NEON_CYAN)
        self.txt_term.tag_config("green", foreground=COLOR_NEON_GREEN)
        self.txt_term.tag_config("yellow", foreground="#FACC15")
        self.txt_term.tag_config("muted", foreground=COLOR_TEXT_MUTED)
        self.txt_term.tag_config("white", foreground=COLOR_TEXT_MAIN)
        self.txt_term.tag_config("red", foreground=COLOR_ACCENT_RED)

        self.append_terminal(">>> IN4_KERNEL_INIT... INITIALIZING HARDWARE RECON THREAD...\n", "cyan")
        self.txt_term.config(state="disabled")

        # 4. Section: Server Uplink & Execute Button
        sec_bot = tk.Frame(container, bg=COLOR_BG_DARK)
        sec_bot.pack(fill="x", pady=(0, 10))

        # Server URL bar
        srv_box = tk.Frame(sec_bot, bg=COLOR_PANEL_BG, padx=12, pady=8, highlightbackground=COLOR_BORDER, highlightthickness=1)
        srv_box.pack(fill="x", pady=(0, 8))

        tk.Label(srv_box, text="UPLINK CORE (SERVER IP):", font=("Consolas", 9, "bold"), fg=COLOR_NEON_CYAN, bg=COLOR_PANEL_BG).pack(side="left")
        self.ent_server = self.create_hacker_entry(srv_box)
        self.ent_server.insert(0, self.config_data.get("server_url", DEFAULT_SERVER_URL))
        self.ent_server.pack(side="left", fill="x", expand=True, padx=(10, 0))

        # Nút Cyberpunk Execute
        self.btn_execute = tk.Button(
            sec_bot,
            text="⚡ EXECUTE UPLINK // GỬI DỮ LIỆU VỀ MÁY CHỦ BỆNH VIỆN ⚡",
            font=("Consolas", 12, "bold"),
            bg="#0D2818",
            fg=COLOR_NEON_GREEN,
            activebackground=COLOR_NEON_GREEN,
            activeforeground="#000000",
            relief="flat",
            bd=0,
            padx=20,
            pady=12,
            cursor="hand2",
            highlightbackground=COLOR_NEON_GREEN,
            highlightthickness=2,
            command=self.on_execute_uplink
        )
        self.btn_execute.pack(fill="x")

        # Hiệu ứng hover neon
        self.btn_execute.bind("<Enter>", lambda e: self.btn_execute.config(bg=COLOR_NEON_GREEN, fg="#000000"))
        self.btn_execute.bind("<Leave>", lambda e: self.btn_execute.config(bg="#0D2818", fg=COLOR_NEON_GREEN))

    def create_hacker_entry(self, parent) -> tk.Entry:
        """Tạo Entry với style cyberpunk viền sáng khi click."""
        ent = tk.Entry(parent, font=("Consolas", 10), bg=COLOR_INPUT_BG, fg=COLOR_NEON_GREEN,
                       insertbackground=COLOR_NEON_GREEN, relief="flat",
                       highlightbackground=COLOR_BORDER, highlightcolor=COLOR_NEON_GREEN,
                       highlightthickness=1)
        return ent

    def append_terminal(self, text: str, tag: str = "green"):
        """Ghi log vào màn hình terminal hacker."""
        self.txt_term.config(state="normal")
        self.txt_term.insert("end", text, tag)
        self.txt_term.see("end")
        self.txt_term.config(state="disabled")

    def scan_hardware_stream(self):
        """Quét cấu hình và xuất ra màn hình kiểu hacker."""
        self.after(0, lambda: self.lbl_badge.config(text="[ STATUS: SCANNING... ]", fg="#FACC15", bg="#2B2105", highlightbackground="#FACC15"))
        try:
            self.hw_info = hardware_collector.collect_all_hardware_info()
            self.after(0, self.display_recon_data)
        except Exception as e:
            self.after(0, lambda: self.append_terminal(f"[-] ERROR IN SCAN: {str(e)}\n", "red"))
            self.after(0, lambda: self.lbl_badge.config(text="[ STATUS: SCAN_ERROR ]", fg=COLOR_ACCENT_RED, bg="#2E0814", highlightbackground=COLOR_ACCENT_RED))

    def display_recon_data(self):
        """Hiển thị kết quả thu thập cấu hình lên terminal."""
        self.lbl_badge.config(text="[ STATUS: RECON_COMPLETED ]", fg=COLOR_NEON_GREEN, bg="#0A2416", highlightbackground=COLOR_NEON_GREEN)
        
        self.append_terminal("\n================== TELEMETRY DUMP // IN4 RECON ==================\n", "cyan")
        self.append_terminal(f"[+] HOSTNAME      :: {self.hw_info.get('hostname')}\n", "white")
        self.append_terminal(f"[+] OPERATING SYS :: {self.hw_info.get('os_name')}\n", "muted")
        self.append_terminal(f"[+] NETWORK IP    :: {self.hw_info.get('ip_address')} (LAN)\n", "green")
        self.append_terminal(f"[+] MAC ADDRESS   :: {self.hw_info.get('mac_address')} [UNIQUE_KEY]\n", "yellow")
        self.append_terminal("-----------------------------------------------------------------\n", "cyan")
        self.append_terminal(f"[+] MAINBOARD     :: {self.hw_info.get('mainboard_info')}\n", "cyan")
        self.append_terminal(f"[+] CPU PROCESSOR :: {self.hw_info.get('cpu_info')}\n", "white")
        self.append_terminal(f"[+] RAM MEMORY    :: {self.hw_info.get('ram_details')}\n", "yellow")
        self.append_terminal(f"[+] STORAGE DRIVE :: {self.hw_info.get('storage_details')}\n", "green")
        self.append_terminal(f"[+] ACTIVE MON    :: {self.hw_info.get('monitors_details')}\n", "white")
        self.append_terminal("=================================================================\n", "cyan")
        self.append_terminal(">>> ALL COMPONENT METRICS ACQUIRED. READY FOR UPLINK.\n\n", "green")

    def on_execute_uplink(self):
        """Gửi dữ liệu lên Server với hiệu ứng log trực tiếp."""
        dept = self.cbo_dept.get().strip()
        room_num = self.ent_room_num.get().strip()
        room_name = self.ent_room_name.get().strip()
        user_name = self.ent_user.get().strip()
        phone = self.ent_phone.get().strip()
        notes = self.ent_notes.get().strip()
        server_url = self.ent_server.get().strip().rstrip("/")

        # Validation
        if not room_num or not room_name or not user_name or not phone:
            messagebox.showwarning("MISSING PARAMS", "Vui lòng nhập đầy đủ: Số phòng, Tên phòng, Người dùng, SĐT!")
            return

        if not self.hw_info or not self.hw_info.get("mac_address"):
            messagebox.showwarning("WAITING", "Hệ thống đang quét phần cứng. Vui lòng thử lại sau 2 giây!")
            return

        self.config_data["server_url"] = server_url
        save_config(self.config_data)

        payload = {
            **self.hw_info,
            "department": dept,
            "room_number": room_num,
            "room_name": room_name,
            "user_name": user_name,
            "user_phone": phone,
            "notes": notes
        }

        self.btn_execute.config(state="disabled", text="⏳ TRANSMITTING ENCRYPTED PAYLOAD...")
        self.lbl_badge.config(text="[ STATUS: UPLINKING... ]", fg="#FACC15", bg="#2B2105", highlightbackground="#FACC15")
        self.append_terminal(f"\n[*] CONNECTING TO TARGET CORE: {server_url}/api/inventory ...\n", "yellow")

        threading.Thread(target=self.transmit_thread, args=(server_url, payload), daemon=True).start()

    def transmit_thread(self, server_url, payload):
        api_url = f"{server_url}/api/inventory"
        try:
            req_data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                api_url,
                data=req_data,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=8) as response:
                body = response.read().decode("utf-8")
                res_json = json.loads(body)
                self.after(0, lambda: self.on_transmit_success(res_json))
        except urllib.error.URLError as e:
            self.after(0, lambda: self.on_transmit_error(f"CONNECTION REFUSED: {e.reason}"))
        except Exception as e:
            self.after(0, lambda: self.on_transmit_error(str(e)))

    def on_transmit_success(self, res_json):
        self.btn_execute.config(state="normal", text="⚡ EXECUTE UPLINK // GỬI DỮ LIỆU VỀ MÁY CHỦ BỆNH VIỆN ⚡")
        self.lbl_badge.config(text="[ STATUS: COMMITTED_200 ]", fg=COLOR_NEON_GREEN, bg="#0A2416", highlightbackground=COLOR_NEON_GREEN)
        self.append_terminal("[✓] 200 OK: PAYLOAD SECURELY COMMITTED TO SQLITE CORE DATABASE!\n", "green")
        self.append_terminal(f"[✓] DEVICE MAC [{res_json.get('mac_address')}] SYNCED SUCCESSFUL.\n\n", "cyan")
        messagebox.showinfo("IN4 SUCCESS", "✓ Dữ liệu cấu hình đã được ghi nhận vào CSDL Bệnh viện thành công!")

    def on_transmit_error(self, err_msg):
        self.btn_execute.config(state="normal", text="⚡ EXECUTE UPLINK // GỬI DỮ LIỆU VỀ MÁY CHỦ BỆNH VIỆN ⚡")
        self.lbl_badge.config(text="[ STATUS: UPLINK_FAILED ]", fg=COLOR_ACCENT_RED, bg="#2E0814", highlightbackground=COLOR_ACCENT_RED)
        self.append_terminal(f"[-] UPLINK ERROR: {err_msg}\n", "red")
        messagebox.showerror("IN4 ERROR", f"Không thể gửi dữ liệu đến máy chủ:\n{err_msg}\n\nHãy kiểm tra lại địa chỉ IP server!")


if __name__ == "__main__":
    app = In4HackerApp()
    app.mainloop()
