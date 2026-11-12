@echo off
chcp 65001 >nul
cd /d "%~dp0"
set SCRIPT_DIR=%~dp0
title LYDA — LINKS DE ACESSO NA REDE LOCAL

set "PYTHON_BIN=python"
if exist "%SCRIPT_DIR%lyda_python_path.txt" (
    set /p PYTHON_BIN=<"%SCRIPT_DIR%lyda_python_path.txt"
)
"%PYTHON_BIN%" --version >nul 2>&1
if %errorlevel% neq 0 (
    py -3 --version >nul 2>&1 && set "PYTHON_BIN=py -3"
)

"%PYTHON_BIN%" mostrar_ip_rede.py
echo.
echo Pressione qualquer tecla para abrir o sistema no navegador deste PC...
pause >nul
start http://localhost:8080
