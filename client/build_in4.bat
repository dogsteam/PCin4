@echo off
chcp 65001 >nul
echo ===================================================================
echo   [IN4.EXE] BUILDING NATIVE EXECUTABLE VIA NUITKA (ANTI-AV MODE)
echo ===================================================================

cd /d "%~dp0"
set "BUILD_OK=0"

python -m nuitka --version >nul 2>&1
if errorlevel 1 (
    echo [INFO] Dang cai dat Nuitka va zstandard de bien dich ma may C...
    pip install -U nuitka ordered-set zstandard
)

python -m nuitka --version >nul 2>&1
if not errorlevel 1 (
    echo [INFO] Dang bien dich electron_app.py bang Nuitka --onefile...
    python -m nuitka ^
        --standalone ^
        --onefile ^
        --assume-yes-for-downloads ^
        --windows-console-mode=disable ^
        --windows-icon-from-ico=app_icon.ico ^
        --onefile-tempdir-spec="{CACHE_DIR}/IN4_Agent/rt_1_3_1" ^
        --enable-plugin=pywebview ^
        --include-package=webview ^
        --include-package=pythonnet ^
        --include-package=clr_loader ^
        --include-package-data=webview ^
        --include-package-data=pythonnet ^
        --include-package-data=clr_loader ^
        --include-module=service_manager ^
        --include-module=hardware_collector ^
        --include-data-files=config.json=config.json ^
        --include-data-files=icon_b64.txt=icon_b64.txt ^
        --include-data-files=app_icon.png=app_icon.png ^
        --output-dir=build_nuitka ^
        --output-filename=in4.exe ^
        electron_app.py

    if not errorlevel 1 (
        if exist "build_nuitka\in4.exe" (
            if not exist "dist" mkdir "dist"
            copy /y "build_nuitka\in4.exe" "dist\in4.exe" >nul
            set "BUILD_OK=1"
            echo [OK] Bien dich Nuitka thanh cong!
        )
    )
)

if "%BUILD_OK%"=="0" (
    echo [WARN] Nuitka khong thanh cong hoac chua san sang, chuyen sang PyInstaller fallback...
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
    if errorlevel 1 (
        echo [LOI] Build in4.exe that bai!
        if /I not "%~1"=="--nopause" pause
        exit /b 1
    )
)

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
