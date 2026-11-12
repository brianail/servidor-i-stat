#!/bin/bash
cd "$(dirname "$0")"
DIR="$(pwd)"

echo "============================================================================"
echo "  LYDA — ATUALIZADOR DO SISTEMA VIA GIT (MACOS)"
echo "============================================================================"
echo ""

BACKUP_DIR="$DIR/dados_producao_backup/backup_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"
cp "$DIR"/lyda_istat_*.json "$BACKUP_DIR/" 2>/dev/null || true
cp "$DIR"/lyda_zebra_web_config.json "$BACKUP_DIR/" 2>/dev/null || true
echo "Backup de seguranca salvo em: $BACKUP_DIR"

echo "Baixando atualizacoes do Git..."
git pull origin main 2>/dev/null || git pull origin master 2>/dev/null || git pull

# Restaura o banco de dados local para nunca sobrescrever com dados antigos do git
cp "$BACKUP_DIR"/lyda_istat_*.json "$DIR/" 2>/dev/null || true
cp "$BACKUP_DIR"/lyda_zebra_web_config.json "$DIR/" 2>/dev/null || true

PLIST_FILE="$HOME/Library/LaunchAgents/com.lyda.istat.server.plist"
if [ -f "$PLIST_FILE" ]; then
    launchctl unload "$PLIST_FILE" 2>/dev/null || true
    launchctl load "$PLIST_FILE"
fi

echo ""
echo "Sistema atualizado com sucesso!"
read -p "Pressione Enter para fechar..."
