@echo off
chcp 65001 >nul
cd /d "%~dp0"
set SCRIPT_DIR=%~dp0
set LYDA_WEB_PORT=8080

set "PYTHON_BIN=python"
if exist "%SCRIPT_DIR%lyda_python_path.txt" (
    set /p PYTHON_BIN=<"%SCRIPT_DIR%lyda_python_path.txt"
)
"%PYTHON_BIN%" --version >nul 2>&1
if %errorlevel% neq 0 (
    py -3 --version >nul 2>&1 && set "PYTHON_BIN=py -3"
)

:WATCHDOG_LOOP
"%PYTHON_BIN%" web_server.py --no-browser
timeout /t 3 /nobreak >nul
goto WATCHDOG_LOOP
