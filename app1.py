import importlib
import streamlit as st
import pandas as pd
import os
import requests
import json
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path
from datetime import datetime, timedelta
from typing import Tuple, Optional
import time

# === PERFORMANCE TIMER ===
_perf_timers = {}

def _perf_start(label: str):
    """Inicia timer de performance para uma etapa."""
    _perf_timers[label] = time.perf_counter()

def _perf_end(label: str) -> float:
    """Finaliza timer e retorna tempo em segundos."""
    if label in _perf_timers:
        elapsed = time.perf_counter() - _perf_timers[label]
        del _perf_timers[label]
        return elapsed
    return 0.0

def _perf_log(label: str) -> str:
    """Finaliza timer e retorna mensagem formatada."""
    elapsed = _perf_end(label)
    return f"[PERF] {label}: {elapsed:.3f}s"
import utils  # garante pacote utils carregado
importlib.invalidate_caches()

from utils.ifdata_extractor import (
    gerar_periodos,
    processar_todos_periodos,
    construir_mapa_codinst,
    construir_mapa_codinst_multiperiodo,
    get_log_file_path,
    parece_codigo_instituicao,
)
# Sistema unificado de cache (capital e principal)
from utils.ifdata_cache import (
    # Cache principal (compat)
    carregar_cache,
    salvar_cache,
    get_cache_info,
    # Cache de capital
    gerar_periodos_capital,
    processar_todos_periodos_capital,
    salvar_cache_capital,
    carregar_cache_capital,
    get_capital_cache_info,
    ler_info_cache_capital,
    get_campos_capital_info,
    # Gerenciador unificado
    CacheManager,
    get_manager as get_cache_manager,
)
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import io
import base64
import subprocess
import re
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
import numpy as np
from PIL import Image as PILImage
from io import BytesIO

st.set_page_config(page_title="🏦 👀 toma.conta!", page_icon="👁️", layout="wide", initial_sidebar_state="expanded")

# CSS - sidebar fixa, tipografia e ícones corrigidos
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@100;200;300;400;500;600;700&display=swap');
    @import url('https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200');

    /* ===========================================
       SIDEBAR - esconde completamente quando recolhido
       =========================================== */
    [data-testid="stSidebar"][aria-expanded="false"] {
        display: none !important;
        width: 0 !important;
        min-width: 0 !important;
    }

    [data-testid="stSidebar"][aria-expanded="false"] > div {
        display: none !important;
    }

    /* Esconde decoração do header */
    [data-testid="stDecoration"] { display: none !important; }
    [data-testid="stToolbar"] { display: none !important; }

    /* ===========================================
       TIPOGRAFIA - IBM Plex Sans
       IMPORTANTE: Não aplicar em spans de ícones
       =========================================== */
    html, body, .stApp {
        font-family: 'IBM Plex Sans', sans-serif !important;
    }

    /* Elementos de texto (exclui spans que podem ser ícones) */
    div, p, label, input, select, textarea, button, h1, h2, h3, h4, h5, h6 {
        font-family: 'IBM Plex Sans', sans-serif !important;
    }

    p, label, div { font-weight: 300 !important; }
    h1, h2, h3, h4, h5, h6 { font-weight: 500 !important; }
    button { font-weight: 400 !important; }

    /* ===========================================
       ÍCONES - Material Symbols (corrige texto)
       =========================================== */
    /* Ícone do expander */
    [data-testid="stExpander"] summary span[data-testid="stExpanderToggleIcon"],
    [data-testid="stExpander"] summary > span:first-child,
    [data-testid="stExpanderToggleIcon"] {
        font-family: 'Material Symbols Rounded' !important;
        font-weight: normal !important;
        font-style: normal !important;
        font-size: 24px !important;
        line-height: 1 !important;
        letter-spacing: normal !important;
        text-transform: none !important;
        white-space: nowrap !important;
        direction: ltr !important;
        -webkit-font-feature-settings: 'liga' !important;
        font-feature-settings: 'liga' !important;
        -webkit-font-smoothing: antialiased !important;
    }

    /* ===========================================
       LAYOUT - Sidebar e Expander
       =========================================== */
    .block-container {
        padding-top: 1rem !important;
        padding-bottom: 0rem !important;
    }

    [data-testid="stSidebar"] > div:first-child {
        padding-top: 0.5rem !important;
    }

    /* Expander - corrige sobreposição */
    [data-testid="stExpander"] {
        margin-top: 1rem !important;
        overflow: visible !important;
    }

    [data-testid="stExpander"] summary {
        display: flex !important;
        align-items: center !important;
        gap: 0.5rem !important;
        padding: 0.5rem 0 !important;
    }

    /* ===========================================
       ESTILOS CUSTOMIZADOS
       =========================================== */
    .sidebar-logo-container {
        width: 100%; display: flex; justify-content: center;
        padding: 1rem 0 0.5rem 0;
    }
    .sidebar-logo-container img {
        border-radius: 50%; box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        max-width: 100px;
    }
    .sidebar-title {
        text-align: center; font-size: 1.8rem; font-weight: 300;
        color: #1f77b4; margin: 0.5rem 0 0.2rem 0;
    }
    .sidebar-subtitle {
        text-align: center; font-size: 0.85rem; color: #666;
        margin: 0 0 0.2rem 0;
    }
    .sidebar-author {
        text-align: center; font-size: 0.75rem; color: #888;
        font-style: italic; margin: 0 0 1rem 0;
    }

    .feature-card {
        background-color: #f8f9fa; padding: 1.5rem; border-radius: 8px;
        margin-bottom: 1rem; border-left: 4px solid #1f77b4;
    }
    .feature-card h4 { color: #1f77b4; margin-bottom: 0.5rem; }

    .stMetric {
        background-color: #f8f9fa; padding: 15px;
        border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    div[data-testid="stMetricValue"] { font-size: 2rem; font-weight: 400 !important; }

    .stSelectbox, .stTextInput, .stNumberInput, .stSlider {
        font-weight: 300 !important;
    }

    [data-testid="stMetricLabel"], [data-testid="stMetricValue"] {
        font-family: 'IBM Plex Sans', sans-serif !important;
    }

    [data-testid="stMetricLabel"] {
        font-weight: 300 !important;
    }

    [data-testid="stMetricValue"] {
        font-weight: 400 !important;
    }

    .stMarkdown p, .stMarkdown div {
        font-family: 'IBM Plex Sans', sans-serif !important;
        font-weight: 300 !important;
    }

    .streamlit-expanderHeader {
        font-family: 'IBM Plex Sans', sans-serif !important;
        font-weight: 400 !important;
    }

    .stCaption {
        font-family: 'IBM Plex Sans', sans-serif !important;
        font-weight: 300 !important;
    }

    .stMetric {
        background-color: #f8f9fa;
        padding: 15px;
        border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }

    div[data-testid="stMetricValue"] {
        font-size: 2rem;
        font-weight: 400 !important;
        font-family: 'IBM Plex Sans', sans-serif !important;
    }

    /* ============================================================
       CARDS E ELEMENTOS CUSTOMIZADOS
       ============================================================ */
    .feature-card {
        background-color: #f8f9fa;
        padding: 1.5rem;
        border-radius: 8px;
        margin-bottom: 1rem;
        border-left: 4px solid #1f77b4;
    }

    .feature-card h4 {
        color: #1f77b4;
        margin-bottom: 0.5rem;
        font-family: 'IBM Plex Sans', sans-serif !important;
    }

    .feature-card p {
        font-family: 'IBM Plex Sans', sans-serif !important;
    }
</style>
""", unsafe_allow_html=True)

# Diretório base relativo ao app.py (funciona independente do nome do repo)
APP_DIR = Path(__file__).parent.resolve()
DATA_DIR = APP_DIR / "data"

ALIASES_PATH = str(DATA_DIR / "Aliases.xlsx")
LOGO_PATH = str(DATA_DIR / "logo.png")

# Senha para proteger a funcionalidade de atualização de cache
SENHA_ADMIN = "m4th3u$987"

VARS_PERCENTUAL = [
    'ROE Ac. YTD an. (%)',
    'Índice de Basileia',
    'Crédito/Captações (%)',
    'Crédito/Ativo (%)',
    'Índice de Imobilização',
    # Variáveis de Capital (Relatório 5)
    'Índice de Capital Principal',
    'Índice de Capital Nível I',
    'Razão de Alavancagem',
]
VARS_RAZAO = ['Crédito/PL (%)']
VARS_MOEDAS = [
    'Carteira de Crédito',
    'Lucro Líquido Acumulado YTD',
    'Patrimônio Líquido',
    'Captações',
    'Ativo Total',
    'Títulos e Valores Mobiliários',
    'Passivo Exigível',
    'Patrimônio de Referência',
    'Patrimônio de Referência para Comparação com o RWA (e)',
    # Variáveis de Capital (Relatório 5)
    'Capital Principal',
    'Capital Complementar',
    'Capital Nível II',
    'RWA Total',
    'RWA Crédito',
    'RWA Mercado',
    'RWA Operacional',
    'Exposição Total',
    'Adicional de Capital Principal',
]
VARS_CONTAGEM = ['Número de Agências', 'Número de Postos de Atendimento']

# Variáveis disponíveis para ponderação (variáveis de tamanho/volume em valores absolutos)
# Mapeamento: label exibido -> nome da coluna no DataFrame
VARIAVEIS_PONDERACAO = {
    'Média Simples': None,  # Sem ponderação
    'Ativo Total': 'Ativo Total',
    'Carteira de Crédito': 'Carteira de Crédito',
    'Patrimônio Líquido': 'Patrimônio Líquido',
    'Patrimônio de Referência': 'Patrimônio de Referência',
    'Captações': 'Captações',
    'Passivo Exigível': 'Passivo Exigível',
    'RWA Total': 'RWA Total',
}

def calcular_media_ponderada(df, coluna_valor, coluna_peso=None):
    """Calcula média simples ou ponderada de uma coluna.

    Args:
        df: DataFrame com os dados
        coluna_valor: Nome da coluna cujos valores serão promediados
        coluna_peso: Nome da coluna de peso (None para média simples)

    Returns:
        float: Média calculada
    """
    if df.empty or coluna_valor not in df.columns:
        return 0

    valores = df[coluna_valor].dropna()
    if valores.empty:
        return 0

    # Média simples se não houver coluna de peso
    if coluna_peso is None:
        return valores.mean()

    if coluna_peso not in df.columns:
        return valores.mean()

    # Filtrar apenas registros com peso e valor válidos
    mask = df[coluna_valor].notna() & df[coluna_peso].notna() & (df[coluna_peso] > 0)
    df_valid = df[mask]

    if df_valid.empty:
        return valores.mean()

    # Calcular média ponderada: sum(valor * peso) / sum(peso)
    soma_ponderada = (df_valid[coluna_valor] * df_valid[coluna_peso]).sum()
    soma_pesos = df_valid[coluna_peso].sum()

    if soma_pesos == 0:
        return valores.mean()

    return soma_ponderada / soma_pesos

def get_label_media(coluna_peso):
    """Retorna o label descritivo do tipo de média."""
    if coluna_peso is None:
        return 'Média'
    # Abreviar nomes longos
    abreviacoes = {
        'Ativo Total': 'Ativo Total',
        'Carteira de Crédito': 'Cart. Crédito',
        'Patrimônio Líquido': 'PL',
        'Patrimônio de Referência': 'PR',
        'Captações': 'Captações',
        'Passivo Exigível': 'Passivo',
        'RWA Total': 'RWA',
    }
    nome_abrev = abreviacoes.get(coluna_peso, coluna_peso)
    return f'Média (pond. {nome_abrev})'

def get_cache_info_detalhado():
    """Retorna informações detalhadas sobre o arquivo de cache."""
    cache_manager = get_cache_manager()
    cache = cache_manager.get_cache("principal") if cache_manager else None
    info = {
        'existe': False,
        'caminho': '',
        'tamanho': 0,
        'tamanho_formatado': '0 B',
        'data_modificacao': None,
        'data_formatada': 'N/A',
        'fonte': 'nenhuma',
        'formato': 'N/A',
    }
    if cache and cache.existe():
        if cache.arquivo_dados.exists():
            arquivo_dados = cache.arquivo_dados
            info['formato'] = 'parquet'
        else:
            arquivo_dados = cache.arquivo_dados_pickle
            info['formato'] = 'pickle'

        info['existe'] = True
        info['caminho'] = str(arquivo_dados.resolve())
        stat = arquivo_dados.stat()
        info['tamanho'] = stat.st_size
        # Formatar tamanho
        tamanho = stat.st_size
        for unidade in ['B', 'KB', 'MB', 'GB']:
            if tamanho < 1024:
                info['tamanho_formatado'] = f"{tamanho:.1f} {unidade}"
                break
            tamanho /= 1024
        # Data de modificação
        info['data_modificacao'] = datetime.fromtimestamp(stat.st_mtime)
        info['data_formatada'] = info['data_modificacao'].strftime('%d/%m/%Y %H:%M:%S')

        if cache.arquivo_metadata.exists():
            try:
                metadata = json.loads(cache.arquivo_metadata.read_text())
                info['fonte'] = metadata.get('fonte', 'desconhecida')
            except Exception:
                info['fonte'] = 'desconhecida'
    return info

def recalcular_metricas_derivadas(dados_periodos):
    """Recalcula métricas derivadas para dados carregados do cache.

    SEMPRE recalcula as métricas para garantir que estejam corretas,
    mesmo que a coluna já exista (pode ter valores NaN de cache antigo).
    """
    if not dados_periodos:
        return dados_periodos

    # Mapeamento de nomes antigos para novos
    RENOMEAR_COLUNAS = {
        'Lucro Líquido': 'Lucro Líquido Acumulado YTD',
        'ROE An. (%)': 'ROE Ac. YTD an. (%)',
        'Crédito/PL': 'Crédito/PL (%)',
    }

    # Colunas obsoletas a serem removidas
    COLUNAS_OBSOLETAS = ['Risco/Retorno', 'Funding Gap (%)']

    dados_atualizados = {}
    for periodo, df in dados_periodos.items():
        df_atualizado = df.copy()

        # Renomear colunas antigas para novos nomes
        colunas_para_renomear = {
            old: new for old, new in RENOMEAR_COLUNAS.items()
            if old in df_atualizado.columns and new not in df_atualizado.columns
        }
        if colunas_para_renomear:
            df_atualizado = df_atualizado.rename(columns=colunas_para_renomear)

        # Remover colunas obsoletas
        colunas_remover = [col for col in COLUNAS_OBSOLETAS if col in df_atualizado.columns]
        if colunas_remover:
            df_atualizado = df_atualizado.drop(columns=colunas_remover)

        # Extrair mês do período para cálculo do fator de anualização
        try:
            if 'Período' in df_atualizado.columns:
                periodo_str = df_atualizado['Período'].iloc[0] if len(df_atualizado) > 0 else None
                if periodo_str and '/' in str(periodo_str):
                    mes = int(str(periodo_str).split('/')[0])
                else:
                    mes = int(periodo[4:6]) if len(periodo) >= 6 else 12
            else:
                mes = int(periodo[4:6]) if len(periodo) >= 6 else 12
        except (ValueError, IndexError):
            mes = 12

        # ROE Anualizado - SEMPRE recalcular
        if "Lucro Líquido Acumulado YTD" in df_atualizado.columns and "Patrimônio Líquido" in df_atualizado.columns:
            if mes == 3:
                fator = 4
            elif mes == 6:
                fator = 2
            elif mes == 9:
                fator = 12 / 9
            elif mes == 12:
                fator = 1
            else:
                fator = 12 / mes
            df_atualizado["ROE Ac. YTD an. (%)"] = (
                (fator * df_atualizado["Lucro Líquido Acumulado YTD"].fillna(0)) /
                df_atualizado["Patrimônio Líquido"].replace(0, np.nan)
            )

        # Crédito/PL - SEMPRE recalcular
        if "Carteira de Crédito" in df_atualizado.columns and "Patrimônio Líquido" in df_atualizado.columns:
            df_atualizado["Crédito/PL (%)"] = (
                df_atualizado["Carteira de Crédito"].fillna(0) /
                df_atualizado["Patrimônio Líquido"].replace(0, np.nan)
            )

        # Crédito/Captações - SEMPRE recalcular
        if "Carteira de Crédito" in df_atualizado.columns and "Captações" in df_atualizado.columns:
            df_atualizado["Crédito/Captações (%)"] = (
                df_atualizado["Carteira de Crédito"].fillna(0) /
                df_atualizado["Captações"].replace(0, np.nan)
            )

        # Crédito/Ativo (%) - SEMPRE recalcular
        if "Carteira de Crédito" in df_atualizado.columns and "Ativo Total" in df_atualizado.columns:
            df_atualizado["Crédito/Ativo (%)"] = (
                df_atualizado["Carteira de Crédito"].fillna(0) /
                df_atualizado["Ativo Total"].replace(0, np.nan)
            )

        # Migrar nome antigo Carteira/Ativo (%) para Crédito/Ativo (%) se existir
        if "Carteira/Ativo (%)" in df_atualizado.columns and "Crédito/Ativo (%)" not in df_atualizado.columns:
            df_atualizado["Crédito/Ativo (%)"] = df_atualizado["Carteira/Ativo (%)"]

        dados_atualizados[periodo] = df_atualizado

    return dados_atualizados

# Variáveis de capital que serão mescladas com os dados principais
VARS_CAPITAL_MERGE = [
    'Capital Principal',
    'Capital Complementar',
    'Capital Nível II',
    'RWA Total',
    'RWA Crédito',
    'RWA Mercado',
    'RWA Operacional',
    'Exposição Total',
    'Índice de Capital Principal',
    'Índice de Capital Nível I',
    'Razão de Alavancagem',
    'Adicional de Capital Principal',
]

def mesclar_dados_capital(dados_periodos, dados_capital):
    """Mescla dados de capital (Relatório 5) com os dados principais.

    Permite que as variáveis de capital estejam disponíveis nas abas
    Resumo, Análise Individual, Série Histórica, Scatter Plot, Deltas e Brincar.
    """
    if not dados_periodos or not dados_capital:
        return dados_periodos

    dados_mesclados = {}

    for periodo, df_principal in dados_periodos.items():
        df_merged = df_principal.copy()

        # Encontrar período correspondente no cache de capital
        # O formato pode ser diferente, então precisamos normalizar
        if periodo in dados_capital:
            df_capital = dados_capital[periodo]
        else:
            # Tentar formatos alternativos (ex: "03/2024" vs "202403")
            periodo_alt = None
            for p in dados_capital.keys():
                # Normalizar ambos para comparação
                p_norm = p.replace('/', '')
                periodo_norm = periodo.replace('/', '')
                if p_norm == periodo_norm or p == periodo:
                    periodo_alt = p
                    break
            if periodo_alt:
                df_capital = dados_capital[periodo_alt]
            else:
                dados_mesclados[periodo] = df_merged
                continue

        # Fazer merge por nome da instituição
        if 'Instituição' in df_capital.columns:
            # Selecionar apenas as colunas de capital que queremos mesclar
            colunas_para_merge = ['Instituição'] + [c for c in VARS_CAPITAL_MERGE if c in df_capital.columns]

            if len(colunas_para_merge) > 1:  # Tem pelo menos uma variável de capital
                df_capital_subset = df_capital[colunas_para_merge].drop_duplicates(subset=['Instituição'])

                # Fazer merge preservando os dados principais
                df_merged = df_merged.merge(
                    df_capital_subset,
                    on='Instituição',
                    how='left',
                    suffixes=('', '_capital')
                )

                # Se houver colunas duplicadas, manter a versão do capital (mais atualizada/específica)
                for col in VARS_CAPITAL_MERGE:
                    if f'{col}_capital' in df_merged.columns:
                        df_merged[col] = df_merged[f'{col}_capital']
                        df_merged = df_merged.drop(columns=[f'{col}_capital'])

        dados_mesclados[periodo] = df_merged

    return dados_mesclados

def ler_info_cache():
    cache_manager = get_cache_manager()
    cache = cache_manager.get_cache("principal") if cache_manager else None
    if not cache or not cache.arquivo_metadata.exists():
        return None

    try:
        metadata = json.loads(cache.arquivo_metadata.read_text())
    except Exception:
        return None

    linhas = []
    if metadata.get("timestamp_salvamento"):
        try:
            ts = datetime.fromisoformat(metadata["timestamp_salvamento"])
            linhas.append(f"Última extração: {ts.strftime('%d/%m/%Y %H:%M')}")
        except ValueError:
            linhas.append(f"Última extração: {metadata['timestamp_salvamento']}")

    if metadata.get("total_periodos") is not None:
        linhas.append(f"Total de períodos: {metadata.get('total_periodos')}")

    if metadata.get("fonte"):
        linhas.append(f"Fonte: {metadata.get('fonte')}")

    return "\n".join(linhas) if linhas else None

def forcar_recarregar_cache():
    """Força o recarregamento do cache do disco, ignorando session_state."""
    dados = carregar_cache()
    if dados:
        dados = recalcular_metricas_derivadas(dados)
        if 'dict_aliases' in st.session_state:
            mapa_codigos = None
            periodos_disponiveis = sorted(dados.keys())
            if periodos_disponiveis:
                mapa_codigos = construir_mapa_codinst(periodos_disponiveis[-1])
            dados = aplicar_aliases_em_periodos(
                dados,
                st.session_state['dict_aliases'],
                mapa_codigos=mapa_codigos,
            )
        st.session_state['dados_periodos'] = dados
        st.session_state['cache_fonte'] = 'local (recarregado)'
        return True
    return False

def upload_cache_github(cache_manager: CacheManager, tipo_cache: str, gh_token: str = None) -> Tuple[bool, str]:
    """Publica cache (parquet + metadata) no GitHub Releases.

    Retorna (sucesso, mensagem).
    """
    cache = cache_manager.get_cache(tipo_cache) if cache_manager else None
    if cache is None:
        return False, f"cache '{tipo_cache}' não encontrado"

    data_path = cache.arquivo_dados
    metadata_path = cache.arquivo_metadata

    if not data_path.exists():
        return False, f"arquivo parquet não encontrado para '{tipo_cache}' (gere o cache com pyarrow)"
    if not metadata_path.exists():
        return False, f"metadata.json não encontrada para '{tipo_cache}'"

    repo = os.getenv("TOMACONTA_RELEASE_REPO", "abalroar/tomaconta")
    tag = "v1.0-cache"
    asset_data_name = f"{tipo_cache}_dados.parquet"
    asset_metadata_name = f"{tipo_cache}_metadata.json"

    cache_size = data_path.stat().st_size

    try:
        result = subprocess.run(['gh', 'auth', 'status'], capture_output=True, text=True, timeout=10)
        gh_available = result.returncode == 0

        if gh_available:
            subprocess.run(
                ['gh', 'release', 'delete-asset', tag, asset_data_name, '-y', '-R', repo],
                capture_output=True, text=True, timeout=30
            )
            subprocess.run(
                ['gh', 'release', 'delete-asset', tag, asset_metadata_name, '-y', '-R', repo],
                capture_output=True, text=True, timeout=30
            )

            result = subprocess.run(
                ['gh', 'release', 'upload', tag, f"{data_path}#{asset_data_name}", '--clobber', '-R', repo],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode != 0:
                return False, f"erro ao fazer upload do cache: {result.stderr}"

            subprocess.run(
                ['gh', 'release', 'upload', tag, f"{metadata_path}#{asset_metadata_name}", '--clobber', '-R', repo],
                capture_output=True, text=True, timeout=30
            )

            return True, f"cache '{tipo_cache}' enviado ({cache_size / 1024 / 1024:.1f} MB)"

    except FileNotFoundError:
        pass
    except subprocess.TimeoutExpired:
        return False, "timeout ao executar gh CLI"
    except Exception as e:
        return False, f"erro ao usar gh CLI: {str(e)}"

    if gh_token:
        try:
            headers = {
                'Authorization': f'token {gh_token}',
                'Accept': 'application/vnd.github.v3+json'
            }

            release_url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
            r = requests.get(release_url, headers=headers, timeout=30)
            if r.status_code != 200:
                return False, f"release '{tag}' não encontrada no github"

            release_data = r.json()
            upload_url = release_data['upload_url'].replace('{?name,label}', '')

            for asset in release_data.get('assets', []):
                if asset['name'] in [asset_data_name, asset_metadata_name]:
                    delete_url = f"https://api.github.com/repos/{repo}/releases/assets/{asset['id']}"
                    requests.delete(delete_url, headers=headers, timeout=30)

            upload_headers = {
                'Authorization': f'token {gh_token}',
                'Content-Type': 'application/octet-stream'
            }

            with open(data_path, 'rb') as f:
                r = requests.post(
                    f"{upload_url}?name={asset_data_name}",
                    headers=upload_headers,
                    data=f,
                    timeout=300
                )
                if r.status_code not in [200, 201]:
                    return False, f"erro ao fazer upload do cache: {r.status_code}"

            with open(metadata_path, 'rb') as f:
                r = requests.post(
                    f"{upload_url}?name={asset_metadata_name}",
                    headers=upload_headers,
                    data=f,
                    timeout=60
                )
                if r.status_code not in [200, 201]:
                    return False, f"erro ao fazer upload da metadata: {r.status_code}"

            return True, f"cache '{tipo_cache}' enviado ({cache_size / 1024 / 1024:.1f} MB)"

        except Exception as e:
            return False, f"erro ao usar API do github: {str(e)}"

    return False, "gh CLI não disponível e nenhum token fornecido"


def preparar_download_cache_local(cache_manager: CacheManager, tipo_cache: str) -> Optional[dict]:
    """Prepara bytes do cache local para download (parquet ou pickle)."""
    cache = cache_manager.get_cache(tipo_cache) if cache_manager else None
    if cache is None:
        return None

    if cache.arquivo_dados.exists():
        data_path = cache.arquivo_dados
    elif cache.arquivo_dados_pickle.exists():
        data_path = cache.arquivo_dados_pickle
    else:
        return None

    return {
        "data": data_path.read_bytes(),
        "file_name": f"{tipo_cache}_cache{data_path.suffix}",
        "mime": "application/octet-stream",
    }

@st.cache_data(ttl=3600, show_spinner=False)
def carregar_aliases():
    """Carrega aliases do Excel com cache de 1 hora."""
    _perf_start("carregar_aliases")
    if os.path.exists(ALIASES_PATH):
        df = pd.read_excel(ALIASES_PATH)
        print(_perf_log("carregar_aliases"))
        return df
    print(_perf_log("carregar_aliases"))
    return None

# FIX PROBLEMA 3: Normalização de nomes de instituições
def normalizar_nome_instituicao(nome):
    """Normaliza nome removendo espaços extras e convertendo para uppercase"""
    if pd.isna(nome):
        return ""
    return " ".join(str(nome).split()).upper()

@st.cache_data(ttl=3600, show_spinner=False)
def construir_dict_aliases_normalizado(_df_aliases_hash: str, df_aliases_data: tuple):
    """Constrói dicionário de aliases com nomes normalizados para lookup robusto.

    Usa hash do dataframe para cache (evita recomputar a cada rerun).
    Mapeia tanto o nome original (Instituição) quanto variantes normalizadas
    para o alias amigável (Alias Banco).
    """
    _perf_start("construir_dict_aliases")
    dict_norm = {}
    if not df_aliases_data:
        print(_perf_log("construir_dict_aliases"))
        return dict_norm

    # Reconstruir DataFrame a partir da tupla (para cache funcionar)
    instituicoes, aliases = df_aliases_data

    for i in range(len(instituicoes)):
        instituicao = instituicoes[i]
        alias = aliases[i]

        if pd.notna(instituicao) and pd.notna(alias):
            # Mapeamento direto
            dict_norm[instituicao] = alias
            # Mapeamento normalizado (uppercase, sem espaços extras)
            dict_norm[normalizar_nome_instituicao(instituicao)] = alias
            # Mapeamento sem acentos (simplificado)
            nome_simples = instituicao.upper().strip()
            dict_norm[nome_simples] = alias

    print(_perf_log("construir_dict_aliases"))
    return dict_norm


def _preparar_aliases_para_cache(df_aliases):
    """Prepara dados do DataFrame para funções cacheadas."""
    if df_aliases is None or df_aliases.empty:
        return "", ()
    # Hash baseado no conteúdo
    content_hash = str(hash(tuple(df_aliases['Instituição'].fillna('').tolist())))
    # Dados como tupla (hashável)
    instituicoes = tuple(df_aliases['Instituição'].tolist())
    aliases = tuple(df_aliases['Alias Banco'].tolist())
    return content_hash, (instituicoes, aliases)

def aplicar_aliases_em_periodos(dados_periodos, dict_aliases, mapa_codigos=None):
    if not dados_periodos:
        return dados_periodos
    dados_corrigidos = {}

    for periodo, df in dados_periodos.items():
        if 'Instituição' not in df.columns:
            dados_corrigidos[periodo] = df
            continue

        df_corrigido = df.copy()

        if mapa_codigos:
            df_corrigido['Instituição'] = df_corrigido['Instituição'].apply(
                lambda nome: mapa_codigos.get(str(nome).strip(), nome) if pd.notna(nome) else nome
            )

        df_corrigido['Instituição'] = df_corrigido['Instituição'].apply(
            lambda nome: dict_aliases.get(nome, nome) if pd.notna(nome) else nome
        )

        dados_corrigidos[periodo] = df_corrigido

    return dados_corrigidos


def resolver_nomes_instituicoes_capital(df_capital, dict_aliases, df_aliases=None, dados_periodos=None):
    """Resolve nomes de instituições que estão como códigos [IF xxxxx] no cache de capital.

    Usa múltiplas estratégias de lookup:
    1. Busca direta no dict_aliases (nome original -> alias)
    2. Busca por CodInst no df_aliases se disponível
    3. Busca no dados_periodos (cache principal) como fallback
    4. Mantém o nome original se não encontrar correspondência

    Args:
        df_capital: DataFrame com dados de capital
        dict_aliases: Dicionário nome original -> alias
        df_aliases: DataFrame do Aliases.xlsx com mapeamentos
        dados_periodos: Dicionário do cache principal para fallback de nomes

    Returns:
        DataFrame com nomes de instituições resolvidos
    """
    import re

    if df_capital is None or df_capital.empty:
        return df_capital

    if 'Instituição' not in df_capital.columns:
        return df_capital

    df_result = df_capital.copy()

    # Construir mapa CodInst -> Nome a partir do df_aliases se disponível
    mapa_codinst_nome = {}
    if df_aliases is not None and not df_aliases.empty:
        # Verificar se há coluna de código no aliases
        colunas_codigo = ['CodInst', 'Código', 'Cod', 'CNPJ']
        col_codigo = None
        for col in colunas_codigo:
            if col in df_aliases.columns:
                col_codigo = col
                break

        if col_codigo and 'Alias Banco' in df_aliases.columns:
            for _, row in df_aliases.iterrows():
                cod = row.get(col_codigo)
                alias = row.get('Alias Banco')
                if pd.notna(cod) and pd.notna(alias):
                    mapa_codinst_nome[str(cod).strip()] = alias

    # Construir mapa adicional a partir do dados_periodos (cache principal) como fallback
    mapa_dados_periodos = {}
    if dados_periodos:
        for periodo, df_periodo in dados_periodos.items():
            if 'Instituição' in df_periodo.columns and 'CodInst' in df_periodo.columns:
                for _, row in df_periodo.iterrows():
                    cod = row.get('CodInst')
                    nome = row.get('Instituição')
                    # Só usar se o nome não for um placeholder
                    if pd.notna(cod) and pd.notna(nome) and not str(nome).startswith('[IF'):
                        cod_str = str(int(cod)) if isinstance(cod, float) else str(cod)
                        if cod_str not in mapa_dados_periodos:
                            mapa_dados_periodos[cod_str] = nome

    def resolver_nome(nome, codinst=None):
        """Resolve um nome de instituição."""
        if pd.isna(nome):
            return nome

        nome_str = str(nome).strip()

        # 1. Busca direta no dict_aliases
        if dict_aliases and nome_str in dict_aliases:
            return dict_aliases[nome_str]

        # 2. Verificar se é um placeholder [IF xxxxx] - agora aceita alfanuméricos
        match = re.match(r'\[IF\s+([A-Za-z0-9]+)\]', nome_str)
        if match:
            cod_extraido = match.group(1)

            # Tentar resolver pelo código extraído no mapa de aliases
            if mapa_codinst_nome and cod_extraido in mapa_codinst_nome:
                return mapa_codinst_nome[cod_extraido]

            # Tentar resolver no mapa do dados_periodos
            if mapa_dados_periodos and cod_extraido in mapa_dados_periodos:
                return mapa_dados_periodos[cod_extraido]

            # Se temos CodInst na linha, usar para lookup
            if codinst is not None and pd.notna(codinst):
                cod_str = str(int(codinst)) if isinstance(codinst, float) else str(codinst)
                if mapa_codinst_nome and cod_str in mapa_codinst_nome:
                    return mapa_codinst_nome[cod_str]
                if mapa_dados_periodos and cod_str in mapa_dados_periodos:
                    return mapa_dados_periodos[cod_str]

        # 3. Se temos CodInst, tentar lookup direto
        if codinst is not None and pd.notna(codinst):
            cod_str = str(int(codinst)) if isinstance(codinst, float) else str(codinst)
            if mapa_codinst_nome and cod_str in mapa_codinst_nome:
                return mapa_codinst_nome[cod_str]
            if mapa_dados_periodos and cod_str in mapa_dados_periodos:
                return mapa_dados_periodos[cod_str]

        # 4. Manter nome original se não encontrou correspondência
        return nome_str

    # Aplicar resolução de nomes
    if 'CodInst' in df_result.columns:
        df_result['Instituição'] = df_result.apply(
            lambda row: resolver_nome(row['Instituição'], row.get('CodInst')),
            axis=1
        )
    else:
        df_result['Instituição'] = df_result['Instituição'].apply(
            lambda nome: resolver_nome(nome)
        )

    return df_result



def normalizar_codigo_cor(cor_valor):
    if pd.isna(cor_valor):
        return None

    if isinstance(cor_valor, (int, np.integer)):
        cor_str = f"{int(cor_valor):06X}"
    elif isinstance(cor_valor, (float, np.floating)) and float(cor_valor).is_integer():
        cor_str = f"{int(cor_valor):06X}"
    else:
        cor_str = str(cor_valor).strip().upper()
        if cor_str.startswith('#'):
            cor_str = cor_str[1:]
        cor_str = cor_str.replace(" ", "")

    if len(cor_str) < 6:
        cor_str = cor_str.zfill(6)

    if len(cor_str) == 6 and all(c in '0123456789ABCDEF' for c in cor_str):
        return f"#{cor_str}"

    return None

# FIX PROBLEMA 3: Carregamento correto de cores com normalização
@st.cache_data(ttl=3600, show_spinner=False)
def carregar_cores_aliases_local(_df_hash: str, cores_data: tuple):
    """Lê a cor do Aliases.xlsx e cria um dicionário de cores.

    Usa hash do dataframe para cache (evita recomputar a cada rerun).
    Importante: mapeia tanto o valor da coluna 'Instituição' (nome original vindo do BCB)
    quanto o valor da coluna 'Alias Banco' (nome amigável que aparece no app),
    para que a cor seja aplicada em qualquer tela.
    """
    _perf_start("carregar_cores_aliases")
    dict_cores = {}
    if not cores_data:
        print(_perf_log("carregar_cores_aliases"))
        return dict_cores

    instituicoes, aliases, cores = cores_data

    for i in range(len(instituicoes)):
        instituicao = instituicoes[i]
        alias = aliases[i]
        cor_valor = cores[i]

        cor_str = normalizar_codigo_cor(cor_valor)
        if not cor_str:
            continue

        if pd.notna(instituicao):
            dict_cores[normalizar_nome_instituicao(instituicao)] = cor_str
            # Também aceita busca pelo 'Alias Banco' (útil quando a coluna Instituição já vem renomeada)
            if pd.notna(alias):
                dict_cores[normalizar_nome_instituicao(alias)] = cor_str

        # Também mapeia pelo alias (é o que aparece na UI)
        if pd.notna(alias):
            dict_cores[normalizar_nome_instituicao(alias)] = cor_str

    print(_perf_log("carregar_cores_aliases"))
    return dict_cores


def _preparar_cores_para_cache(df_aliases):
    """Prepara dados de cores do DataFrame para função cacheada."""
    if df_aliases is None or df_aliases.empty:
        return "", ()

    # Encontrar coluna de cor
    colunas_possiveis = ['Código Cor', 'Cor', 'Color', 'Hex', 'Código']
    coluna_cor = None
    for col in colunas_possiveis:
        if col in df_aliases.columns:
            coluna_cor = col
            break

    if coluna_cor is None:
        return "", ()

    # Hash baseado no conteúdo
    content_hash = str(hash(tuple(df_aliases['Instituição'].fillna('').tolist())))
    # Dados como tupla (hashável)
    instituicoes = tuple(df_aliases['Instituição'].tolist())
    aliases = tuple(df_aliases['Alias Banco'].tolist())
    cores = tuple(df_aliases[coluna_cor].tolist())
    return content_hash, (instituicoes, aliases, cores)

def verificar_caches_github() -> dict:
    """Verifica quais caches existem no GitHub Releases.

    Retorna dict com status de cada cache no GitHub (sem autenticação, apenas leitura pública).
    Verifica todos os 8 tipos de cache disponíveis.
    """
    repo = os.getenv("TOMACONTA_RELEASE_REPO", "abalroar/tomaconta")
    tag = "v1.0-cache"

    # Todos os tipos de cache
    tipos_cache = ['principal', 'capital', 'ativo', 'passivo', 'dre',
                   'carteira_pf', 'carteira_pj', 'carteira_instrumentos']

    result = {
        'release_existe': False,
        'repo': repo,
        'tag': tag,
        'erro': None,
        'caches': {}
    }

    # Inicializar todos os caches como não existentes
    for tipo in tipos_cache:
        result['caches'][tipo] = {'existe': False, 'tamanho': 0, 'tamanho_fmt': 'N/A'}

    # Manter compatibilidade com código antigo
    result['cache_principal'] = result['caches']['principal']
    result['cache_capital'] = result['caches']['capital']

    try:
        release_url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
        r = requests.get(release_url, timeout=10)

        if r.status_code == 404:
            result['erro'] = f"Release '{tag}' não encontrada"
            return result
        elif r.status_code != 200:
            result['erro'] = f"Erro ao acessar release: {r.status_code}"
            return result

        result['release_existe'] = True
        release_data = r.json()

        for asset in release_data.get('assets', []):
            size = asset.get('size', 0)
            size_fmt = f"{size / 1024 / 1024:.1f} MB" if size > 1024*1024 else f"{size / 1024:.1f} KB"
            nome_asset = asset.get('name', '')

            # Identificar tipo de cache pelo nome do asset
            for tipo in tipos_cache:
                if nome_asset.startswith(f'{tipo}_dados'):
                    result['caches'][tipo] = {
                        'existe': True,
                        'tamanho': size,
                        'tamanho_fmt': size_fmt,
                        'nome_asset': nome_asset
                    }
                    break

        # Atualizar referências de compatibilidade
        result['cache_principal'] = result['caches']['principal']
        result['cache_capital'] = result['caches']['capital']

    except requests.exceptions.Timeout:
        result['erro'] = "Timeout ao verificar GitHub"
    except Exception as e:
        result['erro'] = str(e)

    return result


def ordenar_periodos(periodos, reverso=False):
    def chave_periodo(valor):
        try:
            mes, ano = valor.split('/')
            return (int(ano), int(mes))
        except (ValueError, AttributeError):
            return (0, 0)

    return sorted(periodos, key=chave_periodo, reverse=reverso)


def periodo_para_exibicao(periodo_trimestre: str) -> str:
    """Converte período trimestral (1/2025) para formato mês abreviado (Mar/25).

    Args:
        periodo_trimestre: Período no formato "trimestre/ano" (ex: "1/2025")

    Returns:
        Período no formato "Mês/AA" (ex: "Mar/25")
    """
    if not periodo_trimestre or '/' not in str(periodo_trimestre):
        return str(periodo_trimestre)
    try:
        trimestre, ano = str(periodo_trimestre).split('/')
        meses_map = {'1': 'Mar', '2': 'Jun', '3': 'Set', '4': 'Dez'}
        mes = meses_map.get(trimestre.strip(), trimestre)
        ano_curto = ano[-2:] if len(ano) == 4 else ano
        return f"{mes}/{ano_curto}"
    except Exception:
        return str(periodo_trimestre)


def formatar_periodos_lista(periodos: list) -> list:
    """Converte lista de períodos para formato de exibição (Mar/25).

    Args:
        periodos: Lista de períodos no formato "trimestre/ano"

    Returns:
        Lista de períodos formatados
    """
    return [periodo_para_exibicao(p) for p in periodos]


def ordenar_bancos_com_alias(bancos: list, dict_aliases: dict = None) -> list:
    """Ordena bancos com alias primeiro (A-Z), depois sem alias (A-Z).

    Args:
        bancos: Lista de nomes de bancos
        dict_aliases: Dicionário de aliases {nome_original: alias}

    Returns:
        Lista ordenada de bancos
    """
    if not dict_aliases:
        return sorted(bancos)

    aliases_set = set(dict_aliases.values())

    bancos_com_alias = []
    bancos_sem_alias = []

    for banco in bancos:
        if banco in aliases_set:
            bancos_com_alias.append(banco)
        else:
            bancos_sem_alias.append(banco)

    def sort_key(nome):
        primeiro_char = nome[0].lower() if nome else 'z'
        if primeiro_char.isdigit():
            return (1, nome.lower())
        return (0, nome.lower())

    bancos_com_alias_sorted = sorted(bancos_com_alias, key=sort_key)
    bancos_sem_alias_sorted = sorted(bancos_sem_alias, key=sort_key)

    return bancos_com_alias_sorted + bancos_sem_alias_sorted


def formatar_valor(valor, variavel):
    if pd.isna(valor) or valor == 0:
        return "N/A"

    if variavel in VARS_PERCENTUAL:
        return f"{valor*100:.2f}%"
    elif variavel in VARS_RAZAO:
        return f"{valor:.2f}x"
    elif variavel in VARS_MOEDAS:
        valor_mm = valor / 1e6
        return f"R$ {valor_mm:,.0f}MM".replace(",", ".")
    elif variavel in VARS_CONTAGEM:
        return f"{valor:,.0f}".replace(",", ".")
    else:
        return f"{valor:.2f}"

def get_axis_format(variavel):
    if variavel in VARS_PERCENTUAL:
        return {'tickformat': '.2f', 'ticksuffix': '%', 'multiplicador': 100}
    elif variavel in VARS_MOEDAS:
        return {'tickformat': ',.0f', 'ticksuffix': 'M', 'multiplicador': 1/1e6}
    elif variavel in VARS_CONTAGEM:
        return {'tickformat': ',.0f', 'ticksuffix': '', 'multiplicador': 1}
    else:
        return {'tickformat': '.2f', 'ticksuffix': '', 'multiplicador': 1}


@st.cache_resource(show_spinner=False)
def _carregar_logo_base64(logo_path: str, target_width: int = 200) -> str:
    """Carrega e processa o logo uma única vez, retornando base64.

    Usa cache_resource para manter em memória entre reruns.
    """
    _perf_start("carregar_logo")
    if not os.path.exists(logo_path):
        print(_perf_log("carregar_logo"))
        return ""

    logo_image = PILImage.open(logo_path)
    if logo_image.width < target_width:
        ratio = target_width / logo_image.width
        new_height = int(logo_image.height * ratio)
        logo_image = logo_image.resize((target_width, new_height), PILImage.LANCZOS)
    buffer = BytesIO()
    logo_image.save(buffer, format="PNG", optimize=True)
    logo_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
    print(_perf_log("carregar_logo"))
    return logo_base64


@st.cache_data(show_spinner=False)
def _get_dados_concatenados(periodos_hash: str, dados_keys: tuple) -> pd.DataFrame:
    """Concatena todos os DataFrames de períodos uma única vez.

    Evita pd.concat() repetido em cada página/rerun.
    Usa hash dos períodos para invalidar cache quando dados mudam.
    """
    _perf_start("concat_dados")
    if 'dados_periodos' not in st.session_state:
        print(_perf_log("concat_dados"))
        return pd.DataFrame()

    df = pd.concat(st.session_state['dados_periodos'].values(), ignore_index=True)
    print(_perf_log("concat_dados"))
    return df


def get_dados_concatenados() -> pd.DataFrame:
    """Retorna DataFrame concatenado de todos os períodos (com cache)."""
    if 'dados_periodos' not in st.session_state or not st.session_state['dados_periodos']:
        return pd.DataFrame()

    # Hash baseado nas chaves dos períodos E nas colunas para invalidação de cache
    # Isso garante que o cache seja invalidado quando métricas derivadas são recalculadas
    # ou quando dados de capital são mesclados
    periodos_keys = tuple(sorted(st.session_state['dados_periodos'].keys()))

    # Incluir colunas do primeiro DataFrame no hash para detectar mudanças
    primeiro_periodo = next(iter(st.session_state['dados_periodos'].values()))
    colunas_hash = tuple(sorted(primeiro_periodo.columns.tolist()))

    # Flag de mesclagem de capital também invalida o cache
    capital_mesclado = st.session_state.get('_dados_capital_mesclados', False)

    periodos_hash = str(hash((periodos_keys, colunas_hash, capital_mesclado)))

    return _get_dados_concatenados(periodos_hash, periodos_keys)


# FIX PROBLEMA 3: Busca de cor com normalização
def obter_cor_banco(instituicao):
    if 'dict_cores_personalizadas' in st.session_state:
        instituicao_norm = normalizar_nome_instituicao(instituicao)
        if instituicao_norm in st.session_state['dict_cores_personalizadas']:
            return st.session_state['dict_cores_personalizadas'][instituicao_norm]
    return None

def criar_mini_grafico(df_banco, variavel, titulo, tipo='linha'):
    df_sorted = df_banco.copy()
    if 'ano' not in df_sorted.columns:
        df_sorted['ano'] = df_sorted['Período'].str.split('/').str[1].astype(int)
        df_sorted['trimestre'] = df_sorted['Período'].str.split('/').str[0].astype(int)
    df_sorted = df_sorted.sort_values(['ano', 'trimestre'])

    instituicao = df_sorted['Instituição'].iloc[0]
    cor_banco = obter_cor_banco(instituicao)
    if not cor_banco:
        cor_banco = '#1f77b4'

    if variavel in VARS_PERCENTUAL:
        hover_values = df_sorted[variavel] * 100
        tickformat = '.2f'
        suffix = '%'
    elif variavel in VARS_MOEDAS:
        hover_values = df_sorted[variavel] / 1e6
        tickformat = ',.0f'
        suffix = 'M'
    elif variavel in VARS_CONTAGEM:
        hover_values = df_sorted[variavel]
        tickformat = ',.0f'
        suffix = ''
    else:
        hover_values = df_sorted[variavel]
        tickformat = '.2f'
        suffix = ''

    fig = go.Figure()

    if tipo == 'barra':
        fig.add_trace(go.Bar(
            x=df_sorted['Período'],
            y=hover_values,
            marker=dict(color=cor_banco, opacity=0.8),
            hovertemplate='%{x}<br>%{y:' + tickformat + '}' + suffix + '<extra></extra>'
        ))
    else:
        fig.add_trace(go.Scatter(
            x=df_sorted['Período'],
            y=hover_values,
            mode='lines',
            line=dict(color=cor_banco, width=2),
            fill='tozeroy',
            fillcolor=f'rgba({int(cor_banco[1:3], 16)}, {int(cor_banco[3:5], 16)}, {int(cor_banco[5:7], 16)}, 0.2)',
            hovertemplate='%{x}<br>%{y:' + tickformat + '}' + suffix + '<extra></extra>'
        ))

    fig.update_layout(
        title=dict(text=titulo, font=dict(size=12, color='#333', family='IBM Plex Sans')),
        height=180,
        margin=dict(l=10, r=10, t=35, b=30),
        plot_bgcolor='#f8f9fa',
        paper_bgcolor='white',
        xaxis=dict(showgrid=False, showticklabels=False),
        yaxis=dict(showgrid=True, gridcolor='#e0e0e0', tickformat=tickformat, ticksuffix=suffix),
        hovermode='x',
        font=dict(family='IBM Plex Sans')
    )

    return fig

def gerar_scorecard_pdf(banco_selecionado, df_banco, periodo_inicial, periodo_final):
    from reportlab.lib.pagesizes import landscape, A4

    def garantir_fontes_ibm_plex():
        fonts_dir = Path("data/fonts")
        fonts_dir.mkdir(parents=True, exist_ok=True)
        regular_path = fonts_dir / "IBMPlexSans-Regular.ttf"
        bold_path = fonts_dir / "IBMPlexSans-Bold.ttf"
        if not regular_path.exists() or not bold_path.exists():
            try:
                regular_url = "https://github.com/google/fonts/raw/main/ofl/ibmplexsans/IBMPlexSans-Regular.ttf"
                bold_url = "https://github.com/google/fonts/raw/main/ofl/ibmplexsans/IBMPlexSans-Bold.ttf"
                if not regular_path.exists():
                    regular_path.write_bytes(requests.get(regular_url, timeout=30).content)
                if not bold_path.exists():
                    bold_path.write_bytes(requests.get(bold_url, timeout=30).content)
            except Exception:
                return False
        try:
            if "IBMPlexSans" not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont("IBMPlexSans", str(regular_path)))
            if "IBMPlexSans-Bold" not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont("IBMPlexSans-Bold", str(bold_path)))
            pdfmetrics.registerFontFamily("IBMPlexSans", normal="IBMPlexSans", bold="IBMPlexSans-Bold")
            return True
        except Exception:
            return False

    df_sorted = df_banco.copy()
    df_sorted['ano'] = df_sorted['Período'].str.split('/').str[1].astype(int)
    df_sorted['trimestre'] = df_sorted['Período'].str.split('/').str[0].astype(int)
    df_sorted = df_sorted.sort_values(['ano', 'trimestre'])

    # Filtra pelo período selecionado
    periodos_disponiveis = ordenar_periodos(df_sorted['Período'].unique())
    try:
        idx_ini = periodos_disponiveis.index(periodo_inicial)
        idx_fin = periodos_disponiveis.index(periodo_final)
        if idx_ini > idx_fin:
            idx_ini, idx_fin = idx_fin, idx_ini
        periodos_filtrados = periodos_disponiveis[idx_ini:idx_fin + 1]
        df_sorted = df_sorted[df_sorted['Período'].isin(periodos_filtrados)]
    except ValueError:
        pass

    instituicao = df_sorted['Instituição'].iloc[0]
    cor_banco = obter_cor_banco(instituicao)
    if not cor_banco:
        cor_banco = '#1f77b4'

    buffer = io.BytesIO()
    # Formato paisagem (landscape)
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), topMargin=0.4*inch, bottomMargin=0.4*inch, leftMargin=0.5*inch, rightMargin=0.5*inch)

    styles = getSampleStyleSheet()

    usa_ibm = garantir_fontes_ibm_plex()
    fonte_regular = "IBMPlexSans" if usa_ibm else "Helvetica"
    fonte_bold = "IBMPlexSans-Bold" if usa_ibm else "Helvetica-Bold"

    title_style = ParagraphStyle('CustomTitle', parent=styles['Heading1'], fontSize=32, textColor=colors.HexColor(cor_banco), spaceAfter=4, alignment=TA_LEFT, fontName=fonte_bold)
    subtitle_style = ParagraphStyle('CustomSubtitle', parent=styles['Normal'], fontSize=12, textColor=colors.HexColor('#666666'), spaceAfter=20, alignment=TA_LEFT, fontName=fonte_regular)
    section_style = ParagraphStyle('SectionStyle', parent=styles['Heading2'], fontSize=14, textColor=colors.HexColor(cor_banco), spaceAfter=12, spaceBefore=16, fontName=fonte_bold)
    metric_style = ParagraphStyle('MetricStyle', parent=styles['Normal'], fontName=fonte_regular)
    footer_style = ParagraphStyle('FooterStyle', parent=styles['Normal'], fontName=fonte_regular, fontSize=9)

    story = []
    story.append(Paragraph(banco_selecionado, title_style))
    story.append(Paragraph(f"Análise de {periodo_inicial} até {periodo_final}", subtitle_style))

    # Dados do período final para métricas
    ultimo_periodo = df_sorted['Período'].iloc[-1]
    dados_ultimo = df_sorted[df_sorted['Período'] == ultimo_periodo].iloc[0]

    metricas_principais = [
        ('Carteira de Crédito', 'Carteira de Crédito'),
        ('ROE Anualizado', 'ROE Ac. YTD an. (%)'),
        ('Índice de Basileia', 'Índice de Basileia'),
        ('Crédito/PL', 'Crédito/PL (%)'),
    ]

    metricas_data = []
    for label, col in metricas_principais:
        valor = formatar_valor(dados_ultimo.get(col), col)
        metricas_data.append([label, valor])

    # Métricas em linha única (4 colunas) para paisagem
    metrics_table_data = [[
        Paragraph(f'<font size="10"><b>{m[0]}</b></font><br/><font size="18"><b>{m[1]}</b></font>', metric_style)
        for m in metricas_data
    ]]

    metrics_table = Table(metrics_table_data, colWidths=[2.5*inch, 2.5*inch, 2.5*inch, 2.5*inch])
    metrics_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8f9fa')),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTNAME', (0, 0), (-1, -1), fonte_regular),
        ('LEFTPADDING', (0, 0), (-1, -1), 15),
        ('RIGHTPADDING', (0, 0), (-1, -1), 15),
        ('TOPPADDING', (0, 0), (-1, -1), 15),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 15),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#e0e0e0')),
    ]))

    story.append(metrics_table)
    story.append(Spacer(1, 0.3*inch))
    story.append(Paragraph("Evolução Histórica das Variáveis", section_style))

    variaveis = [col for col in df_sorted.columns if col not in ['Instituição', 'Período', 'ano', 'trimestre'] and df_sorted[col].notna().sum() > 0]

    cor_rgb = tuple(int(cor_banco[i:i+2], 16) for i in (1, 3, 5))
    cor_rgb_norm = tuple(c/255 for c in cor_rgb)

    def criar_figura_grafico(df_plot, variavel, titulo, use_bar=False):
        # Gráficos maiores e maior DPI para melhor qualidade
        fig, ax = plt.subplots(figsize=(3.5, 2.2), dpi=200)

        y_values = df_plot[variavel].values
        x_labels = df_plot['Período'].values
        x_pos = np.arange(len(x_labels))

        if variavel in VARS_PERCENTUAL:
            y_display = y_values * 100
            suffix = '%'
        elif variavel in VARS_MOEDAS:
            y_display = y_values / 1e6
            suffix = 'M'
        elif variavel in VARS_CONTAGEM:
            y_display = y_values
            suffix = ''
        else:
            y_display = y_values
            suffix = ''

        if use_bar:
            ax.bar(x_pos, y_display, color=cor_rgb_norm, alpha=0.8, width=0.7)
        else:
            ax.fill_between(x_pos, y_display, alpha=0.3, color=cor_rgb_norm)
            ax.plot(x_pos, y_display, color=cor_rgb_norm, linewidth=2.5, marker='o', markersize=4)

        ax.set_title(titulo, fontsize=12, fontweight='bold', color='#333333', pad=10)
        ax.set_facecolor('#f8f9fa')
        fig.patch.set_facecolor('white')

        if len(x_labels) > 6:
            step = max(1, len(x_labels) // 5)
            ax.set_xticks(x_pos[::step])
            ax.set_xticklabels(x_labels[::step], fontsize=8, rotation=45, ha='right')
        else:
            ax.set_xticks(x_pos)
            ax.set_xticklabels(x_labels, fontsize=8, rotation=45, ha='right')

        ax.yaxis.set_major_formatter(FuncFormatter(lambda y, _: f'{y:.1f}{suffix}'))
        ax.tick_params(axis='y', labelsize=8)
        ax.grid(True, alpha=0.3, linestyle='--', color='#e0e0e0')
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        plt.tight_layout()
        return fig

    figs_por_linha = 3
    for i in range(0, len(variaveis), figs_por_linha):
        graficos_linha = variaveis[i:i+figs_por_linha]
        row_images = []
        for var in graficos_linha:
            try:
                use_bar = (var == 'Lucro Líquido Acumulado YTD')
                fig = criar_figura_grafico(df_sorted, var, var, use_bar=use_bar)
                img_buffer = io.BytesIO()
                fig.savefig(img_buffer, format='png', bbox_inches='tight', dpi=200)
                img_buffer.seek(0)
                img = RLImage(img_buffer, width=3.3*inch, height=2.0*inch)
                row_images.append(img)
                plt.close(fig)
            except:
                row_images.append(Paragraph(f"[Erro: {var}]", metric_style))
        while len(row_images) < figs_por_linha:
            row_images.append(Spacer(1, 0))
        img_table = Table([row_images], colWidths=[3.5*inch, 3.5*inch, 3.5*inch])
        img_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 5),
            ('RIGHTPADDING', (0, 0), (-1, -1), 5),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        story.append(img_table)
        story.append(Spacer(1, 0.1*inch))

    story.append(Spacer(1, 0.15*inch))
    rodape = Paragraph(f"<font size='9'><i>Gerado em {datetime.now().strftime('%d/%m/%Y às %H:%M')} | Fonte: API IF.DATA - BCB | toma.conta</i></font>", footer_style)
    story.append(rodape)

    try:
        doc.build(story)
        buffer.seek(0)
        return buffer
    except Exception as e:
        st.error(f"Erro ao gerar PDF: {e}")
        return None

# === INICIALIZAÇÃO COM CACHE E PERFORMANCE LOGS ===
_perf_start("init_total")

if 'df_aliases' not in st.session_state:
    _perf_start("init_aliases")
    df_aliases = carregar_aliases()
    if df_aliases is not None:
        st.session_state['df_aliases'] = df_aliases
        st.session_state['dict_aliases'] = dict(zip(df_aliases['Instituição'], df_aliases['Alias Banco']))
        # Usar funções cacheadas com dados preparados
        alias_hash, alias_data = _preparar_aliases_para_cache(df_aliases)
        st.session_state['dict_aliases_norm'] = construir_dict_aliases_normalizado(alias_hash, alias_data)
        cores_hash, cores_data = _preparar_cores_para_cache(df_aliases)
        st.session_state['dict_cores_personalizadas'] = carregar_cores_aliases_local(cores_hash, cores_data)
        st.session_state['colunas_classificacao'] = [c for c in df_aliases.columns if c not in ['Instituição','Alias Banco','Cor','Código Cor']]
    print(_perf_log("init_aliases"))


def carregar_dados_periodos():
    if 'dados_periodos' in st.session_state and st.session_state['dados_periodos']:
        return
    _perf_start("init_dados_periodos")
    cache_manager = get_cache_manager()
    resultado_principal = cache_manager.carregar("principal")
    cache_principal = cache_manager.get_cache("principal")
    dados_cache = cache_principal.carregar_formato_antigo() if cache_principal else None
    if dados_cache:
        _perf_start("recalc_metricas")
        dados_cache = recalcular_metricas_derivadas(dados_cache)
        print(_perf_log("recalc_metricas"))
        if 'dict_aliases' in st.session_state:
            _perf_start("aplicar_aliases")
            dados_cache = aplicar_aliases_em_periodos(
                dados_cache,
                st.session_state['dict_aliases'],
                mapa_codigos=None,  # Evita chamada HTTP à API Olinda
            )
            print(_perf_log("aplicar_aliases"))
        st.session_state['dados_periodos'] = dados_cache
        if 'cache_fonte' not in st.session_state:
            st.session_state['cache_fonte'] = resultado_principal.fonte if resultado_principal else 'desconhecida'
    print(_perf_log("init_dados_periodos"))


def carregar_dados_capital():
    if 'dados_capital' in st.session_state and st.session_state['dados_capital']:
        return
    _perf_start("init_dados_capital")
    cache_manager = get_cache_manager()
    resultado_capital = cache_manager.carregar("capital")
    cache_capital = cache_manager.get_cache("capital")
    dados_capital = cache_capital.carregar_formato_antigo() if cache_capital else None
    if dados_capital:
        if 'dict_aliases' in st.session_state:
            dados_capital = aplicar_aliases_em_periodos(
                dados_capital,
                st.session_state['dict_aliases'],
                mapa_codigos=None,  # Evita chamada HTTP à API Olinda
            )
        st.session_state['dados_capital'] = dados_capital
        st.session_state['capital_cache_fonte'] = resultado_capital.fonte if resultado_capital else 'desconhecida'
    print(_perf_log("init_dados_capital"))


print(_perf_log("init_total"))

# Menu horizontal no topo
if 'menu_atual' not in st.session_state:
    st.session_state['menu_atual'] = "Sobre"

# Header e menu centralizados
st.markdown("""
<style>
    /* Remove padding extra do topo */
    .main .block-container {
        padding-top: 1rem !important;
    }

    .header-nav {
        display: flex;
        justify-content: center;
        width: 100%;
    }

    .header-nav [data-testid="stSegmentedControl"] > div {
        justify-content: center;
    }

    .header-logo {
        display: flex;
        justify-content: center;
        width: 100%;
        margin-top: 0.5rem;
    }

    .header-logo img {
        width: 200px;
        height: auto;
        image-rendering: auto;
    }
</style>
""", unsafe_allow_html=True)

# Header usando colunas Streamlit para garantir centralização
_, col_header, _ = st.columns([1, 3, 1])
with col_header:
    # OTIMIZAÇÃO: Usar função cacheada para processamento do logo
    logo_base64 = _carregar_logo_base64(LOGO_PATH, target_width=200)
    if logo_base64:
        st.markdown(
            f"""
            <div class="header-logo">
                <img src="data:image/png;base64,{logo_base64}" alt="toma.conta logo" />
            </div>
            """,
            unsafe_allow_html=True
        )

    # Título e subtítulos centralizados via HTML
    st.markdown("""
        <div style="text-align: center; margin-top: -0.5rem;">
            <p style="font-size: 3.6rem; font-weight: 700; color: #1f77b4; margin-bottom: 0.2rem;">toma.conta</p>
            <p style="font-size: 1.6rem; color: #666; margin-bottom: 0.1rem;">análise de instituições financeiras brasileiras</p>
            <p style="font-size: 0.9rem; color: #888; font-style: italic; margin-bottom: 0.5rem;">por matheus prates, cfa</p>
        </div>
    """, unsafe_allow_html=True)

# Lista de opções do menu principal (análise)
MENU_PRINCIPAL = ["Painel", "Histórico Individual", "Histórico Peers", "Scatter Plot", "Deltas (Antes e Depois)", "Capital Regulatório", "DRE", "Carteira 4.966", "Taxas de Juros por Produto", "Crie sua métrica!"]

# Lista de opções do menu secundário (utilitários)
MENU_SECUNDARIO = ["Sobre", "Atualizar Base", "Glossário"]

TODOS_MENUS = MENU_PRINCIPAL + MENU_SECUNDARIO

# Validar menu_atual
if st.session_state['menu_atual'] not in TODOS_MENUS:
    if st.session_state['menu_atual'] == "Taxas de Juros":
        st.session_state['menu_atual'] = "Taxas de Juros por Produto"
    elif st.session_state['menu_atual'] == "Atualização Base":
        st.session_state['menu_atual'] = "Atualizar Base"
    else:
        st.session_state['menu_atual'] = "Sobre"

menu_atual = st.session_state['menu_atual']

# Carregamento sob demanda para reduzir uso de RAM
menus_precisam_principal = {
    "Painel",
    "Histórico Individual",
    "Histórico Peers",
    "Scatter Plot",
    "Deltas (Antes e Depois)",
    "Crie sua métrica!",
}
if menu_atual in menus_precisam_principal:
    carregar_dados_periodos()

if menu_atual == "Capital Regulatório":
    carregar_dados_capital()

# Callbacks para navegação entre menus (evita conflito)
def _on_main_menu_change():
    """Callback quando menu principal é clicado."""
    sel = st.session_state.get('nav_main')
    if sel is not None and sel in MENU_PRINCIPAL:
        st.session_state['menu_atual'] = sel
        # Limpar seleção do menu secundário
        if 'nav_sec' in st.session_state:
            st.session_state['nav_sec'] = None

def _on_sec_menu_change():
    """Callback quando menu secundário é clicado."""
    sel = st.session_state.get('nav_sec')
    if sel is not None and sel in MENU_SECUNDARIO:
        st.session_state['menu_atual'] = sel
        # Limpar seleção do menu principal
        if 'nav_main' in st.session_state:
            st.session_state['nav_main'] = None

# Configurar valores iniciais nos widgets (antes de renderizar)
if menu_atual in MENU_PRINCIPAL:
    st.session_state['nav_main'] = menu_atual
    st.session_state['nav_sec'] = None
else:
    st.session_state['nav_main'] = None
    st.session_state['nav_sec'] = menu_atual

# Menu principal (análise)
st.markdown('<div class="header-nav">', unsafe_allow_html=True)
st.segmented_control(
    "menu principal",
    MENU_PRINCIPAL,
    label_visibility="collapsed",
    key="nav_main",
    on_change=_on_main_menu_change
)
st.markdown('</div>', unsafe_allow_html=True)

# Menu secundário (utilitários)
st.markdown('<div class="header-nav">', unsafe_allow_html=True)
st.segmented_control(
    "menu secundário",
    MENU_SECUNDARIO,
    label_visibility="collapsed",
    key="nav_sec",
    on_change=_on_sec_menu_change
)
st.markdown('</div>', unsafe_allow_html=True)

# Usar menu_atual (já atualizado pelos callbacks)
menu = st.session_state['menu_atual']

st.markdown("---")

# Sidebar apenas para informações básicas
with st.sidebar:
    st.markdown('<p class="sidebar-title">toma.conta</p>', unsafe_allow_html=True)
    st.markdown('<p class="sidebar-subtitle">análise de instituições financeiras brasileiras</p>', unsafe_allow_html=True)
    st.markdown('<p class="sidebar-author">por matheus prates, cfa</p>', unsafe_allow_html=True)

    st.markdown("")

    with st.expander("controle avançado"):
        if 'df_aliases' in st.session_state:
            st.success(f"{len(st.session_state['df_aliases'])} aliases carregados")
        else:
            st.error("aliases não encontrados")

        # Informações detalhadas do cache
        st.markdown("**status do cache**")
        cache_info = get_cache_info_detalhado()
        fonte = st.session_state.get('cache_fonte', 'desconhecida')

        if cache_info['existe']:
            st.caption(f"**caminho:** `{cache_info['caminho']}`")
            st.caption(f"**modificado:** {cache_info['data_formatada']}")
            st.caption(f"**tamanho:** {cache_info['tamanho_formatado']}")
            st.caption(f"**fonte:** {fonte}")

            # Mostrar info do cache_info.txt se existir
            info_cache = ler_info_cache()
            if info_cache:
                st.caption(f"{info_cache.replace(chr(10), ' | ')}")
        else:
            st.warning("cache não encontrado no disco")

        # Botão para forçar recarregamento do cache local
        if st.button("recarregar cache do disco", width='stretch'):
            if forcar_recarregar_cache():
                st.success("cache recarregado do disco com sucesso!")
                st.rerun()
            else:
                st.error("falha ao recarregar cache - arquivo não existe")

        st.markdown("---")
        st.markdown("**atualizar dados (admin)**")

        senha_input = st.text_input("senha de administrador", type="password", key="senha_admin")

        if senha_input == SENHA_ADMIN:
            col1, col2 = st.columns(2)
            with col1:
                ano_i = st.selectbox("ano inicial", range(2015,2028), index=8, key="ano_i")
                mes_i = st.selectbox("trimestre inicial", ['03','06','09','12'], key="mes_i")
            with col2:
                ano_f = st.selectbox("ano final", range(2015,2028), index=10, key="ano_f")
                mes_f = st.selectbox("trimestre final", ['03','06','09','12'], index=2, key="mes_f")

            if 'dict_aliases' in st.session_state:
                if st.button("extrair dados do BCB", type="primary", width='stretch'):
                    periodos = gerar_periodos(ano_i, mes_i, ano_f, mes_f)
                    progress_bar = st.progress(0)
                    status = st.empty()
                    save_status = st.empty()

                    def update(i, total, p):
                        progress_bar.progress((i+1)/total)
                        status.text(f"extraindo {p[4:6]}/{p[:4]} ({i+1}/{total})")

                    # Callback para salvamento progressivo (a cada 5 períodos)
                    def save_progress(dados_parciais, info):
                        save_status.text(f"💾 salvando {len(dados_parciais)} períodos...")
                        salvar_cache(dados_parciais, info, incremental=True)
                        save_status.text(f"✓ {len(dados_parciais)} períodos salvos no cache")

                    st.info(f"🔄 iniciando extração de {len(periodos)} períodos. salvamento progressivo a cada 5 períodos.")

                    dados = processar_todos_periodos(
                        periodos,
                        st.session_state['dict_aliases'],
                        progress_callback=update,
                        save_callback=save_progress,
                        save_interval=5
                    )

                    if not dados:
                        progress_bar.empty()
                        status.empty()
                        save_status.empty()
                        st.error("falha ao extrair dados: nenhum período retornou dados válidos.")
                    else:
                        periodo_info = f"{periodos[0][4:6]}/{periodos[0][:4]} até {periodos[-1][4:6]}/{periodos[-1][:4]}"
                        cache_salvo = salvar_cache(dados, periodo_info, incremental=True)

                        # Atualizar session_state com merge dos dados existentes + novos
                        if 'dados_periodos' in st.session_state and st.session_state['dados_periodos']:
                            # Merge: dados existentes + novos (novos sobrescrevem)
                            dados_merged = st.session_state['dados_periodos'].copy()
                            dados_merged.update(dados)
                            st.session_state['dados_periodos'] = dados_merged
                        else:
                            st.session_state['dados_periodos'] = dados

                        st.session_state['cache_fonte'] = 'extração local'

                        progress_bar.empty()
                        status.empty()
                        save_status.empty()
                        st.success(f"✓ {len(dados)} períodos extraídos! cache total: {len(st.session_state['dados_periodos'])} períodos")
                        st.info(f"cache salvo em: {cache_salvo['caminho']}")
                        st.info(f"tamanho: {cache_salvo['tamanho_formatado']}")
                        st.rerun()

                st.markdown("---")
                st.markdown("**status dos caches**")

                # Verificar status no GitHub
                with st.spinner("verificando github..."):
                    gh_status = verificar_caches_github()

                col_status1, col_status2 = st.columns(2)

                with col_status1:
                    st.caption("**Cache Principal (dados.parquet/pickle)**")
                    # Local
                    cache_info_local = get_cache_info()
                    if cache_info_local['existe']:
                        st.caption(f"📁 Local: ✅ {cache_info_local['tamanho_formatado']}")
                    else:
                        st.caption("📁 Local: ❌ não existe")
                    # GitHub
                    if gh_status['cache_principal']['existe']:
                        st.caption(f"☁️ GitHub: ✅ {gh_status['cache_principal']['tamanho_fmt']}")
                    else:
                        st.caption("☁️ GitHub: ❌ não existe")

                with col_status2:
                    st.caption("**Cache Capital (dados.parquet/pickle)**")
                    # Local
                    capital_info_local = get_capital_cache_info()
                    if capital_info_local['existe']:
                        st.caption(f"📁 Local: ✅ {capital_info_local['tamanho_formatado']} ({capital_info_local['n_periodos']} períodos)")
                    else:
                        st.caption("📁 Local: ❌ não existe")
                    # GitHub
                    if gh_status['cache_capital']['existe']:
                        st.caption(f"☁️ GitHub: ✅ {gh_status['cache_capital']['tamanho_fmt']}")
                    else:
                        st.caption("☁️ GitHub: ⚠️ **NÃO EXISTE** - envie abaixo!")

                if gh_status['erro']:
                    st.warning(f"⚠️ Erro ao verificar GitHub: {gh_status['erro']}")

                st.markdown("---")
                st.markdown("**publicar caches no github**")
                st.caption("envia os caches locais para github releases para persistência")

                # Tentar usar token do Streamlit Secrets primeiro
                token_from_secrets = st.secrets.get("GITHUB_TOKEN", None) if hasattr(st, 'secrets') else None
                if token_from_secrets:
                    st.caption("✓ usando GITHUB_TOKEN dos Secrets")

                gh_token = st.text_input("github token (opcional)", type="password", key="gh_token",
                                        help="token com permissão 'repo'. deixe em branco para usar Secrets ou gh CLI")

                col_upload1, col_upload2 = st.columns(2)

                with col_upload1:
                    if st.button("📦 enviar cache PRINCIPAL", width='stretch', help="Envia dados_cache"):
                        token_final = gh_token if gh_token else token_from_secrets
                        with st.spinner("enviando cache principal para github releases..."):
                            sucesso, mensagem = upload_cache_github(get_cache_manager(), "principal", token_final)
                            if sucesso:
                                st.success(f"✅ Cache PRINCIPAL: {mensagem}")
                            else:
                                st.error(f"❌ Cache PRINCIPAL: {mensagem}")

                with col_upload2:
                    # Botão para enviar cache de capital separadamente
                    capital_info = get_capital_cache_info()
                    btn_disabled = not capital_info['existe']
                    btn_help = "Envia cache de capital" if capital_info['existe'] else "Cache de capital não existe localmente"

                    if st.button("💰 enviar cache CAPITAL", width='stretch', disabled=btn_disabled, help=btn_help):
                        token_final = gh_token if gh_token else token_from_secrets
                        with st.spinner("enviando cache de capital para github releases..."):
                            sucesso, mensagem = upload_cache_github(get_cache_manager(), "capital", token_final)
                            if sucesso:
                                st.success(f"✅ Cache CAPITAL: {mensagem}")
                            else:
                                st.error(f"❌ Cache CAPITAL: {mensagem}")

                # =============================================================
                # SEÇÃO ISOLADA: EXTRAÇÃO DE DADOS DE CAPITAL
                # Cache separado (parquet/pickle), sem impacto no fluxo principal
                # =============================================================
                st.markdown("---")
                st.markdown("**extrair capital (relatório 5)**")
                st.caption("extrai informações de capital (índices, RWA, alavancagem) - cache separado")

                # Mostrar status do cache de capital
                capital_cache_info = get_capital_cache_info()
                if capital_cache_info['existe']:
                    st.caption(f"📊 cache capital: {capital_cache_info['n_periodos']} períodos | {capital_cache_info['tamanho_formatado']}")
                    st.caption(f"📅 atualizado: {capital_cache_info['data_formatada']}")

                    # Botão para baixar o cache localmente (backup)
                    cache_download = preparar_download_cache_local(get_cache_manager(), "capital")
                    if cache_download:
                        st.download_button(
                            label="📥 baixar cache de capital (backup local)",
                            data=cache_download["data"],
                            file_name=cache_download["file_name"],
                            mime=cache_download["mime"],
                            width='stretch',
                            help="Baixe uma cópia do cache antes que o Streamlit reinicie"
                        )
                else:
                    st.caption("📊 cache capital: não existe ainda")

                col_cap1, col_cap2 = st.columns(2)
                with col_cap1:
                    ano_cap_i = st.selectbox("ano inicial", range(2015, 2028), index=8, key="ano_cap_i")
                    mes_cap_i = st.selectbox("trim. inicial", ['03', '06', '09', '12'], key="mes_cap_i")
                with col_cap2:
                    ano_cap_f = st.selectbox("ano final", range(2015, 2028), index=10, key="ano_cap_f")
                    mes_cap_f = st.selectbox("trim. final", ['03', '06', '09', '12'], index=2, key="mes_cap_f")

                # Opção de atualização completa (sobrescreve cache antigo)
                atualizar_completo_capital = st.checkbox(
                    "🔄 atualização completa (sobrescrever cache antigo)",
                    value=False,
                    key="atualizar_completo_capital",
                    help="Marque para apagar o cache existente e extrair tudo do zero. Use quando houver problemas com nomes ou dados antigos."
                )

                if st.button("extrair dados de capital", type="secondary", width='stretch', key="btn_extrair_capital"):
                    periodos_cap = gerar_periodos_capital(ano_cap_i, mes_cap_i, ano_cap_f, mes_cap_f)
                    progress_bar_cap = st.progress(0)
                    status_cap = st.empty()
                    save_status_cap = st.empty()

                    # Se atualização completa, deletar cache existente primeiro
                    incremental_mode = not atualizar_completo_capital
                    if atualizar_completo_capital:
                        cache_manager = get_cache_manager()
                        resultado_limpar = cache_manager.limpar("capital")
                        if resultado_limpar.sucesso:
                            st.info("🗑️ cache antigo de capital removido para atualização completa")

                    def update_cap(i, total, p):
                        progress_bar_cap.progress((i + 1) / total)
                        status_cap.text(f"extraindo capital {p[4:6]}/{p[:4]} ({i + 1}/{total})")

                    def save_progress_cap(dados_parciais, info):
                        save_status_cap.text(f"💾 salvando {len(dados_parciais)} períodos de capital...")
                        salvar_cache_capital(dados_parciais, info, incremental=incremental_mode)
                        save_status_cap.text(f"✓ {len(dados_parciais)} períodos de capital salvos")

                    modo_texto = "completa" if atualizar_completo_capital else "incremental"
                    st.info(f"🔄 iniciando extração de capital ({modo_texto}): {len(periodos_cap)} períodos")

                    # Usar dict_aliases se disponível
                    aliases_para_capital = st.session_state.get('dict_aliases', {})

                    dados_capital = processar_todos_periodos_capital(
                        periodos_cap,
                        dict_aliases=aliases_para_capital,
                        progress_callback=update_cap,
                        save_callback=save_progress_cap,
                        save_interval=5
                    )

                    if not dados_capital:
                        progress_bar_cap.empty()
                        status_cap.empty()
                        save_status_cap.empty()
                        st.error("falha ao extrair dados de capital: nenhum período retornou dados válidos.")
                    else:
                        periodo_info_cap = f"capital {periodos_cap[0][4:6]}/{periodos_cap[0][:4]} até {periodos_cap[-1][4:6]}/{periodos_cap[-1][:4]}"
                        cache_capital_salvo = salvar_cache_capital(dados_capital, periodo_info_cap, incremental=incremental_mode)

                        progress_bar_cap.empty()
                        status_cap.empty()
                        save_status_cap.empty()

                        st.success(f"✓ {len(dados_capital)} períodos de capital extraídos!")
                        st.info(f"cache capital salvo em: {cache_capital_salvo['caminho']}")
                        st.info(f"tamanho: {cache_capital_salvo['tamanho_formatado']} | total: {cache_capital_salvo['n_periodos']} períodos")

                        # Upload para GitHub Releases para persistência
                        # Usa token do Streamlit Secrets se disponível
                        github_token = st.secrets.get("GITHUB_TOKEN", None) if hasattr(st, 'secrets') else None
                        with st.spinner("enviando cache de capital para github releases..."):
                            sucesso_upload, msg_upload = upload_cache_github(get_cache_manager(), "capital", github_token)
                            if sucesso_upload:
                                st.success(f"☁️ {msg_upload}")
                            else:
                                st.warning(f"⚠️ cache local salvo, mas falha no upload: {msg_upload}")

                        # Atualizar session_state com novos dados
                        st.session_state['dados_capital'] = dados_capital

                        # Mostrar campos extraídos
                        with st.expander("campos extraídos"):
                            campos = get_campos_capital_info()
                            for original, exibido in campos.items():
                                st.caption(f"• {exibido} ← _{original}_")

            else:
                st.warning("carregue os aliases primeiro")
        elif senha_input:
            st.error("senha incorreta")

if menu == "Sobre":
    st.markdown("""
    ## sobre a plataforma

    o **toma.conta** é uma plataforma completa de análise financeira do sistema bancário brasileiro. com dados oficiais do banco central, oferece visualizações interativas, comparações entre instituições, análise de capital regulatório e ferramentas para criação de métricas customizadas — tudo em uma interface intuitiva e com exportação profissional.
    """)

    st.markdown("### módulos de análise")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("""
        <div class="feature-card">
            <h4>painel comparativo</h4>
            <p>rankings e gráficos de composição para comparar instituições em um período específico. inclui médias ponderadas do grupo e diferenças calculadas automaticamente.</p>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("""
        <div class="feature-card">
            <h4>histórico individual</h4>
            <p>análise detalhada de uma instituição ao longo do tempo com mini-gráficos de tendência. exportação em pdf scorecard com visão de 4 anos.</p>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("""
        <div class="feature-card">
            <h4>histórico peers</h4>
            <p>séries temporais comparativas entre múltiplas instituições. ideal para acompanhar a evolução de peers ou concorrentes ao longo dos trimestres.</p>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("""
        <div class="feature-card">
            <h4>scatter plot</h4>
            <p>gráficos de dispersão com 3 dimensões (eixo x, eixo y e tamanho da bolha). visualize relações entre variáveis e movimentação entre períodos.</p>
        </div>
        """, unsafe_allow_html=True)

    with col2:
        st.markdown("""
        <div class="feature-card">
            <h4>deltas (antes e depois)</h4>
            <p>análise de variações absolutas e percentuais entre dois períodos. identifique rapidamente quem cresceu, encolheu ou mudou de patamar.</p>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("""
        <div class="feature-card">
            <h4>capital regulatório</h4>
            <p>dados do relatório 5 do bcb: capital principal, complementar, nível ii, rwa por tipo de risco, razão de alavancagem e índices de capital.</p>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("""
        <div class="feature-card">
            <h4>crie sua métrica</h4>
            <p>construa indicadores customizados combinando variáveis com operações matemáticas. visualize como ranking, scatter plot ou análise de deltas.</p>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("""
        <div class="feature-card">
            <h4>glossário técnico</h4>
            <p>definições detalhadas de todas as variáveis, métricas calculadas e informações sobre consolidação prudencial (visão conglomerado).</p>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")

    st.markdown("### indicadores disponíveis")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("""
        **variáveis monetárias**
        - ativo total
        - carteira de crédito (líquida)
        - títulos e valores mobiliários
        - passivo exigível
        - captações
        - patrimônio líquido
        - lucro líquido ac. ytd
        - patrimônio de referência
        """)

    with col2:
        st.markdown("""
        **capital regulatório**
        - capital principal (tier 1)
        - capital complementar
        - capital nível ii
        - rwa total / crédito / mercado / operacional
        - exposição total
        - índices de capital
        - razão de alavancagem
        """)

    with col3:
        st.markdown("""
        **métricas calculadas**
        - roe anualizado (%)
        - crédito / pl (%)
        - crédito / captações (%)
        - crédito / ativo (%)

        **índices**
        - índice de basileia
        - índice de imobilização
        - número de agências e pacs
        """)

    st.markdown("---")

    st.markdown("### recursos avançados")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("""
        <div class="feature-card">
            <h4>filtros inteligentes</h4>
            <p>selecione instituições por top n (por qualquer indicador), por peer group ou lista customizada. 8 opções de ponderação para médias do grupo.</p>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("""
        <div class="feature-card">
            <h4>nomenclatura personalizada</h4>
            <p>renomeie instituições com nomes-fantasia, defina cores personalizadas e agrupe por categoria (peer groups) para análises segmentadas.</p>
        </div>
        """, unsafe_allow_html=True)

    with col2:
        st.markdown("""
        <div class="feature-card">
            <h4>exportação profissional</h4>
            <p>exporte para excel (multi-abas) ou csv. gere pdf scorecards com histórico de 4 anos para apresentações e relatórios.</p>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("""
        <div class="feature-card">
            <h4>dados oficiais</h4>
            <p>fonte única: api if.data e relatório 5 do banco central. dados consolidados (visão conglomerado) com atualização trimestral.</p>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")

    st.markdown("""
    ### como utilizar

    1. **dados pré-carregados**: a plataforma já possui dados históricos prontos para análise imediata
    2. **navegue pelos módulos**: use o menu superior para acessar painel, histórico, scatter plot, deltas ou capital regulatório
    3. **aplique filtros**: selecione instituições por top n, peer group ou lista customizada
    4. **personalize análises**: ajuste variáveis, períodos e ponderações conforme sua necessidade
    5. **exporte resultados**: baixe em excel, csv ou gere pdf scorecards para compartilhar

    ---

    ### stack tecnológica

    | componente | função |
    |------------|--------|
    | **python 3.10+** | linguagem base |
    | **streamlit** | interface web interativa |
    | **pandas** | processamento e análise de dados |
    | **plotly** | visualizações dinâmicas e interativas |
    | **api bcb olinda** | fonte oficial de dados (if.data e relatório 5) |
    """)

    st.markdown("---")
    st.caption("desenvolvido em 2026 por matheus prates, cfa | ferramenta open-source para análise do sistema financeiro brasileiro")

elif menu == "Painel":
    st.markdown("## resumo comparativo por período")
    st.caption("compare múltiplas instituições em um único trimestre, com ranking e média do grupo selecionado.")

    if 'dados_periodos' in st.session_state and st.session_state['dados_periodos']:
        df = get_dados_concatenados()  # OTIMIZAÇÃO: usar cache

        indicadores_config = {
            'Ativo Total': ['Ativo Total'],
            'Carteira de Crédito': ['Carteira de Crédito'],
            'Captações': ['Captações'],
            'Patrimônio Líquido': ['Patrimônio Líquido'],
            'Índice de Capital Principal': ['Índice de Capital Principal'],
            'Índice de Basileia': ['Índice de Basileia'],
            'Lucro Líquido Acumulado YTD': ['Lucro Líquido Acumulado YTD'],
            'ROE Ac. Anualizado (%)': ['ROE Ac. YTD an. (%)'],
        }

        indicadores_disponiveis = {}
        for label, colunas in indicadores_config.items():
            coluna_valida = next((col for col in colunas if col in df.columns), None)
            if coluna_valida:
                indicadores_disponiveis[label] = coluna_valida

        if not indicadores_disponiveis:
            st.warning("nenhum dos indicadores requeridos foi encontrado nos dados atuais.")
        else:
            periodos = ordenar_periodos(df['Período'].dropna().unique(), reverso=True)

            componentes_indicador = {
                'Patrimônio de Referência': [
                    'RWA Crédito',
                    'RWA Contraparte',
                    'RWA Operacional',
                    'RWA Mercado',
                    'RWA Outros',
                ]
            }

            col_periodo, col_indicador, col_tipo, col_media = st.columns([1.2, 2, 1.3, 1.8])
            with col_periodo:
                periodo_resumo = st.selectbox(
                    "período",
                    periodos,
                    index=0,
                    key="periodo_resumo",
                    format_func=periodo_para_exibicao
                )
            with col_indicador:
                indicador_label = st.selectbox(
                    "indicador",
                    list(indicadores_disponiveis.keys()),
                    key="indicador_resumo"
                )
            componentes_disponiveis = [
                col for col in componentes_indicador.get(indicador_label, []) if col in df.columns
            ]
            with col_tipo:
                if componentes_disponiveis:
                    tipo_grafico = st.radio(
                        "tipo de gráfico",
                        ["Ranking", "Composição (100%)"],
                        horizontal=True,
                        key="tipo_grafico_resumo"
                    )
                else:
                    tipo_grafico = "Ranking"
            with col_media:
                tipo_media_label = st.selectbox(
                    "ponderar média por",
                    list(VARIAVEIS_PONDERACAO.keys()),
                    index=0,
                    key="tipo_media_resumo"
                )
                coluna_peso_resumo = VARIAVEIS_PONDERACAO[tipo_media_label]

            col_peers, col_bancos = st.columns([1.2, 2.8])

            peers_disponiveis = []
            if 'colunas_classificacao' in st.session_state and 'df_aliases' in st.session_state:
                peers_disponiveis = st.session_state['colunas_classificacao']

            with col_peers:
                peers_selecionados = st.multiselect(
                    "grupos de peers",
                    peers_disponiveis,
                    key="peers_resumo"
                )

                usar_top_universo = False
                top_universo_n = 30
                if not peers_selecionados:
                    usar_top_universo = st.checkbox(
                        "selecionar automaticamente top N do universo",
                        value=True,
                        key="top_universo_toggle"
                    )
                    top_universo_n = st.selectbox(
                        "top N (universo)",
                        [10, 20, 30, 40],
                        index=2,
                        key="top_universo_n"
                    )

            bancos_do_peer = []
            if peers_selecionados and 'df_aliases' in st.session_state:
                df_aliases = st.session_state['df_aliases']
                peer_vals = df_aliases[peers_selecionados].fillna(0).apply(
                    lambda col: col.astype(str).str.strip().isin(["1", "1.0"])
                )
                mask_peer = peer_vals.any(axis=1)
                bancos_do_peer = df_aliases.loc[mask_peer, 'Alias Banco'].tolist()

            df_periodo = df[df['Período'] == periodo_resumo].copy()
            df_periodo_universo = df_periodo.copy()

            if peers_selecionados and bancos_do_peer:
                df_periodo = df_periodo[df_periodo['Instituição'].isin(bancos_do_peer)]

            bancos_todos = df_periodo['Instituição'].dropna().unique().tolist()
            dict_aliases = st.session_state.get('dict_aliases', {})
            bancos_todos = ordenar_bancos_com_alias(bancos_todos, dict_aliases)

            indicador_col = indicadores_disponiveis[indicador_label]
            coluna_selecao = indicador_col
            if tipo_grafico == "Composição (100%)" and componentes_disponiveis:
                df_periodo['total_componentes'] = df_periodo[componentes_disponiveis].sum(axis=1, skipna=True)
                df_periodo_universo['total_componentes'] = df_periodo_universo[componentes_disponiveis].sum(axis=1, skipna=True)
                coluna_selecao = 'total_componentes'

            bancos_default = bancos_do_peer[:10] if bancos_do_peer else []
            if usar_top_universo:
                df_universo_valid = df_periodo_universo.dropna(subset=[coluna_selecao]).copy()
                if df_universo_valid.empty:
                    st.warning("não há dados disponíveis para calcular o top N do universo.")
                else:
                    df_universo_top = df_universo_valid.sort_values(coluna_selecao, ascending=False).head(top_universo_n)
                    bancos_default = df_universo_top['Instituição'].tolist()

            bancos_default = [banco for banco in bancos_default if banco in bancos_todos]

            with col_bancos:
                bancos_selecionados = st.multiselect(
                    "selecionar instituições (até 40)",
                    bancos_todos,
                    default=bancos_default,
                    key="bancos_resumo"
                )

            col_top, col_ordem, col_sort = st.columns([1.4, 1.4, 1.8])
            with col_top:
                usar_top_n = st.toggle("usar top/bottom n", value=True, key="usar_top_resumo")
                top_n_resumo = st.selectbox("n", [10, 15, 20], index=0, key="top_n_resumo")
            with col_ordem:
                direcao_top = st.radio(
                    "top/bottom",
                    ["Top", "Bottom"],
                    horizontal=True,
                    key="top_bottom_resumo"
                )
            with col_sort:
                modo_ordenacao = st.radio(
                    "ordenação",
                    ["Ordenar por valor", "Manter ordem de seleção"],
                    horizontal=True,
                    key="ordenacao_resumo"
                )

            format_info = get_axis_format(indicador_col)

            def formatar_numero(valor, fmt_info, incluir_sinal=False):
                if pd.isna(valor):
                    return "N/A"
                valor_formatado = format(valor, fmt_info['tickformat'])
                if incluir_sinal and valor > 0:
                    valor_formatado = f"+{valor_formatado}"
                return f"{valor_formatado}{fmt_info['ticksuffix']}"

            max_bancos = 40
            if bancos_selecionados and len(bancos_selecionados) > max_bancos:
                st.warning(f"limite de {max_bancos} instituições excedido; exibindo as primeiras {max_bancos}.")
                bancos_selecionados = bancos_selecionados[:max_bancos]

            if usar_top_n or not bancos_selecionados:
                df_periodo_valid = df_periodo.dropna(subset=[coluna_selecao]).copy()
                if df_periodo_valid.empty:
                    st.info("não há dados suficientes para o período e indicador selecionados.")
                else:
                    ascending = direcao_top == "Bottom"
                    df_selecionado = df_periodo_valid.sort_values(coluna_selecao, ascending=ascending).head(top_n_resumo)
            else:
                df_selecionado = df_periodo[df_periodo['Instituição'].isin(bancos_selecionados)].copy()

            df_selecionado = df_selecionado.dropna(subset=[coluna_selecao])

            if df_selecionado.empty:
                st.info("selecione instituições ou ajuste os filtros para visualizar o resumo.")
            else:
                df_selecionado['valor_display'] = df_selecionado[indicador_col] * format_info['multiplicador']
                media_display = calcular_media_ponderada(df_selecionado, 'valor_display', coluna_peso_resumo)
                label_media = get_label_media(coluna_peso_resumo)

                if modo_ordenacao == "Ordenar por valor":
                    ordenar_asc = direcao_top == "Bottom"
                    if tipo_grafico == "Composição (100%)" and componentes_disponiveis:
                        df_selecionado = df_selecionado.sort_values(coluna_selecao, ascending=ordenar_asc)
                    else:
                        df_selecionado = df_selecionado.sort_values('valor_display', ascending=ordenar_asc)
                elif bancos_selecionados:
                    ordem = bancos_selecionados
                    df_selecionado['ordem'] = pd.Categorical(df_selecionado['Instituição'], categories=ordem, ordered=True)
                    df_selecionado = df_selecionado.sort_values('ordem')

                if tipo_grafico == "Composição (100%)" and componentes_disponiveis:
                    df_componentes = df_selecionado[['Instituição'] + componentes_disponiveis].copy()
                    df_componentes['total'] = df_componentes[componentes_disponiveis].sum(axis=1, skipna=True)
                    df_componentes = df_componentes[df_componentes['total'] > 0]

                    if df_componentes.empty:
                        st.info("não há dados suficientes para exibir a composição selecionada.")
                    else:
                        df_percent = df_componentes.copy()
                        df_percent[componentes_disponiveis] = df_percent[componentes_disponiveis].div(
                            df_componentes['total'],
                            axis=0
                        ) * 100

                        fig_resumo = go.Figure()
                        for componente in componentes_disponiveis:
                            fig_resumo.add_trace(go.Bar(
                                x=df_percent['Instituição'],
                                y=df_percent[componente],
                                name=componente,
                                hovertemplate=(
                                    "<b>%{x}</b><br>"
                                    f"{componente}: %{{y:.1f}}%<extra></extra>"
                                )
                            ))

                        fig_resumo.update_layout(
                            title=f"{indicador_label} - {periodo_resumo} ({len(df_percent)} instituições)",
                            xaxis_title="instituições",
                            yaxis_title="participação (%)",
                            plot_bgcolor='#f8f9fa',
                            paper_bgcolor='white',
                            height=max(650, len(df_percent) * 24),
                            barmode='stack',
                            showlegend=True,
                            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
                            xaxis=dict(tickangle=-45),
                            yaxis=dict(tickformat='.1f', ticksuffix='%'),
                            font=dict(family='IBM Plex Sans')
                        )

                        st.plotly_chart(fig_resumo, width='stretch', config={'displayModeBar': False})

                        df_componentes['ranking'] = df_componentes['total'].rank(method='first', ascending=False).astype(int)
                        # Merge com df_selecionado para ter acesso às colunas de peso
                        colunas_peso_possiveis = [v for v in VARIAVEIS_PONDERACAO.values() if v is not None]
                        colunas_peso_disponiveis = ['Instituição'] + [c for c in colunas_peso_possiveis if c in df_selecionado.columns]
                        if len(colunas_peso_disponiveis) > 1:
                            df_componentes_merge = df_componentes.merge(
                                df_selecionado[colunas_peso_disponiveis].drop_duplicates(),
                                on='Instituição',
                                how='left'
                            )
                        else:
                            df_componentes_merge = df_componentes.copy()
                        media_grupo_raw = calcular_media_ponderada(df_componentes_merge, 'total', coluna_peso_resumo)
                        df_export_base = df_componentes.copy()
                        df_export_base['Período'] = periodo_resumo
                        df_export_base['Indicador'] = indicador_label
                        df_export_base['Valor'] = df_export_base['total']
                        df_export_base['Média do Grupo'] = media_grupo_raw
                        df_export_base['Tipo de Média'] = tipo_media_label
                        df_export_base['Diferença vs Média'] = df_export_base['Valor'] - media_grupo_raw
                        df_export_base = df_export_base[[
                            'Período',
                            'Instituição',
                            'Indicador',
                            'Valor',
                            'ranking',
                            'Média do Grupo',
                            'Tipo de Média',
                            'Diferença vs Média'
                        ]].rename(columns={'ranking': 'Ranking'})

                        df_export_comp = df_percent.melt(
                            id_vars=['Instituição'],
                            value_vars=componentes_disponiveis,
                            var_name='Componente',
                            value_name='Participação (%)'
                        )
                        df_export_comp['Período'] = periodo_resumo
                        df_export_comp['Indicador'] = indicador_label

                        buffer_excel = BytesIO()
                        with pd.ExcelWriter(buffer_excel, engine='xlsxwriter') as writer:
                            df_export_base.to_excel(writer, index=False, sheet_name='resumo')
                            df_export_comp.to_excel(writer, index=False, sheet_name='composicao')
                        buffer_excel.seek(0)

                        st.download_button(
                            label="Exportar Excel",
                            data=buffer_excel,
                            file_name=f"resumo_{periodo_resumo.replace('/', '-')}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            key="exportar_resumo_excel"
                        )
                else:
                    df_selecionado['ranking'] = df_selecionado[indicador_col].rank(method='first', ascending=False).astype(int)
                    df_selecionado['diff_media'] = df_selecionado['valor_display'] - media_display

                    if media_display and media_display != 0:
                        df_selecionado['diff_pct'] = (df_selecionado['valor_display'] / media_display - 1) * 100
                        df_selecionado['diff_pct_text'] = df_selecionado['diff_pct'].map(lambda v: f"{v:.1f}%")
                    else:
                        df_selecionado['diff_pct_text'] = "N/A"

                    df_selecionado['valor_text'] = df_selecionado['valor_display'].map(
                        lambda v: formatar_numero(v, format_info)
                    )
                    df_selecionado['diff_text'] = df_selecionado['diff_media'].map(
                        lambda v: formatar_numero(v, format_info, incluir_sinal=True)
                    )

                    n_bancos = len(df_selecionado)
                    orientacao_horizontal = n_bancos > 15
                    altura_grafico = max(650, n_bancos * 24) if orientacao_horizontal else 650

                    cores_plotly = px.colors.qualitative.Plotly
                    cores_barras = []
                    idx_cor = 0
                    for banco in df_selecionado['Instituição']:
                        cor = obter_cor_banco(banco)
                        if not cor:
                            cor = cores_plotly[idx_cor % len(cores_plotly)]
                            idx_cor += 1
                        cores_barras.append(cor)

                    fig_resumo = go.Figure()
                    banco_hover = "%{y}" if orientacao_horizontal else "%{x}"
                    fig_resumo.add_trace(go.Bar(
                        x=df_selecionado['valor_display'] if orientacao_horizontal else df_selecionado['Instituição'],
                        y=df_selecionado['Instituição'] if orientacao_horizontal else df_selecionado['valor_display'],
                        marker=dict(color=cores_barras, opacity=0.85),
                        name=indicador_label,
                        orientation='h' if orientacao_horizontal else 'v',
                        customdata=np.stack([
                            df_selecionado['ranking'],
                            df_selecionado['diff_text'],
                            df_selecionado['diff_pct_text'],
                            df_selecionado['valor_text'],
                        ], axis=-1),
                        hovertemplate=(
                            f"<b>{banco_hover}</b><br>"
                            f"{indicador_label}: %{{customdata[3]}}<br>"
                            "Ranking: %{customdata[0]}<br>"
                            "Diferença vs média: %{customdata[1]}<br>"
                            "Diferença vs média (%): %{customdata[2]}"
                            "<extra></extra>"
                        )
                    ))

                    if orientacao_horizontal:
                        fig_resumo.add_trace(go.Scatter(
                            x=[media_display] * len(df_selecionado),
                            y=df_selecionado['Instituição'],
                            mode='lines',
                            name=label_media,
                            line=dict(color='#1f77b4', dash='dash')
                        ))
                    else:
                        fig_resumo.add_trace(go.Scatter(
                            x=df_selecionado['Instituição'],
                            y=[media_display] * len(df_selecionado),
                            mode='lines',
                            name=label_media,
                            line=dict(color='#1f77b4', dash='dash')
                        ))

                    fig_resumo.update_layout(
                        title=f"{indicador_label} - {periodo_resumo} ({len(df_selecionado)} instituições)",
                        xaxis_title=indicador_label if orientacao_horizontal else "instituições",
                        yaxis_title="instituições" if orientacao_horizontal else indicador_label,
                        plot_bgcolor='#f8f9fa',
                        paper_bgcolor='white',
                        height=altura_grafico,
                        showlegend=True,
                        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
                        xaxis=dict(
                            tickangle=-45 if not orientacao_horizontal else 0,
                            tickformat=format_info['tickformat'] if orientacao_horizontal else None,
                            ticksuffix=format_info['ticksuffix'] if orientacao_horizontal else None
                        ),
                        yaxis=dict(
                            tickformat=format_info['tickformat'] if not orientacao_horizontal else None,
                            ticksuffix=format_info['ticksuffix'] if not orientacao_horizontal else None
                        ),
                        font=dict(family='IBM Plex Sans')
                    )

                    st.plotly_chart(fig_resumo, width='stretch', config={'displayModeBar': False})

                    media_grupo_raw = calcular_media_ponderada(df_selecionado, indicador_col, coluna_peso_resumo)
                    df_export = df_selecionado.copy()
                    df_export['Período'] = periodo_resumo
                    df_export['Indicador'] = indicador_label
                    df_export['Valor'] = df_export[indicador_col]
                    df_export['Média do Grupo'] = media_grupo_raw
                    df_export['Tipo de Média'] = tipo_media_label
                    df_export['Diferença vs Média'] = df_export['Valor'] - media_grupo_raw
                    df_export = df_export[[
                        'Período',
                        'Instituição',
                        'Indicador',
                        'Valor',
                        'ranking',
                        'Média do Grupo',
                        'Tipo de Média',
                        'Diferença vs Média'
                    ]].rename(columns={'ranking': 'Ranking'})

                    buffer_excel = BytesIO()
                    with pd.ExcelWriter(buffer_excel, engine='xlsxwriter') as writer:
                        df_export.to_excel(writer, index=False, sheet_name='resumo')
                    buffer_excel.seek(0)

                    st.download_button(
                        label="Exportar Excel",
                        data=buffer_excel,
                        file_name=f"resumo_{periodo_resumo.replace('/', '-')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="exportar_resumo_excel"
                    )
    else:
        st.info("carregando dados automaticamente do github...")
        st.markdown("por favor, aguarde alguns segundos e recarregue a página")

elif menu == "Capital Regulatório":
    st.markdown("## infos de capital")
    st.caption("análise de indicadores de capital usando dados do Relatório 5 (IFData/Olinda).")

    if 'dados_capital' in st.session_state and st.session_state['dados_capital']:
        df_capital = pd.concat(st.session_state['dados_capital'].values(), ignore_index=True)

        # Resolver nomes de instituições que estão como códigos [IF xxxxx]
        # Usa múltiplas fontes: dict_aliases, df_aliases, e dados_periodos como fallback
        dict_aliases = st.session_state.get('dict_aliases', {})
        df_aliases = st.session_state.get('df_aliases', None)
        dados_periodos = st.session_state.get('dados_periodos', None)
        df_capital = resolver_nomes_instituicoes_capital(df_capital, dict_aliases, df_aliases, dados_periodos)

        # Mapeamento flexível de colunas (nome esperado -> alternativas)
        mapa_colunas_capital = {
            'Capital Principal': ['Capital Principal', 'Capital Principal para Comparação com RWA (a)'],
            'Capital Complementar': ['Capital Complementar', 'Capital Complementar (b)'],
            'Capital Nível II': ['Capital Nível II', 'Capital Nível II (d)'],
            'RWA Total': ['RWA Total', 'Ativos Ponderados pelo Risco (RWA) (j) = (f) + (g) + (h) + (i)', 'Ativos Ponderados pelo Risco (RWA) (j)', 'RWA'],
            'Índice de Basileia Capital': ['Índice de Basileia Capital', 'Índice de Basileia (n) = (e) / (j)', 'Índice de Basileia'],
        }

        # Encontrar colunas disponíveis
        colunas_encontradas = {}
        colunas_faltantes = []
        for nome_padrao, alternativas in mapa_colunas_capital.items():
            encontrada = None
            for alt in alternativas:
                if alt in df_capital.columns:
                    encontrada = alt
                    break
            if encontrada:
                colunas_encontradas[nome_padrao] = encontrada
            else:
                colunas_faltantes.append(nome_padrao)

        # Verificar colunas essenciais para gráfico de composição (CET1/AT1/T2)
        colunas_composicao = ['Capital Principal', 'Capital Complementar', 'Capital Nível II', 'RWA Total']
        faltantes_composicao = [c for c in colunas_composicao if c in colunas_faltantes]

        # Verificar se temos Índice de Basileia pré-calculado como fallback
        tem_indice_basileia_precalc = 'Índice de Basileia Capital' in colunas_encontradas

        if colunas_faltantes:
            # Mostrar aviso mas não bloquear
            if faltantes_composicao and not tem_indice_basileia_precalc:
                st.warning(f"Colunas ausentes no cache de capital: {', '.join(colunas_faltantes)}. Algumas visualizações podem estar indisponíveis.")
            else:
                st.info(f"Colunas ausentes: {', '.join(colunas_faltantes)}. Usando índices pré-calculados quando disponíveis.")
            with st.expander("Colunas disponíveis no cache"):
                st.write(sorted([c for c in df_capital.columns if c not in ['Instituição', 'CodInst', 'Período']]))

        # Continuar mesmo com colunas faltantes
        periodos_capital = ordenar_periodos(df_capital['Período'].dropna().unique(), reverso=True)

        if len(periodos_capital) > 0:

            # Seletor de tipo de gráfico
            tipos_graficos = ["Índice de Basileia Total"]
            col_tipo_graf, col_periodo_cap, col_media_cap = st.columns([2, 1.5, 1.8])

            with col_tipo_graf:
                tipo_grafico_capital = st.selectbox(
                    "tipo de gráfico",
                    tipos_graficos,
                    key="tipo_grafico_capital"
                )
            with col_periodo_cap:
                periodo_capital = st.selectbox(
                    "período",
                    periodos_capital,
                    index=0,
                    key="periodo_capital",
                    format_func=periodo_para_exibicao
                )
            with col_media_cap:
                tipo_media_cap_label = st.selectbox(
                    "ponderar média por",
                    list(VARIAVEIS_PONDERACAO.keys()),
                    index=0,
                    key="tipo_media_capital"
                )
                coluna_peso_capital = VARIAVEIS_PONDERACAO[tipo_media_cap_label]

            if tipo_grafico_capital == "Índice de Basileia Total":
                # Filtrar dados do período
                df_periodo_cap = df_capital[df_capital['Período'] == periodo_capital].copy()

                # Verificar se podemos calcular composição (CET1/AT1/T2) ou usar índice pré-calculado
                pode_calcular_composicao = all(
                    col in colunas_encontradas
                    for col in ['Capital Principal', 'Capital Complementar', 'Capital Nível II', 'RWA Total']
                )

                if pode_calcular_composicao:
                    # Usar colunas mapeadas
                    col_capital_principal = colunas_encontradas['Capital Principal']
                    col_capital_complementar = colunas_encontradas['Capital Complementar']
                    col_capital_nivel2 = colunas_encontradas['Capital Nível II']
                    col_rwa_total = colunas_encontradas['RWA Total']

                    # Calcular CET1, AT1, T2 como percentuais do RWA Total
                    # CET1 = Capital Principal / RWA Total * 100
                    # AT1 = Capital Complementar / RWA Total * 100
                    # T2 = Capital Nível II / RWA Total * 100

                    # Tratar RWA Total zero ou ausente
                    df_periodo_cap['RWA_valido'] = (
                        df_periodo_cap[col_rwa_total].notna() &
                        (df_periodo_cap[col_rwa_total] != 0)
                    )

                    df_periodo_cap['CET1 (%)'] = np.where(
                        df_periodo_cap['RWA_valido'],
                        (df_periodo_cap[col_capital_principal] / df_periodo_cap[col_rwa_total]) * 100,
                        np.nan
                    )
                    df_periodo_cap['AT1 (%)'] = np.where(
                        df_periodo_cap['RWA_valido'],
                        (df_periodo_cap[col_capital_complementar] / df_periodo_cap[col_rwa_total]) * 100,
                        np.nan
                    )
                    df_periodo_cap['T2 (%)'] = np.where(
                        df_periodo_cap['RWA_valido'],
                        (df_periodo_cap[col_capital_nivel2] / df_periodo_cap[col_rwa_total]) * 100,
                        np.nan
                    )

                    # Índice de Basileia Total = CET1 + AT1 + T2
                    df_periodo_cap['Índice de Basileia Total (%)'] = (
                        df_periodo_cap['CET1 (%)'] +
                        df_periodo_cap['AT1 (%)'] +
                        df_periodo_cap['T2 (%)']
                    )
                elif 'Índice de Basileia Capital' in colunas_encontradas:
                    # Usar índice pré-calculado da API
                    col_indice_basileia = colunas_encontradas['Índice de Basileia Capital']
                    # Converter de decimal (0-1) para percentual se necessário
                    valores_ib = df_periodo_cap[col_indice_basileia]
                    if valores_ib.max() <= 1:  # Valores em decimal
                        df_periodo_cap['Índice de Basileia Total (%)'] = valores_ib * 100
                    else:
                        df_periodo_cap['Índice de Basileia Total (%)'] = valores_ib

                    # Marcar que não temos composição
                    df_periodo_cap['RWA_valido'] = True  # Assumir válido para exibição
                    df_periodo_cap['CET1 (%)'] = np.nan
                    df_periodo_cap['AT1 (%)'] = np.nan
                    df_periodo_cap['T2 (%)'] = np.nan
                    st.caption("ℹ️ Usando Índice de Basileia pré-calculado (composição CET1/AT1/T2 não disponível)")
                else:
                    st.error("Não foi possível calcular o Índice de Basileia. Verifique se o cache possui as colunas necessárias.")
                    st.stop()

                # Merge com dados principais para obter variáveis de ponderação
                if 'dados_periodos' in st.session_state and st.session_state['dados_periodos']:
                    df_dados_periodo = st.session_state['dados_periodos'].get(periodo_capital)
                    if df_dados_periodo is not None:
                        # Todas as colunas de peso possíveis
                        colunas_peso_possiveis = [v for v in VARIAVEIS_PONDERACAO.values() if v is not None]
                        colunas_peso = ['Instituição'] + colunas_peso_possiveis
                        colunas_disponiveis = [c for c in colunas_peso if c in df_dados_periodo.columns]
                        if len(colunas_disponiveis) > 1:  # Pelo menos Instituição + uma coluna de peso
                            df_peso = df_dados_periodo[colunas_disponiveis].drop_duplicates(subset=['Instituição'])
                            df_periodo_cap = df_periodo_cap.merge(df_peso, on='Instituição', how='left')

                # --- Seleção de Bancos (mesmo padrão do Resumo) ---
                col_peers_cap, col_bancos_cap = st.columns([1.2, 2.8])

                peers_disponiveis_cap = []
                if 'colunas_classificacao' in st.session_state and 'df_aliases' in st.session_state:
                    peers_disponiveis_cap = st.session_state['colunas_classificacao']

                with col_peers_cap:
                    peers_selecionados_cap = st.multiselect(
                        "grupos de peers",
                        peers_disponiveis_cap,
                        key="peers_capital"
                    )

                    usar_top_universo_cap = False
                    top_universo_n_cap = 30
                    if not peers_selecionados_cap:
                        usar_top_universo_cap = st.checkbox(
                            "selecionar automaticamente top N do universo",
                            value=True,
                            key="top_universo_toggle_capital"
                        )
                        top_universo_n_cap = st.selectbox(
                            "top N (universo)",
                            [10, 20, 30, 40],
                            index=2,
                            key="top_universo_n_capital"
                        )

                bancos_do_peer_cap = []
                if peers_selecionados_cap and 'df_aliases' in st.session_state:
                    df_aliases = st.session_state['df_aliases']
                    peer_vals = df_aliases[peers_selecionados_cap].fillna(0).apply(
                        lambda col: col.astype(str).str.strip().isin(["1", "1.0"])
                    )
                    mask_peer = peer_vals.any(axis=1)
                    bancos_do_peer_cap = df_aliases.loc[mask_peer, 'Alias Banco'].tolist()

                df_periodo_universo_cap = df_periodo_cap.copy()

                if peers_selecionados_cap and bancos_do_peer_cap:
                    df_periodo_cap = df_periodo_cap[df_periodo_cap['Instituição'].isin(bancos_do_peer_cap)]

                bancos_todos_cap = df_periodo_cap['Instituição'].dropna().unique().tolist()
                dict_aliases = st.session_state.get('dict_aliases', {})
                bancos_todos_cap = ordenar_bancos_com_alias(bancos_todos_cap, dict_aliases)

                # Definir bancos default
                bancos_default_cap = bancos_do_peer_cap[:10] if bancos_do_peer_cap else []
                if usar_top_universo_cap:
                    df_universo_valid_cap = df_periodo_universo_cap.dropna(subset=['Índice de Basileia Total (%)']).copy()
                    if not df_universo_valid_cap.empty:
                        df_universo_top_cap = df_universo_valid_cap.sort_values(
                            'Índice de Basileia Total (%)', ascending=False
                        ).head(top_universo_n_cap)
                        bancos_default_cap = df_universo_top_cap['Instituição'].tolist()

                bancos_default_cap = [banco for banco in bancos_default_cap if banco in bancos_todos_cap]

                with col_bancos_cap:
                    bancos_selecionados_cap = st.multiselect(
                        "selecionar instituições (até 40)",
                        bancos_todos_cap,
                        default=bancos_default_cap,
                        key="bancos_capital"
                    )

                # Controles Top N
                col_top_cap, col_ordem_cap, col_sort_cap = st.columns([1.4, 1.4, 1.8])
                with col_top_cap:
                    usar_top_n_cap = st.toggle("usar top/bottom n", value=True, key="usar_top_capital")
                    top_n_capital = st.selectbox("n", [10, 15, 20], index=0, key="top_n_capital")
                with col_ordem_cap:
                    direcao_top_cap = st.radio(
                        "top/bottom",
                        ["Top", "Bottom"],
                        horizontal=True,
                        key="top_bottom_capital"
                    )
                with col_sort_cap:
                    modo_ordenacao_cap = st.radio(
                        "ordenação",
                        ["Ordenar por valor", "Manter ordem de seleção"],
                        horizontal=True,
                        key="ordenacao_capital"
                    )

                # Limitar a 40 bancos
                max_bancos_cap = 40
                if bancos_selecionados_cap and len(bancos_selecionados_cap) > max_bancos_cap:
                    st.warning(f"limite de {max_bancos_cap} instituições excedido; exibindo as primeiras {max_bancos_cap}.")
                    bancos_selecionados_cap = bancos_selecionados_cap[:max_bancos_cap]

                # Aplicar filtros Top N
                if usar_top_n_cap or not bancos_selecionados_cap:
                    df_periodo_valid_cap = df_periodo_cap.dropna(subset=['Índice de Basileia Total (%)']).copy()
                    if df_periodo_valid_cap.empty:
                        st.info("não há dados suficientes para o período selecionado.")
                        df_selecionado_cap = pd.DataFrame()
                    else:
                        ascending = direcao_top_cap == "Bottom"
                        df_selecionado_cap = df_periodo_valid_cap.sort_values(
                            'Índice de Basileia Total (%)', ascending=ascending
                        ).head(top_n_capital)
                else:
                    df_selecionado_cap = df_periodo_cap[df_periodo_cap['Instituição'].isin(bancos_selecionados_cap)].copy()

                df_selecionado_cap = df_selecionado_cap.dropna(subset=['Índice de Basileia Total (%)'])

                if df_selecionado_cap.empty:
                    st.info("selecione instituições ou ajuste os filtros para visualizar os dados de capital.")
                else:
                    # Ordenação final
                    if modo_ordenacao_cap == "Ordenar por valor":
                        ordenar_asc = direcao_top_cap == "Bottom"
                        df_selecionado_cap = df_selecionado_cap.sort_values(
                            'Índice de Basileia Total (%)', ascending=ordenar_asc
                        )
                    elif bancos_selecionados_cap:
                        ordem = bancos_selecionados_cap
                        df_selecionado_cap['ordem'] = pd.Categorical(
                            df_selecionado_cap['Instituição'], categories=ordem, ordered=True
                        )
                        df_selecionado_cap = df_selecionado_cap.sort_values('ordem')

                    # Calcular médias (simples ou ponderadas)
                    media_basileia = calcular_media_ponderada(df_selecionado_cap, 'Índice de Basileia Total (%)', coluna_peso_capital)
                    media_cet1 = calcular_media_ponderada(df_selecionado_cap, 'CET1 (%)', coluna_peso_capital)
                    media_at1 = calcular_media_ponderada(df_selecionado_cap, 'AT1 (%)', coluna_peso_capital)
                    media_t2 = calcular_media_ponderada(df_selecionado_cap, 'T2 (%)', coluna_peso_capital)
                    label_media_cap = get_label_media(coluna_peso_capital)

                    # Calcular ranking
                    df_selecionado_cap['Ranking'] = df_selecionado_cap['Índice de Basileia Total (%)'].rank(
                        method='first', ascending=False
                    ).astype(int)

                    # Diferença vs média
                    df_selecionado_cap['Diferença vs Média (%)'] = (
                        df_selecionado_cap['Índice de Basileia Total (%)'] - media_basileia
                    )

                    # --- Gráfico de Barras Empilhadas ---
                    n_bancos_cap = len(df_selecionado_cap)

                    # Cores para os componentes
                    cores_componentes = {
                        'CET1 (%)': '#1f77b4',  # Azul
                        'AT1 (%)': '#ff7f0e',   # Laranja
                        'T2 (%)': '#2ca02c'     # Verde
                    }

                    fig_capital = go.Figure()

                    # Adicionar barras empilhadas para CET1, AT1, T2
                    for componente, cor in cores_componentes.items():
                        nome_display = componente.replace(' (%)', '')
                        fig_capital.add_trace(go.Bar(
                            x=df_selecionado_cap['Instituição'],
                            y=df_selecionado_cap[componente],
                            name=nome_display,
                            marker_color=cor,
                            hovertemplate=(
                                "<b>%{x}</b><br>"
                                f"{nome_display}: %{{y:.2f}}%<extra></extra>"
                            )
                        ))

                    # Adicionar data labels com o Índice de Basileia Total no topo das barras
                    fig_capital.add_trace(go.Scatter(
                        x=df_selecionado_cap['Instituição'],
                        y=df_selecionado_cap['Índice de Basileia Total (%)'],
                        mode='text',
                        text=df_selecionado_cap['Índice de Basileia Total (%)'].apply(lambda x: f"{x:.2f}%"),
                        textposition='top center',
                        textfont=dict(size=10, color='#333'),
                        showlegend=False,
                        hoverinfo='skip'
                    ))

                    # Adicionar linha de média
                    fig_capital.add_trace(go.Scatter(
                        x=df_selecionado_cap['Instituição'],
                        y=[media_basileia] * n_bancos_cap,
                        mode='lines',
                        name=f'{label_media_cap} ({media_basileia:.2f}%)',
                        line=dict(color='#3498db', dash='dash', width=2),
                        hovertemplate=f"{label_media_cap}: {media_basileia:.2f}%<extra></extra>"
                    ))

                    # Adicionar linha horizontal do Mínimo Regulatório (10,5%)
                    MINIMO_REGULATORIO = 10.5
                    fig_capital.add_trace(go.Scatter(
                        x=df_selecionado_cap['Instituição'],
                        y=[MINIMO_REGULATORIO] * n_bancos_cap,
                        mode='lines',
                        name=f'Mínimo Regulatório ({MINIMO_REGULATORIO:.1f}%)',
                        line=dict(color='#e74c3c', dash='solid', width=2),
                        hovertemplate=f"Mínimo Regulatório: {MINIMO_REGULATORIO:.1f}%<extra></extra>"
                    ))

                    fig_capital.update_layout(
                        title=f"Índice de Basileia Total - {periodo_capital} ({n_bancos_cap} instituições)",
                        xaxis_title="instituições",
                        yaxis_title="índice (%)",
                        plot_bgcolor='#f8f9fa',
                        paper_bgcolor='white',
                        height=max(650, n_bancos_cap * 24),
                        barmode='stack',
                        showlegend=True,
                        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
                        xaxis=dict(tickangle=-45),
                        yaxis=dict(tickformat='.2f', ticksuffix='%'),
                        font=dict(family='IBM Plex Sans')
                    )

                    st.plotly_chart(fig_capital, width='stretch', config={'displayModeBar': False})

                    # --- Exportação Excel/CSV ---
                    df_export_capital = df_selecionado_cap[[
                        'Instituição', 'CET1 (%)', 'AT1 (%)', 'T2 (%)',
                        'Índice de Basileia Total (%)', 'Ranking', 'Diferença vs Média (%)'
                    ]].copy()
                    df_export_capital.insert(0, 'Período', periodo_capital)

                    # Adicionar médias e mínimo regulatório para referência
                    df_export_capital['Tipo de Média'] = tipo_media_cap_label
                    df_export_capital['Média CET1 (%)'] = round(media_cet1, 2)
                    df_export_capital['Média AT1 (%)'] = round(media_at1, 2)
                    df_export_capital['Média T2 (%)'] = round(media_t2, 2)
                    df_export_capital['Média Basileia (%)'] = round(media_basileia, 2)
                    df_export_capital['Mínimo Regulatório (%)'] = MINIMO_REGULATORIO

                    # Formatar valores percentuais com 2 casas decimais
                    colunas_pct_export = ['CET1 (%)', 'AT1 (%)', 'T2 (%)', 'Índice de Basileia Total (%)', 'Diferença vs Média (%)']
                    for col in colunas_pct_export:
                        df_export_capital[col] = df_export_capital[col].apply(
                            lambda x: round(x, 2) if pd.notna(x) else None
                        )

                    col_excel, col_csv = st.columns(2)

                    with col_excel:
                        buffer_excel_cap = BytesIO()
                        with pd.ExcelWriter(buffer_excel_cap, engine='xlsxwriter') as writer:
                            df_export_capital.to_excel(writer, index=False, sheet_name='indice_basileia')
                        buffer_excel_cap.seek(0)

                        st.download_button(
                            label="Exportar Excel",
                            data=buffer_excel_cap,
                            file_name=f"indice_basileia_{periodo_capital.replace('/', '-')}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            key="exportar_capital_excel"
                        )

                    with col_csv:
                        csv_data_cap = df_export_capital.to_csv(index=False)
                        st.download_button(
                            label="Exportar CSV",
                            data=csv_data_cap,
                            file_name=f"indice_basileia_{periodo_capital.replace('/', '-')}.csv",
                            mime="text/csv",
                            key="exportar_capital_csv"
                        )

                    # --- Tabela com os dados ---
                    st.markdown("### dados detalhados")

                    # Preparar tabela para exibição
                    df_tabela = df_selecionado_cap[[
                        'Instituição', 'CET1 (%)', 'AT1 (%)', 'T2 (%)',
                        'Índice de Basileia Total (%)', 'Ranking', 'Diferença vs Média (%)'
                    ]].copy()
                    df_tabela.insert(0, 'Período', periodo_capital)

                    # Formatar colunas percentuais
                    colunas_pct = ['CET1 (%)', 'AT1 (%)', 'T2 (%)', 'Índice de Basileia Total (%)', 'Diferença vs Média (%)']

                    # Identificar linhas com RWA inválido (para tooltip)
                    df_tabela_orig = df_selecionado_cap.copy()
                    df_tabela['RWA Status'] = df_tabela_orig['RWA_valido'].apply(
                        lambda x: '✓' if x else 'RWA zero/ausente'
                    )

                    # Função para formatar com 2 casas decimais
                    def format_pct(x):
                        if pd.isna(x):
                            return "N/A"
                        return f"{x:.2f}%"

                    for col in colunas_pct:
                        df_tabela[col] = df_tabela[col].apply(format_pct)

                    st.dataframe(
                        df_tabela,
                        width='stretch',
                        hide_index=True,
                        column_config={
                            'Período': st.column_config.TextColumn('Período'),
                            'Instituição': st.column_config.TextColumn('Instituição'),
                            'CET1 (%)': st.column_config.TextColumn('CET1 (%)'),
                            'AT1 (%)': st.column_config.TextColumn('AT1 (%)'),
                            'T2 (%)': st.column_config.TextColumn('T2 (%)'),
                            'Índice de Basileia Total (%)': st.column_config.TextColumn('Índice de Basileia Total (%)'),
                            'Ranking': st.column_config.NumberColumn('Ranking'),
                            'Diferença vs Média (%)': st.column_config.TextColumn('Dif. vs Média (%)'),
                            'RWA Status': st.column_config.TextColumn(
                                'RWA Status',
                                help='Indica se o RWA Total é válido. Se zero ou ausente, os cálculos de índices ficam como N/A.'
                            )
                        }
                    )

                    # Exibir médias do grupo
                    st.caption(
                        f"**médias do grupo exibido:** "
                        f"CET1: {media_cet1:.2f}% | "
                        f"AT1: {media_at1:.2f}% | "
                        f"T2: {media_t2:.2f}% | "
                        f"Índice de Basileia Total: {media_basileia:.2f}%"
                    )

    else:
        st.info("cache de capital não disponível.")
        st.markdown(
            "para usar esta aba, extraia os dados de capital na seção 'controle avançado' → 'extrair capital (relatório 5)' na sidebar."
        )

elif menu == "Histórico Individual":
    if 'dados_periodos' in st.session_state and st.session_state['dados_periodos']:
        df = get_dados_concatenados()  # OTIMIZAÇÃO: usar cache

        if len(df) > 0 and 'Instituição' in df.columns:
            bancos_todos = df['Instituição'].dropna().unique().tolist()
            dict_aliases = st.session_state.get('dict_aliases', {})
            bancos_disponiveis = ordenar_bancos_com_alias(bancos_todos, dict_aliases)

            if len(bancos_disponiveis) > 0:
                banco_selecionado = st.selectbox("selecione uma instituição", bancos_disponiveis, key="banco_individual")

                if banco_selecionado:
                    df_banco = df[df['Instituição'] == banco_selecionado].copy()
                    df_banco['ano'] = df_banco['Período'].str.split('/').str[1].astype(int)
                    df_banco['trimestre'] = df_banco['Período'].str.split('/').str[0].astype(int)
                    df_banco = df_banco.sort_values(['ano', 'trimestre'])

                    st.markdown(f"## {banco_selecionado}")

                    periodos_disponiveis = ordenar_periodos(df_banco['Período'].unique())
                    periodos_dropdown = ordenar_periodos(df_banco['Período'].unique(), reverso=True)

                    # Seletores de período
                    col_p1, col_p2, col_p3 = st.columns([1, 1, 2])
                    with col_p1:
                        periodo_inicial = st.selectbox(
                            "período inicial",
                            periodos_dropdown,
                            index=len(periodos_dropdown) - 1,
                            key="periodo_ini_individual",
                            format_func=periodo_para_exibicao
                        )
                    with col_p2:
                        periodo_final = st.selectbox(
                            "período final",
                            periodos_dropdown,
                            index=0,
                            key="periodo_fin_individual",
                            format_func=periodo_para_exibicao
                        )
                    with col_p3:
                        if len(periodos_disponiveis) >= 2:
                            pdf_buffer = gerar_scorecard_pdf(banco_selecionado, df_banco, periodo_inicial, periodo_final)
                            if pdf_buffer:
                                st.markdown("")  # Espaçamento
                                st.download_button(
                                    label="baixar scorecard",
                                    data=pdf_buffer.getvalue(),
                                    file_name=f"scorecard_{banco_selecionado.replace(' ', '_')}.pdf",
                                    mime="application/pdf"
                                )

                    # Filtra dados pelo período selecionado
                    idx_ini = periodos_disponiveis.index(periodo_inicial)
                    idx_fin = periodos_disponiveis.index(periodo_final)
                    if idx_ini > idx_fin:
                        idx_ini, idx_fin = idx_fin, idx_ini
                    periodos_filtrados = periodos_disponiveis[idx_ini:idx_fin + 1]
                    df_banco_filtrado = df_banco[df_banco['Período'].isin(periodos_filtrados)]

                    # Dados do período final para as métricas
                    dados_periodo_final = df_banco[df_banco['Período'] == periodo_final].iloc[0]

                    # Métricas com colunas flexíveis
                    st.markdown(
                        """
                        <style>
                        div[data-testid="stMetric"] {
                            min-width: fit-content !important;
                        }
                        </style>
                        """,
                        unsafe_allow_html=True
                    )

                    col1, col2, col3, col4 = st.columns([1.3, 1, 1, 1])

                    with col1:
                        st.metric("carteira de crédito", formatar_valor(dados_periodo_final.get('Carteira de Crédito'), 'Carteira de Crédito'))
                    with col2:
                        st.metric("roe ac. ytd an.", formatar_valor(dados_periodo_final.get('ROE Ac. YTD an. (%)'), 'ROE Ac. YTD an. (%)'))
                    with col3:
                        st.metric("índice de basileia", formatar_valor(dados_periodo_final.get('Índice de Basileia'), 'Índice de Basileia'))
                    with col4:
                        st.metric("crédito/pl (%)", formatar_valor(dados_periodo_final.get('Crédito/PL (%)'), 'Crédito/PL (%)'))

                    st.markdown("---")
                    st.markdown("### evolução histórica das variáveis")

                    ordem_variaveis = [
                        'Ativo Total',
                        'Captações',
                        'Patrimônio Líquido',
                        'Carteira de Crédito',
                        'Crédito/Ativo (%)',
                        'Crédito/PL (%)',
                        'Crédito/Captações (%)',
                        'Lucro Líquido Acumulado YTD',
                        'ROE Ac. YTD an. (%)',
                        # Variáveis de Capital (Relatório 5)
                        'RWA Total',
                        'Capital Principal',
                        'Índice de Capital Principal',
                        'Índice de Capital Nível I',
                        'Razão de Alavancagem',
                    ]

                    # Filtra apenas as variáveis que existem e têm dados
                    variaveis = [v for v in ordem_variaveis if v in df_banco_filtrado.columns and df_banco_filtrado[v].notna().any()]

                    for i in range(0, len(variaveis), 3):
                        cols = st.columns(3)
                        for j, col_obj in enumerate(cols):
                            if i + j < len(variaveis):
                                var = variaveis[i + j]
                                with col_obj:
                                    # Usa gráfico de barras para Lucro Líquido Acumulado YTD
                                    tipo_grafico = 'barra' if var == 'Lucro Líquido Acumulado YTD' else 'linha'
                                    fig = criar_mini_grafico(df_banco_filtrado, var, var, tipo=tipo_grafico)
                                    st.plotly_chart(fig, width='stretch', config={'displayModeBar': False})
            else:
                st.warning("nenhuma instituição encontrada nos dados")
        else:
            st.warning("dados incompletos ou vazios")
    else:
        st.info("carregando dados automaticamente do github...")
        st.markdown("por favor, aguarde alguns segundos e recarregue a página")

elif menu == "Histórico Peers":
    if 'dados_periodos' in st.session_state and st.session_state['dados_periodos']:
        df = get_dados_concatenados()  # OTIMIZAÇÃO: usar cache

        if len(df) > 0 and 'Instituição' in df.columns:
            bancos_todos = df['Instituição'].dropna().unique().tolist()
            dict_aliases = st.session_state.get('dict_aliases', {})
            bancos_disponiveis = ordenar_bancos_com_alias(bancos_todos, dict_aliases)

            if len(bancos_disponiveis) > 0:
                col_select, col_vars, col_periodo = st.columns([2, 2, 2])

                with col_select:
                    peers_disponiveis = []
                    if 'colunas_classificacao' in st.session_state and 'df_aliases' in st.session_state:
                        peers_disponiveis = st.session_state['colunas_classificacao']

                    opcoes_peer = ['Nenhum'] + peers_disponiveis
                    peer_selecionado = st.selectbox("filtrar por peer", opcoes_peer, index=0)

                    bancos_selecionados = st.multiselect(
                        "selecionar instituições",
                        bancos_disponiveis,
                        default=bancos_disponiveis[:2],
                        key="bancos_serie_historica"
                    )

                with col_vars:
                    variaveis_disponiveis = [
                        'Ativo Total',
                        'Captações',
                        'Patrimônio Líquido',
                        'Carteira de Crédito',
                        'Crédito/Ativo (%)',
                        'Índice de Basileia',
                        'Crédito/PL (%)',
                        'Crédito/Captações (%)',
                        'Lucro Líquido Acumulado YTD',
                        'ROE Ac. YTD an. (%)',
                        # Variáveis de Capital (Relatório 5)
                        'RWA Total',
                        'Capital Principal',
                        'Índice de Capital Principal',
                        'Índice de Capital Nível I',
                        'Razão de Alavancagem',
                    ]
                    defaults_variaveis = [
                        'Carteira de Crédito',
                        'Patrimônio Líquido',
                        'Lucro Líquido Acumulado YTD',
                        'ROE Ac. YTD an. (%)',
                        'Índice de Basileia'
                    ]
                    defaults_variaveis = [v for v in defaults_variaveis if v in variaveis_disponiveis]

                    variaveis_selecionadas = st.multiselect(
                        "selecionar variáveis (até 10)",
                        variaveis_disponiveis,
                        default=defaults_variaveis,
                        max_selections=10,
                        key="variaveis_serie_historica"
                    )

                periodos_disponiveis = ordenar_periodos(df['Período'].dropna().unique())
                periodos_dropdown = ordenar_periodos(df['Período'].dropna().unique(), reverso=True)
                with col_periodo:
                    periodo_inicial = st.selectbox(
                        "período inicial",
                        periodos_dropdown,
                        index=len(periodos_dropdown) - 1,
                        key="periodo_ini_serie_historica",
                        format_func=periodo_para_exibicao
                    )
                    periodo_final = st.selectbox(
                        "período final",
                        periodos_dropdown,
                        index=0,
                        key="periodo_fin_serie_historica",
                        format_func=periodo_para_exibicao
                    )

                bancos_do_peer = []
                if peer_selecionado != 'Nenhum' and 'df_aliases' in st.session_state:
                    df_aliases = st.session_state['df_aliases']
                    coluna_peer = df_aliases[peer_selecionado]
                    mask_peer = (
                        coluna_peer.fillna(0).astype(str).str.strip().isin(["1", "1.0"])
                    )
                    bancos_do_peer = df_aliases.loc[mask_peer, 'Alias Banco'].tolist()

                bancos_para_comparar = sorted(set(bancos_do_peer) | set(bancos_selecionados))

                if bancos_para_comparar and variaveis_selecionadas:
                    idx_ini = periodos_disponiveis.index(periodo_inicial)
                    idx_fin = periodos_disponiveis.index(periodo_final)
                    if idx_ini > idx_fin:
                        idx_ini, idx_fin = idx_fin, idx_ini
                    periodos_filtrados = periodos_disponiveis[idx_ini:idx_fin + 1]

                    for variavel in variaveis_selecionadas:
                        format_info = get_axis_format(variavel)
                        fig = go.Figure()
                        export_frames = []
                        periodos_filtrados_lucro = periodos_filtrados
                        if variavel == 'Lucro Líquido Acumulado YTD':
                            st.markdown("**período lucro líquido acumulado ytd**")
                            col_lucro_ini, col_lucro_fim = st.columns(2)
                            with col_lucro_ini:
                                periodo_inicial_lucro = st.selectbox(
                                    "período inicial",
                                    periodos_dropdown,
                                    index=len(periodos_dropdown) - 1,
                                    key="periodo_ini_lucro_liquido",
                                    format_func=periodo_para_exibicao
                                )
                            with col_lucro_fim:
                                periodo_final_lucro = st.selectbox(
                                    "período final",
                                    periodos_dropdown,
                                    index=0,
                                    key="periodo_fin_lucro_liquido",
                                    format_func=periodo_para_exibicao
                                )
                            idx_lucro_ini = periodos_disponiveis.index(periodo_inicial_lucro)
                            idx_lucro_fin = periodos_disponiveis.index(periodo_final_lucro)
                            if idx_lucro_ini > idx_lucro_fin:
                                idx_lucro_ini, idx_lucro_fin = idx_lucro_fin, idx_lucro_ini
                            periodos_filtrados_lucro = periodos_disponiveis[idx_lucro_ini:idx_lucro_fin + 1]

                        for instituicao in bancos_para_comparar:
                            df_banco = df[df['Instituição'] == instituicao].copy()
                            if df_banco.empty or variavel not in df_banco.columns:
                                continue

                            df_banco = df_banco[df_banco['Período'].isin(
                                periodos_filtrados_lucro if variavel == 'Lucro Líquido Acumulado YTD' else periodos_filtrados
                            )]
                            df_banco['ano'] = df_banco['Período'].str.split('/').str[1].astype(int)
                            df_banco['trimestre'] = df_banco['Período'].str.split('/').str[0].astype(int)
                            df_banco = df_banco.sort_values(['ano', 'trimestre'])

                            y_values = df_banco[variavel] * format_info['multiplicador']
                            cor_banco = obter_cor_banco(instituicao) or None

                            if variavel == 'Lucro Líquido Acumulado YTD':
                                fig.add_trace(go.Bar(
                                    x=df_banco['Período'],
                                    y=y_values,
                                    name=instituicao,
                                    marker=dict(color=cor_banco),
                                    hovertemplate=f'<b>{instituicao}</b><br>%{{x}}<br>%{{y:{format_info["tickformat"]}}}{format_info["ticksuffix"]}<extra></extra>'
                                ))
                            else:
                                fig.add_trace(go.Scatter(
                                    x=df_banco['Período'],
                                    y=y_values,
                                    mode='lines',
                                    name=instituicao,
                                    line=dict(width=2, color=cor_banco),
                                    hovertemplate=f'<b>{instituicao}</b><br>%{{x}}<br>%{{y:{format_info["tickformat"]}}}{format_info["ticksuffix"]}<extra></extra>'
                                ))

                            export_frames.append(
                                df_banco[['Período', 'Instituição', variavel]].copy()
                            )

                        st.markdown(f"### {variavel}")
                        st.markdown("<div style='height: 0.5rem;'></div>", unsafe_allow_html=True)
                        fig.update_layout(
                            height=320,
                            margin=dict(l=10, r=10, t=40, b=30),
                            plot_bgcolor='#f8f9fa',
                            paper_bgcolor='white',
                            showlegend=True,
                            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
                            xaxis=dict(
                                showgrid=False,
                                tickmode='array' if variavel == 'Lucro Líquido Acumulado YTD' else None,
                                tickvals=periodos_filtrados_lucro if variavel == 'Lucro Líquido Acumulado YTD' else None,
                                ticktext=periodos_filtrados_lucro if variavel == 'Lucro Líquido Acumulado YTD' else None,
                                categoryorder='array' if variavel == 'Lucro Líquido Acumulado YTD' else None,
                                categoryarray=periodos_filtrados_lucro if variavel == 'Lucro Líquido Acumulado YTD' else None
                            ),
                            yaxis=dict(showgrid=True, gridcolor='#e0e0e0', tickformat=format_info['tickformat'], ticksuffix=format_info['ticksuffix']),
                            font=dict(family='IBM Plex Sans'),
                            barmode='group' if variavel == 'Lucro Líquido Acumulado YTD' else None
                        )

                        st.plotly_chart(fig, width='stretch', config={'displayModeBar': False})

                        if export_frames:
                            df_export = pd.concat(export_frames, ignore_index=True)
                            df_export['ano'] = df_export['Período'].str.split('/').str[1].astype(int)
                            df_export['trimestre'] = df_export['Período'].str.split('/').str[0].astype(int)
                            df_export = df_export.sort_values(['ano', 'trimestre', 'Instituição']).drop(columns=['ano', 'trimestre'])

                            buffer_excel = BytesIO()
                            with pd.ExcelWriter(buffer_excel, engine='xlsxwriter') as writer:
                                df_export.to_excel(writer, index=False, sheet_name='dados')
                            buffer_excel.seek(0)

                            nome_variavel = variavel.replace(' ', '_').replace('/', '_')
                            st.download_button(
                                label="Exportar Excel",
                                data=buffer_excel,
                                file_name="Serie_Historica_.xlsx",
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                key=f"exportar_excel_{nome_variavel}"
                            )
                else:
                    st.info("selecione instituições e variáveis para comparar")
            else:
                st.warning("nenhuma instituição encontrada nos dados")
        else:
            st.warning("dados incompletos ou vazios")
    else:
        st.info("carregando dados automaticamente do github...")
        st.markdown("por favor, aguarde alguns segundos e recarregue a página")

elif menu == "Scatter Plot":
    if 'dados_periodos' in st.session_state and st.session_state['dados_periodos']:
        df = get_dados_concatenados()  # OTIMIZAÇÃO: usar cache

        colunas_numericas = [col for col in df.columns if col not in ['Instituição', 'Período'] and df[col].dtype in ['float64', 'int64']]
        periodos = ordenar_periodos(df['Período'].unique(), reverso=True)

        # Lista de todos os bancos disponíveis com ordenação por alias
        bancos_todos = df['Instituição'].dropna().unique().tolist()
        dict_aliases = st.session_state.get('dict_aliases', {})
        todos_bancos = ordenar_bancos_com_alias(bancos_todos, dict_aliases)

        # Primeira linha: variáveis dos eixos e tamanho
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            var_x = st.selectbox("eixo x", colunas_numericas, index=colunas_numericas.index('Índice de Basileia') if 'Índice de Basileia' in colunas_numericas else 0)
        with col2:
            var_y = st.selectbox("eixo y", colunas_numericas, index=colunas_numericas.index('ROE Ac. YTD an. (%)') if 'ROE Ac. YTD an. (%)' in colunas_numericas else 1)
        with col3:
            opcoes_tamanho = ['Tamanho Fixo'] + colunas_numericas
            default_idx = opcoes_tamanho.index('Carteira de Crédito') if 'Carteira de Crédito' in opcoes_tamanho else 1
            var_size = st.selectbox("tamanho", opcoes_tamanho, index=default_idx)
        with col4:
            periodo_scatter = st.selectbox("período", periodos, index=0, format_func=periodo_para_exibicao)

        # Segunda linha: Top N e variável de ordenação
        col_t1, col_t2, col_t3 = st.columns([1, 1, 2])

        with col_t1:
            top_n_scatter = st.slider("top n", 5, 50, 15)
        with col_t2:
            var_top_n = st.selectbox("top n por", colunas_numericas, index=colunas_numericas.index('Carteira de Crédito') if 'Carteira de Crédito' in colunas_numericas else 0)

        # Terceira linha: Peers e Seleção de bancos
        col_f1, col_f2 = st.columns([1, 3])

        # Opções de Peers disponíveis
        peers_disponiveis = []
        if 'colunas_classificacao' in st.session_state and 'df_aliases' in st.session_state:
            peers_disponiveis = st.session_state['colunas_classificacao']

        with col_f1:
            opcoes_peer = ['Nenhum'] + peers_disponiveis
            peer_selecionado = st.selectbox("filtrar por peer", opcoes_peer, index=0)

        # Bancos do peer selecionado (automático: valor = 1)
        bancos_do_peer = []
        if peer_selecionado != 'Nenhum' and 'df_aliases' in st.session_state:
            df_aliases = st.session_state['df_aliases']
            coluna_peer = df_aliases[peer_selecionado]
            mask_peer = (
                coluna_peer.fillna(0).astype(str).str.strip().isin(["1", "1.0"])
            )
            bancos_do_peer = df_aliases.loc[mask_peer, 'Alias Banco'].tolist()

        # Multiselect sempre visível para selecionar bancos adicionais
        with col_f2:
            # Se houver peer selecionado, pré-seleciona os bancos do peer
            default_bancos = bancos_do_peer if bancos_do_peer else []
            bancos_selecionados = st.multiselect(
                "selecionar bancos",
                todos_bancos,
                default=default_bancos,
                key="bancos_multiselect"
            )

        # Aplica filtros ao dataframe
        df_periodo = df[df['Período'] == periodo_scatter]

        if peer_selecionado != 'Nenhum':
            df_periodo = df_periodo[df_periodo['Instituição'].isin(bancos_do_peer)]

        if bancos_selecionados:
            # Usa os bancos selecionados no multiselect
            df_scatter = df_periodo[df_periodo['Instituição'].isin(bancos_selecionados)]
        else:
            # Usa top N pela variável selecionada (remove NaN antes)
            df_periodo_valid = df_periodo.dropna(subset=[var_top_n])
            df_scatter = df_periodo_valid.nlargest(top_n_scatter, var_top_n)

        format_x = get_axis_format(var_x)
        format_y = get_axis_format(var_y)

        df_scatter_plot = df_scatter.copy()
        df_scatter_plot['x_display'] = df_scatter_plot[var_x] * format_x['multiplicador']
        df_scatter_plot['y_display'] = df_scatter_plot[var_y] * format_y['multiplicador']

        if var_size == 'Tamanho Fixo':
            tamanho_constante = 25
        else:
            format_size = get_axis_format(var_size)
            df_scatter_plot['size_display'] = df_scatter_plot[var_size] * format_size['multiplicador']

        fig_scatter = go.Figure()
        cores_plotly = px.colors.qualitative.Plotly
        idx_cor = 0

        for instituicao in df_scatter_plot['Instituição'].unique():
            df_inst = df_scatter_plot[df_scatter_plot['Instituição'] == instituicao]
            cor = obter_cor_banco(instituicao)
            if not cor:
                cor = cores_plotly[idx_cor % len(cores_plotly)]
                idx_cor += 1

            if var_size == 'Tamanho Fixo':
                marker_size = tamanho_constante
            else:
                marker_size = df_inst['size_display'] / df_scatter_plot['size_display'].max() * 100

            fig_scatter.add_trace(go.Scatter(
                x=df_inst['x_display'],
                y=df_inst['y_display'],
                mode='markers',
                name=instituicao,
                marker=dict(size=marker_size, color=cor, opacity=1.0, line=dict(width=1, color='white')),
                hovertemplate=f'<b>{instituicao}</b><br>{var_x}: %{{x:{format_x["tickformat"]}}}{format_x["ticksuffix"]}<br>{var_y}: %{{y:{format_y["tickformat"]}}}{format_y["ticksuffix"]}<extra></extra>'
            ))

        # Título dinâmico - Scatter Plot n=1
        st.markdown("#### Scatter Plot n=1")
        if bancos_selecionados:
            titulo_scatter = f'{var_y} vs {var_x} - {periodo_scatter} ({len(df_scatter)} bancos)'
        else:
            titulo_scatter = f'{var_y} vs {var_x} - {periodo_scatter} (top {top_n_scatter} por {var_top_n})'

        fig_scatter.update_layout(
            title=titulo_scatter,
            xaxis_title=var_x,
            yaxis_title=var_y,
            height=650,
            plot_bgcolor='#f8f9fa',
            paper_bgcolor='white',
            showlegend=True,
            legend=dict(orientation="v", yanchor="top", y=1, xanchor="left", x=1.02),
            xaxis=dict(tickformat=format_x['tickformat'], ticksuffix=format_x['ticksuffix']),
            yaxis=dict(tickformat=format_y['tickformat'], ticksuffix=format_y['ticksuffix']),
            font=dict(family='IBM Plex Sans')
        )

        st.plotly_chart(fig_scatter, width='stretch')

        # ============================================================
        # SCATTER PLOT n=2 - Comparação entre dois períodos
        # ============================================================
        st.markdown("---")
        st.markdown("#### Scatter Plot n=2")
        st.caption("Visualize a movimentação dos bancos entre dois períodos")

        # Seletores para os dois períodos
        col_p1, col_p2, col_p3, col_p4 = st.columns(4)

        with col_p1:
            var_x_n2 = st.selectbox(
                "eixo x",
                colunas_numericas,
                index=colunas_numericas.index('Índice de Basileia') if 'Índice de Basileia' in colunas_numericas else 0,
                key="var_x_n2"
            )
        with col_p2:
            var_y_n2 = st.selectbox(
                "eixo y",
                colunas_numericas,
                index=colunas_numericas.index('ROE Ac. YTD an. (%)') if 'ROE Ac. YTD an. (%)' in colunas_numericas else 1,
                key="var_y_n2"
            )
        with col_p3:
            # Período inicial (mais antigo por padrão)
            idx_inicial = min(1, len(periodos) - 1) if len(periodos) > 1 else 0
            periodo_inicial = st.selectbox(
                "período inicial",
                periodos,
                index=idx_inicial,
                key="periodo_inicial_n2",
                format_func=periodo_para_exibicao
            )
        with col_p4:
            # Período subsequente (mais recente por padrão)
            periodo_subseq = st.selectbox(
                "período subsequente",
                periodos,
                index=0,
                key="periodo_subseq_n2",
                format_func=periodo_para_exibicao
            )

        # Segunda linha: Top N e tamanho
        col_n2_t1, col_n2_t2, col_n2_t3 = st.columns([1, 1, 2])

        with col_n2_t1:
            top_n_scatter_n2 = st.slider("top n", 5, 50, 15, key="top_n_n2")
        with col_n2_t2:
            var_top_n_n2 = st.selectbox(
                "top n por",
                colunas_numericas,
                index=colunas_numericas.index('Carteira de Crédito') if 'Carteira de Crédito' in colunas_numericas else 0,
                key="var_top_n_n2"
            )
        with col_n2_t3:
            opcoes_tamanho_n2 = ['Tamanho Fixo'] + colunas_numericas
            default_idx_n2 = opcoes_tamanho_n2.index('Carteira de Crédito') if 'Carteira de Crédito' in opcoes_tamanho_n2 else 1
            var_size_n2 = st.selectbox("tamanho", opcoes_tamanho_n2, index=default_idx_n2, key="var_size_n2")

        # Terceira linha: Peers e Seleção de bancos
        col_n2_f1, col_n2_f2 = st.columns([1, 3])

        with col_n2_f1:
            peer_selecionado_n2 = st.selectbox(
                "filtrar por peer",
                opcoes_peer,
                index=0,
                key="peer_n2"
            )

        # Bancos do peer selecionado para n=2
        bancos_do_peer_n2 = []
        if peer_selecionado_n2 != 'Nenhum' and 'df_aliases' in st.session_state:
            df_aliases = st.session_state['df_aliases']
            coluna_peer_n2 = df_aliases[peer_selecionado_n2]
            mask_peer_n2 = (
                coluna_peer_n2.fillna(0).astype(str).str.strip().isin(["1", "1.0"])
            )
            bancos_do_peer_n2 = df_aliases.loc[mask_peer_n2, 'Alias Banco'].tolist()

        with col_n2_f2:
            default_bancos_n2 = bancos_do_peer_n2 if bancos_do_peer_n2 else []
            bancos_selecionados_n2 = st.multiselect(
                "selecionar bancos",
                todos_bancos,
                default=default_bancos_n2,
                key="bancos_multiselect_n2"
            )

        # Validação: períodos devem ser diferentes
        if periodo_inicial == periodo_subseq:
            st.warning("Selecione dois períodos diferentes para visualizar a movimentação.")
        else:
            # Filtra dados para os dois períodos
            df_p1 = df[df['Período'] == periodo_inicial].copy()
            df_p2 = df[df['Período'] == periodo_subseq].copy()

            # Aplica filtro de peer
            if peer_selecionado_n2 != 'Nenhum':
                df_p1 = df_p1[df_p1['Instituição'].isin(bancos_do_peer_n2)]
                df_p2 = df_p2[df_p2['Instituição'].isin(bancos_do_peer_n2)]

            # Aplica seleção de bancos ou top N
            if bancos_selecionados_n2:
                df_p1 = df_p1[df_p1['Instituição'].isin(bancos_selecionados_n2)]
                df_p2 = df_p2[df_p2['Instituição'].isin(bancos_selecionados_n2)]
            else:
                # Usa top N do período subsequente (mais recente)
                df_p2_valid = df_p2.dropna(subset=[var_top_n_n2])
                top_bancos = df_p2_valid.nlargest(top_n_scatter_n2, var_top_n_n2)['Instituição'].tolist()
                df_p1 = df_p1[df_p1['Instituição'].isin(top_bancos)]
                df_p2 = df_p2[df_p2['Instituição'].isin(top_bancos)]

            # Encontra bancos presentes em ambos os períodos
            bancos_comuns = set(df_p1['Instituição'].unique()) & set(df_p2['Instituição'].unique())

            if len(bancos_comuns) == 0:
                st.warning("Nenhum banco encontrado em ambos os períodos selecionados.")
            else:
                # Formatos dos eixos
                format_x_n2 = get_axis_format(var_x_n2)
                format_y_n2 = get_axis_format(var_y_n2)

                # Prepara dados com valores de exibição
                df_p1['x_display'] = df_p1[var_x_n2] * format_x_n2['multiplicador']
                df_p1['y_display'] = df_p1[var_y_n2] * format_y_n2['multiplicador']
                df_p2['x_display'] = df_p2[var_x_n2] * format_x_n2['multiplicador']
                df_p2['y_display'] = df_p2[var_y_n2] * format_y_n2['multiplicador']

                # Tamanho dos pontos
                if var_size_n2 != 'Tamanho Fixo':
                    format_size_n2 = get_axis_format(var_size_n2)
                    df_p1['size_display'] = df_p1[var_size_n2] * format_size_n2['multiplicador']
                    df_p2['size_display'] = df_p2[var_size_n2] * format_size_n2['multiplicador']
                    max_size = max(df_p1['size_display'].max(), df_p2['size_display'].max())

                fig_scatter_n2 = go.Figure()
                cores_plotly = px.colors.qualitative.Plotly
                idx_cor_n2 = 0

                for instituicao in sorted(bancos_comuns):
                    # Dados do período inicial
                    row_p1 = df_p1[df_p1['Instituição'] == instituicao]
                    # Dados do período subsequente
                    row_p2 = df_p2[df_p2['Instituição'] == instituicao]

                    if row_p1.empty or row_p2.empty:
                        continue

                    x1 = row_p1['x_display'].values[0]
                    y1 = row_p1['y_display'].values[0]
                    x2 = row_p2['x_display'].values[0]
                    y2 = row_p2['y_display'].values[0]

                    # Cor do banco
                    cor = obter_cor_banco(instituicao)
                    if not cor:
                        cor = cores_plotly[idx_cor_n2 % len(cores_plotly)]
                        idx_cor_n2 += 1

                    # Tamanho dos marcadores
                    if var_size_n2 == 'Tamanho Fixo':
                        marker_size_p1 = 20
                        marker_size_p2 = 20
                    else:
                        marker_size_p1 = row_p1['size_display'].values[0] / max_size * 80 if max_size > 0 else 20
                        marker_size_p2 = row_p2['size_display'].values[0] / max_size * 80 if max_size > 0 else 20

                    # Adiciona linha conectando os dois pontos (seta)
                    fig_scatter_n2.add_trace(go.Scatter(
                        x=[x1, x2],
                        y=[y1, y2],
                        mode='lines',
                        line=dict(color=cor, width=2),
                        showlegend=False,
                        hoverinfo='skip'
                    ))

                    # Ponto do período inicial (círculo vazio/anel)
                    fig_scatter_n2.add_trace(go.Scatter(
                        x=[x1],
                        y=[y1],
                        mode='markers',
                        name=f'{instituicao} ({periodo_inicial})',
                        marker=dict(
                            size=marker_size_p1,
                            color='white',
                            opacity=1.0,
                            line=dict(width=3, color=cor)
                        ),
                        hovertemplate=f'<b>{instituicao}</b> ({periodo_inicial})<br>{var_x_n2}: %{{x:{format_x_n2["tickformat"]}}}{format_x_n2["ticksuffix"]}<br>{var_y_n2}: %{{y:{format_y_n2["tickformat"]}}}{format_y_n2["ticksuffix"]}<extra></extra>',
                        legendgroup=instituicao,
                        showlegend=False
                    ))

                    # Ponto do período subsequente (círculo cheio com seta)
                    fig_scatter_n2.add_trace(go.Scatter(
                        x=[x2],
                        y=[y2],
                        mode='markers',
                        name=instituicao,
                        marker=dict(
                            size=marker_size_p2,
                            color=cor,
                            opacity=1.0,
                            line=dict(width=1, color='white'),
                            symbol='circle'
                        ),
                        hovertemplate=f'<b>{instituicao}</b> ({periodo_subseq})<br>{var_x_n2}: %{{x:{format_x_n2["tickformat"]}}}{format_x_n2["ticksuffix"]}<br>{var_y_n2}: %{{y:{format_y_n2["tickformat"]}}}{format_y_n2["ticksuffix"]}<extra></extra>',
                        legendgroup=instituicao,
                        showlegend=True
                    ))

                    # Adiciona seta (annotation) para indicar direção
                    fig_scatter_n2.add_annotation(
                        x=x2,
                        y=y2,
                        ax=x1,
                        ay=y1,
                        xref='x',
                        yref='y',
                        axref='x',
                        ayref='y',
                        showarrow=True,
                        arrowhead=2,
                        arrowsize=1.5,
                        arrowwidth=2,
                        arrowcolor=cor,
                        opacity=0.7
                    )

                # Título do gráfico n=2
                if bancos_selecionados_n2:
                    titulo_scatter_n2 = f'{var_y_n2} vs {var_x_n2} - {periodo_inicial} → {periodo_subseq} ({len(bancos_comuns)} bancos)'
                else:
                    titulo_scatter_n2 = f'{var_y_n2} vs {var_x_n2} - {periodo_inicial} → {periodo_subseq} (top {top_n_scatter_n2} por {var_top_n_n2})'

                fig_scatter_n2.update_layout(
                    title=titulo_scatter_n2,
                    xaxis_title=var_x_n2,
                    yaxis_title=var_y_n2,
                    height=650,
                    plot_bgcolor='#f8f9fa',
                    paper_bgcolor='white',
                    showlegend=True,
                    legend=dict(orientation="v", yanchor="top", y=1, xanchor="left", x=1.02),
                    xaxis=dict(tickformat=format_x_n2['tickformat'], ticksuffix=format_x_n2['ticksuffix']),
                    yaxis=dict(tickformat=format_y_n2['tickformat'], ticksuffix=format_y_n2['ticksuffix']),
                    font=dict(family='IBM Plex Sans')
                )

                st.plotly_chart(fig_scatter_n2, width='stretch')

                # Legenda explicativa
                st.caption("○ Círculo vazio = período inicial | ● Círculo cheio = período subsequente | → Seta indica direção da movimentação")

    else:
        st.info("carregando dados automaticamente do github...")
        st.markdown("por favor, aguarde alguns segundos e recarregue a página")

elif menu == "Deltas (Antes e Depois)":
    if 'dados_periodos' in st.session_state and st.session_state['dados_periodos']:
        df = get_dados_concatenados()  # OTIMIZAÇÃO: usar cache

        colunas_numericas = [col for col in df.columns if col not in ['Instituição', 'Período'] and df[col].dtype in ['float64', 'int64']]
        periodos_disponiveis = ordenar_periodos(df['Período'].dropna().unique())
        periodos_dropdown = ordenar_periodos(df['Período'].dropna().unique(), reverso=True)

        # Lista de todos os bancos disponíveis com ordenação por alias
        bancos_todos = df['Instituição'].dropna().unique().tolist()
        dict_aliases = st.session_state.get('dict_aliases', {})
        todos_bancos = ordenar_bancos_com_alias(bancos_todos, dict_aliases)

        # ===== LINHA 1: Seleção de variáveis =====
        st.markdown("**variáveis para análise de deltas**")
        variaveis_disponiveis = [
            'Ativo Total',
            'Captações',
            'Patrimônio Líquido',
            'Carteira de Crédito',
            'Crédito/Ativo (%)',
            'Índice de Basileia',
            'Crédito/PL (%)',
            'Crédito/Captações (%)',
            'Lucro Líquido Acumulado YTD',
            'ROE Ac. YTD an. (%)',
            # Variáveis de Capital (Relatório 5)
            'RWA Total',
            'Capital Principal',
            'Índice de Capital Principal',
            'Índice de Capital Nível I',
            'Razão de Alavancagem',
        ]
        variaveis_selecionadas_delta = st.multiselect(
            "selecionar variáveis",
            variaveis_disponiveis,
            default=['Carteira de Crédito'],
            key="variaveis_deltas"
        )

        # ===== LINHA 2: Seleção de períodos e tipo de variação =====
        col_p1, col_p2, col_tipo_var = st.columns([2, 2, 1])
        with col_p1:
            indice_inicial_delta = 1 if len(periodos_dropdown) > 1 else 0
            periodo_inicial_delta = st.selectbox(
                "período inicial",
                periodos_dropdown,
                index=indice_inicial_delta,
                key="periodo_inicial_delta",
                format_func=periodo_para_exibicao
            )
        with col_p2:
            periodo_subsequente_delta = st.selectbox(
                "período subsequente",
                periodos_dropdown,
                index=0,
                key="periodo_subsequente_delta",
                format_func=periodo_para_exibicao
            )
        with col_tipo_var:
            tipo_variacao = st.radio(
                "ordenar por",
                ["Δ absoluto", "Δ %"],
                index=1,
                key="tipo_variacao_delta",
                horizontal=True
            )

        # Validação de períodos
        idx_ini = periodos_disponiveis.index(periodo_inicial_delta)
        idx_sub = periodos_disponiveis.index(periodo_subsequente_delta)
        periodo_valido = idx_sub > idx_ini

        if not periodo_valido:
            st.warning("o período subsequente deve ser posterior ao período inicial")

        # ===== LINHA 3: Modo de seleção de instituições =====
        col_modo, col_config = st.columns([1, 3])

        with col_modo:
            modo_selecao = st.radio(
                "modo de seleção",
                ["Top N", "Peer", "Personalizado"],
                index=0,
                key="modo_selecao_deltas"
            )

        bancos_selecionados_delta = []

        with col_config:
            if modo_selecao == "Top N":
                col_slider, col_var = st.columns(2)
                with col_slider:
                    top_n_delta = st.slider("quantidade de bancos", 5, 50, 15, key="top_n_delta")
                with col_var:
                    var_ordenacao = st.selectbox(
                        "ordenar por",
                        colunas_numericas,
                        index=colunas_numericas.index('Carteira de Crédito') if 'Carteira de Crédito' in colunas_numericas else 0,
                        key="var_ordenacao_delta"
                    )
                # Obtém top N bancos do período mais recente
                df_recente = df[df['Período'] == periodo_subsequente_delta].copy()
                df_recente_valid = df_recente.dropna(subset=[var_ordenacao])
                bancos_top_n = df_recente_valid.nlargest(top_n_delta, var_ordenacao)['Instituição'].tolist()
                bancos_selecionados_delta = bancos_top_n

            elif modo_selecao == "Peer":
                peers_disponiveis = []
                if 'colunas_classificacao' in st.session_state and 'df_aliases' in st.session_state:
                    peers_disponiveis = st.session_state['colunas_classificacao']

                if peers_disponiveis:
                    peer_selecionado_delta = st.selectbox(
                        "selecionar peer group",
                        peers_disponiveis,
                        key="peer_deltas"
                    )
                    # Obtém bancos do peer
                    df_aliases = st.session_state['df_aliases']
                    coluna_peer = df_aliases[peer_selecionado_delta]
                    mask_peer = coluna_peer.fillna(0).astype(str).str.strip().isin(["1", "1.0"])
                    bancos_do_peer = df_aliases.loc[mask_peer, 'Alias Banco'].tolist()
                    bancos_selecionados_delta = [b for b in bancos_do_peer if b in todos_bancos]
                else:
                    st.info("nenhum peer group disponível")

            else:  # Personalizado
                col_peer_custom, col_add_remove = st.columns(2)

                with col_peer_custom:
                    peers_disponiveis = []
                    if 'colunas_classificacao' in st.session_state and 'df_aliases' in st.session_state:
                        peers_disponiveis = st.session_state['colunas_classificacao']

                    opcoes_peer_custom = ['Nenhum'] + peers_disponiveis
                    peer_base = st.selectbox(
                        "peer base (opcional)",
                        opcoes_peer_custom,
                        index=0,
                        key="peer_base_deltas"
                    )

                bancos_base = []
                if peer_base != 'Nenhum' and 'df_aliases' in st.session_state:
                    df_aliases = st.session_state['df_aliases']
                    coluna_peer = df_aliases[peer_base]
                    mask_peer = coluna_peer.fillna(0).astype(str).str.strip().isin(["1", "1.0"])
                    bancos_base = df_aliases.loc[mask_peer, 'Alias Banco'].tolist()
                    bancos_base = [b for b in bancos_base if b in todos_bancos]

                with col_add_remove:
                    bancos_custom = st.multiselect(
                        "adicionar/remover bancos",
                        todos_bancos,
                        default=bancos_base,
                        key="bancos_custom_deltas"
                    )
                bancos_selecionados_delta = bancos_custom

        # ===== GRÁFICOS DE DELTAS =====
        if periodo_valido and variaveis_selecionadas_delta and bancos_selecionados_delta:
            # Filtra dados para os dois períodos
            df_inicial = df[df['Período'] == periodo_inicial_delta].copy()
            df_subsequente = df[df['Período'] == periodo_subsequente_delta].copy()

            # ===== CONTROLES DE ESCALA DO EIXO Y =====
            st.markdown("---")
            col_escala1, col_escala2, col_escala3 = st.columns([1, 1, 2])

            with col_escala1:
                # Inicializa session state para escala se não existir
                if 'delta_escala_modo' not in st.session_state:
                    st.session_state['delta_escala_modo'] = 'Auto (zoom)'

                modo_escala = st.radio(
                    "escala do eixo Y",
                    ["Auto (zoom)", "Zero baseline", "Manual"],
                    index=["Auto (zoom)", "Zero baseline", "Manual"].index(st.session_state['delta_escala_modo']),
                    key="delta_escala_modo_radio",
                    horizontal=True
                )
                st.session_state['delta_escala_modo'] = modo_escala

            with col_escala2:
                # Inicializa session state para margem
                if 'delta_escala_margem' not in st.session_state:
                    st.session_state['delta_escala_margem'] = 10

                if modo_escala == "Auto (zoom)":
                    margem_pct = st.slider(
                        "margem (%)",
                        0, 50, st.session_state['delta_escala_margem'],
                        key="delta_margem_slider",
                        help="Margem adicional acima/abaixo dos valores"
                    )
                    st.session_state['delta_escala_margem'] = margem_pct

            with col_escala3:
                if modo_escala == "Manual":
                    col_min, col_max = st.columns(2)
                    with col_min:
                        if 'delta_y_min' not in st.session_state:
                            st.session_state['delta_y_min'] = 0.0
                        y_min_manual = st.number_input(
                            "Y mínimo",
                            value=st.session_state['delta_y_min'],
                            key="delta_y_min_input"
                        )
                        st.session_state['delta_y_min'] = y_min_manual
                    with col_max:
                        if 'delta_y_max' not in st.session_state:
                            st.session_state['delta_y_max'] = 100.0
                        y_max_manual = st.number_input(
                            "Y máximo",
                            value=st.session_state['delta_y_max'],
                            key="delta_y_max_input"
                        )
                        st.session_state['delta_y_max'] = y_max_manual

            st.markdown("---")

            for variavel in variaveis_selecionadas_delta:
                if variavel not in df.columns:
                    st.warning(f"variável '{variavel}' não encontrada nos dados")
                    continue

                format_info = get_axis_format(variavel)

                # Prepara dados para o gráfico
                dados_grafico = []
                for instituicao in bancos_selecionados_delta:
                    valor_ini = df_inicial[df_inicial['Instituição'] == instituicao][variavel].values
                    valor_sub = df_subsequente[df_subsequente['Instituição'] == instituicao][variavel].values

                    if len(valor_ini) > 0 and len(valor_sub) > 0:
                        v_ini = valor_ini[0]
                        v_sub = valor_sub[0]

                        # Tratamento de edge cases
                        if pd.isna(v_ini) or pd.isna(v_sub):
                            continue  # Pula NAs

                        # Calcula delta absoluto
                        delta_absoluto = v_sub - v_ini

                        # Formata delta texto conforme tipo de variável
                        if variavel in VARS_PERCENTUAL:
                            delta_texto = f"{delta_absoluto * 100:+.2f}pp"
                        elif variavel in VARS_MOEDAS:
                            delta_texto = f"R$ {delta_absoluto/1e6:+,.0f}MM".replace(",", ".")
                        else:
                            delta_texto = f"{delta_absoluto:+.2f}"

                        # Variação percentual com tratamento de edge cases
                        if v_ini == 0:
                            # Divisão por zero
                            if delta_absoluto > 0:
                                variacao_pct = float('inf')
                                variacao_texto = "+∞"
                            elif delta_absoluto < 0:
                                variacao_pct = float('-inf')
                                variacao_texto = "-∞"
                            else:
                                variacao_pct = 0
                                variacao_texto = "0.0%"
                        elif v_ini < 0 and v_sub > 0:
                            # Cruzou de negativo para positivo
                            variacao_pct = ((v_sub - v_ini) / abs(v_ini)) * 100
                            variacao_texto = f"{variacao_pct:+.1f}% (inversão)"
                        elif v_ini > 0 and v_sub < 0:
                            # Cruzou de positivo para negativo
                            variacao_pct = ((v_sub - v_ini) / abs(v_ini)) * 100
                            variacao_texto = f"{variacao_pct:+.1f}% (inversão)"
                        else:
                            variacao_pct = ((v_sub - v_ini) / abs(v_ini)) * 100
                            variacao_texto = f"{variacao_pct:+.1f}%"

                        dados_grafico.append({
                            'instituicao': instituicao,
                            'valor_ini': v_ini,
                            'valor_sub': v_sub,
                            'delta': delta_absoluto,
                            'delta_texto': delta_texto,
                            'variacao_pct': variacao_pct if not (variacao_pct == float('inf') or variacao_pct == float('-inf')) else (1e10 if variacao_pct > 0 else -1e10),
                            'variacao_texto': variacao_texto
                        })

                if not dados_grafico:
                    st.info(f"sem dados disponíveis para '{variavel}' nos períodos selecionados")
                    continue

                # Ordena pela variação (maior positiva → maior negativa)
                if tipo_variacao == "Δ %":
                    dados_grafico = sorted(dados_grafico, key=lambda x: x['variacao_pct'], reverse=True)
                else:
                    dados_grafico = sorted(dados_grafico, key=lambda x: x['delta'], reverse=True)

                # Cria o gráfico estilo lollipop
                fig_delta = go.Figure()

                # Coleta todos os valores Y para calcular escala
                todos_y = []
                for dado in dados_grafico:
                    todos_y.append(dado['valor_ini'] * format_info['multiplicador'])
                    todos_y.append(dado['valor_sub'] * format_info['multiplicador'])

                for i, dado in enumerate(dados_grafico):
                    inst = dado['instituicao']
                    y_ini = dado['valor_ini'] * format_info['multiplicador']
                    y_sub = dado['valor_sub'] * format_info['multiplicador']
                    delta_positivo = dado['delta'] > 0

                    # Cor da bolinha do período subsequente
                    cor_sub = '#2E7D32' if delta_positivo else '#C62828'  # verde ou vermelho

                    # Linha conectando os dois pontos
                    fig_delta.add_trace(go.Scatter(
                        x=[inst, inst],
                        y=[y_ini, y_sub],
                        mode='lines',
                        line=dict(color='#9E9E9E', width=2),
                        showlegend=False,
                        hoverinfo='skip'
                    ))

                    # Bolinha do período inicial (preta/cinza escuro)
                    fig_delta.add_trace(go.Scatter(
                        x=[inst],
                        y=[y_ini],
                        mode='markers',
                        marker=dict(size=12, color='#424242', line=dict(width=1, color='white')),
                        name=periodo_inicial_delta if i == 0 else None,
                        showlegend=(i == 0),
                        legendgroup='inicial',
                        hovertemplate=f'<b>{inst}</b><br>{periodo_inicial_delta}: %{{y:{format_info["tickformat"]}}}{format_info["ticksuffix"]}<extra></extra>'
                    ))

                    # Bolinha do período subsequente (verde/vermelho)
                    fig_delta.add_trace(go.Scatter(
                        x=[inst],
                        y=[y_sub],
                        mode='markers',
                        marker=dict(size=12, color=cor_sub, line=dict(width=1, color='white')),
                        name=periodo_subsequente_delta if i == 0 else None,
                        showlegend=(i == 0),
                        legendgroup='subsequente',
                        customdata=[[dado['delta_texto'], dado['variacao_texto']]],
                        hovertemplate=f'<b>{inst}</b><br>{periodo_subsequente_delta}: %{{y:{format_info["tickformat"]}}}{format_info["ticksuffix"]}<br>Δ: %{{customdata[0]}}<br>Variação: %{{customdata[1]}}<extra></extra>'
                    ))

                # Título do gráfico
                titulo_delta = f"{variavel}: {periodo_inicial_delta} → {periodo_subsequente_delta}"

                # Calcula limites do eixo Y baseado no modo de escala
                yaxis_config = dict(
                    showgrid=True,
                    gridcolor='#e0e0e0',
                    tickformat=format_info['tickformat'],
                    ticksuffix=format_info['ticksuffix'],
                    title=variavel
                )

                if todos_y:
                    y_min_dados = min(todos_y)
                    y_max_dados = max(todos_y)
                    y_range = y_max_dados - y_min_dados if y_max_dados != y_min_dados else abs(y_max_dados) * 0.1 or 1

                    if modo_escala == "Zero baseline":
                        # Sempre incluir zero
                        yaxis_config['range'] = [min(0, y_min_dados - y_range * 0.05), max(0, y_max_dados + y_range * 0.05)]
                    elif modo_escala == "Auto (zoom)":
                        # Zoom nos dados com margem configurável
                        margem = y_range * (margem_pct / 100)
                        yaxis_config['range'] = [y_min_dados - margem, y_max_dados + margem]
                    elif modo_escala == "Manual":
                        # Usar valores manuais
                        yaxis_config['range'] = [y_min_manual, y_max_manual]

                fig_delta.update_layout(
                    title=dict(
                        text=titulo_delta,
                        font=dict(size=16, family='IBM Plex Sans')
                    ),
                    height=max(400, len(dados_grafico) * 25 + 150),
                    plot_bgcolor='#f8f9fa',
                    paper_bgcolor='white',
                    showlegend=True,
                    legend=dict(
                        orientation="h",
                        yanchor="bottom",
                        y=1.02,
                        xanchor="left",
                        x=0
                    ),
                    xaxis=dict(
                        showgrid=False,
                        tickangle=45 if len(dados_grafico) > 10 else 0,
                        tickfont=dict(size=10)
                    ),
                    yaxis=yaxis_config,
                    font=dict(family='IBM Plex Sans'),
                    margin=dict(l=60, r=20, t=80, b=100)
                )

                st.markdown(f"### {variavel}")
                st.plotly_chart(fig_delta, width='stretch', config={'displayModeBar': False})

                # Tabela resumo
                with st.expander("ver dados"):
                    df_resumo = pd.DataFrame(dados_grafico)
                    df_resumo = df_resumo.rename(columns={
                        'instituicao': 'Instituição',
                        'valor_ini': periodo_inicial_delta,
                        'valor_sub': periodo_subsequente_delta,
                        'delta_texto': 'Delta',
                        'variacao_texto': 'Variação %'
                    })
                    df_resumo = df_resumo[['Instituição', periodo_inicial_delta, periodo_subsequente_delta, 'Delta', 'Variação %']]

                    # Formata valores para exibição
                    df_display = df_resumo.copy()
                    df_display[periodo_inicial_delta] = df_display[periodo_inicial_delta].apply(lambda x: formatar_valor(x, variavel))
                    df_display[periodo_subsequente_delta] = df_display[periodo_subsequente_delta].apply(lambda x: formatar_valor(x, variavel))

                    st.dataframe(df_display, width='stretch', hide_index=True)

                    # Botão de exportar Excel
                    buffer_excel = BytesIO()
                    with pd.ExcelWriter(buffer_excel, engine='xlsxwriter') as writer:
                        df_resumo.to_excel(writer, index=False, sheet_name='deltas')
                    buffer_excel.seek(0)

                    nome_variavel = variavel.replace(' ', '_').replace('/', '_')
                    st.download_button(
                        label="Exportar Excel",
                        data=buffer_excel,
                        file_name=f"Deltas_{nome_variavel}_{periodo_inicial_delta.replace('/', '-')}_{periodo_subsequente_delta.replace('/', '-')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key=f"exportar_excel_delta_{nome_variavel}"
                    )

        elif not periodo_valido:
            pass  # Já exibiu warning acima
        elif not variaveis_selecionadas_delta:
            st.info("selecione ao menos uma variável para análise")
        else:
            st.info("selecione instituições para comparar")

    else:
        st.info("carregando dados automaticamente do github...")
        st.markdown("por favor, aguarde alguns segundos e recarregue a página")

elif menu == "DRE":
    st.markdown("### Demonstração de Resultado (DRE)")
    st.caption("Tabela DRE a partir de Mar/25 com YTD irregular e YoY.")

    @st.cache_data(ttl=3600, show_spinner=False)
    def load_dre_data():
        manager = get_cache_manager()
        resultado = manager.carregar("dre")
        if resultado.sucesso and resultado.dados is not None:
            return resultado.dados, None
        return None, resultado.mensagem

    def normalize_sources(value):
        if value is None:
            return []
        if isinstance(value, list):
            return [v for v in value if isinstance(v, str) and v.strip()]
        if isinstance(value, str):
            parts = [p.strip() for p in value.replace("|", ";").split(";")]
            return [p for p in parts if p]
        return []

    def load_dre_mapping():
        return [
            {
                "label": "Resultado de Intermediação Financeira Bruto",
                "sources": [
                    "Rendas de Aplicações Interfinanceiras de Liquidez (a)",
                    "Rendas de Títulos e Valores Mobiliários (b)",
                    "Rendas de Operações de Crédito (c)",
                    "Rendas de Arrendamento Financeiro (d)",
                    "Rendas de Outras Operações com Características de Concessão de Crédito (e)",
                ],
                "concept": "Resultado de intermediação financeira bruto (a+b+c+d+e).",
                "original_label": "Resultado de Intermediação Financeira Bruto",
            },
            {
                "label": "Rec. Aplicações Interfinanceiras Liquidez",
                "sources": ["Rendas de Aplicações Interfinanceiras de Liquidez (a)"],
                "concept": "Receitas de aplicações interfinanceiras de liquidez.",
                "original_label": "Rendas de Aplicações Interfinanceiras de Liquidez (a)",
                "is_child": True,
            },
            {
                "label": "Rec. TVMs",
                "sources": ["Rendas de Títulos e Valores Mobiliários (b)"],
                "concept": "Receitas de títulos e valores mobiliários.",
                "original_label": "Rendas de Títulos e Valores Mobiliários (b)",
                "is_child": True,
            },
            {
                "label": "Rec. Crédito",
                "sources": ["Rendas de Operações de Crédito (c)"],
                "concept": "Receitas de operações de crédito.",
                "original_label": "Rendas de Operações de Crédito (c)",
                "is_child": True,
            },
            {
                "label": "Rec. Arrendamento Financeiro",
                "sources": ["Rendas de Arrendamento Financeiro (d)"],
                "concept": "Receitas de arrendamento financeiro.",
                "original_label": "Rendas de Arrendamento Financeiro (d)",
                "is_child": True,
            },
            {
                "label": "Rec. Outras Operações c/ Características de Crédito",
                "sources": ["Rendas de Outras Operações com Características de Concessão de Crédito (e)"],
                "concept": "Receitas de outras operações com características de crédito.",
                "original_label": "Rendas de Outras Operações com Características de Concessão de Crédito (e)",
                "is_child": True,
            },
            {
                "label": "Desp. PDD",
                "sources": ["Resultado com Perda Esperada (f)"],
                "concept": "Despesa com perdas esperadas (PDD).",
                "original_label": "Resultado com Perda Esperada (f)",
            },
            {
                "label": "Desp. Captação",
                "sources": ["Despesas de Captações (g)"],
                "concept": "Despesas de captação.",
                "original_label": "Despesas de Captações (g)",
            },
            {
                "label": "Desp. Dívida Elegível a Capital",
                "sources": ["Despesas de Instrumentos de Dívida Elegíveis a Capital (h)"],
                "concept": "Despesas com dívida elegível a capital.",
                "original_label": "Despesas de Instrumentos de Dívida Elegíveis a Capital (h)",
            },
            {
                "label": "Res. Derivativos",
                "sources": ["Resultado com Derivativos (i)"],
                "concept": "Resultado com derivativos.",
                "original_label": "Resultado com Derivativos (i)",
            },
            {
                "label": "Outros Res. Intermediação Financeira",
                "sources": ["Outros Resultados de Intermediação Financeira (j)"],
                "concept": "Outros resultados de intermediação financeira.",
                "original_label": "Outros Resultados de Intermediação Financeira (j)",
            },
            {
                "label": "Resultado Int. Financeira Líquido",
                "sources": [
                    "Rendas de Aplicações Interfinanceiras de Liquidez (a)",
                    "Rendas de Títulos e Valores Mobiliários (b)",
                    "Rendas de Operações de Crédito (c)",
                    "Rendas de Arrendamento Financeiro (d)",
                    "Rendas de Outras Operações com Características de Concessão de Crédito (e)",
                    "Resultado com Perda Esperada (f)",
                    "Despesas de Captações (g)",
                    "Despesas de Instrumentos de Dívida Elegíveis a Capital (h)",
                    "Resultado com Derivativos (i)",
                    "Outros Resultados de Intermediação Financeira (j)",
                ],
                "concept": "Resultado de intermediação financeira líquido.",
                "original_label": "Resultado de Intermediação Financeira (k) = (a) + (b) + (c) + (d) + (e) + (f) + (g) + (h) + (i) + (j)",
            },
            {
                "label": "Resultado Transações Pgto",
                "sources": ["Resultado com Transações de Pagamento (l)"],
                "concept": "Resultado com transações de pagamento.",
                "original_label": "Resultado com Transações de Pagamento (l)",
            },
            {
                "label": "Renda Tarifas Bancárias",
                "sources": ["Rendas de Tarifas Bancárias (m)"],
                "concept": "Receitas de tarifas bancárias.",
                "original_label": "Rendas de Tarifas Bancárias (m)",
            },
            {
                "label": "Outras Prestações de Serviços",
                "sources": ["Outras Rendas de Prestação de Serviços (n)"],
                "concept": "Outras receitas de prestação de serviços.",
                "original_label": "Outras Rendas de Prestação de Serviços (n)",
            },
            {
                "label": "Desp. Pessoal",
                "sources": ["Despesas de Pessoal (o)"],
                "concept": "Despesas com pessoal.",
                "original_label": "Despesas de Pessoal (o)",
            },
            {
                "label": "Desp. Adm",
                "sources": ["Despesas Administrativas (p)"],
                "concept": "Despesas administrativas.",
                "original_label": "Despesas Administrativas (p)",
            },
            {
                "label": "Desp. PDD Outras Operações",
                "sources": ["Resultado com Perdas Esperadas de Outras Operações (q)"],
                "concept": "Perdas esperadas de outras operações.",
                "original_label": "Resultado com Perdas Esperadas de Outras Operações (q)",
            },
            {
                "label": "Desp. JSCP Cooperativas",
                "sources": ["Despesas de Juros Sobre Capital Próprio de Cooperativas (r)"],
                "concept": "Juros sobre capital próprio (cooperativas).",
                "original_label": "Despesas de Juros Sobre Capital Próprio de Cooperativas (r)",
            },
            {
                "label": "Desp. Tributárias",
                "sources": ["Despesas Tributárias (s)"],
                "concept": "Despesas tributárias.",
                "original_label": "Despesas Tributárias (s)",
            },
            {
                "label": "Res. Participação Controladas",
                "sources": ["Resultado de Participações (t)"],
                "concept": "Resultado de participações em controladas/coligadas.",
                "original_label": "Resultado de Participações (t)",
            },
            {
                "label": "Outras Receitas",
                "sources": ["Outras Receitas (u)"],
                "concept": "Outras receitas.",
                "original_label": "Outras Receitas (u)",
            },
            {
                "label": "Outras Despesas",
                "sources": ["Outras Despesas (v)"],
                "concept": "Outras despesas.",
                "original_label": "Outras Despesas (v)",
            },
            {
                "label": "IR/CSLL",
                "sources": ["Imposto de Renda e Contribuição Social (y)"],
                "concept": "Imposto de renda e contribuição social.",
                "original_label": "Imposto de Renda e Contribuição Social (y)",
            },
            {
                "label": "Res. Participação Lucro",
                "sources": ["Participações no Lucro (z)"],
                "concept": "Participações no lucro.",
                "original_label": "Participações no Lucro (z)",
            },
            {
                "label": "Lucro Líquido Período Acumulado",
                "sources": ["Lucro Líquido (aa) = (x) + (y) + (z)"],
                "concept": "Lucro líquido acumulado no período.",
                "original_label": "Lucro Líquido (aa) = (x) + (y) + (z)",
            },
        ]

    def find_column(df, source_name: str):
        if source_name in df.columns:
            return source_name
        target = source_name.strip().lower()
        for col in df.columns:
            if str(col).strip().lower() == target:
                return col
        for col in df.columns:
            if target in str(col).strip().lower():
                return col
        return None

    def coerce_numeric(series: pd.Series) -> pd.Series:
        if series is None:
            return series
        if series.dtype == object:
            cleaned = (
                series.astype(str)
                .str.replace(".", "", regex=False)
                .str.replace(",", ".", regex=False)
            )
            return pd.to_numeric(cleaned, errors="coerce")
        return pd.to_numeric(series, errors="coerce")

    def detectar_colunas_basicas(df: pd.DataFrame):
        col_periodo = None
        for candidato in ["Período", "Periodo", "PERIODO", "PERÍODO"]:
            if candidato in df.columns:
                col_periodo = candidato
                break
        if col_periodo is None:
            for col in df.columns:
                if "period" in str(col).lower():
                    col_periodo = col
                    break
        col_inst = None
        for candidato in ["Instituição", "Instituicao", "INSTITUICAO", "INSTITUIÇÃO"]:
            if candidato in df.columns:
                col_inst = candidato
                break
        if col_inst is None:
            for col in df.columns:
                if "institu" in str(col).lower():
                    col_inst = col
                    break
        return col_periodo, col_inst

    def parse_periodo(periodo_val):
        if periodo_val is None:
            return None, None
        texto = str(periodo_val).strip()
        if "/" in texto:
            partes = texto.split("/")
            if len(partes) >= 2 and partes[0].isdigit() and partes[1].isdigit():
                parte1 = int(partes[0])
                ano = int(partes[1])
                if 1 <= parte1 <= 4:
                    mes = {1: 3, 2: 6, 3: 9, 4: 12}.get(parte1)
                else:
                    mes = parte1
                return ano, mes
        if texto.isdigit():
            if len(texto) == 6:
                ano = int(texto[:4])
                mes = int(texto[4:])
                return ano, mes
            if len(texto) == 8:
                ano = int(texto[:4])
                mes = int(texto[4:6])
                return ano, mes
        return None, None

    def compute_ytd_irregular(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df[["ano", "mes"]] = df["Periodo"].apply(
            lambda x: pd.Series(parse_periodo(x))
        )
        df["ytd"] = pd.NA
        for (instituicao, label, ano), grupo in df.groupby(["Instituicao", "Label", "ano"]):
            valores_mes = {row["mes"]: row["valor"] for _, row in grupo.iterrows()}
            for idx, row in grupo.iterrows():
                mes = row["mes"]
                valor = row["valor"]
                ytd_val = pd.NA
                if pd.isna(valor):
                    ytd_val = pd.NA
                elif mes in (3, 6):
                    ytd_val = valor
                elif mes in (9, 12):
                    valor_jun = valores_mes.get(6)
                    if valor_jun is None or pd.isna(valor_jun):
                        ytd_val = pd.NA
                    else:
                        ytd_val = valor + valor_jun
                else:
                    ytd_val = valor
                df.at[idx, "ytd"] = ytd_val
        return df

    def compute_yoy(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["yoy"] = pd.NA
        for (instituicao, label, mes), grupo in df.groupby(["Instituicao", "Label", "mes"]):
            valores_ano = {
                row["ano"]: row["ytd"]
                for _, row in grupo.iterrows()
                if row["ano"] is not None
            }
            for idx, row in grupo.iterrows():
                ano = row["ano"]
                if ano is None or pd.isna(row["ytd"]):
                    continue
                anterior = valores_ano.get(ano - 1)
                if anterior is None or pd.isna(anterior) or anterior == 0:
                    continue
                df.at[idx, "yoy"] = (row["ytd"] / anterior) - 1
        return df

    def compute_line_values(df_base: pd.DataFrame, entry: dict) -> pd.DataFrame:
        fontes = normalize_sources(entry.get("sources", []))
        colunas = []
        for fonte in fontes:
            col = find_column(df_base, fonte)
            if col:
                colunas.append(col)
        if not colunas:
            return pd.DataFrame()
        series_list = [coerce_numeric(df_base[col]) for col in colunas]
        valores = pd.concat(series_list, axis=1).sum(axis=1, min_count=1)
        df_out = df_base[["Instituicao", "Periodo"]].copy()
        df_out["Label"] = entry["label"]
        df_out["valor"] = valores
        return df_out

    def formatar_valor_br(valor, decimais=0):
        if pd.isna(valor) or valor is None:
            return "—"
        try:
            if decimais == 0:
                return f"{valor:,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")
            return f"{valor:,.{decimais}f}".replace(",", "X").replace(".", ",").replace("X", ".")
        except Exception:
            return "—"

    def formatar_percentual(valor, decimais=1):
        if pd.isna(valor) or valor is None:
            return "—"
        try:
            return f"{valor * 100:.{decimais}f}%"
        except Exception:
            return "—"

    def render_table_like_carteira_4966(df_linhas: pd.DataFrame, entradas: list, periodos: list, formato_por_label: dict, tooltip_por_label: dict):
        html_tabela = """
        <style>
        .carteira-table {
            width: 88%;
            margin: 10px auto 0 auto;
            border-collapse: collapse;
            font-size: 14px;
        }
        .carteira-table th, .carteira-table td {
            border: 1px solid #ddd;
            padding: 6px 10px;
            text-align: right;
            vertical-align: top;
        }
        .carteira-table th {
            background-color: #f5f5f5;
            font-weight: 600;
        }
        .carteira-table td:first-child {
            text-align: left;
            font-weight: 500;
        }
        .carteira-table thead tr:first-child th {
            background-color: #4a4a4a;
            color: white;
            text-align: center;
        }
        .carteira-table thead tr:nth-child(2) th {
            background-color: #6a6a6a;
            color: white;
        }
        .dre-info {
            font-size: 12px;
            color: #666;
            margin-left: 6px;
            cursor: help;
        }
        .dre-subitem {
            font-size: 12px;
        }
        .dre-subitem td:first-child {
            padding-left: 18px;
        }
        .dre-negative {
            color: #7a1e2b;
            font-weight: 600;
        }
        </style>
        <table class="carteira-table">
        <thead>
        <tr>
        <th rowspan="2">Item</th>
        """

        for periodo in periodos:
            html_tabela += f'<th colspan="2">{periodo}</th>'
        html_tabela += "</tr><tr>"
        for _ in periodos:
            html_tabela += "<th>YTD</th><th>Δ% YoY</th>"
        html_tabela += "</tr></thead><tbody>"

        for entry in entradas:
            label = entry["label"]
            label_exib = entry.get("label_exib", label)
            tooltip = tooltip_por_label.get(label, "")
            info_html = f'<span class="dre-info" title="{tooltip}">ⓘ</span>' if tooltip else ""
            row_class = "dre-subitem" if entry.get("is_child") else ""
            html_tabela += f"<tr class=\"{row_class}\"><td>{label_exib} {info_html}</td>"
            linha = df_linhas[df_linhas["Label"] == label]
            for periodo in periodos:
                cell = linha[linha["PeriodoExib"] == periodo]
                if not cell.empty:
                    ytd_val = cell["ytd"].iloc[0]
                    yoy_val = cell["yoy"].iloc[0]
                else:
                    ytd_val = pd.NA
                    yoy_val = pd.NA
                formato = formato_por_label.get(label, "num")
                if formato == "pct":
                    ytd_fmt = formatar_percentual(ytd_val, decimais=2)
                    ytd_neg = False
                else:
                    ytd_fmt = formatar_valor_br(ytd_val)
                    ytd_neg = pd.notna(ytd_val) and ytd_val < 0
                yoy_fmt = formatar_percentual(yoy_val, decimais=1)
                yoy_neg = pd.notna(yoy_val) and yoy_val < 0
                ytd_span = f"<span class=\"dre-negative\">{ytd_fmt}</span>" if ytd_neg else ytd_fmt
                yoy_span = f"<span class=\"dre-negative\">{yoy_fmt}</span>" if yoy_neg else yoy_fmt
                html_tabela += f"<td>{ytd_span}</td><td>{yoy_span}</td>"
            html_tabela += "</tr>"

        html_tabela += "</tbody></table>"
        st.markdown(html_tabela, unsafe_allow_html=True)

    df_dre, dre_msg = load_dre_data()
    if df_dre is None or df_dre.empty:
        detalhe = f" ({dre_msg})" if dre_msg else ""
        st.warning(f"Dados DRE não disponíveis no cache. Atualize a base no menu 'Atualizar Base'.{detalhe}")
        with st.expander("Limites de recursos do Streamlit Community Cloud"):
            st.markdown(
                """
                Os limites atuais (fev/2024) são aproximadamente:
                - CPU: 0,078 cores mínimo, 2 cores máximo
                - Memória: 690MB mínimo, 2,7GB máximo
                - Armazenamento: sem mínimo, 50GB máximo

                Sintomas comuns de limite excedido:
                - App lento (throttling)
                - Mensagem "🤯 This app has gone over its resource limits."
                - Mensagem "😦 Oh no."

                Apps educacionais, open-source ou de impacto social podem solicitar aumento de recursos.
                """
            )
    else:
        col_periodo, col_inst = detectar_colunas_basicas(df_dre)
        if col_periodo is None:
            st.warning("Coluna de período não encontrada nos dados DRE.")
        else:
            mapping_entries = load_dre_mapping()

            if not mapping_entries:
                st.warning("Mapeamento DRE não encontrado ou vazio.")
            else:
                colunas_necessarias = {col_periodo}
                if col_inst:
                    colunas_necessarias.add(col_inst)
                for entry in mapping_entries:
                    for fonte in entry.get("sources", []):
                        col_encontrada = find_column(df_dre, fonte)
                        if col_encontrada:
                            colunas_necessarias.add(col_encontrada)
                colunas_necessarias = [c for c in df_dre.columns if c in colunas_necessarias]
                if colunas_necessarias:
                    df_dre = df_dre[colunas_necessarias].copy()

                df_base = df_dre.copy()
                if col_inst is None:
                    df_base["Instituicao"] = df_base.get("CodInst", "Instituição")
                else:
                    df_base = df_base.rename(columns={col_inst: "Instituicao"})
                df_base = df_base.rename(columns={col_periodo: "Periodo"})

                df_base[["ano", "mes"]] = df_base["Periodo"].apply(
                    lambda x: pd.Series(parse_periodo(x))
                )
                df_new = df_base[
                    (df_base["ano"].fillna(0) > 2025)
                    | ((df_base["ano"] == 2025) & (df_base["mes"].fillna(0) >= 3))
                ].copy()

                instit_col = "Instituicao"
                instituicoes = sorted(df_base[instit_col].dropna().unique().tolist())
                anos_disponiveis = sorted(df_base["ano"].dropna().unique().astype(int).tolist())

                if not instituicoes or not anos_disponiveis:
                    st.warning("Dados DRE sem instituições ou períodos válidos.")
                    st.stop()

                col_inst, col_ano = st.columns([1, 1])
                with col_inst:
                    instituicao_selecionada = st.selectbox(
                        "Instituição",
                        instituicoes,
                        key="dre_instituicao"
                    )
                with col_ano:
                    ano_selecionado = st.selectbox(
                        "Ano",
                        anos_disponiveis[::-1],
                        index=0,
                        key="dre_ano"
                    )

                df_values = []
                for entry in mapping_entries:
                    df_entry = compute_line_values(df_new, entry)
                    if not df_entry.empty:
                        df_values.append(df_entry)

                if not df_values:
                    st.warning("Nenhuma linha DRE foi encontrada com o mapeamento atual.")
                else:
                    df_valores = pd.concat(df_values, ignore_index=True)
                    df_ytd = compute_ytd_irregular(df_valores)
                    df_ytd = compute_yoy(df_ytd)

                    df_ytd["PeriodoExib"] = df_ytd["Periodo"].apply(periodo_para_exibicao)

                    formato_por_label = {entry["label"]: entry.get("format", "num") for entry in mapping_entries}
                    tooltip_por_label = {}
                    entradas_com_label = []
                    for entry in mapping_entries:
                        fonte_original = entry.get("original_label")
                        fontes = [fonte_original] if fonte_original else entry.get("sources", [])
                        fontes_fmt = ", ".join([f for f in fontes if f])
                        tooltip_parts = []
                        if entry.get("concept"):
                            tooltip_parts.append(entry["concept"])
                        if fontes_fmt:
                            tooltip_parts.append(f"Fontes: {fontes_fmt}")
                        if entry.get("ytd_note"):
                            tooltip_parts.append("Nota YTD: set/dez = jun + período.")
                        tooltip_por_label[entry["label"]] = " | ".join(tooltip_parts)

                        label_exib = entry["label"]
                        entrada_copy = entry.copy()
                        entrada_copy["label_exib"] = label_exib
                        entradas_com_label.append(entrada_copy)

                    df_filtrado = df_ytd[
                        (df_ytd["Instituicao"] == instituicao_selecionada)
                        & (df_ytd["ano"] == int(ano_selecionado))
                    ].copy()

                    periodos_ordem = ["Mar", "Jun", "Set", "Dez"]
                    periodos_disponiveis = []
                    for mes in [3, 6, 9, 12]:
                        periodo_texto = periodo_para_exibicao(f"{int(mes/3)}/{ano_selecionado}")
                        periodos_disponiveis.append(periodo_texto)

                    render_table_like_carteira_4966(
                        df_filtrado,
                        entradas_com_label,
                        periodos_disponiveis,
                        formato_por_label,
                        tooltip_por_label
                    )

                    st.markdown("#### Exportar DRE (formato simples)")
                    df_export = []
                    for entry in entradas_com_label:
                        label = entry["label"]
                        linha = {"Item": label}
                        for periodo in periodos_disponiveis:
                            cell = df_filtrado[
                                (df_filtrado["Label"] == label)
                                & (df_filtrado["PeriodoExib"] == periodo)
                            ]
                            if not cell.empty:
                                ytd_val = cell["ytd"].iloc[0]
                                yoy_val = cell["yoy"].iloc[0]
                            else:
                                ytd_val = pd.NA
                                yoy_val = pd.NA
                            linha[f"{periodo} YTD"] = ytd_val
                            linha[f"{periodo} Δ% YoY"] = yoy_val
                        df_export.append(linha)

                    df_export = pd.DataFrame(df_export)
                    buffer_excel = BytesIO()
                    with pd.ExcelWriter(buffer_excel, engine="xlsxwriter") as writer:
                        df_export.to_excel(writer, index=False, sheet_name="DRE")
                        worksheet = writer.sheets["DRE"]
                        for idx, col in enumerate(df_export.columns):
                            max_len = max(
                                len(str(col)),
                                df_export[col].astype(str).map(len).max()
                            )
                            worksheet.set_column(idx, idx, min(max_len + 2, 40))
                    buffer_excel.seek(0)

                    st.download_button(
                        label="Baixar Excel (DRE)",
                        data=buffer_excel,
                        file_name=f"DRE_{instituicao_selecionada.replace(' ', '_')}_{ano_selecionado}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="dre_download_excel"
                    )

elif menu == "Carteira 4.966":
    # =========================================================================
    # ABA CARTEIRA 4.966 - Classificação de Instrumentos Financeiros (Res. 4.966)
    # =========================================================================

    @st.cache_data(ttl=3600, show_spinner=False)
    def load_carteira_4966_data():
        """Carrega dados da Carteira 4.966 (Relatório 16) com cache."""
        from utils.ifdata_cache import get_manager
        manager = get_manager()
        resultado = manager.carregar("carteira_instrumentos")
        if resultado.sucesso and resultado.dados is not None:
            return resultado.dados
        return None

    def periodo_para_exibicao_mes(periodo_trimestre: str) -> str:
        """Converte período trimestral (1/2025) para formato mês abreviado (mar/25)."""
        if not periodo_trimestre or '/' not in periodo_trimestre:
            return periodo_trimestre
        try:
            trimestre, ano = periodo_trimestre.split('/')
            meses_map = {'1': 'mar', '2': 'jun', '3': 'set', '4': 'dez'}
            mes = meses_map.get(trimestre, trimestre)
            ano_curto = ano[-2:] if len(ano) == 4 else ano
            return f"{mes}/{ano_curto}"
        except:
            return periodo_trimestre

    def formatar_valor_br(valor, decimais=0):
        """Formata valor numérico no padrão brasileiro (pontos como separador de milhar)."""
        if pd.isna(valor) or valor is None:
            return "-"
        try:
            if decimais == 0:
                return f"{valor:,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")
            else:
                return f"{valor:,.{decimais}f}".replace(",", "X").replace(".", ",").replace("X", ".")
        except:
            return str(valor)

    def formatar_percentual(valor, decimais=1):
        """Formata percentual com casas decimais."""
        if pd.isna(valor) or valor is None:
            return "-"
        try:
            return f"{valor * 100:.{decimais}f}%"
        except:
            return "-"

    # Mapeamento das linhas da tabela para colunas da API
    LINHAS_CARTEIRA_4966 = [
        ("C1", "C1"),
        ("C2", "C2"),
        ("C3", "C3"),
        ("C4", "C4"),
        ("C5", "C5"),
        ("Carteira Total", "Total Geral"),
        ("Carteira Não Informada", "Carteira não Informada ou não se Aplica"),
        ("Carteira no Exterior", "Total Exterior"),
        ("Total não Individualizado", "Total não Individualizado"),
    ]

    df_carteira = load_carteira_4966_data()

    if df_carteira is not None and not df_carteira.empty:
        # Verificar colunas disponíveis
        colunas_disponiveis = df_carteira.columns.tolist()

        # Obter lista de instituições e períodos
        if 'Instituição' in df_carteira.columns:
            instituicoes = sorted(df_carteira['Instituição'].dropna().unique().tolist())
        else:
            instituicoes = []

        col_periodo = 'Período' if 'Período' in df_carteira.columns else 'Periodo'
        if col_periodo in df_carteira.columns:
            periodos_disponiveis = ordenar_periodos(df_carteira[col_periodo].dropna().unique(), reverso=True)
        else:
            periodos_disponiveis = []

        if instituicoes and periodos_disponiveis:
            st.markdown("### Carteira de Crédito por Instrumentos Financeiros (Res. 4.966)")
            st.caption("Classificação conforme estágios de risco de crédito - C1 a C5")

            # Seletores
            col_inst, col_periodos = st.columns([1, 2])

            with col_inst:
                instituicao_selecionada = st.selectbox(
                    "Instituição",
                    instituicoes,
                    key="carteira_4966_instituicao"
                )

            # Filtrar períodos disponíveis para a instituição selecionada
            df_inst = df_carteira[df_carteira['Instituição'] == instituicao_selecionada]
            periodos_inst = ordenar_periodos(df_inst[col_periodo].dropna().unique(), reverso=True)

            with col_periodos:
                periodos_selecionados = st.multiselect(
                    "Períodos (selecione 2 ou mais para comparação)",
                    periodos_inst,
                    default=periodos_inst[:2] if len(periodos_inst) >= 2 else periodos_inst,
                    key="carteira_4966_periodos",
                    help="Selecione múltiplos períodos para comparar. O delta será calculado em relação ao período anterior na lista."
                )

            if periodos_selecionados and len(periodos_selecionados) >= 1:
                # Ordenar períodos do mais antigo para o mais recente (para cálculo de deltas)
                periodos_ordenados = ordenar_periodos(periodos_selecionados, reverso=False)

                # Construir dados da tabela
                dados_tabela = []

                for nome_linha, coluna_api in LINHAS_CARTEIRA_4966:
                    linha_dados = {"Tipo de Carteira": nome_linha}

                    # Verificar se a coluna existe nos dados
                    coluna_encontrada = None
                    for col in colunas_disponiveis:
                        if col.lower().strip() == coluna_api.lower().strip():
                            coluna_encontrada = col
                            break

                    if coluna_encontrada is None:
                        # Tentar busca parcial
                        for col in colunas_disponiveis:
                            if coluna_api.lower() in col.lower():
                                coluna_encontrada = col
                                break

                    for i, periodo in enumerate(periodos_ordenados):
                        df_periodo = df_inst[df_inst[col_periodo] == periodo]

                        if not df_periodo.empty and coluna_encontrada and coluna_encontrada in df_periodo.columns:
                            valor = df_periodo[coluna_encontrada].iloc[0]
                        else:
                            valor = None

                        # Obter Total Geral para calcular percentual
                        total_geral = None
                        for col in colunas_disponiveis:
                            if 'total geral' in col.lower():
                                if not df_periodo.empty and col in df_periodo.columns:
                                    total_geral = df_periodo[col].iloc[0]
                                break

                        periodo_exib = periodo_para_exibicao_mes(periodo)
                        linha_dados[f"{periodo_exib}"] = valor

                        # Calcular percentual
                        if valor is not None and total_geral is not None and total_geral != 0:
                            pct = valor / total_geral
                        else:
                            pct = None
                        linha_dados[f"{periodo_exib} %"] = pct

                    dados_tabela.append(linha_dados)

                df_resultado = pd.DataFrame(dados_tabela)

                # Criar tabela estilizada com HTML
                st.markdown("---")

                # Construir HTML da tabela
                html_tabela = """
                <style>
                .carteira-table {
                    width: 100%;
                    border-collapse: collapse;
                    font-size: 14px;
                    margin-top: 10px;
                }
                .carteira-table th, .carteira-table td {
                    border: 1px solid #ddd;
                    padding: 8px 12px;
                    text-align: right;
                }
                .carteira-table th {
                    background-color: #f5f5f5;
                    font-weight: 600;
                }
                .carteira-table td:first-child {
                    text-align: left;
                    font-weight: 500;
                }
                .carteira-table tr.total-row {
                    background-color: #e8f4e8;
                    font-weight: bold;
                }
                .carteira-table tr.total-row td {
                    font-weight: bold;
                }
                .carteira-table thead tr:first-child th {
                    background-color: #4a4a4a;
                    color: white;
                    text-align: center;
                }
                .carteira-table thead tr:nth-child(2) th {
                    background-color: #6a6a6a;
                    color: white;
                }
                .delta-pos { color: #28a745; }
                .delta-neg { color: #dc3545; }
                </style>
                <table class="carteira-table">
                <thead>
                <tr>
                <th rowspan="2">Tipo de Carteira</th>
                """

                # Cabeçalhos agrupados por período
                for periodo in periodos_ordenados:
                    periodo_exib = periodo_para_exibicao_mes(periodo)
                    html_tabela += f'<th colspan="2">{periodo_exib}</th>'

                html_tabela += "</tr><tr>"

                for _ in periodos_ordenados:
                    html_tabela += '<th>Valor</th><th>% Carteira Total</th>'

                html_tabela += "</tr></thead><tbody>"

                # Linhas de dados
                for idx, row in df_resultado.iterrows():
                    tipo = row["Tipo de Carteira"]
                    is_total = tipo == "Carteira Total"
                    row_class = 'class="total-row"' if is_total else ''

                    html_tabela += f"<tr {row_class}><td>{tipo}</td>"

                    valor_anterior = None
                    for i, periodo in enumerate(periodos_ordenados):
                        periodo_exib = periodo_para_exibicao_mes(periodo)
                        valor = row.get(f"{periodo_exib}")
                        pct = row.get(f"{periodo_exib} %")

                        valor_fmt = formatar_valor_br(valor)
                        pct_fmt = formatar_percentual(pct) if pct is not None else "-"

                        # Se for linhas especiais (Não Informada, Exterior, Não Individualizado), não mostrar percentual
                        if tipo in ["Carteira Não Informada", "Carteira no Exterior", "Total não Individualizado"]:
                            pct_fmt = "-"

                        # Adicionar delta visual se houver período anterior
                        delta_html = ""
                        if i > 0 and valor_anterior is not None and valor is not None:
                            delta = valor - valor_anterior
                            if delta > 0:
                                delta_html = f' <span class="delta-pos">▲</span>'
                            elif delta < 0:
                                delta_html = f' <span class="delta-neg">▼</span>'

                        html_tabela += f"<td>{valor_fmt}{delta_html}</td><td>{pct_fmt}</td>"
                        valor_anterior = valor

                    html_tabela += "</tr>"

                html_tabela += "</tbody></table>"

                st.markdown(html_tabela, unsafe_allow_html=True)

                # Tabela de auditoria (dataframe simples)
                with st.expander("Dados para auditoria"):
                    st.dataframe(df_resultado, width='stretch')

                # Exportação Excel
                st.markdown("---")

                def criar_excel_carteira_4966(df, instituicao, periodos):
                    """Cria arquivo Excel com colunas flattened."""
                    import io
                    buffer = io.BytesIO()

                    # Preparar DataFrame para exportação com colunas flattened
                    df_export = df.copy()

                    # Renomear colunas para formato explícito
                    colunas_rename = {"Tipo de Carteira": "Tipo de Carteira"}
                    for periodo in periodos:
                        periodo_exib = periodo_para_exibicao_mes(periodo)
                        colunas_rename[f"{periodo_exib}"] = f"{periodo_exib} Valor"
                        colunas_rename[f"{periodo_exib} %"] = f"{periodo_exib} %"

                    df_export = df_export.rename(columns=colunas_rename)

                    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                        df_export.to_excel(writer, index=False, sheet_name='Carteira 4.966')

                        # Ajustar largura das colunas
                        worksheet = writer.sheets['Carteira 4.966']
                        for i, col in enumerate(df_export.columns):
                            max_length = max(
                                df_export[col].astype(str).map(len).max() if len(df_export) > 0 else 0,
                                len(col)
                            )
                            worksheet.column_dimensions[chr(65 + i)].width = min(max_length + 2, 30)

                    buffer.seek(0)
                    return buffer.getvalue()

                col_btn1, col_btn2 = st.columns(2)

                with col_btn1:
                    excel_data = criar_excel_carteira_4966(df_resultado, instituicao_selecionada, periodos_ordenados)
                    periodos_str = "_".join([periodo_para_exibicao_mes(p).replace("/", "-") for p in periodos_ordenados])
                    st.download_button(
                        label="Baixar Excel (Tabela Atual)",
                        data=excel_data,
                        file_name=f"Carteira_4966_{instituicao_selecionada.replace(' ', '_')[:30]}_{periodos_str}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="download_excel_carteira_4966"
                    )

                with col_btn2:
                    # Exportar dados brutos da instituição
                    df_inst_export = df_inst.copy()
                    buffer_raw = io.BytesIO()
                    with pd.ExcelWriter(buffer_raw, engine='openpyxl') as writer:
                        df_inst_export.to_excel(writer, index=False, sheet_name='Dados Brutos')
                    buffer_raw.seek(0)

                    st.download_button(
                        label="Baixar Excel (Dados Brutos)",
                        data=buffer_raw.getvalue(),
                        file_name=f"Carteira_4966_{instituicao_selecionada.replace(' ', '_')[:30]}_dados_brutos.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="download_excel_carteira_4966_raw"
                    )

            else:
                st.info("Selecione ao menos um período para visualizar os dados.")

        else:
            st.warning("Dados de Carteira 4.966 não contêm instituições ou períodos válidos.")
            st.caption(f"Colunas disponíveis: {colunas_disponiveis[:10]}...")

    else:
        st.warning("Dados da Carteira 4.966 (Relatório 16) não disponíveis.")
        st.info("Os dados precisam ser extraídos via 'Atualização Base' no painel de administração.")

        # Mostrar informações sobre o cache
        from utils.ifdata_cache import get_manager
        manager = get_manager()
        info = manager.info("carteira_instrumentos")
        if info and not info.get("erro"):
            st.caption(f"Status do cache: {info}")

elif menu == "Taxas de Juros por Produto":
    # =========================================================================
    # ABA TAXAS DE JUROS POR PRODUTO - Extração direta da API do BCB
    # Dropdowns cascateados: Segmento → Produto → Bancos
    # =========================================================================
    import requests

    # URL da API do BCB
    API_TAXAS_URL = "https://olinda.bcb.gov.br/olinda/servico/taxaJuros/versao/v2/odata/TaxasJurosDiariaPorInicioPeriodo"

    def formatar_modalidade(nome: str) -> str:
        """Formata nome da modalidade para exibição."""
        if not nome:
            return nome
        preposicoes = {'de', 'da', 'do', 'das', 'dos', 'e', 'em', 'para', 'com', 'sem', 'por'}
        palavras = nome.lower().split()
        resultado = []
        for i, palavra in enumerate(palavras):
            if i == 0 or palavra not in preposicoes:
                resultado.append(palavra.capitalize())
            else:
                resultado.append(palavra)
        return ' '.join(resultado)

    @st.cache_data(ttl=3600, show_spinner="Buscando dados do BCB (12 meses)...")
    def buscar_taxas_bcb_historico() -> pd.DataFrame:
        """Busca dados de taxas de juros dos últimos 12 meses da API do BCB.
        Retorna apenas a última data de cada mês para otimizar performance."""
        from datetime import date

        # Data de 13 meses atrás (para garantir 12 meses completos)
        data_inicio = (date.today() - timedelta(days=400)).strftime('%Y-%m-%d')

        # Tentar diferentes formatos de URL
        urls_tentar = [
            f"{API_TAXAS_URL}?$format=json&$top=500000",
            f"{API_TAXAS_URL}(dataInicioPeriodo=@dataInicioPeriodo)?$format=json&$top=500000&@dataInicioPeriodo='{data_inicio}'",
        ]

        response = None
        for url in urls_tentar:
            try:
                response = requests.get(url, timeout=120)
                if response.status_code == 200:
                    break
            except:
                continue

        if response is None or response.status_code != 200:
            return pd.DataFrame()

        try:
            dados = response.json()

            if 'value' not in dados or not dados['value']:
                return pd.DataFrame()

            df = pd.DataFrame(dados['value'])

            # Renomear colunas
            df = df.rename(columns={
                'InicioPeriodo': 'Início Período',
                'FimPeriodo': 'Fim Período',
                'Segmento': 'Segmento',
                'Modalidade': 'Produto',
                'Posicao': 'Posição',
                'InstituicaoFinanceira': 'Instituição Financeira',
                'TaxaJurosAoMes': 'Taxa Mensal (%)',
                'TaxaJurosAoAno': 'Taxa Anual (%)'
            })

            # Converter datas
            df['Fim Período'] = pd.to_datetime(df['Fim Período'])

            # Filtrar últimos 12 meses
            data_limite = pd.Timestamp.today() - pd.DateOffset(months=12)
            df = df[df['Fim Período'] >= data_limite]

            # Criar coluna Ano-Mês para agrupar
            df['AnoMes'] = df['Fim Período'].dt.to_period('M')

            # Para cada combinação (Segmento, Produto, Instituição, AnoMes), pegar a última data
            idx = df.groupby(['Segmento', 'Produto', 'Instituição Financeira', 'AnoMes'])['Fim Período'].idxmax()
            df_mensal = df.loc[idx].copy()

            # Criar coluna de data formatada para o gráfico
            df_mensal['Mês'] = df_mensal['Fim Período'].dt.strftime('%b/%y')

            return df_mensal

        except Exception as e:
            return pd.DataFrame()

    st.markdown("### Taxas de Juros por Produto")
    st.caption("Histórico dos últimos 12 meses - API do Banco Central do Brasil")

    with st.expander("ℹ️ Sobre os dados", expanded=False):
        st.markdown("""
        **Fonte:** API do Banco Central do Brasil - Taxas de Juros

        **Histórico:** Última data disponível de cada mês (últimos 12 meses).

        **Posição:** Ranking da instituição para aquele produto/período.
        Posição 1 = menor taxa (melhor para o cliente).
        """)

    st.markdown("---")

    # =============================================================
    # BUSCAR DADOS HISTÓRICOS (12 MESES)
    # =============================================================
    df_taxas = buscar_taxas_bcb_historico()

    if df_taxas.empty:
        st.warning("Nenhum dado encontrado. A API do BCB pode estar indisponível.")
        st.info("Tente novamente em alguns minutos.")
    else:
        # Data mais recente disponível
        data_mais_recente = df_taxas['Fim Período'].max()
        meses_disponiveis = df_taxas['AnoMes'].nunique()

        st.success(f"✅ {len(df_taxas):,} registros | {meses_disponiveis} meses | Até: {data_mais_recente.strftime('%d/%m/%Y')}")

        st.markdown("---")

        # Usar dados da data mais recente para seleção de segmento/produto
        df_recente = df_taxas[df_taxas['Fim Período'] == data_mais_recente]

        # =============================================================
        # DROPDOWN 1: SEGMENTO (PF / PJ)
        # =============================================================
        segmentos = sorted(df_recente['Segmento'].dropna().unique().tolist())

        segmento_sel = st.selectbox(
            "1️⃣ Selecione o Segmento",
            options=segmentos,
            key="tj_segmento",
            help="PF = Pessoa Física, PJ = Pessoa Jurídica"
        )

        if segmento_sel:
            df_seg_recente = df_recente[df_recente['Segmento'] == segmento_sel]

            # =============================================================
            # DROPDOWN 2: PRODUTO (filtrado pelo segmento)
            # =============================================================
            produtos = sorted(df_seg_recente['Produto'].dropna().unique().tolist())

            produto_sel = st.selectbox(
                "2️⃣ Selecione o Produto",
                options=produtos,
                format_func=formatar_modalidade,
                key="tj_produto"
            )

            if produto_sel:
                # Filtrar dados históricos para o segmento e produto
                df_prod_hist = df_taxas[
                    (df_taxas['Segmento'] == segmento_sel) &
                    (df_taxas['Produto'] == produto_sel)
                ]

                st.markdown(f"#### {formatar_modalidade(produto_sel)}")

                # =============================================================
                # MULTISELECT 3: BANCOS (baseado na data mais recente)
                # =============================================================
                df_prod_recente = df_prod_hist[df_prod_hist['Fim Período'] == data_mais_recente]

                # Ordenar por posição (menor = melhor taxa)
                if 'Posição' in df_prod_recente.columns and not df_prod_recente.empty:
                    df_prod_ord = df_prod_recente.sort_values('Posição', ascending=True)
                else:
                    df_prod_ord = df_prod_recente.sort_values('Instituição Financeira')

                bancos_disponiveis = df_prod_ord['Instituição Financeira'].unique().tolist()

                # Top 10 como default
                top_10 = bancos_disponiveis[:10]

                # Ordenar lista com aliases primeiro
                dict_aliases = st.session_state.get('dict_aliases', {})
                bancos_ordenados = ordenar_bancos_com_alias(bancos_disponiveis, dict_aliases)

                bancos_sel = st.multiselect(
                    "3️⃣ Selecione os Bancos (máx 15)",
                    options=bancos_ordenados,
                    default=[b for b in top_10 if b in bancos_ordenados][:10],
                    max_selections=15,
                    key="tj_bancos",
                    help="Top 10 por menor taxa pré-selecionados"
                )

                if not bancos_sel:
                    st.warning("Selecione ao menos um banco.")
                else:
                    # =============================================================
                    # TIPO DE TAXA
                    # =============================================================
                    tipo_taxa = st.radio(
                        "Tipo de taxa",
                        ["Taxa Mensal (%)", "Taxa Anual (%)"],
                        horizontal=True,
                        key="tj_tipo_taxa"
                    )

                    # Filtrar dados históricos para os bancos selecionados
                    df_chart = df_prod_hist[df_prod_hist['Instituição Financeira'].isin(bancos_sel)].copy()
                    df_chart = df_chart.sort_values('Fim Período')

                    # =============================================================
                    # GRÁFICO DE LINHAS - HISTÓRICO 12 MESES
                    # =============================================================
                    fig = px.line(
                        df_chart,
                        x='Fim Período',
                        y=tipo_taxa,
                        color='Instituição Financeira',
                        title=f'{formatar_modalidade(produto_sel)} - {tipo_taxa} (Últimos 12 meses)',
                        labels={
                            'Fim Período': 'Data',
                            tipo_taxa: tipo_taxa,
                            'Instituição Financeira': 'Instituição'
                        },
                        template='plotly_white',
                        markers=True
                    )

                    fig.update_layout(
                        height=500,
                        legend=dict(
                            orientation="h",
                            yanchor="bottom",
                            y=-0.35,
                            xanchor="center",
                            x=0.5
                        ),
                        xaxis_title="",
                        yaxis_title=tipo_taxa,
                        hovermode='x unified',
                        margin=dict(b=100)
                    )

                    fig.update_xaxes(tickformat="%b/%y")
                    fig.update_traces(marker=dict(size=6))

                    st.plotly_chart(fig, width='stretch')

                    # =============================================================
                    # TABELA DE DADOS (data mais recente)
                    # =============================================================
                    with st.expander("📋 Ver ranking atual"):
                        df_rank = df_prod_recente[df_prod_recente['Instituição Financeira'].isin(bancos_sel)]
                        cols_mostrar = ['Posição', 'Instituição Financeira', 'Taxa Mensal (%)', 'Taxa Anual (%)']
                        cols_disp = [c for c in cols_mostrar if c in df_rank.columns]
                        df_display = df_rank[cols_disp].sort_values('Posição' if 'Posição' in cols_disp else tipo_taxa)
                        st.caption(f"Ranking em {data_mais_recente.strftime('%d/%m/%Y')}:")
                        st.dataframe(df_display, width='stretch', hide_index=True)

                    # =============================================================
                    # EXPORTAÇÃO
                    # =============================================================
                    with st.expander("📥 Exportar dados"):
                        csv_data = df_chart.to_csv(index=False, sep=';', decimal=',')
                        st.download_button(
                            label="⬇️ Baixar CSV (histórico)",
                            data=csv_data,
                            file_name=f"taxas_hist_{segmento_sel}_{produto_sel[:20]}.csv",
                            mime="text/csv",
                            key="tj_download_csv"
                        )

elif menu == "Crie sua métrica!":
    if 'dados_periodos' in st.session_state and st.session_state['dados_periodos']:
        df = get_dados_concatenados()  # OTIMIZAÇÃO: usar cache

        colunas_numericas = [col for col in df.columns if col not in ['Instituição', 'Período'] and df[col].dtype in ['float64', 'int64']]
        periodos_disponiveis = ordenar_periodos(df['Período'].dropna().unique())
        periodos_dropdown = ordenar_periodos(df['Período'].dropna().unique(), reverso=True)

        # Lista de todos os bancos disponíveis com ordenação por alias
        bancos_todos = df['Instituição'].dropna().unique().tolist()
        dict_aliases = st.session_state.get('dict_aliases', {})
        todos_bancos = ordenar_bancos_com_alias(bancos_todos, dict_aliases)

        st.markdown("### construtor de métricas derivadas")
        st.caption("monte uma métrica personalizada combinando variáveis com operações matemáticas")

        # ===== CONSTRUTOR DE FÓRMULA PASSO-A-PASSO =====
        # Inicializa session state para a fórmula
        if 'brincar_formula_steps' not in st.session_state:
            st.session_state['brincar_formula_steps'] = []
        if 'brincar_nome_metrica' not in st.session_state:
            st.session_state['brincar_nome_metrica'] = "Métrica Personalizada"

        col_nome, col_formato = st.columns([2, 1])
        with col_nome:
            nome_metrica = st.text_input(
                "nome da métrica",
                value=st.session_state['brincar_nome_metrica'],
                key="nome_metrica_input"
            )
            st.session_state['brincar_nome_metrica'] = nome_metrica

        with col_formato:
            formato_resultado = st.selectbox(
                "formato do resultado",
                ["Auto", "Valor bruto (R$)", "Percentual (%)", "Múltiplo (x)", "Número"],
                key="formato_resultado_brincar"
            )

        st.markdown("---")
        st.markdown("**construir fórmula**")

        # Interface de construção
        col_var, col_op, col_add = st.columns([2, 1, 1])

        with col_var:
            var_nova = st.selectbox(
                "variável",
                colunas_numericas,
                key="var_nova_brincar"
            )

        with col_op:
            operacao = st.selectbox(
                "operação seguinte",
                ["(fim)", "+", "-", "×", "÷"],
                key="operacao_brincar"
            )

        with col_add:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("adicionar", key="btn_add_step", width='stretch'):
                st.session_state['brincar_formula_steps'].append({
                    'variavel': var_nova,
                    'operacao': operacao if operacao != "(fim)" else None
                })
                st.rerun()

        # Exibir fórmula atual
        if st.session_state['brincar_formula_steps']:
            formula_texto = ""
            for i, step in enumerate(st.session_state['brincar_formula_steps']):
                formula_texto += f"**{step['variavel']}**"
                if step['operacao']:
                    formula_texto += f" {step['operacao']} "

            col_formula, col_limpar = st.columns([3, 1])
            with col_formula:
                st.markdown(f"Fórmula: {formula_texto}")
            with col_limpar:
                if st.button("limpar fórmula", key="btn_limpar_formula"):
                    st.session_state['brincar_formula_steps'] = []
                    st.rerun()
        else:
            st.info("adicione variáveis para construir sua fórmula")

        # Função para calcular a métrica derivada
        def calcular_metrica_derivada(df_input, steps):
            if not steps:
                return None

            # Inicializa com a primeira variável
            resultado = df_input[steps[0]['variavel']].copy()

            for i in range(len(steps) - 1):
                op = steps[i]['operacao']
                proxima_var = steps[i + 1]['variavel']

                if op == '+':
                    resultado = resultado + df_input[proxima_var]
                elif op == '-':
                    resultado = resultado - df_input[proxima_var]
                elif op == '×':
                    resultado = resultado * df_input[proxima_var]
                elif op == '÷':
                    # Evita divisão por zero
                    resultado = resultado / df_input[proxima_var].replace(0, np.nan)

            return resultado

        # Função para detectar se é uma razão/divisão
        def formula_eh_divisao(steps):
            for step in steps:
                if step['operacao'] == '÷':
                    return True
            return False

        # ===== SELEÇÃO DE BANCOS =====
        st.markdown("---")
        st.markdown("**seleção de instituições**")

        col_modo, col_config = st.columns([1, 3])

        with col_modo:
            modo_selecao_brincar = st.radio(
                "modo de seleção",
                ["Top N", "Peer", "Personalizado"],
                index=0,
                key="modo_selecao_brincar"
            )

        bancos_selecionados_brincar = []

        with col_config:
            if modo_selecao_brincar == "Top N":
                col_slider, col_var_ord = st.columns(2)
                with col_slider:
                    top_n_brincar = st.slider("quantidade de bancos", 5, 40, 15, key="top_n_brincar")
                with col_var_ord:
                    var_ordenacao_brincar = st.selectbox(
                        "ordenar por",
                        colunas_numericas,
                        index=colunas_numericas.index('Carteira de Crédito') if 'Carteira de Crédito' in colunas_numericas else 0,
                        key="var_ordenacao_brincar"
                    )
                # Obtém top N bancos do período mais recente
                periodo_mais_recente = periodos_disponiveis[-1]
                df_recente = df[df['Período'] == periodo_mais_recente].copy()
                df_recente_valid = df_recente.dropna(subset=[var_ordenacao_brincar])
                bancos_top_n = df_recente_valid.nlargest(top_n_brincar, var_ordenacao_brincar)['Instituição'].tolist()
                bancos_selecionados_brincar = bancos_top_n

            elif modo_selecao_brincar == "Peer":
                peers_disponiveis = []
                if 'colunas_classificacao' in st.session_state and 'df_aliases' in st.session_state:
                    peers_disponiveis = st.session_state['colunas_classificacao']

                if peers_disponiveis:
                    peer_selecionado_brincar = st.selectbox(
                        "selecionar peer group",
                        peers_disponiveis,
                        key="peer_brincar"
                    )
                    # Obtém bancos do peer
                    df_aliases = st.session_state['df_aliases']
                    coluna_peer = df_aliases[peer_selecionado_brincar]
                    mask_peer = coluna_peer.fillna(0).astype(str).str.strip().isin(["1", "1.0"])
                    bancos_do_peer = df_aliases.loc[mask_peer, 'Alias Banco'].tolist()
                    bancos_selecionados_brincar = [b for b in bancos_do_peer if b in todos_bancos]
                else:
                    st.info("nenhum peer group disponível")

            else:  # Personalizado
                col_peer_custom, col_add_remove = st.columns(2)

                with col_peer_custom:
                    peers_disponiveis = []
                    if 'colunas_classificacao' in st.session_state and 'df_aliases' in st.session_state:
                        peers_disponiveis = st.session_state['colunas_classificacao']

                    opcoes_peer_custom = ['Nenhum'] + peers_disponiveis
                    peer_base_brincar = st.selectbox(
                        "peer base (opcional)",
                        opcoes_peer_custom,
                        index=0,
                        key="peer_base_brincar"
                    )

                bancos_base = []
                if peer_base_brincar != 'Nenhum' and 'df_aliases' in st.session_state:
                    df_aliases = st.session_state['df_aliases']
                    coluna_peer = df_aliases[peer_base_brincar]
                    mask_peer = coluna_peer.fillna(0).astype(str).str.strip().isin(["1", "1.0"])
                    bancos_base = df_aliases.loc[mask_peer, 'Alias Banco'].tolist()
                    bancos_base = [b for b in bancos_base if b in todos_bancos]

                with col_add_remove:
                    bancos_custom_brincar = st.multiselect(
                        "adicionar/remover bancos",
                        todos_bancos,
                        default=bancos_base,
                        max_selections=40,
                        key="bancos_custom_brincar"
                    )
                bancos_selecionados_brincar = bancos_custom_brincar

        # ===== TIPO DE VISUALIZAÇÃO =====
        st.markdown("---")
        st.markdown("**visualização**")

        tipo_visualizacao = st.radio(
            "tipo de gráfico",
            ["Scatter Plot", "Deltas", "Ranking (barras)"],
            horizontal=True,
            key="tipo_viz_brincar"
        )

        # ===== CALCULAR E VISUALIZAR =====
        if st.session_state['brincar_formula_steps'] and bancos_selecionados_brincar:
            steps = st.session_state['brincar_formula_steps']

            # Verifica se a fórmula está completa (última operação é None ou não tem operação pendente)
            formula_completa = steps[-1]['operacao'] is None

            if not formula_completa:
                st.warning("adicione mais uma variável ou selecione '(fim)' como operação para completar a fórmula")
            else:
                # ===== SCATTER PLOT =====
                if tipo_visualizacao == "Scatter Plot":
                    st.markdown("---")
                    col_periodo, col_eixo_x, col_eixo_y, col_tamanho = st.columns(4)

                    with col_periodo:
                        periodo_scatter_brincar = st.selectbox(
                            "período",
                            periodos_dropdown,
                            index=0,
                            key="periodo_scatter_brincar",
                            format_func=periodo_para_exibicao
                        )

                    with col_eixo_x:
                        opcoes_eixo = ['Métrica Derivada'] + colunas_numericas
                        eixo_x_brincar = st.selectbox(
                            "eixo X",
                            opcoes_eixo,
                            index=0,
                            key="eixo_x_brincar"
                        )

                    with col_eixo_y:
                        eixo_y_brincar = st.selectbox(
                            "eixo Y",
                            opcoes_eixo,
                            index=min(1, len(opcoes_eixo) - 1),
                            key="eixo_y_brincar"
                        )

                    with col_tamanho:
                        opcoes_tamanho = ['Tamanho Fixo', 'Métrica Derivada'] + colunas_numericas
                        var_tamanho_brincar = st.selectbox(
                            "tamanho",
                            opcoes_tamanho,
                            index=0,
                            key="var_tamanho_brincar"
                        )

                    # Filtrar dados para o período
                    df_periodo = df[df['Período'] == periodo_scatter_brincar].copy()
                    df_scatter_brincar = df_periodo[df_periodo['Instituição'].isin(bancos_selecionados_brincar)].copy()

                    # Calcular métrica derivada
                    df_scatter_brincar['Métrica Derivada'] = calcular_metrica_derivada(df_scatter_brincar, steps)

                    # Remover linhas com NaN na métrica
                    df_scatter_brincar = df_scatter_brincar.dropna(subset=['Métrica Derivada'])

                    if len(df_scatter_brincar) > 0:
                        # Preparar dados para o gráfico
                        def get_format_for_var(var_name):
                            if var_name == 'Métrica Derivada':
                                if formato_resultado == "Percentual (%)":
                                    return {'tickformat': '.2f', 'ticksuffix': '%', 'multiplicador': 100}
                                elif formato_resultado == "Valor bruto (R$)":
                                    return {'tickformat': ',.0f', 'ticksuffix': 'M', 'multiplicador': 1/1e6}
                                elif formato_resultado == "Múltiplo (x)":
                                    return {'tickformat': '.2f', 'ticksuffix': 'x', 'multiplicador': 1}
                                elif formato_resultado == "Auto":
                                    if formula_eh_divisao(steps):
                                        return {'tickformat': '.2f', 'ticksuffix': 'x', 'multiplicador': 1}
                                    else:
                                        return {'tickformat': ',.0f', 'ticksuffix': 'M', 'multiplicador': 1/1e6}
                                else:
                                    return {'tickformat': '.2f', 'ticksuffix': '', 'multiplicador': 1}
                            else:
                                return get_axis_format(var_name)

                        format_x = get_format_for_var(eixo_x_brincar)
                        format_y = get_format_for_var(eixo_y_brincar)

                        df_scatter_brincar['x_display'] = df_scatter_brincar[eixo_x_brincar] * format_x['multiplicador']
                        df_scatter_brincar['y_display'] = df_scatter_brincar[eixo_y_brincar] * format_y['multiplicador']

                        if var_tamanho_brincar == 'Tamanho Fixo':
                            tamanho_constante = 25
                        else:
                            format_size = get_format_for_var(var_tamanho_brincar)
                            df_scatter_brincar['size_display'] = df_scatter_brincar[var_tamanho_brincar].abs() * format_size['multiplicador']

                        fig_scatter_brincar = go.Figure()
                        cores_plotly = px.colors.qualitative.Plotly
                        idx_cor = 0

                        for instituicao in df_scatter_brincar['Instituição'].unique():
                            df_inst = df_scatter_brincar[df_scatter_brincar['Instituição'] == instituicao]
                            cor = obter_cor_banco(instituicao)
                            if not cor:
                                cor = cores_plotly[idx_cor % len(cores_plotly)]
                                idx_cor += 1

                            if var_tamanho_brincar == 'Tamanho Fixo':
                                marker_size = tamanho_constante
                            else:
                                max_size = df_scatter_brincar['size_display'].max()
                                if max_size > 0:
                                    marker_size = df_inst['size_display'] / max_size * 100
                                else:
                                    marker_size = 25

                            eixo_x_label = nome_metrica if eixo_x_brincar == 'Métrica Derivada' else eixo_x_brincar
                            eixo_y_label = nome_metrica if eixo_y_brincar == 'Métrica Derivada' else eixo_y_brincar

                            fig_scatter_brincar.add_trace(go.Scatter(
                                x=df_inst['x_display'],
                                y=df_inst['y_display'],
                                mode='markers',
                                name=instituicao,
                                marker=dict(size=marker_size, color=cor, opacity=1.0, line=dict(width=1, color='white')),
                                hovertemplate=f'<b>{instituicao}</b><br>{eixo_x_label}: %{{x:{format_x["tickformat"]}}}{format_x["ticksuffix"]}<br>{eixo_y_label}: %{{y:{format_y["tickformat"]}}}{format_y["ticksuffix"]}<extra></extra>'
                            ))

                        titulo_scatter = f'{nome_metrica}: {eixo_y_brincar} vs {eixo_x_brincar} - {periodo_scatter_brincar}'

                        fig_scatter_brincar.update_layout(
                            title=titulo_scatter,
                            xaxis_title=eixo_x_label,
                            yaxis_title=eixo_y_label,
                            height=650,
                            plot_bgcolor='#f8f9fa',
                            paper_bgcolor='white',
                            showlegend=True,
                            legend=dict(orientation="v", yanchor="top", y=1, xanchor="left", x=1.02),
                            xaxis=dict(tickformat=format_x['tickformat'], ticksuffix=format_x['ticksuffix']),
                            yaxis=dict(tickformat=format_y['tickformat'], ticksuffix=format_y['ticksuffix']),
                            font=dict(family='IBM Plex Sans')
                        )

                        st.plotly_chart(fig_scatter_brincar, width='stretch')

                        # Tabela e exportação
                        with st.expander("ver dados e exportar"):
                            # Prepara dados para exportação
                            df_export = df_scatter_brincar[['Instituição', eixo_x_brincar, eixo_y_brincar]].copy()
                            df_export['Período'] = periodo_scatter_brincar

                            # Adiciona componentes da fórmula
                            componentes = list(set([s['variavel'] for s in steps]))
                            for comp in componentes:
                                if comp not in df_export.columns:
                                    df_export[comp] = df_scatter_brincar[comp]

                            # Reordena colunas
                            cols_ordem = ['Período', 'Instituição', 'Métrica Derivada'] + [c for c in df_export.columns if c not in ['Período', 'Instituição', 'Métrica Derivada', eixo_x_brincar, eixo_y_brincar]]
                            if eixo_x_brincar != 'Métrica Derivada':
                                cols_ordem.append(eixo_x_brincar)
                            if eixo_y_brincar != 'Métrica Derivada' and eixo_y_brincar not in cols_ordem:
                                cols_ordem.append(eixo_y_brincar)

                            df_export['Métrica Derivada'] = df_scatter_brincar['Métrica Derivada']
                            df_export = df_export[[c for c in cols_ordem if c in df_export.columns]]

                            st.dataframe(df_export, width='stretch', hide_index=True)

                            col_excel, col_csv = st.columns(2)
                            with col_excel:
                                buffer_excel = BytesIO()
                                with pd.ExcelWriter(buffer_excel, engine='xlsxwriter') as writer:
                                    df_export.to_excel(writer, index=False, sheet_name='dados')
                                buffer_excel.seek(0)
                                st.download_button(
                                    label="Exportar Excel",
                                    data=buffer_excel,
                                    file_name=f"Brincar_Scatter_{nome_metrica.replace(' ', '_')}_{periodo_scatter_brincar.replace('/', '-')}.xlsx",
                                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                    key="export_excel_scatter_brincar"
                                )
                            with col_csv:
                                csv_data = df_export.to_csv(index=False)
                                st.download_button(
                                    label="Exportar CSV",
                                    data=csv_data,
                                    file_name=f"Brincar_Scatter_{nome_metrica.replace(' ', '_')}_{periodo_scatter_brincar.replace('/', '-')}.csv",
                                    mime="text/csv",
                                    key="export_csv_scatter_brincar"
                                )
                    else:
                        st.warning("sem dados válidos para exibir no scatter plot")

                # ===== DELTAS =====
                elif tipo_visualizacao == "Deltas":
                    st.markdown("---")
                    col_p1, col_p2, col_tipo_var = st.columns([2, 2, 1])

                    with col_p1:
                        indice_inicial_brincar = 1 if len(periodos_dropdown) > 1 else 0
                        periodo_inicial_brincar = st.selectbox(
                            "período inicial",
                            periodos_dropdown,
                            index=indice_inicial_brincar,
                            key="periodo_inicial_brincar",
                            format_func=periodo_para_exibicao
                        )
                    with col_p2:
                        periodo_subsequente_brincar = st.selectbox(
                            "período subsequente",
                            periodos_dropdown,
                            index=0,
                            key="periodo_subsequente_brincar",
                            format_func=periodo_para_exibicao
                        )
                    with col_tipo_var:
                        tipo_variacao_brincar = st.radio(
                            "ordenar por",
                            ["Δ absoluto", "Δ %"],
                            index=1,
                            key="tipo_variacao_brincar",
                            horizontal=True
                        )

                    # Validação de períodos
                    idx_ini = periodos_disponiveis.index(periodo_inicial_brincar)
                    idx_sub = periodos_disponiveis.index(periodo_subsequente_brincar)
                    periodo_valido = idx_sub > idx_ini

                    if not periodo_valido:
                        st.warning("o período subsequente deve ser posterior ao período inicial")
                    else:
                        # Filtra dados para os dois períodos
                        df_inicial = df[df['Período'] == periodo_inicial_brincar].copy()
                        df_subsequente = df[df['Período'] == periodo_subsequente_brincar].copy()

                        # Calcular métrica derivada para ambos os períodos
                        df_inicial_calc = df_inicial[df_inicial['Instituição'].isin(bancos_selecionados_brincar)].copy()
                        df_subsequente_calc = df_subsequente[df_subsequente['Instituição'].isin(bancos_selecionados_brincar)].copy()

                        df_inicial_calc['Métrica Derivada'] = calcular_metrica_derivada(df_inicial_calc, steps)
                        df_subsequente_calc['Métrica Derivada'] = calcular_metrica_derivada(df_subsequente_calc, steps)

                        # Determinar formato
                        if formato_resultado == "Percentual (%)":
                            format_info = {'tickformat': '.2f', 'ticksuffix': '%', 'multiplicador': 100}
                        elif formato_resultado == "Valor bruto (R$)":
                            format_info = {'tickformat': ',.0f', 'ticksuffix': 'M', 'multiplicador': 1/1e6}
                        elif formato_resultado == "Múltiplo (x)":
                            format_info = {'tickformat': '.2f', 'ticksuffix': 'x', 'multiplicador': 1}
                        elif formato_resultado == "Auto":
                            if formula_eh_divisao(steps):
                                format_info = {'tickformat': '.2f', 'ticksuffix': 'x', 'multiplicador': 1}
                            else:
                                format_info = {'tickformat': ',.0f', 'ticksuffix': 'M', 'multiplicador': 1/1e6}
                        else:
                            format_info = {'tickformat': '.2f', 'ticksuffix': '', 'multiplicador': 1}

                        # Prepara dados para o gráfico
                        dados_grafico_brincar = []
                        for instituicao in bancos_selecionados_brincar:
                            valor_ini = df_inicial_calc[df_inicial_calc['Instituição'] == instituicao]['Métrica Derivada'].values
                            valor_sub = df_subsequente_calc[df_subsequente_calc['Instituição'] == instituicao]['Métrica Derivada'].values

                            if len(valor_ini) > 0 and len(valor_sub) > 0:
                                v_ini = valor_ini[0]
                                v_sub = valor_sub[0]

                                if pd.isna(v_ini) or pd.isna(v_sub):
                                    continue

                                delta_absoluto = v_sub - v_ini

                                # Formata delta texto
                                if formato_resultado == "Percentual (%)" or (formato_resultado == "Auto" and formula_eh_divisao(steps)):
                                    delta_texto = f"{delta_absoluto * format_info['multiplicador']:+.2f}{format_info['ticksuffix']}"
                                elif formato_resultado == "Valor bruto (R$)" or (formato_resultado == "Auto" and not formula_eh_divisao(steps)):
                                    delta_texto = f"R$ {delta_absoluto/1e6:+,.0f}MM".replace(",", ".")
                                else:
                                    delta_texto = f"{delta_absoluto:+.2f}"

                                # Variação percentual
                                if v_ini == 0:
                                    if delta_absoluto > 0:
                                        variacao_pct = float('inf')
                                        variacao_texto = "+∞"
                                    elif delta_absoluto < 0:
                                        variacao_pct = float('-inf')
                                        variacao_texto = "-∞"
                                    else:
                                        variacao_pct = 0
                                        variacao_texto = "0.0%"
                                else:
                                    variacao_pct = ((v_sub - v_ini) / abs(v_ini)) * 100
                                    variacao_texto = f"{variacao_pct:+.1f}%"

                                dados_grafico_brincar.append({
                                    'instituicao': instituicao,
                                    'valor_ini': v_ini,
                                    'valor_sub': v_sub,
                                    'delta': delta_absoluto,
                                    'delta_texto': delta_texto,
                                    'variacao_pct': variacao_pct if not (variacao_pct == float('inf') or variacao_pct == float('-inf')) else (1e10 if variacao_pct > 0 else -1e10),
                                    'variacao_texto': variacao_texto
                                })

                        if dados_grafico_brincar:
                            # Ordena pela variação
                            if tipo_variacao_brincar == "Δ %":
                                dados_grafico_brincar = sorted(dados_grafico_brincar, key=lambda x: x['variacao_pct'], reverse=True)
                            else:
                                dados_grafico_brincar = sorted(dados_grafico_brincar, key=lambda x: x['delta'], reverse=True)

                            # Cria o gráfico estilo lollipop
                            fig_delta_brincar = go.Figure()

                            for i, dado in enumerate(dados_grafico_brincar):
                                inst = dado['instituicao']
                                y_ini = dado['valor_ini'] * format_info['multiplicador']
                                y_sub = dado['valor_sub'] * format_info['multiplicador']
                                delta_positivo = dado['delta'] > 0

                                cor_sub = '#2E7D32' if delta_positivo else '#C62828'

                                # Linha conectando os dois pontos
                                fig_delta_brincar.add_trace(go.Scatter(
                                    x=[inst, inst],
                                    y=[y_ini, y_sub],
                                    mode='lines',
                                    line=dict(color='#9E9E9E', width=2),
                                    showlegend=False,
                                    hoverinfo='skip'
                                ))

                                # Bolinha do período inicial
                                fig_delta_brincar.add_trace(go.Scatter(
                                    x=[inst],
                                    y=[y_ini],
                                    mode='markers',
                                    marker=dict(size=12, color='#424242', line=dict(width=1, color='white')),
                                    name=periodo_inicial_brincar if i == 0 else None,
                                    showlegend=(i == 0),
                                    legendgroup='inicial',
                                    hovertemplate=f'<b>{inst}</b><br>{periodo_inicial_brincar}: %{{y:{format_info["tickformat"]}}}{format_info["ticksuffix"]}<extra></extra>'
                                ))

                                # Bolinha do período subsequente
                                fig_delta_brincar.add_trace(go.Scatter(
                                    x=[inst],
                                    y=[y_sub],
                                    mode='markers',
                                    marker=dict(size=12, color=cor_sub, line=dict(width=1, color='white')),
                                    name=periodo_subsequente_brincar if i == 0 else None,
                                    showlegend=(i == 0),
                                    legendgroup='subsequente',
                                    customdata=[[dado['delta_texto'], dado['variacao_texto']]],
                                    hovertemplate=f'<b>{inst}</b><br>{periodo_subsequente_brincar}: %{{y:{format_info["tickformat"]}}}{format_info["ticksuffix"]}<br>Δ: %{{customdata[0]}}<br>Variação: %{{customdata[1]}}<extra></extra>'
                                ))

                            titulo_delta_brincar = f"{nome_metrica}: {periodo_inicial_brincar} → {periodo_subsequente_brincar}"

                            fig_delta_brincar.update_layout(
                                title=dict(
                                    text=titulo_delta_brincar,
                                    font=dict(size=16, family='IBM Plex Sans')
                                ),
                                height=max(400, len(dados_grafico_brincar) * 25 + 150),
                                plot_bgcolor='#f8f9fa',
                                paper_bgcolor='white',
                                showlegend=True,
                                legend=dict(
                                    orientation="h",
                                    yanchor="bottom",
                                    y=1.02,
                                    xanchor="left",
                                    x=0
                                ),
                                xaxis=dict(
                                    showgrid=False,
                                    tickangle=45 if len(dados_grafico_brincar) > 10 else 0,
                                    tickfont=dict(size=10)
                                ),
                                yaxis=dict(
                                    showgrid=True,
                                    gridcolor='#e0e0e0',
                                    tickformat=format_info['tickformat'],
                                    ticksuffix=format_info['ticksuffix'],
                                    title=nome_metrica
                                ),
                                font=dict(family='IBM Plex Sans'),
                                margin=dict(l=60, r=20, t=80, b=100)
                            )

                            st.plotly_chart(fig_delta_brincar, width='stretch', config={'displayModeBar': False})

                            # Tabela e exportação
                            with st.expander("ver dados e exportar"):
                                df_resumo_brincar = pd.DataFrame(dados_grafico_brincar)
                                df_resumo_brincar = df_resumo_brincar.rename(columns={
                                    'instituicao': 'Instituição',
                                    'valor_ini': periodo_inicial_brincar,
                                    'valor_sub': periodo_subsequente_brincar,
                                    'delta_texto': 'Delta',
                                    'variacao_texto': 'Variação %'
                                })

                                # Adiciona componentes da fórmula
                                componentes = list(set([s['variavel'] for s in steps]))
                                df_export_delta = df_resumo_brincar[['Instituição', periodo_inicial_brincar, periodo_subsequente_brincar, 'Delta', 'Variação %']].copy()

                                st.dataframe(df_export_delta, width='stretch', hide_index=True)

                                col_excel, col_csv = st.columns(2)
                                with col_excel:
                                    buffer_excel = BytesIO()
                                    with pd.ExcelWriter(buffer_excel, engine='xlsxwriter') as writer:
                                        df_export_delta.to_excel(writer, index=False, sheet_name='deltas')
                                    buffer_excel.seek(0)
                                    st.download_button(
                                        label="Exportar Excel",
                                        data=buffer_excel,
                                        file_name=f"Brincar_Deltas_{nome_metrica.replace(' ', '_')}_{periodo_inicial_brincar.replace('/', '-')}_{periodo_subsequente_brincar.replace('/', '-')}.xlsx",
                                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                        key="export_excel_delta_brincar"
                                    )
                                with col_csv:
                                    csv_data = df_export_delta.to_csv(index=False)
                                    st.download_button(
                                        label="Exportar CSV",
                                        data=csv_data,
                                        file_name=f"Brincar_Deltas_{nome_metrica.replace(' ', '_')}_{periodo_inicial_brincar.replace('/', '-')}_{periodo_subsequente_brincar.replace('/', '-')}.csv",
                                        mime="text/csv",
                                        key="export_csv_delta_brincar"
                                    )
                        else:
                            st.info("sem dados válidos para exibir")

                # ===== RANKING (BARRAS) =====
                elif tipo_visualizacao == "Ranking (barras)":
                    st.markdown("---")
                    col_periodo_rank, col_ordem, col_media = st.columns([2, 1, 1])

                    with col_periodo_rank:
                        periodo_ranking = st.selectbox(
                            "período",
                            periodos_dropdown,
                            index=0,
                            key="periodo_ranking_brincar",
                            format_func=periodo_para_exibicao
                        )

                    with col_ordem:
                        ordem_ranking = st.radio(
                            "ordenação",
                            ["Maior → Menor", "Menor → Maior"],
                            horizontal=True,
                            key="ordem_ranking_brincar"
                        )

                    with col_media:
                        mostrar_media = st.checkbox("mostrar média do grupo", value=True, key="mostrar_media_brincar")

                    # Filtrar dados para o período
                    df_periodo_rank = df[df['Período'] == periodo_ranking].copy()
                    df_ranking = df_periodo_rank[df_periodo_rank['Instituição'].isin(bancos_selecionados_brincar)].copy()

                    # Calcular métrica derivada
                    df_ranking['Métrica Derivada'] = calcular_metrica_derivada(df_ranking, steps)
                    df_ranking = df_ranking.dropna(subset=['Métrica Derivada'])

                    if len(df_ranking) > 0:
                        # Ordenar
                        ascending = ordem_ranking == "Menor → Maior"
                        df_ranking = df_ranking.sort_values('Métrica Derivada', ascending=ascending)

                        # Determinar formato
                        if formato_resultado == "Percentual (%)":
                            format_info = {'tickformat': '.2f', 'ticksuffix': '%', 'multiplicador': 100}
                        elif formato_resultado == "Valor bruto (R$)":
                            format_info = {'tickformat': ',.0f', 'ticksuffix': 'M', 'multiplicador': 1/1e6}
                        elif formato_resultado == "Múltiplo (x)":
                            format_info = {'tickformat': '.2f', 'ticksuffix': 'x', 'multiplicador': 1}
                        elif formato_resultado == "Auto":
                            if formula_eh_divisao(steps):
                                format_info = {'tickformat': '.2f', 'ticksuffix': 'x', 'multiplicador': 1}
                            else:
                                format_info = {'tickformat': ',.0f', 'ticksuffix': 'M', 'multiplicador': 1/1e6}
                        else:
                            format_info = {'tickformat': '.2f', 'ticksuffix': '', 'multiplicador': 1}

                        # Preparar valores para exibição
                        df_ranking['valor_display'] = df_ranking['Métrica Derivada'] * format_info['multiplicador']

                        # Cores por instituição
                        cores = []
                        cores_plotly = px.colors.qualitative.Plotly
                        idx_cor = 0
                        for inst in df_ranking['Instituição']:
                            cor = obter_cor_banco(inst)
                            if not cor:
                                cor = cores_plotly[idx_cor % len(cores_plotly)]
                                idx_cor += 1
                            cores.append(cor)

                        fig_ranking = go.Figure()

                        fig_ranking.add_trace(go.Bar(
                            x=df_ranking['Instituição'],
                            y=df_ranking['valor_display'],
                            marker=dict(color=cores, line=dict(width=1, color='white')),
                            hovertemplate='<b>%{x}</b><br>' + nome_metrica + ': %{y:' + format_info['tickformat'] + '}' + format_info['ticksuffix'] + '<extra></extra>'
                        ))

                        # Adicionar linha de média
                        if mostrar_media:
                            media_valor = df_ranking['valor_display'].mean()
                            fig_ranking.add_hline(
                                y=media_valor,
                                line_dash="dash",
                                line_color="#FF6B6B",
                                line_width=2,
                                annotation_text=f"Média: {media_valor:{format_info['tickformat']}}{format_info['ticksuffix']}",
                                annotation_position="top right",
                                annotation_font=dict(color="#FF6B6B", size=12)
                            )

                        titulo_ranking = f"{nome_metrica} - Ranking {periodo_ranking}"

                        fig_ranking.update_layout(
                            title=dict(
                                text=titulo_ranking,
                                font=dict(size=16, family='IBM Plex Sans')
                            ),
                            height=max(400, len(df_ranking) * 25 + 150),
                            plot_bgcolor='#f8f9fa',
                            paper_bgcolor='white',
                            showlegend=False,
                            xaxis=dict(
                                showgrid=False,
                                tickangle=45 if len(df_ranking) > 10 else 0,
                                tickfont=dict(size=10)
                            ),
                            yaxis=dict(
                                showgrid=True,
                                gridcolor='#e0e0e0',
                                tickformat=format_info['tickformat'],
                                ticksuffix=format_info['ticksuffix'],
                                title=nome_metrica
                            ),
                            font=dict(family='IBM Plex Sans'),
                            margin=dict(l=60, r=20, t=60, b=100)
                        )

                        st.plotly_chart(fig_ranking, width='stretch', config={'displayModeBar': False})

                        # Tabela e exportação
                        with st.expander("ver dados e exportar"):
                            # Prepara dados para exportação
                            df_export_rank = df_ranking[['Instituição']].copy()
                            df_export_rank['Período'] = periodo_ranking
                            df_export_rank[nome_metrica] = df_ranking['Métrica Derivada']

                            # Adiciona componentes da fórmula
                            componentes = list(set([s['variavel'] for s in steps]))
                            for comp in componentes:
                                if comp in df_ranking.columns:
                                    df_export_rank[comp] = df_ranking[comp].values

                            # Reordena colunas
                            cols_ordem = ['Período', 'Instituição', nome_metrica] + componentes
                            df_export_rank = df_export_rank[[c for c in cols_ordem if c in df_export_rank.columns]]

                            st.dataframe(df_export_rank, width='stretch', hide_index=True)

                            col_excel, col_csv = st.columns(2)
                            with col_excel:
                                buffer_excel = BytesIO()
                                with pd.ExcelWriter(buffer_excel, engine='xlsxwriter') as writer:
                                    df_export_rank.to_excel(writer, index=False, sheet_name='ranking')
                                buffer_excel.seek(0)
                                st.download_button(
                                    label="Exportar Excel",
                                    data=buffer_excel,
                                    file_name=f"Brincar_Ranking_{nome_metrica.replace(' ', '_')}_{periodo_ranking.replace('/', '-')}.xlsx",
                                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                    key="export_excel_ranking_brincar"
                                )
                            with col_csv:
                                csv_data = df_export_rank.to_csv(index=False)
                                st.download_button(
                                    label="Exportar CSV",
                                    data=csv_data,
                                    file_name=f"Brincar_Ranking_{nome_metrica.replace(' ', '_')}_{periodo_ranking.replace('/', '-')}.csv",
                                    mime="text/csv",
                                    key="export_csv_ranking_brincar"
                                )
                    else:
                        st.warning("sem dados válidos para exibir no ranking")

        elif not st.session_state['brincar_formula_steps']:
            st.info("construa uma fórmula adicionando variáveis para começar a análise")
        else:
            st.info("selecione instituições para comparar")

    else:
        st.info("carregando dados automaticamente do github...")
        st.markdown("por favor, aguarde alguns segundos e recarregue a página")

elif menu == "Atualizar Base":
    st.markdown("## Atualização Base")
    st.markdown("painel de controle unificado para extração de dados do IFData/BCB")
    st.markdown("---")

    # Importar o gerenciador de cache unificado
    from utils.ifdata_cache import CacheManager, CACHES_INFO, gerar_periodos_trimestrais as gerar_periodos_cache

    # Inicializar gerenciador
    if 'cache_manager' not in st.session_state:
        st.session_state['cache_manager'] = CacheManager()
    cache_manager = st.session_state['cache_manager']

    if 'df_aliases' in st.session_state:
        st.success(f"{len(st.session_state['df_aliases'])} aliases carregados")
    else:
        st.error("aliases não encontrados")

    # =============================================================
    # STATUS DE TODOS OS CACHES (LOCAL + GITHUB)
    # =============================================================
    st.markdown("### Status dos Caches")

    # Verificar status no GitHub Releases
    github_status = verificar_caches_github()
    gh_caches = github_status.get('caches', {})

    with st.expander("ver status de todos os caches", expanded=True):
        caches_disponiveis = cache_manager.listar_caches()
        caches_info = CACHES_INFO

        # Criar tabela UNIFICADA de status (Local + GitHub + Persistência)
        status_data = []
        for tipo_cache in caches_disponiveis:
            info = cache_manager.info(tipo_cache)
            cache_info = caches_info.get(tipo_cache, {})
            gh_info = gh_caches.get(tipo_cache, {})

            existe_local = info.get("existe", False)
            existe_github = gh_info.get("existe", False)

            # Determinar situação de PERSISTÊNCIA (o que importa no Streamlit Cloud)
            if existe_github:
                persistencia = "☁️ Persistido"  # Vai sobreviver ao restart
            elif existe_local:
                persistencia = "⚠️ Efêmero"  # Vai sumir no restart
            else:
                persistencia = "❌ Ausente"

            status_data.append({
                "Cache": cache_info.get("nome_exibicao", tipo_cache),
                "Local": "✅" if existe_local else "❌",
                "GitHub": "☁️" if existe_github else "❌",
                "Persistência": persistencia,
                "Períodos": info.get("total_periodos", 0) if existe_local else "-",
                "Registros": info.get("total_registros", 0) if existe_local else "-",
                "Tamanho GH": gh_info.get("tamanho_fmt", "-") if existe_github else "-",
            })

        df_status = pd.DataFrame(status_data)
        st.dataframe(df_status, width='stretch', hide_index=True)

        # Legenda
        st.caption("""
        **Legenda:**
        - **Local**: Existe no filesystem (efêmero no Streamlit Cloud)
        - **GitHub**: Publicado no GitHub Releases (persistente)
        - **☁️ Persistido**: Dados seguros, serão recuperados após restart
        - **⚠️ Efêmero**: Só existe local, será perdido no restart - PUBLIQUE!
        """)

        # Resumo e alertas
        total_local = sum(1 for s in status_data if s["Local"] == "✅")
        total_github = sum(1 for s in status_data if s["GitHub"] == "☁️")
        total_efemero = sum(1 for s in status_data if s["Persistência"] == "⚠️ Efêmero")

        st.markdown("---")
        col_r1, col_r2, col_r3 = st.columns(3)
        with col_r1:
            st.metric("Cache Local", f"{total_local}/8")
        with col_r2:
            st.metric("GitHub Releases", f"{total_github}/8")
        with col_r3:
            if total_efemero > 0:
                st.metric("⚠️ Efêmeros", f"{total_efemero}", delta="Publicar!", delta_color="inverse")
            else:
                st.metric("✅ Efêmeros", "0")

        if total_efemero > 0:
            caches_efemeros = [s["Cache"] for s in status_data if s["Persistência"] == "⚠️ Efêmero"]
            st.warning(f"⚠️ **Atenção:** Os caches a seguir existem apenas localmente e serão perdidos no restart: **{', '.join(caches_efemeros)}**. Publique-os no GitHub!")

        if not github_status.get('release_existe'):
            st.error(f"❌ Release não acessível: {github_status.get('erro', 'erro desconhecido')}")
        else:
            st.caption(f"📦 Repositório: `{github_status.get('repo')}` | Tag: `{github_status.get('tag')}`")

    st.markdown("---")
    st.markdown("### Extração de Dados (Admin)")

    senha_input = st.text_input("senha de administrador", type="password", key="senha_admin_atualizacao_nova")

    if senha_input == SENHA_ADMIN:

        # =============================================================
        # SELEÇÃO DO CACHE A ATUALIZAR
        # =============================================================
        st.markdown("#### 1. Selecione o cache a atualizar")

        # Opções de cache com descrição
        opcoes_cache = {
            "principal": "Resumo (Rel. 1) - variáveis selecionadas",
            "capital": "Capital Regulatório (Rel. 5) - variáveis selecionadas",
            "ativo": "Ativo (Rel. 2) - TODAS as variáveis",
            "passivo": "Passivo (Rel. 3) - TODAS as variáveis",
            "dre": "DRE (Rel. 4) - TODAS as variáveis",
            "carteira_pf": "Carteira PF (Rel. 11) - TODAS as variáveis",
            "carteira_pj": "Carteira PJ (Rel. 13) - TODAS as variáveis",
            "carteira_instrumentos": "Carteira Instrumentos 4.966 (Rel. 16) - TODAS as variáveis",
            "taxas_juros": "Taxas de Juros (API BCB) - TODOS produtos/instituições",
        }

        cache_selecionado = st.selectbox(
            "cache para atualizar",
            options=list(opcoes_cache.keys()),
            format_func=lambda x: opcoes_cache[x],
            key="cache_selecionado"
        )

        # Mostrar status do cache selecionado
        info_selecionado = cache_manager.info(cache_selecionado)
        if info_selecionado.get("existe"):
            st.info(f"Cache atual: {info_selecionado.get('total_periodos', 0)} períodos, {info_selecionado.get('total_registros', 0):,} registros")
        else:
            st.warning(f"Cache '{cache_selecionado}' não existe ainda")

        # Flag para identificar se é extração de taxas de juros
        is_taxas_juros = (cache_selecionado == "taxas_juros")

        # =============================================================
        # MODO DE ATUALIZAÇÃO
        # =============================================================
        st.markdown("#### 2. Modo de atualização")

        modo_atualizacao = st.radio(
            "modo",
            options=["incremental", "overwrite"],
            format_func=lambda x: "Incremental (adiciona/atualiza períodos)" if x == "incremental" else "Overwrite (substitui todo o cache)",
            horizontal=True,
            key="modo_atualizacao"
        )

        if modo_atualizacao == "overwrite":
            st.warning("Modo OVERWRITE: todos os dados existentes serão substituídos!")

        # =============================================================
        # SELEÇÃO DE PERÍODOS
        # =============================================================
        st.markdown("#### 3. Selecione o período de extração")

        # Taxas de Juros usa seleção de data (diário), demais usam trimestral
        if is_taxas_juros:
            st.caption("⚠️ Taxas de Juros: extração completa de TODOS os produtos e TODAS as instituições")

            col_data1, col_data2 = st.columns(2)

            hoje = datetime.now()
            data_minima_tj = hoje - timedelta(days=365*3)  # 3 anos de histórico

            with col_data1:
                data_inicio_tj = st.date_input(
                    "Data inicial",
                    value=hoje - timedelta(days=365),  # 1 ano atrás por padrão
                    min_value=data_minima_tj.date(),
                    max_value=hoje.date(),
                    key="taxas_juros_data_inicio_extracao",
                    format="DD/MM/YYYY"
                )

            with col_data2:
                data_fim_tj = st.date_input(
                    "Data final",
                    value=hoje.date(),
                    min_value=data_minima_tj.date(),
                    max_value=hoje.date(),
                    key="taxas_juros_data_fim_extracao",
                    format="DD/MM/YYYY"
                )

            st.caption(f"Período selecionado: {data_inicio_tj.strftime('%d/%m/%Y')} até {data_fim_tj.strftime('%d/%m/%Y')}")
            st.info("A extração inclui paginação completa ($skip/$top) para garantir que todos os dados sejam capturados sem truncamento.")

            # Não precisa de periodos_extrair para taxas_juros
            periodos_extrair = None

        else:
            col1, col2 = st.columns(2)
            with col1:
                ano_i = st.selectbox("ano inicial", range(2015, 2029), index=8, key="ano_i_unificado")
                mes_i = st.selectbox("trimestre inicial", ['03', '06', '09', '12'], key="mes_i_unificado")
            with col2:
                ano_f = st.selectbox("ano final", range(2015, 2029), index=10, key="ano_f_unificado")
                mes_f = st.selectbox("trimestre final", ['03', '06', '09', '12'], index=2, key="mes_f_unificado")

            periodos_extrair = gerar_periodos_cache(ano_i, mes_i, ano_f, mes_f)
            st.caption(f"Serão extraídos {len(periodos_extrair)} períodos: {periodos_extrair[0][4:6]}/{periodos_extrair[0][:4]} até {periodos_extrair[-1][4:6]}/{periodos_extrair[-1][:4]}")

        # =============================================================
        # CONFIGURAÇÕES AVANÇADAS
        # =============================================================
        if not is_taxas_juros:
            with st.expander("configurações avançadas"):
                intervalo_save = st.slider(
                    "salvar a cada N períodos",
                    min_value=1,
                    max_value=10,
                    value=4,
                    help="O cache será salvo parcialmente a cada N períodos extraídos para evitar perda de dados",
                    key="intervalo_save"
                )

                st.caption("Nota: a extração usa Tipo de Instituição 1 (Conglomerados Prudenciais e Instituições Independentes)")
        else:
            intervalo_save = 1  # Não usado para taxas de juros

        # =============================================================
        # CONFIGURAÇÃO DO TOKEN GITHUB (para publicação)
        # =============================================================
        st.markdown("#### Token GitHub (para publicação)")

        # Verificar se há token nos secrets do Streamlit
        token_from_secrets = None
        try:
            token_from_secrets = st.secrets.get("GITHUB_TOKEN")
        except Exception:
            pass

        if token_from_secrets:
            st.success("✅ Token GitHub configurado via Streamlit Secrets")
            gh_token_final = token_from_secrets
        else:
            st.info("💡 Configure `GITHUB_TOKEN` nos Secrets do Streamlit Cloud para upload automático")
            gh_token_manual = st.text_input(
                "ou insira token manualmente (permissão 'repo')",
                type="password",
                key="gh_token_unificado",
                help="Token com permissão 'repo'. Configure nos Secrets para não precisar digitar."
            )
            gh_token_final = gh_token_manual if gh_token_manual else None

        # Armazenar no session_state para usar em outras partes
        st.session_state['_gh_token_unificado'] = gh_token_final

        # =============================================================
        # BOTÃO DE EXTRAÇÃO
        # =============================================================
        st.markdown("#### 4. Executar extração")

        # Para taxas de juros, não precisa de aliases; para outros, precisa
        pode_extrair = is_taxas_juros or ('dict_aliases' in st.session_state)

        if pode_extrair:

            if st.button(f"Extrair dados de {opcoes_cache[cache_selecionado]}", type="primary", width='stretch', key="btn_extrair_unificado"):

                # Containers para UI
                progress_bar = st.progress(0)
                status_text = st.empty()
                save_status = st.empty()
                log_container = st.container()
                error_container = st.container()
                erros_encontrados = []
                logs_extracao = []

                # =============================================================
                # EXTRAÇÃO ESPECIAL PARA TAXAS DE JUROS
                # =============================================================
                if is_taxas_juros:
                    from utils.ifdata_cache import TaxasJurosCache

                    def callback_progresso_tj(progress, message):
                        progress_bar.progress(min(progress, 1.0))
                        status_text.text(message)

                    def callback_log_tj(message):
                        logs_extracao.append(message)
                        with log_container:
                            st.caption(f"📝 {message}")

                    st.info(f"Iniciando extração de Taxas de Juros de {data_inicio_tj.strftime('%d/%m/%Y')} até {data_fim_tj.strftime('%d/%m/%Y')}")

                    try:
                        # Obter o cache de taxas de juros
                        cache_taxas = cache_manager.get_cache("taxas_juros")

                        if cache_taxas is None:
                            st.error("Cache de Taxas de Juros não configurado corretamente")
                        else:
                            # Executar extração completa com paginação
                            resultado = cache_taxas.extrair_completo(
                                data_inicio=data_inicio_tj.strftime('%Y-%m-%d'),
                                data_fim=data_fim_tj.strftime('%Y-%m-%d'),
                                progress_callback=callback_progresso_tj,
                                log_callback=callback_log_tj
                            )

                            # Limpar UI de progresso
                            progress_bar.empty()
                            status_text.empty()

                            if resultado.sucesso:
                                # Salvar cache
                                save_status.text("Salvando cache...")

                                # Se modo overwrite, limpar antes
                                if modo_atualizacao == "overwrite":
                                    cache_taxas.limpar_local()

                                # Salvar os dados
                                save_result = cache_taxas.salvar_local(resultado.dados, resultado.metadata)

                                save_status.empty()

                                if save_result.sucesso:
                                    st.success(f"✅ Extração e salvamento concluídos: {resultado.mensagem}")

                                    # Mostrar estatísticas
                                    meta = resultado.metadata or {}
                                    col_stat1, col_stat2, col_stat3, col_stat4 = st.columns(4)
                                    with col_stat1:
                                        st.metric("Total de linhas", f"{meta.get('total_registros', 0):,}")
                                    with col_stat2:
                                        st.metric("Produtos", meta.get('produtos_unicos', 0))
                                    with col_stat3:
                                        st.metric("Instituições", meta.get('instituicoes_unicas', 0))
                                    with col_stat4:
                                        st.metric("Períodos (datas)", meta.get('periodos_unicos', 0))

                                    # Verificar truncamento
                                    if meta.get('truncado'):
                                        st.warning("⚠️ AVISO: Possível truncamento detectado! Verifique se todos os dados foram extraídos.")
                                    else:
                                        st.success("✅ Extração completa sem truncamento")

                                    # Mostrar logs em expander
                                    with st.expander("📋 Log de extração", expanded=False):
                                        for log_line in logs_extracao:
                                            st.text(log_line)
                                else:
                                    st.error(f"Erro ao salvar cache: {save_result.mensagem}")
                            else:
                                st.error(f"Erro na extração: {resultado.mensagem}")

                    except Exception as e:
                        progress_bar.empty()
                        status_text.empty()
                        st.error(f"Erro durante extração: {e}")
                        import traceback
                        st.code(traceback.format_exc())

                # =============================================================
                # EXTRAÇÃO PADRÃO PARA OUTROS CACHES
                # =============================================================
                else:
                    def callback_progresso(i, total, periodo):
                        progress_bar.progress((i + 1) / total)
                        status_text.text(f"extraindo {periodo[4:6]}/{periodo[:4]} ({i + 1}/{total})")

                    def callback_salvamento(info):
                        save_status.text(f"salvando... {info}")

                    def callback_erro(periodo, mensagem):
                        erros_encontrados.append(f"{periodo[4:6]}/{periodo[:4]}: {mensagem}")
                        with error_container:
                            st.warning(f"Erro em {periodo[4:6]}/{periodo[:4]}: {mensagem[:100]}...")

                    st.info(f"iniciando extração de {len(periodos_extrair)} períodos para '{cache_selecionado}'. Salvamento a cada {intervalo_save} períodos.")

                    try:
                        # Usar o gerenciador unificado para extração
                        resultado = cache_manager.extrair_periodos_com_salvamento(
                            tipo=cache_selecionado,
                            periodos=periodos_extrair,
                            modo=modo_atualizacao,
                            intervalo_salvamento=intervalo_save,
                            callback_progresso=callback_progresso,
                            callback_salvamento=callback_salvamento,
                            callback_erro=callback_erro,
                            dict_aliases=st.session_state.get('dict_aliases', {})
                        )

                        # Limpar UI de progresso
                        progress_bar.empty()
                        status_text.empty()
                        save_status.empty()

                        if resultado.sucesso:
                            st.success(f"Extração concluída: {resultado.mensagem}")

                            # Mostrar estatísticas
                            metadata = resultado.metadata or {}
                            col_stat1, col_stat2, col_stat3 = st.columns(3)
                            with col_stat1:
                                st.metric("Períodos extraídos", f"{metadata.get('periodos_extraidos', 0)}/{metadata.get('periodos_total', 0)}")
                            with col_stat2:
                                st.metric("Registros totais", f"{metadata.get('total_registros', 0):,}")
                            with col_stat3:
                                st.metric("Modo", metadata.get('modo', 'N/A'))

                            # Mostrar erros se houver
                            if metadata.get('erros'):
                                with st.expander(f"erros encontrados ({len(metadata['erros'])})", expanded=False):
                                    for erro in metadata['erros']:
                                        st.caption(f"- {erro}")

                            # =============================================================
                            # DOWNLOAD IMEDIATO DO CACHE
                            # =============================================================
                            st.markdown("---")
                            st.markdown("#### Download do cache")
                            st.caption("Faça download imediato do cache para backup caso a publicação no GitHub falhe")

                            col_dl1, col_dl2 = st.columns(2)

                            with col_dl1:
                                # Download com fallback (parquet/csv/pickle)
                                download_payload = cache_manager.get_dados_para_download(cache_selecionado)
                                if download_payload:
                                    st.download_button(
                                        label=f"Download ({download_payload['label']})",
                                        data=download_payload["data"],
                                        file_name=f"{cache_selecionado}_cache{download_payload['ext']}",
                                        mime=download_payload["mime"],
                                        key="download_parquet"
                                    )
                                    if download_payload["label"].lower() != "parquet":
                                        st.caption("fallback usado por indisponibilidade do parquet")

                            with col_dl2:
                                # Download CSV
                                dados_csv = cache_manager.get_dados_para_download_csv(cache_selecionado)
                                if dados_csv:
                                    st.download_button(
                                        label="Download (CSV)",
                                        data=dados_csv,
                                        file_name=f"{cache_selecionado}_cache.csv",
                                        mime="text/csv",
                                        key="download_csv"
                                    )

                            # Atualizar session_state para caches principais
                            if cache_selecionado == "principal" and resultado.dados is not None:
                                # Converter para formato antigo se necessário
                                from utils.ifdata_cache import PrincipalCache
                                pc = PrincipalCache(cache_manager.base_dir)
                                dados_dict = pc.carregar_formato_antigo()
                                if dados_dict:
                                    if 'dados_periodos' in st.session_state and st.session_state['dados_periodos'] and modo_atualizacao == "incremental":
                                        st.session_state['dados_periodos'].update(dados_dict)
                                    else:
                                        st.session_state['dados_periodos'] = dados_dict
                                    st.session_state['cache_fonte'] = 'extração local'

                            elif cache_selecionado == "capital" and resultado.dados is not None:
                                from utils.ifdata_cache import CapitalCache
                                cc = CapitalCache(cache_manager.base_dir)
                                dados_dict = cc.carregar_formato_antigo()
                                if dados_dict:
                                    st.session_state['dados_capital'] = dados_dict

                        else:
                            st.error(f"Extração falhou: {resultado.mensagem}")
                            if resultado.metadata and resultado.metadata.get('erros'):
                                with st.expander("detalhes dos erros"):
                                    for erro in resultado.metadata['erros']:
                                        st.caption(f"- {erro}")

                    except Exception as e:
                        progress_bar.empty()
                        status_text.empty()
                        save_status.empty()
                        st.error(f"Erro durante extração: {str(e)}")

                        import traceback
                        with st.expander("traceback completo"):
                            st.code(traceback.format_exc())

        else:
            st.warning("carregue os aliases primeiro (verifique a conexão com Google Sheets)")

        # =============================================================
        # SEÇÃO: PUBLICAR NO GITHUB
        # =============================================================
        st.markdown("---")
        st.markdown("### Publicar cache no GitHub")
        st.caption("Envia o cache local para GitHub Releases (tag v1.0-cache) para uso permanente")

        # Recuperar token do session_state
        token_para_upload = st.session_state.get('_gh_token_unificado')

        if not token_para_upload:
            st.warning("⚠️ Nenhum token GitHub disponível. Configure nos Secrets ou insira manualmente acima.")

        col_pub1, col_pub2 = st.columns([3, 1])
        with col_pub1:
            if st.button(f"📤 Enviar '{cache_selecionado}' para GitHub", width='stretch', key="btn_enviar_github_unificado", disabled=not token_para_upload):
                with st.spinner(f"enviando cache '{cache_selecionado}' para github releases..."):
                    sucesso, mensagem = upload_cache_github(
                        cache_manager,
                        cache_selecionado,
                        token_para_upload
                    )
                    if sucesso:
                        st.success(f"✅ {mensagem}")
                        st.balloons()
                    else:
                        st.error(f"❌ {mensagem}")
        with col_pub2:
            st.caption(f"Token: {'✅' if token_para_upload else '❌'}")

        # =============================================================
        # SEÇÃO LEGACY: EXTRAÇÃO PRINCIPAL (COMPATIBILIDADE)
        # =============================================================
        st.markdown("---")
        with st.expander("extração legacy (sistema antigo)", expanded=False):
            st.caption("Use esta opção apenas para compatibilidade com o sistema antigo")

            col_leg1, col_leg2 = st.columns(2)
            with col_leg1:
                ano_leg_i = st.selectbox("ano inicial", range(2015, 2028), index=8, key="ano_leg_i")
                mes_leg_i = st.selectbox("trim. inicial", ['03', '06', '09', '12'], key="mes_leg_i")
            with col_leg2:
                ano_leg_f = st.selectbox("ano final", range(2015, 2028), index=10, key="ano_leg_f")
                mes_leg_f = st.selectbox("trim. final", ['03', '06', '09', '12'], index=2, key="mes_leg_f")

            if st.button("extrair (sistema legado)", key="btn_extrair_legado"):
                periodos = gerar_periodos(ano_leg_i, mes_leg_i, ano_leg_f, mes_leg_f)
                progress_bar = st.progress(0)
                status = st.empty()
                save_status = st.empty()

                def update(i, total, p):
                    progress_bar.progress((i+1)/total)
                    status.text(f"extraindo {p[4:6]}/{p[:4]} ({i+1}/{total})")

                def save_progress(dados_parciais, info):
                    save_status.text(f"salvando {len(dados_parciais)} períodos...")
                    salvar_cache(dados_parciais, info, incremental=True)
                    save_status.text(f"salvos {len(dados_parciais)} períodos")

                dados = processar_todos_periodos(
                    periodos,
                    st.session_state['dict_aliases'],
                    progress_callback=update,
                    save_callback=save_progress,
                    save_interval=5
                )

                if not dados:
                    progress_bar.empty()
                    status.empty()
                    save_status.empty()
                    st.error("falha ao extrair dados")
                else:
                    periodo_info = f"{periodos[0][4:6]}/{periodos[0][:4]} até {periodos[-1][4:6]}/{periodos[-1][:4]}"
                    cache_salvo = salvar_cache(dados, periodo_info, incremental=True)

                    if 'dados_periodos' in st.session_state and st.session_state['dados_periodos']:
                        dados_merged = st.session_state['dados_periodos'].copy()
                        dados_merged.update(dados)
                        st.session_state['dados_periodos'] = dados_merged
                    else:
                        st.session_state['dados_periodos'] = dados

                    st.session_state['cache_fonte'] = 'extração local'

                    progress_bar.empty()
                    status.empty()
                    save_status.empty()
                    st.success(f"{len(dados)} períodos extraídos!")
                    st.rerun()

    elif senha_input:
        st.error("senha incorreta")

elif menu == "Glossário":
    st.markdown("""
    ## **Sobre os Dados Apresentados**

    Os dados são obtidos via API Olinda do IFdata do Banco Central, na visão **Conglomerado**.

    **O que isso significa:**

    **Conglomerado Prudencial** é um grupo de instituições financeiras e entidades autorizadas, controladas por uma mesma instituição líder, que deve consolidar suas demonstrações contábeis para fins regulatórios.

    O Banco Central supervisiona o grupo como um todo, considerando o somatório das instituições, e decisões sobre liquidez ou insolvência afetam todas as entidades do conglomerado.

    **Exemplos:**
    - O Banco PAN faz parte do Conglomerado Prudencial BTG Pactual. O próprio PAN esclarece que, por estar consolidado no prudencial do BTG, o índice de Basileia "individual" deixou de ser formalmente reportado.
    - O Banco Digio faz parte do conglomerado financeiro do Bradesco, então em leituras "por conglomerado" você não verá o Digio como um grupo separado.
    - O Conglomerado Prudencial Original inclui Banco Original, PicPay Bank e a IP do PicPay (além de outros veículos do grupo). Dependendo do recorte, você verá o conglomerado (ou o líder) e não cada entidade isoladamente.

    Em caso de dúvidas, consulte o site do Banco Central.

    ---

    ## **Informações de Capital Regulatório**

    **Capital Principal:** Parcela do capital de melhor qualidade e imediatamente disponível para absorver perdas (base regulatória usada para comparação com o RWA).

    **Capital Complementar:** Instrumentos de capital e dívida perpétuos elegíveis como patrimônio regulatório (complementam o Capital Principal na formação do Nível I).

    **Capital Nível II:** Parcela do capital composta por instrumentos subordinados, elegíveis como patrimônio regulatório, aptos a absorver perdas durante o funcionamento da instituição.

    **Patrimônio de Referência:** Montante de capital regulatório total formado pela soma do Patrimônio de Referência Nível I e do Capital Nível II (usado para comparação com o RWA).

    **RWA Crédito:** Parcela dos ativos ponderados pelo risco (RWA) referente à exposição ao risco de crédito (pode ser apurado pela abordagem padronizada ou por modelo interno IRB, quando aplicável).

    **RWA Mercado:** Parcela do RWA referente à exposição ao risco de mercado, composta pela soma das parcelas de risco cambial, commodities, juros/cupons, ações e CVA (ajuste de valor de crédito da contraparte em derivativos), entre outras componentes do relatório.

    **RWA Operacional:** Parcela do RWA referente à exposição ao risco operacional.

    **RWA Total:** Soma das parcelas de RWA de Crédito, Mercado, Operacional e (quando existir no relatório) a parcela relativa a serviços de pagamento.

    **Exposição Total:** Exposição total sem ponderação de risco (definição regulatória usada no cálculo da razão de alavancagem, conforme Circular 3.748/2015).

    **Índice de Capital Principal:** Relação entre Capital Principal e RWA Total (Capital Principal / RWA Total).

    **Índice de Capital Nível I:** Relação entre Patrimônio de Referência Nível I e RWA Total (Nível I / RWA Total).

    **Índice de Basileia:** Relação entre Patrimônio de Referência e RWA Total (Patrimônio de Referência / RWA Total).

    **Adicional de Capital Principal:** Requerimento de adicional de capital principal (ACP), apurado pela soma de ACP Conservação, ACP Contracíclico e ACP Sistêmico.

    ---

    ## **Variáveis Monetárias**

    **Ativo Total:** Padrão COSIF.

    **Carteira de Crédito:** Valor líquido, já descontada a PDD.

    **Títulos e Valores Mobiliários:** Títulos de Renda Fixa + Aplicação em COEs + Cotas de Fundos de Curto Prazo e Fundos de Investimentos, já descontados de Perda Incorrida, Perda Esperada e Ajuste a Valor Justo.

    **Passivo Exigível:** Passivo Total, incluindo Depósitos, Compromissadas, Outros Instrumentos de Dívida, Relações Interfinanceiras, Relações Interdependências, Derivativos, Provisões (Cíveis, Fiscais, Trabalhistas) e Outras Obrigações.

    **Captações:** Todos os tipos de passivos, exceto (i) Títulos de Dívida Elegíveis a Capital e (ii) Dívidas Subordinadas Elegíveis a Capital.

    **Patrimônio Líquido:** Padrão COSIF.

    **Lucro Líquido Acumulado YTD:** Lucro líquido acumulado entre janeiro do ano-competência até o final do semestre de referência (ex: 09/2025 refere-se ao lucro acumulado no ano de 2025, até 30/09/2025).

    ---

    ## **Índices e Percentuais**

    **Índice de Imobilização:** Ativo Permanente dividido pelo Patrimônio de Referência.

    ---

    ## **Métricas Calculadas**

    **ROE Ac. YTD an. (%):** Lucro Líquido acumulado entre janeiro e o fim do período, dividido pelo Patrimônio Líquido.

    **Crédito/PL (%):** Carteira de Crédito Líquida dividida pelo Patrimônio Líquido.

    **Crédito/Captações (%):** Carteira de Crédito Líquida dividida pelas Captações.

    **Crédito/Ativo (%):** Carteira de Crédito Líquida dividida pelo Ativo Total.
    """)
