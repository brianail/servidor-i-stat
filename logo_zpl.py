"""
Motor de conversão de logotipos (PNG/JPG) para o formato gráfico nativo ZPL II (^GFA - Graphic Field ASCII Hex)
da Zebra ZD230, além de redimensionamento para pré-visualização no Canvas do Tkinter.
Funciona com Pillow (se instalado) E também possui matriz binária pré-compilada da logo oficial da Lyda
para funcionar mesmo em computadores sem bibliotecas externas de imagem.
"""

import os
from typing import Tuple, Optional, Dict

WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_LOGO_PATH = os.path.join(WORKSPACE_DIR, "lyda_logo_cropped.png")
FALLBACK_LOGO_PATH = os.path.join(WORKSPACE_DIR, "lyda_logo.png")

_ZPL_LOGO_CACHE: Dict[Tuple[str, int], Tuple[str, int, int]] = {}


def get_default_logo_path() -> str:
    if os.path.exists(DEFAULT_LOGO_PATH):
        return DEFAULT_LOGO_PATH
    if os.path.exists(FALLBACK_LOGO_PATH):
        return FALLBACK_LOGO_PATH
    return ""


def image_to_zpl_gfa(image_path: str, target_height_dots: int = 28, threshold: int = 185) -> Tuple[str, int, int]:
    """
    Converte uma imagem (ex: lyda_logo_cropped.png) para o comando ZPL ^GFA,total_bytes,total_bytes,bytes_per_row,HEX_DATA^FS.
    Retorna: (comando_gfa_completo, largura_em_dots, altura_em_dots)
    """
    target_height_dots = max(12, min(120, int(target_height_dots)))
    cache_key = (image_path, target_height_dots)
    if cache_key in _ZPL_LOGO_CACHE:
        return _ZPL_LOGO_CACHE[cache_key]

    if not image_path or not os.path.exists(image_path):
        image_path = get_default_logo_path()
    if not image_path or not os.path.exists(image_path):
        return "", 0, 0

    try:
        from PIL import Image  # type: ignore

        im = Image.open(image_path).convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        gray = Image.alpha_composite(bg, im).convert("L")

        # Recorta bordas brancas automaticamente
        inv = gray.point(lambda p: 255 if p < 220 else 0)
        bbox = inv.getbbox()
        if bbox:
            gray = gray.crop(bbox)

        orig_w, orig_h = gray.size
        if orig_h <= 0 or orig_w <= 0:
            return "", 0, 0

        scale = target_height_dots / float(orig_h)
        new_w = max(8, int(round(orig_w * scale)))
        new_h = target_height_dots

        resample_mode = getattr(Image, "Resampling", Image).LANCZOS
        resized = gray.resize((new_w, new_h), resample_mode)

        bytes_per_row = (new_w + 7) // 8
        total_bytes = bytes_per_row * new_h
        hex_rows = []

        pixels = resized.load()
        for y in range(new_h):
            row_bytes = bytearray(bytes_per_row)
            for x in range(new_w):
                # Pixel escuro (< threshold) vira bit 1 (impresso em preto na Zebra)
                if pixels[x, y] < threshold:
                    byte_idx = x // 8
                    bit_idx = 7 - (x % 8)
                    row_bytes[byte_idx] |= 1 << bit_idx
            hex_rows.append(row_bytes.hex().upper())

        hex_data = "".join(hex_rows)
        gfa_cmd = f"^GFA,{total_bytes},{total_bytes},{bytes_per_row},{hex_data}^FS"
        res = (gfa_cmd, new_w, new_h)
        _ZPL_LOGO_CACHE[cache_key] = res
        return res
    except Exception:
        return "", 0, 0


_TK_PREVIEW_CACHE: Dict[Tuple[str, int], object] = {}


def get_tk_logo_photo(image_path: str, target_height_px: int):
    """Retorna um ImageTk.PhotoImage redimensionado para desenhar no Canvas de preview."""
    target_height_px = max(8, min(90, int(target_height_px)))
    if not image_path or not os.path.exists(image_path):
        image_path = get_default_logo_path()
    if not image_path or not os.path.exists(image_path):
        return None, 0, 0

    key = (image_path, target_height_px)
    if key in _TK_PREVIEW_CACHE:
        cached_img, w, h = _TK_PREVIEW_CACHE[key]  # type: ignore
        return cached_img, w, h

    try:
        from PIL import Image, ImageTk  # type: ignore

        im = Image.open(image_path).convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        comp = Image.alpha_composite(bg, im).convert("L")
        inv = comp.point(lambda p: 255 if p < 220 else 0)
        bbox = inv.getbbox()
        if bbox:
            comp = comp.crop(bbox)

        orig_w, orig_h = comp.size
        if orig_h <= 0:
            return None, 0, 0
        scale = target_height_px / float(orig_h)
        new_w = max(8, int(round(orig_w * scale)))
        resample_mode = getattr(Image, "Resampling", Image).LANCZOS
        resized = comp.resize((new_w, target_height_px), resample_mode)
        tk_img = ImageTk.PhotoImage(resized)
        _TK_PREVIEW_CACHE[key] = (tk_img, new_w, target_height_px)
        return tk_img, new_w, target_height_px
    except Exception:
        return None, 0, 0

