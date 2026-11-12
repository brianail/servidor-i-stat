@echo off
chcp 65001 >nul
title LYDA - SERVIDOR WEB CONTROLE DE ESTOQUE i-STAT (PORTA 8080)
cd /d "%~dp0"

echo ============================================================================
echo   LYDA - SERVIDOR WEB CENTRAL DE ESTOQUE, CLIENTES E ROTA i-STAT
echo ============================================================================
echo.
echo [1/3] Verificando bibliotecas Python necessarias (Flask, OpenPyXL, ReportLab, Pillow)...
python -c "import flask, openpyxl, reportlab, PIL" 2>nul
if errorlevel 1 (
    echo Instalando pacotes necessarios...
    python -m pip install --upgrade pip
    python -m pip install flask openpyxl reportlab pillow pywin32
)

echo [2/3] Liberando porta 8080 na rede local da LYDA (caso executado como Administrador)...
netsh advfirewall firewall show rule name="LYDA Servidor Web i-STAT 8080" >nul 2>&1
if errorlevel 1 (
    netsh advfirewall firewall add rule name="LYDA Servidor Web i-STAT 8080" dir=in action=allow protocol=TCP localport=8080 >nul 2>&1
)

echo [3/3] Iniciando Servidor Web na porta 8080 e abrindo o navegador...
echo       Mantenha esta janela aberta no PC Servidor da LYDA para que todos acessem o link!
echo.
python web_server.py
pause

