"""Cache curado para Snapshot e Peers."""

from __future__ import annotations

from datetime import datetime
import json
import logging
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd

from .availability import display_period_to_api, filter_supported_periods
from .base import BaseCache, CacheConfig, CacheResult
from .bloprudencial import load_bloprudencial_df_cached
from .diagnostics import max_period_from_metadata, normalize_period_reference
from .derived_metrics import (
    _acumular_dre_ytd_por_periodo,
    _anualizar_serie_por_periodo,
    _media_captacoes_ytd,
    _prepare_base_dre,
    _prepare_base_principal,
)
from .institutions import (
    build_institution_to_conglomerate_map,
    canonicalize_institution_dataframe,
    canonicalize_institution_name,
    normalize_institution_name,
)

if TYPE_CHECKING:
    from .manager import CacheManager

logger = logging.getLogger("ifdata_cache")

CRITICAL_SCREENS_SCHEMA_VERSION = 3
BUNDLED_CRITICAL_SCREENS_DIR = Path("data") / "bundled" / "critical_screens"


CRITICAL_SCREENS_CONFIG = CacheConfig(
    nome="critical_screens",
    descricao="Métricas curadas para Snapshot e Peers",
    subdir="critical_screens",
    arquivo_dados="dados.parquet",
    arquivo_metadata="metadata.json",
    github_url_base=None,
    max_idade_horas=None,
    colunas_obrigatorias=["Instituição", "Período", "InstituiçãoKey"],
)


CRITICAL_EXTRA_METRICS = [
    "Ativos Líquidos",
    "Depósitos Totais",
    "Core Funding",
    "Core Funding*",
    "Carteira de Crédito Bruta",
    "Carteira de Crédito*",
    "Perda Esperada",
    "Perda Esperada / Carteira de Crédito Bruta",
    "Perda Esperada / Carteira de Crédito*",
    "Carteira de Crédito Classificada",
    "Carteira de Créd. Class. C4+C5",
    "Carteira de Créd. Class. C4+C5 / Carteira Classificada",
    "Perda Esperada / (Carteira C4 + C5)",
    "Saldo PDD Crédito",
    "Saldo PDD Outros Créditos",
    "PDD Total 4060",
    "Carteira Estágio 1",
    "Ativos Estágio 2",
    "Ativos Estágio 3",
    "PDD / Estágio 3",
    "Perda Esperada / Estágio 3",
    "Perda Esperada / Est2+3",
    "Índice de Capital Principal (CET1)",
    "Índice de Basileia Total (%)",
]

CRITICAL_BASE_METRICS = [
    "Ativo Total",
    "Patrimônio Líquido",
    "Lucro Líquido Acumulado YTD",
    "Lucro Líquido Trimestral",
    "ROE Ac. Anualizado (%)",
    "ROE trimestral anualizado (%)",
    "ROE Ac. YTD an. (%)",
    "Crédito / Captações",
    "Desp Captação / Captação",
]

CRITICAL_TRACE_COLUMNS = [
    "InstituiçãoRaw",
    "Trace::PL Dez Ano Anterior",
    "Trace::Fator Anualização",
    "Trace::Ativos Líquidos::Disponibilidades (a)",
    "Trace::Ativos Líquidos::Aplicações Interfinanceiras de Liquidez (b)",
    "Trace::Ativos Líquidos::Títulos e Valores Mobiliários (c)",
    "Trace::Carteira::Operações de Crédito (d1)",
    "Trace::Carteira::Arrendamento Mercantil a Receber (e1)",
    "Trace::Carteira::Outros Créditos - Líquido de Provisão (f)",
    "Trace::Carteira::Valor Contábil Bruto (e1)",
    "Trace::Carteira::Valor Contábil Bruto (f1)",
    "Trace::Carteira::Valor Contábil Bruto (g1)",
    "Trace::Carteira::Valor Contábil Bruto (h1)",
    "Trace::Perda Esperada::Perda Esperada (e2)",
    "Trace::Perda Esperada::Hedge de Valor Justo (e3)",
    "Trace::Perda Esperada::Ajuste a Valor Justo (e4)",
    "Trace::Perda Esperada::Perda Esperada (f2)",
    "Trace::Perda Esperada::Hedge de Valor Justo (f3)",
    "Trace::Perda Esperada::Perda Esperada (g2)",
    "Trace::Perda Esperada::Hedge de Valor Justo (g3)",
    "Trace::Perda Esperada::Ajuste a Valor Justo (g4)",
    "Trace::Perda Esperada::Perda Esperada (h2)",
    "Trace::Depósitos Totais::Depósitos (e)",
    "Trace::Depósitos Totais::Depósitos à Vista (a1)",
    "Trace::Depósitos Totais::Depósitos de Poupança (a2)",
    "Trace::Depósitos Totais::Depósitos Interfinanceiros (a3)",
    "Trace::Depósitos Totais::Depósitos a Prazo (a4)",
    "Trace::Depósitos Totais::Outros Depósitos (a5)",
    "Trace::Depósitos Totais::Depósitos Outros (a6)",
    "Trace::Core Funding::Captações (e)",
    "Trace::Core Funding::Instrumentos de Dívida Elegíveis a Capital (h)",
    "Trace::Capital::Capital Principal",
    "Trace::Capital::Capital Complementar",
    "Trace::Capital::Capital Nível II",
    "Trace::Capital::RWA Total",
    "Trace::Capital::Índice CET1 Publicado",
    "Trace::Capital::Índice Basileia Publicado",
    "Trace::Desp Captação::Despesa YTD",
    "Trace::Desp Captação::Despesa Anualizada",
    "Trace::Desp Captação::Captações Média YTD",
]


SOURCE_CACHE_TYPES = [
    "principal",
    "capital",
    "ativo",
    "passivo",
    "dre",
    "carteira_pf",
    "carteira_pj",
    "carteira_instrumentos",
]
CRITICAL_SOURCE_TYPES = [*SOURCE_CACHE_TYPES, "bloprudencial"]


class CriticalScreensCache(BaseCache):
    """Cache materializado para consumo rápido das telas críticas."""

    def __init__(self, base_dir: Path):
        super().__init__(CRITICAL_SCREENS_CONFIG, base_dir)

    @property
    def bundled_dir(self) -> Path:
        return self.base_dir / BUNDLED_CRITICAL_SCREENS_DIR

    @property
    def bundled_data_file(self) -> Path:
        return self.bundled_dir / self.config.arquivo_dados

    @property
    def bundled_metadata_file(self) -> Path:
        return self.bundled_dir / self.config.arquivo_metadata

    def bundle_available(self) -> bool:
        return self.bundled_data_file.exists() and self.bundled_metadata_file.exists()

    def bootstrap_local_from_bundle(self) -> CacheResult:
        """Replica o artefato bundled para o diretório de cache local."""
        if not self.bundle_available():
            return CacheResult(
                sucesso=False,
                mensagem="Artefato bundled de critical_screens indisponível",
                fonte="nenhum",
            )

        try:
            self._garantir_diretorio()
            shutil.copy2(self.bundled_data_file, self.arquivo_dados)
            shutil.copy2(self.bundled_metadata_file, self.arquivo_metadata)
        except Exception as exc:
            return CacheResult(
                sucesso=False,
                mensagem=f"Falha ao copiar artefato bundled: {exc}",
                fonte="nenhum",
            )
        return self.carregar_local()

    def sync_bundle_from_local(self) -> CacheResult:
        """Atualiza o artefato bundled a partir do cache local atual."""
        if not self.existe() or not self.arquivo_metadata.exists():
            return CacheResult(
                sucesso=False,
                mensagem="Cache local de critical_screens indisponível para bundle",
                fonte="nenhum",
            )

        try:
            self.bundled_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.arquivo_dados, self.bundled_data_file)
            shutil.copy2(self.arquivo_metadata, self.bundled_metadata_file)
        except Exception as exc:
            return CacheResult(
                sucesso=False,
                mensagem=f"Falha ao atualizar artefato bundled: {exc}",
                fonte="nenhum",
            )
        return CacheResult(
            sucesso=True,
            mensagem="Artefato bundled de critical_screens atualizado",
            fonte="cache_local",
        )

    def baixar_remoto(self):
        return CacheResult(
            sucesso=False,
            mensagem="Cache critical_screens não possui fonte remota",
            fonte="nenhum",
        )

    def extrair_periodo(self, periodo: str, **kwargs):
        return CacheResult(
            sucesso=False,
            mensagem="Cache critical_screens não suporta extração por período",
            fonte="nenhum",
        )


def _read_metadata_if_exists(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _critical_screens_schema_valid(metadata: Optional[dict]) -> bool:
    if not metadata:
        return False
    extra = metadata.get("extra") or {}
    return extra.get("schema_version") == CRITICAL_SCREENS_SCHEMA_VERSION


def _parse_metadata_timestamp(metadata: Optional[dict]) -> Optional[datetime]:
    if not metadata:
        return None
    texto = str(metadata.get("timestamp_salvamento") or "").strip()
    if not texto:
        return None
    try:
        return datetime.fromisoformat(texto.replace("Z", "+00:00"))
    except Exception:
        return None


def _bundle_is_newer_than_local(
    local_metadata: Optional[dict],
    bundled_metadata: Optional[dict],
) -> bool:
    if not _critical_screens_schema_valid(bundled_metadata):
        return False
    if not _critical_screens_schema_valid(local_metadata):
        return True

    local_period_ref = normalize_period_reference(max_period_from_metadata(local_metadata))
    bundled_period_ref = normalize_period_reference(max_period_from_metadata(bundled_metadata))
    if bundled_period_ref and bundled_period_ref != local_period_ref:
        return bundled_period_ref > local_period_ref

    local_ts = _parse_metadata_timestamp(local_metadata)
    bundled_ts = _parse_metadata_timestamp(bundled_metadata)
    if local_ts is None:
        return bundled_ts is not None
    if bundled_ts is None:
        return False
    return bundled_ts > local_ts


def _missing_local_source_caches(cache_manager: "CacheManager") -> list[str]:
    missing: list[str] = []
    for cache_name in CRITICAL_SOURCE_TYPES:
        cache = cache_manager.get_cache(cache_name)
        if cache is None or not cache.existe():
            missing.append(cache_name)
    return missing


def get_critical_screens_runtime_status(
    *,
    base_dir: Path | None = None,
    manager: "CacheManager" | None = None,
) -> dict[str, Any]:
    """Diagnóstico do artefato curado para uso em runtime.

    Runtime e manutenção têm regras diferentes:
    - runtime deve privilegiar o artefato curado já materializado/bundled;
    - refresh só faz sentido quando todas as fontes locais existem.
    """
    root = Path(base_dir).resolve() if base_dir else Path(__file__).resolve().parents[2]
    from .manager import CacheManager

    cache_manager = manager or CacheManager(root)
    cache = CriticalScreensCache(root)

    local_metadata = _read_metadata_if_exists(cache.arquivo_metadata)
    bundled_metadata = _read_metadata_if_exists(cache.bundled_metadata_file)

    local_ready = cache.existe() and _critical_screens_schema_valid(local_metadata)
    bundle_ready = cache.bundle_available() and _critical_screens_schema_valid(bundled_metadata)
    bundle_newer_than_local = bundle_ready and _bundle_is_newer_than_local(local_metadata, bundled_metadata)
    missing_local_sources = _missing_local_source_caches(cache_manager)
    can_materialize_from_local_sources = not missing_local_sources

    if bundle_newer_than_local:
        mode = "bootstrap_bundle"
        message = "artefato bundled de critical_screens está mais novo e deve substituir o cache local"
    elif local_ready:
        mode = "use_local"
        message = "artefato local de critical_screens está pronto para runtime"
    elif bundle_ready:
        mode = "bootstrap_bundle"
        message = "artefato bundled de critical_screens está pronto para bootstrap local"
    elif can_materialize_from_local_sources:
        mode = "materialize_local"
        message = "artefato curado ausente; fontes locais completas permitem rematerialização explícita"
    else:
        mode = "missing"
        message = (
            "artefato curado ausente/inválido e fontes locais incompletas; "
            "runtime não deve iniciar rematerialização remota automática"
        )

    return {
        "cache": cache,
        "local_ready": local_ready,
        "bundle_ready": bundle_ready,
        "bundle_newer_than_local": bundle_newer_than_local,
        "can_materialize_from_local_sources": can_materialize_from_local_sources,
        "missing_local_source_caches": missing_local_sources,
        "mode": mode,
        "message": message,
        "local_metadata": local_metadata,
        "bundled_metadata": bundled_metadata,
    }


def _normalize_period_display(periodo: str | None) -> str:
    return str(periodo or "").strip()


def _api_to_display_period(periodo_api: str) -> str:
    ano = periodo_api[:4]
    mes = periodo_api[4:6]
    trimestre = {"03": "1", "06": "2", "09": "3", "12": "4"}.get(mes)
    if trimestre is not None:
        return f"{trimestre}/{ano}"
    return f"{mes}/{ano}"


def _pick_col(df: Optional[pd.DataFrame], candidates: Sequence[str]) -> Optional[str]:
    if df is None or df.empty:
        return None

    cols = list(df.columns)
    if not cols:
        return None

    normalized = {normalize_institution_name(str(col)): col for col in cols}
    for candidate in candidates:
        key = normalize_institution_name(candidate)
        if key in normalized:
            return normalized[key]

    for candidate in candidates:
        key = normalize_institution_name(candidate)
        for col in cols:
            col_key = normalize_institution_name(col)
            if key and (key in col_key or col_key in key):
                return col
    return None


def _pick_exact_col(df: Optional[pd.DataFrame], candidates: Sequence[str]) -> Optional[str]:
    if df is None or df.empty:
        return None
    normalized = {normalize_institution_name(str(col)): col for col in df.columns}
    for candidate in candidates:
        key = normalize_institution_name(candidate)
        if key in normalized:
            return normalized[key]
    return None


def _coerce_numeric_value(value) -> Optional[float]:
    if value is None or pd.isna(value):
        return None
    try:
        coerced = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    except Exception:
        return None
    if pd.isna(coerced):
        return None
    return float(coerced)


def _sum_values(values: Iterable[object]) -> Optional[float]:
    nums = [_coerce_numeric_value(v) for v in values]
    nums = [v for v in nums if v is not None]
    if not nums:
        return None
    return float(sum(nums))


def _sum_required_values(values: Iterable[object]) -> Optional[float]:
    nums = [_coerce_numeric_value(v) for v in values]
    if any(v is None for v in nums):
        return None
    return float(sum(nums))


def _calc_ratio(valor_num, valor_den) -> Optional[float]:
    num = _coerce_numeric_value(valor_num)
    den = _coerce_numeric_value(valor_den)
    if num is None or den is None or den == 0:
        return None
    return float(num) / float(den)


def _period_part_to_quarter_idx(value) -> Optional[int]:
    parte_txt = str(value).strip()
    if parte_txt == "03":
        return 1
    if parte_txt == "06":
        return 2
    if parte_txt == "09":
        return 3
    if parte_txt == "12":
        return 4
    try:
        parte = int(parte_txt)
    except Exception:
        return None
    if parte in (1, 2, 3, 4):
        return parte
    if parte == 6:
        return 2
    if parte == 9:
        return 3
    if parte == 12:
        return 4
    return None


def _annualization_factor(months) -> float | pd.Series:
    if isinstance(months, pd.Series):
        return pd.to_numeric(months, errors="coerce").map(_annualization_factor)
    if months == 3:
        return 4.0
    if months == 6:
        return 2.0
    if months == 9:
        return 12 / 9
    if months == 12:
        return 1.0
    return 12 / months if months and months > 0 else 1.0


def _normalize_principal_metrics(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df

    out = df.copy()
    periodo_split = out["Período"].astype(str).str.split("/", expand=True)
    out["_tri_idx_tmp"] = pd.to_numeric(periodo_split[0], errors="coerce").map(_period_part_to_quarter_idx)
    out["_ano_tmp"] = pd.to_numeric(periodo_split[1], errors="coerce")
    out["_mes_tmp"] = out["_tri_idx_tmp"].map({1: 3, 2: 6, 3: 9, 4: 12}).fillna(12)

    ll_col = "Lucro Líquido Acumulado YTD"
    pl_col = "Patrimônio Líquido"
    if ll_col in out.columns:
        ll_ytd_ajustado = pd.Series(np.nan, index=out.index, dtype="float64")
        ll_trimestral = pd.Series(np.nan, index=out.index, dtype="float64")
        for (_, _), idx in out.groupby(["InstituiçãoKey", "_ano_tmp"], dropna=False, observed=False).groups.items():
            grupo = out.loc[idx].copy().sort_values("_tri_idx_tmp")
            raw_map = pd.to_numeric(grupo[ll_col], errors="coerce")
            raw_map = pd.Series(raw_map.to_numpy(), index=grupo["_tri_idx_tmp"].to_numpy()).to_dict()
            for row_idx, tri_idx in zip(grupo.index, grupo["_tri_idx_tmp"]):
                tri = int(tri_idx) if pd.notna(tri_idx) else None
                ll_db = raw_map.get(tri)
                if tri is None or pd.isna(ll_db):
                    continue
                if tri in (1, 2):
                    ll_ytd_ajustado.at[row_idx] = float(ll_db)
                elif tri in (3, 4):
                    ll_jun = raw_map.get(2)
                    if pd.notna(ll_jun):
                        ll_ytd_ajustado.at[row_idx] = float(ll_jun) + float(ll_db)
                if tri in (1, 3):
                    ll_trimestral.at[row_idx] = float(ll_db)
                elif tri == 2:
                    ll_mar = raw_map.get(1)
                    if pd.notna(ll_mar):
                        ll_trimestral.at[row_idx] = float(ll_db) - float(ll_mar)
                elif tri == 4:
                    ll_set = raw_map.get(3)
                    if pd.notna(ll_set):
                        ll_trimestral.at[row_idx] = float(ll_db) - float(ll_set)
        out[ll_col] = ll_ytd_ajustado.where(ll_ytd_ajustado.notna(), pd.to_numeric(out[ll_col], errors="coerce"))
        out["Lucro Líquido Trimestral"] = ll_trimestral

    if {ll_col, pl_col}.issubset(out.columns):
        ll_num = pd.to_numeric(out[ll_col], errors="coerce")
        pl_num = pd.to_numeric(out[pl_col], errors="coerce")
        pl_dez = (
            out[out["_tri_idx_tmp"] == 4]
            .dropna(subset=["_ano_tmp"])
            .sort_values(["InstituiçãoKey", "_ano_tmp", "Período"])
            .drop_duplicates(subset=["InstituiçãoKey", "_ano_tmp"], keep="last")
            .set_index(["InstituiçãoKey", "_ano_tmp"])[pl_col]
        )
        idx_prev = pd.MultiIndex.from_arrays(
            [out["InstituiçãoKey"].values, (out["_ano_tmp"] - 1).values],
            names=["InstituiçãoKey", "_ano_tmp"],
        )
        pl_dez_prev = pd.to_numeric(pl_dez.reindex(idx_prev).to_numpy(), errors="coerce")
        pl_medio = (pl_num + pl_dez_prev) / 2
        fator_anualizacao = _annualization_factor(out["_mes_tmp"])
        roe = (fator_anualizacao * ll_num) / pl_medio.where(pl_medio > 0, np.nan)
        out["ROE Ac. Anualizado (%)"] = roe
        out["ROE Ac. YTD an. (%)"] = roe
        out["Trace::PL Dez Ano Anterior"] = pl_dez_prev
        out["Trace::Fator Anualização"] = fator_anualizacao
        ll_trimestral = pd.to_numeric(out.get("Lucro Líquido Trimestral"), errors="coerce")
        roe_tri = (ll_trimestral * 4.0) / pl_medio.where(pl_medio > 0, np.nan)
        out["ROE trimestral anualizado (%)"] = roe_tri

    return out.drop(columns=["_tri_idx_tmp", "_ano_tmp", "_mes_tmp"], errors="ignore")


def _prepare_frame(
    df: Optional[pd.DataFrame],
    catalog_map: Dict[str, str],
    *,
    base_dir: Path | None = None,
    canonicalize_names: bool = True,
    dedupe: bool = True,
    extra_frames: Iterable[pd.DataFrame | None] = (),
) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    if "Instituição" not in out.columns or "Período" not in out.columns:
        return pd.DataFrame()

    out["InstituiçãoRaw"] = out["Instituição"].astype(str).str.strip()
    extra_frames = tuple(extra_frames or ())

    if canonicalize_names:
        if extra_frames:
            # Em publicações recentes o Passivo pode chegar com placeholders
            # "[IF ...]". Nesses casos, usamos o principal como autoridade
            # de nomes por CodInst antes de montar o lookup textual do curado.
            out = canonicalize_institution_dataframe(
                out,
                catalog_map=catalog_map,
                base_dir=base_dir,
                name_column="Instituição",
                extra_frames=extra_frames,
            )
            out["Instituição"] = out["Instituição"].astype(str).str.strip()
        else:
            nomes_brutos = out["InstituiçãoRaw"].astype(str)
            mapa_canonico = {
                nome: canonicalize_institution_name(nome, catalog_map=catalog_map)
                for nome in nomes_brutos.dropna().unique().tolist()
            }
            out["Instituição"] = nomes_brutos.map(mapa_canonico).fillna(nomes_brutos)
    else:
        out["Instituição"] = out["InstituiçãoRaw"].astype(str).str.strip()

    out["Período"] = out["Período"].astype(str).str.strip()
    out["InstituiçãoKey"] = out["Instituição"].map(normalize_institution_name)
    out = out[out["InstituiçãoKey"].astype(bool)].copy()
    if not dedupe:
        return out
    metric_columns = [
        col
        for col in out.columns
        if col not in {"Instituição", "InstituiçãoRaw", "Período", "InstituiçãoKey"}
    ]
    out["_canonical_exact"] = (
        out["InstituiçãoRaw"].map(normalize_institution_name) == out["InstituiçãoKey"]
    ).astype(int)
    out["_non_null_score"] = out[metric_columns].notna().sum(axis=1) if metric_columns else 0
    out = out.sort_values(
        ["InstituiçãoKey", "Período", "_canonical_exact", "_non_null_score", "InstituiçãoRaw"],
        ascending=[True, True, False, False, True],
    )
    out = out.drop_duplicates(subset=["InstituiçãoKey", "Período"], keep="first")
    out = out.drop(columns=["_canonical_exact", "_non_null_score"], errors="ignore")
    return out


def _prepare_lookup(df: Optional[pd.DataFrame], columns: Sequence[Optional[str]]) -> Dict[tuple[str, str], dict]:
    if df is None or df.empty:
        return {}
    valid_columns = list(dict.fromkeys([col for col in columns if col and col in df.columns]))
    if not valid_columns:
        return {}
    base = df[["InstituiçãoKey", "Período", *valid_columns]].copy()
    base = base.dropna(subset=["InstituiçãoKey", "Período"])
    if base.empty:
        return {}
    return base.set_index(["InstituiçãoKey", "Período"]).to_dict("index")


def _lk_get(lookup: Dict[tuple[str, str], dict], institution_key: str, periodo: str, coluna: Optional[str]):
    if not lookup or not coluna:
        return None
    row = lookup.get((institution_key, periodo))
    if row is None:
        return None
    return row.get(coluna)


def _list_local_bloprud_periods(base_dir: Path) -> set[str]:
    periodos: set[str] = set()
    cache_dir = base_dir / "data" / "cache" / "bcb_bloprudencial"
    for pattern in ("csv/*BLOPRUDENCIAL*.CSV", "zips/*BLOPRUDENCIAL*.zip"):
        for path in cache_dir.glob(pattern):
            match = re.match(r"(\d{6})BLOPRUDENCIAL", path.name.upper())
            if match:
                periodos.add(match.group(1))
    for path in base_dir.glob("*BLOPRUDENCIAL*.CSV"):
        match = re.match(r"(\d{6})BLOPRUDENCIAL", path.name.upper())
        if match:
            periodos.add(match.group(1))
    return periodos


def _normalize_bloprud_frame(
    df: Optional[pd.DataFrame],
    periodos_display: Sequence[str],
) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    out = df.copy()
    if "Período" not in out.columns:
        col_data_base = _pick_col(out, ["DATA_BASE", "Data_Base", "data_base"])
        if not col_data_base:
            return pd.DataFrame()
        periodos_api = out[col_data_base].astype(str).str.replace(r"\D", "", regex=True).str[:6]
        out["Período"] = periodos_api.map(_api_to_display_period)

    out["Período"] = out["Período"].astype(str).str.strip()
    periodos_validos = {str(periodo) for periodo in periodos_display if str(periodo).strip()}
    if periodos_validos:
        out = out[out["Período"].isin(periodos_validos)].copy()
    return out


def _load_bloprud_cached(manager: "CacheManager", periodos_display: Sequence[str]) -> pd.DataFrame:
    try:
        resultado = manager.carregar("bloprudencial")
    except Exception as exc:
        logger.warning("[CACHE:CRITICAL_SCREENS] Falha ao carregar cache persistido BLOPRUDENCIAL: %s", exc)
        return pd.DataFrame()

    if not resultado.sucesso or resultado.dados is None or resultado.dados.empty:
        return pd.DataFrame()
    return _normalize_bloprud_frame(resultado.dados, periodos_display)


def _load_bloprud_periods(base_dir: Path, periodos_display: Sequence[str]) -> pd.DataFrame:
    periodos_desejados = sorted(
        {display_period_to_api(periodo) for periodo in periodos_display if display_period_to_api(periodo)}
    )
    periodos_locais = _list_local_bloprud_periods(base_dir)
    if periodos_locais:
        periodos_api = [periodo for periodo in periodos_desejados if periodo in periodos_locais]
        faltantes = sorted(set(periodos_desejados) - set(periodos_api))
        if faltantes:
            logger.info(
                "[CACHE:CRITICAL_SCREENS] BLOPRUDENCIAL indisponível localmente para %d período(s): %s",
                len(faltantes),
                ", ".join(faltantes[:8]),
            )
    else:
        periodos_api = []
    if not periodos_api:
        return pd.DataFrame()

    dfs = []
    for periodo_api in periodos_api:
        try:
            df_periodo = load_bloprudencial_df_cached(
                periodo_api,
                cache_dir=str(base_dir / "data" / "cache" / "bcb_bloprudencial"),
                force_refresh=False,
            )
        except Exception as exc:
            logger.warning("[CACHE:CRITICAL_SCREENS] Falha ao carregar BLOPRUDENCIAL %s: %s", periodo_api, exc)
            continue
        if df_periodo is None or df_periodo.empty:
            continue
        df_periodo = df_periodo.copy()
        df_periodo["Período"] = _api_to_display_period(periodo_api)
        dfs.append(df_periodo)

    if not dfs:
        return pd.DataFrame()
    return pd.concat(dfs, ignore_index=True)


def _load_bloprud_sources(
    *,
    manager: "CacheManager",
    base_dir: Path,
    periodos_display: Sequence[str],
) -> pd.DataFrame:
    periodos_criticos = [str(periodo) for periodo in periodos_display if str(periodo).strip()]
    if not periodos_criticos:
        return pd.DataFrame()

    dfs = []
    persisted = _load_bloprud_cached(manager, periodos_criticos)
    if not persisted.empty:
        dfs.append(persisted)

    periodos_presentes = set()
    for df in dfs:
        if "Período" in df.columns:
            periodos_presentes.update(df["Período"].dropna().astype(str).tolist())

    missing = [periodo for periodo in periodos_criticos if periodo not in periodos_presentes]
    if missing:
        local = _load_bloprud_periods(base_dir, missing)
        if not local.empty:
            dfs.append(local)

    if not dfs:
        return pd.DataFrame()

    combined = pd.concat(dfs, ignore_index=True)
    if "Período" in combined.columns:
        combined = combined.drop_duplicates(keep="last")
    return combined.reset_index(drop=True)


def _source_fingerprints(cache_manager: "CacheManager", root: Path) -> dict:
    fingerprints = {}
    for cache_name in CRITICAL_SOURCE_TYPES:
        cache = cache_manager.get_cache(cache_name)
        if cache is None or not cache.existe():
            fingerprints[cache_name] = None
            continue
        info = cache.get_info()
        fingerprints[cache_name] = {
            "timestamp_salvamento": info.get("timestamp_salvamento"),
            "total_registros": info.get("total_registros"),
            "total_periodos": info.get("total_periodos"),
            "fonte": info.get("fonte"),
        }

    fingerprints["_bloprud_local_periods"] = sorted(_list_local_bloprud_periods(root))
    return fingerprints


def critical_screens_needs_refresh(
    *,
    base_dir: Path | None = None,
    manager: "CacheManager" | None = None,
) -> bool:
    root = Path(base_dir).resolve() if base_dir else Path(__file__).resolve().parents[2]
    from .manager import CacheManager

    cache_manager = manager or CacheManager(root)
    cache = CriticalScreensCache(root)
    if not cache.existe() or not cache.arquivo_metadata.exists():
        return True

    try:
        metadata = json.loads(cache.arquivo_metadata.read_text(encoding="utf-8"))
    except Exception:
        return True

    extra = metadata.get("extra") or {}
    if extra.get("schema_version") != CRITICAL_SCREENS_SCHEMA_VERSION:
        return True

    # Sem todas as fontes locais, não há base para afirmar que o artefato
    # bundled/local está desatualizado em runtime. Esse caso é comum no deploy.
    if _missing_local_source_caches(cache_manager):
        return False

    previous = extra.get("source_fingerprints") or {}
    current = _source_fingerprints(cache_manager, root)
    for key, current_value in current.items():
        if current_value is None:
            continue
        if key == "_bloprud_local_periods" and not current_value:
            continue
        if previous.get(key) != current_value:
            return True
    return False


def _build_bloprud_lookup(df_bloprudencial: Optional[pd.DataFrame], catalog_map: Dict[str, str]) -> Dict[tuple[str, str, str], float]:
    if df_bloprudencial is None or df_bloprudencial.empty:
        return {}

    df = df_bloprudencial.copy()
    col_nome_inst = _pick_col(df, ["NOME_INSTITUICAO", "Instituição", "Instituicao"])
    col_nome_congl = _pick_col(df, ["NOME_CONGL", "Nome_Congl", "nome_congl"])
    col_conta = _pick_col(df, ["CONTA", "Conta", "codigo_conta", "COD_CONTA"])
    col_saldo = _pick_col(df, ["SALDO", "Saldo", "VALOR", "Valor"])
    col_documento = _pick_col(df, ["DOCUMENTO", "Documento", "doc", "cadoc"])
    if not col_conta or not col_saldo or (not col_nome_inst and not col_nome_congl):
        return {}

    if col_documento:
        docs = pd.to_numeric(df[col_documento], errors="coerce")
        mask_4060 = docs == 4060
        if mask_4060.any():
            df = df.loc[mask_4060].copy()

    col_data_base = _pick_col(df, ["DATA_BASE", "Data_Base", "data_base"])
    if col_data_base:
        df["PeríodoApi"] = df[col_data_base].astype(str).str.replace(r"\D", "", regex=True).str[:6]
    else:
        df["PeríodoApi"] = df["Período"].map(display_period_to_api)

    df["_conta"] = df[col_conta].astype(str).str.replace(r"\D", "", regex=True)
    df["_saldo"] = pd.to_numeric(df[col_saldo], errors="coerce")
    df = df[df["_conta"].isin({"1490000004", "1890000006", "3311000002", "3312000001", "3313000000"})].copy()
    if df.empty:
        return {}

    names = []
    if col_nome_congl:
        names.append(df[col_nome_congl].fillna(""))
    if col_nome_inst:
        names.append(df[col_nome_inst].fillna(""))

    if not names:
        return {}

    df["_instituicao_canonica"] = names[0].astype(str)
    for serie in names[1:]:
        serie = serie.astype(str)
        df["_instituicao_canonica"] = df["_instituicao_canonica"].where(df["_instituicao_canonica"].str.strip().ne(""), serie)

    nomes_canonicos = df["_instituicao_canonica"].astype(str)
    mapa_canonico = {
        nome: canonicalize_institution_name(nome, catalog_map=catalog_map)
        for nome in nomes_canonicos.dropna().unique().tolist()
    }
    df["_instituicao_canonica"] = nomes_canonicos.map(mapa_canonico).fillna(nomes_canonicos)
    df["InstituiçãoKey"] = df["_instituicao_canonica"].map(normalize_institution_name)
    df = df[df["InstituiçãoKey"].astype(bool)].copy()
    if df.empty:
        return {}

    grouped = (
        df.groupby(["PeríodoApi", "InstituiçãoKey", "_conta"], dropna=False)["_saldo"]
        .sum(min_count=1)
        .reset_index()
    )
    out: Dict[tuple[str, str, str], float] = {}
    for row in grouped.itertuples(index=False):
        if pd.isna(row[3]):
            continue
        out[(str(row[0]), str(row[1]), str(row[2]))] = float(row[3])
    return out


def _build_desp_capt_lookup(
    df_dre: Optional[pd.DataFrame],
    df_principal: Optional[pd.DataFrame],
    catalog_map: Dict[str, str],
) -> Dict[tuple[str, str], dict]:
    if df_dre is None or df_dre.empty or df_principal is None or df_principal.empty:
        return {}

    try:
        df_dre_base, colunas_dre = _prepare_base_dre(df_dre)
        df_principal_base = _prepare_base_principal(df_principal)
    except Exception:
        return {}

    col_desp_captacao = colunas_dre.get("desp_captacao")
    if not col_desp_captacao or col_desp_captacao not in df_dre_base.columns:
        return {}

    desp_ytd = _acumular_dre_ytd_por_periodo(df_dre_base, pd.to_numeric(df_dre_base[col_desp_captacao], errors="coerce"))
    periodos = df_dre_base["Período"].astype(str)
    desp_anualizada = _anualizar_serie_por_periodo(desp_ytd, periodos)

    df_merge = df_dre_base[["Instituição", "Período"]].copy().merge(
        df_principal_base,
        on=["Instituição", "Período"],
        how="left",
        suffixes=("", "_principal"),
    )
    capt_media_ytd = _media_captacoes_ytd(
        df_merge["Instituição"],
        df_merge["Período"],
        df_merge["Captações"],
    )
    denominador_valido = capt_media_ytd.notna() & (capt_media_ytd != 0)
    ratio = desp_anualizada.where(denominador_valido) / capt_media_ytd.where(denominador_valido)

    df_lookup = pd.DataFrame(
        {
            "Instituição": df_dre_base["Instituição"].astype(str),
            "Período": df_dre_base["Período"].astype(str),
            "Desp Captação / Captação": ratio,
            "Trace::Desp Captação::Despesa YTD": desp_ytd,
            "Trace::Desp Captação::Despesa Anualizada": desp_anualizada,
            "Trace::Desp Captação::Captações Média YTD": capt_media_ytd,
        }
    )
    prepared = _prepare_frame(df_lookup, catalog_map)
    return _prepare_lookup(
        prepared,
        [
            "Desp Captação / Captação",
            "Trace::Desp Captação::Despesa YTD",
            "Trace::Desp Captação::Despesa Anualizada",
            "Trace::Desp Captação::Captações Média YTD",
        ],
    )


def _collect_variant_audit(*frames: Optional[pd.DataFrame]) -> dict:
    canonical_variants: Dict[str, set[str]] = {}
    raw_to_canonical: Dict[str, str] = {}
    dedupe_conflicts: Dict[str, list[str]] = {}

    for frame in frames:
        if frame is None or frame.empty:
            continue
        if not {"Instituição", "InstituiçãoRaw"}.issubset(frame.columns):
            continue
        pares = (
            frame[["Instituição", "InstituiçãoRaw"]]
            .dropna()
            .drop_duplicates()
            .to_dict("records")
        )
        for item in pares:
            canonical = str(item["Instituição"]).strip()
            raw = str(item["InstituiçãoRaw"]).strip()
            if not canonical or not raw:
                continue
            canonical_variants.setdefault(canonical, set()).add(raw)
            raw_to_canonical.setdefault(raw, canonical)

        if {"InstituiçãoKey", "Período", "InstituiçãoRaw"}.issubset(frame.columns):
            dup = frame.groupby(["InstituiçãoKey", "Período"], dropna=False)["InstituiçãoRaw"].nunique()
            for (inst_key, periodo), total in dup.items():
                if int(total) <= 1:
                    continue
                raws = (
                    frame.loc[
                        (frame["InstituiçãoKey"] == inst_key) & (frame["Período"] == periodo),
                        "InstituiçãoRaw",
                    ]
                    .dropna()
                    .astype(str)
                    .sort_values()
                    .unique()
                    .tolist()
                )
                dedupe_conflicts[f"{inst_key}|{periodo}"] = raws

    return {
        "canonical_variants": {k: sorted(v) for k, v in sorted(canonical_variants.items())},
        "raw_to_canonical": dict(sorted(raw_to_canonical.items())),
        "dedupe_conflicts": dict(sorted(dedupe_conflicts.items())),
    }


def build_critical_screens_dataframe(
    *,
    df_principal: pd.DataFrame,
    df_ativo: Optional[pd.DataFrame],
    df_passivo: Optional[pd.DataFrame],
    df_capital: Optional[pd.DataFrame],
    df_dre: Optional[pd.DataFrame],
    df_carteira_pf: Optional[pd.DataFrame],
    df_carteira_pj: Optional[pd.DataFrame],
    df_carteira_instrumentos: Optional[pd.DataFrame],
    df_bloprudencial: Optional[pd.DataFrame],
    base_dir: Path | None = None,
) -> pd.DataFrame:
    """Constroi dataset curado das métricas extras das telas críticas."""
    root = Path(base_dir).resolve() if base_dir else Path(__file__).resolve().parents[2]
    catalog_map = build_institution_to_conglomerate_map(root)

    auxiliary_reference_frames = (df_principal,)

    base = _prepare_frame(df_principal, catalog_map, base_dir=root, canonicalize_names=True)
    if base.empty:
        return pd.DataFrame(
            columns=[
                "Instituição",
                "Período",
                "InstituiçãoKey",
                *CRITICAL_BASE_METRICS,
                *CRITICAL_EXTRA_METRICS,
                *CRITICAL_TRACE_COLUMNS,
            ]
        )
    base = _normalize_principal_metrics(base)

    ativo = _prepare_frame(df_ativo, catalog_map, base_dir=root, extra_frames=auxiliary_reference_frames)
    passivo = _prepare_frame(df_passivo, catalog_map, base_dir=root, extra_frames=auxiliary_reference_frames)
    capital = _prepare_frame(df_capital, catalog_map, base_dir=root, extra_frames=auxiliary_reference_frames)
    carteira_pf = _prepare_frame(df_carteira_pf, catalog_map, base_dir=root, extra_frames=auxiliary_reference_frames)
    carteira_pj = _prepare_frame(df_carteira_pj, catalog_map, base_dir=root, extra_frames=auxiliary_reference_frames)
    carteira_instr = _prepare_frame(df_carteira_instrumentos, catalog_map, base_dir=root, extra_frames=auxiliary_reference_frames)
    blop_lookup = _build_bloprud_lookup(df_bloprudencial, catalog_map)
    desp_capt_lookup = _build_desp_capt_lookup(df_dre, df_principal, catalog_map)

    col_disp_ativo = _pick_col(ativo, ["Disponibilidades (a)", "Disponibilidades", "Disponibilidades (a) ="])
    col_aplic_ativo = _pick_col(
        ativo,
        [
            "Aplicações Interfinanceiras de Liquidez (b)",
            "Aplicacoes Interfinanceiras de Liquidez (b)",
            "Aplicações Interfinanceiras de Liquidez",
        ],
    )
    col_tvm_ativo = _pick_col(
        ativo,
        [
            "Títulos e Valores Mobiliários (c)",
            "Titulos e Valores Mobiliarios (c)",
            "Títulos e Valores Mobiliários e Instrumentos Financeiros Derivativos (c)",
            "Títulos e Valores Mobiliários",
        ],
    )
    col_depositos_passivo = _pick_exact_col(
        passivo,
        [
            "Depósitos (e)",
            "Depositos (e)",
            "Depósitos (a)",
            "Depósitos Totais (a)",
            "Depósito Total (a)",
            "Depositos (a)",
            "Deposito Total (a)",
        ],
    )
    col_dep_a1 = _pick_col(passivo, ["Depósitos à Vista (a1)", "Depositos a Vista (a1)", "Depósitos à Vista", "Depositos a Vista"])
    col_dep_a2 = _pick_col(passivo, ["Depósitos de Poupança (a2)", "Depositos de Poupanca (a2)", "Depósitos de Poupança"])
    col_dep_a3 = _pick_col(passivo, ["Depósitos Interfinanceiros (a3)", "Depositos Interfinanceiros (a3)"])
    col_dep_a4 = _pick_col(passivo, ["Depósitos a Prazo (a4)", "Depositos a Prazo (a4)"])
    col_dep_a5 = _pick_col(
        passivo,
        [
            "Outros Depósitos (a5)",
            "Outros Depositos (a5)",
            "Conta de Pagamento Pré-Paga (a5)",
            "Conta de Pagamento Pre-Paga (a5)",
            "Conta de Pagamento Pre Paga (a5)",
        ],
    )
    col_dep_a6 = _pick_col(passivo, ["Depósitos Outros (a6)", "Depositos Outros (a6)"])
    col_capt_passivo = _pick_col(
        passivo,
        [
            "Captações (e) = (a) + (b) + (c) + (d)",
            "Captações (e)",
            "Captações",
            "Captacoes (e)",
        ],
    )
    col_instr_passivo = _pick_col(
        passivo,
        [
            "Instrumentos de Dívida Elegíveis a Capital (h)",
            "Instrumentos de Divida Elegiveis a Capital (h)",
            "Instrumentos de Dívida Elegíveis a Capital",
            "Instrumentos de Divida Elegiveis a Capital",
        ],
    )

    col_credito_bruta_e1 = _pick_col(ativo, ["Valor Contábil Bruto (e1)", "Valor Contabil Bruto (e1)"])
    col_credito_bruta_f1 = _pick_col(ativo, ["Valor Contábil Bruto (f1)", "Valor Contabil Bruto (f1)"])
    col_credito_bruta_g1 = _pick_col(ativo, ["Valor Contábil Bruto (g1)", "Valor Contabil Bruto (g1)"])
    col_credito_bruta_h1 = _pick_col(ativo, ["Valor Contábil Bruto (h1)", "Valor Contabil Bruto (h1)"])
    col_credito_bruta_d1 = _pick_col(ativo, ["Operações de Crédito (d1)", "Operacoes de Credito (d1)"])
    col_credito_bruta_e1_alt = _pick_col(ativo, ["Arrendamento Mercantil a Receber (e1)", "Arrendamento Mercantil a Receber"])
    col_credito_bruta_f = _pick_col(
        ativo,
        ["Outros Créditos - Líquido de Provisão (f)", "Outros Creditos - Liquido de Provisao (f)", "Outros Créditos - Líquido de Provisão"],
    )
    col_credito_net_e = _pick_col(ativo, ["Operações de Crédito (e)", "Operacoes de Credito (e)"])
    col_credito_net_f = _pick_col(ativo, ["Operações de Arrendamento Financeiro (f)", "Operacoes de Arrendamento Financeiro (f)"])
    col_credito_net_g = _pick_col(
        ativo,
        ["Outras Operações com Características de Concessão de Crédito (g)", "Outras Operacoes com Caracteristicas de Concessao de Credito (g)"],
    )
    col_credito_net_h = _pick_col(
        ativo,
        [
            "Valores a Receber de Transações de Pagamentos - Usuários Finais (Pós-pago) (h)",
            "Valores a Receber de Transacoes de Pagamentos - Usuarios Finais (Pos-pago) (h)",
        ],
    )

    col_perda_e2 = _pick_col(ativo, ["Perda Esperada (e2)"])
    col_perda_e3 = _pick_col(ativo, ["Hedge de Valor Justo (e3)"])
    col_perda_e4 = _pick_col(ativo, ["Ajuste a Valor Justo (e4)"])
    col_perda_f2 = _pick_col(ativo, ["Perda Esperada (f2)"])
    col_perda_f3 = _pick_col(ativo, ["Hedge de Valor Justo (f3)"])
    col_perda_g2 = _pick_col(ativo, ["Perda Esperada (g2)"])
    col_perda_g3 = _pick_col(ativo, ["Hedge de Valor Justo (g3)"])
    col_perda_g4 = _pick_col(ativo, ["Ajuste a Valor Justo (g4)"])
    col_perda_h2 = _pick_col(ativo, ["Perda Esperada (h2)"])
    perda_colunas = [
        coluna
        for coluna in [
            col_perda_e2,
            col_perda_e3,
            col_perda_e4,
            col_perda_f2,
            col_perda_f3,
            col_perda_g2,
            col_perda_g3,
            col_perda_g4,
            col_perda_h2,
        ]
        if coluna
    ]

    col_pf_total = _pick_col(
        carteira_pf,
        ["Total da Carteira PF", "Total da Carteira de Pessoa Física", "Total da Carteira de Pessoa Fisica"],
    )
    col_pj_total = _pick_col(
        carteira_pj,
        ["Total da Carteira PJ", "Total da Carteira de Pessoa Jurídica", "Total da Carteira de Pessoa Juridica"],
    )
    col_c4 = _pick_col(carteira_instr, ["C4"])
    col_c5 = _pick_col(carteira_instr, ["C5"])

    col_cap_principal = _pick_col(capital, ["Capital Principal", "Capital Principal para Comparação com RWA (a)"])
    col_cap_complementar = _pick_col(capital, ["Capital Complementar", "Capital Complementar (b)"])
    col_cap_nivel2 = _pick_col(capital, ["Capital Nível II", "Capital Nível II (d)", "Capital Nivel II"])
    col_rwa_total = _pick_col(
        capital,
        [
            "RWA Total",
            "Ativos Ponderados pelo Risco (RWA) (j) = (f) + (g) + (h) + (i)",
            "Ativos Ponderados pelo Risco (RWA) (j)",
            "Ativos Ponderados pelo Risco (RWA) (i) = (f) + (g) + (h)",
            "Ativos Ponderados pelo Risco (RWA) (i)",
            "RWA",
        ],
    )
    col_indice_cap_principal = _pick_col(
        capital,
        [
            "Índice de Capital Principal",
            "Índice de Capital Principal (l) = (a) / (j)",
            "Índice de Capital Principal (k) = (a) / (i)",
        ],
    )
    col_indice_basileia_precalc = _pick_col(
        capital,
        [
            "Índice de Basileia",
            "Índice de Basileia Capital",
            "Índice de Basileia (n) = (e) / (j)",
            "Índice de Basileia (m) = (e) / (i)",
        ],
    )

    lk_ativo = _prepare_lookup(
        ativo,
        [
            col_credito_bruta_e1,
            col_credito_bruta_f1,
            col_credito_bruta_g1,
            col_credito_bruta_h1,
            col_credito_bruta_d1,
            col_credito_bruta_e1_alt,
            col_credito_bruta_f,
            col_credito_net_e,
            col_credito_net_f,
            col_credito_net_g,
            col_credito_net_h,
            col_disp_ativo,
            col_aplic_ativo,
            col_tvm_ativo,
            *perda_colunas,
        ],
    )
    lk_passivo = _prepare_lookup(
        passivo,
        [col_depositos_passivo, col_dep_a1, col_dep_a2, col_dep_a3, col_dep_a4, col_dep_a5, col_dep_a6, col_capt_passivo, col_instr_passivo],
    )
    lk_capital = _prepare_lookup(
        capital,
        [col_cap_principal, col_cap_complementar, col_cap_nivel2, col_rwa_total, col_indice_cap_principal, col_indice_basileia_precalc],
    )
    lk_pf = _prepare_lookup(carteira_pf, [col_pf_total])
    lk_pj = _prepare_lookup(carteira_pj, [col_pj_total])
    lk_instr = _prepare_lookup(carteira_instr, [col_c4, col_c5])

    base = base.sort_values(["Período", "InstituiçãoKey", "Instituição"]).reset_index(drop=True)
    rows = []
    for item in base.to_dict("records"):
        instituicao = str(item.get("Instituição"))
        instituicao_raw = str(item.get("InstituiçãoRaw") or instituicao)
        institution_key = str(item.get("InstituiçãoKey"))
        periodo = str(item.get("Período"))
        periodo_api = display_period_to_api(periodo)
        ano_ref = int(periodo_api[:4]) if periodo_api else None
        ativo_total = _coerce_numeric_value(item.get("Ativo Total"))
        patrimonio_liquido = _coerce_numeric_value(item.get("Patrimônio Líquido"))
        lucro_liquido_ytd = _coerce_numeric_value(item.get("Lucro Líquido Acumulado YTD"))
        lucro_liquido_tri = _coerce_numeric_value(item.get("Lucro Líquido Trimestral"))
        roe_ac_ytd = _coerce_numeric_value(item.get("ROE Ac. Anualizado (%)"))
        roe_tri = _coerce_numeric_value(item.get("ROE trimestral anualizado (%)"))
        pl_dez_anterior = _coerce_numeric_value(item.get("Trace::PL Dez Ano Anterior"))
        fator_anualizacao = _coerce_numeric_value(item.get("Trace::Fator Anualização"))

        valor_pf = _lk_get(lk_pf, institution_key, periodo, col_pf_total)
        valor_pj = _lk_get(lk_pj, institution_key, periodo, col_pj_total)
        carteira_classificada = _sum_values([valor_pf, valor_pj])

        trace_disp = _coerce_numeric_value(_lk_get(lk_ativo, institution_key, periodo, col_disp_ativo))
        trace_aplic = _coerce_numeric_value(_lk_get(lk_ativo, institution_key, periodo, col_aplic_ativo))
        trace_tvm = _coerce_numeric_value(_lk_get(lk_ativo, institution_key, periodo, col_tvm_ativo))

        if ano_ref is not None and ano_ref <= 2024:
            trace_cart_d1 = _coerce_numeric_value(_lk_get(lk_ativo, institution_key, periodo, col_credito_bruta_d1))
            trace_cart_e1_alt = _coerce_numeric_value(_lk_get(lk_ativo, institution_key, periodo, col_credito_bruta_e1_alt))
            trace_cart_f_old = _coerce_numeric_value(_lk_get(lk_ativo, institution_key, periodo, col_credito_bruta_f))
            trace_cart_e1 = None
            trace_cart_f1 = None
            trace_cart_g1 = None
            trace_cart_h1 = None
            carteira_bruta = _sum_values(
                [
                    trace_cart_d1,
                    trace_cart_e1_alt,
                    trace_cart_f_old,
                ]
            )
        else:
            trace_cart_d1 = None
            trace_cart_e1_alt = None
            trace_cart_f_old = None
            trace_cart_e1 = _coerce_numeric_value(_lk_get(lk_ativo, institution_key, periodo, col_credito_bruta_e1))
            trace_cart_f1 = _coerce_numeric_value(_lk_get(lk_ativo, institution_key, periodo, col_credito_bruta_f1))
            trace_cart_g1 = _coerce_numeric_value(_lk_get(lk_ativo, institution_key, periodo, col_credito_bruta_g1))
            trace_cart_h1 = _coerce_numeric_value(_lk_get(lk_ativo, institution_key, periodo, col_credito_bruta_h1))
            carteira_bruta = _sum_values(
                [
                    trace_cart_e1,
                    trace_cart_f1,
                    trace_cart_g1,
                    trace_cart_h1,
                ]
            )
        if carteira_bruta is None:
            carteira_bruta = _sum_values(
                [
                    _lk_get(lk_ativo, institution_key, periodo, col_credito_net_e),
                    _lk_get(lk_ativo, institution_key, periodo, col_credito_net_f),
                    _lk_get(lk_ativo, institution_key, periodo, col_credito_net_g),
                    _lk_get(lk_ativo, institution_key, periodo, col_credito_net_h),
                ]
            )

        ativos_liquidos = _sum_values(
            [
                trace_disp,
                trace_aplic,
                trace_tvm,
            ]
        )
        trace_dep_e = _coerce_numeric_value(_lk_get(lk_passivo, institution_key, periodo, col_depositos_passivo))
        trace_dep_a1 = _coerce_numeric_value(_lk_get(lk_passivo, institution_key, periodo, col_dep_a1))
        trace_dep_a2 = _coerce_numeric_value(_lk_get(lk_passivo, institution_key, periodo, col_dep_a2))
        trace_dep_a3 = _coerce_numeric_value(_lk_get(lk_passivo, institution_key, periodo, col_dep_a3))
        trace_dep_a4 = _coerce_numeric_value(_lk_get(lk_passivo, institution_key, periodo, col_dep_a4))
        trace_dep_a5 = _coerce_numeric_value(_lk_get(lk_passivo, institution_key, periodo, col_dep_a5))
        trace_dep_a6 = _coerce_numeric_value(_lk_get(lk_passivo, institution_key, periodo, col_dep_a6))
        depositos_totais = trace_dep_e
        if _coerce_numeric_value(depositos_totais) is None:
            depositos_totais = _sum_values(
                [
                    trace_dep_a1,
                    trace_dep_a2,
                    trace_dep_a3,
                    trace_dep_a4,
                    trace_dep_a5,
                    trace_dep_a6,
                ]
            )

        trace_cap_e = _coerce_numeric_value(_lk_get(lk_passivo, institution_key, periodo, col_capt_passivo))
        trace_instr_h = _coerce_numeric_value(_lk_get(lk_passivo, institution_key, periodo, col_instr_passivo))
        cap_val = trace_cap_e
        if ano_ref is None or ano_ref <= 2024:
            core_funding = _coerce_numeric_value(cap_val)
        else:
            core_funding = _sum_values([cap_val, trace_instr_h])

        trace_perda_e2 = _coerce_numeric_value(_lk_get(lk_ativo, institution_key, periodo, col_perda_e2))
        trace_perda_e3 = _coerce_numeric_value(_lk_get(lk_ativo, institution_key, periodo, col_perda_e3))
        trace_perda_e4 = _coerce_numeric_value(_lk_get(lk_ativo, institution_key, periodo, col_perda_e4))
        trace_perda_f2 = _coerce_numeric_value(_lk_get(lk_ativo, institution_key, periodo, col_perda_f2))
        trace_perda_f3 = _coerce_numeric_value(_lk_get(lk_ativo, institution_key, periodo, col_perda_f3))
        trace_perda_g2 = _coerce_numeric_value(_lk_get(lk_ativo, institution_key, periodo, col_perda_g2))
        trace_perda_g3 = _coerce_numeric_value(_lk_get(lk_ativo, institution_key, periodo, col_perda_g3))
        trace_perda_g4 = _coerce_numeric_value(_lk_get(lk_ativo, institution_key, periodo, col_perda_g4))
        trace_perda_h2 = _coerce_numeric_value(_lk_get(lk_ativo, institution_key, periodo, col_perda_h2))
        perda_esperada = _sum_values(
            [
                trace_perda_e2,
                trace_perda_e3,
                trace_perda_e4,
                trace_perda_f2,
                trace_perda_f3,
                trace_perda_g2,
                trace_perda_g3,
                trace_perda_g4,
                trace_perda_h2,
            ]
        )
        valor_c4 = _lk_get(lk_instr, institution_key, periodo, col_c4)
        valor_c5 = _lk_get(lk_instr, institution_key, periodo, col_c5)
        carteira_c4_c5 = _sum_values([valor_c4, valor_c5])

        pdd_credito = blop_lookup.get((str(periodo_api), institution_key, "1490000004")) if periodo_api else None
        pdd_outros = blop_lookup.get((str(periodo_api), institution_key, "1890000006")) if periodo_api else None
        estagio1 = blop_lookup.get((str(periodo_api), institution_key, "3311000002")) if periodo_api else None
        estagio2 = blop_lookup.get((str(periodo_api), institution_key, "3312000001")) if periodo_api else None
        estagio3 = blop_lookup.get((str(periodo_api), institution_key, "3313000000")) if periodo_api else None
        pdd_total_4060 = _sum_values([pdd_credito, pdd_outros])

        indice_cap_principal = None
        val_cp = _coerce_numeric_value(_lk_get(lk_capital, institution_key, periodo, col_cap_principal))
        val_rwa = _coerce_numeric_value(_lk_get(lk_capital, institution_key, periodo, col_rwa_total))
        val_cet1_publicado = None
        if val_cp is not None and val_rwa is not None and val_rwa != 0:
            indice_cap_principal = val_cp / val_rwa
        if indice_cap_principal is None:
            val_precalc = _coerce_numeric_value(_lk_get(lk_capital, institution_key, periodo, col_indice_cap_principal))
            if val_precalc is not None:
                indice_cap_principal = val_precalc / 100 if abs(val_precalc) > 1 else val_precalc
                val_cet1_publicado = indice_cap_principal

        indice_basileia = None
        val_cc = _coerce_numeric_value(_lk_get(lk_capital, institution_key, periodo, col_cap_complementar))
        val_n2 = _coerce_numeric_value(_lk_get(lk_capital, institution_key, periodo, col_cap_nivel2))
        val_bas_publicado = None
        if None not in (val_cp, val_cc, val_n2, val_rwa) and val_rwa not in (None, 0):
            indice_basileia = (val_cp + val_cc + val_n2) / val_rwa
        if indice_basileia is None:
            val_precalc = _coerce_numeric_value(_lk_get(lk_capital, institution_key, periodo, col_indice_basileia_precalc))
            if val_precalc is not None:
                indice_basileia = val_precalc / 100 if abs(val_precalc) > 1 else val_precalc
                val_bas_publicado = indice_basileia

        desp_capt_row = desp_capt_lookup.get((institution_key, periodo), {})
        desp_capt = _coerce_numeric_value(desp_capt_row.get("Desp Captação / Captação"))
        desp_capt_ytd = _coerce_numeric_value(desp_capt_row.get("Trace::Desp Captação::Despesa YTD"))
        desp_capt_anual = _coerce_numeric_value(desp_capt_row.get("Trace::Desp Captação::Despesa Anualizada"))
        capt_media_ytd = _coerce_numeric_value(desp_capt_row.get("Trace::Desp Captação::Captações Média YTD"))
        credito_capt = _calc_ratio(carteira_bruta, core_funding)

        rows.append(
            {
                "Instituição": instituicao,
                "InstituiçãoRaw": instituicao_raw,
                "Período": periodo,
                "InstituiçãoKey": institution_key,
                "Ativo Total": ativo_total,
                "Patrimônio Líquido": patrimonio_liquido,
                "Lucro Líquido Acumulado YTD": lucro_liquido_ytd,
                "Lucro Líquido Trimestral": lucro_liquido_tri,
                "ROE Ac. Anualizado (%)": roe_ac_ytd,
                "ROE trimestral anualizado (%)": roe_tri,
                "ROE Ac. YTD an. (%)": roe_ac_ytd,
                "Crédito / Captações": credito_capt,
                "Desp Captação / Captação": desp_capt,
                "Ativos Líquidos": ativos_liquidos,
                "Depósitos Totais": _coerce_numeric_value(depositos_totais),
                "Core Funding": _coerce_numeric_value(core_funding),
                "Core Funding*": _coerce_numeric_value(core_funding),
                "Carteira de Crédito Bruta": carteira_bruta,
                "Carteira de Crédito*": carteira_bruta,
                "Perda Esperada": perda_esperada,
                "Perda Esperada / Carteira de Crédito Bruta": _calc_ratio(perda_esperada, carteira_bruta),
                "Perda Esperada / Carteira de Crédito*": _calc_ratio(perda_esperada, carteira_bruta),
                "Carteira de Crédito Classificada": carteira_classificada,
                "Carteira de Créd. Class. C4+C5": carteira_c4_c5,
                "Carteira de Créd. Class. C4+C5 / Carteira Classificada": _calc_ratio(carteira_c4_c5, carteira_classificada),
                "Perda Esperada / (Carteira C4 + C5)": _calc_ratio(perda_esperada, carteira_c4_c5),
                "Saldo PDD Crédito": pdd_credito,
                "Saldo PDD Outros Créditos": pdd_outros,
                "PDD Total 4060": pdd_total_4060,
                "Carteira Estágio 1": estagio1,
                "Ativos Estágio 2": estagio2,
                "Ativos Estágio 3": estagio3,
                "PDD / Estágio 3": _calc_ratio(pdd_total_4060, estagio3),
                "Perda Esperada / Estágio 3": _calc_ratio(perda_esperada, estagio3),
                "Perda Esperada / Est2+3": _calc_ratio(
                    perda_esperada,
                    _sum_required_values([estagio2, estagio3]),
                ),
                "Índice de Capital Principal (CET1)": indice_cap_principal,
                "Índice de Basileia Total (%)": indice_basileia,
                "Trace::PL Dez Ano Anterior": pl_dez_anterior,
                "Trace::Fator Anualização": fator_anualizacao,
                "Trace::Ativos Líquidos::Disponibilidades (a)": trace_disp,
                "Trace::Ativos Líquidos::Aplicações Interfinanceiras de Liquidez (b)": trace_aplic,
                "Trace::Ativos Líquidos::Títulos e Valores Mobiliários (c)": trace_tvm,
                "Trace::Carteira::Operações de Crédito (d1)": trace_cart_d1,
                "Trace::Carteira::Arrendamento Mercantil a Receber (e1)": trace_cart_e1_alt,
                "Trace::Carteira::Outros Créditos - Líquido de Provisão (f)": trace_cart_f_old,
                "Trace::Carteira::Valor Contábil Bruto (e1)": trace_cart_e1,
                "Trace::Carteira::Valor Contábil Bruto (f1)": trace_cart_f1,
                "Trace::Carteira::Valor Contábil Bruto (g1)": trace_cart_g1,
                "Trace::Carteira::Valor Contábil Bruto (h1)": trace_cart_h1,
                "Trace::Perda Esperada::Perda Esperada (e2)": trace_perda_e2,
                "Trace::Perda Esperada::Hedge de Valor Justo (e3)": trace_perda_e3,
                "Trace::Perda Esperada::Ajuste a Valor Justo (e4)": trace_perda_e4,
                "Trace::Perda Esperada::Perda Esperada (f2)": trace_perda_f2,
                "Trace::Perda Esperada::Hedge de Valor Justo (f3)": trace_perda_f3,
                "Trace::Perda Esperada::Perda Esperada (g2)": trace_perda_g2,
                "Trace::Perda Esperada::Hedge de Valor Justo (g3)": trace_perda_g3,
                "Trace::Perda Esperada::Ajuste a Valor Justo (g4)": trace_perda_g4,
                "Trace::Perda Esperada::Perda Esperada (h2)": trace_perda_h2,
                "Trace::Depósitos Totais::Depósitos (e)": trace_dep_e,
                "Trace::Depósitos Totais::Depósitos à Vista (a1)": trace_dep_a1,
                "Trace::Depósitos Totais::Depósitos de Poupança (a2)": trace_dep_a2,
                "Trace::Depósitos Totais::Depósitos Interfinanceiros (a3)": trace_dep_a3,
                "Trace::Depósitos Totais::Depósitos a Prazo (a4)": trace_dep_a4,
                "Trace::Depósitos Totais::Outros Depósitos (a5)": trace_dep_a5,
                "Trace::Depósitos Totais::Depósitos Outros (a6)": trace_dep_a6,
                "Trace::Core Funding::Captações (e)": trace_cap_e,
                "Trace::Core Funding::Instrumentos de Dívida Elegíveis a Capital (h)": trace_instr_h,
                "Trace::Capital::Capital Principal": val_cp,
                "Trace::Capital::Capital Complementar": val_cc,
                "Trace::Capital::Capital Nível II": val_n2,
                "Trace::Capital::RWA Total": val_rwa,
                "Trace::Capital::Índice CET1 Publicado": val_cet1_publicado,
                "Trace::Capital::Índice Basileia Publicado": val_bas_publicado,
                "Trace::Desp Captação::Despesa YTD": desp_capt_ytd,
                "Trace::Desp Captação::Despesa Anualizada": desp_capt_anual,
                "Trace::Desp Captação::Captações Média YTD": capt_media_ytd,
            }
        )

    out = pd.DataFrame(rows)
    if out.empty:
        return out

    out["CapitalDisponivel"] = out["Índice de Capital Principal (CET1)"].notna() | out["Índice de Basileia Total (%)"].notna()
    out["BloprudencialDisponivel"] = out["Ativos Estágio 3"].notna() | out["PDD Total 4060"].notna()
    out["QualidadeCarteiraDisponivel"] = out["Perda Esperada"].notna() & (
        out["Perda Esperada / Carteira de Crédito*"].notna() | out["Perda Esperada / Estágio 3"].notna()
    )

    return out.sort_values(["Período", "Instituição"]).reset_index(drop=True)


def _load_source_cache(
    manager: CacheManager,
    cache_name: str,
    *,
    allow_remote_source_download: bool = False,
) -> pd.DataFrame:
    cache = manager.get_cache(cache_name)
    if cache is None:
        raise RuntimeError(f"{cache_name}: cache não registrado")

    if allow_remote_source_download:
        resultado = manager.carregar(cache_name)
    else:
        if not cache.existe():
            raise RuntimeError(
                f"{cache_name}: cache local ausente; rematerialização exige fontes locais "
                "preparadas previamente ou allow_remote_source_download=True"
            )
        resultado = cache.carregar_local()

    if not resultado.sucesso or resultado.dados is None:
        raise RuntimeError(f"{cache_name}: {resultado.mensagem}")
    return resultado.dados


def materialize_critical_screens_cache(
    *,
    base_dir: Path | None = None,
    manager: "CacheManager" | None = None,
    force: bool = False,
    periodos: Optional[Sequence[str]] = None,
    save_bundled: bool = False,
    allow_remote_source_download: bool = False,
) -> CacheResult:
    """Materializa o cache curado das telas críticas."""
    root = Path(base_dir).resolve() if base_dir else Path(__file__).resolve().parents[2]
    from .manager import CacheManager

    cache_manager = manager or CacheManager(root)
    cache = CriticalScreensCache(root)

    if cache.existe() and not force and not periodos:
        result = cache.carregar_local()
        if result.sucesso and save_bundled:
            bundle_result = cache.sync_bundle_from_local()
            if not bundle_result.sucesso:
                return CacheResult(
                    sucesso=False,
                    mensagem=f"{result.mensagem}; {bundle_result.mensagem}",
                    dados=result.dados,
                    metadata=result.metadata,
                    fonte=result.fonte,
                )
        return result

    try:
        loaded = {
            cache_name: _load_source_cache(
                cache_manager,
                cache_name,
                allow_remote_source_download=allow_remote_source_download,
            )
            for cache_name in SOURCE_CACHE_TYPES
        }
    except Exception as exc:
        return CacheResult(
            sucesso=False,
            mensagem=f"Falha ao carregar fontes de critical_screens: {exc}",
            fonte="nenhum",
        )
    principal = loaded["principal"]
    principal_periodos = sorted(principal["Período"].dropna().astype(str).unique().tolist())
    periodos_criticos = list(periodos) if periodos else principal_periodos

    if periodos_criticos:
        for cache_name, df in list(loaded.items()):
            loaded[cache_name] = df[df["Período"].astype(str).isin(periodos_criticos)].copy()

    blop_df = _load_bloprud_sources(manager=cache_manager, base_dir=root, periodos_display=periodos_criticos)
    curated = build_critical_screens_dataframe(
        df_principal=loaded["principal"],
        df_ativo=loaded["ativo"],
        df_passivo=loaded["passivo"],
        df_capital=loaded["capital"],
        df_dre=loaded["dre"],
        df_carteira_pf=loaded["carteira_pf"],
        df_carteira_pj=loaded["carteira_pj"],
        df_carteira_instrumentos=loaded["carteira_instrumentos"],
        df_bloprudencial=blop_df,
        base_dir=root,
    )

    catalog_map = build_institution_to_conglomerate_map(root)
    canonical_audit = _collect_variant_audit(
        _prepare_frame(loaded["principal"], catalog_map, base_dir=root, dedupe=False),
        _prepare_frame(loaded["ativo"], catalog_map, base_dir=root, dedupe=False, extra_frames=(loaded["principal"],)),
        _prepare_frame(loaded["passivo"], catalog_map, base_dir=root, dedupe=False, extra_frames=(loaded["principal"],)),
        _prepare_frame(loaded["capital"], catalog_map, base_dir=root, dedupe=False, extra_frames=(loaded["principal"],)),
        _prepare_frame(loaded["dre"], catalog_map, base_dir=root, dedupe=False),
        _prepare_frame(loaded["carteira_pf"], catalog_map, base_dir=root, dedupe=False, extra_frames=(loaded["principal"],)),
        _prepare_frame(loaded["carteira_pj"], catalog_map, base_dir=root, dedupe=False, extra_frames=(loaded["principal"],)),
        _prepare_frame(loaded["carteira_instrumentos"], catalog_map, base_dir=root, dedupe=False, extra_frames=(loaded["principal"],)),
    )

    info_extra = {
        "tipos_origem": SOURCE_CACHE_TYPES,
        "periodos_materializados": sorted(curated["Período"].dropna().astype(str).unique().tolist()) if not curated.empty else [],
        "linhas_bloprudencial": int(len(blop_df)),
        "metricas_extra": CRITICAL_EXTRA_METRICS,
        "metricas_base": CRITICAL_BASE_METRICS,
        "trace_columns": CRITICAL_TRACE_COLUMNS,
        "schema_version": CRITICAL_SCREENS_SCHEMA_VERSION,
        "source_fingerprints": _source_fingerprints(cache_manager, root),
        "canonical_variants": canonical_audit.get("canonical_variants", {}),
        "raw_to_canonical": canonical_audit.get("raw_to_canonical", {}),
        "dedupe_conflicts": canonical_audit.get("dedupe_conflicts", {}),
    }
    result = cache.salvar_local(curated, fonte="materialized", info_extra=info_extra)
    if result.sucesso and save_bundled:
        bundle_result = cache.sync_bundle_from_local()
        if not bundle_result.sucesso:
            return CacheResult(
                sucesso=False,
                mensagem=f"{result.mensagem}; {bundle_result.mensagem}",
                dados=result.dados,
                metadata=result.metadata,
                fonte=result.fonte,
            )
    return result


def load_critical_screens_slice(
    *,
    base_dir: Path | None = None,
    periodos: Optional[Sequence[str]] = None,
    instituicoes: Optional[Sequence[str]] = None,
) -> pd.DataFrame:
    """Carrega recorte do cache curado sem abrir todo o dataset em memória."""
    root = Path(base_dir).resolve() if base_dir else Path(__file__).resolve().parents[2]
    cache = CriticalScreensCache(root)
    status = get_critical_screens_runtime_status(base_dir=root)
    if status.get("mode") == "bootstrap_bundle":
        cache.bootstrap_local_from_bundle()
    elif not cache.existe():
        cache.bootstrap_local_from_bundle()
    if not cache.arquivo_dados.exists():
        resultado = cache.carregar_local()
        if not resultado.sucesso or resultado.dados is None or resultado.dados.empty:
            return pd.DataFrame()
        df = resultado.dados
    else:
        try:
            import pyarrow.dataset as ds

            dataset = ds.dataset(cache.arquivo_dados, format="parquet")
            filtros = []
            if periodos:
                filtros.append(ds.field("Período").isin([str(periodo) for periodo in periodos]))
            if instituicoes:
                canonicas = build_institution_to_conglomerate_map(root)
                instituicoes_canonicas = [canonicalize_institution_name(nome, catalog_map=canonicas) for nome in instituicoes]
                filtros.append(ds.field("Instituição").isin([str(inst) for inst in instituicoes_canonicas]))

            if filtros:
                filtro = filtros[0]
                for extra in filtros[1:]:
                    filtro = filtro & extra
                table = dataset.to_table(filter=filtro)
            else:
                table = dataset.to_table()
            df = table.to_pandas()
        except Exception as exc:
            logger.warning("[CACHE:CRITICAL_SCREENS] Falha ao carregar slice filtrado: %s", exc)
            resultado = cache.carregar_local()
            if not resultado.sucesso or resultado.dados is None or resultado.dados.empty:
                return pd.DataFrame()
            df = resultado.dados

    if periodos:
        df = df[df["Período"].astype(str).isin([str(periodo) for periodo in periodos])].copy()
    if instituicoes:
        canonicas = build_institution_to_conglomerate_map(root)
        instituicoes_canonicas = [canonicalize_institution_name(nome, catalog_map=canonicas) for nome in instituicoes]
        df = df[df["Instituição"].astype(str).isin([str(inst) for inst in instituicoes_canonicas])].copy()
    return df.reset_index(drop=True)


def supported_periods_for_cache(cache_name: str, periodos: Sequence[str]) -> List[str]:
    """Retorna apenas períodos suportados para um cache."""
    suportados, _ = filter_supported_periods(cache_name, periodos)
    return suportados
