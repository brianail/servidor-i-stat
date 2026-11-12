#!/bin/bash
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"
if [ -d "$DIR/LYDA i-STAT Estoque.app" ]; then
    open -n "$DIR/LYDA i-STAT Estoque.app"
else
    nohup python3 "$DIR/main.py" >/dev/null 2>&1 &
fi
osascript -e 'tell application "Terminal" to close (every window whose name contains "ABRIR_NO_MAC")' >/dev/null 2>&1 &
exit 0
