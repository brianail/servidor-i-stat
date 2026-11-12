@echo off
chcp 65001 >nul
cd /d "%~dp0"
set LYDA_WEB_PORT=8080

:WATCHDOG_LOOP
python web_server.py --no-browser
timeout /t 3 /nobreak >nul
goto WATCHDOG_LOOP
