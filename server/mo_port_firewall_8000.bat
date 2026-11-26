@echo off
chcp 65001 >nul
title MO PORT 8000 FIREWALL CHO MAY CHU 10.10.12.188
echo ===================================================================
echo   MO PORT 8000 TREN WINDOWS FIREWALL CHO MAY CHU 10.10.12.188
echo ===================================================================
echo.
echo Luu y: Vui long nhap chuot phai chon "Run as administrator" (Chay voi quyen Admin)
echo.
netsh advfirewall firewall add rule name="IN4_Hospital_Server_8000" dir=in action=allow protocol=TCP localport=8000
echo.
if %ERRORLEVEL% EQU 0 (
    echo [OK] DA MO PORT 8000 THANH CONG!
    echo Cac may PC con trong mang vien da co the gui du lieu ve 10.10.12.188.
) else (
    echo [LOI] Khong the mo port! Ban phai nhap chuot phai chon "Run as administrator".
)
echo.
pause
