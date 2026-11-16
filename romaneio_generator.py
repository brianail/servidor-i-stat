"""
Gerador de Protocolo / Romaneio de Movimentação e Termo de Substituição de Equipamentos i-STAT — LYDA.
Gera documentos HTML/A4 no Timbre Oficial da LYDA (prontos para impressão ou PDF),
com código de barras Code 128 nítido para leitura por bipe óptico/laser, dados do Hospital,
especificação do equipamento entregue e do aparelho substituído/retirado, e campos de assinatura.
"""

import base64
import html
import os
import re
import webbrowser
from datetime import datetime
from typing import List, Dict, Any, Optional

from logo_zpl import get_default_logo_path

# =========================================================================
# GERADOR DE CÓDIGO DE BARRAS CODE 128 (100% ESCANEÁVEL EM SVG)
# =========================================================================
CODE128_PATTERNS = [
    "212222", "222122", "222221", "121223", "121322", "131222", "122213", "122312", "132212", "221213",
    "221312", "231212", "112232", "122132", "122231", "113222", "123122", "123221", "223211", "221132",
    "221231", "213212", "223112", "312131", "311222", "321122", "321221", "312212", "322112", "322211",
    "212123", "212321", "232121", "111323", "131123", "131321", "112313", "132113", "132311", "211313",
    "231113", "231311", "112133", "112331", "132131", "113123", "113321", "133121", "313121", "211331",
    "231131", "213113", "213311", "213131", "311123", "311321", "331121", "312113", "312311", "332111",
    "314111", "221411", "431111", "111224", "111422", "121124", "121421", "141122", "141221", "112214",
    "112412", "122114", "122411", "142112", "142211", "241211", "221114", "413111", "241112", "134111",
    "111242", "121142", "121241", "114212", "124112", "124211", "411212", "421112", "421211", "212141",
    "214121", "412121", "111143", "111341", "131141", "114113", "114311", "411113", "411311", "113141",
    "114131", "311141", "411131", "211412", "211214", "211232", "2331112"
]


def generate_code128_svg(text: str, height: int = 46, module_width: float = 1.9, show_text: bool = True) -> str:
    """Gera um código de barras Code 128 Subset B perfeitamente escaneável por leitores ópticos."""
    clean_text = str(text or "000000").strip()
    if not clean_text:
        clean_text = "000000"

    START_B = 104
    STOP = 106

    indices = [START_B]
    for ch in clean_text:
        val = ord(ch) - 32
        indices.append(val if 0 <= val <= 94 else 0)

    checksum = indices[0]
    for pos, val in enumerate(indices[1:], start=1):
        checksum += pos * val
    checksum %= 103
    indices.append(checksum)
    indices.append(STOP)

    bars = []
    x = 12.0  # Quiet zone
    for idx in indices:
        pattern = CODE128_PATTERNS[idx]
        is_bar = True
        for digit in pattern:
            w = int(digit) * module_width
            if is_bar:
                bars.append(f'<rect x="{x:.1f}" y="0" width="{w:.1f}" height="{height}" fill="#000000"/>')
            x += w
            is_bar = not is_bar

    total_w = x + 12.0
    text_html = ""
    total_h = height
    if show_text:
        total_h += 16
        text_html = f'<text x="{total_w / 2:.1f}" y="{height + 13}" font-family="Courier New, monospace" font-size="13" font-weight="800" text-anchor="middle" fill="#000000">{html.escape(clean_text)}</text>'

    return (
        f'<svg width="{total_w:.1f}" height="{total_h}" viewBox="0 0 {total_w:.1f} {total_h}" '
        f'xmlns="http://www.w3.org/2000/svg" style="display:inline-block; vertical-align:middle;">'
        + "".join(bars)
        + text_html
        + "</svg>"
    )


def _get_logo_base64_data_uri() -> str:
    # Prioriza o logotipo extraído do arquivo docx oficial
    candidate_paths = [
        os.path.join(os.path.dirname(__file__), "web_static", "lyda_timbre_logo.png"),
        os.path.join(os.path.dirname(__file__), "lyda_timbre_logo.png"),
        get_default_logo_path(),
    ]
    for path in candidate_paths:
        if path and os.path.exists(path):
            try:
                with open(path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("ascii")
                return f"data:image/png;base64,{b64}"
            except Exception:
                pass
    return ""


# =========================================================================
# TERMO OFICIAL DE ENTREGA E SUBSTITUIÇÃO DE EQUIPAMENTO i-STAT
# =========================================================================
def generate_termo_substituicao_html(
    workspace_dir: str,
    cliente: str,
    serial_novo: str,
    tipo_equipamento: str = "Analisador i-STAT",
    serial_antigo: str = "",
    motivo_troca: str = "Substituição preventiva / Manutenção",
    recebedor_nome: str = "",
    recebedor_cpf: str = "",
    data_str: str = "",
    responsavel_lyda: str = "Lyda Comércio Importação e Exportação Ltda",
) -> str:
    """
    Gera o Termo de Substituição / Entrega de Equipamento em cima do Timbre Oficial da LYDA,
    contendo os códigos de barras de leitura do aparelho Novo e do aparelho Antigo para bipe.
    """
    romaneios_dir = os.path.join(workspace_dir, "romaneios_protocolos")
    os.makedirs(romaneios_dir, exist_ok=True)

    now = datetime.now()
    if not data_str:
        data_str = now.strftime("%d/%m/%Y")
    data_hora_digital = now.strftime("%Y.%m.%d %H:%M:%S -03'00'")

    logo_uri = _get_logo_base64_data_uri()
    logo_img_tag = (
        f'<img src="{logo_uri}" alt="LYDA" style="height: 52px; object-fit: contain;" />'
        if logo_uri
        else '<div style="font-size:24px; font-weight:800; color:#0F172A;">LYDA</div>'
    )

    bc_novo_svg = generate_code128_svg(serial_novo, height=44, module_width=1.9, show_text=True)
    bc_antigo_svg = generate_code128_svg(serial_antigo, height=44, module_width=1.9, show_text=True) if serial_antigo else ""

    is_troca = bool(serial_antigo and serial_antigo.strip())
    doc_title = "Termo de Entrega de Equipamento" if not is_troca else "Termo de Substituição e Entrega de Equipamento"

    troca_bullet = ""
    if is_troca:
        troca_bullet = f"""
        <div class="equip-card returning">
          <div class="bullet-row">
            <span class="bullet-dot">•</span>
            <div>
              <strong>Equipamento substituído / retirado (Retorno ao Estoque):</strong>
              <div style="font-size:14px; margin-top:2px;">Número de Série Anterior (S/N): <strong>{html.escape(serial_antigo)}</strong></div>
            </div>
          </div>
          <div class="barcode-container">
            <div class="barcode-label">CÓDIGO DE BARRAS P/ BIPAR DEVOLUÇÃO (ANTIGO):</div>
            {bc_antigo_svg}
          </div>
        </div>
        """

    html_content = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8" />
  <title>{doc_title} — SN {html.escape(serial_novo)} — LYDA</title>
  <style>
    @page {{
      size: A4 portrait;
      margin: 13mm 16mm 18mm 16mm;
    }}
    * {{
      box-sizing: border-box;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      color: #111827;
      background: #F3F4F6;
      margin: 0;
      padding: 24px;
      line-height: 1.5;
    }}
    .no-print-bar {{
      max-width: 800px;
      margin: 0 auto 16px auto;
      background: #0F172A;
      color: #FFFFFF;
      padding: 12px 18px;
      border-radius: 8px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    }}
    .no-print-bar button {{
      background: #2563EB;
      color: #FFFFFF;
      border: none;
      padding: 9px 18px;
      font-size: 13.5px;
      font-weight: 700;
      border-radius: 6px;
      cursor: pointer;
    }}
    .no-print-bar button:hover {{
      background: #1D4ED8;
    }}
    .page-sheet {{
      max-width: 800px;
      min-height: 1040px;
      margin: 0 auto;
      background: #FFFFFF;
      padding: 40px 48px;
      border: 1px solid #E5E7EB;
      border-radius: 6px;
      box-shadow: 0 6px 18px rgba(0,0,0,0.06);
      display: flex;
      flex-direction: column;
      justify-content: space-between;
    }}
    /* CABEÇALHO DO TIMBRE PROFISSIONAL LYDA */
    .timbre-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      border-bottom: 1.5px solid #CBD5E1;
      padding-bottom: 10px;
      margin-bottom: 16px;
    }}
    .timbre-title {{
      border-left: 1.5px solid #94A3B8;
      padding-left: 16px;
      text-align: right;
      font-size: 15px;
      font-weight: 700;
      color: #1F2937;
      letter-spacing: -0.2px;
    }}
    .timbre-subtitle {{
      font-size: 11px;
      color: #6B7280;
      margin-top: 2px;
    }}
    .date-row {{
      font-size: 13.5px;
      font-weight: 600;
      color: #111827;
      margin-bottom: 12px;
    }}
    .declaration-p {{
      font-size: 13.5px;
      color: #1F2937;
      text-align: justify;
      margin-bottom: 14px;
      line-height: 1.55;
    }}
    .client-highlight {{
      font-weight: 800;
      color: #0F172A;
      text-transform: uppercase;
    }}
    .equip-card {{
      background: #F8FAFC;
      border: 1.5px solid #E2E8F0;
      border-radius: 8px;
      padding: 12px 16px;
      margin-bottom: 12px;
    }}
    .equip-card.returning {{
      background: #FFFBEB;
      border-color: #FDE68A;
    }}
    .bullet-row {{
      display: flex;
      gap: 10px;
      align-items: flex-start;
      margin-bottom: 6px;
      font-size: 13.5px;
    }}
    .bullet-dot {{
      font-size: 18px;
      line-height: 1;
      color: #2563EB;
      font-weight: 900;
    }}
    .barcode-container {{
      background: #FFFFFF;
      border: 1px dashed #CBD5E1;
      border-radius: 6px;
      padding: 10px 14px;
      display: inline-block;
      margin-top: 8px;
      margin-left: 20px;
      text-align: center;
    }}
    .barcode-label {{
      font-size: 9.5px;
      font-weight: 800;
      letter-spacing: 0.5px;
      color: #64748B;
      margin-bottom: 4px;
      text-transform: uppercase;
    }}
    .declaration-accept {{
      display: flex;
      gap: 10px;
      font-size: 13px;
      color: #374151;
      margin: 12px 0 18px 0;
      font-style: italic;
    }}
    /* QUADROS AMPLOS PARA ASSINATURA FÍSICA OU GOV.BR / ICP-BRASIL */
    .gov-signatures-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 20px;
      margin-top: 16px;
      margin-bottom: 12px;
      page-break-inside: avoid;
    }}
    .gov-sig-card {{
      border: 1px solid #CBD5E1;
      border-radius: 6px;
      padding: 12px 14px;
      background: #FFFFFF;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
    }}
    .gov-sig-title {{
      font-size: 12px;
      font-weight: 800;
      color: #0F172A;
      margin-bottom: 6px;
    }}
    .gov-sig-meta {{
      font-size: 11.5px;
      color: #334155;
      line-height: 1.55;
      margin-bottom: 10px;
    }}
    .gov-meta-line {{
      display: flex;
      align-items: baseline;
      gap: 6px;
      margin-bottom: 3px;
    }}
    .gov-meta-line span.fill {{
      flex: 1;
      border-bottom: 1px solid #94A3B8;
      min-height: 16px;
      font-weight: 600;
      color: #0F172A;
    }}
    .gov-stamp-area {{
      height: 92px;
      border: 1px dashed #CBD5E1;
      border-radius: 4px;
      background: #FFFFFF;
      margin-bottom: 8px;
    }}
    .gov-sig-hint {{
      border-top: 1px solid #334155;
      padding-top: 5px;
      font-size: 10px;
      color: #475569;
      text-align: center;
      font-weight: 600;
    }}
    /* RODAPÉ DO TIMBRE PROFISSIONAL LYDA */
    .timbre-footer {{
      border-top: 1.5px solid #CBD5E1;
      padding-top: 10px;
      margin-top: 24px;
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      font-size: 11px;
      color: #6B7280;
    }}
    @media print {{
      body {{
        background: #FFFFFF !important;
        padding: 0 0 16mm 0 !important;
      }}
      .no-print-bar {{
        display: none !important;
      }}
      .page-sheet {{
        box-shadow: none !important;
        border: none !important;
        padding: 0 !important;
        min-height: auto !important;
      }}
      .timbre-footer {{
        position: fixed;
        bottom: 0;
        left: 0;
        right: 0;
        background: #FFFFFF;
        margin: 0;
        padding: 6px 0 0 0;
      }}
    }}
  </style>
</head>
<body>
  <div class="no-print-bar">
    <div>
      <strong>{doc_title.upper()} — LYDA</strong>
      <span style="font-size:12px; color:#CBD5E1; margin-left:12px;">Pronto para impressão A4 ou Salvar em PDF</span>
    </div>
    <div style="display:flex; gap:8px;">
      <button onclick="window.print()">Imprimir / Salvar PDF</button>
    </div>
  </div>

  <div class="page-sheet">
    <div>
      <!-- CABEÇALHO COM TIMBRE OFICIAL LYDA -->
      <div class="timbre-header">
        <div>{logo_img_tag}</div>
        <div class="timbre-title">
          <div>{doc_title}</div>
          <div class="timbre-subtitle">Gestão Hospitalar & Assistência Especializada i-STAT</div>
        </div>
      </div>

      <!-- DATA -->
      <div class="date-row">
        Data: {html.escape(data_str)}
      </div>

      <!-- DECLARAÇÃO DE ALOCAÇÃO -->
      <div class="declaration-p">
        Pelo presente documento, a <strong>Lyda Comércio Importação e Exportação Ltda</strong> declara que deixou alocado nas dependências da <span class="client-highlight">{html.escape(cliente or "HOSPITAL / CLIENTE")}</span>, o equipamento abaixo descrito:
      </div>

      <!-- EQUIPAMENTO ENTREGUE (NOVO / ATIVO) -->
      <div class="equip-card">
        <div class="bullet-row">
          <span class="bullet-dot">•</span>
          <div>
            <strong>Equipamento:</strong> {html.escape(tipo_equipamento)}
          </div>
        </div>
        <div class="bullet-row">
          <span class="bullet-dot">•</span>
          <div>
            <strong>Número de Série (S/N):</strong> <span style="font-size:16px; font-weight:800; font-family: 'Courier New', monospace;">{html.escape(serial_novo)}</span>
          </div>
        </div>
        <div class="barcode-container">
          <div class="barcode-label">CÓDIGO DE BARRAS OFICIAL P/ BIPAR (ENTREGUE):</div>
          {bc_novo_svg}
        </div>
      </div>

      <!-- EQUIPAMENTO SUBSTITUÍDO (SE HOUVER TROCA) -->
      {troca_bullet}

      <!-- DECLARAÇÃO DE RECEBIMENTO -->
      <div class="declaration-accept">
        <span class="bullet-dot">•</span>
        <span>Declaro o recebimento do equipamento acima identificado, que permanecerá alocado na unidade informada.</span>
      </div>

      <!-- QUADROS AMPLOS PARA ASSINATURA (RECEBEDOR & LYDA - GOV.BR / FÍSICA) -->
      <div class="gov-signatures-grid">
        <div class="gov-sig-card">
          <div>
            <div class="gov-sig-title">Recebedor (Unidade Hospitalar / Cliente)</div>
            <div class="gov-sig-meta">
              <div class="gov-meta-line"><strong>Nome:</strong><span class="fill">{html.escape(recebedor_nome)}</span></div>
              <div class="gov-meta-line"><strong>CPF:</strong><span class="fill">{html.escape(recebedor_cpf)}</span></div>
              <div class="gov-meta-line"><strong>Data:</strong><span class="fill">{html.escape(data_str)}</span></div>
            </div>
          </div>
          <div>
            <div class="gov-stamp-area"></div>
            <div class="gov-sig-hint">Assinatura Física ou Assinatura Digital Gov.br / ICP-Brasil</div>
          </div>
        </div>

        <div class="gov-sig-card">
          <div>
            <div class="gov-sig-title">Lyda Comércio Importação e Exportação Ltda</div>
            <div class="gov-sig-meta">
              <div class="gov-meta-line"><strong>CNPJ:</strong><span class="fill">61.817.692/0001-50</span></div>
              <div class="gov-meta-line"><strong>Responsável:</strong><span class="fill">{html.escape(responsavel_lyda if responsavel_lyda != "Lyda Comércio Importação e Exportação Ltda" else "")}</span></div>
              <div class="gov-meta-line"><strong>Data:</strong><span class="fill">{html.escape(data_str)}</span></div>
            </div>
          </div>
          <div>
            <div class="gov-stamp-area"></div>
            <div class="gov-sig-hint">Assinatura Digital Gov.br / ICP-Brasil ou Responsável LYDA</div>
          </div>
        </div>
      </div>
    </div>

    <!-- RODAPÉ DO TIMBRE PROFISSIONAL LYDA -->
    <div class="timbre-footer">
      <div>Alameda 3 de Outubro, 795<br/>Sarandi, Porto Alegre/RS</div>
      <div style="text-align:center;">(51) 2700-2025</div>
      <div style="text-align:right;">comercial@lyda.com.br</div>
    </div>
  </div>
</body>
</html>
"""
    clean_serial = re.sub(r"[^A-Za-z0-9_-]", "", str(serial_novo))
    filename = f"Termo_Troca_iSTAT_{clean_serial}_{now.strftime('%Y%m%d_%H%M%S')}.html"
    fpath = os.path.join(romaneios_dir, filename)
    with open(fpath, "w", encoding="utf-8") as f:
        f.write(html_content)

    return fpath


# =========================================================================
# PROTOCOLO / ROMANEIO GERAL (MULTI-EQUIPAMENTOS) NO TIMBRE LYDA
# =========================================================================
def generate_and_open_romaneio(
    workspace_dir: str,
    acao: str,
    cliente: str,
    cidade: str,
    uf: str,
    setor: str,
    modalidade: str,
    status: str,
    condicao: str,
    defeito: str,
    observacoes: str,
    responsavel: str,
    items: List[Dict[str, Any]],
) -> str:
    """
    Cria o arquivo HTML de Protocolo/Romaneio A4 no Timbre Oficial LYDA com códigos de barras
    escaneáveis para cada serial bipado na lista.
    """
    romaneios_dir = os.path.join(workspace_dir, "romaneios_protocolos")
    os.makedirs(romaneios_dir, exist_ok=True)

    now = datetime.now()
    proto_num = now.strftime("%Y%m%d-%H%M%S")
    data_hora_str = now.strftime("%d/%m/%Y às %H:%M:%S")
    data_dia_str = now.strftime("%d/%m/%Y")
    data_digital = now.strftime("%Y.%m.%d %H:%M:%S -03'00'")

    logo_uri = _get_logo_base64_data_uri()
    logo_img_tag = (
        f'<img src="{logo_uri}" alt="LYDA" style="height: 48px; object-fit: contain;" />'
        if logo_uri
        else '<div style="font-size:24px; font-weight:800; color:#0F172A;">LYDA</div>'
    )

    rows_html = []
    for idx, it in enumerate(items, start=1):
        tipo = html.escape(str(it.get("TIPO", "ANALISADOR")))
        codigo = str(it.get("CODIGO", "")).strip()
        cond_it = html.escape(str(it.get("CONDICAO") or condicao or "PERFEITO / FUNCIONANDO 100%"))
        obs_it = html.escape(str(it.get("DEFEITO") or it.get("OBSERVACOES") or defeito or observacoes or "-"))

        barcode_svg = generate_code128_svg(codigo, height=36, module_width=1.6, show_text=False) if codigo else ""

        rows_html.append(
            f"""
            <tr>
              <td style="text-align:center; font-weight:700;">{idx}</td>
              <td><span class="badge-tipo">{tipo}</span></td>
              <td style="font-family: 'Courier New', monospace; font-size: 14px; font-weight: 800; white-space:nowrap;">
                {html.escape(codigo)}
                <div style="margin-top:3px;">{barcode_svg}</div>
              </td>
              <td style="font-size:12px;">{cond_it}</td>
              <td style="font-size:12px;">{obs_it}</td>
            </tr>
            """
        )

    html_content = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8" />
  <title>Protocolo de Movimentação i-STAT #{proto_num} - LYDA</title>
  <style>
    @page {{
      size: A4;
      margin: 14mm 16mm 14mm 16mm;
    }}
    * {{
      box-sizing: border-box;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }}
    body {{
      background: #F1F5F9;
      color: #0F172A;
      margin: 0;
      padding: 24px;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
    }}
    .toolbar {{
      max-width: 820px;
      margin: 0 auto 16px auto;
      background: #0F172A;
      color: #FFFFFF;
      padding: 12px 18px;
      border-radius: 6px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }}
    .toolbar button {{
      background: #2563EB;
      color: #FFFFFF;
      border: none;
      padding: 10px 18px;
      font-size: 14px;
      font-weight: 700;
      border-radius: 4px;
      cursor: pointer;
    }}
    .toolbar button:hover {{
      background: #1D4ED8;
    }}
    .sheet {{
      max-width: 820px;
      margin: 0 auto;
      background: #FFFFFF;
      padding: 36px 40px;
      border: 1px solid #CBD5E1;
      border-radius: 4px;
      min-height: 1040px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
    }}
    .timbre-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      border-bottom: 1.5px solid #CBD5E1;
      padding-bottom: 12px;
      margin-bottom: 20px;
    }}
    .timbre-title {{
      border-left: 1.5px solid #94A3B8;
      padding-left: 16px;
      text-align: right;
    }}
    .timbre-title h1 {{
      margin: 0;
      font-size: 16px;
      font-weight: 800;
      color: #0F172A;
      text-transform: uppercase;
    }}
    .timbre-title p {{
      margin: 3px 0 0 0;
      font-size: 11px;
      color: #64748B;
    }}
    .proto-box {{
      font-size: 11.5px;
      color: #475569;
      margin-top: 4px;
    }}
    .info-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px 16px;
      background: #F8FAFC;
      border: 1px solid #E2E8F0;
      padding: 12px 16px;
      border-radius: 6px;
      margin-bottom: 16px;
      font-size: 12.5px;
    }}
    .info-item span.lbl {{
      display: block;
      font-size: 10px;
      font-weight: 700;
      text-transform: uppercase;
      color: #64748B;
      margin-bottom: 1px;
    }}
    .info-item span.val {{
      font-weight: 700;
      color: #0F172A;
      font-size: 13px;
    }}
    h2.sec-title {{
      font-size: 12.5px;
      text-transform: uppercase;
      color: #0F172A;
      border-left: 4px solid #2563EB;
      padding-left: 8px;
      margin: 16px 0 8px 0;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
      margin-bottom: 14px;
    }}
    th {{
      background: #0F172A;
      color: #FFFFFF;
      text-align: left;
      padding: 7px 10px;
      font-size: 10.5px;
      text-transform: uppercase;
    }}
    td {{
      padding: 8px 10px;
      border-bottom: 1px solid #E2E8F0;
      color: #1E293B;
      vertical-align: middle;
    }}
    .badge-tipo {{
      background: #EFF6FF;
      color: #1E40AF;
      border: 1px solid #BFDBFE;
      padding: 2px 6px;
      border-radius: 3px;
      font-weight: 700;
      font-size: 10.5px;
    }}
    .obs-box {{
      background: #FFFBEB;
      border: 1px solid #FDE68A;
      padding: 10px 14px;
      border-radius: 4px;
      font-size: 11.5px;
      margin-bottom: 22px;
    }}
    .gov-signatures-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 20px;
      margin-top: 20px;
      margin-bottom: 16px;
      page-break-inside: avoid;
    }}
    .gov-sig-card {{
      border: 1px solid #CBD5E1;
      border-radius: 6px;
      padding: 12px 14px;
      background: #FFFFFF;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
    }}
    .gov-sig-title {{
      font-size: 12px;
      font-weight: 800;
      color: #0F172A;
      margin-bottom: 6px;
    }}
    .gov-sig-meta {{
      font-size: 11px;
      color: #334155;
      line-height: 1.5;
      margin-bottom: 10px;
    }}
    .gov-meta-line {{
      display: flex;
      align-items: baseline;
      gap: 6px;
      margin-bottom: 3px;
    }}
    .gov-meta-line span.fill {{
      flex: 1;
      border-bottom: 1px solid #94A3B8;
      min-height: 15px;
      font-weight: 600;
      color: #0F172A;
    }}
    .gov-stamp-area {{
      height: 92px;
      border: 1px dashed #CBD5E1;
      border-radius: 4px;
      background: #FFFFFF;
      margin-bottom: 8px;
    }}
    .gov-sig-hint {{
      border-top: 1px solid #334155;
      padding-top: 5px;
      font-size: 10px;
      color: #475569;
      text-align: center;
      font-weight: 600;
    }}
    .timbre-footer {{
      border-top: 1.5px solid #CBD5E1;
      padding-top: 10px;
      margin-top: 24px;
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      font-size: 11px;
      color: #6B7280;
    }}
    @media print {{
      body {{
        background: #FFFFFF !important;
        padding: 0 0 16mm 0 !important;
      }}
      .toolbar {{
        display: none !important;
      }}
      .sheet {{
        border: none !important;
        padding: 0 !important;
        max-width: 100% !important;
        min-height: auto !important;
      }}
      .timbre-footer {{
        position: fixed;
        bottom: 0;
        left: 0;
        right: 0;
        background: #FFFFFF;
        margin: 0;
        padding: 6px 0 0 0;
      }}
    }}
  </style>
</head>
<body>
  <div class="toolbar">
    <div>
      <strong>PROTOCOLO / ROMANEIO PRONTO (# {proto_num})</strong>
      <span style="font-size:12px; color:#CBD5E1; margin-left:10px;">Imprima em folha A4 ou escolha "Salvar como PDF"</span>
    </div>
    <button onclick="window.print()">IMPRIMIR / SALVAR PDF</button>
  </div>

  <div class="sheet">
    <div>
      <div class="timbre-header">
        <div>{logo_img_tag}</div>
        <div class="timbre-title">
          <h1>Protocolo de Movimentação i-STAT</h1>
          <p>Controle de Estoque & Rastreabilidade de Equipamentos</p>
          <div class="proto-box">Protocolo Nº <strong>{proto_num}</strong> • Emissão: {data_hora_str}</div>
        </div>
      </div>

      <div class="info-grid">
        <div class="info-item">
          <span class="lbl">Operação / Movimentação</span>
          <span class="val">{html.escape(acao or "MOVIMENTAÇÃO DE EQUIPAMENTO")}</span>
        </div>
        <div class="info-item">
          <span class="lbl">Modalidade / Contrato</span>
          <span class="val">{html.escape(modalidade or "-")} &nbsp;•&nbsp; Status: {html.escape(status or "-")}</span>
        </div>
        <div class="info-item">
          <span class="lbl">Hospital / Cliente / Destino</span>
          <span class="val">{html.escape(cliente or "SEM CLIENTE (ESTOQUE LYDA)")}</span>
        </div>
        <div class="info-item">
          <span class="lbl">Cidade / UF & Setor</span>
          <span class="val">{html.escape(cidade or "-")} / {html.escape(uf or "-")} — Setor: {html.escape(setor or "-")}</span>
        </div>
      </div>

      <h2 class="sec-title">Equipamentos Incluídos ({len(items)} aparelho(s)) — Códigos de Barras Escaneáveis</h2>
      <table>
        <thead>
          <tr>
            <th style="width:36px; text-align:center;">#</th>
            <th style="width:120px;">Aparelho</th>
            <th style="width:230px;">Nº Série & Código de Barras</th>
            <th style="width:160px;">Condição Física</th>
            <th>Observações / Defeito</th>
          </tr>
        </thead>
        <tbody>
          {"".join(rows_html)}
        </tbody>
      </table>

      <div class="obs-box">
        <strong>Observações / Instruções Adicionais:</strong><br/>
        {html.escape(defeito + " — " + observacoes if (defeito and observacoes) else (defeito or observacoes or "Nenhuma observação adicional registrada."))}
      </div>

      <div class="gov-signatures-grid">
        <div class="gov-sig-card">
          <div>
            <div class="gov-sig-title">Lyda Comércio Importação e Exportação Ltda</div>
            <div class="gov-sig-meta">
              <div class="gov-meta-line"><strong>CNPJ:</strong><span class="fill">61.817.692/0001-50</span></div>
              <div class="gov-meta-line"><strong>Responsável:</strong><span class="fill">{html.escape(responsavel or "EXPEDIÇÃO LYDA")}</span></div>
              <div class="gov-meta-line"><strong>Data:</strong><span class="fill">{data_dia_str}</span></div>
            </div>
          </div>
          <div>
            <div class="gov-stamp-area"></div>
            <div class="gov-sig-hint">Expedição / Responsável LYDA (Gov.br / ICP-Brasil ou Física)</div>
          </div>
        </div>

        <div class="gov-sig-card">
          <div>
            <div class="gov-sig-title">Recebedor (Cliente / Unidade Hospitalar)</div>
            <div class="gov-sig-meta">
              <div class="gov-meta-line"><strong>Nome Legível:</strong><span class="fill"></span></div>
              <div class="gov-meta-line"><strong>CPF:</strong><span class="fill"></span></div>
              <div class="gov-meta-line"><strong>Data:</strong><span class="fill">{data_dia_str}</span></div>
            </div>
          </div>
          <div>
            <div class="gov-stamp-area"></div>
            <div class="gov-sig-hint">Recebedor no Hospital / Cliente (Gov.br ou Assinatura e Carimbo)</div>
          </div>
        </div>
      </div>
    </div>

    <!-- RODAPÉ DO TIMBRE PROFISSIONAL LYDA -->
    <div class="timbre-footer">
      <div>Alameda 3 de Outubro, 795<br/>Sarandi, Porto Alegre/RS</div>
      <div style="text-align:center;">(51) 2700-2025</div>
      <div style="text-align:right;">comercial@lyda.com.br</div>
    </div>
  </div>
</body>
</html>
"""
    file_path = os.path.join(romaneios_dir, f"Romaneio_iSTAT_{proto_num}.html")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    return file_path
