"""
taxas_juros.py - Cache para dados de Taxas de Juros do BCB

Integra dados de taxas de juros ao sistema de cache do IFData.
API: TaxasJurosDiariaPorInicioPeriodo
Periodicidade: Janelas de 5 dias úteis (rolling window)
"""

import logging
import requests
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode, quote

from .base import BaseCache, CacheConfig, CacheResult

logger = logging.getLogger("ifdata_cache")

# URL da API do BCB para taxas de juros
API_URL = "https://olinda.bcb.gov.br/olinda/servico/taxaJuros/versao/v2/odata/TaxasJurosDiariaPorInicioPeriodo"

# Timeout padrão para requisições (segundos)
REQUEST_TIMEOUT = 120

# Máximo de registros por requisição
MAX_RECORDS = 150000


# Configuração do cache
TAXAS_JUROS_CONFIG = CacheConfig(
    nome="taxas_juros",
    descricao="Taxas de Juros por Produto e Instituição (API BCB)",
    subdir="taxas_juros",
    arquivo_dados="dados.parquet",
    arquivo_metadata="metadata.json",
    github_url_base=None,  # Sem suporte a download remoto por enquanto
    max_idade_horas=24.0,  # Dados atualizados diariamente
    colunas_obrigatorias=["Fim Período", "Instituição Financeira"],
    api_url=API_URL,
)


class TaxasJurosCache(BaseCache):
    """Cache para dados de taxas de juros do BCB."""

    def __init__(self, base_dir: Path):
        super().__init__(TAXAS_JUROS_CONFIG, base_dir)

    def baixar_remoto(self) -> CacheResult:
        """Baixa dados de fonte remota (API BCB).

        Para taxas de juros, não há cache no GitHub, então tentamos
        carregar os últimos 90 dias da API diretamente.
        """
        try:
            data_inicio = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')
            resultado = self._extrair_periodo_api(data_inicio)
            if resultado.sucesso:
                resultado.fonte = "api"
            return resultado
        except Exception as e:
            return CacheResult(
                sucesso=False,
                mensagem=f"Erro ao baixar dados: {e}",
                fonte="nenhum"
            )

    def extrair_periodo(
        self,
        periodo: str,
        data_fim: Optional[str] = None,
        **kwargs
    ) -> CacheResult:
        """Extrai dados de um período específico da API.

        Para taxas de juros, o período é uma data no formato YYYY-MM-DD.
        """
        return self._extrair_periodo_api(periodo, data_fim)

    def _extrair_periodo_api(
        self,
        data_inicio: str,
        data_fim: Optional[str] = None
    ) -> CacheResult:
        """Extrai dados da API do BCB."""
        if data_fim is None:
            data_fim = datetime.now().strftime('%Y-%m-%d')

        params = {
            "$format": "json",
            "$top": MAX_RECORDS,
            "dataInicioPeriodo": f"'{data_inicio}'"
        }

        try:
            self._log("info", f"Extraindo dados de {data_inicio} a {data_fim}...")
            response = requests.get(API_URL, params=params, timeout=REQUEST_TIMEOUT * 2)

            if response.status_code != 200:
                return CacheResult(
                    sucesso=False,
                    mensagem=f"Erro HTTP: {response.status_code}",
                    fonte="nenhum"
                )

            dados = response.json()

            if 'value' not in dados or not dados['value']:
                return CacheResult(
                    sucesso=False,
                    mensagem="Nenhum dado retornado pela API",
                    fonte="nenhum"
                )

            df = pd.DataFrame(dados['value'])

            # Converter datas
            df['InicioPeriodo'] = pd.to_datetime(df['InicioPeriodo'])
            df['FimPeriodo'] = pd.to_datetime(df['FimPeriodo'])

            # Filtrar por data final
            data_fim_dt = pd.to_datetime(data_fim)
            df = df[df['FimPeriodo'] <= data_fim_dt]

            # Selecionar colunas relevantes
            colunas_manter = [
                'InicioPeriodo', 'FimPeriodo', 'Segmento', 'Modalidade',
                'Posicao', 'InstituicaoFinanceira', 'TaxaJurosAoMes', 'TaxaJurosAoAno', 'cnpj8'
            ]
            colunas_existentes = [c for c in colunas_manter if c in df.columns]
            df = df[colunas_existentes]

            # Renomear colunas
            df = df.rename(columns={
                'InicioPeriodo': 'Início Período',
                'FimPeriodo': 'Fim Período',
                'Segmento': 'Segmento',
                'Modalidade': 'Produto',
                'Posicao': 'Posição',
                'InstituicaoFinanceira': 'Instituição Financeira',
                'TaxaJurosAoMes': 'Taxa Mensal (%)',
                'TaxaJurosAoAno': 'Taxa Anual (%)',
                'cnpj8': 'CNPJ'
            })

            # Ordenar por data e produto
            df = df.sort_values(['Fim Período', 'Produto', 'Posição'], ascending=[False, True, True])

            self._log("info", f"Extraídos {len(df)} registros de taxas de juros")

            return CacheResult(
                sucesso=True,
                mensagem=f"Extraídos {len(df)} registros",
                dados=df,
                fonte="api"
            )

        except requests.exceptions.Timeout:
            return CacheResult(
                sucesso=False,
                mensagem="Timeout ao extrair dados do BCB",
                fonte="nenhum"
            )
        except Exception as e:
            return CacheResult(
                sucesso=False,
                mensagem=f"Erro na extração: {e}",
                fonte="nenhum"
            )

    def _validar_dados(self, dados: Any) -> Tuple[bool, str]:
        """Valida dados específicos de taxas de juros."""
        if dados is None:
            return False, "Dados são None"

        if not isinstance(dados, pd.DataFrame):
            return False, f"Esperado DataFrame, recebido {type(dados)}"

        if dados.empty:
            return False, "DataFrame vazio"

        # Verificar colunas obrigatórias
        colunas_obrig = ['Fim Período', 'Instituição Financeira']
        for col in colunas_obrig:
            if col not in dados.columns:
                return False, f"Coluna obrigatória ausente: {col}"

        return True, "OK"

    def extrair_com_filtros(
        self,
        data_inicio: str,
        data_fim: Optional[str] = None,
        modalidades: Optional[List[str]] = None,
        instituicoes: Optional[List[str]] = None,
        progress_callback=None
    ) -> CacheResult:
        """Extrai dados com filtros opcionais.

        Args:
            data_inicio: Data de início no formato 'YYYY-MM-DD'
            data_fim: Data de fim no formato 'YYYY-MM-DD'
            modalidades: Lista de modalidades para filtrar
            instituicoes: Lista de instituições para filtrar
            progress_callback: Função de callback para progresso
        """
        if progress_callback:
            progress_callback(0.1, "Conectando à API do BCB...")

        resultado = self._extrair_periodo_api(data_inicio, data_fim)

        if not resultado.sucesso:
            return resultado

        df = resultado.dados

        if progress_callback:
            progress_callback(0.7, "Aplicando filtros...")

        # Filtrar por modalidades se especificado
        if modalidades and len(modalidades) > 0:
            df = df[df['Produto'].isin(modalidades)]

        # Filtrar por instituições se especificado
        if instituicoes and len(instituicoes) > 0:
            df = df[df['Instituição Financeira'].isin(instituicoes)]

        if progress_callback:
            progress_callback(1.0, "Extração concluída!")

        return CacheResult(
            sucesso=True,
            mensagem=f"Extraídos {len(df)} registros",
            dados=df,
            fonte="api"
        )

    def extrair_completo(
        self,
        data_inicio: str,
        data_fim: str,
        progress_callback=None,
        log_callback=None
    ) -> CacheResult:
        """Extrai dados COMPLETOS da API com paginação.

        Extrai TODOS os produtos e TODAS as instituições disponíveis
        para o período especificado, com paginação completa.

        Args:
            data_inicio: Data de início no formato 'YYYY-MM-DD'
            data_fim: Data de fim no formato 'YYYY-MM-DD'
            progress_callback: Função(progress: float, message: str)
            log_callback: Função(message: str) para logs detalhados
        """
        def log(msg: str):
            if log_callback:
                log_callback(msg)
            self._log("info", msg)

        log(f"Iniciando extração completa de {data_inicio} a {data_fim}")
        log("Extraindo TODOS os produtos e TODAS as instituições disponíveis")

        all_data = []
        page = 0
        page_size = MAX_RECORDS
        total_fetched = 0
        has_more = True

        while has_more:
            skip = page * page_size

            params = {
                "$format": "json",
                "$top": page_size,
                "$skip": skip,
                "dataInicioPeriodo": f"'{data_inicio}'"
            }

            try:
                if progress_callback:
                    progress_callback(0.1 + (page * 0.05), f"Página {page + 1}: buscando registros {skip + 1} a {skip + page_size}...")

                log(f"Requisição página {page + 1}: $skip={skip}, $top={page_size}")

                response = requests.get(API_URL, params=params, timeout=REQUEST_TIMEOUT * 3)

                if response.status_code != 200:
                    log(f"ERRO HTTP: {response.status_code}")
                    return CacheResult(
                        sucesso=False,
                        mensagem=f"Erro HTTP: {response.status_code}",
                        fonte="nenhum"
                    )

                dados = response.json()

                if 'value' not in dados or not dados['value']:
                    log(f"Página {page + 1}: nenhum dado retornado (fim dos dados)")
                    has_more = False
                    break

                records = dados['value']
                num_records = len(records)
                all_data.extend(records)
                total_fetched += num_records

                log(f"Página {page + 1}: {num_records} registros (total: {total_fetched})")

                # Se retornou menos que o page_size, não há mais páginas
                if num_records < page_size:
                    log("Última página detectada (registros < page_size)")
                    has_more = False
                else:
                    page += 1
                    # Limite de segurança (máximo 50 páginas = 7.5M registros)
                    if page >= 50:
                        log("AVISO: Limite de 50 páginas atingido!")
                        has_more = False

            except requests.exceptions.Timeout:
                log(f"ERRO: Timeout na página {page + 1}")
                return CacheResult(
                    sucesso=False,
                    mensagem=f"Timeout na página {page + 1}",
                    fonte="nenhum"
                )
            except Exception as e:
                log(f"ERRO na página {page + 1}: {e}")
                return CacheResult(
                    sucesso=False,
                    mensagem=f"Erro na extração: {e}",
                    fonte="nenhum"
                )

        if not all_data:
            return CacheResult(
                sucesso=False,
                mensagem="Nenhum dado retornado pela API",
                fonte="nenhum"
            )

        log(f"Total bruto extraído: {len(all_data)} registros")

        if progress_callback:
            progress_callback(0.7, "Processando dados...")

        # Criar DataFrame
        df = pd.DataFrame(all_data)

        # Converter datas
        df['InicioPeriodo'] = pd.to_datetime(df['InicioPeriodo'])
        df['FimPeriodo'] = pd.to_datetime(df['FimPeriodo'])

        # Filtrar por data final
        data_fim_dt = pd.to_datetime(data_fim)
        df_original_len = len(df)
        df = df[df['FimPeriodo'] <= data_fim_dt]
        log(f"Filtro por data final: {df_original_len} → {len(df)} registros")

        # Selecionar e renomear colunas
        colunas_manter = [
            'InicioPeriodo', 'FimPeriodo', 'Segmento', 'Modalidade',
            'Posicao', 'InstituicaoFinanceira', 'TaxaJurosAoMes', 'TaxaJurosAoAno', 'cnpj8'
        ]
        colunas_existentes = [c for c in colunas_manter if c in df.columns]
        df = df[colunas_existentes]

        df = df.rename(columns={
            'InicioPeriodo': 'Início Período',
            'FimPeriodo': 'Fim Período',
            'Segmento': 'Segmento',
            'Modalidade': 'Produto',
            'Posicao': 'Posição',
            'InstituicaoFinanceira': 'Instituição Financeira',
            'TaxaJurosAoMes': 'Taxa Mensal (%)',
            'TaxaJurosAoAno': 'Taxa Anual (%)',
            'cnpj8': 'CNPJ'
        })

        # Ordenar
        df = df.sort_values(['Fim Período', 'Produto', 'Posição'], ascending=[False, True, True])

        if progress_callback:
            progress_callback(0.9, "Gerando estatísticas...")

        # Estatísticas para logs
        produtos_unicos = df['Produto'].nunique() if 'Produto' in df.columns else 0
        instituicoes_unicas = df['Instituição Financeira'].nunique() if 'Instituição Financeira' in df.columns else 0
        periodos_unicos = df['Fim Período'].nunique() if 'Fim Período' in df.columns else 0

        # Verificar PF/PJ
        if 'Segmento' in df.columns:
            segmentos = df['Segmento'].value_counts().to_dict()
            log(f"Segmentos: {segmentos}")

        log("=" * 50)
        log("RESUMO DA EXTRAÇÃO COMPLETA:")
        log(f"  - Total de linhas: {len(df):,}")
        log(f"  - Produtos únicos: {produtos_unicos}")
        log(f"  - Instituições únicas: {instituicoes_unicas}")
        log(f"  - Períodos únicos (datas): {periodos_unicos}")
        log(f"  - Páginas processadas: {page + 1}")
        log(f"  - Truncamento: {'NÃO' if not has_more or page < 49 else 'POSSÍVEL (verificar)'}")
        log("=" * 50)

        if progress_callback:
            progress_callback(1.0, f"Extração concluída: {len(df):,} registros")

        return CacheResult(
            sucesso=True,
            mensagem=f"Extraídos {len(df):,} registros ({produtos_unicos} produtos, {instituicoes_unicas} instituições, {periodos_unicos} períodos)",
            dados=df,
            fonte="api",
            metadata={
                "total_registros": len(df),
                "produtos_unicos": produtos_unicos,
                "instituicoes_unicas": instituicoes_unicas,
                "periodos_unicos": periodos_unicos,
                "paginas_processadas": page + 1,
                "data_inicio": data_inicio,
                "data_fim": data_fim,
                "truncado": has_more and page >= 49
            }
        )


def _escape_odata_literal(value: str) -> str:
    """Escapa aspas simples para literais string em OData."""
    return str(value).replace("'", "''")


def _rename_taxas_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Aplica o layout de colunas usado pela aba de taxas."""
    rename_map = {
        'InicioPeriodo': 'Início Período',
        'FimPeriodo': 'Fim Período',
        'Segmento': 'Segmento',
        'Modalidade': 'Produto',
        'Posicao': 'Posição',
        'InstituicaoFinanceira': 'Instituição Financeira',
        'TaxaJurosAoMes': 'Taxa Mensal (%)',
        'TaxaJurosAoAno': 'Taxa Anual (%)',
        'cnpj8': 'CNPJ'
    }
    return df.rename(columns=rename_map)


def _optimize_taxas_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Reduz footprint de memória para frames escopados de taxas."""
    if df.empty:
        return df

    optimized = df.copy()
    for col in ('Início Período', 'Fim Período'):
        if col in optimized.columns:
            optimized[col] = pd.to_datetime(optimized[col], errors='coerce')

    for col in ('Taxa Mensal (%)', 'Taxa Anual (%)'):
        if col in optimized.columns:
            optimized[col] = pd.to_numeric(optimized[col], errors='coerce').astype('float32')

    if 'Posição' in optimized.columns:
        optimized['Posição'] = pd.to_numeric(optimized['Posição'], errors='coerce').astype('Int16')

    return optimized


def fetch_taxas_juros_scoped(
    *,
    data_inicio: str,
    data_fim: Optional[str] = None,
    segmento: Optional[str] = None,
    modalidade: Optional[str] = None,
    instituicao: Optional[str] = None,
    select_fields: Optional[List[str]] = None,
    page_size: int = 5000,
    max_pages: int = 6,
    timeout: int = REQUEST_TIMEOUT,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Busca dados escopados da API do BCB com filtros no servidor.

    O objetivo aqui é suportar consultas leves da UI, evitando a estratégia
    antiga de baixar o universo inteiro e filtrar depois no Streamlit.
    """
    select_fields = select_fields or [
        "InicioPeriodo",
        "FimPeriodo",
        "Segmento",
        "Modalidade",
        "Posicao",
        "InstituicaoFinanceira",
        "TaxaJurosAoMes",
        "TaxaJurosAoAno",
        "cnpj8",
    ]

    filters = []
    if segmento:
        filters.append(f"Segmento eq '{_escape_odata_literal(segmento)}'")
    if modalidade:
        filters.append(f"Modalidade eq '{_escape_odata_literal(modalidade)}'")
    if instituicao:
        filters.append(f"InstituicaoFinanceira eq '{_escape_odata_literal(instituicao)}'")

    frames: List[pd.DataFrame] = []
    rows_fetched = 0
    pages_loaded = 0
    hit_page_limit = False
    error_message = ""

    for page in range(max_pages):
        params = {
            "$format": "json",
            "$top": int(page_size),
            "$skip": int(page * page_size),
            "$select": ",".join(select_fields),
            "$orderby": "FimPeriodo desc",
            "dataInicioPeriodo": f"'{data_inicio}'",
        }
        if filters:
            params["$filter"] = " and ".join(filters)

        try:
            query_string = urlencode(params, quote_via=quote, safe="(),'$")
            response = requests.get(f"{API_URL}?{query_string}", timeout=timeout)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            error_message = str(exc)
            break

        rows = payload.get("value") or []
        if not rows:
            break

        frames.append(pd.DataFrame.from_records(rows))
        rows_fetched += len(rows)
        pages_loaded += 1

        if len(rows) < page_size:
            break

        if page == max_pages - 1:
            hit_page_limit = True

    if not frames:
        return pd.DataFrame(), {
            "rows_fetched": 0,
            "pages_loaded": pages_loaded,
            "page_size": page_size,
            "max_pages": max_pages,
            "hit_page_limit": hit_page_limit,
            "error": error_message,
        }

    df = pd.concat(frames, ignore_index=True)
    df = _rename_taxas_columns(df)
    df = _optimize_taxas_frame(df)

    if data_fim and 'Fim Período' in df.columns:
        data_fim_dt = pd.to_datetime(data_fim, errors='coerce')
        if not pd.isna(data_fim_dt):
            df = df[df['Fim Período'] <= data_fim_dt].copy()

    if {'Fim Período', 'Produto'}.issubset(df.columns):
        sort_cols = ['Fim Período', 'Produto']
        asc = [False, True]
        if 'Posição' in df.columns:
            sort_cols.append('Posição')
            asc.append(True)
        df = df.sort_values(sort_cols, ascending=asc, na_position='last').reset_index(drop=True)

    return df, {
        "rows_fetched": rows_fetched,
        "rows_returned": int(len(df)),
        "pages_loaded": pages_loaded,
        "page_size": page_size,
        "max_pages": max_pages,
        "hit_page_limit": hit_page_limit,
        "error": error_message,
    }


def fetch_taxas_juros_for_institutions(
    *,
    instituicoes: List[str],
    data_inicio: str,
    data_fim: Optional[str] = None,
    segmento: Optional[str] = None,
    modalidade: Optional[str] = None,
    select_fields: Optional[List[str]] = None,
    page_size: int = 1000,
    max_pages_per_institution: int = 3,
    timeout: int = REQUEST_TIMEOUT,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Busca dados escopados no servidor para uma lista pequena de instituições.

    Uso ideal: recortes recentes de 3 a 12 bancos escolhidos pelo usuário.
    Isso reduz bastante o volume frente à consulta ampla por produto.
    """
    frames: List[pd.DataFrame] = []
    total_rows_fetched = 0
    total_rows_returned = 0
    total_pages_loaded = 0
    hit_any_page_limit = False
    errors: Dict[str, str] = {}
    per_institution: List[Dict[str, Any]] = []

    for instituicao in instituicoes:
        df_inst, meta_inst = fetch_taxas_juros_scoped(
            data_inicio=data_inicio,
            data_fim=data_fim,
            segmento=segmento,
            modalidade=modalidade,
            instituicao=instituicao,
            select_fields=select_fields,
            page_size=page_size,
            max_pages=max_pages_per_institution,
            timeout=timeout,
        )
        if not df_inst.empty:
            frames.append(df_inst)

        total_rows_fetched += int(meta_inst.get("rows_fetched", 0) or 0)
        total_rows_returned += int(meta_inst.get("rows_returned", 0) or 0)
        total_pages_loaded += int(meta_inst.get("pages_loaded", 0) or 0)
        hit_any_page_limit = hit_any_page_limit or bool(meta_inst.get("hit_page_limit"))
        if meta_inst.get("error"):
            errors[instituicao] = str(meta_inst["error"])

        per_institution.append(
            {
                "instituicao": instituicao,
                "rows_returned": int(meta_inst.get("rows_returned", 0) or 0),
                "pages_loaded": int(meta_inst.get("pages_loaded", 0) or 0),
                "hit_page_limit": bool(meta_inst.get("hit_page_limit")),
                "error": meta_inst.get("error", ""),
            }
        )

    if not frames:
        return pd.DataFrame(), {
            "rows_fetched": total_rows_fetched,
            "rows_returned": total_rows_returned,
            "pages_loaded": total_pages_loaded,
            "hit_page_limit": hit_any_page_limit,
            "errors": errors,
            "per_institution": per_institution,
        }

    df = pd.concat(frames, ignore_index=True)
    if {'Fim Período', 'Instituição Financeira'}.issubset(df.columns):
        df = df.sort_values(['Fim Período', 'Instituição Financeira']).reset_index(drop=True)

    return df, {
        "rows_fetched": total_rows_fetched,
        "rows_returned": total_rows_returned,
        "pages_loaded": total_pages_loaded,
        "hit_page_limit": hit_any_page_limit,
        "errors": errors,
        "per_institution": per_institution,
    }


def reduce_taxas_juros_to_monthly_snapshot(df: pd.DataFrame) -> pd.DataFrame:
    """Mantém a última observação disponível de cada mês por banco/produto."""
    if df is None or df.empty or 'Fim Período' not in df.columns:
        return pd.DataFrame() if df is None else df.copy()

    monthly = df.copy()
    monthly['Fim Período'] = pd.to_datetime(monthly['Fim Período'], errors='coerce')
    monthly = monthly.dropna(subset=['Fim Período'])
    monthly['AnoMes'] = monthly['Fim Período'].dt.to_period('M')

    group_cols = ['AnoMes', 'Instituição Financeira']
    for optional_col in ('Segmento', 'Produto'):
        if optional_col in monthly.columns:
            group_cols.insert(0, optional_col)

    idx = monthly.groupby(group_cols, observed=False)['Fim Período'].idxmax()
    reduced = monthly.loc[idx].copy()
    reduced['Mês'] = reduced['Fim Período'].dt.strftime('%b/%y')
    reduced = reduced.sort_values(['Fim Período', 'Instituição Financeira']).reset_index(drop=True)
    return reduced


def buscar_modalidades_disponiveis(dias_amostra: int = 60) -> List[str]:
    """Busca todas as modalidades (produtos) disponíveis na API."""
    data_inicio = (datetime.now() - timedelta(days=dias_amostra)).strftime('%Y-%m-%d')

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
                if 'Modalidade' in df.columns:
                    return sorted(df['Modalidade'].unique().tolist())

        return []

    except Exception as e:
        logger.error(f"Erro ao buscar modalidades: {e}")
        return []


def buscar_instituicoes_disponiveis(dias_amostra: int = 60) -> List[str]:
    """Busca todas as instituições disponíveis na API."""
    data_inicio = (datetime.now() - timedelta(days=dias_amostra)).strftime('%Y-%m-%d')

    params = {
        "$format": "json",
        "$top": 100000,
        "dataInicioPeriodo": f"'{data_inicio}'"
    }

    try:
        response = requests.get(API_URL, params=params, timeout=REQUEST_TIMEOUT)

        if response.status_code == 200:
            dados = response.json()
            if 'value' in dados and dados['value']:
                df = pd.DataFrame(dados['value'])
                if 'InstituicaoFinanceira' in df.columns:
                    return sorted(df['InstituicaoFinanceira'].unique().tolist())

        return []

    except Exception as e:
        logger.error(f"Erro ao buscar instituições: {e}")
        return []


def formatar_nome_modalidade(nome: str) -> str:
    """Formata o nome da modalidade para exibição mais curta."""
    substituicoes = {
        ' - Pré-fixado': ' (Pré)',
        ' - Pós-fixado referenciado em moeda estrangeira': ' (Pós M.E.)',
        ' - Pós-fixado referenciado em juros flutuantes': ' (Pós Flutuante)',
        ' - Pós-fixado referenciado em TR': ' (Pós TR)',
        ' - Pós-fixado referenciado em IPCA': ' (Pós IPCA)',
        'Adiantamento sobre contratos de câmbio (ACC)': 'ACC',
        'Capital de giro com prazo até 365 dias': 'Capital Giro até 365d',
        'Capital de giro com prazo superior a 365 dias': 'Capital Giro > 365d',
        'Cartão de crédito - parcelado': 'Cartão Parcelado',
        'Cartão de crédito - rotativo total': 'Cartão Rotativo',
        'Crédito pessoal consignado INSS': 'Consignado INSS',
        'Crédito pessoal consignado privado': 'Consignado Privado',
        'Crédito pessoal consignado público': 'Consignado Público',
        'Crédito pessoal não consignado': 'Crédito Pessoal',
        'Antecipação de faturas de cartão de crédito': 'Antecipação Fatura',
        'Aquisição de outros bens': 'Aquisição Outros',
        'Aquisição de veículos': 'Aquisição Veículos',
        'Desconto de cheques': 'Desconto Cheques',
        'Desconto de duplicatas': 'Desconto Duplicatas',
        'Conta garantida': 'Conta Garantida',
        'Cheque especial': 'Cheque Especial',
    }

    resultado = nome
    for original, abreviado in substituicoes.items():
        resultado = resultado.replace(original, abreviado)

    return resultado


# Modalidades conhecidas (fallback)
MODALIDADES_CONHECIDAS = [
    "Adiantamento sobre contratos de câmbio (ACC) - Pós-fixado referenciado em moeda estrangeira",
    "Antecipação de faturas de cartão de crédito - Pré-fixado",
    "Aquisição de outros bens - Pré-fixado",
    "Aquisição de veículos - Pré-fixado",
    "Capital de giro com prazo até 365 dias - Pré-fixado",
    "Capital de giro com prazo até 365 dias - Pós-fixado referenciado em juros flutuantes",
    "Capital de giro com prazo superior a 365 dias - Pré-fixado",
    "Capital de giro com prazo superior a 365 dias - Pós-fixado referenciado em juros flutuantes",
    "Cartão de crédito - parcelado - Pré-fixado",
    "Cartão de crédito - rotativo total - Pré-fixado",
    "Cheque especial - Pré-fixado",
    "Conta garantida - Pré-fixado",
    "Conta garantida - Pós-fixado referenciado em juros flutuantes",
    "Crédito pessoal consignado INSS - Pré-fixado",
    "Crédito pessoal consignado privado - Pré-fixado",
    "Crédito pessoal consignado público - Pré-fixado",
    "Crédito pessoal não consignado - Pré-fixado",
    "Desconto de cheques - Pré-fixado",
    "Desconto de duplicatas - Pré-fixado",
    "Vendor - Pré-fixado",
]
