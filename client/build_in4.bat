@echo off
chcp 65001 >nul
echo ===================================================================
echo   [IN4.EXE] BUILDING PORTABLE CLIENT EXECUTABLE (ELECTRON WEBVIEW)
echo ===================================================================

cd /d "%~dp0"
pyinstaller --noconfirm --onefile --windowed --name "in4" ^
    --icon "app_icon.ico" ^
    --add-data "config.json;." ^
    --add-data "icon_b64.txt;." ^
    --add-data "app_icon.png;." ^
    --hidden-import "service_manager" ^
    --hidden-import "hardware_collector" ^
    --distpath "dist" ^
    --workpath "build" ^
    electron_app.py

copy /y "dist\in4.exe" "..\in4.exe" >nul
copy /y "dist\in4.exe" "..\server\in4.exe" >nul

echo.
echo ===================================================================
echo   [BUILD COMPLETE] in4.exe da duoc tao thanh cong!
echo   - client\dist\in4.exe
echo   - server\in4.exe
echo   - in4.exe (root project folder)
echo ===================================================================
if /I not "%~1"=="--nopause" pause
