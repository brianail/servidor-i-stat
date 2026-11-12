@echo off
chcp 65001 >nul
cd /d "%~dp0"
set SCRIPT_DIR=%~dp0

echo ============================================================================
echo   LYDA — PERSONALIZADOR DE NOME DO SERVIDOR LOCAL
echo ============================================================================
echo.
echo Este utilitario permite trocar o "localhost" por um nome personalizado
echo para a sua empresa (exemplo: http://lyda:8080 ou http://servidor-lyda:8080).
echo.

:: Verifica se esta executando como Administrador
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [AVISO] Solicitando permissao de Administrador...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process cmd.exe -ArgumentList '/k cd /d \"%~dp0\" && \"%~f0\"' -Verb RunAs"
    exit /b
)

set /p NOME_ESCOLHIDO="Digite o nome desejado (letras e tracos, ex: lyda ou servidor-lyda): "
if "%NOME_ESCOLHIDO%"=="" set "NOME_ESCOLHIDO=servidor-lyda"

:: Remove espacos acidentais
set NOME_ESCOLHIDO=%NOME_ESCOLHIDO: =-%

echo.
echo [1/3] Configurando o apelido "%NOME_ESCOLHIDO%" no arquivo hosts deste computador...
powershell -NoProfile -Command "$hostsPath = 'C:\Windows\System32\drivers\etc\hosts'; $content = Get-Content $hostsPath -Raw -ErrorAction SilentlyContinue; if ($content -notmatch '127\.0\.0\.1\s+%NOME_ESCOLHIDO%') { Add-Content -Path $hostsPath -Value \"`n127.0.0.1    %NOME_ESCOLHIDO%`n127.0.0.1    lyda\" }"
echo       Apelido configurado com sucesso!

echo.
echo [2/3] Atualizando atalho da Area de Trabalho...
set "DESKTOP_DIR=%USERPROFILE%\Desktop"
if exist "%DESKTOP_DIR%" (
    echo [InternetShortcut] > "%DESKTOP_DIR%\Acessar Sistema LYDA (%NOME_ESCOLHIDO%).url"
    echo URL=http://%NOME_ESCOLHIDO%:8080 >> "%DESKTOP_DIR%\Acessar Sistema LYDA (%NOME_ESCOLHIDO%).url"
    echo IconIndex=0 >> "%DESKTOP_DIR%\Acessar Sistema LYDA (%NOME_ESCOLHIDO%).url"
    if exist "%SCRIPT_DIR%lyda_icon.ico" (
        echo IconFile=%SCRIPT_DIR%lyda_icon.ico >> "%DESKTOP_DIR%\Acessar Sistema LYDA (%NOME_ESCOLHIDO%).url"
    )
)
echo       Atalho atualizado com o novo endereco!

echo.
echo [3/3] Deseja tambem renomear o Computador no Windows para "%NOME_ESCOLHIDO%"?
echo       (Isso permite que TODOS os outros computadores da rede acessem por http://%NOME_ESCOLHIDO%:8080)
echo.
set /p RENOMEAR_PC="Renomear o computador agora? (S/N) [padrao: S]: "
if /i "%RENOMEAR_PC%"=="" set RENOMEAR_PC=S
if /i "%RENOMEAR_PC%"=="S" (
    powershell -NoProfile -Command "Rename-Computer -NewName '%NOME_ESCOLHIDO%' -Force -ErrorAction SilentlyContinue"
    echo.
    echo Computador renomeado para "%NOME_ESCOLHIDO%"!
    echo Para que a rede inteira reconheca o novo nome, basta reiniciar o Windows quando for conveniente.
)

echo.
echo ============================================================================
echo   CONFIGURACAO CONCLUIDA!
echo ============================================================================
echo.
echo  Novo link no navegador deste computador:
echo    --> http://%NOME_ESCOLHIDO%:8080
echo    --> http://lyda:8080
echo.
echo  Link para a equipe na rede (apos reiniciar o computador):
echo    --> http://%NOME_ESCOLHIDO%:8080
echo.
echo ============================================================================
pause

