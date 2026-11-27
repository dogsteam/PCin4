@echo off
chcp 65001 >nul
echo Dang mo cong Firewall 1994 (PCin4Server Hot-Deploy)...
netsh advfirewall firewall add rule name="PCin4Server_HotDeploy_1994" dir=in action=allow protocol=TCP localport=1994
echo Da mo xong cong 1994!
pause
