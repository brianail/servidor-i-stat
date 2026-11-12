@echo off
chcp 65001 >nul
cd /d "%~dp0"
set SCRIPT_DIR=%~dp0

echo ============================================================================
echo   LYDA — INSTALADOR DO SERVIDOR LOCAL PERMANENTE (WINDOWS)
echo ============================================================================
echo.
echo Este instalador vai configurar este computador para ser o SERVIDOR CENTRAL da LYDA.
echo O sistema vai rodar 100%% em segundo plano:
echo  - Sem janelas abertas para ninguem fechar por engano
echo  - Inicializacao automatica ao ligar o computador ou fazer login
echo  - Auto-recuperacao se o processo cair (Watchdog)
echo  - Porta 8080 liberada no Firewall para todos na rede acessarem
echo  - Modo de suspensao do PC desativado na tomada (para nunca cair)
echo.

:: 1. Verifica permissoes de Administrador
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [AVISO] Solicitando permissao de Administrador do Windows...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process cmd.exe -ArgumentList '/k cd /d \"%~dp0\" && \"%~f0\"' -Verb RunAs"
    exit /b
)

:: 2. Identifica ou instala o Python no Windows
set "PYTHON_BIN="

:: Testa se o comando python ja funciona diretamente
python --version >nul 2>&1
if %errorlevel% equ 0 set "PYTHON_BIN=python"

:: Testa py launcher
if not defined PYTHON_BIN (
    py -3 --version >nul 2>&1
    if %errorlevel% equ 0 set "PYTHON_BIN=py -3"
)

:: Testa caminhos padrao comuns do Windows
if not defined PYTHON_BIN (
    if exist "%ProgramFiles%\Python312\python.exe" set "PYTHON_BIN=%ProgramFiles%\Python312\python.exe"
)
if not defined PYTHON_BIN (
    if exist "%ProgramFiles%\Python311\python.exe" set "PYTHON_BIN=%ProgramFiles%\Python311\python.exe"
)
if not defined PYTHON_BIN (
    if exist "%ProgramFiles%\Python310\python.exe" set "PYTHON_BIN=%ProgramFiles%\Python310\python.exe"
)
if not defined PYTHON_BIN (
    if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PYTHON_BIN=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
)
if not defined PYTHON_BIN (
    if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PYTHON_BIN=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
)
if not defined PYTHON_BIN (
    if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" set "PYTHON_BIN=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
)

:: Se o Python nao foi encontrado, faz o download e instalacao oficial
if not defined PYTHON_BIN (
    echo ============================================================================
    echo   [!] PYTHON NAO FOI ENCONTRADO NESTE COMPUTADOR
    echo ============================================================================
    echo Para que o servidor local funcione, o Windows precisa do Python instalado.
    echo.
    echo Baixando o instalador oficial do Python 3.11 da Python.org...
    powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Write-Host 'Download em andamento...'; (New-Object System.Net.WebClient).DownloadFile('https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe', '$env:TEMP\python_setup.exe'); Write-Host 'Download concluido!'"
    
    if exist "%TEMP%\python_setup.exe" (
        echo.
        echo Instalando Python silenciosamente e configurando no Windows...
        echo Aguarde alguns instantes...
        start /wait "" "%TEMP%\python_setup.exe" /passive InstallAllUsers=1 PrependPath=1 Include_pip=1
        del /f /q "%TEMP%\python_setup.exe" >nul 2>&1
        
        if exist "%ProgramFiles%\Python311\python.exe" (
            set "PYTHON_BIN=%ProgramFiles%\Python311\python.exe"
        ) else if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
            set "PYTHON_BIN=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
        ) else (
            set "PYTHON_BIN=python"
        )
        echo [OK] Python instalado com sucesso!
        echo.
    ) else (
        echo.
        echo [ERRO] Nao foi possivel baixar o Python automaticamente.
        echo Por favor baixe e instale manualmente acessando:
        echo https://www.python.org/downloads/
        echo (IMPORTANTE: Marque a opcao 'Add python.exe to PATH' na instalacao)
        echo.
        pause
        exit /b
    )
)

:: Salva o caminho do executavel Python para o watchdog
<nul set /p="%PYTHON_BIN%" > "%SCRIPT_DIR%lyda_python_path.txt"

echo [1/6] Verificando e instalando bibliotecas necessarias...
echo       (Flask, OpenPyXL, ReportLab, Pillow)
"%PYTHON_BIN%" -m pip install --upgrade pip
"%PYTHON_BIN%" -m pip install flask openpyxl reportlab pillow
"%PYTHON_BIN%" -c "import flask, openpyxl, reportlab, PIL" >nul 2>&1
if %errorlevel% neq 0 (
    echo [Tentando instalacao local com --user...]
    "%PYTHON_BIN%" -m pip install --user flask openpyxl reportlab pillow
)
echo       Bibliotecas verificadas com sucesso!

echo.
echo [2/6] Liberando porta 8080 no Firewall do Windows para a rede local...
netsh advfirewall firewall delete rule name="LYDA Servidor Web i-STAT 8080" >nul 2>&1
netsh advfirewall firewall add rule name="LYDA Servidor Web i-STAT 8080" dir=in action=allow protocol=TCP localport=8080 profile=private,domain,public >nul 2>&1
echo       Porta 8080 liberada com sucesso!

echo.
echo [3/6] Configurando energia para o PC nunca dormir enquanto ligado a tomada...
powercfg /change standby-timeout-ac 0 >nul 2>&1
powercfg /change hibernate-timeout-ac 0 >nul 2>&1
echo       Modo de suspensao desativado com sucesso!

echo.
echo [4/6] Registrando Servidor Permanente no Agendador de Tarefas do Windows...
schtasks /delete /tn "LYDA_Servidor_iSTAT" /f >nul 2>&1
schtasks /create /tn "LYDA_Servidor_iSTAT" /tr "wscript.exe \"%SCRIPT_DIR%servidor_background.vbs\"" /sc onlogon /rl highest /f >nul 2>&1

set "STARTUP_FOLDER=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
if exist "%STARTUP_FOLDER%" (
    copy /y "%SCRIPT_DIR%servidor_background.vbs" "%STARTUP_FOLDER%\LYDA_Servidor_iSTAT.vbs" >nul 2>&1
)
echo       Inicializacao automatica configurada com sucesso!

echo.
echo [5/6] Iniciando o Servidor LYDA agora em segundo plano...
taskkill /f /im python.exe /fi "WINDOWTITLE eq *LYDA*" >nul 2>&1
wscript.exe "%SCRIPT_DIR%servidor_background.vbs"
echo       Servidor em execucao invisivel protegida (Watchdog ativo)!

echo.
echo [6/6] Criando atalho na Area de Trabalho deste computador...
set "DESKTOP_DIR=%USERPROFILE%\Desktop"
if exist "%DESKTOP_DIR%" (
    echo [InternetShortcut] > "%DESKTOP_DIR%\Acessar Sistema LYDA (Servidor Local).url"
    echo URL=http://localhost:8080 >> "%DESKTOP_DIR%\Acessar Sistema LYDA (Servidor Local).url"
    echo IconIndex=0 >> "%DESKTOP_DIR%\Acessar Sistema LYDA (Servidor Local).url"
    if exist "%SCRIPT_DIR%lyda_icon.ico" (
        echo IconFile=%SCRIPT_DIR%lyda_icon.ico >> "%DESKTOP_DIR%\Acessar Sistema LYDA (Servidor Local).url"
    )
)

echo.
"%PYTHON_BIN%" mostrar_ip_rede.py
echo.
echo Pode fechar esta janela agora. O servidor continuara rodando silenciosamente.
echo ============================================================================
pause
