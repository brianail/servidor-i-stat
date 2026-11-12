#!/bin/bash
PLIST_FILE="$HOME/Library/LaunchAgents/com.lyda.istat.server.plist"
launchctl unload "$PLIST_FILE" 2>/dev/null || true
pkill -f "web_server.py" 2>/dev/null || true
echo "Servidor LYDA desativado."
read -p "Pressione Enter para fechar..."
