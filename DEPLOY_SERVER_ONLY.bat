@echo off
chcp 65001 >nul
cd /d "%~dp0"
call "%~dp0BUILD_AND_DEPLOY.bat" --server-only
