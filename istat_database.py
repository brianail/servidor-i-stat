"""
Motor de Banco de Dados e Sincronização com a Planilha "Mapeamento Equipamento i-STAT - LYDA.xlsx".
Transforma automaticamente as abas ('Venda', 'Comodato ', ' Propriedade LYda') em registros individuais
de equipamentos onde cada ANALISADOR, IMPRESSORA, SIMULADOR e DOWNLOADER possui seu próprio Serial,
Código de Barras limpo para bipar, Cliente/Localização, Cidade/UF, Setor, Modalidade, Status e Histórico.
"""

import getpass
import json
import os
import re
import shutil
import socket
import time
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple


from rota_enfermeira import DEFAULT_LYDA_SEDE_ADDRESS, get_suggested_hospital_address, compute_update_cycle_info


DEFAULT_EXCEL_FILENAME = "Mapeamento Equipamento i-STAT - LYDA.xlsx"
DB_JSON_FILENAME = "lyda_istat_db.json"
HISTORY_JSON_FILENAME = "lyda_istat_historico.json"
LOCAL_PC_CONFIG_FILENAME = "lyda_local_pc.json"

EQUIPMENT_TYPES = ["ANALISADOR", "IMPRESSORA", "SIMULADOR", "DOWNLOADER"]
MODALITIES = ["VENDA", "COMODATO", "ALUGUEL", "PROPRIEDADE LYDA"]
STATUS_OPTIONS = [
    "ATIVO NO CLIENTE",
    "ESTOQUE LYDA NOVOS",
    "ESTOQUE USADOS",
    "EM BACKUP",
    "EM MANUTENÇÃO / SP",
    "COM DEFEITO / AGUARDANDO REPARO",
    "EMPRESTADO / DEMONSTRAÇÃO",
    "DEVOLVIDO",
]
CONDICAO_FISICA_OPTIONS = [
    "PERFEITO / FUNCIONANDO 100%",
    "COM DEFEITO (VER OBSERVAÇÕES)",
    "AGUARDANDO TESTE / TRIAGEM",
    "AGUARDANDO ORÇAMENTO / SP",
    "FALTA ACESSÓRIO / CABO",
]
MOVIMENTO_ACOES = [
    "SAÍDA DA LYDA -> CLIENTE / HOSPITAL",
    "RETORNO -> ESTOQUE LYDA",
    "ENVIO -> MANUTENÇÃO / ASSISTÊNCIA (SP)",
    "RETORNO DE MANUTENÇÃO -> ESTOQUE LYDA",
    "REGISTRAR DEFEITO / OCORRÊNCIA TÉCNICA",
    "CONFERÊNCIA DE INVENTÁRIO (BIP)",
]


def clean_barcode_serial(raw_serial: Any) -> str:
    """
    Extrai o número de série limpo para o Código de Barras (para bater 100% no leitor ao bipar).
    Exemplos reais da planilha da Lyda:
    - "(21) 426086" -> "426086"
    - "(21)426086"  -> "426086"
    - "S-119719"    -> "S-119719"
    - "S137045"     -> "S137045"
    - "DRC110815"   -> "DRC110815"
    - 401348        -> "401348"
    """
    if raw_serial is None:
        return ""
    s = str(raw_serial).strip()
    if not s or s in ("-", "--", "None", "nan", "N/A", "NÃO", "SIM"):
        return ""
    # Remove prefixo GS1 (21) usado em etiquetas da Abbott i-STAT quando presente
    s_no_gs1 = re.sub(r"^\(\s*21\s*\)\s*", "", s)
    # Remove espaços internos extras mantendo hífens e alfanuméricos
    s_clean = re.sub(r"\s+", "", s_no_gs1)
    # Se veio como float do Excel ex: "401348.0"
    if s_clean.endswith(".0"):
        s_clean = s_clean[:-2]
    return s_clean.upper()


def format_raw_serial(raw_serial: Any) -> str:
    if raw_serial is None:
        return ""
    s = str(raw_serial).strip()
    if s.endswith(".0"):
        s = s[:-2]
    if s in ("-", "--", "None", "nan"):
        return ""
    return s


def normalize_equipment_type(raw_type: str) -> str:
    t = str(raw_type or "").strip().upper()
    if "ANALISADOR" in t:
        return "ANALISADOR"
    if "IMPRESSORA" in t:
        return "IMPRESSORA"
    if "SIMULADOR" in t:
        return "SIMULADOR"
    if "DOWNLOAD" in t or "DOWLOAD" in t:
        return "DOWNLOADER"
    return t or "ANALISADOR"


def infer_status(modality: str, location: str, status_col: str, obs: str, neg: str) -> str:
    combined = f"{location} {status_col} {obs} {neg}".upper()
    if "DEVOLVIDO" in combined:
        return "DEVOLVIDO"
    if any(k in combined for k in ("SP:", "CRITICALMED", "CONCERTO", "CONSERTO", "ERRO ", "ORÇAMENTO", "MANUTEN")):
        return "EM MANUTENÇÃO / SP"
    if "BACKUP" in combined or "BACK UP" in combined:
        return "EM BACKUP"
    if "NOVO" in combined and "ESTOQUE" in combined:
        return "ESTOQUE LYDA NOVOS"
    if "ESTOQUE" in combined:
        return "ESTOQUE USADOS"
    if "EMPRESTADO" in combined or "DEMONSTRA" in combined:
        return "EMPRESTADO / DEMONSTRAÇÃO"
    return "ATIVO NO CLIENTE"


def classify_item_row_state(item: Dict[str, Any]) -> str:
    """
    Classifica o estado visual do equipamento para cores e filtros rápidos:
    - 'DEFEITO': Em manutenção, com defeito registrado ou em SP/conserto
    - 'ESTOQUE': Disponível no estoque da Lyda (Sem Cliente / Estoque Lyda Novos / Estoque Usados)
    - 'ATIVO': Ativo em cliente / hospital
    """
    status = str(item.get("STATUS", "")).upper()
    cond = str(item.get("CONDICAO", "")).upper()
    defeito = str(item.get("DEFEITO", "")).strip()
    obs = str(item.get("OBSERVACOES", "")).upper()
    cliente = str(item.get("CLIENTE", "")).upper()

    if (
        defeito
        or "DEFEITO" in status
        or "MANUTEN" in status
        or "DEFEITO" in cond
        or "ORÇAMENTO" in cond
        or any(k in obs for k in ("[DEFEITO", "CONSERTO", "CONCERTO", "CRITICALMED", "ERRO "))
    ):
        return "DEFEITO"

    if (
        "SEM CLIENTE" in cliente
        or "ESTOQUE LYDA" in cliente
        or "LYDA ESTOQUE" in cliente
        or "ESTOQUE USADOS" in cliente
        or cliente in ("LYDA", "ESTOQUE", "LYDA COMERCIO IMPORTAÇÃO E EXPORTAÇÃO LTDA", "LYDA COMERCIO IMPORTACAO E EXPORTACAO LTDA")
        or status in ("ESTOQUE LYDA NOVOS", "ESTOQUE USADOS", "DEVOLVIDO", "EM BACKUP")
    ):
        return "ESTOQUE"

    return "ATIVO"


class IStatDatabaseManager:
    """
    Gerencia os equipamentos i-STAT (Analisador, Impressora, Simulador, Downloader)
    com persistência local ou em Pasta Compartilhada (Rede Local SMB / Google Drive / OneDrive / Dropbox),
    sincronização em tempo real entre múltiplos computadores sem conflito (Merge Atômico por Registro),
    identificação de Operador/Computador, backups automáticos diários e exportação Excel (.xlsx).
    """

    def __init__(self, workspace_dir: str):
        self.workspace_dir = workspace_dir
        self.local_pc_cfg_path = os.path.join(workspace_dir, LOCAL_PC_CONFIG_FILENAME)
        self.default_excel_path = os.path.join(workspace_dir, DEFAULT_EXCEL_FILENAME)

        try:
            self.pc_hostname = socket.gethostname() or "PC-LYDA"
        except Exception:
            self.pc_hostname = "PC-LYDA"
        try:
            default_user = getpass.getuser().upper()
        except Exception:
            default_user = "OPERADOR"

        local_cfg = self._load_local_pc_config()
        self.operador_atual: str = local_cfg.get("operador_atual", default_user) or default_user
        self.lyda_hq_address: str = local_cfg.get("lyda_hq_address", DEFAULT_LYDA_SEDE_ADDRESS) or DEFAULT_LYDA_SEDE_ADDRESS
        self.default_update_cycle_months: int = int(local_cfg.get("default_update_cycle_months", 6) or 6)
        self.sharepoint_backup_dir: str = local_cfg.get("sharepoint_backup_dir", "").strip()
        self.sharepoint_backup_time: str = local_cfg.get("sharepoint_backup_time", "18:00").strip() or "18:00"
        self.sharepoint_auto_sync: bool = bool(local_cfg.get("sharepoint_auto_sync", True))
        self.last_sharepoint_backup_at: str = local_cfg.get("last_sharepoint_backup_at", "")
        self.last_sharepoint_backup_status: str = local_cfg.get("last_sharepoint_backup_status", "")
        configured_shared = local_cfg.get("shared_db_dir", "").strip()
        if configured_shared and os.path.isdir(configured_shared):
            self.shared_db_dir = configured_shared
        else:
            self.shared_db_dir = workspace_dir

        self._update_paths_for_shared_dir()
        self.items: List[Dict[str, Any]] = []
        self.history: List[Dict[str, Any]] = []
        self.clients: List[Dict[str, Any]] = []
        self.operators: List[str] = ["EXPEDIÇÃO LYDA", "ASSISTÊNCIA TÉCNICA", "ESTOQUE LYDA", "ENFERMEIRA LYDA"]
        self._last_db_mtime: float = 0.0
        self._last_hist_mtime: float = 0.0
        self.load()
        if self.operador_atual and self.operador_atual not in self.operators:
            self.operators.insert(0, self.operador_atual)
        self.ensure_daily_backup()

    def _load_local_pc_config(self) -> Dict[str, Any]:
        if os.path.exists(self.local_pc_cfg_path):
            try:
                with open(self.local_pc_cfg_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def save_local_pc_config(self):
        try:
            payload = {
                "shared_db_dir": self.shared_db_dir,
                "operador_atual": self.operador_atual,
                "lyda_hq_address": self.lyda_hq_address,
                "default_update_cycle_months": self.default_update_cycle_months,
                "pc_hostname": self.pc_hostname,
                "sharepoint_backup_dir": getattr(self, "sharepoint_backup_dir", ""),
                "sharepoint_backup_time": getattr(self, "sharepoint_backup_time", "18:00"),
                "sharepoint_auto_sync": getattr(self, "sharepoint_auto_sync", True),
                "last_sharepoint_backup_at": getattr(self, "last_sharepoint_backup_at", ""),
                "last_sharepoint_backup_status": getattr(self, "last_sharepoint_backup_status", ""),
            }
            with open(self.local_pc_cfg_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _update_paths_for_shared_dir(self):
        os.makedirs(self.shared_db_dir, exist_ok=True)
        self.db_path = os.path.join(self.shared_db_dir, DB_JSON_FILENAME)
        self.history_path = os.path.join(self.shared_db_dir, HISTORY_JSON_FILENAME)
        self.clients_path = os.path.join(self.shared_db_dir, "lyda_istat_clientes.json")
        self.operators_path = os.path.join(self.shared_db_dir, "lyda_istat_operadores.json")
        self.users_path = os.path.join(self.shared_db_dir, "lyda_istat_usuarios.json")
        self.audit_logs_path = os.path.join(self.shared_db_dir, "lyda_istat_audit_logs.json")
        self.backups_dir = os.path.join(self.shared_db_dir, "backups_automaticos")
        os.makedirs(self.backups_dir, exist_ok=True)

    def add_operator(self, name: str) -> List[str]:
        clean_name = name.strip().upper()
        if clean_name and clean_name not in self.operators:
            self.operators.append(clean_name)
            self._save_operators()
        return self.operators

    def remove_operator(self, name: str) -> List[str]:
        clean_name = name.strip().upper()
        if clean_name in self.operators and len(self.operators) > 1:
            self.operators.remove(clean_name)
            self._save_operators()
        return self.operators

    def _save_operators(self):
        try:
            with open(self.operators_path, "w", encoding="utf-8") as f:
                json.dump(self.operators, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def is_using_external_shared_folder(self) -> bool:
        return os.path.abspath(self.shared_db_dir) != os.path.abspath(self.workspace_dir)

    def set_shared_folder(self, new_folder: str) -> Tuple[bool, str]:
        r"""
        Configura uma pasta compartilhada (Rede Local \\SERVIDOR\..., Google Drive, OneDrive ou Dropbox)
        para sincronizar todos os computadores da Lyda em tempo real.
        """
        if not new_folder:
            return False, "Nenhuma pasta selecionada."
        try:
            os.makedirs(new_folder, exist_ok=True)
            target_db = os.path.join(new_folder, DB_JSON_FILENAME)
            target_hist = os.path.join(new_folder, HISTORY_JSON_FILENAME)

            # Se a pasta compartilhada ainda não tem banco de dados, copia a base atual para lá!
            if not os.path.exists(target_db) and self.items:
                with open(target_db, "w", encoding="utf-8") as f:
                    json.dump(self.items, f, ensure_ascii=False, indent=2)
            if not os.path.exists(target_hist) and self.history:
                with open(target_hist, "w", encoding="utf-8") as f:
                    json.dump(self.history, f, ensure_ascii=False, indent=2)

            self.shared_db_dir = new_folder
            self._update_paths_for_shared_dir()
            self.save_local_pc_config()
            self.load()
            return (
                True,
                f"Sincronização Multi-PC ativada com sucesso na pasta:\n{new_folder}\n\n"
                f"Total de {len(self.items)} equipamentos sincronizados em tempo real.",
            )
        except Exception as e:
            return False, f"Erro ao configurar pasta compartilhada: {e}"

    def _record_disk_mtimes(self):
        try:
            if os.path.exists(self.db_path):
                self._last_db_mtime = os.path.getmtime(self.db_path)
            if os.path.exists(self.history_path):
                self._last_hist_mtime = os.path.getmtime(self.history_path)
        except Exception:
            pass

    def check_for_external_updates(self) -> Optional[str]:
        """
        Verifica a cada poucos segundos se outro computador da Lyda salvou alguma alteração
        na pasta compartilhada. Se houver alteração externa, recarrega automaticamente!
        """
        try:
            db_m = os.path.getmtime(self.db_path) if os.path.exists(self.db_path) else 0.0
            hist_m = os.path.getmtime(self.history_path) if os.path.exists(self.history_path) else 0.0
            if (db_m > self._last_db_mtime + 0.05) or (hist_m > self._last_hist_mtime + 0.05):
                self.load()
                if self.history:
                    latest = self.history[0]
                    op = latest.get("OPERADOR") or latest.get("RESPONSAVEL") or "Outro PC"
                    pc = latest.get("COMPUTADOR", "")
                    acao = latest.get("ACAO", "Atualização")
                    ser = latest.get("CODIGO_BARRAS", "")
                    return f"Sincronizado em tempo real: [{ser}] {acao} por {op}" + (f" ({pc})" if pc else "")
                return "Base sincronizada automaticamente com alterações de outro computador."
        except Exception:
            pass
        return None

    def load(self):
        if hasattr(self, "operators_path") and os.path.exists(self.operators_path):
            try:
                with open(self.operators_path, "r", encoding="utf-8") as f:
                    ops = json.load(f)
                if isinstance(ops, list) and ops:
                    self.operators = [str(x).strip().upper() for x in ops if str(x).strip()]
            except Exception:
                pass
        if os.path.exists(self.history_path):
            try:
                with open(self.history_path, "r", encoding="utf-8") as f:
                    self.history = json.load(f)
            except Exception:
                self.history = []

        if hasattr(self, "clients_path") and os.path.exists(self.clients_path):
            try:
                with open(self.clients_path, "r", encoding="utf-8") as f:
                    loaded_clients = json.load(f)
                if isinstance(loaded_clients, list):
                    self.clients = loaded_clients
            except Exception:
                self.clients = []

        if os.path.exists(self.db_path):
            try:
                with open(self.db_path, "r", encoding="utf-8") as f:
                    self.items = json.load(f)
                if self.items:
                    self._enrich_missing_hospital_addresses()
                    self._sync_clients_from_items()
                    self._record_disk_mtimes()
                    return
            except Exception:
                pass

        # Se ainda não existe banco JSON local, importa automaticamente da planilha Mapeamento Equipamento i-STAT - LYDA.xlsx
        if os.path.exists(self.default_excel_path):
            self.import_from_lyda_excel(self.default_excel_path)
            self._enrich_missing_hospital_addresses()
            self._sync_clients_from_items()
        self._record_disk_mtimes()

    def _enrich_missing_hospital_addresses(self):
        """Preenche automaticamente endereços conhecidos dos hospitais da carteira LYDA e da Sede Lyda quando vazios."""
        changed = False
        for it in self.items:
            cli = (it.get("CLIENTE") or "").strip()
            cli_up = cli.upper()
            if not it.get("ENDERECO"):
                if "ESTOQUE" in cli_up or "SEM CLIENTE" in cli_up or cli_up.startswith("LYDA"):
                    it["ENDERECO"] = self.lyda_hq_address
                    it.setdefault("CEP", "90240-005")
                    it.setdefault("CIDADE", "PORTO ALEGRE")
                    it.setdefault("UF", "RS")
                    changed = True
                else:
                    sug = get_suggested_hospital_address(cli)
                    if sug:
                        it["ENDERECO"] = sug.get("ENDERECO", "")
                        if not it.get("CEP"):
                            it["CEP"] = sug.get("CEP", "")
                        if not it.get("CIDADE"):
                            it["CIDADE"] = sug.get("CIDADE", "")
                        if not it.get("UF"):
                            it["UF"] = sug.get("UF", "")
                        changed = True
            it.setdefault("ENDERECO", "")
            it.setdefault("CEP", "")
            it.setdefault("CONTATO_LOCAL", "")
            it.setdefault("ULTIMA_ATUALIZACAO", "")
            it.setdefault("VERSAO_CLEW", "")
            it.setdefault("CICLO_ATUALIZACAO_MESES", 6)
            it.setdefault("ATUALIZADO_NO_ESTOQUE", "")
            it.setdefault("NOTA_FISCAL", "")
            it.setdefault("ACESSORIOS", "")
            cyc = compute_update_cycle_info(it)
            it["PROXIMA_ATUALIZACAO"] = cyc["summary_table"]
        if changed:
            try:
                self.save()
            except Exception:
                pass

    def save(self):
        """
        Salva com escrita atômica (.tmp -> replace) e mesclagem inteligente contra conflitos Multi-PC:
        se outro computador alterou outro equipamento um segundo antes, preserva ambas as alterações!
        """
        try:
            # 1. Mescla itens do disco caso outro PC tenha acabado de salvar um registro mais recente
            if os.path.exists(self.db_path):
                try:
                    disk_m = os.path.getmtime(self.db_path)
                    if self._last_db_mtime > 0 and disk_m > self._last_db_mtime + 0.01:
                        with open(self.db_path, "r", encoding="utf-8") as f:
                            disk_items = json.load(f)
                        if isinstance(disk_items, list):
                            mem_by_key = {(x.get("TIPO", ""), x.get("CODIGO", "")): x for x in self.items}
                            for d_it in disk_items:
                                k = (d_it.get("TIPO", ""), d_it.get("CODIGO", ""))
                                if k in mem_by_key:
                                    d_ts = float(d_it.get("_updated_epoch", 0.0) or 0.0)
                                    m_ts = float(mem_by_key[k].get("_updated_epoch", 0.0) or 0.0)
                                    if d_ts > m_ts:
                                        idx_m = self.items.index(mem_by_key[k])
                                        self.items[idx_m] = d_it
                                elif d_it.get("CODIGO"):
                                    # Novo item adicionado por outro PC
                                    if float(d_it.get("_updated_epoch", 0.0) or 0.0) > self._last_db_mtime:
                                        self.items.append(d_it)
                except Exception:
                    pass

            # 2. Mescla histórico do disco caso outro PC tenha registrado bipagem simultânea
            if os.path.exists(self.history_path):
                try:
                    hist_m = os.path.getmtime(self.history_path)
                    if self._last_hist_mtime > 0 and hist_m > self._last_hist_mtime + 0.01:
                        with open(self.history_path, "r", encoding="utf-8") as f:
                            disk_hist = json.load(f)
                        if isinstance(disk_hist, list):
                            seen_ids = {
                                (h.get("DATA_HORA", ""), h.get("CODIGO_BARRAS", ""), h.get("ACAO", ""))
                                for h in self.history
                            }
                            for dh in disk_hist:
                                hk = (dh.get("DATA_HORA", ""), dh.get("CODIGO_BARRAS", ""), dh.get("ACAO", ""))
                                if hk not in seen_ids:
                                    self.history.append(dh)
                                    seen_ids.add(hk)
                            self.history.sort(key=lambda x: float(x.get("_epoch", 0.0) or 0.0), reverse=True)
                            self.history = self.history[:2000]
                except Exception:
                    pass

            tmp_db = self.db_path + f".tmp.{os.getpid()}"
            with open(tmp_db, "w", encoding="utf-8") as f:
                json.dump(self.items, f, ensure_ascii=False, indent=2)
            os.replace(tmp_db, self.db_path)

            tmp_hist = self.history_path + f".tmp.{os.getpid()}"
            with open(tmp_hist, "w", encoding="utf-8") as f:
                json.dump(self.history, f, ensure_ascii=False, indent=2)
            os.replace(tmp_hist, self.history_path)

            self._record_disk_mtimes()
        except Exception:
            # Fallback direto caso pasta de rede não aceite os.replace temporário
            with open(self.db_path, "w", encoding="utf-8") as f:
                json.dump(self.items, f, ensure_ascii=False, indent=2)
            with open(self.history_path, "w", encoding="utf-8") as f:
                json.dump(self.history, f, ensure_ascii=False, indent=2)
            self._record_disk_mtimes()

        # Espelha os arquivos JSON vivos na pasta do SharePoint se o auto_sync estiver ativo
        if getattr(self, "sharepoint_backup_dir", "") and getattr(self, "sharepoint_auto_sync", True):
            try:
                sp_live = os.path.join(self.sharepoint_backup_dir, "Backups_Sistema_iSTAT_LYDA", "Banco_Atual_Servidor")
                os.makedirs(sp_live, exist_ok=True)
                for src_p in (
                    self.db_path,
                    self.history_path,
                    self.clients_path,
                    self.operators_path,
                    getattr(self, "users_path", ""),
                    getattr(self, "audit_logs_path", ""),
                ):
                    if src_p and os.path.exists(src_p):
                        shutil.copy2(src_p, os.path.join(sp_live, os.path.basename(src_p)))
            except Exception:
                pass

    def add_history_log(
        self,
        serial_barcode: str,
        tipo: str,
        acao: str,
        detalhes: str,
        cliente: str = "",
        modalidade: str = "",
        condicao: str = "",
        defeito_obs: str = "",
        responsavel: str = "",
    ):
        op_final = (responsavel or self.operador_atual or "OPERADOR").strip()
        entry = {
            "_epoch": time.time(),
            "DATA_HORA": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
            "CODIGO_BARRAS": serial_barcode,
            "TIPO": tipo,
            "ACAO": acao,
            "CLIENTE": cliente,
            "MODALIDADE": modalidade,
            "CONDICAO": condicao,
            "DEFEITO_OBS": defeito_obs,
            "RESPONSAVEL": op_final,
            "OPERADOR": op_final,
            "COMPUTADOR": self.pc_hostname,
            "DETALHES": detalhes,
        }
        self.history.insert(0, entry)
        self.history = self.history[:2000]
        self.save()

    def get_item_history(self, serial_barcode: str) -> List[Dict[str, Any]]:
        """Retorna todo o histórico de movimentações/defeitos daquele número de série específico."""
        bc = clean_barcode_serial(serial_barcode)
        if not bc:
            return []
        return [h for h in self.history if clean_barcode_serial(h.get("CODIGO_BARRAS", "")) == bc]

    def _save_clients(self):
        try:
            with open(self.clients_path, "w", encoding="utf-8") as f:
                json.dump(self.clients, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _is_internal_stock_client_name(self, name: str) -> bool:
        up = (name or "").strip().upper()
        if not up:
            return True
        if any(k in up for k in ("SEM CLIENTE", "ESTOQUE LYDA", "LYDA ESTOQUE", "ESTOQUE USADOS", "ESTOQUE NOVOS")):
            return True
        if up in ("LYDA", "ESTOQUE", "LYDA COMERCIO IMPORTAÇÃO E EXPORTAÇÃO LTDA", "LYDA COMERCIO IMPORTACAO E EXPORTACAO LTDA"):
            return True
        return False

    def _sync_clients_from_items(self):
        """
        Garante que todos os hospitais/clínicas presentes nos aparelhos tenham um cadastro
        completo na base de clientes (self.clients), ignorando posições internas de Estoque da LYDA.
        """
        cleaned_clients = [
            c for c in self.clients
            if not self._is_internal_stock_client_name(c.get("CLIENTE", ""))
        ]
        changed = len(cleaned_clients) != len(self.clients)
        self.clients = cleaned_clients

        by_name: Dict[str, Dict[str, Any]] = {
            (c.get("CLIENTE") or "").strip().upper(): c
            for c in self.clients
        }
        for it in self.items:
            raw_cli = (it.get("CLIENTE") or "").strip()
            cli_up = raw_cli.upper()
            if self._is_internal_stock_client_name(raw_cli):
                continue
            if cli_up not in by_name:
                sug = get_suggested_hospital_address(raw_cli) or {}
                rec = {
                    "CLIENTE": raw_cli,
                    "CNPJ": "",
                    "ENDERECO": it.get("ENDERECO") or sug.get("ENDERECO", ""),
                    "CEP": it.get("CEP") or sug.get("CEP", ""),
                    "CIDADE": (it.get("CIDADE") or sug.get("CIDADE", "PORTO ALEGRE")).strip().upper(),
                    "UF": (it.get("UF") or sug.get("UF", "RS")).strip().upper(),
                    "CONTATO_LOCAL": it.get("CONTATO_LOCAL", ""),
                    "TELEFONE": "",
                    "EMAIL": "",
                    "SETORES": (it.get("SETOR") or "").strip(),
                    "OBSERVACOES": "",
                    "_updated_epoch": time.time(),
                }
                self.clients.append(rec)
                by_name[cli_up] = rec
                changed = True
            else:
                rec = by_name[cli_up]
                sug = get_suggested_hospital_address(raw_cli) or {}
                if not rec.get("ENDERECO"):
                    addr_val = it.get("ENDERECO") or sug.get("ENDERECO", "")
                    if addr_val:
                        rec["ENDERECO"] = addr_val
                        changed = True
                if not rec.get("CEP"):
                    cep_val = it.get("CEP") or sug.get("CEP", "")
                    if cep_val:
                        rec["CEP"] = cep_val
                        changed = True
                if not rec.get("CIDADE") and (it.get("CIDADE") or sug.get("CIDADE")):
                    rec["CIDADE"] = (it.get("CIDADE") or sug.get("CIDADE", "")).strip().upper()
                    changed = True
                if not rec.get("UF") and (it.get("UF") or sug.get("UF")):
                    rec["UF"] = (it.get("UF") or sug.get("UF", "")).strip().upper()
                    changed = True
                if not rec.get("CONTATO_LOCAL") and it.get("CONTATO_LOCAL"):
                    rec["CONTATO_LOCAL"] = it["CONTATO_LOCAL"]
                    changed = True
                if rec.get("ENDERECO") and not it.get("ENDERECO"):
                    it["ENDERECO"] = rec["ENDERECO"]
                    if rec.get("CEP") and not it.get("CEP"):
                        it["CEP"] = rec["CEP"]
                    if rec.get("CIDADE"):
                        it["CIDADE"] = rec["CIDADE"]
                    if rec.get("UF"):
                        it["UF"] = rec["UF"]

        self.clients.sort(key=lambda x: (x.get("CLIENTE") or "").upper())
        if changed:
            self._save_clients()
            try:
                with open(self.db_path, "w", encoding="utf-8") as f:
                    json.dump(self.items, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

    def get_all_clients_records(self) -> List[Dict[str, Any]]:
        """Retorna todos os clientes cadastrados com a contagem atualizada dos aparelhos vinculados."""
        self._sync_clients_from_items()
        out: List[Dict[str, Any]] = []
        default_cyc = getattr(self, "default_update_cycle_months", 6)
        for c in self.clients:
            c_name = (c.get("CLIENTE") or "").strip()
            if not c_name:
                continue
            linked = [
                it for it in self.items
                if (it.get("CLIENTE") or "").strip().upper() == c_name.upper()
            ]
            pendentes = sum(
                1
                for it in linked
                if compute_update_cycle_info(it, default_cyc)["status_code"] in ("VENCIDA", "VENCENDO", "SEM_DATA")
            )
            em_manutencao = sum(
                1
                for it in linked
                if classify_item_row_state(it) == "DEFEITO"
            )
            comodato_cnt = sum(
                1
                for it in linked
                if (it.get("MODALIDADE") or "").strip().upper() in ("COMODATO", "ALUGUEL")
            )
            venda_cnt = sum(
                1
                for it in linked
                if (it.get("MODALIDADE") or "").strip().upper() == "VENDA"
            )
            ativos_operando = len(linked) - em_manutencao
            setores_set = sorted({(it.get("SETOR") or "").strip() for it in linked if (it.get("SETOR") or "").strip()})
            mods_set = sorted({(it.get("MODALIDADE") or "").strip() for it in linked if (it.get("MODALIDADE") or "").strip()})
            enriched = dict(c)
            enriched["_total_aparelhos"] = len(linked)
            enriched["_ativos_operando"] = ativos_operando
            enriched["_em_manutencao"] = em_manutencao
            enriched["_comodato_count"] = comodato_cnt
            enriched["_venda_count"] = venda_cnt
            enriched["_pendentes_6m"] = pendentes
            enriched["_setores_ativos"] = ", ".join(setores_set) or c.get("SETORES", "")
            enriched["_modalidades_ativas"] = " / ".join(mods_set) if mods_set else "COMODATO / VENDA"
            out.append(enriched)
        return out

    def get_client_record(self, cliente_name: str) -> Optional[Dict[str, Any]]:
        target = (cliente_name or "").strip().upper()
        if not target:
            return None
        for c in self.clients:
            if (c.get("CLIENTE") or "").strip().upper() == target:
                return c
        return None

    def get_client_items(self, cliente_name: str) -> List[Tuple[int, Dict[str, Any]]]:
        """Retorna [(indice_no_db, item_dict), ...] de todos os aparelhos vinculados a este cliente."""
        target = (cliente_name or "").strip().upper()
        if not target:
            return []
        return [
            (idx, it)
            for idx, it in enumerate(self.items)
            if (it.get("CLIENTE") or "").strip().upper() == target
        ]

    def upsert_client(self, client_data: Dict[str, Any], old_name: str = "") -> Dict[str, Any]:
        """
        Cadastra ou atualiza um Hospital/Cliente e propaga automaticamente nome, endereço, CEP,
        cidade, UF e contato para todos os aparelhos vinculados a ele!
        """
        new_name = (client_data.get("CLIENTE") or "").strip()
        if not new_name:
            raise ValueError("Informe o nome do Hospital / Clínica / Cliente.")
        target_old = (old_name or new_name).strip().upper()
        existing_rec = None
        for c in self.clients:
            c_up = (c.get("CLIENTE") or "").strip().upper()
            if c_up == target_old or c_up == new_name.upper():
                existing_rec = c
                break

        payload = {
            "CLIENTE": new_name,
            "CNPJ": (client_data.get("CNPJ") or "").strip(),
            "ENDERECO": (client_data.get("ENDERECO") or "").strip(),
            "CEP": (client_data.get("CEP") or "").strip(),
            "CIDADE": (client_data.get("CIDADE") or "PORTO ALEGRE").strip().upper(),
            "UF": (client_data.get("UF") or "RS").strip().upper(),
            "CONTATO_LOCAL": (client_data.get("CONTATO_LOCAL") or "").strip(),
            "TELEFONE": (client_data.get("TELEFONE") or "").strip(),
            "EMAIL": (client_data.get("EMAIL") or "").strip(),
            "SETORES": (client_data.get("SETORES") or "").strip(),
            "OBSERVACOES": (client_data.get("OBSERVACOES") or "").strip(),
            "_updated_epoch": time.time(),
        }
        if existing_rec is not None:
            existing_rec.update(payload)
            rec_out = existing_rec
        else:
            self.clients.append(payload)
            rec_out = payload

        # Se o nome do cliente foi renomeado, atualiza também nos aparelhos vinculados
        if old_name and old_name.strip().upper() != new_name.upper():
            for it in self.items:
                if (it.get("CLIENTE") or "").strip().upper() == old_name.strip().upper():
                    it["CLIENTE"] = new_name
                    it["_updated_epoch"] = time.time()

        self.propagate_client_address(
            cliente_name=new_name,
            endereco=payload["ENDERECO"],
            cep=payload["CEP"],
            cidade=payload["CIDADE"],
            uf=payload["UF"],
            contato_local=payload["CONTATO_LOCAL"],
        )
        self.clients.sort(key=lambda x: (x.get("CLIENTE") or "").upper())
        self._save_clients()
        self.save()
        return rec_out

    def delete_client(self, cliente_name: str) -> Tuple[bool, str]:
        target = (cliente_name or "").strip().upper()
        if not target:
            return False, "Selecione um cliente."
        before = len(self.clients)
        self.clients = [c for c in self.clients if (c.get("CLIENTE") or "").strip().upper() != target]
        unlinked = 0
        for it in self.items:
            if (it.get("CLIENTE") or "").strip().upper() == target:
                it["CLIENTE"] = "SEM CLIENTE (ESTOQUE LYDA)"
                it["STATUS"] = "ESTOQUE USADOS"
                it["ENDERECO"] = self.lyda_hq_address
                it["_updated_epoch"] = time.time()
                unlinked += 1
        self._save_clients()
        if unlinked > 0:
            self.save()
        if len(self.clients) < before or unlinked > 0:
            return True, f"Cliente removido ({unlinked} aparelho(s) movido(s) para o Estoque Lyda)."
        return False, "Cliente não encontrado."

    def get_known_clients(self) -> List[str]:
        """Retorna lista de clientes já cadastrados na base (incluindo opção SEM CLIENTE / ESTOQUE LYDA no topo)."""
        base = ["SEM CLIENTE (ESTOQUE LYDA)"]
        from_items = {
            it.get("CLIENTE", "").strip()
            for it in self.items
            if it.get("CLIENTE", "").strip()
            and not self._is_internal_stock_client_name(it.get("CLIENTE", ""))
        }
        from_reg = {
            c.get("CLIENTE", "").strip()
            for c in self.clients
            if c.get("CLIENTE", "").strip()
            and not self._is_internal_stock_client_name(c.get("CLIENTE", ""))
        }
        clients = sorted(from_items | from_reg)
        return base + clients

    def get_client_address_info(self, cliente_name: str) -> Dict[str, str]:
        """
        Retorna o Endereço Completo, CEP, Cidade, UF e Contato Local já salvos para este Hospital/Cliente
        (ou busca da base sugerida da Lyda) para preencher automaticamente ao escolher o cliente!
        """
        target = (cliente_name or "").strip().upper()
        if not target or self._is_internal_stock_client_name(cliente_name):
            return {
                "ENDERECO": self.lyda_hq_address,
                "CEP": "91130-470",
                "CIDADE": "PORTO ALEGRE",
                "UF": "RS",
                "CONTATO_LOCAL": "Estoque LYDA",
            }
        rec = self.get_client_record(cliente_name)
        if rec and (rec.get("ENDERECO") or rec.get("CEP") or rec.get("CIDADE")):
            sug = get_suggested_hospital_address(cliente_name) or {}
            return {
                "ENDERECO": rec.get("ENDERECO") or sug.get("ENDERECO", ""),
                "CEP": rec.get("CEP") or sug.get("CEP", ""),
                "CIDADE": rec.get("CIDADE") or sug.get("CIDADE", "PORTO ALEGRE"),
                "UF": rec.get("UF") or sug.get("UF", "RS"),
                "CONTATO_LOCAL": rec.get("CONTATO_LOCAL", ""),
            }
        for it in self.items:
            if (it.get("CLIENTE") or "").strip().upper() == target:
                if it.get("ENDERECO") or it.get("CEP") or it.get("CIDADE"):
                    sug = get_suggested_hospital_address(cliente_name) or {}
                    return {
                        "ENDERECO": it.get("ENDERECO") or sug.get("ENDERECO", ""),
                        "CEP": it.get("CEP") or sug.get("CEP", ""),
                        "CIDADE": it.get("CIDADE") or sug.get("CIDADE", "PORTO ALEGRE"),
                        "UF": it.get("UF") or sug.get("UF", "RS"),
                        "CONTATO_LOCAL": it.get("CONTATO_LOCAL", ""),
                    }
        sug = get_suggested_hospital_address(cliente_name)
        if sug:
            return {
                "ENDERECO": sug.get("ENDERECO", ""),
                "CEP": sug.get("CEP", ""),
                "CIDADE": sug.get("CIDADE", "PORTO ALEGRE"),
                "UF": sug.get("UF", "RS"),
                "CONTATO_LOCAL": "",
            }
        return {}

    def propagate_client_address(
        self,
        cliente_name: str,
        endereco: str,
        cep: str,
        cidade: str,
        uf: str,
        contato_local: str = "",
    ) -> int:
        """
        Propaga o endereço completo atualizado de um Hospital/Cliente para todos os equipamentos
        que estão nesse mesmo Hospital/Cliente.
        """
        target = (cliente_name or "").strip().upper()
        if not target or "SEM CLIENTE" in target or "ESTOQUE" in target:
            return 0
        count = 0
        now_ts = time.time()
        for it in self.items:
            if (it.get("CLIENTE") or "").strip().upper() == target:
                if endereco:
                    it["ENDERECO"] = endereco.strip()
                if cep:
                    it["CEP"] = cep.strip()
                if cidade:
                    it["CIDADE"] = cidade.strip().upper()
                if uf:
                    it["UF"] = uf.strip().upper()
                if contato_local:
                    it["CONTATO_LOCAL"] = contato_local.strip()
                it["_updated_epoch"] = now_ts
                count += 1
        if count > 0:
            self.save()
        return count

    def get_kit_companions(self, serial_barcode: str) -> List[Dict[str, Any]]:
        """
        Encontra outros equipamentos que fazem parte do mesmo Kit deste serial
        (ex: se bipou o Analisador 426086, retorna a Impressora/Simulador/Downloader vinculados a 426086, e vice-versa).
        """
        bc = clean_barcode_serial(serial_barcode)
        if not bc:
            return []
        target_item = next((it for it in self.items if clean_barcode_serial(it.get("CODIGO", "")) == bc), None)
        kit_ref = clean_barcode_serial(target_item.get("KIT_ANALISADOR", "")) if target_item else ""
        keys = {bc}
        if kit_ref:
            keys.add(kit_ref)

        companions = []
        for it in self.items:
            it_bc = clean_barcode_serial(it.get("CODIGO", ""))
            it_kit = clean_barcode_serial(it.get("KIT_ANALISADOR", ""))
            if it_bc != bc and ((it_kit and it_kit in keys) or (it_bc in keys)):
                companions.append(it)
        return companions

    # =========================================================================
    # SISTEMA DE BACKUP AUTOMÁTICO DIÁRIO, ENVIO P/ SHAREPOINT E RESTAURAÇÃO
    # =========================================================================
    def detect_sharepoint_folders(self) -> List[str]:
        """
        Detecta automaticamente pastas do SharePoint / OneDrive / Google Drive sincronizadas
        no computador (Windows ou macOS) para facilitar a configuração em 1 clique.
        """
        candidates: List[str] = []
        home = os.path.expanduser("~")
        try:
            # 1. Variáveis de ambiente padrão do OneDrive / SharePoint Comercial no Windows
            for env_key in ("OneDriveCommercial", "OneDrive", "OneDriveConsumer"):
                env_val = os.environ.get(env_key, "").strip()
                if env_val and os.path.isdir(env_val) and env_val not in candidates:
                    candidates.append(env_val)

            # 2. Pastas na Home do usuário (Windows C:\Users\Nome\OneDrive - LYDA... ou SharePoint...)
            if os.path.isdir(home):
                for entry in sorted(os.listdir(home)):
                    low = entry.lower()
                    if any(k in low for k in ("onedrive", "sharepoint", "lyda", "google drive", "dropbox")):
                        full_p = os.path.join(home, entry)
                        if os.path.isdir(full_p) and full_p not in candidates:
                            candidates.append(full_p)

            # 3. macOS CloudStorage (~/Library/CloudStorage/OneDrive-...)
            cloud_storage = os.path.join(home, "Library", "CloudStorage")
            if os.path.isdir(cloud_storage):
                for entry in sorted(os.listdir(cloud_storage)):
                    full_p = os.path.join(cloud_storage, entry)
                    if os.path.isdir(full_p) and full_p not in candidates:
                        candidates.append(full_p)
        except Exception:
            pass
        return candidates

    def set_sharepoint_backup_config(
        self,
        folder_path: str,
        backup_time: str = "18:00",
        auto_sync: bool = True,
    ) -> Tuple[bool, str]:
        """Configura a pasta do SharePoint/OneDrive para onde o servidor envia o backup diário automático."""
        clean_path = (folder_path or "").strip()
        self.sharepoint_backup_time = (backup_time or "18:00").strip() or "18:00"
        self.sharepoint_auto_sync = bool(auto_sync)

        if not clean_path:
            self.sharepoint_backup_dir = ""
            self.save_local_pc_config()
            return True, "Backup local diário mantido (pasta externa do SharePoint desativada)."

        try:
            os.makedirs(clean_path, exist_ok=True)
            self.sharepoint_backup_dir = clean_path
            self.save_local_pc_config()
            ok, msg = self.sync_backup_to_sharepoint(reason="configuracao_sharepoint")
            return ok, msg
        except Exception as e:
            return False, f"Não foi possível acessar ou criar a pasta do SharePoint '{clean_path}': {e}"

    def ensure_daily_backup(self):
        """Garante que exista pelo menos 1 backup automático salvo no dia de hoje (local e no SharePoint)."""
        if not self.items:
            return
        today_str = datetime.now().strftime("%Y%m%d")
        today_prefix = f"backup_lyda_{today_str}_"
        try:
            existing = [f for f in os.listdir(self.backups_dir) if f.startswith(today_prefix) and f.endswith(".json")]
            if not existing:
                self.create_backup(reason="diario_automatico")
            elif self.sharepoint_backup_dir and self.sharepoint_auto_sync:
                # Verifica se o SharePoint já recebeu o backup de hoje
                sp_sub = os.path.join(self.sharepoint_backup_dir, "Backups_Sistema_iSTAT_LYDA")
                sp_existing = (
                    [f for f in os.listdir(sp_sub) if f.startswith(today_prefix) and f.endswith(".json")]
                    if os.path.isdir(sp_sub)
                    else []
                )
                if not sp_existing:
                    self.sync_backup_to_sharepoint(reason="diario_automatico")
        except Exception:
            pass

    def create_backup(self, reason: str = "manual") -> str:
        os.makedirs(self.backups_dir, exist_ok=True)
        now = datetime.now()
        safe_reason = re.sub(r"[^a-zA-Z0-9_-]", "_", reason)[:24]
        fname = f"backup_lyda_{now.strftime('%Y%m%d_%H%M%S')}_{safe_reason}.json"
        fpath = os.path.join(self.backups_dir, fname)
        payload = {
            "created_at": now.strftime("%d/%m/%Y %H:%M:%S"),
            "reason": reason,
            "pc_hostname": self.pc_hostname,
            "items_count": len(self.items),
            "clients_count": len(self.clients),
            "history_count": len(self.history),
            "items": self.items,
            "clients": self.clients,
            "operators": self.operators,
            "history": self.history,
        }
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        # Mantém até os 60 backups mais recentes para nunca lotar o disco
        try:
            all_files = sorted(
                [os.path.join(self.backups_dir, x) for x in os.listdir(self.backups_dir) if x.endswith(".json")],
                key=os.path.getmtime,
                reverse=True,
            )
            for old_f in all_files[60:]:
                os.remove(old_f)
        except Exception:
            pass

        # Se a pasta do SharePoint estiver configurada e ativa, envia cópia automaticamente!
        if getattr(self, "sharepoint_backup_dir", "") and getattr(self, "sharepoint_auto_sync", True):
            try:
                self._copy_backup_file_to_sharepoint(fpath, reason=reason)
            except Exception:
                pass
        return fpath

    def _copy_backup_file_to_sharepoint(self, local_backup_fpath: str, reason: str = "auto") -> Tuple[bool, str]:
        sp_root = (getattr(self, "sharepoint_backup_dir", "") or "").strip()
        if not sp_root:
            return False, "Pasta do SharePoint não configurada."
        try:
            sp_target_dir = os.path.join(sp_root, "Backups_Sistema_iSTAT_LYDA")
            sp_live_dir = os.path.join(sp_target_dir, "Banco_Atual_Servidor")
            os.makedirs(sp_target_dir, exist_ok=True)
            os.makedirs(sp_live_dir, exist_ok=True)

            # 1. Copia o arquivo de backup JSON datado + ULTIMO_BACKUP_LYDA.json
            bname = os.path.basename(local_backup_fpath)
            shutil.copy2(local_backup_fpath, os.path.join(sp_target_dir, bname))
            shutil.copy2(local_backup_fpath, os.path.join(sp_target_dir, "ULTIMO_BACKUP_LYDA.json"))

            # 2. Espelha os arquivos JSON vivos do servidor na subpasta Banco_Atual_Servidor
            for src_p in (
                self.db_path,
                self.history_path,
                self.clients_path,
                self.operators_path,
                getattr(self, "users_path", ""),
                getattr(self, "audit_logs_path", ""),
            ):
                if src_p and os.path.exists(src_p):
                    shutil.copy2(src_p, os.path.join(sp_live_dir, os.path.basename(src_p)))

            # 3. Exporta a planilha Excel atualizada direto na pasta do SharePoint para consulta rápida
            now = datetime.now()
            excel_latest = os.path.join(sp_target_dir, "Mapeamento_Equipamento_i-STAT_LYDA_ATUALIZADO.xlsx")
            excel_daily = os.path.join(sp_target_dir, f"Planilha_iSTAT_LYDA_{now.strftime('%Y-%m-%d')}.xlsx")
            self.export_to_excel(excel_latest)
            shutil.copy2(excel_latest, excel_daily)

            # Limpa backups antigos na pasta do SharePoint mantendo os últimos 60
            sp_jsons = sorted(
                [
                    os.path.join(sp_target_dir, x)
                    for x in os.listdir(sp_target_dir)
                    if x.startswith("backup_lyda_") and x.endswith(".json")
                ],
                key=os.path.getmtime,
                reverse=True,
            )
            for old_sp in sp_jsons[60:]:
                try:
                    os.remove(old_sp)
                except Exception:
                    pass

            self.last_sharepoint_backup_at = now.strftime("%d/%m/%Y %H:%M:%S")
            self.last_sharepoint_backup_status = f"OK ({len(self.items)} aparelhos enviados p/ SharePoint)"
            self.save_local_pc_config()
            return (
                True,
                f"Backup completo (Banco JSON + Planilha Excel) enviado para o SharePoint em:\n{sp_target_dir}",
            )
        except Exception as e:
            self.last_sharepoint_backup_status = f"ERRO: {e}"
            self.save_local_pc_config()
            return False, f"Erro ao enviar backup para o SharePoint: {e}"

    def sync_backup_to_sharepoint(self, reason: str = "envio_sharepoint") -> Tuple[bool, str]:
        """Cria um backup imediato do servidor local e envia (JSON + Excel .xlsx) para a pasta do SharePoint."""
        local_fp = self.create_backup(reason=reason)
        if not getattr(self, "sharepoint_backup_dir", "").strip():
            return (
                True,
                f"Backup local salvo com sucesso em:\n{local_fp}\n\n"
                "(Configure a pasta do SharePoint nas Configurações para espelhar automaticamente na nuvem da LYDA).",
            )
        return self._copy_backup_file_to_sharepoint(local_fp, reason=reason)

    def list_backups(self) -> List[Dict[str, Any]]:
        os.makedirs(self.backups_dir, exist_ok=True)
        out = []
        seen_names = set()
        dirs_to_scan = [("Servidor Local", self.backups_dir)]
        if getattr(self, "sharepoint_backup_dir", "").strip():
            sp_dir = os.path.join(self.sharepoint_backup_dir, "Backups_Sistema_iSTAT_LYDA")
            if os.path.isdir(sp_dir):
                dirs_to_scan.append(("SharePoint", sp_dir))

        for origin_label, folder in dirs_to_scan:
            try:
                files = sorted(
                    [x for x in os.listdir(folder) if x.startswith("backup_lyda_") and x.endswith(".json")],
                    reverse=True,
                )
                for fn in files:
                    if fn in seen_names:
                        continue
                    seen_names.add(fn)
                    fp = os.path.join(folder, fn)
                    try:
                        with open(fp, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        out.append(
                            {
                                "filename": fn,
                                "filepath": fp,
                                "origin": origin_label,
                                "created_at": data.get("created_at", fn),
                                "reason": data.get("reason", "auto"),
                                "items_count": data.get("items_count", len(data.get("items", []))),
                                "clients_count": data.get("clients_count", len(data.get("clients", []))),
                                "history_count": data.get("history_count", len(data.get("history", []))),
                            }
                        )
                    except Exception:
                        continue
            except Exception:
                pass
        out.sort(key=lambda x: x.get("filename", ""), reverse=True)
        return out

    def restore_backup(self, backup_filepath: str) -> Tuple[bool, str]:
        if not os.path.exists(backup_filepath):
            return False, "Arquivo de backup não encontrado."
        try:
            with open(backup_filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            items = data.get("items", [])
            history = data.get("history", [])
            clients = data.get("clients", [])
            if not isinstance(items, list) or not items:
                return False, "O backup selecionado está vazio ou inválido."
            # Salva backup de segurança antes de restaurar
            self.create_backup(reason="antes_de_restaurar")
            self.items = items
            self.history = history if isinstance(history, list) else self.history
            if isinstance(clients, list) and clients:
                self.clients = clients
                self._save_clients()
            self.save()
            self.add_history_log(
                "SISTEMA",
                "TODOS",
                "RESTAURAÇÃO DE BACKUP",
                f"Base restaurada de {os.path.basename(backup_filepath)} ({len(self.items)} equipamentos)",
            )
            return True, f"Backup restaurado com sucesso! ({len(self.items)} equipamentos recuperados)."
        except Exception as e:
            return False, f"Erro ao restaurar backup: {e}"

    def import_from_lyda_excel(self, excel_path: str) -> Tuple[int, str]:
        """
        Lê o arquivo Excel 'Mapeamento Equipamento i-STAT - LYDA.xlsx' (ou qualquer planilha no mesmo padrão)
        e desmembra cada coluna (ANALISADOR, IMPRESSORA, SIMULADOR, DOWNLOADER) em um equipamento individual
        com seu próprio código de barras!
        Também suporta importar uma planilha já unificada.
        """
        import openpyxl  # type: ignore

        wb = openpyxl.load_workbook(excel_path, data_only=True)
        extracted: List[Dict[str, Any]] = []
        seen_keys = set()

        def _register_item(
            tipo: str,
            raw_serial: Any,
            cliente_local: str,
            uf: str,
            cidade: str,
            setor: str,
            modalidade: str,
            status_col: str,
            obs: str,
            kit_analisador_ref: str = "",
        ):
            bc = clean_barcode_serial(raw_serial)
            if not bc:
                return
            tipo_norm = normalize_equipment_type(tipo)

            status_final = infer_status(modalidade, cliente_local, status_col, obs, modalidade)
            cli_clean = (cliente_local or "").strip()
            if "ESTOQUE" in status_final.upper() or any(k in cli_clean.upper() for k in ("ESTOQUE", "SEM CLIENTE")):
                cli_clean = "SEM CLIENTE (ESTOQUE LYDA)"
                modalidade = "PROPRIEDADE LYDA"
                if not setor or setor.upper() in ("USADO", "NOVO", "ESTOQUE"):
                    setor = "ESTOQUE LYDA (NOVOS)" if "NOVOS" in status_final.upper() else "ESTOQUE LYDA"

            item_dict = {
                "ID": f"{tipo_norm[:3]}-{bc}",
                "CODIGO": bc,
                "SERIAL_ORIGINAL": format_raw_serial(raw_serial),
                "TIPO": tipo_norm,
                "EQUIPAMENTO": f"i-STAT {tipo_norm.title()}",
                "CLIENTE": cli_clean or "SEM CLIENTE (ESTOQUE LYDA)",
                "UF": (uf or "RS").strip(),
                "CIDADE": (cidade or "PORTO ALEGRE").strip(),
                "SETOR": (setor or "ESTOQUE LYDA").strip(),
                "MODALIDADE": modalidade,
                "STATUS": status_final,
                "KIT_ANALISADOR": kit_analisador_ref,
                "OBSERVACOES": (obs or "").strip(),
                "ATUALIZADO_EM": datetime.now().strftime("%d/%m/%Y %H:%M"),
            }

            # Chave única para nunca duplicar o mesmo aparelho
            dedup_key = (tipo_norm, bc)
            if dedup_key in seen_keys:
                # Atualiza o registro existente com a informação mais recente
                for ex_i, ex_it in enumerate(extracted):
                    if (ex_it.get("TIPO"), ex_it.get("CODIGO")) == dedup_key:
                        extracted[ex_i] = item_dict
                        break
                return
            seen_keys.add(dedup_key)
            extracted.append(item_dict)

        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            sname_upper = sheet_name.strip().upper()
            # Ignora a aba rascunho '..' se já estivermos lendo 'Propriedade LYda' para não duplicar itens
            if sname_upper == "..":
                continue

            headers = [str(ws.cell(1, c).value or "").strip() for c in range(1, ws.max_column + 1)]
            headers_upper = [h.upper() for h in headers]

            # Caso 1: Abas estilo 'Venda' e 'Comodato' (colunas: Nome, UF, Cidade, ANALISADOR, IMPRESSORA, SIMULADOR, DOWNLOADER, Setor, Negociação, OBSERVAÇÕES)
            if "ANALISADOR" in headers_upper and "NOME" in headers_upper:
                idx_nome = headers_upper.index("NOME")
                idx_uf = headers_upper.index("UF") if "UF" in headers_upper else -1
                idx_cid = headers_upper.index("CIDADE") if "CIDADE" in headers_upper else -1
                idx_ana = headers_upper.index("ANALISADOR")
                idx_imp = headers_upper.index("IMPRESSORA") if "IMPRESSORA" in headers_upper else -1
                idx_sim = headers_upper.index("SIMULADOR") if "SIMULADOR" in headers_upper else -1
                idx_dwl = next((i for i, h in enumerate(headers_upper) if "DOWNLOAD" in h or "DOWLOAD" in h), -1)
                idx_setor = next((i for i, h in enumerate(headers_upper) if "SETOR" in h), -1)
                idx_neg = next((i for i, h in enumerate(headers_upper) if "NEGOCIA" in h), -1)
                idx_obs = next((i for i, h in enumerate(headers_upper) if "OBSERVA" in h), -1)

                default_mod = "COMODATO" if "COMODATO" in sname_upper else "VENDA"

                for r in range(2, ws.max_row + 1):
                    row_vals = [ws.cell(r, c).value for c in range(1, len(headers) + 1)]
                    if not any(row_vals):
                        continue
                    cliente = str(row_vals[idx_nome] or "").strip()
                    uf = str(row_vals[idx_uf] or "").strip() if idx_uf >= 0 and row_vals[idx_uf] is not None else ""
                    cidade = str(row_vals[idx_cid] or "").strip() if idx_cid >= 0 and row_vals[idx_cid] is not None else ""
                    setor = str(row_vals[idx_setor] or "").strip() if idx_setor >= 0 and row_vals[idx_setor] is not None else ""
                    neg = str(row_vals[idx_neg] or "").strip() if idx_neg >= 0 and row_vals[idx_neg] is not None else default_mod
                    obs = str(row_vals[idx_obs] or "").strip() if idx_obs >= 0 and row_vals[idx_obs] is not None else ""
                    if obs in ("SIM", "NÃO"):
                        obs = f"Confirmado: {obs}"

                    ana_raw = row_vals[idx_ana] if idx_ana >= 0 else None
                    ana_bc = clean_barcode_serial(ana_raw)

                    # Desmembra cada um dos 4 tipos se tiver serial preenchido na linha!
                    if ana_raw is not None:
                        _register_item("ANALISADOR", ana_raw, cliente, uf, cidade, setor, default_mod, neg, obs, kit_analisador_ref=ana_bc)
                    if idx_imp >= 0 and row_vals[idx_imp] is not None:
                        _register_item("IMPRESSORA", row_vals[idx_imp], cliente, uf, cidade, setor, default_mod, neg, obs, kit_analisador_ref=ana_bc)
                    if idx_sim >= 0 and row_vals[idx_sim] is not None:
                        _register_item("SIMULADOR", row_vals[idx_sim], cliente, uf, cidade, setor, default_mod, neg, obs, kit_analisador_ref=ana_bc)
                    if idx_dwl >= 0 and row_vals[idx_dwl] is not None:
                        _register_item("DOWNLOADER", row_vals[idx_dwl], cliente, uf, cidade, setor, default_mod, neg, obs, kit_analisador_ref=ana_bc)

            # Caso 2: Aba 'Propriedade LYda' (colunas: Equipamento, Serial, Localização, Status, Observações)
            elif "EQUIPAMENTO" in headers_upper and "SERIAL" in headers_upper:
                idx_eq = headers_upper.index("EQUIPAMENTO")
                idx_ser = headers_upper.index("SERIAL")
                idx_loc = next((i for i, h in enumerate(headers_upper) if "LOCALIZA" in h), -1)
                idx_st = next((i for i, h in enumerate(headers_upper) if "STATUS" in h), -1)
                idx_obs = next((i for i, h in enumerate(headers_upper) if "OBSERVA" in h), -1)

                for r in range(2, ws.max_row + 1):
                    row_vals = [ws.cell(r, c).value for c in range(1, len(headers) + 1)]
                    if not any(row_vals):
                        continue
                    eq_type = str(row_vals[idx_eq] or "ANALISADOR").strip()
                    ser_raw = row_vals[idx_ser]
                    loc = str(row_vals[idx_loc] or "Estoque Lyda").strip() if idx_loc >= 0 and row_vals[idx_loc] is not None else "Estoque Lyda"
                    st = str(row_vals[idx_st] or "").strip() if idx_st >= 0 and row_vals[idx_st] is not None else ""
                    obs = str(row_vals[idx_obs] or "").strip() if idx_obs >= 0 and row_vals[idx_obs] is not None else ""
                    inferred_mod = "COMODATO" if "COMODATO" in loc.upper() else "PROPRIEDADE LYDA"

                    _register_item(
                        tipo=eq_type,
                        raw_serial=ser_raw,
                        cliente_local=loc,
                        uf="RS",
                        cidade="PORTO ALEGRE",
                        setor=st or "ESTOQUE LYDA",
                        modalidade=inferred_mod,
                        status_col=st,
                        obs=obs,
                        kit_analisador_ref="",
                    )

            # Caso 3: Planilha já exportada pelo nosso próprio sistema (colunas incluem CODIGO e TIPO)
            elif "CODIGO" in headers_upper and "TIPO" in headers_upper:
                for r in range(2, ws.max_row + 1):
                    row_dict = {}
                    for c_i, h_name in enumerate(headers_upper):
                        val = ws.cell(r, c_i + 1).value
                        row_dict[h_name] = "" if val is None else str(val).strip()
                    if row_dict.get("CODIGO"):
                        extracted.append(row_dict)

        if extracted:
            if self.items:
                self.create_backup(reason="antes_importar_excel")
            self.items = extracted
            self.save()
            self.add_history_log("SISTEMA", "TODOS", "IMPORTAÇÃO EXCEL", f"{len(extracted)} equipamentos carregados de {os.path.basename(excel_path)}")
            return len(extracted), f"{len(extracted)} equipamentos (Analisadores, Impressoras, Simuladores e Downloaders) importados e numerados com código de barras!"
        return 0, "Nenhum equipamento válido encontrado na planilha."

    def find_by_barcode(self, scanned_code: str) -> List[Dict[str, Any]]:
        """
        Busca um equipamento quando o usuário BIPA o código de barras no leitor USB.
        Aceita tanto o serial limpo ('446761') quanto leituras com prefixo '(21)446761' ou 'ANA-446761'.
        """
        raw = scanned_code.strip()
        if not raw:
            return []
        cleaned = clean_barcode_serial(raw)
        # Se tiver prefixo tipo ANA-446761
        for pref in ("ANA-", "IMP-", "SIM-", "DWL-"):
            if cleaned.startswith(pref):
                cleaned = cleaned[len(pref) :]

        exact_matches = [
            it
            for it in self.items
            if it.get("CODIGO", "").upper() == cleaned.upper()
            or clean_barcode_serial(it.get("SERIAL_ORIGINAL", "")) == cleaned.upper()
            or it.get("ID", "").upper() == raw.upper()
        ]
        if exact_matches:
            return exact_matches

        # Busca parcial caso tenha bipado apenas parte ou digitado manualmente
        partial = [
            it
            for it in self.items
            if cleaned.upper() in it.get("CODIGO", "").upper()
            or cleaned.upper() in it.get("SERIAL_ORIGINAL", "").upper()
        ]
        return partial

    def upsert_item(
        self,
        item_data: Dict[str, Any],
        original_idx: Optional[int] = None,
        custom_action: str = "",
        custom_details: str = "",
        responsavel: str = "",
    ) -> Dict[str, Any]:
        """Adiciona ou atualiza um equipamento (Analisador, Impressora, Simulador ou Downloader)."""
        bc = clean_barcode_serial(item_data.get("CODIGO") or item_data.get("SERIAL_ORIGINAL", ""))
        tipo = normalize_equipment_type(item_data.get("TIPO", "ANALISADOR"))
        cliente_val = item_data.get("CLIENTE", "").strip() or "SEM CLIENTE (ESTOQUE LYDA)"
        condicao_val = item_data.get("CONDICAO", "PERFEITO / FUNCIONANDO 100%").strip()
        defeito_val = item_data.get("DEFEITO", "").strip()
        obs_val = item_data.get("OBSERVACOES", "").strip()

        prev_rec = self.items[original_idx] if (original_idx is not None and 0 <= original_idx < len(self.items)) else {}
        endereco_val = item_data.get("ENDERECO", prev_rec.get("ENDERECO", "")).strip()
        cep_val = item_data.get("CEP", prev_rec.get("CEP", "")).strip()
        contato_val = item_data.get("CONTATO_LOCAL", prev_rec.get("CONTATO_LOCAL", "")).strip()
        ult_att_val = item_data.get("ULTIMA_ATUALIZACAO", prev_rec.get("ULTIMA_ATUALIZACAO", "")).strip()
        versao_clew_val = item_data.get("VERSAO_CLEW", prev_rec.get("VERSAO_CLEW", "")).strip()
        try:
            ciclo_meses_val = max(1, int(item_data.get("CICLO_ATUALIZACAO_MESES", prev_rec.get("CICLO_ATUALIZACAO_MESES", self.default_update_cycle_months)) or 6))
        except Exception:
            ciclo_meses_val = 6
        att_estoque_val = item_data.get("ATUALIZADO_NO_ESTOQUE", prev_rec.get("ATUALIZADO_NO_ESTOQUE", "")).strip()
        nf_val = item_data.get("NOTA_FISCAL", prev_rec.get("NOTA_FISCAL", "")).strip()
        acessorios_val = item_data.get("ACESSORIOS", prev_rec.get("ACESSORIOS", "")).strip()

        # Se o status é Estoque (ex: ESTOQUE USADOS, ESTOQUE LYDA NOVOS ou ESTOQUE),
        # ou se o cliente foi preenchido como Sem Cliente / Estoque:
        # o aparelho está no armário da LYDA, portanto SEMPRE deve ser SEM CLIENTE (ESTOQUE LYDA)
        status_input = item_data.get("STATUS", prev_rec.get("STATUS", "ATIVO NO CLIENTE")).strip().upper()
        is_stock_status = "ESTOQUE" in status_input
        is_stock_client = any(k in cliente_val.upper() for k in ("SEM CLIENTE", "ESTOQUE", "LYDA"))

        if is_stock_status:
            cliente_val = "SEM CLIENTE (ESTOQUE LYDA)"
            modalidade_val = "PROPRIEDADE LYDA"
            setor_val = item_data.get("SETOR", prev_rec.get("SETOR", "")).strip().upper()
            if not setor_val or setor_val in ("USADO", "NOVO", "ESTOQUE", "GERAL"):
                setor_val = "ESTOQUE LYDA (NOVOS)" if "NOVOS" in status_input else "ESTOQUE LYDA"
            endereco_val = self.lyda_hq_address
            cidade_val = "PORTO ALEGRE"
            uf_val = "RS"
            cep_val = "91130-470"
        else:
            modalidade_val = item_data.get("MODALIDADE", prev_rec.get("MODALIDADE", "COMODATO")).strip().upper()
            setor_val = item_data.get("SETOR", prev_rec.get("SETOR", "")).strip().upper()
            cidade_val = item_data.get("CIDADE", prev_rec.get("CIDADE", "")).strip().upper()
            uf_val = item_data.get("UF", prev_rec.get("UF", "")).strip().upper()

        if not endereco_val:
            cli_up = cliente_val.upper()
            if "ESTOQUE" in cli_up or "SEM CLIENTE" in cli_up or cli_up.startswith("LYDA"):
                endereco_val = self.lyda_hq_address
                cep_val = cep_val or "90240-005"
            else:
                sug = get_suggested_hospital_address(cliente_val)
                if sug:
                    endereco_val = sug.get("ENDERECO", "")
                    cep_val = cep_val or sug.get("CEP", "")

        record = {
            "ID": f"{tipo[:3]}-{bc}",
            "CODIGO": bc,
            "SERIAL_ORIGINAL": item_data.get("SERIAL_ORIGINAL") or bc,
            "TIPO": tipo,
            "EQUIPAMENTO": f"i-STAT {tipo.title()}",
            "CLIENTE": cliente_val,
            "ENDERECO": endereco_val,
            "CEP": cep_val,
            "CONTATO_LOCAL": contato_val,
            "UF": uf_val,
            "CIDADE": cidade_val,
            "SETOR": setor_val,
            "MODALIDADE": modalidade_val,
            "STATUS": status_input,
            "CONDICAO": condicao_val,
            "DEFEITO": defeito_val,
            "ULTIMA_ATUALIZACAO": ult_att_val,
            "VERSAO_CLEW": versao_clew_val,
            "CICLO_ATUALIZACAO_MESES": ciclo_meses_val,
            "ATUALIZADO_NO_ESTOQUE": att_estoque_val,
            "NOTA_FISCAL": nf_val,
            "ACESSORIOS": acessorios_val,
            "KIT_ANALISADOR": item_data.get("KIT_ANALISADOR", prev_rec.get("KIT_ANALISADOR", "")).strip(),
            "OBSERVACOES": obs_val,
            "ATUALIZADO_EM": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "ULTIMO_OPERADOR": (responsavel or self.operador_atual or "OPERADOR").strip(),
            "ULTIMO_PC": self.pc_hostname,
            "_updated_epoch": time.time(),
        }
        cyc_info = compute_update_cycle_info(record)
        record["PROXIMA_ATUALIZACAO"] = cyc_info["summary_table"]
        action_label = custom_action or ("MOVIMENTAÇÃO / EDIÇÃO" if original_idx is not None else "NOVO CADASTRO")
        details_str = custom_details or (
            f"Cliente/Local: {record['CLIENTE']} | Endereço: {endereco_val or '-'} | Modalidade: {record['MODALIDADE']} | "
            f"Status: {record['STATUS']} | Últ. Atualização: {ult_att_val or 'Pendente'} (Próx: {cyc_info['next_date_str']})"
            + (f" | Estoque Atualizado: {att_estoque_val}" if att_estoque_val else "")
            + (f" | Defeito/Obs: {defeito_val or obs_val}" if (defeito_val or obs_val) else "")
            + (f" | Resp: {responsavel}" if responsavel else "")
        )

        # Localiza se este equipamento já existe na base para atualizar SEM DUPLICAR
        target_idx = None
        if original_idx is not None and 0 <= original_idx < len(self.items):
            target_idx = original_idx
        else:
            for i, it in enumerate(self.items):
                if it.get("CODIGO") == bc and normalize_equipment_type(it.get("TIPO", "")) == tipo:
                    target_idx = i
                    break
            if target_idx is None:
                for i, it in enumerate(self.items):
                    if it.get("CODIGO") == bc:
                        target_idx = i
                        break

        if target_idx is not None and 0 <= target_idx < len(self.items):
            self.items[target_idx] = record
        else:
            self.items.append(record)

        # Remove eventuais duplicatas anteriores deste mesmo serial se existirem em outros índices
        unique_items = []
        seen_keys = set()
        for it in self.items:
            k = (normalize_equipment_type(it.get("TIPO", "")), clean_barcode_serial(it.get("CODIGO", "")))
            if k[1]:
                if k in seen_keys:
                    continue
                seen_keys.add(k)
            unique_items.append(it)
        self.items = unique_items

        self.add_history_log(
            serial_barcode=bc,
            tipo=tipo,
            acao=action_label,
            detalhes=details_str,
            cliente=record["CLIENTE"],
            modalidade=record["MODALIDADE"],
            condicao=condicao_val,
            defeito_obs=defeito_val or obs_val,
            responsavel=responsavel,
        )
        self.save()
        return record

    def delete_indices(self, indices: List[int]):
        if indices and self.items:
            self.create_backup(reason="antes_excluir_item")
        for idx in sorted(indices, reverse=True):
            if 0 <= idx < len(self.items):
                removed = self.items.pop(idx)
                self.add_history_log(removed.get("CODIGO", ""), removed.get("TIPO", ""), "EXCLUSÃO", f"Removido ({removed.get('CLIENTE', '')})")
        self.save()

    def export_to_excel(self, output_path: str) -> str:
        """
        Exporta toda a base atualizada para um arquivo Excel (.xlsx) organizado:
        - Aba 1: 'Base Unificada (Códigos Barras)' (pronta para filtro e auditoria, 1 linha por serial)
        - Aba 2: 'Venda' (no formato tradicional da Lyda)
        - Aba 3: 'Comodato ' (no formato tradicional da Lyda)
        - Aba 4: ' Propriedade LYda' (no formato tradicional da Lyda)
        - Aba 5: 'Historico Bipagens'
        """
        import openpyxl  # type: ignore
        from openpyxl.styles import Font, PatternFill  # type: ignore

        wb = openpyxl.Workbook()
        # Aba 1: Base Unificada
        ws_all = wb.active
        ws_all.title = "Todos_Equipamentos_CodBarras"
        cols_all = [
            "ID",
            "CODIGO",
            "TIPO",
            "SERIAL_ORIGINAL",
            "CLIENTE",
            "ENDERECO",
            "CEP",
            "CIDADE",
            "UF",
            "SETOR",
            "CONTATO_LOCAL",
            "MODALIDADE",
            "STATUS",
            "ULTIMA_ATUALIZACAO",
            "KIT_ANALISADOR",
            "OBSERVACOES",
            "ATUALIZADO_EM",
        ]
        ws_all.append(cols_all)
        for cell in ws_all[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="0F172A")

        for it in self.items:
            ws_all.append([it.get(c, "") for c in cols_all])

        # Aba Propriedade Lyda
        ws_prop = wb.create_sheet("Propriedade LYda")
        ws_prop.append(["Equipamento", "Serial", "Código de Barras", "Localização", "Status", "Observações"])
        for cell in ws_prop[1]:
            cell.font = Font(bold=True)
        for it in self.items:
            if it.get("MODALIDADE") == "PROPRIEDADE LYDA":
                ws_prop.append(
                    [
                        it.get("TIPO", "").title(),
                        it.get("SERIAL_ORIGINAL", ""),
                        it.get("CODIGO", ""),
                        it.get("CLIENTE", ""),
                        it.get("STATUS", ""),
                        it.get("OBSERVACOES", ""),
                    ]
                )

        # Aba Histórico de Bipagens
        ws_hist = wb.create_sheet("Historico_Bipagens")
        ws_hist.append(["DATA_HORA", "CODIGO_BARRAS", "TIPO", "ACAO", "DETALHES"])
        for cell in ws_hist[1]:
            cell.font = Font(bold=True)
        for h in self.history:
            ws_hist.append([h.get("DATA_HORA", ""), h.get("CODIGO_BARRAS", ""), h.get("TIPO", ""), h.get("ACAO", ""), h.get("DETALHES", "")])

        wb.save(output_path)
        return output_path

