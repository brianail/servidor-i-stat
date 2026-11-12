let APP_STATE = {
  authenticated: false,
  current_user: null,
  items: [],
  clients: [],
  known_client_names: [],
  history: [],
  users: [],
  audit_logs: [],
  kpis: {},
  config: {},
  server_info: {},
  selectedIndices: new Set(),
  zebraSelectedIndices: new Set(),
  kpiQuickFilter: "ALL",
  radarSubFilter: "ALL_NEED",
  clientListFilter: "ALL",
  selectedClientName: "",
  routeStops: [],
  selectedRouteStopIdx: 0,
  routeMetrics: {},
  batchMode: "",
};

let routeLeafletMap = null;
let routeTileLayer = null;
let routeMarkersLayer = null;
let routePolylineLayer = null;

function showToast(msg, type = "info") {
  const wrap = document.getElementById("toastContainer");
  if (!wrap) return;
  const el = document.createElement("div");
  el.className = "toast " + type;
  el.innerText = msg;
  wrap.appendChild(el);
  setTimeout(() => el.remove(), 4500);
}

function escapeHtml(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function formatCleanTitleCase(str) {
  const s = String(str || "").trim();
  if (!s) return "";
  const lowerWords = new Set(["da", "de", "do", "das", "dos", "e"]);
  return s
    .toLowerCase()
    .split(/\s+/)
    .map((w, i) => {
      if (i > 0 && lowerWords.has(w)) return w;
      return w.charAt(0).toUpperCase() + w.slice(1);
    })
    .join(" ");
}

function formatRealPct(count, total) {
  const t = Number(total) || 0;
  if (t <= 0) return "0%";
  const v = (Number(count) / t) * 100;
  if (Math.abs(v - Math.round(v)) < 0.005) return `${Math.round(v)}%`;
  return `${v.toFixed(1).replace(".", ",")}%`;
}

// =========================================================================
// BOOTSTRAP E AUTENTICAÇÃO (LOGIN / SESSÃO / PERFIS)
// =========================================================================
async function loadBootstrapData(preserveSelection = true) {
  try {
    const res = await fetch("/api/bootstrap");
    const data = await res.json();
    if (!data.ok) return;

    const darkSurfaceLogo = data.logo_white_data_uri || data.logo_data_uri;
    if (darkSurfaceLogo) {
      const topLogo = document.getElementById("logoContainer");
      if (topLogo) topLogo.innerHTML = `<img src="${darkSurfaceLogo}" alt="LYDA" />`;
      const loginLogo = document.getElementById("loginLogoContainer");
      if (loginLogo) loginLogo.innerHTML = `<img src="${darkSurfaceLogo}" alt="LYDA" />`;
    }

    if (!data.authenticated) {
      APP_STATE.authenticated = false;
      APP_STATE.current_user = null;
      document.getElementById("loginScreen").classList.add("active");
      renderLoginQuickHints();
      return;
    }

    document.getElementById("loginScreen").classList.remove("active");
    APP_STATE.authenticated = true;
    APP_STATE.current_user = data.current_user || {};
    APP_STATE.items = data.items || [];
    APP_STATE.clients = data.clients || [];
    APP_STATE.known_client_names = data.known_client_names || [];
    APP_STATE.history = data.history || [];
    APP_STATE.users = data.users || [];
    APP_STATE.audit_logs = data.audit_logs || [];
    APP_STATE.kpis = data.kpis || {};
    APP_STATE.config = data.config || {};
    APP_STATE.server_info = data.server_info || {};
    APP_STATE.logo_data_uri = data.logo_data_uri || "";

    if (!preserveSelection) {
      APP_STATE.selectedIndices.clear();
    }

    renderCurrentUserTopbar();

    if (APP_STATE.current_user && APP_STATE.current_user.must_change_password) {
      openForceChangePasswordModal();
    } else {
      closeForceChangePasswordModal();
    }

    const srv = APP_STATE.server_info;
    const lblSrv = document.getElementById("lblServerUrl");
    if (lblSrv) {
      lblSrv.innerText = "Online";
      lblSrv.title = `Rede Local: ${srv.primary_url || window.location.origin} (${srv.hostname || "Servidor"})`;
    }
    const spDir = srv.sharepoint_backup_dir;
    const lblSp = document.getElementById("lblSharepointStatus");
    if (lblSp) {
      lblSp.innerText = spDir ? "SharePoint Ativo" : "Backup Diário Ativo";
    }

    populateDropdownOptions();
    renderKpis();
    renderExecutiveDashboard();
    renderItemsTable();
    renderRadar6mTab();
    renderClientsList();
    renderZebraStudio();
    renderHistoryTable();
    renderServerAndSharepointTab();
    renderAdminUsersAndLogsTab();
  } catch (err) {
    console.error("Erro no bootstrap:", err);
  }
}

const LOGIN_REMEMBER_KEY = "LYDA_LOGIN_LAST_USERS";

function getRememberedLoginUsers() {
  try {
    const arr = JSON.parse(localStorage.getItem(LOGIN_REMEMBER_KEY) || "[]");
    return Array.isArray(arr) ? arr.filter(x => typeof x === "string" && x).slice(0, 4) : [];
  } catch (e) {
    return [];
  }
}

function rememberLoginUser(username) {
  const chk = document.getElementById("chkLoginRemember");
  if (chk && !chk.checked) return;
  const list = [username, ...getRememberedLoginUsers().filter(u => u !== username)].slice(0, 4);
  try { localStorage.setItem(LOGIN_REMEMBER_KEY, JSON.stringify(list)); } catch (e) {}
}

function forgetLoginUser(username) {
  const list = getRememberedLoginUsers().filter(u => u !== username);
  try { localStorage.setItem(LOGIN_REMEMBER_KEY, JSON.stringify(list)); } catch (e) {}
  renderLoginQuickHints();
}

// Apenas nomes de usuario (nunca senhas) usados neste computador. Sem lista publica de contas.
function renderLoginQuickHints() {
  const box = document.getElementById("divLoginQuickPills");
  const section = document.getElementById("loginQuickSection");
  if (!box) return;
  const users = getRememberedLoginUsers();
  if (section) section.style.display = users.length ? "block" : "none";
  box.innerHTML = users.map(u => `
    <div class="quick-user-pill" title="Usar o usuário ${escapeHtml(u)}">
      <span class="qu-main" onclick="fillQuickLogin('${escapeHtml(u).replace(/'/g, "\\'")}')">
        <span class="qu-avatar" style="background:#2563EB;">${escapeHtml(u.slice(0, 2).toUpperCase())}</span>
        <span class="qu-name">${escapeHtml(u)}</span>
      </span>
      <button type="button" class="qu-forget" title="Esquecer este usuário" onclick="forgetLoginUser('${escapeHtml(u).replace(/'/g, "\\'")}')">
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.8" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
      </button>
    </div>
  `).join("");
}

function fillQuickLogin(username) {
  document.getElementById("inpLoginUsername").value = username;
  const pwd = document.getElementById("inpLoginPassword");
  pwd.value = "";
  pwd.focus();
}

function setLoginPasswordHidden() {
  const inp = document.getElementById("inpLoginPassword");
  if (inp) inp.type = "password";
  const eyeOn = document.getElementById("loginEyeOn");
  const eyeOff = document.getElementById("loginEyeOff");
  if (eyeOn) eyeOn.style.display = "block";
  if (eyeOff) eyeOff.style.display = "none";
}

function toggleLoginPasswordVisibility() {
  const inp = document.getElementById("inpLoginPassword");
  const show = inp.type === "password";
  inp.type = show ? "text" : "password";
  const eyeOn = document.getElementById("loginEyeOn");
  const eyeOff = document.getElementById("loginEyeOff");
  if (eyeOn) eyeOn.style.display = show ? "none" : "block";
  if (eyeOff) eyeOff.style.display = show ? "block" : "none";
}

function onLoginPasswordKey(e) {
  const warn = document.getElementById("lblLoginCaps");
  if (!warn || !e.getModifierState) return;
  warn.style.display = e.getModifierState("CapsLock") ? "flex" : "none";
}

async function submitLogin(e) {
  if (e) e.preventDefault();
  const username = document.getElementById("inpLoginUsername").value.trim();
  const password = document.getElementById("inpLoginPassword").value.trim();
  const errBox = document.getElementById("lblLoginError");
  const btn = document.getElementById("btnLoginSubmit");
  errBox.style.display = "none";
  if (btn) { btn.disabled = true; btn.classList.add("loading"); }

  try {
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) {
      errBox.innerText = data.error || "Falha no login.";
      errBox.style.display = "block";
      document.getElementById("inpLoginPassword").value = "";
      document.getElementById("inpLoginPassword").focus();
      return;
    }
    rememberLoginUser(username);
    document.getElementById("inpLoginPassword").value = "";
    setLoginPasswordHidden();
    showToast(`Bem-vindo(a), ${data.user.nome}!`, "success");
    await loadBootstrapData(false);
  } catch (err) {
    errBox.innerText = "Erro de conexão com o servidor.";
    errBox.style.display = "block";
  } finally {
    if (btn) { btn.disabled = false; btn.classList.remove("loading"); }
  }
}

async function logoutUser() {
  closeForceChangePasswordModal();
  await fetch("/api/auth/logout", { method: "POST" });
  showToast("Sessão encerrada.", "info");
  await loadBootstrapData(false);
}

// =========================================================================
// PRIMEIRO ACESSO: TROCA OBRIGATÓRIA DE SENHA
// =========================================================================
function openForceChangePasswordModal() {
  const backdrop = document.getElementById("forceChangePasswordModalBackdrop");
  if (!backdrop) return;
  const u = APP_STATE.current_user || {};
  const elAvatar = document.getElementById("forcePwdAvatar");
  if (elAvatar) {
    elAvatar.innerText = u.initials || "LY";
    elAvatar.style.background = u.avatar_color || "#2563EB";
  }
  const elNome = document.getElementById("forcePwdNome");
  if (elNome) elNome.innerText = u.nome || "Usuário";
  const elUser = document.getElementById("forcePwdUser");
  if (elUser) elUser.innerText = `Login: ${u.username || "admin"} • Nível: ${u.role === "ADMIN" ? "Administrador" : "Operador"}`;

  const inpNew = document.getElementById("inpForceNewPwd");
  const inpConf = document.getElementById("inpForceConfirmPwd");
  if (inpNew) { inpNew.value = ""; inpNew.type = "password"; }
  if (inpConf) { inpConf.value = ""; inpConf.type = "password"; }

  const eyeNewOn = document.getElementById("eyeForceNewOn");
  const eyeNewOff = document.getElementById("eyeForceNewOff");
  if (eyeNewOn) eyeNewOn.style.display = "block";
  if (eyeNewOff) eyeNewOff.style.display = "none";

  const eyeConfOn = document.getElementById("eyeForceConfirmOn");
  const eyeConfOff = document.getElementById("eyeForceConfirmOff");
  if (eyeConfOn) eyeConfOn.style.display = "block";
  if (eyeConfOff) eyeConfOff.style.display = "none";

  const errBox = document.getElementById("lblForcePwdError");
  if (errBox) { errBox.innerText = ""; errBox.style.display = "none"; }
  const matchBox = document.getElementById("lblForcePwdMatch");
  if (matchBox) { matchBox.innerText = ""; matchBox.style.display = "none"; }

  backdrop.classList.add("open");
  if (inpNew) setTimeout(() => inpNew.focus(), 150);
}

function closeForceChangePasswordModal() {
  const backdrop = document.getElementById("forceChangePasswordModalBackdrop");
  if (backdrop) backdrop.classList.remove("open");
}

function toggleForcePwdVisibility(inputId, eyeOnId, eyeOffId) {
  const inp = document.getElementById(inputId);
  if (!inp) return;
  const show = inp.type === "password";
  inp.type = show ? "text" : "password";
  const eyeOn = document.getElementById(eyeOnId);
  const eyeOff = document.getElementById(eyeOffId);
  if (eyeOn) eyeOn.style.display = show ? "none" : "block";
  if (eyeOff) eyeOff.style.display = show ? "block" : "none";
}

function validateForcePasswordMatch() {
  const inpNew = document.getElementById("inpForceNewPwd");
  const inpConf = document.getElementById("inpForceConfirmPwd");
  const matchBox = document.getElementById("lblForcePwdMatch");
  const errBox = document.getElementById("lblForcePwdError");
  if (!inpNew || !inpConf || !matchBox) return;

  const vNew = inpNew.value;
  const vConf = inpConf.value;
  if (errBox) errBox.style.display = "none";

  if (!vConf) {
    matchBox.style.display = "none";
    return;
  }

  matchBox.style.display = "block";
  if (vNew === vConf) {
    matchBox.style.color = "#059669";
    matchBox.innerText = "As senhas digitadas conferem.";
  } else {
    matchBox.style.color = "#DC2626";
    matchBox.innerText = "As senhas digitadas ainda não coincidem.";
  }
}

async function submitForceChangePassword(e) {
  if (e) e.preventDefault();
  const inpNew = document.getElementById("inpForceNewPwd");
  const inpConf = document.getElementById("inpForceConfirmPwd");
  const errBox = document.getElementById("lblForcePwdError");
  const btn = document.getElementById("btnForceSubmit");
  if (errBox) errBox.style.display = "none";

  const newPwd = ((inpNew && inpNew.value) || "").trim();
  const confPwd = ((inpConf && inpConf.value) || "").trim();

  if (!newPwd) {
    if (errBox) { errBox.innerText = "Por favor, digite a nova senha."; errBox.style.display = "block"; }
    if (inpNew) inpNew.focus();
    return;
  }
  if (newPwd.length < 4) {
    if (errBox) { errBox.innerText = "A nova senha deve ter no mínimo 4 caracteres."; errBox.style.display = "block"; }
    if (inpNew) inpNew.focus();
    return;
  }
  if (newPwd.toLowerCase() === "lyda123") {
    if (errBox) { errBox.innerText = "A nova senha não pode ser a senha temporária 'lyda123'. Escolha uma senha pessoal segura."; errBox.style.display = "block"; }
    if (inpNew) inpNew.focus();
    return;
  }
  if (newPwd !== confPwd) {
    if (errBox) { errBox.innerText = "A confirmação de senha não coincide com a nova senha digitada."; errBox.style.display = "block"; }
    if (inpConf) inpConf.focus();
    return;
  }

  if (btn) { btn.disabled = true; btn.innerText = "Salvando..."; }

  try {
    const res = await fetch("/api/auth/force-change-password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ new_password: newPwd, confirm_password: confPwd }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) {
      if (errBox) {
        errBox.innerText = data.error || "Erro ao definir nova senha.";
        errBox.style.display = "block";
      }
      return;
    }

    closeForceChangePasswordModal();
    if (data.user) {
      APP_STATE.current_user = data.user;
    }
    showToast(data.message || "Nova senha cadastrada com sucesso! Bem-vindo(a).", "success");
    await loadBootstrapData(true);
  } catch (err) {
    if (errBox) {
      errBox.innerText = "Erro de conexão com o servidor.";
      errBox.style.display = "block";
    }
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><polyline points="20 6 9 17 4 12"/></svg> Salvar Nova Senha & Entrar`;
    }
  }
}

function renderCurrentUserTopbar() {
  const u = APP_STATE.current_user || {};
  const isAdmin = u.role === "ADMIN";

  const avatar = document.getElementById("topUserAvatar");
  if (avatar) {
    avatar.innerText = u.initials || "LY";
    avatar.style.background = u.avatar_color || "#2563EB";
  }
  const cleanName = formatCleanTitleCase(u.nome || u.username || "Usuário");
  document.getElementById("topUserName").innerText = cleanName;
  document.getElementById("topUserRole").innerText = isAdmin ? "Administrador" : "Operador i-STAT";

  // Mostra/Oculta aba de Admin de Usuários & Logs conforme perfil
  const tabAdminBtn = document.getElementById("navTabAdminUsers");
  if (tabAdminBtn) {
    tabAdminBtn.style.display = isAdmin ? "flex" : "none";
  }
  document.querySelectorAll(".admin-only").forEach(el => {
    el.style.display = isAdmin ? "" : "none";
  });
}

// =========================================================================
// MODAL "MEU PERFIL" (EDITAR DADOS E ALTERAR PRÓPRIA SENHA)
// =========================================================================
function openProfileModal() {
  const u = APP_STATE.current_user;
  if (!u) return;
  document.getElementById("inpProfUsername").value = u.username || "";
  document.getElementById("inpProfRole").value = u.role === "ADMIN" ? "ADMINISTRADOR TOTAL" : "USUÁRIO / OPERADOR";
  document.getElementById("inpProfNome").value = u.nome || "";
  document.getElementById("inpProfCargo").value = u.cargo || "";
  document.getElementById("inpProfSetor").value = u.setor || "";
  document.getElementById("inpProfEmail").value = u.email || "";
  document.getElementById("inpProfTelefone").value = u.telefone || "";
  document.getElementById("selProfColor").value = u.avatar_color || "#2563EB";
  document.getElementById("inpProfCurPwd").value = "";
  document.getElementById("inpProfNewPwd").value = "";
  document.getElementById("profileModalBackdrop").classList.add("open");
}

function closeProfileModal() {
  document.getElementById("profileModalBackdrop").classList.remove("open");
}

async function saveOwnProfile() {
  const payload = {
    nome: document.getElementById("inpProfNome").value.trim(),
    cargo: document.getElementById("inpProfCargo").value.trim(),
    setor: document.getElementById("inpProfSetor").value.trim(),
    email: document.getElementById("inpProfEmail").value.trim(),
    telefone: document.getElementById("inpProfTelefone").value.trim(),
    avatar_color: document.getElementById("selProfColor").value,
    current_password: document.getElementById("inpProfCurPwd").value.trim(),
    new_password: document.getElementById("inpProfNewPwd").value.trim(),
  };

  try {
    const res = await fetch("/api/auth/profile", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!data.ok) {
      showToast(data.error || "Erro ao atualizar perfil.", "error");
      return;
    }
    showToast(data.message, "success");
    closeProfileModal();
    await loadBootstrapData(true);
  } catch (e) {
    showToast("Erro ao salvar perfil.", "error");
  }
}

// =========================================================================
// ABA 5 (EXCLUSIVA ADMIN): GESTÃO DE USUÁRIOS, PERFIS E LOGS DE AUDITORIA
// =========================================================================
function renderAdminUsersAndLogsTab() {
  const u = APP_STATE.current_user;
  if (!u || u.role !== "ADMIN") return;

  const users = APP_STATE.users || [];
  const badgeUsers = document.getElementById("badgeCountAdminUsers");
  if (badgeUsers) badgeUsers.innerText = users.length;

  const tbodyUsers = document.getElementById("tbodyAdminUsers");
  if (tbodyUsers) {
    tbodyUsers.innerHTML = users.map(usr => {
      const roleBadge = usr.role === "ADMIN"
        ? `<span class="badge badge-admin">ADMIN</span>`
        : `<span class="badge badge-user">USUÁRIO</span>`;
      const activeBadge = usr.active !== false
        ? `<span class="badge badge-em-dia">ATIVO</span>`
        : `<span class="badge badge-vencida">BLOQUEADO</span>`;
      return `
        <tr>
          <td>
            <div style="display:flex; align-items:center; gap:8px;">
              <div class="user-avatar" style="width:26px; height:26px; font-size:10px; background:${escapeHtml(usr.avatar_color || '#2563EB')};">${escapeHtml(usr.initials || 'U')}</div>
              <div>
                <div style="font-weight:800;">${escapeHtml(usr.nome)}</div>
                <div style="font-size:11px; color:#64748B;">Login: <strong>${escapeHtml(usr.username)}</strong></div>
              </div>
            </div>
          </td>
          <td>${roleBadge}</td>
          <td>${escapeHtml(usr.cargo || "-")}</td>
          <td>${escapeHtml(usr.setor || "-")}</td>
          <td>${activeBadge}</td>
          <td style="font-size:11px; color:#475569;">${escapeHtml(usr.last_login || "Nunca acessou")}</td>
          <td style="text-align:right; white-space:nowrap;">
            <button class="btn btn-primary btn-sm" onclick="editUserInAdminForm('${escapeHtml(usr.username)}')">Editar / Senha</button>
            <button class="btn btn-danger btn-sm" onclick="deleteUserByAdmin('${escapeHtml(usr.username)}')">Excluir</button>
          </td>
        </tr>
      `;
    }).join("");
  }

  // Filtro de usuários nos logs
  const selLogUser = document.getElementById("selFilterLogUser");
  if (selLogUser) {
    const curVal = selLogUser.value;
    const uniqueUsers = Array.from(new Set((APP_STATE.audit_logs || []).map(l => l.user_nome).filter(Boolean))).sort();
    selLogUser.innerHTML = `<option value="TODOS">TODOS OS USUÁRIOS</option>` +
      uniqueUsers.map(un => `<option value="${escapeHtml(un)}">${escapeHtml(un)}</option>`).join("");
    if (uniqueUsers.includes(curVal)) selLogUser.value = curVal;
  }

  renderAuditLogsTable();
}

function prepareNewAdminUserForm() {
  document.getElementById("lblAdminUserFormTitle").innerText = "Criar Novo Usuário / Operador";
  document.getElementById("inpAdmUsername").value = "";
  document.getElementById("inpAdmUsername").readOnly = false;
  document.getElementById("inpAdmNome").value = "";
  document.getElementById("selAdmRole").value = "USUARIO";
  document.getElementById("inpAdmCargo").value = "Enfermeira / Operador i-STAT";
  document.getElementById("inpAdmSetor").value = "ESTOQUE LYDA";
  document.getElementById("inpAdmEmail").value = "";
  document.getElementById("inpAdmPassword").value = "";
  document.getElementById("inpAdmPassword").placeholder = "Senha inicial (obrigatória)";
  document.getElementById("selAdmActive").value = "SIM";
  document.getElementById("selAdmColor").value = "#2563EB";
  document.getElementById("inpAdmUsername").focus();
}

function editUserInAdminForm(username) {
  const usr = (APP_STATE.users || []).find(u => u.username === username);
  if (!usr) return;
  document.getElementById("lblAdminUserFormTitle").innerText = `Editando Usuário: ${usr.nome} (${usr.username})`;
  document.getElementById("inpAdmUsername").value = usr.username;
  document.getElementById("inpAdmUsername").readOnly = true;
  document.getElementById("inpAdmNome").value = usr.nome || "";
  document.getElementById("selAdmRole").value = usr.role || "USUARIO";
  document.getElementById("inpAdmCargo").value = usr.cargo || "";
  document.getElementById("inpAdmSetor").value = usr.setor || "";
  document.getElementById("inpAdmEmail").value = usr.email || "";
  document.getElementById("inpAdmPassword").value = "";
  document.getElementById("inpAdmPassword").placeholder = "Deixe em branco p/ manter a senha atual";
  document.getElementById("selAdmActive").value = usr.active !== false ? "SIM" : "NAO";
  document.getElementById("selAdmColor").value = usr.avatar_color || "#2563EB";
}

async function saveAdminUserForm() {
  const payload = {
    username: document.getElementById("inpAdmUsername").value.trim(),
    nome: document.getElementById("inpAdmNome").value.trim(),
    role: document.getElementById("selAdmRole").value,
    cargo: document.getElementById("inpAdmCargo").value.trim(),
    setor: document.getElementById("inpAdmSetor").value.trim(),
    email: document.getElementById("inpAdmEmail").value.trim(),
    password: document.getElementById("inpAdmPassword").value.trim(),
    active: document.getElementById("selAdmActive").value === "SIM",
    avatar_color: document.getElementById("selAdmColor").value,
  };

  try {
    const res = await fetch("/api/admin/users/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!data.ok) {
      showToast(data.error || "Erro ao salvar usuário.", "error");
      return;
    }
    showToast(data.message, "success");
    prepareNewAdminUserForm();
    await loadBootstrapData(true);
  } catch (e) {
    showToast("Erro ao salvar usuário.", "error");
  }
}

async function deleteUserByAdmin(username) {
  if (!confirm(`Deseja realmente excluir a conta do usuário '${username}'?`)) return;
  const res = await fetch("/api/admin/users/delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username }),
  });
  const data = await res.json();
  if (!data.ok) {
    showToast(data.error || "Erro ao excluir usuário.", "error");
    return;
  }
  showToast(data.message, "success");
  await loadBootstrapData(true);
}

function renderAuditLogsTable() {
  const tbody = document.getElementById("tbodyAuditLogs");
  if (!tbody) return;

  const q = (document.getElementById("inpSearchAuditLogs").value || "").trim().toUpperCase();
  const fUser = document.getElementById("selFilterLogUser").value;
  const fCat = document.getElementById("selFilterLogCategory").value;

  const allLogs = APP_STATE.audit_logs || [];
  const filtered = allLogs.filter(lg => {
    if (fUser !== "TODOS" && lg.user_nome !== fUser) return false;
    if (fCat !== "TODAS" && lg.category !== fCat) return false;
    if (q) {
      const hay = [lg.timestamp, lg.username, lg.user_nome, lg.category, lg.action, lg.target, lg.details, lg.ip_address].join(" ").toUpperCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });

  document.getElementById("lblAuditLogsCount").innerText =
    `Exibindo ${Math.min(filtered.length, 300)} de ${filtered.length} registros de auditoria`;

  tbody.innerHTML = filtered.slice(0, 300).map(lg => {
    let sevBadge = `<span class="badge badge-ana">${escapeHtml(lg.category)}</span>`;
    if (lg.severity === "SUCCESS") sevBadge = `<span class="badge badge-em-dia">${escapeHtml(lg.category)}</span>`;
    else if (lg.severity === "WARNING") sevBadge = `<span class="badge badge-vencendo">${escapeHtml(lg.category)}</span>`;
    else if (lg.severity === "DANGER") sevBadge = `<span class="badge badge-vencida">${escapeHtml(lg.category)}</span>`;

    const canDelete = String(lg.id || "").startsWith("LOG-");
    return `
      <tr>
        <td style="white-space:nowrap; font-weight:700;">${escapeHtml(lg.timestamp)}</td>
        <td>
          <strong>${escapeHtml(lg.user_nome)}</strong>
          <span style="font-size:10px; color:#64748B; display:block;">${escapeHtml(lg.user_role)} • IP: ${escapeHtml(lg.ip_address)}</span>
        </td>
        <td>${sevBadge}</td>
        <td style="font-weight:800; color:#0F172A;">${escapeHtml(lg.action)}</td>
        <td style="font-family:monospace; font-weight:700; color:#1E40AF;">${escapeHtml(lg.target)}</td>
        <td>${escapeHtml(lg.details)}</td>
        <td style="text-align:right;">
          ${canDelete ? `<button class="btn btn-danger btn-sm" onclick="deleteSingleAuditLog('${escapeHtml(lg.id)}')">Excluir</button>` : `-`}
        </td>
      </tr>
    `;
  }).join("");
}

async function deleteSingleAuditLog(logId) {
  const res = await fetch("/api/admin/logs/manage", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "DELETE_ONE", log_id: logId }),
  });
  const data = await res.json();
  if (data.ok) {
    APP_STATE.audit_logs = data.logs || [];
    renderAuditLogsTable();
  }
}

async function clearOldAuditLogs() {
  if (!confirm("Deseja arquivar/limpar os logs antigos mantendo apenas os 100 registros mais recentes?")) return;
  const res = await fetch("/api/admin/logs/manage", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "CLEAR_OLD", keep_last: 100 }),
  });
  const data = await res.json();
  if (data.ok) {
    APP_STATE.audit_logs = data.logs || [];
    showToast(data.message, "success");
    renderAuditLogsTable();
  }
}

// =========================================================================
// ESTOQUE, FILTROS E TABELA PRINCIPAL
// =========================================================================
function populateDropdownOptions() {
  const cfg = APP_STATE.config;
  const ops = cfg.operators || ["OPERADOR"];
  const curOp = (APP_STATE.current_user && APP_STATE.current_user.nome) || cfg.operador_atual || ops[0];

  for (const selId of ["selModalOperador", "selRouteNurse"]) {
    const sel = document.getElementById(selId);
    if (!sel) continue;
    sel.innerHTML = ops.map(o => `<option value="${escapeHtml(o)}">${escapeHtml(o)}</option>`).join("");
    sel.value = curOp;
  }

  const selStatus = document.getElementById("selModalStatus");
  if (selStatus) {
    selStatus.innerHTML = (cfg.status_options || []).map(s => `<option value="${escapeHtml(s)}">${escapeHtml(s)}</option>`).join("");
  }

  const selCond = document.getElementById("selModalCondicao");
  if (selCond) {
    selCond.innerHTML = (cfg.condicao_options || []).map(c => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join("");
  }

  const dl = document.getElementById("dlKnownClients");
  if (dl) {
    dl.innerHTML = (APP_STATE.known_client_names || []).map(c => `<option value="${escapeHtml(c)}"></option>`).join("");
  }

  const selRouteAdd = document.getElementById("selRouteAddClient");
  if (selRouteAdd) {
    const activeClients = (APP_STATE.known_client_names || []).filter(c => !c.includes("SEM CLIENTE"));
    selRouteAdd.innerHTML = activeClients.map(c => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join("");
  }

  const selPrn = document.getElementById("selZebraPrinter");
  if (selPrn) {
    const printers = cfg.printers || [];
    selPrn.innerHTML = printers.length
      ? printers.map(p => `<option value="${escapeHtml(p)}">${escapeHtml(p)}</option>`).join("")
      : `<option value="">Nenhuma impressora detectada no Servidor</option>`;
  }

  initZebraFormFromServerConfig(cfg.zebra_config);

  const inpOrigin = document.getElementById("inpRouteOrigin");
  if (inpOrigin && !inpOrigin.value) {
    inpOrigin.value = cfg.lyda_hq_address || "";
  }
  const inpDate = document.getElementById("inpRouteDate");
  if (inpDate && !inpDate.value) {
    inpDate.value = new Date().toLocaleDateString("pt-BR");
  }
}

function renderKpis() {
  const k = APP_STATE.kpis || {};
  const elTotal = document.getElementById("valKpiTotal");
  if (elTotal) elTotal.innerText = k.total || 0;

  const elCli = document.getElementById("valKpiCliente");
  if (elCli) elCli.innerText = k.em_cliente || 0;

  const subCli = document.getElementById("subKpiCliente");
  if (subCli) {
    const defCli = k.defeito_em_cliente || 0;
    subCli.innerText = defCli > 0
      ? `Ativos: ${k.em_cliente || 0} (+${defCli} em manutenção)`
      : `Em operação externa`;
  }

  const elEst = document.getElementById("valKpiEstoque");
  if (elEst) elEst.innerText = k.em_estoque || 0;

  const subEst = document.getElementById("subKpiEstoque");
  if (subEst) {
    const estNovos = k.estoque_novos || 0;
    const estUsados = k.estoque_usados || 0;
    const estBackup = k.estoque_backup || 0;
    if (estNovos > 0 || estUsados > 0) {
      subEst.innerText = `${estNovos} Novos • ${estUsados} Usados${estBackup > 0 ? ` • ${estBackup} Backup` : ""}`;
    } else {
      subEst.innerText = `Atualizados: ${k.estoque_atualizado || 0} | Falta: ${k.estoque_falta_atualizar || 0}`;
    }
  }

  const elCom = document.getElementById("valKpiComodato");
  if (elCom) elCom.innerText = k.comodato_aluguel || 0;

  const subCom = document.getElementById("subKpiComodato");
  if (subCom) {
    const comAtivo = k.comodato_ativo ?? (k.comodato_aluguel || 0);
    const comManut = k.comodato_manut || 0;
    subCom.innerText = comManut > 0
      ? `Ativos: ${comAtivo} (+${comManut} manut.)`
      : `Ativos em hospitais: ${comAtivo}`;
  }

  const elVenda = document.getElementById("valKpiVenda");
  if (elVenda) elVenda.innerText = k.venda || 0;

  const subVenda = document.getElementById("subKpiVenda");
  if (subVenda) {
    const vndAtivo = k.venda_ativo ?? (k.venda || 0);
    const vndManut = k.venda_manut || 0;
    subVenda.innerText = vndManut > 0
      ? `Em uso: ${vndAtivo} (+${vndManut} manut.)`
      : `Vendidos em operação: ${vndAtivo}`;
  }

  const elCicloOk = document.getElementById("valKpiCicloOk");
  if (elCicloOk) elCicloOk.innerText = k.ciclo_em_dia || 0;

  const elCicloPend = document.getElementById("valKpiCicloPend");
  if (elCicloPend) elCicloPend.innerText = k.ciclo_pendente_vencido || 0;

  const subCicloPend = document.getElementById("subKpiCicloPend");
  if (subCicloPend) {
    subCicloPend.innerText = `Perto 6m: ${k.ciclo_vencendo || 0} | Vencidos: ${k.ciclo_vencida || 0} | S/ data: ${k.ciclo_sem_data || 0}`;
  }

  const defCount = k.defeito_manutencao ?? k.em_defeito ?? 0;
  const elDefeito = document.getElementById("valKpiDefeito");
  if (elDefeito) elDefeito.innerText = defCount;

  const subDefeito = document.getElementById("subKpiDefeito");
  if (subDefeito) {
    const defCli = k.defeito_em_cliente || 0;
    const defEst = k.defeito_em_estoque || 0;
    subDefeito.innerText = defCount > 0
      ? `${defCli} de hospitais • ${defEst} estoque (SP)`
      : `Em reparo ou assistência SP`;
  }

  // Badges da Sidebar e Topbar
  const bEst = document.getElementById("badgeCountEstoque");
  if (bEst) bEst.innerText = k.total || 0;

  const bCli = document.getElementById("badgeCountClientes");
  if (bCli) bCli.innerText = (APP_STATE.clients || []).length;

  const totalNeed6m = (k.ciclo_pendente_vencido || 0);
  const bRadar = document.getElementById("badgeCountRadar6m");
  if (bRadar) bRadar.innerText = totalNeed6m;

  const lblTopRadar = document.getElementById("lblTopRadarBtnText");
  if (lblTopRadar) {
    const urgent = (k.ciclo_vencendo || 0) + (k.ciclo_vencida || 0);
    lblTopRadar.innerText = urgent > 0
      ? `Alerta 6 Meses: ${urgent} (${totalNeed6m} pend.)`
      : `Atualizações 6m: ${totalNeed6m}`;
  }

  // Banner Inteligente de Aviso de 6 Meses no topo do Estoque
  const banner = document.getElementById("divCycleWarningBanner");
  if (banner) {
    const vencendo = k.ciclo_vencendo || 0;
    const vencida = k.ciclo_vencida || 0;
    const semData = k.ciclo_sem_data || 0;
    const faltaBancada = k.estoque_falta_atualizar || 0;

    if (vencendo > 0 || vencida > 0 || faltaBancada > 0 || semData > 0) {
      banner.style.display = "flex";
      banner.classList.toggle("danger", vencida > 0);
      const titleEl = document.getElementById("lblBannerCycleTitle");
      const subEl = document.getElementById("lblBannerCycleSub");

      if (vencendo > 0 || vencida > 0) {
        titleEl.innerText = `Aviso de Ciclo Semestral (6 Meses): ${vencendo} perto de bater 6 meses e ${vencida} vencido(s)`;
      } else {
        titleEl.innerText = `Monitoramento Semestral (6 em 6 Meses): ${totalNeed6m} aparelho(s) aguardando registro ou atualização`;
      }

      const parts = [];
      if (vencendo > 0) parts.push(`${vencendo} perto de bater 6 meses (<= 45 dias)`);
      if (vencida > 0) parts.push(`${vencida} com ciclo de 6 meses vencido`);
      if (faltaBancada > 0) parts.push(`${faltaBancada} no estoque aguardando atualização`);
      if (semData > 0) parts.push(`${semData} sem data inicial de atualização preenchida`);
      subEl.innerText = parts.join("  •  ");
    } else {
      banner.style.display = "none";
    }
  }

  const kTotal = k.total || 0;
  const setPct = (id, c) => { const el = document.getElementById(id); if (el) el.innerText = formatRealPct(c, kTotal); };
  setPct("pctKpiTotal", kTotal);
  setPct("pctKpiCliente", k.em_cliente || 0);
  setPct("pctKpiEstoque", k.em_estoque || 0);
  setPct("pctKpiComodato", k.comodato_aluguel || 0);
  setPct("pctKpiVenda", k.venda || 0);
  setPct("pctKpiCicloOk", k.ciclo_em_dia || 0);
  setPct("pctKpiCicloPend", k.ciclo_pendente_vencido || 0);
  setPct("pctKpiDefeito", defCount);

  document.querySelectorAll("#tab-estoque .kpi-card").forEach(el => el.classList.remove("active-filter"));
  const activeCard = document.getElementById("kpi-" + APP_STATE.kpiQuickFilter);
  if (activeCard) activeCard.classList.add("active-filter");
}

function classifyStockSubgroup(it) {
  const stUp = String(it.STATUS || "").toUpperCase();
  const cliUp = String(it.CLIENTE || "").toUpperCase();
  const setUp = String(it.SETOR || "").toUpperCase();
  if (stUp.includes("NOVO") || cliUp.includes("NOVO") || setUp.includes("NOVO")) {
    return "NOVOS";
  }
  if (stUp.includes("BACKUP") || stUp.includes("BACK UP") || cliUp.includes("BACKUP") || stUp.includes("DEVOLVIDO")) {
    return "BACKUP_RETORNO";
  }
  return "USADOS";
}

function applyKpiQuickFilter(code) {
  APP_STATE.kpiQuickFilter = code;
  document.getElementById("selFilterTipo").value = "TODOS";
  document.getElementById("selFilterModalidade").value = "TODAS";
  document.getElementById("selFilterSituacao").value = "TODOS";
  document.getElementById("selFilterCiclo").value = "TODOS";

  if (code === "ATIVO") document.getElementById("selFilterSituacao").value = "ATIVO";
  else if (code === "ESTOQUE") document.getElementById("selFilterSituacao").value = "ESTOQUE";
  else if (code === "ESTOQUE_NOVOS") document.getElementById("selFilterSituacao").value = "ESTOQUE_NOVOS";
  else if (code === "ESTOQUE_USADOS") document.getElementById("selFilterSituacao").value = "ESTOQUE_USADOS";
  else if (code === "ESTOQUE_BACKUP") document.getElementById("selFilterSituacao").value = "ESTOQUE_BACKUP";
  else if (code === "DEFEITO") document.getElementById("selFilterSituacao").value = "DEFEITO";
  else if (code === "COMODATO") document.getElementById("selFilterModalidade").value = "COMODATO";
  else if (code === "VENDA") document.getElementById("selFilterModalidade").value = "VENDA";
  else if (code === "CICLO_OK") document.getElementById("selFilterCiclo").value = "EM_DIA";
  else if (code === "CICLO_PEND") document.getElementById("selFilterCiclo").value = "PENDENTE_OU_VENCIDA";

  renderKpis();
  renderItemsTable();
}

function resetAllFilters() {
  APP_STATE.kpiQuickFilter = "ALL";
  APP_STATE.selectedIndices.clear();
  document.getElementById("inpFilterSearch").value = "";
  document.getElementById("selFilterTipo").value = "TODOS";
  document.getElementById("selFilterModalidade").value = "TODAS";
  document.getElementById("selFilterSituacao").value = "TODOS";
  document.getElementById("selFilterCiclo").value = "TODOS";
  const chkAll = document.getElementById("chkHeaderAll");
  if (chkAll) chkAll.checked = false;
  renderKpis();
  renderItemsTable();
}

function getEstoqueItemSortPriority(it) {
  const st = it._row_state || "ATIVO";
  if (st === "ESTOQUE") {
    const sub = classifyStockSubgroup(it);
    if (sub === "NOVOS") return 1;
    if (sub === "USADOS") return 2;
    return 3;
  }
  const mod = String(it.MODALIDADE || "").toUpperCase();
  if (st === "ATIVO") {
    if (mod === "COMODATO" || mod === "ALUGUEL") return 4;
    return 5;
  }
  return 6; // DEFEITO / MANUTENÇÃO
}

function getFilteredItems() {
  const q = (document.getElementById("inpFilterSearch").value || "").trim().toUpperCase();
  const fTipo = document.getElementById("selFilterTipo").value;
  const fMod = document.getElementById("selFilterModalidade").value;
  const fSit = document.getElementById("selFilterSituacao").value;
  const fCiclo = document.getElementById("selFilterCiclo").value;

  const filtered = APP_STATE.items.filter(it => {
    if (fTipo !== "TODOS" && it.TIPO !== fTipo) return false;
    if (fMod !== "TODAS") {
      if (fMod === "COMODATO") {
        if (!["COMODATO", "ALUGUEL"].includes(it.MODALIDADE)) return false;
      } else if (it.MODALIDADE !== fMod) {
        return false;
      }
    }
    const st = it._row_state || "ATIVO";
    const attEst = String(it.ATUALIZADO_NO_ESTOQUE || "").toUpperCase();
    const stockSub = st === "ESTOQUE" ? classifyStockSubgroup(it) : "";

    if (fSit === "ATIVO" && st !== "ATIVO") return false;
    if (fSit === "ESTOQUE" && st !== "ESTOQUE") return false;
    if (fSit === "ESTOQUE_NOVOS" && (st !== "ESTOQUE" || stockSub !== "NOVOS")) return false;
    if (fSit === "ESTOQUE_USADOS" && (st !== "ESTOQUE" || stockSub !== "USADOS")) return false;
    if (fSit === "ESTOQUE_BACKUP" && (st !== "ESTOQUE" || stockSub !== "BACKUP_RETORNO")) return false;
    if (fSit === "DEFEITO" && st !== "DEFEITO") return false;
    if (fSit === "ESTOQUE_ATUALIZADO" && (st !== "ESTOQUE" || !attEst.includes("SIM"))) return false;
    if (fSit === "ESTOQUE_FALTA" && (st !== "ESTOQUE" || (!attEst.includes("NÃO") && !attEst.includes("FALTA")))) return false;

    const cycCode = (it._cycle && it._cycle.status_code) || "SEM_DATA";
    if (fCiclo === "PENDENTE_OU_VENCIDA" && !["VENCIDA", "VENCENDO", "SEM_DATA"].includes(cycCode)) return false;
    if (fCiclo === "VENCIDA" && cycCode !== "VENCIDA") return false;
    if (fCiclo === "VENCENDO" && cycCode !== "VENCENDO") return false;
    if (fCiclo === "EM_DIA" && cycCode !== "EM_DIA") return false;

    if (q) {
      const hay = [
        it.CODIGO,
        it.SERIAL_ORIGINAL,
        it.TIPO,
        it.CLIENTE,
        it.ENDERECO,
        it.CIDADE,
        it.UF,
        it.SETOR,
        it.MODALIDADE,
        it.STATUS,
        it.OBSERVACOES,
        it.DEFEITO,
        it.ULTIMA_ATUALIZACAO,
        st === "ESTOQUE" ? "ESTOQUE DA LYDA NOVOS USADOS SEDE PORTO ALEGRE" : "",
      ].join(" ").toUpperCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });

  // Ordena para que o Estoque da LYDA (Novos -> Usados -> Backup) apareça no topo
  // tanto na visão geral de Estoque & Mapeamento quanto ao filtrar por Estoque da LYDA!
  return filtered.slice().sort((a, b) => {
    const pa = getEstoqueItemSortPriority(a);
    const pb = getEstoqueItemSortPriority(b);
    if (pa !== pb) return pa - pb;
    return (a._idx || 0) - (b._idx || 0);
  });
}

function getTipoBadgeHtml(tipo) {
  const t = String(tipo || "ANALISADOR").toUpperCase();
  if (t.includes("IMPRESSORA")) return `<span class="badge badge-imp">IMPRESSORA</span>`;
  if (t.includes("SIMULADOR")) return `<span class="badge badge-sim">SIMULADOR</span>`;
  if (t.includes("DOWNLOAD")) return `<span class="badge badge-dwl">DOWNLOADER</span>`;
  return `<span class="badge badge-ana">ANALISADOR</span>`;
}

function getCycleBadgeHtml(cyc) {
  if (!cyc) return `<span class="badge badge-sem-data">PENDENTE (6m)</span>`;
  const code = cyc.status_code;
  const txt = escapeHtml(cyc.summary_table || "PENDENTE");
  if (code === "EM_DIA") return `<span class="badge badge-em-dia">${txt}</span>`;
  if (code === "VENCIDA") return `<span class="badge badge-vencida">${txt}</span>`;
  if (code === "VENCENDO") return `<span class="badge badge-vencendo">${txt}</span>`;
  return `<span class="badge badge-sem-data">${txt}</span>`;
}

function getCycleProgressCellHtml(it) {
  const cyc = it._cycle || {};
  const code = cyc.status_code || "SEM_DATA";
  const pct = typeof cyc.progress_pct === "number" ? cyc.progress_pct : 0;
  let fillColor = "#94A3B8";
  if (code === "EM_DIA") fillColor = "#10B981";
  else if (code === "VENCENDO") fillColor = "#F59E0B";
  else if (code === "VENCIDA") fillColor = "#E11D48";

  const ult = it.ULTIMA_ATUALIZACAO || "-";
  const prox = cyc.next_date_str || "Sem data";
  const subInfo = ult !== "-"
    ? `Últ: ${escapeHtml(ult)} • Próx: ${escapeHtml(prox)}`
    : `Sem data base registrada`;

  return `
    <div class="cycle-progress-wrap">
      <div>${getCycleBadgeHtml(cyc)}</div>
      <div class="cycle-progress-track" title="Progresso do ciclo de 6 meses: ${pct}%">
        <div class="cycle-progress-fill" style="width:${pct}%; background:${fillColor};"></div>
      </div>
      <div class="cell-sub">${subInfo}</div>
    </div>
  `;
}

function getItemRowColorClass(it, checked = false) {
  if (checked) return "row-selected";
  if (it._row_state === "DEFEITO") return "row-defeito";
  if (it._row_state === "ESTOQUE") return "row-estoque";
  const mod = String(it.MODALIDADE || "").toUpperCase();
  if (mod.includes("COMODATO") || mod.includes("ALUGUEL")) return "row-comodato";
  return "row-venda";
}

function renderItemsTable() {
  const tbody = document.getElementById("tbodyItems");
  if (!tbody) return;
  const filtered = getFilteredItems();
  const totalAll = (APP_STATE.items || []).length;

  const lblShowing = document.getElementById("lblEstoqueShowingCount");
  if (lblShowing) {
    lblShowing.innerText = filtered.length === totalAll
      ? `Mostrando todos os ${totalAll} aparelhos:`
      : `Mostrando ${filtered.length} de ${totalAll} aparelhos:`;
  }

  const chkAll = document.getElementById("chkHeaderAll");
  if (chkAll) {
    chkAll.checked = filtered.length > 0 && filtered.every(it => APP_STATE.selectedIndices.has(it._idx));
  }

  const lydaHqAddr = (APP_STATE.config && APP_STATE.config.lyda_hq_address) || "Av. Pernambuco, 2623 - Navegantes, Porto Alegre - RS";

  const rows = filtered.map(it => {
    const idx = it._idx;
    const checked = APP_STATE.selectedIndices.has(idx);
    const rowClass = getItemRowColorClass(it, checked);

    const obsText = [it.DEFEITO ? `[DEFEITO: ${it.DEFEITO}]` : "", it.OBSERVACOES || ""]
      .filter(Boolean)
      .join(" ");

    let cliPrimaryHtml = escapeHtml(it.CLIENTE || "-");
    let cliSubHtml = `Setor: <strong>${escapeHtml(it.SETOR || "-")}</strong>`;
    let addrPrimary = it.ENDERECO || "-";
    let addrSub = `${it.CIDADE || "-"} / ${it.UF || "-"}`;
    let sitText = it.STATUS || "ATIVO NO CLIENTE";
    let sitBadgeClass = "badge-ana";

    if (it._row_state === "DEFEITO") {
      sitBadgeClass = "badge-vencida";
      const cliUp = String(it.CLIENTE || "").toUpperCase();
      if (cliUp.includes("ESTOQUE") || cliUp === "LYDA" || cliUp.includes("LYDA COMERCIO")) {
        cliPrimaryHtml = `<span style="color:#BE123C; font-weight:800;">ESTOQUE DA LYDA (EM MANUTENÇÃO)</span>`;
        cliSubHtml = `Origem: <strong>Sede LYDA — Assistência SP</strong>`;
      }
    } else if (it._row_state === "ESTOQUE") {
      const subGrp = classifyStockSubgroup(it);
      const attEstUp = String(it.ATUALIZADO_NO_ESTOQUE || "").toUpperCase();
      if (subGrp === "NOVOS") {
        cliPrimaryHtml = `<span style="color:#065F46; font-weight:800;">ESTOQUE DA LYDA — NOVOS</span>`;
        cliSubHtml = `Sede LYDA • <strong>Equipamento Novo</strong>`;
        addrPrimary = lydaHqAddr;
        addrSub = "PORTO ALEGRE / RS";
        sitText = attEstUp.includes("SIM") ? "ESTOQUE NOVO (ATUALIZADO)" : "ESTOQUE LYDA — NOVO";
        sitBadgeClass = "badge-em-dia";
      } else if (subGrp === "USADOS") {
        cliPrimaryHtml = `<span style="color:#065F46; font-weight:800;">ESTOQUE DA LYDA — USADOS</span>`;
        cliSubHtml = `Sede LYDA • <strong>Disponível no Estoque</strong>`;
        addrPrimary = lydaHqAddr;
        addrSub = "PORTO ALEGRE / RS";
        sitText = attEstUp.includes("SIM") ? "ESTOQUE USADO (ATUALIZADO)" : "ESTOQUE LYDA — USADO";
        sitBadgeClass = "badge-em-dia";
      } else {
        const stUp = String(it.STATUS || "").toUpperCase();
        if (stUp.includes("DEVOLVIDO")) {
          cliPrimaryHtml = `<span style="color:#065F46; font-weight:800;">DEVOLVIDO AO ESTOQUE LYDA</span>`;
          cliSubHtml = `Ex-Cliente: <strong>${escapeHtml(it.CLIENTE || "-")}</strong>`;
          sitText = "DEVOLVIDO / EMPRÉSTIMO";
          sitBadgeClass = "badge-vencendo";
        } else {
          cliPrimaryHtml = `<span style="color:#065F46; font-weight:800;">ESTOQUE LYDA — EM BACKUP</span>`;
          cliSubHtml = `Alocado em: <strong>${escapeHtml(it.CLIENTE || "-")}</strong>`;
          sitText = "EM BACKUP";
          sitBadgeClass = "badge-vencendo";
        }
      }
    }

    return `
      <tr class="${rowClass}" ondblclick="openItemModal(${idx})">
        <td style="text-align:center;" onclick="event.stopPropagation()">
          <input type="checkbox" ${checked ? "checked" : ""} onchange="toggleItemSelection(${idx}, this.checked)" />
        </td>
        <td>
          <div style="display:flex; align-items:center; gap:6px;">
            ${getTipoBadgeHtml(it.TIPO)}
            <span style="font-family:monospace; font-weight:800; font-size:13px; color:#0F172A;">${escapeHtml(it.CODIGO)}</span>
          </div>
          ${it.KIT_ANALISADOR ? `<div class="cell-sub">Kit: ${escapeHtml(it.KIT_ANALISADOR)}</div>` : ""}
        </td>
        <td style="max-width:250px;">
          <div class="cell-primary" style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${escapeHtml(it.CLIENTE)}">${cliPrimaryHtml}</div>
          <div class="cell-sub">${cliSubHtml}</div>
        </td>
        <td style="max-width:230px;">
          <div style="color:#334155; font-weight:600; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${escapeHtml(addrPrimary)}">${escapeHtml(addrPrimary)}</div>
          <div class="cell-sub">${escapeHtml(addrSub)}</div>
        </td>
        <td>
          <div class="cell-primary">${escapeHtml(it.MODALIDADE || "-")}</div>
          <div style="margin-top:3px;"><span class="badge ${sitBadgeClass}">${escapeHtml(sitText)}</span></div>
        </td>
        <td>${getCycleProgressCellHtml(it)}</td>
        <td style="max-width:190px;">
          <div style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:#475569; font-size:11.5px;" title="${escapeHtml(obsText)}">${escapeHtml(obsText || "-")}</div>
        </td>
        <td style="text-align:right; white-space:nowrap;" onclick="event.stopPropagation()">
          <button class="btn btn-secondary btn-sm" onclick="openItemModal(${idx})"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>Ficha</button>
        </td>
      </tr>
    `;
  });

  tbody.innerHTML = rows.length
    ? rows.join("")
    : `<tr><td colspan="8" style="text-align:center; padding:28px; color:#64748B;">Nenhum aparelho encontrado para o filtro selecionado.</td></tr>`;

  updateSelectedCountBanner();
}

function toggleItemSelection(idx, isChecked) {
  if (isChecked) APP_STATE.selectedIndices.add(idx);
  else APP_STATE.selectedIndices.delete(idx);
  renderItemsTable();
  renderRadar6mTable();
}

function toggleSelectAllVisible(selectAll) {
  const visible = getFilteredItems();
  visible.forEach(it => {
    if (selectAll) APP_STATE.selectedIndices.add(it._idx);
    else APP_STATE.selectedIndices.delete(it._idx);
  });
  const chkAll = document.getElementById("chkHeaderAll");
  if (chkAll) chkAll.checked = selectAll;
  renderItemsTable();
}

function clearAllEstoqueSelection() {
  APP_STATE.selectedIndices.clear();
  const chkAll = document.getElementById("chkHeaderAll");
  if (chkAll) chkAll.checked = false;
  renderItemsTable();
  renderRadar6mTable();
}

function openZebraWithEstoqueSelection() {
  const indices = getSelectedIndicesArray();
  if (!indices.length) {
    showToast("Selecione pelo menos 1 aparelho na tabela para gerar etiquetas.", "error");
    return;
  }
  zebraInitialSelectionApplied = true;
  APP_STATE.zebraSelectedIndices = new Set(indices);
  switchTab("tab-etiquetas");
  renderZebraStudio();
  showToast(`${indices.length} aparelho(s) enviado(s) para o Estúdio de Etiquetas Zebra!`, "success");
}

function updateSelectedCountBanner() {
  const n = APP_STATE.selectedIndices.size;
  const lbl = document.getElementById("lblSelectedCount");
  if (lbl) lbl.innerText = `${n} aparelho(s) selecionado(s)`;
  const bar = document.getElementById("divContextualBatchBar");
  if (bar) {
    bar.classList.toggle("visible", n > 0);
  }
}

// =========================================================================
// ABA 2: RADAR DE ATUALIZAÇÕES SEMESTRAIS (6 EM 6 MESES)
// =========================================================================
function isItemBenchPending(it) {
  if (it._row_state !== "ESTOQUE") return false;
  const att = String(it.ATUALIZADO_NO_ESTOQUE || "").toUpperCase();
  return att.includes("NÃO") || att.includes("FALTA");
}

function isItemNeedingRadarAttention(it) {
  const cycCode = (it._cycle && it._cycle.status_code) || "SEM_DATA";
  if (["VENCENDO", "VENCIDA", "SEM_DATA"].includes(cycCode)) return true;
  if (isItemBenchPending(it)) return true;
  return false;
}

function getRadarFilteredItems() {
  const mode = APP_STATE.radarSubFilter || "ALL_NEED";
  const qEl = document.getElementById("inpSearchRadar");
  const q = ((qEl && qEl.value) || "").trim().toUpperCase();

  const list = (APP_STATE.items || []).filter(it => {
    const cycCode = (it._cycle && it._cycle.status_code) || "SEM_DATA";
    if (mode === "ALL_NEED" && !isItemNeedingRadarAttention(it)) return false;
    if (mode === "VENCENDO" && cycCode !== "VENCENDO") return false;
    if (mode === "VENCIDA" && cycCode !== "VENCIDA") return false;
    if (mode === "BANCADA" && !isItemBenchPending(it)) return false;
    if (mode === "SEM_DATA" && cycCode !== "SEM_DATA") return false;
    if (mode === "EM_DIA" && cycCode !== "EM_DIA") return false;

    if (q) {
      const hay = [
        it.CODIGO,
        it.TIPO,
        it.CLIENTE,
        it.CIDADE,
        it.UF,
        it.ENDERECO,
        it.SETOR,
        it.ULTIMA_ATUALIZACAO,
      ].join(" ").toUpperCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });

  // Ordenar por urgência: VENCIDA primeiro -> VENCENDO (menor dias restantes) -> BANCADA -> SEM_DATA
  const rank = { VENCIDA: 1, VENCENDO: 2, SEM_DATA: 3, EM_DIA: 4 };
  list.sort((a, b) => {
    const ca = (a._cycle && a._cycle.status_code) || "SEM_DATA";
    const cb = (b._cycle && b._cycle.status_code) || "SEM_DATA";
    const ra = rank[ca] || 9;
    const rb = rank[cb] || 9;
    if (ra !== rb) return ra - rb;
    const da = (a._cycle && typeof a._cycle.days_rem === "number") ? a._cycle.days_rem : 9999;
    const db = (b._cycle && typeof b._cycle.days_rem === "number") ? b._cycle.days_rem : 9999;
    return da - db;
  });

  return list;
}

function renderRadar6mTab() {
  const items = APP_STATE.items || [];
  let countAllNeed = 0;
  let countVencendo = 0;
  let countVencida = 0;
  let countBancada = 0;

  items.forEach(it => {
    const cycCode = (it._cycle && it._cycle.status_code) || "SEM_DATA";
    if (isItemNeedingRadarAttention(it)) countAllNeed++;
    if (cycCode === "VENCENDO") countVencendo++;
    if (cycCode === "VENCIDA") countVencida++;
    if (isItemBenchPending(it)) countBancada++;
  });

  const elAll = document.getElementById("valRadarAllNeed");
  if (elAll) elAll.innerText = countAllNeed;
  const elVencendo = document.getElementById("valRadarVencendo");
  if (elVencendo) elVencendo.innerText = countVencendo;
  const elVencida = document.getElementById("valRadarVencida");
  if (elVencida) elVencida.innerText = countVencida;
  const elBancada = document.getElementById("valRadarBancada");
  if (elBancada) elBancada.innerText = countBancada;

  document.querySelectorAll("#tab-radar6m .kpi-card").forEach(el => el.classList.remove("active-filter"));
  const activeCard = document.getElementById("radarCard-" + APP_STATE.radarSubFilter);
  if (activeCard) activeCard.classList.add("active-filter");

  const sel = document.getElementById("selRadarStatusFilter");
  if (sel && sel.value !== APP_STATE.radarSubFilter) {
    sel.value = APP_STATE.radarSubFilter;
  }

  renderRadar6mTable();
}

function setRadarSubFilter(mode) {
  APP_STATE.radarSubFilter = mode || "ALL_NEED";
  renderRadar6mTab();
}

function renderRadar6mTable() {
  const tbody = document.getElementById("tbodyRadar6m");
  if (!tbody) return;

  const list = getRadarFilteredItems();
  const todayStr = new Date().toLocaleDateString("pt-BR");

  tbody.innerHTML = list.length
    ? list.map(it => {
        const idx = it._idx;
        const checked = APP_STATE.selectedIndices.has(idx);
        const curDate = it.ULTIMA_ATUALIZACAO || "";
        const rowClass = getItemRowColorClass(it, checked);

        return `
          <tr class="${rowClass}">
            <td style="text-align:center;">
              <input type="checkbox" ${checked ? "checked" : ""} onchange="toggleItemSelection(${idx}, this.checked)" />
            </td>
            <td>
              <div style="display:flex; align-items:center; gap:6px;">
                ${getTipoBadgeHtml(it.TIPO)}
                <span style="font-family:monospace; font-weight:800; font-size:13px;">${escapeHtml(it.CODIGO)}</span>
              </div>
              <div class="cell-sub">${escapeHtml(it.MODALIDADE || "-")} • ${escapeHtml(it.STATUS || "-")}</div>
            </td>
            <td>
              <div class="cell-primary">${escapeHtml(it.CLIENTE || "-")}</div>
              <div class="cell-sub">${escapeHtml(it.CIDADE || "-")} / ${escapeHtml(it.UF || "-")} • Setor: ${escapeHtml(it.SETOR || "-")}</div>
            </td>
            <td style="max-width:230px;">
              <div style="font-size:12px; color:#334155; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${escapeHtml(it.ENDERECO)}">${escapeHtml(it.ENDERECO || "-")}</div>
              <div class="cell-sub">CEP: ${escapeHtml(it.CEP || "-")}</div>
            </td>
            <td>${getCycleProgressCellHtml(it)}</td>
            <td>
              <div style="display:flex; align-items:center; gap:6px;">
                <input
                  type="text"
                  id="inpRadarDate_${idx}"
                  class="date-input-br"
                  data-datepicker="br"
                  autocomplete="off"
                  value="${escapeHtml(curDate)}"
                  placeholder="DD/MM/AAAA"
                  style="width:126px; height:32px; font-weight:700;"
                />
                <button class="btn btn-secondary btn-sm" onclick="quickSaveItemUpdateDate(${idx}, document.getElementById('inpRadarDate_${idx}').value)">Salvar Data</button>
              </div>
            </td>
            <td style="text-align:right; white-space:nowrap;">
              <button class="btn btn-success btn-sm" onclick="quickSaveItemUpdateDate(${idx}, '${todayStr}')" title="Marcar atualizado hoje e projetar +6 meses">Hoje (+6m)</button>
              <button class="btn btn-secondary btn-sm" onclick="openItemModal(${idx})"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>Ficha</button>
            </td>
          </tr>
        `;
      }).join("")
    : `<tr><td colspan="7" style="text-align:center; padding:28px; color:#64748B;">Nenhum aparelho encontrado neste filtro de atualização semestral.</td></tr>`;
}

async function quickSaveItemUpdateDate(idx, newDateStr) {
  const cleanDate = (newDateStr || "").trim();
  if (!cleanDate) {
    showToast("Informe uma data válida no formato DD/MM/AAAA.", "error");
    return;
  }
  const it = (APP_STATE.items || []).find(x => x._idx === idx);
  if (!it) return;

  const loggedName = (APP_STATE.current_user && APP_STATE.current_user.nome) || APP_STATE.config.operador_atual || "OPERADOR";
  const isEstoque = it._row_state === "ESTOQUE";

  const payload = {
    original_idx: idx,
    responsavel: loggedName,
    propagate_address: false,
    item: {
      TIPO: it.TIPO,
      CODIGO: it.CODIGO,
      MODALIDADE: it.MODALIDADE,
      STATUS: it.STATUS,
      CLIENTE: it.CLIENTE,
      SETOR: it.SETOR,
      ULTIMA_ATUALIZACAO: cleanDate,
      VERSAO_CLEW: it.VERSAO_CLEW || "",
      ATUALIZADO_NO_ESTOQUE: isEstoque ? "SIM - JÁ ATUALIZADO NO ESTOQUE" : (it.ATUALIZADO_NO_ESTOQUE || "EM USO NO CLIENTE / N/A"),
      ENDERECO: it.ENDERECO || "",
      CEP: it.CEP || "",
      CIDADE: it.CIDADE || "PORTO ALEGRE",
      UF: it.UF || "RS",
      CONDICAO: it.CONDICAO || "PERFEITO / FUNCIONANDO 100%",
      DEFEITO: it.DEFEITO || "",
      CONTATO_LOCAL: it.CONTATO_LOCAL || "",
      KIT_ANALISADOR: it.KIT_ANALISADOR || "",
      OBSERVACOES: it.OBSERVACOES || "",
    },
  };

  try {
    const res = await fetch("/api/item/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!data.ok) {
      showToast(data.error || "Erro ao atualizar data.", "error");
      return;
    }
    showToast(`Aparelho ${it.CODIGO} atualizado para ${cleanDate} (+6 meses calculado)!`, "success");
    await loadBootstrapData(true);
  } catch (e) {
    showToast("Erro ao salvar data de atualização.", "error");
  }
}

function selectAllRadarVisible(selectAll) {
  const list = getRadarFilteredItems();
  list.forEach(it => {
    if (selectAll) APP_STATE.selectedIndices.add(it._idx);
    else APP_STATE.selectedIndices.delete(it._idx);
  });
  const chk = document.getElementById("chkRadarAll");
  if (chk) chk.checked = selectAll;
  renderRadar6mTable();
  renderItemsTable();
}

function createRouteFromRadarItems() {
  const visible = getRadarFilteredItems();
  const selectedInRadar = visible.filter(it => APP_STATE.selectedIndices.has(it._idx));
  const targetItems = selectedInRadar.length > 0 ? selectedInRadar : visible;

  if (!targetItems.length) {
    showToast("Nenhum aparelho listado para gerar rota.", "error");
    return;
  }

  APP_STATE.selectedIndices.clear();
  targetItems.forEach(it => APP_STATE.selectedIndices.add(it._idx));
  switchTab("tab-rota");
  loadRouteFromMode("FROM_INDICES");
}

// =========================================================================
// LEITOR DE CÓDIGO DE BARRAS USB GLOBAL
// =========================================================================
async function handleQuickScanInput() {
  const inp = document.getElementById("inpQuickScan");
  const code = (inp.value || "").trim();
  if (!code) return;
  inp.value = "";
  await processScannedBarcode(code);
}

async function processScannedBarcode(code) {
  if (!APP_STATE.authenticated) return;
  try {
    const res = await fetch(`/api/scan?code=${encodeURIComponent(code)}`);
    const data = await res.json();
    if (!data.ok) {
      showToast(data.error || "Erro ao buscar código", "error");
      return;
    }
    const matches = data.matches || [];
    if (matches.length >= 1) {
      showToast(`Aparelho localizado: ${matches[0].TIPO} [${matches[0].CODIGO}]`, "success");
      openItemModal(matches[0]._idx);
    } else {
      showToast(`Serial ${data.cleaned_code} não encontrado. Abrindo cadastro!`, "info");
      openItemModal(null, data.cleaned_code);
    }
  } catch (e) {
    showToast("Erro ao consultar serial bipado.", "error");
  }
}

let usbScanBuffer = "";
let usbScanLastTime = 0;
window.addEventListener("keydown", e => {
  if (e.key === "Escape") {
    if (APP_STATE.current_user && APP_STATE.current_user.must_change_password) {
      return;
    }
    const dp = document.getElementById("lydaDatePickerPopover");
    if (dp && dp.classList.contains("open")) {
      closeLydaDatePicker();
      return;
    }
    closeItemModal();
    closeBatchModal();
    closeProfileModal();
    return;
  }
  if (!APP_STATE.authenticated) return;
  const tag = (document.activeElement && document.activeElement.tagName) || "";
  if (["INPUT", "TEXTAREA", "SELECT"].includes(tag)) return;

  const now = Date.now();
  if (now - usbScanLastTime > 120) {
    usbScanBuffer = "";
  }
  usbScanLastTime = now;

  if (e.key === "Enter" && usbScanBuffer.length >= 4) {
    const scanned = usbScanBuffer;
    usbScanBuffer = "";
    processScannedBarcode(scanned);
  } else if (e.key.length === 1) {
    usbScanBuffer += e.key;
  }
});

// =========================================================================
// MEGA MODAL DO APARELHO i-STAT
// =========================================================================
async function openItemModal(idx, prefillSerial = "") {
  const backdrop = document.getElementById("itemModalBackdrop");
  document.getElementById("hidModalIdx").value = idx != null ? String(idx) : "";
  const loggedName = (APP_STATE.current_user && APP_STATE.current_user.nome) || APP_STATE.config.operador_atual || "";

  if (idx == null) {
    document.getElementById("lblModalTitle").innerText = "Novo Cadastro de Aparelho i-STAT";
    document.getElementById("lblModalSubtitle").innerText = "Preencha os dados do equipamento para cadastrar no estoque";
    document.getElementById("selModalTipo").value = "ANALISADOR";
    document.getElementById("inpModalCodigo").value = prefillSerial || "";
    document.getElementById("selModalModalidade").value = "PROPRIEDADE LYDA";
    document.getElementById("selModalStatus").value = "ESTOQUE USADOS";
    document.getElementById("inpModalCliente").value = "SEM CLIENTE (ESTOQUE LYDA)";
    document.getElementById("inpModalSetor").value = "ESTOQUE LYDA";
    document.getElementById("selModalOperador").value = loggedName;
    document.getElementById("inpModalUltAtt").value = new Date().toLocaleDateString("pt-BR");
    document.getElementById("inpModalVersaoClew").value = "";
    document.getElementById("selModalAttEstoque").value = "SIM - JÁ ATUALIZADO NO ESTOQUE";
    document.getElementById("inpModalEndereco").value = APP_STATE.config.lyda_hq_address || "";
    document.getElementById("inpModalCep").value = "91130-470";
    document.getElementById("inpModalCidade").value = "PORTO ALEGRE";
    document.getElementById("inpModalUf").value = "RS";
    document.getElementById("selModalCondicao").value = "PERFEITO / FUNCIONANDO 100%";
    document.getElementById("inpModalDefeito").value = "";
    document.getElementById("inpModalContato").value = "";
    document.getElementById("inpModalKit").value = "";
    document.getElementById("txtModalObservacoes").value = "";
    document.getElementById("tbodyModalHistory").innerHTML =
      `<tr><td colspan="5" style="text-align:center; color:#64748B;">Novo equipamento (sem histórico anterior).</td></tr>`;
    document.getElementById("lblModalCompanions").innerText = "";
    updateModalNextDatePreview();
    renderModalSingleLabelPreview();
    backdrop.classList.add("open");
    return;
  }

  try {
    const res = await fetch(`/api/item/${idx}/details`);
    const data = await res.json();
    if (!data.ok) return;
    const it = data.item;

    document.getElementById("lblModalTitle").innerText =
      `Ficha do Aparelho i-STAT — ${it.TIPO} [SN: ${it.CODIGO}]`;
    document.getElementById("lblModalSubtitle").innerText =
      `Local: ${it.CLIENTE} | Modalidade: ${it.MODALIDADE} | Status: ${it.STATUS}`;

    document.getElementById("selModalTipo").value = it.TIPO || "ANALISADOR";
    document.getElementById("inpModalCodigo").value = it.CODIGO || "";
    document.getElementById("selModalModalidade").value = it.MODALIDADE || "COMODATO";
    document.getElementById("selModalStatus").value = it.STATUS || "ATIVO NO CLIENTE";
    document.getElementById("inpModalCliente").value = it.CLIENTE || "";
    document.getElementById("inpModalSetor").value = it.SETOR || "";
    document.getElementById("selModalOperador").value = loggedName;
    document.getElementById("inpModalUltAtt").value = it.ULTIMA_ATUALIZACAO || "";
    document.getElementById("inpModalVersaoClew").value = it.VERSAO_CLEW || "";
    document.getElementById("selModalAttEstoque").value =
      it.ATUALIZADO_NO_ESTOQUE || "EM USO NO CLIENTE / N/A";
    document.getElementById("inpModalEndereco").value = it.ENDERECO || "";
    document.getElementById("inpModalCep").value = it.CEP || "";
    document.getElementById("inpModalCidade").value = it.CIDADE || "PORTO ALEGRE";
    document.getElementById("inpModalUf").value = it.UF || "RS";
    document.getElementById("selModalCondicao").value = it.CONDICAO || "PERFEITO / FUNCIONANDO 100%";
    document.getElementById("inpModalDefeito").value = it.DEFEITO || "";
    document.getElementById("inpModalContato").value = it.CONTATO_LOCAL || "";
    document.getElementById("inpModalKit").value = it.KIT_ANALISADOR || "";
    document.getElementById("txtModalObservacoes").value = it.OBSERVACOES || "";

    updateModalNextDatePreview();
    renderModalSingleLabelPreview();

    const hist = data.history || [];
    document.getElementById("tbodyModalHistory").innerHTML = hist.length
      ? hist.map(h => `
          <tr>
            <td style="white-space:nowrap;">${escapeHtml(h.DATA_HORA)}</td>
            <td><strong>${escapeHtml(h.ACAO)}</strong></td>
            <td>${escapeHtml(h.CLIENTE || "-")}</td>
            <td>${escapeHtml(h.OPERADOR || h.RESPONSAVEL || "-")}</td>
            <td>${escapeHtml(h.DETALHES || "-")}</td>
          </tr>
        `).join("")
      : `<tr><td colspan="5" style="text-align:center; color:#64748B;">Nenhuma movimentação registrada ainda para este serial.</td></tr>`;

    const comps = data.companions || [];
    document.getElementById("lblModalCompanions").innerText = comps.length
      ? `Mesmo Kit: ` + comps.map(c => `${c.TIPO} (${c.CODIGO})`).join(", ")
      : "";

    backdrop.classList.add("open");
  } catch (e) {
    showToast("Erro ao carregar detalhes do aparelho.", "error");
  }
}

function closeItemModal() {
  document.getElementById("itemModalBackdrop").classList.remove("open");
}

function getModalCurrentItemObject() {
  return {
    TIPO: (document.getElementById("selModalTipo") && document.getElementById("selModalTipo").value) || "ANALISADOR",
    CODIGO: ((document.getElementById("inpModalCodigo") && document.getElementById("inpModalCodigo").value) || "").trim() || "000000",
    CLIENTE: ((document.getElementById("inpModalCliente") && document.getElementById("inpModalCliente").value) || "").trim() || "SEM CLIENTE (ESTOQUE LYDA)",
    SETOR: ((document.getElementById("inpModalSetor") && document.getElementById("inpModalSetor").value) || "").trim(),
    MODALIDADE: (document.getElementById("selModalModalidade") && document.getElementById("selModalModalidade").value) || "COMODATO",
    STATUS: (document.getElementById("selModalStatus") && document.getElementById("selModalStatus").value) || "ATIVO NO CLIENTE",
  };
}

function renderModalSingleLabelPreview() {
  const holder = document.getElementById("divModalSingleLabelPreview");
  if (!holder) return;

  const rec = getModalCurrentItemObject();
  const cfg = typeof collectZebraConfigPayload === "function" ? collectZebraConfigPayload() : {
    show_logo: true,
    header_text: "i-STAT",
    draw_border: true,
    show_equipamento: true,
    show_serial_line: true,
    barcode_type: "CODE128",
  };
  const showLocChk = document.getElementById("chkModalLabelShowLoc");
  const showLoc = showLocChk ? showLocChk.checked : true;

  let headerHtml = "";
  if (cfg.show_logo && APP_STATE.logo_data_uri) {
    headerHtml = `
      <div class="z-mini-header">
        <img src="${APP_STATE.logo_data_uri}" alt="LYDA" class="z-mini-logo" />
        <span class="z-mini-hdr-txt">${escapeHtml(cfg.header_text || "i-STAT")}</span>
      </div>
    `;
  } else {
    headerHtml = `
      <div class="z-mini-header" style="justify-content:center;">
        <span class="z-mini-hdr-txt">LYDA • ${escapeHtml(cfg.header_text || "i-STAT")}</span>
      </div>
    `;
  }

  const upperCli = String(rec.CLIENTE || "").toUpperCase();
  const upperSt = String(rec.STATUS || "").toUpperCase();
  const isStock = !upperCli || upperCli.includes("SEM CLIENTE") || upperCli.includes("ESTOQUE") || upperSt.includes("ESTOQUE") || upperCli === "LYDA";
  const cliStr = isStock ? "ESTOQUE LYDA" : rec.CLIENTE;

  const fieldLines = [
    `<div class="z-mini-line">EQ: ${escapeHtml(rec.TIPO || "ANALISADOR")}</div>`,
    `<div class="z-mini-line">SN: ${escapeHtml(rec.CODIGO || "")}</div>`,
  ];
  if (showLoc) {
    fieldLines.push(`<div class="z-mini-line client-line">${escapeHtml(cliStr)}</div>`);
  }

  const codeVisual = cfg.barcode_type === "QRCODE" && typeof generateQrSvgHtml === "function"
    ? generateQrSvgHtml(rec.CODIGO, 26)
    : (typeof generateBarcodeSvgHtml === "function" ? generateBarcodeSvgHtml(rec.CODIGO, 19) : "");

  holder.innerHTML = `
    <div class="zebra-mini-slot with-border">
      ${headerHtml}
      <div class="z-mini-fields">
        ${fieldLines.join("")}
      </div>
      <div class="z-mini-barcode-wrap">
        ${codeVisual}
        <div class="z-mini-barcode-num">${escapeHtml(rec.CODIGO)}</div>
      </div>
    </div>
  `;

  const cardTitle = document.getElementById("lblModalLabelCardTitle");
  if (cardTitle) {
    cardTitle.innerText = `Etiqueta Térmica — ${rec.TIPO} [SN: ${rec.CODIGO}]`;
  }

  const btnPrnTxt = document.getElementById("lblModalBtnDownloadPrn");
  if (btnPrnTxt) {
    btnPrnTxt.innerText = `Baixar Etiqueta .PRN (${rec.CODIGO})`;
  }
}

async function downloadModalItemPrnFile(ext = "prn") {
  const rec = getModalCurrentItemObject();
  if (!rec.CODIGO || rec.CODIGO === "000000") {
    showToast("Informe o Serial / Código de Barras do aparelho primeiro.", "error");
    return;
  }

  const cfg = typeof collectZebraConfigPayload === "function" ? collectZebraConfigPayload() : {};
  const showLocChk = document.getElementById("chkModalLabelShowLoc");
  const copiesEl = document.getElementById("inpModalLabelCopies");
  cfg.show_location = showLocChk ? showLocChk.checked : true;
  cfg.copies_per_item = Math.max(1, Math.min(20, parseInt((copiesEl && copiesEl.value) || "1", 10) || 1));
  cfg.single_item = rec;
  cfg.only_preview_zpl = true;
  cfg.is_prn_download = true;

  try {
    const res = await fetch("/api/zebra/print", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cfg),
    });
    const data = await res.json();
    if (!data.ok || !data.zpl) {
      showToast(data.error || "Erro ao gerar o arquivo .PRN deste aparelho.", "error");
      return;
    }

    const cleanExt = (ext || "prn").toLowerCase().replace(/^\./, "");
    const baseName = (data.filename || `etiqueta_lyda_${rec.TIPO}_${rec.CODIGO}.prn`).replace(/\.(prn|zpl|txt)$/i, "");
    const finalFilename = `${baseName}.${cleanExt}`;

    const blob = new Blob([data.zpl], { type: "application/octet-stream;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = finalFilename;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    }, 200);

    showToast(`Etiqueta ${finalFilename} baixada com sucesso!`, "success");
  } catch (e) {
    showToast("Erro ao baixar arquivo .PRN da etiqueta.", "error");
  }
}

async function printModalItemDirectly() {
  const rec = getModalCurrentItemObject();
  if (!rec.CODIGO || rec.CODIGO === "000000") {
    showToast("Informe o Serial / Código de Barras do aparelho primeiro.", "error");
    return;
  }

  const cfg = typeof collectZebraConfigPayload === "function" ? collectZebraConfigPayload() : {};
  const showLocChk = document.getElementById("chkModalLabelShowLoc");
  const copiesEl = document.getElementById("inpModalLabelCopies");
  cfg.show_location = showLocChk ? showLocChk.checked : true;
  cfg.copies_per_item = Math.max(1, Math.min(20, parseInt((copiesEl && copiesEl.value) || "1", 10) || 1));
  cfg.single_item = rec;

  try {
    const res = await fetch("/api/zebra/print", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cfg),
    });
    const data = await res.json();
    if (data.ok) {
      showToast(data.message || `Etiqueta ${rec.CODIGO} enviada para a Zebra ZD230!`, "success");
    } else {
      showToast(data.message || data.error || "Verifique a impressora Zebra ZD230 conectada.", "error");
    }
  } catch (e) {
    showToast("Erro ao enviar etiqueta para a Zebra ZD230.", "error");
  }
}

function printModalItemInBrowser() {
  const rec = getModalCurrentItemObject();
  const copiesEl = document.getElementById("inpModalLabelCopies");
  const copies = Math.max(1, Math.min(20, parseInt((copiesEl && copiesEl.value) || "1", 10) || 1));
  const showLocChk = document.getElementById("chkModalLabelShowLoc");
  const showLoc = showLocChk ? showLocChk.checked : true;

  const logoHtml = APP_STATE.logo_data_uri
    ? `<img src="${APP_STATE.logo_data_uri}" style="height:5mm; max-width:65%; object-fit:contain; filter:contrast(1.3) grayscale(1);" />`
    : `<span>LYDA</span>`;
  const cliLine = showLoc
    ? `<div class="line cli">${escapeHtml((rec.CLIENTE && !rec.CLIENTE.includes("SEM CLIENTE")) ? rec.CLIENTE : "ESTOQUE LYDA")}</div>`
    : "";

  const cells = [];
  for (let i = 0; i < copies; i++) {
    cells.push(`
      <div class="lbl-box">
        <div class="top">${logoHtml}<span>i-STAT</span></div>
        <div class="fields">
          <div class="line">EQ: ${escapeHtml(rec.TIPO || "ANALISADOR")}</div>
          <div class="line">SN: ${escapeHtml(rec.CODIGO)}</div>
          ${cliLine}
        </div>
        <div class="bars">${generateBarcodeSvgHtml(rec.CODIGO, 22)}</div>
        <div class="sn-num">${escapeHtml(rec.CODIGO)}</div>
      </div>
    `);
  }

  const html = `
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
      <meta charset="UTF-8" />
      <title>Etiqueta ${escapeHtml(rec.CODIGO)} — LYDA</title>
      <style>
        @page { size: 46mm 27.2mm; margin: 0; }
        body { font-family: Arial, Helvetica, sans-serif; margin: 0; color: #000; background: #F1F5F9; }
        .no-print { background: #0F172A; color: #FFF; padding: 10px 16px; margin-bottom: 14px; display: flex; justify-content: space-between; align-items: center; }
        .no-print button { background: #2563EB; color: #FFF; border: none; padding: 8px 16px; border-radius: 6px; font-weight: 700; cursor: pointer; }
        .lbl-box { width: 46mm; height: 27.2mm; padding: 1.4mm 1.8mm 1.6mm 1.8mm; box-sizing: border-box; display: flex; flex-direction: column; justify-content: space-between; overflow: hidden; background: #FFF; border: 1.5px solid #000; border-radius: 1mm; margin: 0 auto 4mm auto; page-break-after: always; }
        .top { width: 100%; display: flex; align-items: center; justify-content: space-between; font-size: 7.2pt; font-weight: 900; border-bottom: 1px solid #000; padding-bottom: 0.6mm; margin-bottom: 0.6mm; }
        .fields { width: 100%; text-align: left; }
        .line { font-size: 6.8pt; font-weight: 800; line-height: 1.15; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .line.cli { font-size: 5.8pt; font-weight: 700; }
        .bars { width: 100%; display: flex; justify-content: center; margin-top: auto; }
        .sn-num { font-family: monospace; font-size: 7pt; font-weight: 900; text-align: center; letter-spacing: 0.5px; padding-bottom: 0.4mm; }
        @media print { body { background: #FFF; } .no-print { display: none !important; } .lbl-box { margin: 0; } }
      </style>
    </head>
    <body>
      <div class="no-print">
        <span><strong>Etiqueta ${escapeHtml(rec.CODIGO)} (${copies} cópia(s))</strong></span>
        <div style="display:flex; gap:8px;">
          <button onclick="window.print()">Imprimir / Salvar PDF</button>
          <button style="background:#475569;" onclick="window.close()">Fechar</button>
        </div>
      </div>
      ${cells.join("")}
    </body>
    </html>
  `;
  const win = window.open("", "_blank");
  if (win) {
    win.document.open();
    win.document.write(html);
    win.document.close();
  }
}

function openModalItemInZebraStudio() {
  const idxRaw = document.getElementById("hidModalIdx").value;
  closeItemModal();
  zebraInitialSelectionApplied = true;
  APP_STATE.zebraSelectedIndices.clear();
  if (idxRaw !== "") {
    APP_STATE.zebraSelectedIndices.add(parseInt(idxRaw, 10));
  }
  switchTab("tab-etiquetas");
  renderZebraStudio();
}

function applyModalPreset(preset) {
  const today = new Date().toLocaleDateString("pt-BR");
  if (preset === "ENVIAR_CLIENTE") {
    document.getElementById("selModalStatus").value = "ATIVO NO CLIENTE";
    document.getElementById("selModalAttEstoque").value = "EM USO NO CLIENTE / N/A";
    const modSel = document.getElementById("selModalModalidade");
    if (modSel && modSel.value === "PROPRIEDADE LYDA") {
      modSel.value = "COMODATO";
    }
    const cliInp = document.getElementById("inpModalCliente");
    if (cliInp.value.includes("SEM CLIENTE") || cliInp.value.includes("ESTOQUE")) {
      cliInp.value = "";
      cliInp.focus();
    }
    showToast("Modo: Enviar p/ Hospital/Cliente. Escolha o Hospital e confira a Modalidade (Comodato ou Venda).", "info");
  } else if (preset === "ESTOQUE_ATUALIZADO") {
    setModalClientToStock();
    document.getElementById("selModalStatus").value = "ESTOQUE USADOS";
    document.getElementById("selModalAttEstoque").value = "SIM - JÁ ATUALIZADO NO ESTOQUE";
    document.getElementById("inpModalUltAtt").value = today;
    updateModalNextDatePreview();
    showToast("Marcado como: Voltou p/ Estoque da LYDA (JÁ ATUALIZADO hoje)!", "success");
  } else if (preset === "ESTOQUE_FALTA") {
    setModalClientToStock();
    document.getElementById("selModalStatus").value = "ESTOQUE USADOS";
    document.getElementById("selModalAttEstoque").value = "NÃO - FALTA ATUALIZAR NA BANCADA";
    showToast("Marcado como: Voltou p/ Estoque da LYDA (FALTA ATUALIZAR na bancada).", "info");
  } else if (preset === "DEFEITO") {
    document.getElementById("selModalStatus").value = "COM DEFEITO / AGUARDANDO REPARO";
    document.getElementById("selModalCondicao").value = "COM DEFEITO (VER OBSERVAÇÕES)";
    document.getElementById("inpModalDefeito").focus();
    showToast("Modo Defeito/Manutenção selecionado. Descreva o defeito apresentado.", "info");
  }
  renderModalSingleLabelPreview();
}

function onModalStatusChange(newStatus) {
  const stUp = String(newStatus || "").toUpperCase();
  if (stUp.includes("ESTOQUE")) {
    setModalClientToStock();
    const setInp = document.getElementById("inpModalSetor");
    if (setInp) {
      setInp.value = stUp.includes("NOVOS") ? "ESTOQUE LYDA (NOVOS)" : "ESTOQUE LYDA";
    }
    const attEstSel = document.getElementById("selModalAttEstoque");
    if (attEstSel && attEstSel.value.includes("N/A")) {
      attEstSel.value = "SIM - JÁ ATUALIZADO NO ESTOQUE";
    }
  }
  renderModalSingleLabelPreview();
}

function setModalClientToStock() {
  const cliInp = document.getElementById("inpModalCliente");
  if (cliInp) cliInp.value = "SEM CLIENTE (ESTOQUE LYDA)";
  const setInp = document.getElementById("inpModalSetor");
  if (setInp) setInp.value = "ESTOQUE LYDA";
  const modSel = document.getElementById("selModalModalidade");
  if (modSel) modSel.value = "PROPRIEDADE LYDA";
  const endInp = document.getElementById("inpModalEndereco");
  if (endInp) endInp.value = APP_STATE.config.lyda_hq_address || "Av. Pernambuco, 2623 - Navegantes, Porto Alegre - RS";
  const cepInp = document.getElementById("inpModalCep");
  if (cepInp) cepInp.value = "91130-470";
  const cidInp = document.getElementById("inpModalCidade");
  if (cidInp) cidInp.value = "PORTO ALEGRE";
  const ufInp = document.getElementById("inpModalUf");
  if (ufInp) ufInp.value = "RS";
  renderModalSingleLabelPreview();
}

async function onModalClientChange(clientName) {
  if (!clientName) return;
  const upperName = String(clientName).toUpperCase();
  if (!upperName.includes("SEM CLIENTE") && !upperName.includes("ESTOQUE LYDA")) {
    const modSel = document.getElementById("selModalModalidade");
    if (modSel && modSel.value === "PROPRIEDADE LYDA") {
      const cliRec = (APP_STATE.clients || []).find(c => (c.CLIENTE || "").toUpperCase() === upperName);
      if (cliRec && (cliRec._venda_count || 0) > 0 && (cliRec._comodato_count || 0) === 0) {
        modSel.value = "VENDA";
      } else {
        modSel.value = "COMODATO";
      }
    }
  }
  try {
    const res = await fetch(`/api/client/address_info?cliente=${encodeURIComponent(clientName)}`);
    const data = await res.json();
    if (data.ok && data.address_info) {
      const info = data.address_info;
      if (info.ENDERECO) document.getElementById("inpModalEndereco").value = info.ENDERECO;
      if (info.CEP) document.getElementById("inpModalCep").value = info.CEP;
      if (info.CIDADE) document.getElementById("inpModalCidade").value = info.CIDADE;
      if (info.UF) document.getElementById("inpModalUf").value = info.UF;
      if (info.CONTATO_LOCAL) document.getElementById("inpModalContato").value = info.CONTATO_LOCAL;
    }
  } catch (e) {}
}

function setModalUpdateDateToday() {
  document.getElementById("inpModalUltAtt").value = new Date().toLocaleDateString("pt-BR");
  updateModalNextDatePreview();
}

function updateModalNextDatePreview() {
  const raw = (document.getElementById("inpModalUltAtt").value || "").trim();
  const proxInp = document.getElementById("inpModalProxAtt");
  const badge = document.getElementById("badgeModalCycle");
  const m = raw.match(/(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{2,4})/);
  if (!m) {
    proxInp.value = "PENDENTE (6m)";
    badge.className = "badge badge-sem-data";
    badge.innerText = "Ciclo 6m: PENDENTE";
    return;
  }
  let d = parseInt(m[1], 10);
  let mo = parseInt(m[2], 10);
  let y = parseInt(m[3], 10);
  if (y < 100) y += 2000;
  const dt = new Date(y, mo - 1 + 6, d);
  const nextStr = dt.toLocaleDateString("pt-BR");
  const diffDays = Math.ceil((dt - new Date()) / (1000 * 60 * 60 * 24));
  if (diffDays < 0) {
    proxInp.value = `VENCIDA (${nextStr})`;
    badge.className = "badge badge-vencida";
    badge.innerText = `Ciclo 6m: VENCIDA (${nextStr})`;
  } else {
    proxInp.value = `EM DIA (Próx: ${nextStr})`;
    badge.className = "badge badge-em-dia";
    badge.innerText = `Ciclo 6m: EM DIA (${nextStr})`;
  }
}

async function saveItemFromModal(openRomaneioAfter = false, printZebraAfter = false, downloadPrnAfter = false) {
  const idxRaw = document.getElementById("hidModalIdx").value;
  const original_idx = idxRaw !== "" ? parseInt(idxRaw, 10) : null;

  const stUp = (document.getElementById("selModalStatus").value || "").toUpperCase();
  const cliInpVal = document.getElementById("inpModalCliente").value.trim();
  const isStock = stUp.includes("ESTOQUE") || cliInpVal.toUpperCase().includes("SEM CLIENTE") || cliInpVal.toUpperCase().includes("ESTOQUE");

  const itemPayload = {
    TIPO: document.getElementById("selModalTipo").value,
    CODIGO: document.getElementById("inpModalCodigo").value.trim(),
    MODALIDADE: isStock ? "PROPRIEDADE LYDA" : document.getElementById("selModalModalidade").value,
    STATUS: document.getElementById("selModalStatus").value,
    CLIENTE: isStock ? "SEM CLIENTE (ESTOQUE LYDA)" : cliInpVal,
    SETOR: isStock && (!document.getElementById("inpModalSetor").value.trim() || ["USADO", "NOVO", "ESTOQUE"].includes(document.getElementById("inpModalSetor").value.trim().toUpperCase()))
      ? (stUp.includes("NOVOS") ? "ESTOQUE LYDA (NOVOS)" : "ESTOQUE LYDA")
      : document.getElementById("inpModalSetor").value.trim(),
    ULTIMA_ATUALIZACAO: document.getElementById("inpModalUltAtt").value.trim(),
    VERSAO_CLEW: document.getElementById("inpModalVersaoClew").value.trim(),
    ATUALIZADO_NO_ESTOQUE: document.getElementById("selModalAttEstoque").value,
    ENDERECO: isStock ? (APP_STATE.config.lyda_hq_address || "Av. Pernambuco, 2623 - Navegantes, Porto Alegre - RS") : document.getElementById("inpModalEndereco").value.trim(),
    CEP: isStock ? "91130-470" : document.getElementById("inpModalCep").value.trim(),
    CIDADE: isStock ? "PORTO ALEGRE" : document.getElementById("inpModalCidade").value.trim(),
    UF: isStock ? "RS" : document.getElementById("inpModalUf").value.trim(),
    CONDICAO: document.getElementById("selModalCondicao").value,
    DEFEITO: document.getElementById("inpModalDefeito").value.trim(),
    CONTATO_LOCAL: document.getElementById("inpModalContato").value.trim(),
    KIT_ANALISADOR: document.getElementById("inpModalKit").value.trim(),
    OBSERVACOES: document.getElementById("txtModalObservacoes").value.trim(),
  };

  const responsavel = document.getElementById("selModalOperador").value;

  try {
    const res = await fetch("/api/item/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        item: itemPayload,
        original_idx: original_idx,
        responsavel: responsavel,
        propagate_address: true,
      }),
    });
    const data = await res.json();
    if (!data.ok) {
      showToast(data.error || "Erro ao salvar aparelho.", "error");
      return;
    }
    showToast(data.message, "success");
    if (downloadPrnAfter) {
      await downloadModalItemPrnFile("prn");
    }
    closeItemModal();
    await loadBootstrapData(true);

    if (typeof renderZebraItemsChecklist === "function") renderZebraItemsChecklist();
    if (typeof renderZebraVisualPreview === "function") renderZebraVisualPreview();

    const savedIdx = data.item._idx;
    if (openRomaneioAfter) {
      await openRomaneioWindow([savedIdx]);
    }
    if (printZebraAfter) {
      await printZebraIndices([savedIdx]);
    }
  } catch (e) {
    showToast("Erro de comunicação ao salvar aparelho.", "error");
  }
}

// =========================================================================
// OPERAÇÕES EM LOTE (MULTI-SELEÇÃO)
// =========================================================================
function getSelectedIndicesArray() {
  return Array.from(APP_STATE.selectedIndices);
}

function openBatchModal(mode) {
  const indices = getSelectedIndicesArray();
  if (!indices.length) {
    showToast("Marque pelo menos 1 aparelho na coluna de seleção da tabela primeiro.", "error");
    return;
  }
  APP_STATE.batchMode = mode;
  const body = document.getElementById("divBatchModalBody");
  const today = new Date().toLocaleDateString("pt-BR");

  if (mode === "ENVIAR_CLIENTE") {
    document.getElementById("lblBatchModalTitle").innerText =
      `Enviar Lote (${indices.length} Aparelhos) p/ Hospital / Cliente`;
    body.innerHTML = `
      <div class="form-group" style="margin-bottom:10px;">
        <label>Hospital / Clínica / Cliente de Destino:</label>
        <input type="text" id="inpBatchCliente" list="dlKnownClients" placeholder="Escolha ou digite o nome do Hospital..." onchange="onBatchClientChange(this.value)" />
      </div>
      <div class="form-grid-2">
        <div class="form-group">
          <label>Modalidade:</label>
          <select id="selBatchModalidade">
            <option value="COMODATO">COMODATO</option>
            <option value="VENDA">VENDA</option>
            <option value="ALUGUEL">ALUGUEL</option>
          </select>
        </div>
        <div class="form-group">
          <label>Setor de Destino:</label>
          <input type="text" id="inpBatchSetor" placeholder="Ex: UTI / EMERGÊNCIA / LABORATÓRIO" />
        </div>
      </div>
      <div class="form-grid-3">
        <div class="form-group" style="grid-column: span 2;">
          <label>Endereço Completo:</label>
          <input type="text" id="inpBatchEndereco" placeholder="Preenchido automaticamente pelo cadastro do hospital" />
        </div>
        <div class="form-group">
          <label>CEP:</label>
          <input type="text" id="inpBatchCep" />
        </div>
      </div>
      <div class="form-group">
        <label>Observações da Saída (opcional):</label>
        <input type="text" id="inpBatchObs" placeholder="Ex: Entregue conforme protocolo..." />
      </div>
      <label style="display:flex; align-items:center; gap:8px; margin-top:10px; font-weight:700;">
        <input type="checkbox" id="chkBatchOpenRomaneio" checked />
        <span>Abrir Protocolo / Romaneio A4 automaticamente após salvar</span>
      </label>
    `;
  } else if (mode === "DEVOLVER_ESTOQUE") {
    document.getElementById("lblBatchModalTitle").innerText =
      `Retornar Lote (${indices.length} Aparelhos) p/ Estoque da LYDA`;
    body.innerHTML = `
      <div class="form-group" style="margin-bottom:10px;">
        <label>Quando voltou para o Estoque da LYDA, já foi atualizado?</label>
        <select id="selBatchJaAtualizado">
          <option value="SIM">SIM — Já foi atualizado na bancada (renovar ciclo +6 meses hoje)</option>
          <option value="NAO">NÃO — Falta atualizar na bancada do estoque</option>
        </select>
      </div>
      <div class="form-grid-2">
        <div class="form-group">
          <label>Data da Atualização (se atualizado):</label>
          <input type="text" id="inpBatchDataAtt" class="date-input-br" data-datepicker="br" autocomplete="off" value="${today}" />
        </div>
        <div class="form-group">
          <label>Versão CLEW / JAMS (opcional):</label>
          <input type="text" id="inpBatchVersao" placeholder="Ex: CLEW A45" />
        </div>
      </div>
      <div class="form-group">
        <label>Observações do Retorno (opcional):</label>
        <input type="text" id="inpBatchObs" placeholder="Ex: Recolhido do cliente p/ estoque da Lyda" />
      </div>
    `;
  } else if (mode === "MARCAR_ATUALIZADO_6M") {
    document.getElementById("lblBatchModalTitle").innerText =
      `Marcar Lote (${indices.length} Aparelhos) Atualizado (Ciclo 6 em 6 Meses)`;
    body.innerHTML = `
      <div class="form-grid-2">
        <div class="form-group">
          <label>Data da Atualização Semestral:</label>
          <input type="text" id="inpBatchDataAtt" class="date-input-br" data-datepicker="br" autocomplete="off" value="${today}" />
        </div>
        <div class="form-group">
          <label>Pacote / Versão CLEW / JAMS:</label>
          <input type="text" id="inpBatchVersao" placeholder="Ex: CLEW A45 / JAMS 148" />
        </div>
      </div>
    `;
  }

  document.getElementById("batchModalBackdrop").classList.add("open");
}

function closeBatchModal() {
  document.getElementById("batchModalBackdrop").classList.remove("open");
}

async function onBatchClientChange(cli) {
  if (!cli) return;
  try {
    const res = await fetch(`/api/client/address_info?cliente=${encodeURIComponent(cli)}`);
    const data = await res.json();
    if (data.ok && data.address_info) {
      document.getElementById("inpBatchEndereco").value = data.address_info.ENDERECO || "";
      document.getElementById("inpBatchCep").value = data.address_info.CEP || "";
    }
  } catch (e) {}
}

async function confirmBatchAction() {
  const indices = getSelectedIndicesArray();
  const mode = APP_STATE.batchMode;
  const payload = {
    indices: indices,
    action_type: mode,
    responsavel: (APP_STATE.current_user && APP_STATE.current_user.nome) || "OPERADOR",
  };

  let shouldOpenRomaneio = false;
  if (mode === "ENVIAR_CLIENTE") {
    payload.cliente = (document.getElementById("inpBatchCliente").value || "").trim();
    payload.modalidade = document.getElementById("selBatchModalidade").value;
    payload.setor = (document.getElementById("inpBatchSetor").value || "").trim();
    payload.endereco = (document.getElementById("inpBatchEndereco").value || "").trim();
    payload.cep = (document.getElementById("inpBatchCep").value || "").trim();
    payload.observacoes = (document.getElementById("inpBatchObs").value || "").trim();
    shouldOpenRomaneio = document.getElementById("chkBatchOpenRomaneio").checked;
  } else if (mode === "DEVOLVER_ESTOQUE") {
    payload.ja_atualizado = document.getElementById("selBatchJaAtualizado").value === "SIM";
    payload.data_atualizacao = (document.getElementById("inpBatchDataAtt").value || "").trim();
    payload.versao_clew = (document.getElementById("inpBatchVersao").value || "").trim();
    payload.observacoes = (document.getElementById("inpBatchObs").value || "").trim();
  } else if (mode === "MARCAR_ATUALIZADO_6M") {
    payload.data_atualizacao = (document.getElementById("inpBatchDataAtt").value || "").trim();
    payload.versao_clew = (document.getElementById("inpBatchVersao").value || "").trim();
  }

  try {
    const res = await fetch("/api/items/batch_action", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!data.ok) {
      showToast(data.error || "Erro na operação em lote.", "error");
      return;
    }
    showToast(data.message, "success");
    APP_STATE.selectedIndices.clear();
    closeBatchModal();
    await loadBootstrapData(true);
    if (shouldOpenRomaneio) {
      await openRomaneioWindow(indices);
    }
  } catch (e) {
    showToast("Erro ao executar operação em lote.", "error");
  }
}

async function deleteSelectedItemsByAdmin() {
  const indices = getSelectedIndicesArray();
  if (!indices.length) {
    showToast("Marque pelo menos 1 aparelho na tabela.", "error");
    return;
  }
  if (!confirm(`Deseja realmente excluir ${indices.length} aparelho(s) selecionado(s)?`)) return;
  const res = await fetch("/api/items/delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ indices }),
  });
  const data = await res.json();
  if (!data.ok) {
    showToast(data.error || "Erro ao excluir.", "error");
    return;
  }
  showToast(data.message, "success");
  await loadBootstrapData(false);
}

// =========================================================================
// ABA 3: CLIENTES & HOSPITAIS (DIRETÓRIO EM TELA CHEIA -> CLIQUE ABRE FICHA)
// =========================================================================
function setClientListFilter(mode) {
  APP_STATE.clientListFilter = mode || "ALL";
  renderClientsList();
}

function getClientInitials(name) {
  const words = String(name || "H")
    .replace(/[^A-Za-zÀ-ÿ0-9\s]/g, " ")
    .trim()
    .split(/\s+/)
    .filter(w => w.length > 2 && !["DOS", "DAS", "LTDA", "SOCIEDADE", "ASSOCIACAO", "ASSOC"].includes(w.toUpperCase()));
  if (words.length >= 2) {
    return (words[0][0] + words[1][0]).toUpperCase();
  }
  if (words.length === 1) {
    return words[0].substring(0, 2).toUpperCase();
  }
  return "HP";
}

function backToClientsDirectory() {
  const dirView = document.getElementById("divClientsDirectoryView");
  const detView = document.getElementById("divClientDetailView");
  if (dirView) dirView.style.display = "block";
  if (detView) detView.style.display = "none";
  renderClientsList();
}

function renderClientsList() {
  const inpSearch = document.getElementById("inpSearchClient");
  const q = ((inpSearch && inpSearch.value) || "").trim().toUpperCase();
  const tbodyDir = document.getElementById("tbodyClientsDirectory");
  if (!tbodyDir) return;

  const allClients = APP_STATE.clients || [];

  // Contadores das 5 pílulas de filtro
  let cntAll = allClients.length;
  let cntWith = 0;
  let cntComodato = 0;
  let cntVenda = 0;
  let cntPend = 0;
  allClients.forEach(c => {
    if ((c._total_aparelhos || 0) > 0) cntWith++;
    if ((c._comodato_count || 0) > 0) cntComodato++;
    if ((c._venda_count || 0) > 0) cntVenda++;
    if ((c._pendentes_6m || 0) > 0) cntPend++;
  });

  const elAll = document.getElementById("cntCliFilterAll");
  if (elAll) elAll.innerText = cntAll;
  const elWith = document.getElementById("cntCliFilterWith");
  if (elWith) elWith.innerText = cntWith;
  const elCom = document.getElementById("cntCliFilterComodato");
  if (elCom) elCom.innerText = cntComodato;
  const elVenda = document.getElementById("cntCliFilterVenda");
  if (elVenda) elVenda.innerText = cntVenda;
  const elPend = document.getElementById("cntCliFilterPend");
  if (elPend) elPend.innerText = cntPend;

  const subLbl = document.getElementById("lblClientsTotalSub");
  if (subLbl) {
    subLbl.innerText = `${cntAll} hospitais/clientes cadastrados • ${cntComodato} com Comodato • ${cntVenda} com Venda • Clique em qualquer hospital para abrir a ficha completa`;
  }

  ["ALL", "WITH_ITEMS", "COMODATO", "VENDA", "PENDING_6M"].forEach(code => {
    const btn = document.getElementById("btnCliFilter-" + code);
    if (btn) btn.classList.toggle("active", APP_STATE.clientListFilter === code);
  });

  const filtered = allClients.filter(c => {
    if (APP_STATE.clientListFilter === "WITH_ITEMS" && (c._total_aparelhos || 0) <= 0) return false;
    if (APP_STATE.clientListFilter === "COMODATO" && (c._comodato_count || 0) <= 0) return false;
    if (APP_STATE.clientListFilter === "VENDA" && (c._venda_count || 0) <= 0) return false;
    if (APP_STATE.clientListFilter === "PENDING_6M" && (c._pendentes_6m || 0) <= 0) return false;
    if (q) {
      const clientItemsSerials = (APP_STATE.items || [])
        .filter(it => (it.CLIENTE || "").toUpperCase() === (c.CLIENTE || "").toUpperCase())
        .map(it => it.CODIGO)
        .join(" ");
      const hay = [c.CLIENTE, c.CIDADE, c.UF, c.ENDERECO, c.CNPJ, c.SETORES, clientItemsSerials]
        .join(" ")
        .toUpperCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });

  if (!filtered.length) {
    tbodyDir.innerHTML = `
      <tr>
        <td colspan="6" style="text-align:center; padding:32px 14px; color:var(--slate-500); font-size:12px;">
          Nenhum hospital/cliente encontrado para esta busca.
        </td>
      </tr>
    `;
    return;
  }

  tbodyDir.innerHTML = filtered.map(c => {
    const isSel = c.CLIENTE === APP_STATE.selectedClientName;
    const totalAp = c._total_aparelhos || 0;
    const pend6m = c._pendentes_6m || 0;
    const emManut = c._em_manutencao || 0;
    const cityUf = `${c.CIDADE || "PORTO ALEGRE"} / ${c.UF || "RS"}`;
    const safeNameJs = escapeHtml(c.CLIENTE).replace(/\\/g, "\\\\").replace(/'/g, "\\'");
    const initials = getClientInitials(c.CLIENTE);
    const setoresTxt = c._setores_ativos || c.SETORES || "Sem setor especificado";
    const cCom = c._comodato_count || 0;
    const cVnd = c._venda_count || 0;
    const modParts = [];
    if (cCom > 0) modParts.push(`Comodato: ${cCom}`);
    if (cVnd > 0) modParts.push(`Venda: ${cVnd}`);
    const modsTxt = modParts.length ? modParts.join(" • ") : (c._modalidades_ativas || "SEM APARELHOS");

    let statusPill = `<span class="badge badge-em-dia">6m Em Dia</span>`;
    if (totalAp === 0) {
      statusPill = `<span class="badge badge-sem-data">Sem aparelhos</span>`;
    } else if (pend6m > 0) {
      statusPill = `<span class="badge badge-vencendo">${pend6m} Pendente(s) 6m</span>`;
    }
    if (emManut > 0) {
      statusPill += ` <span class="badge badge-vencida" title="Aparelho(s) deste hospital em manutenção/SP">${emManut} em Manut.</span>`;
    }

    const addrLine = c.ENDERECO
      ? `<span style="color:var(--slate-600); font-size:11.5px;">${escapeHtml(c.ENDERECO)}</span>`
      : `<span class="badge badge-vencendo" style="font-size:10px;">Sem endereço p/ Rota</span>`;

    return `
      <tr class="${isSel ? "row-selected" : ""}" style="cursor:pointer;" onclick="selectClientRecord('${safeNameJs}')">
        <td>
          <div style="display:flex; align-items:center; gap:10px;">
            <div style="width:32px; height:32px; border-radius:8px; background:var(--slate-900); color:#FFF; font-weight:800; font-size:11px; display:flex; align-items:center; justify-content:center; flex-shrink:0;">
              ${escapeHtml(initials)}
            </div>
            <div>
              <div class="cell-primary" style="font-size:12.5px;">${escapeHtml(c.CLIENTE)}</div>
              <div class="cell-sub">${c.CONTATO_LOCAL ? `Contato: ${escapeHtml(c.CONTATO_LOCAL)}` : (c.CNPJ ? `CNPJ: ${escapeHtml(c.CNPJ)}` : `Clique para abrir o cadastro e aparelhos`)}</div>
            </div>
          </div>
        </td>
        <td>
          <div class="cell-primary">${escapeHtml(cityUf)}</div>
          <div class="cell-sub">${addrLine}</div>
        </td>
        <td style="max-width:250px;">
          <div class="cell-primary">${escapeHtml(modsTxt)}</div>
          <div class="cell-sub" style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${escapeHtml(setoresTxt)}">${escapeHtml(setoresTxt)}</div>
        </td>
        <td style="text-align:center;">
          <span class="badge badge-ana" style="font-size:11.5px; padding:3px 10px;">${totalAp} ap.</span>
        </td>
        <td>${statusPill}</td>
        <td style="text-align:right; white-space:nowrap;" onclick="event.stopPropagation()">
          <button class="btn btn-primary btn-sm" onclick="selectClientRecord('${safeNameJs}')">Abrir Cadastro</button>
        </td>
      </tr>
    `;
  }).join("");

  if (APP_STATE.selectedClientName) {
    updateSelectedClientHeroAndForm();
    renderSelectedClientLinkedItems();
  }
}

function selectClientRecord(cliName) {
  APP_STATE.selectedClientName = cliName;
  const dirView = document.getElementById("divClientsDirectoryView");
  const detView = document.getElementById("divClientDetailView");
  if (dirView) dirView.style.display = "none";
  if (detView) detView.style.display = "block";
  updateSelectedClientHeroAndForm();
  renderSelectedClientLinkedItems();
}

function updateSelectedClientHeroAndForm() {
  const cliName = APP_STATE.selectedClientName;
  const rec = (APP_STATE.clients || []).find(c => c.CLIENTE === cliName);
  if (!rec) return;

  // Preenche o formulário de edição (mesmo quando recolhido)
  document.getElementById("hidClientOldName").value = rec.CLIENTE;
  document.getElementById("lblClientFormTitle").innerText = `Editar Cadastro — ${rec.CLIENTE}`;
  document.getElementById("inpCliNome").value = rec.CLIENTE || "";
  document.getElementById("inpCliCnpj").value = rec.CNPJ || "";
  document.getElementById("inpCliEndereco").value = rec.ENDERECO || "";
  document.getElementById("inpCliCep").value = rec.CEP || "";
  document.getElementById("inpCliCidade").value = rec.CIDADE || "PORTO ALEGRE";
  document.getElementById("inpCliUf").value = rec.UF || "RS";
  document.getElementById("inpCliSetores").value = rec._setores_ativos || rec.SETORES || "";
  document.getElementById("inpCliContato").value = rec.CONTATO_LOCAL || "";
  document.getElementById("inpCliTelefone").value = rec.TELEFONE || "";
  document.getElementById("inpCliEmail").value = rec.EMAIL || "";
  document.getElementById("inpCliObs").value = rec.OBSERVACOES || "";

  // Atualiza o Hero Card no topo da ficha do hospital
  const initialsEl = document.getElementById("divHeroClientInitials");
  if (initialsEl) initialsEl.innerText = getClientInitials(rec.CLIENTE);

  const nameEl = document.getElementById("lblHeroClientName");
  if (nameEl) nameEl.innerText = rec.CLIENTE;

  const cityBadge = document.getElementById("badgeHeroClientCity");
  if (cityBadge) {
    cityBadge.innerText = `${rec.CIDADE || "PORTO ALEGRE"} / ${rec.UF || "RS"}`;
  }

  const metaEl = document.getElementById("divHeroClientMeta");
  if (metaEl) {
    const addrHtml = rec.ENDERECO
      ? `<span><strong>Endereço:</strong> ${escapeHtml(rec.ENDERECO)}${rec.CEP ? ` (CEP: ${escapeHtml(rec.CEP)})` : ""}</span>`
      : `<span class="badge badge-vencendo" style="cursor:pointer;" onclick="toggleClientEditDrawer(true)">Sem endereço cadastrado p/ Rota — Clique para informar</span>`;

    const extraParts = [];
    if (rec.CNPJ) extraParts.push(`<span><strong>CNPJ:</strong> ${escapeHtml(rec.CNPJ)}</span>`);
    if (rec.CONTATO_LOCAL) extraParts.push(`<span><strong>Contato:</strong> ${escapeHtml(rec.CONTATO_LOCAL)}</span>`);
    if (rec.TELEFONE) extraParts.push(`<span><strong>Tel:</strong> ${escapeHtml(rec.TELEFONE)}</span>`);
    if (rec.OBSERVACOES) extraParts.push(`<span><strong>Obs:</strong> ${escapeHtml(rec.OBSERVACOES)}</span>`);

    metaEl.innerHTML = [addrHtml, ...extraParts].join(`<span style="color:var(--slate-300);">|</span>`);
  }
}

function toggleClientEditDrawer(forceState) {
  const drawer = document.getElementById("divClientEditDrawer");
  if (!drawer) return;
  const isOpen = drawer.style.display !== "none";
  const nextState = typeof forceState === "boolean" ? forceState : !isOpen;
  drawer.style.display = nextState ? "block" : "none";

  const btn = document.getElementById("btnToggleClientEdit");
  if (btn) {
    btn.innerText = nextState ? "Ocultar Edição Cadastral" : "Editar Cadastro & Endereço";
  }
  if (nextState) {
    document.getElementById("inpCliEndereco").focus();
  }
}

function prepareNewClientForm() {
  APP_STATE.selectedClientName = "";
  const dirView = document.getElementById("divClientsDirectoryView");
  const detView = document.getElementById("divClientDetailView");
  if (dirView) dirView.style.display = "none";
  if (detView) detView.style.display = "block";

  document.getElementById("hidClientOldName").value = "";
  document.getElementById("lblClientFormTitle").innerText = "Novo Cadastro de Hospital / Cliente";
  for (const id of ["inpCliNome","inpCliCnpj","inpCliEndereco","inpCliCep","inpCliSetores","inpCliContato","inpCliTelefone","inpCliEmail","inpCliObs"]) {
    const el = document.getElementById(id);
    if (el) el.value = "";
  }
  document.getElementById("inpCliCidade").value = "PORTO ALEGRE";
  document.getElementById("inpCliUf").value = "RS";

  document.getElementById("lblHeroClientName").innerText = "Novo Hospital / Cliente";
  document.getElementById("badgeHeroClientCity").innerText = "NOVO CADASTRO";
  document.getElementById("divHeroClientMeta").innerText = "Preencha os campos abaixo e clique em Salvar Cadastro do Hospital.";

  toggleClientEditDrawer(true);
  document.getElementById("tbodyClientLinkedItems").innerHTML =
    `<tr><td colspan="6" style="text-align:center; padding:24px; color:#64748B;">Salve o cadastro do hospital para vincular aparelhos.</td></tr>`;
  document.getElementById("inpCliNome").focus();
}

function renderSelectedClientLinkedItems() {
  const cliName = APP_STATE.selectedClientName;
  const linked = (APP_STATE.items || []).filter(
    it => (it.CLIENTE || "").toUpperCase() === (cliName || "").toUpperCase()
  );

  const titleEl = document.getElementById("lblClientLinkedTitle");
  if (titleEl) {
    titleEl.innerText = `Aparelhos i-STAT Vinculados a este Hospital (${linked.length})`;
  }

  // Calcula os 4 Mini-KPIs do Hospital selecionado
  let cntAna = 0, cntImp = 0, cntSim = 0, cntDwl = 0;
  let cntOk = 0, cntPend = 0, cntVencendo = 0, cntVencida = 0, cntManut = 0;
  let cntCom = 0, cntVnd = 0;
  const modsSet = new Set();
  const setoresSet = new Set();

  linked.forEach(it => {
    const t = String(it.TIPO || "ANALISADOR").toUpperCase();
    if (t.includes("IMPRESSORA")) cntImp++;
    else if (t.includes("SIMULADOR")) cntSim++;
    else if (t.includes("DOWNLOAD")) cntDwl++;
    else cntAna++;

    if (it._row_state === "DEFEITO") cntManut++;
    const modU = String(it.MODALIDADE || "").toUpperCase();
    if (modU) modsSet.add(modU);
    if (modU === "COMODATO" || modU === "ALUGUEL") cntCom++;
    else if (modU === "VENDA") cntVnd++;
    if (it.SETOR) setoresSet.add(it.SETOR);

    const code = (it._cycle && it._cycle.status_code) || "SEM_DATA";
    if (code === "EM_DIA") cntOk++;
    else {
      cntPend++;
      if (code === "VENCENDO") cntVencendo++;
      if (code === "VENCIDA") cntVencida++;
    }
  });

  const elTotal = document.getElementById("valCliKpiTotal");
  if (elTotal) elTotal.innerText = linked.length;

  const subTypes = document.getElementById("subCliKpiTypes");
  if (subTypes) {
    if (!linked.length) {
      subTypes.innerText = "Nenhum aparelho vinculado";
    } else {
      const parts = [];
      if (cntAna) parts.push(`${cntAna} Analisador(es)`);
      if (cntImp) parts.push(`${cntImp} Impressora(s)`);
      if (cntSim) parts.push(`${cntSim} Simulador(es)`);
      if (cntDwl) parts.push(`${cntDwl} Downloader(s)`);
      if (cntManut) parts.push(`${cntManut} em Manutenção/SP`);
      subTypes.innerText = parts.join(" • ");
    }
  }

  const elMod = document.getElementById("valCliKpiModalidade");
  if (elMod) {
    const modParts = [];
    if (cntCom > 0) modParts.push(`Comodato: ${cntCom}`);
    if (cntVnd > 0) modParts.push(`Venda: ${cntVnd}`);
    elMod.innerText = modParts.length ? modParts.join(" / ") : (modsSet.size ? Array.from(modsSet).join(" / ") : "-");
  }
  const subSet = document.getElementById("subCliKpiSetores");
  if (subSet) {
    subSet.innerText = setoresSet.size ? `Setores: ${Array.from(setoresSet).join(", ")}` : "Sem setor especificado";
  }

  const elOk = document.getElementById("valCliKpiOk");
  if (elOk) elOk.innerText = cntOk;

  const elPend = document.getElementById("valCliKpiPend");
  if (elPend) elPend.innerText = cntPend;

  const subPend = document.getElementById("subCliKpiPend");
  if (subPend) {
    subPend.innerText = cntPend > 0
      ? `Perto 6m: ${cntVencendo} • Vencidos: ${cntVencida}`
      : "Todos os aparelhos em dia";
  }

  const tbody = document.getElementById("tbodyClientLinkedItems");
  if (!tbody) return;
  const todayStr = new Date().toLocaleDateString("pt-BR");

  tbody.innerHTML = linked.length
    ? linked.map(it => {
        const idx = it._idx;
        const curDate = it.ULTIMA_ATUALIZACAO || "";
        const obsText = [it.DEFEITO ? `[DEFEITO: ${it.DEFEITO}]` : "", it.OBSERVACOES || ""]
          .filter(Boolean)
          .join(" ");
        const rowClass = getItemRowColorClass(it, false);

        return `
          <tr class="${rowClass}" ondblclick="openItemModal(${idx})">
            <td>
              <div style="display:flex; align-items:center; gap:6px;">
                ${getTipoBadgeHtml(it.TIPO)}
                <span style="font-family:monospace; font-weight:800; font-size:13px; color:#0F172A;">${escapeHtml(it.CODIGO)}</span>
              </div>
              ${it.KIT_ANALISADOR ? `<div class="cell-sub">Kit: ${escapeHtml(it.KIT_ANALISADOR)}</div>` : ""}
            </td>
            <td>
              <div class="cell-primary">${escapeHtml(it.SETOR || "NÃO INFORMADO")}</div>
              <div class="cell-sub"><strong>${escapeHtml(it.MODALIDADE || "-")}</strong> • ${escapeHtml(it.STATUS || "ATIVO")}</div>
            </td>
            <td>${getCycleProgressCellHtml(it)}</td>
            <td onclick="event.stopPropagation()">
              <div style="display:flex; align-items:center; gap:5px;">
                <input
                  type="text"
                  id="inpCliItemDate_${idx}"
                  class="date-input-br"
                  data-datepicker="br"
                  autocomplete="off"
                  value="${escapeHtml(curDate)}"
                  placeholder="DD/MM/AAAA"
                  style="width:124px; height:32px; font-weight:700;"
                />
                <button class="btn btn-secondary btn-sm" onclick="quickSaveItemUpdateDate(${idx}, document.getElementById('inpCliItemDate_${idx}').value)">Salvar</button>
                <button class="btn btn-success btn-sm" onclick="quickSaveItemUpdateDate(${idx}, '${todayStr}')" title="Marcar atualizado hoje (+6 meses)">Hoje (+6m)</button>
              </div>
            </td>
            <td style="max-width:190px;">
              <div style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:11.5px; color:#475569;" title="${escapeHtml(obsText)}">${escapeHtml(obsText || "-")}</div>
            </td>
            <td style="text-align:right; white-space:nowrap;" onclick="event.stopPropagation()">
              <button class="btn btn-secondary btn-sm" onclick="openItemModal(${idx})"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>Ficha</button>
              <button class="btn btn-secondary btn-sm" onclick="quickReturnSingleItemToStock(${idx})" title="Retornar este aparelho para o Estoque da LYDA">Devolver p/ Estoque</button>
            </td>
          </tr>
        `;
      }).join("")
    : `
      <tr>
        <td colspan="6" style="text-align:center; padding:32px 16px; color:#64748B;">
          <div style="font-weight:700; color:#334155; margin-bottom:4px;">Nenhum aparelho vinculado a este hospital no momento.</div>
          <div style="font-size:11.5px; margin-bottom:10px;">Clique no botão abaixo para vincular um aparelho disponível no Estoque da LYDA.</div>
          <button class="btn btn-primary btn-sm" onclick="toggleQuickLinkStockBar(true)">+ Vincular Aparelho do Estoque</button>
        </td>
      </tr>
    `;
}

async function saveClientRecord() {
  const clientPayload = {
    CLIENTE: document.getElementById("inpCliNome").value.trim(),
    CNPJ: document.getElementById("inpCliCnpj").value.trim(),
    ENDERECO: document.getElementById("inpCliEndereco").value.trim(),
    CEP: document.getElementById("inpCliCep").value.trim(),
    CIDADE: document.getElementById("inpCliCidade").value.trim(),
    UF: document.getElementById("inpCliUf").value.trim(),
    SETORES: document.getElementById("inpCliSetores").value.trim(),
    CONTATO_LOCAL: document.getElementById("inpCliContato").value.trim(),
    TELEFONE: document.getElementById("inpCliTelefone").value.trim(),
    EMAIL: document.getElementById("inpCliEmail").value.trim(),
    OBSERVACOES: document.getElementById("inpCliObs").value.trim(),
  };
  const oldName = document.getElementById("hidClientOldName").value.trim();

  try {
    const res = await fetch("/api/client/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ client: clientPayload, old_name: oldName }),
    });
    const data = await res.json();
    if (!data.ok) {
      showToast(data.error || "Erro ao salvar cliente.", "error");
      return;
    }
    APP_STATE.selectedClientName = data.client.CLIENTE;
    showToast(data.message, "success");
    toggleClientEditDrawer(false);
    await loadBootstrapData(true);
    selectClientRecord(data.client.CLIENTE);
  } catch (e) {
    showToast("Erro ao salvar cadastro do cliente.", "error");
  }
}

async function deleteSelectedClient() {
  const cli = APP_STATE.selectedClientName;
  if (!cli) return;
  if (!confirm(`Deseja realmente excluir o cliente '${cli}'? Os aparelhos vinculados voltarão para o Estoque da LYDA.`)) return;
  const res = await fetch("/api/client/delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ cliente: cli }),
  });
  const data = await res.json();
  if (!data.ok) {
    showToast(data.error || "Erro ao excluir cliente.", "error");
    return;
  }
  APP_STATE.selectedClientName = "";
  toggleClientEditDrawer(false);
  backToClientsDirectory();
  showToast(data.message, "success");
  await loadBootstrapData(true);
}

function openSelectedClientInGoogleMaps() {
  const addr = document.getElementById("inpCliEndereco").value.trim();
  const city = document.getElementById("inpCliCidade").value.trim();
  const uf = document.getElementById("inpCliUf").value.trim();
  const cli = document.getElementById("inpCliNome").value.trim() || APP_STATE.selectedClientName;
  const q = [addr || cli, city, uf, "Brasil"].filter(Boolean).join(", ");
  window.open(`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(q)}`, "_blank");
}

function createRouteForSelectedClient() {
  const cli = APP_STATE.selectedClientName;
  if (!cli) return;
  const indices = APP_STATE.items
    .filter(it => (it.CLIENTE || "").toUpperCase() === cli.toUpperCase())
    .map(it => it._idx);
  switchTab("tab-rota");
  if (indices.length > 0) {
    loadRouteFromIndices(indices);
  } else {
    APP_STATE.routeStops = [{ CLIENTE: cli }];
    recalculateCurrentRoute(false);
  }
}

async function markAllClientItemsUpdated6m() {
  const cli = APP_STATE.selectedClientName;
  if (!cli) return;
  const indices = APP_STATE.items
    .filter(it => (it.CLIENTE || "").toUpperCase() === cli.toUpperCase())
    .map(it => it._idx);
  if (!indices.length) {
    showToast("Este cliente não possui aparelhos vinculados.", "error");
    return;
  }
  APP_STATE.selectedIndices = new Set(indices);
  openBatchModal("MARCAR_ATUALIZADO_6M");
}

async function generateRomaneioForSelectedClient() {
  const cli = APP_STATE.selectedClientName;
  if (!cli) return;
  const indices = APP_STATE.items
    .filter(it => (it.CLIENTE || "").toUpperCase() === cli.toUpperCase())
    .map(it => it._idx);
  if (!indices.length) {
    showToast("Nenhum aparelho vinculado a este cliente.", "error");
    return;
  }
  await openRomaneioWindow(indices);
}

function toggleQuickLinkStockBar(forceState) {
  const cli = APP_STATE.selectedClientName;
  if (!cli) {
    showToast("Selecione ou salve um hospital/cliente primeiro.", "error");
    return;
  }
  const bar = document.getElementById("divQuickLinkStockBar");
  if (!bar) return;
  const isOpen = bar.style.display !== "none";
  const nextState = typeof forceState === "boolean" ? forceState : !isOpen;
  bar.style.display = nextState ? "block" : "none";

  if (nextState) {
    // Popula datalist com aparelhos atualmente no Estoque da LYDA (e também todos os demais)
    const dl = document.getElementById("dlStockAvailableItems");
    if (dl) {
      const stockItems = (APP_STATE.items || []).filter(it => it._row_state === "ESTOQUE");
      const otherItems = (APP_STATE.items || []).filter(it => it._row_state !== "ESTOQUE");
      dl.innerHTML = [...stockItems, ...otherItems]
        .map(it => {
          const originTag = it._row_state === "ESTOQUE" ? "NO ESTOQUE LYDA" : `Em: ${it.CLIENTE}`;
          return `<option value="${escapeHtml(it.CODIGO)}">${escapeHtml(it.TIPO)} — SN: ${escapeHtml(it.CODIGO)} (${escapeHtml(originTag)})</option>`;
        })
        .join("");
    }
    const inp = document.getElementById("inpQuickLinkSerial");
    if (inp) {
      inp.value = "";
      inp.focus();
    }
  }
}

async function confirmQuickLinkStockToClient() {
  const cli = APP_STATE.selectedClientName;
  if (!cli) return;
  const rawSerial = (document.getElementById("inpQuickLinkSerial").value || "").trim();
  if (!rawSerial) {
    showToast("Escolha ou digite o serial do aparelho.", "error");
    return;
  }
  const setor = (document.getElementById("inpQuickLinkSetor").value || "").trim() || "LABORATÓRIO";
  const modalidade = document.getElementById("selQuickLinkModalidade").value || "COMODATO";

  const res = await fetch(`/api/scan?code=${encodeURIComponent(rawSerial)}`);
  const data = await res.json();
  if (!data.ok || !data.matches || !data.matches.length) {
    showToast(`Serial '${rawSerial}' não encontrado no estoque.`, "error");
    return;
  }
  const match = data.matches[0];
  const rec = (APP_STATE.clients || []).find(c => c.CLIENTE === cli) || {};
  const loggedName = (APP_STATE.current_user && APP_STATE.current_user.nome) || "OPERADOR";

  const batchRes = await fetch("/api/items/batch_action", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      indices: [match._idx],
      action_type: "ENVIAR_CLIENTE",
      cliente: cli,
      modalidade: modalidade,
      setor: setor,
      endereco: rec.ENDERECO || "",
      cep: rec.CEP || "",
      observacoes: `Vinculado ao cliente ${cli} (${setor})`,
      responsavel: loggedName,
    }),
  });
  const batchData = await batchRes.json();
  if (!batchData.ok) {
    showToast(batchData.error || "Erro ao vincular aparelho.", "error");
    return;
  }
  showToast(`Aparelho ${match.CODIGO} vinculado a ${cli}!`, "success");
  toggleQuickLinkStockBar(false);
  await loadBootstrapData(true);
}

function quickReturnSingleItemToStock(idx) {
  APP_STATE.selectedIndices = new Set([idx]);
  openBatchModal("DEVOLVER_ESTOQUE");
}

async function lookupCepIntoFields(cepId, addrId, cityId, ufId) {
  const rawCep = (document.getElementById(cepId).value || "").trim();
  if (!rawCep) {
    showToast("Digite o CEP antes de buscar.", "error");
    return;
  }
  try {
    const res = await fetch(`/api/cep/${encodeURIComponent(rawCep)}`);
    const data = await res.json();
    if (!data.ok) {
      showToast(data.error || "CEP não encontrado.", "error");
      return;
    }
    const c = data.cep_data;
    const curAddr = document.getElementById(addrId).value.trim();
    const numMatch = curAddr.match(/,\s*(\d+[^,\-]*)/);
    const numPart = numMatch ? `, ${numMatch[1]}` : ", Nº ";
    document.getElementById(addrId).value = `${c.logradouro}${numPart} - ${c.bairro}`;
    document.getElementById(cityId).value = (c.cidade || "PORTO ALEGRE").toUpperCase();
    document.getElementById(ufId).value = (c.uf || "RS").toUpperCase();
    document.getElementById(cepId).value = c.cep || rawCep;
    showToast(`Endereço preenchido via CEP ${c.cep}!`, "success");
  } catch (e) {
    showToast("Erro ao consultar ViaCEP.", "error");
  }
}

// =========================================================================
// ABA 3: ROTA DA ENFERMEIRA + GOOGLE MAPS INTERATIVO NO NAVEGADOR
// =========================================================================
function initRouteLeafletMap() {
  if (routeLeafletMap) {
    setTimeout(() => routeLeafletMap.invalidateSize(), 80);
    return;
  }
  routeLeafletMap = L.map("routeMapContainer", {
    center: [-30.0346, -51.2177],
    zoom: 12,
    zoomControl: true,
  });
  setGoogleMapsTileLayer("m");
  routeMarkersLayer = L.layerGroup().addTo(routeLeafletMap);
  routePolylineLayer = L.layerGroup().addTo(routeLeafletMap);
}

function setGoogleMapsTileLayer(layerCode) {
  if (!routeLeafletMap) return;
  if (routeTileLayer) {
    routeLeafletMap.removeLayer(routeTileLayer);
  }
  routeTileLayer = L.tileLayer(
    `https://mt{s}.google.com/vt/lyrs=${layerCode}&hl=pt-BR&x={x}&y={y}&z={z}`,
    {
      subdomains: ["0", "1", "2", "3"],
      maxZoom: 20,
      attribution: "Google Maps — LYDA Rota da Enfermeira",
    }
  ).addTo(routeLeafletMap);
}

function openRouteWithSelectedItems() {
  const indices = getSelectedIndicesArray();
  switchTab("tab-rota");
  loadRouteFromIndices(indices);
}

async function loadRouteFromMode(mode) {
  initRouteLeafletMap();
  const indices = getSelectedIndicesArray();
  await requestRouteBuild({
    mode: mode,
    indices: indices,
    optimize_order: true,
  });
}

async function loadRouteFromIndices(indices) {
  initRouteLeafletMap();
  await requestRouteBuild({
    mode: "FROM_INDICES",
    indices: indices,
    optimize_order: true,
  });
}

async function recalculateCurrentRoute(optimizeOrder = false) {
  initRouteLeafletMap();
  await requestRouteBuild({
    mode: "CUSTOM_STOPS",
    stops: APP_STATE.routeStops,
    optimize_order: optimizeOrder,
  });
}

async function requestRouteBuild(extraParams) {
  const payload = Object.assign(
    {
      origin_address: document.getElementById("inpRouteOrigin").value.trim(),
      nurse_name: document.getElementById("selRouteNurse").value,
      update_version: document.getElementById("inpRouteVersion").value.trim(),
      route_date: document.getElementById("inpRouteDate").value.trim(),
      return_to_origin: document.getElementById("chkRouteCircular").checked,
    },
    extraParams
  );

  try {
    const res = await fetch("/api/route/build", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!data.ok) return;

    APP_STATE.routeStops = data.stops || [];
    APP_STATE.routeMetrics = data.metrics || {};
    if (APP_STATE.selectedRouteStopIdx >= APP_STATE.routeStops.length) {
      APP_STATE.selectedRouteStopIdx = 0;
    }

    document.getElementById("inpRouteGoogleMapsUrl").value = data.google_maps_url || "";
    document.getElementById("txtRouteWhatsappPreview").value = data.whatsapp_text || "";
    document.getElementById("lblRouteMetricsBanner").innerText =
      `3. Google Maps da Rota: ${data.metrics.total_km || 0} km | ~${data.metrics.total_time_str || "0 min"} | ${APP_STATE.routeStops.length} Parada(s)`;

    const qrUrl = `https://api.qrserver.com/v1/create-qr-code/?size=160x160&margin=4&data=${encodeURIComponent(data.google_maps_url || "https://maps.google.com")}`;
    document.getElementById("imgRouteQrCode").src = qrUrl;

    renderRouteStopsTable();
    renderRouteOnLeafletGoogleMap(data.origin_coord, APP_STATE.routeStops);
  } catch (e) {
    showToast("Erro ao calcular rota no Google Maps.", "error");
  }
}

function renderRouteStopsTable() {
  const tbody = document.getElementById("tbodyRouteStops");
  const stops = APP_STATE.routeStops || [];

  tbody.innerHTML = stops.length
    ? stops.map((st, idx) => {
        const isSel = idx === APP_STATE.selectedRouteStopIdx;
        const legTxt = st._leg_km ? `+${st._leg_km} km (~${st._leg_min} min)` : "-";
        return `
          <tr class="${isSel ? "row-selected" : ""}" style="cursor:pointer;" onclick="selectRouteStop(${idx})">
            <td style="font-weight:800; color:#1E40AF;">#${idx + 1}</td>
            <td style="font-weight:700;">${escapeHtml(st.CLIENTE)}</td>
            <td>${escapeHtml(st.ENDERECO || "-")}</td>
            <td style="white-space:nowrap; font-weight:700; color:#1D4ED8;">${escapeHtml(legTxt)}</td>
            <td style="text-align:center; font-weight:800;">${st.ITEMS_COUNT || (st.ITEMS || []).length}</td>
            <td style="font-family:monospace; font-size:11px;">${escapeHtml(st.SERIAIS_RESUMO || "")}</td>
            <td style="text-align:right; white-space:nowrap;" onclick="event.stopPropagation()">
              <button class="btn btn-secondary btn-sm" onclick="moveRouteStop(${idx}, -1)">Subir</button>
              <button class="btn btn-secondary btn-sm" onclick="moveRouteStop(${idx}, 1)">Descer</button>
              <button class="btn btn-danger btn-sm" onclick="removeRouteStop(${idx})">X</button>
            </td>
          </tr>
        `;
      }).join("")
    : `<tr><td colspan="7" style="text-align:center; padding:20px; color:#64748B;">Nenhuma parada na rota. Escolha um hospital acima ou clique em "Carregar Pendentes/Vencidos (6m)".</td></tr>`;

  populateSelectedStopEditBox();
}

function selectRouteStop(idx) {
  APP_STATE.selectedRouteStopIdx = idx;
  renderRouteStopsTable();
  const st = APP_STATE.routeStops[idx];
  if (st && st._lat && st._lon && routeLeafletMap) {
    routeLeafletMap.setView([st._lat, st._lon], 15, { animate: true });
  }
}

function populateSelectedStopEditBox() {
  const st = APP_STATE.routeStops[APP_STATE.selectedRouteStopIdx];
  if (!st) {
    document.getElementById("lblEditStopTitle").innerText = "Selecione uma parada acima para editar o endereço:";
    document.getElementById("inpStopAddr").value = "";
    document.getElementById("inpStopCep").value = "";
    return;
  }
  document.getElementById("lblEditStopTitle").innerText =
    `Editar Endereço da Parada #${APP_STATE.selectedRouteStopIdx + 1} — ${st.CLIENTE}:`;
  document.getElementById("inpStopAddr").value = st.ENDERECO || "";
  document.getElementById("inpStopCep").value = st.CEP || "";
}

async function lookupStopCep() {
  const rawCep = document.getElementById("inpStopCep").value.trim();
  if (!rawCep) return;
  const res = await fetch(`/api/cep/${encodeURIComponent(rawCep)}`);
  const data = await res.json();
  if (data.ok && data.cep_data) {
    const c = data.cep_data;
    document.getElementById("inpStopAddr").value = `${c.logradouro}, Nº  - ${c.bairro}`;
    document.getElementById("inpStopCep").value = c.cep;
  }
}

async function saveSelectedStopAddress() {
  const idx = APP_STATE.selectedRouteStopIdx;
  const st = APP_STATE.routeStops[idx];
  if (!st) return;
  st.ENDERECO = document.getElementById("inpStopAddr").value.trim();
  st.CEP = document.getElementById("inpStopCep").value.trim();

  await fetch("/api/client/save", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      client: {
        CLIENTE: st.CLIENTE,
        ENDERECO: st.ENDERECO,
        CEP: st.CEP,
        CIDADE: st.CIDADE || "PORTO ALEGRE",
        UF: st.UF || "RS",
      },
    }),
  });
  showToast(`Endereço de ${st.CLIENTE} atualizado no mapa e no cadastro!`, "success");
  await recalculateCurrentRoute(false);
}

function moveRouteStop(idx, dir) {
  const target = idx + dir;
  if (target < 0 || target >= APP_STATE.routeStops.length) return;
  const tmp = APP_STATE.routeStops[idx];
  APP_STATE.routeStops[idx] = APP_STATE.routeStops[target];
  APP_STATE.routeStops[target] = tmp;
  APP_STATE.selectedRouteStopIdx = target;
  recalculateCurrentRoute(false);
}

function removeRouteStop(idx) {
  APP_STATE.routeStops.splice(idx, 1);
  recalculateCurrentRoute(false);
}

function clearRouteStops() {
  APP_STATE.routeStops = [];
  recalculateCurrentRoute(false);
}

function addClientStopToRoute() {
  const cli = document.getElementById("selRouteAddClient").value;
  if (!cli) return;
  if (APP_STATE.routeStops.some(s => (s.CLIENTE || "").toUpperCase() === cli.toUpperCase())) {
    showToast("Este hospital já está incluído na rota.", "info");
    return;
  }
  APP_STATE.routeStops.push({ CLIENTE: cli });
  recalculateCurrentRoute(false);
}

function renderRouteOnLeafletGoogleMap(originCoord, stops) {
  initRouteLeafletMap();
  routeMarkersLayer.clearLayers();
  routePolylineLayer.clearLayers();

  const coordsList = [];

  if (originCoord && originCoord.length === 2) {
    coordsList.push(originCoord);
    const hqIcon = L.divIcon({
      className: "",
      html: `<div class="gmaps-pin gmaps-pin-hq">S</div>`,
      iconSize: [28, 28],
      iconAnchor: [14, 14],
    });
    const hqAddr = document.getElementById("inpRouteOrigin").value;
    L.marker(originCoord, { icon: hqIcon })
      .bindPopup(`<strong>[PARTIDA] SEDE DA LYDA</strong><br/>${escapeHtml(hqAddr)}`)
      .addTo(routeMarkersLayer);
  }

  stops.forEach((st, idx) => {
    if (st._lat && st._lon) {
      const pt = [st._lat, st._lon];
      coordsList.push(pt);
      const pinIcon = L.divIcon({
        className: "",
        html: `<div class="gmaps-pin gmaps-pin-stop">${idx + 1}</div>`,
        iconSize: [28, 28],
        iconAnchor: [14, 14],
      });
      const popupHtml = `
        <div style="font-size:12px; line-height:1.4;">
          <strong style="color:#1E40AF;">PARADA #${idx + 1}: ${escapeHtml(st.CLIENTE)}</strong><br/>
          <span>${escapeHtml(st.ENDERECO || "-")} (${escapeHtml(st.CIDADE || "POA")}/${escapeHtml(st.UF || "RS")})</span><br/>
          <span><strong>Trecho:</strong> +${st._leg_km || 0} km (~${st._leg_min || 0} min)</span><br/>
          <span><strong>Aparelhos (${st.ITEMS_COUNT || 1}):</strong> ${escapeHtml(st.SERIAIS_RESUMO || "")}</span><br/>
          <div style="margin-top:6px; display:flex; gap:6px;">
            <a href="${st._maps_single_url}" target="_blank" style="color:#1D4ED8; font-weight:700;">Abrir Google Maps</a>
            <span>|</span>
            <a href="${st._waze_single_url}" target="_blank" style="color:#0284C7; font-weight:700;">Abrir Waze</a>
          </div>
        </div>
      `;
      L.marker(pt, { icon: pinIcon })
        .bindPopup(popupHtml)
        .addTo(routeMarkersLayer);
    }
  });

  if (document.getElementById("chkRouteCircular").checked && originCoord && stops.length > 0) {
    coordsList.push(originCoord);
  }

  if (coordsList.length >= 2) {
    L.polyline(coordsList, { color: "#174EA6", weight: 8, opacity: 0.85 }).addTo(routePolylineLayer);
    L.polyline(coordsList, { color: "#1A73E8", weight: 5, opacity: 1.0 }).addTo(routePolylineLayer);
  }

  fitRouteMapBounds();
}

function fitRouteMapBounds() {
  if (!routeLeafletMap) return;
  const pts = [];
  routeMarkersLayer.eachLayer(layer => {
    if (layer.getLatLng) pts.push(layer.getLatLng());
  });
  if (pts.length >= 2) {
    routeLeafletMap.fitBounds(L.latLngBounds(pts), { padding: [36, 36] });
  } else if (pts.length === 1) {
    routeLeafletMap.setView(pts[0], 14);
  }
}

async function downloadOfficialRoutePdf() {
  if (!APP_STATE.routeStops.length) {
    showToast("Adicione pelo menos 1 parada na rota antes de gerar o PDF.", "error");
    return;
  }
  copyOnlyGoogleMapsUrl();
  try {
    showToast("Gerando PDF Oficial da Rota da Enfermeira...", "info");
    const res = await fetch("/api/route/pdf", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        origin_address: document.getElementById("inpRouteOrigin").value.trim(),
        stops: APP_STATE.routeStops,
        nurse_name: document.getElementById("selRouteNurse").value,
        update_version: document.getElementById("inpRouteVersion").value.trim(),
        route_date: document.getElementById("inpRouteDate").value.trim(),
        return_to_origin: document.getElementById("chkRouteCircular").checked,
        observacoes_rota: document.getElementById("inpRouteObs").value.trim(),
      }),
    });
    if (!res.ok) {
      showToast("Erro ao gerar o PDF da rota.", "error");
      return;
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    window.open(url, "_blank");
    showToast("PDF Oficial gerado e Link do Google Maps copiado!", "success");
    await loadBootstrapData(true);
  } catch (e) {
    showToast("Erro ao baixar PDF da rota.", "error");
  }
}

function copyRouteWhatsappText() {
  const txt = document.getElementById("txtRouteWhatsappPreview").value;
  navigator.clipboard.writeText(txt);
  showToast("Roteiro completo + Link do Google Maps copiado para colar no WhatsApp!", "success");
}

function copyOnlyGoogleMapsUrl() {
  const url = document.getElementById("inpRouteGoogleMapsUrl").value;
  if (url) {
    navigator.clipboard.writeText(url);
    showToast("Link da Rota Google Maps copiado!", "success");
  }
}

function openFullRouteInGoogleMaps() {
  const url = document.getElementById("inpRouteGoogleMapsUrl").value;
  if (url) window.open(url, "_blank");
}

async function markAllRouteItemsUpdated6m() {
  const serials = new Set();
  APP_STATE.routeStops.forEach(st => {
    (st.ITEMS || []).forEach(it => {
      if (it.CODIGO) serials.add(String(it.CODIGO).toUpperCase());
    });
  });
  const indices = APP_STATE.items
    .filter(it => serials.has(String(it.CODIGO).toUpperCase()))
    .map(it => it._idx);
  if (!indices.length) {
    showToast("Nenhum aparelho encontrado nas paradas da rota.", "error");
    return;
  }
  APP_STATE.selectedIndices = new Set(indices);
  openBatchModal("MARCAR_ATUALIZADO_6M");
}

async function saveLydaHqFromRoute() {
  const hq = document.getElementById("inpRouteOrigin").value.trim();
  if (!hq) return;
  await fetch("/api/settings/save", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ lyda_hq_address: hq }),
  });
  showToast("Endereço da Sede da LYDA salvo!", "success");
  recalculateCurrentRoute(false);
}

// =========================================================================
// ROMANEIO A4 & IMPRESSÃO ZEBRA ZD230
// =========================================================================
async function generateRomaneioForSelected() {
  const indices = getSelectedIndicesArray();
  if (!indices.length) {
    showToast("Marque pelo menos 1 aparelho na tabela para gerar o Romaneio A4.", "error");
    return;
  }
  await openRomaneioWindow(indices);
}

async function openRomaneioWindow(indices) {
  try {
    const res = await fetch("/api/romaneio/html", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ indices: indices }),
    });
    const data = await res.json();
    if (!data.ok) {
      showToast(data.error || "Erro ao gerar Romaneio.", "error");
      return;
    }
    const win = window.open("", "_blank");
    if (win) {
      win.document.open();
      win.document.write(data.html);
      win.document.close();
    }
  } catch (e) {
    showToast("Erro ao abrir Romaneio A4.", "error");
  }
}

// =========================================================================
// ABA 0 (INICIAL): DASHBOARD EXECUTIVO, GRÁFICOS INTERATIVOS & RELATÓRIOS
// =========================================================================
function renderExecutiveDashboard() {
  const items = APP_STATE.items || [];
  const clients = APP_STATE.clients || [];
  const k = APP_STATE.kpis || {};
  const total = Math.max(1, items.length);

  const cntCliente = k.em_cliente || 0;
  const cntEstoque = k.em_estoque || 0;
  const cntDefeito = k.defeito_manutencao ?? k.em_defeito ?? 0;
  const defCli = k.defeito_em_cliente || 0;
  const defEst = k.defeito_em_estoque || 0;
  const cntComodato = k.comodato_aluguel || 0;
  const cntVenda = k.venda || 0;
  const cntPend6m = k.ciclo_pendente_vencido || 0;
  const cntOk6m = k.ciclo_em_dia || 0;

  // contagens por Tipo
  let cntAna = 0, cntImp = 0, cntSim = 0, cntDwl = 0;
  items.forEach(it => {
    const t = String(it.TIPO || "ANALISADOR").toUpperCase();
    if (t.includes("IMPRESSORA")) cntImp++;
    else if (t.includes("SIMULADOR")) cntSim++;
    else if (t.includes("DOWNLOAD")) cntDwl++;
    else cntAna++;
  });

  // 1. Atualiza os 6 KPI Cards do Dashboard
  const setTxt = (id, v) => { const el = document.getElementById(id); if (el) el.innerText = v; };
  const setBar = (id, pct) => { const el = document.getElementById(id); if (el) el.style.width = `${Math.min(100, Math.max(0, pct))}%`; };

  setTxt("valDashTotal", items.length);
  setTxt("subDashTotal", `${cntAna} Analis. • ${cntImp} Imp. • ${cntSim} Sim. • ${cntDwl} Dwl.`);

  const pctCli = (cntCliente / total) * 100;
  setTxt("valDashCliente", cntCliente);
  setTxt("pctDashCliente", formatRealPct(cntCliente, total));
  setTxt(
    "subDashCliente",
    defCli > 0
      ? `Em ${clients.length} hospitais (+${defCli} em manutenção)`
      : `Distribuídos em ${clients.length} hospitais/clínicas`
  );
  setBar("barDashCliente", pctCli);

  const pctEst = (cntEstoque / total) * 100;
  setTxt("valDashEstoque", cntEstoque);
  setTxt("pctDashEstoque", formatRealPct(cntEstoque, total));
  const estNovos = k.estoque_novos || 0;
  const estUsados = k.estoque_usados || 0;
  const estBackup = k.estoque_backup || 0;
  setTxt(
    "subDashEstoque",
    estNovos > 0 || estUsados > 0
      ? `${estNovos} Novos • ${estUsados} Usados${estBackup > 0 ? ` • ${estBackup} Backup` : ""}`
      : `Atualizados: ${k.estoque_atualizado || 0} | Falta: ${k.estoque_falta_atualizar || 0}`
  );
  setBar("barDashEstoque", pctEst);

  const pctCom = (cntComodato / total) * 100;
  setTxt("valDashComodato", cntComodato);
  setTxt("pctDashComodato", formatRealPct(cntComodato, total));
  const comAtivo = k.comodato_ativo ?? cntComodato;
  const comManut = k.comodato_manut || 0;
  setTxt(
    "subDashComodato",
    comManut > 0
      ? `Ativos em hospitais: ${comAtivo} (+${comManut} manut.)`
      : `Patrimônio LYDA cedido em comodato`
  );
  setBar("barDashComodato", pctCom);

  const pctVenda = (cntVenda / total) * 100;
  setTxt("valDashVenda", cntVenda);
  setTxt("pctDashVenda", formatRealPct(cntVenda, total));
  const vndAtivo = k.venda_ativo ?? cntVenda;
  const vndManut = k.venda_manut || 0;
  setTxt(
    "subDashVenda",
    vndManut > 0
      ? `Em uso: ${vndAtivo} (+${vndManut} em manutenção)`
      : `Equipamentos vendidos em operação`
  );
  setBar("barDashVenda", pctVenda);

  const pctPend = (cntPend6m / total) * 100;
  setTxt("valDashPend6m", cntPend6m);
  setTxt("pctDashPend6m", formatRealPct(cntPend6m, total));
  setTxt("subDashPend6m", `Em dia: ${cntOk6m} | Perto 6m: ${k.ciclo_vencendo || 0} | Venc: ${k.ciclo_vencida || 0}`);
  setBar("barDashPend6m", pctPend);

  const pctDef = (cntDefeito / total) * 100;
  setTxt("valDashDefeito", cntDefeito);
  setTxt("pctDashDefeito", formatRealPct(cntDefeito, total));
  setTxt(
    "subDashDefeito",
    cntDefeito > 0
      ? `${defCli} de hospitais • ${defEst} estoque em assistência SP`
      : `Em manutenção, reparo ou devolvidos`
  );
  setBar("barDashDefeito", pctDef);

  // 2. Gráfico 1: Donut SVG interativo com TODAS as categorias e tipos
  const donutWrap = document.getElementById("divDashDonutSituacao");
  if (donutWrap) {
    const mode = APP_STATE.dashDonutMode === "TIPOS" ? "TIPOS" : "COMPLETO";
    document.querySelectorAll("#dashDonutModeSwitch .dash-mode-btn").forEach(b => {
      b.classList.toggle("active", b.getAttribute("data-mode") === mode);
    });

    const g = { com: 0, vnd: 0, outros: 0, novos: 0, usados: 0, backup: 0, manut: 0 };
    items.forEach(it => {
      const st = it._row_state || "ATIVO";
      if (st === "DEFEITO") { g.manut++; return; }
      if (st === "ESTOQUE") {
        const sg = classifyStockSubgroup(it);
        if (sg === "NOVOS") g.novos++;
        else if (sg === "USADOS") g.usados++;
        else g.backup++;
        return;
      }
      const m = String(it.MODALIDADE || "").toUpperCase();
      if (m === "COMODATO" || m === "ALUGUEL") g.com++;
      else if (m === "VENDA") g.vnd++;
      else g.outros++;
    });

    const typeSegs = [
      { label: "Analisador", sub: "Analisadores i-STAT", count: cntAna, color: "#2563EB", jump: "null, null, 'ANALISADOR'" },
      { label: "Impressora", sub: "Impressoras de bancada", count: cntImp, color: "#7C3AED", jump: "null, null, 'IMPRESSORA'" },
      { label: "Simulador", sub: "Simuladores eletrônicos", count: cntSim, color: "#0D9488", jump: "null, null, 'SIMULADOR'" },
      { label: "Downloader", sub: "Downloaders de dados", count: cntDwl, color: "#F59E0B", jump: "null, null, 'DOWNLOADER'" },
    ];

    let segments;
    if (mode === "TIPOS") {
      segments = typeSegs;
    } else {
      segments = [
        { label: "Em Hospitais — Comodato", sub: "Patrimônio LYDA em operação", count: g.com, color: "#0284C7", jump: "'ATIVO', 'COMODATO'" },
        { label: "Em Hospitais — Venda", sub: "Vendidos e em uso nos clientes", count: g.vnd, color: "#6366F1", jump: "'ATIVO', 'VENDA'" },
        { label: "Em Hospitais — Outras Modalidades", sub: "Propriedade LYDA alocada em cliente", count: g.outros, color: "#64748B", jump: "'ATIVO'" },
        { label: "Estoque da LYDA — Novos", sub: "Equipamentos novos na sede", count: g.novos, color: "#10B981", jump: "'ESTOQUE_NOVOS'" },
        { label: "Estoque da LYDA — Usados", sub: "Usados disponíveis na sede", count: g.usados, color: "#34D399", jump: "'ESTOQUE_USADOS'" },
        { label: "Estoque da LYDA — Backup / Retorno", sub: "Backup ou devolvidos", count: g.backup, color: "#A7F3D0", jump: "'ESTOQUE_BACKUP'" },
        { label: "Manutenção / Reparo (SP)", sub: "Assistência técnica ou defeito", count: g.manut, color: "#E11D48", jump: "'DEFEITO'" },
      ].filter(sg => sg.count > 0);
    }

    const r = 62;
    const circ = 2 * Math.PI * r;
    let offsetAcc = 0;
    const circlesSvg = segments.map(seg => {
      const frac = seg.count / total;
      const dash = frac * circ;
      const gap = circ - dash;
      const rotOffset = -offsetAcc;
      offsetAcc += dash;
      return `<circle cx="85" cy="85" r="${r}" fill="transparent" stroke="${seg.color}" stroke-width="22" stroke-dasharray="${dash.toFixed(2)} ${gap.toFixed(2)}" stroke-dashoffset="${rotOffset.toFixed(2)}" transform="rotate(-90 85 85)" style="cursor:pointer;" onclick="dashJumpFilter(${seg.jump});"><title>${seg.label}: ${seg.count} (${formatRealPct(seg.count, total)})</title></circle>`;
    }).join("");

    const legendHtml = segments.map(seg => `
      <div class="dash-legend-item" onclick="dashJumpFilter(${seg.jump});">
        <div class="dash-legend-left">
          <span class="dash-legend-dot" style="background:${seg.color};"></span>
          <div>
            <div class="dash-legend-title">${escapeHtml(seg.label)}</div>
            <div class="dash-legend-sub">${escapeHtml(seg.sub)}</div>
          </div>
        </div>
        <div class="dash-legend-right">
          <span class="dash-legend-count">${seg.count}</span>
          <span class="dash-legend-pct">${formatRealPct(seg.count, total)}</span>
        </div>
      </div>`).join("");

    const typePillsHtml = mode === "COMPLETO" ? `
      <div style="font-size:11px; font-weight:700; color:var(--slate-600);">Por tipo de aparelho (${items.length} no total):</div>
      <div class="dash-donut-type-pills">
        ${typeSegs.map(ts => `
          <div class="dash-type-pill" onclick="dashJumpFilter(${ts.jump});">
            <span style="display:flex; align-items:center; gap:6px; font-size:11px; font-weight:800; color:var(--slate-700);">
              <span class="dash-legend-dot" style="background:${ts.color};"></span>${ts.label}
            </span>
            <span style="font-size:17px; font-weight:900; color:var(--slate-900);">${ts.count}</span>
            <span style="font-size:10.5px; color:var(--slate-500);">${formatRealPct(ts.count, total)} do total</span>
          </div>`).join("")}
      </div>` : "";

    donutWrap.innerHTML = `
      <div class="dash-donut-wrapper">
        <div style="display:flex; align-items:center; gap:22px; flex-wrap:wrap;">
          <div class="dash-donut-svg-wrap">
            <svg width="170" height="170" viewBox="0 0 170 170">
              <circle cx="85" cy="85" r="${r}" fill="transparent" stroke="#F1F5F9" stroke-width="22"></circle>
              ${circlesSvg}
            </svg>
            <div class="dash-donut-center">
              <span class="dc-val">${items.length}</span>
              <span class="dc-lbl">Aparelhos</span>
            </div>
          </div>
          <div class="dash-legend-list">${legendHtml}</div>
        </div>
        ${typePillsHtml}
      </div>
    `;
  }

  // 3. Gráfico 2: Barras Horizontais de Modalidade Comercial
  const modWrap = document.getElementById("divDashBarsModalidade");
  if (modWrap) {
    const modCounts = {
      "PROPRIEDADE LYDA": 0,
      "VENDA": 0,
      "COMODATO": 0,
      "ALUGUEL": 0,
    };
    items.forEach(it => {
      const m = String(it.MODALIDADE || "PROPRIEDADE LYDA").toUpperCase();
      if (modCounts[m] !== undefined) modCounts[m]++;
      else modCounts["PROPRIEDADE LYDA"]++;
    });

    const modRows = [
      { key: "PROPRIEDADE LYDA", title: "Propriedade LYDA (Estoque / Sede)", color: "#10B981", badge: "badge-em-dia" },
      { key: "VENDA", title: "Venda (Equipamentos Vendidos a Clientes)", color: "#6366F1", badge: "badge-dwl" },
      { key: "COMODATO", title: "Comodato (Patrimônio LYDA em Hospitais)", color: "#0284C7", badge: "badge-sim" },
      { key: "ALUGUEL", title: "Aluguel / Locação Temporária", color: "#F59E0B", badge: "badge-vencendo" },
    ];

    modWrap.innerHTML = modRows.map(mr => {
      const c = modCounts[mr.key] || 0;
      const pct = (c / total) * 100;
      return `
        <div class="dash-bar-row" onclick="switchTab('tab-estoque'); resetAllFilters(); document.getElementById('selFilterModalidade').value='${mr.key}'; renderItemsTable();">
          <div class="dash-bar-top">
            <span class="dash-bar-label">
              <span style="width:9px; height:9px; border-radius:50%; background:${mr.color}; display:inline-block;"></span>
              <span>${escapeHtml(mr.title)}</span>
            </span>
            <span class="dash-bar-stats">
              <span>${c} ap.</span>
              <span class="badge ${mr.badge}" style="font-size:10px; padding:1px 6px;">${formatRealPct(c, total)}</span>
            </span>
          </div>
          <div class="dash-bar-track">
            <div class="dash-bar-fill" style="width:${Math.max(c > 0 ? 4 : 0, pct)}%; background:${mr.color};"></div>
          </div>
        </div>
      `;
    }).join("");
  }

  // 4. Gráfico 3: Ciclo de Atualização Semestral (6m) & Tipos de Equipamento
  const cycTypesWrap = document.getElementById("divDashCycleAndTypes");
  if (cycTypesWrap) {
    const cOk = k.ciclo_em_dia || 0;
    const cVencendo = k.ciclo_vencendo || 0;
    const cVencida = k.ciclo_vencida || 0;
    const cSemData = k.ciclo_sem_data || 0;

    const pOk = (cOk / total) * 100;
    const pVencendo = (cVencendo / total) * 100;
    const pVencida = (cVencida / total) * 100;
    const pSemData = Math.max(0, 100 - pOk - pVencendo - pVencida);

    cycTypesWrap.innerHTML = `
      <div style="font-size:11px; font-weight:700; color:var(--slate-600); margin-bottom:5px; display:flex; justify-content:space-between;">
        <span> Termômetro Semestral (CLEW / JAMS de 6 em 6 Meses):</span>
        <span>${cOk} em dia • ${cntPend6m} pendentes</span>
      </div>
      <div class="dash-cycle-stacked-bar">
        <div style="width:${pOk}%; background:#10B981;" title="Em Dia: ${cOk}"></div>
        <div style="width:${pVencendo}%; background:#F59E0B;" title="Perto de 6m: ${cVencendo}"></div>
        <div style="width:${pVencida}%; background:#E11D48;" title="Vencidos: ${cVencida}"></div>
        <div style="width:${pSemData}%; background:#94A3B8;" title="Sem Data Base: ${cSemData}"></div>
      </div>

      <div class="dash-cycle-grid">
        <div class="dash-cycle-box" style="border-left:3px solid #10B981;" onclick="switchTab('tab-radar6m'); setRadarSubFilter('EM_DIA');">
          <div class="dcb-val" style="color:#059669;">${cOk}</div>
          <div class="dcb-lbl">Em Dia (6m)</div>
        </div>
        <div class="dash-cycle-box" style="border-left:3px solid #F59E0B;" onclick="switchTab('tab-radar6m'); setRadarSubFilter('VENCENDO');">
          <div class="dcb-val" style="color:#D97706;">${cVencendo}</div>
          <div class="dcb-lbl">Perto 6m (<=45d)</div>
        </div>
        <div class="dash-cycle-box" style="border-left:3px solid #E11D48;" onclick="switchTab('tab-radar6m'); setRadarSubFilter('VENCIDA');">
          <div class="dcb-val" style="color:#E11D48;">${cVencida}</div>
          <div class="dcb-lbl">Vencidos (>6m)</div>
        </div>
        <div class="dash-cycle-box" style="border-left:3px solid #64748B;" onclick="switchTab('tab-radar6m'); setRadarSubFilter('SEM_DATA');">
          <div class="dcb-val" style="color:#475569;">${cSemData}</div>
          <div class="dcb-lbl">Sem Data Base</div>
        </div>
      </div>

      <div style="font-size:11px; font-weight:700; color:var(--slate-600); margin-bottom:6px;">
        Composição por Categoria de Equipamento i-STAT:
      </div>
      <div class="dash-type-grid">
        <div class="dash-type-pill" onclick="switchTab('tab-estoque'); resetAllFilters(); document.getElementById('selFilterTipo').value='ANALISADOR'; renderItemsTable();">
          <span class="badge badge-ana" style="align-self:flex-start;">ANALISADOR</span>
          <span style="font-size:18px; font-weight:900; color:var(--slate-900); margin-top:2px;">${cntAna}</span>
          <span style="font-size:10.5px; color:var(--slate-500);">${formatRealPct(cntAna, total)} do total</span>
        </div>
        <div class="dash-type-pill" onclick="switchTab('tab-estoque'); resetAllFilters(); document.getElementById('selFilterTipo').value='IMPRESSORA'; renderItemsTable();">
          <span class="badge badge-imp" style="align-self:flex-start;">IMPRESSORA</span>
          <span style="font-size:18px; font-weight:900; color:#6B21A8; margin-top:2px;">${cntImp}</span>
          <span style="font-size:10.5px; color:var(--slate-500);">${formatRealPct(cntImp, total)} do total</span>
        </div>
        <div class="dash-type-pill" onclick="switchTab('tab-estoque'); resetAllFilters(); document.getElementById('selFilterTipo').value='SIMULADOR'; renderItemsTable();">
          <span class="badge badge-sim" style="align-self:flex-start;">SIMULADOR</span>
          <span style="font-size:18px; font-weight:900; color:#0369A1; margin-top:2px;">${cntSim}</span>
          <span style="font-size:10.5px; color:var(--slate-500);">${formatRealPct(cntSim, total)} do total</span>
        </div>
        <div class="dash-type-pill" onclick="switchTab('tab-estoque'); resetAllFilters(); document.getElementById('selFilterTipo').value='DOWNLOADER'; renderItemsTable();">
          <span class="badge badge-dwl" style="align-self:flex-start;">DOWNLOADER</span>
          <span style="font-size:18px; font-weight:900; color:#3730A3; margin-top:2px;">${cntDwl}</span>
          <span style="font-size:10.5px; color:var(--slate-500);">${formatRealPct(cntDwl, total)} do total</span>
        </div>
      </div>
    `;
  }

  // 5. Gráfico 4: Top Cidades / Regiões do RS Atendidas
  const cidWrap = document.getElementById("divDashBarsCidades");
  if (cidWrap) {
    const cityMap = {};
    items.forEach(it => {
      const city = String(it.CIDADE || "PORTO ALEGRE").trim().toUpperCase();
      const uf = String(it.UF || "RS").trim().toUpperCase();
      const key = `${city} / ${uf}`;
      if (!cityMap[key]) cityMap[key] = { city: city, key: key, count: 0, hospitals: new Set() };
      cityMap[key].count++;
      if (it.CLIENTE && !String(it.CLIENTE).toUpperCase().includes("SEM CLIENTE")) {
        cityMap[key].hospitals.add(it.CLIENTE);
      }
    });

    const topCities = Object.values(cityMap)
      .sort((a, b) => b.count - a.count)
      .slice(0, 5);
    const maxCityCount = Math.max(1, topCities[0] ? topCities[0].count : 1);
    const cityColors = ["#2563EB", "#0284C7", "#0D9488", "#4F46E5", "#7C3AED"];

    cidWrap.innerHTML = topCities.map((cObj, idx) => {
      const pctBar = Math.round((cObj.count / maxCityCount) * 100);
      const pctTotal = (cObj.count / total) * 100;
      const color = cityColors[idx % cityColors.length];
      const safeCityJs = escapeHtml(cObj.city).replace(/\\/g, "\\\\").replace(/'/g, "\\'");
      const hospCount = cObj.hospitals.size;
      return `
        <div class="dash-bar-row" onclick="switchTab('tab-estoque'); resetAllFilters(); document.getElementById('inpFilterSearch').value='${safeCityJs}'; renderItemsTable();">
          <div class="dash-bar-top">
            <span class="dash-bar-label">
              <span style="width:9px; height:9px; border-radius:2px; background:${color}; display:inline-block;"></span>
              <span>${escapeHtml(cObj.key)}</span>
              <span style="font-size:11px; font-weight:500; color:var(--slate-500);">(${hospCount} ${hospCount === 1 ? 'local' : 'locais'})</span>
            </span>
            <span class="dash-bar-stats">
              <span>${cObj.count} ap.</span>
              <span class="badge badge-ana" style="font-size:10px; padding:1px 6px;">${formatRealPct(cObj.count, total)}</span>
            </span>
          </div>
          <div class="dash-bar-track">
            <div class="dash-bar-fill" style="width:${Math.max(6, pctBar)}%; background:${color};"></div>
          </div>
        </div>
      `;
    }).join("");
  }

  // 6. Tabela Inferior Esquerda: Top 10 Hospitais / Clientes com Mais Aparelhos
  const tbodyTopCli = document.getElementById("tbodyDashTopClients");
  if (tbodyTopCli) {
    const sortedClients = [...clients]
      .sort((a, b) => (b._total_aparelhos || 0) - (a._total_aparelhos || 0))
      .slice(0, 10);

    tbodyTopCli.innerHTML = sortedClients.map(c => {
      const totalAp = c._total_aparelhos || 0;
      const pend6m = c._pendentes_6m || 0;
      const emManut = c._em_manutencao || 0;
      const modsTxt = c._modalidades_ativas || "COMODATO / VENDA";
      const setoresTxt = c._setores_ativos || c.SETORES || "-";
      const safeNameJs = escapeHtml(c.CLIENTE).replace(/\\/g, "\\\\").replace(/'/g, "\\'");
      const rowCls = String(modsTxt).toUpperCase().includes("COMODATO") ? "row-comodato" : "row-venda";
      let statusBadge = pend6m > 0
        ? `<span class="badge badge-vencendo">${pend6m} pend. 6m</span>`
        : `<span class="badge badge-em-dia">6m Em Dia</span>`;
      if (emManut > 0) {
        statusBadge += ` <span class="badge badge-vencida">${emManut} manut.</span>`;
      }

      return `
        <tr class="${rowCls}" style="cursor:pointer;" onclick="switchTab('tab-clientes'); selectClientRecord('${safeNameJs}');">
          <td>
            <div class="cell-primary">${escapeHtml(c.CLIENTE)}</div>
            <div class="cell-sub">${escapeHtml(c.ENDERECO || "Endereço cadastrado na ficha")}</div>
          </td>
          <td>
            <div class="cell-primary">${escapeHtml(c.CIDADE || "PORTO ALEGRE")} / ${escapeHtml(c.UF || "RS")}</div>
          </td>
          <td style="max-width:210px;">
            <div class="cell-primary">${escapeHtml(modsTxt)}</div>
            <div class="cell-sub" style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${escapeHtml(setoresTxt)}">${escapeHtml(setoresTxt)}</div>
          </td>
          <td style="text-align:center;">
            <span class="badge badge-ana" style="font-size:12px; padding:3px 9px;">${totalAp} ap.</span>
          </td>
          <td>${statusBadge}</td>
          <td style="text-align:right; white-space:nowrap;" onclick="event.stopPropagation()">
            <button class="btn btn-secondary btn-sm" onclick="switchTab('tab-clientes'); selectClientRecord('${safeNameJs}');">Abrir Ficha</button>
          </td>
        </tr>
      `;
    }).join("");
  }

  // 7. Painel Inferior Direito: Últimas Movimentações & Atividades
  const actWrap = document.getElementById("divDashRecentActivity");
  if (actWrap) {
    const recent = (APP_STATE.history || []).slice(0, 12);
    if (!recent.length) {
      actWrap.innerHTML = `<div style="text-align:center; padding:28px; color:var(--slate-500); font-size:12px;">Nenhuma movimentação recente registrada.</div>`;
    } else {
      actWrap.innerHTML = recent.map(h => {
        const acao = String(h.ACAO || "MOVIMENTAÇÃO");
        let dotColor = "#2563EB";
        if (acao.includes("ESTOQUE") || acao.includes("ENTRADA")) dotColor = "#10B981";
        else if (acao.includes("DEFEITO") || acao.includes("EXCLU")) dotColor = "#E11D48";
        else if (acao.includes("ROTA")) dotColor = "#D97706";

        return `
          <div class="dash-activity-item">
            <span class="dash-activity-dot" style="background:${dotColor};"></span>
            <div style="flex:1; min-width:0;">
              <div style="display:flex; align-items:center; justify-content:space-between; gap:8px;">
                <span style="font-size:12px; font-weight:800; color:var(--slate-900);">${escapeHtml(acao)} — SN: ${escapeHtml(h.CODIGO_BARRAS || "-")}</span>
                <span style="font-size:10.5px; color:var(--slate-500); white-space:nowrap;">${escapeHtml(h.DATA_HORA || "")}</span>
              </div>
              <div style="font-size:11.5px; font-weight:600; color:var(--primary); margin-top:2px;">
                ${escapeHtml(h.CLIENTE || "Estoque LYDA")} • Operador: ${escapeHtml(h.OPERADOR || h.RESPONSAVEL || "LYDA")}
              </div>
              <div style="font-size:11px; color:var(--slate-600); margin-top:2px; line-height:1.35;">
                ${escapeHtml(h.DETALHES || "")}
              </div>
            </div>
          </div>
        `;
      }).join("");
    }
  }
}

// GERADOR DE RELATÓRIOS EXECUTIVOS A4 / PDF (PRONTOS PARA IMPRIMIR OU SALVAR PDF)
function openExecutiveReportPrintWindow(reportType = "GERAL") {
  const items = APP_STATE.items || [];
  const clients = APP_STATE.clients || [];
  const k = APP_STATE.kpis || {};
  const nowStr = new Date().toLocaleString("pt-BR");
  const userStr = (APP_STATE.current_user && APP_STATE.current_user.nome) || "Administrador LYDA";
  const logoImg = APP_STATE.logo_data_uri
    ? `<img src="${APP_STATE.logo_data_uri}" style="height:42px; width:auto; object-fit:contain;" alt="LYDA" />`
    : `<strong style="font-size:24px; color:#0F172A;">LYDA</strong>`;

  const cycBadge = it => {
    const code = (it._cycle && it._cycle.status_code) || "SEM_DATA";
    const txt = escapeHtml((it._cycle && it._cycle.summary_table) || "PENDENTE");
    const cls = code === "EM_DIA" ? "b-ok" : code === "VENCIDA" ? "b-bad" : code === "VENCENDO" ? "b-warn" : "b-gray";
    return `<span class="badge ${cls}">${txt}</span>`;
  };
  const modBadge = it => {
    const m = String(it.MODALIDADE || "-").toUpperCase();
    const cls = (m === "COMODATO" || m === "ALUGUEL") ? "b-sky" : m === "VENDA" ? "b-ind" : "b-gray";
    return `<span class="badge ${cls}">${escapeHtml(it.MODALIDADE || "-")}</span>`;
  };
  const tipoBadge = it => {
    const t = String(it.TIPO || "ANALISADOR").toUpperCase();
    const cls = t.includes("IMPRESSORA") ? "b-pur" : t.includes("SIMULADOR") ? "b-teal" : t.includes("DOWNLOAD") ? "b-amb" : "b-blue";
    return `<span class="badge ${cls}">${escapeHtml(it.TIPO || "-")}</span>`;
  };

  let reportTitle = "Relatório Executivo Geral de Equipamentos i-STAT";
  let reportSub = "Mapeamento completo de analisadores, impressoras, simuladores, downloaders, modalidades e ciclo semestral";
  let tableHtml = "";

  if (reportType === "GERAL") {
    tableHtml = `
      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>Tipo</th>
            <th>Serial</th>
            <th>Hospital / Cliente / Local</th>
            <th>Cidade / UF</th>
            <th>Setor</th>
            <th>Modalidade</th>
            <th>Situação</th>
            <th>Últ. Atualiz.</th>
            <th>Ciclo 6m</th>
          </tr>
        </thead>
        <tbody>
          ${items.map((it, i) => `
            <tr class="${it._row_state === 'ESTOQUE' ? 'tr-est' : (it._row_state === 'DEFEITO' ? 'tr-def' : '')}">
              <td>${i + 1}</td>
              <td>${tipoBadge(it)}</td>
              <td style="font-family:monospace; font-weight:800;">${escapeHtml(it.CODIGO)}</td>
              <td><strong>${escapeHtml(it.CLIENTE || "-")}</strong></td>
              <td>${escapeHtml(it.CIDADE || "-")} / ${escapeHtml(it.UF || "RS")}</td>
              <td>${escapeHtml(it.SETOR || "-")}</td>
              <td>${modBadge(it)}</td>
              <td>${escapeHtml(it.STATUS || "-")}</td>
              <td>${escapeHtml(it.ULTIMA_ATUALIZACAO || "-")}</td>
              <td>${cycBadge(it)}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    `;
  } else if (reportType === "RADAR_6M") {
    reportTitle = "Relatório de Controle de Atualizações Semestrais (Ciclo 6 em 6 Meses)";
    reportSub = "Equipamentos próximos de completar 6 meses, com ciclo vencido, aguardando bancada ou sem data base registrada";
    const pendItems = items.filter(it => isItemNeedingRadarAttention(it));
    tableHtml = `
      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>Tipo</th>
            <th>Serial</th>
            <th>Hospital / Cliente</th>
            <th>Endereço Completo</th>
            <th>Cidade / UF</th>
            <th>Setor</th>
            <th>Últ. Atualização</th>
            <th>Próx. Atualização (+6m)</th>
            <th>Status do Ciclo</th>
          </tr>
        </thead>
        <tbody>
          ${pendItems.map((it, i) => `
            <tr>
              <td>${i + 1}</td>
              <td>${tipoBadge(it)}</td>
              <td style="font-family:monospace; font-weight:800;">${escapeHtml(it.CODIGO)}</td>
              <td><strong>${escapeHtml(it.CLIENTE || "-")}</strong></td>
              <td>${escapeHtml(it.ENDERECO || "-")}</td>
              <td>${escapeHtml(it.CIDADE || "-")} / ${escapeHtml(it.UF || "RS")}</td>
              <td>${escapeHtml(it.SETOR || "-")}</td>
              <td>${escapeHtml(it.ULTIMA_ATUALIZACAO || "Sem data")}</td>
              <td>${escapeHtml((it._cycle && it._cycle.next_date_str) || "Imediata")}</td>
              <td>${cycBadge(it)}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    `;
  } else if (reportType === "HOSPITAIS") {
    reportTitle = "Relatório Consolidado da Carteira de Hospitais & Clientes";
    reportSub = "Relação de todas as instituições atendidas pela LYDA, endereços, setores, modalidades e seriais vinculados";
    tableHtml = `
      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>Hospital / Clínica / Cliente</th>
            <th>Cidade / UF</th>
            <th>Endereço Cadastrado</th>
            <th>Modalidades</th>
            <th>Setores Atendidos</th>
            <th>Total Ap.</th>
            <th>Seriais Vinculados</th>
          </tr>
        </thead>
        <tbody>
          ${clients.map((c, i) => {
            const cItems = items.filter(it => (it.CLIENTE || "").toUpperCase() === (c.CLIENTE || "").toUpperCase());
            const seriais = cItems.map(it => `${it.CODIGO} (${it.TIPO.slice(0,3)})`).join(", ");
            return `
              <tr>
                <td>${i + 1}</td>
                <td><strong>${escapeHtml(c.CLIENTE)}</strong></td>
                <td>${escapeHtml(c.CIDADE || "PORTO ALEGRE")} / ${escapeHtml(c.UF || "RS")}</td>
                <td>${escapeHtml(c.ENDERECO || "-")}</td>
                <td>${escapeHtml(c._modalidades_ativas || "-")}</td>
                <td>${escapeHtml(c._setores_ativos || c.SETORES || "-")}</td>
                <td style="text-align:center; font-weight:800;">${c._total_aparelhos || 0}</td>
                <td style="font-family:monospace; font-size:10.5px;">${escapeHtml(seriais || "-")}</td>
              </tr>
            `;
          }).join("")}
        </tbody>
      </table>
    `;
  } else if (reportType === "MANUTENCAO") {
    reportTitle = "Relatório de Equipamentos em Manutenção, Reparo ou Devolvidos";
    reportSub = "Aparelhos i-STAT com registro de defeito, em assistência técnica ou devolvidos com observação";
    const defItems = items.filter(it => it._row_state === "DEFEITO");
    tableHtml = `
      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>Tipo</th>
            <th>Serial</th>
            <th>Local / Origem</th>
            <th>Cidade / UF</th>
            <th>Status Atual</th>
            <th>Condição Física</th>
            <th>Defeito / Observações Técnicas</th>
          </tr>
        </thead>
        <tbody>
          ${defItems.map((it, i) => `
            <tr class="tr-def">
              <td>${i + 1}</td>
              <td>${tipoBadge(it)}</td>
              <td style="font-family:monospace; font-weight:800;">${escapeHtml(it.CODIGO)}</td>
              <td><strong>${escapeHtml(it.CLIENTE || "-")}</strong></td>
              <td>${escapeHtml(it.CIDADE || "-")} / ${escapeHtml(it.UF || "RS")}</td>
              <td>${escapeHtml(it.STATUS || "-")}</td>
              <td>${escapeHtml(it.CONDICAO || "-")}</td>
              <td><strong>${escapeHtml([it.DEFEITO, it.OBSERVACOES].filter(Boolean).join(" — ") || "-")}</strong></td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    `;
  }

  // Resumo visual (distribuicao por situacao/modalidade e por tipo)
  const totalAll = Math.max(1, items.length);
  const g = { com: 0, vnd: 0, outros: 0, novos: 0, usados: 0, backup: 0, manut: 0 };
  const tp = { ANALISADOR: 0, IMPRESSORA: 0, SIMULADOR: 0, DOWNLOADER: 0 };
  items.forEach(it => {
    const t = String(it.TIPO || "ANALISADOR").toUpperCase();
    if (t.includes("IMPRESSORA")) tp.IMPRESSORA++;
    else if (t.includes("SIMULADOR")) tp.SIMULADOR++;
    else if (t.includes("DOWNLOAD")) tp.DOWNLOADER++;
    else tp.ANALISADOR++;
    const st = it._row_state || "ATIVO";
    if (st === "DEFEITO") { g.manut++; return; }
    if (st === "ESTOQUE") {
      const sg = classifyStockSubgroup(it);
      if (sg === "NOVOS") g.novos++; else if (sg === "USADOS") g.usados++; else g.backup++;
      return;
    }
    const m = String(it.MODALIDADE || "").toUpperCase();
    if (m === "COMODATO" || m === "ALUGUEL") g.com++;
    else if (m === "VENDA") g.vnd++;
    else g.outros++;
  });
  const barRow = (label, count, color) => `
    <div class="bar-row">
      <div class="bar-label">${escapeHtml(label)}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${Math.max(count > 0 ? 2 : 0, (count / totalAll) * 100).toFixed(1)}%; background:${color};"></div></div>
      <div class="bar-val"><strong>${count}</strong> <span>${formatRealPct(count, totalAll)}</span></div>
    </div>`;
  const summaryHtml = `
    <div class="summary-grid">
      <div class="summary-card">
        <h3>Distribuição por Situação e Modalidade</h3>
        ${barRow("Hospitais — Comodato", g.com, "#0284C7")}
        ${barRow("Hospitais — Venda", g.vnd, "#6366F1")}
        ${g.outros > 0 ? barRow("Hospitais — Outras", g.outros, "#64748B") : ""}
        ${barRow("Estoque LYDA — Novos", g.novos, "#10B981")}
        ${barRow("Estoque LYDA — Usados", g.usados, "#34D399")}
        ${barRow("Estoque LYDA — Backup", g.backup, "#6EE7B7")}
        ${barRow("Manutenção / Reparo", g.manut, "#E11D48")}
      </div>
      <div class="summary-card">
        <h3>Distribuição por Tipo de Equipamento</h3>
        ${barRow("Analisador", tp.ANALISADOR, "#2563EB")}
        ${barRow("Impressora", tp.IMPRESSORA, "#7C3AED")}
        ${barRow("Simulador", tp.SIMULADOR, "#0D9488")}
        ${barRow("Downloader", tp.DOWNLOADER, "#F59E0B")}
        <h3 style="margin-top:12px;">Ciclo de Atualização (6 meses)</h3>
        ${barRow("Em dia", k.ciclo_em_dia || 0, "#10B981")}
        ${barRow("Perto de 6 meses", k.ciclo_vencendo || 0, "#F59E0B")}
        ${barRow("Vencidos", k.ciclo_vencida || 0, "#E11D48")}
        ${barRow("Sem data base", k.ciclo_sem_data || 0, "#94A3B8")}
      </div>
    </div>`;
  const defCountRep = k.defeito_manutencao ?? k.em_defeito ?? 0;
  // Analises avancadas: cidades, hospitais, donut e destaques
  const cityMapR = {};
  const cliMapR = {};
  items.forEach(it => {
    const city = `${String(it.CIDADE || "PORTO ALEGRE").trim().toUpperCase()} / ${String(it.UF || "RS").trim().toUpperCase()}`;
    cityMapR[city] = (cityMapR[city] || 0) + 1;
    const cli = String(it.CLIENTE || "").trim();
    if (cli && it._row_state !== "ESTOQUE" && !cli.toUpperCase().includes("SEM CLIENTE")) {
      if (!cliMapR[cli]) cliMapR[cli] = { n: 0, pend: 0, manut: 0 };
      cliMapR[cli].n++;
      const cc = (it._cycle && it._cycle.status_code) || "SEM_DATA";
      if (cc !== "EM_DIA") cliMapR[cli].pend++;
      if (it._row_state === "DEFEITO") cliMapR[cli].manut++;
    }
  });
  const topCitiesR = Object.entries(cityMapR).sort((a, b) => b[1] - a[1]).slice(0, 8);
  const topClientsR = Object.entries(cliMapR).sort((a, b) => b[1].n - a[1].n).slice(0, 10);
  const maxClientN = Math.max(1, topClientsR[0] ? topClientsR[0][1].n : 1);

  const donutSegs = [
    ["Hospitais — Comodato", g.com, "#0284C7"], ["Hospitais — Venda", g.vnd, "#6366F1"], ["Hospitais — Outras", g.outros, "#64748B"],
    ["Estoque — Novos", g.novos, "#10B981"], ["Estoque — Usados", g.usados, "#34D399"], ["Estoque — Backup", g.backup, "#6EE7B7"],
    ["Manutenção / Reparo", g.manut, "#E11D48"],
  ].filter(x => x[1] > 0);
  const dR = 52, dC = 2 * Math.PI * dR;
  let dAcc = 0;
  const donutCircles = donutSegs.map(([lb, c, col]) => {
    const dash = (c / totalAll) * dC;
    const out = `<circle cx="70" cy="70" r="${dR}" fill="none" stroke="${col}" stroke-width="20" stroke-dasharray="${dash.toFixed(2)} ${(dC - dash).toFixed(2)}" stroke-dashoffset="${(-dAcc).toFixed(2)}" transform="rotate(-90 70 70)"/>`;
    dAcc += dash;
    return out;
  }).join("");
  const donutLegend = donutSegs.map(([lb, c, col]) => `
    <div class="lg-row"><span class="lg-dot" style="background:${col};"></span><span class="lg-name">${escapeHtml(lb)}</span><span class="lg-val"><strong>${c}</strong> ${formatRealPct(c, totalAll)}</span></div>`).join("");

  const analyticsHtml = `
    <div class="summary-grid">
      <div class="summary-card">
        <h3>Composição do Parque por Situação</h3>
        <div class="donut-box">
          <svg width="140" height="140" viewBox="0 0 140 140">
            <circle cx="70" cy="70" r="${dR}" fill="none" stroke="#F1F5F9" stroke-width="20"/>
            ${donutCircles}
            <text x="70" y="68" text-anchor="middle" font-size="24" font-weight="900" fill="#0F172A">${items.length}</text>
            <text x="70" y="84" text-anchor="middle" font-size="9" font-weight="700" fill="#64748B">APARELHOS</text>
          </svg>
          <div class="lg-list">${donutLegend}</div>
        </div>
      </div>
      <div class="summary-card">
        <h3>Principais Cidades Atendidas</h3>
        ${topCitiesR.map(([c, n]) => barRow(c, n, "#2563EB")).join("")}
      </div>
    </div>`;

  const rankingHtml = `
    <div class="summary-card" style="margin-bottom:16px; page-break-inside:avoid;">
      <h3>Ranking dos Hospitais e Clientes por Volume de Equipamentos</h3>
      <table class="mini-table">
        <thead><tr><th style="width:28px;">#</th><th>Hospital / Cliente</th><th style="width:60px;">Aparelhos</th><th style="width:34%;">Volume</th><th style="width:70px;">Pend. 6m</th><th style="width:70px;">Manut.</th></tr></thead>
        <tbody>
          ${topClientsR.map(([nm, o], i) => `
            <tr>
              <td>${i + 1}</td>
              <td><strong>${escapeHtml(nm)}</strong></td>
              <td><strong>${o.n}</strong></td>
              <td><div class="bar-track"><div class="bar-fill" style="width:${((o.n / maxClientN) * 100).toFixed(0)}%; background:#2563EB;"></div></div></td>
              <td>${o.pend > 0 ? `<span class="badge b-warn">${o.pend}</span>` : `<span class="badge b-ok">0</span>`}</td>
              <td>${o.manut > 0 ? `<span class="badge b-bad">${o.manut}</span>` : `<span class="badge b-gray">0</span>`}</td>
            </tr>`).join("")}
        </tbody>
      </table>
    </div>`;

  const nVenc = k.ciclo_vencida || 0, nVencendo = k.ciclo_vencendo || 0, nSem = k.ciclo_sem_data || 0, nBanc = k.estoque_falta_atualizar || 0;
  const insights = [];
  insights.push(["#0284C7", `<strong>${formatRealPct(k.em_cliente || 0, totalAll)}</strong> do parque (${k.em_cliente || 0} aparelhos) está em operação em <strong>${(clients || []).length}</strong> hospitais e clínicas.`]);
  insights.push(["#10B981", `O estoque da LYDA reúne <strong>${k.em_estoque || 0}</strong> aparelhos (${k.estoque_novos || 0} novos, ${k.estoque_usados || 0} usados e ${k.estoque_backup || 0} em backup/retorno).`]);
  if (nVenc > 0) insights.push(["#E11D48", `<strong>${nVenc}</strong> aparelho(s) estão com o ciclo de 6 meses <strong>vencido</strong> e exigem atualização imediata.`]);
  if (nVencendo > 0) insights.push(["#F59E0B", `<strong>${nVencendo}</strong> aparelho(s) completam 6 meses em até 45 dias.`]);
  if (nSem > 0) insights.push(["#64748B", `<strong>${nSem}</strong> aparelho(s) ainda não possuem data base de atualização registrada.`]);
  if (nBanc > 0) insights.push(["#D97706", `<strong>${nBanc}</strong> aparelho(s) do estoque aguardam atualização na bancada.`]);
  if (defCountRep > 0) insights.push(["#E11D48", `<strong>${defCountRep}</strong> aparelho(s) em manutenção ou reparo (${k.defeito_em_cliente || 0} em hospitais e ${k.defeito_em_estoque || 0} no estoque).`]);
  if (topClientsR[0]) insights.push(["#2563EB", `Maior carteira: <strong>${escapeHtml(topClientsR[0][0])}</strong> com ${topClientsR[0][1].n} aparelho(s).`]);
  if (topCitiesR[0]) insights.push(["#6366F1", `Cidade com mais equipamentos: <strong>${escapeHtml(topCitiesR[0][0])}</strong> (${topCitiesR[0][1]}).`]);
  const insightsHtml = `
    <div class="insights-card">
      <h3>Destaques e Pontos de Atenção</h3>
      <ul>${insights.map(([col, txt]) => `<li><span class="lg-dot" style="background:${col};"></span><span>${txt}</span></li>`).join("")}</ul>
    </div>`;

  const cycleBoxesHtml = `
    <div class="cycle-boxes">
      <div class="cbox" style="border-top-color:#10B981;"><div class="v" style="color:#059669;">${k.ciclo_em_dia || 0}</div><div class="l">Em dia</div></div>
      <div class="cbox" style="border-top-color:#F59E0B;"><div class="v" style="color:#D97706;">${nVencendo}</div><div class="l">Perto de 6 meses</div></div>
      <div class="cbox" style="border-top-color:#E11D48;"><div class="v" style="color:#E11D48;">${nVenc}</div><div class="l">Vencidos</div></div>
      <div class="cbox" style="border-top-color:#94A3B8;"><div class="v" style="color:#475569;">${nSem}</div><div class="l">Sem data base</div></div>
      <div class="cbox" style="border-top-color:#D97706;"><div class="v" style="color:#B45309;">${nBanc}</div><div class="l">Aguardando bancada</div></div>
    </div>`;

  let richSections = "";
  if (reportType === "GERAL") richSections = insightsHtml + summaryHtml + analyticsHtml + rankingHtml;
  else if (reportType === "RADAR_6M") richSections = insightsHtml + cycleBoxesHtml;
  else if (reportType === "HOSPITAIS") richSections = insightsHtml + rankingHtml;
  else richSections = insightsHtml + summaryHtml;

  const signatureHtml = `
    <div class="signature-row">
      <div><div class="line"></div><span>Responsável pela emissão — ${escapeHtml(userStr)}</span></div>
      <div><div class="line"></div><span>Conferido por</span></div>
      <div><div class="line"></div><span>Data da conferência</span></div>
    </div>`;

  const kpiBox = (lbl, val, color) => `
    <div class="kpi-box" style="border-top-color:${color};">
      <div class="lbl">${lbl}</div>
      <div class="val" style="color:${color};">${val}</div>
      <div class="pct">${formatRealPct(val, totalAll)} do total</div>
    </div>`;
  const recordCount = (tableHtml.match(/<tr/g) || []).length - 1;

  const html = `
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
      <meta charset="UTF-8" />
      <title>${escapeHtml(reportTitle)} — LYDA</title>
      <style>
        @page { size: A4 landscape; margin: 10mm 10mm 14mm 10mm; }
        * { box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif; color: #0F172A; margin: 0; padding: 22px 26px 40px 26px; font-size: 11.5px; background: #FFFFFF; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
        .no-print-bar { background: #0F172A; color: #FFF; padding: 11px 18px; border-radius: 10px; margin-bottom: 18px; display: flex; align-items: center; justify-content: space-between; }
        .no-print-bar button { background: #2563EB; color: #FFF; border: none; padding: 8px 16px; border-radius: 7px; font-weight: 700; cursor: pointer; font-size: 12px; }
        .cover { background: linear-gradient(135deg, #0F172A 0%, #1E3A8A 100%); color: #FFFFFF; border-radius: 12px; padding: 18px 24px; display: flex; align-items: center; justify-content: space-between; gap: 20px; margin-bottom: 14px; }
        .cover .logo-box { background: #FFFFFF; border-radius: 9px; padding: 8px 14px; display: flex; align-items: center; }
        .cover .left { display: flex; align-items: center; gap: 18px; }
        .cover h1 { margin: 0; font-size: 19px; font-weight: 800; letter-spacing: -0.3px; }
        .cover p { margin: 4px 0 0 0; font-size: 11.5px; color: #CBD5E1; max-width: 560px; line-height: 1.4; }
        .cover .meta { text-align: right; font-size: 11px; color: #CBD5E1; line-height: 1.7; }
        .cover .meta strong { color: #FFFFFF; }
        .cover .tag { display: inline-block; background: rgba(96,165,250,0.25); border: 1px solid rgba(147,197,253,0.5); color: #BFDBFE; font-size: 9.5px; font-weight: 800; letter-spacing: 0.7px; text-transform: uppercase; padding: 2px 9px; border-radius: 99px; margin-bottom: 6px; }
        .kpi-strip { display: grid; grid-template-columns: repeat(7, 1fr); gap: 8px; margin-bottom: 14px; }
        .kpi-box { border: 1px solid #E2E8F0; border-top: 4px solid #2563EB; border-radius: 8px; padding: 9px 11px; background: #F8FAFC; }
        .kpi-box .lbl { font-size: 9.5px; font-weight: 800; text-transform: uppercase; color: #475569; letter-spacing: 0.3px; }
        .kpi-box .val { font-size: 22px; font-weight: 900; margin-top: 2px; line-height: 1.1; }
        .kpi-box .pct { font-size: 10px; color: #64748B; font-weight: 600; margin-top: 2px; }
        .summary-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 16px; page-break-inside: avoid; }
        .summary-card { border: 1px solid #E2E8F0; border-radius: 10px; padding: 11px 14px; background: #FFFFFF; }
        .summary-card h3 { margin: 0 0 8px 0; font-size: 11px; font-weight: 800; text-transform: uppercase; letter-spacing: 0.4px; color: #334155; border-bottom: 1px solid #E2E8F0; padding-bottom: 5px; }
        .bar-row { display: grid; grid-template-columns: 150px 1fr 90px; align-items: center; gap: 8px; margin-bottom: 5px; }
        .bar-label { font-size: 10.5px; font-weight: 700; color: #1E293B; }
        .bar-track { height: 9px; background: #F1F5F9; border-radius: 99px; overflow: hidden; }
        .bar-fill { height: 100%; border-radius: 99px; }
        .bar-val { font-size: 10.5px; text-align: right; white-space: nowrap; }
        .bar-val span { color: #64748B; font-weight: 600; margin-left: 3px; }
        .section-head { display: flex; align-items: center; justify-content: space-between; margin: 4px 0 8px 0; }
        .section-head h2 { margin: 0; font-size: 13px; font-weight: 800; color: #0F172A; border-left: 4px solid #2563EB; padding-left: 9px; }
        .section-head span { font-size: 10.5px; color: #64748B; font-weight: 600; }
        table { width: 100%; border-collapse: separate; border-spacing: 0; font-size: 10.5px; border: 1px solid #CBD5E1; border-radius: 8px; overflow: hidden; }
        thead { display: table-header-group; }
        th { background: #0F172A; color: #FFF; text-align: left; padding: 8px 9px; font-size: 9.5px; text-transform: uppercase; letter-spacing: 0.4px; font-weight: 800; }
        td { border-bottom: 1px solid #E2E8F0; padding: 6px 9px; vertical-align: middle; }
        tbody tr:nth-child(even) td { background: #F8FAFC; }
        tr { page-break-inside: avoid; }
        tr.tr-est td { background: #ECFDF5 !important; }
        tr.tr-def td { background: #FFF1F2 !important; }
        tr.tr-est td:first-child { border-left: 3px solid #10B981; }
        tr.tr-def td:first-child { border-left: 3px solid #E11D48; }
        .doc-footer { margin-top: 14px; padding-top: 8px; border-top: 1px solid #CBD5E1; display: flex; justify-content: space-between; font-size: 9.5px; color: #64748B; }
        .badge { display: inline-block; padding: 2px 8px; border-radius: 99px; font-size: 9.5px; font-weight: 800; white-space: nowrap; border: 1px solid transparent; }
        .b-ok { background: #D1FAE5; color: #065F46; border-color: #6EE7B7; }
        .b-warn { background: #FEF3C7; color: #92400E; border-color: #FCD34D; }
        .b-bad { background: #FFE4E6; color: #9F1239; border-color: #FDA4AF; }
        .b-gray { background: #F1F5F9; color: #475569; border-color: #CBD5E1; }
        .b-sky { background: #E0F2FE; color: #075985; border-color: #7DD3FC; }
        .b-ind { background: #E0E7FF; color: #3730A3; border-color: #A5B4FC; }
        .b-pur { background: #F3E8FF; color: #6B21A8; border-color: #D8B4FE; }
        .b-teal { background: #CCFBF1; color: #115E59; border-color: #5EEAD4; }
        .b-amb { background: #FEF3C7; color: #92400E; border-color: #FCD34D; }
        .b-blue { background: #DBEAFE; color: #1E40AF; border-color: #93C5FD; }
        .insights-card { border: 1px solid #BFDBFE; background: #EFF6FF; border-radius: 10px; padding: 11px 16px; margin-bottom: 14px; page-break-inside: avoid; }
        .insights-card h3 { margin: 0 0 7px 0; font-size: 11px; font-weight: 800; text-transform: uppercase; letter-spacing: 0.4px; color: #1E3A8A; }
        .insights-card ul { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: 1fr 1fr; gap: 5px 20px; }
        .insights-card li { display: flex; gap: 8px; align-items: flex-start; font-size: 11px; line-height: 1.4; color: #1E293B; }
        .lg-dot { width: 9px; height: 9px; border-radius: 3px; flex-shrink: 0; margin-top: 3px; display: inline-block; }
        .donut-box { display: flex; align-items: center; gap: 16px; }
        .lg-list { flex: 1; display: flex; flex-direction: column; gap: 4px; }
        .lg-row { display: flex; align-items: center; gap: 7px; font-size: 10.5px; }
        .lg-row .lg-dot { margin-top: 0; }
        .lg-name { flex: 1; font-weight: 700; color: #1E293B; }
        .lg-val { color: #475569; white-space: nowrap; }
        table.mini-table { font-size: 10.5px; }
        table.mini-table td, table.mini-table th { padding: 5px 8px; }
        .cycle-boxes { display: grid; grid-template-columns: repeat(5, 1fr); gap: 8px; margin-bottom: 14px; }
        .cbox { border: 1px solid #E2E8F0; border-top: 4px solid #2563EB; border-radius: 8px; padding: 9px 12px; background: #F8FAFC; }
        .cbox .v { font-size: 24px; font-weight: 900; line-height: 1.1; }
        .cbox .l { font-size: 10px; font-weight: 800; text-transform: uppercase; color: #475569; margin-top: 2px; }
        .signature-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 40px; margin-top: 34px; page-break-inside: avoid; }
        .signature-row .line { border-top: 1px solid #0F172A; margin-bottom: 4px; }
        .signature-row span { font-size: 10px; color: #475569; font-weight: 600; }
        @media print {
          .no-print-bar { display: none !important; }
          body { padding: 0; }
          .doc-footer { position: fixed; bottom: 0; left: 0; right: 0; background: #FFFFFF; margin: 0; padding: 4px 0 0 0; }
        }
      </style>
    </head>
    <body>
      <div class="no-print-bar">
        <span><strong>Visualização Oficial de Impressão A4 / PDF</strong> — ${escapeHtml(reportTitle)}</span>
        <div style="display:flex; gap:8px;">
          <button onclick="window.print()">Imprimir / Salvar como PDF</button>
          <button style="background:#475569;" onclick="window.close()">Fechar</button>
        </div>
      </div>
      <div class="cover">
        <div class="left">
          <div class="logo-box">${logoImg}</div>
          <div>
            <span class="tag">Relatório Oficial LYDA i-STAT</span>
            <h1>${escapeHtml(reportTitle)}</h1>
            <p>${escapeHtml(reportSub)}</p>
          </div>
        </div>
        <div class="meta">
          <div><strong>Emissão:</strong> ${escapeHtml(nowStr)}</div>
          <div><strong>Emitido por:</strong> ${escapeHtml(userStr)}</div>
          <div><strong>Registros listados:</strong> ${recordCount}</div>
        </div>
      </div>
      <div class="kpi-strip">
        ${kpiBox("Total Cadastrados", k.total || 0, "#2563EB")}
        ${kpiBox("Em Hospitais", k.em_cliente || 0, "#0284C7")}
        ${kpiBox("No Estoque LYDA", k.em_estoque || 0, "#10B981")}
        ${kpiBox("Em Comodato", k.comodato_aluguel || 0, "#0369A1")}
        ${kpiBox("Venda (Clientes)", k.venda || 0, "#6366F1")}
        ${kpiBox("Pendentes 6m", k.ciclo_pendente_vencido || 0, "#D97706")}
        ${kpiBox("Manutenção / Reparo", defCountRep, "#E11D48")}
      </div>
      ${richSections}
      <div class="section-head">
        <h2>Detalhamento</h2>
        <span>${recordCount} registro(s)</span>
      </div>
      ${tableHtml}
      ${signatureHtml}
      <div class="doc-footer">
        <span>LYDA — Controle de Estoque &amp; Rotas i-STAT</span>
        <span>${escapeHtml(reportTitle)} • Emitido em ${escapeHtml(nowStr)}</span>
      </div>
    </body>
    </html>
  `;

  const win = window.open("", "_blank");
  if (win) {
    win.document.open();
    win.document.write(html);
    win.document.close();
  }
}

// =========================================================================
// ESTÚDIO DE IMPRESSÃO DE ETIQUETAS ZEBRA ZD230 (BOBINA GRANDE + LOGO LYDA)
// =========================================================================
let zebraPreviewPageMode = "ALL"; // "ALL" (mostra todas as folhas roláveis) ou índice 0, 1, 2...
let zebraConfigInitialized = false;
let zebraInitialSelectionApplied = false;
let zebraActivePresetId = "BOBINA_100x150_2x5";

const ZEBRA_PRESET_MAP = {
  BOBINA_100x150_2x5: { bigW: 100, bigH: 150, cols: 2, rows: 5, border: true, cut: true },
  BOBINA_100x150_2x6: { bigW: 100, bigH: 150, cols: 2, rows: 6, border: true, cut: true },
  BOBINA_100x150_3x6: { bigW: 100, bigH: 150, cols: 3, rows: 6, border: true, cut: true },
  BOBINA_100x100_2x4: { bigW: 100, bigH: 100, cols: 2, rows: 4, border: true, cut: true },
  DUPLA_100x25_2x1:   { bigW: 100, bigH: 25,  cols: 2, rows: 1, border: false, cut: false },
  INDIV_50x25_1x1:    { bigW: 50,  bigH: 25,  cols: 1, rows: 1, border: false, cut: false },
  INDIV_60x40_1x1:    { bigW: 60,  bigH: 40,  cols: 1, rows: 1, border: false, cut: false },
  KIT_100x60_2x2:     { bigW: 100, bigH: 60,  cols: 2, rows: 2, border: true, cut: true },
};

function initZebraFormFromServerConfig(zCfg) {
  if (!zCfg || zebraConfigInitialized) return;
  zebraConfigInitialized = true;

  const setVal = (id, v) => {
    const el = document.getElementById(id);
    if (el && v !== undefined && v !== null) el.value = v;
  };
  const setChk = (id, v) => {
    const el = document.getElementById(id);
    if (el && v !== undefined && v !== null) el.checked = Boolean(v);
  };

  zebraActivePresetId = zCfg.preset_id || "BOBINA_100x150_2x5";
  setVal("selZebraPresetDropdown", zebraActivePresetId);
  setVal("inpZebraBigW", zCfg.big_width_mm ?? 100);
  setVal("inpZebraBigH", zCfg.big_height_mm ?? 150);
  setVal("inpZebraCols", zCfg.cols ?? 2);
  setVal("inpZebraRows", zCfg.rows ?? 5);
  setVal("inpZebraGapH", zCfg.gap_h_mm ?? 2.0);
  setVal("inpZebraGapV", zCfg.gap_v_mm ?? 2.0);
  setVal("inpZebraMargin", zCfg.margin_left_mm ?? 3.0);
  setVal("inpZebraCopies", zCfg.copies_per_item ?? 1);
  setVal("inpZebraSkip", zCfg.skip_slots ?? 0);

  setChk("chkZebraShowLogo", zCfg.show_logo !== false);
  setChk("chkZebraDrawBorder", zCfg.draw_border !== false);
  setChk("chkZebraCutMarks", zCfg.draw_cut_marks !== false);
  setChk("chkZebraShowEq", zCfg.show_equipamento !== false);
  setChk("chkZebraShowSn", zCfg.show_serial_line !== false);
  setChk("chkZebraShowLocation", zCfg.show_location !== undefined ? Boolean(zCfg.show_location) : true);

  setVal("inpZebraHeaderText", zCfg.header_text || "i-STAT");
  setVal("inpZebraLogoDots", zCfg.logo_height_dots ?? 26);
  setVal("selZebraBarcodeType", zCfg.barcode_type || "CODE128");
  setVal("inpZebraBarcodeH", zCfg.barcode_height_mm ?? 10);

  setVal("selZebraConnMode", zCfg.mode || "USB_DRIVER");
  if (zCfg.printer_name) {
    const selPrn = document.getElementById("selZebraPrinter");
    if (selPrn && Array.from(selPrn.options).some(o => o.value === zCfg.printer_name)) {
      selPrn.value = zCfg.printer_name;
    }
  }
  setVal("inpZebraIp", zCfg.ip_address || "192.168.0.200");
  setVal("inpZebraPort", zCfg.port ?? 9100);
  setVal("inpZebraDarkness", zCfg.darkness ?? 18);
  setVal("inpZebraSpeed", zCfg.print_speed ?? 4);
  setVal("selZebraDpi", zCfg.dpi ?? 203);

  onZebraConnModeChange();
}

function toggleZebraAdvancedDrawer(forceState) {
  const drw = document.getElementById("divZebraAdvancedDrawer");
  if (!drw) return;
  const isOpen = drw.style.display !== "none";
  const next = typeof forceState === "boolean" ? forceState : !isOpen;
  drw.style.display = next ? "block" : "none";
  if (next) {
    previewZplForSelected();
  }
}

function onZebraPresetDropdownChange(presetId) {
  if (presetId === "CUSTOM") {
    zebraActivePresetId = "CUSTOM";
    toggleZebraAdvancedDrawer(true);
    return;
  }
  const p = ZEBRA_PRESET_MAP[presetId];
  if (!p) return;
  applyZebraPaperPreset(presetId, p.bigW, p.bigH, p.cols, p.rows, p.border, p.cut);
}

function applyZebraPaperPreset(presetId, bigW, bigH, cols, rows, drawBorder, cutMarks) {
  zebraActivePresetId = presetId;
  const setVal = (id, v) => { const el = document.getElementById(id); if (el) el.value = v; };
  const setChk = (id, v) => { const el = document.getElementById(id); if (el) el.checked = Boolean(v); };

  setVal("selZebraPresetDropdown", presetId);
  setVal("inpZebraBigW", bigW);
  setVal("inpZebraBigH", bigH);
  setVal("inpZebraCols", cols);
  setVal("inpZebraRows", rows);
  setVal("inpZebraSkip", 0);

  if (cols === 1 && rows === 1) {
    setVal("inpZebraGapH", 0);
    setVal("inpZebraGapV", 0);
    setVal("inpZebraMargin", 1.5);
  } else {
    setVal("inpZebraGapH", 2.0);
    setVal("inpZebraGapV", 2.0);
    setVal("inpZebraMargin", 3.0);
  }

  setChk("chkZebraDrawBorder", drawBorder);
  setChk("chkZebraCutMarks", cutMarks);

  zebraPreviewPageMode = "ALL";
  renderZebraVisualPreview();
}

function onZebraManualDimensionChange() {
  zebraActivePresetId = "CUSTOM";
  const sel = document.getElementById("selZebraPresetDropdown");
  if (sel) sel.value = "CUSTOM";
  zebraPreviewPageMode = "ALL";
  renderZebraVisualPreview();
}

function syncLocationCheckboxes() {
  renderZebraVisualPreview();
}

function onZebraConnModeChange() {
  const modeEl = document.getElementById("selZebraConnMode");
  const mode = (modeEl && modeEl.value) || "USB_DRIVER";
  const usbGrp = document.getElementById("grpZebraUsbPrinter");
  const tcpGrp = document.getElementById("grpZebraTcpIp");
  if (usbGrp) usbGrp.style.display = mode === "USB_DRIVER" ? "flex" : "none";
  if (tcpGrp) tcpGrp.style.display = mode === "TCP_IP" ? "flex" : "none";
}

async function refreshZebraPrintersList() {
  try {
    const res = await fetch("/api/zebra/config");
    const data = await res.json();
    if (data.ok) {
      APP_STATE.config.printers = data.printers || [];
      const selPrn = document.getElementById("selZebraPrinter");
      if (selPrn) {
        const printers = data.printers || [];
        selPrn.innerHTML = printers.length
          ? printers.map(p => `<option value="${escapeHtml(p)}">${escapeHtml(p)}</option>`).join("")
          : `<option value="">Nenhuma impressora detectada no Servidor</option>`;
      }
      showToast(`${(data.printers || []).length} impressora(s) detectada(s) no computador.`, "info");
    }
  } catch (e) {
    showToast("Erro ao atualizar lista de impressoras.", "error");
  }
}

function collectZebraConfigPayload() {
  const numVal = (id, defVal) => {
    const el = document.getElementById(id);
    if (!el) return defVal;
    const v = parseFloat(el.value);
    return Number.isFinite(v) ? v : defVal;
  };
  const chkVal = (id, defVal) => {
    const el = document.getElementById(id);
    return el ? Boolean(el.checked) : defVal;
  };
  const strVal = (id, defVal) => {
    const el = document.getElementById(id);
    return el ? String(el.value || "").trim() : defVal;
  };

  const margin = Math.max(0, numVal("inpZebraMargin", 3.0));
  return {
    preset_id: zebraActivePresetId || "BOBINA_100x150_2x5",
    big_width_mm: Math.max(25, numVal("inpZebraBigW", 100)),
    big_height_mm: Math.max(15, numVal("inpZebraBigH", 150)),
    margin_left_mm: margin,
    margin_top_mm: margin,
    cols: Math.max(1, Math.min(6, Math.round(numVal("inpZebraCols", 2)))),
    rows: Math.max(1, Math.min(15, Math.round(numVal("inpZebraRows", 5)))),
    gap_h_mm: Math.max(0, numVal("inpZebraGapH", 2.0)),
    gap_v_mm: Math.max(0, numVal("inpZebraGapV", 2.0)),
    skip_slots: Math.max(0, Math.round(numVal("inpZebraSkip", 0))),
    copies_per_item: Math.max(1, Math.min(20, Math.round(numVal("inpZebraCopies", 1)))),
    draw_border: chkVal("chkZebraDrawBorder", true),
    draw_cut_marks: chkVal("chkZebraCutMarks", true),
    show_logo: chkVal("chkZebraShowLogo", true),
    logo_height_dots: Math.max(12, Math.min(65, Math.round(numVal("inpZebraLogoDots", 26)))),
    show_header: true,
    header_text: strVal("inpZebraHeaderText", "i-STAT") || "i-STAT",
    show_equipamento: chkVal("chkZebraShowEq", true),
    show_serial_line: chkVal("chkZebraShowSn", true),
    show_location: chkVal("chkZebraShowLocation", true),
    barcode_type: strVal("selZebraBarcodeType", "CODE128") || "CODE128",
    barcode_height_mm: Math.max(4, Math.min(30, numVal("inpZebraBarcodeH", 10))),
    show_barcode_text: true,
    mode: strVal("selZebraConnMode", "USB_DRIVER") || "USB_DRIVER",
    printer_name: strVal("selZebraPrinter", ""),
    ip_address: strVal("inpZebraIp", "192.168.0.200"),
    port: Math.round(numVal("inpZebraPort", 9100)),
    darkness: Math.max(5, Math.min(30, Math.round(numVal("inpZebraDarkness", 18)))),
    print_speed: Math.max(2, Math.min(6, Math.round(numVal("inpZebraSpeed", 4)))),
    dpi: Math.round(numVal("selZebraDpi", 203)),
  };
}

function computeMiniDimensionsMm(cfg) {
  const usableW = Math.max(10, cfg.big_width_mm - 2 * cfg.margin_left_mm - (cfg.cols - 1) * cfg.gap_h_mm);
  const usableH = Math.max(10, cfg.big_height_mm - 2 * cfg.margin_top_mm - (cfg.rows - 1) * cfg.gap_v_mm);
  const mw = Math.max(8, usableW / Math.max(1, cfg.cols));
  const mh = Math.max(8, usableH / Math.max(1, cfg.rows));
  return { mw, mh };
}

function generateBarcodeSvgHtml(codeStr, heightPx = 19) {
  const s = String(codeStr || "000000").trim() || "000000";
  const bars = [];
  let x = 3;
  const h = Math.max(12, Math.round(heightPx));
  [2, 1, 1, 2, 3, 1].forEach((w, idx) => {
    if (idx % 2 === 0) bars.push(`<rect x="${x}" y="0" width="${w}" height="${h}" fill="#000000"/>`);
    x += w;
  });
  for (let i = 0; i < s.length; i++) {
    const ch = s.charCodeAt(i);
    const w1 = (ch % 3) + 1;
    const s1 = ((ch >> 1) % 2) + 1;
    const w2 = ((ch >> 2) % 3) + 1;
    const s2 = ((ch >> 3) % 2) + 1;
    bars.push(`<rect x="${x}" y="0" width="${w1}" height="${h}" fill="#000000"/>`);
    x += w1 + s1;
    bars.push(`<rect x="${x}" y="0" width="${w2}" height="${h}" fill="#000000"/>`);
    x += w2 + s2;
  }
  [2, 3, 1, 1, 2].forEach((w, idx) => {
    if (idx % 2 === 0) bars.push(`<rect x="${x}" y="0" width="${w}" height="${h}" fill="#000000"/>`);
    x += w;
  });
  return `<svg viewBox="0 0 ${x + 3} ${h}" preserveAspectRatio="none" style="width:90%; max-width:155px; height:${h}px; display:block;">${bars.join("")}</svg>`;
}

function generateQrSvgHtml(codeStr, sizePx = 26) {
  const s = String(codeStr || "000000");
  const cells = 7;
  const rects = [];
  for (let r = 0; r < cells; r++) {
    for (let c = 0; c < cells; c++) {
      const isCorner = (r < 2 && c < 2) || (r < 2 && c >= cells - 2) || (r >= cells - 2 && c < 2);
      const hashBit = ((r * 7 + c * 13 + s.charCodeAt((r + c) % s.length)) % 3) === 0;
      if (isCorner || hashBit) {
        rects.push(`<rect x="${c * 4}" y="${r * 4}" width="4" height="4" fill="#000000"/>`);
      }
    }
  }
  return `<svg viewBox="0 0 28 28" style="width:${sizePx}px; height:${sizePx}px; display:block; border:1px solid #0F172A; padding:1px; background:#FFF;">${rects.join("")}</svg>`;
}

function getZebraSelectedIndicesArray() {
  return Array.from(APP_STATE.zebraSelectedIndices || []);
}

function renderZebraStudio() {
  initZebraFormFromServerConfig(APP_STATE.config && APP_STATE.config.zebra_config);

  const items = APP_STATE.items || [];

  // Na primeira vez que abre a aba da Zebra e não há nenhum marcado, seleciona todos APENAS na fila da Zebra
  // (sem marcar nada na tabela de Estoque & Mapeamento!)
  if (!zebraInitialSelectionApplied && items.length > 0 && APP_STATE.zebraSelectedIndices.size === 0) {
    zebraInitialSelectionApplied = true;
    items.forEach(it => APP_STATE.zebraSelectedIndices.add(it._idx));
  }

  // Atualiza contadores nos botões rápidos (Todos / Estoque / Hospitais / Comodato / Venda / Manutenção)
  const stockCount = items.filter(it => it._row_state === "ESTOQUE").length;
  const hospCount = items.filter(it => it._row_state === "ATIVO").length;
  const comodatoCount = items.filter(it => ["COMODATO", "ALUGUEL"].includes(String(it.MODALIDADE || "").toUpperCase())).length;
  const vendaCount = items.filter(it => String(it.MODALIDADE || "").toUpperCase() === "VENDA").length;
  const maintCount = items.filter(it => it._row_state === "DEFEITO").length;
  const setTxt = (id, v) => { const el = document.getElementById(id); if (el) el.innerText = v; };
  setTxt("lblBtnZebraAllCount", `Todos os Aparelhos (${items.length})`);
  setTxt("lblBtnZebraStockCount", `Só Estoque LYDA (${stockCount})`);
  setTxt("lblBtnZebraHospCount", `Só em Hospitais (${hospCount})`);
  setTxt("lblBtnZebraComodatoCount", `Só Comodato (${comodatoCount})`);
  setTxt("lblBtnZebraVendaCount", `Só Venda (${vendaCount})`);
  setTxt("lblBtnZebraMaintCount", `Em Manutenção / SP (${maintCount})`);

  // Popula dropdown de filtro por Local / Hospital na lista da Zebra
  const selLocal = document.getElementById("selZebraFilterLocal");
  if (selLocal) {
    const prevVal = selLocal.value || "TODOS";
    const uniqueClients = Array.from(
      new Set(
        items
          .map(it => (it.CLIENTE || "").trim())
          .filter(c => c && !c.toUpperCase().includes("SEM CLIENTE"))
      )
    ).sort();
    selLocal.innerHTML = [
      `<option value="TODOS">Todos os Locais / Hospitais (${items.length})</option>`,
      `<option value="__ESTOQUE__">Somente Estoque LYDA (${stockCount})</option>`,
      `<option value="__HOSPITAIS__">Somente em Hospitais (${hospCount})</option>`,
      `<option value="__COMODATO__">Somente em Comodato (${comodatoCount})</option>`,
      `<option value="__VENDA__">Somente Venda / Clientes (${vendaCount})</option>`,
      `<option value="__MANUTENCAO__">Somente em Manutenção / SP (${maintCount})</option>`,
      ...uniqueClients.map(c => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`),
    ].join("");
    if (Array.from(selLocal.options).some(o => o.value === prevVal)) {
      selLocal.value = prevVal;
    }
  }

  renderZebraItemsChecklist();
  renderZebraVisualPreview();
}

function getFilteredZebraChecklistItems() {
  const items = APP_STATE.items || [];
  const qEl = document.getElementById("inpZebraFilterSearch");
  const tipoEl = document.getElementById("selZebraFilterTipo");
  const locEl = document.getElementById("selZebraFilterLocal");

  const q = ((qEl && qEl.value) || "").trim().toUpperCase();
  const fTipo = (tipoEl && tipoEl.value) || "TODOS";
  const fLoc = (locEl && locEl.value) || "TODOS";

  return items.filter(it => {
    if (fTipo !== "TODOS" && String(it.TIPO || "").toUpperCase() !== fTipo) return false;
    const modU = String(it.MODALIDADE || "").toUpperCase();
    if (fLoc === "__ESTOQUE__" && it._row_state !== "ESTOQUE") return false;
    if (fLoc === "__HOSPITAIS__" && it._row_state !== "ATIVO") return false;
    if (fLoc === "__COMODATO__" && !["COMODATO", "ALUGUEL"].includes(modU)) return false;
    if (fLoc === "__VENDA__" && modU !== "VENDA") return false;
    if (fLoc === "__MANUTENCAO__" && it._row_state !== "DEFEITO") return false;
    if (!["TODOS", "__ESTOQUE__", "__HOSPITAIS__", "__COMODATO__", "__VENDA__", "__MANUTENCAO__"].includes(fLoc)) {
      if (String(it.CLIENTE || "").trim().toUpperCase() !== fLoc.toUpperCase()) return false;
    }
    if (q) {
      const hay = [it.CODIGO, it.TIPO, it.CLIENTE, it.SETOR, it.CIDADE, it.MODALIDADE].join(" ").toUpperCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}

function renderZebraItemsChecklist() {
  const tbody = document.getElementById("tbodyZebraChecklist");
  if (!tbody) return;

  const filtered = getFilteredZebraChecklistItems();
  const selCount = APP_STATE.zebraSelectedIndices.size;

  const badge = document.getElementById("badgeZebraQueueCount");
  if (badge) {
    badge.innerText = `${selCount} selecionado(s)`;
    badge.className = selCount > 0 ? "badge badge-em-dia" : "badge badge-ana";
  }

  const masterChk = document.getElementById("chkZebraMasterAll");
  if (masterChk) {
    masterChk.checked = filtered.length > 0 && filtered.every(it => APP_STATE.zebraSelectedIndices.has(it._idx));
  }

  if (!filtered.length) {
    tbody.innerHTML = `<tr><td colspan="4" style="text-align:center; padding:20px; color:var(--slate-500);">Nenhum aparelho para este filtro.</td></tr>`;
    return;
  }

  tbody.innerHTML = filtered.map(it => {
    const isSel = APP_STATE.zebraSelectedIndices.has(it._idx);
    const rowColor = typeof getItemRowColorClass === "function" ? getItemRowColorClass(it, false) : "";
    const upperCli = String(it.CLIENTE || "").toUpperCase();
    const upperSt = String(it.STATUS || "").toUpperCase();
    const isStock = !upperCli || upperCli.includes("SEM CLIENTE") || upperCli.includes("ESTOQUE") || upperSt.includes("ESTOQUE") || upperCli === "LYDA";
    const locName = isStock ? "ESTOQUE LYDA" : it.CLIENTE;
    return `
      <tr class="${rowColor} ${isSel ? 'row-selected' : ''}" style="cursor:pointer;" onclick="toggleSingleZebraItem(${it._idx})">
        <td style="text-align:center;" onclick="event.stopPropagation()">
          <input type="checkbox" ${isSel ? "checked" : ""} onchange="toggleSingleZebraItem(${it._idx}, this.checked)" />
        </td>
        <td style="font-family:monospace; font-weight:900; font-size:12px;">${escapeHtml(it.CODIGO)}</td>
        <td>${getTipoBadgeHtml(it.TIPO)}</td>
        <td style="max-width:190px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${escapeHtml(locName)}">
          <strong>${escapeHtml(locName)}</strong>
        </td>
      </tr>
    `;
  }).join("");
}

function toggleSingleZebraItem(idx, forceState) {
  const has = APP_STATE.zebraSelectedIndices.has(idx);
  const next = typeof forceState === "boolean" ? forceState : !has;
  if (next) APP_STATE.zebraSelectedIndices.add(idx);
  else APP_STATE.zebraSelectedIndices.delete(idx);

  renderZebraItemsChecklist();
  renderZebraVisualPreview();
}

function toggleZebraChecklistMaster(checked) {
  const filtered = getFilteredZebraChecklistItems();
  filtered.forEach(it => {
    if (checked) APP_STATE.zebraSelectedIndices.add(it._idx);
    else APP_STATE.zebraSelectedIndices.delete(it._idx);
  });
  renderZebraItemsChecklist();
  renderZebraVisualPreview();
}

function selectAllVisibleInZebraChecklist() {
  const filtered = getFilteredZebraChecklistItems();
  APP_STATE.zebraSelectedIndices.clear();
  filtered.forEach(it => APP_STATE.zebraSelectedIndices.add(it._idx));
  zebraPreviewPageMode = "ALL";
  renderZebraItemsChecklist();
  renderZebraVisualPreview();
  showToast(`${filtered.length} aparelho(s) do filtro selecionados para impressão!`, "success");
}

function selectZebraPresetGroup(groupMode) {
  const items = APP_STATE.items || [];
  APP_STATE.zebraSelectedIndices.clear();
  if (groupMode === "ALL") {
    items.forEach(it => APP_STATE.zebraSelectedIndices.add(it._idx));
    showToast(`Todos os ${items.length} aparelhos selecionados! Role o preview ao lado para ver todas as folhas.`, "success");
  } else if (groupMode === "ESTOQUE") {
    const est = items.filter(it => it._row_state === "ESTOQUE");
    est.forEach(it => APP_STATE.zebraSelectedIndices.add(it._idx));
    showToast(`${est.length} aparelhos do Estoque da LYDA selecionados!`, "success");
  } else if (groupMode === "HOSPITAIS") {
    const hosp = items.filter(it => it._row_state === "ATIVO");
    hosp.forEach(it => APP_STATE.zebraSelectedIndices.add(it._idx));
    showToast(`${hosp.length} aparelhos em Hospitais/Clientes selecionados!`, "success");
  } else if (groupMode === "COMODATO") {
    const com = items.filter(it => ["COMODATO", "ALUGUEL"].includes(String(it.MODALIDADE || "").toUpperCase()));
    com.forEach(it => APP_STATE.zebraSelectedIndices.add(it._idx));
    showToast(`${com.length} aparelhos em Comodato selecionados!`, "success");
  } else if (groupMode === "VENDA") {
    const vnd = items.filter(it => String(it.MODALIDADE || "").toUpperCase() === "VENDA");
    vnd.forEach(it => APP_STATE.zebraSelectedIndices.add(it._idx));
    showToast(`${vnd.length} aparelhos de Venda (Clientes) selecionados!`, "success");
  } else if (groupMode === "MANUTENCAO") {
    const maint = items.filter(it => it._row_state === "DEFEITO");
    maint.forEach(it => APP_STATE.zebraSelectedIndices.add(it._idx));
    showToast(`${maint.length} aparelhos em Manutenção / SP selecionados!`, "success");
  }
  zebraPreviewPageMode = "ALL";
  renderZebraItemsChecklist();
  renderZebraVisualPreview();
}

function clearZebraQueue() {
  zebraInitialSelectionApplied = true;
  APP_STATE.zebraSelectedIndices.clear();
  zebraPreviewPageMode = "ALL";
  renderZebraItemsChecklist();
  renderZebraVisualPreview();
}

function getEffectiveZebraPreviewRecords(cfg) {
  const items = APP_STATE.items || [];
  const selIndices = getZebraSelectedIndicesArray();
  const baseItems = selIndices.map(idx => items.find(x => x._idx === idx)).filter(Boolean);

  const out = [];
  const copies = Math.max(1, cfg.copies_per_item || 1);
  baseItems.forEach(it => {
    for (let c = 0; c < copies; c++) {
      out.push(it);
    }
  });
  return { records: out, isSample: false };
}

function setZebraPreviewPageMode(mode) {
  zebraPreviewPageMode = mode;
  renderZebraVisualPreview();
}

function toggleSkipSlotFromPreview(slotIdxOnFirstPage) {
  const skipEl = document.getElementById("inpZebraSkip");
  if (!skipEl) return;
  const curSkip = parseInt(skipEl.value || "0", 10);
  if (slotIdxOnFirstPage + 1 === curSkip) {
    skipEl.value = Math.max(0, slotIdxOnFirstPage);
  } else {
    skipEl.value = slotIdxOnFirstPage + 1;
  }
  renderZebraVisualPreview();
}

function renderZebraVisualPreview() {
  const stage = document.getElementById("divZebraVisualPreview");
  if (!stage) return;

  const cfg = collectZebraConfigPayload();
  const { mw, mh } = computeMiniDimensionsMm(cfg);
  const perBig = Math.max(1, cfg.cols * cfg.rows);
  const maxSkip = Math.max(0, perBig - 1);
  const skip = Math.min(maxSkip, cfg.skip_slots);

  const { records } = getEffectiveZebraPreviewRecords(cfg);
  const totalMini = records.length;
  const effectiveSlotsNeeded = totalMini > 0 ? totalMini + skip : 0;
  const totalBigPages = totalMini > 0 ? Math.max(1, Math.ceil(effectiveSlotsNeeded / perBig)) : 1;

  if (typeof zebraPreviewPageMode === "number" && zebraPreviewPageMode >= totalBigPages) {
    zebraPreviewPageMode = "ALL";
  }

  // Atualiza textos de resumo e botões
  const calcBanner = document.getElementById("divZebraCalcBanner");
  if (calcBanner) {
    if (perBig === 1) {
      calcBanner.innerHTML = `Papel Individual: <strong>${cfg.big_width_mm.toFixed(0)}×${cfg.big_height_mm.toFixed(0)} mm</strong> (1 etiqueta por vez, sem recorte).`;
    } else {
      calcBanner.innerHTML = `Cada Folha da Bobina (<strong>${cfg.big_width_mm.toFixed(0)}×${cfg.big_height_mm.toFixed(0)} mm</strong>) imprime <strong>${perBig} mini-etiquetas</strong> (${cfg.cols}×${cfg.rows}) de <strong>${mw.toFixed(1)} × ${mh.toFixed(1)} mm</strong>.`;
    }
  }

  const dimsLbl = document.getElementById("lblZebraRollerDims");
  if (dimsLbl) {
    dimsLbl.innerText = `Papel: ${cfg.big_width_mm.toFixed(0)}×${cfg.big_height_mm.toFixed(0)} mm | Grade: ${cfg.cols}×${cfg.rows} (${perBig} etiquetas de ${mw.toFixed(1)}×${mh.toFixed(1)} mm por folha)`;
  }

  const hdrTitle = document.getElementById("lblZebraPreviewHeaderTitle");
  if (hdrTitle) {
    hdrTitle.innerText = totalMini > 0
      ? `Pré-Visualização Completa: ${totalMini} Etiqueta(s) em ${totalBigPages} Folha(s)`
      : `Nenhum aparelho selecionado — Clique em "Todos os Aparelhos" ao lado`;
  }

  const selSummary = document.getElementById("lblZebraSelectionSummary");
  if (selSummary) {
    selSummary.innerHTML = totalMini > 0
      ? `Mostrando <strong>${zebraPreviewPageMode === "ALL" ? `Todas as ${totalBigPages} Folha(s)` : `Folha #${zebraPreviewPageMode + 1} de ${totalBigPages}`}</strong> • Role para baixo para ver todas as etiquetas.`
      : `Selecione os aparelhos na lista à esquerda para visualizar as folhas.`;
  }

  const topPrintBtn = document.getElementById("lblZebraTopPrintBtn");
  if (topPrintBtn) {
    topPrintBtn.innerText = totalMini > 0
      ? `Imprimir ${totalMini} Etiqueta(s) (${totalBigPages} Folha${totalBigPages > 1 ? 's' : ''}) na Zebra ZD230`
      : `Imprimir Selecionados na Zebra ZD230`;
  }

  const topPrnBtn = document.getElementById("lblZebraTopPrnBtn");
  if (topPrnBtn) {
    topPrnBtn.innerText = totalMini > 0
      ? `Baixar Arquivo .PRN (${totalMini} Etiquetas)`
      : `Baixar Arquivo .PRN`;
  }

  const footerPrnBtn = document.getElementById("lblZebraFooterPrnBtn");
  if (footerPrnBtn) {
    footerPrnBtn.innerText = totalMini > 0
      ? `Baixar Arquivo .PRN (${totalMini} Etiquetas / ${totalBigPages} Folha${totalBigPages > 1 ? 's' : ''})`
      : `Baixar Arquivo .PRN das Etiquetas`;
  }

  const btnMainTxt = document.getElementById("lblZebraPrintBtnText");
  if (btnMainTxt) {
    btnMainTxt.innerText = totalMini > 0
      ? `IMPRIMIR TODAS AS ${totalMini} ETIQUETAS (${totalBigPages} FOLHA${totalBigPages > 1 ? 'S' : ''}) NA ZEBRA ZD230`
      : `SELECIONE OS APARELHOS À ESQUERDA PARA IMPRIMIR`;
  }

  // Abas de seleção rápida de folha ("Todas (10) | Folha 1 | Folha 2...")
  const tabsWrap = document.getElementById("divZebraSheetTabs");
  if (tabsWrap) {
    const tabBtns = [
      `<button type="button" class="zebra-sheet-tab-btn ${zebraPreviewPageMode === 'ALL' ? 'active' : ''}" onclick="setZebraPreviewPageMode('ALL')">Ver Todas as Folhas (${totalBigPages})</button>`
    ];
    const maxTabs = Math.min(totalBigPages, 12);
    for (let p = 0; p < maxTabs; p++) {
      tabBtns.push(
        `<button type="button" class="zebra-sheet-tab-btn ${zebraPreviewPageMode === p ? 'active' : ''}" onclick="setZebraPreviewPageMode(${p})">Folha ${p + 1}</button>`
      );
    }
    tabsWrap.innerHTML = tabBtns.join("");
  }

  if (totalMini === 0) {
    stage.innerHTML = `
      <div style="background:#FFFFFF; border:2px dashed #94A3B8; border-radius:10px; padding:36px 24px; text-align:center; max-width:440px;">
        <div style="font-size:14px; font-weight:800; color:var(--slate-900); margin-bottom:6px;">Nenhum Aparelho Selecionado</div>
        <div style="font-size:12px; color:var(--slate-600); margin-bottom:14px;">Clique em um dos botões abaixo para carregar as etiquetas na folha:</div>
        <div style="display:flex; gap:8px; justify-content:center; flex-wrap:wrap;">
          <button type="button" class="btn btn-primary btn-sm" onclick="selectZebraPresetGroup('ALL')">Selecionar Todos os Aparelhos</button>
          <button type="button" class="btn btn-secondary btn-sm" onclick="selectZebraPresetGroup('ESTOQUE')">Selecionar Estoque LYDA</button>
        </div>
      </div>
    `;
    return;
  }

  // Monta a lista com as posições puladas na 1ª folha
  const paddedRecords = [];
  for (let s = 0; s < skip; s++) paddedRecords.push(null);
  records.forEach(r => paddedRecords.push(r));

  const pagesToRender = zebraPreviewPageMode === "ALL"
    ? Array.from({ length: totalBigPages }, (_, i) => i)
    : [zebraPreviewPageMode];

  const sheetsBlocksHtml = pagesToRender.map(pageIdx => {
    const startIdx = pageIdx * perBig;
    const pageRecords = paddedRecords.slice(startIdx, startIdx + perBig);
    const activeInThisSheet = pageRecords.filter(Boolean).length;

    const slotsHtml = [];
    for (let slotIdx = 0; slotIdx < perBig; slotIdx++) {
      const cIdx = slotIdx % cfg.cols;
      const isLastCol = cIdx === cfg.cols - 1;
      const cutRightCls = cfg.draw_cut_marks && !isLastCol ? "cut-guide-right" : "";
      const clickHandler = pageIdx === 0 ? `onclick="toggleSkipSlotFromPreview(${slotIdx})"` : "";

      if (slotIdx >= pageRecords.length) {
        slotsHtml.push(`
          <div class="zebra-mini-slot empty-slot ${cutRightCls}" ${clickHandler}>
            <span>(Posição Livre)</span>
          </div>
        `);
        continue;
      }

      const rec = pageRecords[slotIdx];
      if (rec === null) {
        slotsHtml.push(`
          <div class="zebra-mini-slot skipped-slot ${cutRightCls}" ${clickHandler} title="Clique para reativar esta posição">
            <div style="font-size:10px; font-weight:800; color:#475569;">(Posição #${slotIdx + 1} Pulada)</div>
            <div style="font-size:8.5px; color:#64748B;">Já Recortada • Clique p/ usar</div>
          </div>
        `);
        continue;
      }

      const borderCls = cfg.draw_border ? "with-border" : "no-border";
      const hdrLineCls = cfg.draw_border ? "" : "no-line";

      let headerHtml = "";
      if (cfg.show_logo && APP_STATE.logo_data_uri) {
        headerHtml = `
          <div class="z-mini-header ${hdrLineCls}">
            <img src="${APP_STATE.logo_data_uri}" alt="LYDA" class="z-mini-logo" />
            <span class="z-mini-hdr-txt">${escapeHtml(cfg.header_text)}</span>
          </div>
        `;
      } else if (cfg.header_text) {
        headerHtml = `
          <div class="z-mini-header ${hdrLineCls}" style="justify-content:center;">
            <span class="z-mini-hdr-txt">LYDA • ${escapeHtml(cfg.header_text)}</span>
          </div>
        `;
      }

      const fieldLines = [];
      if (cfg.show_equipamento) {
        fieldLines.push(`<div class="z-mini-line">EQ: ${escapeHtml(rec.TIPO || "ANALISADOR")}</div>`);
      }
      if (cfg.show_serial_line) {
        fieldLines.push(`<div class="z-mini-line">SN: ${escapeHtml(rec.CODIGO || "")}</div>`);
      }
      if (cfg.show_location) {
        const upperCli = String(rec.CLIENTE || "").toUpperCase();
        const upperSt = String(rec.STATUS || "").toUpperCase();
        const isStock = !upperCli || upperCli.includes("SEM CLIENTE") || upperCli.includes("ESTOQUE") || upperSt.includes("ESTOQUE") || upperCli === "LYDA";
        const cliStr = isStock ? "ESTOQUE LYDA" : rec.CLIENTE;
        fieldLines.push(`<div class="z-mini-line client-line">${escapeHtml(cliStr)}</div>`);
      }

      const codeVisual = cfg.barcode_type === "QRCODE"
        ? generateQrSvgHtml(rec.CODIGO, 26)
        : generateBarcodeSvgHtml(rec.CODIGO, 19);

      slotsHtml.push(`
        <div class="zebra-mini-slot ${borderCls} ${cutRightCls}" ${clickHandler} title="Folha #${pageIdx + 1} • Posição #${slotIdx + 1} (${rec.TIPO} ${rec.CODIGO})">
          ${headerHtml}
          <div class="z-mini-fields">
            ${fieldLines.join("")}
          </div>
          <div class="z-mini-barcode-wrap">
            ${codeVisual}
            <div class="z-mini-barcode-num">${escapeHtml(rec.CODIGO)}</div>
          </div>
        </div>
      `);
    }

    return `
      <div class="zebra-sheet-block">
        <div class="zebra-sheet-block-header">
          <span>FOLHA #${pageIdx + 1} DE ${totalBigPages} — Bobina ${cfg.big_width_mm.toFixed(0)}×${cfg.big_height_mm.toFixed(0)} mm (${activeInThisSheet} mini-etiqueta${activeInThisSheet > 1 ? 's' : ''})</span>
          <div style="display:flex; gap:6px; align-items:center;">
            <button type="button" class="btn btn-secondary btn-sm" style="height:24px; padding:0 10px; font-size:11px; background:#1E293B; color:#E2E8F0; border-color:#475569;" onclick="downloadZebraPrnFile(${pageIdx}, 'prn')" title="Baixar arquivo .PRN apenas desta folha">
              Baixar .PRN Folha #${pageIdx + 1}
            </button>
            <button type="button" class="btn btn-primary btn-sm" style="height:24px; padding:0 10px; font-size:11px;" onclick="printSingleZebraSheetByIndex(${pageIdx})">
              Imprimir Só Folha #${pageIdx + 1}
            </button>
          </div>
        </div>
        <div class="zebra-sheet-paper" style="padding:10px; gap:8px; grid-template-columns:repeat(${cfg.cols}, minmax(0, 1fr));">
          ${slotsHtml.join("")}
        </div>
      </div>
    `;
  });

  stage.innerHTML = sheetsBlocksHtml.join("");
}

async function saveZebraDefaultConfig() {
  const payload = collectZebraConfigPayload();
  try {
    const res = await fetch("/api/zebra/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (data.ok) {
      if (APP_STATE.config) APP_STATE.config.zebra_config = data.zebra_config;
      showToast(data.message || "Configuração padrão da Zebra ZD230 salva!", "success");
    } else {
      showToast(data.error || "Erro ao salvar configuração.", "error");
    }
  } catch (e) {
    showToast("Erro ao salvar configuração padrão da Zebra ZD230.", "error");
  }
}

async function printSingleZebraSheetByIndex(pageIdx) {
  const indices = getZebraSelectedIndicesArray();
  if (!indices.length) {
    showToast("Selecione pelo menos 1 aparelho para imprimir.", "error");
    return;
  }
  await printZebraIndices(indices, pageIdx);
}

async function printZebraForSelected(onlyFirstTestPage = false) {
  const indices = getZebraSelectedIndicesArray();
  if (!indices.length) {
    showToast("Clique em 'Todos os Aparelhos' ou 'Só Estoque LYDA' para selecionar o que imprimir.", "error");
    return;
  }
  const pageIdx = onlyFirstTestPage ? (typeof zebraPreviewPageMode === "number" ? zebraPreviewPageMode : 0) : null;
  await printZebraIndices(indices, pageIdx);
}

async function printZebraIndices(indices, specificPageIndex = null) {
  const payload = collectZebraConfigPayload();
  payload.indices = indices;
  if (specificPageIndex !== null && specificPageIndex !== undefined && specificPageIndex !== false) {
    payload.only_page_index = Number(specificPageIndex);
  }

  try {
    const res = await fetch("/api/zebra/print", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (data.zpl) {
      const zplEl = document.getElementById("txtZplPreview");
      if (zplEl) zplEl.value = data.zpl;
    }
    if (data.ok) {
      showToast(data.message, "success");
    } else {
      showToast(data.message || data.error || "Verifique a impressora Zebra ZD230 conectada.", "error");
    }
  } catch (e) {
    showToast("Erro ao enviar para a Zebra ZD230.", "error");
  }
}

function printVisualLabelsInBrowser() {
  const cfg = collectZebraConfigPayload();
  const { mw, mh } = computeMiniDimensionsMm(cfg);
  const { records } = getEffectiveZebraPreviewRecords(cfg);

  if (!records.length) {
    showToast("Selecione pelo menos 1 aparelho para imprimir as etiquetas.", "error");
    return;
  }

  const perBig = Math.max(1, cfg.cols * cfg.rows);
  const skip = Math.min(perBig - 1, cfg.skip_slots);
  const padded = [];
  for (let s = 0; s < skip; s++) padded.push(null);
  records.forEach(r => padded.push(r));

  const totalSheets = Math.max(1, Math.ceil(padded.length / perBig));
  const sheetsHtml = [];

  for (let p = 0; p < totalSheets; p++) {
    const slice = padded.slice(p * perBig, (p + 1) * perBig);
    const cells = [];
    for (let i = 0; i < perBig; i++) {
      const it = slice[i];
      if (!it) {
        cells.push(`<div class="lbl-box empty"></div>`);
        continue;
      }
      const logoHtml = (cfg.show_logo && APP_STATE.logo_data_uri)
        ? `<img src="${APP_STATE.logo_data_uri}" style="height:4.4mm; max-width:65%; object-fit:contain; filter:contrast(1.3) grayscale(1);" />`
        : `<span>LYDA</span>`;
      const upperCli = String(it.CLIENTE || "").toUpperCase();
      const upperSt = String(it.STATUS || "").toUpperCase();
      const isStock = !upperCli || upperCli.includes("SEM CLIENTE") || upperCli.includes("ESTOQUE") || upperSt.includes("ESTOQUE") || upperCli === "LYDA";
      const cliStr = isStock ? "ESTOQUE LYDA" : it.CLIENTE;
      const cliLine = cfg.show_location
        ? `<div class="line cli">${escapeHtml(cliStr)}</div>`
        : "";
      const eqLine = cfg.show_equipamento ? `<div class="line">EQ: ${escapeHtml(it.TIPO || "ANALISADOR")}</div>` : "";
      const snLine = cfg.show_serial_line ? `<div class="line">SN: ${escapeHtml(it.CODIGO)}</div>` : "";

      cells.push(`
        <div class="lbl-box ${cfg.draw_border ? 'bordered' : 'unbordered'}">
          <div class="top">${logoHtml}<span>${escapeHtml(cfg.header_text)}</span></div>
          <div class="fields">${eqLine}${snLine}${cliLine}</div>
          <div class="bars">${cfg.barcode_type === 'QRCODE' ? generateQrSvgHtml(it.CODIGO, 30) : generateBarcodeSvgHtml(it.CODIGO, 20)}</div>
          <div class="sn-num">${escapeHtml(it.CODIGO)}</div>
        </div>
      `);
    }
    sheetsHtml.push(`<div class="big-sheet">${cells.join("")}</div>`);
  }

  const html = `
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
      <meta charset="UTF-8" />
      <title>Etiquetas Zebra ZD230 (${cfg.big_width_mm}x${cfg.big_height_mm}mm) — LYDA</title>
      <style>
        body { font-family: Arial, Helvetica, sans-serif; margin: 14px; color: #0F172A; background: #F1F5F9; }
        .no-print { background: #0F172A; color: #FFF; padding: 10px 16px; border-radius: 8px; margin-bottom: 16px; display: flex; justify-content: space-between; align-items: center; }
        .no-print button { background: #2563EB; color: #FFF; border: none; padding: 8px 16px; border-radius: 6px; font-weight: 700; cursor: pointer; }
        .big-sheet {
          width: ${cfg.big_width_mm}mm;
          height: ${cfg.big_height_mm}mm;
          background: #FFFFFF;
          padding: ${cfg.margin_left_mm}mm;
          box-sizing: border-box;
          display: grid;
          grid-template-columns: repeat(${cfg.cols}, 1fr);
          grid-template-rows: repeat(${cfg.rows}, 1fr);
          column-gap: ${cfg.gap_h_mm}mm;
          row-gap: ${cfg.gap_v_mm}mm;
          margin: 0 auto 12mm auto;
          border: 1px dashed #64748B;
          page-break-after: always;
        }
        .lbl-box {
          width: 100%;
          height: 100%;
          padding: 1.4mm 1.8mm 1.6mm 1.8mm;
          box-sizing: border-box;
          display: flex;
          flex-direction: column;
          justify-content: space-between;
          overflow: hidden;
        }
        .lbl-box.bordered { border: 1.5px solid #000000; border-radius: 1mm; }
        .lbl-box.unbordered { border: 0.5px dashed #CBD5E1; }
        .lbl-box.empty { border: 0.5px dashed #E2E8F0; }
        .top { width: 100%; display: flex; align-items: center; justify-content: space-between; font-size: 7.2pt; font-weight: 900; border-bottom: 1px solid #000; padding-bottom: 0.6mm; margin-bottom: 0.6mm; }
        .fields { width: 100%; text-align: left; }
        .line { font-size: 6.8pt; font-weight: 800; line-height: 1.15; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .line.cli { font-size: 5.8pt; font-weight: 700; }
        .bars { width: 100%; display: flex; justify-content: center; margin-top: auto; }
        .sn-num { font-family: monospace; font-size: 7pt; font-weight: 900; text-align: center; letter-spacing: 0.5px; padding-bottom: 0.4mm; }
        @media print {
          body { background: #FFF; margin: 0; }
          .no-print { display: none !important; }
          .big-sheet { margin: 0; border: none; }
        }
      </style>
    </head>
    <body>
      <div class="no-print">
        <span><strong>${totalSheets} Folha(s) de Etiquetas Zebra ZD230 (${records.length} mini-etiquetas • ${cfg.big_width_mm}×${cfg.big_height_mm} mm)</strong></span>
        <div style="display:flex; gap:8px;">
          <button onclick="window.print()">Imprimir / Salvar PDF</button>
          <button style="background:#475569;" onclick="window.close()">Fechar</button>
        </div>
      </div>
      ${sheetsHtml.join("")}
    </body>
    </html>
  `;
  const win = window.open("", "_blank");
  if (win) {
    win.document.open();
    win.document.write(html);
    win.document.close();
  }
}

async function previewZplForSelected() {
  const indices = getZebraSelectedIndicesArray();
  const cfg = collectZebraConfigPayload();
  const perBig = Math.max(1, cfg.cols * cfg.rows);
  const targetIndices = indices.length ? indices : (APP_STATE.items || []).slice(0, perBig).map(it => it._idx);
  if (!targetIndices.length) return;

  cfg.indices = targetIndices;
  cfg.only_preview_zpl = true;

  const res = await fetch("/api/zebra/print", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cfg),
  });
  const data = await res.json();
  if (data.ok) {
    const zplEl = document.getElementById("txtZplPreview");
    if (zplEl) zplEl.value = data.zpl || "";
  }
}

async function downloadZebraPrnFile(onlyPageIndex = null, ext = "prn") {
  const indices = getZebraSelectedIndicesArray();
  if (!indices.length) {
    showToast("Selecione pelo menos 1 aparelho (ou clique em 'Todos os Aparelhos') para baixar o arquivo .PRN.", "error");
    return;
  }

  const cfg = collectZebraConfigPayload();
  cfg.indices = indices;
  cfg.only_preview_zpl = true;
  cfg.is_prn_download = true;
  if (onlyPageIndex !== null && onlyPageIndex !== undefined && onlyPageIndex !== false) {
    cfg.only_page_index = Number(onlyPageIndex);
  }

  try {
    const res = await fetch("/api/zebra/print", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cfg),
    });
    const data = await res.json();
    if (!data.ok || !data.zpl) {
      showToast(data.error || "Não foi possível gerar o arquivo .PRN das etiquetas.", "error");
      return;
    }

    const zplEl = document.getElementById("txtZplPreview");
    if (zplEl) zplEl.value = data.zpl;

    const cleanExt = (ext || "prn").toLowerCase().replace(/^\./, "");
    const baseName = (data.filename || `etiquetas_lyda_zd230_${cfg.big_width_mm}x${cfg.big_height_mm}mm.prn`)
      .replace(/\.(prn|zpl|txt)$/i, "");
    const finalFilename = `${baseName}.${cleanExt}`;

    const blob = new Blob([data.zpl], { type: "application/octet-stream;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = finalFilename;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    }, 200);

    showToast(`Arquivo ${finalFilename} baixado com sucesso!`, "success");
  } catch (err) {
    showToast("Erro ao baixar o arquivo .PRN das etiquetas.", "error");
  }
}

function renderHistoryTable() {
  const qEl = document.getElementById("inpSearchHistory");
  const q = ((qEl && qEl.value) || "").trim().toUpperCase();
  const tbody = document.getElementById("tbodyHistory");
  if (!tbody) return;

  const filtered = (APP_STATE.history || []).filter(h => {
    if (!q) return true;
    const hay = [h.DATA_HORA, h.CODIGO_BARRAS, h.TIPO, h.ACAO, h.CLIENTE, h.OPERADOR, h.DETALHES].join(" ").toUpperCase();
    return hay.includes(q);
  });

  if (!filtered.length) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding:28px; color:var(--slate-500);">Nenhum registro encontrado no histórico para este filtro.</td></tr>`;
    return;
  }

  tbody.innerHTML = filtered.slice(0, 200).map(h => {
    const acao = String(h.ACAO || "");
    const cli = String(h.CLIENTE || "-");
    const isEst = cli.toUpperCase().includes("ESTOQUE") || acao.toUpperCase().includes("ESTOQUE");
    const rowCls = isEst ? "row-estoque" : "row-comodato";
    return `
      <tr class="${rowCls}">
        <td style="white-space:nowrap; font-weight:600; color:var(--slate-600);">${escapeHtml(h.DATA_HORA)}</td>
        <td style="font-family:monospace; font-weight:800; font-size:13px; color:var(--slate-900);">${escapeHtml(h.CODIGO_BARRAS)}</td>
        <td>${getTipoBadgeHtml(h.TIPO)}</td>
        <td><span class="badge badge-ana" style="font-weight:800;">${escapeHtml(acao)}</span></td>
        <td><strong>${escapeHtml(cli)}</strong></td>
        <td><span class="badge badge-user">${escapeHtml(h.OPERADOR || h.RESPONSAVEL || "-")}</span></td>
        <td style="min-width:280px; line-height:1.4; color:var(--slate-700);">${escapeHtml(h.DETALHES || "-")}</td>
      </tr>
    `;
  }).join("");
}

// =========================================================================
// ABA 6: SERVIDOR LOCAL, BACKUP DIÁRIO SHAREPOINT & CONFIGURAÇÕES
// =========================================================================
function renderServerAndSharepointTab() {
  const srv = APP_STATE.server_info || {};
  const cfg = APP_STATE.config || {};

  const primaryUrl = srv.primary_url || window.location.origin;
  document.getElementById("inpServerNetworkUrl").value = primaryUrl;
  document.getElementById("lblAllServerUrls").innerText =
    `Computador Servidor: ${srv.hostname || "PC-LYDA"} | Pasta Local do Banco: ${srv.db_dir || ""}`;

  document.getElementById("imgServerUrlQr").src =
    `https://api.qrserver.com/v1/create-qr-code/?size=140x140&margin=4&data=${encodeURIComponent(primaryUrl)}`;

  document.getElementById("inpSharepointDir").value = srv.sharepoint_backup_dir || "";
  document.getElementById("inpSharepointTime").value = srv.sharepoint_backup_time || "18:00";
  document.getElementById("chkSharepointAutoSync").checked = srv.sharepoint_auto_sync !== false;

  const lastInfo = srv.last_sharepoint_backup_at
    ? `${srv.last_sharepoint_backup_at} — ${srv.last_sharepoint_backup_status || "OK"}`
    : "Nenhum envio registrado ainda (clique em 'Fazer Backup Agora p/ SharePoint')";
  document.getElementById("lblLastSharepointBackupInfo").innerText = lastInfo;

  const cands = srv.sharepoint_candidates || [];
  const candDiv = document.getElementById("divSharepointCandidates");
  if (cands.length > 0) {
    candDiv.innerHTML =
      `<div style="font-size:11px; font-weight:700; color:#1E40AF; margin-bottom:4px;">Pastas OneDrive / SharePoint detectadas neste PC (clique para selecionar):</div>` +
      cands.map(p => `
        <button class="btn btn-secondary btn-sm" style="margin-right:6px; margin-bottom:4px;" onclick="document.getElementById('inpSharepointDir').value='${escapeHtml(p).replace(/\\/g, "\\\\").replace(/'/g, "\\'")}'">
          Usar: ${escapeHtml(p)}
        </button>
      `).join("");
  } else {
    candDiv.innerHTML = "";
  }

  document.getElementById("inpSettingsHqAddress").value = cfg.lyda_hq_address || "";
  document.getElementById("inpSettingsCycleMonths").value = cfg.default_update_cycle_months || 6;

  loadBackupsList();
}

function copyServerNetworkUrl() {
  const url = document.getElementById("inpServerNetworkUrl").value;
  navigator.clipboard.writeText(url);
  showToast(`Link do Servidor (${url}) copiado! Envie para os outros computadores da LYDA.`, "success");
}

async function saveServerAndSharepointSettings() {
  const payload = {
    sharepoint_backup_dir: document.getElementById("inpSharepointDir").value.trim(),
    sharepoint_backup_time: document.getElementById("inpSharepointTime").value.trim() || "18:00",
    sharepoint_auto_sync: document.getElementById("chkSharepointAutoSync").checked,
    lyda_hq_address: document.getElementById("inpSettingsHqAddress").value.trim(),
    default_update_cycle_months: parseInt(document.getElementById("inpSettingsCycleMonths").value || "6", 10),
  };
  try {
    const res = await fetch("/api/settings/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!data.ok) {
      showToast(data.error || "Erro ao salvar configurações.", "error");
      return;
    }
    showToast(data.message, "success");
    await loadBootstrapData(true);
  } catch (e) {
    showToast("Erro ao salvar configurações do Servidor.", "error");
  }
}

async function triggerImmediateSharePointBackup() {
  try {
    showToast("Executando backup completo (Banco JSON + Planilha Excel) para o SharePoint...", "info");
    const res = await fetch("/api/backups/run_now", { method: "POST" });
    const data = await res.json();
    if (data.ok) {
      showToast(data.message, "success");
    } else {
      showToast(data.message || "Erro ao realizar backup.", "error");
    }
    await loadBootstrapData(true);
  } catch (e) {
    showToast("Erro ao executar backup.", "error");
  }
}

async function loadBackupsList() {
  try {
    const res = await fetch("/api/backups/list");
    const data = await res.json();
    if (!data.ok) return;
    const tbody = document.getElementById("tbodyBackups");
    const list = data.backups || [];
    const isAdmin = APP_STATE.current_user && APP_STATE.current_user.role === "ADMIN";
    tbody.innerHTML = list.length
      ? list.map(b => `
          <tr>
            <td style="white-space:nowrap; font-weight:700;">${escapeHtml(b.created_at)}</td>
            <td><span class="badge ${b.origin === 'SharePoint' ? 'badge-em-dia' : 'badge-ana'}">${escapeHtml(b.origin || 'Servidor Local')}</span></td>
            <td>${escapeHtml(b.reason)}</td>
            <td style="text-align:center; font-weight:800;">${b.items_count || 0}</td>
            <td style="text-align:right;">
              ${isAdmin ? `<button class="btn btn-secondary btn-sm" onclick="restoreBackupFile('${escapeHtml(b.filepath).replace(/\\/g, "\\\\").replace(/'/g, "\\'")}')">Restaurar</button>` : `-`}
            </td>
          </tr>
        `).join("")
      : `<tr><td colspan="5" style="text-align:center; color:#64748B;">Nenhum backup listado.</td></tr>`;
  } catch (e) {}
}

async function restoreBackupFile(filepath) {
  if (!confirm("Deseja restaurar o banco de dados para este ponto de backup? (Um backup automático do estado atual será salvo antes).")) return;
  const res = await fetch("/api/backups/restore", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filepath: filepath }),
  });
  const data = await res.json();
  if (!data.ok) {
    showToast(data.error || "Erro ao restaurar backup.", "error");
    return;
  }
  showToast(data.message, "success");
  await loadBootstrapData(false);
}

async function uploadAndImportExcel(fileInput) {
  if (!fileInput.files || !fileInput.files[0]) return;
  const fd = new FormData();
  fd.append("file", fileInput.files[0]);
  showToast("Importando planilha Excel...", "info");
  try {
    const res = await fetch("/api/excel/import", { method: "POST", body: fd });
    const data = await res.json();
    fileInput.value = "";
    if (!data.ok) {
      showToast(data.error || "Erro ao importar planilha.", "error");
      return;
    }
    showToast(data.message, "success");
    await loadBootstrapData(false);
  } catch (e) {
    showToast("Erro ao enviar planilha Excel.", "error");
  }
}

// =========================================================================
// NAVEGAÇÃO ENTRE ABAS
// =========================================================================
function switchTab(tabId) {
  document.querySelectorAll(".tab-pane").forEach(el => el.classList.remove("active"));
  document.querySelectorAll(".nav-tab").forEach(el => el.classList.remove("active"));

  const pane = document.getElementById(tabId);
  if (pane) pane.classList.add("active");
  const btn = document.querySelector(`.nav-tab[data-tab="${tabId}"]`);
  if (btn) {
    btn.classList.add("active");
    const pageTitle = btn.getAttribute("data-title");
    const lblTitle = document.getElementById("lblTopPageTitle");
    if (pageTitle && lblTitle) {
      lblTitle.innerText = pageTitle;
    }
  }

  if (tabId === "tab-dashboard") {
    renderExecutiveDashboard();
  } else if (tabId === "tab-radar6m") {
    renderRadar6mTab();
  } else if (tabId === "tab-clientes") {
    backToClientsDirectory();
  } else if (tabId === "tab-etiquetas") {
    renderZebraStudio();
    renderHistoryTable();
  } else if (tabId === "tab-rota") {
    initRouteLeafletMap();
    if (!APP_STATE.routeStops.length) {
      loadRouteFromMode("FROM_INDICES");
    } else {
      setTimeout(() => {
        routeLeafletMap.invalidateSize();
        fitRouteMapBounds();
      }, 100);
    }
  } else if (tabId === "tab-admin") {
    renderAdminUsersAndLogsTab();
  }
}

// =========================================================================
// CALENDÁRIO INTERATIVO CUSTOMIZADO PT-BR (POPOVER DD/MM/AAAA)
// =========================================================================
const LYDA_DP_MONTHS = [
  "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
  "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"
];

let LYDA_DP_STATE = {
  activeInput: null,
  viewYear: new Date().getFullYear(),
  viewMonth: new Date().getMonth(),
  selectedDate: null,
};

function parseBrDateString(str) {
  const m = String(str || "").trim().match(/^(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{2,4})$/);
  if (!m) return null;
  let d = parseInt(m[1], 10);
  let mo = parseInt(m[2], 10) - 1;
  let y = parseInt(m[3], 10);
  if (y < 100) y += 2000;
  if (mo < 0 || mo > 11 || d < 1 || d > 31) return null;
  const dt = new Date(y, mo, d);
  if (dt.getFullYear() !== y || dt.getMonth() !== mo || dt.getDate() !== d) return null;
  return dt;
}

function formatBrDateObj(dt) {
  const dd = String(dt.getDate()).padStart(2, "0");
  const mm = String(dt.getMonth() + 1).padStart(2, "0");
  const yyyy = dt.getFullYear();
  return `${dd}/${mm}/${yyyy}`;
}

function openLydaDatePicker(inputEl) {
  if (!inputEl) return;
  const pop = document.getElementById("lydaDatePickerPopover");
  if (!pop) return;

  LYDA_DP_STATE.activeInput = inputEl;
  const parsed = parseBrDateString(inputEl.value);
  const baseDate = parsed || new Date();
  LYDA_DP_STATE.selectedDate = parsed;
  LYDA_DP_STATE.viewYear = baseDate.getFullYear();
  LYDA_DP_STATE.viewMonth = baseDate.getMonth();

  renderLydaDatePickerPopover();
  pop.classList.add("open");
  positionLydaDatePicker(inputEl);
}

function positionLydaDatePicker(inputEl) {
  const pop = document.getElementById("lydaDatePickerPopover");
  if (!pop || !inputEl) return;
  const rect = inputEl.getBoundingClientRect();
  const popWidth = 284;
  const popHeight = pop.offsetHeight || 310;

  let left = rect.left;
  if (left + popWidth > window.innerWidth - 12) {
    left = Math.max(12, window.innerWidth - popWidth - 12);
  }

  let top = rect.bottom + 6;
  if (top + popHeight > window.innerHeight - 12 && rect.top > popHeight + 12) {
    top = rect.top - popHeight - 6;
  }

  pop.style.left = `${Math.round(left)}px`;
  pop.style.top = `${Math.round(top)}px`;
}

function closeLydaDatePicker() {
  const pop = document.getElementById("lydaDatePickerPopover");
  if (pop) pop.classList.remove("open");
  LYDA_DP_STATE.activeInput = null;
}

function stepLydaDatePickerMonth(delta) {
  let m = LYDA_DP_STATE.viewMonth + delta;
  let y = LYDA_DP_STATE.viewYear;
  if (m < 0) {
    m = 11;
    y--;
  } else if (m > 11) {
    m = 0;
    y++;
  }
  LYDA_DP_STATE.viewMonth = m;
  LYDA_DP_STATE.viewYear = y;
  renderLydaDatePickerPopover();
}

function onLydaDpMonthYearSelectChange() {
  const selM = document.getElementById("selLydaDpMonth");
  const selY = document.getElementById("selLydaDpYear");
  if (selM) LYDA_DP_STATE.viewMonth = parseInt(selM.value, 10);
  if (selY) LYDA_DP_STATE.viewYear = parseInt(selY.value, 10);
  renderLydaDatePickerPopover();
}

function applyLydaDateValueToActiveInput(valStr) {
  const inp = LYDA_DP_STATE.activeInput;
  if (!inp) return;
  inp.value = valStr;
  inp.dispatchEvent(new Event("input", { bubbles: true }));
  inp.dispatchEvent(new Event("change", { bubbles: true }));
  closeLydaDatePicker();
}

function selectLydaCalendarDay(year, month, day) {
  const dt = new Date(year, month, day);
  applyLydaDateValueToActiveInput(formatBrDateObj(dt));
}

function setLydaDatePickerQuick(mode) {
  const now = new Date();
  if (mode === "TODAY") {
    applyLydaDateValueToActiveInput(formatBrDateObj(now));
  } else if (mode === "MINUS_6M") {
    const dt6 = new Date(now.getFullYear(), now.getMonth() - 6, now.getDate());
    applyLydaDateValueToActiveInput(formatBrDateObj(dt6));
  } else if (mode === "CLEAR") {
    applyLydaDateValueToActiveInput("");
  }
}

function renderLydaDatePickerPopover() {
  const pop = document.getElementById("lydaDatePickerPopover");
  if (!pop) return;

  const y = LYDA_DP_STATE.viewYear;
  const m = LYDA_DP_STATE.viewMonth;
  const today = new Date();
  const sel = LYDA_DP_STATE.selectedDate;

  const firstDayWeek = new Date(y, m, 1).getDay();
  const daysInMonth = new Date(y, m + 1, 0).getDate();
  const daysInPrevMonth = new Date(y, m, 0).getDate();

  const monthOptions = LYDA_DP_MONTHS.map((name, idx) =>
    `<option value="${idx}" ${idx === m ? "selected" : ""}>${name}</option>`
  ).join("");

  const yearOptions = [];
  for (let yr = 2020; yr <= 2032; yr++) {
    yearOptions.push(`<option value="${yr}" ${yr === y ? "selected" : ""}>${yr}</option>`);
  }

  const dayCells = [];
  // Dias do mês anterior
  for (let i = firstDayWeek - 1; i >= 0; i--) {
    const d = daysInPrevMonth - i;
    const pm = m === 0 ? 11 : m - 1;
    const py = m === 0 ? y - 1 : y;
    dayCells.push(
      `<button type="button" class="lyda-dp-day muted" onclick="selectLydaCalendarDay(${py}, ${pm}, ${d})">${d}</button>`
    );
  }

  // Dias do mês atual
  for (let d = 1; d <= daysInMonth; d++) {
    const isToday =
      d === today.getDate() && m === today.getMonth() && y === today.getFullYear();
    const isSelected =
      sel && d === sel.getDate() && m === sel.getMonth() && y === sel.getFullYear();
    const cls = ["lyda-dp-day", isToday ? "today" : "", isSelected ? "selected" : ""]
      .filter(Boolean)
      .join(" ");
    dayCells.push(
      `<button type="button" class="${cls}" onclick="selectLydaCalendarDay(${y}, ${m}, ${d})">${d}</button>`
    );
  }

  // Completa 42 células com o próximo mês
  const rem = 42 - dayCells.length;
  for (let d = 1; d <= rem; d++) {
    const nm = m === 11 ? 0 : m + 1;
    const ny = m === 11 ? y + 1 : y;
    dayCells.push(
      `<button type="button" class="lyda-dp-day muted" onclick="selectLydaCalendarDay(${ny}, ${nm}, ${d})">${d}</button>`
    );
  }

  pop.innerHTML = `
    <div class="lyda-dp-header">
      <button type="button" class="lyda-dp-nav-btn" onclick="stepLydaDatePickerMonth(-1)" title="Mês Anterior">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"><polyline points="15 18 9 12 15 6"/></svg>
      </button>
      <div class="lyda-dp-title-selects">
        <select id="selLydaDpMonth" class="lyda-dp-select" onchange="onLydaDpMonthYearSelectChange()">${monthOptions}</select>
        <select id="selLydaDpYear" class="lyda-dp-select" onchange="onLydaDpMonthYearSelectChange()">${yearOptions.join("")}</select>
      </div>
      <button type="button" class="lyda-dp-nav-btn" onclick="stepLydaDatePickerMonth(1)" title="Próximo Mês">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"><polyline points="9 18 15 12 9 6"/></svg>
      </button>
    </div>
    <div class="lyda-dp-weekdays">
      <span>Dom</span><span>Seg</span><span>Ter</span><span>Qua</span><span>Qui</span><span>Sex</span><span>Sáb</span>
    </div>
    <div class="lyda-dp-days">
      ${dayCells.join("")}
    </div>
    <div class="lyda-dp-footer">
      <div style="display:flex; gap:4px;">
        <button type="button" class="lyda-dp-quick-btn primary" onclick="setLydaDatePickerQuick('TODAY')">Hoje</button>
        <button type="button" class="lyda-dp-quick-btn" onclick="setLydaDatePickerQuick('MINUS_6M')" title="Há 6 meses atrás">-6 Meses</button>
      </div>
      <button type="button" class="lyda-dp-quick-btn" onclick="setLydaDatePickerQuick('CLEAR')">Limpar</button>
    </div>
  `;
}

function initLydaCustomDatePicker() {
  document.addEventListener("focusin", e => {
    const t = e.target;
    if (t && t.matches && t.matches("input.date-input-br, input[data-datepicker='br']")) {
      openLydaDatePicker(t);
    }
  });

  document.addEventListener("click", e => {
    const pop = document.getElementById("lydaDatePickerPopover");
    if (!pop) return;
    const t = e.target;
    if (t && t.closest && t.closest("input.date-input-br, input[data-datepicker='br']")) {
      openLydaDatePicker(t.closest("input.date-input-br, input[data-datepicker='br']"));
      return;
    }
    if (pop.classList.contains("open") && !pop.contains(t)) {
      closeLydaDatePicker();
    }
  });

  window.addEventListener("resize", () => {
    if (LYDA_DP_STATE.activeInput) {
      positionLydaDatePicker(LYDA_DP_STATE.activeInput);
    }
  });
}

// =========================================================================
// FILTRO RAPIDO DOS GRAFICOS, MENU RECOLHIVEL, HISTORICO (VOLTAR/AVANCAR)
// E PERSISTENCIA COMPLETA DO ESTADO DA INTERFACE
// =========================================================================
function dashJumpFilter(sit, mod, tipo) {
  switchTab("tab-estoque");
  resetAllFilters();
  const set = (id, v) => { const el = document.getElementById(id); if (el) el.value = v; };
  if (sit) set("selFilterSituacao", sit);
  if (mod) set("selFilterModalidade", mod);
  if (tipo) set("selFilterTipo", tipo);
  renderKpis();
  renderItemsTable();
  schedulePushUiHistory("dashJumpFilter");
}

function setDashDonutMode(mode) {
  APP_STATE.dashDonutMode = mode === "TIPOS" ? "TIPOS" : "COMPLETO";
  renderExecutiveDashboard();
}

const UI_STORAGE_KEY = "LYDA_UI_STATE_V2";
const UI_SIDEBAR_KEY = "LYDA_SIDEBAR_COLLAPSED";
const UI_SESSION_ID = String(Date.now());
let UI_HISTORY = [];
let UI_HIST_IDX = -1;
let UI_RESTORING = false;
let UI_PUSH_TIMER = null;
let UI_SCROLL_BY_TAB = {};

function toggleSidebarCollapsed(forceState) {
  const shell = document.getElementById("appShell");
  if (!shell) return;
  const next = typeof forceState === "boolean" ? forceState : !shell.classList.contains("sidebar-collapsed");
  shell.classList.toggle("sidebar-collapsed", next);
  try { localStorage.setItem(UI_SIDEBAR_KEY, next ? "1" : "0"); } catch (e) {}
  if (typeof routeLeafletMap !== "undefined" && routeLeafletMap) {
    setTimeout(() => routeLeafletMap.invalidateSize(), 250);
  }
}

function initSidebarCollapsedFromStorage() {
  let v = "0";
  try { v = localStorage.getItem(UI_SIDEBAR_KEY) || "0"; } catch (e) {}
  toggleSidebarCollapsed(v === "1");
}

function getActiveTabId() {
  const el = document.querySelector(".tab-pane.active");
  return el ? el.id : "tab-dashboard";
}

function captureUiStateSnapshot() {
  const val = id => { const el = document.getElementById(id); return el ? el.value : ""; };
  UI_SCROLL_BY_TAB[getActiveTabId()] = window.scrollY || 0;
  return {
    tab: getActiveTabId(),
    kpiQuickFilter: APP_STATE.kpiQuickFilter,
    radarSubFilter: APP_STATE.radarSubFilter,
    clientListFilter: APP_STATE.clientListFilter,
    selectedClientName: APP_STATE.selectedClientName || "",
    dashDonutMode: APP_STATE.dashDonutMode || "COMPLETO",
    filters: {
      search: val("inpFilterSearch"),
      tipo: val("selFilterTipo") || "TODOS",
      modalidade: val("selFilterModalidade") || "TODAS",
      situacao: val("selFilterSituacao") || "TODOS",
      ciclo: val("selFilterCiclo") || "TODOS",
      radarSearch: val("inpSearchRadar"),
    },
    selected: Array.from(APP_STATE.selectedIndices || []),
    zebraSelected: Array.from(APP_STATE.zebraSelectedIndices || []),
    scrollByTab: Object.assign({}, UI_SCROLL_BY_TAB),
  };
}

function uiSnapshotKey(snap) {
  const c = Object.assign({}, snap);
  delete c.scrollByTab;
  return JSON.stringify(c);
}

function updateNavHistoryButtons() {
  const back = document.getElementById("btnNavBack");
  const fwd = document.getElementById("btnNavForward");
  if (back) back.disabled = UI_HIST_IDX <= 0;
  if (fwd) fwd.disabled = UI_HIST_IDX >= UI_HISTORY.length - 1;
}

function savePersistentUiState() {
  try {
    const snap = captureUiStateSnapshot();
    localStorage.setItem(UI_STORAGE_KEY, JSON.stringify(snap));
  } catch (e) {}
}

function pushUiHistoryState(reason) {
  if (UI_RESTORING || !APP_STATE.authenticated) return;
  const snap = captureUiStateSnapshot();
  const cur = UI_HISTORY[UI_HIST_IDX];
  if (cur) {
    cur.scrollByTab = Object.assign({}, UI_SCROLL_BY_TAB);
    if (uiSnapshotKey(cur) === uiSnapshotKey(snap)) {
      savePersistentUiState();
      return;
    }
  }
  UI_HISTORY = UI_HISTORY.slice(0, UI_HIST_IDX + 1);
  UI_HISTORY.push(snap);
  UI_HIST_IDX = UI_HISTORY.length - 1;
  try {
    history.pushState({ lyda: true, sid: UI_SESSION_ID, idx: UI_HIST_IDX }, "", "#" + snap.tab);
  } catch (e) {}
  updateNavHistoryButtons();
  savePersistentUiState();
}

function schedulePushUiHistory(reason, delay = 160) {
  if (UI_RESTORING) return;
  clearTimeout(UI_PUSH_TIMER);
  UI_PUSH_TIMER = setTimeout(() => pushUiHistoryState(reason), delay);
}

function restoreUiStateSnapshot(snap) {
  if (!snap) return;
  UI_RESTORING = true;
  try {
    APP_STATE.kpiQuickFilter = snap.kpiQuickFilter || "ALL";
    APP_STATE.radarSubFilter = snap.radarSubFilter || "ALL_NEED";
    APP_STATE.clientListFilter = snap.clientListFilter || "ALL";
    APP_STATE.dashDonutMode = snap.dashDonutMode || "COMPLETO";
    const valid = new Set((APP_STATE.items || []).map(it => it._idx));
    APP_STATE.selectedIndices = new Set((snap.selected || []).filter(i => valid.has(i)));
    APP_STATE.zebraSelectedIndices = new Set((snap.zebraSelected || []).filter(i => valid.has(i)));
    UI_SCROLL_BY_TAB = Object.assign({}, snap.scrollByTab || {});

    const f = snap.filters || {};
    const set = (id, v) => { const el = document.getElementById(id); if (el && v !== undefined) el.value = v; };
    set("inpFilterSearch", f.search || "");
    set("selFilterTipo", f.tipo || "TODOS");
    set("selFilterModalidade", f.modalidade || "TODAS");
    set("selFilterSituacao", f.situacao || "TODOS");
    set("selFilterCiclo", f.ciclo || "TODOS");
    set("inpSearchRadar", f.radarSearch || "");

    switchTab(snap.tab || "tab-dashboard");
    if (snap.tab === "tab-clientes" && snap.selectedClientName) {
      selectClientRecord(snap.selectedClientName);
    }
    renderKpis();
    renderItemsTable();
    renderRadar6mTab();
    renderExecutiveDashboard();
    setTimeout(() => window.scrollTo(0, UI_SCROLL_BY_TAB[snap.tab] || 0), 60);
  } finally {
    setTimeout(() => { UI_RESTORING = false; }, 400);
  }
}

function navigateAppHistory(delta) {
  const target = UI_HIST_IDX + delta;
  if (target < 0 || target >= UI_HISTORY.length) return;
  UI_HIST_IDX = target;
  restoreUiStateSnapshot(UI_HISTORY[target]);
  try {
    history.replaceState({ lyda: true, sid: UI_SESSION_ID, idx: target }, "", "#" + UI_HISTORY[target].tab);
  } catch (e) {}
  updateNavHistoryButtons();
}

function restorePersistentUiStateOnLoad() {
  if (!APP_STATE.authenticated) return;
  let snap = null;
  try { snap = JSON.parse(localStorage.getItem(UI_STORAGE_KEY) || "null"); } catch (e) {}
  if (snap && snap.tab) {
    restoreUiStateSnapshot(snap);
  }
  setTimeout(() => {
    const first = captureUiStateSnapshot();
    UI_HISTORY = [first];
    UI_HIST_IDX = 0;
    try {
      history.replaceState({ lyda: true, sid: UI_SESSION_ID, idx: 0 }, "", "#" + first.tab);
    } catch (e) {}
    updateNavHistoryButtons();
  }, 500);
}

function initUiNavigationAndPersistence() {
  // Envolve as funcoes de navegacao/acao para gravar historico automaticamente
  ["applyKpiQuickFilter", "resetAllFilters", "selectClientRecord", "backToClientsDirectory", "setRadarSubFilter", "setDashDonutMode"].forEach(name => {
    const orig = window[name];
    if (typeof orig !== "function") return;
    window[name] = function (...args) {
      const r = orig.apply(this, args);
      schedulePushUiHistory(name);
      return r;
    };
  });

  const origSwitch = window.switchTab;
  window.switchTab = function (tabId) {
    if (!UI_RESTORING) UI_SCROLL_BY_TAB[getActiveTabId()] = window.scrollY || 0;
    const r = origSwitch.apply(this, arguments);
    if (!UI_RESTORING) {
      window.scrollTo(0, UI_SCROLL_BY_TAB[tabId] || 0);
      schedulePushUiHistory("switchTab");
    }
    return r;
  };

  window.addEventListener("popstate", e => {
    const st = e.state;
    if (!st || !st.lyda || st.sid !== UI_SESSION_ID) return;
    if (st.idx < 0 || st.idx >= UI_HISTORY.length || st.idx === UI_HIST_IDX) return;
    UI_HIST_IDX = st.idx;
    restoreUiStateSnapshot(UI_HISTORY[st.idx]);
    updateNavHistoryButtons();
  });

  let scrollTimer = null;
  window.addEventListener("scroll", () => {
    clearTimeout(scrollTimer);
    scrollTimer = setTimeout(() => {
      if (!UI_RESTORING) {
        UI_SCROLL_BY_TAB[getActiveTabId()] = window.scrollY || 0;
        savePersistentUiState();
      }
    }, 250);
  }, { passive: true });

  ["inpFilterSearch", "selFilterTipo", "selFilterModalidade", "selFilterSituacao", "selFilterCiclo", "inpSearchRadar"].forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    const evt = el.tagName === "SELECT" ? "change" : "input";
    el.addEventListener(evt, () => schedulePushUiHistory("filter", 700));
  });

  window.addEventListener("beforeunload", savePersistentUiState);
}

window.addEventListener("DOMContentLoaded", () => {
  initLydaCustomDatePicker();
  const scanInp = document.getElementById("inpQuickScan");
  if (scanInp) {
    scanInp.addEventListener("keydown", e => {
      if (e.key === "Enter") {
        e.preventDefault();
        handleQuickScanInput();
      }
    });
  }
  initSidebarCollapsedFromStorage();
  document.querySelectorAll(".nav-tab").forEach(b => {
    const t = b.getAttribute("data-title");
    if (t) b.title = t;
  });
  initUiNavigationAndPersistence();
  loadBootstrapData(false).then(() => restorePersistentUiStateOnLoad());
});

