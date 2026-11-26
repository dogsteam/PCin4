@echo off
chcp 65001 >nul
echo ===================================================================
echo  ĐANG ĐÓNG GÓI CLIENT TOOL THÀNH ĐÚNG 1 FILE .EXE DUY NHẤT (PORTABLE)
echo ===================================================================

cd /d "%~dp0"
pyinstaller --noconfirm --onefile --windowed --name "HospitalPCInventory" ^
    --add-data "config.json;." ^
    gui_app.py

echo.
echo ===================================================================
echo  HOÀN THÀNH! File chạy duy nhất nằm tại:
echo  dist\HospitalPCInventory.exe
echo ===================================================================
pause
