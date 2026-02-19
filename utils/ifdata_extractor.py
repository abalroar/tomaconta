import requests
import pandas as pd
import numpy as np
import time
import logging
import re
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List

# =============================================================================
# CONFIGURAÇÃO DE LOGGING PARA DEPURAÇÃO DE NOMES DE INSTITUIÇÕES
# =============================================================================
LOG_DIR = Path(__file__).parent.parent / "data" / "logs"
LOG_FILE = None

# Configurar logger
logger = logging.getLogger("ifdata_extractor")
logger.setLevel(logging.DEBUG)

# Handler para console (sempre funciona)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_format = logging.Formatter('%(levelname)s: %(message)s')
console_handler.setFormatter(console_format)
logger.addHandler(console_handler)

# Handler para arquivo (opcional - pode falhar em ambientes read-only como Streamlit Cloud)
try:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    LOG_FILE = LOG_DIR / f"ifdata_extraction_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    file_handler = logging.FileHandler(LOG_FILE, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_format = logging.Formatter('%(asctime)s | %(levelname)s | %(funcName)s | %(message)s')
    file_handler.setFormatter(file_format)
    logger.addHandler(file_handler)
except (OSError, PermissionError):
    # Em ambientes read-only, usar apenas console
    pass

# =============================================================================
# CONFIGURAÇÕES E CONSTANTES
# =============================================================================
BASE_URL = "https://olinda.bcb.gov.br/olinda/servico/IFDATA/versao/v1/odata"
FALLBACK_FILE = Path(__file__).parent.parent / "data" / "instituicoes_fallback.json"

# Cache de lucros por período (otimização de chamadas)
cache_lucros = {}

# CACHE GLOBAL DE NOMES DE INSTITUIÇÕES
# Mapeia CodInst (várias variantes) -> NomeInstituicao "humano" (limpo)
# Este cache é preenchido progressivamente conforme dados são extraídos
_cache_nomes_instituicoes = {}
_cache_nomes_carregado = False
_fallback_carregado = False

# Período de referência para cadastro de nomes (será atualizado dinamicamente)
_periodo_referencia_cadastro = None


def _carregar_fallback_nomes():
    """Carrega mapeamento de nomes do arquivo de fallback estático."""
    global _cache_nomes_instituicoes, _fallback_carregado

    if _fallback_carregado:
        return

    if not FALLBACK_FILE.exists():
        logger.warning(f"[FALLBACK] Arquivo não encontrado: {FALLBACK_FILE}")
        _fallback_carregado = True
        return

    try:
        import json
        with open(FALLBACK_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)

        count = 0
        for codigo, nome in data.items():
            if codigo.startswith('_'):  # Ignorar metadados
                continue
            # Adicionar variantes do código
            _adicionar_ao_cache_nomes(codigo, nome)
            count += 1

        logger.info(f"[FALLBACK] Carregadas {count} instituições do arquivo de fallback")
        _fallback_carregado = True

    except Exception as e:
        logger.error(f"[FALLBACK] Erro ao carregar arquivo: {e}")
        _fallback_carregado = True


# =============================================================================
# FUNÇÕES DE LOGGING E DIAGNÓSTICO
# =============================================================================
def log_api_request(endpoint: str, params: dict, status_code: int = None,
                    error: str = None, response_count: int = None):
    """Registra detalhes de uma chamada à API do Olinda."""
    msg = f"[API] {endpoint}"
    if params:
        msg += f" | params={params}"
    if status_code is not None:
        msg += f" | status={status_code}"
    if response_count is not None:
        msg += f" | registros={response_count}"
    if error:
        msg += f" | ERRO: {error}"
        logger.error(msg)
    else:
        logger.debug(msg)


def log_nome_resolution(codinst: str, nome_original: str, nome_final: str,
                        fonte: str, periodo: str = None):
    """Registra o processo de resolução de nome de uma instituição."""
    mudou = nome_original != nome_final
    status = "ALTERADO" if mudou else "mantido"
    periodo_str = f" (período {periodo})" if periodo else ""
    logger.debug(f"[NOME] CodInst={codinst}{periodo_str} | original='{nome_original}' | final='{nome_final}' | fonte={fonte} | {status}")


def log_nome_warning(codinst: str, nome: str, motivo: str, periodo: str = None):
    """Registra aviso sobre nome problemático (código no lugar de nome)."""
    periodo_str = f" (período {periodo})" if periodo else ""
    logger.warning(f"[NOME SUSPEITO] CodInst={codinst}{periodo_str} | valor='{nome}' | motivo={motivo}")


def diagnosticar_nomes(df: pd.DataFrame, coluna_nome: str = "Instituição", periodo: str = None):
    """Analisa e loga diagnóstico de qualidade dos nomes em um DataFrame."""
    if df.empty or coluna_nome not in df.columns:
        return

    nomes = df[coluna_nome].dropna()
    total = len(nomes)

    # Detectar nomes suspeitos (parecem códigos)
    suspeitos = nomes[nomes.apply(parece_codigo_instituicao)]
    n_suspeitos = len(suspeitos)

    periodo_str = f" período {periodo}" if periodo else ""

    logger.info(f"[DIAGNÓSTICO{periodo_str}] Total nomes: {total} | Suspeitos (parecem código): {n_suspeitos} ({100*n_suspeitos/max(total,1):.1f}%)")

    if n_suspeitos > 0:
        exemplos = suspeitos.head(5).tolist()
        logger.warning(f"[DIAGNÓSTICO] Exemplos de nomes suspeitos: {exemplos}")


def get_log_file_path() -> Optional[str]:
    """Retorna o caminho do arquivo de log atual, ou None se não disponível."""
    return str(LOG_FILE) if LOG_FILE else None


# =============================================================================
# FUNÇÕES DE DETECÇÃO E NORMALIZAÇÃO
# =============================================================================
def parece_codigo_instituicao(valor) -> bool:
    """Verifica se um valor parece ser um código em vez de um nome de instituição.

    Códigos típicos:
    - Números puros: "123", "1234567"
    - C-prefixados: "C123", "C0001234"
    - Zero-padded: "0000123"
    - Combinações: "123_nome", "CODINST:123"
    """
    if pd.isna(valor):
        return True

    s = str(valor).strip()

    # Vazio = suspeito
    if not s:
        return True

    # Número puro
    if s.isdigit():
        return True

    # Padrão C + dígitos (com ou sem zeros à esquerda)
    if re.match(r'^C\d+$', s, re.IGNORECASE):
        return True

    # Começa com dígitos seguido de separador (ex: "123_", "123-", "123 ")
    if re.match(r'^\d+[\s_\-\.:]', s):
        return True

    # String muito curta (menos de 3 chars) e numérica
    if len(s) <= 3 and any(c.isdigit() for c in s):
        return True

    # Predominantemente numérico (>70% dígitos)
    digitos = sum(c.isdigit() for c in s)
    if len(s) > 0 and digitos / len(s) > 0.7:
        return True

    return False


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


# =============================================================================
# CACHE GLOBAL DE NOMES DE INSTITUIÇÕES
# =============================================================================
def _adicionar_ao_cache_nomes(codinst, nome: str):
    """Adiciona um mapeamento CodInst -> Nome ao cache global.

    Gera múltiplas variantes de chave para o mesmo código:
    - Número puro: "123"
    - Zero-padded 7 dígitos: "0000123"
    - C-prefixado: "C123"
    - C-prefixado + padded: "C0000123"
    """
    global _cache_nomes_instituicoes

    if pd.isna(codinst) or pd.isna(nome):
        return

    cod_str = str(codinst).strip()
    nome_str = str(nome).strip()

    # Não cachear se o "nome" parece ser um código
    if parece_codigo_instituicao(nome_str):
        return

    # Gerar variantes de chave
    chaves = {cod_str}

    # Extrair número base se for C-prefixado
    if cod_str.upper().startswith('C'):
        num_base = cod_str[1:]
        chaves.add(num_base)
    else:
        num_base = cod_str

    # Se for numérico, gerar variantes
    if num_base.isdigit():
        cod_pad = num_base.zfill(7)
        chaves.update({
            num_base,           # "123"
            cod_pad,            # "0000123"
            f"C{num_base}",     # "C123"
            f"C{cod_pad}",      # "C0000123"
        })

    # Adicionar ao cache
    for chave in chaves:
        if chave not in _cache_nomes_instituicoes:
            _cache_nomes_instituicoes[chave] = nome_str
            logger.debug(f"[CACHE] Adicionado: '{chave}' -> '{nome_str}'")


def _buscar_no_cache_nomes(codinst) -> Optional[str]:
    """Busca um nome no cache global a partir do CodInst."""
    if pd.isna(codinst):
        return None

    cod_str = str(codinst).strip()

    # Tentar lookup direto
    if cod_str in _cache_nomes_instituicoes:
        return _cache_nomes_instituicoes[cod_str]

    # Tentar variantes
    chaves_tentativas = [cod_str]

    if cod_str.upper().startswith('C'):
        num_base = cod_str[1:]
        chaves_tentativas.append(num_base)
    else:
        num_base = cod_str

    if num_base.isdigit():
        cod_pad = num_base.zfill(7)
        chaves_tentativas.extend([
            num_base, cod_pad, f"C{num_base}", f"C{cod_pad}"
        ])

    for chave in chaves_tentativas:
        if chave in _cache_nomes_instituicoes:
            return _cache_nomes_instituicoes[chave]

    return None


def carregar_cache_nomes_de_cadastro(ano_mes: str = None) -> int:
    """Carrega o cache de nomes a partir do endpoint de cadastro.

    Args:
        ano_mes: Período no formato YYYYMM. Se None, usa o período mais recente disponível.

    Returns:
        Número de instituições carregadas no cache.
    """
    global _cache_nomes_carregado, _periodo_referencia_cadastro

    if ano_mes is None:
        # Tentar período atual ou recente
        from datetime import datetime
        now = datetime.now()
        # Usar último trimestre disponível
        if now.month >= 10:
            ano_mes = f"{now.year}09"
        elif now.month >= 7:
            ano_mes = f"{now.year}06"
        elif now.month >= 4:
            ano_mes = f"{now.year}03"
        else:
            ano_mes = f"{now.year - 1}12"

    logger.info(f"[CACHE] Carregando cache de nomes a partir do cadastro período {ano_mes}")

    df_cad = extrair_cadastro(ano_mes)
    if df_cad.empty:
        logger.warning(f"[CACHE] Cadastro vazio para período {ano_mes}")
        return 0

    coluna_nome = obter_coluna_nome_instituicao(df_cad)
    if not coluna_nome or "CodInst" not in df_cad.columns:
        logger.warning(f"[CACHE] Colunas necessárias não encontradas no cadastro")
        return 0

    count = 0
    for _, row in df_cad.iterrows():
        codinst = row.get("CodInst")
        nome = row.get(coluna_nome)
        if pd.notna(codinst) and pd.notna(nome) and not parece_codigo_instituicao(nome):
            _adicionar_ao_cache_nomes(codinst, nome)
            count += 1

    _cache_nomes_carregado = True
    _periodo_referencia_cadastro = ano_mes
    logger.info(f"[CACHE] Cache de nomes carregado: {count} instituições de {ano_mes}")

    return count


def construir_mapa_codinst(ano_mes: str) -> dict:
    """Constrói mapa de CodInst -> Nome para resolução de códigos.

    Este mapa é usado para converter códigos numéricos em nomes de instituições.
    Combina dados do cache global com dados frescos do período especificado.
    """
    global _cache_nomes_instituicoes

    logger.info(f"[MAPA] Construindo mapa CodInst para período {ano_mes}")

    # Garantir que o cache global está preenchido
    if not _cache_nomes_carregado:
        carregar_cache_nomes_de_cadastro(ano_mes)

    # Também carregar dados específicos do período solicitado
    df_cad = extrair_cadastro(ano_mes)
    if not df_cad.empty:
        coluna_nome = obter_coluna_nome_instituicao(df_cad)
        if coluna_nome and "CodInst" in df_cad.columns:
            for _, row in df_cad.iterrows():
                _adicionar_ao_cache_nomes(row.get("CodInst"), row.get(coluna_nome))

    # Retornar cópia do cache
    mapa = dict(_cache_nomes_instituicoes)
    logger.info(f"[MAPA] Mapa construído com {len(mapa)} entradas")

    return mapa


def construir_mapa_codinst_multiperiodo(periodos: list) -> dict:
    """Constrói mapa de nomes a partir de múltiplos períodos.

    Útil para garantir cobertura máxima quando alguns períodos têm dados incompletos.
    Prioriza dados de períodos mais recentes.
    """
    logger.info(f"[MAPA] Construindo mapa multi-período com {len(periodos)} períodos")

    # Ordenar períodos do mais antigo ao mais recente (mais recente sobrescreve)
    periodos_ordenados = sorted(periodos)

    for periodo in periodos_ordenados:
        try:
            df_cad = extrair_cadastro(periodo)
            if not df_cad.empty:
                coluna_nome = obter_coluna_nome_instituicao(df_cad)
                if coluna_nome and "CodInst" in df_cad.columns:
                    count = 0
                    for _, row in df_cad.iterrows():
                        codinst = row.get("CodInst")
                        nome = row.get(coluna_nome)
                        if pd.notna(codinst) and pd.notna(nome) and not parece_codigo_instituicao(nome):
                            _adicionar_ao_cache_nomes(codinst, nome)
                            count += 1
                    logger.debug(f"[MAPA] Período {periodo}: {count} nomes carregados")
        except Exception as e:
            logger.warning(f"[MAPA] Erro ao carregar período {periodo}: {e}")
            continue

    mapa = dict(_cache_nomes_instituicoes)
    logger.info(f"[MAPA] Mapa multi-período construído com {len(mapa)} entradas")

    return mapa


def resolver_nome_instituicao(codinst, nome_atual: str = None, periodo: str = None) -> str:
    """Resolve o nome "humano" de uma instituição a partir do código.

    Ordem de resolução:
    1. Se nome_atual já é um nome válido (não parece código), mantém
    2. Busca no cache global de nomes (inclui fallback estático)
    3. Se não encontrar, retorna placeholder com logging para diagnóstico

    IMPORTANTE: Nunca retorna o CodInst como nome. Se não conseguir resolver,
    retorna "[IF {codigo}]" com logging para diagnóstico.
    """
    # Se nome atual é válido, usar
    if nome_atual and not parece_codigo_instituicao(nome_atual):
        log_nome_resolution(str(codinst), nome_atual, nome_atual, "original_valido", periodo)
        return nome_atual

    # Garantir que o fallback está carregado
    _carregar_fallback_nomes()

    # Tentar cache (agora inclui dados do fallback)
    nome_cache = _buscar_no_cache_nomes(codinst)
    if nome_cache:
        log_nome_resolution(str(codinst), str(nome_atual), nome_cache, "cache_global", periodo)
        return nome_cache

    # Não encontrou - logar aviso e retornar placeholder
    log_nome_warning(str(codinst), str(nome_atual), "nome_nao_resolvido", periodo)

    # Retornar placeholder descritivo em vez de código
    return f"[IF {codinst}]"


# =============================================================================
# FUNÇÕES DE EXTRAÇÃO DE DADOS DA API OLINDA
# =============================================================================
def _fetch_json(url: str, timeout: int, retries: int = 3, backoff: float = 2.0):
    """Faz requisição HTTP com retry e backoff exponencial.

    Args:
        url: URL completa da API
        timeout: Timeout em segundos para a requisição
        retries: Número máximo de tentativas (padrão: 3)
        backoff: Fator de backoff exponencial (padrão: 2.0)

    Returns:
        JSON parseado da resposta ou None em caso de erro

    Raises:
        requests.RequestException: Se todas as tentativas falharem
    """
    last_error = None

    for attempt in range(retries + 1):
        try:
            logger.debug(f"[HTTP] Tentativa {attempt + 1}/{retries + 1}: {url[:100]}...")
            response = requests.get(url, timeout=timeout)

            log_api_request(
                endpoint=url.split('?')[0].split('/')[-1],
                params={"url_truncated": url[:150]},
                status_code=response.status_code
            )

            # Rate limit (429) - esperar mais tempo
            if response.status_code == 429:
                wait_time = backoff * (2 ** attempt) * 2  # Dobrar o tempo para rate limit
                logger.warning(f"[HTTP] Rate limit (429). Aguardando {wait_time:.1f}s...")
                time.sleep(wait_time)
                continue

            # Erros de servidor (5xx) - retry com backoff
            if response.status_code >= 500:
                wait_time = backoff * (2 ** attempt)
                logger.warning(f"[HTTP] Erro servidor ({response.status_code}). Aguardando {wait_time:.1f}s...")
                time.sleep(wait_time)
                continue

            response.raise_for_status()
            data = response.json()

            record_count = len(data.get("value", [])) if isinstance(data, dict) else 0
            log_api_request(
                endpoint=url.split('?')[0].split('/')[-1],
                params={},
                status_code=response.status_code,
                response_count=record_count
            )

            return data

        except requests.Timeout as e:
            last_error = e
            wait_time = backoff * (2 ** attempt)
            logger.warning(f"[HTTP] Timeout. Tentativa {attempt + 1}/{retries + 1}. Aguardando {wait_time:.1f}s...")
            time.sleep(wait_time)

        except requests.RequestException as e:
            last_error = e
            log_api_request(
                endpoint=url.split('?')[0].split('/')[-1],
                params={"url_truncated": url[:150]},
                error=str(e)
            )
            if attempt >= retries:
                raise
            wait_time = backoff * (2 ** attempt)
            logger.warning(f"[HTTP] Erro: {e}. Aguardando {wait_time:.1f}s...")
            time.sleep(wait_time)

        except ValueError as e:
            # JSON decode error
            last_error = e
            logger.error(f"[HTTP] Erro ao decodificar JSON: {e}")
            if attempt >= retries:
                raise
            time.sleep(backoff * (attempt + 1))

    if last_error:
        raise last_error
    return None


def extrair_cadastro(ano_mes: str) -> pd.DataFrame:
    """Extrai dados de cadastro das instituições financeiras.

    Endpoint: IfDataCadastro
    Retorna: DataFrame com CodInst, NomeInstituicao e outros campos de cadastro
    """
    url = f"{BASE_URL}/IfDataCadastro(AnoMes={int(ano_mes)})?$format=json&$top=5000"

    logger.info(f"[EXTRAÇÃO] Extraindo cadastro para período {ano_mes}")

    try:
        data = _fetch_json(url, timeout=60, retries=3, backoff=2.0)
        df = pd.DataFrame((data or {}).get("value", []))

        if df.empty:
            logger.warning(f"[EXTRAÇÃO] Cadastro vazio para período {ano_mes}")
        else:
            coluna_nome = obter_coluna_nome_instituicao(df)
            logger.info(f"[EXTRAÇÃO] Cadastro {ano_mes}: {len(df)} registros, coluna_nome='{coluna_nome}'")

            # Adicionar ao cache global de nomes
            if coluna_nome and "CodInst" in df.columns:
                for _, row in df.iterrows():
                    _adicionar_ao_cache_nomes(row.get("CodInst"), row.get(coluna_nome))

        return df

    except requests.RequestException as e:
        logger.error(f"[EXTRAÇÃO] Falha ao extrair cadastro {ano_mes}: {e}")
        return pd.DataFrame()


def extrair_valores(ano_mes: str) -> pd.DataFrame:
    """Extrai valores financeiros das instituições.

    Endpoint: IfDataValores
    Retorna: DataFrame com CodInst, NomeColuna, Saldo e outros campos
    """
    url = (
        f"{BASE_URL}/IfDataValores("
        f"AnoMes={int(ano_mes)},"
        f"TipoInstituicao=1,"
        f"Relatorio='1'"
        f")?$format=json&$top=200000"
    )

    logger.info(f"[EXTRAÇÃO] Extraindo valores para período {ano_mes}")

    try:
        data = _fetch_json(url, timeout=120, retries=3, backoff=2.0)
        df = pd.DataFrame((data or {}).get("value", []))

        if df.empty:
            logger.warning(f"[EXTRAÇÃO] Valores vazio para período {ano_mes}")
        else:
            n_instituicoes = df["CodInst"].nunique() if "CodInst" in df.columns else 0
            logger.info(f"[EXTRAÇÃO] Valores {ano_mes}: {len(df)} registros, {n_instituicoes} instituições")

        return df

    except requests.RequestException as e:
        logger.error(f"[EXTRAÇÃO] Falha ao extrair valores {ano_mes}: {e}")
        return pd.DataFrame()


def extrair_lucro_periodo(ano_mes: str) -> pd.DataFrame:
    """Extrai lucro líquido das instituições (com cache)."""
    if ano_mes in cache_lucros:
        logger.debug(f"[CACHE] Lucro {ano_mes} encontrado em cache")
        return cache_lucros[ano_mes]

    url = (
        f"{BASE_URL}/IfDataValores("
        f"AnoMes={int(ano_mes)},"
        f"TipoInstituicao=1,"
        f"Relatorio='1'"
        f")?$format=json&$top=200000"
    )

    try:
        data = _fetch_json(url, timeout=120, retries=3, backoff=2.0)
    except requests.RequestException:
        return pd.DataFrame()

    df = pd.DataFrame((data or {}).get("value", []))
    if df.empty:
        return pd.DataFrame()

    df_lucro = df[df["NomeColuna"] == "Lucro Líquido"].copy()
    df_lucro = df_lucro.groupby("CodInst")["Saldo"].sum().reset_index()
    df_lucro.columns = ["CodInst", "Lucro Líquido Acumulado YTD"]

    cache_lucros[ano_mes] = df_lucro
    return df_lucro


# =============================================================================
# FUNÇÕES DE CÁLCULO E PROCESSAMENTO
# =============================================================================
def calcular_lucro_semestral(ano_mes: str, df_pivot: pd.DataFrame) -> pd.DataFrame:
    """Ajusta lucro para acumulado semestral/anual conforme o trimestre."""
    ano = ano_mes[:4]
    mes = ano_mes[4:6]
    df_result = df_pivot.copy()

    if mes == "09":
        periodo_anterior = f"{ano}06"
        df_lucro_anterior = extrair_lucro_periodo(periodo_anterior)

        if not df_lucro_anterior.empty and "Lucro Líquido Acumulado YTD" in df_result.columns:
            df_result = df_result.merge(
                df_lucro_anterior, on="CodInst", how="left", suffixes=("", "_06")
            )
            df_result["Lucro Líquido Acumulado YTD"] = (
                df_result["Lucro Líquido Acumulado YTD"].fillna(0) +
                df_result["Lucro Líquido Acumulado YTD_06"].fillna(0)
            )
            df_result = df_result.drop(columns=["Lucro Líquido Acumulado YTD_06"], errors="ignore")

    elif mes == "12":
        periodo_anterior = f"{ano}09"
        df_lucro_anterior = extrair_lucro_periodo(periodo_anterior)

        if not df_lucro_anterior.empty and "Lucro Líquido Acumulado YTD" in df_result.columns:
            df_result = df_result.merge(
                df_lucro_anterior, on="CodInst", how="left", suffixes=("", "_09")
            )
            df_result["Lucro Líquido Acumulado YTD"] = (
                df_result["Lucro Líquido Acumulado YTD"].fillna(0) +
                df_result["Lucro Líquido Acumulado YTD_09"].fillna(0)
            )
            df_result = df_result.drop(columns=["Lucro Líquido Acumulado YTD_09"], errors="ignore")

    return df_result


def aplicar_aliases(df: pd.DataFrame, dict_aliases: dict) -> pd.DataFrame:
    """Aplica dicionário de aliases aos nomes de instituições."""
    df = df.copy()
    df['Instituição'] = df['Instituição'].apply(
        lambda x: dict_aliases.get(x, x) if pd.notna(x) else x
    )
    return df


def processar_periodo(ano_mes: str, dict_aliases: dict) -> pd.DataFrame:
    """Processa dados de um período específico.

    Esta função:
    1. Extrai cadastro (para nomes) e valores (para métricas financeiras)
    2. Resolve nomes de instituições usando múltiplas fontes
    3. Calcula métricas derivadas (ROE, ratios, etc.)
    4. Aplica aliases para nomes amigáveis

    IMPORTANTE: Nunca usa CodInst como nome. Se não conseguir resolver,
    usa placeholder "[IF {codigo}]" com logging para diagnóstico.
    """
    logger.info(f"[PROCESSAMENTO] Iniciando período {ano_mes}")

    # 1. Extrair dados
    df_cad = extrair_cadastro(ano_mes)
    df_valores = extrair_valores(ano_mes)

    if df_valores.empty:
        logger.warning(f"[PROCESSAMENTO] Sem valores para período {ano_mes}")
        return None

    if "NomeColuna" in df_valores.columns:
        df_valores["NomeColuna"] = df_valores["NomeColuna"].map(normalizar_nome_coluna)

    # 2. Preparar dados de nomes
    # Prioridade: cadastro > valores > cache global > placeholder

    nome_col_valores = obter_coluna_nome_instituicao(df_valores)
    if nome_col_valores:
        df_nomes = df_valores[["CodInst", nome_col_valores]].drop_duplicates().rename(
            columns={nome_col_valores: "NomeInstituicao"}
        )
        logger.debug(f"[PROCESSAMENTO] Nomes de valores: {len(df_nomes)} registros")
    else:
        df_nomes = pd.DataFrame()

    # Construir DataFrame de cadastro com nomes
    if df_cad.empty:
        logger.warning(f"[PROCESSAMENTO] Cadastro vazio para {ano_mes}, usando fallbacks")
        if not df_nomes.empty:
            df_cad = df_nomes.copy()
            logger.debug(f"[PROCESSAMENTO] Usando nomes de valores como fallback")
        else:
            # FALLBACK CRÍTICO: Não usar CodInst como nome!
            # Criar DataFrame com CodInst e tentar resolver via cache
            df_cad = df_valores[["CodInst"]].drop_duplicates().copy()
            df_cad["NomeInstituicao"] = df_cad["CodInst"].apply(
                lambda cod: resolver_nome_instituicao(cod, None, ano_mes)
            )
            logger.warning(f"[PROCESSAMENTO] Fallback: resolvendo {len(df_cad)} nomes via cache")

    else:
        # Cadastro OK, mas verificar se tem a coluna de nome
        nome_col_cad = obter_coluna_nome_instituicao(df_cad)

        if nome_col_cad:
            # Renomear para NomeInstituicao se necessário
            if nome_col_cad != "NomeInstituicao":
                df_cad = df_cad.rename(columns={nome_col_cad: "NomeInstituicao"})

            # Complementar com dados de valores onde cadastro está vazio
            if not df_nomes.empty:
                df_cad = df_cad.merge(
                    df_nomes,
                    on="CodInst",
                    how="left",
                    suffixes=("", "_valores")
                )
                # Preencher nomes faltantes
                df_cad["NomeInstituicao"] = df_cad["NomeInstituicao"].fillna(
                    df_cad.get("NomeInstituicao_valores")
                )
                df_cad = df_cad.drop(columns=["NomeInstituicao_valores"], errors="ignore")
        else:
            # Cadastro não tem coluna de nome - usar valores ou cache
            if not df_nomes.empty:
                df_cad = df_cad.merge(df_nomes, on="CodInst", how="left")
            else:
                df_cad["NomeInstituicao"] = df_cad["CodInst"].apply(
                    lambda cod: resolver_nome_instituicao(cod, None, ano_mes)
                )

    # 3. Validar nomes - resolver qualquer código remanescente
    if "NomeInstituicao" in df_cad.columns:
        df_cad["NomeInstituicao"] = df_cad.apply(
            lambda row: resolver_nome_instituicao(
                row.get("CodInst"),
                row.get("NomeInstituicao"),
                ano_mes
            ),
            axis=1
        )

    # 4. Extrair métricas financeiras
    # IMPORTANTE: "Lucro Líquido" é o nome da coluna na API do BC,
    # depois é renomeado para "Lucro Líquido Acumulado YTD" no passo 6.
    colunas_desejadas = [
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

    df_filt = df_valores[df_valores["NomeColuna"].isin(colunas_desejadas)].copy()

    if df_filt.empty:
        logger.warning(f"[PROCESSAMENTO] Sem colunas desejadas para {ano_mes}")
        return None

    df_pivot = df_filt.pivot_table(
        index="CodInst",
        columns="NomeColuna",
        values="Saldo",
        aggfunc="sum",
    ).reset_index()
    df_pivot.columns.name = None

    # 5. Consolidar carteira de crédito
    if "Carteira de Crédito Classificada" in df_pivot.columns:
        if "Carteira de Crédito" in df_pivot.columns:
            df_pivot["Carteira de Crédito"] = (
                df_pivot["Carteira de Crédito"].fillna(0) +
                df_pivot["Carteira de Crédito Classificada"].fillna(0)
            )
        else:
            df_pivot["Carteira de Crédito"] = df_pivot["Carteira de Crédito Classificada"]

        df_pivot = df_pivot.drop(columns=["Carteira de Crédito Classificada"], errors="ignore")

    # 6. Renomear coluna de Lucro Líquido e ajustar lucro semestral
    if "Lucro Líquido" in df_pivot.columns:
        df_pivot = df_pivot.rename(columns={"Lucro Líquido": "Lucro Líquido Acumulado YTD"})
    df_pivot = calcular_lucro_semestral(ano_mes, df_pivot)

    # 7. Merge com nomes
    df_merged = df_pivot.merge(
        df_cad[["CodInst", "NomeInstituicao"]].drop_duplicates(),
        on="CodInst",
        how="left",
    )

    # Resolver nomes faltantes após o merge
    df_merged["NomeInstituicao"] = df_merged.apply(
        lambda row: resolver_nome_instituicao(
            row.get("CodInst"),
            row.get("NomeInstituicao"),
            ano_mes
        ),
        axis=1
    )

    # 8. Organizar colunas
    colunas_ordem = [
        "NomeInstituicao",
        "Ativo Total",
        "Carteira de Crédito",
        "Títulos e Valores Mobiliários",
        "Passivo Exigível",
        "Captações",
        "Patrimônio Líquido",
        "Lucro Líquido Acumulado YTD",
        "Patrimônio de Referência",
        "Patrimônio de Referência para Comparação com o RWA (e)",
        "Índice de Basileia",
        "Índice de Imobilização",
        "Número de Agências",
        "Número de Postos de Atendimento",
    ]
    colunas_finais = [c for c in colunas_ordem if c in df_merged.columns]
    df_out = df_merged[colunas_finais].copy()

    num_cols = [c for c in colunas_finais if c != "NomeInstituicao"]
    df_out = df_out.dropna(subset=num_cols, how="all")

    # 9. Calcular métricas derivadas
    mes = int(ano_mes[4:6])

    if "Lucro Líquido Acumulado YTD" in df_out.columns and "Patrimônio Líquido" in df_out.columns:
        fator = 12 / mes if mes else 1

        df_out["ROE Ac. YTD an. (%)"] = (
            (fator * df_out["Lucro Líquido Acumulado YTD"].fillna(0)) /
            df_out["Patrimônio Líquido"].replace(0, np.nan)
        )

    if "Carteira de Crédito" in df_out.columns and "Patrimônio Líquido" in df_out.columns:
        df_out["Crédito/PL (%)"] = (
            df_out["Carteira de Crédito"].fillna(0) /
            df_out["Patrimônio Líquido"].replace(0, np.nan)
        )

    if "Carteira de Crédito" in df_out.columns and "Captações" in df_out.columns:
        df_out["Crédito/Captações (%)"] = (
            df_out["Carteira de Crédito"].fillna(0) /
            df_out["Captações"].replace(0, np.nan)
        )

    if "Carteira de Crédito" in df_out.columns and "Ativo Total" in df_out.columns:
        df_out["Crédito/Ativo (%)"] = (
            df_out["Carteira de Crédito"].fillna(0) /
            df_out["Ativo Total"].replace(0, np.nan)
        )

    # 10. Renomear e aplicar aliases
    df_out = df_out.rename(columns={"NomeInstituicao": "Instituição"})
    df_out = aplicar_aliases(df_out, dict_aliases)
    df_out["Período"] = f"{ano_mes[4:6]}/{ano_mes[:4]}"

    if "Carteira de Crédito" in df_out.columns:
        df_out = df_out.sort_values("Carteira de Crédito", ascending=False, na_position="last")

    # 11. Diagnóstico final
    diagnosticar_nomes(df_out, "Instituição", ano_mes)

    logger.info(f"[PROCESSAMENTO] Período {ano_mes} concluído: {len(df_out)} instituições")

    return df_out


# =============================================================================
# FUNÇÕES DE GERAÇÃO DE PERÍODOS E PROCESSAMENTO EM LOTE
# =============================================================================
def gerar_periodos(ano_inicial, mes_inicial, ano_final, mes_final):
    """Gera lista de períodos trimestrais entre datas especificadas."""
    PERIODOS = []
    ano_atual = ano_inicial
    mes_atual = mes_inicial

    while True:
        periodo = f"{ano_atual}{mes_atual}"
        PERIODOS.append(periodo)

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

    return PERIODOS


def processar_todos_periodos(periodos, dict_aliases, progress_callback=None, save_callback=None, save_interval=5):
    """Processa múltiplos períodos com rate limiting, logging e salvamento progressivo.

    IMPORTANTE: Antes de processar, carrega cache de nomes de múltiplos períodos
    para maximizar a cobertura de resolução de nomes.

    Args:
        periodos: Lista de períodos no formato 'YYYYMM'
        dict_aliases: Dicionário de aliases de instituições
        progress_callback: Função chamada a cada período (i, total, periodo)
        save_callback: Função chamada para salvar dados incrementalmente (dados_periodos, periodo_info)
                       Se fornecida, salva a cada save_interval períodos para evitar perda de dados
        save_interval: Intervalo de períodos para salvamento progressivo (padrão: 5)

    Returns:
        Dicionário {periodo: DataFrame} com todos os dados extraídos
    """
    logger.info(f"[BATCH] Iniciando processamento de {len(periodos)} períodos")

    # Pré-carregar cache de nomes de múltiplos períodos
    logger.info("[BATCH] Pré-carregando cache de nomes de instituições...")
    construir_mapa_codinst_multiperiodo(periodos[-3:] if len(periodos) >= 3 else periodos)

    dados_periodos = {}
    periodos_desde_ultimo_save = 0

    for i, per in enumerate(periodos):
        if progress_callback:
            progress_callback(i, len(periodos), per)

        try:
            df_per = processar_periodo(per, dict_aliases)
            if df_per is not None and not df_per.empty:
                dados_periodos[per] = df_per
                periodos_desde_ultimo_save += 1

                # Salvamento progressivo: salva a cada N períodos para evitar perda de dados
                if save_callback and periodos_desde_ultimo_save >= save_interval:
                    try:
                        periodo_info = f"salvamento progressivo até {per[4:6]}/{per[:4]}"
                        save_callback(dados_periodos, periodo_info)
                        periodos_desde_ultimo_save = 0
                        logger.info(f"[BATCH] Salvamento progressivo: {len(dados_periodos)} períodos salvos")
                    except Exception as save_error:
                        logger.warning(f"[BATCH] Erro no salvamento progressivo: {save_error}")

            # Rate limiting: esperar entre requisições
            time.sleep(1.5)

        except Exception as e:
            logger.error(f"[BATCH] Erro no período {per}: {e}")
            print(f"Erro no período {per}: {e}")

            # Tentar salvar o que temos até agora em caso de erro
            if save_callback and dados_periodos:
                try:
                    periodo_info = f"salvamento de emergência após erro em {per}"
                    save_callback(dados_periodos, periodo_info)
                    logger.info(f"[BATCH] Salvamento de emergência: {len(dados_periodos)} períodos salvos")
                except Exception as save_error:
                    logger.warning(f"[BATCH] Erro no salvamento de emergência: {save_error}")

    # Salvamento final
    if save_callback and dados_periodos and periodos_desde_ultimo_save > 0:
        try:
            periodo_info = f"{periodos[0][4:6]}/{periodos[0][:4]} até {periodos[-1][4:6]}/{periodos[-1][:4]}"
            save_callback(dados_periodos, periodo_info)
            logger.info(f"[BATCH] Salvamento final: {len(dados_periodos)} períodos salvos")
        except Exception as save_error:
            logger.warning(f"[BATCH] Erro no salvamento final: {save_error}")

    logger.info(f"[BATCH] Processamento concluído: {len(dados_periodos)} períodos com dados")

    return dados_periodos


# =============================================================================
# FUNÇÕES AUXILIARES PARA CORES (mantidas do original)
# =============================================================================
def carregar_cores_aliases(df_aliases):
    """Carrega cores personalizadas do arquivo de aliases."""
    dict_cores_personalizadas = {}

    mapa_cores = {
        'Azul-marinho': '#003366',
        'Laranja': '#FF6600',
        'Amarelo ouro': '#FFD700',
        'Vinho': '#8B0000',
        'Verde': '#28A745',
        'Roxo-vivo': '#820AD1',
        'Laranja 2': '#FF8C00',
        'Verde mais claro': '#03A64A',
        'Ciano': '#00B0FF',
        'Laranja 3': '#FF7F50',
        'Ciano 2': '#00CED1',
        'Amarelo ouro 2': '#FFB500',
        'Verde whatsapp': '#25D366',
        'Marrom': '#8B4513',
        'Azul royal': '#4169E1',
        'Cinza escuro': '#404040',
        'Azul petróleo': '#006699',
        'Vermelho': '#DC143C',
        'Preto': '#000000',
        'Rosa': '#FF1493',
        'Azul Citi': '#003DA5',
        'Laranja escuro': '#FF4500',
        'Verde oliva': '#556B2F',
        'Azul Porto': '#0066CC',
        'Azul escuro': '#000080'
    }

    for idx, row in df_aliases.iterrows():
        banco = row['Alias Banco']

        if pd.notna(row.get('Código Cor')):
            dict_cores_personalizadas[banco] = row['Código Cor']
        elif pd.notna(row.get('Cor')):
            cor_nome = row['Cor']
            if cor_nome in mapa_cores:
                dict_cores_personalizadas[banco] = mapa_cores[cor_nome]
            else:
                dict_cores_personalizadas[banco] = cor_nome

    return dict_cores_personalizadas
