"""
extractor.py - Sistema de extração autônomo para dados do IFData/BCB

Este módulo fornece extração completa e independente de todos os relatórios
da API Olinda do BCB, sem dependências externas.

Relatórios suportados:
- 1: Resumo (variáveis selecionadas para gráficos)
- 2: Ativo (todas as variáveis)
- 3: Passivo (todas as variáveis)
- 4: Demonstração de Resultado (todas as variáveis)
- 5: Informações de Capital (variáveis selecionadas)
- 11: Carteira de crédito ativa PF
- 13: Carteira de crédito ativa PJ
- 16: Carteira de crédito ativa - Instrumentos 4.966 (C1-C5)

IMPORTANTE: Este extrator produz dados no formato exato que os gráficos esperam:
- Coluna "Instituição" (não "NomeInstituicao")
- Coluna "Período" no formato "1/2024" (trimestre/ano)
- Valores numéricos em formato bruto (percentuais como 0-1, moedas em reais)
"""

import logging
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd
import requests

# Configuração de logging
logger = logging.getLogger("ifdata_extractor")

# =============================================================================
# CONSTANTES DA API
# =============================================================================
BASE_URL = "https://olinda.bcb.gov.br/olinda/servico/IFDATA/versao/v1/odata"
TIPO_INSTITUICAO = 1  # Conglomerados Prudenciais e Instituições Independentes

# Timeout e retry
DEFAULT_TIMEOUT = 120
MAX_RETRIES = 3
BACKOFF_FACTOR = 2.0
RATE_LIMIT_DELAY = 1.5

# =============================================================================
# VARIÁVEIS DO RELATÓRIO 1 (RESUMO) - Para compatibilidade com gráficos
# =============================================================================
# Estas são as variáveis que os gráficos do app1.py esperam

VARIAVEIS_RESUMO_API = [
    # Variáveis monetárias (VARS_MOEDAS)
    "Ativo Total",
    "Carteira de Crédito",
    "Carteira de Crédito Classificada",
    "Títulos e Valores Mobiliários",
    "Passivo Exigível",
    "Captações",
    "Patrimônio Líquido",
    "Lucro Líquido",
    "Patrimônio de Referência",
    "Patrimônio de Referência para Comparação com o RWA (e)",
    # Variáveis percentuais (VARS_PERCENTUAL)
    "Índice de Basileia",
    "Índice de Imobilização",
    # Variáveis de contagem (VARS_CONTAGEM)
    "Número de Agências",
    "Número de Postos de Atendimento",
]

# Variáveis derivadas calculadas após extração
VARIAVEIS_DERIVADAS = [
    "Lucro Líquido Acumulado YTD",
    "ROE Ac. YTD an. (%)",
    "Crédito/Captações (%)",
    "Crédito/Ativo (%)",
    "Crédito/PL (%)",
]

# =============================================================================
# VARIÁVEIS DO RELATÓRIO 5 (CAPITAL)
# =============================================================================
# NOTA: Os nomes da API contêm \n (quebras de linha) que são removidos na normalização
CAMPOS_CAPITAL = {
    "Capital Principal para Comparação com RWA (a)": "Capital Principal",
    "Capital Complementar (b)": "Capital Complementar",
    "Patrimônio de Referência Nível I para Comparação com RWA (c) = (a) + (b)": "Patrimônio de Referência Nível I",
    "Capital Nível II (d)": "Capital Nível II",
    "RWA para Risco de Crédito (f)": "RWA Crédito",
    "RWA para Risco de Mercado (g) = (g1) + (g2) + (g3) + (g4) + (g5) + (g6)": "RWA Mercado",
    "RWA para Risco Operacional (h)": "RWA Operacional",
    "Ativos Ponderados pelo Risco (RWA) (j) = (f) + (g) + (h) + (i)": "RWA Total",
    "Exposição Total (k)": "Exposição Total",
    "Índice de Capital Principal (l) = (a) / (j)": "Índice de Capital Principal",
    "Índice de Capital Nível I (m) = (c) / (j)": "Índice de Capital Nível I",
    "Índice de Basileia (n) = (e) / (j)": "Índice de Basileia Capital",
    "Adicional de Capital Principal": "Adicional de Capital Principal",
    "IRRBB": "IRRBB",
    "Razão de Alavancagem (o) = (c) / (k)": "Razão de Alavancagem",
    "Índice de Imobilização (p)": "Índice de Imobilização Capital",
    # Adicionar também o Patrimônio de Referência (sem os parênteses)
    "Patrimônio de Referência para Comparação com o RWA": "Patrimônio de Referência",
}


def _normalizar_nome_coluna(nome: str) -> str:
    """Normaliza nome de coluna removendo quebras de linha e espaços extras."""
    if not isinstance(nome, str):
        return nome
    # Remover quebras de linha e substituir por espaço
    nome = nome.replace('\n', ' ').replace('\r', ' ')
    # Remover espaços extras
    nome = ' '.join(nome.split())
    return nome


# =============================================================================
# FUNÇÕES HTTP
# =============================================================================
def _fetch_json(url: str, timeout: int = DEFAULT_TIMEOUT) -> Optional[dict]:
    """Faz requisição HTTP com retry e backoff exponencial."""
    last_error = None

    for attempt in range(MAX_RETRIES + 1):
        try:
            logger.debug(f"Requisição (tentativa {attempt + 1}): {url[:80]}...")
            response = requests.get(url, timeout=timeout)

            # Rate limit
            if response.status_code == 429:
                wait = BACKOFF_FACTOR * (2 ** attempt) * 2
                logger.warning(f"Rate limit (429). Aguardando {wait:.1f}s...")
                time.sleep(wait)
                continue

            # Erro de servidor
            if response.status_code >= 500:
                wait = BACKOFF_FACTOR * (2 ** attempt)
                logger.warning(f"Erro servidor ({response.status_code}). Aguardando {wait:.1f}s...")
                time.sleep(wait)
                continue

            response.raise_for_status()
            return response.json()

        except requests.Timeout:
            last_error = "Timeout"
            wait = BACKOFF_FACTOR * (2 ** attempt)
            logger.warning(f"Timeout. Aguardando {wait:.1f}s...")
            time.sleep(wait)

        except requests.RequestException as e:
            last_error = str(e)
            if attempt >= MAX_RETRIES:
                logger.error(f"Falha após {MAX_RETRIES + 1} tentativas: {e}")
                return None
            wait = BACKOFF_FACTOR * (2 ** attempt)
            time.sleep(wait)

        except ValueError as e:
            logger.error(f"Erro JSON: {e}")
            return None

    logger.error(f"Falha final: {last_error}")
    return None


# =============================================================================
# FUNÇÕES DE EXTRAÇÃO DA API
# =============================================================================
def extrair_cadastro(periodo: str) -> pd.DataFrame:
    """Extrai cadastro de instituições para um período.

    Args:
        periodo: Período no formato YYYYMM (ex: "202312")

    Returns:
        DataFrame com CodInst e NomeInstituicao
    """
    url = f"{BASE_URL}/IfDataCadastro(AnoMes={int(periodo)})?$format=json&$top=5000"

    data = _fetch_json(url, timeout=60)
    if not data or "value" not in data:
        logger.warning(f"Cadastro vazio para {periodo}")
        return pd.DataFrame()

    df = pd.DataFrame(data["value"])
    logger.debug(f"Cadastro {periodo}: {len(df)} instituições")
    return df


def extrair_valores(periodo: str, relatorio: int) -> pd.DataFrame:
    """Extrai valores de um relatório específico.

    Args:
        periodo: Período no formato YYYYMM
        relatorio: Número do relatório (1, 2, 3, 4, 5, 11, 13, 16)

    Returns:
        DataFrame com CodInst, NomeColuna, Saldo
    """
    url = (
        f"{BASE_URL}/IfDataValores("
        f"AnoMes={int(periodo)},"
        f"TipoInstituicao={TIPO_INSTITUICAO},"
        f"Relatorio='{relatorio}'"
        f")?$format=json&$top=500000"
    )

    data = _fetch_json(url, timeout=180)
    if not data or "value" not in data:
        logger.warning(f"Valores vazios para {periodo}, relatório {relatorio}")
        return pd.DataFrame()

    df = pd.DataFrame(data["value"])
    logger.debug(f"Valores {periodo} rel.{relatorio}: {len(df)} registros")
    return df


# =============================================================================
# FUNÇÕES DE CONVERSÃO DE PERÍODO
# =============================================================================
def periodo_api_para_exibicao(periodo_api: str) -> str:
    """Converte período da API (YYYYMM) para formato de exibição (T/YYYY).

    Args:
        periodo_api: "202312"

    Returns:
        "4/2023" (trimestre 4 de 2023)
    """
    ano = periodo_api[:4]
    mes = periodo_api[4:6]

    # Mapear mês para trimestre
    trimestre_map = {"03": "1", "06": "2", "09": "3", "12": "4"}
    trimestre = trimestre_map.get(mes, "1")

    return f"{trimestre}/{ano}"


def periodo_exibicao_para_api(periodo_exib: str) -> str:
    """Converte período de exibição (T/YYYY) para formato da API (YYYYMM).

    Args:
        periodo_exib: "4/2023"

    Returns:
        "202312"
    """
    partes = periodo_exib.split("/")
    trimestre = partes[0]
    ano = partes[1]

    # Mapear trimestre para mês
    mes_map = {"1": "03", "2": "06", "3": "09", "4": "12"}
    mes = mes_map.get(trimestre, "03")

    return f"{ano}{mes}"


# =============================================================================
# EXTRAÇÃO PARA RELATÓRIO 1 (RESUMO) - COMPATÍVEL COM GRÁFICOS
# =============================================================================
def extrair_resumo(
    periodo: str,
    dict_aliases: Optional[Dict[str, str]] = None
) -> Optional[pd.DataFrame]:
    """Extrai dados do Relatório 1 (Resumo) no formato dos gráficos.

    Retorna DataFrame com:
    - Coluna "Instituição" (nome da instituição)
    - Coluna "Período" no formato "1/2024"
    - Colunas de métricas financeiras

    Args:
        periodo: Período no formato YYYYMM
        dict_aliases: Dicionário de aliases para nomes de instituições

    Returns:
        DataFrame formatado ou None se erro
    """
    logger.info(f"Extraindo Resumo para {periodo}...")

    # 1. Extrair cadastro e valores
    df_cad = extrair_cadastro(periodo)
    df_val = extrair_valores(periodo, relatorio=1)

    if df_val.empty:
        logger.warning(f"Sem dados para Resumo {periodo}")
        return None

    # 2. Normalizar nomes de colunas (remover \n e espaços extras)
    if "NomeColuna" in df_val.columns:
        df_val["NomeColuna"] = df_val["NomeColuna"].apply(_normalizar_nome_coluna)

    # 3. Filtrar apenas variáveis desejadas (normalizar também a lista)
    variaveis_norm = [_normalizar_nome_coluna(v) for v in VARIAVEIS_RESUMO_API]
    df_filtrado = df_val[df_val["NomeColuna"].isin(variaveis_norm)].copy()

    if df_filtrado.empty:
        logger.warning(f"Nenhuma variável encontrada para {periodo}")
        # Log variáveis disponíveis para debug
        if not df_val.empty and "NomeColuna" in df_val.columns:
            vars_disponiveis = df_val["NomeColuna"].unique()[:10]
            logger.debug(f"Variáveis disponíveis (primeiras 10): {list(vars_disponiveis)}")
        return None

    # 4. Pivotar dados
    df_pivot = df_filtrado.pivot_table(
        index="CodInst",
        columns="NomeColuna",
        values="Saldo",
        aggfunc="sum"
    ).reset_index()
    df_pivot.columns.name = None

    # 5. Adicionar nomes de instituições
    if not df_cad.empty and "CodInst" in df_cad.columns:
        # Encontrar coluna de nome
        col_nome = None
        for candidato in ["NomeInstituicao", "NomeInstituição"]:
            if candidato in df_cad.columns:
                col_nome = candidato
                break

        if col_nome:
            df_nomes = df_cad[["CodInst", col_nome]].drop_duplicates()
            df_pivot = df_pivot.merge(df_nomes, on="CodInst", how="left")
            df_pivot = df_pivot.rename(columns={col_nome: "Instituição"})

    # 6. Preencher nomes faltantes
    if "Instituição" not in df_pivot.columns:
        df_pivot["Instituição"] = df_pivot["CodInst"].apply(lambda x: f"[IF {x}]")
    else:
        df_pivot["Instituição"] = df_pivot.apply(
            lambda row: row["Instituição"] if pd.notna(row["Instituição"])
            else f"[IF {row['CodInst']}]",
            axis=1
        )

    # 7. Aplicar aliases
    if dict_aliases:
        df_pivot["Instituição"] = df_pivot["Instituição"].apply(
            lambda x: dict_aliases.get(x, x) if pd.notna(x) else x
        )

    # 8. Adicionar período no formato de exibição
    df_pivot["Período"] = periodo_api_para_exibicao(periodo)

    # 9. Calcular métricas derivadas
    df_pivot = _calcular_metricas_derivadas(df_pivot, periodo)

    # 10. Remover CodInst (não usado nos gráficos)
    if "CodInst" in df_pivot.columns:
        df_pivot = df_pivot.drop(columns=["CodInst"])

    # 11. Reordenar colunas
    cols_inicio = ["Instituição", "Período"]
    outras_cols = sorted([c for c in df_pivot.columns if c not in cols_inicio])
    df_pivot = df_pivot[cols_inicio + outras_cols]

    # 12. Remover linhas sem dados
    colunas_numericas = [c for c in df_pivot.columns if c not in cols_inicio]
    if colunas_numericas:
        df_pivot = df_pivot.dropna(subset=colunas_numericas, how="all")

    logger.info(f"Resumo {periodo}: {len(df_pivot)} instituições, {len(colunas_numericas)} variáveis")
    return df_pivot


def _calcular_metricas_derivadas(df: pd.DataFrame, periodo: str) -> pd.DataFrame:
    """Calcula métricas derivadas (ROE, ratios, etc.)."""
    df = df.copy()

    # Lucro Líquido Acumulado YTD
    if "Lucro Líquido" in df.columns:
        mes = periodo[4:6]
        mes_int = int(mes) if str(mes).isdigit() else None
        fator = 12 / mes_int if mes_int else 1
        df["Lucro Líquido Acumulado YTD"] = df["Lucro Líquido"]
        # Nota: o Lucro Líquido já vem acumulado do BCB

    # ROE Acumulado YTD Anualizado (%)
    if "Lucro Líquido" in df.columns and "Patrimônio Líquido" in df.columns:
        mes = periodo[4:6]
        mes_int = int(mes) if str(mes).isdigit() else None
        fator = 12 / mes_int if mes_int else 1

        # ROE = (Lucro / PL) * fator_anualização
        # Armazenado como decimal (0-1), não percentual
        df["ROE Ac. YTD an. (%)"] = df.apply(
            lambda row: (row["Lucro Líquido"] / row["Patrimônio Líquido"] * fator)
            if pd.notna(row["Patrimônio Líquido"]) and row["Patrimônio Líquido"] != 0
            else None,
            axis=1
        )

    # Crédito/Captações (%)
    if "Carteira de Crédito" in df.columns and "Captações" in df.columns:
        df["Crédito/Captações (%)"] = df.apply(
            lambda row: row["Carteira de Crédito"] / row["Captações"]
            if pd.notna(row["Captações"]) and row["Captações"] != 0
            else None,
            axis=1
        )

    # Crédito/Ativo (%)
    if "Carteira de Crédito" in df.columns and "Ativo Total" in df.columns:
        df["Crédito/Ativo (%)"] = df.apply(
            lambda row: row["Carteira de Crédito"] / row["Ativo Total"]
            if pd.notna(row["Ativo Total"]) and row["Ativo Total"] != 0
            else None,
            axis=1
        )

    # Crédito/PL (%)
    if "Carteira de Crédito" in df.columns and "Patrimônio Líquido" in df.columns:
        df["Crédito/PL (%)"] = df.apply(
            lambda row: row["Carteira de Crédito"] / row["Patrimônio Líquido"]
            if pd.notna(row["Patrimônio Líquido"]) and row["Patrimônio Líquido"] != 0
            else None,
            axis=1
        )

    # Converter índices que vêm como percentual (0-100) para decimal (0-1).
    # Tratamento por linha (não por coluna inteira) para evitar dividir novamente
    # valores que já estão em base decimal quando há dados mistos no mesmo período.
    for col in ["Índice de Basileia", "Índice de Imobilização"]:
        if col in df.columns:
            serie_num = pd.to_numeric(df[col], errors="coerce")
            mask_percentual = serie_num.abs() > 1
            if mask_percentual.any():
                df.loc[mask_percentual, col] = serie_num.loc[mask_percentual] / 100

    return df


# =============================================================================
# EXTRAÇÃO PARA RELATÓRIO 5 (CAPITAL)
# =============================================================================
def extrair_capital(
    periodo: str,
    dict_aliases: Optional[Dict[str, str]] = None
) -> Optional[pd.DataFrame]:
    """Extrai dados do Relatório 5 (Capital) no formato dos gráficos.

    Args:
        periodo: Período no formato YYYYMM
        dict_aliases: Dicionário de aliases

    Returns:
        DataFrame formatado ou None
    """
    logger.info(f"Extraindo Capital para {periodo}...")

    df_cad = extrair_cadastro(periodo)
    df_val = extrair_valores(periodo, relatorio=5)

    if df_val.empty:
        logger.warning(f"Sem dados de Capital para {periodo}")
        return None

    # Normalizar nomes das colunas (remover \n e espaços extras)
    if "NomeColuna" in df_val.columns:
        df_val["NomeColuna"] = df_val["NomeColuna"].apply(_normalizar_nome_coluna)

    # Criar mapeamento normalizado para filtrar e renomear
    campos_api_normalizados = {_normalizar_nome_coluna(k): v for k, v in CAMPOS_CAPITAL.items()}

    # Filtrar campos desejados
    df_filtrado = df_val[df_val["NomeColuna"].isin(campos_api_normalizados.keys())].copy()

    if df_filtrado.empty:
        logger.warning(f"Nenhum campo de capital encontrado para {periodo}")
        # Log das colunas disponíveis para debug
        if not df_val.empty and "NomeColuna" in df_val.columns:
            cols_disponiveis = df_val["NomeColuna"].unique()[:10]
            logger.debug(f"Colunas disponíveis (primeiras 10): {list(cols_disponiveis)}")
        return None

    # Pivotar
    df_pivot = df_filtrado.pivot_table(
        index="CodInst",
        columns="NomeColuna",
        values="Saldo" if "Saldo" in df_filtrado.columns else "Valor",
        aggfunc="first"
    ).reset_index()
    df_pivot.columns.name = None

    # Renomear colunas usando o mapeamento normalizado
    rename_map = {k: v for k, v in campos_api_normalizados.items() if k in df_pivot.columns}
    df_pivot = df_pivot.rename(columns=rename_map)

    # Adicionar nomes
    if not df_cad.empty:
        col_nome = None
        for candidato in ["NomeInstituicao", "NomeInstituição"]:
            if candidato in df_cad.columns:
                col_nome = candidato
                break
        if col_nome:
            df_nomes = df_cad[["CodInst", col_nome]].drop_duplicates()
            df_pivot = df_pivot.merge(df_nomes, on="CodInst", how="left")
            df_pivot = df_pivot.rename(columns={col_nome: "Instituição"})

    if "Instituição" not in df_pivot.columns:
        df_pivot["Instituição"] = df_pivot["CodInst"].apply(lambda x: f"[IF {x}]")

    # Aplicar aliases
    if dict_aliases:
        df_pivot["Instituição"] = df_pivot["Instituição"].apply(
            lambda x: dict_aliases.get(x, x) if pd.notna(x) else x
        )

    # Adicionar período
    df_pivot["Período"] = periodo_api_para_exibicao(periodo)

    # Converter índices percentuais para decimal com tratamento por linha
    # para evitar dupla divisão em colunas com escala mista (0-1 e 0-100).
    for col in ["Índice de Capital Principal", "Índice de Capital Nível I",
                "Índice de Basileia Capital", "Razão de Alavancagem",
                "Índice de Imobilização Capital"]:
        if col in df_pivot.columns:
            serie_num = pd.to_numeric(df_pivot[col], errors="coerce")
            mask_percentual = serie_num.abs() > 1
            if mask_percentual.any():
                df_pivot.loc[mask_percentual, col] = serie_num.loc[mask_percentual] / 100

    # Remover CodInst
    if "CodInst" in df_pivot.columns:
        df_pivot = df_pivot.drop(columns=["CodInst"])

    # Reordenar
    cols_inicio = ["Instituição", "Período"]
    outras_cols = sorted([c for c in df_pivot.columns if c not in cols_inicio])
    df_pivot = df_pivot[cols_inicio + outras_cols]

    logger.info(f"Capital {periodo}: {len(df_pivot)} instituições")
    return df_pivot


# =============================================================================
# EXTRAÇÃO PARA RELATÓRIOS COMPLETOS (2, 3, 4, 11, 13, 14)
# =============================================================================
def extrair_relatorio_completo(
    periodo: str,
    relatorio: int,
    dict_aliases: Optional[Dict[str, str]] = None
) -> Optional[pd.DataFrame]:
    """Extrai TODAS as variáveis de um relatório.

    Args:
        periodo: Período no formato YYYYMM
        relatorio: Número do relatório (2, 3, 4, 11, 13, 16)
        dict_aliases: Dicionário de aliases

    Returns:
        DataFrame com todas as variáveis ou None
    """
    nome_rel = {2: "Ativo", 3: "Passivo", 4: "DRE",
                11: "Carteira PF", 13: "Carteira PJ", 16: "Carteira Instrumentos 4.966"}
    logger.info(f"Extraindo {nome_rel.get(relatorio, f'Rel.{relatorio}')} para {periodo}...")

    df_cad = extrair_cadastro(periodo)
    df_val = extrair_valores(periodo, relatorio)

    if df_val.empty:
        logger.warning(f"Sem dados para relatório {relatorio}, período {periodo}")
        return None

    # Normalizar nomes de colunas (remover \n e espaços extras)
    if "NomeColuna" in df_val.columns:
        df_val["NomeColuna"] = df_val["NomeColuna"].apply(_normalizar_nome_coluna)

    # Pivotar TODAS as variáveis
    df_pivot = df_val.pivot_table(
        index="CodInst",
        columns="NomeColuna",
        values="Saldo" if "Saldo" in df_val.columns else "Valor",
        aggfunc="sum"
    ).reset_index()
    df_pivot.columns.name = None

    # Adicionar nomes
    if not df_cad.empty:
        col_nome = None
        for candidato in ["NomeInstituicao", "NomeInstituição"]:
            if candidato in df_cad.columns:
                col_nome = candidato
                break
        if col_nome:
            df_nomes = df_cad[["CodInst", col_nome]].drop_duplicates()
            df_pivot = df_pivot.merge(df_nomes, on="CodInst", how="left")
            df_pivot = df_pivot.rename(columns={col_nome: "Instituição"})

    if "Instituição" not in df_pivot.columns:
        df_pivot["Instituição"] = df_pivot["CodInst"].apply(lambda x: f"[IF {x}]")

    # Aplicar aliases
    if dict_aliases:
        df_pivot["Instituição"] = df_pivot["Instituição"].apply(
            lambda x: dict_aliases.get(x, x) if pd.notna(x) else x
        )

    # Adicionar período
    df_pivot["Período"] = periodo_api_para_exibicao(periodo)

    # Remover CodInst
    if "CodInst" in df_pivot.columns:
        df_pivot = df_pivot.drop(columns=["CodInst"])

    # Reordenar
    cols_inicio = ["Instituição", "Período"]
    outras_cols = sorted([c for c in df_pivot.columns if c not in cols_inicio])
    df_pivot = df_pivot[cols_inicio + outras_cols]

    n_vars = len([c for c in df_pivot.columns if c not in cols_inicio])
    logger.info(f"Relatório {relatorio} {periodo}: {len(df_pivot)} instituições, {n_vars} variáveis")
    return df_pivot


# =============================================================================
# FUNÇÃO PRINCIPAL DE EXTRAÇÃO
# =============================================================================
def extrair_periodo(
    periodo: str,
    relatorio: int,
    dict_aliases: Optional[Dict[str, str]] = None
) -> Optional[pd.DataFrame]:
    """Função principal para extrair qualquer relatório.

    Args:
        periodo: Período no formato YYYYMM
        relatorio: Número do relatório
        dict_aliases: Dicionário de aliases

    Returns:
        DataFrame formatado para gráficos ou None
    """
    if relatorio == 1:
        return extrair_resumo(periodo, dict_aliases)
    elif relatorio == 5:
        return extrair_capital(periodo, dict_aliases)
    else:
        return extrair_relatorio_completo(periodo, relatorio, dict_aliases)


def extrair_multiplos_periodos(
    periodos: List[str],
    relatorio: int,
    dict_aliases: Optional[Dict[str, str]] = None,
    callback_progresso: Optional[Callable[[int, int, str], None]] = None,
    callback_salvamento: Optional[Callable[[Dict[str, pd.DataFrame], str], None]] = None,
    intervalo_salvamento: int = 4
) -> Dict[str, pd.DataFrame]:
    """Extrai múltiplos períodos e retorna no formato de dicionário.

    IMPORTANTE: Retorna no formato {periodo_exib: DataFrame} que o app1.py espera.

    Args:
        periodos: Lista de períodos no formato YYYYMM
        relatorio: Número do relatório
        dict_aliases: Dicionário de aliases
        callback_progresso: Função(i, total, periodo) chamada a cada período
        callback_salvamento: Função(dados, info) para salvamento parcial
        intervalo_salvamento: Salvar a cada N períodos

    Returns:
        Dicionário {periodo_exibicao: DataFrame}
    """
    logger.info(f"Iniciando extração de {len(periodos)} períodos, relatório {relatorio}")

    dados = {}
    periodos_desde_save = 0

    for i, periodo_api in enumerate(periodos):
        if callback_progresso:
            callback_progresso(i, len(periodos), periodo_api)

        try:
            df = extrair_periodo(periodo_api, relatorio, dict_aliases)

            if df is not None and not df.empty:
                # Usar período de exibição como chave (formato "1/2024")
                periodo_exib = periodo_api_para_exibicao(periodo_api)
                dados[periodo_exib] = df
                periodos_desde_save += 1

                # Salvamento parcial
                if callback_salvamento and periodos_desde_save >= intervalo_salvamento:
                    info = f"Parcial até {periodo_exib}"
                    callback_salvamento(dados, info)
                    periodos_desde_save = 0
                    logger.info(f"Salvamento parcial: {len(dados)} períodos")
            else:
                logger.warning(f"Sem dados para {periodo_api}")

        except Exception as e:
            logger.error(f"Erro em {periodo_api}: {e}")

            # Salvamento de emergência
            if callback_salvamento and dados:
                try:
                    callback_salvamento(dados, f"Emergência após erro em {periodo_api}")
                except Exception:
                    pass

        # Rate limiting
        time.sleep(RATE_LIMIT_DELAY)

    # Salvamento final
    if callback_salvamento and periodos_desde_save > 0:
        periodo_ini = periodo_api_para_exibicao(periodos[0])
        periodo_fim = periodo_api_para_exibicao(periodos[-1])
        callback_salvamento(dados, f"Final: {periodo_ini} até {periodo_fim}")

    logger.info(f"Extração concluída: {len(dados)}/{len(periodos)} períodos")
    return dados


# =============================================================================
# FUNÇÕES AUXILIARES
# =============================================================================
def gerar_periodos(
    ano_inicial: int,
    trimestre_inicial: str,
    ano_final: int,
    trimestre_final: str
) -> List[str]:
    """Gera lista de períodos no formato da API (YYYYMM).

    Args:
        ano_inicial: Ano inicial
        trimestre_inicial: '03', '06', '09', ou '12'
        ano_final: Ano final
        trimestre_final: '03', '06', '09', ou '12'

    Returns:
        Lista de períodos ["202303", "202306", ...]
    """
    periodos = []
    trimestres = ['03', '06', '09', '12']

    ano = ano_inicial
    idx = trimestres.index(trimestre_inicial)

    while True:
        periodo = f"{ano}{trimestres[idx]}"
        periodos.append(periodo)

        if ano == ano_final and trimestres[idx] == trimestre_final:
            break

        idx += 1
        if idx >= len(trimestres):
            idx = 0
            ano += 1

        # Proteção contra loop infinito
        if ano > ano_final + 1:
            break

    return periodos
