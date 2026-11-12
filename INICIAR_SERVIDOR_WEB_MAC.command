#!/bin/bash
cd "$(dirname "$0")"
echo "============================================================================"
echo "  LYDA — SERVIDOR WEB DE CONTROLE DE ESTOQUE, CLIENTES & ROTA i-STAT"
echo "============================================================================"
if [ -x "/opt/anaconda3/bin/python3" ]; then
    PY="/opt/anaconda3/bin/python3"
else
    PY="python3"
fi
"$PY" web_server.py

