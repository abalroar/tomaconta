import streamlit as st
import pandas as pd
import pickle
import os
import requests
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path
from datetime import datetime
from utils.ifdata_extractor import gerar_periodos, processar_todos_periodos
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
    'Carteira/Ativo (%)',
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

def salvar_cache(dados_periodos, periodo_info):
    """Salva o cache localmente e retorna informações do arquivo salvo."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(CACHE_FILE, 'wb') as f:
        pickle.dump(dados_periodos, f)
    with open(CACHE_INFO, 'w') as f:
        f.write(f"Última extração: {datetime.now().strftime('%d/%m/%Y %H:%M')}\n")
        f.write(f"Períodos: {periodo_info}\n")
        f.write(f"Total de períodos: {len(dados_periodos)}\n")
    return get_cache_info_detalhado()

def ordenar_periodos_cache(periodos):
    return sorted(periodos, key=lambda p: (p[:4], p[4:6]))

def formatar_periodo_chave(periodo):
    if isinstance(periodo, str) and len(periodo) >= 6:
        return f"{periodo[4:6]}/{periodo[:4]}"
    return str(periodo)

def mesclar_cache_existente(dados_existentes, dados_novos):
    if not dados_existentes:
        return {
            "modo": "overwrite",
            "dados": dados_novos,
            "periodos_antes": [],
            "periodos_adicionados": list(dados_novos.keys()),
            "periodos_atualizados": [],
        }

    periodos_antes = set(dados_existentes.keys())
    periodos_novos = set(dados_novos.keys())
    periodos_adicionados = sorted(periodos_novos - periodos_antes)
    periodos_atualizados = sorted(periodos_novos & periodos_antes)

    dados_mesclados = dict(dados_existentes)
    dados_mesclados.update(dados_novos)

    return {
        "modo": "merge",
        "dados": dados_mesclados,
        "periodos_antes": sorted(periodos_antes),
        "periodos_adicionados": periodos_adicionados,
        "periodos_atualizados": periodos_atualizados,
    }

def carregar_cache():
    """Carrega o cache do arquivo local."""
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, 'rb') as f:
            return pickle.load(f)
    return None

def ler_info_cache():
    if os.path.exists(CACHE_INFO):
        with open(CACHE_INFO, 'r') as f:
            return f.read()
    return None

def forcar_recarregar_cache():
    """Força o recarregamento do cache do disco, ignorando session_state."""
    dados = carregar_cache()
    if dados:
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

def carregar_aliases():
    if os.path.exists(ALIASES_PATH):
        return pd.read_excel(ALIASES_PATH)
    return None

# FIX PROBLEMA 3: Normalização de nomes de instituições
def normalizar_nome_instituicao(nome):
    """Normaliza nome removendo espaços extras e convertendo para uppercase"""
    if pd.isna(nome):
        return ""
    return " ".join(str(nome).split()).upper()



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
def carregar_cores_aliases_local(df_aliases):
    """Lê a cor do Aliases.xlsx e cria um dicionário de cores.

    Importante: mapeia tanto o valor da coluna 'Instituição' (nome original vindo do BCB)
    quanto o valor da coluna 'Alias Banco' (nome amigável que aparece no app),
    para que a cor seja aplicada em qualquer tela.
    """
    dict_cores = {}
    if df_aliases is None or df_aliases.empty:
        return dict_cores

    colunas_possiveis = ['Código Cor', 'Cor', 'Color', 'Hex', 'Código']
    coluna_cor = None
    for col in colunas_possiveis:
        if col in df_aliases.columns:
            coluna_cor = col
            break

    if coluna_cor is None:
        return dict_cores

    for _, row in df_aliases.iterrows():
        instituicao = row.get('Instituição')
        alias = row.get('Alias Banco')
        cor_valor = row.get(coluna_cor)

        cor_str = normalizar_codigo_cor(cor_valor)
        if not cor_str:
            continue

        if pd.notna(instituicao):
            dict_cores[normalizar_nome_instituicao(instituicao)] = cor_str
            # Também aceita busca pelo 'Alias Banco' (útil quando a coluna Instituição já vem renomeada)
            alias_banco = row.get('Alias Banco')
            if pd.notna(alias_banco):
                dict_cores[normalizar_nome_instituicao(alias_banco)] = cor_str

        # Também mapeia pelo alias (é o que aparece na UI)
        if pd.notna(alias):
            dict_cores[normalizar_nome_instituicao(alias)] = cor_str

    return dict_cores

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
    periodos_disponiveis = sorted(df_sorted['Período'].unique(), key=lambda x: (x.split('/')[1], x.split('/')[0]))
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

if 'df_aliases' not in st.session_state:
    df_aliases = carregar_aliases()
    if df_aliases is not None:
        st.session_state['df_aliases'] = df_aliases
        st.session_state['dict_aliases'] = dict(zip(df_aliases['Instituição'], df_aliases['Alias Banco']))
        st.session_state['dict_cores_personalizadas'] = carregar_cores_aliases_local(df_aliases)
        st.session_state['colunas_classificacao'] = [c for c in df_aliases.columns if c not in ['Instituição','Alias Banco','Cor','Código Cor']]

if 'dados_periodos' not in st.session_state:
    sucesso, fonte = baixar_cache_inicial()
    dados_cache = carregar_cache()
    if dados_cache:
        st.session_state['dados_periodos'] = dados_cache
        if 'cache_fonte' not in st.session_state:
            st.session_state['cache_fonte'] = fonte

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
    if os.path.exists(LOGO_PATH):
        logo_image = PILImage.open(LOGO_PATH)
        target_width = 200
        if logo_image.width < target_width:
            ratio = target_width / logo_image.width
            new_height = int(logo_image.height * ratio)
            logo_image = logo_image.resize((target_width, new_height), PILImage.LANCZOS)
        buffer = BytesIO()
        logo_image.save(buffer, format="PNG", optimize=True)
        logo_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
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
    ["Sobre", "Resumo", "Análise Individual", "Série Histórica", "Scatter Plot"],
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

                    def update(i, total, p):
                        progress_bar.progress((i+1)/total)
                        status.text(f"{p[4:6]}/{p[:4]} ({i+1}/{total})")

                    dados = processar_todos_periodos(periodos, st.session_state['dict_aliases'], update)

                    if not dados:
                        progress_bar.empty()
                        status.empty()
                        st.error("falha ao extrair dados: nenhum período retornou dados válidos.")
                    else:
                        dados_existentes = carregar_cache() or {}
                        resultado_merge = mesclar_cache_existente(dados_existentes, dados)
                        dados_finais = resultado_merge["dados"]

                        periodos_finais = ordenar_periodos_cache(dados_finais.keys())
                        periodo_info = (
                            f"{formatar_periodo_chave(periodos_finais[0])} até {formatar_periodo_chave(periodos_finais[-1])}"
                            if periodos_finais
                            else "N/A"
                        )
                        cache_salvo = salvar_cache(dados_finais, periodo_info)

                        # Atualizar session_state com os novos dados
                        st.session_state['dados_periodos'] = dados_finais
                        st.session_state['cache_fonte'] = 'extração local'

                        progress_bar.empty()
                        status.empty()
                        if resultado_merge["modo"] == "merge":
                            st.success("merge incremental aplicado no cache.")
                        else:
                            st.success("cache salvo com overwrite total (sem cache anterior).")
                        st.info(
                            f"períodos antes: {len(resultado_merge['periodos_antes'])} | "
                            f"adicionados: {len(resultado_merge['periodos_adicionados'])} | "
                            f"atualizados: {len(resultado_merge['periodos_atualizados'])}"
                        )
                        st.caption(
                            "períodos finais: "
                            + ", ".join(formatar_periodo_chave(p) for p in periodos_finais)
                        )
                        st.success(f"{len(dados)} períodos extraídos e salvos!")
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
        df = pd.concat(st.session_state['dados_periodos'].values(), ignore_index=True)

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
            periodos = sorted(df['Período'].dropna().unique(), key=lambda x: (x.split('/')[1], x.split('/')[0]))

            componentes_indicador = {
                'Patrimônio de Referência': [
                    'RWA Crédito',
                    'RWA Contraparte',
                    'RWA Operacional',
                    'RWA Mercado',
                    'RWA Outros',
                ]
            }

            col_periodo, col_indicador, col_escala, col_tipo = st.columns([1.2, 2, 1.1, 1.3])
            with col_periodo:
                periodo_resumo = st.selectbox(
                    "período (trimestre)",
                    periodos,
                    index=len(periodos) - 1,
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
                media_display = df_selecionado['valor_display'].mean()

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
                        media_grupo_raw = df_componentes['total'].mean()
                        df_export_base = df_componentes.copy()
                        df_export_base['Período'] = periodo_resumo
                        df_export_base['Indicador'] = indicador_label
                        df_export_base['Valor'] = df_export_base['total']
                        df_export_base['Média do Grupo'] = media_grupo_raw
                        df_export_base['Diferença vs Média'] = df_export_base['Valor'] - media_grupo_raw
                        df_export_base = df_export_base[[
                            'Período',
                            'Instituição',
                            'Indicador',
                            'Valor',
                            'ranking',
                            'Média do Grupo',
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
                            name='Média',
                            line=dict(color='#1f77b4', dash='dash')
                        ))
                    else:
                        fig_resumo.add_trace(go.Scatter(
                            x=df_selecionado['Instituição'],
                            y=[media_display] * len(df_selecionado),
                            mode='lines',
                            name='Média',
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

                    media_grupo_raw = df_selecionado[indicador_col].mean()
                    df_export = df_selecionado.copy()
                    df_export['Período'] = periodo_resumo
                    df_export['Indicador'] = indicador_label
                    df_export['Valor'] = df_export[indicador_col]
                    df_export['Média do Grupo'] = media_grupo_raw
                    df_export['Diferença vs Média'] = df_export['Valor'] - media_grupo_raw
                    df_export = df_export[[
                        'Período',
                        'Instituição',
                        'Indicador',
                        'Valor',
                        'ranking',
                        'Média do Grupo',
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

elif menu == "Análise Individual":
    if 'dados_periodos' in st.session_state and st.session_state['dados_periodos']:
        df = pd.concat(st.session_state['dados_periodos'].values(), ignore_index=True)

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

                    periodos_disponiveis = sorted(df_banco['Período'].unique(), key=lambda x: (x.split('/')[1], x.split('/')[0]))

                    # Seletores de período
                    col_p1, col_p2, col_p3 = st.columns([1, 1, 2])
                    with col_p1:
                        periodo_inicial = st.selectbox("período inicial", periodos_disponiveis, index=0, key="periodo_ini_individual")
                    with col_p2:
                        idx_final = len(periodos_disponiveis) - 1
                        periodo_final = st.selectbox("período final", periodos_disponiveis, index=idx_final, key="periodo_fin_individual")
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
                        'Carteira/Ativo (%)',
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
        df = pd.concat(st.session_state['dados_periodos'].values(), ignore_index=True)

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
                        'Carteira/Ativo (%)',
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

                periodos_disponiveis = sorted(
                    df['Período'].dropna().unique(),
                    key=lambda x: (x.split('/')[1], x.split('/')[0])
                )
                with col_periodo:
                    periodo_inicial = st.selectbox(
                        "período inicial",
                        periodos_disponiveis,
                        index=0,
                        key="periodo_ini_serie_historica"
                    )
                    periodo_final = st.selectbox(
                        "período final",
                        periodos_disponiveis,
                        index=len(periodos_disponiveis) - 1,
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
                                    periodos_disponiveis,
                                    index=0,
                                    key="periodo_ini_lucro_liquido"
                                )
                            with col_lucro_fim:
                                periodo_final_lucro = st.selectbox(
                                    "período final",
                                    periodos_disponiveis,
                                    index=len(periodos_disponiveis) - 1,
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
        df = pd.concat(st.session_state['dados_periodos'].values(), ignore_index=True)

        colunas_numericas = [col for col in df.columns if col not in ['Instituição', 'Período'] and df[col].dtype in ['float64', 'int64']]
        periodos = sorted(df['Período'].unique(), key=lambda x: (x.split('/')[1], x.split('/')[0]))

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
            periodo_scatter = st.selectbox("período", periodos, index=len(periodos)-1)

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

        # Título dinâmico
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
    else:
        st.info("carregando dados automaticamente do github...")
        st.markdown("por favor, aguarde alguns segundos e recarregue a página")
