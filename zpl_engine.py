"""
Motor de geração de código ZPL II nativo para Zebra ZD230 (203 DPI / 300 DPI).
Suporta múltiplas mini-etiquetas (grade N colunas x M linhas) dentro de uma etiqueta grande,
com contorno de corte, código de barras Code 128 / QR Code, cabeçalho fixo e campos dinâmicos da planilha.
"""

import unicodedata
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from logo_zpl import image_to_zpl_gfa, get_default_logo_path


def sanitize_zpl_text(text: Any) -> str:
    """
    Normaliza e limpa texto para envio em ZPL (^CI28 UTF-8 ou ASCII seguro).
    Remove quebras de linha e escapa caracteres especiais do ZPL.
    """
    if text is None:
        return ""
    s = str(text).strip()
    if s.lower() == "nan":
        return ""
    # Substituir caracteres de controle ZPL (~ e ^)
    s = s.replace("^", "-").replace("~", "-")
    return s


def sanitize_barcode_value(text: Any) -> str:
    """
    Limpa o valor para Code 128 (apenas ASCII imprimível sem acentos para leitura 100% confiável no leitor).
    """
    s = sanitize_zpl_text(text)
    # Remove acentos para código de barras
    nfkd = unicodedata.normalize("NFKD", s)
    ascii_str = "".join([c for c in nfkd if not unicodedata.combining(c)])
    # Mantém caracteres ASCII imprimíveis (32 a 126)
    clean = "".join(c for c in ascii_str if 32 <= ord(c) <= 126)
    return clean.strip()


@dataclass
class ExtraFieldConfig:
    """Representa uma linha extra de texto configurada pelo usuário para sair na mini-etiqueta."""
    prefix: str = ""          # Ex: "PAT: " ou "SETOR: "
    column_name: str = ""     # Nome da coluna na planilha, ou "__TEXTO_FIXO__"
    fixed_value: str = ""     # Usado caso column_name == "__TEXTO_FIXO__"
    font_size: int = 18       # Altura da fonte em dots (203dpi: 18 dots ~ 2.2mm)
    bold: bool = False


@dataclass
class LabelLayoutConfig:
    """Configuração completa do papel grande e da grade de mini-etiquetas para Zebra ZD230."""
    # Impressora
    dpi: int = 203                        # Zebra ZD230 padrão = 203 DPI (8 dots/mm)
    darkness: int = 18                    # ^MD / ~SD (0 a 30)
    print_speed: int = 4                  # ^PR (2 a 6 pol/seg)

    # Papel Grande (em milímetros)
    big_width_mm: float = 100.0           # Largura total da etiqueta grande
    big_height_mm: float = 150.0          # Altura total da etiqueta grande
    margin_left_mm: float = 3.0           # Margem esquerda inicial (mm)
    margin_top_mm: float = 3.0            # Margem superior inicial (mm)

    # Grade de Mini-Etiquetas
    cols: int = 2                         # Quantidade de colunas por etiqueta grande
    rows: int = 5                         # Quantidade de linhas por etiqueta grande
    gap_h_mm: float = 2.0                 # Espaço horizontal entre mini-etiquetas (mm)
    gap_v_mm: float = 2.0                 # Espaço vertical entre mini-etiquetas (mm)
    auto_size_mini: bool = True           # Calcular tamanho da mini-etiqueta automaticamente pelo papel grande
    mini_width_mm: float = 46.0           # Largura manual da mini-etiqueta (se auto_size_mini=False)
    mini_height_mm: float = 27.0          # Altura manual da mini-etiqueta (se auto_size_mini=False)
    skip_slots: int = 0                   # Quantas posições iniciais pular na 1ª etiqueta grande (reaproveitar folha)

    # Contorno para corte (tesoura / estilete)
    draw_border: bool = True              # Desenhar borda ao redor de cada mini-etiqueta
    border_thickness_dots: int = 2        # Espessura da linha em dots
    border_corner_rounding: int = 0       # 0 (reto) a 8 (arredondado)
    draw_cut_marks: bool = True           # Linha tracejada / marcas de corte entre etiquetas
    inner_padding_mm: float = 2.0         # Espaçamento interno entre a borda e o texto/código

    # Cabeçalho fixo / Mini-Logo Lyda
    show_logo: bool = True                # Imprimir a mini-logo gráfica da Lyda (^GFA) no topo
    logo_path: str = ""                   # Caminho da imagem da logo (vazio = lyda_logo_cropped.png padrão)
    logo_height_dots: int = 24            # Altura da mini-logo em dots (24 dots ~ 3mm em 203 DPI)
    show_header: bool = False             # Texto adicional opcional ao lado/abaixo se não usar logo
    header_text: str = "i-STAT"
    header_font_size: int = 18

    # Código de Barras / QR Code
    barcode_enabled: bool = True
    barcode_type: str = "CODE128"         # "CODE128" ou "QRCODE"
    barcode_column: str = "CODIGO"        # Coluna da planilha que alimenta o código de barras
    barcode_height_mm: float = 10.0       # Altura da barra (mm) - maior para leitura rápida no leitor USB
    barcode_module_width: int = 2         # Largura do módulo em dots (1=fino/denso, 2=padrão, 3=largo)
    show_barcode_text: bool = True        # Mostrar o código legível logo abaixo das barras

    # Campos de Texto Dinâmicos (vindos da planilha ou fixos)
    extra_fields: List[ExtraFieldConfig] = field(default_factory=list)

    @property
    def dots_per_mm(self) -> float:
        return self.dpi / 25.4

    def mm_to_dots(self, mm: float) -> int:
        return max(1, int(round(mm * self.dots_per_mm)))

    def get_effective_mini_dimensions_mm(self) -> tuple[float, float]:
        """Retorna (largura_mm, altura_mm) real de cada mini-etiqueta."""
        if self.auto_size_mini:
            usable_w = self.big_width_mm - (2 * self.margin_left_mm) - (max(0, self.cols - 1) * self.gap_h_mm)
            usable_h = self.big_height_mm - (2 * self.margin_top_mm) - (max(0, self.rows - 1) * self.gap_v_mm)
            w = max(10.0, round(usable_w / max(1, self.cols), 1))
            h = max(8.0, round(usable_h / max(1, self.rows), 1))
            return w, h
        return self.mini_width_mm, self.mini_height_mm

    @property
    def items_per_big_label(self) -> int:
        return max(1, self.cols * self.rows)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dpi": self.dpi,
            "darkness": self.darkness,
            "print_speed": self.print_speed,
            "big_width_mm": self.big_width_mm,
            "big_height_mm": self.big_height_mm,
            "margin_left_mm": self.margin_left_mm,
            "margin_top_mm": self.margin_top_mm,
            "cols": self.cols,
            "rows": self.rows,
            "gap_h_mm": self.gap_h_mm,
            "gap_v_mm": self.gap_v_mm,
            "auto_size_mini": self.auto_size_mini,
            "mini_width_mm": self.mini_width_mm,
            "mini_height_mm": self.mini_height_mm,
            "skip_slots": self.skip_slots,
            "draw_border": self.draw_border,
            "border_thickness_dots": self.border_thickness_dots,
            "border_corner_rounding": self.border_corner_rounding,
            "draw_cut_marks": self.draw_cut_marks,
            "inner_padding_mm": self.inner_padding_mm,
            "show_logo": self.show_logo,
            "logo_path": self.logo_path,
            "logo_height_dots": self.logo_height_dots,
            "show_header": self.show_header,
            "header_text": self.header_text,
            "header_font_size": self.header_font_size,
            "barcode_enabled": self.barcode_enabled,
            "barcode_type": self.barcode_type,
            "barcode_column": self.barcode_column,
            "barcode_height_mm": self.barcode_height_mm,
            "barcode_module_width": self.barcode_module_width,
            "show_barcode_text": self.show_barcode_text,
            "extra_fields": [
                {
                    "prefix": ef.prefix,
                    "column_name": ef.column_name,
                    "fixed_value": ef.fixed_value,
                    "font_size": ef.font_size,
                    "bold": ef.bold,
                }
                for ef in self.extra_fields
            ],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LabelLayoutConfig":
        extra_raw = data.get("extra_fields", [])
        extra_fields = [ExtraFieldConfig(**ef) for ef in extra_raw]
        copy_data = {k: v for k, v in data.items() if k != "extra_fields" and k in cls.__dataclass_fields__}
        return cls(**copy_data, extra_fields=extra_fields)


class ZPLGenerator:
    """Gera código ZPL II paginado agrupando N mini-etiquetas dentro de cada etiqueta grande."""

    def __init__(self, config: LabelLayoutConfig):
        self.cfg = config

    def generate_single_mini_zpl(self, x_dots: int, y_dots: int, w_dots: int, h_dots: int, row_data: Dict[str, Any]) -> List[str]:
        """Gera os comandos ZPL para uma única mini-etiqueta posicionada em (x_dots, y_dots)."""
        cmds: List[str] = []
        cfg = self.cfg
        pad = cfg.mm_to_dots(cfg.inner_padding_mm)

        # 1. Contorno para corte (^GB)
        if cfg.draw_border:
            thickness = max(1, cfg.border_thickness_dots)
            rounding = max(0, min(8, cfg.border_corner_rounding))
            cmds.append(f"^FO{x_dots},{y_dots}^GB{w_dots},{h_dots},{thickness},B,{rounding}^FS")

        inner_x = x_dots + pad
        inner_w = max(20, w_dots - (2 * pad))
        cursor_y = y_dots + pad
        max_y = y_dots + h_dots - pad

        # 2. Mini-Logo Gráfica da Lyda (^GFA) e/ou Cabeçalho fixo no topo da mini-etiqueta
        header_drawn = False
        if cfg.show_logo:
            l_path = cfg.logo_path or get_default_logo_path()
            gfa_cmd, lw, lh = image_to_zpl_gfa(l_path, target_height_dots=cfg.logo_height_dots)
            if gfa_cmd and cursor_y + lh <= max_y:
                if cfg.show_header and cfg.header_text.strip():
                    # Logo à esquerda + texto complementar à direita
                    logo_x = inner_x + 2
                    cmds.append(f"^FO{logo_x},{cursor_y}{gfa_cmd}")
                    hdr = sanitize_zpl_text(cfg.header_text)
                    fs = max(12, cfg.header_font_size)
                    txt_x = logo_x + lw + 6
                    txt_w = max(20, (inner_x + inner_w) - txt_x)
                    txt_y = cursor_y + max(0, (lh - fs) // 2)
                    cmds.append(f"^FO{txt_x},{txt_y}^A0N,{fs},{fs}^FB{txt_w},1,0,R,0^FD{hdr}^FS")
                else:
                    # Mini-logo centralizada no topo da mini-etiqueta
                    logo_x = inner_x + max(0, (inner_w - lw) // 2)
                    cmds.append(f"^FO{logo_x},{cursor_y}{gfa_cmd}")
                cursor_y += lh + 3
                header_drawn = True
        elif cfg.show_header and cfg.header_text.strip():
            hdr = sanitize_zpl_text(cfg.header_text)
            fs = max(12, cfg.header_font_size)
            if cursor_y + fs <= max_y:
                cmds.append(f"^FO{inner_x},{cursor_y}^A0N,{fs},{fs}^FB{inner_w},1,0,C,0^FD{hdr}^FS")
                cursor_y += fs + 3
                header_drawn = True

        if header_drawn and cfg.draw_border and cursor_y + 3 <= max_y:
            cmds.append(f"^FO{inner_x},{cursor_y}^GB{inner_w},1,1,B,0^FS")
            cursor_y += 4

        # 3. Campos de texto dinâmicos (Equipamento, Patrimônio, Setor, etc.)
        for ef in cfg.extra_fields:
            if not ef.column_name:
                continue
            if ef.column_name == "__TEXTO_FIXO__":
                raw_val = ef.fixed_value
            else:
                raw_val = row_data.get(ef.column_name, "")
                if ef.column_name == "CLIENTE":
                    raw_up = str(raw_val or "").upper()
                    st_up = str(row_data.get("STATUS", "")).upper()
                    if not raw_up or "SEM CLIENTE" in raw_up or "ESTOQUE" in raw_up or "ESTOQUE" in st_up or raw_up.startswith("LYDA"):
                        raw_val = "ESTOQUE LYDA"
            val_str = sanitize_zpl_text(raw_val)
            if not val_str and not ef.prefix:
                continue

            pref_str = str(ef.prefix).replace("^", "-").replace("~", "-") if ef.prefix else ""
            full_line = f"{pref_str}{val_str}"
            if len(full_line) > 32:
                full_line = full_line[:31].rstrip() + "."
            fs = max(12, ef.font_size)
            if cursor_y + fs > max_y:
                break  # Evita vazar para fora da mini-etiqueta

            font_w = int(fs * 1.1) if ef.bold else fs
            cmds.append(f"^FO{inner_x},{cursor_y}^A0N,{fs},{font_w}^FB{inner_w},1,0,L,0^FD{full_line}^FS")
            cursor_y += fs + 3

        # 4. Código de Barras ou QR Code na parte inferior/restante da mini-etiqueta
        if cfg.barcode_enabled and cfg.barcode_column:
            raw_code = row_data.get(cfg.barcode_column, "")
            code_val = sanitize_barcode_value(raw_code)
            if code_val:
                if cfg.barcode_type == "QRCODE":
                    # QR Code posicionado centralizado
                    mag = max(2, min(6, cfg.barcode_module_width + 1))
                    qr_x = x_dots + max(pad, (w_dots - (mag * 25)) // 2)
                    if cursor_y + 40 <= max_y:
                        cmds.append(f"^FO{qr_x},{cursor_y}^BQN,2,{mag}^FDQA,{code_val}^FS")
                        if cfg.show_barcode_text:
                            txt_y = min(max_y - 16, cursor_y + (mag * 23))
                            cmds.append(f"^FO{inner_x},{txt_y}^A0N,16,16^FB{inner_w},1,0,C,0^FD{code_val}^FS")
                else:
                    # CODE 128 (^BC)
                    bc_h = cfg.mm_to_dots(cfg.barcode_height_mm)
                    text_space = 22 if cfg.show_barcode_text else 0
                    # Ajusta altura se o espaço restante for menor
                    remaining_h = (max_y - cursor_y) - text_space
                    if remaining_h >= 12:
                        actual_bc_h = min(bc_h, remaining_h)
                        mod_w = max(1, min(4, cfg.barcode_module_width))
                        # Estimativa de largura do Code 128 em dots para centralizar na mini-etiqueta:
                        # (11 * num_chars + 35) * module_width
                        est_bc_width = ((11 * len(code_val)) + 35) * mod_w
                        # Se o código for mais largo que a mini-etiqueta com mod_w atual, reduz mod_w automaticamente
                        while est_bc_width > inner_w and mod_w > 1:
                            mod_w -= 1
                            est_bc_width = ((11 * len(code_val)) + 35) * mod_w

                        # Centraliza verticalmente na área restante para deixar respiro limpo para o leitor bipar
                        extra_v_space = max(0, remaining_h - actual_bc_h)
                        bc_y = cursor_y + (extra_v_space // 4)
                        bc_x = x_dots + max(pad, (w_dots - est_bc_width) // 2)
                        # Desativa linha nativa do ^BC e desenha com ^FB centralizado para nunca cortar nem desalinhar
                        cmds.append(f"^FO{bc_x},{bc_y}^BY{mod_w},2,{actual_bc_h}^BCN,{actual_bc_h},N,N,N^FD{code_val}^FS")
                        txt_y = bc_y + actual_bc_h + 2
                        if cfg.show_barcode_text and txt_y + 16 <= max_y:
                            cmds.append(f"^FO{inner_x},{txt_y}^A0N,15,15^FB{inner_w},1,0,C,0^FD{code_val}^FS")

        return cmds

    def generate_zpl_pages(self, records: List[Dict[str, Any]]) -> List[str]:
        """
        Divide a lista de registros em páginas (cada página = 1 etiqueta grande física)
        e retorna uma lista de blocos ZPL (^XA ... ^XZ).
        """
        if not records:
            return []

        cfg = self.cfg
        mini_w_mm, mini_h_mm = cfg.get_effective_mini_dimensions_mm()

        big_w_dots = cfg.mm_to_dots(cfg.big_width_mm)
        big_h_dots = cfg.mm_to_dots(cfg.big_height_mm)
        margin_l_dots = cfg.mm_to_dots(cfg.margin_left_mm)
        margin_t_dots = cfg.mm_to_dots(cfg.margin_top_mm)
        gap_h_dots = cfg.mm_to_dots(cfg.gap_h_mm)
        gap_v_dots = cfg.mm_to_dots(cfg.gap_v_mm)
        mini_w_dots = cfg.mm_to_dots(mini_w_mm)
        mini_h_dots = cfg.mm_to_dots(mini_h_mm)

        per_page = cfg.items_per_big_label
        skip_n = max(0, min(per_page - 1, int(getattr(cfg, "skip_slots", 0) or 0)))
        padded_records: List[Optional[Dict[str, Any]]] = ([None] * skip_n) + list(records)
        pages_zpl: List[str] = []

        for page_start in range(0, len(padded_records), per_page):
            chunk = padded_records[page_start : page_start + per_page]
            lines = [
                "^XA",
                "^CI28",  # UTF-8 internacional para acentos em português
                f"^PW{big_w_dots}",
                f"^LL{big_h_dots}",
                "^LH0,0",
                f"^MD{max(-30, min(30, cfg.darkness - 15))}",
                f"^PR{max(2, min(6, cfg.print_speed))}",
            ]

            for idx, record in enumerate(chunk):
                r = idx // cfg.cols
                c = idx % cfg.cols

                if record is None:
                    lines.append(f"^FX --- Posicao #{idx+1} (Linha {r+1} Coluna {c+1}) PULADA (ja usada na folha) ---")
                    continue

                x_dots = margin_l_dots + c * (mini_w_dots + gap_h_dots)
                y_dots = margin_t_dots + r * (mini_h_dots + gap_v_dots)

                lines.append(f"^FX --- Mini Etiqueta Linha {r+1} Coluna {c+1} ---")
                mini_cmds = self.generate_single_mini_zpl(
                    x_dots=x_dots,
                    y_dots=y_dots,
                    w_dots=mini_w_dots,
                    h_dots=mini_h_dots,
                    row_data=record,
                )
                lines.extend(mini_cmds)

            # Guias de corte opcionais nas extremidades entre colunas e linhas
            if cfg.draw_cut_marks and (cfg.cols > 1 or cfg.rows > 1):
                lines.append("^FX --- Marcas auxiliares de corte (tesoura) ---")
                # Marcas verticais entre colunas
                for c in range(1, cfg.cols):
                    cut_x = margin_l_dots + c * mini_w_dots + (c - 1) * gap_h_dots + (gap_h_dots // 2)
                    lines.append(f"^FO{cut_x},2^GB1,12,1,B,0^FS")
                    lines.append(f"^FO{cut_x},{max(2, big_h_dots - 14)}^GB1,12,1,B,0^FS")
                # Marcas horizontais entre linhas
                for r in range(1, cfg.rows):
                    cut_y = margin_t_dots + r * mini_h_dots + (r - 1) * gap_v_dots + (gap_v_dots // 2)
                    lines.append(f"^FO2,{cut_y}^GB12,1,1,B,0^FS")
                    lines.append(f"^FO{max(2, big_w_dots - 14)},{cut_y}^GB12,1,1,B,0^FS")

            lines.append("^XZ")
            pages_zpl.append("\n".join(lines))

        return pages_zpl

    def generate_full_zpl(self, records: List[Dict[str, Any]]) -> str:
        """Retorna todo o ZPL concatenado pronto para envio RAW à Zebra ZD230."""
        return "\n\n".join(self.generate_zpl_pages(records))
