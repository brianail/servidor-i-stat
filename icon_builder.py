"""
Gerador do Ícone Oficial do Aplicativo LYDA i-STAT (Windows .ico, macOS .icns/.app e Tkinter PNG).
Cria um ícone moderno de 256x256 com a identidade visual da LYDA + símbolo de código de barras.
"""

import os
import subprocess
from PIL import Image, ImageDraw

WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGO_CROPPED_PATH = os.path.join(WORKSPACE_DIR, "lyda_logo_cropped.png")
LOGO_ORIG_PATH = os.path.join(WORKSPACE_DIR, "lyda_logo.png")
ICON_PNG_PATH = os.path.join(WORKSPACE_DIR, "lyda_app_icon.png")
ICON_ICO_PATH = os.path.join(WORKSPACE_DIR, "lyda_icon.ico")


def build_app_icons() -> tuple[str, str]:
    """Gera lyda_app_icon.png (256x256) e lyda_icon.ico (multi-resolução para Windows)."""
    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Fundo squircle escuro institucional (#0F172A) com borda azul (#2563EB)
    draw.rounded_rectangle((8, 8, size - 8, size - 8), radius=52, fill=(15, 23, 42, 255), outline=(37, 99, 235, 255), width=6)

    # Card branco central para destacar a logo original da LYDA
    draw.rounded_rectangle((26, 34, size - 26, 154), radius=24, fill=(255, 255, 255, 255))

    logo_src = LOGO_CROPPED_PATH if os.path.exists(LOGO_CROPPED_PATH) else LOGO_ORIG_PATH
    if os.path.exists(logo_src):
        try:
            logo = Image.open(logo_src).convert("RGBA")
            # Redimensiona mantendo proporção para caber em (180 x 86)
            max_lw, max_lh = 180, 86
            ratio = min(max_lw / max(1, logo.width), max_lh / max(1, logo.height))
            nw = max(1, int(round(logo.width * ratio)))
            nh = max(1, int(round(logo.height * ratio)))
            logo_resized = logo.resize((nw, nh), Image.Resampling.LANCZOS)
            lx = (size - nw) // 2
            ly = 34 + (120 - nh) // 2
            img.paste(logo_resized, (lx, ly), logo_resized)
        except Exception:
            pass

    # Desenha barras de código de barras estilizadas na metade inferior do ícone (azul claro / branco)
    bar_pattern = [6, 3, 4, 8, 3, 5, 3, 6, 4, 3, 7, 3, 4, 6, 3, 5, 8, 3, 4, 6]
    total_w = sum(bar_pattern) + (len(bar_pattern) - 1) * 4
    cur_x = (size - total_w) // 2
    bar_top = 172
    bar_bot = 218
    for idx, bw in enumerate(bar_pattern):
        color = (56, 189, 248, 255) if idx % 3 == 0 else (248, 250, 252, 255)
        draw.rectangle((cur_x, bar_top, cur_x + bw, bar_bot), fill=color)
        cur_x += bw + 4

    # Faixa laser vermelha/verde de leitura de código de barras
    draw.rounded_rectangle((36, 193, size - 36, 198), radius=2, fill=(16, 185, 129, 240))

    img.save(ICON_PNG_PATH, format="PNG")
    img.save(
        ICON_ICO_PATH,
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    return ICON_PNG_PATH, ICON_ICO_PATH


def build_macos_app_bundle() -> str:
    """
    Cria o aplicativo nativo macOS 'LYDA i-STAT Estoque.app' que abre direto sem janela de Terminal
    e com o ícone personalizado da LYDA no Dock/Finder.
    """
    build_app_icons()
    app_dir = os.path.join(WORKSPACE_DIR, "LYDA i-STAT Estoque.app")
    contents_dir = os.path.join(app_dir, "Contents")
    macos_dir = os.path.join(contents_dir, "MacOS")
    res_dir = os.path.join(contents_dir, "Resources")
    os.makedirs(macos_dir, exist_ok=True)
    os.makedirs(res_dir, exist_ok=True)

    # Converte o PNG para AppIcon.icns usando sips/iconutil se disponível no macOS
    icns_path = os.path.join(res_dir, "AppIcon.icns")
    iconset_dir = os.path.join(res_dir, "AppIcon.iconset")
    try:
        os.makedirs(iconset_dir, exist_ok=True)
        src_img = Image.open(ICON_PNG_PATH)
        for sz in (16, 32, 64, 128, 256, 512):
            resized = src_img.resize((sz, sz), Image.Resampling.LANCZOS)
            resized.save(os.path.join(iconset_dir, f"icon_{sz}x{sz}.png"))
            if sz <= 256:
                resized2x = src_img.resize((sz * 2, sz * 2), Image.Resampling.LANCZOS)
                resized2x.save(os.path.join(iconset_dir, f"icon_{sz}x{sz}@2x.png"))
        subprocess.run(["iconutil", "-c", "icns", iconset_dir, "-o", icns_path], check=False, capture_output=True)
    except Exception:
        pass

    info_plist = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>LydaLauncher</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>CFBundleIdentifier</key>
    <string>br.com.lyda.istat.estoque</string>
    <key>CFBundleName</key>
    <string>LYDA i-STAT Estoque</string>
    <key>CFBundleDisplayName</key>
    <string>LYDA i-STAT Estoque</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>2.0</string>
    <key>LSMinimumSystemVersion</key>
    <string>10.15</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
"""
    with open(os.path.join(contents_dir, "Info.plist"), "w", encoding="utf-8") as f:
        f.write(info_plist)

    launcher_sh = f"""#!/bin/bash
export PATH="/opt/anaconda3/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
DIR="{WORKSPACE_DIR}"
cd "$DIR"
if [ -x "/opt/anaconda3/bin/python3" ]; then
    exec "/opt/anaconda3/bin/python3" "$DIR/main.py" >/dev/null 2>&1
else
    exec python3 "$DIR/main.py" >/dev/null 2>&1
fi
"""
    launcher_path = os.path.join(macos_dir, "LydaLauncher")
    with open(launcher_path, "w", encoding="utf-8") as f:
        f.write(launcher_sh)
    os.chmod(launcher_path, 0o755)
    return app_dir


if __name__ == "__main__":
    p_png, p_ico = build_app_icons()
    app_p = build_macos_app_bundle()
    print(f"Ícones gerados: {p_png}, {p_ico} | App macOS: {app_p}")

