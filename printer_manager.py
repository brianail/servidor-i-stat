"""
Módulo de envio RAW ZPL para impressoras Zebra (ZD230 e similares).
Suporta:
1. Impressora instalada no Windows via USB (win32print RAW API ou compartilhamento local)
2. Impressora em Rede TCP/IP (Porta 9100 JetDirect)
3. Impressora USB no Mac/Linux via comando `lp -o raw`
4. Salvamento direto em arquivo .zpl
"""

import os
import platform
import socket
import subprocess
from typing import List, Tuple


def list_system_printers() -> List[str]:
    """Lista todas as impressoras instaladas no sistema operacional."""
    sys_name = platform.system().lower()
    printers: List[str] = []

    if sys_name == "windows":
        # 1. Tenta via pywin32 (win32print)
        try:
            import win32print  # type: ignore
            flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
            for p in win32print.EnumPrinters(flags):
                # p[2] é o nome da impressora
                if len(p) > 2 and p[2]:
                    printers.append(str(p[2]))
            if printers:
                return sorted(list(set(printers)), key=lambda x: ("zebra" not in x.lower() and "zd230" not in x.lower(), x))
        except Exception:
            pass

        # 2. Fallback via PowerShell Get-Printer (nativo do Windows 10/11 sem precisar de lib extra)
        try:
            cmd = ["powershell", "-NoProfile", "-Command", "Get-Printer | Select-Object -ExpandProperty Name"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=5, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    name = line.strip()
                    if name:
                        printers.append(name)
        except Exception:
            pass

    else:
        # macOS / Linux via lpstat -a
        try:
            res = subprocess.run(["lpstat", "-a"], capture_output=True, text=True, timeout=4)
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    parts = line.strip().split()
                    if parts:
                        printers.append(parts[0])
        except Exception:
            pass

    # Prioriza impressoras com "zebra", "zd230" ou "zdesigner" no topo da lista
    unique_printers = sorted(
        list(set(printers)),
        key=lambda x: (
            not any(k in x.lower() for k in ("zebra", "zd230", "zdesigner", "zpl")),
            x.lower(),
        ),
    )
    return unique_printers


def send_zpl_to_windows_printer(printer_name: str, zpl_data: str) -> Tuple[bool, str]:
    """
    Envia comandos ZPL II em modo RAW direto para a fila da impressora no Windows,
    sem passar pelo renderizador gráfico GDI (garante nitidez máxima na Zebra ZD230).
    """
    raw_bytes = zpl_data.encode("utf-8")

    # Tentativa 1: win32print (pywin32)
    try:
        import win32print  # type: ignore

        h_printer = win32print.OpenPrinter(printer_name)
        try:
            h_job = win32print.StartDocPrinter(h_printer, 1, ("Lyda_ZPL_Labels", None, "RAW"))
            try:
                win32print.StartPagePrinter(h_printer)
                win32print.WritePrinter(h_printer, raw_bytes)
                win32print.EndPagePrinter(h_printer)
            finally:
                win32print.EndDocPrinter(h_printer)
        finally:
            win32print.ClosePrinter(h_printer)
        return True, f"Enviado com sucesso via Windows RAW (win32print) para '{printer_name}'."
    except ImportError:
        pass
    except Exception as e:
        return False, f"Erro ao imprimir em '{printer_name}' via win32print: {e}"

    # Tentativa 2: Fallback nativo em ctypes chamando winspool.drv (funciona mesmo sem pywin32 instalado!)
    try:
        import ctypes
        from ctypes import wintypes

        winspool = ctypes.WinDLL("winspool.drv", use_last_error=True)

        class DOC_INFO_1(ctypes.Structure):
            _fields_ = [
                ("pDocName", wintypes.LPWSTR),
                ("pOutputFile", wintypes.LPWSTR),
                ("pDatatype", wintypes.LPWSTR),
            ]

        winspool.OpenPrinterW.argtypes = [wintypes.LPWSTR, ctypes.POINTER(wintypes.HANDLE), wintypes.LPVOID]
        winspool.OpenPrinterW.restype = wintypes.BOOL

        winspool.StartDocPrinterW.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(DOC_INFO_1)]
        winspool.StartDocPrinterW.restype = wintypes.DWORD

        winspool.StartPagePrinter.argtypes = [wintypes.HANDLE]
        winspool.StartPagePrinter.restype = wintypes.BOOL

        winspool.WritePrinter.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        winspool.WritePrinter.restype = wintypes.BOOL

        winspool.EndPagePrinter.argtypes = [wintypes.HANDLE]
        winspool.EndPagePrinter.restype = wintypes.BOOL

        winspool.EndDocPrinter.argtypes = [wintypes.HANDLE]
        winspool.EndDocPrinter.restype = wintypes.BOOL

        winspool.ClosePrinter.argtypes = [wintypes.HANDLE]
        winspool.ClosePrinter.restype = wintypes.BOOL

        h_printer = wintypes.HANDLE()
        if not winspool.OpenPrinterW(printer_name, ctypes.byref(h_printer), None):
            err = ctypes.get_last_error()
            return False, f"Não foi possível abrir a impressora '{printer_name}' (Código Win32: {err})."

        try:
            doc_info = DOC_INFO_1("Lyda_Etiquetas_ZPL", None, "RAW")
            job_id = winspool.StartDocPrinterW(h_printer, 1, ctypes.byref(doc_info))
            if job_id == 0:
                err = ctypes.get_last_error()
                return False, f"Falha ao iniciar documento RAW na impressora (Código Win32: {err})."
            try:
                winspool.StartPagePrinter(h_printer)
                written = wintypes.DWORD(0)
                buf = ctypes.create_string_buffer(raw_bytes)
                ok = winspool.WritePrinter(h_printer, buf, len(raw_bytes), ctypes.byref(written))
                winspool.EndPagePrinter(h_printer)
                if not ok:
                    err = ctypes.get_last_error()
                    return False, f"Falha ao gravar bytes ZPL na impressora (Código Win32: {err})."
            finally:
                winspool.EndDocPrinter(h_printer)
        finally:
            winspool.ClosePrinter(h_printer)

        return True, f"Enviado com sucesso via WinSpool RAW ({len(raw_bytes)} bytes) para '{printer_name}'!"
    except Exception as e:
        return False, f"Falha no envio RAW para Windows: {e}"


def send_zpl_to_network_printer(ip_address: str, port: int, zpl_data: str, timeout: float = 5.0) -> Tuple[bool, str]:
    """Envia ZPL diretamente via socket TCP/IP (porta padrão Zebra: 9100)."""
    try:
        with socket.create_connection((ip_address.strip(), int(port)), timeout=timeout) as sock:
            sock.sendall(zpl_data.encode("utf-8"))
        return True, f"Enviado com sucesso via Rede TCP/IP ({ip_address}:{port})."
    except Exception as e:
        return False, f"Falha ao conectar na Zebra em {ip_address}:{port} -> {e}"


def send_zpl_to_cups_printer(printer_name: str, zpl_data: str) -> Tuple[bool, str]:
    """Envia ZPL em modo RAW via CUPS (`lp -d <printer> -o raw`) no macOS / Linux."""
    try:
        res = subprocess.run(
            ["lp", "-d", printer_name, "-o", "raw"],
            input=zpl_data.encode("utf-8"),
            capture_output=True,
            timeout=10,
        )
        if res.returncode == 0:
            return True, f"Enviado via CUPS RAW para '{printer_name}'."
        err_msg = res.stderr.decode("utf-8", errors="replace").strip()
        return False, f"Erro no comando lp: {err_msg}"
    except Exception as e:
        return False, f"Erro ao enviar via CUPS: {e}"


def dispatch_zpl_print(
    mode: str,
    zpl_data: str,
    printer_name: str = "",
    ip_address: str = "",
    port: int = 9100,
) -> Tuple[bool, str]:
    """
    Roteador principal de impressão:
    - mode == 'USB_DRIVER': envia via fila do SO (Windows WinSpool RAW ou CUPS RAW)
    - mode == 'NETWORK_IP': envia via TCP/IP direto para a Zebra
    """
    if not zpl_data.strip():
        return False, "Nenhum código ZPL gerado para imprimir."

    if mode in ("NETWORK_IP", "TCP_IP"):
        if not ip_address.strip():
            return False, "Informe o endereço IP da impressora Zebra."
        return send_zpl_to_network_printer(ip_address, port, zpl_data)

    # Modo USB / Driver instalado no Sistema
    if not printer_name.strip():
        return False, "Selecione uma impressora na lista antes de imprimir."

    sys_name = platform.system().lower()
    if sys_name == "windows":
        return send_zpl_to_windows_printer(printer_name, zpl_data)
    else:
        return send_zpl_to_cups_printer(printer_name, zpl_data)

