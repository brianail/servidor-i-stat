"""
Módulo de Endereçamento, Consulta de CEP (ViaCEP), Geocodificação/Ordenação de Paradas
e Geração da Rota da Enfermeira (Google Maps Multi-Paradas + Folha de Rota A4/PDF/Celular)
para Atualização Externa de Equipamentos i-STAT saindo da Sede da LYDA.
"""

import base64
import calendar
import html
import json
import math
import os
import re
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from logo_zpl import get_default_logo_path


_LOGO_URI_CACHE: Dict[str, str] = {}


def get_logo_base64_data_uri(logo_path: str = "", white_ink: bool = False) -> str:
    """
    Gera Data URI PNG da logo da LYDA com fundo 100% transparente (sem caixa branca quadrada).
    - white_ink=True: traços em branco puro (#FFFFFF) com anti-aliasing suave para fundos escuros (Sidebar / Login).
    - white_ink=False: traços em grafite escuro (#0F172A) com fundo transparente para fundos claros / PDFs.
    """
    cache_key = f"{logo_path or 'default'}_{'white' if white_ink else 'dark'}"
    if cache_key in _LOGO_URI_CACHE:
        return _LOGO_URI_CACHE[cache_key]

    p = logo_path or get_default_logo_path()
    if p and os.path.exists(p):
        try:
            import io
            from PIL import Image

            im = Image.open(p).convert("L")
            # Upscale 2x com Lanczos para suavizar bordas antes de extrair canal Alpha
            w, h = im.size
            im = im.resize((w * 2, h * 2), Image.Resampling.LANCZOS)

            rgba = Image.new("RGBA", im.size)
            src_pixels = im.load()
            dst_pixels = rgba.load()
            for y in range(im.size[1]):
                for x in range(im.size[0]):
                    lum = src_pixels[x, y]
                    # Fundo claro (> 235) fica 100% transparente; traços escuros ganham opacidade proporcional
                    if lum >= 238:
                        dst_pixels[x, y] = (255, 255, 255, 0)
                    else:
                        alpha = int(min(255, max(0, (240 - lum) * 255 / 195)))
                        if white_ink:
                            dst_pixels[x, y] = (255, 255, 255, alpha)
                        else:
                            dst_pixels[x, y] = (15, 23, 42, alpha)

            buf = io.BytesIO()
            rgba.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode("ascii")
            uri = f"data:image/png;base64,{b64}"
            _LOGO_URI_CACHE[cache_key] = uri
            return uri
        except Exception:
            try:
                with open(p, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("ascii")
                return f"data:image/png;base64,{b64}"
            except Exception:
                pass
    return ""


def parse_br_date(raw_text: str) -> Optional[datetime]:
    """Extrai a primeira data DD/MM/AAAA encontrada na string (ex: '10/05/2026 (CLEW A45)')."""
    if not raw_text:
        return None
    m = re.search(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})", str(raw_text))
    if not m:
        return None
    day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if year < 100:
        year += 2000
    try:
        return datetime(year, month, day)
    except ValueError:
        return None


def add_months_to_date(dt: datetime, months: int = 6) -> datetime:
    """Soma `months` meses (padrão: 6 em 6 meses) preservando o dia do mês com segurança."""
    m_total = (dt.month - 1) + int(months)
    year = dt.year + (m_total // 12)
    month = (m_total % 12) + 1
    max_day = calendar.monthrange(year, month)[1]
    day = min(dt.day, max_day)
    return datetime(year, month, day)


def compute_update_cycle_info(item: Dict[str, Any], default_cycle_months: int = 6) -> Dict[str, Any]:
    """
    Calcula a situação do ciclo semestral de atualização (6 em 6 meses) de um aparelho i-STAT:
    Retorna:
      - last_date_str: 'DD/MM/AAAA' ou ''
      - next_date_str: 'DD/MM/AAAA' ou 'PENDENTE'
      - days_remaining: int (negativo se vencida) ou None
      - state / status_code: 'EM_DIA' | 'VENCENDO' | 'VENCIDA' | 'SEM_DATA'
      - summary_table / badge_text: texto curto para a coluna da tabela
      - banner_text: texto completo para o Mega Editor
      - bg_color / fg_color: cores para badges visuais
    """
    raw_ult = str(item.get("ULTIMA_ATUALIZACAO", "") or "").strip()
    try:
        ciclo_meses = max(1, int(item.get("CICLO_ATUALIZACAO_MESES") or default_cycle_months or 6))
    except Exception:
        ciclo_meses = default_cycle_months or 6

    dt_last = parse_br_date(raw_ult)
    if not dt_last:
        summary = f"Sem data ({ciclo_meses}m)"
        return {
            "last_date_str": "",
            "next_date_str": "PENDENTE",
            "days_remaining": None,
            "days_elapsed": None,
            "progress_pct": 0,
            "ciclo_meses": ciclo_meses,
            "state": "SEM_DATA",
            "status_code": "SEM_DATA",
            "summary_table": summary,
            "badge_text": summary,
            "banner_text": f"SEM DATA DE ATUALIZAÇÃO REGISTRADA (Ciclo padrão: {ciclo_meses} em {ciclo_meses} meses)",
            "bg_color": "#FEF3C7",
            "fg_color": "#92400E",
        }

    dt_next = add_months_to_date(dt_last, ciclo_meses)
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    days_rem = (dt_next - today).days
    total_cycle_days = max(1, (dt_next - dt_last).days)
    days_elapsed = max(0, (today - dt_last).days)
    progress_pct = min(100, max(0, int(round((days_elapsed / total_cycle_days) * 100))))
    last_s = dt_last.strftime("%d/%m/%Y")
    next_s = dt_next.strftime("%d/%m/%Y")

    if days_rem < 0:
        atraso = abs(days_rem)
        summary = f"Vencida há {atraso}d ({next_s})"
        return {
            "last_date_str": last_s,
            "next_date_str": next_s,
            "days_remaining": days_rem,
            "days_elapsed": days_elapsed,
            "progress_pct": 100,
            "ciclo_meses": ciclo_meses,
            "state": "VENCIDA",
            "status_code": "VENCIDA",
            "summary_table": summary,
            "badge_text": summary,
            "banner_text": f"ATUALIZAÇÃO VENCIDA HÁ {atraso} DIA(S)!  |  Última: {last_s}  ->  Venceu em: {next_s}",
            "bg_color": "#FEE2E2",
            "fg_color": "#991B1B",
        }
    if days_rem <= 45:
        summary = f"Faltam {days_rem}d ({next_s})"
        return {
            "last_date_str": last_s,
            "next_date_str": next_s,
            "days_remaining": days_rem,
            "days_elapsed": days_elapsed,
            "progress_pct": progress_pct,
            "ciclo_meses": ciclo_meses,
            "state": "VENCENDO",
            "status_code": "VENCENDO",
            "summary_table": summary,
            "badge_text": summary,
            "banner_text": f"AVISO: PERTO DE BATER 6 MESES (Faltam {days_rem} dias)  |  Última: {last_s}  ->  Próxima: {next_s}",
            "bg_color": "#FEF3C7",
            "fg_color": "#B45309",
        }
    summary = f"Em dia • Próx: {next_s}"
    return {
        "last_date_str": last_s,
        "next_date_str": next_s,
        "days_remaining": days_rem,
        "days_elapsed": days_elapsed,
        "progress_pct": progress_pct,
        "ciclo_meses": ciclo_meses,
        "state": "EM_DIA",
        "status_code": "EM_DIA",
        "summary_table": summary,
        "badge_text": summary,
        "banner_text": f"ATUALIZAÇÃO EM DIA (Faltam {days_rem} dias)  |  Última: {last_s}  ->  Próxima ({ciclo_meses}m): {next_s}",
        "bg_color": "#DCFCE7",
        "fg_color": "#166534",
    }


# Endereço padrão da Sede da LYDA em Porto Alegre - RS (editável pelo usuário no sistema)
DEFAULT_LYDA_SEDE_ADDRESS = "Rua Alameda 3 de Outubro, 795 - Sarandi, Porto Alegre - RS, 91130-470"

# Coordenadas exatas (Latitude, Longitude) da Sede LYDA e dos Hospitais/Clínicas conhecidos
EXACT_HOSPITAL_COORDS: Dict[str, Tuple[float, float]] = {
    # Sedes LYDA (Sarandi e Navegantes)
    "91130-470": (-29.9912, -51.1278),
    "91130470": (-29.9912, -51.1278),
    "ALAMEDA 3 DE OUTUBRO": (-29.9912, -51.1278),
    "90240-005": (-30.0007, -51.1965),
    "90240005": (-30.0007, -51.1965),
    "AV. PERNAMBUCO, 2623": (-30.0007, -51.1965),
    # Hospitais e Clínicas de Porto Alegre
    "HOSPITAL DE CLINICAS DE PORTO ALEGRE": (-30.0386, -51.2067),
    "90035-903": (-30.0386, -51.2067),
    "ASSOCIACAO HOSPITALAR MOINHOS DE VENTO": (-30.0249, -51.2082),
    "90035-001": (-30.0249, -51.2082),
    "HMV PONTAL": (-30.0805, -51.2452),
    "90810-240": (-30.0805, -51.2452),
    "ASSOCIACAO EDUCADORA SAO CARLOS - AESC": (-30.0589, -51.2291),
    "90880-481": (-30.0589, -51.2291),
    "SOCIEDADE SULINA DIVINA PROVIDENCIA": (-30.0844, -51.1872),
    "91712-000": (-30.0844, -51.1872),
    "FERTILITAT - CENTRO DE MEDICINA REPRODUTIVA S/S": (-30.1147, -51.2465),
    "91760-470": (-30.1147, -51.2465),
    "CLINICA MEDICA DR NILO FRANTZ LTDA": (-30.0308, -51.1812),
    "90480-004": (-30.0308, -51.1812),
    "CLINICA DE REPRODUCAO ASSISTIDA PROSER SOCIEDADE S": (-30.0209, -51.1924),
    "90560-002": (-30.0209, -51.1924),
    "GUEDES DA LUZ MEDICOS ASSOCIADOS LTDA ( INSEMINE)": (-30.0253, -51.1631),
    "91330-001": (-30.0253, -51.1631),
    # Região Metropolitana, Serra, Interior RS e SC
    "FUNDACAO EDUCACIONAL ALTO MEDIO SAO FRANCISCO(HU CANOAS)": (-29.8872, -51.1642),
    "92425-900": (-29.8872, -51.1642),
    "ASS PRO ENSINO SUP EM NOVO HAMBURGO (FEEVALE)": (-29.6648, -51.1194),
    "93525-075": (-29.6648, -51.1194),
    "HOSPITAL OURO BRANCO": (-29.4503, -51.8082),
    "95890-000": (-29.4503, -51.8082),
    "HOSPITAL BENEFICENTE NOSSA SENHORA DE FATIMA": (-29.0294, -51.1825),
    "95270-000": (-29.0294, -51.1825),
    "SOCIEDADE HOSPITALAR SAO JOSE": (-28.8576, -51.2819),
    "95250-000": (-28.8576, -51.2819),
    "ASSOC. VERANENSE DE ASSISTENCIA EM SAUDE": (-28.9361, -51.5494),
    "95330-000": (-28.9361, -51.5494),
    "HOSPITAL SANTO ANTONIO": (-28.0678, -52.0125),
    "99950-000": (-28.0678, -52.0125),
    "HOSPITAL BENEFICENTE SAO JOAO": (-27.9502, -51.8058),
    "99840-000": (-27.9502, -51.8058),
    "HOSPITAL SANTA LÚCIA": (-28.6411, -53.6062),
    "98005-000": (-28.6411, -53.6062),
    "UNIMED MISSÕES": (-28.2974, -54.2598),
    "98801-600": (-28.2974, -54.2598),
    "UNIMED CRICIÚMA": (-28.6815, -49.3424),
    "88815-180": (-28.6815, -49.3424),
    "UNIMED ARARANGUA": (-28.9362, -49.4895),
    "88900-027": (-28.9362, -49.4895),
    "SANTA CASA DE SANTA VITORIA DO PALMAR": (-33.5194, -53.3668),
    "96230-000": (-33.5194, -53.3668),
    "COMANDO DA MARINHA": (-32.0432, -52.0894),
    "96201-020": (-32.0432, -52.0894),
    "FIERGS": (-29.9885, -51.1142),
    "91140-001": (-29.9885, -51.1142),
    "CCG/ HAPVIDA": (-30.0258, -51.2095),
    "LAB HUMANIZA": (-30.0258, -51.2095),
    "BLUTS": (-29.1685, -51.1862),
    "DOAÇÃO BLUT'S": (-29.1685, -51.1862),
    "ONCOSUPORT": (-29.1678, -51.1835),
    "BIOVET LABORATORIOS LTDA (VERTÁ)": (-28.2571, -52.4215),
    "CENTRO CLINICO VETERINARIO LTDA ( LATE MAIS AUUTO)": (-30.0195, -51.1882),
    "EM BACKUP HMV": (-30.0249, -51.2082),
    "EM BACKUP HMD": (-30.0589, -51.2291),
}

# Base pré-mapeada de endereços reais dos principais Hospitais/Clínicas da carteira LYDA (RS e SC)
# Permite que os aparelhos atuais já tenham endereço sugerido automaticamente, podendo ser editado livremente
KNOWN_HOSPITAL_ADDRESSES: Dict[str, Dict[str, str]] = {
    "HOSPITAL DE CLINICAS DE PORTO ALEGRE": {
        "ENDERECO": "Rua Ramiro Barcelos, 2350 - Santa Cecília",
        "CEP": "90035-903",
        "CIDADE": "PORTO ALEGRE",
        "UF": "RS",
    },
    "ASSOCIACAO HOSPITALAR MOINHOS DE VENTO": {
        "ENDERECO": "Rua Ramiro Barcelos, 910 - Moinhos de Vento",
        "CEP": "90035-001",
        "CIDADE": "PORTO ALEGRE",
        "UF": "RS",
    },
    "HMV PONTAL": {
        "ENDERECO": "Av. Padre Cacique, 2893 - Cristal (Pontal Shopping)",
        "CEP": "90810-240",
        "CIDADE": "PORTO ALEGRE",
        "UF": "RS",
    },
    "ASSOCIACAO EDUCADORA SAO CARLOS - AESC": {
        "ENDERECO": "Rua José de Alencar, 286 - Menino Deus (Hosp. Mãe de Deus)",
        "CEP": "90880-481",
        "CIDADE": "PORTO ALEGRE",
        "UF": "RS",
    },
    "SOCIEDADE SULINA DIVINA PROVIDENCIA": {
        "ENDERECO": "Estrada da Cascata, 1148 - Cascata (Hosp. Divina Providência)",
        "CEP": "91712-000",
        "CIDADE": "PORTO ALEGRE",
        "UF": "RS",
    },
    "FERTILITAT - CENTRO DE MEDICINA REPRODUTIVA S/S": {
        "ENDERECO": "Av. Gomes de Freitas, 77 - Jardim Isabel",
        "CEP": "91760-470",
        "CIDADE": "PORTO ALEGRE",
        "UF": "RS",
    },
    "CLINICA MEDICA DR NILO FRANTZ LTDA": {
        "ENDERECO": "Av. Carlos Gomes, 1111 - Auxiliadora",
        "CEP": "90480-004",
        "CIDADE": "PORTO ALEGRE",
        "UF": "RS",
    },
    "CLINICA DE REPRODUCAO ASSISTIDA PROSER SOCIEDADE S": {
        "ENDERECO": "Av. Cristovão Colombo, 3084 - Higienópolis",
        "CEP": "90560-002",
        "CIDADE": "PORTO ALEGRE",
        "UF": "RS",
    },
    "GUEDES DA LUZ MEDICOS ASSOCIADOS LTDA ( INSEMINE)": {
        "ENDERECO": "Av. Dr. Nilo Peçanha, 2825 - Chácara das Pedras",
        "CEP": "91330-001",
        "CIDADE": "PORTO ALEGRE",
        "UF": "RS",
    },
    "FUNDACAO EDUCACIONAL ALTO MEDIO SAO FRANCISCO(HU CANOAS)": {
        "ENDERECO": "Av. Farroupilha, 8001 - São José (Hospital Universitário Canoas)",
        "CEP": "92425-900",
        "CIDADE": "CANOAS",
        "UF": "RS",
    },
    "ASS PRO ENSINO SUP EM NOVO HAMBURGO (FEEVALE)": {
        "ENDERECO": "Rodovia RS-239, 2755 - Vila Nova",
        "CEP": "93525-075",
        "CIDADE": "CAMPO BOM",
        "UF": "RS",
    },
    "HOSPITAL OURO BRANCO": {
        "ENDERECO": "Rua Fernando Ferrari, 200 - Boa Vista",
        "CEP": "95890-000",
        "CIDADE": "TEUTÔNIA",
        "UF": "RS",
    },
    "HOSPITAL BENEFICENTE NOSSA SENHORA DE FATIMA": {
        "ENDERECO": "Rua Heitor Curra, 2019 - Centro",
        "CEP": "95270-000",
        "CIDADE": "FLORES DA CUNHA",
        "UF": "RS",
    },
    "SOCIEDADE HOSPITALAR SAO JOSE": {
        "ENDERECO": "Rua Dr. Ramiro Barcelos, 295 - Centro",
        "CEP": "95250-000",
        "CIDADE": "ANTÔNIO PRADO",
        "UF": "RS",
    },
    "ASSOC. VERANENSE DE ASSISTENCIA EM SAUDE": {
        "ENDERECO": "Rua Júlio de Castilhos, 885 - Centro (Hosp. São Peregrino Lazziozi)",
        "CEP": "95330-000",
        "CIDADE": "VERANÓPOLIS",
        "UF": "RS",
    },
    "HOSPITAL SANTO ANTONIO": {
        "ENDERECO": "Av. Sete de Setembro, 1855 - Centro",
        "CEP": "99950-000",
        "CIDADE": "TAPEJARA",
        "UF": "RS",
    },
    "HOSPITAL BENEFICENTE SAO JOAO": {
        "ENDERECO": "Av. Fiorentino Bachi, 1480 - Centro",
        "CEP": "99840-000",
        "CIDADE": "SANANDUVA",
        "UF": "RS",
    },
    "HOSPITAL SANTA LÚCIA": {
        "ENDERECO": "Av. Venâncio Aires, 1277 - Centro",
        "CEP": "98005-000",
        "CIDADE": "CRUZ ALTA",
        "UF": "RS",
    },
    "UNIMED MISSÕES": {
        "ENDERECO": "Av. Rio Grande do Sul, 1189 - Centro (Hosp. Regional Unimed Missões)",
        "CEP": "98801-600",
        "CIDADE": "SANTO ÂNGELO",
        "UF": "RS",
    },
    "UNIMED CRICIÚMA": {
        "ENDERECO": "Rua Estevão Emílio de Souza, 129 - Próspera",
        "CEP": "88815-180",
        "CIDADE": "CRICIÚMA",
        "UF": "SC",
    },
    "UNIMED ARARANGUA": {
        "ENDERECO": "Av. Sete de Setembro, 1980 - Centro",
        "CEP": "88900-027",
        "CIDADE": "ARARANGUA",
        "UF": "SC",
    },
    "SANTA CASA DE SANTA VITORIA DO PALMAR": {
        "ENDERECO": "Rua Barão do Rio Branco, 780 - Centro",
        "CEP": "96230-000",
        "CIDADE": "SANTA VITÓRIA DO PALMAR",
        "UF": "RS",
    },
    "COMANDO DA MARINHA": {
        "ENDERECO": "Av. Honório Bicalho, s/n - Getúlio Vargas (Policlínica Naval de Rio Grande)",
        "CEP": "96201-020",
        "CIDADE": "RIO GRANDE",
        "UF": "RS",
    },
    "FIERGS": {
        "ENDERECO": "Av. Assis Brasil, 8787 - Sarandi (Sede FIERGS / SESI)",
        "CEP": "91140-001",
        "CIDADE": "PORTO ALEGRE",
        "UF": "RS",
    },
    "CCG/ HAPVIDA": {
        "ENDERECO": "Rua Ramiro Barcelos, 630 - Floresta (Hospital Humaniza / CCG)",
        "CEP": "90035-001",
        "CIDADE": "PORTO ALEGRE",
        "UF": "RS",
    },
    "LAB HUMANIZA": {
        "ENDERECO": "Rua Ramiro Barcelos, 630 - Floresta (Hospital Humaniza)",
        "CEP": "90035-001",
        "CIDADE": "PORTO ALEGRE",
        "UF": "RS",
    },
    "BLUTS": {
        "ENDERECO": "Rua Pinheiro Machado, 2321 - São Pelegrino (Blut's Diagnósticos)",
        "CEP": "95020-172",
        "CIDADE": "CAXIAS DO SUL",
        "UF": "RS",
    },
    "DOAÇÃO BLUT'S": {
        "ENDERECO": "Rua Pinheiro Machado, 2321 - São Pelegrino (Blut's Diagnósticos)",
        "CEP": "95020-172",
        "CIDADE": "CAXIAS DO SUL",
        "UF": "RS",
    },
    "ONCOSUPORT": {
        "ENDERECO": "Rua Pinheiro Machado, 2076 - Centro",
        "CEP": "95020-172",
        "CIDADE": "CAXIAS DO SUL",
        "UF": "RS",
    },
    "BIOVET LABORATORIOS LTDA (VERTÁ)": {
        "ENDERECO": "Av. Brasil Oeste, 1525 - Boqueirão (Instituto Vertá)",
        "CEP": "99025-003",
        "CIDADE": "PASSO FUNDO",
        "UF": "RS",
    },
    "CENTRO CLINICO VETERINARIO LTDA ( LATE MAIS AUUTO)": {
        "ENDERECO": "Av. Plínio Brasil Milano, 1185 - Higienópolis",
        "CEP": "90520-002",
        "CIDADE": "PORTO ALEGRE",
        "UF": "RS",
    },
    "EM BACKUP HMV": {
        "ENDERECO": "Rua Ramiro Barcelos, 910 - Moinhos de Vento (Hosp. Moinhos de Vento)",
        "CEP": "90035-001",
        "CIDADE": "PORTO ALEGRE",
        "UF": "RS",
    },
    "EM BACKUP HMD": {
        "ENDERECO": "Rua José de Alencar, 286 - Menino Deus (Hosp. Mãe de Deus)",
        "CEP": "90880-481",
        "CIDADE": "PORTO ALEGRE",
        "UF": "RS",
    },
}

# Coordenadas aproximadas (Latitude, Longitude) das cidades para ordenação geográfica inteligente da rota
# usando o algoritmo do Vizinho Mais Próximo (Nearest-Neighbor) a partir da Sede da LYDA em Porto Alegre
CITY_COORDS_RS_SC: Dict[str, Tuple[float, float]] = {
    "PORTO ALEGRE": (-30.0277, -51.2287),
    "CANOAS": (-29.9178, -51.1836),
    "SÃO LEOPOLDO": (-29.7604, -51.1472),
    "SAO LEOPOLDO": (-29.7604, -51.1472),
    "NOVO HAMBURGO": (-29.6875, -51.1328),
    "CAMPO BOM": (-29.6747, -51.0606),
    "TRIUNFO": (-29.9419, -51.7117),
    "SÃO SEBASTIÃO CAI": (-29.5869, -51.3756),
    "SAO SEBASTIAO DO CAI": (-29.5869, -51.3756),
    "TEUTÔNIA": (-29.4481, -51.8064),
    "TEUTONIA": (-29.4481, -51.8064),
    "FLORES DA CUNHA": (-29.0289, -51.1817),
    "ANTÔNIO PRADO": (-28.8583, -51.2828),
    "ANTONIO PRADO": (-28.8583, -51.2828),
    "VERANÓPOLIS": (-28.9358, -51.5489),
    "VERANOPOLIS": (-28.9358, -51.5489),
    "PASSO FUNDO": (-28.2628, -52.4067),
    "TAPEJARA": (-28.0681, -52.0139),
    "SANANDUVA": (-27.9497, -51.8067),
    "ERECHIM": (-27.6342, -52.2739),
    "CRUZ ALTA": (-28.6386, -53.6064),
    "SANTO ÂNGELO": (-28.2992, -54.2631),
    "SANTO ANGELO": (-28.2992, -54.2631),
    "RIO GRANDE": (-32.0350, -52.0986),
    "SANTA VITÓRIA DO PALMAR": (-33.5189, -53.3681),
    "SANTA VITORIA DO PALMAR": (-33.5189, -53.3681),
    "ARARANGUA": (-28.9356, -49.4919),
    "ARARANGUÁ": (-28.9356, -49.4919),
    "CRICIÚMA": (-28.6775, -49.3697),
    "CRICIUMA": (-28.6775, -49.3697),
}


def lookup_cep_viacep(raw_cep: str) -> Tuple[bool, Dict[str, str], str]:
    """
    Consulta o CEP informado na API pública gratuita ViaCEP (https://viacep.com.br)
    e retorna Logradouro, Bairro, Cidade e UF.
    """
    digits = re.sub(r"\D", "", raw_cep or "")
    if len(digits) != 8:
        return False, {}, "Digite um CEP válido com 8 números (ex: 90035-903)."
    url = f"https://viacep.com.br/ws/{digits}/json/"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "LydaIStatApp/2.0"})
        with urllib.request.urlopen(req, timeout=4.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("erro"):
            return False, {}, f"CEP {digits} não encontrado na base dos Correios."
        logradouro = (data.get("logradouro") or "").strip()
        bairro = (data.get("bairro") or "").strip()
        complemento = (data.get("complemento") or "").strip()
        localidade = (data.get("localidade") or "").strip().upper()
        uf = (data.get("uf") or "").strip().upper()
        cep_fmt = f"{digits[:5]}-{digits[5:]}"

        end_parts = [p for p in (logradouro, f"- {bairro}" if bairro else "") if p]
        endereco_sugerido = " ".join(end_parts).strip()
        return (
            True,
            {
                "ENDERECO": endereco_sugerido,
                "BAIRRO": bairro,
                "COMPLEMENTO": complemento,
                "CIDADE": localidade,
                "UF": uf,
                "CEP": cep_fmt,
            },
            f"CEP {cep_fmt} localizado: {endereco_sugerido} ({localidade}/{uf})",
        )
    except Exception as e:
        return False, {}, f"Não foi possível consultar o CEP online agora ({e}). Você pode digitar o endereço manualmente."


def get_suggested_hospital_address(cliente_name: str) -> Optional[Dict[str, str]]:
    """Verifica se o cliente consta na tabela de endereços pré-conhecidos da Lyda."""
    key = (cliente_name or "").strip().upper()
    if not key:
        return None
    if key in KNOWN_HOSPITAL_ADDRESSES:
        return dict(KNOWN_HOSPITAL_ADDRESSES[key])
    for k, val in KNOWN_HOSPITAL_ADDRESSES.items():
        if k in key or key in k:
            return dict(val)
    return None


def format_full_destination_for_maps(stop: Dict[str, Any]) -> str:
    """
    Monta a string ideal de endereço para o Google Maps / Waze localizar o hospital sem erro.
    Prioriza: Endereço Completo + Cidade + UF + CEP.
    Se o endereço de rua estiver em branco, usa: Nome do Hospital + Cidade + UF + Brasil.
    """
    cliente = (stop.get("CLIENTE") or "").strip()
    endereco = (stop.get("ENDERECO") or "").strip()
    cidade = (stop.get("CIDADE") or "PORTO ALEGRE").strip()
    uf = (stop.get("UF") or "RS").strip()
    cep = (stop.get("CEP") or "").strip()

    if endereco:
        parts = [endereco]
        if cidade:
            parts.append(f"{cidade} - {uf}" if uf else cidade)
        if cep:
            parts.append(cep)
        parts.append("Brasil")
        return ", ".join(parts)

    # Fallback inteligente pelo nome do Hospital + Cidade + UF
    parts = []
    if cliente and "SEM CLIENTE" not in cliente.upper() and "ESTOQUE" not in cliente.upper():
        parts.append(cliente)
    if cidade:
        parts.append(f"{cidade} - {uf}" if uf else cidade)
    parts.append("Brasil")
    return ", ".join(parts)


def group_items_into_route_stops(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Agrupa múltiplos equipamentos i-STAT que estão no mesmo Hospital / Cliente / Endereço
    em uma única Parada da Rota, listando todos os seriais e setores que a enfermeira
    precisa atualizar naquele local.
    """
    grouped: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for it in items:
        cliente = (it.get("CLIENTE") or "SEM CLIENTE (ESTOQUE LYDA)").strip()
        cidade = (it.get("CIDADE") or "PORTO ALEGRE").strip().upper()
        uf = (it.get("UF") or "RS").strip().upper()
        endereco = (it.get("ENDERECO") or "").strip()
        cep = (it.get("CEP") or "").strip()
        contato = (it.get("CONTATO_LOCAL") or "").strip()

        # Preenche automaticamente se o hospital for conhecido e ainda estiver sem rua
        if not endereco:
            sug = get_suggested_hospital_address(cliente)
            if sug:
                endereco = sug.get("ENDERECO", "")
                cep = cep or sug.get("CEP", "")
                cidade = cidade or sug.get("CIDADE", "PORTO ALEGRE")
                uf = uf or sug.get("UF", "RS")

        group_key = (cliente.upper(), cidade.upper())
        if group_key not in grouped:
            grouped[group_key] = {
                "CLIENTE": cliente,
                "ENDERECO": endereco,
                "CEP": cep,
                "CIDADE": cidade,
                "UF": uf,
                "CONTATO_LOCAL": contato,
                "SETORES": [],
                "ITEMS": [],
            }
        else:
            if endereco and not grouped[group_key]["ENDERECO"]:
                grouped[group_key]["ENDERECO"] = endereco
            if cep and not grouped[group_key]["CEP"]:
                grouped[group_key]["CEP"] = cep
            if contato and not grouped[group_key]["CONTATO_LOCAL"]:
                grouped[group_key]["CONTATO_LOCAL"] = contato

        setor = (it.get("SETOR") or "").strip()
        if setor and setor not in grouped[group_key]["SETORES"]:
            grouped[group_key]["SETORES"].append(setor)
        grouped[group_key]["ITEMS"].append(it)

    return list(grouped.values())


def _haversine_km(c1: Tuple[float, float], c2: Tuple[float, float]) -> float:
    lat1, lon1 = math.radians(c1[0]), math.radians(c1[1])
    lat2, lon2 = math.radians(c2[0]), math.radians(c2[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371.0 * (2 * math.asin(math.sqrt(a)))


# Caches em memória para geocodificação, rotas OSRM e tiles do Google Maps
_GEOCODE_MEM_CACHE: Dict[str, Tuple[float, float]] = {}
_OSRM_ROUTE_MEM_CACHE: Dict[str, Dict[str, Any]] = {}
_MAP_TILE_MEM_CACHE: Dict[Tuple[str, int, int, int], Any] = {}

# Coordenadas aproximadas por prefixo de CEP (3 dígitos) em Porto Alegre / Região Metropolitana
POA_CEP_PREFIX_COORDS: Dict[str, Tuple[float, float]] = {
    "900": (-30.0318, -51.2215),  # Centro / Bom Fim / Santa Cecília
    "901": (-30.0525, -51.2280),  # Cidade Baixa / Praia de Belas / Menino Deus
    "902": (-29.9965, -51.1920),  # Navegantes / Farrapos / Humaitá
    "904": (-30.0285, -51.1865),  # Auxiliadora / Moinhos / Bela Vista / Petrópolis
    "905": (-30.0155, -51.1910),  # São João / Higienópolis / Passo d'Areia
    "906": (-30.0560, -51.1875),  # Santana / Partenon / Jardim Botânico
    "908": (-30.0725, -51.2360),  # Menino Deus / Santa Tereza / Cristal
    "910": (-29.9980, -51.1490),  # Cristo Redentor / Lindóia / São Sebastião
    "911": (-29.9912, -51.1278),  # Sarandi / Rubem Berta
    "912": (-30.0250, -51.1240),  # Jardim Itu / Sabará / Morro Santana
    "913": (-30.0245, -51.1610),  # Chácara das Pedras / Três Figueiras / Boa Vista
    "914": (-30.0445, -51.1520),  # Jardim Carvalho / Bom Jesus
    "915": (-30.0780, -51.1410),  # Agronomia / Lomba do Pinheiro
    "917": (-30.1150, -51.2250),  # Cavalhada / Tristeza / Ipanema / Cascata
}


def resolve_address_coordinates(
    address_str: str = "",
    cep_str: str = "",
    city_str: str = "PORTO ALEGRE",
    client_name: str = "",
    allow_network: bool = False,
) -> Tuple[float, float]:
    """
    Resolve as coordenadas exatas (Latitude, Longitude) de um endereço, CEP ou Hospital/Cliente.
    1. Verifica tabela de coordenadas exatas (por CEP, Nome do Hospital ou Logradouro).
    2. Verifica cache em memória.
    3. Se allow_network=True, consulta Nominatim OpenStreetMap (com timeout rápido).
    4. Fallback por prefixo de CEP de Porto Alegre ou coordenadas da Cidade (RS/SC).
    """
    cep_clean = re.sub(r"\D", "", cep_str or "")
    cep_fmt = f"{cep_clean[:5]}-{cep_clean[5:]}" if len(cep_clean) == 8 else ""
    cli_up = (client_name or "").strip().upper()
    addr_up = (address_str or "").strip().upper()
    city_up = (city_str or "PORTO ALEGRE").strip().upper()

    # 1. Busca direta por CEP no dicionário de coordenadas exatas
    if cep_fmt and cep_fmt in EXACT_HOSPITAL_COORDS:
        return EXACT_HOSPITAL_COORDS[cep_fmt]
    if cep_clean and cep_clean in EXACT_HOSPITAL_COORDS:
        return EXACT_HOSPITAL_COORDS[cep_clean]

    # Extrai CEP de dentro da string de endereço se houver (ex: Sede LYDA)
    m_cep = re.search(r"(\d{5})-?(\d{3})", addr_up)
    if m_cep:
        emb_fmt = f"{m_cep.group(1)}-{m_cep.group(2)}"
        if emb_fmt in EXACT_HOSPITAL_COORDS:
            return EXACT_HOSPITAL_COORDS[emb_fmt]
        if not cep_clean:
            cep_clean = f"{m_cep.group(1)}{m_cep.group(2)}"

    # 2. Busca pelo nome do Hospital / Cliente ou trecho de rua conhecido
    if cli_up and cli_up in EXACT_HOSPITAL_COORDS:
        return EXACT_HOSPITAL_COORDS[cli_up]
    for k, coords in EXACT_HOSPITAL_COORDS.items():
        if len(k) > 8 and ((cli_up and (k in cli_up or cli_up in k)) or (addr_up and k in addr_up)):
            return coords

    # Verifica endereço sugerido do hospital
    if cli_up:
        sug = get_suggested_hospital_address(cli_up)
        if sug:
            sug_cep = sug.get("CEP", "")
            if sug_cep in EXACT_HOSPITAL_COORDS:
                return EXACT_HOSPITAL_COORDS[sug_cep]

    cache_key = f"{addr_up}|{cep_clean}|{city_up}|{cli_up}"
    if cache_key in _GEOCODE_MEM_CACHE:
        return _GEOCODE_MEM_CACHE[cache_key]

    # 3. Consulta online opcional via Nominatim
    if allow_network and (addr_up or cep_clean):
        q_str = f"{address_str}, {city_str}, RS, Brasil" if address_str else f"{cep_clean}, {city_str}, Brasil"
        url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
            {"q": q_str, "format": "json", "limit": "1", "countrycodes": "br"}
        )
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "LydaIStatApp/2.5"})
            with urllib.request.urlopen(req, timeout=2.2) as resp:
                res = json.loads(resp.read().decode("utf-8"))
            if res and isinstance(res, list):
                lat = float(res[0]["lat"])
                lon = float(res[0]["lon"])
                _GEOCODE_MEM_CACHE[cache_key] = (lat, lon)
                return (lat, lon)
        except Exception:
            pass

    # 4. Fallback por prefixo de CEP em Porto Alegre ou coordenadas da cidade
    if len(cep_clean) >= 3 and cep_clean[:3] in POA_CEP_PREFIX_COORDS:
        base_lat, base_lon = POA_CEP_PREFIX_COORDS[cep_clean[:3]]
        # Pequeno deslocamento determinístico pelos últimos dígitos do CEP para não sobrepor pinos
        offset_seed = int(cep_clean[-3:]) if len(cep_clean) >= 6 and cep_clean[-3:].isdigit() else 0
        d_lat = ((offset_seed % 19) - 9) * 0.0007
        d_lon = (((offset_seed // 19) % 19) - 9) * 0.0007
        coords = (base_lat + d_lat, base_lon + d_lon)
        _GEOCODE_MEM_CACHE[cache_key] = coords
        return coords

    city_coord = CITY_COORDS_RS_SC.get(city_up, (-30.0277, -51.2287))
    _GEOCODE_MEM_CACHE[cache_key] = city_coord
    return city_coord


def resolve_stop_coordinates(stop: Dict[str, Any], allow_network: bool = False) -> Tuple[float, float]:
    """Resolve as coordenadas (Latitude, Longitude) de uma parada da rota."""
    return resolve_address_coordinates(
        address_str=stop.get("ENDERECO", ""),
        cep_str=stop.get("CEP", ""),
        city_str=stop.get("CIDADE", "PORTO ALEGRE"),
        client_name=stop.get("CLIENTE", ""),
        allow_network=allow_network,
    )


def optimize_stops_order(
    stops: List[Dict[str, Any]],
    origin_address: str = DEFAULT_LYDA_SEDE_ADDRESS,
) -> List[Dict[str, Any]]:
    """
    Ordena as paradas usando heurística do Vizinho Mais Próximo (Nearest-Neighbor TSP)
    com coordenadas exatas de rua/CEP partindo da Sede da LYDA para minimizar o deslocamento.
    """
    if len(stops) <= 1:
        return list(stops)

    remaining = list(stops)
    ordered: List[Dict[str, Any]] = []
    cur_coords = resolve_address_coordinates(address_str=origin_address or DEFAULT_LYDA_SEDE_ADDRESS)

    while remaining:
        best_idx = 0
        best_dist = float("inf")
        for idx, st in enumerate(remaining):
            st_coords = resolve_stop_coordinates(st, allow_network=False)
            d = _haversine_km(cur_coords, st_coords)
            if d < best_dist - 0.05:
                best_dist = d
                best_idx = idx
        chosen = remaining.pop(best_idx)
        ordered.append(chosen)
        cur_coords = resolve_stop_coordinates(chosen, allow_network=False)

    return ordered


def compute_route_metrics_and_geometry(
    origin_address: str,
    stops: List[Dict[str, Any]],
    return_to_origin: bool = True,
    allow_network: bool = True,
) -> Dict[str, Any]:
    """
    Calcula a rota viária completa entre a Sede da LYDA e todas as paradas:
    - Consulta a malha viária real no OSRM (Open Source Routing Machine) quando online,
      retornando a polilinha exata pelas ruas, distância em km e tempo estimado em minutos
      de cada trecho (leg) e do roteiro total.
    - Possui fallback instantâneo offline (Haversine * fator viário urbano 1.32x e 32 km/h).
    """
    origin_clean = (origin_address or DEFAULT_LYDA_SEDE_ADDRESS).strip()
    origin_coord = resolve_address_coordinates(address_str=origin_clean, allow_network=False)
    stop_coords = [resolve_stop_coordinates(st, allow_network=False) for st in stops]

    all_waypoints: List[Tuple[float, float]] = [origin_coord] + list(stop_coords)
    if return_to_origin and stops:
        all_waypoints.append(origin_coord)

    cache_key = (
        origin_clean
        + "|"
        + ";".join(f"{c[0]:.5f},{c[1]:.5f}" for c in all_waypoints)
        + f"|ret={int(bool(return_to_origin))}"
    )
    if cache_key in _OSRM_ROUTE_MEM_CACHE:
        return _OSRM_ROUTE_MEM_CACHE[cache_key]

    legs_info: List[Dict[str, Any]] = []
    outbound_polyline: List[Tuple[float, float]] = []
    return_polyline: List[Tuple[float, float]] = []
    total_km = 0.0
    total_min = 0
    source = "ESTIMADO"

    if allow_network and len(all_waypoints) >= 2:
        try:
            coords_param = ";".join(f"{c[1]:.6f},{c[0]:.6f}" for c in all_waypoints)
            url = f"https://router.project-osrm.org/route/v1/driving/{coords_param}?overview=full&geometries=geojson&steps=false"
            req = urllib.request.Request(url, headers={"User-Agent": "LydaIStatApp/2.5"})
            with urllib.request.urlopen(req, timeout=3.2) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if data.get("code") == "Ok" and data.get("routes"):
                route_obj = data["routes"][0]
                osrm_legs = route_obj.get("legs", [])
                raw_geom = route_obj.get("geometry", {}).get("coordinates", [])
                full_poly = [( float(pt[1]), float(pt[0]) ) for pt in raw_geom]

                for idx, leg in enumerate(osrm_legs):
                    d_km = round(float(leg.get("distance", 0.0)) / 1000.0, 1)
                    dur_m = max(2, int(round(float(leg.get("duration", 0.0)) / 60.0)))
                    is_ret = bool(return_to_origin and idx == len(osrm_legs) - 1 and idx == len(stops))
                    from_label = "Sede LYDA" if idx == 0 else f"Parada #{idx} ({stops[idx - 1].get('CLIENTE', '')[:24]})"
                    to_label = (
                        "Retorno à Sede LYDA"
                        if is_ret
                        else f"Parada #{idx + 1} ({stops[idx].get('CLIENTE', '')[:24]})"
                    )
                    legs_info.append(
                        {
                            "leg_index": idx,
                            "from_name": from_label,
                            "to_name": to_label,
                            "distance_km": d_km,
                            "duration_min": dur_m,
                            "label": f"{d_km:.1f} km (~{dur_m} min)",
                            "is_return_leg": is_ret,
                        }
                    )
                    total_km += d_km
                    total_min += dur_m

                if return_to_origin and len(all_waypoints) >= 3 and full_poly:
                    # Separa o trecho de ida do trecho de retorno à sede procurando o ponto mais próximo da última parada
                    last_stop_c = stop_coords[-1]
                    best_split = len(full_poly) - 1
                    best_d = float("inf")
                    # Procura na segunda metade da polilinha o vértice na última parada
                    start_search = max(1, len(full_poly) // 3)
                    for p_i in range(start_search, len(full_poly)):
                        d_p = (full_poly[p_i][0] - last_stop_c[0]) ** 2 + (full_poly[p_i][1] - last_stop_c[1]) ** 2
                        if d_p < best_d:
                            best_d = d_p
                            best_split = p_i
                    outbound_polyline = full_poly[: best_split + 1]
                    return_polyline = full_poly[best_split:]
                else:
                    outbound_polyline = full_poly
                    return_polyline = []

                source = "OSRM"
        except Exception:
            pass

    # Fallback instantâneo caso sem internet ou OSRM indisponível
    if not legs_info and len(all_waypoints) >= 2:
        for idx in range(len(all_waypoints) - 1):
            c1 = all_waypoints[idx]
            c2 = all_waypoints[idx + 1]
            straight_km = _haversine_km(c1, c2)
            road_km = round(max(0.6, straight_km * 1.32), 1)
            avg_speed_kmh = 30.0 if road_km < 25.0 else 65.0
            dur_m = max(3, int(round((road_km / avg_speed_kmh) * 60.0)))
            is_ret = bool(return_to_origin and idx == len(all_waypoints) - 2 and idx == len(stops))
            from_label = "Sede LYDA" if idx == 0 else f"Parada #{idx} ({stops[idx - 1].get('CLIENTE', '')[:24]})"
            to_label = (
                "Retorno à Sede LYDA"
                if is_ret
                else f"Parada #{idx + 1} ({stops[idx].get('CLIENTE', '')[:24]})"
            )
            legs_info.append(
                {
                    "leg_index": idx,
                    "from_name": from_label,
                    "to_name": to_label,
                    "distance_km": road_km,
                    "duration_min": dur_m,
                    "label": f"{road_km:.1f} km (~{dur_m} min)",
                    "is_return_leg": is_ret,
                }
            )
            total_km += road_km
            total_min += dur_m

        outbound_polyline = [origin_coord] + list(stop_coords)
        if return_to_origin and stop_coords:
            return_polyline = [stop_coords[-1], origin_coord]

    result = {
        "origin_coord": origin_coord,
        "stop_coords": stop_coords,
        "legs": legs_info,
        "total_distance_km": round(total_km, 1),
        "total_duration_min": int(total_min),
        "outbound_polyline": outbound_polyline,
        "return_polyline": return_polyline,
        "source": source,
    }
    if source == "OSRM" or not allow_network:
        _OSRM_ROUTE_MEM_CACHE[cache_key] = result
    return result


def _latlon_to_world_px(lat: float, lon: float, zoom: int) -> Tuple[float, float]:
    lat_clamped = max(-85.0511, min(85.0511, float(lat)))
    lat_rad = math.radians(lat_clamped)
    n = 2.0 ** zoom
    x = (float(lon) + 180.0) / 360.0 * n * 256.0
    y = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n * 256.0
    return x, y


def _fetch_single_map_tile(
    z: int,
    tx: int,
    ty: int,
    cache_dir: str,
    allow_network: bool = True,
    map_layer: str = "m",
):
    """
    Baixa o tile diretamente do servidor oficial de mapas do Google Maps (mt0..mt3.google.com):
      - map_layer = 'm': Google Maps Padrão (Ruas, Avenidas, Bairros e POIs em Português pt-BR)
      - map_layer = 'y': Google Maps Satélite Híbrido (Foto de Satélite + Ruas)
      - map_layer = 'p': Google Maps Terreno / Relevo
    """
    import io
    from PIL import Image

    layer_clean = map_layer if map_layer in ("m", "y", "p", "s") else "m"
    n_tiles = 2 ** z
    tx_wrapped = tx % n_tiles
    if ty < 0 or ty >= n_tiles:
        return Image.new("RGB", (256, 256), "#E2E8F0")

    mem_key = (layer_clean, z, tx_wrapped, ty)
    if mem_key in _MAP_TILE_MEM_CACHE:
        return _MAP_TILE_MEM_CACHE[mem_key]

    os.makedirs(cache_dir, exist_ok=True)
    disk_path = os.path.join(cache_dir, f"gmaps_{layer_clean}_{z}_{tx_wrapped}_{ty}.png")
    if os.path.exists(disk_path):
        try:
            with Image.open(disk_path) as im:
                rgb_im = im.convert("RGB")
                _MAP_TILE_MEM_CACHE[mem_key] = rgb_im
                return rgb_im
        except Exception:
            pass

    if allow_network:
        srv_idx = (tx_wrapped + ty) % 4
        urls = [
            f"https://mt{srv_idx}.google.com/vt/lyrs={layer_clean}&hl=pt-BR&x={tx_wrapped}&y={ty}&z={z}",
            f"https://mt0.google.com/vt/lyrs={layer_clean}&hl=pt-BR&x={tx_wrapped}&y={ty}&z={z}",
            f"https://tile.openstreetmap.org/{z}/{tx_wrapped}/{ty}.png",
        ]
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9",
        }
        for u in urls:
            try:
                req = urllib.request.Request(u, headers=headers)
                with urllib.request.urlopen(req, timeout=2.8) as resp:
                    raw_bytes = resp.read()
                with Image.open(io.BytesIO(raw_bytes)) as im:
                    rgb_im = im.convert("RGB")
                with open(disk_path, "wb") as f:
                    f.write(raw_bytes)
                _MAP_TILE_MEM_CACHE[mem_key] = rgb_im
                return rgb_im
            except Exception:
                continue

    return None


def render_route_map_pil_image(
    workspace_dir: str,
    origin_address: str,
    stops: List[Dict[str, Any]],
    return_to_origin: bool = True,
    width: int = 560,
    height: int = 340,
    zoom_offset: int = 0,
    pan_offset_px: Tuple[int, int] = (0, 0),
    map_layer: str = "m",
    selected_stop_idx: Optional[int] = None,
    route_metrics: Optional[Dict[str, Any]] = None,
    allow_network: bool = True,
) -> Tuple[Any, List[Dict[str, Any]], Dict[str, Any]]:
    """
    Renderiza o próprio Google Maps (Ruas ou Satélite Híbrido em pt-BR) dentro do quadro do sistema:
    - Usa os tiles oficiais do Google Maps (mt0..mt3.google.com/vt/lyrs=m&hl=pt-BR)
    - Suporta arrastar com o mouse (pan_offset_px), zoom com scroll/botões e alternância Mapa/Satélite
    - Desenha o trajeto viário azul oficial do Google Maps pelas ruas (OSRM) + pinos numerados #1..#N
    - Retorna (pil_image, pin_hitboxes, route_metrics)
    """
    from concurrent.futures import ThreadPoolExecutor
    from PIL import Image, ImageDraw, ImageFont

    metrics = route_metrics or compute_route_metrics_and_geometry(
        origin_address=origin_address,
        stops=stops,
        return_to_origin=return_to_origin,
        allow_network=allow_network,
    )
    origin_coord = metrics["origin_coord"]
    stop_coords = metrics["stop_coords"]
    outbound_poly = metrics["outbound_polyline"]
    return_poly = metrics["return_polyline"]
    legs = metrics["legs"]

    all_pts = [origin_coord] + list(stop_coords) + list(outbound_poly)
    focus_pts = all_pts if all_pts else [origin_coord]

    lats = [p[0] for p in focus_pts]
    lons = [p[1] for p in focus_pts]
    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)

    # Escolhe o nível de zoom ideal que enquadra todos os pontos com margem confortável
    pad_x = 110
    pad_y = 85
    avail_w = max(160, width - pad_x)
    avail_h = max(120, height - pad_y)

    chosen_zoom = 13
    for z in range(16, 4, -1):
        x1, y1 = _latlon_to_world_px(max_lat, min_lon, z)
        x2, y2 = _latlon_to_world_px(min_lat, max_lon, z)
        if abs(x2 - x1) <= avail_w and abs(y2 - y1) <= avail_h:
            chosen_zoom = z
            break
    chosen_zoom = max(4, min(18, chosen_zoom + int(zoom_offset)))

    # Centro do mapa em pixels globais + deslocamento de arrasto do mouse (pan_offset_px)
    x_min_px, y_min_px = _latlon_to_world_px(max_lat, min_lon, chosen_zoom)
    x_max_px, y_max_px = _latlon_to_world_px(min_lat, max_lon, chosen_zoom)
    center_wx = ((x_min_px + x_max_px) / 2.0) - float(pan_offset_px[0])
    center_wy = ((y_min_px + y_max_px) / 2.0) - float(pan_offset_px[1])

    top_left_wx = center_wx - (width / 2.0)
    top_left_wy = center_wy - (height / 2.0)

    def to_canvas_xy(lat: float, lon: float) -> Tuple[float, float]:
        wx, wy = _latlon_to_world_px(lat, lon, chosen_zoom)
        return (wx - top_left_wx, wy - top_left_wy)

    canvas_im = Image.new("RGB", (width, height), "#E5E3DF")
    cache_dir = os.path.join(workspace_dir, ".map_cache")

    # Baixa/carrega os tiles do Google Maps em paralelo
    t_x0 = int(math.floor(top_left_wx / 256.0))
    t_y0 = int(math.floor(top_left_wy / 256.0))
    t_x1 = int(math.floor((top_left_wx + width) / 256.0))
    t_y1 = int(math.floor((top_left_wy + height) / 256.0))

    tile_coords = [(tx, ty) for tx in range(t_x0, t_x1 + 1) for ty in range(t_y0, t_y1 + 1)]
    tiles_loaded = 0

    if len(tile_coords) <= 36:
        with ThreadPoolExecutor(max_workers=8) as pool:
            futs = {
                (tx, ty): pool.submit(_fetch_single_map_tile, chosen_zoom, tx, ty, cache_dir, allow_network, map_layer)
                for (tx, ty) in tile_coords
            }
            for (tx, ty), fut in futs.items():
                try:
                    t_im = fut.result(timeout=3.2)
                    if t_im is not None:
                        paste_x = int(round(tx * 256 - top_left_wx))
                        paste_y = int(round(ty * 256 - top_left_wy))
                        canvas_im.paste(t_im, (paste_x, paste_y))
                        tiles_loaded += 1
                except Exception:
                    pass

    draw = ImageDraw.Draw(canvas_im, "RGBA")

    if tiles_loaded == 0:
        draw.rectangle([0, 0, width, height], fill=(241, 245, 249, 255))
        for gx in range(0, width, 40):
            draw.line([(gx, 0), (gx, height)], fill=(226, 232, 240, 255), width=1)
        for gy in range(0, height, 40):
            draw.line([(0, gy), (width, gy)], fill=(226, 232, 240, 255), width=1)

    def _load_font(sz: int, bold: bool = False):
        candidates = (
            [
                "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                "/System/Library/Fonts/Helvetica.ttc",
                "C:/Windows/Fonts/segoeui.ttf",
            ]
            if bold
            else [
                "/System/Library/Fonts/Supplemental/Arial.ttf",
                "/System/Library/Fonts/Helvetica.ttc",
                "C:/Windows/Fonts/segoeui.ttf",
            ]
        )
        for fp in candidates:
            if os.path.exists(fp):
                try:
                    return ImageFont.truetype(fp, sz)
                except Exception:
                    pass
        return ImageFont.load_default()

    f_hud = _load_font(11, bold=True)
    f_pin = _load_font(11, bold=True)
    f_lbl_b = _load_font(10, bold=True)
    f_lbl_s = _load_font(9, bold=False)

    # 1. LINHA DE RETORNO À SEDE (TRACEJADA DISCRETA) SE ATIVA
    if return_to_origin and len(return_poly) >= 2:
        ret_pts = [to_canvas_xy(p[0], p[1]) for p in return_poly]
        for i in range(len(ret_pts) - 1):
            x1, y1 = ret_pts[i]
            x2, y2 = ret_pts[i + 1]
            seg_len = math.hypot(x2 - x1, y2 - y1)
            if seg_len < 1:
                continue
            steps = max(1, int(seg_len // 9))
            for s_i in range(0, steps, 2):
                t0 = s_i / steps
                t1 = min(1.0, (s_i + 1) / steps)
                p0 = (x1 + (x2 - x1) * t0, y1 + (y2 - y1) * t0)
                p1 = (x1 + (x2 - x1) * t1, y1 + (y2 - y1) * t1)
                draw.line([p0, p1], fill=(255, 255, 255, 195), width=5)
                draw.line([p0, p1], fill=(100, 116, 139, 215), width=3)

    # 2. ROTA PRINCIPAL (AZUL GOOGLE MAPSDIRECTIONS #1A73E8 COM BORDA #174EA6)
    if len(outbound_poly) >= 2:
        poly_px = [to_canvas_xy(p[0], p[1]) for p in outbound_poly]
        draw.line(poly_px, fill=(23, 78, 166, 245), width=8, joint="curve")
        draw.line(poly_px, fill=(26, 115, 232, 255), width=5, joint="curve")

        # Setas direcionais estilo Google Maps ao longo da via
        accum_d = 0.0
        for i in range(len(poly_px) - 1):
            x1, y1 = poly_px[i]
            x2, y2 = poly_px[i + 1]
            d_seg = math.hypot(x2 - x1, y2 - y1)
            accum_d += d_seg
            if accum_d >= 85.0 and d_seg >= 8.0:
                accum_d = 0.0
                mx, my = (x1 + x2) / 2.0, (y1 + y2) / 2.0
                ang = math.atan2(y2 - y1, x2 - x1)
                ah = 5.5
                p_tip = (mx + math.cos(ang) * ah, my + math.sin(ang) * ah)
                p_l = (mx + math.cos(ang + 2.45) * ah, my + math.sin(ang + 2.45) * ah)
                p_r = (mx + math.cos(ang - 2.45) * ah, my + math.sin(ang - 2.45) * ah)
                draw.polygon([p_tip, p_l, p_r], fill=(255, 255, 255, 250), outline=(23, 78, 166, 255))

    # 3. PINOS COMPACTOS ESTILO GOOGLE MAPS (DEIXAM AS RUAS DO GOOGLE MAPS VISÍVEIS)
    hitboxes: List[Dict[str, Any]] = []
    occupied_boxes: List[Tuple[int, int, int, int]] = [(0, 0, width, 30)]

    def _find_non_overlapping_box(px: int, py: int, bw: int, bh: int) -> Tuple[int, int]:
        candidates = [
            (px + 14, py - bh // 2),
            (px - bw - 14, py - bh // 2),
            (px - bw // 2, py - bh - 15),
            (px - bw // 2, py + 15),
            (px + 12, py - bh - 10),
            (px - bw - 12, py - bh - 10),
            (px + 12, py + 10),
            (px - bw - 12, py + 10),
        ]
        best_pos = candidates[0]
        best_overlap = float("inf")
        for cx, cy in candidates:
            cx_c = max(6, min(width - bw - 6, cx))
            cy_c = max(32, min(height - bh - 22, cy))
            box = (cx_c - 2, cy_c - 2, cx_c + bw + 2, cy_c + bh + 2)
            overlap = 0
            for ob in occupied_boxes:
                ix = max(0, min(box[2], ob[2]) - max(box[0], ob[0]))
                iy = max(0, min(box[3], ob[3]) - max(box[1], ob[1]))
                overlap += ix * iy
            if overlap == 0:
                occupied_boxes.append(box)
                return cx_c, cy_c
            if overlap < best_overlap:
                best_overlap = overlap
                best_pos = (cx_c, cy_c)
        occupied_boxes.append((best_pos[0], best_pos[1], best_pos[0] + bw, best_pos[1] + bh))
        return best_pos

    ox, oy = to_canvas_xy(origin_coord[0], origin_coord[1])
    ox_i, oy_i = int(round(ox)), int(round(oy))
    occupied_boxes.append((ox_i - 15, oy_i - 15, ox_i + 15, oy_i + 15))
    for sc in stop_coords:
        sx, sy = to_canvas_xy(sc[0], sc[1])
        sx_i, sy_i = int(round(sx)), int(round(sy))
        occupied_boxes.append((sx_i - 15, sy_i - 15, sx_i + 15, sy_i + 15))

    # Pino da Sede da LYDA (Partida) - Estilo Google Maps Vermelho #EA4335
    draw.ellipse([ox_i - 13, oy_i - 13, ox_i + 13, oy_i + 13], fill=(255, 255, 255, 255), outline=(15, 23, 42, 255), width=2)
    draw.ellipse([ox_i - 10, oy_i - 10, ox_i + 10, oy_i + 10], fill=(234, 67, 53, 255))
    draw.text((ox_i, oy_i), "S", fill=(255, 255, 255, 255), font=f_pin, anchor="mm")
    hitboxes.append({"type": "origin", "index": -1, "x": ox_i, "y": oy_i, "r": 15, "title": "Sede da LYDA (Partida)"})

    sb_w, sb_h = 84, 18
    sl_x, sl_y = _find_non_overlapping_box(ox_i, oy_i, sb_w, sb_h)
    draw.rounded_rectangle([sl_x, sl_y, sl_x + sb_w, sl_y + sb_h], radius=4, fill=(15, 23, 42, 225), outline=(255, 255, 255, 230), width=1)
    draw.text((sl_x + 6, sl_y + sb_h // 2), "SEDE LYDA", fill=(255, 255, 255, 255), font=f_lbl_b, anchor="lm")

    # Pinos Numerados das Paradas (#1, #2, #3...)
    for idx, st in enumerate(stops):
        if idx >= len(stop_coords):
            break
        sx, sy = to_canvas_xy(stop_coords[idx][0], stop_coords[idx][1])
        sx_i, sy_i = int(round(sx)), int(round(sy))
        is_sel = (selected_stop_idx == idx)

        pin_r = 14 if is_sel else 12
        pin_fill = (217, 119, 6, 255) if is_sel else (26, 115, 232, 255)
        halo_fill = (254, 243, 199, 255) if is_sel else (255, 255, 255, 255)
        halo_out = (180, 83, 9, 255) if is_sel else (23, 78, 166, 255)

        if is_sel:
            draw.ellipse([sx_i - 18, sy_i - 18, sx_i + 18, sy_i + 18], fill=(245, 158, 11, 100))

        draw.ellipse([sx_i - pin_r, sy_i - pin_r, sx_i + pin_r, sy_i + pin_r], fill=halo_fill, outline=halo_out, width=2)
        draw.ellipse([sx_i - (pin_r - 3), sy_i - (pin_r - 3), sx_i + (pin_r - 3), sy_i + (pin_r - 3)], fill=pin_fill)
        draw.text((sx_i, sy_i), str(idx + 1), fill=(255, 255, 255, 255), font=f_pin, anchor="mm")

        # Rótulo compacto p/ não tapar as ruas do Google Maps
        cli_raw = (st.get("CLIENTE") or f"Parada {idx + 1}").strip()
        max_chars = 22 if is_sel else 16
        cli_short = cli_raw[:max_chars].rstrip() + ("…" if len(cli_raw) > max_chars else "")
        leg_str = f"+{legs[idx]['distance_km']:.1f}km ({legs[idx]['duration_min']}m)" if idx < len(legs) else ""

        if is_sel and leg_str:
            bw = max(122, min(176, len(cli_short) * 6 + 24))
            bh = 29
            lx, ly = _find_non_overlapping_box(sx_i, sy_i, bw, bh)
            draw.rounded_rectangle([lx, ly, lx + bw, ly + bh], radius=5, fill=(254, 243, 199, 245), outline=(217, 119, 6, 255), width=2)
            draw.text((lx + 6, ly + 8), f"#{idx + 1} {cli_short}", fill=(15, 23, 42, 255), font=f_lbl_b, anchor="lm")
            draw.text((lx + 6, ly + 21), leg_str, fill=(180, 83, 9, 255), font=f_lbl_s, anchor="lm")
        else:
            pill_txt = f"#{idx + 1} {cli_short}"
            bw = max(88, min(140, len(pill_txt) * 6 + 12))
            bh = 18
            lx, ly = _find_non_overlapping_box(sx_i, sy_i, bw, bh)
            draw.rounded_rectangle([lx, ly, lx + bw, ly + bh], radius=4, fill=(255, 255, 255, 232), outline=(26, 115, 232, 220), width=1)
            draw.text((lx + 5, ly + bh // 2), pill_txt, fill=(15, 23, 42, 255), font=f_lbl_b, anchor="lm")

        hitboxes.append(
            {
                "type": "stop",
                "index": idx,
                "x": sx_i,
                "y": sy_i,
                "r": 17,
                "box": (lx, ly, lx + bw, ly + bh),
                "title": f"#{idx + 1} {st.get('CLIENTE', '')}",
            }
        )

    # 4. BARRA FLUTUANTE ESTILO GOOGLE MAPS NO TOPO
    tot_km = metrics["total_distance_km"]
    tot_min = metrics["total_duration_min"]
    dur_fmt = f"{tot_min // 60}h {tot_min % 60:02d}min" if tot_min >= 60 else f"{tot_min} min"
    ret_badge = " (Ida + Volta)" if return_to_origin else " (Só Ida)"
    hud_text = f"Google Maps: {tot_km:.1f} km  •  ~{dur_fmt} de carro{ret_badge}"
    hud_w = min(width - 16, max(260, len(hud_text) * 6 + 24))
    draw.rounded_rectangle([8, 6, 8 + hud_w, 28], radius=5, fill=(15, 23, 42, 225), outline=(255, 255, 255, 180), width=1)
    draw.text((16, 17), hud_text, fill=(255, 255, 255, 255), font=f_hud, anchor="lm")

    # Rodapé discreto
    draw.rectangle([0, height - 17, width, height], fill=(15, 23, 42, 185))
    leg_txt = " Arraste com o mouse p/ mover o Google Maps  |  Scroll p/ Zoom  |  Clique no pino p/ selecionar ou 2x p/ abrir no navegador"
    draw.text((8, height - 8), leg_txt, fill=(241, 245, 249, 255), font=f_lbl_s, anchor="lm")

    return canvas_im, hitboxes, metrics


def build_google_maps_multi_stop_url(
    origin_address: str,
    stops: List[Dict[str, Any]],
    return_to_origin: bool = False,
) -> str:
    """
    Constrói a URL oficial do Google Maps Directions com múltiplas paradas:
    origin = Sede da LYDA
    waypoints = Paradas intermediárias separadas por '|'
    destination = Última parada (ou Sede da LYDA se return_to_origin=True)
    """
    if not stops:
        q = urllib.parse.quote_plus(origin_address)
        return f"https://www.google.com/maps/search/?api=1&query={q}"

    dest_strings = [format_full_destination_for_maps(s) for s in stops]
    origin_clean = (origin_address or DEFAULT_LYDA_SEDE_ADDRESS).strip()

    if return_to_origin:
        final_dest = origin_clean
        waypoints_list = dest_strings
    else:
        final_dest = dest_strings[-1]
        waypoints_list = dest_strings[:-1]

    params = {
        "api": "1",
        "origin": origin_clean,
        "destination": final_dest,
        "travelmode": "driving",
    }
    if waypoints_list:
        params["waypoints"] = "|".join(waypoints_list)

    return "https://www.google.com/maps/dir/?" + urllib.parse.urlencode(params, safe="|")


def build_single_stop_maps_url(stop: Dict[str, Any]) -> str:
    q = urllib.parse.quote_plus(format_full_destination_for_maps(stop))
    return f"https://www.google.com/maps/search/?api=1&query={q}"


def build_single_stop_waze_url(stop: Dict[str, Any]) -> str:
    q = urllib.parse.quote_plus(format_full_destination_for_maps(stop))
    return f"https://waze.com/ul?q={q}&navigate=yes"


def build_whatsapp_route_summary(
    origin_address: str,
    stops: List[Dict[str, Any]],
    nurse_name: str,
    update_version: str,
    route_date: str,
    return_to_origin: bool = False,
    route_metrics: Optional[Dict[str, Any]] = None,
) -> str:
    """Gera o texto formatado pronto para colar no WhatsApp da Enfermeira com o link da rota e distâncias."""
    maps_url = build_google_maps_multi_stop_url(origin_address, stops, return_to_origin=return_to_origin)
    metrics = route_metrics or compute_route_metrics_and_geometry(
        origin_address=origin_address,
        stops=stops,
        return_to_origin=return_to_origin,
        allow_network=False,
    )
    total_aparelhos = sum(len(s.get("ITEMS", [])) for s in stops)
    tot_km = metrics.get("total_distance_km", 0.0)
    tot_min = metrics.get("total_duration_min", 0)
    legs = metrics.get("legs", [])

    lines = [
        f"*ROTA DE ATUALIZAÇÃO i-STAT — LYDA*",
        f"Data: {route_date}  |  Enfermeira(o): {nurse_name}",
        f"Pacote / Versão: {update_version}",
        f"Partida (Sede LYDA): {origin_address}",
        f"Percurso Total Estimado: *{tot_km:.1f} km (~{tot_min} min de carro)*  |  {len(stops)} parada(s) ({total_aparelhos} aparelho(s))",
        "",
        "*PARADAS DO ROTEIRO:*",
    ]
    for idx, st in enumerate(stops, start=1):
        cli = st.get("CLIENTE", "-")
        end = st.get("ENDERECO") or "(Endereço pelo nome do hospital)"
        cid_uf = f"{st.get('CIDADE', '')}/{st.get('UF', '')}".strip("/")
        cep = st.get("CEP", "")
        contato = st.get("CONTATO_LOCAL", "")
        setores = ", ".join(st.get("SETORES", [])) or "-"
        seriais = ", ".join(f"{it.get('TIPO', '')[:3]}:{it.get('CODIGO', '')}" for it in st.get("ITEMS", []))
        leg_txt = f"  [{legs[idx - 1]['label']}]" if (idx - 1) < len(legs) else ""

        lines.append(f"*{idx}. {cli}* ({cid_uf}){leg_txt}")
        lines.append(f"   Endereço: {end}" + (f" - CEP {cep}" if cep else ""))
        lines.append(f"   Setor(es): {setores}" + (f" | Contato: {contato}" if contato else ""))
        lines.append(f"   Aparelhos ({len(st.get('ITEMS', []))}): {seriais}")
        lines.append("")

    if return_to_origin and len(legs) > len(stops):
        ret_leg = legs[-1]
        lines.append(f"*Retorno à Sede LYDA:* +{ret_leg['label']}")
        lines.append("")

    lines.append("*LINK DIRETO DA ROTA NO GOOGLE MAPS:*")
    lines.append(maps_url)
    return "\n".join(lines)


def generate_and_open_nurse_route_html(
    workspace_dir: str,
    origin_address: str,
    stops: List[Dict[str, Any]],
    nurse_name: str,
    update_version: str,
    route_date: str,
    return_to_origin: bool = False,
    observacoes_rota: str = "",
) -> str:
    """
    Gera a Folha de Rota & Checklist de Atualização da Enfermeira (HTML imprimível em A4 / PDF
    e interativo no celular com botões Google Maps e Waze em cada parada).
    """
    romaneios_dir = os.path.join(workspace_dir, "rotas_enfermeira")
    os.makedirs(romaneios_dir, exist_ok=True)

    now = datetime.now()
    protocol_num = now.strftime("%Y%m%d-%H%M%S")
    logo_uri = get_logo_base64_data_uri(get_default_logo_path())
    logo_img_tag = (
        f'<img src="{logo_uri}" alt="LYDA" style="height:46px; width:auto; object-fit:contain;" />'
        if logo_uri
        else '<div style="font-size:24px;font-weight:900;letter-spacing:2px;">LYDA</div>'
    )

    full_maps_url = build_google_maps_multi_stop_url(origin_address, stops, return_to_origin=return_to_origin)
    total_aparelhos = sum(len(s.get("ITEMS", [])) for s in stops)

    stops_html = ""
    for idx, st in enumerate(stops, start=1):
        cli = html.escape(st.get("CLIENTE", "-"))
        end = html.escape(st.get("ENDERECO") or "Endereço não informado (buscar pelo nome do Hospital)")
        cep = html.escape(st.get("CEP") or "-")
        cid_uf = html.escape(f"{st.get('CIDADE', '')} / {st.get('UF', '')}".strip(" /"))
        contato = html.escape(st.get("CONTATO_LOCAL") or "-")
        setores = html.escape(", ".join(st.get("SETORES", [])) or "-")

        single_maps = build_single_stop_maps_url(st)
        single_waze = build_single_stop_waze_url(st)

        items_rows = ""
        for it in st.get("ITEMS", []):
            tipo = html.escape(it.get("TIPO", ""))
            cod = html.escape(it.get("CODIGO", ""))
            setor_it = html.escape(it.get("SETOR", "-"))
            mod_it = html.escape(it.get("MODALIDADE", "-"))
            ult_att = html.escape(it.get("ULTIMA_ATUALIZACAO", "Pendente"))
            items_rows += f"""
            <tr>
                <td style="width:28px;text-align:center;"><span class="chk-box"></span></td>
                <td><strong>{tipo}</strong></td>
                <td class="mono">{cod}</td>
                <td>{setor_it}</td>
                <td>{mod_it}</td>
                <td>{ult_att}</td>
                <td>________________________</td>
            </tr>
            """

        stops_html += f"""
        <div class="stop-card">
            <div class="stop-header">
                <div>
                    <span class="stop-badge">PARADA #{idx}</span>
                    <span class="stop-title">{cli}</span>
                    <span class="stop-city">({cid_uf})</span>
                </div>
                <div class="no-print stop-links">
                    <a href="{single_maps}" target="_blank" class="btn-link btn-maps">Google Maps desta Parada</a>
                    <a href="{single_waze}" target="_blank" class="btn-link btn-waze">Abrir no Waze</a>
                </div>
            </div>
            <div class="stop-address-grid">
                <div><strong>Endereço Completo:</strong> {end} &nbsp;|&nbsp; <strong>CEP:</strong> {cep}</div>
                <div><strong>Setor(es):</strong> {setores} &nbsp;|&nbsp; <strong>Contato Local / Enfermagem:</strong> {contato}</div>
            </div>
            <table class="items-table">
                <thead>
                    <tr>
                        <th style="width:28px;">OK</th>
                        <th>Equipamento</th>
                        <th>Serial / Cód. Barras</th>
                        <th>Setor</th>
                        <th>Modalidade</th>
                        <th>Última Atualização</th>
                        <th>Versão Instalada / Assinatura Local</th>
                    </tr>
                </thead>
                <tbody>
                    {items_rows}
                </tbody>
            </table>
        </div>
        """

    retorno_txt = "Sim (Retorno à Sede da LYDA ao final)" if return_to_origin else "Não (Encerra na última parada)"

    html_doc = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<title>Rota de Atualização Enfermeira #{protocol_num} - LYDA i-STAT</title>
<style>
    @page {{ size: A4 portrait; margin: 12mm; }}
    * {{ box-sizing: border-box; font-family: 'Segoe UI', Arial, Helvetica, sans-serif; }}
    body {{ margin: 0; padding: 18px; color: #0F172A; background: #F1F5F9; }}
    .page {{
        max-width: 210mm;
        margin: 0 auto;
        background: #FFFFFF;
        padding: 20px 24px;
        border: 1px solid #CBD5E1;
        box-shadow: 0 4px 16px rgba(15, 23, 42, 0.08);
    }}
    .top-bar {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        border-bottom: 3px solid #0F172A;
        padding-bottom: 12px;
        margin-bottom: 14px;
    }}
    .doc-title {{
        font-size: 16px;
        font-weight: 800;
        color: #0F172A;
        text-transform: uppercase;
    }}
    .doc-sub {{
        font-size: 11px;
        color: #475569;
        margin-top: 3px;
        font-weight: 600;
    }}
    .route-summary {{
        background: #EFF6FF;
        border: 1px solid #BFDBFE;
        border-left: 5px solid #2563EB;
        border-radius: 6px;
        padding: 10px 14px;
        margin-bottom: 16px;
        font-size: 12px;
        line-height: 1.5;
    }}
    .stop-card {{
        border: 1px solid #CBD5E1;
        border-radius: 6px;
        margin-bottom: 14px;
        page-break-inside: avoid;
        overflow: hidden;
    }}
    .stop-header {{
        background: #0F172A;
        color: #FFFFFF;
        padding: 8px 12px;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }}
    .stop-badge {{
        background: #2563EB;
        color: #FFFFFF;
        font-size: 10px;
        font-weight: 800;
        padding: 3px 7px;
        border-radius: 4px;
        margin-right: 8px;
    }}
    .stop-title {{ font-size: 13px; font-weight: 800; }}
    .stop-city {{ font-size: 11px; color: #38BDF8; margin-left: 6px; font-weight: 700; }}
    .stop-address-grid {{
        background: #F8FAFC;
        padding: 8px 12px;
        font-size: 11px;
        border-bottom: 1px solid #E2E8F0;
        line-height: 1.45;
    }}
    .items-table {{
        width: 100%;
        border-collapse: collapse;
        font-size: 11px;
    }}
    .items-table th {{
        background: #F1F5F9;
        color: #334155;
        text-align: left;
        padding: 6px 8px;
        border-bottom: 1px solid #CBD5E1;
        font-size: 10px;
        text-transform: uppercase;
    }}
    .items-table td {{
        padding: 7px 8px;
        border-bottom: 1px solid #E2E8F0;
    }}
    .mono {{ font-family: 'Consolas', 'Courier New', monospace; font-weight: 700; font-size: 12px; }}
    .chk-box {{
        display: inline-block;
        width: 13px;
        height: 13px;
        border: 2px solid #0F172A;
        border-radius: 2px;
    }}
    .btn-link {{
        text-decoration: none;
        font-size: 10px;
        font-weight: 700;
        padding: 4px 8px;
        border-radius: 4px;
        margin-left: 4px;
    }}
    .btn-maps {{ background: #2563EB; color: #FFFFFF; }}
    .btn-waze {{ background: #0284C7; color: #FFFFFF; }}
    .no-print-bar {{
        max-width: 210mm;
        margin: 0 auto 14px auto;
        background: #0F172A;
        color: #FFFFFF;
        padding: 12px 16px;
        border-radius: 6px;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }}
    .btn-action {{
        background: #2563EB;
        color: #FFFFFF;
        border: none;
        padding: 8px 14px;
        font-size: 12px;
        font-weight: 700;
        border-radius: 4px;
        cursor: pointer;
        text-decoration: none;
        margin-left: 8px;
    }}
    .btn-green {{ background: #059669; }}
    .sig-row {{
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 32px;
        margin-top: 28px;
        padding-top: 12px;
    }}
    .sig-box {{
        border-top: 1px solid #334155;
        text-align: center;
        padding-top: 6px;
        font-size: 11px;
        color: #334155;
    }}
    @media print {{
        body {{ background: #FFFFFF; padding: 0; }}
        .page {{ box-shadow: none; border: none; padding: 0; max-width: 100%; }}
        .no-print, .no-print-bar {{ display: none !important; }}
    }}
</style>
</head>
<body>
    <div class="no-print-bar">
        <div>
            <strong>ROTA DA ENFERMEIRA PRONTA</strong> — Abra o mapa completo ou imprima / salve em PDF (Ctrl+P / Cmd+P)
        </div>
        <div>
            <a href="{full_maps_url}" target="_blank" class="btn-action btn-green">Abrir Rota Completa no Google Maps</a>
            <button class="btn-action" onclick="window.print()">Imprimir / Salvar em PDF</button>
        </div>
    </div>

    <div class="page">
        <div class="top-bar">
            <div>{logo_img_tag}</div>
            <div style="text-align:right;">
                <div class="doc-title">Roteiro &amp; Checklist de Atualização Externa i-STAT</div>
                <div class="doc-sub">Rota Nº {protocol_num} &nbsp;|&nbsp; Data Prevista: {html.escape(route_date)} &nbsp;|&nbsp; Enfermeira(o): {html.escape(nurse_name)}</div>
            </div>
        </div>

        <div class="route-summary">
            <div><strong>PONTO DE PARTIDA (SEDE LYDA):</strong> {html.escape(origin_address)}</div>
            <div><strong>PACOTE / VERSÃO DE ATUALIZAÇÃO:</strong> {html.escape(update_version)} &nbsp;|&nbsp; <strong>RETORNO À SEDE:</strong> {retorno_txt}</div>
            <div><strong>RESUMO DO ROTEIRO:</strong> {len(stops)} parada(s) / hospital(is) &nbsp;|&nbsp; <strong>TOTAL DE APARELHOS A ATUALIZAR:</strong> {total_aparelhos} equipamento(s)</div>
            {f'<div><strong>OBSERVAÇÕES DA ROTA:</strong> {html.escape(observacoes_rota)}</div>' if observacoes_rota else ''}
        </div>

        {stops_html}

        <div class="sig-row">
            <div class="sig-box">
                <strong>Enfermeira(o) Responsável — LYDA</strong><br/>
                {html.escape(nurse_name)}
            </div>
            <div class="sig-box">
                <strong>Conferência / Coordenação Técnica — LYDA</strong><br/>
                Data de Conclusão: ____/____/202___
            </div>
        </div>
    </div>
</body>
</html>
"""
    filepath = os.path.join(romaneios_dir, f"Rota_Enfermeira_iSTAT_{protocol_num}.html")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html_doc)

    webbrowser.open(f"file://{os.path.abspath(filepath)}")
    return filepath


def open_or_reveal_file(filepath: str, reveal_in_folder: bool = False):
    """Abre o arquivo PDF no visualizador padrão do sistema (ou mostra na pasta para arrastar p/ WhatsApp)."""
    import platform
    import subprocess

    abs_p = os.path.abspath(filepath)
    sys_name = platform.system().lower()
    try:
        if "darwin" in sys_name:
            if reveal_in_folder:
                subprocess.Popen(["open", "-R", abs_p])
            else:
                subprocess.Popen(["open", abs_p])
        elif "windows" in sys_name:
            if reveal_in_folder:
                subprocess.Popen(["explorer", f"/select,{abs_p}"])
            else:
                os.startfile(abs_p)  # type: ignore[attr-defined]
        else:
            webbrowser.open(f"file://{abs_p}")
    except Exception:
        webbrowser.open(f"file://{abs_p}")


def generate_nurse_route_pdf(
    workspace_dir: str,
    origin_address: str,
    stops: List[Dict[str, Any]],
    nurse_name: str,
    update_version: str,
    route_date: str,
    return_to_origin: bool = False,
    observacoes_rota: str = "",
    custom_output_path: Optional[str] = None,
    auto_open_pdf: bool = True,
    reveal_in_folder: bool = False,
    route_metrics: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Gera um arquivo .PDF nativo e profissional (Roteiro da Enfermeira LYDA i-STAT)
    contendo:
    - Logo oficial da LYDA e cabeçalho executivo
    - Link clicável direto dentro do PDF para abrir a Rota Completa no Google Maps
    - QR Code da Rota do Google Maps (para escanear pelo celular)
    - Mapa Visual da Rota (com ruas, trajeto azul, pinos numerados #1..#N e distância/tempo total)
    - Ficha detalhada de cada Parada (Hospital, Endereço completo, CEP, Distância/Tempo, Setor, Contato, Links Maps/Waze)
    - Tabela de todos os aparelhos i-STAT a atualizar em cada hospital + campos de check e assinatura
    """
    import io
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        Image as RLImage,
        KeepTogether,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    rotas_dir = os.path.join(workspace_dir, "rotas_enfermeira")
    os.makedirs(rotas_dir, exist_ok=True)

    now = datetime.now()
    date_slug = re.sub(r"[^0-9]", "-", route_date or now.strftime("%d-%m-%Y"))
    protocol_num = now.strftime("%Y%m%d_%H%M")
    if custom_output_path:
        pdf_path = custom_output_path
    else:
        pdf_path = os.path.join(rotas_dir, f"Roteiro_Enfermeira_LYDA_{date_slug}_{protocol_num}.pdf")

    full_maps_url = build_google_maps_multi_stop_url(origin_address, stops, return_to_origin=return_to_origin)
    metrics = route_metrics or compute_route_metrics_and_geometry(
        origin_address=origin_address,
        stops=stops,
        return_to_origin=return_to_origin,
        allow_network=True,
    )
    tot_km = metrics.get("total_distance_km", 0.0)
    tot_min = metrics.get("total_duration_min", 0)
    legs = metrics.get("legs", [])

    total_aparelhos = sum(len(s.get("ITEMS", [])) for s in stops)
    retorno_txt = "Sim (Retorno à Sede da LYDA no final)" if return_to_origin else "Não (Encerra na última parada)"

    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=A4,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=11 * mm,
        bottomMargin=11 * mm,
        title=f"Roteiro Enfermeira LYDA i-STAT - {route_date}",
        author="LYDA - Controle de Estoque i-STAT",
    )

    styles = getSampleStyleSheet()
    st_title = ParagraphStyle(
        "LydaTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=16,
        textColor=colors.HexColor("#0F172A"),
        alignment=2,
    )
    st_sub = ParagraphStyle(
        "LydaSub",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor("#475569"),
        alignment=2,
    )
    st_box = ParagraphStyle(
        "LydaBox",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#0F172A"),
    )
    st_maps_btn = ParagraphStyle(
        "LydaMapsBtn",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9.5,
        leading=13,
        textColor=colors.HexColor("#1D4ED8"),
    )
    st_stop_hdr = ParagraphStyle(
        "LydaStopHdr",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9.5,
        leading=13,
        textColor=colors.white,
    )
    st_stop_links = ParagraphStyle(
        "LydaStopLinks",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#93C5FD"),
        alignment=2,
    )
    st_addr = ParagraphStyle(
        "LydaAddr",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor("#1E293B"),
    )
    st_cell = ParagraphStyle(
        "LydaCell",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=10.5,
        textColor=colors.HexColor("#0F172A"),
    )
    st_cell_bold = ParagraphStyle(
        "LydaCellBold",
        parent=st_cell,
        fontName="Helvetica-Bold",
    )
    st_th = ParagraphStyle(
        "LydaTH",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#1E293B"),
    )

    story: List[Any] = []
    usable_w = A4[0] - 24 * mm

    # 1. CABEÇALHO COM LOGO DA LYDA E DADOS DA ROTA
    logo_p = get_default_logo_path()
    logo_flowable: Any = Paragraph("<b>LYDA</b>", st_title)
    if logo_p and os.path.exists(logo_p):
        try:
            from PIL import Image as PILImage

            with PILImage.open(logo_p) as pim:
                w_px, h_px = pim.size
            target_h = 13 * mm
            target_w = target_h * (w_px / max(1, h_px))
            logo_flowable = RLImage(logo_p, width=min(target_w, 55 * mm), height=target_h)
        except Exception:
            pass

    hdr_right = [
        Paragraph("ROTEIRO DE VISITA &amp; ATUALIZAÇÃO i-STAT (6 MESES)", st_title),
        Paragraph(
            f"Data da Rota: <b>{html.escape(route_date)}</b> &nbsp;|&nbsp; "
            f"Enfermeira(o): <b>{html.escape(nurse_name)}</b> &nbsp;|&nbsp; "
            f"Percurso: <b>{tot_km:.1f} km (~{tot_min} min)</b> &nbsp;|&nbsp; "
            f"<b>{len(stops)} parada(s) / {total_aparelhos} aparelho(s)</b>",
            st_sub,
        ),
    ]
    hdr_tbl = Table([[logo_flowable, hdr_right]], colWidths=[58 * mm, usable_w - 58 * mm])
    hdr_tbl.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LINEBELOW", (0, 0), (-1, 0), 2, colors.HexColor("#0F172A")),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
            ]
        )
    )
    story.append(hdr_tbl)
    story.append(Spacer(1, 3.5 * mm))

    # 2. QUADRO PRINCIPAL DE NAVEGAÇÃO GOOGLE MAPS + QR CODE
    qr_flowable: Any = Paragraph("", st_box)
    try:
        import qrcode

        qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=4, border=1)
        qr.add_data(full_maps_url)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="#0F172A", back_color="white")
        bio = io.BytesIO()
        qr_img.save(bio, format="PNG")
        bio.seek(0)
        qr_flowable = RLImage(bio, width=28 * mm, height=28 * mm)
    except Exception:
        pass

    route_chain_names = ["Sede LYDA"] + [f"#{i + 1} {st.get('CLIENTE', '')[:24]}" for i, st in enumerate(stops)]
    if return_to_origin:
        route_chain_names.append("Sede LYDA")
    chain_str = "  ->  ".join(route_chain_names)

    maps_safe_url = html.escape(full_maps_url, quote=True)
    summary_left = [
        Paragraph(f"<b>PONTO DE PARTIDA (SEDE LYDA):</b> {html.escape(origin_address)}", st_box),
        Paragraph(
            f"<b>DISTÂNCIA TOTAL ESTIMADA:</b> <b>{tot_km:.1f} km (~{tot_min} min de carro)</b> &nbsp;&nbsp;|&nbsp;&nbsp; "
            f"<b>RETORNO À SEDE:</b> {html.escape(retorno_txt)}",
            st_box,
        ),
        Paragraph(f"<b>PACOTE / ATUALIZAÇÃO:</b> {html.escape(update_version)}", st_box),
        Paragraph(f"<b>SEQUÊNCIA DE VISITAS:</b> {html.escape(chain_str)}", st_box),
    ]
    if observacoes_rota:
        summary_left.append(Paragraph(f"<b>OBSERVAÇÕES DA ROTA:</b> {html.escape(observacoes_rota)}", st_box))
    summary_left.append(Spacer(1, 1.5 * mm))
    summary_left.append(
        Paragraph(
            f'<link href="{maps_safe_url}"><u><b>&gt;&gt; CLIQUE AQUI PARA ABRIR A ROTA COMPLETA NO GOOGLE MAPS &lt;&lt;</b></u></link>',
            st_maps_btn,
        )
    )
    summary_left.append(
        Paragraph(
            '<font size="7.5" color="#475569">Dica: No celular ou WhatsApp, toque no link azul acima ou aponte a câmera para o QR Code ao lado para abrir o trajeto completo no Google Maps.</font>',
            st_box,
        )
    )

    qr_col = [
        qr_flowable,
        Paragraph('<font size="7" color="#1E3A8A"><b>QR Code Google Maps</b></font>', ParagraphStyle("QRC", parent=st_cell, alignment=1)),
    ]

    nav_tbl = Table([[summary_left, qr_col]], colWidths=[usable_w - 34 * mm, 34 * mm])
    nav_tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EFF6FF")),
                ("BOX", (0, 0), (-1, -1), 1.2, colors.HexColor("#2563EB")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (1, 0), (1, 0), "CENTER"),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    story.append(nav_tbl)
    story.append(Spacer(1, 3.5 * mm))

    # 2.5. MAPA VISUAL DO TRAJETO (RUAS + PINOS NUMERADOS #1..#N) EMBUTIDO NO PDF
    try:
        map_pil, _hb, _m = render_route_map_pil_image(
            workspace_dir=workspace_dir,
            origin_address=origin_address,
            stops=stops,
            return_to_origin=return_to_origin,
            width=720,
            height=300,
            zoom_offset=0,
            selected_stop_idx=None,
            route_metrics=metrics,
            allow_network=True,
        )
        map_bio = io.BytesIO()
        map_pil.save(map_bio, format="PNG")
        map_bio.seek(0)
        pdf_map_h = usable_w * (300.0 / 720.0)
        map_rl = RLImage(map_bio, width=usable_w, height=pdf_map_h)
        map_tbl = Table([[map_rl]], colWidths=[usable_w])
        map_tbl.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 1.0, colors.HexColor("#0F172A")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )
        story.append(map_tbl)
        story.append(Spacer(1, 4 * mm))
    except Exception:
        pass

    # 3. CARTÕES DE CADA PARADA (HOSPITAL / CLÍNICA + TABELA DE APARELHOS)
    for idx, st in enumerate(stops, start=1):
        cli = html.escape(st.get("CLIENTE", "-"))
        end = html.escape(st.get("ENDERECO") or "Endereço pelo nome do Hospital")
        cep = html.escape(st.get("CEP") or "-")
        cid_uf = html.escape(f"{st.get('CIDADE', '')} / {st.get('UF', '')}".strip(" /"))
        contato = html.escape(st.get("CONTATO_LOCAL") or "-")
        setores = html.escape(", ".join(st.get("SETORES", [])) or "-")
        leg_badge = ""
        if (idx - 1) < len(legs):
            leg_badge = f" &nbsp;&bull;&nbsp; <font color='#38BDF8'>Trecho: +{legs[idx - 1]['label']}</font>"

        single_maps_url = html.escape(build_single_stop_maps_url(st), quote=True)
        single_waze_url = html.escape(build_single_stop_waze_url(st), quote=True)

        # Barra superior da Parada
        stop_hdr_tbl = Table(
            [
                [
                    Paragraph(f"<b>PARADA #{idx} — {cli} ({cid_uf})</b>{leg_badge}", st_stop_hdr),
                    Paragraph(
                        f'<link href="{single_maps_url}"><u>[Abrir no Google Maps]</u></link> &nbsp; '
                        f'<link href="{single_waze_url}"><u>[Abrir no Waze]</u></link>',
                        st_stop_links,
                    ),
                ]
            ],
            colWidths=[usable_w * 0.70, usable_w * 0.30],
        )
        stop_hdr_tbl.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#0F172A")),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )

        # Bloco de Endereço e Contato da Parada
        addr_info_tbl = Table(
            [
                [
                    Paragraph(
                        f"<b>Endereço Completo:</b> {end} &nbsp;&nbsp;|&nbsp;&nbsp; <b>CEP:</b> {cep}<br/>"
                        f"<b>Setor(es) p/ Visitar:</b> {setores} &nbsp;&nbsp;|&nbsp;&nbsp; <b>Contato Local / Enfermagem:</b> {contato}",
                        st_addr,
                    )
                ]
            ],
            colWidths=[usable_w],
        )
        addr_info_tbl.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
                    ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#CBD5E1")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )

        # Tabela de Aparelhos desta Parada
        rows_data: List[List[Any]] = [
            [
                Paragraph("<b>OK</b>", st_th),
                Paragraph("<b>Equipamento</b>", st_th),
                Paragraph("<b>Nº de Série</b>", st_th),
                Paragraph("<b>Setor / Ala</b>", st_th),
                Paragraph("<b>Modalidade</b>", st_th),
                Paragraph("<b>Ciclo 6 Meses</b>", st_th),
                Paragraph("<b>Observações / Anotações</b>", st_th),
            ]
        ]

        for it in st.get("ITEMS", []):
            c_info = compute_update_cycle_info(it)
            obs_it = (it.get("OBSERVACOES") or "").strip()
            rows_data.append(
                [
                    Paragraph("[ &nbsp;&nbsp; ]", st_cell_bold),
                    Paragraph(html.escape(it.get("TIPO", "")), st_cell_bold),
                    Paragraph(html.escape(it.get("CODIGO", "")), st_cell_bold),
                    Paragraph(html.escape(it.get("SETOR", "-")), st_cell),
                    Paragraph(html.escape(it.get("MODALIDADE", "-")), st_cell),
                    Paragraph(html.escape(c_info["badge_text"]), st_cell),
                    Paragraph(html.escape(obs_it[:75] if obs_it else "_____________________"), st_cell),
                ]
            )

        col_w = [
            12 * mm,
            25 * mm,
            24 * mm,
            26 * mm,
            24 * mm,
            32 * mm,
            usable_w - (12 + 25 + 24 + 26 + 24 + 32) * mm,
        ]
        items_tbl = Table(rows_data, colWidths=col_w)
        items_tbl.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E2E8F0")),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )

        # Linha de Assinatura / Recebimento do Hospital
        sig_stop_tbl = Table(
            [
                [
                    Paragraph(
                        "<b>Conferência no Hospital:</b> Responsável Setor: __________________________ &nbsp;&nbsp; "
                        "Horário: ____:____ &nbsp;&nbsp; Assinatura/Carimbo: __________________________",
                        st_cell,
                    )
                ]
            ],
            colWidths=[usable_w],
        )
        sig_stop_tbl.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FFFFFF")),
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )

        story.append(KeepTogether([stop_hdr_tbl, addr_info_tbl, items_tbl, sig_stop_tbl, Spacer(1, 3.5 * mm)]))

    # 4. ASSINATURAS FINAIS DO ROTEIRO
    story.append(Spacer(1, 3 * mm))
    footer_sig = Table(
        [
            [
                Paragraph("_____________________________________________<br/><b>Enfermeira(o) Responsável — LYDA</b><br/>" + html.escape(nurse_name), ParagraphStyle("Sig1", parent=st_cell, alignment=1)),
                Paragraph("_____________________________________________<br/><b>Coordenação / Controle de Estoque i-STAT — LYDA</b><br/>Data de Conclusão: ____/____/202___", ParagraphStyle("Sig2", parent=st_cell, alignment=1)),
            ]
        ],
        colWidths=[usable_w * 0.5, usable_w * 0.5],
    )
    footer_sig.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 6)]))
    story.append(footer_sig)

    doc.build(story)

    if auto_open_pdf:
        open_or_reveal_file(pdf_path, reveal_in_folder=reveal_in_folder)
    return pdf_path
