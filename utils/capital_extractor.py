"""
capital_extractor.py - Extração de Dados de Capital (Relatório Tipo 5)

Este módulo é COMPLETAMENTE ISOLADO do ifdata_extractor.py e do fluxo principal.
Usa cache próprio (capital_cache.pkl) e não interfere nas funcionalidades existentes.

Fonte: API Olinda IFData, Tipo de Relatório 5 ("Informações de Capital")
"""

import requests
import pandas as pd
import numpy as np
import time
import logging
import pickle
import os
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Callable, Tuple

# =============================================================================
# CONFIGURAÇÃO DE LOGGING (ISOLADO)
# =============================================================================
logger = logging.getLogger("capital_extractor")
logger.setLevel(logging.DEBUG)

# Evitar duplicação de handlers
if not logger.handlers:
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_format = logging.Formatter('[CAPITAL] %(levelname)s: %(message)s')
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)

# =============================================================================
# CONFIGURAÇÕES E CONSTANTES (ISOLADAS DO FLUXO PRINCIPAL)
# =============================================================================
BASE_URL = "https://olinda.bcb.gov.br/olinda/servico/IFDATA/versao/v1/odata"

# Diretório de dados
APP_DIR = Path(__file__).parent.parent.resolve()
DATA_DIR = APP_DIR / "data"

# Cache SEPARADO para dados de capital
CAPITAL_CACHE_FILE = DATA_DIR / "capital_cache.pkl"
CAPITAL_CACHE_INFO = DATA_DIR / "capital_cache_info.txt"

# Mapeamento de campos: Nome Original -> Nome Exibido
# NOTA: Os nomes na API têm quebras de linha (\n) que precisam ser normalizados
# Mantemos os nomes originais em uma coluna separada para auditoria
CAMPOS_CAPITAL = {
    # Nomes exatos da API (com quebras de linha normalizadas para espaço)
    "Capital Principal para Comparação com RWA (a)": "Capital Principal",
    "Capital Complementar (b)": "Capital Complementar",
    "Patrimônio de Referência Nível I para Comparação com RWA (c) = (a) + (b)": "Patrimônio de Referência",
    "Capital Nível II (d)": "Capital Nível II",
    "RWA para Risco de Crédito (f)": "RWA Crédito",
    "RWA para Risco de Mercado (g) = (g1) + (g2) + (g3) + (g4) + (g5) + (g6)": "RWA Mercado",
    "RWA para Risco de Mercado (g) = (g1) + (g2) + (g3) + (g4)": "RWA Mercado",
    "RWA para Risco Operacional (h)": "RWA Operacional",
    "Ativos Ponderados pelo Risco (RWA) (j) = (f) + (g) + (h) + (i)": "RWA Total",
    "Ativos Ponderados pelo Risco (RWA) (i) = (f) + (g) + (h)": "RWA Total",
    "Exposição Total (k)": "Exposição Total",
    "Índice de Capital Principal (l) = (a) / (j)": "Índice de Capital Principal",
    "Índice de Capital Principal (k) = (a) / (i)": "Índice de Capital Principal",
    "Índice de Capital Nível I (m) = (c) / (j)": "Índice de Capital Nível I",
    "Índice de Basileia (n) = (e) / (j)": "Índice de Basileia",
    "Índice de Basileia (m) = (e) / (i)": "Índice de Basileia",
    "Adicional de Capital Principal": "Adicional de Capital Principal",
    "IRRBB": "IRRBB",
    "Razão de Alavancagem (o) = (c) / (k)": "Razão de Alavancagem",
    "Índice de Imobilização (p)": "Índice de Imobilização",
}

# Lista de colunas originais para extração (normalizadas)
# Criamos uma versão normalizada para comparação com os dados da API
COLUNAS_CAPITAL_ORIGINAIS = list(CAMPOS_CAPITAL.keys())

# Mapeamento normalizado: nome_normalizado -> nome_exibido
# Usado para match com os nomes da API após normalização
CAMPOS_CAPITAL_NORMALIZADO = {
    " ".join(k.split()): v for k, v in CAMPOS_CAPITAL.items()
}


# =============================================================================
# FUNÇÕES HTTP COM RETRY/BACKOFF (ISOLADAS)
# =============================================================================
def _fetch_json_capital(url: str, timeout: int = 120, retries: int = 3, backoff: float = 2.0) -> Optional[dict]:
    """Faz requisição HTTP com retry e backoff exponencial.

    Esta função é isolada do ifdata_extractor para evitar dependências.
    """
    last_error = None

    for attempt in range(retries + 1):
        try:
            logger.debug(f"Tentativa {attempt + 1}/{retries + 1}: {url[:100]}...")
            response = requests.get(url, timeout=timeout)

            # Rate limit (429) - esperar mais tempo
            if response.status_code == 429:
                wait_time = backoff * (2 ** attempt) * 2
                logger.warning(f"Rate limit (429). Aguardando {wait_time:.1f}s...")
                time.sleep(wait_time)
                continue

            # Erros de servidor (5xx) - retry com backoff
            if response.status_code >= 500:
                wait_time = backoff * (2 ** attempt)
                logger.warning(f"Erro servidor ({response.status_code}). Aguardando {wait_time:.1f}s...")
                time.sleep(wait_time)
                continue

            response.raise_for_status()
            data = response.json()

            record_count = len(data.get("value", [])) if isinstance(data, dict) else 0
            logger.debug(f"Sucesso: {record_count} registros")

            return data

        except requests.Timeout as e:
            last_error = e
            wait_time = backoff * (2 ** attempt)
            logger.warning(f"Timeout. Tentativa {attempt + 1}/{retries + 1}. Aguardando {wait_time:.1f}s...")
            time.sleep(wait_time)

        except requests.RequestException as e:
            last_error = e
            logger.error(f"Erro HTTP: {e}")
            if attempt >= retries:
                raise
            wait_time = backoff * (2 ** attempt)
            logger.warning(f"Erro: {e}. Aguardando {wait_time:.1f}s...")
            time.sleep(wait_time)

        except ValueError as e:
            # JSON decode error
            last_error = e
            logger.error(f"Erro ao decodificar JSON: {e}")
            if attempt >= retries:
                raise
            time.sleep(backoff * (attempt + 1))

    if last_error:
        raise last_error
    return None


# =============================================================================
# FUNÇÕES DE EXTRAÇÃO DE DADOS DE CAPITAL
# =============================================================================
def extrair_cadastro_capital(ano_mes: str) -> pd.DataFrame:
    """Extrai cadastro de instituições para obter nomes.

    Usa o endpoint IfDataCadastro para mapear CodInst -> NomeInstituicao.
    """
    url = f"{BASE_URL}/IfDataCadastro(AnoMes={int(ano_mes)})?$format=json&$top=5000"

    logger.info(f"Extraindo cadastro para período {ano_mes}")

    try:
        data = _fetch_json_capital(url, timeout=60, retries=3, backoff=2.0)
        df = pd.DataFrame((data or {}).get("value", []))

        if df.empty:
            logger.warning(f"Cadastro vazio para período {ano_mes}")
        else:
            logger.info(f"Cadastro {ano_mes}: {len(df)} registros")

        return df

    except requests.RequestException as e:
        logger.error(f"Falha ao extrair cadastro {ano_mes}: {e}")
        return pd.DataFrame()


def extrair_valores_capital(ano_mes: str) -> pd.DataFrame:
    """Extrai valores de capital das instituições (Relatório Tipo 5).

    Endpoint: IfDataValores com Relatorio='5' (Informações de Capital)
    """
    url = (
        f"{BASE_URL}/IfDataValores("
        f"AnoMes={int(ano_mes)},"
        f"TipoInstituicao=1,"
        f"Relatorio='5'"
        f")?$format=json&$top=200000"
    )

    logger.info(f"Extraindo valores de capital para período {ano_mes}")

    try:
        data = _fetch_json_capital(url, timeout=120, retries=3, backoff=2.0)
        df = pd.DataFrame((data or {}).get("value", []))

        if df.empty:
            logger.warning(f"Valores de capital vazios para período {ano_mes}")
        else:
            n_instituicoes = df["CodInst"].nunique() if "CodInst" in df.columns else 0
            logger.info(f"Valores capital {ano_mes}: {len(df)} registros, {n_instituicoes} instituições")

        return df

    except requests.RequestException as e:
        logger.error(f"Falha ao extrair valores de capital {ano_mes}: {e}")
        return pd.DataFrame()


def normalizar_nome_coluna(valor: str) -> str:
    """Normaliza nome de coluna removendo espaços extras."""
    if not isinstance(valor, str):
        return valor
    return " ".join(valor.split())


def obter_coluna_nome_instituicao(df: pd.DataFrame) -> Optional[str]:
    """Encontra a coluna que contém o nome da instituição no DataFrame."""
    candidatos = {
        "NomeInstituicao",
        "NomeInstituição",
        "Nome Instituicao",
        "Nome Instituição",
        "Nome da Instituicao",
        "Nome da Instituição",
    }
    for coluna in df.columns:
        if coluna in candidatos:
            return coluna
        if normalizar_nome_coluna(str(coluna)) in candidatos:
            return coluna
    return None


def processar_periodo_capital(ano_mes: str, dict_aliases: dict = None) -> Optional[pd.DataFrame]:
    """Processa dados de capital de um período específico.

    Esta função:
    1. Extrai cadastro (para nomes) e valores de capital (Relatório 5)
    2. Pivota os dados por instituição
    3. Renomeia as colunas conforme o mapeamento CAMPOS_CAPITAL
    4. Mantém coluna com nome original para auditoria
    5. Aplica aliases se fornecido

    Args:
        ano_mes: Período no formato YYYYMM (ex: "202412")
        dict_aliases: Dicionário opcional de aliases para nomes de instituições

    Returns:
        DataFrame com dados de capital ou None se falhar
    """
    logger.info(f"Processando dados de capital para período {ano_mes}")

    # 1. Extrair dados
    df_cad = extrair_cadastro_capital(ano_mes)
    df_valores = extrair_valores_capital(ano_mes)

    if df_valores.empty:
        logger.warning(f"Sem valores de capital para período {ano_mes}")
        return None

    # Normalizar nomes de colunas (remove quebras de linha e espaços extras)
    if "NomeColuna" in df_valores.columns:
        df_valores["NomeColuna"] = df_valores["NomeColuna"].map(normalizar_nome_coluna)

    # 2. Filtrar apenas colunas de capital desejadas
    # Usar o mapeamento normalizado para comparação
    colunas_desejadas_normalizadas = set(CAMPOS_CAPITAL_NORMALIZADO.keys())
    df_filt = df_valores[df_valores["NomeColuna"].isin(colunas_desejadas_normalizadas)].copy()

    if df_filt.empty:
        logger.warning(f"Nenhuma coluna de capital encontrada para {ano_mes}")
        # Log das colunas disponíveis para debug
        if "NomeColuna" in df_valores.columns:
            colunas_disponiveis = df_valores["NomeColuna"].unique().tolist()
            logger.info(f"Colunas disponíveis ({len(colunas_disponiveis)}): {colunas_disponiveis[:10]}...")
        return None

    logger.info(f"Colunas de capital encontradas: {df_filt['NomeColuna'].nunique()}")

    # 3. Pivotar por instituição
    df_pivot = df_filt.pivot_table(
        index="CodInst",
        columns="NomeColuna",
        values="Saldo",
        aggfunc="sum",
    ).reset_index()
    df_pivot.columns.name = None

    # 4. Preparar mapeamento de nomes de instituições
    mapa_nomes = {}
    fonte_nomes = "nenhuma"

    if not df_cad.empty:
        coluna_nome = obter_coluna_nome_instituicao(df_cad)
        logger.debug(f"Cadastro {ano_mes}: {len(df_cad)} registros, coluna nome: {coluna_nome}")
        logger.debug(f"Cadastro colunas disponíveis: {list(df_cad.columns)}")

        if coluna_nome and "CodInst" in df_cad.columns:
            for _, row in df_cad.iterrows():
                cod = row.get("CodInst")
                nome = row.get(coluna_nome)
                if pd.notna(cod) and pd.notna(nome):
                    mapa_nomes[cod] = nome
            fonte_nomes = "cadastro"
            logger.info(f"Mapa de nomes populado do cadastro: {len(mapa_nomes)} instituições")
        else:
            logger.warning(f"Cadastro {ano_mes}: coluna nome não encontrada ou sem CodInst")
    else:
        logger.warning(f"Cadastro {ano_mes} vazio - tentando fallback em df_valores")

    # Tentar obter nomes do próprio df_valores se cadastro falhou
    if not mapa_nomes:
        coluna_nome_valores = obter_coluna_nome_instituicao(df_valores)
        logger.debug(f"Valores {ano_mes}: coluna nome: {coluna_nome_valores}")

        if coluna_nome_valores and "CodInst" in df_valores.columns:
            for _, row in df_valores.drop_duplicates(subset=["CodInst"]).iterrows():
                cod = row.get("CodInst")
                nome = row.get(coluna_nome_valores)
                if pd.notna(cod) and pd.notna(nome):
                    mapa_nomes[cod] = nome
            fonte_nomes = "valores"
            logger.info(f"Mapa de nomes populado de df_valores: {len(mapa_nomes)} instituições")
        else:
            logger.error(f"FALHA: Não foi possível obter nomes para período {ano_mes}")

    # 5. Adicionar nome da instituição
    df_pivot["Instituição"] = df_pivot["CodInst"].map(mapa_nomes)

    # Contar quantos nomes foram resolvidos vs faltantes
    nomes_resolvidos = df_pivot["Instituição"].notna().sum()
    nomes_faltantes = df_pivot["Instituição"].isna().sum()

    if nomes_faltantes > 0:
        logger.warning(f"Período {ano_mes}: {nomes_faltantes} instituições sem nome (fonte: {fonte_nomes})")
        # Listar códigos sem nome para debug
        codigos_sem_nome = df_pivot[df_pivot["Instituição"].isna()]["CodInst"].tolist()[:10]
        logger.debug(f"Exemplos de códigos sem nome: {codigos_sem_nome}")

    # Preencher nomes faltantes com placeholder
    df_pivot["Instituição"] = df_pivot.apply(
        lambda row: row["Instituição"] if pd.notna(row["Instituição"]) else f"[IF {row['CodInst']}]",
        axis=1
    )

    # 6. Criar DataFrame de saída com colunas renomeadas
    # Manter uma estrutura que preserve os nomes originais para auditoria
    df_out = pd.DataFrame()
    df_out["Instituição"] = df_pivot["Instituição"]
    df_out["CodInst"] = df_pivot["CodInst"]

    # Adicionar colunas com nomes exibidos
    # Usar mapeamento normalizado porque as colunas do pivot estão normalizadas
    for col_normalizada, col_exibido in CAMPOS_CAPITAL_NORMALIZADO.items():
        if col_normalizada in df_pivot.columns:
            df_out[col_exibido] = df_pivot[col_normalizada]

    # 7. Preservar nome oficial da fonte; alias foi removido do pipeline.

    # 8. Adicionar metadados
    df_out["Período"] = f"{ano_mes[4:6]}/{ano_mes[:4]}"

    # 9. Ordenar por RWA Total (se disponível) ou alfabeticamente
    if "RWA Total" in df_out.columns:
        df_out = df_out.sort_values("RWA Total", ascending=False, na_position="last")
    else:
        df_out = df_out.sort_values("Instituição")

    # Remover linhas sem dados numéricos
    colunas_numericas = [c for c in CAMPOS_CAPITAL.values() if c in df_out.columns]
    if colunas_numericas:
        df_out = df_out.dropna(subset=colunas_numericas, how="all")

    logger.info(f"Período {ano_mes} concluído: {len(df_out)} instituições com dados de capital")

    return df_out


# =============================================================================
# FUNÇÕES DE GERAÇÃO DE PERÍODOS (ISOLADA)
# =============================================================================
def gerar_periodos_capital(ano_inicial: int, mes_inicial: str,
                           ano_final: int, mes_final: str) -> List[str]:
    """Gera lista de períodos trimestrais entre datas especificadas.

    Função isolada para evitar dependência do ifdata_extractor.
    """
    periodos = []
    ano_atual = ano_inicial
    mes_atual = mes_inicial

    while True:
        periodo = f"{ano_atual}{mes_atual}"
        periodos.append(periodo)

        if ano_atual == ano_final and mes_atual == mes_final:
            break

        if mes_atual == '03':
            mes_atual = '06'
        elif mes_atual == '06':
            mes_atual = '09'
        elif mes_atual == '09':
            mes_atual = '12'
        elif mes_atual == '12':
            mes_atual = '03'
            ano_atual += 1

    return periodos


# =============================================================================
# PROCESSAMENTO EM LOTE COM SALVAMENTO PROGRESSIVO
# =============================================================================
def processar_todos_periodos_capital(
    periodos: List[str],
    dict_aliases: dict = None,
    progress_callback: Callable[[int, int, str], None] = None,
    save_callback: Callable[[Dict[str, pd.DataFrame], str], None] = None,
    save_interval: int = 5
) -> Dict[str, pd.DataFrame]:
    """Processa múltiplos períodos de dados de capital.

    Args:
        periodos: Lista de períodos no formato 'YYYYMM'
        dict_aliases: Dicionário opcional de aliases
        progress_callback: Função (i, total, periodo) chamada a cada período
        save_callback: Função (dados, info) para salvamento incremental
        save_interval: Intervalo de períodos para salvamento progressivo

    Returns:
        Dicionário {periodo: DataFrame} com dados de capital
    """
    logger.info(f"Iniciando processamento de {len(periodos)} períodos de capital")

    dados_periodos = {}
    periodos_desde_ultimo_save = 0

    for i, per in enumerate(periodos):
        if progress_callback:
            progress_callback(i, len(periodos), per)

        try:
            df_per = processar_periodo_capital(per, dict_aliases)
            if df_per is not None and not df_per.empty:
                dados_periodos[per] = df_per
                periodos_desde_ultimo_save += 1

                # Salvamento progressivo
                if save_callback and periodos_desde_ultimo_save >= save_interval:
                    try:
                        periodo_info = f"salvamento progressivo capital até {per[4:6]}/{per[:4]}"
                        save_callback(dados_periodos, periodo_info)
                        periodos_desde_ultimo_save = 0
                        logger.info(f"Salvamento progressivo: {len(dados_periodos)} períodos de capital salvos")
                    except Exception as save_error:
                        logger.warning(f"Erro no salvamento progressivo: {save_error}")

            # Rate limiting
            time.sleep(1.5)

        except Exception as e:
            logger.error(f"Erro no período {per}: {e}")

            # Tentar salvar o que temos em caso de erro
            if save_callback and dados_periodos:
                try:
                    periodo_info = f"salvamento de emergência capital após erro em {per}"
                    save_callback(dados_periodos, periodo_info)
                    logger.info(f"Salvamento de emergência: {len(dados_periodos)} períodos salvos")
                except Exception as save_error:
                    logger.warning(f"Erro no salvamento de emergência: {save_error}")

    # Salvamento final
    if save_callback and dados_periodos and periodos_desde_ultimo_save > 0:
        try:
            periodo_info = f"capital {periodos[0][4:6]}/{periodos[0][:4]} até {periodos[-1][4:6]}/{periodos[-1][:4]}"
            save_callback(dados_periodos, periodo_info)
            logger.info(f"Salvamento final: {len(dados_periodos)} períodos de capital salvos")
        except Exception as save_error:
            logger.warning(f"Erro no salvamento final: {save_error}")

    logger.info(f"Processamento concluído: {len(dados_periodos)} períodos de capital com dados")

    return dados_periodos


# =============================================================================
# GERENCIAMENTO DE CACHE DE CAPITAL (ISOLADO)
# =============================================================================
def get_capital_cache_info() -> dict:
    """Retorna informações detalhadas sobre o cache de capital."""
    info = {
        'existe': False,
        'caminho': str(CAPITAL_CACHE_FILE),
        'tamanho': 0,
        'tamanho_formatado': '0 B',
        'data_modificacao': None,
        'data_formatada': 'N/A',
        'n_periodos': 0,
    }

    if CAPITAL_CACHE_FILE.exists():
        info['existe'] = True
        stat = CAPITAL_CACHE_FILE.stat()
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

        # Tentar contar períodos
        try:
            dados = carregar_cache_capital()
            if dados:
                info['n_periodos'] = len(dados)
        except Exception:
            pass

    return info


def carregar_cache_capital() -> Optional[Dict[str, pd.DataFrame]]:
    """Carrega o cache de capital do arquivo local."""
    if CAPITAL_CACHE_FILE.exists():
        try:
            with open(CAPITAL_CACHE_FILE, 'rb') as f:
                return pickle.load(f)
        except Exception as e:
            logger.error(f"Erro ao carregar cache de capital: {e}")
    return None


def salvar_cache_capital(dados_periodos: Dict[str, pd.DataFrame],
                         periodo_info: str,
                         incremental: bool = True) -> dict:
    """Salva o cache de capital, fazendo merge incremental com dados existentes.

    Args:
        dados_periodos: Dicionário {periodo: DataFrame} com novos dados
        periodo_info: String com informação do período extraído
        incremental: Se True (padrão), faz merge com cache existente

    Returns:
        Informações do cache salvo
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Se modo incremental, carregar dados existentes e fazer merge
    dados_finais = {}
    if incremental and CAPITAL_CACHE_FILE.exists():
        try:
            with open(CAPITAL_CACHE_FILE, 'rb') as f:
                dados_existentes = pickle.load(f)
            if dados_existentes:
                dados_finais = dados_existentes.copy()
                logger.info(f"Carregados {len(dados_existentes)} períodos existentes de capital para merge")
        except Exception as e:
            logger.warning(f"Erro ao carregar cache existente de capital: {e}, criando novo")

    # Adicionar/atualizar com novos dados
    novos = 0
    atualizados = 0
    for periodo, df in dados_periodos.items():
        if periodo in dados_finais:
            atualizados += 1
        else:
            novos += 1
        dados_finais[periodo] = df

    logger.info(f"Merge capital: {novos} novos, {atualizados} atualizados, {len(dados_finais)} total")

    # Salvar dados combinados
    with open(CAPITAL_CACHE_FILE, 'wb') as f:
        pickle.dump(dados_finais, f)

    # Atualizar info do cache
    with open(CAPITAL_CACHE_INFO, 'w') as f:
        f.write(f"Última extração capital: {datetime.now().strftime('%d/%m/%Y %H:%M')}\n")
        f.write(f"Última operação: {periodo_info}\n")
        f.write(f"Total de períodos: {len(dados_finais)}\n")
        if incremental:
            f.write(f"Novos períodos: {novos}, Atualizados: {atualizados}\n")

    return get_capital_cache_info()


def ler_info_cache_capital() -> Optional[str]:
    """Lê informações do arquivo de info do cache de capital."""
    if CAPITAL_CACHE_INFO.exists():
        try:
            with open(CAPITAL_CACHE_INFO, 'r') as f:
                return f.read()
        except Exception:
            pass
    return None


# =============================================================================
# FUNÇÕES AUXILIARES
# =============================================================================
def get_campos_capital_info() -> Dict[str, str]:
    """Retorna o mapeamento de campos para exibição/documentação."""
    return CAMPOS_CAPITAL.copy()


def get_colunas_capital_disponiveis() -> List[str]:
    """Retorna lista de colunas de capital disponíveis (nomes exibidos)."""
    return list(CAMPOS_CAPITAL.values())
