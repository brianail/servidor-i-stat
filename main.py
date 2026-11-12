"""
LYDA - Sistema de Gestão de Equipamentos i-STAT + Leitor de Código de Barras + Impressão Zebra ZD230
Desmembra e gerencia todos os equipamentos da base (ANALISADOR, IMPRESSORA, SIMULADOR, DOWNLOADER),
onde cada serial possui seu próprio código de barras, tela para bipar no leitor USB, cadastro/edição
de movimentações (Venda, Comodato, Propriedade Lyda) e impressão de mini-etiquetas com contorno em ZPL II.
Interface limpa com ícones vetoriais (sem emojis).
"""

import json
import os
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import List, Dict, Any, Optional

import webbrowser
from datetime import datetime, timedelta
from zpl_engine import LabelLayoutConfig, ExtraFieldConfig, ZPLGenerator, sanitize_barcode_value
from printer_manager import list_system_printers, dispatch_zpl_print
from data_loader import load_spreadsheet
from istat_database import (
    IStatDatabaseManager,
    EQUIPMENT_TYPES,
    MODALITIES,
    STATUS_OPTIONS,
    CONDICAO_FISICA_OPTIONS,
    MOVIMENTO_ACOES,
    clean_barcode_serial,
    classify_item_row_state,
)
from ui_icons import VectorIconFactory
from logo_zpl import get_tk_logo_photo, get_default_logo_path
from romaneio_generator import generate_and_open_romaneio
from rota_enfermeira import (
    DEFAULT_LYDA_SEDE_ADDRESS,
    lookup_cep_viacep,
    add_months_to_date,
    compute_update_cycle_info,
    group_items_into_route_stops,
    optimize_stops_order,
    compute_route_metrics_and_geometry,
    render_route_map_pil_image,
    build_google_maps_multi_stop_url,
    build_single_stop_maps_url,
    build_whatsapp_route_summary,
    generate_and_open_nurse_route_html,
    generate_nurse_route_pdf,
    open_or_reveal_file,
)

WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(WORKSPACE_DIR, "lyda_zebra_config.json")

ALL_COLUMNS = [
    "CODIGO",
    "TIPO",
    "EQUIPAMENTO",
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
    "PROXIMA_ATUALIZACAO",
    "ATUALIZADO_NO_ESTOQUE",
    "VERSAO_CLEW",
    "KIT_ANALISADOR",
    "OBSERVACOES",
]


class LydaZebraApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("LYDA — Controle de Estoque i-STAT")
        self.geometry("1420x860")
        self.minsize(1180, 740)
        self.configure(bg="#F1F5F9")

        # Fábrica de ícones vetoriais limpos (sem emojis)
        self.icons = VectorIconFactory()

        # Banco de dados unificado i-STAT
        self.db = IStatDatabaseManager(WORKSPACE_DIR)
        self.columns: List[str] = list(ALL_COLUMNS)
        self.checked_indices: set[int] = set()
        self.selected_indices: List[int] = []
        self.current_preview_page: int = 0
        self.currently_scanned_index: Optional[int] = None

        # Estado do leitor de código de barras global (hands-free / sem precisar clicar)
        self._active_modal_open: bool = False
        self._global_scan_buffer: str = ""
        self._global_last_key_ts: float = 0.0
        self._global_scan_fast_count: int = 0
        self._global_scan_after_id: Optional[str] = None
        self._entry_scan_after_id: Optional[str] = None
        self._entry_last_key_ts: float = 0.0
        self._entry_fast_count: int = 0

        # Configuração de etiqueta (Etiquetas começam ocultas por padrão: foco 100% em Mapeamento & Estoque)
        self.layout_cfg = self._load_saved_config()
        has_cliente_field = any(ef.column_name == "CLIENTE" for ef in self.layout_cfg.extra_fields)
        self.var_show_location_on_label = tk.BooleanVar(value=has_cliente_field)
        self.var_skip_slots = tk.IntVar(value=getattr(self.layout_cfg, "skip_slots", 0))
        self.var_auto_open_modal = tk.BooleanVar(value=True)
        self.preview_visible: bool = False
        self.var_operador_atual = tk.StringVar(value=self.db.operador_atual)
        self.var_operador_atual.trace_add("write", self._on_operador_changed)

        self._apply_app_icon()
        self._setup_styles()
        self._build_ui()
        self._setup_global_scanner_listener()
        self._refresh_column_selectors()
        self._populate_data_tree()
        self._refresh_history_tree()
        self._update_preview()
        self._start_multi_pc_sync_polling()

    def _apply_app_icon(self):
        """Aplica o ícone oficial da LYDA na barra de título e no Dock / Barra de Tarefas."""
        try:
            ico_path = os.path.join(WORKSPACE_DIR, "lyda_icon.ico")
            png_path = os.path.join(WORKSPACE_DIR, "lyda_app_icon.png")
            if os.name == "nt" and os.path.exists(ico_path):
                self.iconbitmap(ico_path)
            if os.path.exists(png_path):
                self._app_icon_img = tk.PhotoImage(file=png_path)
                self.iconphoto(True, self._app_icon_img)
        except Exception:
            pass

    def _on_operador_changed(self, *_args):
        val = self.var_operador_atual.get().strip().upper()
        if val:
            self.db.operador_atual = val
            self.db.save_local_pc_config()

    def _setup_styles(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        # Garante que no macOS (inclusive em Dark Mode) textos e cursores nunca fiquem brancos sobre fundo branco
        self.option_add("*Label.Foreground", "#0F172A")
        self.option_add("*Checkbutton.Foreground", "#0F172A")
        self.option_add("*Radiobutton.Foreground", "#0F172A")
        self.option_add("*LabelFrame.Foreground", "#0F172A")
        self.option_add("*Entry.Foreground", "#0F172A")
        self.option_add("*Entry.Background", "#FFFFFF")
        self.option_add("*Entry.insertBackground", "#0F172A")
        self.option_add("*Text.Foreground", "#0F172A")
        self.option_add("*Text.Background", "#FFFFFF")
        self.option_add("*Text.insertBackground", "#0F172A")

        style.configure("TFrame", background="#F1F5F9")
        style.configure("Card.TFrame", background="#FFFFFF", relief="flat")
        style.configure("TLabel", background="#FFFFFF", foreground="#1E293B", font=("Segoe UI", 9))
        style.configure("Header.TLabel", background="#0F172A", foreground="#FFFFFF", font=("Segoe UI", 14, "bold"))
        style.configure("SubHeader.TLabel", background="#0F172A", foreground="#94A3B8", font=("Segoe UI", 9))
        style.configure("Section.TLabel", background="#FFFFFF", foreground="#0F172A", font=("Segoe UI", 10, "bold"))
        style.configure(
            "TEntry",
            foreground="#0F172A",
            fieldbackground="#FFFFFF",
            insertcolor="#0F172A",
            selectbackground="#BFDBFE",
            selectforeground="#0F172A",
            padding=5,
        )
        style.configure(
            "TCombobox",
            foreground="#0F172A",
            fieldbackground="#FFFFFF",
            insertcolor="#0F172A",
            selectbackground="#BFDBFE",
            selectforeground="#0F172A",
            padding=4,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", "#FFFFFF"), ("!disabled", "#FFFFFF")],
            foreground=[("readonly", "#0F172A"), ("!disabled", "#0F172A")],
            selectbackground=[("readonly", "#DBEAFE"), ("!disabled", "#DBEAFE")],
            selectforeground=[("readonly", "#0F172A"), ("!disabled", "#0F172A")],
        )
        style.configure("TNotebook", background="#F1F5F9", borderwidth=0)
        style.configure("TNotebook.Tab", font=("Segoe UI", 10, "bold"), padding=(18, 8), background="#E2E8F0", foreground="#334155")
        style.map(
            "TNotebook.Tab",
            background=[("selected", "#FFFFFF"), ("active", "#CBD5E1")],
            foreground=[("selected", "#1D4ED8"), ("active", "#0F172A")],
        )
        style.configure("Treeview", font=("Segoe UI", 10), rowheight=30, background="#FFFFFF", fieldbackground="#FFFFFF", foreground="#0F172A")
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"), padding=(6, 6), background="#F1F5F9", foreground="#0F172A")
        style.map(
            "Treeview",
            background=[("selected", "#DBEAFE")],
            foreground=[("selected", "#1E3A8A")],
        )

        # Estilos de botões com fundo sólido real em macOS e Windows (ttk.Button no tema clam)
        btn_specs = [
            ("Primary.TButton", "#2563EB", "#1D4ED8", "#FFFFFF", ("Segoe UI", 9, "bold"), (12, 7)),
            ("Success.TButton", "#059669", "#047857", "#FFFFFF", ("Segoe UI", 9, "bold"), (12, 7)),
            ("PrintGreen.TButton", "#16A34A", "#15803D", "#FFFFFF", ("Segoe UI", 10, "bold"), (14, 10)),
            ("Amber.TButton", "#D97706", "#B45309", "#FFFFFF", ("Segoe UI", 9, "bold"), (12, 7)),
            ("Dark.TButton", "#1E293B", "#334155", "#FFFFFF", ("Segoe UI", 9, "bold"), (11, 7)),
            ("Secondary.TButton", "#E2E8F0", "#CBD5E1", "#0F172A", ("Segoe UI", 9, "bold"), (10, 6)),
            ("Danger.TButton", "#FEE2E2", "#FECACA", "#991B1B", ("Segoe UI", 9, "bold"), (10, 6)),
        ]
        for st_name, bg_c, active_c, fg_c, fnt, pad_v in btn_specs:
            style.configure(
                st_name,
                background=bg_c,
                foreground=fg_c,
                font=fnt,
                padding=pad_v,
                borderwidth=1,
                focusthickness=0,
                relief="flat",
            )
            style.map(
                st_name,
                background=[("active", active_c), ("pressed", active_c), ("!disabled", bg_c)],
                foreground=[("active", fg_c), ("pressed", fg_c), ("!disabled", fg_c)],
            )

    def _load_saved_config(self) -> LabelLayoutConfig:
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                cfg = LabelLayoutConfig.from_dict(data)
                if "show_logo" not in data:
                    cfg.show_logo = True
                    cfg.logo_height_dots = 24
                if any(ef.column_name == "PATRIMONIO" for ef in cfg.extra_fields) or not data.get("explicit_location_choice", False):
                    cfg.extra_fields = [
                        ExtraFieldConfig(prefix="", column_name="TIPO", font_size=18, bold=True),
                        ExtraFieldConfig(prefix="SN: ", column_name="CODIGO", font_size=16, bold=True),
                    ]
                    cfg.barcode_height_mm = max(10.0, cfg.barcode_height_mm)
                return cfg
            except Exception:
                pass

        return LabelLayoutConfig(
            big_width_mm=100.0,
            big_height_mm=150.0,
            margin_left_mm=3.0,
            margin_top_mm=3.0,
            cols=2,
            rows=5,
            gap_h_mm=2.0,
            gap_v_mm=2.0,
            auto_size_mini=True,
            draw_border=True,
            border_thickness_dots=2,
            draw_cut_marks=True,
            show_logo=True,
            logo_height_dots=24,
            show_header=False,
            header_text="i-STAT",
            header_font_size=18,
            barcode_enabled=True,
            barcode_type="CODE128",
            barcode_column="CODIGO",
            barcode_height_mm=10.5,
            barcode_module_width=2,
            show_barcode_text=True,
            extra_fields=[
                ExtraFieldConfig(prefix="", column_name="TIPO", font_size=18, bold=True),
                ExtraFieldConfig(prefix="SN: ", column_name="CODIGO", font_size=16, bold=True),
            ],
        )

    def _save_config_to_disk(self, silent: bool = False):
        self._sync_ui_to_config()
        try:
            d = self.layout_cfg.to_dict()
            d["explicit_location_choice"] = True
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=2)
            if not silent:
                messagebox.showinfo("Configuração Salva", "Layout da etiqueta salvo como padrão.")
        except Exception as e:
            if not silent:
                messagebox.showerror("Erro ao Salvar", str(e))

    def _build_ui(self):
        # Barra Superior Minimalista & Limpa: Apenas Logo + "Controle de Estoque i-STAT"
        top_bar = tk.Frame(self, bg="#0F172A", height=56)
        top_bar.pack(fill="x", side="top")
        top_bar.pack_propagate(False)

        hdr_logo_photo, _, _ = get_tk_logo_photo(get_default_logo_path(), target_height_px=26)
        if hdr_logo_photo:
            self._hdr_logo_ref = hdr_logo_photo
            logo_badge = tk.Frame(top_bar, bg="#FFFFFF", padx=8, pady=4, highlightthickness=1, highlightbackground="#38BDF8")
            logo_badge.pack(side="left", padx=(16, 6), pady=9)
            tk.Label(logo_badge, image=hdr_logo_photo, bg="#FFFFFF").pack()

        ttk.Label(
            top_bar,
            text="Controle de Estoque i-STAT",
            style="Header.TLabel",
        ).pack(side="left", padx=8)

        # Label discreto de status de sincronização à direita do título (sem poluir)
        self.lbl_sync_status_bar = tk.Label(
            top_bar,
            text="",
            bg="#0F172A",
            fg="#38BDF8",
            font=("Segoe UI", 8, "bold"),
            anchor="w",
        )
        self.lbl_sync_status_bar.pack(side="left", padx=(12, 0))

        btn_box = tk.Frame(top_bar, bg="#0F172A")
        btn_box.pack(side="right", padx=16)

        # 1. Seletor Limpo de Operador
        op_frame = tk.Frame(btn_box, bg="#1E293B", padx=8, pady=4, highlightthickness=1, highlightbackground="#334155")
        op_frame.pack(side="left", padx=(0, 8))
        tk.Label(op_frame, text="Operador:", bg="#1E293B", fg="#94A3B8", font=("Segoe UI", 8, "bold")).pack(side="left")
        self.cmb_operador_top = ttk.Combobox(
            op_frame,
            textvariable=self.var_operador_atual,
            values=self.db.operators,
            width=14,
            font=("Segoe UI", 9, "bold"),
        )
        self.cmb_operador_top.pack(side="left", padx=(6, 0))

        # 2. Botão Etiquetas (Plus sob demanda)
        self.btn_toggle_preview = ttk.Button(
            btn_box,
            text=" Etiquetas",
            image=self.icons.get("grid", "#FFFFFF"),
            compound="left",
            style="Dark.TButton",
            cursor="hand2",
            command=self._toggle_preview_panel,
        )
        self.btn_toggle_preview.pack(side="left", padx=4)

        # 3. Botão Configurações
        ttk.Button(
            btn_box,
            text=" Configurações",
            image=self.icons.get("printer", "#FFFFFF"),
            compound="left",
            style="Dark.TButton",
            cursor="hand2",
            command=self._open_settings_tab,
        ).pack(side="left", padx=(4, 0))

        # Painel principal
        self.main_paned = tk.PanedWindow(self, orient="horizontal", bg="#CBD5E1", sashwidth=5, bd=0)
        self.main_paned.pack(fill="both", expand=True, padx=12, pady=10)

        self.left_container = ttk.Frame(self.main_paned)
        self.right_container = ttk.Frame(self.main_paned, style="Card.TFrame")
        self.main_paned.add(self.left_container, minsize=740)
        if self.preview_visible:
            self.main_paned.add(self.right_container, minsize=430)

        self.notebook = ttk.Notebook(self.left_container)
        self.notebook.pack(fill="both", expand=True)

        self.tab_data = ttk.Frame(self.notebook, style="Card.TFrame")
        self.tab_clients = ttk.Frame(self.notebook, style="Card.TFrame")
        self.tab_scanner = ttk.Frame(self.notebook, style="Card.TFrame")
        self.tab_settings = ttk.Frame(self.notebook, style="Card.TFrame")

        self.notebook.add(
            self.tab_data,
            text="  Estoque  ",
            image=self.icons.get("box", "#0F172A"),
            compound="left",
        )
        self.notebook.add(
            self.tab_clients,
            text="  Clientes  ",
            image=self.icons.get("route", "#0F172A"),
            compound="left",
        )
        self.notebook.add(
            self.tab_scanner,
            text="  Histórico & Bipagem  ",
            image=self.icons.get("barcode", "#0F172A"),
            compound="left",
        )
        self.notebook.add(
            self.tab_settings,
            text="  Configurações  ",
            image=self.icons.get("printer", "#0F172A"),
            compound="left",
        )

        # Sub-abas organizadas dentro de Configurações
        settings_pad = tk.Frame(self.tab_settings, bg="#F8FAFC", padx=8, pady=8)
        settings_pad.pack(fill="both", expand=True)

        self.sub_notebook = ttk.Notebook(settings_pad)
        self.sub_notebook.pack(fill="both", expand=True)

        self.tab_zpl = ttk.Frame(self.sub_notebook, style="Card.TFrame")
        self.tab_layout = ttk.Frame(self.sub_notebook, style="Card.TFrame")
        self.tab_fields = ttk.Frame(self.sub_notebook, style="Card.TFrame")

        self.sub_notebook.add(
            self.tab_zpl,
            text="  Sede Lyda, SharePoint, Operadores & Impressora  ",
            image=self.icons.get("printer", "#0F172A"),
            compound="left",
        )
        self.sub_notebook.add(
            self.tab_layout,
            text="  Etiqueta: Tamanho & Grade  ",
            image=self.icons.get("grid", "#0F172A"),
            compound="left",
        )
        self.sub_notebook.add(
            self.tab_fields,
            text="  Etiqueta: Texto & Logo  ",
            image=self.icons.get("tag", "#0F172A"),
            compound="left",
        )

        self._build_tab_data()
        self._build_tab_clients()
        self._build_tab_scanner()
        self._build_tab_layout()
        self._build_tab_fields()
        self._build_tab_zpl()
        self._build_right_preview_panel(self.right_container)
        self.notebook.bind("<<NotebookTabChanged>>", self._on_notebook_tab_changed)

    def _open_settings_tab(self):
        """Abre diretamente a aba de Configurações."""
        self.notebook.select(self.tab_settings)
        self.sub_notebook.select(self.tab_zpl)

    def _toggle_preview_panel(self):
        """Mostra ou esconde o painel direito de Etiquetas."""
        if self.preview_visible:
            try:
                self.main_paned.forget(self.right_container)
            except Exception:
                pass
            self.preview_visible = False
            self.btn_toggle_preview.configure(
                text=" Etiquetas",
                style="Dark.TButton",
            )
        else:
            try:
                self.main_paned.add(self.right_container, minsize=430)
            except Exception:
                pass
            self.preview_visible = True
            self.btn_toggle_preview.configure(
                text=" Fechar Etiquetas",
                style="Amber.TButton",
            )
            self.after(60, self._draw_canvas_preview)

    def _on_notebook_tab_changed(self, _event=None):
        try:
            current_tab = self.notebook.select()
            if current_tab == str(self.tab_scanner):
                self.after(60, lambda: self.ent_scanner.focus_set())
        except Exception:
            pass

    # =========================================================================
    # ABA 1: CONTROLE DE ESTOQUE i-STAT (INTERFACE LIMPA + SELEÇÃO DE VÁRIOS)
    # =========================================================================
    def _build_tab_data(self):
        pad = tk.Frame(self.tab_data, bg="#FFFFFF", padx=16, pady=12)
        pad.pack(fill="both", expand=True)

        # 1. Cinco Cards Limpos e Espaçosos de Resumo (Clique para Filtrar)
        self.cards_frame = tk.Frame(pad, bg="#FFFFFF")
        self.cards_frame.pack(fill="x", pady=(0, 10))
        self.lbl_counter_cards: Dict[str, tk.Label] = {}

        card_specs = [
            ("TODOS", "Todos os Aparelhos", "#0F172A", "#F8FAFC"),
            ("ATIVOS_CLIENTES", "Em Hospitais / Clientes", "#1D4ED8", "#EFF6FF"),
            ("ESTOQUE_LYDA", "No Estoque Lyda", "#15803D", "#DCFCE7"),
            ("COMODATO", "Em Comodato", "#0369A1", "#E0F2FE"),
            ("VENDA", "Venda (Clientes)", "#4F46E5", "#EEF2FF"),
            ("ATT_PENDENTE_6M", "Atualização Pendente (6m)", "#B45309", "#FEF3C7"),
            ("DEFEITO_MANUT", "Em Manutenção / Defeito", "#B91C1C", "#FEE2E2"),
        ]
        for idx, (key, title, fg_col, bg_col) in enumerate(card_specs):
            cf = tk.Frame(
                self.cards_frame,
                bg=bg_col,
                padx=14,
                pady=8,
                highlightthickness=1,
                highlightbackground="#CBD5E1",
                cursor="hand2",
            )
            cf.grid(row=0, column=idx, sticky="ew", padx=4)
            self.cards_frame.columnconfigure(idx, weight=1)
            lbl_t = tk.Label(cf, text=title, bg=bg_col, fg=fg_col, font=("Segoe UI", 9, "bold"))
            lbl_t.pack(anchor="w")
            lbl_v = tk.Label(cf, text="0", bg=bg_col, fg=fg_col, font=("Segoe UI", 16, "bold"))
            lbl_v.pack(anchor="w", pady=(2, 0))
            self.lbl_counter_cards[key] = lbl_v

            for w in (cf, lbl_t, lbl_v):
                w.bind("<Button-1>", lambda _e, k=key: self._quick_filter_by_type(k))

        # 2. Barra Única e Limpa de Busca + Filtros
        filter_bar = tk.Frame(pad, bg="#F8FAFC", padx=12, pady=8, highlightthickness=1, highlightbackground="#E2E8F0")
        filter_bar.pack(fill="x", pady=(0, 10))

        tk.Label(
            filter_bar,
            text=" Buscar:",
            image=self.icons.get("search", "#334155"),
            compound="left",
            bg="#F8FAFC",
            fg="#0F172A",
            font=("Segoe UI", 9, "bold"),
        ).pack(side="left")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._populate_data_tree())
        ttk.Entry(filter_bar, textvariable=self.search_var, width=28, font=("Segoe UI", 10)).pack(
            side="left", padx=(6, 14), fill="x", expand=True
        )

        tk.Label(filter_bar, text="Equipamento:", bg="#F8FAFC", fg="#334155", font=("Segoe UI", 9, "bold")).pack(side="left")
        self.filter_type_var = tk.StringVar(value="TODOS")
        cmb_ft = ttk.Combobox(
            filter_bar,
            textvariable=self.filter_type_var,
            values=["TODOS"] + EQUIPMENT_TYPES,
            state="readonly",
            width=13,
        )
        cmb_ft.pack(side="left", padx=(4, 12))
        cmb_ft.bind("<<ComboboxSelected>>", lambda _e: self._populate_data_tree())

        tk.Label(filter_bar, text="Modalidade:", bg="#F8FAFC", fg="#334155", font=("Segoe UI", 9, "bold")).pack(side="left")
        self.filter_mod_var = tk.StringVar(value="TODAS")
        cmb_fm = ttk.Combobox(
            filter_bar,
            textvariable=self.filter_mod_var,
            values=["TODAS", "COMODATO", "VENDA", "PROPRIEDADE LYDA", "ALUGUEL"],
            state="readonly",
            width=15,
        )
        cmb_fm.pack(side="left", padx=(4, 12))
        cmb_fm.bind("<<ComboboxSelected>>", lambda _e: self._populate_data_tree())

        tk.Label(filter_bar, text="Filtro:", bg="#F8FAFC", fg="#334155", font=("Segoe UI", 9, "bold")).pack(side="left")
        self.filter_status_var = tk.StringVar(value="TODOS")
        status_filter_opts = [
            "TODOS",
            "DISPONÍVEIS NO ESTOQUE LYDA (SEM CLIENTE)",
            "ATIVOS EM CLIENTES / HOSPITAIS",
            "ATUALIZAÇÃO 6 MESES VENCIDA OU PENDENTE",
            "ATUALIZAÇÃO 6 MESES EM DIA",
            "ESTOQUE LYDA: JÁ ATUALIZADOS NA BANCADA",
            "ESTOQUE LYDA: FALTA ATUALIZAR NA BANCADA",
            "COM DEFEITO / EM MANUTENÇÃO",
        ]
        cmb_fs = ttk.Combobox(
            filter_bar,
            textvariable=self.filter_status_var,
            values=status_filter_opts,
            state="readonly",
            width=32,
        )
        cmb_fs.pack(side="left", padx=(4, 8))
        cmb_fs.bind("<<ComboboxSelected>>", lambda _e: self._populate_data_tree())

        ttk.Button(
            filter_bar,
            text=" Limpar Filtros",
            style="Secondary.TButton",
            cursor="hand2",
            command=lambda: [
                self.search_var.set(""),
                self.filter_type_var.set("TODOS"),
                self.filter_mod_var.set("TODAS"),
                self.filter_status_var.set("TODOS"),
                self._populate_data_tree(),
            ],
        ).pack(side="left")

        # 3. Barra de Ações Diretas + Seleção de Vários Aparelhos
        action_bar = tk.Frame(pad, bg="#FFFFFF")
        action_bar.pack(fill="x", pady=(0, 8))

        self.btn_main_edit = ttk.Button(
            action_bar,
            text=" Editar / Movimentar",
            image=self.icons.get("edit", "#FFFFFF"),
            compound="left",
            style="Success.TButton",
            cursor="hand2",
            command=self._open_movement_for_selected,
        )
        self.btn_main_edit.pack(side="left", padx=(0, 6))

        ttk.Button(
            action_bar,
            text=" + Novo Aparelho",
            image=self.icons.get("plus", "#FFFFFF"),
            compound="left",
            style="Primary.TButton",
            cursor="hand2",
            command=lambda: self._open_item_dialog(edit_index=None),
        ).pack(side="left", padx=3)

        ttk.Button(
            action_bar,
            text=" Atualizar 6m (Hoje)",
            image=self.icons.get("check", "#FFFFFF"),
            compound="left",
            style="Dark.TButton",
            cursor="hand2",
            command=self._batch_mark_updated_today,
        ).pack(side="left", padx=3)

        ttk.Button(
            action_bar,
            text=" Rota da Enfermeira",
            image=self.icons.get("route", "#FFFFFF"),
            compound="left",
            style="Amber.TButton",
            cursor="hand2",
            command=self._open_nurse_route_modal,
        ).pack(side="left", padx=3)

        ttk.Button(
            action_bar,
            text=" Excluir",
            image=self.icons.get("trash", "#991B1B"),
            compound="left",
            style="Danger.TButton",
            cursor="hand2",
            command=self._delete_selected_rows,
        ).pack(side="left", padx=3)

        # Controles de Seleção Múltipla à direita ("Selecionar Vários")
        self.copies_per_item_var = tk.IntVar(value=1)

        ttk.Button(
            action_bar,
            text=" Limpar Seleção",
            image=self.icons.get("uncheck", "#0F172A"),
            compound="left",
            style="Secondary.TButton",
            cursor="hand2",
            command=self._deselect_all_rows,
        ).pack(side="right", padx=(4, 0))

        ttk.Button(
            action_bar,
            text=" Marcar Todos Visíveis",
            image=self.icons.get("check", "#0F172A"),
            compound="left",
            style="Secondary.TButton",
            cursor="hand2",
            command=self._select_all_rows,
        ).pack(side="right", padx=4)

        self.lbl_multi_sel_badge = tk.Label(
            action_bar,
            text="Clique na 1ª coluna [  ] para selecionar vários",
            bg="#F1F5F9",
            fg="#475569",
            font=("Segoe UI", 9, "bold"),
            padx=10,
            pady=5,
        )
        self.lbl_multi_sel_badge.pack(side="right", padx=6)

        # 4. Tabela Limpa com Coluna de Checkbox [✓] para Selecionar Vários
        tree_frame = tk.Frame(pad, bg="#FFFFFF")
        tree_frame.pack(fill="both", expand=True)

        self.tree = ttk.Treeview(tree_frame, selectmode="extended", show="headings")
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

        self.tree.tag_configure("ANALISADOR", background="#FFFFFF")
        self.tree.tag_configure("IMPRESSORA", background="#F8FAFC")
        self.tree.tag_configure("SIMULADOR", background="#FFFFFF")
        self.tree.tag_configure("DOWNLOADER", background="#F8FAFC")
        self.tree.tag_configure("ROW_DEFEITO", background="#FEE2E2", foreground="#991B1B")
        self.tree.tag_configure("ROW_ESTOQUE", background="#DCFCE7", foreground="#166534")
        self.tree.tag_configure("ROW_ATT_VENCIDA", background="#FEF3C7", foreground="#92400E")
        self.tree.tag_configure("ROW_CHECKED", background="#DBEAFE", foreground="#1E3A8A")

        self.tree.bind("<Button-1>", self._on_tree_click_check, add="+")
        self.tree.bind("<space>", self._on_tree_space_toggle)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_selection_changed)
        self.tree.bind("<Double-1>", self._on_tree_double_click)

        self.lbl_selection_summary = tk.Label(
            pad,
            text="",
            bg="#FFFFFF",
            fg="#475569",
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        )
        self.lbl_selection_summary.pack(fill="x", pady=(6, 0))

    # =========================================================================
    # ABA CLIENTES: CADASTRO COMPLETO DE HOSPITAIS/CLÍNICAS E APARELHOS VINCULADOS
    # =========================================================================
    def _build_tab_clients(self):
        pad = tk.Frame(self.tab_clients, bg="#FFFFFF", padx=14, pady=12)
        pad.pack(fill="both", expand=True)

        self._selected_client_original_name: str = ""
        self._current_client_linked_indices: List[int] = []

        # Divisão Horizontal: Esquerda = Lista de Clientes | Direita = Cadastro + Aparelhos Vinculados
        paned_cli = tk.PanedWindow(pad, orient="horizontal", bg="#CBD5E1", sashwidth=5, bd=0)
        paned_cli.pack(fill="both", expand=True)

        left_box = tk.Frame(paned_cli, bg="#FFFFFF", padx=6, pady=4)
        right_box = tk.Frame(paned_cli, bg="#FFFFFF", padx=8, pady=4)
        paned_cli.add(left_box, minsize=350, width=390)
        paned_cli.add(right_box, minsize=560)

        # ---------------------------------------------------------------------
        # COLUNA ESQUERDA: BUSCA + LISTA DE CLIENTES CADASTRADOS
        # ---------------------------------------------------------------------
        left_hdr = tk.Frame(left_box, bg="#F8FAFC", padx=10, pady=8, highlightthickness=1, highlightbackground="#E2E8F0")
        left_hdr.pack(fill="x", pady=(0, 8))

        top_l_row = tk.Frame(left_hdr, bg="#F8FAFC")
        top_l_row.pack(fill="x", pady=(0, 6))

        tk.Label(
            top_l_row,
            text="Hospitais / Clientes",
            bg="#F8FAFC",
            fg="#0F172A",
            font=("Segoe UI", 11, "bold"),
        ).pack(side="left")

        ttk.Button(
            top_l_row,
            text=" + Novo Cliente",
            image=self.icons.get("plus", "#FFFFFF"),
            compound="left",
            style="Primary.TButton",
            cursor="hand2",
            command=self._clear_client_form_for_new,
        ).pack(side="right")

        search_l_row = tk.Frame(left_hdr, bg="#F8FAFC")
        search_l_row.pack(fill="x")

        tk.Label(
            search_l_row,
            text="Buscar:",
            image=self.icons.get("search", "#334155"),
            compound="left",
            bg="#F8FAFC",
            fg="#0F172A",
            font=("Segoe UI", 9, "bold"),
        ).pack(side="left")

        self.var_client_search = tk.StringVar()
        ent_c_search = ttk.Entry(search_l_row, textvariable=self.var_client_search, font=("Segoe UI", 10))
        ent_c_search.pack(side="left", fill="x", expand=True, padx=(6, 0))
        ent_c_search.bind("<KeyRelease>", lambda _e: self._refresh_clients_tab(preserve_selection=True))

        # Tabela de Clientes
        cli_tree_frame = tk.Frame(left_box, bg="#FFFFFF")
        cli_tree_frame.pack(fill="both", expand=True)

        cols_c = ("CLIENTE", "CIDADE_UF", "APARELHOS", "CICLO")
        self.tree_clients = ttk.Treeview(cli_tree_frame, columns=cols_c, show="headings", selectmode="browse")
        for c_id, c_title, c_w in [
            ("CLIENTE", "Hospital / Clínica / Cliente", 185),
            ("CIDADE_UF", "Cidade / UF", 95),
            ("APARELHOS", "Aparelhos", 72),
            ("CICLO", "Ciclo 6m", 85),
        ]:
            self.tree_clients.heading(c_id, text=c_title)
            self.tree_clients.column(c_id, width=c_w, anchor="center" if c_id in ("APARELHOS", "CICLO") else "w")

        self.tree_clients.tag_configure("CLI_OK", background="#FFFFFF", foreground="#0F172A")
        self.tree_clients.tag_configure("CLI_PEND", background="#FEF3C7", foreground="#92400E")

        vsb_c = ttk.Scrollbar(cli_tree_frame, orient="vertical", command=self.tree_clients.yview)
        self.tree_clients.configure(yscrollcommand=vsb_c.set)
        self.tree_clients.pack(side="left", fill="both", expand=True)
        vsb_c.pack(side="right", fill="y")

        self.tree_clients.bind("<<TreeviewSelect>>", self._on_client_tree_selected)

        self.lbl_clients_total = tk.Label(
            left_box,
            text="",
            bg="#FFFFFF",
            fg="#475569",
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        )
        self.lbl_clients_total.pack(fill="x", pady=(6, 0))

        # ---------------------------------------------------------------------
        # COLUNA DIREITA — PARTE 1: CADASTRO COMPLETO DO CLIENTE SELECIONADO
        # ---------------------------------------------------------------------
        self.lf_client_form = tk.LabelFrame(
            right_box,
            text=" 1. Cadastro do Cliente / Hospital Selecionado ",
            bg="#FFFFFF",
            fg="#0F172A",
            font=("Segoe UI", 10, "bold"),
            padx=12,
            pady=8,
        )
        self.lf_client_form.pack(fill="x", pady=(0, 10))
        for col_i in range(4):
            self.lf_client_form.columnconfigure(col_i, weight=1)

        self.v_cli_nome = tk.StringVar()
        self.v_cli_cnpj = tk.StringVar()
        self.v_cli_setores = tk.StringVar()
        self.v_cli_endereco = tk.StringVar()
        self.v_cli_cep = tk.StringVar()
        self.v_cli_cidade = tk.StringVar(value="PORTO ALEGRE")
        self.v_cli_uf = tk.StringVar(value="RS")
        self.v_cli_contato = tk.StringVar()
        self.v_cli_telefone = tk.StringVar()
        self.v_cli_email = tk.StringVar()
        self.v_cli_obs = tk.StringVar()

        # Linha 0 & 1: Nome do Hospital, CNPJ, Setores
        tk.Label(
            self.lf_client_form,
            text="Nome do Hospital / Clínica / Cliente:",
            bg="#FFFFFF",
            fg="#0F172A",
            font=("Segoe UI", 9, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=4)
        self.ent_cli_nome = ttk.Entry(self.lf_client_form, textvariable=self.v_cli_nome, font=("Segoe UI", 10, "bold"))
        self.ent_cli_nome.grid(row=1, column=0, columnspan=2, sticky="ew", padx=4, pady=(2, 6))

        tk.Label(
            self.lf_client_form,
            text="CNPJ / Código (opcional):",
            bg="#FFFFFF",
            fg="#0F172A",
            font=("Segoe UI", 9, "bold"),
        ).grid(row=0, column=2, sticky="w", padx=4)
        ttk.Entry(self.lf_client_form, textvariable=self.v_cli_cnpj).grid(row=1, column=2, sticky="ew", padx=4, pady=(2, 6))

        tk.Label(
            self.lf_client_form,
            text="Setores Atendidos (ex: UTI, Emergência):",
            bg="#FFFFFF",
            fg="#0F172A",
            font=("Segoe UI", 9, "bold"),
        ).grid(row=0, column=3, sticky="w", padx=4)
        ttk.Entry(self.lf_client_form, textvariable=self.v_cli_setores).grid(row=1, column=3, sticky="ew", padx=4, pady=(2, 6))

        # Linha 2 & 3: Endereço Completo, CEP + Buscar CEP, Cidade / UF
        tk.Label(
            self.lf_client_form,
            text="Endereço Completo (Rua/Av., Número, Bairro):",
            bg="#FFFFFF",
            fg="#1E3A8A",
            font=("Segoe UI", 9, "bold"),
        ).grid(row=2, column=0, columnspan=2, sticky="w", padx=4)
        ttk.Entry(self.lf_client_form, textvariable=self.v_cli_endereco).grid(
            row=3, column=0, columnspan=2, sticky="ew", padx=4, pady=(2, 6)
        )

        tk.Label(
            self.lf_client_form,
            text="CEP:",
            bg="#FFFFFF",
            fg="#1E3A8A",
            font=("Segoe UI", 9, "bold"),
        ).grid(row=2, column=2, sticky="w", padx=4)
        c_cep_box = tk.Frame(self.lf_client_form, bg="#FFFFFF")
        c_cep_box.grid(row=3, column=2, sticky="ew", padx=4, pady=(2, 6))
        ttk.Entry(c_cep_box, textvariable=self.v_cli_cep, width=10).pack(side="left", fill="x", expand=True)

        def _buscar_cep_aba_cli():
            ok_c, data_c, msg_c = lookup_cep_viacep(self.v_cli_cep.get())
            if ok_c:
                self.v_cli_cep.set(data_c.get("CEP", self.v_cli_cep.get()))
                if data_c.get("ENDERECO"):
                    self.v_cli_endereco.set(data_c["ENDERECO"])
                if data_c.get("CIDADE"):
                    self.v_cli_cidade.set(data_c["CIDADE"])
                if data_c.get("UF"):
                    self.v_cli_uf.set(data_c["UF"])
            else:
                messagebox.showwarning("Consulta CEP", msg_c)

        ttk.Button(c_cep_box, text="Buscar CEP", style="Secondary.TButton", cursor="hand2", command=_buscar_cep_aba_cli).pack(
            side="left", padx=(4, 0)
        )

        tk.Label(
            self.lf_client_form,
            text="Cidade / UF:",
            bg="#FFFFFF",
            fg="#0F172A",
            font=("Segoe UI", 9, "bold"),
        ).grid(row=2, column=3, sticky="w", padx=4)
        c_cid_box = tk.Frame(self.lf_client_form, bg="#FFFFFF")
        c_cid_box.grid(row=3, column=3, sticky="ew", padx=4, pady=(2, 6))
        ttk.Entry(c_cid_box, textvariable=self.v_cli_cidade, width=13).pack(side="left", fill="x", expand=True)
        ttk.Combobox(c_cid_box, textvariable=self.v_cli_uf, values=["RS", "SC", "PR", "SP", "RJ", "MG", "OUTRO"], width=4).pack(
            side="left", padx=(4, 0)
        )

        # Linha 4 & 5: Contato, Telefone/WhatsApp, E-mail, Observações do Cliente
        tk.Label(
            self.lf_client_form,
            text="Contato / Enfermeiro(a) no Local:",
            bg="#FFFFFF",
            fg="#0F172A",
            font=("Segoe UI", 9, "bold"),
        ).grid(row=4, column=0, sticky="w", padx=4)
        ttk.Entry(self.lf_client_form, textvariable=self.v_cli_contato).grid(row=5, column=0, sticky="ew", padx=4, pady=(2, 8))

        tk.Label(
            self.lf_client_form,
            text="Telefone / WhatsApp:",
            bg="#FFFFFF",
            fg="#0F172A",
            font=("Segoe UI", 9, "bold"),
        ).grid(row=4, column=1, sticky="w", padx=4)
        ttk.Entry(self.lf_client_form, textvariable=self.v_cli_telefone).grid(row=5, column=1, sticky="ew", padx=4, pady=(2, 8))

        tk.Label(
            self.lf_client_form,
            text="E-mail:",
            bg="#FFFFFF",
            fg="#0F172A",
            font=("Segoe UI", 9, "bold"),
        ).grid(row=4, column=2, sticky="w", padx=4)
        ttk.Entry(self.lf_client_form, textvariable=self.v_cli_email).grid(row=5, column=2, sticky="ew", padx=4, pady=(2, 8))

        tk.Label(
            self.lf_client_form,
            text="Observações do Cliente:",
            bg="#FFFFFF",
            fg="#0F172A",
            font=("Segoe UI", 9, "bold"),
        ).grid(row=4, column=3, sticky="w", padx=4)
        ttk.Entry(self.lf_client_form, textvariable=self.v_cli_obs).grid(row=5, column=3, sticky="ew", padx=4, pady=(2, 8))

        # Barra de Botões do Cadastro do Cliente
        cli_btn_bar = tk.Frame(self.lf_client_form, bg="#F8FAFC", padx=8, pady=6)
        cli_btn_bar.grid(row=6, column=0, columnspan=4, sticky="ew", padx=4)

        ttk.Button(
            cli_btn_bar,
            text=" Salvar Cadastro do Cliente",
            image=self.icons.get("save", "#FFFFFF"),
            compound="left",
            style="Success.TButton",
            cursor="hand2",
            command=self._save_client_form,
        ).pack(side="left", padx=(0, 6))

        ttk.Button(
            cli_btn_bar,
            text=" Abrir Endereço no Google Maps",
            image=self.icons.get("route", "#0F172A"),
            compound="left",
            style="Secondary.TButton",
            cursor="hand2",
            command=lambda: webbrowser.open(
                build_single_stop_maps_url(
                    {
                        "CLIENTE": self.v_cli_nome.get(),
                        "ENDERECO": self.v_cli_endereco.get(),
                        "CEP": self.v_cli_cep.get(),
                        "CIDADE": self.v_cli_cidade.get(),
                        "UF": self.v_cli_uf.get(),
                    }
                )
            ),
        ).pack(side="left", padx=4)

        ttk.Button(
            cli_btn_bar,
            text=" Gerar Rota + PDF p/ este Cliente",
            image=self.icons.get("route", "#FFFFFF"),
            compound="left",
            style="Primary.TButton",
            cursor="hand2",
            command=lambda: self._open_nurse_route_modal(initial_client_name=self.v_cli_nome.get().strip()),
        ).pack(side="left", padx=4)

        ttk.Button(
            cli_btn_bar,
            text=" Romaneio / Ficha A4 do Cliente",
            image=self.icons.get("printer", "#FFFFFF"),
            compound="left",
            style="Dark.TButton",
            cursor="hand2",
            command=self._generate_client_romaneio,
        ).pack(side="left", padx=4)

        ttk.Button(
            cli_btn_bar,
            text=" Excluir Cliente",
            image=self.icons.get("trash", "#991B1B"),
            compound="left",
            style="Danger.TButton",
            cursor="hand2",
            command=self._delete_selected_client,
        ).pack(side="right")

        # ---------------------------------------------------------------------
        # COLUNA DIREITA — PARTE 2: TODOS OS APARELHOS VINCULADOS A ESTE CLIENTE
        # ---------------------------------------------------------------------
        self.lf_client_devices = tk.LabelFrame(
            right_box,
            text=" 2. Aparelhos i-STAT Vinculados a este Cliente ",
            bg="#FFFFFF",
            fg="#0F172A",
            font=("Segoe UI", 10, "bold"),
            padx=12,
            pady=8,
        )
        self.lf_client_devices.pack(fill="both", expand=True)

        dev_act_bar = tk.Frame(self.lf_client_devices, bg="#EFF6FF", padx=8, pady=6)
        dev_act_bar.pack(fill="x", pady=(0, 8))

        ttk.Button(
            dev_act_bar,
            text=" Editar / Ver Aparelho",
            image=self.icons.get("edit", "#FFFFFF"),
            compound="left",
            style="Primary.TButton",
            cursor="hand2",
            command=self._open_selected_client_device_modal,
        ).pack(side="left", padx=(0, 6))

        ttk.Button(
            dev_act_bar,
            text=" + Vincular Aparelho do Estoque",
            image=self.icons.get("plus", "#FFFFFF"),
            compound="left",
            style="Success.TButton",
            cursor="hand2",
            command=self._open_link_stock_device_to_client_dialog,
        ).pack(side="left", padx=4)

        ttk.Button(
            dev_act_bar,
            text=" Atualizar Todos Hoje (6m)",
            image=self.icons.get("check", "#FFFFFF"),
            compound="left",
            style="Amber.TButton",
            cursor="hand2",
            command=self._mark_all_client_devices_updated_today,
        ).pack(side="left", padx=4)

        ttk.Button(
            dev_act_bar,
            text=" Devolver p/ Estoque Lyda",
            image=self.icons.get("download", "#0F172A"),
            compound="left",
            style="Secondary.TButton",
            cursor="hand2",
            command=self._return_selected_client_device_to_stock,
        ).pack(side="right")

        # Tabela dos Aparelhos Vinculados ao Cliente
        dev_tree_box = tk.Frame(self.lf_client_devices, bg="#FFFFFF")
        dev_tree_box.pack(fill="both", expand=True)

        cols_cd = ("TIPO", "CODIGO", "SETOR", "MODALIDADE", "STATUS", "CICLO_6M", "OBSERVACOES")
        self.tree_client_items = ttk.Treeview(dev_tree_box, columns=cols_cd, show="headings", selectmode="browse")
        for c_id, c_title, c_w in [
            ("TIPO", "Equipamento", 105),
            ("CODIGO", "Nº de Série", 100),
            ("SETOR", "Setor / Ala", 125),
            ("MODALIDADE", "Modalidade", 110),
            ("STATUS", "Status", 130),
            ("CICLO_6M", "Ciclo 6 Meses", 155),
            ("OBSERVACOES", "Observações do Aparelho", 260),
        ]:
            self.tree_client_items.heading(c_id, text=c_title)
            self.tree_client_items.column(c_id, width=c_w, anchor="w")

        self.tree_client_items.tag_configure("DEV_OK", background="#FFFFFF", foreground="#0F172A")
        self.tree_client_items.tag_configure("DEV_PEND", background="#FEF3C7", foreground="#92400E")
        self.tree_client_items.tag_configure("DEV_DEF", background="#FEE2E2", foreground="#991B1B")

        vsb_cd = ttk.Scrollbar(dev_tree_box, orient="vertical", command=self.tree_client_items.yview)
        self.tree_client_items.configure(yscrollcommand=vsb_cd.set)
        self.tree_client_items.pack(side="left", fill="both", expand=True)
        vsb_cd.pack(side="right", fill="y")

        self.tree_client_items.bind("<Double-1>", lambda _e: self._open_selected_client_device_modal())

        self.lbl_client_devices_summary = tk.Label(
            self.lf_client_devices,
            text="Selecione um cliente na lista à esquerda para ver seu cadastro e todos os aparelhos vinculados.",
            bg="#FFFFFF",
            fg="#1E3A8A",
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        )
        self.lbl_client_devices_summary.pack(fill="x", pady=(6, 0))

        self._refresh_clients_tab()

    def _refresh_clients_tab(self, preserve_selection: bool = True, select_client_name: str = ""):
        if not hasattr(self, "tree_clients"):
            return
        prev_name = select_client_name or self._selected_client_original_name
        query = (self.var_client_search.get() or "").strip().lower()
        all_clients = self.db.get_all_clients_records()

        self.tree_clients.delete(*self.tree_clients.get_children())
        shown_clients: List[Dict[str, Any]] = []

        for idx, c in enumerate(all_clients):
            c_name = c.get("CLIENTE", "")
            cid_uf = f"{c.get('CIDADE', '')} / {c.get('UF', '')}".strip(" /")
            if query and query not in f"{c_name} {cid_uf} {c.get('ENDERECO', '')} {c.get('CONTATO_LOCAL', '')}".lower():
                continue
            shown_clients.append(c)
            tot = c.get("_total_aparelhos", 0)
            pend = c.get("_pendentes_6m", 0)
            ciclo_str = f"{pend} Pendente(s)" if pend > 0 else ("Em Dia" if tot > 0 else "-")
            tag = "CLI_PEND" if pend > 0 else "CLI_OK"
            self.tree_clients.insert(
                "",
                "end",
                iid=str(idx),
                values=(c_name, cid_uf, f"{tot} ap.", ciclo_str),
                tags=(tag,),
            )

        self.lbl_clients_total.configure(
            text=f"Total: {len(shown_clients)} cliente(s) cadastrado(s)"
        )

        # Restaura a seleção ou seleciona o 1º cliente automaticamente
        target_iid = None
        if preserve_selection and prev_name:
            for iid in self.tree_clients.get_children():
                vals = self.tree_clients.item(iid, "values")
                if vals and str(vals[0]).strip().upper() == prev_name.strip().upper():
                    target_iid = iid
                    break
        if target_iid is None:
            children = self.tree_clients.get_children()
            if children:
                target_iid = children[0]

        if target_iid is not None:
            self.tree_clients.selection_set(target_iid)
            self.tree_clients.see(target_iid)
            self._on_client_tree_selected()

    def _on_client_tree_selected(self, _event=None):
        sel = self.tree_clients.selection()
        if not sel:
            return
        vals = self.tree_clients.item(sel[0], "values")
        if not vals:
            return
        cli_name = str(vals[0]).strip()
        rec = self.db.get_client_record(cli_name) or {"CLIENTE": cli_name}
        self._selected_client_original_name = cli_name

        self.v_cli_nome.set(rec.get("CLIENTE", cli_name))
        self.v_cli_cnpj.set(rec.get("CNPJ", ""))
        self.v_cli_setores.set(rec.get("SETORES", ""))
        self.v_cli_endereco.set(rec.get("ENDERECO", ""))
        self.v_cli_cep.set(rec.get("CEP", ""))
        self.v_cli_cidade.set(rec.get("CIDADE", "PORTO ALEGRE"))
        self.v_cli_uf.set(rec.get("UF", "RS"))
        self.v_cli_contato.set(rec.get("CONTATO_LOCAL", ""))
        self.v_cli_telefone.set(rec.get("TELEFONE", ""))
        self.v_cli_email.set(rec.get("EMAIL", ""))
        self.v_cli_obs.set(rec.get("OBSERVACOES", ""))

        self.lf_client_form.configure(text=f" 1. Cadastro do Cliente: {cli_name} ")
        self._populate_selected_client_devices(cli_name)

    def _populate_selected_client_devices(self, cli_name: str):
        self.tree_client_items.delete(*self.tree_client_items.get_children())
        self._current_client_linked_indices = []
        linked = self.db.get_client_items(cli_name)
        default_cyc = getattr(self.db, "default_update_cycle_months", 6)

        counts_by_type: Dict[str, int] = {}
        for db_idx, it in linked:
            self._current_client_linked_indices.append(db_idx)
            tp = it.get("TIPO", "ANALISADOR")
            counts_by_type[tp] = counts_by_type.get(tp, 0) + 1
            c_info = compute_update_cycle_info(it, default_cyc)
            row_st = classify_item_row_state(it)
            if row_st == "DEFEITO":
                tag = "DEV_DEF"
            elif c_info["status_code"] in ("VENCIDA", "VENCENDO", "SEM_DATA"):
                tag = "DEV_PEND"
            else:
                tag = "DEV_OK"

            self.tree_client_items.insert(
                "",
                "end",
                iid=str(db_idx),
                values=(
                    tp,
                    it.get("CODIGO", ""),
                    it.get("SETOR", ""),
                    it.get("MODALIDADE", ""),
                    it.get("STATUS", ""),
                    c_info["badge_text"],
                    it.get("OBSERVACOES", ""),
                ),
                tags=(tag,),
            )

        self.lf_client_devices.configure(
            text=f" 2. Aparelhos i-STAT Vinculados a {cli_name} ({len(linked)} aparelho(s)) "
        )
        if linked:
            parts = [f"{qtd} {tp.title()}" for tp, qtd in sorted(counts_by_type.items())]
            self.lbl_client_devices_summary.configure(
                text=f"Total neste cliente: {len(linked)} aparelho(s) ({', '.join(parts)}) — Dê duplo-clique em qualquer aparelho para abrir sua ficha."
            )
        else:
            self.lbl_client_devices_summary.configure(
                text="Nenhum aparelho vinculado a este cliente no momento. Clique em '+ Vincular Aparelho do Estoque' para enviar aparelhos."
            )

    def _clear_client_form_for_new(self):
        self.tree_clients.selection_remove(self.tree_clients.selection())
        self._selected_client_original_name = ""
        self._current_client_linked_indices = []
        self.v_cli_nome.set("")
        self.v_cli_cnpj.set("")
        self.v_cli_setores.set("")
        self.v_cli_endereco.set("")
        self.v_cli_cep.set("")
        self.v_cli_cidade.set("PORTO ALEGRE")
        self.v_cli_uf.set("RS")
        self.v_cli_contato.set("")
        self.v_cli_telefone.set("")
        self.v_cli_email.set("")
        self.v_cli_obs.set("")
        self.lf_client_form.configure(text=" 1. Cadastrar Novo Cliente / Hospital ")
        self.lf_client_devices.configure(text=" 2. Aparelhos i-STAT Vinculados (Salve o novo cliente primeiro) ")
        self.tree_client_items.delete(*self.tree_client_items.get_children())
        self.lbl_client_devices_summary.configure(text="Preencha os dados acima e clique em 'Salvar Cadastro do Cliente'.")
        self.ent_cli_nome.focus_set()

    def _save_client_form(self):
        nome = self.v_cli_nome.get().strip()
        if not nome:
            messagebox.showwarning("Nome Obrigatório", "Informe o Nome do Hospital / Clínica / Cliente.")
            self.ent_cli_nome.focus_set()
            return
        try:
            saved = self.db.upsert_client(
                {
                    "CLIENTE": nome,
                    "CNPJ": self.v_cli_cnpj.get().strip(),
                    "SETORES": self.v_cli_setores.get().strip(),
                    "ENDERECO": self.v_cli_endereco.get().strip(),
                    "CEP": self.v_cli_cep.get().strip(),
                    "CIDADE": self.v_cli_cidade.get().strip(),
                    "UF": self.v_cli_uf.get().strip(),
                    "CONTATO_LOCAL": self.v_cli_contato.get().strip(),
                    "TELEFONE": self.v_cli_telefone.get().strip(),
                    "EMAIL": self.v_cli_email.get().strip(),
                    "OBSERVACOES": self.v_cli_obs.get().strip(),
                },
                old_name=self._selected_client_original_name,
            )
            self._selected_client_original_name = saved["CLIENTE"]
            self._populate_data_tree()
            self._refresh_clients_tab(preserve_selection=True, select_client_name=saved["CLIENTE"])
            messagebox.showinfo(
                "Cadastro do Cliente Salvo",
                f"Dados do cliente '{saved['CLIENTE']}' salvos com sucesso!\n"
                f"O endereço e contato foram sincronizados automaticamente em todos os aparelhos vinculados.",
            )
        except Exception as e:
            messagebox.showerror("Erro ao Salvar Cliente", str(e))

    def _delete_selected_client(self):
        cli_name = self._selected_client_original_name or self.v_cli_nome.get().strip()
        if not cli_name:
            messagebox.showinfo("Excluir Cliente", "Selecione um cliente na lista à esquerda.")
            return
        linked = self.db.get_client_items(cli_name)
        msg = f"Deseja excluir o cadastro do cliente '{cli_name}'?"
        if linked:
            msg += f"\n\nAtenção: Os {len(linked)} aparelho(s) atualmente vinculados a ele serão movidos para 'SEM CLIENTE (ESTOQUE LYDA)'."
        if not messagebox.askyesno("Confirmar Exclusão de Cliente", msg):
            return
        ok, info_msg = self.db.delete_client(cli_name)
        if ok:
            self._selected_client_original_name = ""
            self._populate_data_tree()
            self._refresh_clients_tab(preserve_selection=False)
            messagebox.showinfo("Cliente Removido", info_msg)

    def _open_selected_client_device_modal(self):
        sel = self.tree_client_items.selection()
        if not sel:
            messagebox.showinfo("Selecionar Aparelho", "Clique em um aparelho da lista deste cliente (ou dê duplo-clique) para editar.")
            return
        iid = sel[0]
        if iid.isdigit():
            idx = int(iid)
            if 0 <= idx < len(self.db.items):
                it = self.db.items[idx]
                self._open_barcode_movement_modal(scanned_serial=it.get("CODIGO", ""), item_idx=idx)

    def _return_selected_client_device_to_stock(self):
        sel = self.tree_client_items.selection()
        if not sel:
            messagebox.showinfo("Devolver ao Estoque", "Selecione na tabela abaixo o aparelho que voltou para o Estoque da Lyda.")
            return
        iid = sel[0]
        if not iid.isdigit():
            return
        idx = int(iid)
        if not (0 <= idx < len(self.db.items)):
            return
        it = self.db.items[idx]
        cli_antigo = it.get("CLIENTE", "")
        if not messagebox.askyesno(
            "Devolver Aparelho para o Estoque Lyda",
            f"Confirmar retorno do aparelho [{it.get('TIPO')}] SN: {it.get('CODIGO')} (de {cli_antigo}) para o Estoque da Sede Lyda?",
        ):
            return
        it["CLIENTE"] = "SEM CLIENTE (ESTOQUE LYDA)"
        it["ENDERECO"] = self.db.lyda_hq_address
        it["CEP"] = "90240-005"
        it["CIDADE"] = "PORTO ALEGRE"
        it["UF"] = "RS"
        it["SETOR"] = "ESTOQUE SEDE LYDA"
        it["MODALIDADE"] = "PROPRIEDADE LYDA"
        it["STATUS"] = "ESTOQUE USADOS"
        it["_updated_epoch"] = time.time()
        self.db.add_history_log(
            serial_barcode=it.get("CODIGO", ""),
            tipo=it.get("TIPO", "ANALISADOR"),
            acao="RETORNO -> ESTOQUE LYDA",
            detalhes=f"Devolvido de {cli_antigo} para o Estoque Lyda",
            cliente="SEM CLIENTE (ESTOQUE LYDA)",
            modalidade="PROPRIEDADE LYDA",
            condicao=it.get("CONDICAO", "PERFEITO / FUNCIONANDO 100%"),
            responsavel=self.var_operador_atual.get(),
        )
        self.db.save()
        self._populate_data_tree()
        self._refresh_history_tree()

    def _mark_all_client_devices_updated_today(self):
        cli_name = self._selected_client_original_name or self.v_cli_nome.get().strip()
        linked = self.db.get_client_items(cli_name)
        if not linked:
            messagebox.showinfo("Sem Aparelhos", "Este cliente não possui aparelhos vinculados no momento.")
            return
        hoje_str = datetime.now().strftime("%d/%m/%Y")
        default_cyc = getattr(self.db, "default_update_cycle_months", 6)
        if not messagebox.askyesno(
            "Atualizar Aparelhos deste Cliente (6m)",
            f"Deseja marcar todos os {len(linked)} aparelho(s) de '{cli_name}' como atualizados hoje ({hoje_str})?",
        ):
            return
        for _idx, it in linked:
            it["ULTIMA_ATUALIZACAO"] = hoje_str
            c_info = compute_update_cycle_info(it, default_cyc)
            it["PROXIMA_ATUALIZACAO"] = c_info["next_date_str"]
            it["_updated_epoch"] = time.time()
            self.db.add_history_log(
                serial_barcode=it.get("CODIGO", ""),
                tipo=it.get("TIPO", "ANALISADOR"),
                acao="ATUALIZAÇÃO DE 6 MESES (POR CLIENTE)",
                detalhes=f"Atualizado em {hoje_str} no cliente {cli_name} | Próx: {it['PROXIMA_ATUALIZACAO']}",
                cliente=cli_name,
                modalidade=it.get("MODALIDADE", ""),
                condicao=it.get("CONDICAO", "PERFEITO / FUNCIONANDO 100%"),
                responsavel=self.var_operador_atual.get(),
            )
        self.db.save()
        self._populate_data_tree()
        self._refresh_history_tree()
        messagebox.showinfo("Atualizados", f"Todos os {len(linked)} aparelhos de '{cli_name}' foram marcados como atualizados hoje!")

    def _generate_client_romaneio(self):
        cli_name = self._selected_client_original_name or self.v_cli_nome.get().strip()
        linked = [it for _idx, it in self.db.get_client_items(cli_name)]
        if not linked:
            messagebox.showwarning("Sem Aparelhos", "Este cliente ainda não possui aparelhos vinculados para gerar o romaneio.")
            return
        generate_and_open_romaneio(
            workspace_dir=WORKSPACE_DIR,
            acao="RELAÇÃO DE APARELHOS VINCULADOS AO CLIENTE",
            cliente=cli_name,
            cidade=self.v_cli_cidade.get(),
            uf=self.v_cli_uf.get(),
            setor=self.v_cli_setores.get() or "-",
            modalidade=linked[0].get("MODALIDADE", "COMODATO"),
            status="ATIVO NO CLIENTE",
            condicao="PERFEITO / FUNCIONANDO 100%",
            defeito="",
            observacoes=self.v_cli_obs.get(),
            responsavel=self.var_operador_atual.get(),
            items=linked,
        )

    def _open_link_stock_device_to_client_dialog(self):
        cli_name = self.v_cli_nome.get().strip() or self._selected_client_original_name
        if not cli_name:
            messagebox.showwarning("Selecione um Cliente", "Selecione ou salve um cliente antes de vincular aparelhos.")
            return

        dlg = tk.Toplevel(self)
        dlg.title(f"Vincular Aparelhos ao Cliente — {cli_name}")
        dlg.geometry("760x520")
        dlg.configure(bg="#F1F5F9")
        dlg.transient(self)
        dlg.grab_set()

        hdr = tk.Frame(dlg, bg="#0F172A", padx=16, pady=10)
        hdr.pack(fill="x")
        tk.Label(
            hdr,
            text=f"Vincular Aparelho(s) do Estoque para: {cli_name}",
            bg="#0F172A",
            fg="#FFFFFF",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w")

        body = tk.Frame(dlg, bg="#FFFFFF", padx=14, pady=10)
        body.pack(fill="both", expand=True, padx=12, pady=10)

        top_opts = tk.Frame(body, bg="#EFF6FF", padx=10, pady=8)
        top_opts.pack(fill="x", pady=(0, 8))

        tk.Label(top_opts, text="Modalidade:", bg="#EFF6FF", fg="#0F172A", font=("Segoe UI", 9, "bold")).pack(side="left")
        v_link_mod = tk.StringVar(value="COMODATO")
        ttk.Combobox(top_opts, textvariable=v_link_mod, values=["COMODATO", "ALUGUEL", "VENDA"], state="readonly", width=14).pack(
            side="left", padx=(4, 14)
        )

        tk.Label(top_opts, text="Setor de Destino no Hospital:", bg="#EFF6FF", fg="#0F172A", font=("Segoe UI", 9, "bold")).pack(side="left")
        v_link_setor = tk.StringVar(value=self.v_cli_setores.get().split(",")[0].strip() if self.v_cli_setores.get().strip() else "LABORATÓRIO")
        ttk.Entry(top_opts, textvariable=v_link_setor, width=22).pack(side="left", padx=4)

        tk.Label(
            body,
            text="Selecione abaixo um ou mais aparelhos disponíveis no Estoque da Lyda (segure Shift/Cmd para vários):",
            bg="#FFFFFF",
            fg="#0F172A",
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w", pady=(0, 4))

        t_box = tk.Frame(body, bg="#FFFFFF")
        t_box.pack(fill="both", expand=True)

        cols_st = ("TIPO", "CODIGO", "STATUS", "CICLO_6M", "OBSERVACOES")
        tree_st = ttk.Treeview(t_box, columns=cols_st, show="headings", selectmode="extended")
        for c_id, c_title, c_w in [
            ("TIPO", "Equipamento", 115),
            ("CODIGO", "Nº de Série", 110),
            ("STATUS", "Situação no Estoque", 145),
            ("CICLO_6M", "Atualização (6m)", 155),
            ("OBSERVACOES", "Observações", 190),
        ]:
            tree_st.heading(c_id, text=c_title)
            tree_st.column(c_id, width=c_w, anchor="w")

        vsb_s = ttk.Scrollbar(t_box, orient="vertical", command=tree_st.yview)
        tree_st.configure(yscrollcommand=vsb_s.set)
        tree_st.pack(side="left", fill="both", expand=True)
        vsb_s.pack(side="right", fill="y")

        default_cyc = getattr(self.db, "default_update_cycle_months", 6)
        for idx, it in enumerate(self.db.items):
            if classify_item_row_state(it) == "ESTOQUE":
                c_info = compute_update_cycle_info(it, default_cyc)
                tree_st.insert(
                    "",
                    "end",
                    iid=str(idx),
                    values=(
                        it.get("TIPO", ""),
                        it.get("CODIGO", ""),
                        it.get("STATUS", ""),
                        c_info["badge_text"],
                        it.get("OBSERVACOES", ""),
                    ),
                )

        ftr = tk.Frame(body, bg="#FFFFFF")
        ftr.pack(fill="x", pady=(10, 0))

        def _confirm_link():
            sel = tree_st.selection()
            if not sel:
                messagebox.showwarning("Selecione", "Selecione pelo menos um aparelho da lista.", parent=dlg)
                return
            # Garante que o cliente esteja salvo
            self.db.upsert_client(
                {
                    "CLIENTE": cli_name,
                    "CNPJ": self.v_cli_cnpj.get().strip(),
                    "SETORES": self.v_cli_setores.get().strip(),
                    "ENDERECO": self.v_cli_endereco.get().strip(),
                    "CEP": self.v_cli_cep.get().strip(),
                    "CIDADE": self.v_cli_cidade.get().strip(),
                    "UF": self.v_cli_uf.get().strip(),
                    "CONTATO_LOCAL": self.v_cli_contato.get().strip(),
                    "TELEFONE": self.v_cli_telefone.get().strip(),
                    "EMAIL": self.v_cli_email.get().strip(),
                    "OBSERVACOES": self.v_cli_obs.get().strip(),
                },
                old_name=self._selected_client_original_name,
            )
            for iid in sel:
                idx = int(iid)
                it = self.db.items[idx]
                it["CLIENTE"] = cli_name
                it["ENDERECO"] = self.v_cli_endereco.get().strip()
                it["CEP"] = self.v_cli_cep.get().strip()
                it["CIDADE"] = self.v_cli_cidade.get().strip().upper()
                it["UF"] = self.v_cli_uf.get().strip().upper()
                it["CONTATO_LOCAL"] = self.v_cli_contato.get().strip()
                it["MODALIDADE"] = v_link_mod.get()
                it["SETOR"] = v_link_setor.get().strip()
                it["STATUS"] = "ATIVO NO CLIENTE"
                it["ATUALIZADO_NO_ESTOQUE"] = "EM USO NO CLIENTE / N/A"
                it["_updated_epoch"] = time.time()
                self.db.add_history_log(
                    serial_barcode=it.get("CODIGO", ""),
                    tipo=it.get("TIPO", "ANALISADOR"),
                    acao="SAÍDA DA LYDA -> CLIENTE / HOSPITAL",
                    detalhes=f"Vinculado ao cliente {cli_name} (Setor: {it['SETOR']}, Modalidade: {it['MODALIDADE']})",
                    cliente=cli_name,
                    modalidade=it["MODALIDADE"],
                    condicao=it.get("CONDICAO", "PERFEITO / FUNCIONANDO 100%"),
                    responsavel=self.var_operador_atual.get(),
                )
            self.db.save()
            dlg.destroy()
            self._populate_data_tree()
            self._refresh_history_tree()
            self._refresh_clients_tab(preserve_selection=True, select_client_name=cli_name)

        ttk.Button(ftr, text=" Cancelar", style="Secondary.TButton", cursor="hand2", command=dlg.destroy).pack(side="left")
        ttk.Button(
            ftr,
            text=" Confirmar Vínculo com este Cliente",
            image=self.icons.get("check", "#FFFFFF"),
            compound="left",
            style="Success.TButton",
            cursor="hand2",
            command=_confirm_link,
        ).pack(side="right")

    # =========================================================================
    # ABA 2: CENTRAL DE BIPAGEM (LEITOR DE CÓDIGO DE BARRAS USB)
    # =========================================================================
    def _build_tab_scanner(self):
        pad = tk.Frame(self.tab_scanner, bg="#FFFFFF", padx=16, pady=12)
        pad.pack(fill="both", expand=True)

        scan_hero = tk.Frame(pad, bg="#0F172A", padx=16, pady=12)
        scan_hero.pack(fill="x", pady=(0, 12))

        tk.Label(
            scan_hero,
            text=" LEITOR AUTOMÁTICO ATIVO: Bipe o código em QUALQUER tela (sem precisar clicar em nada) para abrir o Modal!",
            image=self.icons.get("barcode", "#38BDF8"),
            compound="left",
            bg="#0F172A",
            fg="#38BDF8",
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w")

        input_row = tk.Frame(scan_hero, bg="#0F172A", pady=6)
        input_row.pack(fill="x")

        self.scan_input_var = tk.StringVar()
        self.ent_scanner = tk.Entry(
            input_row,
            textvariable=self.scan_input_var,
            font=("Consolas", 16, "bold"),
            bg="#FFFFFF",
            fg="#0F172A",
            width=24,
            relief="flat",
        )
        self.ent_scanner.pack(side="left", ipady=5, padx=(0, 10))
        self.ent_scanner.bind("<Return>", self._on_barcode_scanned)
        self.ent_scanner.bind("<KP_Enter>", self._on_barcode_scanned)
        self.ent_scanner.bind("<KeyRelease>", self._on_scanner_entry_keyrelease)

        ttk.Button(
            input_row,
            text=" Abrir Modal de Estoque",
            image=self.icons.get("search", "#FFFFFF"),
            compound="left",
            style="Primary.TButton",
            cursor="hand2",
            command=self._on_barcode_scanned,
        ).pack(side="left", padx=4)

        ttk.Button(
            input_row,
            text=" Imprimir Etiqueta Deste Equipamento",
            image=self.icons.get("printer", "#FFFFFF"),
            compound="left",
            style="Success.TButton",
            cursor="hand2",
            command=self._print_scanned_item_only,
        ).pack(side="right")

        auto_row = tk.Frame(scan_hero, bg="#0F172A")
        auto_row.pack(fill="x", pady=(2, 0))
        tk.Checkbutton(
            auto_row,
            text="Abrir Modal de Estoque automaticamente assim que bipar / digitar o código (sem precisar clicar ou dar Enter)",
            variable=self.var_auto_open_modal,
            bg="#0F172A",
            fg="#E2E8F0",
            selectcolor="#1E293B",
            activebackground="#0F172A",
            activeforeground="#FFFFFF",
            font=("Segoe UI", 8, "bold"),
        ).pack(side="left")

        lf_card = tk.LabelFrame(
            pad,
            text=" Ficha do Equipamento Bipado (Atualize o Cliente / Destino / Status rapidamente ao bipar) ",
            bg="#FFFFFF",
            fg="#0F172A",
            font=("Segoe UI", 9, "bold"),
            padx=14,
            pady=10,
        )
        lf_card.pack(fill="x", pady=(0, 12))

        self.lbl_scan_status = tk.Label(
            lf_card,
            text="Aguardando leitura do código de barras... (Ex: tente digitar 446761, S137045 ou DRC110815 e dar Enter)",
            bg="#F1F5F9",
            fg="#475569",
            font=("Segoe UI", 9, "bold"),
            padx=10,
            pady=6,
            anchor="w",
        )
        self.lbl_scan_status.pack(fill="x", pady=(0, 8))

        form_grid = tk.Frame(lf_card, bg="#FFFFFF")
        form_grid.pack(fill="x")
        for c_i in range(4):
            form_grid.columnconfigure(c_i, weight=1)

        self.scan_tipo_var = tk.StringVar()
        self.scan_bc_var = tk.StringVar()
        self.scan_mod_var = tk.StringVar()
        self.scan_status_var = tk.StringVar()
        self.scan_cliente_var = tk.StringVar()
        self.scan_cidade_var = tk.StringVar()
        self.scan_uf_var = tk.StringVar()
        self.scan_setor_var = tk.StringVar()
        self.scan_obs_var = tk.StringVar()

        tk.Label(form_grid, text="Tipo de Equipamento:", bg="#FFFFFF", fg="#0F172A", font=("Segoe UI", 8, "bold")).grid(row=0, column=0, sticky="w", padx=4)
        ttk.Combobox(form_grid, textvariable=self.scan_tipo_var, values=EQUIPMENT_TYPES, state="readonly").grid(row=1, column=0, sticky="ew", padx=4, pady=(0, 6))

        tk.Label(form_grid, text="Serial / Código de Barras:", bg="#FFFFFF", fg="#0F172A", font=("Segoe UI", 8, "bold")).grid(row=0, column=1, sticky="w", padx=4)
        ttk.Entry(form_grid, textvariable=self.scan_bc_var, font=("Consolas", 10, "bold")).grid(row=1, column=1, sticky="ew", padx=4, pady=(0, 6))

        tk.Label(form_grid, text="Modalidade:", bg="#FFFFFF", fg="#0F172A", font=("Segoe UI", 8, "bold")).grid(row=0, column=2, sticky="w", padx=4)
        ttk.Combobox(form_grid, textvariable=self.scan_mod_var, values=MODALITIES, state="readonly").grid(row=1, column=2, sticky="ew", padx=4, pady=(0, 6))

        tk.Label(form_grid, text="Status Atual:", bg="#FFFFFF", fg="#0F172A", font=("Segoe UI", 8, "bold")).grid(row=0, column=3, sticky="w", padx=4)
        ttk.Combobox(form_grid, textvariable=self.scan_status_var, values=STATUS_OPTIONS).grid(row=1, column=3, sticky="ew", padx=4, pady=(0, 6))

        tk.Label(form_grid, text="Hospital / Cliente / Localização (ou SEM CLIENTE):", bg="#FFFFFF", fg="#0F172A", font=("Segoe UI", 8, "bold")).grid(row=2, column=0, columnspan=2, sticky="w", padx=4)
        ttk.Combobox(form_grid, textvariable=self.scan_cliente_var, values=self.db.get_known_clients()).grid(row=3, column=0, columnspan=2, sticky="ew", padx=4, pady=(0, 6))

        tk.Label(form_grid, text="Cidade / UF:", bg="#FFFFFF", fg="#0F172A", font=("Segoe UI", 8, "bold")).grid(row=2, column=2, sticky="w", padx=4)
        cid_box = tk.Frame(form_grid, bg="#FFFFFF")
        cid_box.grid(row=3, column=2, sticky="ew", padx=4, pady=(0, 6))
        ttk.Entry(cid_box, textvariable=self.scan_cidade_var, width=16).pack(side="left", fill="x", expand=True)
        ttk.Entry(cid_box, textvariable=self.scan_uf_var, width=4).pack(side="left", padx=(4, 0))

        tk.Label(form_grid, text="Setor (ex: UTI, Lab, Bloco):", bg="#FFFFFF", fg="#0F172A", font=("Segoe UI", 8, "bold")).grid(row=2, column=3, sticky="w", padx=4)
        ttk.Entry(form_grid, textvariable=self.scan_setor_var).grid(row=3, column=3, sticky="ew", padx=4, pady=(0, 6))

        tk.Label(form_grid, text="Observações / Histórico:", bg="#FFFFFF", fg="#0F172A", font=("Segoe UI", 8, "bold")).grid(row=4, column=0, columnspan=3, sticky="w", padx=4)
        ttk.Entry(form_grid, textvariable=self.scan_obs_var).grid(row=5, column=0, columnspan=3, sticky="ew", padx=4, pady=(0, 4))

        ttk.Button(
            form_grid,
            text=" Salvar Alteração do Equipamento Bipado",
            image=self.icons.get("save", "#FFFFFF"),
            compound="left",
            style="Success.TButton",
            cursor="hand2",
            command=self._save_scanned_item_changes,
        ).grid(row=5, column=3, sticky="ew", padx=4)

        lf_hist = tk.LabelFrame(
            pad,
            text=" Histórico Geral de Movimentações, Bipagens e Auditoria Multi-PC ",
            bg="#FFFFFF",
            fg="#0F172A",
            font=("Segoe UI", 9, "bold"),
            padx=10,
            pady=8,
        )
        lf_hist.pack(fill="both", expand=True)

        hist_filter_bar = tk.Frame(lf_hist, bg="#F8FAFC", padx=6, pady=4)
        hist_filter_bar.pack(fill="x", pady=(0, 6))
        tk.Label(
            hist_filter_bar,
            text=" Filtrar Histórico (Serial, Cliente, Operador, Ação):",
            image=self.icons.get("search", "#334155"),
            compound="left",
            bg="#F8FAFC",
            fg="#334155",
            font=("Segoe UI", 8, "bold"),
        ).pack(side="left")
        self.hist_search_var = tk.StringVar()
        self.hist_search_var.trace_add("write", lambda *_: self._refresh_history_tree())
        ttk.Entry(hist_filter_bar, textvariable=self.hist_search_var, width=28).pack(side="left", padx=6)

        ttk.Button(
            hist_filter_bar,
            text=" Gerar / Reimprimir Romaneio (A4/PDF) Selecionado",
            image=self.icons.get("copy", "#FFFFFF"),
            compound="left",
            style="Dark.TButton",
            cursor="hand2",
            command=self._reprint_romaneio_from_history,
        ).pack(side="right")

        hist_cols = ("DATA_HORA", "CODIGO_BARRAS", "TIPO", "ACAO", "OPERADOR_PC", "DETALHES")
        self.tree_hist = ttk.Treeview(lf_hist, columns=hist_cols, show="headings", height=7)
        for col_id, title, w in [
            ("DATA_HORA", "Data / Hora", 125),
            ("CODIGO_BARRAS", "Serial / Cód. Barras", 110),
            ("TIPO", "Equipamento", 100),
            ("ACAO", "Movimentação / Ação", 155),
            ("OPERADOR_PC", "Operador (PC)", 130),
            ("DETALHES", "Detalhes / Localização / Observações", 280),
        ]:
            self.tree_hist.heading(col_id, text=title)
            self.tree_hist.column(col_id, width=w, anchor="w")

        h_vsb = ttk.Scrollbar(lf_hist, orient="vertical", command=self.tree_hist.yview)
        self.tree_hist.configure(yscrollcommand=h_vsb.set)
        self.tree_hist.pack(side="left", fill="both", expand=True)
        h_vsb.pack(side="right", fill="y")
        self.tree_hist.bind("<Double-1>", lambda _e: self._reprint_romaneio_from_history())

    # =========================================================================
    # ABA 3: TAMANHO DO PAPEL GRANDE E GRADE DE MINI-ETIQUETAS
    # =========================================================================
    def _build_tab_layout(self):
        pad = tk.Frame(self.tab_layout, bg="#FFFFFF", padx=16, pady=12)
        pad.pack(fill="both", expand=True)

        preset_frame = tk.LabelFrame(
            pad,
            text=" Predefinições Rápidas (Escolha ou digite qualquer medida abaixo) ",
            bg="#FFFFFF",
            fg="#0F172A",
            font=("Segoe UI", 9, "bold"),
            padx=10,
            pady=8,
        )
        preset_frame.pack(fill="x", pady=(0, 12))

        presets = [
            ("Etiqueta 100x150mm  ->  10 Mini (2x5)", 100, 150, 2, 5),
            ("Etiqueta 100x150mm  ->  12 Mini (2x6)", 100, 150, 2, 6),
            ("Etiqueta 100x150mm  ->  18 Mini (3x6)", 100, 150, 3, 6),
            ("Etiqueta 100x100mm  ->  8 Mini (2x4)", 100, 100, 2, 4),
            ("Kit i-STAT 4 Etiquetas (2x2 em 100x60mm)", 100, 60, 2, 2),
        ]
        for idx, (label_txt, bw, bh, c, r) in enumerate(presets):
            ttk.Button(
                preset_frame,
                text=" " + label_txt,
                image=self.icons.get("grid", "#0F172A"),
                compound="left",
                style="Secondary.TButton",
                cursor="hand2",
                command=lambda bw=bw, bh=bh, c=c, r=r: self._apply_preset(bw, bh, c, r),
            ).grid(row=idx // 3, column=idx % 3, padx=4, pady=3, sticky="ew")
        for col_i in range(3):
            preset_frame.columnconfigure(col_i, weight=1)

        mid_grid = tk.Frame(pad, bg="#FFFFFF")
        mid_grid.pack(fill="x", pady=4)
        mid_grid.columnconfigure(0, weight=1)
        mid_grid.columnconfigure(1, weight=1)

        lf_big = tk.LabelFrame(
            mid_grid,
            text=" 1. Papel Grande Instalado na Zebra ZD230 ",
            bg="#FFFFFF",
            fg="#0F172A",
            font=("Segoe UI", 9, "bold"),
            padx=12,
            pady=10,
        )
        lf_big.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        self.var_big_w = tk.DoubleVar(value=self.layout_cfg.big_width_mm)
        self.var_big_h = tk.DoubleVar(value=self.layout_cfg.big_height_mm)
        self.var_margin_l = tk.DoubleVar(value=self.layout_cfg.margin_left_mm)
        self.var_margin_t = tk.DoubleVar(value=self.layout_cfg.margin_top_mm)
        self.var_dpi = tk.IntVar(value=self.layout_cfg.dpi)

        self._add_spin_row(lf_big, 0, "Largura da Etiqueta Grande (mm):", self.var_big_w, 20, 118, 1.0)
        self._add_spin_row(lf_big, 1, "Altura da Etiqueta Grande (mm):", self.var_big_h, 15, 400, 1.0)
        self._add_spin_row(lf_big, 2, "Margem Lateral Esq/Dir (mm):", self.var_margin_l, 0, 30, 0.5)
        self._add_spin_row(lf_big, 3, "Margem Superior/Inferior (mm):", self.var_margin_t, 0, 30, 0.5)

        tk.Label(lf_big, text="Resolução da Zebra (DPI):", bg="#FFFFFF", fg="#334155", font=("Segoe UI", 9)).grid(row=4, column=0, sticky="w", pady=4)
        cmb_dpi = ttk.Combobox(lf_big, textvariable=self.var_dpi, values=[203, 300], state="readonly", width=10)
        cmb_dpi.grid(row=4, column=1, sticky="e", pady=4)
        cmb_dpi.bind("<<ComboboxSelected>>", lambda _e: self._update_preview())

        lf_mini = tk.LabelFrame(
            mid_grid,
            text=" 2. Grade de Mini-Etiquetas (Subdivisão) ",
            bg="#FFFFFF",
            fg="#0F172A",
            font=("Segoe UI", 9, "bold"),
            padx=12,
            pady=10,
        )
        lf_mini.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        self.var_cols = tk.IntVar(value=self.layout_cfg.cols)
        self.var_rows = tk.IntVar(value=self.layout_cfg.rows)
        self.var_gap_h = tk.DoubleVar(value=self.layout_cfg.gap_h_mm)
        self.var_gap_v = tk.DoubleVar(value=self.layout_cfg.gap_v_mm)
        self.var_auto_mini = tk.BooleanVar(value=self.layout_cfg.auto_size_mini)
        self.var_mini_w = tk.DoubleVar(value=self.layout_cfg.mini_width_mm)
        self.var_mini_h = tk.DoubleVar(value=self.layout_cfg.mini_height_mm)

        self._add_spin_row(lf_mini, 0, "Colunas (quantas lado a lado):", self.var_cols, 1, 8, 1)
        self._add_spin_row(lf_mini, 1, "Linhas (quantas de cima a baixo):", self.var_rows, 1, 20, 1)
        self._add_spin_row(lf_mini, 2, "Espaço Horiz. entre Mini-Etiquetas (mm):", self.var_gap_h, 0, 20, 0.5)
        self._add_spin_row(lf_mini, 3, "Espaço Vert. entre Mini-Etiquetas (mm):", self.var_gap_v, 0, 20, 0.5)

        tk.Checkbutton(
            lf_mini,
            text="Calcular tamanho da mini-etiqueta automaticamente",
            variable=self.var_auto_mini,
            bg="#FFFFFF",
            fg="#0F172A",
            font=("Segoe UI", 8, "bold"),
            command=self._on_toggle_auto_mini,
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 2))

        self.spn_mini_w = self._add_spin_row(lf_mini, 5, "Largura Manual da Mini (mm):", self.var_mini_w, 10, 110, 0.5)
        self.spn_mini_h = self._add_spin_row(lf_mini, 6, "Altura Manual da Mini (mm):", self.var_mini_h, 8, 150, 0.5)

        lf_border = tk.LabelFrame(
            pad,
            text=" 3. Contorno para Recorte (Borda de cada Mini-Etiqueta) ",
            bg="#FFFFFF",
            fg="#0F172A",
            font=("Segoe UI", 9, "bold"),
            padx=12,
            pady=10,
        )
        lf_border.pack(fill="x", pady=(12, 0))

        self.var_draw_border = tk.BooleanVar(value=self.layout_cfg.draw_border)
        self.var_border_thick = tk.IntVar(value=self.layout_cfg.border_thickness_dots)
        self.var_corner_round = tk.IntVar(value=self.layout_cfg.border_corner_rounding)
        self.var_cut_marks = tk.BooleanVar(value=self.layout_cfg.draw_cut_marks)
        self.var_inner_pad = tk.DoubleVar(value=self.layout_cfg.inner_padding_mm)

        tk.Checkbutton(
            lf_border,
            text="Desenhar contorno (caixa preta) ao redor de cada mini-etiqueta para recortar",
            variable=self.var_draw_border,
            bg="#FFFFFF",
            fg="#0F172A",
            font=("Segoe UI", 9, "bold"),
            command=self._update_preview,
        ).grid(row=0, column=0, columnspan=2, sticky="w")

        tk.Checkbutton(
            lf_border,
            text="Imprimir marcas guias de corte nas bordas externas",
            variable=self.var_cut_marks,
            bg="#FFFFFF",
            fg="#334155",
            font=("Segoe UI", 9),
            command=self._update_preview,
        ).grid(row=0, column=2, columnspan=2, sticky="w", padx=16)

        self._add_spin_row(lf_border, 1, "Espessura da Borda (dots):", self.var_border_thick, 1, 8, 1, col_offset=0)
        self._add_spin_row(lf_border, 1, "Arredondamento do Canto (0-8):", self.var_corner_round, 0, 8, 1, col_offset=2)
        self._add_spin_row(lf_border, 2, "Recuo Interno Texto/Borda (mm):", self.var_inner_pad, 0.5, 8.0, 0.5, col_offset=0)

        self.lbl_calc_dimensions = tk.Label(
            pad,
            text="",
            bg="#EFF6FF",
            fg="#1E40AF",
            font=("Segoe UI", 9, "bold"),
            pady=8,
            padx=10,
        )
        self.lbl_calc_dimensions.pack(fill="x", pady=(12, 0))
        self._on_toggle_auto_mini()

    def _add_spin_row(self, parent, row: int, label_text: str, var: tk.Variable, from_: float, to: float, inc: float, col_offset: int = 0):
        tk.Label(parent, text=label_text, bg="#FFFFFF", fg="#334155", font=("Segoe UI", 9)).grid(
            row=row, column=col_offset, sticky="w", pady=4, padx=(8 if col_offset else 0, 6)
        )
        spn = ttk.Spinbox(parent, from_=from_, to=to, increment=inc, textvariable=var, width=9, command=self._update_preview)
        spn.grid(row=row, column=col_offset + 1, sticky="e", pady=4)
        spn.bind("<KeyRelease>", lambda _e: self._update_preview())
        spn.bind("<FocusOut>", lambda _e: self._update_preview())
        return spn

    # =========================================================================
    # ABA 4: O QUE ESCREVER NA MINI-ETIQUETA
    # =========================================================================
    def _build_tab_fields(self):
        pad = tk.Frame(self.tab_fields, bg="#FFFFFF", padx=16, pady=12)
        pad.pack(fill="both", expand=True)

        lf_hdr = tk.LabelFrame(
            pad,
            text=" 1. Mini-Logo da LYDA e Cabeçalho no Topo da Mini-Etiqueta ",
            bg="#FFFFFF",
            fg="#0F172A",
            font=("Segoe UI", 9, "bold"),
            padx=12,
            pady=8,
        )
        lf_hdr.pack(fill="x", pady=(0, 10))

        self.var_show_logo = tk.BooleanVar(value=self.layout_cfg.show_logo)
        self.var_logo_h_dots = tk.IntVar(value=self.layout_cfg.logo_height_dots)
        self.var_show_header = tk.BooleanVar(value=self.layout_cfg.show_header)
        self.var_header_text = tk.StringVar(value=self.layout_cfg.header_text)
        self.var_header_fs = tk.IntVar(value=self.layout_cfg.header_font_size)

        row_logo = tk.Frame(lf_hdr, bg="#FFFFFF")
        row_logo.pack(fill="x", pady=(0, 6))

        tk.Checkbutton(
            row_logo,
            text="Imprimir Mini-Logo Gráfica da LYDA no topo (^GFA)",
            variable=self.var_show_logo,
            bg="#FFFFFF",
            fg="#0F172A",
            font=("Segoe UI", 9, "bold"),
            command=self._update_preview,
        ).pack(side="left")

        tk.Label(row_logo, text="Altura da Logo (dots):", bg="#FFFFFF", font=("Segoe UI", 9)).pack(side="left", padx=(16, 4))
        spn_logo_h = ttk.Spinbox(row_logo, from_=14, to=70, increment=2, textvariable=self.var_logo_h_dots, width=6, command=self._update_preview)
        spn_logo_h.pack(side="left")
        spn_logo_h.bind("<KeyRelease>", lambda _e: self._update_preview())

        ttk.Button(
            row_logo,
            text=" Trocar Imagem da Logo...",
            image=self.icons.get("upload", "#0F172A"),
            compound="left",
            style="Secondary.TButton",
            cursor="hand2",
            command=self._on_choose_logo_file,
        ).pack(side="right")

        row_hdr_txt = tk.Frame(lf_hdr, bg="#FFFFFF")
        row_hdr_txt.pack(fill="x")

        tk.Checkbutton(
            row_hdr_txt,
            text="Exibir Texto Adicional no Cabeçalho:",
            variable=self.var_show_header,
            bg="#FFFFFF",
            font=("Segoe UI", 9),
            command=self._update_preview,
        ).pack(side="left")

        ent_hdr = ttk.Entry(row_hdr_txt, textvariable=self.var_header_text, width=22)
        ent_hdr.pack(side="left", padx=8)
        ent_hdr.bind("<KeyRelease>", lambda _e: self._update_preview())

        tk.Label(row_hdr_txt, text="Tam. Fonte (dots):", bg="#FFFFFF", font=("Segoe UI", 9)).pack(side="left", padx=(10, 4))
        spn_hdr_fs = ttk.Spinbox(row_hdr_txt, from_=12, to=45, textvariable=self.var_header_fs, width=6, command=self._update_preview)
        spn_hdr_fs.pack(side="left")
        spn_hdr_fs.bind("<KeyRelease>", lambda _e: self._update_preview())

        lf_bc = tk.LabelFrame(
            pad,
            text=" 2. Código de Barras / QR Code (Serial limpo para bipar no leitor) ",
            bg="#FFFFFF",
            fg="#0F172A",
            font=("Segoe UI", 9, "bold"),
            padx=12,
            pady=10,
        )
        lf_bc.pack(fill="x", pady=(0, 10))

        self.var_bc_enabled = tk.BooleanVar(value=self.layout_cfg.barcode_enabled)
        self.var_bc_type = tk.StringVar(value=self.layout_cfg.barcode_type)
        self.var_bc_col = tk.StringVar(value=self.layout_cfg.barcode_column)
        self.var_bc_height = tk.DoubleVar(value=self.layout_cfg.barcode_height_mm)
        self.var_bc_mod_w = tk.IntVar(value=self.layout_cfg.barcode_module_width)
        self.var_bc_show_txt = tk.BooleanVar(value=self.layout_cfg.show_barcode_text)

        row_bc1 = tk.Frame(lf_bc, bg="#FFFFFF")
        row_bc1.pack(fill="x", pady=2)

        tk.Checkbutton(
            row_bc1,
            text="Imprimir Código de Barras",
            variable=self.var_bc_enabled,
            bg="#FFFFFF",
            font=("Segoe UI", 9, "bold"),
            command=self._update_preview,
        ).pack(side="left")

        tk.Label(row_bc1, text="Coluna do Código:", bg="#FFFFFF", font=("Segoe UI", 9, "bold")).pack(side="left", padx=(16, 4))
        self.cmb_bc_col = ttk.Combobox(row_bc1, textvariable=self.var_bc_col, state="readonly", width=20)
        self.cmb_bc_col.pack(side="left")
        self.cmb_bc_col.bind("<<ComboboxSelected>>", lambda _e: self._update_preview())

        tk.Label(row_bc1, text="Tipo:", bg="#FFFFFF", font=("Segoe UI", 9)).pack(side="left", padx=(16, 4))
        cmb_bctype = ttk.Combobox(row_bc1, textvariable=self.var_bc_type, values=["CODE128", "QRCODE"], state="readonly", width=11)
        cmb_bctype.pack(side="left")
        cmb_bctype.bind("<<ComboboxSelected>>", lambda _e: self._update_preview())

        row_bc2 = tk.Frame(lf_bc, bg="#FFFFFF")
        row_bc2.pack(fill="x", pady=(8, 2))

        tk.Label(row_bc2, text="Altura das Barras (mm):", bg="#FFFFFF", font=("Segoe UI", 9)).pack(side="left")
        spn_bch = ttk.Spinbox(row_bc2, from_=4.0, to=35.0, increment=0.5, textvariable=self.var_bc_height, width=7, command=self._update_preview)
        spn_bch.pack(side="left", padx=6)
        spn_bch.bind("<KeyRelease>", lambda _e: self._update_preview())

        tk.Label(row_bc2, text="Largura da Barra (1=Fino, 2=Padrão, 3=Largo):", bg="#FFFFFF", font=("Segoe UI", 9)).pack(side="left", padx=(14, 4))
        spn_bcm = ttk.Spinbox(row_bc2, from_=1, to=4, increment=1, textvariable=self.var_bc_mod_w, width=5, command=self._update_preview)
        spn_bcm.pack(side="left", padx=4)
        spn_bcm.bind("<KeyRelease>", lambda _e: self._update_preview())

        tk.Checkbutton(
            row_bc2,
            text="Exibir número de série abaixo das barras",
            variable=self.var_bc_show_txt,
            bg="#FFFFFF",
            font=("Segoe UI", 9),
            command=self._update_preview,
        ).pack(side="left", padx=14)

        lf_extra = tk.LabelFrame(
            pad,
            text=" 3. Campos de Texto na Mini-Etiqueta (Escolha: TIPO, CODIGO, CLIENTE, SETOR, MODALIDADE ou Texto Livre) ",
            bg="#FFFFFF",
            fg="#0F172A",
            font=("Segoe UI", 9, "bold"),
            padx=12,
            pady=10,
        )
        lf_extra.pack(fill="both", expand=True)

        loc_toggle_bar = tk.Frame(lf_extra, bg="#EFF6FF", padx=8, pady=5)
        loc_toggle_bar.pack(fill="x", pady=(0, 6))
        tk.Checkbutton(
            loc_toggle_bar,
            text="Mostrar Local / Cliente na Etiqueta (desmarcado = oculta o hospital/cliente e deixa o código de barras maior para bipar mais fácil)",
            variable=self.var_show_location_on_label,
            bg="#EFF6FF",
            fg="#1E40AF",
            font=("Segoe UI", 8, "bold"),
            command=self._on_toggle_location_on_label,
        ).pack(side="left")

        hdr_row = tk.Frame(lf_extra, bg="#F8FAFC", pady=4)
        hdr_row.pack(fill="x")
        tk.Label(hdr_row, text="Linha", width=6, bg="#F8FAFC", font=("Segoe UI", 8, "bold"), anchor="w").pack(side="left", padx=4)
        tk.Label(hdr_row, text="Prefixo (ex: 'SN: ')", width=18, bg="#F8FAFC", font=("Segoe UI", 8, "bold"), anchor="w").pack(side="left", padx=4)
        tk.Label(hdr_row, text="Puxar de qual Campo?", width=24, bg="#F8FAFC", font=("Segoe UI", 8, "bold"), anchor="w").pack(side="left", padx=4)
        tk.Label(hdr_row, text="Ou Texto Fixo Livre", width=18, bg="#F8FAFC", font=("Segoe UI", 8, "bold"), anchor="w").pack(side="left", padx=4)
        tk.Label(hdr_row, text="Tam. Fonte", width=10, bg="#F8FAFC", font=("Segoe UI", 8, "bold"), anchor="w").pack(side="left", padx=4)
        tk.Label(hdr_row, text="Negrito", width=8, bg="#F8FAFC", font=("Segoe UI", 8, "bold"), anchor="w").pack(side="left", padx=4)

        self.extra_rows_widgets = []
        rows_container = tk.Frame(lf_extra, bg="#FFFFFF")
        rows_container.pack(fill="both", expand=True, pady=4)

        existing_extras = self.layout_cfg.extra_fields
        for i in range(5):
            ef = existing_extras[i] if i < len(existing_extras) else ExtraFieldConfig(prefix="", column_name="", font_size=15, bold=False)
            rf = tk.Frame(rows_container, bg="#FFFFFF", pady=3)
            rf.pack(fill="x")

            tk.Label(rf, text=f"#{i+1}", width=5, bg="#FFFFFF", fg="#475569", font=("Segoe UI", 9, "bold"), anchor="w").pack(side="left", padx=4)

            v_pref = tk.StringVar(value=ef.prefix)
            ent_pref = ttk.Entry(rf, textvariable=v_pref, width=18)
            ent_pref.pack(side="left", padx=4)
            ent_pref.bind("<KeyRelease>", lambda _e: self._update_preview())

            v_col = tk.StringVar(value=ef.column_name)
            cmb_col = ttk.Combobox(rf, textvariable=v_col, state="readonly", width=23)
            cmb_col.pack(side="left", padx=4)

            v_fix = tk.StringVar(value=ef.fixed_value)
            ent_fix = ttk.Entry(rf, textvariable=v_fix, width=18)
            ent_fix.pack(side="left", padx=4)
            ent_fix.bind("<KeyRelease>", lambda _e: self._update_preview())

            v_fs = tk.IntVar(value=ef.font_size)
            spn_fs = ttk.Spinbox(rf, from_=12, to=42, textvariable=v_fs, width=7, command=self._update_preview)
            spn_fs.pack(side="left", padx=6)
            spn_fs.bind("<KeyRelease>", lambda _e: self._update_preview())

            v_bold = tk.BooleanVar(value=ef.bold)
            chk_b = tk.Checkbutton(rf, variable=v_bold, bg="#FFFFFF", command=self._update_preview)
            chk_b.pack(side="left", padx=10)

            cmb_col.bind("<<ComboboxSelected>>", lambda _e: self._update_preview())

            self.extra_rows_widgets.append(
                {
                    "prefix": v_pref,
                    "column": v_col,
                    "cmb": cmb_col,
                    "fixed": v_fix,
                    "font_size": v_fs,
                    "bold": v_bold,
                }
            )

    # =========================================================================
    # ABA 3.1: SISTEMA — SEDE LYDA, SHAREPOINT, OPERADORES E IMPRESSORA ZEBRA
    # =========================================================================
    def _build_tab_zpl(self):
        pad = tk.Frame(self.tab_zpl, bg="#FFFFFF", padx=14, pady=10)
        pad.pack(fill="both", expand=True)

        # ---------------------------------------------------------------------
        # CARD 1: ENDEREÇO DA SEDE LYDA, CICLO 6 MESES & SHAREPOINT MULTI-PC
        # ---------------------------------------------------------------------
        lf_sp = tk.LabelFrame(
            pad,
            text=" 1. Endereço da Sede da LYDA, Ciclo de Atualização (6 em 6 Meses) & Pasta Local do SharePoint ",
            bg="#FFFFFF",
            fg="#0F172A",
            font=("Segoe UI", 9, "bold"),
            padx=12,
            pady=8,
        )
        lf_sp.pack(fill="x", pady=(0, 8))

        # Linha 1: Endereço da Sede da LYDA + Ciclo de Atualização (6 em 6 meses)
        sede_cfg_row = tk.Frame(lf_sp, bg="#F8FAFC", padx=8, pady=6, highlightthickness=1, highlightbackground="#CBD5E1")
        sede_cfg_row.pack(fill="x", pady=(0, 6))

        tk.Label(
            sede_cfg_row,
            text="Endereço da Sede da LYDA (Estoque & Partida da Rota):",
            bg="#F8FAFC",
            fg="#0F172A",
            font=("Segoe UI", 8, "bold"),
        ).pack(side="left")

        self.var_sede_cfg = tk.StringVar(value=self.db.lyda_hq_address)
        ent_sede_cfg = ttk.Entry(sede_cfg_row, textvariable=self.var_sede_cfg, font=("Segoe UI", 9, "bold"))
        ent_sede_cfg.pack(side="left", fill="x", expand=True, padx=8)

        tk.Label(
            sede_cfg_row,
            text="Ciclo de Atualização (Meses):",
            bg="#F8FAFC",
            fg="#1E3A8A",
            font=("Segoe UI", 8, "bold"),
        ).pack(side="left", padx=(4, 4))

        self.var_ciclo_padrao_cfg = tk.IntVar(value=getattr(self.db, "default_update_cycle_months", 6))
        ttk.Spinbox(sede_cfg_row, from_=1, to=24, textvariable=self.var_ciclo_padrao_cfg, width=4).pack(side="left", padx=(0, 8))

        ttk.Button(
            sede_cfg_row,
            text=" Salvar Sede & Ciclo",
            image=self.icons.get("save", "#FFFFFF"),
            compound="left",
            style="Success.TButton",
            cursor="hand2",
            command=self._save_sede_and_cycle_inline,
        ).pack(side="left")

        tk.Label(
            lf_sp,
            text=(
                "Como sincronizar pelo SharePoint da Lyda: sincronize a biblioteca do SharePoint no PC (via OneDrive/SharePoint)\n"
                "e selecione abaixo a pasta local sincronizada. Todos os PCs apontados para essa pasta atualizam o estoque juntos!"
            ),
            bg="#EFF6FF",
            fg="#1E40AF",
            font=("Segoe UI", 8, "bold"),
            justify="left",
            anchor="w",
            padx=8,
            pady=5,
        ).pack(fill="x", pady=(0, 6))

        sp_row = tk.Frame(lf_sp, bg="#FFFFFF")
        sp_row.pack(fill="x", pady=2)

        tk.Label(sp_row, text="Pasta Local / SharePoint Ativa:", bg="#FFFFFF", fg="#0F172A", font=("Segoe UI", 9, "bold")).pack(side="left")
        self.var_shared_folder_cfg = tk.StringVar(value=self.db.shared_db_dir)
        ent_sp = ttk.Entry(sp_row, textvariable=self.var_shared_folder_cfg, font=("Consolas", 9, "bold"))
        ent_sp.pack(side="left", fill="x", expand=True, padx=8)

        ttk.Button(
            sp_row,
            text=" Escolher Pasta do SharePoint / Local...",
            image=self.icons.get("upload", "#FFFFFF"),
            compound="left",
            style="Primary.TButton",
            cursor="hand2",
            command=self._on_browse_sharepoint_folder_inline,
        ).pack(side="left", padx=(0, 4))

        ttk.Button(
            sp_row,
            text=" Aplicar Pasta",
            image=self.icons.get("check", "#FFFFFF"),
            compound="left",
            style="Success.TButton",
            cursor="hand2",
            command=lambda: self._apply_sharepoint_folder_inline(self.var_shared_folder_cfg.get().strip()),
        ).pack(side="left")

        # Atalhos automáticos se detectar SharePoint / OneDrive no PC + Botões de Excel e Backup
        sp_actions_row = tk.Frame(lf_sp, bg="#FFFFFF")
        sp_actions_row.pack(fill="x", pady=(6, 0))

        cloud_cands = self._detect_cloud_or_network_candidates()
        if cloud_cands:
            lbl_cand, path_cand = cloud_cands[0]
            ttk.Button(
                sp_actions_row,
                text=f" Usar {lbl_cand} Detectado",
                image=self.icons.get("refresh", "#0F172A"),
                compound="left",
                style="Secondary.TButton",
                cursor="hand2",
                command=lambda p=path_cand: self._apply_sharepoint_folder_inline(p),
            ).pack(side="left", padx=(0, 6))

        ttk.Button(
            sp_actions_row,
            text=" Importar Planilha (.xlsx)",
            image=self.icons.get("upload", "#FFFFFF"),
            compound="left",
            style="Dark.TButton",
            cursor="hand2",
            command=self._on_import_excel,
        ).pack(side="left", padx=3)

        ttk.Button(
            sp_actions_row,
            text=" Exportar Base (.xlsx)",
            image=self.icons.get("download", "#FFFFFF"),
            compound="left",
            style="Success.TButton",
            cursor="hand2",
            command=self._on_export_excel,
        ).pack(side="left", padx=3)

        ttk.Button(
            sp_actions_row,
            text=" Backups Automáticos",
            image=self.icons.get("save", "#0F172A"),
            compound="left",
            style="Secondary.TButton",
            cursor="hand2",
            command=self._on_open_backup_manager,
        ).pack(side="left", padx=3)

        # ---------------------------------------------------------------------
        # CARD 2: CADASTRO DE OPERADORES DA LYDA
        # ---------------------------------------------------------------------
        lf_ops = tk.LabelFrame(
            pad,
            text=" 2. Operadores Cadastrados (Aparecem na lista de seleção do topo e no modal de bipagem) ",
            bg="#FFFFFF",
            fg="#0F172A",
            font=("Segoe UI", 9, "bold"),
            padx=12,
            pady=8,
        )
        lf_ops.pack(fill="x", pady=(0, 8))

        ops_row = tk.Frame(lf_ops, bg="#FFFFFF")
        ops_row.pack(fill="x")

        tk.Label(ops_row, text="Novo Operador:", bg="#FFFFFF", fg="#0F172A", font=("Segoe UI", 9, "bold")).pack(side="left")
        self.var_new_operator = tk.StringVar()
        ent_new_op = ttk.Entry(ops_row, textvariable=self.var_new_operator, width=20, font=("Segoe UI", 9, "bold"))
        ent_new_op.pack(side="left", padx=6)
        ent_new_op.bind("<Return>", lambda _e: self._on_add_operator_click())

        ttk.Button(
            ops_row,
            text=" + Adicionar Operador",
            image=self.icons.get("plus", "#FFFFFF"),
            compound="left",
            style="Primary.TButton",
            cursor="hand2",
            command=self._on_add_operator_click,
        ).pack(side="left", padx=(0, 14))

        tk.Label(ops_row, text="Operadores Atuais:", bg="#FFFFFF", fg="#334155", font=("Segoe UI", 9, "bold")).pack(side="left")
        self.var_remove_operator = tk.StringVar(value=self.db.operators[0] if self.db.operators else "")
        self.cmb_manage_operators = ttk.Combobox(
            ops_row,
            textvariable=self.var_remove_operator,
            values=self.db.operators,
            state="readonly",
            width=18,
            font=("Segoe UI", 9, "bold"),
        )
        self.cmb_manage_operators.pack(side="left", padx=6)

        ttk.Button(
            ops_row,
            text=" Remover Selecionado",
            image=self.icons.get("trash", "#991B1B"),
            compound="left",
            style="Danger.TButton",
            cursor="hand2",
            command=self._on_remove_operator_click,
        ).pack(side="left")

        self.lbl_operators_list = tk.Label(
            lf_ops,
            text="",
            bg="#F8FAFC",
            fg="#334155",
            font=("Segoe UI", 8, "bold"),
            anchor="w",
            padx=8,
            pady=4,
        )
        self.lbl_operators_list.pack(fill="x", pady=(6, 0))
        self._refresh_operators_ui()

        # ---------------------------------------------------------------------
        # CARD 3: SELEÇÃO DA IMPRESSORA ZEBRA ZD230
        # ---------------------------------------------------------------------
        lf_conn = tk.LabelFrame(
            pad,
            text=" 3. Seleção da Impressora Zebra ZD230 & Ajustes de Impressão ",
            bg="#FFFFFF",
            fg="#0F172A",
            font=("Segoe UI", 9, "bold"),
            padx=12,
            pady=8,
        )
        lf_conn.pack(fill="x", pady=(0, 8))

        self.var_conn_mode = tk.StringVar(value="USB_DRIVER")
        row_m = tk.Frame(lf_conn, bg="#FFFFFF")
        row_m.pack(fill="x", pady=2)

        tk.Radiobutton(
            row_m,
            text="Impressora USB / Instalada no Sistema (WinSpool RAW / CUPS RAW)",
            variable=self.var_conn_mode,
            value="USB_DRIVER",
            bg="#FFFFFF",
            font=("Segoe UI", 9, "bold"),
        ).pack(side="left")

        tk.Radiobutton(
            row_m,
            text="Impressora Zebra em Rede (IP / Porta 9100)",
            variable=self.var_conn_mode,
            value="NETWORK_IP",
            bg="#FFFFFF",
            font=("Segoe UI", 9, "bold"),
        ).pack(side="left", padx=18)

        row_usb = tk.Frame(lf_conn, bg="#FFFFFF")
        row_usb.pack(fill="x", pady=4)

        tk.Label(row_usb, text="Impressora do Sistema:", bg="#FFFFFF", font=("Segoe UI", 9, "bold")).pack(side="left")
        self.var_printer_name = tk.StringVar()
        self.cmb_printers = ttk.Combobox(row_usb, textvariable=self.var_printer_name, width=34)
        self.cmb_printers.pack(side="left", padx=8)

        ttk.Button(
            row_usb,
            text=" Atualizar Lista",
            image=self.icons.get("refresh", "#0F172A"),
            compound="left",
            style="Secondary.TButton",
            cursor="hand2",
            command=self._refresh_printers_list,
        ).pack(side="left")

        ttk.Button(
            row_usb,
            text=" Salvar Padrão",
            image=self.icons.get("save", "#FFFFFF"),
            compound="left",
            style="Success.TButton",
            cursor="hand2",
            command=lambda: self._save_config_to_disk(silent=False),
        ).pack(side="right")

        row_net_dark = tk.Frame(lf_conn, bg="#FFFFFF")
        row_net_dark.pack(fill="x", pady=4)
        tk.Label(row_net_dark, text="IP Rede:", bg="#FFFFFF", font=("Segoe UI", 9)).pack(side="left")
        self.var_ip = tk.StringVar(value="192.168.1.200")
        ttk.Entry(row_net_dark, textvariable=self.var_ip, width=14).pack(side="left", padx=(4, 10))
        tk.Label(row_net_dark, text="Porta:", bg="#FFFFFF", font=("Segoe UI", 9)).pack(side="left")
        self.var_port = tk.IntVar(value=9100)
        ttk.Entry(row_net_dark, textvariable=self.var_port, width=6).pack(side="left", padx=(4, 14))

        self.var_darkness = tk.IntVar(value=self.layout_cfg.darkness)
        self.var_speed = tk.IntVar(value=self.layout_cfg.print_speed)

        tk.Label(row_net_dark, text="Escuridão (0-30):", bg="#FFFFFF", font=("Segoe UI", 9)).pack(side="left")
        ttk.Spinbox(row_net_dark, from_=5, to=30, textvariable=self.var_darkness, width=5, command=self._update_preview).pack(side="left", padx=(4, 12))

        tk.Label(row_net_dark, text="Velocidade (2-6):", bg="#FFFFFF", font=("Segoe UI", 9)).pack(side="left")
        ttk.Spinbox(row_net_dark, from_=2, to=6, textvariable=self.var_speed, width=4, command=self._update_preview).pack(side="left", padx=4)

        # ---------------------------------------------------------------------
        # CARD 4: CÓDIGO ZPL II GERADO EM TEMPO REAL (COMPACTO)
        # ---------------------------------------------------------------------
        lf_code = tk.LabelFrame(
            pad,
            text=" 4. Código ZPL II Nativo Gerado (Pronto para Zebra ZD230) ",
            bg="#FFFFFF",
            fg="#0F172A",
            font=("Segoe UI", 9, "bold"),
            padx=10,
            pady=6,
        )
        lf_code.pack(fill="both", expand=True)

        btn_zpl_bar = tk.Frame(lf_code, bg="#FFFFFF")
        btn_zpl_bar.pack(fill="x", pady=(0, 4))

        ttk.Button(
            btn_zpl_bar,
            text=" Copiar ZPL",
            image=self.icons.get("copy", "#0F172A"),
            compound="left",
            style="Secondary.TButton",
            cursor="hand2",
            command=self._copy_zpl_to_clipboard,
        ).pack(side="left")

        ttk.Button(
            btn_zpl_bar,
            text=" Salvar Arquivo .PRN / .ZPL",
            image=self.icons.get("save", "#0F172A"),
            compound="left",
            style="Secondary.TButton",
            cursor="hand2",
            command=self._save_zpl_file,
        ).pack(side="left", padx=8)

        self.txt_zpl = tk.Text(lf_code, font=("Consolas", 8), height=5, bg="#0F172A", fg="#38BDF8", insertbackground="#FFFFFF", wrap="none")
        zpl_vsb = ttk.Scrollbar(lf_code, orient="vertical", command=self.txt_zpl.yview)
        self.txt_zpl.configure(yscrollcommand=zpl_vsb.set)
        self.txt_zpl.pack(side="left", fill="both", expand=True)
        zpl_vsb.pack(side="right", fill="y")

        self._refresh_printers_list()

    def _save_sede_and_cycle_inline(self):
        addr = self.var_sede_cfg.get().strip() if hasattr(self, "var_sede_cfg") else ""
        try:
            cyc = int(self.var_ciclo_padrao_cfg.get())
        except Exception:
            cyc = 6
        if addr:
            self.db.lyda_hq_address = addr
        self.db.default_update_cycle_months = max(1, min(24, cyc))
        self.db.save_local_pc_config()
        self.db._enrich_missing_hospital_addresses()
        self._populate_data_tree()
        self._update_sync_status_banner()
        messagebox.showinfo(
            "Sede da LYDA & Ciclo Salvos",
            f"Endereço da Sede da LYDA atualizado para:\n{self.db.lyda_hq_address}\n\n"
            f"Ciclo padrão de atualização definido para: de {self.db.default_update_cycle_months} em {self.db.default_update_cycle_months} meses.",
        )

    def _on_browse_sharepoint_folder_inline(self):
        chosen = filedialog.askdirectory(
            title="Selecionar Pasta Local do SharePoint da Lyda (ou Pasta de Rede)",
            initialdir=self.db.shared_db_dir,
        )
        if chosen:
            self._apply_sharepoint_folder_inline(chosen)

    def _apply_sharepoint_folder_inline(self, target_dir: str):
        if not target_dir:
            return
        ok, msg = self.db.set_shared_folder(target_dir)
        if ok:
            if hasattr(self, "var_shared_folder_cfg"):
                self.var_shared_folder_cfg.set(self.db.shared_db_dir)
            self._populate_data_tree()
            self._refresh_history_tree()
            self._refresh_operators_ui()
            self._update_sync_status_banner()
            messagebox.showinfo("Pasta do SharePoint / Base Configurada", msg)
        else:
            messagebox.showerror("Erro ao Configurar Pasta", msg)

    def _refresh_operators_ui(self):
        ops = self.db.operators
        if hasattr(self, "cmb_operador_top"):
            self.cmb_operador_top["values"] = ops
            if self.var_operador_atual.get() not in ops and ops:
                self.var_operador_atual.set(ops[0])
        if hasattr(self, "cmb_manage_operators"):
            self.cmb_manage_operators["values"] = ops
            if self.var_remove_operator.get() not in ops and ops:
                self.var_remove_operator.set(ops[0])
        if hasattr(self, "lbl_operators_list"):
            self.lbl_operators_list.configure(
                text="Operadores disponíveis para seleção rápida:   " + "   •   ".join(ops)
            )

    def _on_add_operator_click(self):
        new_op = self.var_new_operator.get().strip().upper()
        if not new_op:
            messagebox.showwarning("Operador", "Digite o nome do operador para adicionar.")
            return
        self.db.add_operator(new_op)
        self.var_new_operator.set("")
        self.var_operador_atual.set(new_op)
        self.var_remove_operator.set(new_op)
        self._refresh_operators_ui()

    def _on_remove_operator_click(self):
        target_op = self.var_remove_operator.get().strip()
        if not target_op:
            return
        if len(self.db.operators) <= 1:
            messagebox.showwarning("Operadores", "Mantenha pelo menos 1 operador cadastrado.")
            return
        self.db.remove_operator(target_op)
        self._refresh_operators_ui()

    # =========================================================================
    # PAINEL DIREITO: PREVIEW EM ESCALA DA ETIQUETA GRANDE + IMPRESSÃO ZPL
    # =========================================================================
    def _build_right_preview_panel(self, container):
        pad = tk.Frame(container, bg="#FFFFFF", padx=14, pady=12)
        pad.pack(fill="both", expand=True)

        hdr = tk.Frame(pad, bg="#FFFFFF")
        hdr.pack(fill="x")
        tk.Label(
            hdr,
            text=" Pré-Visualização da Etiqueta Grande",
            image=self.icons.get("grid", "#0F172A"),
            compound="left",
            bg="#FFFFFF",
            fg="#0F172A",
            font=("Segoe UI", 10, "bold"),
        ).pack(side="left")

        nav = tk.Frame(hdr, bg="#FFFFFF")
        nav.pack(side="right")
        ttk.Button(
            nav,
            image=self.icons.get("prev", "#0F172A"),
            style="Secondary.TButton",
            cursor="hand2",
            command=self._prev_preview_page,
        ).pack(side="left")
        self.lbl_page_indicator = tk.Label(nav, text="Etiqueta 1 / 1", bg="#FFFFFF", fg="#334155", font=("Segoe UI", 9, "bold"), padx=8)
        self.lbl_page_indicator.pack(side="left")
        ttk.Button(
            nav,
            image=self.icons.get("next", "#0F172A"),
            style="Secondary.TButton",
            cursor="hand2",
            command=self._next_preview_page,
        ).pack(side="left")
        ttk.Button(
            nav,
            text=" Esconder",
            style="Secondary.TButton",
            cursor="hand2",
            command=self._toggle_preview_panel,
        ).pack(side="left", padx=(8, 0))

        self.lbl_preview_subtitle = tk.Label(pad, text="", bg="#FFFFFF", fg="#64748B", font=("Segoe UI", 8), anchor="w")
        self.lbl_preview_subtitle.pack(fill="x", pady=(2, 4))

        quick_opt_bar = tk.Frame(pad, bg="#EFF6FF", padx=8, pady=4, highlightbackground="#BFDBFE", highlightthickness=1)
        quick_opt_bar.pack(fill="x", pady=(0, 6))
        tk.Checkbutton(
            quick_opt_bar,
            text="Mostrar Local/Cliente",
            variable=self.var_show_location_on_label,
            bg="#EFF6FF",
            fg="#1E3A8A",
            font=("Segoe UI", 8, "bold"),
            command=self._on_toggle_location_on_label,
        ).pack(side="left")

        skip_box = tk.Frame(quick_opt_bar, bg="#EFF6FF")
        skip_box.pack(side="right")
        tk.Label(
            skip_box,
            text="Pular posições já usadas (1ª folha):",
            bg="#EFF6FF",
            fg="#1E3A8A",
            font=("Segoe UI", 8, "bold"),
        ).pack(side="left", padx=(4, 4))
        spn_skip = ttk.Spinbox(
            skip_box,
            from_=0,
            to=24,
            increment=1,
            textvariable=self.var_skip_slots,
            width=4,
            command=self._update_preview,
        )
        spn_skip.pack(side="left")
        spn_skip.bind("<KeyRelease>", lambda _e: self._update_preview())
        spn_skip.bind("<FocusOut>", lambda _e: self._update_preview())

        self.canvas_preview = tk.Canvas(pad, bg="#CBD5E1", highlightthickness=1, highlightbackground="#94A3B8")
        self.canvas_preview.pack(fill="both", expand=True)
        self.canvas_preview.bind("<Configure>", lambda _e: self._draw_canvas_preview())

        bottom_bar = tk.Frame(pad, bg="#FFFFFF", pady=10)
        bottom_bar.pack(fill="x", side="bottom")

        top_action_row = tk.Frame(bottom_bar, bg="#FFFFFF")
        top_action_row.pack(fill="x", pady=(0, 6))

        ttk.Button(
            top_action_row,
            text=" Imprimir 1 Folha de Teste",
            image=self.icons.get("printer", "#FFFFFF"),
            compound="left",
            style="Amber.TButton",
            cursor="hand2",
            command=lambda: self._execute_print(only_current_page=True),
        ).pack(side="left", fill="x", expand=True, padx=(0, 4))

        ttk.Button(
            top_action_row,
            text=" Baixar Arquivo .PRN",
            image=self.icons.get("download", "#FFFFFF"),
            compound="left",
            style="Primary.TButton",
            cursor="hand2",
            command=self._save_zpl_file,
        ).pack(side="left", fill="x", expand=True, padx=(4, 0))

        self.btn_print_all = ttk.Button(
            bottom_bar,
            text=" IMPRIMIR SELECIONADOS NA ZEBRA ZD230 (ZPL)",
            image=self.icons.get("printer", "#FFFFFF"),
            compound="left",
            style="PrintGreen.TButton",
            cursor="hand2",
            command=lambda: self._execute_print(only_current_page=False),
        )
        self.btn_print_all.pack(fill="x")

    # =========================================================================
    # FUNÇÕES DE GESTÃO i-STAT, FILTROS, BIPAGEM E CADASTRO
    # =========================================================================
    def _update_counter_cards(self):
        total = len(self.db.items)
        if "TODOS" in self.lbl_counter_cards:
            self.lbl_counter_cards["TODOS"].configure(text=str(total))
        for t in EQUIPMENT_TYPES:
            cnt = sum(1 for x in self.db.items if x.get("TIPO") == t)
            if t in self.lbl_counter_cards:
                self.lbl_counter_cards[t].configure(text=str(cnt))
        if "ATIVOS_CLIENTES" in self.lbl_counter_cards:
            cnt_atv = sum(1 for x in self.db.items if classify_item_row_state(x) == "ATIVO")
            self.lbl_counter_cards["ATIVOS_CLIENTES"].configure(text=str(cnt_atv))
        if "ESTOQUE_LYDA" in self.lbl_counter_cards:
            cnt_est = sum(1 for x in self.db.items if classify_item_row_state(x) == "ESTOQUE")
            self.lbl_counter_cards["ESTOQUE_LYDA"].configure(text=str(cnt_est))
        if "ATT_PENDENTE_6M" in self.lbl_counter_cards:
            cnt_pend = sum(
                1
                for x in self.db.items
                if compute_update_cycle_info(x, getattr(self.db, "default_update_cycle_months", 6))["status_code"]
                in ("VENCIDA", "VENCENDO", "SEM_DATA")
            )
            self.lbl_counter_cards["ATT_PENDENTE_6M"].configure(text=str(cnt_pend))
        if "ATT_EM_DIA_6M" in self.lbl_counter_cards:
            cnt_ok = sum(
                1
                for x in self.db.items
                if compute_update_cycle_info(x, getattr(self.db, "default_update_cycle_months", 6))["status_code"] == "EM_DIA"
            )
            self.lbl_counter_cards["ATT_EM_DIA_6M"].configure(text=str(cnt_ok))
        if "ESTOQUE_FALTA_ATT" in self.lbl_counter_cards:
            cnt_est_falta = sum(
                1
                for x in self.db.items
                if classify_item_row_state(x) == "ESTOQUE"
                and (
                    "NÃO" in (x.get("ATUALIZADO_NO_ESTOQUE") or "").upper()
                    or "PENDENTE" in (x.get("ATUALIZADO_NO_ESTOQUE") or "").upper()
                    or compute_update_cycle_info(x, getattr(self.db, "default_update_cycle_months", 6))["status_code"] != "EM_DIA"
                )
            )
            self.lbl_counter_cards["ESTOQUE_FALTA_ATT"].configure(text=str(cnt_est_falta))
        if "DEFEITO_MANUT" in self.lbl_counter_cards:
            cnt_def = sum(1 for x in self.db.items if classify_item_row_state(x) == "DEFEITO")
            self.lbl_counter_cards["DEFEITO_MANUT"].configure(text=str(cnt_def))
        if "COMODATO" in self.lbl_counter_cards:
            cnt_com = sum(
                1 for x in self.db.items if (x.get("MODALIDADE") or "").upper() in ("COMODATO", "ALUGUEL")
            )
            self.lbl_counter_cards["COMODATO"].configure(text=str(cnt_com))
        if "VENDA" in self.lbl_counter_cards:
            cnt_vnd = sum(1 for x in self.db.items if (x.get("MODALIDADE") or "").upper() == "VENDA")
            self.lbl_counter_cards["VENDA"].configure(text=str(cnt_vnd))

    def _quick_filter_by_type(self, tipo_key: str):
        if hasattr(self, "filter_mod_var"):
            self.filter_mod_var.set("TODAS")
        if tipo_key == "ESTOQUE_LYDA":
            self.filter_type_var.set("TODOS")
            self.filter_status_var.set("DISPONÍVEIS NO ESTOQUE LYDA (SEM CLIENTE)")
        elif tipo_key == "ATIVOS_CLIENTES":
            self.filter_type_var.set("TODOS")
            self.filter_status_var.set("ATIVOS EM CLIENTES / HOSPITAIS")
        elif tipo_key == "COMODATO":
            self.filter_type_var.set("TODOS")
            self.filter_status_var.set("TODOS")
            if hasattr(self, "filter_mod_var"):
                self.filter_mod_var.set("COMODATO")
        elif tipo_key == "VENDA":
            self.filter_type_var.set("TODOS")
            self.filter_status_var.set("TODOS")
            if hasattr(self, "filter_mod_var"):
                self.filter_mod_var.set("VENDA")
        elif tipo_key == "ATT_PENDENTE_6M":
            self.filter_type_var.set("TODOS")
            self.filter_status_var.set("ATUALIZAÇÃO 6 MESES VENCIDA OU PENDENTE")
        elif tipo_key == "ATT_EM_DIA_6M":
            self.filter_type_var.set("TODOS")
            self.filter_status_var.set("ATUALIZAÇÃO 6 MESES EM DIA")
        elif tipo_key == "ESTOQUE_FALTA_ATT":
            self.filter_type_var.set("TODOS")
            self.filter_status_var.set("ESTOQUE LYDA: FALTA ATUALIZAR NA BANCADA")
        elif tipo_key == "DEFEITO_MANUT":
            self.filter_type_var.set("TODOS")
            self.filter_status_var.set("COM DEFEITO / EM MANUTENÇÃO")
        elif tipo_key == "TODOS":
            self.filter_type_var.set("TODOS")
            if hasattr(self, "filter_status_var"):
                self.filter_status_var.set("TODOS")
            if hasattr(self, "filter_mod_var"):
                self.filter_mod_var.set("TODAS")
        else:
            self.filter_type_var.set(tipo_key)
        self._populate_data_tree()

    def _populate_data_tree(self):
        self._update_counter_cards()
        self.tree.delete(*self.tree.get_children())
        # Remove índices que já não existem
        self.checked_indices = {i for i in self.checked_indices if 0 <= i < len(self.db.items)}

        table_cols = [
            "SEL",
            "TIPO",
            "CODIGO",
            "CLIENTE",
            "CIDADE_UF",
            "SETOR",
            "MODALIDADE",
            "CICLO_6M",
            "SITUACAO_RESUMO",
        ]
        self.tree["columns"] = table_cols

        col_widths = {
            "SEL": 64,
            "TIPO": 110,
            "CODIGO": 105,
            "CLIENTE": 255,
            "CIDADE_UF": 140,
            "SETOR": 125,
            "MODALIDADE": 115,
            "CICLO_6M": 170,
            "SITUACAO_RESUMO": 230,
        }
        col_titles = {
            "SEL": "Marcar",
            "TIPO": "Equipamento",
            "CODIGO": "Serial (SN)",
            "CLIENTE": "Hospital / Local Atual",
            "CIDADE_UF": "Cidade / UF",
            "SETOR": "Setor",
            "MODALIDADE": "Modalidade",
            "CICLO_6M": "Atualização (6m)",
            "SITUACAO_RESUMO": "Status / Bancada",
        }
        for c in table_cols:
            self.tree.heading(c, text=col_titles.get(c, c))
            self.tree.column(c, width=col_widths.get(c, 110), anchor="center" if c == "SEL" else "w")

        f_type = self.filter_type_var.get() if hasattr(self, "filter_type_var") else "TODOS"
        f_mod = self.filter_mod_var.get() if hasattr(self, "filter_mod_var") else "TODAS"
        f_st = self.filter_status_var.get() if hasattr(self, "filter_status_var") else "TODOS"
        query = self.search_var.get().strip().lower() if hasattr(self, "search_var") else ""
        default_cyc = getattr(self.db, "default_update_cycle_months", 6)

        def _sort_prio(idx_and_row):
            idx_val, r = idx_and_row
            st = classify_item_row_state(r)
            if st == "ESTOQUE":
                st_u = (r.get("STATUS") or "").upper()
                cli_u = (r.get("CLIENTE") or "").upper()
                set_u = (r.get("SETOR") or "").upper()
                if "NOVO" in st_u or "NOVO" in cli_u or "NOVO" in set_u:
                    return (1, idx_val)
                if "BACKUP" in st_u or "BACK UP" in st_u or "BACKUP" in cli_u or "DEVOLVIDO" in st_u:
                    return (3, idx_val)
                return (2, idx_val)
            if st == "ATIVO":
                mod_u = (r.get("MODALIDADE") or "").upper()
                return (4 if mod_u in ("COMODATO", "ALUGUEL") else 5, idx_val)
            return (6, idx_val)

        for idx, row in sorted(enumerate(self.db.items), key=_sort_prio):
            if f_type != "TODOS" and row.get("TIPO") != f_type:
                continue
            if f_mod != "TODAS":
                row_mod = (row.get("MODALIDADE") or "").upper()
                if f_mod == "COMODATO":
                    if row_mod not in ("COMODATO", "ALUGUEL"):
                        continue
                elif row_mod != f_mod.upper():
                    continue
            row_state = classify_item_row_state(row)
            cyc_info = compute_update_cycle_info(row, default_cyc)
            att_est_str = (row.get("ATUALIZADO_NO_ESTOQUE") or "").upper()

            if f_st != "TODOS":
                if f_st == "DISPONÍVEIS NO ESTOQUE LYDA (SEM CLIENTE)":
                    if row_state != "ESTOQUE":
                        continue
                elif f_st == "ATIVOS EM CLIENTES / HOSPITAIS":
                    if row_state != "ATIVO":
                        continue
                elif f_st == "ATUALIZAÇÃO 6 MESES VENCIDA OU PENDENTE":
                    if cyc_info["status_code"] not in ("VENCIDA", "VENCENDO", "SEM_DATA"):
                        continue
                elif f_st == "ATUALIZAÇÃO 6 MESES EM DIA":
                    if cyc_info["status_code"] != "EM_DIA":
                        continue
                elif f_st == "ESTOQUE LYDA: JÁ ATUALIZADOS NA BANCADA":
                    if row_state != "ESTOQUE" or ("SIM" not in att_est_str and cyc_info["status_code"] != "EM_DIA"):
                        continue
                elif f_st == "ESTOQUE LYDA: FALTA ATUALIZAR NA BANCADA":
                    if row_state != "ESTOQUE" or ("SIM" in att_est_str and cyc_info["status_code"] == "EM_DIA"):
                        continue
                elif f_st == "COM DEFEITO / EM MANUTENÇÃO":
                    if row_state != "DEFEITO":
                        continue
                elif row.get("STATUS", "").upper() != f_st.upper():
                    continue

            if query:
                joined = " ".join(str(v).lower() for v in row.values()) + " " + cyc_info["badge_text"].lower()
                if query not in joined:
                    continue

            is_chk = idx in self.checked_indices
            sel_mark = "[ ✓ ]" if is_chk else "[    ]"
            cid = (row.get("CIDADE") or "").strip()
            uf = (row.get("UF") or "").strip()
            cidade_uf = f"{cid} / {uf}".strip(" /") or "-"

            cli_display = row.get("CLIENTE", "")
            if row_state == "ESTOQUE":
                st_u = (row.get("STATUS") or "").upper()
                cli_u = (row.get("CLIENTE") or "").upper()
                set_u = (row.get("SETOR") or "").upper()
                if "NOVO" in st_u or "NOVO" in cli_u or "NOVO" in set_u:
                    cli_display = "ESTOQUE DA LYDA — NOVOS"
                    sit_resumo = "No Estoque LYDA (Novo)"
                elif "BACKUP" in st_u or "BACK UP" in st_u or "BACKUP" in cli_u:
                    cli_display = f"ESTOQUE LYDA — BACKUP ({row.get('CLIENTE', '')})"
                    sit_resumo = "Em Backup"
                elif "DEVOLVIDO" in st_u:
                    cli_display = f"DEVOLVIDO AO ESTOQUE (Ex: {row.get('CLIENTE', '')})"
                    sit_resumo = "Devolvido"
                else:
                    cli_display = "ESTOQUE DA LYDA — USADOS"
                    sit_resumo = "No Estoque LYDA (Usado)"
            elif row_state == "DEFEITO":
                sit_resumo = row.get("DEFEITO") or row.get("STATUS") or "Em Manutenção / Defeito"
            else:
                sit_resumo = row.get("STATUS") or "Ativo no Cliente"

            vals = [
                sel_mark,
                row.get("TIPO", ""),
                row.get("CODIGO", ""),
                cli_display,
                cidade_uf,
                row.get("SETOR", ""),
                row.get("MODALIDADE", ""),
                cyc_info["badge_text"],
                sit_resumo,
            ]

            if is_chk:
                tag = "ROW_CHECKED"
            elif row_state == "DEFEITO":
                tag = "ROW_DEFEITO"
            elif row_state == "ESTOQUE":
                tag = "ROW_ESTOQUE"
            elif cyc_info["status_code"] == "VENCIDA":
                tag = "ROW_ATT_VENCIDA"
            else:
                tag = row.get("TIPO", "ANALISADOR")
            self.tree.insert("", "end", iid=str(idx), values=vals, tags=(tag,))

        self._sync_selection_ui()
        if hasattr(self, "tree_clients"):
            self._refresh_clients_tab(preserve_selection=True)

    def _get_target_indices(self) -> List[int]:
        """Retorna os índices marcados com [✓] ou, se nenhum estiver marcado, as linhas selecionadas na tabela."""
        if self.checked_indices:
            return sorted(i for i in self.checked_indices if 0 <= i < len(self.db.items))
        sel = self.tree.selection()
        return [int(iid) for iid in sel if iid.isdigit() and 0 <= int(iid) < len(self.db.items)]

    def _sync_selection_ui(self):
        targets = self._get_target_indices()
        self.selected_indices = targets if targets else list(range(len(self.db.items)))
        n_chk = len(self.checked_indices)
        if hasattr(self, "lbl_multi_sel_badge"):
            if n_chk > 0:
                self.lbl_multi_sel_badge.configure(
                    text=f"{n_chk} aparelho(s) marcado(s) [ ✓ ]",
                    bg="#DBEAFE",
                    fg="#1D4ED8",
                )
            else:
                self.lbl_multi_sel_badge.configure(
                    text="Clique em [    ] para selecionar vários",
                    bg="#F1F5F9",
                    fg="#475569",
                )
        if hasattr(self, "btn_main_edit"):
            if n_chk > 1:
                self.btn_main_edit.configure(text=f" Editar / Movimentar ({n_chk})")
            else:
                self.btn_main_edit.configure(text=" Editar / Movimentar")
        self.current_preview_page = 0
        self._update_preview()

    def _refresh_row_check_visual(self, idx: int):
        iid = str(idx)
        if not self.tree.exists(iid) or not (0 <= idx < len(self.db.items)):
            return
        row = self.db.items[idx]
        is_chk = idx in self.checked_indices
        vals = list(self.tree.item(iid, "values"))
        if vals:
            vals[0] = "[ ✓ ]" if is_chk else "[    ]"
            self.tree.item(iid, values=vals)
        row_state = classify_item_row_state(row)
        cyc_info = compute_update_cycle_info(row, getattr(self.db, "default_update_cycle_months", 6))
        if is_chk:
            tag = "ROW_CHECKED"
        elif row_state == "DEFEITO":
            tag = "ROW_DEFEITO"
        elif row_state == "ESTOQUE":
            tag = "ROW_ESTOQUE"
        elif cyc_info["status_code"] == "VENCIDA":
            tag = "ROW_ATT_VENCIDA"
        else:
            tag = row.get("TIPO", "ANALISADOR")
        self.tree.item(iid, tags=(tag,))

    def _on_tree_click_check(self, event):
        """Se o usuário clicar na 1ª coluna ('Marcar'), marca/desmarca o aparelho sem perder os outros marcados."""
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        col = self.tree.identify_column(event.x)
        iid = self.tree.identify_row(event.y)
        if col == "#1" and iid and iid.isdigit():
            idx = int(iid)
            if idx in self.checked_indices:
                self.checked_indices.remove(idx)
            else:
                self.checked_indices.add(idx)
            self._refresh_row_check_visual(idx)
            self._sync_selection_ui()
            return "break"

    def _on_tree_space_toggle(self, _event=None):
        """Barra de espaço marca/desmarca as linhas destacadas."""
        for iid in self.tree.selection():
            if iid.isdigit():
                idx = int(iid)
                if idx in self.checked_indices:
                    self.checked_indices.remove(idx)
                else:
                    self.checked_indices.add(idx)
                self._refresh_row_check_visual(idx)
        self._sync_selection_ui()

    def _on_tree_double_click(self, event):
        col = self.tree.identify_column(event.x)
        if col == "#1":
            return
        iid = self.tree.identify_row(event.y)
        if iid and iid.isdigit():
            idx = int(iid)
            if idx not in self.checked_indices and len(self.checked_indices) <= 1:
                self.tree.selection_set(iid)
            self._open_movement_for_selected()

    def _select_all_rows(self):
        for iid in self.tree.get_children():
            if iid.isdigit():
                idx = int(iid)
                self.checked_indices.add(idx)
                self._refresh_row_check_visual(idx)
        self._sync_selection_ui()

    def _deselect_all_rows(self):
        old_checked = list(self.checked_indices)
        self.checked_indices.clear()
        for idx in old_checked:
            self._refresh_row_check_visual(idx)
        self.tree.selection_remove(self.tree.get_children())
        self._sync_selection_ui()

    def _on_tree_selection_changed(self, _event=None):
        self._sync_selection_ui()

    def _batch_mark_updated_today(self):
        """Marca 1 ou vários aparelhos selecionados como atualizados hoje (calculando +6 meses automaticamente)."""
        targets = self._get_target_indices()
        if not targets:
            messagebox.showinfo(
                "Selecionar Aparelhos",
                "Clique na coluna [    ] (ou selecione uma linha) para marcar os aparelhos que foram atualizados hoje.",
            )
            return
        hoje_str = datetime.now().strftime("%d/%m/%Y")
        default_cyc = getattr(self.db, "default_update_cycle_months", 6)
        if not messagebox.askyesno(
            "Confirmar Atualização de 6 Meses",
            f"Deseja registrar que {len(targets)} aparelho(s) selecionado(s) foram atualizados hoje ({hoje_str})?\n\n"
            f"• Próxima atualização será calculada para +{default_cyc} meses;\n"
            f"• Aparelhos no Estoque Lyda serão marcados como 'Já Atualizados na Bancada'.",
        ):
            return
        op = self.var_operador_atual.get() or "OPERADOR LYDA"
        for idx in targets:
            it = self.db.items[idx]
            it["ULTIMA_ATUALIZACAO"] = hoje_str
            c_info = compute_update_cycle_info(it, default_cyc)
            it["PROXIMA_ATUALIZACAO"] = c_info["next_date_str"]
            if classify_item_row_state(it) == "ESTOQUE":
                it["ATUALIZADO_NO_ESTOQUE"] = "SIM - JÁ ATUALIZADO NO ESTOQUE (PRONTO P/ SAÍDA)"
            it["_updated_epoch"] = time.time()
            self.db.add_history_log(
                serial_barcode=it.get("CODIGO", ""),
                tipo=it.get("TIPO", "ANALISADOR"),
                acao="ATUALIZAÇÃO DE 6 MESES (EM LOTE)",
                detalhes=f"Atualizado em {hoje_str} | Próxima: {it['PROXIMA_ATUALIZACAO']}",
                cliente=it.get("CLIENTE", ""),
                modalidade=it.get("MODALIDADE", ""),
                condicao=it.get("CONDICAO", "PERFEITO / FUNCIONANDO 100%"),
                responsavel=op,
            )
        self.db.save()
        self._populate_data_tree()
        self._refresh_history_tree()
        messagebox.showinfo("Atualização Concluída", f"{len(targets)} aparelho(s) atualizados com sucesso para o ciclo de 6 meses!")

    def _on_toggle_location_on_label(self):
        """Liga ou desliga a exibição do CLIENTE/Local na mini-etiqueta e ajusta a altura do código de barras."""
        show_loc = bool(self.var_show_location_on_label.get())
        if not hasattr(self, "extra_rows_widgets") or len(self.extra_rows_widgets) < 3:
            return
        if show_loc:
            # Verifica se algum campo já tem CLIENTE; se não, coloca na linha #3
            if not any(w["column"].get() == "CLIENTE" for w in self.extra_rows_widgets):
                w3 = self.extra_rows_widgets[2]
                w3["prefix"].set("")
                w3["column"].set("CLIENTE")
                w3["font_size"].set(14)
                w3["bold"].set(False)
            if float(self.var_bc_height.get()) > 8.5:
                self.var_bc_height.set(8.0)
        else:
            # Remove CLIENTE das linhas extras e aumenta a altura das barras para leitura fácil
            for w in self.extra_rows_widgets:
                if w["column"].get() in ("CLIENTE", "CIDADE", "SETOR"):
                    w["prefix"].set("")
                    w["column"].set("")
                    w["fixed"].set("")
            if float(self.var_bc_height.get()) < 10.0:
                self.var_bc_height.set(10.5)
        self._update_preview()

    # =========================================================================
    # LEITOR DE CÓDIGO DE BARRAS AUTOMÁTICO (SEM PRECISAR CLICAR EM NADA)
    # =========================================================================
    def _setup_global_scanner_listener(self):
        """
        Escuta o leitor USB de código de barras em qualquer tela do sistema.
        Se o usuário bipar um aparelho sem clicar em nenhum campo (ou mesmo na Aba 1),
        captura os caracteres enviados pelo leitor e abre o Modal de Estoque automaticamente.
        """
        self.bind_all("<KeyPress>", self._on_global_keypress, add="+")

    def _is_text_input_focused(self, widget) -> bool:
        if widget is None:
            return False
        if widget is self.ent_scanner:
            return False
        w_class = widget.winfo_class()
        return w_class in ("Entry", "TEntry", "TSpinbox", "Spinbox", "Text", "TCombobox")

    def _on_global_keypress(self, event):
        if self._active_modal_open:
            return
        try:
            if event.widget and event.widget.winfo_toplevel() is not self:
                return
        except Exception:
            pass

        # Se o foco já está no campo da Aba 2 (ent_scanner), o próprio bind do ent_scanner cuida disso
        if event.widget is self.ent_scanner:
            return

        now = time.monotonic()
        dt = now - self._global_last_key_ts
        self._global_last_key_ts = now

        in_other_input = self._is_text_input_focused(event.widget)

        if event.keysym in ("Return", "KP_Enter"):
            if self._global_scan_buffer and len(self._global_scan_buffer) >= 3:
                if not in_other_input or self._global_scan_fast_count >= 2:
                    code_to_run = self._global_scan_buffer
                    self._global_scan_buffer = ""
                    self._global_scan_fast_count = 0
                    if self._global_scan_after_id:
                        self.after_cancel(self._global_scan_after_id)
                        self._global_scan_after_id = None
                    self._trigger_auto_scan(code_to_run)
                    return
            self._global_scan_buffer = ""
            self._global_scan_fast_count = 0
            return

        ch = event.char or ""
        if len(ch) == 1 and ch.isprintable() and ch not in ("\r", "\n", "\t"):
            # Se estiver fora de qualquer caixa de texto, aceita intervalo de até 350ms;
            # se estiver dentro de outro campo, só captura se for rajada rápida de leitor USB (< 65ms)
            max_gap = 0.065 if in_other_input else 0.35
            if dt <= max_gap:
                self._global_scan_buffer += ch
                self._global_scan_fast_count += 1
            else:
                self._global_scan_buffer = ch
                self._global_scan_fast_count = 0

            if self._global_scan_after_id:
                self.after_cancel(self._global_scan_after_id)

            # Caso o leitor USB não envie Enter no final, dispara sozinho após 260ms de pausa
            if not in_other_input or self._global_scan_fast_count >= 3:
                self._global_scan_after_id = self.after(260, self._flush_global_scan_buffer)

    def _flush_global_scan_buffer(self):
        self._global_scan_after_id = None
        if self._active_modal_open:
            self._global_scan_buffer = ""
            return
        buf = self._global_scan_buffer.strip()
        fast_cnt = self._global_scan_fast_count
        self._global_scan_buffer = ""
        self._global_scan_fast_count = 0
        if len(buf) >= 4 and (fast_cnt >= 2 or bool(self.db.find_by_barcode(buf))):
            self._trigger_auto_scan(buf)

    def _on_scanner_entry_keyrelease(self, event):
        """
        Quando o usuário bipa ou digita no campo da Aba 2:
        Mesmo sem apertar Enter nem clicar em buscar, se o código bater com um equipamento
        ou vier de uma leitura rápida do scanner, abre o modal sozinho após 280ms!
        """
        if self._active_modal_open or not self.var_auto_open_modal.get():
            return
        if event.keysym in (
            "Return",
            "KP_Enter",
            "Escape",
            "Tab",
            "Shift_L",
            "Shift_R",
            "Control_L",
            "Control_R",
            "Alt_L",
            "Alt_R",
            "Left",
            "Right",
            "Up",
            "Down",
        ):
            return

        now = time.monotonic()
        dt = now - self._entry_last_key_ts
        self._entry_last_key_ts = now
        if dt < 0.085:
            self._entry_fast_count += 1
        else:
            self._entry_fast_count = 0

        if self._entry_scan_after_id:
            self.after_cancel(self._entry_scan_after_id)

        code = self.scan_input_var.get().strip()
        if len(code) >= 4:
            self._entry_scan_after_id = self.after(280, self._auto_check_scanner_entry)

    def _auto_check_scanner_entry(self):
        self._entry_scan_after_id = None
        if self._active_modal_open or not self.var_auto_open_modal.get():
            return
        code = self.scan_input_var.get().strip()
        if not code or len(code) < 4:
            return
        clean_c = clean_barcode_serial(code)
        # Se for um serial exato da base OU se veio de rajada rápida do leitor USB (>= 3 teclas rápidas)
        exact_match = any(x.get("CODIGO", "").upper() == clean_c.upper() for x in self.db.items)
        if exact_match or self._entry_fast_count >= 3:
            self._entry_fast_count = 0
            self._on_barcode_scanned()

    def _trigger_auto_scan(self, scanned_code: str):
        if self._active_modal_open:
            return
        clean_c = clean_barcode_serial(scanned_code)
        if not clean_c:
            return
        self.scan_input_var.set(clean_c)
        self._on_barcode_scanned()

    def _on_barcode_scanned(self, _event=None):
        code = self.scan_input_var.get().strip()
        if not code:
            return
        clean_c = clean_barcode_serial(code)
        matches = self.db.find_by_barcode(code)

        if not matches:
            self.currently_scanned_index = None
            default_tipo = "SIMULADOR" if clean_c.startswith("S") else ("DOWNLOADER" if clean_c.startswith("DRC") else "ANALISADOR")
            self.lbl_scan_status.configure(
                text=f"[NOVO APARELHO] Serial '{clean_c}' não estava na base. Abrindo modal de Controle de Estoque...",
                bg="#FEF3C7",
                fg="#92400E",
            )
            self.scan_tipo_var.set(default_tipo)
            self.scan_bc_var.set(clean_c)
            self.scan_mod_var.set("PROPRIEDADE LYDA")
            self.scan_status_var.set("ESTOQUE LYDA NOVOS")
            self.scan_cliente_var.set("SEM CLIENTE (ESTOQUE LYDA)")
            self.scan_cidade_var.set("PORTO ALEGRE")
            self.scan_uf_var.set("RS")
            self.scan_setor_var.set("ESTOQUE LYDA")
            self.scan_obs_var.set("")
            self.ent_scanner.selection_range(0, "end")
            # Abre imediatamente o Modal de Movimentação / Controle de Estoque para este novo aparelho
            self._open_barcode_movement_modal(scanned_serial=clean_c, item_idx=None)
            return

        item = matches[0]
        real_idx = next((i for i, x in enumerate(self.db.items) if x is item), None)
        self.currently_scanned_index = real_idx

        self.lbl_scan_status.configure(
            text=f"[LOCALIZADO] [{item.get('TIPO')}] Serial: {item.get('CODIGO')}   |   Local: {item.get('CLIENTE')} ({item.get('MODALIDADE')})",
            bg="#DCFCE7",
            fg="#166534",
        )
        self.scan_tipo_var.set(item.get("TIPO", "ANALISADOR"))
        self.scan_bc_var.set(item.get("CODIGO", ""))
        self.scan_mod_var.set(item.get("MODALIDADE", "VENDA"))
        self.scan_status_var.set(item.get("STATUS", "ATIVO NO CLIENTE"))
        self.scan_cliente_var.set(item.get("CLIENTE", ""))
        self.scan_cidade_var.set(item.get("CIDADE", ""))
        self.scan_uf_var.set(item.get("UF", ""))
        self.scan_setor_var.set(item.get("SETOR", ""))
        self.scan_obs_var.set(item.get("OBSERVACOES", ""))

        if real_idx is not None:
            self.selected_indices = [real_idx]
            self.current_preview_page = 0
            self._update_preview()

        self.ent_scanner.selection_range(0, "end")
        # Abre automaticamente o Modal de Controle de Estoque / Movimentação / Histórico do Aparelho!
        self._open_barcode_movement_modal(scanned_serial=item.get("CODIGO", clean_c), item_idx=real_idx)

    def _open_movement_for_selected(self):
        targets = self._get_target_indices()
        if not targets:
            messagebox.showinfo(
                "Selecionar Aparelho(s)",
                "Clique em uma linha da tabela (ou marque vários na coluna [ ✓ ]) para editar ou movimentar.",
            )
            return
        first_idx = targets[0]
        if 0 <= first_idx < len(self.db.items):
            item = self.db.items[first_idx]
            self.currently_scanned_index = first_idx
            self._open_barcode_movement_modal(
                scanned_serial=item.get("CODIGO", ""),
                item_idx=first_idx,
                extra_batch_indices=targets[1:] if len(targets) > 1 else None,
            )

    def _open_scan_movement_modal(self, scanned_serial: str, item_idx: Optional[int]):
        self._open_barcode_movement_modal(scanned_serial=scanned_serial, item_idx=item_idx)

    def _open_barcode_movement_modal(
        self,
        scanned_serial: str,
        item_idx: Optional[int],
        extra_batch_indices: Optional[List[int]] = None,
    ):
        """
        Editor Simplificado, Claro e Completo do Aparelho i-STAT:
        - Todos os rótulos em preto forte (#0F172A) para leitura perfeita em macOS e Windows
        - Aba 1: Tudo o que importa organizado em 3 Passos Numerados:
            Passo 1: Onde está o Aparelho & Endereço Completo
            Passo 2: Atualização de 6 em 6 Meses
            Passo 3: Observações / Anotações (Caixa Grande Multi-linha + Botões Rápidos) & Condição
        - Aba 2: Histórico Completo de Movimentações deste Aparelho & Operação em Lote
        """
        is_existing = item_idx is not None and 0 <= item_idx < len(self.db.items)
        existing = self.db.items[item_idx] if is_existing else {}
        serial_init = scanned_serial or existing.get("CODIGO", "")

        self._active_modal_open = True
        dlg = tk.Toplevel(self)
        dlg.title(
            f"Controle de Estoque i-STAT — SN: {serial_init}"
            if serial_init
            else "Novo Aparelho i-STAT"
        )
        dlg.geometry("980x760")
        dlg.minsize(920, 700)
        dlg.configure(bg="#F1F5F9")
        dlg.transient(self)
        dlg.grab_set()
        dlg.lift()

        def _on_modal_close(evt=None):
            if evt is None or evt.widget is dlg:
                self._active_modal_open = False

        dlg.bind("<Destroy>", _on_modal_close)

        # =====================================================================
        # CABEÇALHO LIMPO E DIRETO
        # =====================================================================
        hdr = tk.Frame(dlg, bg="#0F172A", padx=18, pady=10)
        hdr.pack(fill="x")

        hdr_left = tk.Frame(hdr, bg="#0F172A")
        hdr_left.pack(side="left", fill="x", expand=True)

        lbl_hdr_title = tk.Label(
            hdr_left,
            text=f"Aparelho i-STAT — Nº de Série: {serial_init or 'NOVO'}",
            bg="#0F172A",
            fg="#FFFFFF",
            font=("Segoe UI", 13, "bold"),
        )
        lbl_hdr_title.pack(anchor="w")

        lbl_hdr_sub = tk.Label(
            hdr_left,
            text="",
            bg="#0F172A",
            fg="#CBD5E1",
            font=("Segoe UI", 9, "bold"),
        )
        lbl_hdr_sub.pack(anchor="w", pady=(2, 0))

        lbl_hdr_cycle_badge = tk.Label(
            hdr,
            text="",
            bg="#1E293B",
            fg="#FFFFFF",
            font=("Segoe UI", 9, "bold"),
            padx=12,
            pady=6,
            relief="solid",
            bd=1,
        )
        lbl_hdr_cycle_badge.pack(side="right", padx=(10, 0))

        body = tk.Frame(dlg, bg="#F1F5F9", padx=14, pady=8)
        body.pack(fill="both", expand=True)

        # =====================================================================
        # VARIÁVEIS DO EDITOR
        # =====================================================================
        default_tipo = existing.get(
            "TIPO",
            "SIMULADOR" if serial_init.startswith("S") else ("DOWNLOADER" if serial_init.startswith("DRC") else "ANALISADOR"),
        )
        default_cyc = getattr(self.db, "default_update_cycle_months", 6)
        try:
            init_cyc = int(existing.get("CICLO_ATUALIZACAO_MESES") or default_cyc)
        except Exception:
            init_cyc = default_cyc

        v_acao = tk.StringVar(value="CADASTRO / ENTRADA NO ESTOQUE" if not is_existing else "ATUALIZAÇÃO DE FICHA / ESTOQUE")
        v_tipo = tk.StringVar(value=default_tipo)
        v_serial = tk.StringVar(value=serial_init)
        v_mod = tk.StringVar(value=existing.get("MODALIDADE", "PROPRIEDADE LYDA" if not is_existing else "COMODATO"))
        v_status = tk.StringVar(value=existing.get("STATUS", "ESTOQUE LYDA NOVOS" if not is_existing else "ATIVO NO CLIENTE"))
        v_nf = tk.StringVar(value=existing.get("NOTA_FISCAL", ""))
        v_kit_ana = tk.StringVar(value=existing.get("KIT_ANALISADOR", ""))
        v_resp = tk.StringVar(value=self.var_operador_atual.get())

        v_ult_att = tk.StringVar(value=existing.get("ULTIMA_ATUALIZACAO", ""))
        v_ciclo_meses = tk.IntVar(value=init_cyc)
        v_versao_clew = tk.StringVar(value=existing.get("VERSAO_CLEW", "CLEW / JAMS Semestral"))

        att_estoque_options = [
            "SIM - JÁ ATUALIZADO NO ESTOQUE (PRONTO P/ SAÍDA)",
            "NÃO - PENDENTE ATUALIZAR NA BANCADA LYDA",
            "EM USO NO CLIENTE / N/A",
        ]
        init_att_est = existing.get("ATUALIZADO_NO_ESTOQUE", "")
        if not init_att_est:
            init_att_est = (
                "NÃO - PENDENTE ATUALIZAR NA BANCADA LYDA"
                if classify_item_row_state(existing) == "ESTOQUE"
                else "EM USO NO CLIENTE / N/A"
            )
        v_att_estoque = tk.StringVar(value=init_att_est)

        v_cliente = tk.StringVar(value=existing.get("CLIENTE", "SEM CLIENTE (ESTOQUE LYDA)"))
        v_endereco = tk.StringVar(value=existing.get("ENDERECO", ""))
        v_cep = tk.StringVar(value=existing.get("CEP", ""))
        v_contato = tk.StringVar(value=existing.get("CONTATO_LOCAL", ""))
        v_cidade = tk.StringVar(value=existing.get("CIDADE", "PORTO ALEGRE"))
        v_uf = tk.StringVar(value=existing.get("UF", "RS"))
        v_setor = tk.StringVar(value=existing.get("SETOR", "ESTOQUE LYDA" if not is_existing else "LABORATÓRIO"))
        v_propagate_addr = tk.BooleanVar(value=True)

        v_condicao = tk.StringVar(value=existing.get("CONDICAO", CONDICAO_FISICA_OPTIONS[0]))
        v_defeito = tk.StringVar(value=existing.get("DEFEITO", ""))
        v_acessorios = tk.StringVar(value=existing.get("ACESSORIOS", ""))
        init_obs_text = existing.get("OBSERVACOES", "")

        if not v_endereco.get().strip():
            cli_up = v_cliente.get().strip().upper()
            if not cli_up or "SEM CLIENTE" in cli_up or "ESTOQUE" in cli_up:
                v_endereco.set(self.db.lyda_hq_address)
                if not v_cep.get().strip():
                    v_cep.set("90240-005")
            else:
                c_info = self.db.get_client_address_info(v_cliente.get())
                if c_info.get("ENDERECO"):
                    v_endereco.set(c_info["ENDERECO"])
                if not v_cep.get() and c_info.get("CEP"):
                    v_cep.set(c_info["CEP"])

        # Lista de aparelhos deste lote (carrega automaticamente se o usuário selecionou vários [✓] na tabela!)
        batch_items: List[Dict[str, Any]] = [
            {
                "serial": serial_init,
                "tipo": default_tipo,
                "idx": item_idx if is_existing else None,
            }
        ]
        if extra_batch_indices:
            for e_idx in extra_batch_indices:
                if 0 <= e_idx < len(self.db.items):
                    e_it = self.db.items[e_idx]
                    batch_items.append(
                        {
                            "serial": e_it.get("CODIGO", ""),
                            "tipo": e_it.get("TIPO", "ANALISADOR"),
                            "idx": e_idx,
                        }
                    )

        # =====================================================================
        # BARRA DE AÇÕES RÁPIDAS (1 CLIQUE PARA PREENCHER AUTOMÁTICO)
        # =====================================================================
        q_box = tk.Frame(body, bg="#E2E8F0", padx=10, pady=6)
        q_box.pack(fill="x", pady=(0, 8))

        tk.Label(
            q_box,
            text="Ação Rápida (1 clique):",
            bg="#E2E8F0",
            fg="#0F172A",
            font=("Segoe UI", 9, "bold"),
        ).pack(side="left", padx=(0, 8))

        def _focus_obs_box():
            txt_obs.focus_set()
            txt_obs.mark_set("insert", "end")
            txt_obs.see("insert")

        def _preset_saida_cliente():
            modal_tabs.select(tab_main)
            v_acao.set("SAÍDA DA LYDA -> CLIENTE / HOSPITAL")
            if v_cliente.get().strip().upper() in ("", "SEM CLIENTE (ESTOQUE LYDA)", "ESTOQUE LYDA", "LYDA ESTOQUE"):
                v_cliente.set("")
                v_endereco.set("")
                v_cep.set("")
            if v_mod.get() == "PROPRIEDADE LYDA":
                v_mod.set("COMODATO")
            v_status.set("ATIVO NO CLIENTE")
            v_condicao.set("PERFEITO / FUNCIONANDO 100%")
            v_att_estoque.set("EM USO NO CLIENTE / N/A")
            cmb_cliente.focus_set()
            _refresh_live_cycle_ui()

        def _preset_volta_estoque_ja_atualizado():
            modal_tabs.select(tab_main)
            hoje_str = datetime.now().strftime("%d/%m/%Y")
            v_acao.set("RETORNO -> ESTOQUE LYDA (JÁ ATUALIZADO)")
            v_cliente.set("SEM CLIENTE (ESTOQUE LYDA)")
            v_endereco.set(self.db.lyda_hq_address)
            v_cep.set("90240-005")
            v_cidade.set("PORTO ALEGRE")
            v_uf.set("RS")
            v_setor.set("ESTOQUE SEDE LYDA")
            v_mod.set("PROPRIEDADE LYDA")
            v_status.set("ESTOQUE USADOS")
            v_ult_att.set(hoje_str)
            v_att_estoque.set("SIM - JÁ ATUALIZADO NO ESTOQUE (PRONTO P/ SAÍDA)")
            _refresh_live_cycle_ui()

        def _preset_volta_estoque_falta_atualizar():
            modal_tabs.select(tab_main)
            v_acao.set("RETORNO -> ESTOQUE LYDA (FALTA ATUALIZAR)")
            v_cliente.set("SEM CLIENTE (ESTOQUE LYDA)")
            v_endereco.set(self.db.lyda_hq_address)
            v_cep.set("90240-005")
            v_cidade.set("PORTO ALEGRE")
            v_uf.set("RS")
            v_setor.set("BANCADA TÉCNICA LYDA")
            v_mod.set("PROPRIEDADE LYDA")
            v_status.set("ESTOQUE USADOS")
            v_att_estoque.set("NÃO - PENDENTE ATUALIZAR NA BANCADA LYDA")
            _refresh_live_cycle_ui()

        def _preset_defeito_manut():
            modal_tabs.select(tab_main)
            v_acao.set("REGISTRAR DEFEITO / OCORRÊNCIA TÉCNICA")
            v_status.set("EM MANUTENÇÃO / SP")
            v_condicao.set("COM DEFEITO (VER OBSERVAÇÕES)")
            ent_defeito.focus_set()
            _refresh_live_cycle_ui()

        ttk.Button(
            q_box,
            text=" 1. Enviar p/ Hospital / Cliente",
            image=self.icons.get("upload", "#FFFFFF"),
            compound="left",
            style="Primary.TButton",
            cursor="hand2",
            command=_preset_saida_cliente,
        ).pack(side="left", padx=3, expand=True, fill="x")

        ttk.Button(
            q_box,
            text=" 2. Voltou p/ Estoque (JÁ ATUALIZADO)",
            image=self.icons.get("check", "#FFFFFF"),
            compound="left",
            style="Success.TButton",
            cursor="hand2",
            command=_preset_volta_estoque_ja_atualizado,
        ).pack(side="left", padx=3, expand=True, fill="x")

        ttk.Button(
            q_box,
            text=" 3. Voltou p/ Estoque (FALTA ATUALIZAR)",
            image=self.icons.get("download", "#FFFFFF"),
            compound="left",
            style="Dark.TButton",
            cursor="hand2",
            command=_preset_volta_estoque_falta_atualizar,
        ).pack(side="left", padx=3, expand=True, fill="x")

        ttk.Button(
            q_box,
            text=" 4. Com Defeito / Manutenção",
            image=self.icons.get("edit", "#FFFFFF"),
            compound="left",
            style="Amber.TButton",
            cursor="hand2",
            command=_preset_defeito_manut,
        ).pack(side="left", padx=3, expand=True, fill="x")

        # =====================================================================
        # DUAS ABAS SIMPLES E CLARAS
        # =====================================================================
        modal_tabs = ttk.Notebook(body)
        modal_tabs.pack(fill="both", expand=True, pady=(0, 8))

        tab_main = tk.Frame(modal_tabs, bg="#FFFFFF", padx=14, pady=10)
        tab_hist = tk.Frame(modal_tabs, bg="#FFFFFF", padx=14, pady=10)

        modal_tabs.add(tab_main, text="  1. Ficha do Aparelho (Local, Atualização & Observações)  ")
        modal_tabs.add(tab_hist, text=f"  2. Histórico deste Aparelho & Lote ({len(batch_items)})  ")

        # ---------------------------------------------------------------------
        # PASSO 1: ONDE ESTÁ O APARELHO E ENDEREÇO COMPLETO
        # ---------------------------------------------------------------------
        lf_dest = tk.LabelFrame(
            tab_main,
            text=" PASSO 1 — Onde está o Aparelho? (Hospital / Cliente ou Estoque da Lyda) ",
            bg="#FFFFFF",
            fg="#0F172A",
            font=("Segoe UI", 10, "bold"),
            padx=12,
            pady=8,
        )
        lf_dest.pack(fill="x", pady=(0, 8))
        for col_i in range(4):
            lf_dest.columnconfigure(col_i, weight=1)

        # Linha 0 & 1: Tipo, Serial, Modalidade, Status
        tk.Label(lf_dest, text="Equipamento:", bg="#FFFFFF", fg="#0F172A", font=("Segoe UI", 9, "bold")).grid(
            row=0, column=0, sticky="w", padx=4
        )
        ttk.Combobox(lf_dest, textvariable=v_tipo, values=EQUIPMENT_TYPES, state="readonly").grid(
            row=1, column=0, sticky="ew", padx=4, pady=(2, 6)
        )

        tk.Label(lf_dest, text="Nº de Série (Código de Barras):", bg="#FFFFFF", fg="#0F172A", font=("Segoe UI", 9, "bold")).grid(
            row=0, column=1, sticky="w", padx=4
        )
        ttk.Entry(lf_dest, textvariable=v_serial, font=("Consolas", 10, "bold")).grid(
            row=1, column=1, sticky="ew", padx=4, pady=(2, 6)
        )

        tk.Label(lf_dest, text="Modalidade (Comodato / Aluguel / Venda):", bg="#FFFFFF", fg="#0F172A", font=("Segoe UI", 9, "bold")).grid(
            row=0, column=2, sticky="w", padx=4
        )
        ttk.Combobox(lf_dest, textvariable=v_mod, values=MODALITIES, state="readonly").grid(
            row=1, column=2, sticky="ew", padx=4, pady=(2, 6)
        )

        tk.Label(lf_dest, text="Status Atual:", bg="#FFFFFF", fg="#0F172A", font=("Segoe UI", 9, "bold")).grid(
            row=0, column=3, sticky="w", padx=4
        )
        ttk.Combobox(lf_dest, textvariable=v_status, values=STATUS_OPTIONS).grid(
            row=1, column=3, sticky="ew", padx=4, pady=(2, 6)
        )

        # Linha 2 & 3: Hospital/Cliente, Setor, Operador
        cli_hdr = tk.Frame(lf_dest, bg="#FFFFFF")
        cli_hdr.grid(row=2, column=0, columnspan=2, sticky="ew", padx=4)
        tk.Label(
            cli_hdr,
            text="Hospital / Clínica / Local Atual:",
            bg="#FFFFFF",
            fg="#0F172A",
            font=("Segoe UI", 9, "bold"),
        ).pack(side="left")

        def _set_sede_lyda_address():
            v_cliente.set("SEM CLIENTE (ESTOQUE LYDA)")
            v_endereco.set(self.db.lyda_hq_address)
            v_cep.set("90240-005")
            v_cidade.set("PORTO ALEGRE")
            v_uf.set("RS")
            v_setor.set("ESTOQUE SEDE LYDA")
            v_mod.set("PROPRIEDADE LYDA")
            _refresh_live_cycle_ui()

        ttk.Button(
            cli_hdr,
            text=" Colocar no Estoque Lyda (Sem Cliente)",
            style="Secondary.TButton",
            cursor="hand2",
            command=_set_sede_lyda_address,
        ).pack(side="right")

        cmb_cliente = ttk.Combobox(lf_dest, textvariable=v_cliente, values=self.db.get_known_clients(), font=("Segoe UI", 10))
        cmb_cliente.grid(row=3, column=0, columnspan=2, sticky="ew", padx=4, pady=(2, 6))

        def _on_mov_client_selected(_evt=None):
            cli_sel = v_cliente.get().strip()
            if "SEM CLIENTE" in cli_sel.upper() or "ESTOQUE" in cli_sel.upper():
                _set_sede_lyda_address()
                return
            info = self.db.get_client_address_info(cli_sel)
            if info:
                if info.get("ENDERECO"):
                    v_endereco.set(info["ENDERECO"])
                if info.get("CEP"):
                    v_cep.set(info["CEP"])
                if info.get("CIDADE"):
                    v_cidade.set(info["CIDADE"])
                if info.get("UF"):
                    v_uf.set(info["UF"])
                if info.get("CONTATO_LOCAL"):
                    v_contato.set(info["CONTATO_LOCAL"])
            _refresh_live_cycle_ui()

        cmb_cliente.bind("<<ComboboxSelected>>", _on_mov_client_selected)

        tk.Label(
            lf_dest,
            text="Setor / Unidade (ex: UTI, Angio, Emergência):",
            bg="#FFFFFF",
            fg="#0F172A",
            font=("Segoe UI", 9, "bold"),
        ).grid(row=2, column=2, sticky="w", padx=4)
        ttk.Entry(lf_dest, textvariable=v_setor).grid(row=3, column=2, sticky="ew", padx=4, pady=(2, 6))

        tk.Label(
            lf_dest,
            text="Operador Responsável:",
            bg="#FFFFFF",
            fg="#0F172A",
            font=("Segoe UI", 9, "bold"),
        ).grid(row=2, column=3, sticky="w", padx=4)
        ttk.Combobox(lf_dest, textvariable=v_resp, values=self.db.operators).grid(
            row=3, column=3, sticky="ew", padx=4, pady=(2, 6)
        )

        # Linha 4 & 5: Endereço Completo (para Rota da Enfermeira), CEP e Cidade/UF
        tk.Label(
            lf_dest,
            text="Endereço Completo (Rua/Av., Número, Bairro — p/ Rota da Enfermeira):",
            bg="#FFFFFF",
            fg="#1E3A8A",
            font=("Segoe UI", 9, "bold"),
        ).grid(row=4, column=0, columnspan=2, sticky="w", padx=4)
        ttk.Entry(lf_dest, textvariable=v_endereco).grid(row=5, column=0, columnspan=2, sticky="ew", padx=4, pady=(2, 2))

        tk.Label(lf_dest, text="CEP:", bg="#FFFFFF", fg="#1E3A8A", font=("Segoe UI", 9, "bold")).grid(
            row=4, column=2, sticky="w", padx=4
        )
        cep_f = tk.Frame(lf_dest, bg="#FFFFFF")
        cep_f.grid(row=5, column=2, sticky="ew", padx=4, pady=(2, 2))
        ttk.Entry(cep_f, textvariable=v_cep, width=10).pack(side="left", fill="x", expand=True)

        def _buscar_cep_mov():
            ok_c, data_c, msg_c = lookup_cep_viacep(v_cep.get())
            if ok_c:
                v_cep.set(data_c.get("CEP", v_cep.get()))
                if data_c.get("ENDERECO"):
                    v_endereco.set(data_c["ENDERECO"])
                if data_c.get("CIDADE"):
                    v_cidade.set(data_c["CIDADE"])
                if data_c.get("UF"):
                    v_uf.set(data_c["UF"])
            else:
                messagebox.showwarning("Consulta CEP", msg_c, parent=dlg)

        ttk.Button(cep_f, text="Buscar CEP", style="Secondary.TButton", cursor="hand2", command=_buscar_cep_mov).pack(
            side="left", padx=(4, 0)
        )

        tk.Label(lf_dest, text="Cidade / UF:", bg="#FFFFFF", fg="#0F172A", font=("Segoe UI", 9, "bold")).grid(
            row=4, column=3, sticky="w", padx=4
        )
        cid_f = tk.Frame(lf_dest, bg="#FFFFFF")
        cid_f.grid(row=5, column=3, sticky="ew", padx=4, pady=(2, 2))
        ttk.Entry(cid_f, textvariable=v_cidade, width=12).pack(side="left", fill="x", expand=True)
        ttk.Combobox(cid_f, textvariable=v_uf, values=["RS", "SC", "PR", "SP", "RJ", "MG", "OUTRO"], width=4).pack(
            side="left", padx=(4, 0)
        )

        # ---------------------------------------------------------------------
        # PASSO 2: CONTROLE DE ATUALIZAÇÃO (DE 6 EM 6 MESES) — 1 LINHA LIMPA!
        # ---------------------------------------------------------------------
        lf_cycle = tk.LabelFrame(
            tab_main,
            text=" PASSO 2 — Controle de Atualização (De 6 em 6 Meses) ",
            bg="#F0FDF4",
            fg="#14532D",
            font=("Segoe UI", 10, "bold"),
            padx=12,
            pady=8,
        )
        lf_cycle.pack(fill="x", pady=(0, 8))
        for col_i in range(3):
            lf_cycle.columnconfigure(col_i, weight=1)

        tk.Label(
            lf_cycle,
            text="Data da Última Atualização (DD/MM/AAAA):",
            bg="#F0FDF4",
            fg="#14532D",
            font=("Segoe UI", 9, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=4)

        att_date_row = tk.Frame(lf_cycle, bg="#F0FDF4")
        att_date_row.grid(row=1, column=0, sticky="ew", padx=4, pady=(2, 2))
        ttk.Entry(att_date_row, textvariable=v_ult_att, width=13, font=("Consolas", 10, "bold")).pack(
            side="left", fill="x", expand=True
        )

        ttk.Button(
            att_date_row,
            text=" Foi Atualizado Hoje",
            style="Success.TButton",
            cursor="hand2",
            command=lambda: [
                v_ult_att.set(datetime.now().strftime("%d/%m/%Y")),
                v_att_estoque.set(
                    "SIM - JÁ ATUALIZADO NO ESTOQUE (PRONTO P/ SAÍDA)"
                    if "ESTOQUE" in v_cliente.get().upper() or "SEM CLIENTE" in v_cliente.get().upper()
                    else "EM USO NO CLIENTE / N/A"
                ),
                _refresh_live_cycle_ui(),
            ],
        ).pack(side="left", padx=(6, 0))

        tk.Label(
            lf_cycle,
            text="Próxima Atualização (+6 Meses Automático):",
            bg="#F0FDF4",
            fg="#14532D",
            font=("Segoe UI", 9, "bold"),
        ).grid(row=0, column=1, sticky="w", padx=4)
        lbl_calc_prox = tk.Label(
            lf_cycle,
            text="",
            bg="#FFFFFF",
            fg="#0F172A",
            font=("Segoe UI", 10, "bold"),
            padx=10,
            pady=5,
            relief="solid",
            bd=1,
            anchor="w",
        )
        lbl_calc_prox.grid(row=1, column=1, sticky="ew", padx=4, pady=(2, 2))

        tk.Label(
            lf_cycle,
            text="Situação de Atualização quando está no Estoque:",
            bg="#F0FDF4",
            fg="#14532D",
            font=("Segoe UI", 9, "bold"),
        ).grid(row=0, column=2, sticky="w", padx=4)
        ttk.Combobox(
            lf_cycle,
            textvariable=v_att_estoque,
            values=att_estoque_options,
            state="readonly",
            font=("Segoe UI", 9, "bold"),
        ).grid(row=1, column=2, sticky="ew", padx=4, pady=(2, 2))

        # ---------------------------------------------------------------------
        # PASSO 3: OBSERVAÇÕES, ANOTAÇÕES & CONDIÇÃO FÍSICA (CAIXA GRANDE E CLARA!)
        # ---------------------------------------------------------------------
        lf_obs = tk.LabelFrame(
            tab_main,
            text=" PASSO 3 — Observações, Anotações de Movimentação & Condição do Aparelho ",
            bg="#EFF6FF",
            fg="#1E3A8A",
            font=("Segoe UI", 10, "bold"),
            padx=12,
            pady=8,
        )
        lf_obs.pack(fill="both", expand=True)

        cond_row = tk.Frame(lf_obs, bg="#EFF6FF")
        cond_row.pack(fill="x", pady=(0, 6))
        cond_row.columnconfigure(0, weight=1)
        cond_row.columnconfigure(1, weight=1)

        tk.Label(
            cond_row,
            text="Condição de Funcionamento:",
            bg="#EFF6FF",
            fg="#0F172A",
            font=("Segoe UI", 9, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=4)
        ttk.Combobox(cond_row, textvariable=v_condicao, values=CONDICAO_FISICA_OPTIONS).grid(
            row=1, column=0, sticky="ew", padx=4, pady=(2, 0)
        )

        tk.Label(
            cond_row,
            text="Defeito / Erro Apresentado (preencha apenas se tiver defeito):",
            bg="#EFF6FF",
            fg="#B91C1C",
            font=("Segoe UI", 9, "bold"),
        ).grid(row=0, column=1, sticky="w", padx=4)
        ent_defeito = ttk.Entry(cond_row, textvariable=v_defeito)
        ent_defeito.grid(row=1, column=1, sticky="ew", padx=4, pady=(2, 0))

        # Barra de título + Botões rápidos para Observações
        obs_hdr = tk.Frame(lf_obs, bg="#EFF6FF")
        obs_hdr.pack(fill="x", pady=(6, 4))

        tk.Label(
            obs_hdr,
            text="OBSERVAÇÕES E ANOTAÇÕES DO APARELHO (Digite livremente abaixo):",
            bg="#EFF6FF",
            fg="#1E3A8A",
            font=("Segoe UI", 10, "bold"),
        ).pack(side="left", padx=4)

        def _append_obs_snippet(snippet: str):
            cur = txt_obs.get("1.0", "end-1c").strip()
            if cur:
                new_val = f"{cur}\n{snippet}"
            else:
                new_val = snippet
            txt_obs.delete("1.0", "end")
            txt_obs.insert("1.0", new_val)
            _focus_obs_box()

        def _clear_obs_box():
            txt_obs.delete("1.0", "end")
            _focus_obs_box()

        ttk.Button(
            obs_hdr,
            text=" Limpar Observação",
            style="Danger.TButton",
            cursor="hand2",
            command=_clear_obs_box,
        ).pack(side="right", padx=2)

        ttk.Button(
            obs_hdr,
            text=" + Pronto p/ Envio",
            style="Secondary.TButton",
            cursor="hand2",
            command=lambda: _append_obs_snippet(
                f"[{datetime.now().strftime('%d/%m/%Y')}] Revisado e atualizado na Lyda, pronto para envio."
            ),
        ).pack(side="right", padx=2)

        ttk.Button(
            obs_hdr,
            text=" + Recolhido / Vai para...",
            style="Secondary.TButton",
            cursor="hand2",
            command=lambda: _append_obs_snippet(
                f"[{datetime.now().strftime('%d/%m/%Y')}] Recolhido de: ___  ->  Vai para: "
            ),
        ).pack(side="right", padx=2)

        ttk.Button(
            obs_hdr,
            text=" + Inserir Data de Hoje",
            style="Primary.TButton",
            cursor="hand2",
            command=lambda: _append_obs_snippet(
                f"[{datetime.now().strftime('%d/%m/%Y')} - {v_resp.get() or 'LYDA'}]: "
            ),
        ).pack(side="right", padx=2)

        # Caixa de texto grande multi-linha (tk.Text) com borda destacada e cursor preto visível
        obs_frame = tk.Frame(lf_obs, bg="#2563EB", padx=2, pady=2)
        obs_frame.pack(fill="both", expand=True, padx=4, pady=(0, 2))

        txt_obs = tk.Text(
            obs_frame,
            height=4,
            bg="#FFFFFF",
            fg="#0F172A",
            insertbackground="#0F172A",
            selectbackground="#BFDBFE",
            selectforeground="#0F172A",
            font=("Segoe UI", 11),
            wrap="word",
            relief="flat",
            padx=10,
            pady=6,
            undo=True,
        )
        obs_scroll = ttk.Scrollbar(obs_frame, orient="vertical", command=txt_obs.yview)
        txt_obs.configure(yscrollcommand=obs_scroll.set)
        txt_obs.pack(side="left", fill="both", expand=True)
        obs_scroll.pack(side="right", fill="y")

        if init_obs_text:
            txt_obs.insert("1.0", init_obs_text)
        txt_obs.bind("<Button-1>", lambda _e: txt_obs.focus_set(), add="+")

        # ---------------------------------------------------------------------
        # ABA 2: HISTÓRICO COMPLETO DESTE APARELHO, EXTRAS & LOTE
        # ---------------------------------------------------------------------
        lf_extras = tk.LabelFrame(
            tab_hist,
            text=" Dados Complementares (Contato, Nota Fiscal, Acessórios e Lote) ",
            bg="#FFFFFF",
            fg="#0F172A",
            font=("Segoe UI", 9, "bold"),
            padx=12,
            pady=8,
        )
        lf_extras.pack(fill="x", pady=(0, 8))
        for col_i in range(4):
            lf_extras.columnconfigure(col_i, weight=1)

        tk.Label(lf_extras, text="Contato / Enfermeiro(a) no Local:", bg="#FFFFFF", fg="#0F172A", font=("Segoe UI", 9, "bold")).grid(
            row=0, column=0, sticky="w", padx=4
        )
        ttk.Entry(lf_extras, textvariable=v_contato).grid(row=1, column=0, sticky="ew", padx=4, pady=(2, 6))

        tk.Label(lf_extras, text="Nota Fiscal / Contrato:", bg="#FFFFFF", fg="#0F172A", font=("Segoe UI", 9, "bold")).grid(
            row=0, column=1, sticky="w", padx=4
        )
        ttk.Entry(lf_extras, textvariable=v_nf).grid(row=1, column=1, sticky="ew", padx=4, pady=(2, 6))

        tk.Label(lf_extras, text="Acessórios (Cabos / Fonte / Mala):", bg="#FFFFFF", fg="#0F172A", font=("Segoe UI", 9, "bold")).grid(
            row=0, column=2, sticky="w", padx=4
        )
        ttk.Entry(lf_extras, textvariable=v_acessorios).grid(row=1, column=2, sticky="ew", padx=4, pady=(2, 6))

        tk.Label(lf_extras, text="Versão do Software (CLEW / JAMS):", bg="#FFFFFF", fg="#0F172A", font=("Segoe UI", 9, "bold")).grid(
            row=0, column=3, sticky="w", padx=4
        )
        ttk.Entry(lf_extras, textvariable=v_versao_clew).grid(row=1, column=3, sticky="ew", padx=4, pady=(2, 6))

        # Lote de Aparelhos
        batch_top_row = tk.Frame(lf_extras, bg="#EFF6FF", padx=8, pady=6)
        batch_top_row.grid(row=2, column=0, columnspan=4, sticky="ew", padx=4, pady=(4, 4))

        tk.Label(
            batch_top_row,
            text="Adicionar outro Serial neste lote:",
            image=self.icons.get("barcode", "#1E3A8A"),
            compound="left",
            bg="#EFF6FF",
            fg="#1E3A8A",
            font=("Segoe UI", 9, "bold"),
        ).pack(side="left")

        v_batch_add = tk.StringVar()
        ent_batch_add = ttk.Entry(batch_top_row, textvariable=v_batch_add, width=18, font=("Consolas", 10, "bold"))
        ent_batch_add.pack(side="left", padx=6)

        lbl_batch_summary = tk.Label(
            lf_extras,
            text="",
            bg="#F8FAFC",
            fg="#0F172A",
            font=("Consolas", 9, "bold"),
            anchor="w",
            justify="left",
            padx=10,
            pady=6,
            relief="solid",
            bd=1,
            wraplength=860,
        )
        lbl_batch_summary.grid(row=3, column=0, columnspan=4, sticky="ew", padx=4)

        def _refresh_batch_banner():
            if batch_items:
                batch_items[0]["serial"] = clean_barcode_serial(v_serial.get()) or serial_init
                batch_items[0]["tipo"] = v_tipo.get()
            parts = [f"{i+1}. [{b['tipo']}] SN: {b['serial']}" for i, b in enumerate(batch_items)]
            lbl_batch_summary.configure(text=f"Aparelhos neste lote ({len(batch_items)}):  " + "   |   ".join(parts))
            modal_tabs.tab(tab_hist, text=f"  2. Histórico deste Aparelho & Lote ({len(batch_items)})  ")
            if len(batch_items) > 1:
                lbl_hdr_title.configure(text=f"Editando / Movimentando {len(batch_items)} Aparelhos Selecionados em Lote")
            else:
                lbl_hdr_title.configure(text=f"Aparelho i-STAT — Nº de Série: {v_serial.get() or serial_init or 'NOVO'}")

        def _add_serial_to_batch(raw_code: str):
            c_ser = clean_barcode_serial(raw_code)
            if not c_ser:
                return
            if any(b["serial"].upper() == c_ser.upper() for b in batch_items if b["serial"]):
                v_batch_add.set("")
                return
            found = self.db.find_by_barcode(c_ser)
            if found:
                f_item = found[0]
                f_idx = next((i for i, x in enumerate(self.db.items) if x is f_item), None)
                f_tipo = f_item.get("TIPO", "ANALISADOR")
                f_ser = f_item.get("CODIGO", c_ser)
            else:
                f_idx = None
                f_tipo = "SIMULADOR" if c_ser.startswith("S") else ("DOWNLOADER" if c_ser.startswith("DRC") else "ANALISADOR")
                f_ser = c_ser
            batch_items.append({"serial": f_ser, "tipo": f_tipo, "idx": f_idx})
            v_batch_add.set("")
            _refresh_batch_banner()

        def _on_add_batch_click(_evt=None):
            _add_serial_to_batch(v_batch_add.get())

        ent_batch_add.bind("<Return>", _on_add_batch_click)
        ent_batch_add.bind("<KP_Enter>", _on_add_batch_click)

        ttk.Button(
            batch_top_row,
            text=" + Incluir no Lote",
            image=self.icons.get("plus", "#FFFFFF"),
            compound="left",
            style="Primary.TButton",
            cursor="hand2",
            command=_on_add_batch_click,
        ).pack(side="left", padx=2)

        def _remove_last_from_batch():
            if len(batch_items) > 1:
                batch_items.pop()
                _refresh_batch_banner()

        ttk.Button(
            batch_top_row,
            text=" Remover Último",
            style="Secondary.TButton",
            cursor="hand2",
            command=_remove_last_from_batch,
        ).pack(side="right")

        # Tabela de Histórico deste Aparelho
        lf_h_tbl = tk.LabelFrame(
            tab_hist,
            text=" Histórico Completo de Movimentações, Atualizações e Observações deste Aparelho ",
            bg="#FFFFFF",
            fg="#0F172A",
            font=("Segoe UI", 9, "bold"),
            padx=8,
            pady=6,
        )
        lf_h_tbl.pack(fill="both", expand=True)

        cols_ih = ("DATA_HORA", "ACAO", "CLIENTE", "MODALIDADE", "CONDICAO", "DETALHES")
        tree_ih = ttk.Treeview(lf_h_tbl, columns=cols_ih, show="headings", height=9)
        for c_id, c_title, c_w in [
            ("DATA_HORA", "Data / Hora", 130),
            ("ACAO", "Operação / Movimento", 185),
            ("CLIENTE", "Hospital / Local", 175),
            ("MODALIDADE", "Modalidade", 105),
            ("CONDICAO", "Condição", 135),
            ("DETALHES", "Observações / Detalhes", 280),
        ]:
            tree_ih.heading(c_id, text=c_title)
            tree_ih.column(c_id, width=c_w, anchor="w")

        ih_vsb = ttk.Scrollbar(lf_h_tbl, orient="vertical", command=tree_ih.yview)
        tree_ih.configure(yscrollcommand=ih_vsb.set)
        tree_ih.pack(side="left", fill="both", expand=True)
        ih_vsb.pack(side="right", fill="y")

        if serial_init:
            for h_row in self.db.get_item_history(serial_init):
                tree_ih.insert(
                    "",
                    "end",
                    values=(
                        h_row.get("DATA_HORA", ""),
                        h_row.get("ACAO", ""),
                        h_row.get("CLIENTE", ""),
                        h_row.get("MODALIDADE", ""),
                        h_row.get("CONDICAO", ""),
                        h_row.get("DEFEITO_OBS") or h_row.get("DETALHES", ""),
                    ),
                )

        def _refresh_live_cycle_ui(*_args):
            try:
                c_m = int(v_ciclo_meses.get())
            except Exception:
                c_m = 6
            temp_item = {
                "ULTIMA_ATUALIZACAO": v_ult_att.get().strip(),
                "CICLO_ATUALIZACAO_MESES": c_m,
                "ATUALIZADO_NO_ESTOQUE": v_att_estoque.get(),
            }
            c_info = compute_update_cycle_info(temp_item, default_cycle_months=c_m)
            lbl_calc_prox.configure(
                text=c_info["badge_text"],
                bg=c_info["bg_color"],
                fg=c_info["fg_color"],
            )
            lbl_hdr_cycle_badge.configure(
                text=f"Ciclo 6m: {c_info['badge_text']}",
                bg=c_info["bg_color"],
                fg=c_info["fg_color"],
            )
            lbl_hdr_sub.configure(
                text=f"Local: {v_cliente.get()}   |   Modalidade: {v_mod.get()}   |   Bancada: {v_att_estoque.get()}"
            )

        v_ult_att.trace_add("write", _refresh_live_cycle_ui)
        v_att_estoque.trace_add("write", _refresh_live_cycle_ui)
        v_cliente.trace_add("write", _refresh_live_cycle_ui)
        v_tipo.trace_add("write", lambda *_: _refresh_batch_banner())
        v_serial.trace_add("write", lambda *_: _refresh_batch_banner())
        _refresh_batch_banner()
        _refresh_live_cycle_ui()

        # =====================================================================
        # BARRA INFERIOR DE CONFIRMAÇÃO
        # =====================================================================
        footer = tk.Frame(body, bg="#F1F5F9")
        footer.pack(fill="x", side="bottom")

        def _confirm_movement(and_print: bool = False, and_romaneio: bool = False):
            main_serial = clean_barcode_serial(v_serial.get()) or clean_barcode_serial(serial_init)
            if not main_serial:
                messagebox.showwarning(
                    "Serial Obrigatório",
                    "Informe o Número de Série / Código de Barras do aparelho.",
                    parent=dlg,
                )
                return

            obs_raw = txt_obs.get("1.0", "end-1c").strip()
            obs_combined = " | ".join(line.strip() for line in obs_raw.splitlines() if line.strip())
            defeito_str = v_defeito.get().strip()
            if defeito_str and defeito_str not in obs_combined:
                obs_combined = f"[DEFEITO: {defeito_str}] {obs_combined}".strip()

            batch_items[0]["serial"] = main_serial
            batch_items[0]["tipo"] = v_tipo.get()

            kit_ana_ref = v_kit_ana.get().strip() or next(
                (b["serial"] for b in batch_items if b["tipo"] == "ANALISADOR"),
                existing.get("KIT_ANALISADOR", ""),
            )

            try:
                cyc_months_val = max(1, min(24, int(v_ciclo_meses.get())))
            except Exception:
                cyc_months_val = 6

            cli_final = v_cliente.get().strip() or "SEM CLIENTE (ESTOQUE LYDA)"
            end_final = v_endereco.get().strip()
            if not end_final and ("SEM CLIENTE" in cli_final.upper() or "ESTOQUE" in cli_final.upper()):
                end_final = self.db.lyda_hq_address

            cyc_calc = compute_update_cycle_info(
                {
                    "ULTIMA_ATUALIZACAO": v_ult_att.get().strip(),
                    "CICLO_ATUALIZACAO_MESES": cyc_months_val,
                    "ATUALIZADO_NO_ESTOQUE": v_att_estoque.get(),
                },
                default_cycle_months=cyc_months_val,
            )

            saved_records: List[Dict[str, Any]] = []
            saved_indices: List[int] = []

            for b_entry in batch_items:
                b_ser = b_entry["serial"]
                b_tipo = b_entry["tipo"]
                b_idx = b_entry["idx"]
                b_exists = b_idx is not None and 0 <= b_idx < len(self.db.items)

                rec = self.db.upsert_item(
                    {
                        "CODIGO": b_ser,
                        "SERIAL_ORIGINAL": b_ser,
                        "TIPO": b_tipo,
                        "CLIENTE": cli_final,
                        "ENDERECO": end_final,
                        "CEP": v_cep.get().strip(),
                        "CONTATO_LOCAL": v_contato.get().strip(),
                        "CIDADE": v_cidade.get().strip(),
                        "UF": v_uf.get().strip(),
                        "SETOR": v_setor.get().strip(),
                        "MODALIDADE": v_mod.get(),
                        "STATUS": v_status.get(),
                        "CONDICAO": v_condicao.get(),
                        "DEFEITO": defeito_str,
                        "ULTIMA_ATUALIZACAO": v_ult_att.get().strip(),
                        "VERSAO_CLEW": v_versao_clew.get().strip(),
                        "CICLO_ATUALIZACAO_MESES": cyc_months_val,
                        "PROXIMA_ATUALIZACAO": cyc_calc["next_date_str"] or "PENDENTE",
                        "ATUALIZADO_NO_ESTOQUE": v_att_estoque.get(),
                        "NOTA_FISCAL": v_nf.get().strip(),
                        "ACESSORIOS": v_acessorios.get().strip(),
                        "KIT_ANALISADOR": kit_ana_ref if (len(batch_items) > 1 or kit_ana_ref) else existing.get("KIT_ANALISADOR", ""),
                        "OBSERVACOES": obs_combined,
                    },
                    original_idx=b_idx if b_exists else None,
                    custom_action=v_acao.get(),
                    responsavel=v_resp.get().strip(),
                )
                saved_records.append(rec)
                f_idx = b_idx if b_exists else (len(self.db.items) - 1)
                saved_indices.append(f_idx)

            if v_propagate_addr.get() and end_final and "SEM CLIENTE" not in cli_final.upper() and "ESTOQUE" not in cli_final.upper():
                self.db.propagate_client_address(
                    cli_final,
                    end_final,
                    v_cep.get().strip(),
                    v_cidade.get().strip(),
                    v_uf.get().strip(),
                    v_contato.get().strip(),
                )

            first_saved = saved_records[0]
            self.currently_scanned_index = saved_indices[0]

            self.scan_tipo_var.set(first_saved["TIPO"])
            self.scan_bc_var.set(first_saved["CODIGO"])
            self.scan_mod_var.set(first_saved["MODALIDADE"])
            self.scan_status_var.set(first_saved["STATUS"])
            self.scan_cliente_var.set(first_saved["CLIENTE"])
            self.scan_cidade_var.set(first_saved["CIDADE"])
            self.scan_uf_var.set(first_saved["UF"])
            self.scan_setor_var.set(first_saved["SETOR"])
            self.scan_obs_var.set(first_saved["OBSERVACOES"])

            self._populate_data_tree()
            self._refresh_history_tree()
            if saved_indices:
                self.selected_indices = saved_indices
                self._update_preview()

            dlg.destroy()

            if and_romaneio:
                generate_and_open_romaneio(
                    workspace_dir=WORKSPACE_DIR,
                    acao=v_acao.get(),
                    cliente=cli_final,
                    cidade=v_cidade.get(),
                    uf=v_uf.get(),
                    setor=v_setor.get(),
                    modalidade=v_mod.get(),
                    status=v_status.get(),
                    condicao=v_condicao.get(),
                    defeito=defeito_str,
                    observacoes=obs_combined,
                    responsavel=v_resp.get().strip(),
                    items=saved_records,
                )

            if and_print:
                self._execute_print(only_current_page=True)

        ttk.Button(
            footer,
            text=" Cancelar",
            style="Secondary.TButton",
            cursor="hand2",
            command=dlg.destroy,
        ).pack(side="left")

        ttk.Button(
            footer,
            text=" Salvar & Imprimir Etiqueta",
            image=self.icons.get("printer", "#FFFFFF"),
            compound="left",
            style="Primary.TButton",
            cursor="hand2",
            command=lambda: _confirm_movement(and_print=True, and_romaneio=False),
        ).pack(side="right", padx=(6, 0))

        ttk.Button(
            footer,
            text=" Salvar & Gerar Romaneio (A4)",
            image=self.icons.get("copy", "#FFFFFF"),
            compound="left",
            style="Dark.TButton",
            cursor="hand2",
            command=lambda: _confirm_movement(and_print=False, and_romaneio=True),
        ).pack(side="right", padx=(6, 0))

        ttk.Button(
            footer,
            text=" Salvar Alterações",
            image=self.icons.get("check", "#FFFFFF"),
            compound="left",
            style="Success.TButton",
            cursor="hand2",
            command=lambda: _confirm_movement(and_print=False, and_romaneio=False),
        ).pack(side="right")

    def _save_scanned_item_changes(self):
        bc = clean_barcode_serial(self.scan_bc_var.get())
        if not bc:
            messagebox.showwarning("Atenção", "Informe o número de série / código de barras.")
            return
        data = {
            "CODIGO": bc,
            "SERIAL_ORIGINAL": bc,
            "TIPO": self.scan_tipo_var.get(),
            "CLIENTE": self.scan_cliente_var.get(),
            "CIDADE": self.scan_cidade_var.get(),
            "UF": self.scan_uf_var.get(),
            "SETOR": self.scan_setor_var.get(),
            "MODALIDADE": self.scan_mod_var.get(),
            "STATUS": self.scan_status_var.get(),
            "OBSERVACOES": self.scan_obs_var.get(),
        }
        saved = self.db.upsert_item(data, original_idx=self.currently_scanned_index)
        if self.currently_scanned_index is None:
            self.currently_scanned_index = len(self.db.items) - 1
        self._populate_data_tree()
        self._refresh_history_tree()
        self.selected_indices = [self.currently_scanned_index]
        self._update_preview()
        self.lbl_scan_status.configure(
            text=f"[SALVO] [{saved['TIPO']}] SN: {saved['CODIGO']}  ->  {saved['CLIENTE']} ({saved['STATUS']})",
            bg="#DBEAFE",
            fg="#1E40AF",
        )
        self.ent_scanner.focus_set()
        self.ent_scanner.selection_range(0, "end")

    def _print_scanned_item_only(self):
        if self.currently_scanned_index is None or not (0 <= self.currently_scanned_index < len(self.db.items)):
            messagebox.showwarning("Bipe um Equipamento", "Bipe ou busque um equipamento primeiro para imprimir sua etiqueta.")
            return
        self.selected_indices = [self.currently_scanned_index]
        self._update_preview()
        self._execute_print(only_current_page=True)

    def _refresh_history_tree(self):
        if not hasattr(self, "tree_hist"):
            return
        self.tree_hist.delete(*self.tree_hist.get_children())
        q = self.hist_search_var.get().strip().lower() if hasattr(self, "hist_search_var") else ""
        shown = 0
        for idx, h in enumerate(self.db.history):
            if q:
                blob = " ".join(str(v).lower() for v in h.values())
                if q not in blob:
                    continue
            op = h.get("OPERADOR") or h.get("RESPONSAVEL") or "-"
            pc = h.get("COMPUTADOR", "")
            op_pc = f"{op} ({pc})" if pc else op
            self.tree_hist.insert(
                "",
                "end",
                iid=str(idx),
                values=(
                    h.get("DATA_HORA", ""),
                    h.get("CODIGO_BARRAS", ""),
                    h.get("TIPO", ""),
                    h.get("ACAO", ""),
                    op_pc,
                    h.get("DETALHES", ""),
                ),
            )
            shown += 1
            if shown >= 200:
                break

    def _reprint_romaneio_from_history(self):
        sel = self.tree_hist.selection()
        if not sel:
            messagebox.showinfo(
                "Gerar Romaneio",
                "Selecione uma movimentação na tabela de Histórico abaixo (ou dê duplo clique nela) para abrir/imprimir o Romaneio A4/PDF.",
            )
            return
        h_idx = int(sel[0])
        if not (0 <= h_idx < len(self.db.history)):
            return
        h = self.db.history[h_idx]
        serial = h.get("CODIGO_BARRAS", "")
        matched = self.db.find_by_barcode(serial)
        item_rec = matched[0] if matched else {
            "TIPO": h.get("TIPO", "ANALISADOR"),
            "CODIGO": serial,
            "CONDICAO": h.get("CONDICAO", "PERFEITO / FUNCIONANDO 100%"),
            "OBSERVACOES": h.get("DEFEITO_OBS") or h.get("DETALHES", ""),
        }
        generate_and_open_romaneio(
            workspace_dir=WORKSPACE_DIR,
            acao=h.get("ACAO", "MOVIMENTAÇÃO DE ESTOQUE"),
            cliente=h.get("CLIENTE") or item_rec.get("CLIENTE", "SEM CLIENTE (ESTOQUE LYDA)"),
            cidade=item_rec.get("CIDADE", "PORTO ALEGRE"),
            uf=item_rec.get("UF", "RS"),
            setor=item_rec.get("SETOR", "-"),
            modalidade=h.get("MODALIDADE") or item_rec.get("MODALIDADE", "-"),
            status=item_rec.get("STATUS", "-"),
            condicao=h.get("CONDICAO") or item_rec.get("CONDICAO", "PERFEITO / FUNCIONANDO 100%"),
            defeito=h.get("DEFEITO_OBS", ""),
            observacoes=h.get("DETALHES", ""),
            responsavel=h.get("OPERADOR") or h.get("RESPONSAVEL") or self.var_operador_atual.get(),
            items=[item_rec],
        )

    # =========================================================================
    # SINCRONIZAÇÃO EM TEMPO REAL MULTI-PC (SHAREPOINT LYDA / ONEDRIVE / REDE)
    # =========================================================================
    def _update_sync_status_banner(self, custom_msg: str = ""):
        if not hasattr(self, "lbl_sync_status_bar"):
            return
        if custom_msg:
            self.lbl_sync_status_bar.configure(text=f"[Sincronizado] {custom_msg}", fg="#34D399")
        else:
            self.lbl_sync_status_bar.configure(text="", fg="#94A3B8")

    def _start_multi_pc_sync_polling(self):
        """Verifica automaticamente a cada 2,5 segundos se outro computador salvou alterações na base compartilhada."""
        try:
            if not self._active_modal_open:
                sync_notice = self.db.check_for_external_updates()
                if sync_notice:
                    self._populate_data_tree()
                    self._refresh_history_tree()
                    self._refresh_operators_ui()
                    self._update_sync_status_banner(custom_msg=sync_notice)
        except Exception:
            pass
        self.after(2500, self._start_multi_pc_sync_polling)

    def _detect_cloud_or_network_candidates(self) -> List[tuple[str, str]]:
        """Detecta automaticamente pastas sincronizadas do SharePoint da Lyda, OneDrive Corporativo ou Google Drive."""
        home = os.path.expanduser("~")
        candidates: List[tuple[str, str]] = []
        # Procura pastas SharePoint / OneDrive Corporativo na pasta do usuário (Windows e Mac)
        try:
            for entry in sorted(os.listdir(home)):
                low = entry.lower()
                full_p = os.path.join(home, entry)
                if os.path.isdir(full_p) and any(k in low for k in ("sharepoint", "onedrive", "lyda")):
                    candidates.append((f"SharePoint / OneDrive ({entry})", os.path.join(full_p, "LYDA_iSTAT_Estoque")))
        except Exception:
            pass
        # macOS CloudStorage (OneDrive / SharePoint modernos no Mac)
        cs_dir = os.path.join(home, "Library", "CloudStorage")
        if os.path.isdir(cs_dir):
            try:
                for entry in sorted(os.listdir(cs_dir)):
                    full_p = os.path.join(cs_dir, entry)
                    if os.path.isdir(full_p):
                        candidates.append((f"SharePoint / Nuvem ({entry})", os.path.join(full_p, "LYDA_iSTAT_Estoque")))
            except Exception:
                pass
        return candidates

    def _on_open_multi_pc_sync_modal(self):
        """Abre a central de configuração para vários computadores usarem o mesmo banco de dados sincronizado."""
        self._active_modal_open = True
        dlg = tk.Toplevel(self)
        dlg.title("Sincronização Multi-PC em Tempo Real — Vários Computadores na LYDA")
        dlg.geometry("760x540")
        dlg.configure(bg="#F8FAFC")
        dlg.transient(self)
        dlg.grab_set()
        dlg.bind("<Destroy>", lambda _e: setattr(self, "_active_modal_open", False))

        hdr = tk.Frame(dlg, bg="#0F172A", padx=18, pady=12)
        hdr.pack(fill="x")
        tk.Label(
            hdr,
            text="SINCRONIZAÇÃO MULTI-PC EM TEMPO REAL (REDE LOCAL OU NUVEM)",
            bg="#0F172A",
            fg="#FFFFFF",
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w")
        tk.Label(
            hdr,
            text="Como fazer vários computadores da Lyda enxergarem e atualizarem o mesmo estoque ao mesmo tempo:",
            bg="#0F172A",
            fg="#38BDF8",
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w", pady=(2, 0))

        body = tk.Frame(dlg, bg="#F8FAFC", padx=16, pady=12)
        body.pack(fill="both", expand=True)

        info_card = tk.LabelFrame(
            body,
            text=" Como Funciona a Sincronização Automática entre os Computadores da Lyda ",
            bg="#FFFFFF",
            fg="#0F172A",
            font=("Segoe UI", 9, "bold"),
            padx=12,
            pady=10,
        )
        info_card.pack(fill="x", pady=(0, 10))

        steps_text = (
            "1. Escolha UMA pasta compartilhada que todos os PCs consigam acessar:\n"
            "   • Opção A (Rede Local da Lyda): Uma pasta compartilhada no servidor/PC principal (ex: \\\\SERVIDOR\\Lyda_Estoque ou Z:\\Lyda_Estoque).\n"
            "   • Opção B (Nuvem Automática): Uma pasta dentro do Google Drive Desktop, OneDrive ou Dropbox instalado nos PCs.\n"
            "2. Em cada computador da Lyda, clique em 'Escolher Pasta Compartilhada...' abaixo e aponte para essa mesma pasta.\n"
            "3. Pronto! O sistema possui Mesclagem Atômica sem Conflitos e atualização ao vivo a cada 2,5 segundos:\n"
            "   quando uma pessoa bipar um aparelho no PC 1, a tela do PC 2 e do PC 3 atualiza sozinha na mesma hora!"
        )
        tk.Label(
            info_card,
            text=steps_text,
            bg="#FFFFFF",
            fg="#334155",
            font=("Segoe UI", 9),
            justify="left",
            anchor="w",
        ).pack(fill="x")

        status_card = tk.LabelFrame(
            body,
            text=" Pasta do Banco de Dados Ativa Neste Computador ",
            bg="#FFFFFF",
            fg="#0F172A",
            font=("Segoe UI", 9, "bold"),
            padx=12,
            pady=10,
        )
        status_card.pack(fill="x", pady=(0, 10))

        v_curr_folder = tk.StringVar(value=self.db.shared_db_dir)
        tk.Label(
            status_card,
            text=f"Computador Atual: {self.db.pc_hostname}    |    Operador Atual: {self.var_operador_atual.get()}",
            bg="#FFFFFF",
            fg="#1E40AF",
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w", pady=(0, 6))

        folder_row = tk.Frame(status_card, bg="#FFFFFF")
        folder_row.pack(fill="x")
        ent_f = ttk.Entry(folder_row, textvariable=v_curr_folder, font=("Consolas", 9, "bold"))
        ent_f.pack(side="left", fill="x", expand=True, padx=(0, 8))

        def _apply_folder(target_dir: str):
            ok, msg = self.db.set_shared_folder(target_dir)
            if ok:
                v_curr_folder.set(self.db.shared_db_dir)
                self._populate_data_tree()
                self._refresh_history_tree()
                self._update_sync_status_banner()
                messagebox.showinfo("Sincronização Multi-PC Ativada", msg, parent=dlg)
            else:
                messagebox.showerror("Erro", msg, parent=dlg)

        def _browse_shared_folder():
            chosen = filedialog.askdirectory(
                title="Selecionar Pasta Compartilhada (Rede Local / Google Drive / OneDrive / Dropbox)",
                initialdir=self.db.shared_db_dir,
                parent=dlg,
            )
            if chosen:
                _apply_folder(chosen)

        ttk.Button(
            folder_row,
            text=" Escolher Pasta Compartilhada...",
            image=self.icons.get("upload", "#FFFFFF"),
            compound="left",
            style="Primary.TButton",
            cursor="hand2",
            command=_browse_shared_folder,
        ).pack(side="right")

        ttk.Button(
            status_card,
            text=" Aplicar Caminho Digitado Acima (ex: \\\\SERVIDOR\\Lyda_Estoque)",
            image=self.icons.get("check", "#FFFFFF"),
            compound="left",
            style="Success.TButton",
            cursor="hand2",
            command=lambda: _apply_folder(v_curr_folder.get().strip()),
        ).pack(anchor="e", pady=(6, 0))

        # Atalhos automáticos se detectar OneDrive / Google Drive / Dropbox no computador
        cloud_cands = self._detect_cloud_or_network_candidates()
        if cloud_cands:
            lf_cloud = tk.LabelFrame(
                body,
                text=" Pastas de Nuvem Detectadas Neste Computador (1 Clique para Usar) ",
                bg="#FFFFFF",
                fg="#0F172A",
                font=("Segoe UI", 9, "bold"),
                padx=12,
                pady=8,
            )
            lf_cloud.pack(fill="x", pady=(0, 10))
            for lbl_c, path_c in cloud_cands[:3]:
                ttk.Button(
                    lf_cloud,
                    text=f" Usar {lbl_c}  ->  {path_c}",
                    image=self.icons.get("refresh", "#0F172A"),
                    compound="left",
                    style="Secondary.TButton",
                    cursor="hand2",
                    command=lambda p=path_c: _apply_folder(p),
                ).pack(fill="x", pady=2)

        footer = tk.Frame(body, bg="#F8FAFC")
        footer.pack(fill="x", side="bottom")
        ttk.Button(
            footer,
            text=" Voltar para Pasta Padrão Local",
            style="Secondary.TButton",
            cursor="hand2",
            command=lambda: _apply_folder(WORKSPACE_DIR),
        ).pack(side="left")

        ttk.Button(
            footer,
            text=" Concluído / Fechar",
            style="Dark.TButton",
            cursor="hand2",
            command=dlg.destroy,
        ).pack(side="right")

    def _open_item_dialog(self, edit_index: Optional[int] = None):
        """Abre o Mega Editor Completo do Aparelho i-STAT (Cadastro ou Edição Unificada)."""
        is_edit = edit_index is not None and 0 <= edit_index < len(self.db.items)
        serial_str = self.db.items[edit_index].get("CODIGO", "") if is_edit else ""
        self._open_barcode_movement_modal(scanned_serial=serial_str, item_idx=edit_index if is_edit else None)

    def _open_kit_dialog(self):
        self._active_modal_open = True
        dlg = tk.Toplevel(self)
        dlg.title("Cadastrar Kit Completo i-STAT (Analisador + Impressora + Simulador + Downloader)")
        dlg.geometry("600x540")
        dlg.configure(bg="#FFFFFF")
        dlg.transient(self)
        dlg.grab_set()
        dlg.bind("<Destroy>", lambda _e: setattr(self, "_active_modal_open", False))

        frm = tk.Frame(dlg, bg="#FFFFFF", padx=18, pady=14)
        frm.pack(fill="both", expand=True)

        tk.Label(
            frm,
            text="Preencha os seriais do Kit (deixe em branco os aparelhos que não fizerem parte):\nCada serial preenchido ganhará sua própria mini-etiqueta de código de barras.",
            bg="#EFF6FF",
            fg="#1E40AF",
            font=("Segoe UI", 8, "bold"),
            justify="left",
            padx=8,
            pady=6,
        ).grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))

        v_cliente = tk.StringVar(value="SEM CLIENTE (ESTOQUE LYDA)")
        v_endereco = tk.StringVar(value="")
        v_cep = tk.StringVar(value="")
        v_cidade = tk.StringVar(value="PORTO ALEGRE")
        v_uf = tk.StringVar(value="RS")
        v_setor = tk.StringVar(value="LABORATÓRIO")
        v_mod = tk.StringVar(value="COMODATO")
        v_ana = tk.StringVar()
        v_imp = tk.StringVar()
        v_sim = tk.StringVar()
        v_dwl = tk.StringVar()
        v_obs = tk.StringVar()

        rows_spec = [
            ("Cliente / Hospital (ou SEM CLIENTE):", v_cliente, self.db.get_known_clients()),
            ("Endereço Completo (Rua, Nº, Bairro):", v_endereco, None),
            ("CEP:", v_cep, None),
            ("Cidade:", v_cidade, None),
            ("UF:", v_uf, ["RS", "SC", "PR", "SP", "OUTRO"]),
            ("Setor:", v_setor, None),
            ("Modalidade:", v_mod, MODALITIES),
            ("Serial do ANALISADOR:", v_ana, None),
            ("Serial da IMPRESSORA:", v_imp, None),
            ("Serial do SIMULADOR (ex: S-146178):", v_sim, None),
            ("Serial do DOWNLOADER (ex: DRC110815):", v_dwl, None),
            ("Observações:", v_obs, None),
        ]

        for idx, (lbl, var, opts) in enumerate(rows_spec, start=1):
            tk.Label(frm, text=lbl, bg="#FFFFFF", fg="#0F172A", font=("Segoe UI", 9, "bold")).grid(row=idx, column=0, sticky="w", pady=3)
            if opts:
                w = ttk.Combobox(frm, textvariable=var, values=opts, width=28)
                if var is v_cliente:
                    def _on_kit_cli(_e=None):
                        inf = self.db.get_client_address_info(v_cliente.get())
                        if inf.get("ENDERECO"):
                            v_endereco.set(inf["ENDERECO"])
                        if inf.get("CEP"):
                            v_cep.set(inf["CEP"])
                        if inf.get("CIDADE"):
                            v_cidade.set(inf["CIDADE"])
                        if inf.get("UF"):
                            v_uf.set(inf["UF"])
                    w.bind("<<ComboboxSelected>>", _on_kit_cli)
            else:
                w = ttk.Entry(frm, textvariable=var, width=30)
            w.grid(row=idx, column=1, sticky="ew", pady=3, padx=(8, 0))
        frm.columnconfigure(1, weight=1)

        def _confirm_kit():
            new_indices = []
            ana_clean = clean_barcode_serial(v_ana.get())
            cli_final = v_cliente.get() or "LYDA ESTOQUE"
            for tipo, raw_s in [
                ("ANALISADOR", v_ana.get()),
                ("IMPRESSORA", v_imp.get()),
                ("SIMULADOR", v_sim.get()),
                ("DOWNLOADER", v_dwl.get()),
            ]:
                if clean_barcode_serial(raw_s):
                    self.db.upsert_item(
                        {
                            "TIPO": tipo,
                            "CODIGO": raw_s,
                            "SERIAL_ORIGINAL": raw_s,
                            "CLIENTE": cli_final,
                            "ENDERECO": v_endereco.get().strip(),
                            "CEP": v_cep.get().strip(),
                            "CIDADE": v_cidade.get(),
                            "UF": v_uf.get(),
                            "SETOR": v_setor.get(),
                            "MODALIDADE": v_mod.get(),
                            "STATUS": "ATIVO NO CLIENTE",
                            "KIT_ANALISADOR": ana_clean,
                            "OBSERVACOES": v_obs.get(),
                        }
                    )
                    new_indices.append(len(self.db.items) - 1)

            if not new_indices:
                messagebox.showwarning("Atenção", "Preencha pelo menos 1 serial do Kit.", parent=dlg)
                return

            self._populate_data_tree()
            self._refresh_history_tree()
            self.tree.selection_set([str(i) for i in new_indices if self.tree.exists(str(i))])
            self._on_tree_selection_changed()
            dlg.destroy()
            messagebox.showinfo(
                "Kit Cadastrado",
                f"{len(new_indices)} equipamento(s) cadastrado(s) e já selecionado(s) no preview ao lado para imprimir.",
            )

        ttk.Button(
            frm,
            text=" Cadastrar Kit e Preparar Etiquetas",
            image=self.icons.get("check", "#FFFFFF"),
            compound="left",
            style="Success.TButton",
            cursor="hand2",
            command=_confirm_kit,
        ).grid(row=len(rows_spec) + 1, column=0, columnspan=2, pady=(12, 0), sticky="ew")

    # =========================================================================
    # CENTRAL DE ROTAS DA ENFERMEIRA (PREVIEW AO VIVO DO MAPA GOOGLE MAPS + PDF)
    # =========================================================================
    def _open_nurse_route_modal(self, initial_client_name: str = ""):
        """
        Abre o Planejador de Rota da Enfermeira saindo da Sede da LYDA com:
        - Preview Visual ao Vivo do Mapa da Rota Google Maps (ruas reais, trajeto azul, pinos #1..#N, km e minutos)
        - Passo a Passo do Trajeto + QR Code escaneável na própria tela + Preview do Roteiro PDF/WhatsApp
        - Geração do arquivo .PDF nativo (com o mapa embutido) e cópia do link direto Google Maps
        """
        import threading
        from PIL import ImageTk

        self._active_modal_open = True
        dlg = tk.Toplevel(self)
        dlg.title("Rota da Enfermeira — Preview da Rota Google Maps + Gerador de Roteiro PDF")
        dlg.geometry("1360x850")
        dlg.minsize(1140, 740)
        dlg.configure(bg="#F1F5F9")
        dlg.transient(self)
        dlg.grab_set()

        def _on_close_route(evt=None):
            if evt is None or evt.widget is dlg:
                self._active_modal_open = False

        dlg.bind("<Destroy>", _on_close_route)

        # Cabeçalho Limpo
        hdr = tk.Frame(dlg, bg="#0F172A", padx=18, pady=9)
        hdr.pack(fill="x")
        tk.Label(
            hdr,
            text="Rota da Enfermeira — Preview do Mapa Google Maps + Roteiro em PDF",
            bg="#0F172A",
            fg="#FFFFFF",
            font=("Segoe UI", 13, "bold"),
        ).pack(anchor="w")
        tk.Label(
            hdr,
            text="Visualize o mapa do trajeto (distância em km e tempo de carro), ordene as paradas saindo da Sede da LYDA e gere o .PDF + Link Google Maps",
            bg="#0F172A",
            fg="#38BDF8",
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w", pady=(1, 0))

        body = tk.Frame(dlg, bg="#F1F5F9", padx=12, pady=8)
        body.pack(fill="both", expand=True)

        # ---------------------------------------------------------------------
        # 1. CONFIGURAÇÃO DA PARTIDA (SEDE LYDA), ENFERMEIRA, DATA E OBSERVAÇÕES
        # ---------------------------------------------------------------------
        lf_origin = tk.LabelFrame(
            body,
            text=" 1. Partida (Sede da LYDA), Enfermeira Responsável, Data e Instruções da Rota ",
            bg="#FFFFFF",
            fg="#0F172A",
            font=("Segoe UI", 9, "bold"),
            padx=12,
            pady=6,
        )
        lf_origin.pack(fill="x", pady=(0, 6))
        for c_i in range(4):
            lf_origin.columnconfigure(c_i, weight=1)

        v_sede = tk.StringVar(value=self.db.lyda_hq_address)
        v_nurse = tk.StringVar(value=self.var_operador_atual.get() or "ENFERMEIRA LYDA")
        v_version = tk.StringVar(value="Atualização Semestral i-STAT (CLEW / JAMS)")
        v_date = tk.StringVar(value=datetime.now().strftime("%d/%m/%Y"))
        v_obs_rota = tk.StringVar(value="")
        v_return_hq = tk.BooleanVar(value=True)

        tk.Label(
            lf_origin,
            text="Ponto de Partida (Endereço da Sede da LYDA):",
            bg="#FFFFFF",
            fg="#1E3A8A",
            font=("Segoe UI", 8, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=4)

        sede_row = tk.Frame(lf_origin, bg="#FFFFFF")
        sede_row.grid(row=1, column=0, columnspan=2, sticky="ew", padx=4, pady=(0, 4))
        ent_sede = ttk.Entry(sede_row, textvariable=v_sede, font=("Segoe UI", 9, "bold"))
        ent_sede.pack(side="left", fill="x", expand=True)
        ent_sede.bind("<Return>", lambda _e: _refresh_stops_tree())

        def _save_sede_default():
            addr = v_sede.get().strip()
            if addr:
                self.db.lyda_hq_address = addr
                self.db.save_local_pc_config()
                _refresh_stops_tree()
                messagebox.showinfo("Sede da LYDA Salva", f"Endereço padrão da Sede da LYDA atualizado para:\n{addr}", parent=dlg)

        ttk.Button(
            sede_row,
            text="Salvar Sede",
            style="Secondary.TButton",
            cursor="hand2",
            command=_save_sede_default,
        ).pack(side="left", padx=(4, 0))

        tk.Label(
            lf_origin, text="Enfermeira(o) Responsável:", bg="#FFFFFF", fg="#0F172A", font=("Segoe UI", 8, "bold")
        ).grid(row=0, column=2, sticky="w", padx=4)
        cmb_nurse = ttk.Combobox(lf_origin, textvariable=v_nurse, values=self.db.operators)
        cmb_nurse.grid(row=1, column=2, sticky="ew", padx=4, pady=(0, 4))
        cmb_nurse.bind("<<ComboboxSelected>>", lambda _e: _update_text_preview_only())

        tk.Label(
            lf_origin, text="Data da Rota:", bg="#FFFFFF", fg="#0F172A", font=("Segoe UI", 8, "bold")
        ).grid(row=0, column=3, sticky="w", padx=4)
        ent_dt = ttk.Entry(lf_origin, textvariable=v_date)
        ent_dt.grid(row=1, column=3, sticky="ew", padx=4, pady=(0, 4))
        ent_dt.bind("<KeyRelease>", lambda _e: _update_text_preview_only())

        tk.Label(
            lf_origin,
            text="Pacote / Motivo da Visita (ex: CLEW Semestral):",
            bg="#FFFFFF",
            fg="#0F172A",
            font=("Segoe UI", 8, "bold"),
        ).grid(row=2, column=0, sticky="w", padx=4)
        ent_ver = ttk.Entry(lf_origin, textvariable=v_version)
        ent_ver.grid(row=3, column=0, sticky="ew", padx=4, pady=(0, 2))
        ent_ver.bind("<KeyRelease>", lambda _e: _update_text_preview_only())

        tk.Label(
            lf_origin,
            text="Observações / Instruções p/ Enfermeira (vai no PDF e WhatsApp):",
            bg="#FFFFFF",
            fg="#0F172A",
            font=("Segoe UI", 8, "bold"),
        ).grid(row=2, column=1, columnspan=2, sticky="w", padx=4)
        ent_obs_r = ttk.Entry(lf_origin, textvariable=v_obs_rota)
        ent_obs_r.grid(row=3, column=1, columnspan=2, sticky="ew", padx=4, pady=(0, 2))
        ent_obs_r.bind("<KeyRelease>", lambda _e: _update_text_preview_only())

        tk.Checkbutton(
            lf_origin,
            text="Retornar à Sede da LYDA no final (Rota Circular)",
            variable=v_return_hq,
            bg="#FFFFFF",
            fg="#0F172A",
            font=("Segoe UI", 8, "bold"),
            command=lambda: _refresh_stops_tree(),
        ).grid(row=3, column=3, sticky="w", padx=4)

        # ---------------------------------------------------------------------
        # ÁREA CENTRAL DIVIDIDA: ESQUERDA (PARADAS) | DIREITA (PREVIEW MAPA + ROTEIRO)
        # ---------------------------------------------------------------------
        split_main = tk.Frame(body, bg="#F1F5F9")
        split_main.pack(fill="both", expand=True, pady=(0, 6))
        split_main.columnconfigure(0, weight=55)
        split_main.columnconfigure(1, weight=45)
        split_main.rowconfigure(0, weight=1)

        # =====================================================================
        # COLUNA ESQUERDA: 2. PARADAS DA ROTA (TABELA + EDIÇÃO DE ENDEREÇO)
        # =====================================================================
        lf_stops = tk.LabelFrame(
            split_main,
            text=" 2. Paradas da Rota (Hospitais / Clínicas que a Enfermeira vai visitar) ",
            bg="#FFFFFF",
            fg="#0F172A",
            font=("Segoe UI", 9, "bold"),
            padx=10,
            pady=6,
        )
        lf_stops.grid(row=0, column=0, sticky="nsew", padx=(0, 5))

        # Linha 1 de Seleção: Carregar por Filtro ou Região
        filter_bar = tk.Frame(lf_stops, bg="#EFF6FF", padx=6, pady=4)
        filter_bar.pack(fill="x", pady=(0, 4))

        tk.Label(
            filter_bar,
            text="Carregar:",
            bg="#EFF6FF",
            fg="#1E3A8A",
            font=("Segoe UI", 8, "bold"),
        ).pack(side="left")

        all_cities = sorted({(it.get("CIDADE") or "").strip().upper() for it in self.db.items if (it.get("CIDADE") or "").strip()})
        scope_options = [
            "APARELHOS MARCADOS [ ✓ ] NA TABELA (OU TODOS EM CLIENTES)",
            "APARELHOS COM ATUALIZAÇÃO 6 MESES VENCIDA OU PENDENTE",
            "TODOS ATIVOS EM PORTO ALEGRE",
            "REGIÃO METROPOLITANA / VALE DOS SINOS (CANOAS, SÃO LEOPOLDO, CAMPO BOM, TRIUNFO)",
            "SERRA GAÚCHA (FLORES DA CUNHA, ANTÔNIO PRADO, VERANÓPOLIS)",
            "NORTE RS (PASSO FUNDO, TAPEJARA, SANANDUVA, ERECHIM)",
            "NOROESTE RS (CRUZ ALTA, SANTO ÂNGELO)",
            "SUL RS (RIO GRANDE, SANTA VITÓRIA DO PALMAR)",
            "SANTA CATARINA (CRICIÚMA, ARARANGUÁ)",
        ] + [f"CIDADE: {c}" for c in all_cities]

        v_route_scope = tk.StringVar(value=scope_options[0])
        cmb_scope = ttk.Combobox(filter_bar, textvariable=v_route_scope, values=scope_options, state="readonly", width=36)
        cmb_scope.pack(side="left", padx=4)

        stops_state: List[Dict[str, Any]] = []
        current_metrics_state: Dict[str, Any] = {}
        map_zoom_offset = 0
        map_pan_offset = [0, 0]
        map_layer_mode = ["m"]  # 'm' = Google Maps Ruas | 'y' = Google Maps Satélite + Ruas
        map_photo_ref: List[Any] = [None]
        qr_photo_ref: List[Any] = [None]
        map_hitboxes_state: List[Dict[str, Any]] = []
        render_seq_counter = [0]

        def _load_stops_from_scope(_evt=None):
            nonlocal stops_state, map_zoom_offset
            sc = v_route_scope.get()
            source_items: List[Dict[str, Any]] = []
            default_cyc = getattr(self.db, "default_update_cycle_months", 6)

            if sc.startswith("APARELHOS MARCADOS"):
                target_idxs = self._get_target_indices()
                if target_idxs:
                    raw_sel = [self.db.items[i] for i in target_idxs if 0 <= i < len(self.db.items)]
                else:
                    raw_sel = [it for it in self.db.items if classify_item_row_state(it) != "ESTOQUE"]
                external_sel = [it for it in raw_sel if classify_item_row_state(it) != "ESTOQUE"]
                source_items = external_sel if external_sel else raw_sel
            elif sc.startswith("APARELHOS COM ATUALIZAÇÃO 6 MESES"):
                source_items = [
                    it
                    for it in self.db.items
                    if classify_item_row_state(it) != "ESTOQUE"
                    and compute_update_cycle_info(it, default_cyc)["status_code"] in ("VENCIDA", "VENCENDO", "SEM_DATA")
                ]
            elif sc == "TODOS ATIVOS EM PORTO ALEGRE":
                source_items = [
                    it for it in self.db.items
                    if classify_item_row_state(it) != "ESTOQUE" and (it.get("CIDADE") or "").strip().upper() == "PORTO ALEGRE"
                ]
            elif sc.startswith("REGIÃO METROPOLITANA"):
                cids = {"CANOAS", "SÃO LEOPOLDO", "SAO LEOPOLDO", "NOVO HAMBURGO", "CAMPO BOM", "TRIUNFO", "SÃO SEBASTIÃO CAI"}
                source_items = [
                    it for it in self.db.items
                    if classify_item_row_state(it) != "ESTOQUE" and (it.get("CIDADE") or "").strip().upper() in cids
                ]
            elif sc.startswith("SERRA GAÚCHA"):
                cids = {"FLORES DA CUNHA", "ANTÔNIO PRADO", "ANTONIO PRADO", "VERANÓPOLIS", "VERANOPOLIS"}
                source_items = [
                    it for it in self.db.items
                    if classify_item_row_state(it) != "ESTOQUE" and (it.get("CIDADE") or "").strip().upper() in cids
                ]
            elif sc.startswith("NORTE RS"):
                cids = {"PASSO FUNDO", "TAPEJARA", "SANANDUVA", "ERECHIM"}
                source_items = [
                    it for it in self.db.items
                    if classify_item_row_state(it) != "ESTOQUE" and (it.get("CIDADE") or "").strip().upper() in cids
                ]
            elif sc.startswith("NOROESTE RS"):
                cids = {"CRUZ ALTA", "SANTO ÂNGELO", "SANTO ANGELO"}
                source_items = [
                    it for it in self.db.items
                    if classify_item_row_state(it) != "ESTOQUE" and (it.get("CIDADE") or "").strip().upper() in cids
                ]
            elif sc.startswith("SUL RS"):
                cids = {"RIO GRANDE", "SANTA VITÓRIA DO PALMAR", "SANTA VITORIA DO PALMAR"}
                source_items = [
                    it for it in self.db.items
                    if classify_item_row_state(it) != "ESTOQUE" and (it.get("CIDADE") or "").strip().upper() in cids
                ]
            elif sc.startswith("SANTA CATARINA"):
                source_items = [
                    it for it in self.db.items
                    if classify_item_row_state(it) != "ESTOQUE" and (it.get("UF") or "").strip().upper() == "SC"
                ]
            elif sc.startswith("CIDADE: "):
                target_cid = sc.replace("CIDADE: ", "").strip().upper()
                source_items = [
                    it for it in self.db.items
                    if classify_item_row_state(it) != "ESTOQUE" and (it.get("CIDADE") or "").strip().upper() == target_cid
                ]

            map_zoom_offset = 0
            map_pan_offset[0] = 0
            map_pan_offset[1] = 0
            stops_state = optimize_stops_order(
                group_items_into_route_stops(source_items),
                origin_address=v_sede.get().strip() or DEFAULT_LYDA_SEDE_ADDRESS,
            )
            _refresh_stops_tree()

        cmb_scope.bind("<<ComboboxSelected>>", _load_stops_from_scope)

        def _optimize_now():
            nonlocal stops_state
            stops_state = optimize_stops_order(
                stops_state,
                origin_address=v_sede.get().strip() or DEFAULT_LYDA_SEDE_ADDRESS,
            )
            _refresh_stops_tree()

        ttk.Button(
            filter_bar,
            text=" Otimizar Ordem (Mais Próximos 1º)",
            image=self.icons.get("refresh", "#FFFFFF"),
            compound="left",
            style="Primary.TButton",
            cursor="hand2",
            command=_optimize_now,
        ).pack(side="left", padx=3)

        def _clear_all_stops():
            nonlocal stops_state
            stops_state = []
            _refresh_stops_tree()

        ttk.Button(
            filter_bar,
            text=" Limpar",
            style="Secondary.TButton",
            cursor="hand2",
            command=_clear_all_stops,
        ).pack(side="left", padx=3)

        # Linha 2 de Seleção: Adicionar qualquer Hospital / Cliente individualmente + Subir/Descer/Remover
        add_cli_bar = tk.Frame(lf_stops, bg="#F8FAFC", padx=6, pady=4, highlightthickness=1, highlightbackground="#E2E8F0")
        add_cli_bar.pack(fill="x", pady=(0, 5))

        tk.Label(
            add_cli_bar,
            text="Adicionar Hospital:",
            bg="#F8FAFC",
            fg="#0F172A",
            font=("Segoe UI", 8, "bold"),
        ).pack(side="left")

        known_hospitals = [
            c for c in self.db.get_known_clients()
            if "SEM CLIENTE" not in c.upper() and "ESTOQUE" not in c.upper()
        ]
        v_add_hospital = tk.StringVar(value=known_hospitals[0] if known_hospitals else "")
        cmb_add_hosp = ttk.Combobox(add_cli_bar, textvariable=v_add_hospital, values=known_hospitals, width=28)
        cmb_add_hosp.pack(side="left", padx=4)

        def _add_single_hospital_to_route():
            nonlocal stops_state
            h_name = v_add_hospital.get().strip()
            if not h_name:
                return
            if any(st.get("CLIENTE", "").strip().upper() == h_name.upper() for st in stops_state):
                messagebox.showinfo("Já Incluído", f"O cliente '{h_name}' já está nas paradas da rota.", parent=dlg)
                return
            h_items = [it for _idx, it in self.db.get_client_items(h_name)]
            if h_items:
                new_stops = group_items_into_route_stops(h_items)
                stops_state.extend(new_stops)
            else:
                c_info = self.db.get_client_address_info(h_name)
                stops_state.append(
                    {
                        "CLIENTE": h_name,
                        "ENDERECO": c_info.get("ENDERECO", ""),
                        "CEP": c_info.get("CEP", ""),
                        "CIDADE": c_info.get("CIDADE", "PORTO ALEGRE"),
                        "UF": c_info.get("UF", "RS"),
                        "CONTATO_LOCAL": c_info.get("CONTATO_LOCAL", ""),
                        "SETORES": [],
                        "ITEMS": [],
                    }
                )
            _refresh_stops_tree(select_idx=len(stops_state) - 1)

        ttk.Button(
            add_cli_bar,
            text=" + Incluir",
            image=self.icons.get("plus", "#FFFFFF"),
            compound="left",
            style="Success.TButton",
            cursor="hand2",
            command=_add_single_hospital_to_route,
        ).pack(side="left", padx=2)

        def _move_stop(delta: int):
            sel = tree_stops.selection()
            if not sel:
                return
            idx = int(sel[0])
            new_idx = idx + delta
            if 0 <= new_idx < len(stops_state):
                stops_state[idx], stops_state[new_idx] = stops_state[new_idx], stops_state[idx]
                _refresh_stops_tree(select_idx=new_idx)

        def _remove_selected_stop():
            sel = tree_stops.selection()
            if not sel:
                return
            idx = int(sel[0])
            if 0 <= idx < len(stops_state):
                stops_state.pop(idx)
                _refresh_stops_tree()

        ttk.Button(
            add_cli_bar,
            text=" Remover",
            image=self.icons.get("trash", "#991B1B"),
            compound="left",
            style="Danger.TButton",
            cursor="hand2",
            command=_remove_selected_stop,
        ).pack(side="right", padx=2)

        ttk.Button(
            add_cli_bar,
            text="Descer",
            style="Secondary.TButton",
            cursor="hand2",
            command=lambda: _move_stop(1),
        ).pack(side="right", padx=2)

        ttk.Button(
            add_cli_bar,
            text="Subir",
            style="Secondary.TButton",
            cursor="hand2",
            command=lambda: _move_stop(-1),
        ).pack(side="right", padx=2)

        # Tabela de Paradas da Rota (com coluna TRECHO km / min)
        tree_box = tk.Frame(lf_stops, bg="#FFFFFF")
        tree_box.pack(fill="both", expand=True)

        cols_st = ("ORDEM", "TRECHO", "CLIENTE", "ENDERECO", "CIDADE_UF", "SETORES", "QTD", "SERIAIS")
        tree_stops = ttk.Treeview(tree_box, columns=cols_st, show="headings", height=8, selectmode="browse")
        for c_id, c_title, c_w in [
            ("ORDEM", "Parada", 50),
            ("TRECHO", "Trecho (km / min)", 112),
            ("CLIENTE", "Hospital / Clínica / Cliente", 180),
            ("ENDERECO", "Endereço Completo (Rua, Nº, Bairro)", 175),
            ("CIDADE_UF", "Cidade / UF", 95),
            ("SETORES", "Setor(es)", 80),
            ("QTD", "Qtd", 42),
            ("SERIAIS", "Seriais", 125),
        ]:
            tree_stops.heading(c_id, text=c_title)
            tree_stops.column(c_id, width=c_w, anchor="center" if c_id in ("ORDEM", "QTD", "TRECHO") else "w")

        vsb_st = ttk.Scrollbar(tree_box, orient="vertical", command=tree_stops.yview)
        hsb_st = ttk.Scrollbar(lf_stops, orient="horizontal", command=tree_stops.xview)
        tree_stops.configure(yscrollcommand=vsb_st.set, xscrollcommand=hsb_st.set)
        tree_stops.pack(side="left", fill="both", expand=True)
        vsb_st.pack(side="right", fill="y")
        hsb_st.pack(fill="x")

        # Editor Rápido de Endereço da Parada Selecionada
        edit_stop_bar = tk.LabelFrame(
            lf_stops,
            text=" Editar Endereço da Parada Selecionada (Salva no Hospital e Atualiza o Mapa) ",
            bg="#F8FAFC",
            fg="#0F172A",
            font=("Segoe UI", 8, "bold"),
            padx=8,
            pady=5,
        )
        edit_stop_bar.pack(fill="x", pady=(5, 0))

        v_st_end = tk.StringVar()
        v_st_cep = tk.StringVar()
        v_st_cid = tk.StringVar()
        v_st_uf = tk.StringVar()
        v_st_cont = tk.StringVar()

        edit_r1 = tk.Frame(edit_stop_bar, bg="#F8FAFC")
        edit_r1.pack(fill="x", pady=(0, 3))
        tk.Label(edit_r1, text="Endereço:", bg="#F8FAFC", fg="#0F172A", font=("Segoe UI", 8, "bold")).pack(side="left")
        ttk.Entry(edit_r1, textvariable=v_st_end, width=28).pack(side="left", padx=(4, 6), fill="x", expand=True)

        tk.Label(edit_r1, text="CEP:", bg="#F8FAFC", fg="#0F172A", font=("Segoe UI", 8, "bold")).pack(side="left")
        ttk.Entry(edit_r1, textvariable=v_st_cep, width=10).pack(side="left", padx=3)

        def _buscar_cep_stop():
            ok_c, data_c, msg_c = lookup_cep_viacep(v_st_cep.get())
            if ok_c:
                v_st_cep.set(data_c.get("CEP", v_st_cep.get()))
                if data_c.get("ENDERECO"):
                    v_st_end.set(data_c["ENDERECO"])
                if data_c.get("CIDADE"):
                    v_st_cid.set(data_c["CIDADE"])
                if data_c.get("UF"):
                    v_st_uf.set(data_c["UF"])
            else:
                messagebox.showwarning("CEP", msg_c, parent=dlg)

        ttk.Button(edit_r1, text="Buscar CEP", style="Secondary.TButton", cursor="hand2", command=_buscar_cep_stop).pack(side="left")

        edit_r2 = tk.Frame(edit_stop_bar, bg="#F8FAFC")
        edit_r2.pack(fill="x")
        tk.Label(edit_r2, text="Cidade/UF:", bg="#F8FAFC", fg="#0F172A", font=("Segoe UI", 8, "bold")).pack(side="left")
        ttk.Entry(edit_r2, textvariable=v_st_cid, width=14).pack(side="left", padx=3)
        ttk.Entry(edit_r2, textvariable=v_st_uf, width=3).pack(side="left", padx=(0, 8))

        tk.Label(edit_r2, text="Contato Local:", bg="#F8FAFC", fg="#0F172A", font=("Segoe UI", 8, "bold")).pack(side="left")
        ttk.Entry(edit_r2, textvariable=v_st_cont, width=16).pack(side="left", padx=3, fill="x", expand=True)

        def _save_selected_stop_address():
            sel = tree_stops.selection()
            if not sel:
                return
            idx = int(sel[0])
            if not (0 <= idx < len(stops_state)):
                return
            st = stops_state[idx]
            st["ENDERECO"] = v_st_end.get().strip()
            st["CEP"] = v_st_cep.get().strip()
            st["CIDADE"] = v_st_cid.get().strip().upper()
            st["UF"] = v_st_uf.get().strip().upper()
            st["CONTATO_LOCAL"] = v_st_cont.get().strip()

            self.db.propagate_client_address(
                st["CLIENTE"],
                st["ENDERECO"],
                st["CEP"],
                st["CIDADE"],
                st["UF"],
                st["CONTATO_LOCAL"],
            )
            self._populate_data_tree()
            _refresh_stops_tree(select_idx=idx)

        ttk.Button(
            edit_r2,
            text=" Salvar Endereço na Parada",
            image=self.icons.get("save", "#FFFFFF"),
            compound="left",
            style="Success.TButton",
            cursor="hand2",
            command=_save_selected_stop_address,
        ).pack(side="right", padx=(6, 0))

        # Barra do Link Direto do Google Maps
        maps_bar = tk.Frame(lf_stops, bg="#DBEAFE", padx=8, pady=5, highlightthickness=1, highlightbackground="#93C5FD")
        maps_bar.pack(fill="x", pady=(5, 0))

        tk.Label(
            maps_bar,
            text="Link Google Maps:",
            image=self.icons.get("route", "#1E3A8A"),
            compound="left",
            bg="#DBEAFE",
            fg="#1E3A8A",
            font=("Segoe UI", 8, "bold"),
        ).pack(side="left")

        v_live_maps_url = tk.StringVar()
        ent_maps_url = ttk.Entry(maps_bar, textvariable=v_live_maps_url, font=("Consolas", 8))
        ent_maps_url.pack(side="left", fill="x", expand=True, padx=6)

        def _copy_only_maps_url():
            url = v_live_maps_url.get().strip()
            if not url:
                return
            self.clipboard_clear()
            self.clipboard_append(url)
            messagebox.showinfo(
                "Link do Google Maps Copiado",
                f"O link direto da rota no Google Maps foi copiado!\n\n{url}",
                parent=dlg,
            )

        ttk.Button(
            maps_bar,
            text=" Copiar Link",
            image=self.icons.get("copy", "#0F172A"),
            compound="left",
            style="Secondary.TButton",
            cursor="hand2",
            command=_copy_only_maps_url,
        ).pack(side="right")

        lbl_route_stats = tk.Label(
            lf_stops,
            text="",
            bg="#FFFFFF",
            fg="#1E3A8A",
            font=("Segoe UI", 8, "bold"),
            anchor="w",
        )
        lbl_route_stats.pack(fill="x", pady=(4, 0))

        # =====================================================================
        # COLUNA DIREITA: 3. PREVIEW AO VIVO DA ROTA & MAPA GOOGLE MAPS
        # =====================================================================
        lf_preview = tk.LabelFrame(
            split_main,
            text=" 3. Preview da Rota & Trajeto Google Maps Ao Vivo ",
            bg="#FFFFFF",
            fg="#0F172A",
            font=("Segoe UI", 9, "bold"),
            padx=10,
            pady=6,
        )
        lf_preview.grid(row=0, column=1, sticky="nsew", padx=(5, 0))

        # Barra de Controles do Mapa e Resumo de Distância/Tempo
        prev_ctrl = tk.Frame(lf_preview, bg="#0F172A", padx=8, pady=5)
        prev_ctrl.pack(fill="x", pady=(0, 5))

        def _adjust_map_zoom(delta: int, reset: bool = False):
            nonlocal map_zoom_offset
            if reset:
                map_zoom_offset = 0
                map_pan_offset[0] = 0
                map_pan_offset[1] = 0
            else:
                if delta > 0:
                    map_pan_offset[0] = int(map_pan_offset[0] * 2)
                    map_pan_offset[1] = int(map_pan_offset[1] * 2)
                elif delta < 0:
                    map_pan_offset[0] = int(map_pan_offset[0] / 2)
                    map_pan_offset[1] = int(map_pan_offset[1] / 2)
                map_zoom_offset = max(-5, min(5, map_zoom_offset + delta))
            _trigger_live_map_render()

        def _toggle_map_layer():
            map_layer_mode[0] = "y" if map_layer_mode[0] == "m" else "m"
            btn_layer_toggle.configure(text="Mapa Ruas" if map_layer_mode[0] == "y" else "Satélite")
            _trigger_live_map_render()

        # Empacota os botões da direita PRIMEIRO para nunca serem espremidos pelo texto
        ttk.Button(
            prev_ctrl,
            text="Enquadrar",
            style="Secondary.TButton",
            cursor="hand2",
            command=lambda: _adjust_map_zoom(0, reset=True),
        ).pack(side="right", padx=(2, 0))

        btn_layer_toggle = ttk.Button(
            prev_ctrl,
            text="Satélite",
            style="Secondary.TButton",
            cursor="hand2",
            command=_toggle_map_layer,
        )
        btn_layer_toggle.pack(side="right", padx=2)

        ttk.Button(
            prev_ctrl,
            text="+ Zoom",
            style="Secondary.TButton",
            cursor="hand2",
            command=lambda: _adjust_map_zoom(1),
        ).pack(side="right", padx=2)

        ttk.Button(
            prev_ctrl,
            text="- Zoom",
            style="Secondary.TButton",
            cursor="hand2",
            command=lambda: _adjust_map_zoom(-1),
        ).pack(side="right", padx=2)

        lbl_preview_summary = tk.Label(
            prev_ctrl,
            text="Calculando trajeto...",
            bg="#0F172A",
            fg="#38BDF8",
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        )
        lbl_preview_summary.pack(side="left", fill="x", expand=True)

        # Notebook do Preview: Aba 1 = Mapa + Passo a Passo + QR Code | Aba 2 = Preview Folha PDF / WhatsApp
        nb_prev = ttk.Notebook(lf_preview)
        nb_prev.pack(fill="both", expand=True)

        tab_map_view = tk.Frame(nb_prev, bg="#FFFFFF", padx=4, pady=4)
        tab_doc_view = tk.Frame(nb_prev, bg="#FFFFFF", padx=4, pady=4)
        nb_prev.add(tab_map_view, text="  Google Maps da Rota (Interativo — Arraste & Zoom)  ")
        nb_prev.add(tab_doc_view, text="  Preview do Roteiro (PDF / WhatsApp)  ")

        # --- ABA 1: CANVAS DO GOOGLE MAPS + LINHA DO TEMPO DAS PARADAS + QR CODE ---
        map_canvas_frame = tk.Frame(tab_map_view, bg="#0F172A", highlightthickness=1, highlightbackground="#CBD5E1")
        map_canvas_frame.pack(fill="both", expand=True)

        canvas_map = tk.Canvas(
            map_canvas_frame,
            width=540,
            height=305,
            bg="#E5E3DF",
            highlightthickness=0,
            cursor="fleur",
        )
        canvas_map.pack(fill="both", expand=True)

        drag_state = {"start_x": 0, "start_y": 0, "orig_pan_x": 0, "orig_pan_y": 0, "moved": False}

        def _on_map_press(evt):
            drag_state["start_x"] = evt.x
            drag_state["start_y"] = evt.y
            drag_state["orig_pan_x"] = map_pan_offset[0]
            drag_state["orig_pan_y"] = map_pan_offset[1]
            drag_state["moved"] = False

        def _on_map_drag(evt):
            dx = evt.x - drag_state["start_x"]
            dy = evt.y - drag_state["start_y"]
            if abs(dx) > 4 or abs(dy) > 4:
                drag_state["moved"] = True
                # Move a imagem atual no canvas imediatamente p/ feedback visual fluido
                canvas_map.delete("all")
                if map_photo_ref[0] is not None:
                    canvas_map.create_image(dx, dy, anchor="nw", image=map_photo_ref[0])

        def _on_map_release(evt):
            dx = evt.x - drag_state["start_x"]
            dy = evt.y - drag_state["start_y"]
            if drag_state["moved"]:
                map_pan_offset[0] = drag_state["orig_pan_x"] + dx
                map_pan_offset[1] = drag_state["orig_pan_y"] + dy
                _trigger_live_map_render()
                return

            # Se foi um clique simples (sem arrastar), verifica se clicou sobre um pino #1, #2...
            for hb in map_hitboxes_state:
                if hb.get("type") == "stop":
                    idx_hb = hb.get("index", -1)
                    h_dx = evt.x - hb.get("x", -999)
                    h_dy = evt.y - hb.get("y", -999)
                    box = hb.get("box")
                    in_box = bool(box and box[0] <= evt.x <= box[2] and box[1] <= evt.y <= box[3])
                    if (h_dx * h_dx + h_dy * h_dy) <= (hb.get("r", 18) ** 2) or in_box:
                        if 0 <= idx_hb < len(stops_state):
                            tree_stops.selection_set(str(idx_hb))
                            tree_stops.see(str(idx_hb))
                            _on_stop_selected()
                            return

        def _on_map_wheel(evt):
            if getattr(evt, "delta", 0) > 0 or getattr(evt, "num", 0) == 4:
                _adjust_map_zoom(1)
            elif getattr(evt, "delta", 0) < 0 or getattr(evt, "num", 0) == 5:
                _adjust_map_zoom(-1)

        canvas_map.bind("<ButtonPress-1>", _on_map_press)
        canvas_map.bind("<B1-Motion>", _on_map_drag)
        canvas_map.bind("<ButtonRelease-1>", _on_map_release)
        canvas_map.bind("<Double-Button-1>", lambda _e: _open_google_maps_route())
        canvas_map.bind("<MouseWheel>", _on_map_wheel)
        canvas_map.bind("<Button-4>", _on_map_wheel)
        canvas_map.bind("<Button-5>", _on_map_wheel)

        # Painel inferior da Aba 1: QR Code ao Vivo (Empacotado à direita PRIMEIRO) + Passo a Passo (Esquerda)
        bottom_map_split = tk.Frame(tab_map_view, bg="#F8FAFC", padx=6, pady=6, highlightthickness=1, highlightbackground="#E2E8F0")
        bottom_map_split.pack(fill="x", pady=(5, 0))

        qr_side = tk.Frame(bottom_map_split, bg="#EFF6FF", padx=8, pady=5, highlightthickness=1, highlightbackground="#BFDBFE")
        qr_side.pack(side="right", fill="y", padx=(8, 0))

        tk.Label(
            qr_side,
            text="QR Code Google Maps",
            bg="#EFF6FF",
            fg="#1E3A8A",
            font=("Segoe UI", 8, "bold"),
        ).pack()

        lbl_qr_preview = tk.Label(qr_side, bg="#FFFFFF", bd=1, relief="solid")
        lbl_qr_preview.pack(pady=3)

        tk.Label(
            qr_side,
            text="Aponte o celular p/\nabrir a rota no Maps",
            bg="#EFF6FF",
            fg="#334155",
            font=("Segoe UI", 7),
            justify="center",
        ).pack()

        steps_col = tk.Frame(bottom_map_split, bg="#F8FAFC")
        steps_col.pack(side="left", fill="both", expand=True)

        tk.Label(
            steps_col,
            text="Passo a Passo do Trajeto no Google Maps (Clique 2x na parada p/ abrir no Maps):",
            bg="#F8FAFC",
            fg="#0F172A",
            font=("Segoe UI", 8, "bold"),
        ).pack(anchor="w", pady=(0, 3))

        txt_steps_timeline = tk.Text(
            steps_col,
            width=32,
            height=8,
            bg="#FFFFFF",
            fg="#0F172A",
            font=("Segoe UI", 8),
            wrap="word",
            relief="solid",
            bd=1,
            padx=8,
            pady=5,
        )
        txt_steps_timeline.pack(fill="both", expand=True)
        txt_steps_timeline.tag_configure("tag_sede", foreground="#991B1B", font=("Segoe UI", 8, "bold"))
        txt_steps_timeline.tag_configure("tag_leg", foreground="#1D4ED8", font=("Segoe UI", 8, "bold"))
        txt_steps_timeline.tag_configure("tag_stop", foreground="#0F172A", font=("Segoe UI", 9, "bold"))
        txt_steps_timeline.tag_configure("tag_sub", foreground="#475569", font=("Segoe UI", 8))

        # --- ABA 2: PREVIEW COMPLETO DO ROTEIRO (PDF / WHATSAPP) ---
        doc_top_bar = tk.Frame(tab_doc_view, bg="#EFF6FF", padx=8, pady=5)
        doc_top_bar.pack(fill="x", pady=(0, 4))
        tk.Label(
            doc_top_bar,
            text="Preview Ao Vivo do Roteiro Completo (Texto WhatsApp + Checklist do PDF):",
            bg="#EFF6FF",
            fg="#1E3A8A",
            font=("Segoe UI", 8, "bold"),
        ).pack(side="left")

        txt_doc_preview = tk.Text(
            tab_doc_view,
            bg="#FFFFFF",
            fg="#0F172A",
            font=("Consolas", 9),
            wrap="word",
            relief="solid",
            bd=1,
            padx=10,
            pady=8,
        )
        txt_doc_preview.pack(fill="both", expand=True)

        # ---------------------------------------------------------------------
        # FUNÇÕES DE ATUALIZAÇÃO DO PREVIEW AO VIVO (MAPA + QR CODE + TIMELINE)
        # ---------------------------------------------------------------------
        def _get_selected_stop_idx() -> Optional[int]:
            sel = tree_stops.selection()
            if not sel:
                return None
            try:
                idx = int(sel[0])
                return idx if 0 <= idx < len(stops_state) else None
            except Exception:
                return None

        def _update_qr_code_widget(maps_url: str):
            try:
                import qrcode

                qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=3, border=1)
                qr.add_data(maps_url)
                qr.make(fit=True)
                pil_qr = qr.make_image(fill_color="#0F172A", back_color="white").convert("RGB")
                pil_qr = pil_qr.resize((104, 104))
                tk_qr = ImageTk.PhotoImage(pil_qr)
                qr_photo_ref[0] = tk_qr
                lbl_qr_preview.configure(image=tk_qr)
            except Exception:
                pass

        def _populate_timeline_and_doc_preview(metrics: Dict[str, Any]):
            origin_str = v_sede.get().strip() or DEFAULT_LYDA_SEDE_ADDRESS
            ret_hq = bool(v_return_hq.get())
            legs = metrics.get("legs", [])
            tot_km = metrics.get("total_distance_km", 0.0)
            tot_min = metrics.get("total_duration_min", 0)
            total_eq = sum(len(s.get("ITEMS", [])) for s in stops_state)

            if tot_min >= 60:
                dur_str = f"{tot_min // 60}h {tot_min % 60:02d}min"
            else:
                dur_str = f"{tot_min} min"

            lbl_preview_summary.configure(
                text=f"Google Maps: {tot_km:.1f} km  |  ~{dur_str}  |  {len(stops_state)} Parada(s)"
            )
            lbl_route_stats.configure(
                text=f"Percurso Total: {tot_km:.1f} km (~{dur_str})  ->  {len(stops_state)} Parada(s)  ->  {total_eq} Aparelho(s) i-STAT."
            )

            # Atualiza a coluna TRECHO (km / min) de cada parada na Treeview
            for idx in range(len(stops_state)):
                iid_s = str(idx)
                if tree_stops.exists(iid_s) and idx < len(legs):
                    tree_stops.set(iid_s, "TRECHO", f"+{legs[idx]['label']}")

            # Preenche a Linha do Tempo Passo a Passo
            txt_steps_timeline.configure(state="normal")
            txt_steps_timeline.delete("1.0", "end")
            txt_steps_timeline.insert("end", f"[PARTIDA] SEDE DA LYDA\n", "tag_sede")
            txt_steps_timeline.insert("end", f"   {origin_str}\n", "tag_sub")

            for idx, st in enumerate(stops_state):
                if idx < len(legs):
                    txt_steps_timeline.insert(
                        "end",
                        f"   |  Trecho #{idx + 1}: +{legs[idx]['label']} de carro\n",
                        "tag_leg",
                    )
                items_st = st.get("ITEMS", [])
                seriais_s = ", ".join(f"{it.get('TIPO', '')[:3]}:{it.get('CODIGO', '')}" for it in items_st) or "Visita técnica"
                end_s = st.get("ENDERECO") or "(Endereço pelo nome do hospital)"
                cid_s = f"{st.get('CIDADE', '')}/{st.get('UF', '')}".strip("/")
                txt_steps_timeline.insert("end", f"[PARADA #{idx + 1}] {st.get('CLIENTE', '')} ({cid_s})\n", "tag_stop")
                txt_steps_timeline.insert("end", f"   End: {end_s}  |  Aparelhos ({len(items_st)}): {seriais_s}\n", "tag_sub")

            if ret_hq and len(legs) > len(stops_state):
                ret_leg = legs[-1]
                txt_steps_timeline.insert("end", f"   |  Retorno à Sede LYDA: +{ret_leg['label']}\n", "tag_leg")
                txt_steps_timeline.insert(
                    "end",
                    f"[CHEGADA] SEDE DA LYDA — Percurso Total: {tot_km:.1f} km (~{dur_str})\n",
                    "tag_sede",
                )
            txt_steps_timeline.configure(state="disabled")

            _update_text_preview_only(metrics)

        def _update_text_preview_only(metrics: Optional[Dict[str, Any]] = None):
            m_use = metrics or current_metrics_state
            wa_txt = build_whatsapp_route_summary(
                origin_address=v_sede.get().strip() or DEFAULT_LYDA_SEDE_ADDRESS,
                stops=stops_state,
                nurse_name=v_nurse.get().strip() or "ENFERMEIRA LYDA",
                update_version=v_version.get().strip(),
                route_date=v_date.get().strip(),
                return_to_origin=bool(v_return_hq.get()),
                route_metrics=m_use if m_use else None,
            )
            if v_obs_rota.get().strip():
                wa_txt = f"*Observações:* {v_obs_rota.get().strip()}\n\n" + wa_txt
            txt_doc_preview.configure(state="normal")
            txt_doc_preview.delete("1.0", "end")
            txt_doc_preview.insert("1.0", wa_txt)
            txt_doc_preview.configure(state="disabled")

        def _trigger_live_map_render():
            nonlocal current_metrics_state, map_hitboxes_state
            render_seq_counter[0] += 1
            my_seq = render_seq_counter[0]

            origin_addr = v_sede.get().strip() or DEFAULT_LYDA_SEDE_ADDRESS
            stops_snapshot = [dict(s) for s in stops_state]
            ret_hq = bool(v_return_hq.get())
            sel_idx = _get_selected_stop_idx()
            z_off = map_zoom_offset
            pan_snap = (map_pan_offset[0], map_pan_offset[1])
            lyr_snap = map_layer_mode[0]

            canvas_map.update_idletasks()
            cw = max(460, canvas_map.winfo_width())
            ch = max(265, canvas_map.winfo_height())

            # 1. Cálculo rápido local instantâneo (0ms) para atualizar números na hora
            fast_metrics = compute_route_metrics_and_geometry(
                origin_address=origin_addr,
                stops=stops_snapshot,
                return_to_origin=ret_hq,
                allow_network=False,
            )
            current_metrics_state = fast_metrics
            _populate_timeline_and_doc_preview(fast_metrics)

            # 2. Thread em segundo plano para buscar rota viária OSRM real e tiles do Google Maps sem travar a janela
            def _bg_worker():
                try:
                    full_metrics = compute_route_metrics_and_geometry(
                        origin_address=origin_addr,
                        stops=stops_snapshot,
                        return_to_origin=ret_hq,
                        allow_network=True,
                    )
                    pil_im, hbs, _m = render_route_map_pil_image(
                        workspace_dir=WORKSPACE_DIR,
                        origin_address=origin_addr,
                        stops=stops_snapshot,
                        return_to_origin=ret_hq,
                        width=cw,
                        height=ch,
                        zoom_offset=z_off,
                        pan_offset_px=pan_snap,
                        map_layer=lyr_snap,
                        selected_stop_idx=sel_idx,
                        route_metrics=full_metrics,
                        allow_network=True,
                    )
                except Exception:
                    return

                def _apply_on_ui():
                    nonlocal current_metrics_state, map_hitboxes_state
                    if my_seq != render_seq_counter[0] or not dlg.winfo_exists():
                        return
                    current_metrics_state = full_metrics
                    map_hitboxes_state = hbs
                    tk_im = ImageTk.PhotoImage(pil_im)
                    map_photo_ref[0] = tk_im
                    canvas_map.delete("all")
                    canvas_map.create_image(0, 0, anchor="nw", image=tk_im)
                    _populate_timeline_and_doc_preview(full_metrics)

                try:
                    if dlg.winfo_exists():
                        dlg.after(0, _apply_on_ui)
                except Exception:
                    pass

            threading.Thread(target=_bg_worker, daemon=True).start()

        def _on_stop_selected(_evt=None):
            sel = tree_stops.selection()
            if not sel:
                return
            idx = int(sel[0])
            if 0 <= idx < len(stops_state):
                st = stops_state[idx]
                v_st_end.set(st.get("ENDERECO", ""))
                v_st_cep.set(st.get("CEP", ""))
                v_st_cid.set(st.get("CIDADE", ""))
                v_st_uf.set(st.get("UF", ""))
                v_st_cont.set(st.get("CONTATO_LOCAL", ""))
                _trigger_live_map_render()

        tree_stops.bind("<<TreeviewSelect>>", _on_stop_selected)
        tree_stops.bind(
            "<Double-1>",
            lambda _e: webbrowser.open(build_single_stop_maps_url(stops_state[_get_selected_stop_idx()]))
            if _get_selected_stop_idx() is not None
            else None,
        )

        def _refresh_stops_tree(select_idx: int = 0):
            tree_stops.delete(*tree_stops.get_children())
            origin_addr = v_sede.get().strip() or DEFAULT_LYDA_SEDE_ADDRESS
            fast_m = compute_route_metrics_and_geometry(
                origin_address=origin_addr,
                stops=stops_state,
                return_to_origin=bool(v_return_hq.get()),
                allow_network=False,
            )
            legs_fast = fast_m.get("legs", [])

            for idx, st in enumerate(stops_state):
                items_st = st.get("ITEMS", [])
                seriais_str = ", ".join(f"{it.get('TIPO', '')[:3]}:{it.get('CODIGO', '')}" for it in items_st)
                setores_str = ", ".join(st.get("SETORES", [])) or "-"
                cid_uf_str = f"{st.get('CIDADE', '')} / {st.get('UF', '')}".strip(" /")
                end_str = st.get("ENDERECO") or "(Usará nome do Hospital + Cidade no Maps)"
                trecho_str = f"+{legs_fast[idx]['label']}" if idx < len(legs_fast) else "-"
                tree_stops.insert(
                    "",
                    "end",
                    iid=str(idx),
                    values=(
                        f"#{idx + 1}",
                        trecho_str,
                        st.get("CLIENTE", ""),
                        end_str,
                        cid_uf_str,
                        setores_str,
                        len(items_st),
                        seriais_str,
                    ),
                )

            live_url = build_google_maps_multi_stop_url(
                origin_address=origin_addr,
                stops=stops_state,
                return_to_origin=bool(v_return_hq.get()),
            )
            v_live_maps_url.set(live_url)
            _update_qr_code_widget(live_url)

            if stops_state and 0 <= select_idx < len(stops_state):
                tree_stops.selection_set(str(select_idx))
                st = stops_state[select_idx]
                v_st_end.set(st.get("ENDERECO", ""))
                v_st_cep.set(st.get("CEP", ""))
                v_st_cid.set(st.get("CIDADE", ""))
                v_st_uf.set(st.get("UF", ""))
                v_st_cont.set(st.get("CONTATO_LOCAL", ""))

            _trigger_live_map_render()

        if initial_client_name:
            h_items = [it for _idx, it in self.db.get_client_items(initial_client_name)]
            if h_items:
                stops_state = group_items_into_route_stops(h_items)
            else:
                c_info = self.db.get_client_address_info(initial_client_name)
                stops_state = [
                    {
                        "CLIENTE": initial_client_name,
                        "ENDERECO": c_info.get("ENDERECO", ""),
                        "CEP": c_info.get("CEP", ""),
                        "CIDADE": c_info.get("CIDADE", "PORTO ALEGRE"),
                        "UF": c_info.get("UF", "RS"),
                        "CONTATO_LOCAL": c_info.get("CONTATO_LOCAL", ""),
                        "SETORES": [],
                        "ITEMS": [],
                    }
                ]
            _refresh_stops_tree()
        else:
            _load_stops_from_scope()

        # Re-renderiza o mapa ao redimensionar a janela para ocupar todo o painel
        _resize_after_id: List[Optional[str]] = [None]

        def _on_canvas_configure(_evt=None):
            if _resize_after_id[0]:
                try:
                    dlg.after_cancel(_resize_after_id[0])
                except Exception:
                    pass
            _resize_after_id[0] = dlg.after(220, _trigger_live_map_render)

        canvas_map.bind("<Configure>", _on_canvas_configure)

        # ---------------------------------------------------------------------
        # 4. BOTÕES PRINCIPAIS: GERAR PDF + LINK GOOGLE MAPS P/ WHATSAPP
        # ---------------------------------------------------------------------
        footer = tk.Frame(body, bg="#F1F5F9")
        footer.pack(fill="x", side="bottom")

        def _open_google_maps_route():
            if not stops_state:
                messagebox.showwarning("Rota Vazia", "Adicione pelo menos 1 parada na rota.", parent=dlg)
                return
            self.db.lyda_hq_address = v_sede.get().strip() or DEFAULT_LYDA_SEDE_ADDRESS
            self.db.save_local_pc_config()
            url = build_google_maps_multi_stop_url(
                origin_address=self.db.lyda_hq_address,
                stops=stops_state,
                return_to_origin=bool(v_return_hq.get()),
            )
            webbrowser.open(url)

        def _generate_pdf_and_copy_whatsapp(choose_save_path: bool = False):
            if not stops_state:
                messagebox.showwarning("Rota Vazia", "Adicione pelo menos 1 parada na rota.", parent=dlg)
                return
            self.db.lyda_hq_address = v_sede.get().strip() or DEFAULT_LYDA_SEDE_ADDRESS
            self.db.save_local_pc_config()

            custom_pdf_path: Optional[str] = None
            if choose_save_path:
                date_slug = v_date.get().strip().replace("/", "-")
                custom_pdf_path = filedialog.asksaveasfilename(
                    parent=dlg,
                    title="Salvar Roteiro em PDF da Enfermeira",
                    defaultextension=".pdf",
                    initialfile=f"Roteiro_Enfermeira_LYDA_{date_slug}.pdf",
                    filetypes=[("Arquivo PDF (*.pdf)", "*.pdf")],
                )
                if not custom_pdf_path:
                    return

            pdf_file = generate_nurse_route_pdf(
                workspace_dir=WORKSPACE_DIR,
                origin_address=self.db.lyda_hq_address,
                stops=stops_state,
                nurse_name=v_nurse.get().strip() or "ENFERMEIRA LYDA",
                update_version=v_version.get().strip(),
                route_date=v_date.get().strip(),
                return_to_origin=bool(v_return_hq.get()),
                observacoes_rota=v_obs_rota.get().strip(),
                custom_output_path=custom_pdf_path,
                auto_open_pdf=True,
                reveal_in_folder=False,
                route_metrics=current_metrics_state if current_metrics_state else None,
            )

            # Também copia automaticamente o texto formatado com o Link da Rota no Google Maps para o WhatsApp!
            txt_wa = build_whatsapp_route_summary(
                origin_address=self.db.lyda_hq_address,
                stops=stops_state,
                nurse_name=v_nurse.get().strip() or "ENFERMEIRA LYDA",
                update_version=v_version.get().strip(),
                route_date=v_date.get().strip(),
                return_to_origin=bool(v_return_hq.get()),
                route_metrics=current_metrics_state if current_metrics_state else None,
            )
            if v_obs_rota.get().strip():
                txt_wa = f"*Observações:* {v_obs_rota.get().strip()}\n\n" + txt_wa
            self.clipboard_clear()
            self.clipboard_append(txt_wa)

            if messagebox.askyesno(
                "PDF com Mapa Gerado + Link Google Maps Copiado!",
                f"1. O arquivo PDF da rota (com Mapa Visual, QR Code e Checklist) foi gerado e aberto:\n{pdf_file}\n\n"
                f"2. O Roteiro + Link da Rota no Google Maps já está copiado (basta dar Cmd+V / Ctrl+V no WhatsApp da Enfermeira)!\n\n"
                f"Deseja abrir a pasta onde o arquivo PDF foi salvo para arrastá-lo direto para o WhatsApp?",
                parent=dlg,
            ):
                open_or_reveal_file(pdf_file, reveal_in_folder=True)

        def _copy_whatsapp_route():
            if not stops_state:
                messagebox.showwarning("Rota Vazia", "Adicione pelo menos 1 parada na rota.", parent=dlg)
                return
            txt = build_whatsapp_route_summary(
                origin_address=v_sede.get().strip() or DEFAULT_LYDA_SEDE_ADDRESS,
                stops=stops_state,
                nurse_name=v_nurse.get().strip() or "ENFERMEIRA LYDA",
                update_version=v_version.get().strip(),
                route_date=v_date.get().strip(),
                return_to_origin=bool(v_return_hq.get()),
                route_metrics=current_metrics_state if current_metrics_state else None,
            )
            if v_obs_rota.get().strip():
                txt = f"*Observações:* {v_obs_rota.get().strip()}\n\n" + txt
            self.clipboard_clear()
            self.clipboard_append(txt)
            messagebox.showinfo(
                "Roteiro + Link Google Maps Copiado",
                "O roteiro completo com distâncias, endereços, seriais e o Link da Rota no Google Maps foi copiado!\n\nBasta colar (Cmd+V / Ctrl+V) no WhatsApp da Enfermeira.",
                parent=dlg,
            )

        def _mark_all_route_items_updated():
            if not stops_state:
                return
            all_route_items = [it for st in stops_state for it in st.get("ITEMS", [])]
            if not all_route_items:
                messagebox.showinfo("Sem Aparelhos", "As paradas atuais não possuem aparelhos vinculados.", parent=dlg)
                return
            if not messagebox.askyesno(
                "Registrar Atualização Semestral Realizada",
                f"Deseja registrar no histórico e na ficha dos {len(all_route_items)} aparelhos desta rota que a atualização ({v_version.get()}) foi concluída em {v_date.get()} por {v_nurse.get()} (calculando automaticamente +6 meses para a próxima)?",
                parent=dlg,
            ):
                return
            date_clean = v_date.get().strip() or datetime.now().strftime("%d/%m/%Y")
            ver_clean = v_version.get().strip()
            nurse_op = v_nurse.get().strip() or "ENFERMEIRA LYDA"
            default_cyc = getattr(self.db, "default_update_cycle_months", 6)
            for it in all_route_items:
                it["ULTIMA_ATUALIZACAO"] = date_clean
                it["VERSAO_CLEW"] = ver_clean
                c_info = compute_update_cycle_info(it, default_cyc)
                it["PROXIMA_ATUALIZACAO"] = c_info["next_date_str"] or "EM DIA"
                it["_updated_epoch"] = time.time()
                self.db.add_history_log(
                    serial_barcode=it.get("CODIGO", ""),
                    tipo=it.get("TIPO", "ANALISADOR"),
                    acao="ATUALIZAÇÃO DE 6 MESES REALIZADA (ENFERMEIRA)",
                    detalhes=f"Atualização: {ver_clean} | Próx. Att: {it['PROXIMA_ATUALIZACAO']} | Local: {it.get('CLIENTE', '')}",
                    cliente=it.get("CLIENTE", ""),
                    modalidade=it.get("MODALIDADE", ""),
                    condicao=it.get("CONDICAO", "PERFEITO / FUNCIONANDO 100%"),
                    responsavel=nurse_op,
                )
            self.db.save()
            self._populate_data_tree()
            self._refresh_history_tree()
            messagebox.showinfo(
                "Atualização de 6 em 6 Meses Registrada",
                f"{len(all_route_items)} aparelho(s) marcados como atualizados em {date_clean}!\n"
                f"Próxima atualização calculada automaticamente (+{default_cyc} meses).",
                parent=dlg,
            )

        ttk.Button(
            footer,
            text=" Fechar",
            style="Secondary.TButton",
            cursor="hand2",
            command=dlg.destroy,
        ).pack(side="left")

        ttk.Button(
            footer,
            text=" Marcar Aparelhos Atualizados (6m)",
            image=self.icons.get("check", "#FFFFFF"),
            compound="left",
            style="Amber.TButton",
            cursor="hand2",
            command=_mark_all_route_items_updated,
        ).pack(side="left", padx=6)

        ttk.Button(
            footer,
            text=" Abrir Rota no Google Maps",
            image=self.icons.get("route", "#FFFFFF"),
            compound="left",
            style="Dark.TButton",
            cursor="hand2",
            command=_open_google_maps_route,
        ).pack(side="right", padx=(6, 0))

        ttk.Button(
            footer,
            text=" Copiar Roteiro + Link Maps",
            image=self.icons.get("copy", "#0F172A"),
            compound="left",
            style="Secondary.TButton",
            cursor="hand2",
            command=_copy_whatsapp_route,
        ).pack(side="right", padx=(6, 0))

        ttk.Button(
            footer,
            text=" Salvar PDF Como...",
            image=self.icons.get("download", "#FFFFFF"),
            compound="left",
            style="Primary.TButton",
            cursor="hand2",
            command=lambda: _generate_pdf_and_copy_whatsapp(choose_save_path=True),
        ).pack(side="right", padx=(6, 0))

        ttk.Button(
            footer,
            text=" Gerar PDF da Rota + Copiar Link Google Maps",
            image=self.icons.get("printer", "#FFFFFF"),
            compound="left",
            style="Success.TButton",
            cursor="hand2",
            command=lambda: _generate_pdf_and_copy_whatsapp(choose_save_path=False),
        ).pack(side="right")

    def _edit_selected_row(self):
        targets = self._get_target_indices()
        if not targets:
            messagebox.showinfo("Editar", "Marque ou selecione um aparelho na tabela para editar.")
            return
        self._open_item_dialog(edit_index=targets[0])

    def _delete_selected_rows(self):
        targets = self._get_target_indices()
        if not targets:
            messagebox.showinfo("Excluir", "Marque [ ✓ ] ou clique em pelo menos um aparelho na tabela para excluir.")
            return
        if messagebox.askyesno("Confirmar Exclusão", f"Deseja remover {len(targets)} aparelho(s) selecionado(s)?"):
            self.db.delete_indices(targets)
            self.checked_indices.clear()
            self._populate_data_tree()
            self._refresh_history_tree()

    def _on_import_excel(self):
        path = filedialog.askopenfilename(
            title="Selecionar Planilha Mapeamento i-STAT (.xlsx)",
            filetypes=[("Planilhas Excel (*.xlsx, *.xls)", "*.xlsx *.xls"), ("Todos os arquivos", "*.*")],
        )
        if not path:
            return
        try:
            count, msg = self.db.import_from_lyda_excel(path)
            if count > 0:
                self._populate_data_tree()
                self._refresh_history_tree()
                messagebox.showinfo("Importação Concluída", msg)
            else:
                cols, recs, _ = load_spreadsheet(path)
                if recs:
                    self.columns = cols
                    self.db.items = recs
                    self._refresh_column_selectors()
                    self._populate_data_tree()
                    messagebox.showinfo("Planilha Carregada", f"{len(recs)} linhas carregadas.")
                else:
                    messagebox.showwarning("Aviso", msg)
        except Exception as e:
            messagebox.showerror("Erro ao Importar Planilha", str(e))

    def _on_export_excel(self):
        path = filedialog.asksaveasfilename(
            title="Exportar Base i-STAT Atualizada para Excel",
            defaultextension=".xlsx",
            initialfile="Base_iSTAT_Lyda_Codigos_Barras.xlsx",
            filetypes=[("Planilha Excel (*.xlsx)", "*.xlsx")],
        )
        if not path:
            return
        try:
            saved = self.db.export_to_excel(path)
            messagebox.showinfo(
                "Exportado com Sucesso",
                f"Planilha completa com todos os códigos de barras e histórico salva em:\n{saved}",
            )
        except Exception as e:
            messagebox.showerror("Erro ao Exportar", str(e))

    def _on_open_backup_manager(self):
        """Janela de gestão de Backups Automáticos Diários e Restauração em 1 clique."""
        self._active_modal_open = True
        dlg = tk.Toplevel(self)
        dlg.title("Backups Automáticos & Restauração de Segurança — LYDA")
        dlg.geometry("680x440")
        dlg.configure(bg="#F8FAFC")
        dlg.transient(self)
        dlg.grab_set()
        dlg.bind("<Destroy>", lambda _e: setattr(self, "_active_modal_open", False))

        hdr = tk.Frame(dlg, bg="#0F172A", padx=16, pady=10)
        hdr.pack(fill="x")
        tk.Label(
            hdr,
            text="BACKUPS AUTOMÁTICOS DIÁRIOS DA BASE i-STAT",
            bg="#0F172A",
            fg="#FFFFFF",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w")
        tk.Label(
            hdr,
            text="O sistema salva cópias automáticas todos os dias e antes de importações/exclusões na pasta backups_automaticos/",
            bg="#0F172A",
            fg="#38BDF8",
            font=("Segoe UI", 8, "bold"),
        ).pack(anchor="w")

        body = tk.Frame(dlg, bg="#F8FAFC", padx=14, pady=10)
        body.pack(fill="both", expand=True)

        cols_b = ("DATA_HORA", "MOTIVO", "EQUIPAMENTOS", "HISTORICO", "ARQUIVO")
        tree_b = ttk.Treeview(body, columns=cols_b, show="headings", height=10)
        for c_id, c_title, c_w in [
            ("DATA_HORA", "Data / Hora", 140),
            ("MOTIVO", "Tipo / Motivo", 135),
            ("EQUIPAMENTOS", "Qtd. Aparelhos", 105),
            ("HISTORICO", "Reg. Histórico", 100),
            ("ARQUIVO", "Arquivo", 160),
        ]:
            tree_b.heading(c_id, text=c_title)
            tree_b.column(c_id, width=c_w, anchor="center" if c_id in ("EQUIPAMENTOS", "HISTORICO") else "w")

        vsb_b = ttk.Scrollbar(body, orient="vertical", command=tree_b.yview)
        tree_b.configure(yscrollcommand=vsb_b.set)
        tree_b.pack(side="left", fill="both", expand=True)
        vsb_b.pack(side="right", fill="y")

        backups_cache: List[Dict[str, Any]] = []

        def _reload_backups_list():
            nonlocal backups_cache
            tree_b.delete(*tree_b.get_children())
            backups_cache = self.db.list_backups()
            for idx, b in enumerate(backups_cache):
                tree_b.insert(
                    "",
                    "end",
                    iid=str(idx),
                    values=(
                        b.get("created_at", ""),
                        b.get("reason", ""),
                        b.get("items_count", 0),
                        b.get("history_count", 0),
                        b.get("filename", ""),
                    ),
                )
            if backups_cache:
                tree_b.selection_set("0")

        _reload_backups_list()

        footer = tk.Frame(dlg, bg="#F8FAFC", padx=14, pady=10)
        footer.pack(fill="x")

        def _create_manual_now():
            self.db.create_backup(reason="backup_manual_usuario")
            _reload_backups_list()
            messagebox.showinfo("Backup Criado", "Novo ponto de backup salvo com sucesso!", parent=dlg)

        def _restore_selected():
            sel = tree_b.selection()
            if not sel:
                messagebox.showwarning("Selecione", "Selecione um backup na lista para restaurar.", parent=dlg)
                return
            idx = int(sel[0])
            b_info = backups_cache[idx]
            if messagebox.askyesno(
                "Confirmar Restauração",
                f"Deseja restaurar a base para o backup de {b_info['created_at']} ({b_info['items_count']} aparelhos)?\n\n"
                "Um backup automático do estado atual será criado antes da restauração.",
                parent=dlg,
            ):
                ok, msg = self.db.restore_backup(b_info["filepath"])
                if ok:
                    self._populate_data_tree()
                    self._refresh_history_tree()
                    _reload_backups_list()
                    messagebox.showinfo("Restaurado", msg, parent=dlg)
                else:
                    messagebox.showerror("Erro", msg, parent=dlg)

        ttk.Button(
            footer,
            text=" Fechar",
            style="Secondary.TButton",
            cursor="hand2",
            command=dlg.destroy,
        ).pack(side="left")

        ttk.Button(
            footer,
            text=" Criar Backup Agora",
            image=self.icons.get("save", "#FFFFFF"),
            compound="left",
            style="Primary.TButton",
            cursor="hand2",
            command=_create_manual_now,
        ).pack(side="left", padx=8)

        ttk.Button(
            footer,
            text=" Restaurar Backup Selecionado",
            image=self.icons.get("refresh", "#FFFFFF"),
            compound="left",
            style="Success.TButton",
            cursor="hand2",
            command=_restore_selected,
        ).pack(side="right")

    # =========================================================================
    # MOTOR DE PREVIEW E IMPRESSÃO ZPL
    # =========================================================================
    def _refresh_printers_list(self):
        printers = list_system_printers()
        self.cmb_printers["values"] = printers
        if printers and not self.var_printer_name.get():
            self.var_printer_name.set(printers[0])

    def _refresh_column_selectors(self):
        col_options_bc = list(self.columns)
        col_options_extra = ["", "__TEXTO_FIXO__"] + list(self.columns)

        self.cmb_bc_col["values"] = col_options_bc
        if self.var_bc_col.get() not in col_options_bc and col_options_bc:
            self.var_bc_col.set("CODIGO" if "CODIGO" in col_options_bc else col_options_bc[0])

        for w in self.extra_rows_widgets:
            w["cmb"]["values"] = col_options_extra

    def _get_effective_records_to_print(self) -> List[Dict[str, Any]]:
        try:
            copies = max(1, int(self.copies_per_item_var.get()))
        except Exception:
            copies = 1
        out: List[Dict[str, Any]] = []
        for idx in self.selected_indices:
            if 0 <= idx < len(self.db.items):
                for _ in range(copies):
                    out.append(self.db.items[idx])
        return out

    def _apply_preset(self, big_w: float, big_h: float, cols: int, rows: int):
        self.var_big_w.set(big_w)
        self.var_big_h.set(big_h)
        self.var_cols.set(cols)
        self.var_rows.set(rows)
        self.var_auto_mini.set(True)
        self._on_toggle_auto_mini()
        self._update_preview()

    def _on_toggle_auto_mini(self):
        state = "disabled" if self.var_auto_mini.get() else "normal"
        self.spn_mini_w.configure(state=state)
        self.spn_mini_h.configure(state=state)
        if hasattr(self, "txt_zpl"):
            self._update_preview()

    def _sync_ui_to_config(self):
        if not hasattr(self, "var_show_header") or not hasattr(self, "var_darkness"):
            return
        cfg = self.layout_cfg
        try:
            cfg.big_width_mm = max(20.0, float(self.var_big_w.get()))
            cfg.big_height_mm = max(15.0, float(self.var_big_h.get()))
            cfg.margin_left_mm = max(0.0, float(self.var_margin_l.get()))
            cfg.margin_top_mm = max(0.0, float(self.var_margin_t.get()))
            cfg.dpi = int(self.var_dpi.get())

            cfg.cols = max(1, int(self.var_cols.get()))
            cfg.rows = max(1, int(self.var_rows.get()))
            cfg.gap_h_mm = max(0.0, float(self.var_gap_h.get()))
            cfg.gap_v_mm = max(0.0, float(self.var_gap_v.get()))
            cfg.auto_size_mini = bool(self.var_auto_mini.get())
            cfg.mini_width_mm = max(8.0, float(self.var_mini_w.get()))
            cfg.mini_height_mm = max(8.0, float(self.var_mini_h.get()))
            per_big_max = max(1, cfg.cols * cfg.rows)
            cfg.skip_slots = max(0, min(per_big_max - 1, int(self.var_skip_slots.get() or 0)))

            cfg.draw_border = bool(self.var_draw_border.get())
            cfg.border_thickness_dots = max(1, int(self.var_border_thick.get()))
            cfg.border_corner_rounding = max(0, min(8, int(self.var_corner_round.get())))
            cfg.draw_cut_marks = bool(self.var_cut_marks.get())
            cfg.inner_padding_mm = max(0.5, float(self.var_inner_pad.get()))

            cfg.show_logo = bool(self.var_show_logo.get())
            cfg.logo_height_dots = max(12, min(80, int(self.var_logo_h_dots.get())))
            cfg.show_header = bool(self.var_show_header.get())
            cfg.header_text = self.var_header_text.get()
            cfg.header_font_size = max(10, int(self.var_header_fs.get()))

            cfg.barcode_enabled = bool(self.var_bc_enabled.get())
            cfg.barcode_type = self.var_bc_type.get()
            cfg.barcode_column = self.var_bc_col.get()
            cfg.barcode_height_mm = max(3.0, float(self.var_bc_height.get()))
            cfg.barcode_module_width = max(1, min(4, int(self.var_bc_mod_w.get())))
            cfg.show_barcode_text = bool(self.var_bc_show_txt.get())

            cfg.darkness = max(0, min(30, int(self.var_darkness.get())))
            cfg.print_speed = max(2, min(6, int(self.var_speed.get())))

            extra_list: List[ExtraFieldConfig] = []
            for w in self.extra_rows_widgets:
                col_name = w["column"].get().strip()
                if col_name:
                    extra_list.append(
                        ExtraFieldConfig(
                            prefix=w["prefix"].get(),
                            column_name=col_name,
                            fixed_value=w["fixed"].get(),
                            font_size=max(10, int(w["font_size"].get())),
                            bold=bool(w["bold"].get()),
                        )
                    )
            cfg.extra_fields = extra_list
            self.var_show_location_on_label.set(any(ef.column_name == "CLIENTE" for ef in extra_list))
        except (ValueError, tk.TclError):
            pass

    def _update_preview(self):
        self._sync_ui_to_config()
        cfg = self.layout_cfg
        mw, mh = cfg.get_effective_mini_dimensions_mm()
        if cfg.auto_size_mini:
            self.var_mini_w.set(mw)
            self.var_mini_h.set(mh)

        per_big = cfg.items_per_big_label
        eff_records = self._get_effective_records_to_print()
        total_mini = len(eff_records)
        skip_n = max(0, min(per_big - 1, int(getattr(cfg, "skip_slots", 0) or 0)))
        effective_slots_needed = (total_mini + skip_n) if total_mini > 0 else 0
        total_big_pages = max(1, (effective_slots_needed + per_big - 1) // per_big) if total_mini > 0 else 1

        if self.current_preview_page >= total_big_pages:
            self.current_preview_page = max(0, total_big_pages - 1)

        self.lbl_calc_dimensions.configure(
            text=(
                f"Resultado: Cada Etiqueta Grande ({cfg.big_width_mm:.0f}x{cfg.big_height_mm:.0f} mm) terá "
                f"{per_big} mini-etiquetas ({cfg.cols} col x {cfg.rows} lin) de {mw:.1f} x {mh:.1f} mm cada."
            )
        )
        self.lbl_selection_summary.configure(
            text=f"{total_mini} mini-etiqueta(s) selecionada(s)   ->   Gastará {total_big_pages if total_mini else 0} etiqueta(s) grande(s) na Zebra ZD230."
        )
        self.lbl_page_indicator.configure(text=f"Etiqueta Grande {self.current_preview_page + 1} / {total_big_pages}")
        self.lbl_preview_subtitle.configure(
            text=f"Papel: {cfg.big_width_mm:.0f}x{cfg.big_height_mm:.0f}mm | Grade: {cfg.cols}x{cfg.rows} ({per_big} mini-etiquetas de {mw:.1f}x{mh:.1f}mm)"
        )
        self.btn_print_all.configure(
            text=f" IMPRIMIR {total_mini} MINI-ETIQUETAS ({total_big_pages if total_mini else 0} ETIQUETA(S) GRANDE(S))"
        )

        gen = ZPLGenerator(cfg)
        full_zpl = gen.generate_full_zpl(eff_records)
        self.txt_zpl.delete("1.0", "end")
        self.txt_zpl.insert("1.0", full_zpl if full_zpl else "^FX Nenhum equipamento selecionado na Aba 1 ^FS")

        self._draw_canvas_preview()

    def _prev_preview_page(self):
        if self.current_preview_page > 0:
            self.current_preview_page -= 1
            self._update_preview()

    def _next_preview_page(self):
        per_big = self.layout_cfg.items_per_big_label
        eff_records = self._get_effective_records_to_print()
        skip_n = max(0, min(per_big - 1, int(getattr(self.layout_cfg, "skip_slots", 0) or 0)))
        total_slots = (len(eff_records) + skip_n) if eff_records else 0
        total_pages = max(1, (total_slots + per_big - 1) // per_big)
        if self.current_preview_page + 1 < total_pages:
            self.current_preview_page += 1
            self._update_preview()

    def _draw_canvas_preview(self):
        c = self.canvas_preview
        c.delete("all")
        cw = c.winfo_width()
        ch = c.winfo_height()
        if cw < 50 or ch < 50:
            return

        cfg = self.layout_cfg
        big_w = max(10.0, cfg.big_width_mm)
        big_h = max(10.0, cfg.big_height_mm)

        pad_px = 22
        scale = min((cw - 2 * pad_px) / big_w, (ch - 2 * pad_px) / big_h)
        scale = max(1.0, scale)

        paper_w_px = big_w * scale
        paper_h_px = big_h * scale
        ox = (cw - paper_w_px) / 2
        oy = (ch - paper_h_px) / 2

        c.create_rectangle(ox + 4, oy + 4, ox + paper_w_px + 4, oy + paper_h_px + 4, fill="#94A3B8", outline="")
        c.create_rectangle(ox, oy, ox + paper_w_px, oy + paper_h_px, fill="#FFFFFF", outline="#475569", width=2)

        mw_mm, mh_mm = cfg.get_effective_mini_dimensions_mm()
        per_page = cfg.items_per_big_label
        eff_records = self._get_effective_records_to_print()
        skip_n = max(0, min(per_page - 1, int(getattr(cfg, "skip_slots", 0) or 0)))
        padded_records: List[Optional[Dict[str, Any]]] = ([None] * skip_n) + list(eff_records) if eff_records else []
        start_idx = self.current_preview_page * per_page
        page_records = padded_records[start_idx : start_idx + per_page]

        if cfg.draw_cut_marks and (cfg.cols > 1 or cfg.rows > 1):
            for col_i in range(1, cfg.cols):
                cut_x_mm = cfg.margin_left_mm + col_i * mw_mm + (col_i - 1) * cfg.gap_h_mm + (cfg.gap_h_mm / 2)
                cx = ox + cut_x_mm * scale
                c.create_line(cx, oy, cx, oy + 8, fill="#64748B", width=1)
                c.create_line(cx, oy + paper_h_px - 8, cx, oy + paper_h_px, fill="#64748B", width=1)
            for row_i in range(1, cfg.rows):
                cut_y_mm = cfg.margin_top_mm + row_i * mh_mm + (row_i - 1) * cfg.gap_v_mm + (cfg.gap_v_mm / 2)
                cy = oy + cut_y_mm * scale
                c.create_line(ox, cy, ox + 8, cy, fill="#64748B", width=1)
                c.create_line(ox + paper_w_px - 8, cy, ox + paper_w_px, cy, fill="#64748B", width=1)

        for slot_idx in range(per_page):
            r_idx = slot_idx // cfg.cols
            c_idx = slot_idx % cfg.cols

            x_mm = cfg.margin_left_mm + c_idx * (mw_mm + cfg.gap_h_mm)
            y_mm = cfg.margin_top_mm + r_idx * (mh_mm + cfg.gap_v_mm)

            x1 = ox + x_mm * scale
            y1 = oy + y_mm * scale
            x2 = x1 + mw_mm * scale
            y2 = y1 + mh_mm * scale

            if slot_idx >= len(page_records):
                c.create_rectangle(x1, y1, x2, y2, outline="#CBD5E1", dash=(3, 3))
                c.create_text((x1 + x2) / 2, (y1 + y2) / 2, text="(Vazio)", fill="#CBD5E1", font=("Segoe UI", 7))
                continue

            rec = page_records[slot_idx]
            if rec is None:
                c.create_rectangle(x1, y1, x2, y2, fill="#F1F5F9", outline="#94A3B8", dash=(3, 3))
                c.create_text(
                    (x1 + x2) / 2,
                    (y1 + y2) / 2,
                    text=f"(Posição #{slot_idx+1} Pulada / Já Destacada)",
                    fill="#64748B",
                    font=("Segoe UI", 7, "bold"),
                )
                continue

            if cfg.draw_border:
                b_width = max(1, int(round(cfg.border_thickness_dots * 0.6)))
                c.create_rectangle(x1, y1, x2, y2, outline="#0F172A", width=b_width)
            else:
                c.create_rectangle(x1, y1, x2, y2, outline="#E2E8F0", dash=(2, 2))

            pad_in = cfg.inner_padding_mm * scale
            cur_y = y1 + pad_in
            max_y = y2 - pad_in
            in_x1 = x1 + pad_in
            in_x2 = x2 - pad_in
            center_x = (in_x1 + in_x2) / 2

            header_drawn = False
            if cfg.show_logo:
                logo_h_mm = cfg.logo_height_dots / cfg.dots_per_mm
                logo_h_px = max(8, int(round(logo_h_mm * scale)))
                tk_logo, lw_px, lh_px = get_tk_logo_photo(cfg.logo_path or get_default_logo_path(), logo_h_px)
                if tk_logo and cur_y + lh_px <= max_y:
                    if cfg.show_header and cfg.header_text.strip():
                        c.create_image(in_x1 + 2, cur_y, image=tk_logo, anchor="nw")
                        fs_px = max(6, int((cfg.header_font_size / cfg.dots_per_mm) * scale * 0.72))
                        c.create_text(
                            in_x2 - 2,
                            cur_y + lh_px / 2,
                            text=cfg.header_text.strip(),
                            anchor="e",
                            fill="#0F172A",
                            font=("Segoe UI", fs_px, "bold"),
                        )
                    else:
                        c.create_image(center_x, cur_y, image=tk_logo, anchor="n")
                    cur_y += lh_px + 2
                    header_drawn = True
            elif cfg.show_header and cfg.header_text.strip():
                fs_px = max(6, int((cfg.header_font_size / cfg.dots_per_mm) * scale * 0.72))
                if cur_y + fs_px <= max_y:
                    c.create_text(
                        center_x,
                        cur_y,
                        text=cfg.header_text.strip(),
                        anchor="n",
                        fill="#0F172A",
                        font=("Segoe UI", fs_px, "bold"),
                        width=max(20, int(in_x2 - in_x1)),
                    )
                    cur_y += fs_px + 3
                    header_drawn = True

            if header_drawn and cfg.draw_border and cur_y + 2 <= max_y:
                c.create_line(in_x1, cur_y, in_x2, cur_y, fill="#0F172A", width=1)
                cur_y += 3

            for ef in cfg.extra_fields:
                if not ef.column_name:
                    continue
                val = ef.fixed_value if ef.column_name == "__TEXTO_FIXO__" else rec.get(ef.column_name, "")
                line_str = f"{ef.prefix}{val}".strip()
                if not line_str:
                    continue
                fs_px = max(6, int((ef.font_size / cfg.dots_per_mm) * scale * 0.7))
                if cur_y + fs_px > max_y:
                    break
                weight = "bold" if ef.bold else "normal"
                max_chars = max(6, int((in_x2 - in_x1) / max(4, fs_px * 0.58)))
                disp_str = line_str if len(line_str) <= max_chars else line_str[: max_chars - 1] + "..."
                c.create_text(in_x1 + 1, cur_y, text=disp_str, anchor="nw", fill="#0F172A", font=("Segoe UI", fs_px, weight))
                cur_y += fs_px + 2

            if cfg.barcode_enabled and cfg.barcode_column:
                code_val = sanitize_barcode_value(rec.get(cfg.barcode_column, ""))
                if code_val and cur_y + 10 <= max_y:
                    txt_h = max(6, int(1.9 * scale)) if cfg.show_barcode_text else 0
                    avail_h = (max_y - cur_y) - txt_h
                    bc_h_px = min(cfg.barcode_height_mm * scale, avail_h)
                    if bc_h_px >= 6:
                        total_bc_block = bc_h_px + txt_h
                        rem_space = max_y - cur_y
                        if rem_space > total_bc_block + 2:
                            cur_y += (rem_space - total_bc_block) / 2
                        if cfg.barcode_type == "QRCODE":
                            qr_size = min(bc_h_px, in_x2 - in_x1)
                            qx1 = center_x - qr_size / 2
                            c.create_rectangle(qx1, cur_y, qx1 + qr_size, cur_y + qr_size, outline="#0F172A", width=1)
                            cell = max(2, int(qr_size / 5))
                            for qr_r in range(5):
                                for qr_c in range(5):
                                    if (qr_r + qr_c + len(code_val)) % 2 == 0:
                                        c.create_rectangle(
                                            qx1 + qr_c * cell,
                                            cur_y + qr_r * cell,
                                            qx1 + (qr_c + 1) * cell,
                                            cur_y + (qr_r + 1) * cell,
                                            fill="#0F172A",
                                            outline="",
                                        )
                            cur_y += qr_size + 1
                        else:
                            bc_w = min(in_x2 - in_x1 - 4, max(24, len(code_val) * 5.5 * (cfg.barcode_module_width * 0.6) * (scale / 3.0)))
                            bx1 = center_x - bc_w / 2
                            bx2 = center_x + bc_w / 2
                            num_bars = max(14, min(42, len(code_val) * 3))
                            step = (bx2 - bx1) / num_bars
                            for b_i in range(num_bars):
                                if (b_i * 3 + ord(code_val[b_i % len(code_val)])) % 3 != 0:
                                    lx = bx1 + b_i * step
                                    bar_thick = max(1, int(step * 0.65))
                                    c.create_line(lx, cur_y, lx, cur_y + bc_h_px, fill="#000000", width=bar_thick)
                            cur_y += bc_h_px + 1

                        if cfg.show_barcode_text and cur_y + 6 <= y2:
                            c.create_text(
                                center_x,
                                cur_y,
                                text=code_val,
                                anchor="n",
                                fill="#0F172A",
                                font=("Consolas", max(6, int(1.8 * scale)), "bold"),
                            )

    def _execute_print(self, only_current_page: bool = False):
        self._sync_ui_to_config()
        eff_records = self._get_effective_records_to_print()
        if not eff_records:
            messagebox.showwarning("Nenhum Item Selecionado", "Selecione pelo menos um equipamento na Aba 1 para imprimir.")
            return

        gen = ZPLGenerator(self.layout_cfg)
        pages = gen.generate_zpl_pages(eff_records)
        if not pages:
            return

        if only_current_page:
            idx = min(self.current_preview_page, len(pages) - 1)
            zpl_to_send = pages[idx]
            desc = f"1 Etiqueta Grande de Teste (Página {idx + 1})"
        else:
            zpl_to_send = "\n\n".join(pages)
            desc = f"{len(eff_records)} mini-etiquetas em {len(pages)} etiqueta(s) grande(s)"

        mode = self.var_conn_mode.get()
        printer_name = self.var_printer_name.get().strip()
        ip_addr = self.var_ip.get().strip()
        port = int(self.var_port.get() or 9100)

        ok, msg = dispatch_zpl_print(
            mode=mode,
            zpl_data=zpl_to_send,
            printer_name=printer_name,
            ip_address=ip_addr,
            port=port,
        )
        if ok:
            self._save_config_to_disk(silent=True)
            self.db.add_history_log("IMPRESSORA", "ZEBRA ZD230", "IMPRESSÃO ZPL", desc)
            self._refresh_history_tree()
            messagebox.showinfo("Impressão Enviada para Zebra ZD230", f"{desc}\n\n{msg}")
        else:
            messagebox.showerror("Erro ao Enviar para Impressora", msg)

    def _copy_zpl_to_clipboard(self):
        zpl = self.txt_zpl.get("1.0", "end").strip()
        self.clipboard_clear()
        self.clipboard_append(zpl)
        messagebox.showinfo("Copiado", "Código ZPL II copiado para a área de transferência.")

    def _save_zpl_file(self):
        zpl = self.txt_zpl.get("1.0", "end").strip()
        path = filedialog.asksaveasfilename(
            title="Salvar Arquivo de Etiquetas Zebra (.prn / .zpl)",
            defaultextension=".prn",
            initialfile="etiquetas_istat_lyda_zd230.prn",
            filetypes=[
                ("Arquivo de Impressão Zebra (.prn)", "*.prn"),
                ("Arquivo Zebra ZPL (.zpl)", "*.zpl"),
                ("Texto (.txt)", "*.txt"),
            ],
        )
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(zpl)
            messagebox.showinfo("Salvo", f"Arquivo de etiquetas Zebra (.PRN) salvo com sucesso em:\n{path}")

    def _on_choose_logo_file(self):
        path = filedialog.askopenfilename(
            title="Selecionar Imagem da Logo (PNG / JPG)",
            filetypes=[("Imagens (*.png, *.jpg, *.jpeg, *.bmp)", "*.png *.jpg *.jpeg *.bmp"), ("Todos os arquivos", "*.*")],
        )
        if path:
            self.layout_cfg.logo_path = path
            self.var_show_logo.set(True)
            self._update_preview()


if __name__ == "__main__":
    app = LydaZebraApp()
    app.mainloop()
