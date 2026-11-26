# HỆ THỐNG THU THẬP & QUẢN LÝ CẤU HÌNH PC BỆNH VIỆN (HOSPITAL PC INVENTORY)

Hệ thống chuyên dụng dành cho phòng Công Nghệ Thông Tin (CNTT) bệnh viện để kiểm kê, quản lý thiết bị máy tính, theo dõi năm sản xuất các linh kiện (Mainboard, CPU, RAM, Ổ cứng, Màn hình), phát hiện máy yếu để lên kế hoạch nâng cấp hoặc thanh lý, và xuất báo cáo kiểm kê tài sản ra file Excel (.xlsx).

---

## 1. Cấu trúc Thư mục

```text
hospital_pc_inventory/
├── client/                     # Phần mềm trạm chạy trên PC bệnh viện
│   ├── hardware_collector.py   # Module tự động quét phần cứng & năm sản xuất
│   ├── gui_app.py              # Giao diện đồ họa (Tkinter) cho người dùng nhập liệu
│   ├── config.json             # File cấu hình IP máy chủ Server
│   ├── build_exe.bat           # File tự động đóng gói thư mục dist
│   └── build_onefile_exe.bat   # File đóng gói thành 1 file .exe duy nhất (Portable)
├── server/                     # Máy chủ quản lý trung tâm (Đặt tại phòng CNTT)
│   ├── main.py                 # FastAPI backend & Web Dashboard quản trị
│   ├── database.py             # Thao tác CSDL SQLite (inventory.db)
│   └── run_server.bat          # File 1-click khởi động Server
└── README.md
```

---

## 2. Thông số Phần cứng & Năm sản xuất thu thập được

| Linh kiện | Thông tin thu thập tự động | Cơ chế bóc tách & Năm sản xuất |
| :--- | :--- | :--- |
| **Bo mạch chủ (Mainboard)** | Hãng sản xuất, Model, **Ngày/Năm phát hành BIOS xuất xưởng** | Đọc Registry `HARDWARE\DESCRIPTION\System\BIOS` (VD: *Dell 0NX5H3 - Năm SX: 2021*) |
| **Vi xử lý (CPU)** | Tên CPU, Số nhân/luồng, **Năm ra mắt thế hệ CPU** | Phân tích thế hệ vi xử lý Intel Core Gen 2 - 14 / Pentium / Ryzen (VD: *i7-1165G7 - Năm SX: 2020-2021*) |
| **Bộ nhớ RAM** | Dung lượng (GB), **Hãng sản xuất chuẩn JEDEC**, Tốc độ Bus, Mã Part | WMI `Win32_PhysicalMemory` giải mã mã nhà sản xuất JEDEC (Kingston, Samsung, Micron, Hynix...) |
| **Ổ đĩa lưu trữ** | Phân loại rõ **SSD NVMe / SSD SATA / HDD**, Dung lượng, Model, Serial | PowerShell `Get-PhysicalDisk` bóc tách MediaType và BusType |
| **Màn hình (Monitors)** | **Hãng sản xuất, Model chuẩn, Kích thước Inch, Năm & Tuần sản xuất**, Serial | Giải mã firmware **EDID** (Byte 16 là Tuần, Byte 17 là Năm tính từ 1990; Byte 21 & 22 tính số Inch đường chéo $\frac{\sqrt{W^2+H^2}}{2.54}$) |
| **Mạng & Định danh** | Địa chỉ IPv4 LAN, **Địa chỉ MAC** (Khóa nhận diện chống trùng) | Adapter mạng active, MAC Address làm Unique Key tự động Upsert |
| **Vị trí & Người dùng** | **Số phòng, Tên phòng, Khoa/Phòng ban, Người sử dụng, Số điện thoại, Ghi chú** | Nhập qua form giao diện trực quan |

---

## 3. Hướng dẫn Khởi động Máy chủ (Server IT)

1. Mở thư mục `server/`.
2. Chạy file `run_server.bat` (hoặc mở terminal gõ: `python main.py`).
3. Máy chủ sẽ chạy tại cổng `8000`:
   - **Giao diện Quản trị Web Dashboard:** Mở trình duyệt vào `http://localhost:8000` (hoặc `http://<IP_MÁY_CHỦ>:8000` từ máy bất kỳ trong mạng LAN).
   - **Tài liệu API (Swagger):** `http://localhost:8000/docs`.
   - **Xuất file Excel:** Nhấn nút màu xanh lá **"Xuất File Excel"** trên Dashboard. File CSDL SQLite được lưu tự động tại `server/inventory.db`.

---

## 4. Hướng dẫn Chạy & Đóng gói Client Tool (.exe)

### Cách 1: Chạy trực tiếp bằng Python
```powershell
cd client
python gui_app.py
```

### Cách 2: Đóng gói thành 1 file `.exe` duy nhất (Khuyên dùng)
1. Trong thư mục `client/`, nhấp đúp chạy file `build_onefile_exe.bat`.
2. PyInstaller sẽ tự động biên dịch toàn bộ mã nguồn và thư viện thành **1 file chạy duy nhất**:
   ```text
   client\dist\HospitalPCInventory.exe
   ```
3. Copy file `HospitalPCInventory.exe` (và file `config.json` nếu muốn cấu hình sẵn IP máy chủ) vào USB hoặc chia sẻ qua thư mục mạng nội bộ để các khoa/phòng tải về chạy.
4. Người dùng hoặc nhân viên IT chỉ cần nhấp đúp file `.exe`:
   - Tool tự động nhận diện cấu hình phần cứng trong 1-2 giây.
   - Điền thông tin Khoa, Số phòng, Tên phòng, Bác sĩ/Người dùng, SĐT.
   - Nhấn **"Gửi dữ liệu về máy chủ phòng CNTT"**.
