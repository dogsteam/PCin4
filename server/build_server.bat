@echo off
chcp 65001 >nul
echo ===================================================================
echo   [PCin4Server.exe] BUILDING PORTABLE SERVER EXECUTABLE
echo ===================================================================

cd /d "%~dp0"
pyinstaller --noconfirm --onefile --console --name "PCin4Server" ^
    --hidden-import "database" ^
    --hidden-import "hot_deploy" ^
    --hidden-import "uvicorn.logging" ^
    --hidden-import "uvicorn.loops" ^
    --hidden-import "uvicorn.loops.auto" ^
    --hidden-import "uvicorn.protocols" ^
    --hidden-import "uvicorn.protocols.http" ^
    --hidden-import "uvicorn.protocols.http.auto" ^
    --hidden-import "uvicorn.lifespan" ^
    --hidden-import "uvicorn.lifespan.on" ^
    --distpath "dist" ^
    --workpath "build" ^
    main.py

if errorlevel 1 (
    echo [LOI] Build PCin4Server.exe that bai!
    if /I not "%~1"=="--nopause" pause
    exit /b 1
)

copy /y "dist\PCin4Server.exe" "PCin4Server.exe" >nul
copy /y "dist\PCin4Server.exe" "..\PCin4Server.exe" >nul

echo.
echo ===================================================================
echo   [BUILD COMPLETE] PCin4Server.exe da duoc tao thanh cong!
echo   - server\PCin4Server.exe
echo   - PCin4Server.exe (root project folder)
echo ===================================================================
if /I not "%~1"=="--nopause" pause
