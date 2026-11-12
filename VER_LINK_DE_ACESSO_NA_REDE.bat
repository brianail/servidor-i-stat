@echo off
chcp 65001 >nul
title LYDA — LINKS DE ACESSO NA REDE LOCAL
echo ============================================================================
echo   LYDA — LINKS DE ACESSO DO SERVIDOR NA REDE LOCAL
echo ============================================================================
echo.
python -c "
import socket
ips = set()
try:
    for info in socket.getaddrinfo(socket.gethostname(), None):
        ip = info[4][0]
        if ':' not in ip and not ip.startswith('127.'):
            ips.add(ip)
except:
    pass
print('Link para usar NESTE computador (Servidor):')
print('  http://localhost:8080\n')
print('Link para enviar para a EQUIPE (outros PCs, notebooks e celulares na rede):')
for ip in sorted(ips):
    print(f'  --> http://{ip}:8080')
"
echo.
echo ============================================================================
echo Pressione qualquer tecla para abrir o sistema no navegador...
pause >nul
start http://localhost:8080
