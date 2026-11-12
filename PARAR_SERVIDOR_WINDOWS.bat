@echo off
chcp 65001 >nul
echo Finalizando processos do Servidor LYDA i-STAT em segundo plano...
taskkill /f /im python.exe /fi "WINDOWTITLE eq *LYDA*" >nul 2>&1
wmic process where "commandline like '%web_server.py%'" call terminate >nul 2>&1
wmic process where "commandline like '%watchdog_server.bat%'" call terminate >nul 2>&1
echo Servidor finalizado com sucesso.
pause
