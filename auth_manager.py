"""
Módulo de Autenticação, Gestão de Usuários/Perfis (ADMIN e USUARIO) e Auditoria Completa de Logs — LYDA Web.
Armazena senhas com hash criptográfico PBKDF2-HMAC-SHA256, gerencia sessões, permissões de administrador
e registra todos os logs de acesso, movimentações de estoque, rotas, clientes e alterações administrativas.
"""

import hashlib
import json
import os
import secrets
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


USERS_JSON_FILENAME = "lyda_istat_usuarios.json"
AUDIT_LOGS_JSON_FILENAME = "lyda_istat_audit_logs.json"


def hash_password(plain_password: str, salt: Optional[str] = None) -> str:
    """Gera hash PBKDF2-HMAC-SHA256 seguro no formato 'salt$hex_digest'."""
    if not salt:
        salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        plain_password.encode("utf-8"),
        salt.encode("utf-8"),
        120_000,
    )
    return f"{salt}${dk.hex()}"


def verify_password(plain_password: str, stored_hash: str) -> bool:
    if not stored_hash or "$" not in stored_hash:
        return False
    salt, _ = stored_hash.split("$", 1)
    expected = hash_password(plain_password, salt=salt)
    return secrets.compare_digest(expected, stored_hash)


class AuthAndAuditManager:
    """
    Gerencia Usuários (Admin e Operadores/Enfermeiras), Perfis e Logs de Auditoria do Servidor Web LYDA.
    """

    def __init__(self, storage_dir: str):
        self.storage_dir = storage_dir
        os.makedirs(self.storage_dir, exist_ok=True)
        self.users_path = os.path.join(self.storage_dir, USERS_JSON_FILENAME)
        self.audit_path = os.path.join(self.storage_dir, AUDIT_LOGS_JSON_FILENAME)
        self.users: List[Dict[str, Any]] = []
        self.audit_logs: List[Dict[str, Any]] = []
        self.load()

    def load(self):
        if os.path.exists(self.users_path):
            try:
                with open(self.users_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list) and data:
                    self.users = data
            except Exception:
                self.users = []

        if not self.users:
            self._seed_default_users()

        if os.path.exists(self.audit_path):
            try:
                with open(self.audit_path, "r", encoding="utf-8") as f:
                    logs = json.load(f)
                if isinstance(logs, list):
                    self.audit_logs = logs
            except Exception:
                self.audit_logs = []

    def _seed_default_users(self):
        now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
        self.users = [
            {
                "username": "admin",
                "nome": "ADMINISTRADOR LYDA",
                "email": "admin@lyda.com.br",
                "cargo": "Administrador Geral / TI",
                "setor": "ADMINISTRAÇÃO",
                "telefone": "",
                "role": "ADMIN",
                "avatar_color": "#2563EB",
                "active": True,
                "must_change_password": True,
                "password_hash": hash_password("lyda123"),
                "created_at": now_str,
                "last_login": "",
            },
            {
                "username": "brianail",
                "nome": "BRIAN AIL",
                "email": "brian@lyda.com.br",
                "cargo": "Gestão & Controle i-STAT",
                "setor": "DIRETORIA / OPERAÇÕES",
                "telefone": "",
                "role": "ADMIN",
                "avatar_color": "#0F172A",
                "active": True,
                "must_change_password": True,
                "password_hash": hash_password("lyda123"),
                "created_at": now_str,
                "last_login": "",
            },
            {
                "username": "enfermeira",
                "nome": "ENFERMEIRA LYDA",
                "email": "enfermagem@lyda.com.br",
                "cargo": "Enfermeira de Rota & Atualização CLEW",
                "setor": "ASSESSORIA CIENTÍFICA / CAMPO",
                "telefone": "",
                "role": "USUARIO",
                "avatar_color": "#0D9488",
                "active": True,
                "must_change_password": True,
                "password_hash": hash_password("lyda123"),
                "created_at": now_str,
                "last_login": "",
            },
            {
                "username": "estoque",
                "nome": "ESTOQUE LYDA",
                "email": "estoque@lyda.com.br",
                "cargo": "Operador de Estoque & Expedição",
                "setor": "LOGÍSTICA / BANCADA",
                "telefone": "",
                "role": "USUARIO",
                "avatar_color": "#16A34A",
                "active": True,
                "must_change_password": True,
                "password_hash": hash_password("lyda123"),
                "created_at": now_str,
                "last_login": "",
            },
        ]
        self.save_users()

    def save_users(self):
        tmp = self.users_path + f".tmp.{os.getpid()}"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.users, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.users_path)
        except Exception:
            with open(self.users_path, "w", encoding="utf-8") as f:
                json.dump(self.users, f, ensure_ascii=False, indent=2)

    def save_audit_logs(self):
        tmp = self.audit_path + f".tmp.{os.getpid()}"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.audit_logs[:3000], f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.audit_path)
        except Exception:
            with open(self.audit_path, "w", encoding="utf-8") as f:
                json.dump(self.audit_logs[:3000], f, ensure_ascii=False, indent=2)

    def sanitize_user(self, u: Dict[str, Any]) -> Dict[str, Any]:
        """Retorna os dados públicos do usuário sem expor o hash da senha."""
        out = dict(u)
        out.pop("password_hash", None)
        nome = out.get("nome") or out.get("username") or "U"
        parts = [p for p in nome.strip().split() if p]
        if len(parts) >= 2:
            initials = (parts[0][0] + parts[-1][0]).upper()
        else:
            initials = nome[:2].upper()
        out["initials"] = initials
        # Obrigatório trocar senha se estiver com a senha padrão temporária 'lyda123' ou flag ativa
        is_default = verify_password("lyda123", u.get("password_hash", ""))
        out["must_change_password"] = bool(u.get("must_change_password", False) or is_default)
        return out

    def list_public_users(self) -> List[Dict[str, Any]]:
        return [self.sanitize_user(u) for u in self.users]

    def get_user(self, username: str) -> Optional[Dict[str, Any]]:
        target = (username or "").strip().lower()
        for u in self.users:
            if (u.get("username") or "").strip().lower() == target:
                return u
        return None

    def authenticate(self, username_or_email: str, password: str, ip_address: str = "") -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        ident = (username_or_email or "").strip().lower()
        if not ident or not password:
            return False, "Informe o usuário e a senha.", None

        matched = None
        for u in self.users:
            u_login = (u.get("username") or "").strip().lower()
            u_email = (u.get("email") or "").strip().lower()
            u_nome = (u.get("nome") or "").strip().lower()
            if ident in (u_login, u_email, u_nome):
                matched = u
                break

        if not matched:
            self.record_log(
                username=ident,
                user_nome=ident.upper(),
                user_role="DESCONHECIDO",
                category="SEGURANCA",
                action="FALHA DE LOGIN (USUÁRIO INEXISTENTE)",
                target=ident,
                details=f"Tentativa de login com usuário inexistente a partir do IP {ip_address}",
                ip_address=ip_address,
                severity="WARNING",
            )
            return False, "Usuário não encontrado.", None

        if not matched.get("active", True):
            self.record_log(
                username=matched["username"],
                user_nome=matched.get("nome", ""),
                user_role=matched.get("role", "USUARIO"),
                category="SEGURANCA",
                action="TENTATIVA DE LOGIN (CONTA BLOQUEADA)",
                target=matched["username"],
                details=f"Conta desativada tentou acessar a partir de {ip_address}",
                ip_address=ip_address,
                severity="DANGER",
            )
            return False, "Esta conta de usuário está desativada. Contate o Administrador.", None

        if not verify_password(password, matched.get("password_hash", "")):
            self.record_log(
                username=matched["username"],
                user_nome=matched.get("nome", ""),
                user_role=matched.get("role", "USUARIO"),
                category="SEGURANCA",
                action="SENHA INCORRETA NO LOGIN",
                target=matched["username"],
                details=f"Tentativa de senha inválida para '{matched['username']}' via IP {ip_address}",
                ip_address=ip_address,
                severity="WARNING",
            )
            return False, "Senha incorreta. Tente novamente.", None

        matched["last_login"] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        self.save_users()

        self.record_log(
            username=matched["username"],
            user_nome=matched.get("nome", ""),
            user_role=matched.get("role", "USUARIO"),
            category="ACESSO",
            action="LOGIN NO SISTEMA WEB",
            target=matched["username"],
            details=f"Acesso autenticado com sucesso ({matched.get('cargo', '')}) via IP {ip_address}",
            ip_address=ip_address,
            severity="SUCCESS",
        )
        return True, "Login realizado com sucesso!", self.sanitize_user(matched)

    def create_or_update_user_by_admin(
        self,
        admin_user: Dict[str, Any],
        payload: Dict[str, Any],
        ip_address: str = "",
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Permite ao ADMIN criar um novo usuário ou editar qualquer usuário existente."""
        raw_username = (payload.get("username") or "").strip().lower().replace(" ", "")
        nome = (payload.get("nome") or "").strip().upper()
        if not raw_username or not nome:
            return False, "Informe o login (usuário) e o nome completo.", None

        role = (payload.get("role") or "USUARIO").strip().upper()
        if role not in ("ADMIN", "USUARIO"):
            role = "USUARIO"

        existing = self.get_user(raw_username)
        is_new = existing is None
        new_password = (payload.get("password") or "").strip()

        if is_new and len(new_password) < 4:
            return False, "Defina uma senha inicial de pelo menos 4 caracteres para o novo usuário.", None

        # Impede remover o último ADMIN ativo
        active_flag = bool(payload.get("active", True))
        if existing and existing.get("role") == "ADMIN" and (role != "ADMIN" or not active_flag):
            other_admins = [
                u for u in self.users
                if u.get("username") != raw_username and u.get("role") == "ADMIN" and u.get("active", True)
            ]
            if not other_admins:
                return False, "Não é permitido remover ou desativar o único Administrador ativo do sistema.", None

        avatar_color = (payload.get("avatar_color") or "#2563EB").strip()
        now_str = datetime.now().strftime("%d/%m/%Y %H:%M")

        if is_new:
            user_rec = {
                "username": raw_username,
                "nome": nome,
                "email": (payload.get("email") or "").strip(),
                "cargo": (payload.get("cargo") or "Operador i-STAT").strip(),
                "setor": (payload.get("setor") or "ESTOQUE LYDA").strip().upper(),
                "telefone": (payload.get("telefone") or "").strip(),
                "role": role,
                "avatar_color": avatar_color,
                "active": active_flag,
                "must_change_password": True,
                "password_hash": hash_password(new_password),
                "created_at": now_str,
                "last_login": "",
            }
            self.users.append(user_rec)
            action_str = "CRIAÇÃO DE NOVO USUÁRIO"
            details_str = f"Criado usuário '{raw_username}' ({nome}) com perfil {role} e cargo '{user_rec['cargo']}'"
        else:
            existing["nome"] = nome
            existing["email"] = (payload.get("email") or existing.get("email", "")).strip()
            existing["cargo"] = (payload.get("cargo") or existing.get("cargo", "")).strip()
            existing["setor"] = (payload.get("setor") or existing.get("setor", "")).strip().upper()
            existing["telefone"] = (payload.get("telefone") or existing.get("telefone", "")).strip()
            existing["role"] = role
            existing["avatar_color"] = avatar_color
            existing["active"] = active_flag
            if new_password:
                existing["password_hash"] = hash_password(new_password)
                existing["must_change_password"] = True
            user_rec = existing
            action_str = "ATUALIZAÇÃO DE USUÁRIO PELO ADMIN"
            details_str = (
                f"Usuário '{raw_username}' ({nome}) atualizado | Perfil: {role} | Ativo: {'SIM' if active_flag else 'NÃO'}"
                + (" | Senha redefinida" if new_password else "")
            )

        self.save_users()
        self.record_log(
            username=admin_user.get("username", "admin"),
            user_nome=admin_user.get("nome", "ADMIN"),
            user_role=admin_user.get("role", "ADMIN"),
            category="USUARIOS",
            action=action_str,
            target=raw_username,
            details=details_str,
            ip_address=ip_address,
            severity="INFO",
        )
        return True, f"Usuário '{nome}' ({raw_username}) salvo com sucesso!", self.sanitize_user(user_rec)

    def update_own_profile(
        self,
        username: str,
        payload: Dict[str, Any],
        ip_address: str = "",
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Permite que o próprio usuário logado edite seu Perfil (Nome, Cargo, Telefone, Cor, Senha)."""
        user = self.get_user(username)
        if not user:
            return False, "Usuário não encontrado.", None

        nome = (payload.get("nome") or user.get("nome") or "").strip().upper()
        if not nome:
            return False, "O nome de exibição não pode ficar vazio.", None

        current_pwd = (payload.get("current_password") or "").strip()
        new_pwd = (payload.get("new_password") or "").strip()

        pwd_changed = False
        if new_pwd:
            if len(new_pwd) < 4:
                return False, "A nova senha deve ter pelo menos 4 caracteres.", None
            if current_pwd and not verify_password(current_pwd, user.get("password_hash", "")):
                return False, "A senha atual informada está incorreta.", None
            if new_pwd.lower() == "lyda123":
                return False, "A nova senha não pode ser a senha padrão 'lyda123'. Escolha uma senha pessoal segura.", None
            user["password_hash"] = hash_password(new_pwd)
            user["must_change_password"] = False
            user["last_password_change"] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
            pwd_changed = True

        user["nome"] = nome
        user["email"] = (payload.get("email") or user.get("email", "")).strip()
        user["cargo"] = (payload.get("cargo") or user.get("cargo", "")).strip()
        user["setor"] = (payload.get("setor") or user.get("setor", "")).strip().upper()
        user["telefone"] = (payload.get("telefone") or user.get("telefone", "")).strip()
        if payload.get("avatar_color"):
            user["avatar_color"] = payload["avatar_color"].strip()

        self.save_users()
        self.record_log(
            username=user["username"],
            user_nome=user["nome"],
            user_role=user.get("role", "USUARIO"),
            category="PERFIL",
            action="ATUALIZAÇÃO DE PERFIL PRÓPRIO",
            target=user["username"],
            details=f"Perfil atualizado por {user['nome']}" + (" (Senha alterada)" if pwd_changed else ""),
            ip_address=ip_address,
            severity="INFO",
        )
        return True, "Seu perfil foi atualizado com sucesso!", self.sanitize_user(user)

    def force_change_password(
        self,
        username: str,
        new_password: str,
        ip_address: str = "",
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Permite ao usuário definir obrigatoriamente sua nova senha pessoal no primeiro acesso."""
        user = self.get_user(username)
        if not user:
            return False, "Usuário não encontrado.", None

        new_pwd = (new_password or "").strip()
        if len(new_pwd) < 4:
            return False, "A nova senha deve ter no mínimo 4 caracteres.", None
        if new_pwd.lower() == "lyda123":
            return False, "A nova senha não pode ser a senha temporária 'lyda123'. Escolha uma senha pessoal segura.", None

        user["password_hash"] = hash_password(new_pwd)
        user["must_change_password"] = False
        user["last_password_change"] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

        self.save_users()
        self.record_log(
            username=user["username"],
            user_nome=user.get("nome", ""),
            user_role=user.get("role", "USUARIO"),
            category="SEGURANCA",
            action="NOVA SENHA DEFINIDA NO PRIMEIRO ACESSO",
            target=user["username"],
            details=f"Senha pessoal definida no primeiro acesso pelo usuário via IP {ip_address}",
            ip_address=ip_address,
            severity="SUCCESS",
        )
        return True, "Sua senha pessoal foi definida com sucesso!", self.sanitize_user(user)

    def delete_user_by_admin(
        self,
        admin_user: Dict[str, Any],
        target_username: str,
        ip_address: str = "",
    ) -> Tuple[bool, str]:
        target = (target_username or "").strip().lower()
        if target == (admin_user.get("username") or "").strip().lower():
            return False, "Você não pode excluir a sua própria conta logada."
        user = self.get_user(target)
        if not user:
            return False, "Usuário não encontrado."

        if user.get("role") == "ADMIN":
            other_admins = [
                u for u in self.users
                if u.get("username") != target and u.get("role") == "ADMIN" and u.get("active", True)
            ]
            if not other_admins:
                return False, "Não é possível excluir o único Administrador ativo."

        self.users = [u for u in self.users if (u.get("username") or "").lower() != target]
        self.save_users()
        self.record_log(
            username=admin_user.get("username", "admin"),
            user_nome=admin_user.get("nome", "ADMIN"),
            user_role="ADMIN",
            category="USUARIOS",
            action="EXCLUSÃO DE USUÁRIO",
            target=target,
            details=f"Conta '{target}' ({user.get('nome', '')}) excluída pelo administrador {admin_user.get('nome', '')}",
            ip_address=ip_address,
            severity="WARNING",
        )
        return True, f"Usuário '{target}' removido com sucesso."

    def record_log(
        self,
        username: str,
        user_nome: str,
        user_role: str,
        category: str,
        action: str,
        target: str = "",
        details: str = "",
        ip_address: str = "",
        severity: str = "INFO",
    ) -> Dict[str, Any]:
        now = datetime.now()
        entry = {
            "id": f"LOG-{int(time.time() * 1000)}-{secrets.token_hex(2).upper()}",
            "_epoch": time.time(),
            "timestamp": now.strftime("%d/%m/%Y %H:%M:%S"),
            "date_only": now.strftime("%Y-%m-%d"),
            "username": (username or "sistema").lower(),
            "user_nome": (user_nome or username or "SISTEMA").upper(),
            "user_role": (user_role or "USUARIO").upper(),
            "category": (category or "SISTEMA").upper(),
            "action": (action or "OPERAÇÃO").upper(),
            "target": str(target or "-"),
            "details": str(details or ""),
            "ip_address": str(ip_address or "127.0.0.1"),
            "severity": (severity or "INFO").upper(),
        }
        self.audit_logs.insert(0, entry)
        self.audit_logs = self.audit_logs[:3000]
        self.save_audit_logs()
        return entry

    def delete_audit_log_by_admin(self, log_id: str) -> bool:
        before = len(self.audit_logs)
        self.audit_logs = [x for x in self.audit_logs if x.get("id") != log_id]
        if len(self.audit_logs) < before:
            self.save_audit_logs()
            return True
        return False

    def clear_old_logs_by_admin(self, admin_user: Dict[str, Any], keep_last: int = 100, ip_address: str = "") -> int:
        total_before = len(self.audit_logs)
        if total_before <= keep_last:
            return 0
        removed_count = total_before - keep_last
        self.audit_logs = self.audit_logs[:keep_last]
        self.save_audit_logs()
        self.record_log(
            username=admin_user.get("username", "admin"),
            user_nome=admin_user.get("nome", "ADMIN"),
            user_role="ADMIN",
            category="AUDITORIA",
            action="LIMPEZA DE LOGS ANTIGOS",
            target=f"{removed_count} registros",
            details=f"Administrador arquivou/removeu {removed_count} logs antigos (mantidos os {keep_last} mais recentes).",
            ip_address=ip_address,
            severity="WARNING",
        )
        return removed_count

