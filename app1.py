import streamlit as st
import pandas as pd
import pickle
import os
import requests
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path
from datetime import datetime, timedelta
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
from utils.ifdata_extractor import (
    gerar_periodos,
    processar_todos_periodos,
    construir_mapa_codinst,
    construir_mapa_codinst_multiperiodo,
    get_log_file_path,
    parece_codigo_instituicao,
)
# Import isolado para extração de capital (cache separado, sem impacto no fluxo principal)
from utils.capital_extractor import (
    gerar_periodos_capital,
    processar_todos_periodos_capital,
    salvar_cache_capital,
    carregar_cache_capital,
    get_capital_cache_info,
    ler_info_cache_capital,
    get_campos_capital_info,
)
# Import para extração de taxas de juros do BCB
from utils.taxas_juros_extractor import (
    buscar_modalidades_disponiveis,
    buscar_instituicoes_por_modalidade,
    buscar_instituicoes_todas_modalidades,
    extrair_taxas_juros,
    formatar_nome_modalidade,
    obter_periodos_disponiveis,
    criar_tabela_pivot,
    calcular_estatisticas,
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

CACHE_FILE = str(DATA_DIR / "dados_cache.pkl")
CACHE_INFO = str(DATA_DIR / "cache_info.txt")
ALIASES_PATH = str(DATA_DIR / "Aliases.xlsx")
LOGO_PATH = str(DATA_DIR / "logo.png")
CACHE_URL = "https://github.com/abalroar/tomaconta/releases/download/v1.0-cache/dados_cache.pkl"
CACHE_INFO_URL = "https://github.com/abalroar/tomaconta/releases/download/v1.0-cache/cache_info.txt"

# Senha para proteger a funcionalidade de atualização de cache
SENHA_ADMIN = "m4th3u$987"

VARS_PERCENTUAL = [
    'ROE An. (%)',
    'Índice de Basileia',
    'Crédito/Captações (%)',
    'Crédito/Ativo (%)',
    'Market Share Carteira',
    'Índice de Imobilização',
]
VARS_RAZAO = ['Crédito/PL']
VARS_MOEDAS = [
    'Carteira de Crédito',
    'Lucro Líquido',
    'Patrimônio Líquido',
    'Captações',
    'Ativo Total',
    'Títulos e Valores Mobiliários',
    'Passivo Exigível',
    'Patrimônio de Referência',
    'Patrimônio de Referência para Comparação com o RWA (e)',
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
    info = {
        'existe': False,
        'caminho': os.path.abspath(CACHE_FILE),
        'tamanho': 0,
        'tamanho_formatado': '0 B',
        'data_modificacao': None,
        'data_formatada': 'N/A',
        'fonte': 'nenhuma'
    }
    if os.path.exists(CACHE_FILE):
        info['existe'] = True
        stat = os.stat(CACHE_FILE)
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
    return info

def salvar_cache(dados_periodos, periodo_info, incremental=True):
    """Salva o cache localmente, fazendo merge incremental com dados existentes.

    Args:
        dados_periodos: Dicionário {periodo: DataFrame} com os novos dados
        periodo_info: String com informação do período extraído
        incremental: Se True (padrão), faz merge com cache existente.
                     Se False, sobrescreve completamente.

    Returns:
        Informações do cache salvo
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Se modo incremental, carregar dados existentes e fazer merge
    dados_finais = {}
    if incremental and os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'rb') as f:
                dados_existentes = pickle.load(f)
            if dados_existentes:
                dados_finais = dados_existentes.copy()
                print(f"[CACHE] Carregados {len(dados_existentes)} períodos existentes para merge")
        except Exception as e:
            print(f"[CACHE] Erro ao carregar cache existente: {e}, criando novo")

    # Adicionar/atualizar com novos dados
    novos = 0
    atualizados = 0
    for periodo, df in dados_periodos.items():
        if periodo in dados_finais:
            atualizados += 1
        else:
            novos += 1
        dados_finais[periodo] = df

    print(f"[CACHE] Merge: {novos} novos, {atualizados} atualizados, {len(dados_finais)} total")

    # Salvar dados combinados
    with open(CACHE_FILE, 'wb') as f:
        pickle.dump(dados_finais, f)

    # Atualizar info do cache
    with open(CACHE_INFO, 'w') as f:
        f.write(f"Última extração: {datetime.now().strftime('%d/%m/%Y %H:%M')}\n")
        f.write(f"Última operação: {periodo_info}\n")
        f.write(f"Total de períodos: {len(dados_finais)}\n")
        if incremental:
            f.write(f"Novos períodos: {novos}, Atualizados: {atualizados}\n")

    return get_cache_info_detalhado()

def carregar_cache():
    """Carrega o cache do arquivo local."""
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, 'rb') as f:
            return pickle.load(f)
    return None

def recalcular_metricas_derivadas(dados_periodos):
    """Recalcula métricas derivadas para dados carregados do cache.

    Garante que métricas como Crédito/PL, Crédito/Ativo (%), etc. existam
    mesmo em caches antigos que foram criados antes dessas métricas serem adicionadas.
    """
    if not dados_periodos:
        return dados_periodos

    dados_atualizados = {}
    for periodo, df in dados_periodos.items():
        df_atualizado = df.copy()

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

        # ROE Anualizado
        if "ROE An. (%)" not in df_atualizado.columns:
            if "Lucro Líquido" in df_atualizado.columns and "Patrimônio Líquido" in df_atualizado.columns:
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
                df_atualizado["ROE An. (%)"] = (
                    (fator * df_atualizado["Lucro Líquido"].fillna(0)) /
                    df_atualizado["Patrimônio Líquido"].replace(0, np.nan)
                )

        # Crédito/PL
        if "Crédito/PL" not in df_atualizado.columns:
            if "Carteira de Crédito" in df_atualizado.columns and "Patrimônio Líquido" in df_atualizado.columns:
                df_atualizado["Crédito/PL"] = (
                    df_atualizado["Carteira de Crédito"].fillna(0) /
                    df_atualizado["Patrimônio Líquido"].replace(0, np.nan)
                )

        # Crédito/Captações
        if "Crédito/Captações (%)" not in df_atualizado.columns:
            if "Carteira de Crédito" in df_atualizado.columns and "Captações" in df_atualizado.columns:
                df_atualizado["Crédito/Captações (%)"] = (
                    df_atualizado["Carteira de Crédito"].fillna(0) /
                    df_atualizado["Captações"].replace(0, np.nan)
                )

        # Crédito/Ativo (%) - anteriormente chamado Carteira/Ativo (%)
        if "Crédito/Ativo (%)" not in df_atualizado.columns:
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

def ler_info_cache():
    if os.path.exists(CACHE_INFO):
        with open(CACHE_INFO, 'r') as f:
            return f.read()
    return None

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

def upload_cache_github(gh_token=None):
    """Faz upload do cache para GitHub Releases usando gh CLI ou API.
    Retorna (sucesso, mensagem).
    """
    cache_path = Path(CACHE_FILE)
    cache_info_path = Path(CACHE_INFO)

    if not cache_path.exists():
        return False, "arquivo de cache não encontrado"

    repo = "abalroar/tomaconta"
    tag = "v1.0-cache"

    # Tentar usar gh CLI primeiro (mais simples se autenticado)
    try:
        # Verificar se gh está disponível e autenticado
        result = subprocess.run(['gh', 'auth', 'status'], capture_output=True, text=True, timeout=10)
        gh_available = result.returncode == 0

        if gh_available:
            # Deletar assets antigos e fazer upload dos novos
            # Primeiro, tentar deletar os assets existentes
            subprocess.run(
                ['gh', 'release', 'delete-asset', tag, 'dados_cache.pkl', '-y', '-R', repo],
                capture_output=True, text=True, timeout=30
            )
            subprocess.run(
                ['gh', 'release', 'delete-asset', tag, 'cache_info.txt', '-y', '-R', repo],
                capture_output=True, text=True, timeout=30
            )

            # Upload do cache
            result = subprocess.run(
                ['gh', 'release', 'upload', tag, str(cache_path), '--clobber', '-R', repo],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode != 0:
                return False, f"erro ao fazer upload do cache: {result.stderr}"

            # Upload do cache_info se existir
            if cache_info_path.exists():
                subprocess.run(
                    ['gh', 'release', 'upload', tag, str(cache_info_path), '--clobber', '-R', repo],
                    capture_output=True, text=True, timeout=30
                )

            return True, "cache enviado para github releases com sucesso!"

    except FileNotFoundError:
        pass  # gh CLI não disponível
    except subprocess.TimeoutExpired:
        return False, "timeout ao executar gh CLI"
    except Exception as e:
        return False, f"erro ao usar gh CLI: {str(e)}"

    # Se gh CLI não disponível, usar API REST com token
    if gh_token:
        try:
            headers = {
                'Authorization': f'token {gh_token}',
                'Accept': 'application/vnd.github.v3+json'
            }

            # Obter release info
            release_url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
            r = requests.get(release_url, headers=headers, timeout=30)
            if r.status_code != 200:
                return False, f"release '{tag}' não encontrada no github"

            release_data = r.json()
            upload_url = release_data['upload_url'].replace('{?name,label}', '')

            # Deletar assets antigos se existirem
            for asset in release_data.get('assets', []):
                if asset['name'] in ['dados_cache.pkl', 'cache_info.txt']:
                    delete_url = f"https://api.github.com/repos/{repo}/releases/assets/{asset['id']}"
                    requests.delete(delete_url, headers=headers, timeout=30)

            upload_headers = {
                'Authorization': f'token {gh_token}',
                'Content-Type': 'application/octet-stream'
            }

            # Upload do cache principal
            with open(cache_path, 'rb') as f:
                r = requests.post(
                    f"{upload_url}?name=dados_cache.pkl",
                    headers=upload_headers,
                    data=f,
                    timeout=300
                )
                if r.status_code not in [200, 201]:
                    return False, f"erro ao fazer upload do cache: {r.status_code}"

            # Upload do cache_info.txt se existir
            if cache_info_path.exists():
                with open(cache_info_path, 'rb') as f:
                    r = requests.post(
                        f"{upload_url}?name=cache_info.txt",
                        headers=upload_headers,
                        data=f,
                        timeout=30
                    )
                    if r.status_code not in [200, 201]:
                        return False, f"erro ao fazer upload do cache_info: {r.status_code}"

            return True, "cache enviado para github releases com sucesso!"

        except Exception as e:
            return False, f"erro ao usar API do github: {str(e)}"

    return False, "gh CLI não disponível e nenhum token fornecido"

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


def resolver_nomes_instituicoes_capital(df_capital, dict_aliases, df_aliases=None):
    """Resolve nomes de instituições que estão como códigos [IF xxxxx] no cache de capital.

    Usa múltiplas estratégias de lookup:
    1. Busca direta no dict_aliases (nome original -> alias)
    2. Busca por CodInst no df_aliases se disponível
    3. Mantém o nome original se não encontrar correspondência

    Args:
        df_capital: DataFrame com dados de capital
        dict_aliases: Dicionário nome original -> alias
        df_aliases: DataFrame do Aliases.xlsx com mapeamentos

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

    def resolver_nome(nome, codinst=None):
        """Resolve um nome de instituição."""
        if pd.isna(nome):
            return nome

        nome_str = str(nome).strip()

        # 1. Busca direta no dict_aliases
        if dict_aliases and nome_str in dict_aliases:
            return dict_aliases[nome_str]

        # 2. Verificar se é um placeholder [IF xxxxx]
        match = re.match(r'\[IF\s+(\d+)\]', nome_str)
        if match:
            cod_extraido = match.group(1)

            # Tentar resolver pelo código extraído
            if mapa_codinst_nome and cod_extraido in mapa_codinst_nome:
                return mapa_codinst_nome[cod_extraido]

            # Se temos CodInst na linha, usar para lookup
            if codinst is not None and pd.notna(codinst):
                cod_str = str(int(codinst)) if isinstance(codinst, float) else str(codinst)
                if mapa_codinst_nome and cod_str in mapa_codinst_nome:
                    return mapa_codinst_nome[cod_str]

        # 3. Se temos CodInst, tentar lookup direto
        if codinst is not None and pd.notna(codinst):
            cod_str = str(int(codinst)) if isinstance(codinst, float) else str(codinst)
            if mapa_codinst_nome and cod_str in mapa_codinst_nome:
                return mapa_codinst_nome[cod_str]

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

def baixar_cache_inicial():
    """Baixa o cache inicial do GitHub Releases se não existir localmente.
    Retorna uma tupla (sucesso, fonte) onde fonte pode ser 'local', 'github' ou 'nenhuma'.
    """
    cache_path = Path(CACHE_FILE)
    if cache_path.exists():
        st.session_state['cache_fonte'] = 'local'
        return True, 'local'

    try:
        with st.spinner("carregando dados do github releases..."):
            r = requests.get(CACHE_URL, timeout=120)
            if r.status_code == 200:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_bytes(r.content)
                r_info = requests.get(CACHE_INFO_URL, timeout=30)
                if r_info.status_code == 200:
                    Path(CACHE_INFO).write_text(r_info.text)
                st.session_state['cache_fonte'] = 'github releases'
                return True, 'github releases'
            else:
                st.warning(f"cache não encontrado no github (http {r.status_code})")
                return False, 'nenhuma'
    except Exception as e:
        st.error(f"erro ao baixar cache: {e}")
        return False, 'nenhuma'

def ordenar_periodos(periodos, reverso=False):
    def chave_periodo(valor):
        try:
            mes, ano = valor.split('/')
            return (int(ano), int(mes))
        except (ValueError, AttributeError):
            return (0, 0)

    return sorted(periodos, key=chave_periodo, reverse=reverso)

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

    # Hash baseado nas chaves dos períodos para invalidação de cache
    periodos_keys = tuple(sorted(st.session_state['dados_periodos'].keys()))
    periodos_hash = str(hash(periodos_keys))

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
        ('ROE Anualizado', 'ROE An. (%)'),
        ('Índice de Basileia', 'Índice de Basileia'),
        ('Crédito/PL', 'Crédito/PL'),
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
                use_bar = (var == 'Lucro Líquido')
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

if 'dados_periodos' not in st.session_state:
    _perf_start("init_dados_periodos")
    sucesso, fonte = baixar_cache_inicial()
    dados_cache = carregar_cache()
    if dados_cache:
        _perf_start("recalc_metricas")
        dados_cache = recalcular_metricas_derivadas(dados_cache)
        print(_perf_log("recalc_metricas"))
        if 'dict_aliases' in st.session_state:
            # OTIMIZAÇÃO: NÃO chamar construir_mapa_codinst() aqui
            # O mapa de códigos só é necessário se os dados tiverem códigos
            # numéricos ao invés de nomes. O cache já tem nomes válidos.
            _perf_start("aplicar_aliases")
            dados_cache = aplicar_aliases_em_periodos(
                dados_cache,
                st.session_state['dict_aliases'],
                mapa_codigos=None,  # Evita chamada HTTP à API Olinda
            )
            print(_perf_log("aplicar_aliases"))
        st.session_state['dados_periodos'] = dados_cache
        if 'cache_fonte' not in st.session_state:
            st.session_state['cache_fonte'] = fonte
    print(_perf_log("init_dados_periodos"))

# Carregar cache de capital (isolado) se disponível
if 'dados_capital' not in st.session_state:
    _perf_start("init_dados_capital")
    dados_capital = carregar_cache_capital()
    if dados_capital:
        # Aplicar aliases ao cache de capital (sem mapa de códigos)
        if 'dict_aliases' in st.session_state:
            dados_capital = aplicar_aliases_em_periodos(
                dados_capital,
                st.session_state['dict_aliases'],
                mapa_codigos=None,  # Evita chamada HTTP à API Olinda
            )
        st.session_state['dados_capital'] = dados_capital
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

# Menu centralizado usando CSS flex
st.markdown('<div class="header-nav">', unsafe_allow_html=True)
menu = st.segmented_control(
    "navegação",
    ["Sobre", "Resumo", "Infos de Capital", "Análise Individual", "Série Histórica", "Scatter Plot", "Deltas", "Brincar", "Dados"],
    default=st.session_state['menu_atual'],
    label_visibility="collapsed"
)
st.markdown('</div>', unsafe_allow_html=True)

if menu != st.session_state['menu_atual']:
    st.session_state['menu_atual'] = menu
    st.rerun()

st.markdown("---")

# Sidebar apenas para controle avançado
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
        if st.button("recarregar cache do disco", use_container_width=True):
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
                if st.button("extrair dados do BCB", type="primary", use_container_width=True):
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
                st.markdown("**publicar cache no github**")
                st.caption("envia o cache local para github releases para que outros usuários possam usar")

                gh_token = st.text_input("github token (opcional)", type="password", key="gh_token",
                                        help="token com permissão 'repo'. deixe em branco se gh CLI estiver autenticado")

                if st.button("enviar cache para github", use_container_width=True):
                    with st.spinner("enviando cache para github releases..."):
                        sucesso, mensagem = upload_cache_github(gh_token if gh_token else None)
                        if sucesso:
                            st.success(mensagem)
                        else:
                            st.error(mensagem)

                # =============================================================
                # SEÇÃO ISOLADA: EXTRAÇÃO DE DADOS DE CAPITAL
                # Cache separado (capital_cache.pkl), sem impacto no fluxo principal
                # =============================================================
                st.markdown("---")
                st.markdown("**extrair capital (relatório 5)**")
                st.caption("extrai informações de capital (índices, RWA, alavancagem) - cache separado")

                # Mostrar status do cache de capital
                capital_cache_info = get_capital_cache_info()
                if capital_cache_info['existe']:
                    st.caption(f"📊 cache capital: {capital_cache_info['n_periodos']} períodos | {capital_cache_info['tamanho_formatado']}")
                    st.caption(f"📅 atualizado: {capital_cache_info['data_formatada']}")
                else:
                    st.caption("📊 cache capital: não existe ainda")

                col_cap1, col_cap2 = st.columns(2)
                with col_cap1:
                    ano_cap_i = st.selectbox("ano inicial", range(2015, 2028), index=8, key="ano_cap_i")
                    mes_cap_i = st.selectbox("trim. inicial", ['03', '06', '09', '12'], key="mes_cap_i")
                with col_cap2:
                    ano_cap_f = st.selectbox("ano final", range(2015, 2028), index=10, key="ano_cap_f")
                    mes_cap_f = st.selectbox("trim. final", ['03', '06', '09', '12'], index=2, key="mes_cap_f")

                if st.button("extrair dados de capital", type="secondary", use_container_width=True, key="btn_extrair_capital"):
                    periodos_cap = gerar_periodos_capital(ano_cap_i, mes_cap_i, ano_cap_f, mes_cap_f)
                    progress_bar_cap = st.progress(0)
                    status_cap = st.empty()
                    save_status_cap = st.empty()

                    def update_cap(i, total, p):
                        progress_bar_cap.progress((i + 1) / total)
                        status_cap.text(f"extraindo capital {p[4:6]}/{p[:4]} ({i + 1}/{total})")

                    def save_progress_cap(dados_parciais, info):
                        save_status_cap.text(f"💾 salvando {len(dados_parciais)} períodos de capital...")
                        salvar_cache_capital(dados_parciais, info, incremental=True)
                        save_status_cap.text(f"✓ {len(dados_parciais)} períodos de capital salvos")

                    st.info(f"🔄 iniciando extração de capital: {len(periodos_cap)} períodos")

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
                        cache_capital_salvo = salvar_cache_capital(dados_capital, periodo_info_cap, incremental=True)

                        progress_bar_cap.empty()
                        status_cap.empty()
                        save_status_cap.empty()

                        st.success(f"✓ {len(dados_capital)} períodos de capital extraídos!")
                        st.info(f"cache capital salvo em: {cache_capital_salvo['caminho']}")
                        st.info(f"tamanho: {cache_capital_salvo['tamanho_formatado']} | total: {cache_capital_salvo['n_periodos']} períodos")

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

    o toma.conta é uma plataforma de análise financeira que automatiza a extração, processamento e visualização de dados de instituições financeiras brasileiras, oferecendo insights comparativos e históricos.
    """)

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("""
        <div class="feature-card">
            <h4>extração automatizada</h4>
            <p>integração direta com a api if.data do banco central do brasil para coleta de dados históricos.</p>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("""
        <div class="feature-card">
            <h4>análise temporal</h4>
            <p>acompanhamento histórico de métricas financeiras ao longo de múltiplos trimestres com séries temporais.</p>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("""
        <div class="feature-card">
            <h4>visualização interativa</h4>
            <p>gráficos de dispersão customizáveis com filtros dinâmicos e comparações multi-institucionais.</p>
        </div>
        """, unsafe_allow_html=True)

    with col2:
        st.markdown("""
        <div class="feature-card">
            <h4>nomenclatura personalizada</h4>
            <p>sistema de nomenclaturas para renomear e categorizar instituições conforme nomes-fantasia.</p>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("""
        <div class="feature-card">
            <h4>métricas calculadas</h4>
            <p>roe anualizado (%), alavancagem (crédito / PL), lucro líquido, patrimônio líquido, carteira de crédito (R$ mm)</p>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("""
        <div class="feature-card">
            <h4>dados oficiais</h4>
            <p>fonte única e confiável: api if.data do banco central do brasil com atualização trimestral.</p>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")

    st.markdown("""
    ## dados disponíveis

    todas as informações são extraídas diretamente da **api if.data** do banco central, incluindo:
    """)

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("""
        - carteira de crédito classificada
        - patrimônio líquido e resultado
        - índice de basileia e capital
        """)

    with col2:
        st.markdown("""
        - captações e funding
        - ativo total e composição
        - cadastro de instituições autorizadas
        """)

    st.markdown("---")

    st.markdown("""
    ## como utilizar

    1. **dados pré-carregados**: a plataforma já possui dados históricos prontos para análise
    2. **navegue pelas páginas**: use o menu lateral para acessar análise individual ou scatter plot
    3. **atualize quando necessário**: configure o período desejado e clique em extrair dados
    4. **personalize visualizações**: aplique filtros e ajuste variáveis conforme sua análise

    ---

    ## stack tecnológica

    - **python 3.10+** | linguagem base
    - **streamlit** | interface web interativa
    - **pandas** | processamento e análise de dados
    - **plotly** | visualizações dinâmicas
    - **api bcb olinda** | fonte oficial de dados
    """)

    st.markdown("---")
    st.caption("desenvolvido em 2026 por matheus prates, cfa | ferramenta open-source para análise do sistema financeiro brasileiro")

elif menu == "Resumo":
    st.markdown("## resumo comparativo por período")
    st.caption("compare múltiplas instituições em um único trimestre, com ranking e média do grupo selecionado.")

    if 'dados_periodos' in st.session_state and st.session_state['dados_periodos']:
        df = get_dados_concatenados()  # OTIMIZAÇÃO: usar cache

        indicadores_config = {
            'Ativo Total': ['Ativo Total'],
            'Carteira de Crédito': ['Carteira de Crédito'],
            'Títulos e Valores Mobiliários': ['Títulos e Valores Mobiliários'],
            'Passivo Exigível': ['Passivo Exigível'],
            'Captações': ['Captações'],
            'Patrimônio Líquido': ['Patrimônio Líquido'],
            'Lucro Líquido': ['Lucro Líquido'],
            'Patrimônio de Referência': [
                'Patrimônio de Referência para Comparação com o RWA (e)',
                'Patrimônio de Referência',
            ],
            'Índice de Basileia': ['Índice de Basileia'],
            'Índice de Imobilização': ['Índice de Imobilização'],
            'Número de Agências': ['Número de Agências'],
            'Número de Postos de Atendimento': ['Número de Postos de Atendimento'],
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

            col_periodo, col_indicador, col_escala, col_tipo, col_media = st.columns([1.2, 2, 1.1, 1.3, 1.8])
            with col_periodo:
                periodo_resumo = st.selectbox(
                    "período (trimestre)",
                    periodos,
                    index=0,
                    key="periodo_resumo"
                )
            with col_indicador:
                indicador_label = st.selectbox(
                    "indicador",
                    list(indicadores_disponiveis.keys()),
                    key="indicador_resumo"
                )
            with col_escala:
                escala_resumo = st.radio(
                    "escala",
                    ["Linear", "Log"],
                    horizontal=True,
                    key="escala_resumo"
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

            if 'dict_aliases' in st.session_state and st.session_state['dict_aliases']:
                aliases_set = set(st.session_state['dict_aliases'].values())

                bancos_com_alias = []
                bancos_sem_alias = []

                for banco in bancos_todos:
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
                bancos_todos = bancos_com_alias_sorted + bancos_sem_alias_sorted
            else:
                bancos_todos = sorted(bancos_todos)

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

                        st.plotly_chart(fig_resumo, use_container_width=True, config={'displayModeBar': False})

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

                    usar_log = escala_resumo == "Log"
                    if usar_log and (df_selecionado['valor_display'] <= 0).any():
                        st.warning("escala log desativada: o indicador possui valores zero ou negativos.")
                        usar_log = False

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
                            ticksuffix=format_info['ticksuffix'] if orientacao_horizontal else None,
                            type='log' if usar_log and orientacao_horizontal else None
                        ),
                        yaxis=dict(
                            tickformat=format_info['tickformat'] if not orientacao_horizontal else None,
                            ticksuffix=format_info['ticksuffix'] if not orientacao_horizontal else None,
                            type='log' if usar_log and not orientacao_horizontal else None
                        ),
                        font=dict(family='IBM Plex Sans')
                    )

                    st.plotly_chart(fig_resumo, use_container_width=True, config={'displayModeBar': False})

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

elif menu == "Infos de Capital":
    st.markdown("## infos de capital")
    st.caption("análise de indicadores de capital usando dados do Relatório 5 (IFData/Olinda).")

    if 'dados_capital' in st.session_state and st.session_state['dados_capital']:
        df_capital = pd.concat(st.session_state['dados_capital'].values(), ignore_index=True)

        # Resolver nomes de instituições que estão como códigos [IF xxxxx]
        dict_aliases = st.session_state.get('dict_aliases', {})
        df_aliases = st.session_state.get('df_aliases', None)
        df_capital = resolver_nomes_instituicoes_capital(df_capital, dict_aliases, df_aliases)

        # Mapeamento flexível de colunas (nome esperado -> alternativas)
        mapa_colunas_capital = {
            'Capital Principal': ['Capital Principal', 'Capital Principal para Comparação com RWA (a)'],
            'Capital Complementar': ['Capital Complementar', 'Capital Complementar (b)'],
            'Capital Nível II': ['Capital Nível II', 'Capital Nível II (d)'],
            'RWA Total': ['RWA Total', 'Ativos Ponderados pelo Risco (RWA) (j)', 'RWA']
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

        if colunas_faltantes:
            st.warning(f"Colunas necessárias ausentes no cache de capital: {', '.join(colunas_faltantes)}")
            with st.expander("Colunas disponíveis no cache"):
                st.write(sorted([c for c in df_capital.columns if c not in ['Instituição', 'CodInst', 'Período']]))
        else:
            periodos_capital = ordenar_periodos(df_capital['Período'].dropna().unique(), reverso=True)

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
                    "período (trimestre)",
                    periodos_capital,
                    index=0,
                    key="periodo_capital"
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

                # Ordenar bancos: aliases primeiro, depois por nome
                if 'dict_aliases' in st.session_state and st.session_state['dict_aliases']:
                    aliases_set = set(st.session_state['dict_aliases'].values())

                    bancos_com_alias = []
                    bancos_sem_alias = []

                    for banco in bancos_todos_cap:
                        if banco in aliases_set:
                            bancos_com_alias.append(banco)
                        else:
                            bancos_sem_alias.append(banco)

                    def sort_key_cap(nome):
                        primeiro_char = nome[0].lower() if nome else 'z'
                        if primeiro_char.isdigit():
                            return (1, nome.lower())
                        return (0, nome.lower())

                    bancos_com_alias_sorted = sorted(bancos_com_alias, key=sort_key_cap)
                    bancos_sem_alias_sorted = sorted(bancos_sem_alias, key=sort_key_cap)
                    bancos_todos_cap = bancos_com_alias_sorted + bancos_sem_alias_sorted
                else:
                    bancos_todos_cap = sorted(bancos_todos_cap)

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

                    st.plotly_chart(fig_capital, use_container_width=True, config={'displayModeBar': False})

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
                        use_container_width=True,
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

elif menu == "Análise Individual":
    if 'dados_periodos' in st.session_state and st.session_state['dados_periodos']:
        df = get_dados_concatenados()  # OTIMIZAÇÃO: usar cache

        if len(df) > 0 and 'Instituição' in df.columns:
            bancos_todos = df['Instituição'].dropna().unique().tolist()

            if 'dict_aliases' in st.session_state and st.session_state['dict_aliases']:
                # Cria set de aliases (valores do dicionário) - os dados já têm nomes substituídos
                aliases_set = set(st.session_state['dict_aliases'].values())

                bancos_com_alias = []
                bancos_sem_alias = []

                for banco in bancos_todos:
                    # Verifica se o banco é um alias (está nos valores do dicionário)
                    if banco in aliases_set:
                        bancos_com_alias.append(banco)
                    else:
                        bancos_sem_alias.append(banco)

                # Ordenação: letras antes de números, case-insensitive
                def sort_key(nome):
                    primeiro_char = nome[0].lower() if nome else 'z'
                    if primeiro_char.isdigit():
                        return (1, nome.lower())
                    return (0, nome.lower())

                bancos_com_alias_sorted = sorted(bancos_com_alias, key=sort_key)
                bancos_sem_alias_sorted = sorted(bancos_sem_alias, key=sort_key)
                bancos_disponiveis = bancos_com_alias_sorted + bancos_sem_alias_sorted
            else:
                bancos_disponiveis = sorted(bancos_todos)

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
                            key="periodo_ini_individual"
                        )
                    with col_p2:
                        periodo_final = st.selectbox(
                            "período final",
                            periodos_dropdown,
                            index=0,
                            key="periodo_fin_individual"
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
                        st.metric("roe anualizado", formatar_valor(dados_periodo_final.get('ROE An. (%)'), 'ROE An. (%)'))
                    with col3:
                        st.metric("índice de basileia", formatar_valor(dados_periodo_final.get('Índice de Basileia'), 'Índice de Basileia'))
                    with col4:
                        st.metric("crédito/pl", formatar_valor(dados_periodo_final.get('Crédito/PL'), 'Crédito/PL'))

                    st.markdown("---")
                    st.markdown("### evolução histórica das variáveis")

                    ordem_variaveis = [
                        'Ativo Total',
                        'Captações',
                        'Patrimônio Líquido',
                        'Carteira de Crédito',
                        'Crédito/Ativo (%)',
                        'Crédito/PL',
                        'Crédito/Captações (%)',
                        'Market Share Carteira',
                        'Lucro Líquido',
                        'ROE An. (%)'
                    ]

                    # Filtra apenas as variáveis que existem e têm dados
                    variaveis = [v for v in ordem_variaveis if v in df_banco_filtrado.columns and df_banco_filtrado[v].notna().any()]

                    for i in range(0, len(variaveis), 3):
                        cols = st.columns(3)
                        for j, col_obj in enumerate(cols):
                            if i + j < len(variaveis):
                                var = variaveis[i + j]
                                with col_obj:
                                    # Usa gráfico de barras para Lucro Líquido
                                    tipo_grafico = 'barra' if var == 'Lucro Líquido' else 'linha'
                                    fig = criar_mini_grafico(df_banco_filtrado, var, var, tipo=tipo_grafico)
                                    st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
            else:
                st.warning("nenhuma instituição encontrada nos dados")
        else:
            st.warning("dados incompletos ou vazios")
    else:
        st.info("carregando dados automaticamente do github...")
        st.markdown("por favor, aguarde alguns segundos e recarregue a página")

elif menu == "Série Histórica":
    if 'dados_periodos' in st.session_state and st.session_state['dados_periodos']:
        df = get_dados_concatenados()  # OTIMIZAÇÃO: usar cache

        if len(df) > 0 and 'Instituição' in df.columns:
            bancos_todos = df['Instituição'].dropna().unique().tolist()

            if 'dict_aliases' in st.session_state and st.session_state['dict_aliases']:
                # Cria set de aliases (valores do dicionário) - os dados já têm nomes substituídos
                aliases_set = set(st.session_state['dict_aliases'].values())

                bancos_com_alias = []
                bancos_sem_alias = []

                for banco in bancos_todos:
                    # Verifica se o banco é um alias (está nos valores do dicionário)
                    if banco in aliases_set:
                        bancos_com_alias.append(banco)
                    else:
                        bancos_sem_alias.append(banco)

                # Ordenação: letras antes de números, case-insensitive
                def sort_key(nome):
                    primeiro_char = nome[0].lower() if nome else 'z'
                    if primeiro_char.isdigit():
                        return (1, nome.lower())
                    return (0, nome.lower())

                bancos_com_alias_sorted = sorted(bancos_com_alias, key=sort_key)
                bancos_sem_alias_sorted = sorted(bancos_sem_alias, key=sort_key)
                bancos_disponiveis = bancos_com_alias_sorted + bancos_sem_alias_sorted
            else:
                bancos_disponiveis = sorted(bancos_todos)

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
                        'Crédito/PL',
                        'Crédito/Captações (%)',
                        'Market Share Carteira',
                        'Lucro Líquido',
                        'ROE An. (%)'
                    ]
                    defaults_variaveis = [
                        'Carteira de Crédito',
                        'Patrimônio Líquido',
                        'Lucro Líquido',
                        'ROE An. (%)',
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
                        key="periodo_ini_serie_historica"
                    )
                    periodo_final = st.selectbox(
                        "período final",
                        periodos_dropdown,
                        index=0,
                        key="periodo_fin_serie_historica"
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
                        if variavel == 'Lucro Líquido':
                            st.markdown("**período lucro líquido**")
                            col_lucro_ini, col_lucro_fim = st.columns(2)
                            with col_lucro_ini:
                                periodo_inicial_lucro = st.selectbox(
                                    "período inicial",
                                    periodos_dropdown,
                                    index=len(periodos_dropdown) - 1,
                                    key="periodo_ini_lucro_liquido"
                                )
                            with col_lucro_fim:
                                periodo_final_lucro = st.selectbox(
                                    "período final",
                                    periodos_dropdown,
                                    index=0,
                                    key="periodo_fin_lucro_liquido"
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
                                periodos_filtrados_lucro if variavel == 'Lucro Líquido' else periodos_filtrados
                            )]
                            df_banco['ano'] = df_banco['Período'].str.split('/').str[1].astype(int)
                            df_banco['trimestre'] = df_banco['Período'].str.split('/').str[0].astype(int)
                            df_banco = df_banco.sort_values(['ano', 'trimestre'])

                            y_values = df_banco[variavel] * format_info['multiplicador']
                            cor_banco = obter_cor_banco(instituicao) or None

                            if variavel == 'Lucro Líquido':
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
                                tickmode='array' if variavel == 'Lucro Líquido' else None,
                                tickvals=periodos_filtrados_lucro if variavel == 'Lucro Líquido' else None,
                                ticktext=periodos_filtrados_lucro if variavel == 'Lucro Líquido' else None,
                                categoryorder='array' if variavel == 'Lucro Líquido' else None,
                                categoryarray=periodos_filtrados_lucro if variavel == 'Lucro Líquido' else None
                            ),
                            yaxis=dict(showgrid=True, gridcolor='#e0e0e0', tickformat=format_info['tickformat'], ticksuffix=format_info['ticksuffix']),
                            font=dict(family='IBM Plex Sans'),
                            barmode='group' if variavel == 'Lucro Líquido' else None
                        )

                        st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})

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

        # Lista de todos os bancos disponíveis com a mesma ordenação de "Análise Individual"
        bancos_todos = df['Instituição'].dropna().unique().tolist()

        if 'dict_aliases' in st.session_state and st.session_state['dict_aliases']:
            # Cria set de aliases (valores do dicionário) - os dados já têm nomes substituídos
            aliases_set = set(st.session_state['dict_aliases'].values())

            bancos_com_alias = []
            bancos_sem_alias = []

            for banco in bancos_todos:
                # Verifica se o banco é um alias (está nos valores do dicionário)
                if banco in aliases_set:
                    bancos_com_alias.append(banco)
                else:
                    bancos_sem_alias.append(banco)

            # Ordenação: letras antes de números, case-insensitive
            def sort_key(nome):
                primeiro_char = nome[0].lower() if nome else 'z'
                if primeiro_char.isdigit():
                    return (1, nome.lower())
                return (0, nome.lower())

            bancos_com_alias_sorted = sorted(bancos_com_alias, key=sort_key)
            bancos_sem_alias_sorted = sorted(bancos_sem_alias, key=sort_key)
            todos_bancos = bancos_com_alias_sorted + bancos_sem_alias_sorted
        else:
            todos_bancos = sorted(bancos_todos)

        # Primeira linha: variáveis dos eixos e tamanho
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            var_x = st.selectbox("eixo x", colunas_numericas, index=colunas_numericas.index('Índice de Basileia') if 'Índice de Basileia' in colunas_numericas else 0)
        with col2:
            var_y = st.selectbox("eixo y", colunas_numericas, index=colunas_numericas.index('ROE An. (%)') if 'ROE An. (%)' in colunas_numericas else 1)
        with col3:
            opcoes_tamanho = ['Tamanho Fixo'] + colunas_numericas
            default_idx = opcoes_tamanho.index('Carteira de Crédito') if 'Carteira de Crédito' in opcoes_tamanho else 1
            var_size = st.selectbox("tamanho", opcoes_tamanho, index=default_idx)
        with col4:
            periodo_scatter = st.selectbox("período", periodos, index=0)

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

        st.plotly_chart(fig_scatter, use_container_width=True)

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
                index=colunas_numericas.index('ROE An. (%)') if 'ROE An. (%)' in colunas_numericas else 1,
                key="var_y_n2"
            )
        with col_p3:
            # Período inicial (mais antigo por padrão)
            idx_inicial = min(1, len(periodos) - 1) if len(periodos) > 1 else 0
            periodo_inicial = st.selectbox(
                "período inicial",
                periodos,
                index=idx_inicial,
                key="periodo_inicial_n2"
            )
        with col_p4:
            # Período subsequente (mais recente por padrão)
            periodo_subseq = st.selectbox(
                "período subsequente",
                periodos,
                index=0,
                key="periodo_subseq_n2"
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

                st.plotly_chart(fig_scatter_n2, use_container_width=True)

                # Legenda explicativa
                st.caption("○ Círculo vazio = período inicial | ● Círculo cheio = período subsequente | → Seta indica direção da movimentação")

    else:
        st.info("carregando dados automaticamente do github...")
        st.markdown("por favor, aguarde alguns segundos e recarregue a página")

elif menu == "Deltas":
    if 'dados_periodos' in st.session_state and st.session_state['dados_periodos']:
        df = get_dados_concatenados()  # OTIMIZAÇÃO: usar cache

        colunas_numericas = [col for col in df.columns if col not in ['Instituição', 'Período'] and df[col].dtype in ['float64', 'int64']]
        periodos_disponiveis = ordenar_periodos(df['Período'].dropna().unique())
        periodos_dropdown = ordenar_periodos(df['Período'].dropna().unique(), reverso=True)

        # Lista de todos os bancos disponíveis
        bancos_todos = df['Instituição'].dropna().unique().tolist()

        if 'dict_aliases' in st.session_state and st.session_state['dict_aliases']:
            aliases_set = set(st.session_state['dict_aliases'].values())
            bancos_com_alias = []
            bancos_sem_alias = []

            for banco in bancos_todos:
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
            todos_bancos = bancos_com_alias_sorted + bancos_sem_alias_sorted
        else:
            todos_bancos = sorted(bancos_todos)

        # ===== LINHA 1: Seleção de variáveis =====
        st.markdown("**variáveis para análise de deltas**")
        variaveis_disponiveis = [
            'Ativo Total',
            'Captações',
            'Patrimônio Líquido',
            'Carteira de Crédito',
            'Crédito/Ativo (%)',
            'Índice de Basileia',
            'Crédito/PL',
            'Crédito/Captações (%)',
            'Market Share Carteira',
            'Lucro Líquido',
            'ROE An. (%)'
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
                key="periodo_inicial_delta"
            )
        with col_p2:
            periodo_subsequente_delta = st.selectbox(
                "período subsequente",
                periodos_dropdown,
                index=0,
                key="periodo_subsequente_delta"
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
                st.plotly_chart(fig_delta, use_container_width=True, config={'displayModeBar': False})

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

                    st.dataframe(df_display, use_container_width=True, hide_index=True)

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

elif menu == "Brincar":
    if 'dados_periodos' in st.session_state and st.session_state['dados_periodos']:
        df = get_dados_concatenados()  # OTIMIZAÇÃO: usar cache

        colunas_numericas = [col for col in df.columns if col not in ['Instituição', 'Período'] and df[col].dtype in ['float64', 'int64']]
        periodos_disponiveis = ordenar_periodos(df['Período'].dropna().unique())
        periodos_dropdown = ordenar_periodos(df['Período'].dropna().unique(), reverso=True)

        # Lista de todos os bancos disponíveis
        bancos_todos = df['Instituição'].dropna().unique().tolist()

        if 'dict_aliases' in st.session_state and st.session_state['dict_aliases']:
            aliases_set = set(st.session_state['dict_aliases'].values())
            bancos_com_alias = []
            bancos_sem_alias = []

            for banco in bancos_todos:
                if banco in aliases_set:
                    bancos_com_alias.append(banco)
                else:
                    bancos_sem_alias.append(banco)

            def sort_key_brincar(nome):
                primeiro_char = nome[0].lower() if nome else 'z'
                if primeiro_char.isdigit():
                    return (1, nome.lower())
                return (0, nome.lower())

            bancos_com_alias_sorted = sorted(bancos_com_alias, key=sort_key_brincar)
            bancos_sem_alias_sorted = sorted(bancos_sem_alias, key=sort_key_brincar)
            todos_bancos = bancos_com_alias_sorted + bancos_sem_alias_sorted
        else:
            todos_bancos = sorted(bancos_todos)

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
            if st.button("adicionar", key="btn_add_step", use_container_width=True):
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
                            key="periodo_scatter_brincar"
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

                        st.plotly_chart(fig_scatter_brincar, use_container_width=True)

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

                            st.dataframe(df_export, use_container_width=True, hide_index=True)

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
                            key="periodo_inicial_brincar"
                        )
                    with col_p2:
                        periodo_subsequente_brincar = st.selectbox(
                            "período subsequente",
                            periodos_dropdown,
                            index=0,
                            key="periodo_subsequente_brincar"
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

                            st.plotly_chart(fig_delta_brincar, use_container_width=True, config={'displayModeBar': False})

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

                                st.dataframe(df_export_delta, use_container_width=True, hide_index=True)

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
                            key="periodo_ranking_brincar"
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

                        st.plotly_chart(fig_ranking, use_container_width=True, config={'displayModeBar': False})

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

                            st.dataframe(df_export_rank, use_container_width=True, hide_index=True)

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

# =====================================================================
# ABA: DADOS - Extração de Taxas de Juros do BCB
# =====================================================================
elif menu == "Dados":
    st.markdown("### taxas de juros - banco central")
    st.caption("extração de dados de taxas de juros por produto e instituição financeira")

    # Inicializa session state para a aba Dados
    if 'dados_taxas_modalidades' not in st.session_state:
        st.session_state['dados_taxas_modalidades'] = None
    if 'dados_taxas_df_amostra' not in st.session_state:
        st.session_state['dados_taxas_df_amostra'] = None
    if 'dados_taxas_resultado' not in st.session_state:
        st.session_state['dados_taxas_resultado'] = None
    if 'dados_taxas_instituicoes_cache' not in st.session_state:
        st.session_state['dados_taxas_instituicoes_cache'] = {}

    # Carrega modalidades disponíveis (com cache)
    if st.session_state['dados_taxas_modalidades'] is None:
        with st.spinner("Carregando produtos disponíveis da API do BCB..."):
            modalidades, df_amostra = buscar_modalidades_disponiveis()
            st.session_state['dados_taxas_modalidades'] = modalidades
            st.session_state['dados_taxas_df_amostra'] = df_amostra

    modalidades = st.session_state['dados_taxas_modalidades']
    df_amostra = st.session_state['dados_taxas_df_amostra']

    if not modalidades:
        st.error("Não foi possível conectar à API do BCB. Tente novamente mais tarde.")
    else:
        st.success(f"{len(modalidades)} produtos disponíveis")

        # === SEÇÃO 1: SELEÇÃO DE PRODUTOS ===
        st.markdown("---")
        st.markdown("#### 1. selecione os produtos")
        st.caption("escolha até 4 produtos para consultar simultaneamente")

        # Formata nomes para exibição
        modalidades_formatadas = [formatar_nome_modalidade(m) for m in modalidades]
        mapa_modalidades = dict(zip(modalidades_formatadas, modalidades))

        produtos_selecionados_formatados = st.multiselect(
            "produtos",
            options=modalidades_formatadas,
            max_selections=4,
            help="selecione de 1 a 4 produtos para consultar"
        )

        # Mapeia de volta para nomes originais
        produtos_selecionados = [mapa_modalidades[p] for p in produtos_selecionados_formatados]

        # === SEÇÃO 2: SELEÇÃO DE INSTITUIÇÕES ===
        if produtos_selecionados:
            st.markdown("---")
            st.markdown("#### 2. selecione as instituições financeiras")

            # Busca instituições para os produtos selecionados (com cache)
            cache_key = tuple(sorted(produtos_selecionados))
            if cache_key not in st.session_state['dados_taxas_instituicoes_cache']:
                with st.spinner("Buscando instituições disponíveis..."):
                    instituicoes = buscar_instituicoes_todas_modalidades(
                        produtos_selecionados,
                        df_amostra
                    )
                    st.session_state['dados_taxas_instituicoes_cache'][cache_key] = instituicoes

            instituicoes_disponiveis = st.session_state['dados_taxas_instituicoes_cache'][cache_key]

            if instituicoes_disponiveis:
                st.caption(f"{len(instituicoes_disponiveis)} instituições encontradas")

                # Opção de selecionar todas
                col_todas, col_select = st.columns([1, 3])

                with col_todas:
                    selecionar_todas = st.checkbox("selecionar todas", value=False)

                with col_select:
                    if selecionar_todas:
                        instituicoes_selecionadas = instituicoes_disponiveis
                        st.info(f"{len(instituicoes_selecionadas)} instituições selecionadas")
                    else:
                        instituicoes_selecionadas = st.multiselect(
                            "instituições",
                            options=instituicoes_disponiveis,
                            help="selecione as instituições financeiras"
                        )
            else:
                st.warning("Nenhuma instituição encontrada para os produtos selecionados")
                instituicoes_selecionadas = []

            # === SEÇÃO 3: SELEÇÃO DE PERÍODO ===
            if instituicoes_selecionadas:
                st.markdown("---")
                st.markdown("#### 3. selecione o período")

                col_inicio, col_fim = st.columns(2)

                with col_inicio:
                    # Data inicial - padrão: 6 meses atrás
                    data_inicial_padrao = datetime.now() - timedelta(days=180)
                    data_inicio = st.date_input(
                        "data inicial",
                        value=data_inicial_padrao,
                        max_value=datetime.now(),
                        format="DD/MM/YYYY"
                    )

                with col_fim:
                    # Data final - padrão: hoje
                    opcao_data_fim = st.radio(
                        "data final",
                        ["mais recente", "selecionar data"],
                        horizontal=True
                    )

                    if opcao_data_fim == "mais recente":
                        data_fim = datetime.now()
                        st.caption(f"usando data mais recente: {data_fim.strftime('%d/%m/%Y')}")
                    else:
                        data_fim = st.date_input(
                            "selecione a data final",
                            value=datetime.now(),
                            max_value=datetime.now(),
                            format="DD/MM/YYYY"
                        )

                # === SEÇÃO 4: EXECUTAR EXTRAÇÃO ===
                st.markdown("---")

                # Resumo da seleção
                st.markdown("#### resumo da seleção")
                col_resumo1, col_resumo2 = st.columns(2)

                with col_resumo1:
                    st.markdown(f"**Produtos:** {len(produtos_selecionados)}")
                    for p in produtos_selecionados_formatados:
                        st.caption(f"• {p}")

                with col_resumo2:
                    st.markdown(f"**Instituições:** {len(instituicoes_selecionadas)}")
                    st.markdown(f"**Período:** {data_inicio.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')}")

                st.markdown("---")

                # Botão de extração
                if st.button("extrair dados", type="primary", use_container_width=True):
                    with st.spinner("Extraindo dados da API do BCB..."):
                        placeholder_progresso = st.empty()

                        def callback_progresso(msg):
                            placeholder_progresso.caption(msg)

                        df_resultado = extrair_taxas_juros(
                            modalidades=produtos_selecionados,
                            data_inicio=data_inicio.strftime('%Y-%m-%d'),
                            data_fim=data_fim.strftime('%Y-%m-%d') if isinstance(data_fim, datetime) else str(data_fim),
                            instituicoes=instituicoes_selecionadas,
                            callback_progresso=callback_progresso
                        )

                        placeholder_progresso.empty()

                        if not df_resultado.empty:
                            st.session_state['dados_taxas_resultado'] = df_resultado
                            st.success(f"Extraídos {len(df_resultado)} registros com sucesso!")
                            st.rerun()
                        else:
                            st.error("Nenhum dado encontrado para os critérios selecionados")

                # === SEÇÃO 5: EXIBIÇÃO E EXPORTAÇÃO DOS DADOS ===
                if st.session_state['dados_taxas_resultado'] is not None:
                    df_resultado = st.session_state['dados_taxas_resultado']

                    st.markdown("---")
                    st.markdown("#### dados extraídos")

                    # Estatísticas
                    stats = calcular_estatisticas(df_resultado)
                    col_stat1, col_stat2, col_stat3, col_stat4 = st.columns(4)

                    with col_stat1:
                        st.metric("Registros", f"{stats.get('total_registros', 0):,}")
                    with col_stat2:
                        st.metric("Instituições", f"{stats.get('n_instituicoes', 0)}")
                    with col_stat3:
                        st.metric("Períodos", f"{stats.get('n_periodos', 0)}")
                    with col_stat4:
                        if stats.get('taxa_mensal_media'):
                            st.metric("Taxa Média (a.m.)", f"{stats['taxa_mensal_media']:.2f}%")

                    # Opções de visualização
                    st.markdown("---")
                    tipo_visualizacao = st.radio(
                        "visualização",
                        ["tabela completa", "tabela pivotada (instituições nas colunas)"],
                        horizontal=True
                    )

                    if tipo_visualizacao == "tabela completa":
                        # Formata datas para exibição
                        df_exibir = df_resultado.copy()
                        df_exibir['data_inicio'] = df_exibir['data_inicio'].dt.strftime('%d/%m/%Y')
                        df_exibir['data_fim'] = df_exibir['data_fim'].dt.strftime('%d/%m/%Y')

                        # Renomeia colunas para exibição
                        df_exibir = df_exibir.rename(columns={
                            'data_inicio': 'Início Período',
                            'data_fim': 'Fim Período',
                            'modalidade': 'Produto',
                            'instituicao': 'Instituição Financeira',
                            'posicao': 'Posição',
                            'taxa_mensal': 'Taxa % a.m.',
                            'taxa_anual': 'Taxa % a.a.',
                            'cnpj8': 'CNPJ'
                        })

                        st.dataframe(df_exibir, use_container_width=True, hide_index=True)

                        # Exportação
                        st.markdown("---")
                        st.markdown("#### exportar dados")

                        col_excel, col_csv = st.columns(2)

                        with col_excel:
                            buffer_excel = BytesIO()
                            with pd.ExcelWriter(buffer_excel, engine='xlsxwriter') as writer:
                                df_exibir.to_excel(writer, index=False, sheet_name='taxas_juros')
                            buffer_excel.seek(0)

                            st.download_button(
                                label="Exportar Excel",
                                data=buffer_excel,
                                file_name=f"taxas_juros_bcb_{datetime.now().strftime('%Y%m%d')}.xlsx",
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                key="export_excel_taxas"
                            )

                        with col_csv:
                            csv_data = df_exibir.to_csv(index=False)
                            st.download_button(
                                label="Exportar CSV",
                                data=csv_data,
                                file_name=f"taxas_juros_bcb_{datetime.now().strftime('%Y%m%d')}.csv",
                                mime="text/csv",
                                key="export_csv_taxas"
                            )

                    else:
                        # Tabela pivotada
                        opcao_taxa = st.radio(
                            "tipo de taxa",
                            ["mensal (% a.m.)", "anual (% a.a.)"],
                            horizontal=True
                        )

                        valor_col = 'taxa_mensal' if 'mensal' in opcao_taxa else 'taxa_anual'
                        df_pivot = criar_tabela_pivot(df_resultado, valor=valor_col)

                        if not df_pivot.empty:
                            # Formata data para exibição
                            df_pivot_exibir = df_pivot.copy()
                            df_pivot_exibir['data'] = pd.to_datetime(df_pivot_exibir['data']).dt.strftime('%d/%m/%Y')

                            st.dataframe(df_pivot_exibir, use_container_width=True, hide_index=True)

                            # Exportação
                            st.markdown("---")
                            st.markdown("#### exportar dados")

                            col_excel, col_csv = st.columns(2)

                            with col_excel:
                                buffer_excel = BytesIO()
                                with pd.ExcelWriter(buffer_excel, engine='xlsxwriter') as writer:
                                    df_pivot_exibir.to_excel(writer, index=False, sheet_name='taxas_pivot')
                                buffer_excel.seek(0)

                                st.download_button(
                                    label="Exportar Excel",
                                    data=buffer_excel,
                                    file_name=f"taxas_juros_pivot_{datetime.now().strftime('%Y%m%d')}.xlsx",
                                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                    key="export_excel_taxas_pivot"
                                )

                            with col_csv:
                                csv_data = df_pivot_exibir.to_csv(index=False)
                                st.download_button(
                                    label="Exportar CSV",
                                    data=csv_data,
                                    file_name=f"taxas_juros_pivot_{datetime.now().strftime('%Y%m%d')}.csv",
                                    mime="text/csv",
                                    key="export_csv_taxas_pivot"
                                )
                        else:
                            st.warning("Não foi possível criar tabela pivotada")

                    # Botão para limpar dados
                    st.markdown("---")
                    if st.button("limpar dados e fazer nova consulta", use_container_width=True):
                        st.session_state['dados_taxas_resultado'] = None
                        st.rerun()
