@echo off
chcp 65001 >nul
echo ===================================================================
echo   [IN4.EXE] BUILDING UNDERGROUND HACKER PORTABLE EXECUTABLE
echo ===================================================================

cd /d "%~dp0"
pyinstaller --noconfirm --onefile --windowed --name "in4" ^
    --add-data "config.json;." ^
    --distpath "dist" ^
    --workpath "build" ^
    gui_app.py

copy /y "dist\in4.exe" "..\in4.exe"

echo.
echo ===================================================================
echo   [BUILD COMPLETE] in4.exe has been generated successfully!
echo   Location 1: client\dist\in4.exe
echo   Location 2: in4.exe (root project folder)
echo ===================================================================
pause
