@echo off
chcp 65001 >nul
title MAY CHU QUAN LY THIET BI PC BENH VIEN - 10.10.12.188
echo ===================================================================
echo   MAY CHU QUAN LY VA THU THAP THIET BI PC BENH VIEN (SQLITE DB)
echo ===================================================================
echo.
echo  Dia chi IP May chu: 10.10.12.188
echo  Web Dashboard:     http://localhost:8000  hoac  http://10.10.12.188:8000
echo  Link tai in4.exe:  http://10.10.12.188:8000/in4.exe
echo  API Documentation: http://localhost:8000/docs
echo  CSDL SQLite:       inventory.db (luu tai thu muc hien tai)
echo.
echo ===================================================================
echo  Dang khoi dong may chu...
echo.

cd /d "%~dp0"

if exist server.exe (
    server.exe %*
) else (
    python main.py %*
)
pause
