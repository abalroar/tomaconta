"""
unified_extractor.py - Extrator unificado para todos os relatorios do IFData

Este modulo fornece uma interface comum para extrair dados de qualquer relatorio
da API Olinda do BCB, com suporte a:
- Logging detalhado de erros
- Retry com backoff exponencial
- Salvamento incremental
- Validacao de dados

Relatorios suportados:
- 1: Resumo (variáveis selecionadas)
- 2: Ativo (todas as variáveis)
- 3: Passivo (todas as variáveis)
- 4: Demonstração de Resultado (todas as variáveis)
- 5: Informações de Capital (variáveis selecionadas)
- 11: Carteira de crédito ativa PF - modalidade e prazo
- 13: Carteira de crédito ativa PJ - modalidade e prazo
- 16: Carteira de crédito ativa - Instrumentos 4.966 (C1-C5)
"""

import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd
import requests

# Configuracao de logging
logger = logging.getLogger("ifdata_unified_extractor")
logger.setLevel(logging.DEBUG)

if not logger.handlers:
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_format = logging.Formatter('[EXTRATOR] %(levelname)s: %(message)s')
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)

# =============================================================================
# CONSTANTES E CONFIGURACOES
# =============================================================================
BASE_URL = "https://olinda.bcb.gov.br/olinda/servico/IFDATA/versao/v1/odata"

# Mapeamento de relatorios disponíveis
RELATORIOS_INFO = {
    1: {
        "nome": "Resumo",
        "descricao": "Resumo geral das instituições financeiras",
        "todas_variaveis": False,
    },
    2: {
        "nome": "Ativo",
        "descricao": "Composição detalhada do ativo",
        "todas_variaveis": True,
    },
    3: {
        "nome": "Passivo",
        "descricao": "Composição detalhada do passivo",
        "todas_variaveis": True,
    },
    4: {
        "nome": "DRE",
        "descricao": "Demonstração de Resultado do Exercício",
        "todas_variaveis": True,
    },
    5: {
        "nome": "Capital",
        "descricao": "Informações de Capital Regulatório",
        "todas_variaveis": False,
    },
    11: {
        "nome": "Carteira PF",
        "descricao": "Carteira de crédito ativa PF - modalidade e prazo",
        "todas_variaveis": True,
    },
    13: {
        "nome": "Carteira PJ",
        "descricao": "Carteira de crédito ativa PJ - modalidade e prazo",
        "todas_variaveis": True,
    },
    16: {
        "nome": "Carteira Instrumentos 4.966",
        "descricao": "Carteira de crédito ativa - Instrumentos 4.966 (C1-C5)",
        "todas_variaveis": True,
    },
}

# Variaveis específicas para Resumo (Relatorio 1)
# Estas são as mesmas variáveis do cache principal atual
VARIAVEIS_RESUMO = [
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
    "Índice de Basileia",
    "Índice de Imobilização",
    "Número de Agências",
    "Número de Postos de Atendimento",
]

# Variaveis específicas para Capital (Relatorio 5)
# Estas são as mesmas variáveis do cache de capital atual
VARIAVEIS_CAPITAL = {
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


# =============================================================================
# CLASSE DE RESULTADOS E ERROS
# =============================================================================
class ExtractionResult:
    """Resultado de uma extração."""

    def __init__(
        self,
        sucesso: bool,
        mensagem: str,
        dados: Optional[pd.DataFrame] = None,
        erros: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.sucesso = sucesso
        self.mensagem = mensagem
        self.dados = dados
        self.erros = erros or []
        self.metadata = metadata or {}

    def __repr__(self):
        status = "OK" if self.sucesso else "ERRO"
        n = len(self.dados) if self.dados is not None else 0
        return f"ExtractionResult({status}, {n} registros, {len(self.erros)} erros)"


class ExtractionError(Exception):
    """Erro durante extração de dados."""

    def __init__(self, message: str, periodo: str = None, relatorio: int = None):
        self.message = message
        self.periodo = periodo
        self.relatorio = relatorio
        super().__init__(message)


# =============================================================================
# FUNCOES HTTP COM RETRY
# =============================================================================
def _fetch_json(
    url: str,
    timeout: int = 120,
    retries: int = 3,
    backoff: float = 2.0
) -> Optional[dict]:
    """Faz requisição HTTP com retry e backoff exponencial.

    Args:
        url: URL completa da API
        timeout: Timeout em segundos
        retries: Número máximo de tentativas
        backoff: Fator de backoff exponencial

    Returns:
        JSON parseado ou None

    Raises:
        ExtractionError: Se todas as tentativas falharem
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

            # Erros de servidor (5xx) - retry
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
            last_error = str(e)
            wait_time = backoff * (2 ** attempt)
            logger.warning(f"Timeout. Aguardando {wait_time:.1f}s...")
            time.sleep(wait_time)

        except requests.RequestException as e:
            last_error = str(e)
            if attempt >= retries:
                raise ExtractionError(f"Erro HTTP após {retries + 1} tentativas: {e}")
            wait_time = backoff * (2 ** attempt)
            logger.warning(f"Erro: {e}. Aguardando {wait_time:.1f}s...")
            time.sleep(wait_time)

        except ValueError as e:
            last_error = str(e)
            logger.error(f"Erro ao decodificar JSON: {e}")
            if attempt >= retries:
                raise ExtractionError(f"Erro JSON: {e}")
            time.sleep(backoff * (attempt + 1))

    raise ExtractionError(f"Falha após {retries + 1} tentativas: {last_error}")


# =============================================================================
# FUNCOES DE EXTRACAO
# =============================================================================
def normalizar_nome_coluna(valor: str) -> str:
    """Normaliza nome de coluna removendo espaços extras."""
    if not isinstance(valor, str):
        return valor
    return " ".join(valor.split())


def extrair_cadastro(periodo: str) -> pd.DataFrame:
    """Extrai cadastro de instituições para um período.

    Args:
        periodo: Período no formato YYYYMM

    Returns:
        DataFrame com CodInst, NomeInstituicao e outros campos
    """
    url = f"{BASE_URL}/IfDataCadastro(AnoMes={int(periodo)})?$format=json&$top=5000"

    logger.info(f"Extraindo cadastro para período {periodo}")

    try:
        data = _fetch_json(url, timeout=60)
        df = pd.DataFrame((data or {}).get("value", []))

        if df.empty:
            logger.warning(f"Cadastro vazio para período {periodo}")
        else:
            logger.info(f"Cadastro {periodo}: {len(df)} registros")

        return df

    except ExtractionError as e:
        logger.error(f"Falha ao extrair cadastro {periodo}: {e}")
        return pd.DataFrame()


def extrair_valores(
    periodo: str,
    relatorio: int,
    tipo_instituicao: int = 1
) -> pd.DataFrame:
    """Extrai valores de um relatório específico.

    Args:
        periodo: Período no formato YYYYMM
        relatorio: Número do relatório (1, 2, 3, 4, 5, 11, 13, 16)
        tipo_instituicao: Tipo de instituição (default: 1 = Conglomerados Prudenciais)

    Returns:
        DataFrame com CodInst, NomeColuna, Saldo e outros campos
    """
    url = (
        f"{BASE_URL}/IfDataValores("
        f"AnoMes={int(periodo)},"
        f"TipoInstituicao={tipo_instituicao},"
        f"Relatorio='{relatorio}'"
        f")?$format=json&$top=500000"
    )

    logger.info(f"Extraindo valores - período {periodo}, relatório {relatorio}")

    try:
        data = _fetch_json(url, timeout=180)
        df = pd.DataFrame((data or {}).get("value", []))

        if df.empty:
            logger.warning(f"Valores vazios para período {periodo}, relatório {relatorio}")
        else:
            n_inst = df["CodInst"].nunique() if "CodInst" in df.columns else 0
            n_cols = df["NomeColuna"].nunique() if "NomeColuna" in df.columns else 0
            logger.info(f"Valores {periodo} rel.{relatorio}: {len(df)} registros, {n_inst} instituições, {n_cols} colunas")

        return df

    except ExtractionError as e:
        logger.error(f"Falha ao extrair valores {periodo} rel.{relatorio}: {e}")
        return pd.DataFrame()


# =============================================================================
# PROCESSAMENTO DE DADOS
# =============================================================================
def processar_periodo(
    periodo: str,
    relatorio: int,
    variaveis_filtro: Optional[List[str]] = None,
    mapeamento_colunas: Optional[Dict[str, str]] = None,
    dict_aliases: Optional[Dict[str, str]] = None
) -> ExtractionResult:
    """Processa dados de um período para um relatório específico.

    Args:
        periodo: Período no formato YYYYMM
        relatorio: Número do relatório
        variaveis_filtro: Lista de variáveis a filtrar (None = todas)
        mapeamento_colunas: Dicionário de renomeação de colunas
        dict_aliases: Dicionário de aliases para instituições

    Returns:
        ExtractionResult com dados ou erro
    """
    logger.info(f"Processando período {periodo}, relatório {relatorio}")
    erros = []

    try:
        # 1. Extrair cadastro
        df_cad = extrair_cadastro(periodo)

        # 2. Extrair valores
        df_valores = extrair_valores(periodo, relatorio)

        if df_valores.empty:
            return ExtractionResult(
                sucesso=False,
                mensagem=f"Sem dados para período {periodo}, relatório {relatorio}",
                erros=[f"Valores vazios para {periodo}"]
            )

        # 3. Normalizar nomes de colunas
        if "NomeColuna" in df_valores.columns:
            df_valores["NomeColuna"] = df_valores["NomeColuna"].apply(normalizar_nome_coluna)

        # 4. Filtrar variáveis se especificado
        if variaveis_filtro:
            # Normalizar filtro também
            filtro_normalizado = [normalizar_nome_coluna(v) for v in variaveis_filtro]
            df_valores = df_valores[df_valores["NomeColuna"].isin(filtro_normalizado)].copy()

            if df_valores.empty:
                return ExtractionResult(
                    sucesso=False,
                    mensagem=f"Nenhuma variável encontrada após filtro",
                    erros=[f"Variáveis não encontradas: {variaveis_filtro[:5]}..."]
                )

        # 5. Pivotar dados
        df_pivot = df_valores.pivot_table(
            index="CodInst",
            columns="NomeColuna",
            values="Saldo",
            aggfunc="sum"
        ).reset_index()
        df_pivot.columns.name = None

        # 6. Aplicar mapeamento de colunas se especificado
        if mapeamento_colunas:
            # Normalizar chaves do mapeamento
            mapeamento_normalizado = {
                normalizar_nome_coluna(k): v
                for k, v in mapeamento_colunas.items()
            }
            colunas_para_renomear = {
                col: mapeamento_normalizado[col]
                for col in df_pivot.columns
                if col in mapeamento_normalizado
            }
            df_pivot = df_pivot.rename(columns=colunas_para_renomear)

        # 7. Adicionar nomes de instituições
        if not df_cad.empty and "CodInst" in df_cad.columns:
            # Encontrar coluna de nome
            col_nome = None
            for candidato in ["NomeInstituicao", "NomeInstituição"]:
                if candidato in df_cad.columns:
                    col_nome = candidato
                    break

            if col_nome:
                df_nomes = df_cad[["CodInst", col_nome]].drop_duplicates()
                df_nomes = df_nomes.rename(columns={col_nome: "NomeInstituicao"})
                df_pivot = df_pivot.merge(df_nomes, on="CodInst", how="left")

        # 8. Preencher nomes faltantes
        if "NomeInstituicao" not in df_pivot.columns:
            df_pivot["NomeInstituicao"] = df_pivot["CodInst"].apply(lambda x: f"[IF {x}]")
        else:
            df_pivot["NomeInstituicao"] = df_pivot.apply(
                lambda row: row["NomeInstituicao"] if pd.notna(row["NomeInstituicao"])
                else f"[IF {row['CodInst']}]",
                axis=1
            )

        # 9. Preservar nome oficial da fonte; alias foi removido do pipeline.

        # 10. Adicionar período
        df_pivot["Periodo"] = periodo

        # 11. Reordenar colunas
        cols_inicio = ["Periodo", "CodInst", "NomeInstituicao"]
        outras_cols = sorted([c for c in df_pivot.columns if c not in cols_inicio])
        df_pivot = df_pivot[cols_inicio + outras_cols]

        # 12. Remover linhas sem dados numéricos
        colunas_numericas = [c for c in df_pivot.columns if c not in cols_inicio]
        if colunas_numericas:
            df_pivot = df_pivot.dropna(subset=colunas_numericas, how="all")

        logger.info(f"Período {periodo} rel.{relatorio}: {len(df_pivot)} instituições processadas")

        return ExtractionResult(
            sucesso=True,
            mensagem=f"Extraído {periodo}: {len(df_pivot)} registros, {len(colunas_numericas)} colunas",
            dados=df_pivot,
            metadata={
                "periodo": periodo,
                "relatorio": relatorio,
                "n_registros": len(df_pivot),
                "n_colunas": len(colunas_numericas),
                "colunas": colunas_numericas
            }
        )

    except Exception as e:
        logger.error(f"Erro ao processar {periodo} rel.{relatorio}: {e}")
        return ExtractionResult(
            sucesso=False,
            mensagem=f"Erro: {e}",
            erros=[str(e)]
        )


def processar_multiplos_periodos(
    periodos: List[str],
    relatorio: int,
    variaveis_filtro: Optional[List[str]] = None,
    mapeamento_colunas: Optional[Dict[str, str]] = None,
    dict_aliases: Optional[Dict[str, str]] = None,
    callback_progresso: Optional[Callable[[int, int, str], None]] = None,
    callback_salvamento: Optional[Callable[[pd.DataFrame, str], None]] = None,
    intervalo_salvamento: int = 4
) -> ExtractionResult:
    """Processa múltiplos períodos de um relatório.

    Args:
        periodos: Lista de períodos no formato YYYYMM
        relatorio: Número do relatório
        variaveis_filtro: Lista de variáveis a filtrar
        mapeamento_colunas: Dicionário de renomeação
        dict_aliases: Dicionário de aliases
        callback_progresso: Função(i, total, periodo) chamada a cada período
        callback_salvamento: Função(df, info) para salvamento parcial
        intervalo_salvamento: Salvar a cada N períodos (default: 4)

    Returns:
        ExtractionResult com todos os dados concatenados
    """
    logger.info(f"Iniciando extração de {len(periodos)} períodos, relatório {relatorio}")

    todos_dados = []
    todos_erros = []
    periodos_desde_save = 0

    for i, periodo in enumerate(periodos):
        # Callback de progresso
        if callback_progresso:
            callback_progresso(i, len(periodos), periodo)

        # Processar período
        resultado = processar_periodo(
            periodo=periodo,
            relatorio=relatorio,
            variaveis_filtro=variaveis_filtro,
            mapeamento_colunas=mapeamento_colunas,
            dict_aliases=dict_aliases
        )

        if resultado.sucesso and resultado.dados is not None:
            todos_dados.append(resultado.dados)
            periodos_desde_save += 1

            # Salvamento parcial
            if callback_salvamento and periodos_desde_save >= intervalo_salvamento:
                try:
                    df_parcial = pd.concat(todos_dados, ignore_index=True)
                    info = f"Salvamento parcial até {periodo[4:6]}/{periodo[:4]} ({len(todos_dados)} períodos)"
                    callback_salvamento(df_parcial, info)
                    periodos_desde_save = 0
                    logger.info(f"Salvamento parcial: {len(todos_dados)} períodos")
                except Exception as e:
                    logger.warning(f"Erro no salvamento parcial: {e}")
                    todos_erros.append(f"Erro salvamento parcial: {e}")
        else:
            todos_erros.extend(resultado.erros)
            logger.warning(f"Falha em {periodo}: {resultado.mensagem}")

        # Rate limiting
        time.sleep(1.5)

    # Resultado final
    if not todos_dados:
        return ExtractionResult(
            sucesso=False,
            mensagem=f"Nenhum período extraído com sucesso",
            erros=todos_erros
        )

    df_final = pd.concat(todos_dados, ignore_index=True)

    # Salvamento final
    if callback_salvamento and periodos_desde_save > 0:
        try:
            info = f"Salvamento final: {periodos[0][4:6]}/{periodos[0][:4]} até {periodos[-1][4:6]}/{periodos[-1][:4]}"
            callback_salvamento(df_final, info)
            logger.info(f"Salvamento final: {len(todos_dados)} períodos")
        except Exception as e:
            logger.warning(f"Erro no salvamento final: {e}")
            todos_erros.append(f"Erro salvamento final: {e}")

    logger.info(f"Extração concluída: {len(todos_dados)}/{len(periodos)} períodos, {len(df_final)} registros")

    return ExtractionResult(
        sucesso=True,
        mensagem=f"Extraídos {len(todos_dados)}/{len(periodos)} períodos, {len(df_final)} registros",
        dados=df_final,
        erros=todos_erros,
        metadata={
            "periodos_extraidos": len(todos_dados),
            "periodos_total": len(periodos),
            "total_registros": len(df_final),
            "relatorio": relatorio
        }
    )


# =============================================================================
# FUNCOES DE CONVENIENCIA
# =============================================================================
def gerar_periodos_trimestrais(
    ano_inicial: int,
    mes_inicial: str,
    ano_final: int,
    mes_final: str
) -> List[str]:
    """Gera lista de períodos trimestrais.

    Args:
        ano_inicial: Ano inicial
        mes_inicial: Mês inicial ('03', '06', '09', '12')
        ano_final: Ano final
        mes_final: Mês final ('03', '06', '09', '12')

    Returns:
        Lista de períodos no formato YYYYMM
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


def get_info_relatorio(relatorio: int) -> Dict[str, Any]:
    """Retorna informações sobre um relatório."""
    return RELATORIOS_INFO.get(relatorio, {
        "nome": f"Relatório {relatorio}",
        "descricao": "Relatório desconhecido",
        "todas_variaveis": True
    })


def listar_relatorios_disponiveis() -> List[Dict[str, Any]]:
    """Lista todos os relatórios disponíveis."""
    return [
        {"numero": num, **info}
        for num, info in RELATORIOS_INFO.items()
    ]
