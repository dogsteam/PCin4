@echo off
chcp 65001 >nul
set "ROOT_DIR=%~dp0"
cd /d "%ROOT_DIR%"

if /I "%~1"=="--pulled" goto :after_pull

echo ===================================================================
echo   [CLIENT ONLY] BUILD in4.exe ^& DAY LEN SERVER - KHONG RESTART SERVER
echo ===================================================================
echo.
echo [1/3] Dang cap nhat ma nguon moi nhat tu GitHub...
git pull origin main
if errorlevel 1 (
    echo [LOI] git pull that bai!
    pause
    exit /b 1
)
cmd /c ""%~f0" --pulled"
exit /b %errorlevel%

:after_pull
echo.
echo [2/3] Dang dong goi Client - in4.exe...
cd /d "%ROOT_DIR%"
call client\build_in4.bat --nopause
if errorlevel 1 (
    echo [LOI] Build in4.exe that bai!
    pause
    exit /b 1
)

echo.
echo [3/3] Dang day in4.exe len Server...
cd /d "%ROOT_DIR%"
set "LOCAL_RUN_DIR=C:\Users\Admin\Desktop\In4"
if exist "%LOCAL_RUN_DIR%\inventory.db" goto :deploy_local

python "%ROOT_DIR%scripts\deploy_server.py" 10.10.12.188 1994 PCin4-HotDeploy-2026 --client-only
if errorlevel 1 (
    echo [LOI] Day in4.exe len Server that bai!
    pause
    exit /b 1
)
goto :done_deploy

:deploy_local
copy /y "%ROOT_DIR%server\in4.exe" "%LOCAL_RUN_DIR%\in4.exe"
echo [OK] Da copy in4.exe moi vao %LOCAL_RUN_DIR%!

:done_deploy
echo.
echo ===================================================================
echo   HOAN TAT! Da cap nhat in4.exe moi len Server!
echo ===================================================================
pause
