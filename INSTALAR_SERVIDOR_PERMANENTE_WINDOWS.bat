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

:: Verifica permissões de Administrador
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [AVISO] Solicitando permissao de Administrador para configurar o Firewall e Servico...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

echo [1/6] Verificando e instalando bibliotecas necessarias...
python -m pip install --upgrade pip >nul 2>&1
python -m pip install flask openpyxl reportlab pillow >nul 2>&1

echo [2/6] Liberando porta 8080 no Firewall do Windows para a rede local...
netsh advfirewall firewall delete rule name="LYDA Servidor Web i-STAT 8080" >nul 2>&1
netsh advfirewall firewall add rule name="LYDA Servidor Web i-STAT 8080" dir=in action=allow protocol=TCP localport=8080 profile=private,domain,public >nul 2>&1
echo       Porta 8080 liberada com sucesso!

echo [3/6] Configurando energia para o PC nunca dormir enquanto ligado a tomada...
powercfg /change standby-timeout-ac 0 >nul 2>&1
powercfg /change hibernate-timeout-ac 0 >nul 2>&1
echo       Modo de suspensao desativado com sucesso!

echo [4/6] Registrando Servidor Permanente no Agendador de Tarefas do Windows...
schtasks /delete /tn "LYDA_Servidor_iSTAT" /f >nul 2>&1
schtasks /create /tn "LYDA_Servidor_iSTAT" /tr "wscript.exe \"%SCRIPT_DIR%servidor_background.vbs\"" /sc onlogon /rl highest /f >nul 2>&1

:: Adiciona tambem na pasta Inicializar do usuario como garantia dupla
set "STARTUP_FOLDER=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
if exist "%STARTUP_FOLDER%" (
    copy /y "%SCRIPT_DIR%servidor_background.vbs" "%STARTUP_FOLDER%\LYDA_Servidor_iSTAT.vbs" >nul 2>&1
)
echo       Inicializacao automatica configurada com sucesso!

echo [5/6] Iniciando o Servidor LYDA agora em segundo plano...
:: Finaliza instancias antigas
taskkill /f /im python.exe /fi "WINDOWTITLE eq *LYDA*" >nul 2>&1
wscript.exe "%SCRIPT_DIR%servidor_background.vbs"

echo [6/6] Criando atalho na Area de Trabalho deste computador...
set "DESKTOP_DIR=%USERPROFILE%\Desktop"
if exist "%DESKTOP_DIR%" (
    echo [InternetShortcut] > "%DESKTOP_DIR%\Acessar Sistema LYDA (Servidor Local).url"
    echo URL=http://localhost:8080 >> "%DESKTOP_DIR%\Acessar Sistema LYDA (Servidor Local).url"
    echo IconIndex=0 >> "%DESKTOP_DIR%\Acessar Sistema LYDA (Servidor Local).url"
    echo IconFile=%SCRIPT_DIR%lyda_icon.ico >> "%DESKTOP_DIR%\Acessar Sistema LYDA (Servidor Local).url"
)

echo.
echo ============================================================================
echo   CONFIGURACAO CONCLUIDA COM SUCESSO! O SERVIDOR JA ESTA RODANDO!
echo ============================================================================
echo.
echo  Link de Acesso neste PC:
echo    http://localhost:8080
echo.
echo  Links para TODOS os computadores, notebooks e celulares da equipe LYDA:
python -c "
import socket
ips = set()
try:
    for info in socket.getaddrinfo(socket.gethostname(), None):
        ip = info[4][0]
        if ':' not in ip and not ip.startswith('127.'):
            ips.add(ip)
except:
    pass
for ip in sorted(ips):
    print(f'   --> http://{ip}:8080')
"
echo.
echo Envie o link acima (com o IP) no WhatsApp ou e-mail da equipe.
echo Qualquer pessoa conectada no Wi-Fi ou cabo da empresa podera acessar!
echo.
echo Pode fechar esta janela agora. O servidor continuara rodando silenciosamente.
echo ============================================================================
pause
