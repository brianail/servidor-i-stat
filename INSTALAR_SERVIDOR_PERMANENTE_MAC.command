#!/bin/bash
cd "$(dirname "$0")"
DIR="$(pwd)"

echo "============================================================================"
echo "  LYDA — INSTALADOR DO SERVIDOR LOCAL PERMANENTE (MACOS)"
echo "============================================================================"
echo ""

PYTHON_BIN="$(which python3)"
if [ -z "$PYTHON_BIN" ]; then
    PYTHON_BIN="/usr/bin/python3"
fi

PLIST_DIR="$HOME/Library/LaunchAgents"
mkdir -p "$PLIST_DIR"
PLIST_FILE="$PLIST_DIR/com.lyda.istat.server.plist"

cat > "$PLIST_FILE" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.lyda.istat.server</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON_BIN</string>
        <string>$DIR/web_server.py</string>
        <string>--no-browser</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$DIR</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$HOME/Library/Logs/lyda_istat_server.log</string>
    <key>StandardErrorPath</key>
    <string>$HOME/Library/Logs/lyda_istat_server_err.log</string>
</dict>
</plist>
PLISTEOF

launchctl unload "$PLIST_FILE" 2>/dev/null || true
launchctl load "$PLIST_FILE"

echo "Servidor registrado com sucesso no LaunchAgents do macOS!"
echo "O servidor iniciará automaticamente com o Mac e renascerá caso seja fechado."
echo ""
echo "Links de acesso na rede local:"
"$PYTHON_BIN" -c "
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
echo ""
read -p "Pressione Enter para concluir..."
