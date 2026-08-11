"""
derived_metrics.py - Cache e cálculo de métricas derivadas (formato LONG/TIDY)

Cria um cache separado para indicadores derivados calculados a partir de:
- DRE (Relatório 4)
- Resumo/Principal (Relatório 1) para Captações

Formato LONG/TIDY:
    Instituição | Período | Métrica | Valor | Unidade
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
import io
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests

from .base import BaseCache, CacheConfig, CacheResult
from .metric_registry import (
    get_derived_metric_labels,
    get_derived_metric_format_map,
    get_derived_metric_formula_map,
)
from .release_config import add_release_cache_buster, get_release_config

logger = logging.getLogger("ifdata_cache")


METRIC_PDD_INTERMED = "Desp PDD / Resultado Intermediação Fin. Bruto"
METRIC_DESP_CAPT = "Desp Captação / Captação"
METRIC_CUSTO_CREDITO = "Custo de Crédito (%)"

# Fonte canônica: metric_registry (mantemos labels locais para compatibilidade)
DERIVED_METRICS = get_derived_metric_labels()
if not DERIVED_METRICS:
    DERIVED_METRICS = [
        METRIC_PDD_INTERMED,
        METRIC_DESP_CAPT,
        METRIC_CUSTO_CREDITO,
    ]

DERIVED_METRICS_FORMAT = get_derived_metric_format_map()
if not DERIVED_METRICS_FORMAT:
    DERIVED_METRICS_FORMAT = {
        METRIC_PDD_INTERMED: "pct",
        METRIC_DESP_CAPT: "pct",
        METRIC_CUSTO_CREDITO: "pct",
    }

DERIVED_METRICS_FORMULAS = get_derived_metric_formula_map()
if not DERIVED_METRICS_FORMULAS:
    DERIVED_METRICS_FORMULAS = {
        METRIC_PDD_INTERMED: "Desp. PDD / Resultado de Intermediação Financeira Bruto",
        METRIC_DESP_CAPT: "Desp. Captação anualizada / Captações",
        METRIC_CUSTO_CREDITO: "|Desp. PDD de crédito (f3)| anualizada / Carteira de Crédito*",
    }


DRE_REQUIRED_COLUMNS = {
    "desp_pdd": "Resultado com Perda Esperada (f)",
    "desp_pdd_credito": "Resultado com Perda Esperada de Operações de Crédito (f3)",
    "rec_credito": "Rendas de Operações de Crédito (c)",
    "rec_arrendamento": "Rendas de Arrendamento Financeiro (d)",
    "rec_outras": "Rendas de Outras Operações com Características de Concessão de Crédito (e)",
    "rec_liquidez": "Rendas de Aplicações Interfinanceiras de Liquidez (a)",
    "rec_tvm": "Rendas de Títulos e Valores Mobiliários (b)",
    "desp_captacao": "Despesas de Captações (g)",
}

# Componentes do Relatório 2 usados para reconstruir Carteira de Crédito* com a mesma
# semântica de `critical_screens.resolve_carteira_credito_bruta_value` (ver
# `_resolve_carteira_credito_bruta_series`).
CARTEIRA_LEGACY_COLUMNS = (
    "Operações de Crédito (d1)",
    "Arrendamento Mercantil a Receber (e1)",
    "Outros Créditos - Líquido de Provisão (f)",
)
CARTEIRA_VCB_COLUMNS = (
    "Valor Contábil Bruto (e1)",
    "Valor Contábil Bruto (f1)",
    "Valor Contábil Bruto (g1)",
    "Valor Contábil Bruto (h1)",
)
CARTEIRA_NET_COLUMNS = (
    "Operações de Crédito (e)",
    "Operações de Arrendamento Financeiro (f)",
    "Outras Operações com Características de Concessão de Crédito (g)",
    "Valores a Receber de Transações de Pagamentos - Usuários Finais (Pós-pago) (h)",
)
# Fallback no cache principal (Rel. 1) quando o Relatório 2 não estiver disponível.
CARTEIRA_PRINCIPAL_FALLBACK_COLUMNS = (
    "Carteira de Crédito*",
    "Carteira de Crédito Bruta",
    "Carteira de Crédito",
)


DERIVED_CACHE_CONFIG = CacheConfig(
    nome="derived_metrics",
    descricao="Métricas derivadas (DRE + Resumo)",
    subdir="derived_metrics",
    arquivo_dados="dados.parquet",
    arquivo_metadata="metadata.json",
    github_url_base=None,
    max_idade_horas=None,
    colunas_obrigatorias=["Instituição", "Período", "Métrica", "Valor"],
)

DERIVED_INDIVIDUAL_CACHE_CONFIG = CacheConfig(
    nome="derived_metrics_individual",
    descricao="Métricas derivadas (DRE individual + Resumo individual)",
    subdir="derived_metrics_individual",
    arquivo_dados="dados.parquet",
    arquivo_metadata="metadata.json",
    github_url_base=None,
    max_idade_horas=None,
    colunas_obrigatorias=["Instituição", "Período", "Métrica", "Valor"],
)


class DerivedMetricsCache(BaseCache):
    """Cache dedicado para métricas derivadas."""

    def __init__(self, base_dir: Path, config: CacheConfig = DERIVED_CACHE_CONFIG):
        release = get_release_config()
        super().__init__(replace(config, github_url_base=release.release_base_url), base_dir)
        self.release_tag = release.tag
        self.github_release_parquet_url = f"{release.release_base_url}/{config.nome}_dados.parquet"

    def baixar_remoto(self):
        asset_url = add_release_cache_buster(
            self.github_release_parquet_url,
            self.release_tag,
            self.config.nome,
            "parquet",
        )
        try:
            response = requests.get(
                asset_url,
                timeout=120,
                headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
            )
            if response.status_code == 404:
                return CacheResult(sucesso=False, mensagem="Parquet derivado ausente no release", fonte="nenhum")
            response.raise_for_status()
            df = pd.read_parquet(io.BytesIO(response.content))
            return CacheResult(
                sucesso=True,
                mensagem=f"Baixado dos releases: {len(df)} registros",
                dados=df,
                fonte="github_releases",
            )
        except Exception as exc:
            return CacheResult(sucesso=False, mensagem=f"Falha ao baixar cache derivado: {exc}", fonte="nenhum")

    def extrair_periodo(self, periodo: str, **kwargs):
        return self._unsupported("Cache derivado não suporta extração direta")

    def _unsupported(self, mensagem: str):
        from .base import CacheResult

        return CacheResult(sucesso=False, mensagem=mensagem, fonte="nenhum")


class DerivedMetricsIndividualCache(DerivedMetricsCache):
    """Cache dedicado para métricas derivadas da base individual."""

    def __init__(self, base_dir: Path):
        super().__init__(base_dir, config=DERIVED_INDIVIDUAL_CACHE_CONFIG)


@dataclass
class DerivedMetricsStats:
    denominador_zero_ou_nan: Dict[str, int]
    periodos_detectados: List[str]
    period_type: str
    total_registros: int
    carteira_fonte: str = "indisponivel"


def materialize_derived_metrics_cache(
    *,
    base_dir: Path | None = None,
    manager: "CacheManager" | None = None,
    derived_cache_name: str = "derived_metrics",
    dre_cache_name: str = "dre",
    principal_cache_name: str = "principal",
    ativo_cache_name: Optional[str] = "ativo",
    force: bool = False,
) -> CacheResult:
    """Recalcula e salva o cache derivado a partir de DRE + principal."""
    root = Path(base_dir).resolve() if base_dir else Path(__file__).resolve().parents[2]
    from .manager import CacheManager

    cache_manager = manager or CacheManager(root)
    cache_derivado = cache_manager.get_cache(derived_cache_name)
    if cache_derivado is None:
        return CacheResult(
            sucesso=False,
            mensagem=f"cache derivado '{derived_cache_name}' não configurado",
            fonte="nenhum",
        )

    if cache_derivado.existe() and not force:
        return cache_derivado.carregar_local()

    resultado_dre = cache_manager.carregar(dre_cache_name)
    if not resultado_dre.sucesso or resultado_dre.dados is None:
        return CacheResult(
            sucesso=False,
            mensagem=f"{dre_cache_name}: {resultado_dre.mensagem}",
            fonte="nenhum",
        )

    resultado_principal = cache_manager.carregar(principal_cache_name)
    if not resultado_principal.sucesso or resultado_principal.dados is None:
        return CacheResult(
            sucesso=False,
            mensagem=f"{principal_cache_name}: {resultado_principal.mensagem}",
            fonte="nenhum",
        )

    # Relatório 2 alimenta apenas o denominador de Custo de Crédito (%). A ausência
    # dele não pode derrubar a materialização das demais métricas derivadas.
    df_ativo = None
    if ativo_cache_name:
        try:
            resultado_ativo = cache_manager.carregar(ativo_cache_name)
            if resultado_ativo and resultado_ativo.sucesso:
                df_ativo = resultado_ativo.dados
        except Exception:
            logger.warning(
                "[DERIVED] cache '%s' indisponível; Custo de Crédito usará carteira do principal",
                ativo_cache_name,
            )

    df_derived, stats = build_derived_metrics(
        resultado_dre.dados,
        resultado_principal.dados,
        df_ativo=df_ativo,
    )
    info_extra = {
        "denominador_zero_ou_nan": stats.denominador_zero_ou_nan,
        "period_type": stats.period_type,
        "periodos_detectados": stats.periodos_detectados,
        "cache_origem_dre": dre_cache_name,
        "cache_origem_principal": principal_cache_name,
        "cache_origem_ativo": ativo_cache_name or "",
        "carteira_fonte": stats.carteira_fonte,
    }
    return cache_derivado.salvar_local(df_derived, fonte="derivado", info_extra=info_extra)


def _normalize_label(texto: str) -> str:
    if texto is None:
        return ""
    return (
        str(texto)
        .strip()
        .lower()
        .replace(".", "")
        .replace("á", "a")
        .replace("à", "a")
        .replace("ã", "a")
        .replace("â", "a")
        .replace("é", "e")
        .replace("ê", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ô", "o")
        .replace("õ", "o")
        .replace("ú", "u")
        .replace("ç", "c")
    )


def _find_column(df: pd.DataFrame, label: str) -> Optional[str]:
    if label in df.columns:
        return label
    target = _normalize_label(label)
    for col in df.columns:
        if _normalize_label(col) == target:
            return col
    for col in df.columns:
        if target in _normalize_label(col):
            return col
    return None


def _coerce_numeric(series: pd.Series) -> pd.Series:
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


def _parse_periodo(periodo_val: str) -> Tuple[Optional[int], Optional[int]]:
    """Retorna (ano, mes) a partir do formato '1/2025' ou '202503'."""
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


def _acumular_dre_ytd_por_periodo(
    df_base: pd.DataFrame,
    serie_valor: pd.Series,
) -> pd.Series:
    """Converte série DRE para acumulado YTD quando necessário.

    Relatório 4 (DRE) do BCB é semestral no 2º semestre:
      - 3/AAAA (Set): Jul-Set, precisa somar 2/AAAA (Jan-Jun)
      - 4/AAAA (Dez): Jul-Dez, precisa somar 2/AAAA (Jan-Jun)

    Para períodos no formato mensal:
      - MM=09 ou MM=12, soma MM=06 do mesmo ano.
    """
    out = serie_valor.astype("float64").copy()

    if out.empty:
        return out

    df_aux = pd.DataFrame(
        {
            "Instituição": df_base["Instituição"],
            "Período": df_base["Período"].astype(str),
            "Valor": out,
        }
    )
    ano_mes = df_aux["Período"].apply(_parse_periodo)
    df_aux["Ano"] = ano_mes.str[0]
    df_aux["Mes"] = ano_mes.str[1]

    base_lookup = (
        df_aux[["Instituição", "Ano", "Mes", "Valor"]]
        .dropna(subset=["Ano", "Mes"])
        .drop_duplicates(subset=["Instituição", "Ano", "Mes"], keep="last")
        .rename(columns={"Valor": "Valor_lookup"})
    )

    precisa_acumular = df_aux["Mes"].isin([9, 12])
    if not precisa_acumular.any():
        return out

    idx = df_aux.index[precisa_acumular]
    chave = df_aux.loc[idx, ["Instituição", "Ano"]].copy()
    chave["Mes"] = 6
    jun_lookup = chave.merge(
        base_lookup,
        on=["Instituição", "Ano", "Mes"],
        how="left",
    )["Valor_lookup"]

    out.loc[idx] = out.loc[idx] + jun_lookup.values
    return out


def _anualizar_serie_por_periodo(serie_valor: pd.Series, periodos: pd.Series) -> pd.Series:
    """Aplica fator 12/meses com base no período informado."""
    meses = periodos.astype(str).apply(lambda x: _parse_periodo(x)[1])
    meses = meses.where(meses.notna() & (meses > 0), pd.NA)
    fator_anualizacao = 12 / meses.astype("float32")
    return serie_valor * fator_anualizacao


def _media_captacoes_ytd(
    instituicoes: pd.Series,
    periodos: pd.Series,
    captacoes: pd.Series,
) -> pd.Series:
    """Calcula média simples YTD das captações por instituição/ano."""
    df_aux = pd.DataFrame(
        {
            "Instituição": instituicoes,
            "Período": periodos.astype(str),
            "Captações": _coerce_numeric(captacoes),
        }
    )
    ano_mes = df_aux["Período"].apply(_parse_periodo)
    df_aux["Ano"] = ano_mes.str[0]
    df_aux["Mes"] = ano_mes.str[1]
    df_aux["_ord"] = range(len(df_aux))
    df_aux["Captações_Média_YTD"] = pd.NA

    mask_valid = df_aux["Ano"].notna() & df_aux["Mes"].notna()
    if mask_valid.any():
        df_valid = df_aux.loc[mask_valid].copy()
        df_valid = df_valid.sort_values(["Instituição", "Ano", "Mes", "Período", "_ord"])
        df_valid["Captações_Média_YTD"] = (
            df_valid.groupby(["Instituição", "Ano"], dropna=False)["Captações"]
            .transform(lambda s: s.expanding().mean())
        )
        df_aux.loc[df_valid.index, "Captações_Média_YTD"] = df_valid["Captações_Média_YTD"]

    return pd.to_numeric(df_aux["Captações_Média_YTD"], errors="coerce")


def _detect_period_type(periodos: Iterable[str]) -> str:
    for periodo in periodos:
        texto = str(periodo)
        if "/" in texto:
            return "trimestral"
        if texto.isdigit() and len(texto) in (6, 8):
            return "mensal"
    return "desconhecido"


def _safe_ratio(
    numerador: pd.Series,
    denominador: pd.Series,
    metric_label: str,
    contadores: Dict[str, int],
) -> pd.Series:
    denom_invalid = denominador.isna() | (denominador == 0)
    contadores[metric_label] = int(denom_invalid.sum())
    resultado = numerador / denominador
    resultado = resultado.mask(denom_invalid)
    return resultado


def _prepare_base_dre(df_dre: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, str]]:
    col_periodo = _find_column(df_dre, "Período") or _find_column(df_dre, "Periodo")
    col_inst = _find_column(df_dre, "Instituição") or _find_column(df_dre, "Instituicao")
    if col_periodo is None or col_inst is None:
        raise ValueError("Colunas de período ou instituição não encontradas no DRE")

    colunas = {"Instituição": col_inst, "Período": col_periodo}
    for key, label in DRE_REQUIRED_COLUMNS.items():
        col = _find_column(df_dre, label)
        if col:
            colunas[key] = col

    df_base = df_dre[list(dict.fromkeys(colunas.values()))].copy()
    df_base = df_base.rename(columns={col_inst: "Instituição", col_periodo: "Período"})

    for key, col in colunas.items():
        if key in ("Instituição", "Período"):
            continue
        df_base[col] = _coerce_numeric(df_base[col])

    return df_base, colunas


def _soma_obrigatoria(df: pd.DataFrame, colunas: Tuple[str, ...]) -> Optional[pd.Series]:
    """Soma colunas exigindo todas presentes e não nulas na linha.

    Equivale, de forma vetorizada, a `critical_screens._sum_required_values`:
    qualquer componente ausente invalida a linha inteira (NaN), sem imputar zero.
    Retorna ``None`` quando nenhuma das colunas existe no DataFrame.
    """
    cols_presentes = [_find_column(df, col) for col in colunas]
    cols_presentes = [col for col in cols_presentes if col]
    if not cols_presentes:
        return None
    if len(cols_presentes) < len(colunas):
        # Componente estruturalmente ausente na base: a soma nunca seria válida.
        return pd.Series(np.nan, index=df.index, dtype="float64")
    bloco = pd.DataFrame({col: _coerce_numeric(df[col]) for col in cols_presentes})
    return bloco.sum(axis=1, min_count=len(cols_presentes)).astype("float64")


def _resolve_carteira_credito_bruta_series(df_ativo: pd.DataFrame) -> pd.Series:
    """Reconstrói `Carteira de Crédito*` do Relatório 2 na mesma regra do app.

    Espelha `critical_screens.resolve_carteira_credito_bruta_value` de forma
    vetorizada (a versão escalar é a fonte canônica da regra e o teste
    `test_custo_credito.py` trava a equivalência entre as duas):

    - até 2024: componentes legados (d1 + e1 + f); fallback líquido (e + f + g + h);
    - 2025+: Valor Contábil Bruto (e1 + f1 + g1 + h1); fallback líquido.

    Em qualquer cenário, componente ausente invalida a soma (não imputa zero).
    """
    if df_ativo is None or df_ativo.empty:
        return pd.Series(dtype="float64")

    anos = df_ativo["Período"].astype(str).apply(lambda p: _parse_periodo(p)[0])
    anos = pd.to_numeric(anos, errors="coerce")

    legacy = _soma_obrigatoria(df_ativo, CARTEIRA_LEGACY_COLUMNS)
    vcb = _soma_obrigatoria(df_ativo, CARTEIRA_VCB_COLUMNS)
    net = _soma_obrigatoria(df_ativo, CARTEIRA_NET_COLUMNS)

    vazio = pd.Series(np.nan, index=df_ativo.index, dtype="float64")
    legacy = vazio if legacy is None else legacy
    vcb = vazio if vcb is None else vcb
    net = vazio if net is None else net

    # Ano ausente cai no ramo 2025+ para acompanhar o `else` da versão escalar.
    mask_legado = anos.notna() & (anos <= 2024)
    principal_por_ano = vcb.where(~mask_legado, legacy)
    return principal_por_ano.combine_first(net)


def _carteira_credito_lookup(
    df_principal: pd.DataFrame,
    df_ativo: Optional[pd.DataFrame],
) -> Tuple[pd.DataFrame, str]:
    """Retorna (lookup Instituição+Período -> Carteira de Crédito*, fonte usada)."""
    if df_ativo is not None and not df_ativo.empty:
        col_inst = _find_column(df_ativo, "Instituição") or _find_column(df_ativo, "Instituicao")
        col_periodo = _find_column(df_ativo, "Período") or _find_column(df_ativo, "Periodo")
        if col_inst and col_periodo:
            df_norm = df_ativo.rename(columns={col_inst: "Instituição", col_periodo: "Período"})
            serie = _resolve_carteira_credito_bruta_series(df_norm)
            if not serie.empty and serie.notna().any():
                lookup = pd.DataFrame(
                    {
                        "Instituição": df_norm["Instituição"],
                        "Período": df_norm["Período"].astype(str),
                        "Carteira de Crédito*": serie.values,
                    }
                )
                lookup = lookup.groupby(["Instituição", "Período"], as_index=False)[
                    "Carteira de Crédito*"
                ].sum(min_count=1)
                return lookup, "relatorio_2_carteira_credito_bruta"

    col_inst = _find_column(df_principal, "Instituição") or _find_column(df_principal, "Instituicao")
    col_periodo = _find_column(df_principal, "Período") or _find_column(df_principal, "Periodo")
    if col_inst and col_periodo:
        for candidato in CARTEIRA_PRINCIPAL_FALLBACK_COLUMNS:
            if candidato not in df_principal.columns:
                continue
            lookup = pd.DataFrame(
                {
                    "Instituição": df_principal[col_inst],
                    "Período": df_principal[col_periodo].astype(str),
                    "Carteira de Crédito*": _coerce_numeric(df_principal[candidato]),
                }
            )
            lookup = lookup.groupby(["Instituição", "Período"], as_index=False)[
                "Carteira de Crédito*"
            ].sum(min_count=1)
            return lookup, f"fallback_principal:{candidato}"

    vazio = pd.DataFrame(columns=["Instituição", "Período", "Carteira de Crédito*"])
    return vazio, "indisponivel"


def _prepare_base_principal(df_principal: pd.DataFrame) -> pd.DataFrame:
    col_periodo = _find_column(df_principal, "Período") or _find_column(df_principal, "Periodo")
    col_inst = _find_column(df_principal, "Instituição") or _find_column(df_principal, "Instituicao")
    col_captacoes = _find_column(df_principal, "Captações") or _find_column(df_principal, "Captação")

    if col_periodo is None or col_inst is None or col_captacoes is None:
        raise ValueError("Colunas necessárias (Período/Instituição/Captações) não encontradas no principal")

    df_base = df_principal[[col_inst, col_periodo, col_captacoes]].copy()
    df_base = df_base.rename(
        columns={
            col_inst: "Instituição",
            col_periodo: "Período",
            col_captacoes: "Captações",
        }
    )
    df_base["Captações"] = _coerce_numeric(df_base["Captações"])
    return df_base


def build_derived_metrics(
    df_dre: pd.DataFrame,
    df_principal: pd.DataFrame,
    df_ativo: Optional[pd.DataFrame] = None,
) -> Tuple[pd.DataFrame, DerivedMetricsStats]:
    """Calcula métricas derivadas no formato LONG/TIDY.

    `df_ativo` (Relatório 2) é opcional e serve apenas ao denominador de
    `Custo de Crédito (%)`. Sem ele, o denominador cai para a carteira do cache
    principal e a fonte usada fica registrada em `DerivedMetricsStats.carteira_fonte`.
    """
    df_base, colunas_dre = _prepare_base_dre(df_dre)
    df_principal_base = _prepare_base_principal(df_principal)

    periodo_type = _detect_period_type(df_base["Período"].dropna().unique())

    denominador_counts: Dict[str, int] = {metric: 0 for metric in DERIVED_METRICS}

    def _col(key: str) -> Optional[pd.Series]:
        col = colunas_dre.get(key)
        if col is None:
            return None
        return df_base[col]

    desp_pdd = _col("desp_pdd")
    desp_pdd_credito = _col("desp_pdd_credito")
    rec_credito = _col("rec_credito")
    rec_arrendamento = _col("rec_arrendamento")
    rec_outras = _col("rec_outras")
    rec_liquidez = _col("rec_liquidez")
    rec_tvm = _col("rec_tvm")
    desp_captacao = _col("desp_captacao")

    if desp_pdd is None:
        raise ValueError("Coluna de Desp. PDD não encontrada no DRE")

    if rec_credito is None or rec_arrendamento is None or rec_outras is None:
        raise ValueError("Colunas para Resultado de Intermediação Financeira Bruto não encontradas no DRE")

    if rec_liquidez is None or rec_tvm is None:
        raise ValueError("Colunas para Resultado de Intermediação Financeira Bruto não encontradas no DRE")

    resultado_intermed_bruto = rec_liquidez + rec_tvm + rec_credito + rec_arrendamento + rec_outras

    if desp_captacao is None:
        raise ValueError("Coluna de Desp. Captação não encontrada no DRE")

    periodos = df_base["Período"].astype(str)

    # Para Set/Dez, DRE vem como 2º semestre (não YTD). Precisamos acumular
    # com Jun e anualizar na mesma lógica de captação.
    desp_pdd_ytd = _acumular_dre_ytd_por_periodo(df_base, desp_pdd)
    desp_pdd_anualizada = _anualizar_serie_por_periodo(desp_pdd_ytd, periodos)

    resultado_intermed_bruto_ytd = _acumular_dre_ytd_por_periodo(df_base, resultado_intermed_bruto)
    resultado_intermed_bruto_anualizado = _anualizar_serie_por_periodo(resultado_intermed_bruto_ytd, periodos)

    desp_captacao_ytd = _acumular_dre_ytd_por_periodo(df_base, desp_captacao)
    desp_captacao_anualizada = _anualizar_serie_por_periodo(desp_captacao_ytd, periodos)

    df_merge = df_base[["Instituição", "Período"]].copy()
    df_merge = df_merge.merge(
        df_principal_base,
        on=["Instituição", "Período"],
        how="left",
        suffixes=("", "_principal"),
    )

    dados_metricas = []

    serie_metric_2 = _safe_ratio(
        desp_pdd_anualizada,
        resultado_intermed_bruto_anualizado,
        METRIC_PDD_INTERMED,
        denominador_counts,
    )
    dados_metricas.append((METRIC_PDD_INTERMED, serie_metric_2))

    serie_metric_3 = _safe_ratio(
        desp_captacao_anualizada,
        _media_captacoes_ytd(df_merge["Instituição"], df_merge["Período"], df_merge["Captações"]),
        METRIC_DESP_CAPT,
        denominador_counts,
    )
    dados_metricas.append((METRIC_DESP_CAPT, serie_metric_3))

    # Custo de Crédito: |PDD de crédito (f3)| anualizada ÷ Carteira de Crédito*.
    # f3 só existe no layout IFData 2025+; períodos anteriores permanecem NaN
    # (o layout antigo tem apenas o PDD total b5, sem abertura por tipo de ativo).
    carteira_lookup, carteira_fonte = _carteira_credito_lookup(df_principal, df_ativo)
    if desp_pdd_credito is None:
        serie_custo_credito = pd.Series(np.nan, index=df_base.index, dtype="float64")
        denominador_counts[METRIC_CUSTO_CREDITO] = int(len(df_base))
    else:
        desp_pdd_credito_ytd = _acumular_dre_ytd_por_periodo(df_base, desp_pdd_credito)
        desp_pdd_credito_anualizada = _anualizar_serie_por_periodo(desp_pdd_credito_ytd, periodos)
        if carteira_lookup.empty:
            carteira_serie = pd.Series(np.nan, index=df_base.index, dtype="float64")
        else:
            df_carteira = df_base[["Instituição", "Período"]].copy()
            df_carteira["Período"] = df_carteira["Período"].astype(str)
            carteira_serie = df_carteira.merge(
                carteira_lookup,
                on=["Instituição", "Período"],
                how="left",
            )["Carteira de Crédito*"]
            carteira_serie.index = df_base.index
        serie_custo_credito = _safe_ratio(
            desp_pdd_credito_anualizada.abs(),
            pd.to_numeric(carteira_serie, errors="coerce"),
            METRIC_CUSTO_CREDITO,
            denominador_counts,
        )
    dados_metricas.append((METRIC_CUSTO_CREDITO, serie_custo_credito))

    registros = []
    for label, serie in dados_metricas:
        df_metric = df_base[["Instituição", "Período"]].copy()
        df_metric["Métrica"] = label
        df_metric["Valor"] = serie
        df_metric["Unidade"] = "pct"
        registros.append(df_metric)

    df_final = pd.concat(registros, ignore_index=True)

    df_final["Instituição"] = df_final["Instituição"].astype("category")
    df_final["Período"] = df_final["Período"].astype("category")
    df_final["Métrica"] = df_final["Métrica"].astype("category")
    df_final["Unidade"] = df_final["Unidade"].astype("category")
    df_final["Valor"] = df_final["Valor"].astype("float32")

    stats = DerivedMetricsStats(
        denominador_zero_ou_nan=denominador_counts,
        periodos_detectados=sorted(df_final["Período"].astype(str).unique().tolist()),
        period_type=periodo_type,
        total_registros=len(df_final),
        carteira_fonte=carteira_fonte,
    )

    return df_final, stats


def load_derived_metrics_slice(
    cache: DerivedMetricsCache,
    periodos: Optional[Iterable[str]] = None,
    instituicoes: Optional[Iterable[str]] = None,
    metricas: Optional[Iterable[str]] = None,
) -> pd.DataFrame:
    """Carrega recortes do cache derivado sem carregar todo o parquet em RAM."""
    if not cache.arquivo_dados.exists() and not cache.arquivo_dados_pickle.exists():
        return pd.DataFrame()

    filtros = []
    if periodos:
        filtros.append(("Período", "in", list(periodos)))
    if instituicoes:
        filtros.append(("Instituição", "in", list(instituicoes)))
    if metricas:
        filtros.append(("Métrica", "in", list(metricas)))

    if cache.arquivo_dados.exists():
        try:
            import pyarrow.dataset as ds

            dataset = ds.dataset(cache.arquivo_dados)
            if filtros:
                tabela = dataset.to_table(filter=_build_arrow_filter(filtros))
            else:
                tabela = dataset.to_table()
            df = tabela.to_pandas()
        except Exception as e:
            logger.warning(f"Falha ao ler parquet com filtros ({e}); usando fallback completo")
            df = pd.read_parquet(cache.arquivo_dados)
            df = _apply_filters(df, filtros)
    else:
        import pickle

        with open(cache.arquivo_dados_pickle, "rb") as f:
            df = pickle.load(f)
        df = _apply_filters(df, filtros)

    return df


def _apply_filters(df: pd.DataFrame, filtros: List[Tuple[str, str, list]]) -> pd.DataFrame:
    if not filtros:
        return df
    df_out = df
    for col, op, valores in filtros:
        if col not in df_out.columns:
            continue
        if op == "in":
            df_out = df_out[df_out[col].isin(valores)]
    return df_out


def _build_arrow_filter(filtros: List[Tuple[str, str, list]]):
    import pyarrow.dataset as ds

    filtro_final = None
    for col, op, valores in filtros:
        if op != "in":
            continue
        cond = ds.field(col).isin(valores)
        filtro_final = cond if filtro_final is None else filtro_final & cond
    return filtro_final
