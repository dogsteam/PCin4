@echo off
chcp 65001 >nul
set "ROOT_DIR=%~dp0"
cd /d "%ROOT_DIR%"

set "SERVER_ONLY=0"
if /I "%~1"=="--server-only" set "SERVER_ONLY=1"
if /I "%~2"=="--server-only" set "SERVER_ONLY=1"

if /I "%~1"=="--pulled" goto :after_pull

echo ===================================================================
echo   [1-CLICK] BUILD ^& AUTO DEPLOY LEN 10.10.12.188
echo ===================================================================
echo.
echo [1/4] Dang cap nhat ma nguon moi nhat tu GitHub...
git pull origin main
if errorlevel 1 (
    echo [LOI] git pull that bai!
    pause
    exit /b 1
)
if "%SERVER_ONLY%"=="1" (
    cmd /c ""%~f0" --pulled --server-only"
) else (
    cmd /c ""%~f0" --pulled"
)
exit /b %errorlevel%

:after_pull
if "%SERVER_ONLY%"=="1" (
    echo.
    echo [2/4] Bo qua build Client - che do server-only.
    goto :build_server
)

echo.
echo [2/4] Dang dong goi Client - in4.exe...
cd /d "%ROOT_DIR%"
call client\build_in4.bat --nopause
if errorlevel 1 (
    echo [LOI] Build in4.exe that bai!
    pause
    exit /b 1
)

:build_server
echo.
echo [3/4] Dang dong goi Server - PCin4Server.exe...
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
if exist "%LOCAL_RUN_DIR%\inventory.db" goto :deploy_local

if "%SERVER_ONLY%"=="1" (
    python "%ROOT_DIR%scripts\deploy_server.py" 10.10.12.188 1994 PCin4-HotDeploy-2026
) else (
    python "%ROOT_DIR%scripts\deploy_server.py" 10.10.12.188 1994 PCin4-HotDeploy-2026 --with-client
)
if errorlevel 1 (
    echo [LOI] Hot-Deploy that bai! Kiem tra xem 10.10.12.188 da chay PCin4Server.exe mo port 1994 chua.
    pause
    exit /b 1
)
goto :done_deploy

:deploy_local
echo     Phat hien thu muc may chu: %LOCAL_RUN_DIR%
if exist "%LOCAL_RUN_DIR%\PCin4Server.old" del /f /q "%LOCAL_RUN_DIR%\PCin4Server.old" >nul 2>&1
if exist "%LOCAL_RUN_DIR%\PCin4Server.exe" move /y "%LOCAL_RUN_DIR%\PCin4Server.exe" "%LOCAL_RUN_DIR%\PCin4Server.old"
if "%SERVER_ONLY%"=="0" (
    if exist "%ROOT_DIR%server\in4.exe" copy /y "%ROOT_DIR%server\in4.exe" "%LOCAL_RUN_DIR%\in4.exe"
)
copy /y "%ROOT_DIR%server\PCin4Server.exe" "%LOCAL_RUN_DIR%\PCin4Server.exe"
taskkill /F /IM PCin4Server.exe /T >nul 2>&1
timeout /t 1 /nobreak >nul
start "" /D "%LOCAL_RUN_DIR%" "%LOCAL_RUN_DIR%\PCin4Server.exe" --no-browser
echo [OK] Da copy va khoi dong lai PCin4Server.exe tai %LOCAL_RUN_DIR%!

:done_deploy
echo.
echo ===================================================================
echo   HOAN TAT! Da cap nhat len Server!
echo ===================================================================
pause
