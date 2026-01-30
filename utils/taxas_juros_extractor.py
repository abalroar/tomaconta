"""
Módulo para extração de taxas de juros da API do Banco Central do Brasil.

Este módulo permite:
- Buscar produtos/modalidades disponíveis
- Buscar instituições financeiras por produto
- Extrair dados de taxas de juros por período
- Suporta múltiplos produtos e instituições

API: https://olinda.bcb.gov.br/olinda/servico/taxaJuros/versao/v2/odata/TaxasJurosDiariaPorInicioPeriodo
"""

import requests
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Optional, Tuple, Dict
import logging

# Configurar logger
logger = logging.getLogger("taxas_juros_extractor")
logger.setLevel(logging.INFO)

# URL da API do BCB para taxas de juros
API_URL = "https://olinda.bcb.gov.br/olinda/servico/taxaJuros/versao/v2/odata/TaxasJurosDiariaPorInicioPeriodo"

# Timeout para requisições (em segundos)
REQUEST_TIMEOUT = 120


def buscar_modalidades_disponiveis() -> Tuple[List[str], pd.DataFrame]:
    """
    Busca todos os produtos/modalidades disponíveis na API do BCB.

    Returns:
        Tuple contendo:
        - Lista de nomes de modalidades únicas
        - DataFrame com amostra dos dados (usado para buscar instituições)
    """
    # Busca dados dos últimos 30 dias para obter lista de modalidades
    data_inicio = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')

    params = {
        "$format": "json",
        "$top": 10000,
        "dataInicioPeriodo": f"'{data_inicio}'"
    }

    try:
        response = requests.get(API_URL, params=params, timeout=REQUEST_TIMEOUT)

        if response.status_code == 200:
            dados = response.json()

            if 'value' in dados and dados['value']:
                df = pd.DataFrame(dados['value'])

                if 'Modalidade' in df.columns:
                    modalidades = sorted(df['Modalidade'].unique())
                    logger.info(f"Encontradas {len(modalidades)} modalidades")
                    return modalidades, df

        logger.error(f"Erro ao acessar API: código {response.status_code}")
        return [], pd.DataFrame()

    except requests.exceptions.Timeout:
        logger.error("Timeout ao acessar API do BCB")
        return [], pd.DataFrame()
    except Exception as e:
        logger.error(f"Erro de conexão: {e}")
        return [], pd.DataFrame()


def buscar_instituicoes_por_modalidade(
    modalidade: str,
    df_amostra: Optional[pd.DataFrame] = None
) -> List[str]:
    """
    Busca instituições financeiras que oferecem uma determinada modalidade.

    Args:
        modalidade: Nome da modalidade/produto
        df_amostra: DataFrame com dados já baixados (opcional, para otimização)

    Returns:
        Lista de nomes de instituições financeiras
    """
    # Primeiro, tenta usar dados já baixados
    if df_amostra is not None and not df_amostra.empty:
        df_filtrado = df_amostra[df_amostra['Modalidade'] == modalidade].copy()

        if not df_filtrado.empty and 'InstituicaoFinanceira' in df_filtrado.columns:
            instituicoes = sorted(df_filtrado['InstituicaoFinanceira'].unique())
            if instituicoes:
                logger.info(f"Encontradas {len(instituicoes)} instituições para {modalidade}")
                return instituicoes

    # Se não encontrou, faz busca expandida
    data_inicio = (datetime.now() - timedelta(days=180)).strftime('%Y-%m-%d')

    params = {
        "$format": "json",
        "$top": 50000,
        "dataInicioPeriodo": f"'{data_inicio}'"
    }

    try:
        response = requests.get(API_URL, params=params, timeout=REQUEST_TIMEOUT)

        if response.status_code == 200:
            dados = response.json()

            if 'value' in dados and dados['value']:
                df = pd.DataFrame(dados['value'])
                df_filtrado = df[df['Modalidade'] == modalidade].copy()

                if not df_filtrado.empty and 'InstituicaoFinanceira' in df_filtrado.columns:
                    instituicoes = sorted(df_filtrado['InstituicaoFinanceira'].unique())
                    logger.info(f"Encontradas {len(instituicoes)} instituições para {modalidade}")
                    return instituicoes

        return []

    except Exception as e:
        logger.error(f"Erro ao buscar instituições: {e}")
        return []


def buscar_instituicoes_todas_modalidades(
    modalidades: List[str],
    df_amostra: Optional[pd.DataFrame] = None
) -> List[str]:
    """
    Busca instituições financeiras que oferecem qualquer uma das modalidades selecionadas.

    Args:
        modalidades: Lista de nomes de modalidades/produtos
        df_amostra: DataFrame com dados já baixados (opcional)

    Returns:
        Lista de nomes de instituições financeiras (união de todas as modalidades)
    """
    todas_instituicoes = set()

    for modalidade in modalidades:
        instituicoes = buscar_instituicoes_por_modalidade(modalidade, df_amostra)
        todas_instituicoes.update(instituicoes)

    return sorted(list(todas_instituicoes))


def extrair_taxas_juros(
    modalidades: List[str],
    data_inicio: str,
    data_fim: Optional[str] = None,
    instituicoes: Optional[List[str]] = None,
    callback_progresso=None
) -> pd.DataFrame:
    """
    Extrai dados de taxas de juros para modalidades e período especificados.

    Args:
        modalidades: Lista de modalidades/produtos
        data_inicio: Data inicial no formato 'YYYY-MM-DD'
        data_fim: Data final no formato 'YYYY-MM-DD' (opcional, padrão = hoje)
        instituicoes: Lista de instituições financeiras (opcional, None = todas)
        callback_progresso: Função de callback para atualizar progresso (opcional)

    Returns:
        DataFrame com colunas:
        - data_inicio: Data de início do período
        - data_fim: Data de fim do período
        - modalidade: Nome do produto
        - instituicao: Nome da instituição financeira
        - posicao: Posição no ranking
        - taxa_mensal: Taxa de juros ao mês (%)
        - taxa_anual: Taxa de juros ao ano (%)
        - cnpj8: CNPJ da instituição (8 dígitos)
    """
    if data_fim is None:
        data_fim = datetime.now().strftime('%Y-%m-%d')

    params = {
        "$format": "json",
        "$top": 150000,
        "dataInicioPeriodo": f"'{data_inicio}'"
    }

    try:
        if callback_progresso:
            callback_progresso("Baixando dados da API do BCB...")

        response = requests.get(API_URL, params=params, timeout=180)

        if response.status_code != 200:
            logger.error(f"Erro HTTP {response.status_code}")
            return pd.DataFrame()

        dados = response.json()

        if 'value' not in dados or not dados['value']:
            logger.warning("Nenhum dado retornado pela API")
            return pd.DataFrame()

        if callback_progresso:
            callback_progresso("Processando dados...")

        df = pd.DataFrame(dados['value'])

        # Filtra por modalidades selecionadas
        df = df[df['Modalidade'].isin(modalidades)].copy()

        if df.empty:
            logger.warning("Nenhum dado para as modalidades selecionadas")
            return pd.DataFrame()

        # Renomeia colunas para padrão
        df = df.rename(columns={
            'InicioPeriodo': 'data_inicio',
            'FimPeriodo': 'data_fim',
            'Modalidade': 'modalidade',
            'InstituicaoFinanceira': 'instituicao',
            'Posicao': 'posicao',
            'TaxaJurosAoMes': 'taxa_mensal',
            'TaxaJurosAoAno': 'taxa_anual',
            'cnpj8': 'cnpj8'
        })

        # Converte datas
        df['data_inicio'] = pd.to_datetime(df['data_inicio'])
        df['data_fim'] = pd.to_datetime(df['data_fim'])

        # Filtra por data final
        data_fim_dt = pd.to_datetime(data_fim)
        df = df[df['data_fim'] <= data_fim_dt].copy()

        # Converte taxas para numérico
        df['taxa_mensal'] = pd.to_numeric(df['taxa_mensal'], errors='coerce')
        df['taxa_anual'] = pd.to_numeric(df['taxa_anual'], errors='coerce')
        df['posicao'] = pd.to_numeric(df['posicao'], errors='coerce')

        # Filtra por instituições se especificado
        if instituicoes and len(instituicoes) > 0:
            df = df[df['instituicao'].isin(instituicoes)].copy()

        # Seleciona e ordena colunas
        colunas = ['data_inicio', 'data_fim', 'modalidade', 'instituicao',
                   'posicao', 'taxa_mensal', 'taxa_anual', 'cnpj8']
        colunas_disponiveis = [c for c in colunas if c in df.columns]
        df = df[colunas_disponiveis].copy()

        # Ordena por data e instituição
        df = df.sort_values(['data_inicio', 'modalidade', 'posicao']).reset_index(drop=True)

        # Remove linhas com valores nulos essenciais
        df = df.dropna(subset=['data_inicio', 'modalidade', 'instituicao', 'taxa_mensal'])

        logger.info(f"Extraídos {len(df)} registros de taxas de juros")

        return df

    except requests.exceptions.Timeout:
        logger.error("Timeout ao baixar dados")
        return pd.DataFrame()
    except Exception as e:
        logger.error(f"Erro ao extrair dados: {e}")
        return pd.DataFrame()


def formatar_nome_modalidade(modalidade: str) -> str:
    """
    Formata nome da modalidade para exibição mais curta.

    Args:
        modalidade: Nome completo da modalidade

    Returns:
        Nome formatado para exibição
    """
    # Substituições para nomes mais curtos
    substituicoes = {
        ' (Taxa pré-fixada para Pessoa física)': ' (PF Pré)',
        ' (Taxa pré-fixada para Pessoa jurídica)': ' (PJ Pré)',
        ' (Taxa pós-fixada referenciada em TR para Pessoa física)': ' (PF TR)',
        ' (Taxa pós-fixada referenciada em IPCA para Pessoa física)': ' (PF IPCA)',
        ' (Taxa pós-fixada referenciada em juros flutuantes para Pessoa jurídica)': ' (PJ Flutuante)',
        ' (Taxa pós-fixada referenciada em moeda estrangeira para Pessoa jurídica)': ' (PJ M.E.)',
        ' - Pré-fixado': ' (Pré)',
        ' - Pós-fixado referenciado em TR': ' (TR)',
        ' - Pós-fixado referenciado em IPCA': ' (IPCA)',
        ' - Pós-fixado referenciado em juros flutuantes': ' (Flutuante)',
        ' - Pós-fixado referenciado em moeda estrangeira': ' (M.E.)',
    }

    nome = modalidade
    for antigo, novo in substituicoes.items():
        nome = nome.replace(antigo, novo)

    return nome


def obter_periodos_disponiveis(df: pd.DataFrame) -> List[Tuple[str, str]]:
    """
    Obtém lista de períodos disponíveis nos dados.

    Args:
        df: DataFrame com dados extraídos

    Returns:
        Lista de tuplas (data_inicio, data_fim) formatadas
    """
    if df.empty or 'data_inicio' not in df.columns or 'data_fim' not in df.columns:
        return []

    # Agrupa por período único
    periodos = df.groupby(['data_inicio', 'data_fim']).size().reset_index(name='count')
    periodos = periodos.sort_values('data_inicio', ascending=False)

    resultado = []
    for _, row in periodos.iterrows():
        inicio = row['data_inicio'].strftime('%d/%m/%Y')
        fim = row['data_fim'].strftime('%d/%m/%Y')
        resultado.append((inicio, fim))

    return resultado


def criar_tabela_pivot(
    df: pd.DataFrame,
    valor: str = 'taxa_mensal',
    usar_data_fim: bool = True
) -> pd.DataFrame:
    """
    Cria tabela pivot com instituições nas colunas e datas nas linhas.

    Args:
        df: DataFrame com dados extraídos
        valor: Nome da coluna de valor ('taxa_mensal' ou 'taxa_anual')
        usar_data_fim: Se True, usa data_fim; se False, usa data_inicio

    Returns:
        DataFrame pivotado
    """
    if df.empty:
        return pd.DataFrame()

    coluna_data = 'data_fim' if usar_data_fim else 'data_inicio'

    # Se houver múltiplas modalidades, inclui no pivot
    modalidades_unicas = df['modalidade'].nunique()

    if modalidades_unicas > 1:
        # Cria coluna combinada para múltiplas modalidades
        df_pivot = df.pivot_table(
            index=coluna_data,
            columns=['modalidade', 'instituicao'],
            values=valor,
            aggfunc='mean'
        )
    else:
        df_pivot = df.pivot_table(
            index=coluna_data,
            columns='instituicao',
            values=valor,
            aggfunc='mean'
        )

    df_pivot = df_pivot.reset_index()
    df_pivot = df_pivot.rename(columns={coluna_data: 'data'})
    df_pivot = df_pivot.sort_values('data', ascending=True)

    return df_pivot


def calcular_estatisticas(df: pd.DataFrame) -> Dict:
    """
    Calcula estatísticas básicas dos dados.

    Args:
        df: DataFrame com dados extraídos

    Returns:
        Dicionário com estatísticas
    """
    if df.empty:
        return {}

    stats = {
        'total_registros': len(df),
        'n_modalidades': df['modalidade'].nunique() if 'modalidade' in df.columns else 0,
        'n_instituicoes': df['instituicao'].nunique() if 'instituicao' in df.columns else 0,
        'n_periodos': df['data_fim'].nunique() if 'data_fim' in df.columns else 0,
        'taxa_mensal_media': df['taxa_mensal'].mean() if 'taxa_mensal' in df.columns else None,
        'taxa_mensal_min': df['taxa_mensal'].min() if 'taxa_mensal' in df.columns else None,
        'taxa_mensal_max': df['taxa_mensal'].max() if 'taxa_mensal' in df.columns else None,
        'data_inicio': df['data_inicio'].min().strftime('%d/%m/%Y') if 'data_inicio' in df.columns else None,
        'data_fim': df['data_fim'].max().strftime('%d/%m/%Y') if 'data_fim' in df.columns else None,
    }

    return stats
