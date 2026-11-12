@echo off
chcp 65001 >nul
title Lyda - Sistema de Mini-Etiquetas Zebra ZD230
cd /d "%~dp0"

echo ========================================================
echo   LYDA - SISTEMA DE MINI-ETIQUETAS ZEBRA ZD230 (ZPL)
echo ========================================================
echo.

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERRO] Python nao encontrado neste computador!
    echo Instale o Python 3 em https://www.python.org/downloads/
    echo (Marque a caixinha "Add Python to PATH" na instalacao)
    pause
    exit /b 1
)

if not exist ".venv" (
    echo [1/2] Criando ambiente virtual e instalando leitor de Excel...
    python -m venv .venv
    call .venv\Scripts\activate.bat
    python -m pip install --upgrade pip >nul
    pip install openpyxl pandas Pillow pywin32
) else (
    call .venv\Scripts\activate.bat
)

echo [2/2] Abrindo o sistema Lyda Zebra ZD230...
start "" pythonw main.py
if %errorlevel% neq 0 (
    python main.py
)

