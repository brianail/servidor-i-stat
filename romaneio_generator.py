"""
Gerador de Protocolo / Romaneio de Movimentação de Equipamentos i-STAT — LYDA.
Gera um documento HTML/A4 formatado (pronto para imprimir ou salvar como PDF no navegador)
contendo a Logo da Lyda, dados do Hospital/Cliente, Modalidade (Venda, Comodato, Aluguel, Propriedade Lyda),
tabela com todos os equipamentos bipados no lote/kit, condição física, observações e campos de assinatura.
"""

import base64
import html
import os
import webbrowser
from datetime import datetime
from typing import List, Dict, Any

from logo_zpl import get_default_logo_path


def _get_logo_base64_data_uri() -> str:
    logo_path = get_default_logo_path()
    if logo_path and os.path.exists(logo_path):
        try:
            with open(logo_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("ascii")
            return f"data:image/png;base64,{b64}"
        except Exception:
            pass
    return ""


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
    Cria o arquivo HTML de Protocolo/Romaneio na pasta 'romaneios/' e abre automaticamente no navegador
    pronto para impressão A4 ou 'Salvar como PDF'.
    """
    romaneios_dir = os.path.join(workspace_dir, "romaneios_protocolos")
    os.makedirs(romaneios_dir, exist_ok=True)

    now = datetime.now()
    proto_num = now.strftime("%Y%m%d-%H%M%S")
    data_hora_str = now.strftime("%d/%m/%Y às %H:%M:%S")
    logo_uri = _get_logo_base64_data_uri()

    rows_html = []
    for idx, it in enumerate(items, start=1):
        tipo = html.escape(str(it.get("TIPO", "ANALISADOR")))
        codigo = html.escape(str(it.get("CODIGO", "")))
        cond_it = html.escape(str(it.get("CONDICAO") or condicao or "PERFEITO / FUNCIONANDO 100%"))
        obs_it = html.escape(str(it.get("DEFEITO") or it.get("OBSERVACOES") or defeito or observacoes or "-"))
        rows_html.append(
            f"""
            <tr>
              <td style="text-align:center; font-weight:700;">{idx}</td>
              <td><span class="badge-tipo">{tipo}</span></td>
              <td style="font-family: 'Courier New', monospace; font-size: 14px; font-weight: 700;">{codigo}</td>
              <td>{cond_it}</td>
              <td>{obs_it}</td>
            </tr>
            """
        )

    logo_img_tag = (
        f'<img src="{logo_uri}" alt="LYDA" style="height: 44px; object-fit: contain;" />'
        if logo_uri
        else '<div style="font-size:24px; font-weight:800; color:#0F172A;">LYDA</div>'
    )

    html_content = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8" />
  <title>Protocolo de Movimentação i-STAT #{proto_num} - LYDA</title>
  <style>
    @page {{
      size: A4;
      margin: 14mm;
    }}
    * {{
      box-sizing: border-box;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
    }}
    body {{
      background: #F1F5F9;
      color: #0F172A;
      margin: 0;
      padding: 24px;
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
      background: #16A34A;
      color: #FFFFFF;
      border: none;
      padding: 10px 18px;
      font-size: 14px;
      font-weight: 700;
      border-radius: 4px;
      cursor: pointer;
    }}
    .toolbar button:hover {{
      background: #15803D;
    }}
    .sheet {{
      max-width: 820px;
      margin: 0 auto;
      background: #FFFFFF;
      padding: 32px 36px;
      border: 1px solid #CBD5E1;
      border-radius: 4px;
    }}
    .header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 2px solid #0F172A;
      padding-bottom: 14px;
      margin-bottom: 18px;
    }}
    .title-block h1 {{
      margin: 0;
      font-size: 18px;
      text-transform: uppercase;
      color: #0F172A;
    }}
    .title-block p {{
      margin: 4px 0 0 0;
      font-size: 12px;
      color: #475569;
    }}
    .proto-box {{
      text-align: right;
      font-size: 12px;
      color: #334155;
    }}
    .proto-box strong {{
      display: block;
      font-size: 14px;
      color: #0F172A;
    }}
    .info-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px 18px;
      background: #F8FAFC;
      border: 1px solid #E2E8F0;
      padding: 14px 16px;
      border-radius: 4px;
      margin-bottom: 18px;
      font-size: 13px;
    }}
    .info-item span.lbl {{
      display: block;
      font-size: 10px;
      font-weight: 700;
      text-transform: uppercase;
      color: #64748B;
      margin-bottom: 2px;
    }}
    .info-item span.val {{
      font-weight: 700;
      color: #0F172A;
      font-size: 13px;
    }}
    h2.sec-title {{
      font-size: 13px;
      text-transform: uppercase;
      color: #0F172A;
      border-left: 4px solid #2563EB;
      padding-left: 8px;
      margin: 18px 0 10px 0;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
      margin-bottom: 18px;
    }}
    th {{
      background: #0F172A;
      color: #FFFFFF;
      text-align: left;
      padding: 8px 10px;
      font-size: 11px;
      text-transform: uppercase;
    }}
    td {{
      padding: 9px 10px;
      border-bottom: 1px solid #CBD5E1;
      color: #1E293B;
    }}
    .badge-tipo {{
      background: #EFF6FF;
      color: #1E40AF;
      border: 1px solid #BFDBFE;
      padding: 2px 6px;
      border-radius: 3px;
      font-weight: 700;
      font-size: 11px;
    }}
    .obs-box {{
      background: #FFFBEB;
      border: 1px solid #FDE68A;
      padding: 12px 14px;
      border-radius: 4px;
      font-size: 12px;
      margin-bottom: 26px;
    }}
    .signatures {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 36px;
      margin-top: 48px;
      padding-top: 12px;
    }}
    .sig-line {{
      border-top: 1px solid #0F172A;
      padding-top: 8px;
      text-align: center;
      font-size: 12px;
      color: #334155;
    }}
    @media print {{
      body {{
        background: #FFFFFF;
        padding: 0;
      }}
      .toolbar {{
        display: none !important;
      }}
      .sheet {{
        border: none;
        padding: 0;
        max-width: 100%;
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
    <div class="header">
      <div style="display:flex; align-items:center; gap:16px;">
        {logo_img_tag}
        <div class="title-block">
          <h1>Protocolo de Movimentação de Equipamentos i-STAT</h1>
          <p>Controle de Estoque, Rastreabilidade por Código de Barras e Assistência Técnica — LYDA</p>
        </div>
      </div>
      <div class="proto-box">
        <strong>PROTOCOLO Nº {proto_num}</strong>
        <span>Emissão: {data_hora_str}</span>
      </div>
    </div>

    <div class="info-grid">
      <div class="info-item">
        <span class="lbl">Tipo de Operação / Movimentação</span>
        <span class="val">{html.escape(acao or "MOVIMENTAÇÃO DE EQUIPAMENTO")}</span>
      </div>
      <div class="info-item">
        <span class="lbl">Modalidade / Contrato</span>
        <span class="val">{html.escape(modalidade or "-")} &nbsp;•&nbsp; Status: {html.escape(status or "-")}</span>
      </div>
      <div class="info-item">
        <span class="lbl">Cliente / Hospital / Localização de Destino</span>
        <span class="val">{html.escape(cliente or "SEM CLIENTE (ESTOQUE LYDA)")}</span>
      </div>
      <div class="info-item">
        <span class="lbl">Cidade / UF & Setor</span>
        <span class="val">{html.escape(cidade or "-")} / {html.escape(uf or "-")} — Setor: {html.escape(setor or "-")}</span>
      </div>
    </div>

    <h2 class="sec-title">Equipamentos i-STAT Incluídos nesta Movimentação ({len(items)} aparelho(s))</h2>
    <table>
      <thead>
        <tr>
          <th style="width:40px; text-align:center;">#</th>
          <th style="width:140px;">Aparelho</th>
          <th style="width:150px;">Nº Série (Cód. Barras)</th>
          <th style="width:210px;">Condição Física / Funcionamento</th>
          <th>Observações / Ocorrência / Defeito</th>
        </tr>
      </thead>
      <tbody>
        {"".join(rows_html)}
      </tbody>
    </table>

    <div class="obs-box">
      <strong>Observações Gerais / Defeito Relatado:</strong><br/>
      {html.escape(defeito + " — " + observacoes if (defeito and observacoes) else (defeito or observacoes or "Nenhuma observação adicional registrada."))}
    </div>

    <div class="signatures">
      <div class="sig-line">
        <strong>Responsável Expedição / Estoque LYDA</strong><br/>
        <span>{html.escape(responsavel or "Assinatura / Carimbo")}</span>
      </div>
      <div class="sig-line">
        <strong>Recebido por (Cliente / Hospital / Portador)</strong><br/>
        <span>Nome Legível, Data e Assinatura</span>
      </div>
    </div>
  </div>
</body>
</html>
"""
    file_path = os.path.join(romaneios_dir, f"Romaneio_iSTAT_{proto_num}.html")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    try:
        webbrowser.open(f"file://{os.path.abspath(file_path)}")
    except Exception:
        pass
    return file_path

