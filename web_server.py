"""
Servidor Web Local & Multi-Usuários na Rede Interna — LYDA Controle de Estoque i-STAT.
Permite que um computador da LYDA atue como Servidor Central (mantendo o banco de dados local rápido e seguro),
enquanto todos os outros computadores e celulares da rede acessam pelo navegador via link (ex: http://192.168.x.x:8080),
com Sistema de Login/Senha, Perfis de Acesso (ADMIN e USUARIO), Auditoria Completa de Logs e
Backup Diário Automático enviado para a pasta do SharePoint da LYDA.
"""

import csv
import io
import json
import os
import platform
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from datetime import datetime
from functools import wraps
from typing import Any, Dict, List, Optional

from flask import (
    Flask,
    Response,
    jsonify,
    render_template,
    request,
    send_file,
    session,
)

from auth_manager import AuthAndAuditManager
from istat_database import (
    CONDICAO_FISICA_OPTIONS,
    EQUIPMENT_TYPES,
    IStatDatabaseManager,
    MODALITIES,
    MOVIMENTO_ACOES,
    STATUS_OPTIONS,
    classify_item_row_state,
    clean_barcode_serial,
)
from logo_zpl import get_default_logo_path
from printer_manager import dispatch_zpl_print, list_system_printers
from romaneio_generator import generate_and_open_romaneio, generate_termo_substituicao_html
from rota_enfermeira import (
    DEFAULT_LYDA_SEDE_ADDRESS,
    build_google_maps_multi_stop_url,
    build_single_stop_maps_url,
    build_single_stop_waze_url,
    build_whatsapp_route_summary,
    compute_route_metrics_and_geometry,
    compute_update_cycle_info,
    generate_nurse_route_pdf,
    get_logo_base64_data_uri,
    get_suggested_hospital_address,
    group_items_into_route_stops,
    lookup_cep_viacep,
    optimize_stops_order,
)
from zpl_engine import ExtraFieldConfig, LabelLayoutConfig, ZPLGenerator


WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(WORKSPACE_DIR, "web_templates")
STATIC_DIR = os.path.join(WORKSPACE_DIR, "web_static")
ATTACHMENTS_DIR = os.path.join(WORKSPACE_DIR, "anexos_equipamentos")
os.makedirs(TEMPLATE_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(ATTACHMENTS_DIR, exist_ok=True)

app = Flask(__name__, template_folder=TEMPLATE_DIR, static_folder=STATIC_DIR, static_url_path="/static")
app.config["JSON_AS_ASCII"] = False
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024  # 32 MB upload max
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

# Chave secreta persistente para sessões de login no servidor
_secret_file = os.path.join(WORKSPACE_DIR, ".lyda_web_secret")
if os.path.exists(_secret_file):
    try:
        with open(_secret_file, "r", encoding="utf-8") as _sf:
            app.secret_key = _sf.read().strip() or "lyda-istat-secret-2026"
    except Exception:
        app.secret_key = "lyda-istat-secret-2026"
else:
    _gen_key = secrets.token_hex(32)
    try:
        with open(_secret_file, "w", encoding="utf-8") as _sf:
            _sf.write(_gen_key)
    except Exception:
        pass
    app.secret_key = _gen_key

db_lock = threading.RLock()
db_manager = IStatDatabaseManager(WORKSPACE_DIR)
auth_manager = AuthAndAuditManager(db_manager.shared_db_dir)


def get_client_ip() -> str:
    fwd = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    return fwd or request.remote_addr or "127.0.0.1"


def get_current_user() -> Optional[Dict[str, Any]]:
    uname = session.get("lyda_username")
    if not uname:
        return None
    u = auth_manager.get_user(uname)
    if not u or not u.get("active", True):
        session.pop("lyda_username", None)
        return None
    return auth_manager.sanitize_user(u)


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({"ok": False, "auth_required": True, "error": "Sessão expirada. Faça login novamente."}), 401
        return fn(*args, **kwargs)
    return wrapper


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({"ok": False, "auth_required": True, "error": "Faça login para continuar."}), 401
        if user.get("role") != "ADMIN":
            return jsonify({"ok": False, "error": "Acesso restrito a Administradores."}), 403
        return fn(*args, **kwargs)
    return wrapper


def log_user_action(
    category: str,
    action: str,
    target: str = "",
    details: str = "",
    severity: str = "INFO",
):
    u = get_current_user() or {"username": "sistema", "nome": db_manager.operador_atual or "SISTEMA", "role": "USUARIO"}
    auth_manager.record_log(
        username=u.get("username", "sistema"),
        user_nome=u.get("nome", "SISTEMA"),
        user_role=u.get("role", "USUARIO"),
        category=category,
        action=action,
        target=target,
        details=details,
        ip_address=get_client_ip(),
        severity=severity,
    )


def get_local_network_ips() -> List[str]:
    """Descobre os endereços IP locais (Wi-Fi / Ethernet) deste PC Servidor na rede da LYDA."""
    ips: List[str] = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        primary_ip = s.getsockname()[0]
        s.close()
        if primary_ip and not primary_ip.startswith("127."):
            ips.append(primary_ip)
    except Exception:
        pass

    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
    except Exception:
        pass

    if not ips:
        ips.append("127.0.0.1")
    return ips


def enrich_item_for_api(idx: int, item: Dict[str, Any], default_cycle_months: int = 6) -> Dict[str, Any]:
    """Adiciona campos calculados de ciclo de 6 meses e classificação visual para o frontend Web."""
    cyc = compute_update_cycle_info(item, default_cycle_months)
    row_state = classify_item_row_state(item)
    out = dict(item)
    out["_idx"] = idx
    out["_row_state"] = row_state
    out["_cycle"] = cyc
    out["PROXIMA_ATUALIZACAO"] = cyc["summary_table"]
    return out


def compute_dashboard_kpis(items: List[Dict[str, Any]], default_cycle_months: int = 6) -> Dict[str, int]:
    total = len(items)
    em_cliente = 0
    em_estoque = 0
    em_defeito = 0
    defeito_em_cliente = 0
    defeito_em_estoque = 0
    comodato_aluguel = 0
    comodato_ativo = 0
    comodato_manut = 0
    venda = 0
    venda_ativo = 0
    venda_manut = 0
    propriedade_lyda = 0
    ciclo_em_dia = 0
    ciclo_vencendo = 0
    ciclo_vencida = 0
    ciclo_sem_data = 0
    ciclo_pendente_vencido = 0
    estoque_atualizado = 0
    estoque_falta_atualizar = 0
    estoque_novos = 0
    estoque_usados = 0
    estoque_backup = 0

    for it in items:
        st = classify_item_row_state(it)
        cli_up = str(it.get("CLIENTE", "")).strip().upper()
        st_up = str(it.get("STATUS", "")).strip().upper()
        setor_up = str(it.get("SETOR", "")).strip().upper()
        is_stock_loc = (
            not cli_up
            or "SEM CLIENTE" in cli_up
            or "ESTOQUE" in cli_up
            or cli_up in ("LYDA", "LYDA COMERCIO IMPORTAÇÃO E EXPORTAÇÃO LTDA", "LYDA COMERCIO IMPORTACAO E EXPORTACAO LTDA")
        )
        if st == "ESTOQUE":
            em_estoque += 1
            att_est = str(it.get("ATUALIZADO_NO_ESTOQUE", "")).upper()
            if "SIM" in att_est:
                estoque_atualizado += 1
            elif "NÃO" in att_est or "NAO" in att_est or "FALTA" in att_est:
                estoque_falta_atualizar += 1

            if "NOVO" in st_up or "NOVO" in cli_up or "NOVO" in setor_up:
                estoque_novos += 1
            elif "BACKUP" in st_up or "BACK UP" in st_up or "BACKUP" in cli_up or "DEVOLVIDO" in st_up:
                estoque_backup += 1
            else:
                estoque_usados += 1
        elif st == "DEFEITO":
            em_defeito += 1
            if is_stock_loc:
                defeito_em_estoque += 1
            else:
                defeito_em_cliente += 1
        else:
            em_cliente += 1

        mod = str(it.get("MODALIDADE", "")).upper()
        if mod in ("COMODATO", "ALUGUEL"):
            comodato_aluguel += 1
            if st == "DEFEITO":
                comodato_manut += 1
            elif st == "ATIVO":
                comodato_ativo += 1
        elif mod == "VENDA":
            venda += 1
            if st == "DEFEITO":
                venda_manut += 1
            elif st == "ATIVO":
                venda_ativo += 1
        else:
            propriedade_lyda += 1

        cyc = compute_update_cycle_info(it, default_cycle_months)
        st_code = cyc["status_code"]
        if st_code == "EM_DIA":
            ciclo_em_dia += 1
        elif st_code == "VENCENDO":
            ciclo_vencendo += 1
            ciclo_pendente_vencido += 1
        elif st_code == "VENCIDA":
            ciclo_vencida += 1
            ciclo_pendente_vencido += 1
        else:
            ciclo_sem_data += 1
            ciclo_pendente_vencido += 1

    return {
        "total": total,
        "em_cliente": em_cliente,
        "em_estoque": em_estoque,
        "em_defeito": em_defeito,
        "defeito_manutencao": em_defeito,
        "defeito_em_cliente": defeito_em_cliente,
        "defeito_em_estoque": defeito_em_estoque,
        "total_vinculados_cliente": em_cliente + defeito_em_cliente,
        "total_vinculados_estoque": em_estoque + defeito_em_estoque,
        "comodato_aluguel": comodato_aluguel,
        "comodato": comodato_aluguel,
        "comodato_ativo": comodato_ativo,
        "comodato_manut": comodato_manut,
        "venda": venda,
        "venda_ativo": venda_ativo,
        "venda_manut": venda_manut,
        "propriedade_lyda": propriedade_lyda,
        "ciclo_em_dia": ciclo_em_dia,
        "ciclo_vencendo": ciclo_vencendo,
        "ciclo_vencida": ciclo_vencida,
        "ciclo_sem_data": ciclo_sem_data,
        "ciclo_pendente_vencido": ciclo_pendente_vencido,
        "estoque_atualizado": estoque_atualizado,
        "estoque_falta_atualizar": estoque_falta_atualizar,
        "estoque_novos": estoque_novos,
        "estoque_usados": estoque_usados,
        "estoque_backup": estoque_backup,
    }


def _background_daily_backup_scheduler():
    """
    Thread em background no Servidor que garante:
    1. Backup diário automático no início do dia.
    2. Disparo automático no horário programado (ex: 18:00) enviando Banco JSON + Planilha Excel para o SharePoint.
    """
    last_triggered_date = ""
    while True:
        try:
            time.sleep(60)
            now = datetime.now()
            today_str = now.strftime("%Y-%m-%d")
            current_hhmm = now.strftime("%H:%M")
            with db_lock:
                db_manager.ensure_daily_backup()
                target_hhmm = getattr(db_manager, "sharepoint_backup_time", "18:00") or "18:00"
                if current_hhmm == target_hhmm and last_triggered_date != today_str:
                    last_triggered_date = today_str
                    db_manager.sync_backup_to_sharepoint(reason="agendado_diario_sharepoint")
        except Exception:
            pass


scheduler_thread = threading.Thread(target=_background_daily_backup_scheduler, daemon=True)
scheduler_thread.start()


# =============================================================================
# ROTAS DE AUTENTICAÇÃO, PERFIL E GESTÃO DE USUÁRIOS / LOGS (ADMIN)
# =============================================================================

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/auth/login", methods=["POST"])
def api_auth_login():
    data = request.get_json(force=True) or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    with db_lock:
        ok, msg, user = auth_manager.authenticate(username, password, ip_address=get_client_ip())
        if not ok or not user:
            return jsonify({"ok": False, "error": msg}), 401
        session["lyda_username"] = user["username"]
        session.permanent = True
        # Sincroniza o nome do usuário logado na lista de operadores
        if user.get("nome"):
            db_manager.add_operator(user["nome"])
        return jsonify({"ok": True, "message": msg, "user": user})


@app.route("/api/auth/logout", methods=["POST"])
def api_auth_logout():
    with db_lock:
        u = get_current_user()
        if u:
            auth_manager.record_log(
                username=u["username"],
                user_nome=u["nome"],
                user_role=u["role"],
                category="ACESSO",
                action="LOGOUT DO SISTEMA",
                target=u["username"],
                details=f"Sessão encerrada pelo usuário via IP {get_client_ip()}",
                ip_address=get_client_ip(),
                severity="INFO",
            )
        session.pop("lyda_username", None)
        return jsonify({"ok": True, "message": "Sessão encerrada com sucesso."})


@app.route("/api/auth/profile", methods=["POST"])
@login_required
def api_auth_update_profile():
    data = request.get_json(force=True) or {}
    u = get_current_user()
    with db_lock:
        ok, msg, updated_user = auth_manager.update_own_profile(
            username=u["username"],
            payload=data,
            ip_address=get_client_ip(),
        )
        if not ok:
            return jsonify({"ok": False, "error": msg}), 400
        if updated_user and updated_user.get("nome"):
            db_manager.add_operator(updated_user["nome"])
        return jsonify({"ok": True, "message": msg, "user": updated_user})


@app.route("/api/auth/force-change-password", methods=["POST"])
@login_required
def api_auth_force_change_password():
    data = request.get_json(force=True) or {}
    new_password = (data.get("new_password") or "").strip()
    confirm_password = (data.get("confirm_password") or "").strip()
    if not new_password:
        return jsonify({"ok": False, "error": "Informe a nova senha desejada."}), 400
    if len(new_password) < 4:
        return jsonify({"ok": False, "error": "A nova senha deve ter no mínimo 4 caracteres."}), 400
    if new_password.lower() == "lyda123":
        return jsonify({"ok": False, "error": "A nova senha não pode ser a senha temporária 'lyda123'. Escolha uma senha pessoal segura."}), 400
    if new_password != confirm_password:
        return jsonify({"ok": False, "error": "A confirmação da senha não coincide com a nova senha digitada."}), 400

    u = get_current_user()
    with db_lock:
        ok, msg, updated_user = auth_manager.force_change_password(
            username=u["username"],
            new_password=new_password,
            ip_address=get_client_ip(),
        )
        if not ok:
            return jsonify({"ok": False, "error": msg}), 400
        return jsonify({"ok": True, "message": msg, "user": updated_user})


@app.route("/api/admin/users", methods=["GET"])
@admin_required
def api_admin_list_users():
    with db_lock:
        return jsonify({"ok": True, "users": auth_manager.list_public_users()})


@app.route("/api/admin/users/save", methods=["POST"])
@admin_required
def api_admin_save_user():
    data = request.get_json(force=True) or {}
    admin_u = get_current_user()
    with db_lock:
        ok, msg, saved_u = auth_manager.create_or_update_user_by_admin(
            admin_user=admin_u,
            payload=data,
            ip_address=get_client_ip(),
        )
        if not ok:
            return jsonify({"ok": False, "error": msg}), 400
        if saved_u and saved_u.get("nome"):
            db_manager.add_operator(saved_u["nome"])
        return jsonify(
            {
                "ok": True,
                "message": msg,
                "user": saved_u,
                "users": auth_manager.list_public_users(),
            }
        )


@app.route("/api/admin/users/delete", methods=["POST"])
@admin_required
def api_admin_delete_user():
    data = request.get_json(force=True) or {}
    target_username = (data.get("username") or "").strip()
    admin_u = get_current_user()
    with db_lock:
        ok, msg = auth_manager.delete_user_by_admin(
            admin_user=admin_u,
            target_username=target_username,
            ip_address=get_client_ip(),
        )
        if not ok:
            return jsonify({"ok": False, "error": msg}), 400
        return jsonify({"ok": True, "message": msg, "users": auth_manager.list_public_users()})


def _build_unified_audit_logs() -> List[Dict[str, Any]]:
    """
    Combina os logs de auditoria do sistema (logins, usuários, backups, rotas)
    com o histórico de movimentação dos aparelhos para que o Admin tenha visão 360º.
    """
    combined: List[Dict[str, Any]] = list(auth_manager.audit_logs)
    seen_epochs = {round(float(x.get("_epoch", 0) or 0), 2) for x in combined}

    for h in db_manager.history[:800]:
        ep = float(h.get("_epoch", 0) or 0)
        if round(ep, 2) in seen_epochs:
            continue
        op = (h.get("OPERADOR") or h.get("RESPONSAVEL") or "OPERADOR").upper()
        combined.append(
            {
                "id": f"HIST-{int(ep * 1000)}",
                "_epoch": ep,
                "timestamp": h.get("DATA_HORA", ""),
                "date_only": "",
                "username": op.lower().replace(" ", ""),
                "user_nome": op,
                "user_role": "OPERADOR",
                "category": "ESTOQUE",
                "action": h.get("ACAO", "MOVIMENTAÇÃO"),
                "target": f"{h.get('TIPO', '')} [{h.get('CODIGO_BARRAS', '')}]".strip(),
                "details": f"{h.get('CLIENTE', '')} — {h.get('DETALHES', '')}".strip(" —"),
                "ip_address": h.get("COMPUTADOR", "Servidor"),
                "severity": "INFO",
            }
        )

    combined.sort(key=lambda x: float(x.get("_epoch", 0) or 0), reverse=True)
    return combined[:1500]


@app.route("/api/admin/logs", methods=["GET"])
@admin_required
def api_admin_list_logs():
    with db_lock:
        logs = _build_unified_audit_logs()
        return jsonify({"ok": True, "logs": logs})


@app.route("/api/admin/logs/manage", methods=["POST"])
@admin_required
def api_admin_manage_logs():
    data = request.get_json(force=True) or {}
    action = (data.get("action") or "").strip().upper()
    admin_u = get_current_user()
    with db_lock:
        if action == "DELETE_ONE":
            log_id = (data.get("log_id") or "").strip()
            auth_manager.delete_audit_log_by_admin(log_id)
            return jsonify({"ok": True, "message": "Registro de log removido.", "logs": _build_unified_audit_logs()})
        elif action == "CLEAR_OLD":
            keep_last = int(data.get("keep_last") or 100)
            removed = auth_manager.clear_old_logs_by_admin(admin_u, keep_last=keep_last, ip_address=get_client_ip())
            return jsonify(
                {
                    "ok": True,
                    "message": f"{removed} log(s) antigo(s) removido(s). Mantidos os {keep_last} mais recentes.",
                    "logs": _build_unified_audit_logs(),
                }
            )
        return jsonify({"ok": False, "error": "Ação inválida."}), 400


@app.route("/api/admin/logs/export_csv", methods=["GET"])
@admin_required
def api_admin_export_logs_csv():
    with db_lock:
        logs = _build_unified_audit_logs()
        output = io.StringIO()
        output.write("\ufeff")  # BOM UTF-8 p/ Excel abrir acentos perfeitamente
        writer = csv.writer(output, delimiter=";")
        writer.writerow(["DATA_HORA", "USUARIO_LOGIN", "NOME_USUARIO", "PERFIL", "CATEGORIA", "ACAO", "ALVO_SERIAL", "DETALHES", "IP_COMPUTADOR", "NIVEL"])
        for lg in logs:
            writer.writerow([
                lg.get("timestamp", ""),
                lg.get("username", ""),
                lg.get("user_nome", ""),
                lg.get("user_role", ""),
                lg.get("category", ""),
                lg.get("action", ""),
                lg.get("target", ""),
                lg.get("details", ""),
                lg.get("ip_address", ""),
                lg.get("severity", ""),
            ])
        csv_bytes = output.getvalue().encode("utf-8")
        fname = f"Auditoria_Logs_LYDA_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        return Response(
            csv_bytes,
            mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename={fname}"},
        )


# =============================================================================
# ROTAS PRINCIPAIS DA INTERFACE WEB E API REST
# =============================================================================

@app.route("/api/bootstrap", methods=["GET"])
def api_bootstrap():
    with db_lock:
        current_user = get_current_user()
        logo_uri = get_logo_base64_data_uri(white_ink=False)
        logo_white_uri = get_logo_base64_data_uri(white_ink=True)
        if not current_user:
            return jsonify(
                {
                    "ok": True,
                    "authenticated": False,
                    "logo_data_uri": logo_uri,
                    "logo_white_data_uri": logo_white_uri,
                    "login_hints": [],
                }
            )

        db_manager.check_for_external_updates()
        def_cyc = db_manager.default_update_cycle_months
        enriched_items = [
            enrich_item_for_api(idx, it, def_cyc)
            for idx, it in enumerate(db_manager.items)
        ]
        clients = db_manager.get_all_clients_records()
        known_client_names = db_manager.get_known_clients()
        kpis = compute_dashboard_kpis(db_manager.items, def_cyc)
        ips = get_local_network_ips()
        port = int(os.environ.get("LYDA_WEB_PORT", "8080"))
        primary_url = f"http://{ips[0]}:{port}"
        all_urls = [f"http://{ip}:{port}" for ip in ips]

        # Garante que todos os usuários ativos constem também como operadores
        for u_rec in auth_manager.users:
            if u_rec.get("active", True) and u_rec.get("nome"):
                if u_rec["nome"] not in db_manager.operators:
                    db_manager.operators.append(u_rec["nome"])

        is_admin = current_user.get("role") == "ADMIN"

        return jsonify(
            {
                "ok": True,
                "authenticated": True,
                "current_user": current_user,
                "logo_data_uri": logo_uri,
                "logo_white_data_uri": logo_white_uri,
                "server_info": {
                    "hostname": db_manager.pc_hostname,
                    "os_name": platform.system(),
                    "primary_url": primary_url,
                    "all_urls": all_urls,
                    "port": port,
                    "workspace_dir": WORKSPACE_DIR,
                    "db_dir": db_manager.shared_db_dir,
                    "sharepoint_backup_dir": getattr(db_manager, "sharepoint_backup_dir", ""),
                    "sharepoint_backup_time": getattr(db_manager, "sharepoint_backup_time", "18:00"),
                    "sharepoint_auto_sync": getattr(db_manager, "sharepoint_auto_sync", True),
                    "last_sharepoint_backup_at": getattr(db_manager, "last_sharepoint_backup_at", ""),
                    "last_sharepoint_backup_status": getattr(db_manager, "last_sharepoint_backup_status", ""),
                    "sharepoint_candidates": db_manager.detect_sharepoint_folders(),
                },
                "config": {
                    "operador_atual": current_user.get("nome") or db_manager.operador_atual,
                    "operators": db_manager.operators,
                    "lyda_hq_address": db_manager.lyda_hq_address,
                    "default_update_cycle_months": def_cyc,
                    "equipment_types": EQUIPMENT_TYPES,
                    "modalities": MODALITIES,
                    "status_options": STATUS_OPTIONS,
                    "condicao_options": CONDICAO_FISICA_OPTIONS,
                    "movimento_acoes": MOVIMENTO_ACOES,
                    "printers": list_system_printers(),
                    "zebra_config": load_zebra_web_config(),
                },
                "kpis": kpis,
                "items": enriched_items,
                "clients": clients,
                "known_client_names": known_client_names,
                "history": db_manager.history[:300],
                "users": auth_manager.list_public_users() if is_admin else [current_user],
                "audit_logs": _build_unified_audit_logs()[:400] if is_admin else [],
            }
        )


@app.route("/api/scan", methods=["GET"])
@login_required
def api_scan_barcode():
    code = (request.args.get("code") or "").strip()
    if not code:
        return jsonify({"ok": False, "error": "Informe um código de barras ou serial."}), 400
    with db_lock:
        matches = db_manager.find_by_barcode(code)
        def_cyc = db_manager.default_update_cycle_months
        results = []
        for m in matches:
            try:
                idx = db_manager.items.index(m)
            except ValueError:
                idx = -1
            if idx >= 0:
                results.append(enrich_item_for_api(idx, m, def_cyc))
        cleaned = clean_barcode_serial(code)
        log_user_action(
            category="ESTOQUE",
            action="BIPAGEM / CONSULTA DE SERIAL",
            target=cleaned or code,
            details=f"{len(results)} equipamento(s) localizado(s) para o código '{code}'",
            severity="INFO",
        )
        return jsonify(
            {
                "ok": True,
                "scanned_code": code,
                "cleaned_code": cleaned,
                "matches": results,
            }
        )


@app.route("/api/item/<int:idx>/details", methods=["GET"])
@login_required
def api_item_details(idx: int):
    with db_lock:
        if idx < 0 or idx >= len(db_manager.items):
            return jsonify({"ok": False, "error": "Equipamento não encontrado."}), 404
        it = db_manager.items[idx]
        serial_bc = it.get("CODIGO", "")
        history = db_manager.get_item_history(serial_bc)
        companions = db_manager.get_kit_companions(serial_bc)
        comp_out = []
        for c in companions:
            try:
                c_idx = db_manager.items.index(c)
            except ValueError:
                c_idx = -1
            comp_out.append(enrich_item_for_api(c_idx, c, db_manager.default_update_cycle_months))
        return jsonify(
            {
                "ok": True,
                "item": enrich_item_for_api(idx, it, db_manager.default_update_cycle_months),
                "history": history,
                "companions": comp_out,
            }
        )


@app.route("/api/item/save", methods=["POST"])
@login_required
def api_item_save():
    data = request.get_json(force=True) or {}
    item_data = data.get("item") or {}
    original_idx = data.get("original_idx")
    if original_idx is not None:
        try:
            original_idx = int(original_idx)
            if original_idx < 0:
                original_idx = None
        except Exception:
            original_idx = None

    u = get_current_user()
    custom_action = (data.get("custom_action") or "").strip()
    custom_details = (data.get("custom_details") or "").strip()
    responsavel = (data.get("responsavel") or (u and u.get("nome")) or db_manager.operador_atual or "OPERADOR").strip()
    propagate_addr = bool(data.get("propagate_address", True))

    bc = clean_barcode_serial(item_data.get("CODIGO") or item_data.get("SERIAL_ORIGINAL", ""))
    if not bc:
        return jsonify({"ok": False, "error": "Informe o Número de Série / Código de Barras do aparelho."}), 400

    with db_lock:
        is_new = original_idx is None
        saved = db_manager.upsert_item(
            item_data=item_data,
            original_idx=original_idx,
            custom_action=custom_action,
            custom_details=custom_details,
            responsavel=responsavel,
        )
        if propagate_addr and saved.get("CLIENTE") and saved.get("ENDERECO"):
            db_manager.propagate_client_address(
                cliente_name=saved["CLIENTE"],
                endereco=saved.get("ENDERECO", ""),
                cep=saved.get("CEP", ""),
                cidade=saved.get("CIDADE", ""),
                uf=saved.get("UF", ""),
                contato_local=saved.get("CONTATO_LOCAL", ""),
            )
        db_manager._sync_clients_from_items()
        try:
            saved_idx = db_manager.items.index(saved)
        except ValueError:
            saved_idx = len(db_manager.items) - 1

        log_user_action(
            category="ESTOQUE",
            action="NOVO CADASTRO DE APARELHO" if is_new else "EDIÇÃO / MOVIMENTAÇÃO DE APARELHO",
            target=f"{saved.get('TIPO')} [{saved.get('CODIGO')}]",
            details=f"Local: {saved.get('CLIENTE')} | Status: {saved.get('STATUS')} | Últ. Att: {saved.get('ULTIMA_ATUALIZACAO') or '-'} | Resp: {responsavel}",
            severity="SUCCESS",
        )

        return jsonify(
            {
                "ok": True,
                "message": f"Aparelho {saved.get('TIPO')} [{saved.get('CODIGO')}] salvo com sucesso!",
                "item": enrich_item_for_api(saved_idx, saved, db_manager.default_update_cycle_months),
            }
        )


@app.route("/api/items/delete", methods=["POST"])
@admin_required
def api_items_delete():
    data = request.get_json(force=True) or {}
    indices = data.get("indices") or []
    clean_indices = [int(i) for i in indices if str(i).isdigit()]
    if not clean_indices:
        return jsonify({"ok": False, "error": "Nenhum equipamento selecionado para excluir."}), 400
    with db_lock:
        seriais = [db_manager.items[i].get("CODIGO", "") for i in clean_indices if 0 <= i < len(db_manager.items)]
        db_manager.delete_indices(clean_indices)
        log_user_action(
            category="ESTOQUE",
            action="EXCLUSÃO DE APARELHO(S)",
            target=", ".join(seriais[:8]),
            details=f"{len(clean_indices)} aparelho(s) excluído(s) da base.",
            severity="WARNING",
        )
        return jsonify({"ok": True, "message": f"{len(clean_indices)} equipamento(s) excluído(s) com sucesso."})


@app.route("/api/items/batch_action", methods=["POST"])
@login_required
def api_items_batch_action():
    """
    Executa operações em lote sobre vários aparelhos selecionados na tabela:
    - 'ENVIAR_CLIENTE': envia lote para um Hospital/Cliente com endereço completo
    - 'DEVOLVER_ESTOQUE': retorna lote para o Estoque da LYDA (Já Atualizado ou Falta Atualizar)
    - 'MARCAR_ATUALIZADO_6M': registra data de atualização semestral (CLEW/JAMS) em todos os selecionados
    """
    data = request.get_json(force=True) or {}
    indices = [int(i) for i in (data.get("indices") or []) if str(i).lstrip("-").isdigit()]
    action_type = (data.get("action_type") or "").strip().upper()
    u = get_current_user()
    responsavel = (data.get("responsavel") or (u and u.get("nome")) or db_manager.operador_atual or "OPERADOR").strip()

    if not indices:
        return jsonify({"ok": False, "error": "Selecione pelo menos 1 aparelho na tabela."}), 400

    with db_lock:
        updated_items = []
        today_str = datetime.now().strftime("%d/%m/%Y")

        if action_type == "ENVIAR_CLIENTE":
            cliente = (data.get("cliente") or "").strip()
            if not cliente:
                return jsonify({"ok": False, "error": "Selecione o Hospital / Cliente de destino."}), 400
            addr_info = db_manager.get_client_address_info(cliente)
            endereco = (data.get("endereco") or addr_info.get("ENDERECO") or "").strip()
            cep = (data.get("cep") or addr_info.get("CEP") or "").strip()
            cidade = (data.get("cidade") or addr_info.get("CIDADE") or "PORTO ALEGRE").strip().upper()
            uf = (data.get("uf") or addr_info.get("UF") or "RS").strip().upper()
            setor = (data.get("setor") or "").strip().upper()
            modalidade = (data.get("modalidade") or "COMODATO").strip().upper()
            observacoes = (data.get("observacoes") or "").strip()

            for idx in indices:
                if 0 <= idx < len(db_manager.items):
                    it = dict(db_manager.items[idx])
                    it["CLIENTE"] = cliente
                    it["STATUS"] = "ATIVO NO CLIENTE"
                    it["MODALIDADE"] = modalidade
                    if endereco:
                        it["ENDERECO"] = endereco
                    if cep:
                        it["CEP"] = cep
                    if cidade:
                        it["CIDADE"] = cidade
                    if uf:
                        it["UF"] = uf
                    if setor:
                        it["SETOR"] = setor
                    if observacoes:
                        it["OBSERVACOES"] = observacoes
                    it["ATUALIZADO_NO_ESTOQUE"] = "EM USO NO CLIENTE / N/A"
                    saved = db_manager.upsert_item(
                        it,
                        original_idx=idx,
                        custom_action="SAÍDA EM LOTE -> CLIENTE / HOSPITAL",
                        responsavel=responsavel,
                    )
                    updated_items.append(saved)
            db_manager._sync_clients_from_items()
            log_user_action(
                category="LOTE",
                action="SAÍDA EM LOTE P/ HOSPITAL",
                target=cliente,
                details=f"{len(updated_items)} aparelho(s) enviado(s) para {cliente} ({modalidade})",
                severity="SUCCESS",
            )
            return jsonify(
                {
                    "ok": True,
                    "message": f"{len(updated_items)} aparelho(s) enviado(s) para {cliente}!",
                }
            )

        elif action_type == "DEVOLVER_ESTOQUE":
            ja_atualizado = bool(data.get("ja_atualizado", True))
            versao_clew = (data.get("versao_clew") or "").strip()
            status_estoque = (data.get("status_estoque") or "ESTOQUE USADOS").strip().upper()
            observacoes = (data.get("observacoes") or "").strip()

            for idx in indices:
                if 0 <= idx < len(db_manager.items):
                    it = dict(db_manager.items[idx])
                    it["CLIENTE"] = "SEM CLIENTE (ESTOQUE LYDA)"
                    it["STATUS"] = status_estoque
                    it["ENDERECO"] = db_manager.lyda_hq_address
                    it["CEP"] = "91130-470"
                    it["CIDADE"] = "PORTO ALEGRE"
                    it["UF"] = "RS"
                    it["SETOR"] = "ESTOQUE LYDA"
                    if ja_atualizado:
                        it["ATUALIZADO_NO_ESTOQUE"] = "SIM - JÁ ATUALIZADO NO ESTOQUE"
                        it["ULTIMA_ATUALIZACAO"] = (data.get("data_atualizacao") or today_str).strip()
                        if versao_clew:
                            it["VERSAO_CLEW"] = versao_clew
                    else:
                        it["ATUALIZADO_NO_ESTOQUE"] = "NÃO - FALTA ATUALIZAR NA BANCADA"
                    if observacoes:
                        it["OBSERVACOES"] = observacoes
                    saved = db_manager.upsert_item(
                        it,
                        original_idx=idx,
                        custom_action="RETORNO EM LOTE -> ESTOQUE LYDA",
                        responsavel=responsavel,
                    )
                    updated_items.append(saved)
            log_user_action(
                category="LOTE",
                action="RETORNO EM LOTE P/ ESTOQUE LYDA",
                target=f"{len(updated_items)} aparelho(s)",
                details=f"Retorno p/ Estoque ({'JÁ ATUALIZADO' if ja_atualizado else 'FALTA ATUALIZAR'})",
                severity="INFO",
            )
            return jsonify(
                {
                    "ok": True,
                    "message": f"{len(updated_items)} aparelho(s) retornado(s) para o Estoque da LYDA!",
                }
            )

        elif action_type == "MARCAR_ATUALIZADO_6M":
            data_att = (data.get("data_atualizacao") or today_str).strip()
            versao_clew = (data.get("versao_clew") or "").strip()
            for idx in indices:
                if 0 <= idx < len(db_manager.items):
                    it = dict(db_manager.items[idx])
                    it["ULTIMA_ATUALIZACAO"] = data_att
                    if versao_clew:
                        it["VERSAO_CLEW"] = versao_clew
                    if classify_item_row_state(it) == "ESTOQUE":
                        it["ATUALIZADO_NO_ESTOQUE"] = "SIM - JÁ ATUALIZADO NO ESTOQUE"
                    saved = db_manager.upsert_item(
                        it,
                        original_idx=idx,
                        custom_action="ATUALIZAÇÃO SEMESTRAL (6 EM 6 MESES)",
                        custom_details=f"Atualizado em {data_att}" + (f" ({versao_clew})" if versao_clew else ""),
                        responsavel=responsavel,
                    )
                    updated_items.append(saved)
            log_user_action(
                category="LOTE",
                action="ATUALIZAÇÃO SEMESTRAL EM LOTE (6M)",
                target=f"{len(updated_items)} aparelho(s)",
                details=f"Ciclo de 6 meses renovado com data {data_att} ({versao_clew or 'CLEW/JAMS'})",
                severity="SUCCESS",
            )
            return jsonify(
                {
                    "ok": True,
                    "message": f"Ciclo de 6 meses renovado para {len(updated_items)} aparelho(s) (Data: {data_att})!",
                }
            )

        return jsonify({"ok": False, "error": f"Ação em lote desconhecida: {action_type}"}), 400


# =============================================================================
# API DE CLIENTES & HOSPITAIS
# =============================================================================

@app.route("/api/client/address_info", methods=["GET"])
@login_required
def api_client_address_info():
    name = (request.args.get("cliente") or "").strip()
    with db_lock:
        info = db_manager.get_client_address_info(name)
        return jsonify({"ok": True, "address_info": info})


@app.route("/api/client/save", methods=["POST"])
@login_required
def api_client_save():
    data = request.get_json(force=True) or {}
    client_data = data.get("client") or {}
    old_name = (data.get("old_name") or "").strip()
    try:
        with db_lock:
            saved = db_manager.upsert_client(client_data, old_name=old_name)
            log_user_action(
                category="CLIENTE",
                action="CADASTRO / ATUALIZAÇÃO DE CLIENTE",
                target=saved.get("CLIENTE", ""),
                details=f"Endereço: {saved.get('ENDERECO', '')} ({saved.get('CIDADE', '')}/{saved.get('UF', '')})",
                severity="SUCCESS",
            )
            return jsonify(
                {
                    "ok": True,
                    "message": f"Cadastro do cliente '{saved.get('CLIENTE')}' salvo e endereço propagado para os aparelhos!",
                    "client": saved,
                }
            )
    except ValueError as ve:
        return jsonify({"ok": False, "error": str(ve)}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": f"Erro ao salvar cliente: {e}"}), 500


@app.route("/api/client/delete", methods=["POST"])
@admin_required
def api_client_delete():
    data = request.get_json(force=True) or {}
    cliente_name = (data.get("cliente") or "").strip()
    with db_lock:
        ok, msg = db_manager.delete_client(cliente_name)
        if not ok:
            return jsonify({"ok": False, "error": msg}), 400
        log_user_action(
            category="CLIENTE",
            action="EXCLUSÃO DE CLIENTE",
            target=cliente_name,
            details=msg,
            severity="WARNING",
        )
        return jsonify({"ok": True, "message": msg})


@app.route("/api/cep/<raw_cep>", methods=["GET"])
@login_required
def api_lookup_cep(raw_cep: str):
    res = lookup_cep_viacep(raw_cep)
    if not res:
        return jsonify({"ok": False, "error": "CEP não encontrado ou inválido."}), 404
    return jsonify({"ok": True, "cep_data": res})


# =============================================================================
# API DA ROTA DA ENFERMEIRA (GOOGLE MAPS + OTIMIZAÇÃO + PDF A4)
# =============================================================================

@app.route("/api/route/build", methods=["POST"])
@login_required
def api_route_build():
    """
    Constrói ou recalcula a Rota da Enfermeira com coordenadas reais, trechos em km/minutos,
    geometria para o Google Maps interativo no navegador, link oficial do Google Maps e texto WhatsApp.
    """
    data = request.get_json(force=True) or {}
    mode = (data.get("mode") or "CUSTOM_STOPS").strip().upper()
    origin_address = (data.get("origin_address") or db_manager.lyda_hq_address or DEFAULT_LYDA_SEDE_ADDRESS).strip()
    u = get_current_user()
    nurse_name = (data.get("nurse_name") or (u and u.get("nome")) or db_manager.operador_atual or "ENFERMEIRA LYDA").strip()
    update_version = (data.get("update_version") or "Atualização Semestral i-STAT (CLEW / JAMS)").strip()
    route_date = (data.get("route_date") or datetime.now().strftime("%d/%m/%Y")).strip()
    return_to_origin = bool(data.get("return_to_origin", True))
    optimize_order = bool(data.get("optimize_order", False))

    with db_lock:
        stops: List[Dict[str, Any]] = []
        if mode == "FROM_INDICES":
            indices = [int(i) for i in (data.get("indices") or []) if str(i).lstrip("-").isdigit()]
            selected_items = [
                db_manager.items[i]
                for i in indices
                if 0 <= i < len(db_manager.items)
            ]
            if not selected_items:
                selected_items = [
                    it for it in db_manager.items
                    if classify_item_row_state(it) != "ESTOQUE"
                ]
            stops = group_items_into_route_stops(selected_items)

        elif mode == "PENDING_6M":
            def_cyc = db_manager.default_update_cycle_months
            pending_items = [
                it for it in db_manager.items
                if classify_item_row_state(it) != "ESTOQUE"
                and compute_update_cycle_info(it, def_cyc)["status_code"] in ("VENCIDA", "VENCENDO", "SEM_DATA")
            ]
            stops = group_items_into_route_stops(pending_items)

        elif mode == "ALL_ACTIVE":
            active_items = [
                it for it in db_manager.items
                if classify_item_row_state(it) != "ESTOQUE"
            ]
            stops = group_items_into_route_stops(active_items)

        else:
            raw_stops = data.get("stops") or []
            for st in raw_stops:
                cli_name = (st.get("CLIENTE") or "").strip()
                if not cli_name:
                    continue
                st_copy = dict(st)
                if not st_copy.get("ITEMS"):
                    linked = [it for _, it in db_manager.get_client_items(cli_name)]
                    addr = db_manager.get_client_address_info(cli_name)
                    st_copy.setdefault("ENDERECO", addr.get("ENDERECO", ""))
                    st_copy.setdefault("CEP", addr.get("CEP", ""))
                    st_copy.setdefault("CIDADE", addr.get("CIDADE", "PORTO ALEGRE"))
                    st_copy.setdefault("UF", addr.get("UF", "RS"))
                    st_copy.setdefault("CONTATO_LOCAL", addr.get("CONTATO_LOCAL", ""))
                    st_copy["ITEMS"] = linked
                    st_copy["SERIAIS_RESUMO"] = ", ".join(
                        f"{it.get('TIPO', 'ANA')[:3]}:{it.get('CODIGO', '')}" for it in linked
                    )
                    setores = sorted({(it.get("SETOR") or "").strip() for it in linked if (it.get("SETOR") or "").strip()})
                    st_copy["SETORES_RESUMO"] = ", ".join(setores)
                stops.append(st_copy)

        if optimize_order and stops:
            stops = optimize_stops_order(stops, origin_address=origin_address)

        metrics = compute_route_metrics_and_geometry(
            origin_address=origin_address,
            stops=stops,
            return_to_origin=return_to_origin,
            allow_network=True,
        )
        gmaps_url = build_google_maps_multi_stop_url(
            origin_address=origin_address,
            stops=stops,
            return_to_origin=return_to_origin,
        )
        whatsapp_text = build_whatsapp_route_summary(
            origin_address=origin_address,
            stops=stops,
            nurse_name=nurse_name,
            update_version=update_version,
            route_date=route_date,
            return_to_origin=return_to_origin,
            route_metrics=metrics,
        )

        stop_coords = metrics.get("stop_coords") or []
        legs = metrics.get("legs") or []
        enriched_stops = []
        for idx, st in enumerate(stops):
            st_out = dict(st)
            if idx < len(stop_coords) and stop_coords[idx]:
                st_out["_lat"] = stop_coords[idx][0]
                st_out["_lon"] = stop_coords[idx][1]
            if idx < len(legs):
                st_out["_leg_km"] = legs[idx].get("distance_km", 0.0)
                st_out["_leg_min"] = legs[idx].get("duration_min", 0)
            st_out["_maps_single_url"] = build_single_stop_maps_url(st)
            st_out["_waze_single_url"] = build_single_stop_waze_url(st)
            st_out["ITEMS_COUNT"] = len(st.get("ITEMS") or [])
            enriched_stops.append(st_out)

        return jsonify(
            {
                "ok": True,
                "origin_address": origin_address,
                "origin_coord": metrics.get("origin_coord"),
                "stops": enriched_stops,
                "metrics": {
                    "total_km": metrics.get("total_km", 0.0),
                    "total_min": metrics.get("total_min", 0),
                    "total_time_str": metrics.get("total_time_str", "0 min"),
                    "legs": legs,
                },
                "google_maps_url": gmaps_url,
                "whatsapp_text": whatsapp_text,
            }
        )


@app.route("/api/route/pdf", methods=["POST"])
@login_required
def api_route_download_pdf():
    """Gera o PDF Oficial da Rota da Enfermeira (com Mapa + QR Code + Checklist) e envia para download/abertura no navegador."""
    data = request.get_json(force=True) or {}
    origin_address = (data.get("origin_address") or db_manager.lyda_hq_address or DEFAULT_LYDA_SEDE_ADDRESS).strip()
    stops = data.get("stops") or []
    u = get_current_user()
    nurse_name = (data.get("nurse_name") or (u and u.get("nome")) or db_manager.operador_atual or "ENFERMEIRA LYDA").strip()
    update_version = (data.get("update_version") or "Atualização Semestral i-STAT (CLEW / JAMS)").strip()
    route_date = (data.get("route_date") or datetime.now().strftime("%d/%m/%Y")).strip()
    return_to_origin = bool(data.get("return_to_origin", True))
    observacoes_rota = (data.get("observacoes_rota") or "").strip()

    if not stops:
        return jsonify({"ok": False, "error": "Adicione pelo menos 1 parada na rota antes de gerar o PDF."}), 400

    with db_lock:
        metrics = compute_route_metrics_and_geometry(
            origin_address=origin_address,
            stops=stops,
            return_to_origin=return_to_origin,
            allow_network=True,
        )
        pdf_path = generate_nurse_route_pdf(
            workspace_dir=WORKSPACE_DIR,
            origin_address=origin_address,
            stops=stops,
            nurse_name=nurse_name,
            update_version=update_version,
            route_date=route_date,
            return_to_origin=return_to_origin,
            observacoes_rota=observacoes_rota,
            auto_open_pdf=False,
            reveal_in_folder=False,
            route_metrics=metrics,
        )
        log_user_action(
            category="ROTA_MAPS",
            action="EMISSÃO DE PDF DA ROTA DA ENFERMEIRA",
            target=f"{len(stops)} parada(s) ({metrics.get('total_km', 0)} km)",
            details=f"Enfermeira: {nurse_name} | Data: {route_date} | Hospitais: " + ", ".join(s.get("CLIENTE", "") for s in stops[:5]),
            severity="SUCCESS",
        )
        return send_file(
            pdf_path,
            mimetype="application/pdf",
            as_attachment=False,
            download_name=os.path.basename(pdf_path),
        )


@app.route("/api/romaneio/html", methods=["POST"])
@login_required
def api_romaneio_html():
    """Gera o Protocolo / Romaneio A4 HTML pronto para impressão e retorna a página."""
    data = request.get_json(force=True) or {}
    indices = [int(i) for i in (data.get("indices") or []) if str(i).lstrip("-").isdigit()]
    u = get_current_user()
    with db_lock:
        items = [db_manager.items[i] for i in indices if 0 <= i < len(db_manager.items)]
        if not items and data.get("single_item"):
            items = [data["single_item"]]
        if not items:
            return jsonify({"ok": False, "error": "Nenhum aparelho selecionado para o Romaneio."}), 400

        first = items[0]
        acao = (data.get("acao") or "PROTOCOLO DE MOVIMENTAÇÃO / ENTREGA DE EQUIPAMENTO i-STAT").strip()
        cliente = (data.get("cliente") or first.get("CLIENTE") or "SEM CLIENTE (ESTOQUE LYDA)").strip()
        cidade = (data.get("cidade") or first.get("CIDADE") or "PORTO ALEGRE").strip()
        uf = (data.get("uf") or first.get("UF") or "RS").strip()
        setor = (data.get("setor") or first.get("SETOR") or "-").strip()
        modalidade = (data.get("modalidade") or first.get("MODALIDADE") or "-").strip()
        status = (data.get("status") or first.get("STATUS") or "-").strip()
        condicao = (data.get("condicao") or first.get("CONDICAO") or "PERFEITO / FUNCIONANDO 100%").strip()
        defeito = (data.get("defeito") or first.get("DEFEITO") or "").strip()
        observacoes = (data.get("observacoes") or first.get("OBSERVACOES") or "").strip()
        responsavel = (data.get("responsavel") or (u and u.get("nome")) or db_manager.operador_atual or "OPERADOR").strip()

        orig_wb_open = webbrowser.open
        try:
            webbrowser.open = lambda *a, **kw: False
            fpath = generate_and_open_romaneio(
                workspace_dir=WORKSPACE_DIR,
                acao=acao,
                cliente=cliente,
                cidade=cidade,
                uf=uf,
                setor=setor,
                modalidade=modalidade,
                status=status,
                condicao=condicao,
                defeito=defeito,
                observacoes=observacoes,
                responsavel=responsavel,
                items=items,
            )
        finally:
            webbrowser.open = orig_wb_open

        log_user_action(
            category="ESTOQUE",
            action="EMISSÃO DE PROTOCOLO / ROMANEIO A4",
            target=cliente,
            details=f"{len(items)} aparelho(s) no protocolo #{os.path.basename(fpath)}",
            severity="INFO",
        )

        with open(fpath, "r", encoding="utf-8") as f:
            html_str = f.read()
        return jsonify({"ok": True, "html": html_str, "filename": os.path.basename(fpath)})


@app.route("/api/romaneio/termo-troca", methods=["POST"])
@login_required
def api_termo_troca():
    """Gera o Termo de Substituição / Troca de Aparelho com Timbre Oficial LYDA e códigos de barras."""
    data = request.get_json(force=True) or {}
    idx = data.get("idx")
    serial_novo = str(data.get("serial_novo") or "").strip()
    serial_antigo = str(data.get("serial_antigo") or "").strip()
    tipo = str(data.get("tipo") or "Analisador i-STAT").strip()
    cliente = str(data.get("cliente") or "").strip()
    recebedor_nome = str(data.get("recebedor_nome") or "").strip()
    recebedor_cpf = str(data.get("recebedor_cpf") or "").strip()
    data_str = str(data.get("data") or "").strip()
    save_to_attachments = bool(data.get("save_to_attachments", False))

    if not serial_novo and idx is not None and 0 <= int(idx) < len(db_manager.items):
        it = db_manager.items[int(idx)]
        serial_novo = it.get("CODIGO", "")
        if not cliente:
            cliente = it.get("CLIENTE", "")
        if not tipo:
            tipo = f"i-STAT {it.get('TIPO', 'Analisador').title()}"

    if not serial_novo:
        return jsonify({"ok": False, "error": "Informe o Serial do aparelho entregue."}), 400

    fpath = generate_termo_substituicao_html(
        workspace_dir=WORKSPACE_DIR,
        cliente=cliente,
        serial_novo=serial_novo,
        tipo_equipamento=tipo,
        serial_antigo=serial_antigo,
        recebedor_nome=recebedor_nome,
        recebedor_cpf=recebedor_cpf,
        data_str=data_str,
    )

    with open(fpath, "r", encoding="utf-8") as f:
        html_str = f.read()

    fname = os.path.basename(fpath)

    # Se solicitado salvar automaticamente nos anexos do aparelho
    if save_to_attachments and idx is not None and 0 <= int(idx) < len(db_manager.items):
        with db_lock:
            it = db_manager.items[int(idx)]
            item_folder = os.path.join(ATTACHMENTS_DIR, clean_barcode_serial(it.get("CODIGO", "")))
            os.makedirs(item_folder, exist_ok=True)
            dest_file = os.path.join(item_folder, fname)
            with open(dest_file, "w", encoding="utf-8") as df:
                df.write(html_str)
            att_list = it.setdefault("ANEXOS", [])
            att_list.append({
                "filename": fname,
                "original_name": f"Termo_Substituicao_{serial_novo}.html",
                "size_bytes": os.path.getsize(dest_file),
                "size_str": f"{max(1, round(os.path.getsize(dest_file)/1024))} KB",
                "uploaded_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
                "uploaded_by": (get_current_user() or {}).get("nome") or "SISTEMA",
                "is_termo": True,
            })
            db_manager.save()

    log_user_action(
        category="ESTOQUE",
        action="TERMO DE SUBSTITUIÇÃO / ENTREGA",
        target=f"{tipo} [{serial_novo}]",
        details=f"Cliente: {cliente} | Substituição de: {serial_antigo or 'N/A'}",
        severity="SUCCESS",
    )

    return jsonify({"ok": True, "html": html_str, "filename": fname})


@app.route("/api/item/<int:idx>/attachments/upload", methods=["POST"])
@login_required
def api_item_attachment_upload(idx: int):
    """Anexa um documento (PDF, imagem, termo assinado) à ficha do aparelho i-STAT."""
    with db_lock:
        if idx < 0 or idx >= len(db_manager.items):
            return jsonify({"ok": False, "error": "Equipamento não encontrado."}), 404
        it = db_manager.items[idx]
        bc = clean_barcode_serial(it.get("CODIGO", ""))
        if not bc:
            return jsonify({"ok": False, "error": "Aparelho sem código de barras válido."}), 400

        if "file" not in request.files:
            return jsonify({"ok": False, "error": "Nenhum arquivo enviado."}), 400
        f = request.files["file"]
        if not f.filename:
            return jsonify({"ok": False, "error": "Nome de arquivo inválido."}), 400

        orig_name = f.filename
        ext = os.path.splitext(orig_name)[1].lower()
        allowed_exts = {".pdf", ".png", ".jpg", ".jpeg", ".docx", ".doc", ".html", ".txt"}
        if ext not in allowed_exts:
            return jsonify({"ok": False, "error": "Formato de arquivo não suportado. Envie PDF, imagem (PNG/JPG) ou documento."}), 400

        item_dir = os.path.join(ATTACHMENTS_DIR, bc)
        os.makedirs(item_dir, exist_ok=True)

        clean_base = re.sub(r"[^A-Za-z0-9_-]", "_", os.path.splitext(orig_name)[0])
        now_tag = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_filename = f"{clean_base}_{now_tag}{ext}"
        target_path = os.path.join(item_dir, safe_filename)
        f.save(target_path)

        f_size = os.path.getsize(target_path)
        size_str = f"{f_size / 1024:.1f} KB" if f_size < 1048576 else f"{f_size / 1048576:.1f} MB"
        u = get_current_user() or {}

        att_entry = {
            "filename": safe_filename,
            "original_name": orig_name,
            "size_bytes": f_size,
            "size_str": size_str,
            "uploaded_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "uploaded_by": u.get("nome") or "OPERADOR",
        }
        att_list = it.setdefault("ANEXOS", [])
        att_list.append(att_entry)
        db_manager.save()

        db_manager.add_history_log(
            serial_barcode=bc,
            tipo=it.get("TIPO", "ANALISADOR"),
            acao="ANEXO DE DOCUMENTO",
            detalhes=f"Documento anexado: {orig_name} ({size_str})",
            cliente=it.get("CLIENTE", ""),
            responsavel=u.get("nome") or "OPERADOR",
        )

        log_user_action(
            category="ESTOQUE",
            action="UPLOAD DE ANEXO / TERMO",
            target=f"{it.get('TIPO')} [{bc}]",
            details=f"Arquivo: {orig_name} ({size_str})",
            severity="SUCCESS",
        )

        return jsonify({
            "ok": True,
            "message": f"Documento '{orig_name}' anexado com sucesso!",
            "attachments": it.get("ANEXOS", []),
        })


@app.route("/api/item/<int:idx>/attachments/<path:filename>", methods=["GET"])
@login_required
def api_item_attachment_get(idx: int, filename: str):
    """Exibe ou baixa o documento anexado do aparelho."""
    with db_lock:
        if idx < 0 or idx >= len(db_manager.items):
            return jsonify({"ok": False, "error": "Equipamento não encontrado."}), 404
        it = db_manager.items[idx]
        bc = clean_barcode_serial(it.get("CODIGO", ""))
        item_dir = os.path.join(ATTACHMENTS_DIR, bc)
        return send_from_directory(item_dir, filename)


@app.route("/api/item/<int:idx>/attachments/delete", methods=["POST"])
@login_required
def api_item_attachment_delete(idx: int):
    """Exclui um documento anexado do aparelho."""
    data = request.get_json(force=True) or {}
    filename = data.get("filename", "").strip()
    if not filename:
        return jsonify({"ok": False, "error": "Nome do arquivo não informado."}), 400

    with db_lock:
        if idx < 0 or idx >= len(db_manager.items):
            return jsonify({"ok": False, "error": "Equipamento não encontrado."}), 404
        it = db_manager.items[idx]
        bc = clean_barcode_serial(it.get("CODIGO", ""))
        item_dir = os.path.join(ATTACHMENTS_DIR, bc)
        fpath = os.path.join(item_dir, filename)
        if os.path.exists(fpath):
            try:
                os.remove(fpath)
            except Exception:
                pass

        att_list = it.get("ANEXOS", [])
        it["ANEXOS"] = [a for a in att_list if a.get("filename") != filename]
        db_manager.save()

        u = get_current_user() or {}
        db_manager.add_history_log(
            serial_barcode=bc,
            tipo=it.get("TIPO", "ANALISADOR"),
            acao="EXCLUSÃO DE ANEXO",
            detalhes=f"Anexo removido: {filename}",
            cliente=it.get("CLIENTE", ""),
            responsavel=u.get("nome") or "OPERADOR",
        )

        return jsonify({
            "ok": True,
            "message": "Anexo removido com sucesso.",
            "attachments": it.get("ANEXOS", []),
        })


# =============================================================================
# API DE IMPRESSÃO DE ETIQUETAS ZEBRA ZD230 & CONFIGURAÇÃO DA BOBINA GRANDE
# =============================================================================

ZEBRA_WEB_CONFIG_PATH = os.path.join(WORKSPACE_DIR, "lyda_zebra_web_config.json")


def get_default_zebra_web_config() -> Dict[str, Any]:
    return {
        "preset_id": "BOBINA_100x150_2x5",
        "big_width_mm": 100.0,
        "big_height_mm": 150.0,
        "margin_left_mm": 3.0,
        "margin_top_mm": 3.0,
        "cols": 2,
        "rows": 5,
        "gap_h_mm": 2.0,
        "gap_v_mm": 2.0,
        "skip_slots": 0,
        "copies_per_item": 1,
        "draw_border": True,
        "draw_cut_marks": True,
        "show_logo": True,
        "logo_height_dots": 26,
        "show_header": True,
        "header_text": "i-STAT",
        "show_equipamento": True,
        "show_serial_line": True,
        "show_location": False,
        "barcode_type": "CODE128",
        "barcode_height_mm": 10.0,
        "show_barcode_text": True,
        "dpi": 203,
        "darkness": 18,
        "print_speed": 4,
        "mode": "USB_DRIVER",
        "printer_name": "",
        "ip_address": "192.168.0.200",
        "port": 9100,
    }


def load_zebra_web_config() -> Dict[str, Any]:
    cfg = get_default_zebra_web_config()
    if os.path.isfile(ZEBRA_WEB_CONFIG_PATH):
        try:
            with open(ZEBRA_WEB_CONFIG_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                cfg.update(saved)
        except Exception:
            pass
    return cfg


def save_zebra_web_config(partial: Dict[str, Any]) -> Dict[str, Any]:
    cfg = load_zebra_web_config()
    for k in cfg.keys():
        if k in partial and partial[k] is not None:
            cfg[k] = partial[k]
    try:
        with open(ZEBRA_WEB_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return cfg


def build_label_layout_from_payload(data: Dict[str, Any]) -> LabelLayoutConfig:
    saved = load_zebra_web_config()

    def _f(key: str, default: float, min_v: float, max_v: float) -> float:
        try:
            val = float(data.get(key, saved.get(key, default)))
        except Exception:
            val = default
        return max(min_v, min(max_v, val))

    def _i(key: str, default: int, min_v: int, max_v: int) -> int:
        try:
            val = int(float(data.get(key, saved.get(key, default))))
        except Exception:
            val = default
        return max(min_v, min(max_v, val))

    def _b(key: str, default: bool) -> bool:
        if key in data:
            return bool(data[key])
        return bool(saved.get(key, default))

    big_w = _f("big_width_mm", 100.0, 20.0, 220.0)
    big_h = _f("big_height_mm", 150.0, 15.0, 350.0)
    margin_l = _f("margin_left_mm", 3.0, 0.0, 30.0)
    margin_t = _f("margin_top_mm", 3.0, 0.0, 30.0)
    cols = _i("cols", 2, 1, 6)
    rows = _i("rows", 5, 1, 15)
    gap_h = _f("gap_h_mm", 2.0, 0.0, 20.0)
    gap_v = _f("gap_v_mm", 2.0, 0.0, 20.0)
    max_skip = max(0, (cols * rows) - 1)
    skip_slots = _i("skip_slots", 0, 0, max_skip)

    draw_border = _b("draw_border", True)
    draw_cut_marks = _b("draw_cut_marks", True)
    show_logo = _b("show_logo", True)
    logo_h_dots = _i("logo_height_dots", 26, 12, 70)
    show_header = _b("show_header", True)
    header_text = str(data.get("header_text", saved.get("header_text", "i-STAT")) or "i-STAT").strip()

    show_equipamento = _b("show_equipamento", True)
    show_serial_line = _b("show_serial_line", True)
    show_location = _b("show_location", False)

    bc_type = str(data.get("barcode_type", saved.get("barcode_type", "CODE128")) or "CODE128").strip().upper()
    if bc_type not in ("CODE128", "QRCODE"):
        bc_type = "CODE128"
    bc_h_mm = _f("barcode_height_mm", 10.0, 4.0, 35.0)
    show_bc_txt = _b("show_barcode_text", True)

    dpi = _i("dpi", 203, 203, 300)
    darkness = _i("darkness", 18, 5, 30)
    print_speed = _i("print_speed", 4, 2, 6)

    extra_fields = []
    if show_equipamento:
        extra_fields.append(ExtraFieldConfig(prefix="EQ: ", column_name="TIPO", font_size=18, bold=True))
    if show_serial_line:
        extra_fields.append(ExtraFieldConfig(prefix="SN: ", column_name="CODIGO", font_size=18, bold=True))
    if show_location:
        extra_fields.append(ExtraFieldConfig(prefix="", column_name="CLIENTE", font_size=16, bold=False))

    return LabelLayoutConfig(
        big_width_mm=big_w,
        big_height_mm=big_h,
        margin_left_mm=margin_l,
        margin_top_mm=margin_t,
        dpi=dpi,
        cols=cols,
        rows=rows,
        gap_h_mm=gap_h,
        gap_v_mm=gap_v,
        auto_size_mini=True,
        skip_slots=skip_slots,
        draw_border=draw_border,
        border_thickness_dots=2,
        border_corner_rounding=2,
        draw_cut_marks=draw_cut_marks,
        inner_padding_mm=2.0,
        show_logo=show_logo,
        logo_height_dots=logo_h_dots,
        show_header=show_header,
        header_text=header_text,
        header_font_size=22,
        barcode_enabled=True,
        barcode_type=bc_type,
        barcode_column="CODIGO",
        barcode_height_mm=bc_h_mm,
        barcode_module_width=2,
        show_barcode_text=show_bc_txt,
        extra_fields=extra_fields,
        darkness=darkness,
        print_speed=print_speed,
    )


@app.route("/api/zebra/config", methods=["GET", "POST"])
@login_required
def api_zebra_config():
    if request.method == "GET":
        return jsonify({
            "ok": True,
            "zebra_config": load_zebra_web_config(),
            "printers": list_system_printers(),
        })
    data = request.get_json(force=True) or {}
    saved = save_zebra_web_config(data)
    log_user_action(
        category="ZEBRA",
        action="ATUALIZAÇÃO DE CONFIGURAÇÃO DA ZEBRA ZD230",
        target=f"Papel {saved.get('big_width_mm')}x{saved.get('big_height_mm')}mm ({saved.get('cols')}x{saved.get('rows')})",
        details=f"Contorno Recorte: {saved.get('draw_border')} | Logo LYDA: {saved.get('show_logo')}",
        severity="INFO",
    )
    return jsonify({
        "ok": True,
        "message": "Configuração padrão da Zebra ZD230 salva com sucesso!",
        "zebra_config": saved,
        "printers": list_system_printers(),
    })


@app.route("/api/zebra/print", methods=["POST"])
@login_required
def api_zebra_print():
    data = request.get_json(force=True) or {}
    indices = [int(i) for i in (data.get("indices") or []) if str(i).lstrip("-").isdigit()]
    printer_name = (data.get("printer_name") or "").strip()
    mode = (data.get("mode") or "USB_DRIVER").strip()
    ip_address = (data.get("ip_address") or "").strip()
    port = int(data.get("port") or 9100)
    copies_per_item = max(1, min(20, int(data.get("copies_per_item") or 1)))
    only_page_index = data.get("only_page_index")

    with db_lock:
        if data.get("single_item") and isinstance(data["single_item"], dict):
            base_records = [data["single_item"]]
        else:
            base_records = [db_manager.items[i] for i in indices if 0 <= i < len(db_manager.items)]
        if not base_records:
            return jsonify({"ok": False, "error": "Selecione pelo menos 1 aparelho para gerar/imprimir etiqueta."}), 400

        records = []
        for rec in base_records:
            for _ in range(copies_per_item):
                records.append(rec)

        cfg = build_label_layout_from_payload(data)
        gen = ZPLGenerator(cfg)
        pages = gen.generate_zpl_pages(records)
        full_zpl = "\n\n".join(pages)

        if len(base_records) == 1:
            one = base_records[0]
            s_tipo = re.sub(r"[^A-Za-z0-9_-]", "", str(one.get("TIPO") or "ISTAT").upper()) or "ISTAT"
            s_cod = re.sub(r"[^A-Za-z0-9_-]", "", str(one.get("CODIGO") or "SERIAL").upper()) or "SERIAL"
            single_slug = f"etiqueta_lyda_{s_tipo}_{s_cod}.prn"
        else:
            single_slug = ""

        if only_page_index is not None and pages:
            try:
                p_idx = max(0, min(len(pages) - 1, int(only_page_index)))
                target_zpl = pages[p_idx]
                desc_target = f"Folha #{p_idx + 1} de {len(pages)} ({cfg.big_width_mm:.0f}x{cfg.big_height_mm:.0f}mm)"
                prn_filename = single_slug or f"etiquetas_lyda_zd230_{cfg.big_width_mm:.0f}x{cfg.big_height_mm:.0f}mm_folha_{p_idx + 1}.prn"
            except Exception:
                target_zpl = full_zpl
                desc_target = f"{len(records)} mini-etiqueta(s) em {len(pages)} folha(s)"
                prn_filename = single_slug or f"etiquetas_lyda_zd230_{cfg.big_width_mm:.0f}x{cfg.big_height_mm:.0f}mm_{len(records)}etq.prn"
        else:
            target_zpl = full_zpl
            desc_target = f"{len(records)} mini-etiqueta(s) em {len(pages)} folha(s)"
            prn_filename = single_slug or f"etiquetas_lyda_zd230_{cfg.big_width_mm:.0f}x{cfg.big_height_mm:.0f}mm_{len(records)}etq.prn"

        if data.get("only_preview_zpl"):
            if data.get("is_prn_download"):
                if not data.get("single_item"):
                    save_zebra_web_config(data)
                log_user_action(
                    category="ZEBRA",
                    action="DOWNLOAD DE ARQUIVO .PRN (ZEBRA ZD230)",
                    target=prn_filename,
                    details=f"{desc_target} | Grade {cfg.cols}x{cfg.rows}",
                    severity="INFO",
                )
            return jsonify({
                "ok": True,
                "zpl": target_zpl,
                "full_zpl": full_zpl,
                "filename": prn_filename,
                "pages_count": len(pages),
                "count": len(records),
                "message": f"Arquivo {prn_filename} ({desc_target}) gerado com sucesso!",
            })

        # Salva automaticamente a preferência usada na impressão
        save_zebra_web_config(data)
        zpl_to_send = target_zpl

        if not printer_name and mode == "USB_DRIVER":
            printers = list_system_printers()
            if printers:
                printer_name = printers[0]

        ok, msg = dispatch_zpl_print(
            mode=mode,
            zpl_data=zpl_to_send,
            printer_name=printer_name,
            ip_address=ip_address,
            port=port,
        )
        log_user_action(
            category="ZEBRA",
            action="IMPRESSÃO DE ETIQUETAS ZEBRA ZD230",
            target=desc_target,
            details=f"Papel: {cfg.big_width_mm:.0f}x{cfg.big_height_mm:.0f}mm ({cfg.cols}x{cfg.rows}) | Impressora: {printer_name or ip_address or 'Padrão'} | Status: {msg}",
            severity="SUCCESS" if ok else "WARNING",
        )
        return jsonify({
            "ok": ok,
            "message": f"{desc_target} — {msg}",
            "zpl": full_zpl,
            "pages_count": len(pages),
        })


# =============================================================================
# API DE CONFIGURAÇÕES DO SERVIDOR, OPERADORES, EXCEL E BACKUP SHAREPOINT
# =============================================================================

@app.route("/api/settings/save", methods=["POST"])
@login_required
def api_settings_save():
    data = request.get_json(force=True) or {}
    u = get_current_user()
    with db_lock:
        if "operador_atual" in data:
            op = (data.get("operador_atual") or "").strip().upper()
            if op:
                db_manager.operador_atual = op
                db_manager.add_operator(op)
        if "lyda_hq_address" in data:
            hq = (data.get("lyda_hq_address") or "").strip()
            if hq:
                db_manager.lyda_hq_address = hq
        if "default_update_cycle_months" in data:
            try:
                db_manager.default_update_cycle_months = max(1, int(data["default_update_cycle_months"]))
            except Exception:
                pass
        db_manager.save_local_pc_config()

        sp_msg = ""
        if "sharepoint_backup_dir" in data:
            if u.get("role") != "ADMIN":
                return jsonify({"ok": False, "error": "Apenas Administradores podem alterar a pasta do SharePoint do Servidor."}), 403
            ok_sp, sp_msg = db_manager.set_sharepoint_backup_config(
                folder_path=data.get("sharepoint_backup_dir", ""),
                backup_time=data.get("sharepoint_backup_time", "18:00"),
                auto_sync=bool(data.get("sharepoint_auto_sync", True)),
            )
            if not ok_sp:
                return jsonify({"ok": False, "error": sp_msg}), 400
            log_user_action(
                category="SISTEMA",
                action="CONFIGURAÇÃO DO SERVIDOR & SHAREPOINT",
                target=data.get("sharepoint_backup_dir") or "Backup Local",
                details=f"Horário diário: {data.get('sharepoint_backup_time', '18:00')} | Sede: {db_manager.lyda_hq_address}",
                severity="INFO",
            )

        return jsonify(
            {
                "ok": True,
                "message": "Configurações do Servidor salvas com sucesso!" + (f"\n\n{sp_msg}" if sp_msg else ""),
            }
        )


@app.route("/api/operators/manage", methods=["POST"])
@admin_required
def api_operators_manage():
    data = request.get_json(force=True) or {}
    action = (data.get("action") or "ADD").strip().upper()
    name = (data.get("name") or "").strip().upper()
    if not name:
        return jsonify({"ok": False, "error": "Informe o nome do operador/enfermeira."}), 400
    with db_lock:
        if action == "REMOVE":
            ops = db_manager.remove_operator(name)
        else:
            ops = db_manager.add_operator(name)
            db_manager.operador_atual = name
            db_manager.save_local_pc_config()
        return jsonify({"ok": True, "operators": ops, "operador_atual": db_manager.operador_atual})


@app.route("/api/backups/list", methods=["GET"])
@login_required
def api_backups_list():
    with db_lock:
        backups = db_manager.list_backups()
        return jsonify(
            {
                "ok": True,
                "backups": backups,
                "sharepoint_backup_dir": getattr(db_manager, "sharepoint_backup_dir", ""),
                "last_sharepoint_backup_at": getattr(db_manager, "last_sharepoint_backup_at", ""),
                "last_sharepoint_backup_status": getattr(db_manager, "last_sharepoint_backup_status", ""),
            }
        )


@app.route("/api/backups/run_now", methods=["POST"])
@login_required
def api_backups_run_now():
    with db_lock:
        ok, msg = db_manager.sync_backup_to_sharepoint(reason="manual_painel_web")
        backups = db_manager.list_backups()
        log_user_action(
            category="BACKUP",
            action="BACKUP IMEDIATO + ENVIO SHAREPOINT",
            target=db_manager.sharepoint_backup_dir or "Servidor Local",
            details=msg.replace("\n", " "),
            severity="SUCCESS" if ok else "WARNING",
        )
        return jsonify(
            {
                "ok": ok,
                "message": msg,
                "backups": backups,
                "last_sharepoint_backup_at": getattr(db_manager, "last_sharepoint_backup_at", ""),
                "last_sharepoint_backup_status": getattr(db_manager, "last_sharepoint_backup_status", ""),
            }
        )


@app.route("/api/backups/restore", methods=["POST"])
@admin_required
def api_backups_restore():
    data = request.get_json(force=True) or {}
    filepath = (data.get("filepath") or "").strip()
    with db_lock:
        ok, msg = db_manager.restore_backup(filepath)
        if not ok:
            return jsonify({"ok": False, "error": msg}), 400
        log_user_action(
            category="BACKUP",
            action="RESTAURAÇÃO DE BACKUP PELO ADMIN",
            target=os.path.basename(filepath),
            details=msg,
            severity="WARNING",
        )
        return jsonify({"ok": True, "message": msg})


@app.route("/api/excel/export", methods=["GET"])
@login_required
def api_excel_export():
    with db_lock:
        now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = os.path.join(WORKSPACE_DIR, "exportacoes_excel")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"Mapeamento_Equipamento_i-STAT_LYDA_{now_str}.xlsx")
        db_manager.export_to_excel(out_path)
        log_user_action(
            category="ESTOQUE",
            action="EXPORTAÇÃO DE PLANILHA EXCEL (.XLSX)",
            target=os.path.basename(out_path),
            details=f"{len(db_manager.items)} aparelhos exportados.",
            severity="INFO",
        )
        return send_file(
            out_path,
            as_attachment=True,
            download_name=os.path.basename(out_path),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


@app.route("/api/excel/import", methods=["POST"])
@admin_required
def api_excel_import():
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "Selecione um arquivo Excel (.xlsx)."}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"ok": False, "error": "Arquivo inválido."}), 400
    tmp_dir = tempfile.mkdtemp(prefix="lyda_xlsx_")
    tmp_path = os.path.join(tmp_dir, f.filename)
    f.save(tmp_path)
    with db_lock:
        count, msg = db_manager.import_from_lyda_excel(tmp_path)
        db_manager._enrich_missing_hospital_addresses()
        db_manager._sync_clients_from_items()
        if count <= 0:
            return jsonify({"ok": False, "error": msg}), 400
        log_user_action(
            category="ESTOQUE",
            action="IMPORTAÇÃO DE PLANILHA EXCEL (.XLSX)",
            target=f.filename,
            details=msg,
            severity="WARNING",
        )
        return jsonify({"ok": True, "count": count, "message": msg})


def start_web_server(host: str = "0.0.0.0", port: int = 8080, open_browser: bool = True):
    os.environ["LYDA_WEB_PORT"] = str(port)
    ips = get_local_network_ips()
    local_url = f"http://localhost:{port}"
    lan_url = f"http://{ips[0]}:{port}"

    print("=" * 78)
    print("  LYDA — SERVIDOR WEB DE CONTROLE DE ESTOQUE, CLIENTES & ROTA i-STAT")
    print("=" * 78)
    print(f"  Acesso neste Computador (Servidor):  {local_url}")
    print(f"  Link para TODOS os PCs/Celulares da LYDA na Rede:  {lan_url}")
    for extra_ip in ips[1:]:
        print(f"  Link Alternativo na Rede:            http://{extra_ip}:{port}")
    print(f"  Banco de Dados Local do Servidor:    {db_manager.db_path}")
    print(f"  Backup Diário p/ SharePoint:         {db_manager.sharepoint_backup_dir or 'Configurar na aba Servidor & SharePoint'}")
    print("=" * 78)

    if open_browser:
        def _open():
            time.sleep(1.0)
            try:
                webbrowser.open(local_url)
            except Exception:
                pass
        threading.Thread(target=_open, daemon=True).start()

    app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == "__main__":
    port_arg = int(os.environ.get("LYDA_WEB_PORT", "8080"))
    no_browser = "--no-browser" in sys.argv
    start_web_server(host="0.0.0.0", port=port_arg, open_browser=not no_browser)
