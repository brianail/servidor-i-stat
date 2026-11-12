@echo off
chcp 65001 >nul
title Gerador de Executavel (.EXE) com Icone Oficial - LYDA i-STAT Estoque
cd /d "%~dp0"

echo ========================================================
echo   GERANDO EXECUTAVEL (.EXE) COM ICONE E SEM TERMINAL
echo ========================================================
echo.

if not exist ".venv" (
    python -m venv .venv
)
call .venv\Scripts\activate.bat
pip install --upgrade pip
pip install openpyxl Pillow pywin32 pyinstaller

python icon_builder.py

echo.
echo Compilando LYDA_iSTAT_Estoque.exe (Sem janela de terminal e com icone oficial)...
pyinstaller --noconfirm --onefile --windowed --noconsole --icon="lyda_icon.ico" --add-data "lyda_logo_cropped.png;." --add-data "lyda_app_icon.png;." --add-data "lyda_icon.ico;." --name "LYDA_iSTAT_Estoque" main.py

echo.
echo ========================================================
echo   CONCLUIDO COM SUCESSO!
echo   O executavel pronto (com icone da Lyda e sem terminal)
echo   esta em: dist\LYDA_iSTAT_Estoque.exe
echo ========================================================
pause
