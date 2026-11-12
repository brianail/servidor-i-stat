@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo Criando atalho "LYDA i-STAT Estoque" na Area de Trabalho com icone oficial e sem terminal...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws = New-Object -ComObject WScript.Shell; ^
   $desktop = [Environment]::GetFolderPath('Desktop'); ^
   $sc = $ws.CreateShortcut(\"$desktop\LYDA i-STAT Estoque.lnk\"); ^
   $sc.TargetPath = 'wscript.exe'; ^
   $sc.Arguments = '\"%~dp0ABRIR_SEM_TERMINAL_WINDOWS.vbs\"'; ^
   $sc.WorkingDirectory = '%~dp0'; ^
   $sc.IconLocation = '%~dp0lyda_icon.ico'; ^
   $sc.Description = 'Sistema de Controle de Estoque i-STAT e Impressao Zebra ZD230 - LYDA'; ^
   $sc.Save()"

echo.
echo Atalho criado com sucesso na sua Area de Trabalho!
pause

