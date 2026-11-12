"""
Carregamento de planilhas de equipamentos (.xlsx, .xls, .csv) e gerador de planilha modelo.
"""

import csv
import os
from typing import List, Dict, Any, Tuple


SAMPLE_EQUIPMENTS = [
    {"CODIGO": "EQP-00101", "EQUIPAMENTO": "Monitor Dell 24 Pol", "PATRIMONIO": "PAT-2026-001", "SETOR": "TI / Suporte", "RESPONSAVEL": "Carlos"},
    {"CODIGO": "EQP-00102", "EQUIPAMENTO": "Notebook Lenovo ThinkPad", "PATRIMONIO": "PAT-2026-002", "SETOR": "Financeiro", "RESPONSAVEL": "Ana Paula"},
    {"CODIGO": "EQP-00103", "EQUIPAMENTO": "Impressora Zebra ZD230", "PATRIMONIO": "PAT-2026-003", "SETOR": "Expedição", "RESPONSAVEL": "Marcos"},
    {"CODIGO": "EQP-00104", "EQUIPAMENTO": "Leitor Código de Barras USB", "PATRIMONIO": "PAT-2026-004", "SETOR": "Almoxarifado", "RESPONSAVEL": "Marcos"},
    {"CODIGO": "EQP-00105", "EQUIPAMENTO": "Ar Condicionado Split 12k", "PATRIMONIO": "PAT-2026-005", "SETOR": "Recepção", "RESPONSAVEL": "Administração"},
    {"CODIGO": "EQP-00106", "EQUIPAMENTO": "Nobreak SMS 1500VA", "PATRIMONIO": "PAT-2026-006", "SETOR": "Servidor", "RESPONSAVEL": "Carlos"},
    {"CODIGO": "EQP-00107", "EQUIPAMENTO": "Balança Digital Toledo", "PATRIMONIO": "PAT-2026-007", "SETOR": "Produção", "RESPONSAVEL": "Roberto"},
    {"CODIGO": "EQP-00108", "EQUIPAMENTO": "Switch Gigabit 24 Portas", "PATRIMONIO": "PAT-2026-008", "SETOR": "TI / Rack", "RESPONSAVEL": "Carlos"},
    {"CODIGO": "EQP-00109", "EQUIPAMENTO": "Cadeira Ergonômica Presidente", "PATRIMONIO": "PAT-2026-009", "SETOR": "Diretoria", "RESPONSAVEL": "Fernanda"},
    {"CODIGO": "EQP-00110", "EQUIPAMENTO": "Furadeira Industrial Bosch", "PATRIMONIO": "PAT-2026-010", "SETOR": "Manutenção", "RESPONSAVEL": "João"},
]


def load_spreadsheet(file_path: str, sheet_name: str = "") -> Tuple[List[str], List[Dict[str, Any]], List[str]]:
    """
    Lê um arquivo .xlsx, .xls ou .csv.
    Retorna: (lista_de_colunas, lista_de_dicionarios_linhas, lista_de_abas_disponiveis)
    """
    ext = os.path.splitext(file_path)[1].lower()

    if ext in (".xlsx", ".xls"):
        try:
            import pandas as pd  # type: ignore

            xls = pd.ExcelFile(file_path)
            sheet_names = [str(s) for s in xls.sheet_names]
            target_sheet = sheet_name if (sheet_name and sheet_name in sheet_names) else sheet_names[0]
            df = pd.read_excel(file_path, sheet_name=target_sheet, dtype=str)
            df = df.fillna("")
            columns = [str(c).strip() for c in df.columns]
            df.columns = columns
            records = df.to_dict(orient="records")
            return columns, records, sheet_names
        except ImportError:
            # Fallback usando openpyxl diretamente caso pandas não esteja presente
            import openpyxl  # type: ignore

            wb = openpyxl.load_workbook(file_path, data_only=True)
            sheet_names = list(wb.sheetnames)
            target_sheet = sheet_name if (sheet_name and sheet_name in sheet_names) else sheet_names[0]
            ws = wb[target_sheet]
            rows = list(ws.iter_rows(values_only=True))
            if not rows:
                return [], [], sheet_names
            columns = [str(c).strip() if c is not None else f"COL_{i+1}" for i, c in enumerate(rows[0])]
            records = []
            for r in rows[1:]:
                if all(cell is None or str(cell).strip() == "" for cell in r):
                    continue
                row_dict = {}
                for col_idx, col_name in enumerate(columns):
                    val = r[col_idx] if col_idx < len(r) else ""
                    row_dict[col_name] = "" if val is None else str(val).strip()
                records.append(row_dict)
            return columns, records, sheet_names

    # CSV / TXT
    encodings_to_try = ["utf-8-sig", "utf-8", "cp1252", "latin1"]
    for enc in encodings_to_try:
        try:
            with open(file_path, "r", encoding=enc, newline="") as f:
                sample = f.read(4096)
                f.seek(0)
                try:
                    dialect = csv.Sniffer().sniff(sample, delimiters=";,|\t")
                except Exception:
                    dialect = csv.excel
                reader = csv.DictReader(f, dialect=dialect)
                if not reader.fieldnames:
                    return [], [], ["CSV"]
                columns = [str(c).strip() for c in reader.fieldnames if c is not None]
                records = []
                for row in reader:
                    clean_row = {str(k).strip(): (str(v).strip() if v is not None else "") for k, v in row.items() if k is not None}
                    if any(clean_row.values()):
                        records.append(clean_row)
                return columns, records, ["CSV"]
        except UnicodeDecodeError:
            continue

    raise ValueError("Não foi possível ler o arquivo. Verifique se é um Excel (.xlsx) ou CSV válido.")


def create_sample_spreadsheet(output_path: str) -> str:
    """Cria uma planilha Excel (.xlsx) ou CSV de exemplo para a Lyda testar imediatamente."""
    ext = os.path.splitext(output_path)[1].lower()
    if ext == ".xlsx":
        try:
            import pandas as pd  # type: ignore
            df = pd.DataFrame(SAMPLE_EQUIPMENTS)
            df.to_excel(output_path, index=False)
            return output_path
        except Exception:
            pass
        try:
            import openpyxl  # type: ignore
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Equipamentos"
            headers = list(SAMPLE_EQUIPMENTS[0].keys())
            ws.append(headers)
            for item in SAMPLE_EQUIPMENTS:
                ws.append([item[h] for h in headers])
            wb.save(output_path)
            return output_path
        except Exception:
            output_path = os.path.splitext(output_path)[0] + ".csv"

    # Fallback CSV separado por ponto-e-vírgula (abre direto no Excel em português)
    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        headers = list(SAMPLE_EQUIPMENTS[0].keys())
        writer = csv.DictWriter(f, fieldnames=headers, delimiter=";")
        writer.writeheader()
        writer.writerows(SAMPLE_EQUIPMENTS)
    return output_path

