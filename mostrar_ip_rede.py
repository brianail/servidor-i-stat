# -*- coding: utf-8 -*-
"""
Utilitário para identificar e exibir os links de acesso na rede local
para o Servidor LYDA i-STAT.
"""
import os
import socket
import sys

def get_lan_ips():
    ips = set()
    # Metodo 1: getaddrinfo pelo hostname
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None):
            ip = info[4][0]
            if ":" not in ip and not ip.startswith("127."):
                ips.add(ip)
    except Exception:
        pass

    # Metodo 2: Socket UDP conectado para detectar IP da rota ativa
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith("127."):
            ips.add(ip)
    except Exception:
        pass

    # Metodo 3: Fallback 1.1.1.1
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("1.1.1.1", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith("127."):
            ips.add(ip)
    except Exception:
        pass

    return sorted(ips)

def main():
    port = os.environ.get("LYDA_WEB_PORT", "8080")
    ips = get_lan_ips()

    print("============================================================================")
    print("  LINKS DE ACESSO AO SISTEMA LYDA i-STAT")
    print("============================================================================")
    print()
    print(f"  [1] Para usar NESTE computador (Servidor):")
    print(f"      http://localhost:{port}")
    print()
    print(f"  [2] Para a EQUIPE acessar (outros computadores, notebooks e celulares):")
    if ips:
        for ip in ips:
            print(f"      --> http://{ip}:{port}")
    else:
        print(f"      --> http://localhost:{port}")
    print()
    print("  Dica: Qualquer pessoa conectada no mesmo Wi-Fi ou rede da empresa")
    print("        consegue abrir pelo navegador usando o link [2] acima.")
    print("============================================================================")

if __name__ == "__main__":
    main()
