@echo off
chcp 65001 >nul
set "ROOT_DIR=%~dp0"
cd /d "%ROOT_DIR%"

if /I not "%~1"=="--pulled" (
    echo ===================================================================
    echo   [1-CLICK] BUILD CLIENT + SERVER ^& AUTO DEPLOY LEN 10.10.12.188
    echo ===================================================================
    echo.
    echo [1/4] Dang cap nhat ma nguon moi nhat tu GitHub...
    git pull origin main
    if errorlevel 1 (
        echo [LOI] git pull that bai!
        pause
        exit /b 1
    )
    cmd /c ""%~f0" --pulled"
    exit /b %errorlevel%
)

echo.
echo [2/4] Dang dong goi Client (in4.exe)...
cd /d "%ROOT_DIR%"
call client\build_in4.bat --nopause
if errorlevel 1 (
    echo [LOI] Build in4.exe that bai!
    pause
    exit /b 1
)

echo.
echo [3/4] Dang dong goi Server (PCin4Server.exe)...
cd /d "%ROOT_DIR%"
call server\build_server.bat --nopause
if errorlevel 1 (
    echo [LOI] Build PCin4Server.exe that bai!
    pause
    exit /b 1
)

echo.
echo [4/4] Dang trien khai ban moi...
cd /d "%ROOT_DIR%"
set "LOCAL_RUN_DIR=C:\Users\Admin\Desktop\In4"
if exist "%LOCAL_RUN_DIR%\inventory.db" (
    echo     Phat hien thu muc may chu: %LOCAL_RUN_DIR%
    if exist "%LOCAL_RUN_DIR%\PCin4Server.old" del /f /q "%LOCAL_RUN_DIR%\PCin4Server.old" >nul 2>&1
    if exist "%LOCAL_RUN_DIR%\PCin4Server.exe" move /y "%LOCAL_RUN_DIR%\PCin4Server.exe" "%LOCAL_RUN_DIR%\PCin4Server.old"
    copy /y "%ROOT_DIR%server\in4.exe" "%LOCAL_RUN_DIR%\in4.exe"
    copy /y "%ROOT_DIR%server\PCin4Server.exe" "%LOCAL_RUN_DIR%\PCin4Server.exe"
    taskkill /F /IM PCin4Server.exe /T >nul 2>&1
    timeout /t 1 /nobreak >nul
    start "" /D "%LOCAL_RUN_DIR%" "%LOCAL_RUN_DIR%\PCin4Server.exe" --no-browser
    echo [OK] Da copy va khoi dong lai PCin4Server.exe tai %LOCAL_RUN_DIR%!
) else (
    python "%ROOT_DIR%scripts\deploy_server.py" 10.10.12.188 1994 PCin4-HotDeploy-2026 --with-client
    if errorlevel 1 (
        echo [LOI] Hot-Deploy that bai! Kiem tra xem 10.10.12.188 da chay PCin4Server.exe mo port 1994 chua.
        pause
        exit /b 1
    )
)

echo.
echo ===================================================================
echo   HOAN TAT! Da cap nhat ca in4.exe va PCin4Server.exe len Server!
echo   Vao http://10.10.12.188:8000 bam [Update All] de day xuong may tram.
echo ===================================================================
pause
