@echo off
chcp 65001 >nul
echo ========================================================
echo  ĐANG ĐÓNG GÓI CLIENT TOOL THÀNH FILE .EXE DUY NHẤT
echo ========================================================

cd /d "%~dp0"
pyinstaller --noconfirm --onedir --windowed --name "HospitalPCInventory" ^
    --add-data "config.json;." ^
    gui_app.py

echo.
echo ========================================================
echo  HOÀN THÀNH! File thực thi nằm trong thư mục:
echo  dist\HospitalPCInventory\HospitalPCInventory.exe
echo ========================================================
pause
