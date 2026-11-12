@echo off
chcp 65001 >nul
cd /d "%~dp0"
set SCRIPT_DIR=%~dp0

echo ============================================================================
echo   LYDA — ATUALIZADOR DO SISTEMA VIA GIT (SERVIDOR)
echo ============================================================================
echo.
echo Este script vai:
echo 1. Pausar o servidor temporariamente para atualizar
echo 2. Fazer um backup de seguranca de todos os dados e cadastros atuais
echo 3. Baixar as novidades do Git (git pull)
echo 4. Manter 100%% os dados do servidor intactos (sem perder nenhum cadastro)
echo 5. Atualizar bibliotecas necessarias
echo 6. Reiniciar o servidor automaticamente em segundo plano
echo.

set "BACKUP_DIR=%SCRIPT_DIR%dados_producao_backup"
if not exist "%BACKUP_DIR%" mkdir "%BACKUP_DIR%"
set NOW=%date:~-4%%date:~3,2%%date:~0,2%_%time:~0,2%%time:~3,2%%time:~6,2%
set NOW=%NOW: =0%
set "SNAPSHOT_DIR=%BACKUP_DIR%\backup_%NOW%"
mkdir "%SNAPSHOT_DIR%"

echo [1/5] Pausando servidor temporariamente...
taskkill /f /im python.exe /fi "WINDOWTITLE eq *LYDA*" >nul 2>&1
wmic process where "commandline like '%web_server.py%'" call terminate >nul 2>&1

echo [2/5] Criando backup de seguranca do banco de dados em:
echo       %SNAPSHOT_DIR%
copy /y "%SCRIPT_DIR%lyda_istat_*.json" "%SNAPSHOT_DIR%\" >nul 2>&1
copy /y "%SCRIPT_DIR%lyda_zebra_web_config.json" "%SNAPSHOT_DIR%\" >nul 2>&1

echo [3/5] Baixando atualizacoes do Git (git pull)...
git stash >nul 2>&1
git pull origin main 2>nul || git pull origin master 2>nul || git pull

echo [4/5] Garantindo a integridade dos dados da producao local...
copy /y "%SNAPSHOT_DIR%\lyda_istat_*.json" "%SCRIPT_DIR%\" >nul 2>&1
copy /y "%SNAPSHOT_DIR%\lyda_zebra_web_config.json" "%SCRIPT_DIR%\" >nul 2>&1

echo [5/5] Verificando dependencias e reiniciando o servidor em segundo plano...
set "PYTHON_BIN=python"
if exist "%SCRIPT_DIR%lyda_python_path.txt" (
    set /p PYTHON_BIN=<"%SCRIPT_DIR%lyda_python_path.txt"
)
"%PYTHON_BIN%" --version >nul 2>&1
if %errorlevel% neq 0 (
    py -3 --version >nul 2>&1 && set "PYTHON_BIN=py -3"
)

"%PYTHON_BIN%" -m pip install -r requirements.txt >nul 2>&1
wscript.exe "%SCRIPT_DIR%servidor_background.vbs"

echo.
echo ============================================================================
echo   ATUALIZACAO CONCLUIDA COM SUCESSO!
echo   O Servidor LYDA ja esta rodando atualizado em segundo plano.
echo ============================================================================
pause
