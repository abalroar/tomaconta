"""Cache histórico de taxas de juros do BCB.

Este módulo implementa uma ingestão batch resumível para o histórico completo
das taxas de juros por instituição financeira. O objetivo é tirar a extração
bruta de dentro do Streamlit e servir a UI a partir de artefatos parquet
materializados.
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import quote, urlencode

import pandas as pd
import requests

from .base import BaseCache, CacheConfig, CacheResult
from .release_config import get_release_config

logger = logging.getLogger("ifdata_cache")

CONSULTA_UNIFICADA_URL = "https://olinda.bcb.gov.br/olinda/servico/taxaJuros/versao/v2/odata/ConsultaUnificada"
CONSULTA_DATAS_URL = "https://olinda.bcb.gov.br/olinda/servico/taxaJuros/versao/v2/odata/ConsultaDatas"
PARAMETROS_CONSULTA_URL = "https://olinda.bcb.gov.br/olinda/servico/taxaJuros/versao/v2/odata/ParametrosConsulta"

REQUEST_TIMEOUT = 120
RETRYABLE_STATUSES = {408, 429, 500, 502, 503, 504}
DEFAULT_PAGE_SIZE = 2000
WINDOW_SELECT_FIELDS = [
    "InicioPeriodo",
    "FimPeriodo",
    "codigoSegmento",
    "Segmento",
    "codigoModalidade",
    "Modalidade",
    "Posicao",
    "InstituicaoFinanceira",
    "TaxaJurosAoMes",
    "TaxaJurosAoAno",
    "cnpj8",
]
FACT_REQUIRED_COLUMNS = [
    "inicio_periodo",
    "fim_periodo",
    "codigo_segmento",
    "codigo_modalidade",
    "institution_key",
    "instituicao_nome_observado",
    "taxa_juros_ao_mes",
    "taxa_juros_ao_ano",
]
FACT_SORT_COLUMNS = [
    "codigo_segmento",
    "codigo_modalidade",
    "inicio_periodo",
    "institution_key",
    "posicao",
]

FACT_TO_DISPLAY_RENAME = {
    "inicio_periodo": "Início Período",
    "fim_periodo": "Fim Período",
    "codigo_segmento": "Código Segmento",
    "segmento": "Segmento",
    "codigo_modalidade": "Código Modalidade",
    "modalidade": "Produto",
    "institution_key": "Chave Instituição",
    "institution_key_quality": "Qualidade Chave",
    "cnpj8_raw": "CNPJ",
    "instituicao_nome_observado": "Instituição Financeira",
    "posicao": "Posição",
    "taxa_juros_ao_mes": "Taxa Mensal (%)",
    "taxa_juros_ao_ano": "Taxa Anual (%)",
}

TAXAS_JUROS_HISTORICO_CONFIG = CacheConfig(
    nome="taxas_juros_historico",
    descricao="Taxas de Juros Histórico (ConsultaUnificada/BCB)",
    subdir="taxas_juros_historico",
    arquivo_dados="dados.parquet",
    arquivo_metadata="metadata.json",
    github_url_base=None,
    max_idade_horas=24.0,
    colunas_obrigatorias=FACT_REQUIRED_COLUMNS,
    api_url=CONSULTA_UNIFICADA_URL,
)


def _build_odata_url(base_url: str, params: Dict[str, Any]) -> str:
    cleaned = {key: value for key, value in params.items() if value is not None and value != ""}
    query_string = urlencode(cleaned, quote_via=quote, safe="(),'$")
    return f"{base_url}?{query_string}" if query_string else base_url


def _escape_odata_literal(value: str) -> str:
    return str(value).replace("'", "''")


def _request_json(
    url: str,
    *,
    session: Optional[requests.Session] = None,
    timeout: int = REQUEST_TIMEOUT,
    max_attempts: int = 4,
) -> Dict[str, Any]:
    client = session or requests
    last_error: Optional[Exception] = None

    for attempt in range(1, max_attempts + 1):
        try:
            response = client.get(url, timeout=timeout)
        except requests.RequestException as exc:
            last_error = exc
            if attempt >= max_attempts:
                break
            time.sleep(min(2 ** (attempt - 1), 5))
            continue

        if response.status_code in RETRYABLE_STATUSES and attempt < max_attempts:
            time.sleep(min(2 ** (attempt - 1), 5))
            continue

        if response.status_code != 200:
            detalhe = response.text[:250].strip()
            raise RuntimeError(f"HTTP {response.status_code} em {url}: {detalhe}")

        try:
            payload = response.json()
        except Exception as exc:  # pragma: no cover - protegido por testes de integração
            detalhe = response.text[:250].strip()
            raise RuntimeError(f"Resposta não-JSON em {url}: {detalhe}") from exc

        if not isinstance(payload, dict):
            raise RuntimeError(f"Payload inesperado em {url}: {type(payload)}")

        return payload

    raise RuntimeError(f"Falha de rede após {max_attempts} tentativas: {last_error}")


def _valid_cnpj8(value: Any) -> bool:
    texto = str(value or "").strip()
    return len(texto) == 8 and texto.isdigit() and texto != "00000000"


def _safe_string(value: Any) -> str:
    return str(value or "").strip()


def _make_institution_key(cnpj8: Any, nome: Any) -> Tuple[str, str, str, str]:
    cnpj8_raw = _safe_string(cnpj8)
    nome_observado = _safe_string(nome)
    if _valid_cnpj8(cnpj8_raw):
        return f"cnpj8:{cnpj8_raw}", "cnpj8", cnpj8_raw, nome_observado
    fallback_name = nome_observado or "INSTITUICAO_DESCONHECIDA"
    return f"nome:{fallback_name}", "name_fallback", cnpj8_raw, fallback_name


def fetch_taxas_juros_datas_disponiveis(
    *,
    tipo_modalidade: str = "D",
    session: Optional[requests.Session] = None,
    timeout: int = 60,
) -> pd.DataFrame:
    params = {
        "$format": "json",
        "$top": 5000,
        "$orderby": "inicioPeriodo asc",
        "$filter": f"tipoModalidade eq '{_escape_odata_literal(tipo_modalidade)}'",
    }
    payload = _request_json(_build_odata_url(CONSULTA_DATAS_URL, params), session=session, timeout=timeout)
    df = pd.DataFrame.from_records(payload.get("value") or [])
    if df.empty:
        return pd.DataFrame(columns=["inicio_periodo", "fim_periodo", "tipo_modalidade", "ano_inicio"])

    df = df.rename(
        columns={
            "inicioPeriodo": "inicio_periodo",
            "fimPeriodo": "fim_periodo",
            "tipoModalidade": "tipo_modalidade",
        }
    )
    df["inicio_periodo"] = pd.to_datetime(df["inicio_periodo"], errors="coerce")
    df["fim_periodo"] = pd.to_datetime(df["fim_periodo"], errors="coerce")
    df["tipo_modalidade"] = df["tipo_modalidade"].astype("string")
    df["ano_inicio"] = df["inicio_periodo"].dt.year.astype("Int16")
    df = df.dropna(subset=["inicio_periodo"]).sort_values("inicio_periodo").reset_index(drop=True)
    return df


def fetch_taxas_juros_parametros_consulta(
    *,
    tipo_modalidade: Optional[str] = None,
    session: Optional[requests.Session] = None,
    timeout: int = 60,
) -> pd.DataFrame:
    params = {
        "$format": "json",
        "$top": 1000,
        "$orderby": "tipoModalidade asc,codigoSegmento asc,codigoModalidade asc",
    }
    if tipo_modalidade:
        params["$filter"] = f"tipoModalidade eq '{_escape_odata_literal(tipo_modalidade)}'"

    payload = _request_json(_build_odata_url(PARAMETROS_CONSULTA_URL, params), session=session, timeout=timeout)
    df = pd.DataFrame.from_records(payload.get("value") or [])
    if df.empty:
        return pd.DataFrame(
            columns=["tipo_modalidade", "codigo_segmento", "segmento", "codigo_modalidade", "modalidade"]
        )

    df = df.rename(
        columns={
            "tipoModalidade": "tipo_modalidade",
            "codigoSegmento": "codigo_segmento",
            "segmento": "segmento",
            "codigoModalidade": "codigo_modalidade",
            "modalidade": "modalidade",
        }
    )
    for col in ("tipo_modalidade", "codigo_segmento", "segmento", "codigo_modalidade", "modalidade"):
        if col in df.columns:
            df[col] = df[col].astype("string")
    return df.sort_values(["tipo_modalidade", "codigo_segmento", "codigo_modalidade"]).reset_index(drop=True)


def fetch_taxas_juros_historico_window(
    inicio_periodo: str,
    *,
    session: Optional[requests.Session] = None,
    timeout: int = REQUEST_TIMEOUT,
    page_size: int = DEFAULT_PAGE_SIZE,
    max_pages: int = 3,
) -> pd.DataFrame:
    frames: List[pd.DataFrame] = []
    for page in range(max_pages):
        params = {
            "$format": "json",
            "$top": int(page_size),
            "$skip": int(page * page_size),
            "$select": ",".join(WINDOW_SELECT_FIELDS),
            "$orderby": "codigoSegmento asc,codigoModalidade asc,Posicao asc",
            "$filter": f"InicioPeriodo eq '{_escape_odata_literal(inicio_periodo)}'",
        }
        payload = _request_json(
            _build_odata_url(CONSULTA_UNIFICADA_URL, params),
            session=session,
            timeout=timeout,
        )
        rows = payload.get("value") or []
        if not rows:
            break
        frames.append(pd.DataFrame.from_records(rows))
        if len(rows) < page_size:
            break

    if not frames:
        return pd.DataFrame(columns=WINDOW_SELECT_FIELDS)
    return pd.concat(frames, ignore_index=True)


def normalize_taxas_juros_historico_frame(
    raw_df: pd.DataFrame,
    *,
    run_id: str,
    ingested_at: Optional[str] = None,
    tipo_modalidade: str = "D",
) -> pd.DataFrame:
    if raw_df is None or raw_df.empty:
        return pd.DataFrame(columns=FACT_REQUIRED_COLUMNS)

    df = raw_df.copy()
    ingested_at = ingested_at or datetime.now(timezone.utc).isoformat()

    keys = df.apply(
        lambda row: _make_institution_key(
            row.get("cnpj8"),
            row.get("InstituicaoFinanceira"),
        ),
        axis=1,
        result_type="expand",
    )
    keys.columns = ["institution_key", "institution_key_quality", "cnpj8_raw", "instituicao_nome_observado"]
    df = pd.concat([df, keys], axis=1)

    df = df.rename(
        columns={
            "InicioPeriodo": "inicio_periodo",
            "FimPeriodo": "fim_periodo",
            "codigoSegmento": "codigo_segmento",
            "Segmento": "segmento",
            "codigoModalidade": "codigo_modalidade",
            "Modalidade": "modalidade",
            "Posicao": "posicao",
            "TaxaJurosAoMes": "taxa_juros_ao_mes",
            "TaxaJurosAoAno": "taxa_juros_ao_ano",
        }
    )
    df["tipo_modalidade"] = str(tipo_modalidade)
    df["inicio_periodo"] = pd.to_datetime(df["inicio_periodo"], errors="coerce")
    df["fim_periodo"] = pd.to_datetime(df["fim_periodo"], errors="coerce")
    df["ano_inicio"] = df["inicio_periodo"].dt.year.astype("Int16")
    df["posicao"] = pd.to_numeric(df["posicao"], errors="coerce").astype("Int16")
    df["taxa_juros_ao_mes"] = pd.to_numeric(df["taxa_juros_ao_mes"], errors="coerce").astype("float32")
    df["taxa_juros_ao_ano"] = pd.to_numeric(df["taxa_juros_ao_ano"], errors="coerce").astype("float32")

    for col in (
        "tipo_modalidade",
        "codigo_segmento",
        "segmento",
        "codigo_modalidade",
        "modalidade",
        "institution_key",
        "institution_key_quality",
        "cnpj8_raw",
        "instituicao_nome_observado",
    ):
        if col in df.columns:
            df[col] = df[col].astype("string")

    df["run_id"] = str(run_id)
    df["ingested_at"] = pd.to_datetime(ingested_at, errors="coerce")

    fact_cols = [
        "tipo_modalidade",
        "inicio_periodo",
        "fim_periodo",
        "ano_inicio",
        "codigo_segmento",
        "segmento",
        "codigo_modalidade",
        "modalidade",
        "institution_key",
        "institution_key_quality",
        "cnpj8_raw",
        "instituicao_nome_observado",
        "posicao",
        "taxa_juros_ao_mes",
        "taxa_juros_ao_ano",
        "run_id",
        "ingested_at",
    ]
    df = df[fact_cols].dropna(subset=["inicio_periodo", "codigo_segmento", "codigo_modalidade", "institution_key"])
    df = df.sort_values(FACT_SORT_COLUMNS, kind="stable").reset_index(drop=True)
    return df


def validate_taxas_juros_historico_window(df: pd.DataFrame, *, inicio_periodo_esperado: str) -> None:
    if df.empty:
        raise ValueError(f"Janela {inicio_periodo_esperado} retornou vazia")

    periodos = sorted({str(pd.Timestamp(value).date()) for value in df["inicio_periodo"].dropna().unique()})
    if periodos != [inicio_periodo_esperado]:
        raise ValueError(
            f"Janela {inicio_periodo_esperado} retornou períodos inesperados: {periodos}"
        )

    duplicated = df.duplicated(
        subset=["inicio_periodo", "codigo_segmento", "codigo_modalidade", "institution_key"]
    ).sum()
    if int(duplicated) > 0:
        raise ValueError(f"Janela {inicio_periodo_esperado} retornou {duplicated} duplicidades")


def build_taxas_juros_display_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=list(FACT_TO_DISPLAY_RENAME.values()))

    renamed = df.rename(columns=FACT_TO_DISPLAY_RENAME).copy()
    for col in ("Início Período", "Fim Período"):
        if col in renamed.columns:
            renamed[col] = pd.to_datetime(renamed[col], errors="coerce")
    if "Posição" in renamed.columns:
        renamed["Posição"] = pd.to_numeric(renamed["Posição"], errors="coerce").astype("Int16")
    for col in ("Taxa Mensal (%)", "Taxa Anual (%)"):
        if col in renamed.columns:
            renamed[col] = pd.to_numeric(renamed[col], errors="coerce").astype("float32")
    return renamed


def load_taxas_juros_historico_slice(
    cache: "TaxasJurosHistoricoCache",
    *,
    codigo_segmento: Optional[str] = None,
    codigo_modalidade: Optional[str] = None,
    institution_keys: Optional[Sequence[str]] = None,
    instituicoes_observadas: Optional[Sequence[str]] = None,
    inicio_periodo_min: Optional[str] = None,
    inicio_periodo_max: Optional[str] = None,
    columns: Optional[Sequence[str]] = None,
) -> pd.DataFrame:
    if not cache.arquivo_dados.exists():
        return pd.DataFrame()

    filtros = []
    try:
        import pyarrow.dataset as ds

        dataset = ds.dataset(cache.arquivo_dados, format="parquet")
        if codigo_segmento:
            filtros.append(ds.field("codigo_segmento") == str(codigo_segmento))
        if codigo_modalidade:
            filtros.append(ds.field("codigo_modalidade") == str(codigo_modalidade))
        if institution_keys:
            filtros.append(ds.field("institution_key").isin([str(v) for v in institution_keys]))
        if instituicoes_observadas:
            filtros.append(
                ds.field("instituicao_nome_observado").isin([str(v) for v in instituicoes_observadas])
            )
        if inicio_periodo_min:
            filtros.append(ds.field("inicio_periodo") >= pd.Timestamp(inicio_periodo_min).to_pydatetime())
        if inicio_periodo_max:
            filtros.append(ds.field("inicio_periodo") <= pd.Timestamp(inicio_periodo_max).to_pydatetime())

        filtro_final = None
        for extra in filtros:
            filtro_final = extra if filtro_final is None else filtro_final & extra

        table = dataset.to_table(filter=filtro_final, columns=list(columns) if columns else None)
        return table.to_pandas()
    except Exception as exc:
        logger.warning("[CACHE:TAXAS_JUROS_HISTORICO] Falha no slice parquet filtrado: %s", exc)
        df = pd.read_parquet(cache.arquivo_dados, columns=list(columns) if columns else None)
        if codigo_segmento:
            df = df[df["codigo_segmento"].astype(str) == str(codigo_segmento)]
        if codigo_modalidade:
            df = df[df["codigo_modalidade"].astype(str) == str(codigo_modalidade)]
        if institution_keys:
            df = df[df["institution_key"].astype(str).isin([str(v) for v in institution_keys])]
        if instituicoes_observadas:
            df = df[df["instituicao_nome_observado"].astype(str).isin([str(v) for v in instituicoes_observadas])]
        if inicio_periodo_min:
            df = df[df["inicio_periodo"] >= pd.Timestamp(inicio_periodo_min)]
        if inicio_periodo_max:
            df = df[df["inicio_periodo"] <= pd.Timestamp(inicio_periodo_max)]
        return df.reset_index(drop=True)


def load_taxas_juros_historico_dimension(
    cache: "TaxasJurosHistoricoCache",
    *,
    name: str,
) -> pd.DataFrame:
    path = cache.dimension_paths().get(name)
    if path is None or not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


class TaxasJurosHistoricoCache(BaseCache):
    """Cache histórico batch para taxas de juros do BCB."""

    def __init__(self, base_dir: Path):
        super().__init__(TAXAS_JUROS_HISTORICO_CONFIG, base_dir)
        release_config = get_release_config()
        self.release_repo = release_config.repo
        self.release_tag = release_config.tag
        self.release_base_url = release_config.release_base_url
        self.github_release_parquet_url = f"{self.release_base_url}/{self.config.nome}_dados.parquet"
        self.github_release_metadata_url = f"{self.release_base_url}/{self.config.nome}_metadata.json"
        self.github_release_dim_parametros_url = f"{self.release_base_url}/{self.config.nome}_dim_parametros.parquet"
        self.github_release_dim_datas_url = f"{self.release_base_url}/{self.config.nome}_dim_datas.parquet"
        self.github_release_dim_instituicoes_url = f"{self.release_base_url}/{self.config.nome}_dim_instituicoes.parquet"
        self.github_release_manifest_url = f"{self.release_base_url}/{self.config.nome}_manifest.json"

    @property
    def staging_dir(self) -> Path:
        return self.cache_dir / "staging"

    @property
    def window_dir(self) -> Path:
        return self.staging_dir / "windows"

    @property
    def annual_dir(self) -> Path:
        return self.staging_dir / "annual"

    @property
    def checkpoint_path(self) -> Path:
        return self.staging_dir / "checkpoint.json"

    @property
    def manifest_path(self) -> Path:
        return self.cache_dir / "historico_manifest.json"

    def dimension_paths(self) -> Dict[str, Path]:
        return {
            "parametros": self.cache_dir / "dim_parametros.parquet",
            "datas": self.cache_dir / "dim_datas.parquet",
            "instituicoes": self.cache_dir / "dim_instituicoes.parquet",
        }

    def extra_release_assets(self) -> List[Tuple[Path, str]]:
        extras: List[Tuple[Path, str]] = []
        dim_paths = self.dimension_paths()
        asset_names = {
            "parametros": f"{self.config.nome}_dim_parametros.parquet",
            "datas": f"{self.config.nome}_dim_datas.parquet",
            "instituicoes": f"{self.config.nome}_dim_instituicoes.parquet",
        }
        for key, path in dim_paths.items():
            if path.exists():
                extras.append((path, asset_names[key]))
        if self.manifest_path.exists():
            extras.append((self.manifest_path, f"{self.config.nome}_manifest.json"))
        return extras

    def _garantir_estrutura(self) -> None:
        self._garantir_diretorio()
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        self.window_dir.mkdir(parents=True, exist_ok=True)
        self.annual_dir.mkdir(parents=True, exist_ok=True)

    def _log_local(self, nivel: str, mensagem: str, callback: Optional[Callable[[str], None]] = None) -> None:
        if callback:
            callback(mensagem)
        self._log(nivel, mensagem)

    def _save_json(self, path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def _load_json(self, path: Path) -> Dict[str, Any]:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _window_path(self, inicio_periodo: str) -> Path:
        ano = str(inicio_periodo)[:4]
        return self.window_dir / ano / f"{inicio_periodo}.parquet"

    def _list_window_dates(self) -> List[str]:
        if not self.window_dir.exists():
            return []
        dates: List[str] = []
        for path in self.window_dir.glob("*/*.parquet"):
            dates.append(path.stem)
        return sorted(set(dates))

    def _write_window_file(self, inicio_periodo: str, df: pd.DataFrame) -> None:
        path = self._window_path(inicio_periodo)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".parquet.tmp")
        df.to_parquet(tmp_path, index=False)
        tmp_path.replace(path)

    def _iter_window_paths(self) -> List[Path]:
        return sorted(self.window_dir.glob("*/*.parquet"))

    def _build_annual_slice(self, year: str) -> Tuple[Optional[Path], int]:
        year_dir = self.window_dir / str(year)
        window_files = sorted(year_dir.glob("*.parquet"))
        if not window_files:
            return None, 0

        frames = [pd.read_parquet(path) for path in window_files]
        year_df = pd.concat(frames, ignore_index=True)
        if FACT_SORT_COLUMNS:
            year_df = year_df.sort_values(FACT_SORT_COLUMNS, kind="stable")
        year_df = year_df.drop_duplicates(
            subset=["inicio_periodo", "codigo_segmento", "codigo_modalidade", "institution_key"],
            keep="last",
        ).reset_index(drop=True)

        annual_path = self.annual_dir / f"{year}.parquet"
        tmp_path = annual_path.with_suffix(".parquet.tmp")
        year_df.to_parquet(tmp_path, index=False)
        tmp_path.replace(annual_path)
        return annual_path, int(len(year_df))

    def _build_instituicoes_dimension(self, annual_paths: Sequence[Path]) -> pd.DataFrame:
        state: Dict[str, Dict[str, Any]] = {}

        for path in annual_paths:
            if not path.exists():
                continue
            cols = [
                "institution_key",
                "institution_key_quality",
                "cnpj8_raw",
                "instituicao_nome_observado",
                "inicio_periodo",
            ]
            df = pd.read_parquet(path, columns=cols)
            if df.empty:
                continue
            df = df.sort_values(["institution_key", "inicio_periodo"], kind="stable")

            for row in df.itertuples(index=False):
                key = str(row.institution_key)
                current = state.setdefault(
                    key,
                    {
                        "institution_key": key,
                        "institution_key_quality": str(row.institution_key_quality or ""),
                        "cnpj8_raw": str(row.cnpj8_raw or ""),
                        "primeira_aparicao": row.inicio_periodo,
                        "ultima_aparicao": row.inicio_periodo,
                        "nome_atual": str(row.instituicao_nome_observado or ""),
                        "observed_names": set(),
                    },
                )
                current["primeira_aparicao"] = min(current["primeira_aparicao"], row.inicio_periodo)
                current["ultima_aparicao"] = max(current["ultima_aparicao"], row.inicio_periodo)
                nome = str(row.instituicao_nome_observado or "").strip()
                if nome:
                    current["observed_names"].add(nome)
                    if row.inicio_periodo >= current["ultima_aparicao"]:
                        current["nome_atual"] = nome
                if not current["cnpj8_raw"] and str(row.cnpj8_raw or "").strip():
                    current["cnpj8_raw"] = str(row.cnpj8_raw or "").strip()

        if not state:
            return pd.DataFrame(
                columns=[
                    "institution_key",
                    "institution_key_quality",
                    "cnpj8_raw",
                    "nome_atual",
                    "primeira_aparicao",
                    "ultima_aparicao",
                    "observed_names_count",
                    "observed_names",
                ]
            )

        rows = []
        for payload in state.values():
            observed_names = sorted(payload.pop("observed_names"))
            rows.append(
                {
                    **payload,
                    "observed_names_count": len(observed_names),
                    "observed_names": " | ".join(observed_names),
                }
            )

        df = pd.DataFrame(rows).sort_values("nome_atual").reset_index(drop=True)
        return df

    def _write_dimensions(
        self,
        *,
        df_parametros: pd.DataFrame,
        df_datas: pd.DataFrame,
        df_instituicoes: pd.DataFrame,
    ) -> None:
        dim_paths = self.dimension_paths()
        df_parametros.to_parquet(dim_paths["parametros"], index=False)
        df_datas.to_parquet(dim_paths["datas"], index=False)
        df_instituicoes.to_parquet(dim_paths["instituicoes"], index=False)

    def _write_final_dataset(self, annual_paths: Sequence[Path]) -> int:
        tmp_path = self.cache_dir / "dados.parquet.tmp"
        if tmp_path.exists():
            tmp_path.unlink()

        total_rows = 0
        try:
            import pyarrow.parquet as pq

            writer = None
            for path in annual_paths:
                if not path.exists():
                    continue
                table = pq.read_table(path)
                if writer is None:
                    writer = pq.ParquetWriter(
                        str(tmp_path),
                        table.schema,
                        compression="snappy",
                    )
                writer.write_table(table, row_group_size=50_000)
                total_rows += table.num_rows
            if writer is None:
                raise RuntimeError("Nenhum slice anual disponível para compor o dataset final")
            writer.close()
        except ImportError:
            frames = [pd.read_parquet(path) for path in annual_paths if path.exists()]
            if not frames:
                raise RuntimeError("Nenhum slice anual disponível para compor o dataset final")
            final_df = pd.concat(frames, ignore_index=True)
            total_rows = int(len(final_df))
            final_df.to_parquet(tmp_path, index=False)

        tmp_path.replace(self.arquivo_dados)
        return total_rows

    def _build_metadata(
        self,
        *,
        total_rows: int,
        target_windows: Sequence[str],
        processed_windows: Sequence[str],
        df_parametros: pd.DataFrame,
        finalized_at: str,
    ) -> Dict[str, Any]:
        return {
            "timestamp_salvamento": finalized_at,
            "fonte": "api_bcb_consulta_unificada",
            "total_registros": int(total_rows),
            "total_periodos": len(processed_windows),
            "periodos": [str(item) for item in processed_windows],
            "total_periodos_alvo": len(target_windows),
            "periodo_inicial": processed_windows[0] if processed_windows else None,
            "periodo_final": processed_windows[-1] if processed_windows else None,
            "anos_materializados": sorted({str(item)[:4] for item in processed_windows}),
            "total_modalidades_diarias": int(
                len(
                    df_parametros[
                        df_parametros["tipo_modalidade"].astype(str) == "D"
                    ][["codigo_segmento", "codigo_modalidade"]].drop_duplicates()
                )
            ),
            "schema_version": 1,
        }

    def _write_artifacts(
        self,
        *,
        target_windows: Sequence[str],
        df_parametros: pd.DataFrame,
        df_datas: pd.DataFrame,
        log_callback: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        self._log_local("info", "Consolidando slices anuais...", log_callback)
        annual_paths: List[Path] = []
        annual_rows: Dict[str, int] = {}
        for year in sorted({str(item)[:4] for item in target_windows}):
            annual_path, rows = self._build_annual_slice(year)
            if annual_path is not None:
                annual_paths.append(annual_path)
                annual_rows[year] = rows

        total_rows = self._write_final_dataset(annual_paths)
        self._log_local("info", "Construindo dimensões auxiliares...", log_callback)
        df_instituicoes = self._build_instituicoes_dimension(annual_paths)
        self._write_dimensions(
            df_parametros=df_parametros.reset_index(drop=True),
            df_datas=df_datas.reset_index(drop=True),
            df_instituicoes=df_instituicoes.reset_index(drop=True),
        )

        finalized_at = datetime.now().isoformat()
        metadata = self._build_metadata(
            total_rows=total_rows,
            target_windows=target_windows,
            processed_windows=self._list_window_dates(),
            df_parametros=df_parametros,
            finalized_at=finalized_at,
        )
        self._save_json(self.arquivo_metadata, metadata)
        self._save_json(
            self.manifest_path,
            {
                "finalized_at": finalized_at,
                "total_rows": total_rows,
                "annual_rows": annual_rows,
                "target_windows": len(target_windows),
                "processed_windows": len(self._list_window_dates()),
            },
        )
        return metadata

    def materialize_history(
        self,
        *,
        data_inicio: Optional[str] = None,
        data_fim: Optional[str] = None,
        overwrite: bool = False,
        max_windows_per_run: Optional[int] = None,
        reprocess_tail_windows: int = 20,
        timeout: int = REQUEST_TIMEOUT,
        progress_callback: Optional[Callable[[float, str], None]] = None,
        log_callback: Optional[Callable[[str], None]] = None,
    ) -> CacheResult:
        self._garantir_estrutura()
        if overwrite:
            self.limpar_local()
            if self.staging_dir.exists():
                shutil.rmtree(self.staging_dir, ignore_errors=True)
            self._garantir_estrutura()

        with requests.Session() as session:
            df_datas = fetch_taxas_juros_datas_disponiveis(session=session)
            df_parametros = fetch_taxas_juros_parametros_consulta(tipo_modalidade="D", session=session)

            if data_inicio:
                df_datas = df_datas[df_datas["inicio_periodo"] >= pd.Timestamp(data_inicio)]
            if data_fim:
                df_datas = df_datas[df_datas["inicio_periodo"] <= pd.Timestamp(data_fim)]
            df_datas = df_datas.sort_values("inicio_periodo").reset_index(drop=True)

            target_windows = df_datas["inicio_periodo"].dt.strftime("%Y-%m-%d").tolist()
            if not target_windows:
                return CacheResult(
                    sucesso=False,
                    mensagem="Nenhuma janela disponível para o intervalo selecionado.",
                    fonte="nenhum",
                )

            existing_windows = set(self._list_window_dates())
            missing_windows = [item for item in target_windows if item not in existing_windows]
            tail_windows = target_windows[-max(int(reprocess_tail_windows), 0):] if existing_windows else []
            windows_to_process = []
            seen = set()
            for item in missing_windows + tail_windows:
                if item not in seen:
                    seen.add(item)
                    windows_to_process.append(item)

            if max_windows_per_run is not None:
                windows_to_process = windows_to_process[: max(int(max_windows_per_run), 0)]

            run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            checkpoint = {
                "run_id": run_id,
                "target_windows_total": len(target_windows),
                "requested_windows_this_run": len(windows_to_process),
                "data_inicio": data_inicio,
                "data_fim": data_fim,
                "overwrite": overwrite,
                "reprocess_tail_windows": int(reprocess_tail_windows),
                "started_at": datetime.now().isoformat(),
                "completed_windows": [],
                "failed_windows": [],
            }
            self._save_json(self.checkpoint_path, checkpoint)

            if not windows_to_process:
                metadata = self._write_artifacts(
                    target_windows=target_windows,
                    df_parametros=df_parametros,
                    df_datas=df_datas,
                    log_callback=log_callback,
                )
                return CacheResult(
                    sucesso=True,
                    mensagem="Nenhuma janela nova pendente; artefatos consolidados novamente.",
                    metadata={**metadata, "remaining_windows": 0, "finalized": True},
                    fonte="cache_local",
                )

            failures: List[Dict[str, str]] = []
            total_this_run = len(windows_to_process)
            for idx, inicio_periodo in enumerate(windows_to_process, start=1):
                if progress_callback:
                    progress_callback(
                        idx / max(total_this_run, 1),
                        f"Extraindo janela {inicio_periodo} ({idx}/{total_this_run})",
                    )
                self._log_local("info", f"Extraindo janela {inicio_periodo}...", log_callback)
                try:
                    raw_df = fetch_taxas_juros_historico_window(
                        inicio_periodo,
                        session=session,
                        timeout=timeout,
                    )
                    fact_df = normalize_taxas_juros_historico_frame(
                        raw_df,
                        run_id=run_id,
                        ingested_at=datetime.now(timezone.utc).isoformat(),
                        tipo_modalidade="D",
                    )
                    validate_taxas_juros_historico_window(fact_df, inicio_periodo_esperado=inicio_periodo)
                    self._write_window_file(inicio_periodo, fact_df)
                    checkpoint["completed_windows"].append(inicio_periodo)
                    self._save_json(self.checkpoint_path, checkpoint)
                except Exception as exc:
                    failures.append({"inicio_periodo": inicio_periodo, "erro": str(exc)})
                    checkpoint["failed_windows"].append({"inicio_periodo": inicio_periodo, "erro": str(exc)})
                    self._save_json(self.checkpoint_path, checkpoint)
                    self._log_local("error", f"Falha na janela {inicio_periodo}: {exc}", log_callback)

            processed_after_run = set(self._list_window_dates())
            remaining_windows = [item for item in target_windows if item not in processed_after_run]

            if failures:
                return CacheResult(
                    sucesso=False,
                    mensagem=f"{len(failures)} janela(s) falharam; progresso salvo em staging.",
                    metadata={
                        "run_id": run_id,
                        "processed_this_run": len(checkpoint["completed_windows"]),
                        "remaining_windows": len(remaining_windows),
                        "failures": failures,
                        "finalized": False,
                    },
                    fonte="nenhum",
                )

            if remaining_windows:
                return CacheResult(
                    sucesso=True,
                    mensagem=(
                        f"Chunk concluído: {len(checkpoint['completed_windows'])} janela(s) processada(s), "
                        f"{len(remaining_windows)} pendente(s)."
                    ),
                    metadata={
                        "run_id": run_id,
                        "processed_this_run": len(checkpoint["completed_windows"]),
                        "remaining_windows": len(remaining_windows),
                        "finalized": False,
                    },
                    fonte="api",
                )

            metadata = self._write_artifacts(
                target_windows=target_windows,
                df_parametros=df_parametros,
                df_datas=df_datas,
                log_callback=log_callback,
            )
            checkpoint["finished_at"] = datetime.now().isoformat()
            checkpoint["finalized"] = True
            self._save_json(self.checkpoint_path, checkpoint)

            return CacheResult(
                sucesso=True,
                mensagem=(
                    f"Histórico consolidado com sucesso: {metadata.get('total_registros', 0):,} linhas em "
                    f"{metadata.get('total_periodos', 0)} janelas."
                ),
                metadata={**metadata, "remaining_windows": 0, "finalized": True},
                fonte="api",
            )

    def bootstrap_local_assets(self, *, force: bool = False) -> CacheResult:
        if (
            not force
            and self.arquivo_dados.exists()
            and self.arquivo_metadata.exists()
            and all(path.exists() for path in self.dimension_paths().values())
        ):
            return CacheResult(
                sucesso=True,
                mensagem="Assets históricos já disponíveis localmente.",
                fonte="cache_local",
            )

        urls = {
            self.arquivo_dados: self.github_release_parquet_url,
            self.arquivo_metadata: self.github_release_metadata_url,
            self.dimension_paths()["parametros"]: self.github_release_dim_parametros_url,
            self.dimension_paths()["datas"]: self.github_release_dim_datas_url,
            self.dimension_paths()["instituicoes"]: self.github_release_dim_instituicoes_url,
            self.manifest_path: self.github_release_manifest_url,
        }

        self._garantir_diretorio()

        for local_path, url in urls.items():
            try:
                response = requests.get(url, timeout=120)
            except requests.RequestException as exc:
                if local_path == self.arquivo_dados:
                    return CacheResult(sucesso=False, mensagem=f"Erro de rede: {exc}", fonte="nenhum")
                continue

            if response.status_code == 404:
                if local_path == self.arquivo_dados:
                    return CacheResult(sucesso=False, mensagem="Parquet histórico não encontrado nos releases", fonte="nenhum")
                continue

            if response.status_code != 200:
                if local_path == self.arquivo_dados:
                    return CacheResult(
                        sucesso=False,
                        mensagem=f"Falha ao baixar asset principal ({response.status_code})",
                        fonte="nenhum",
                    )
                continue

            local_path.parent.mkdir(parents=True, exist_ok=True)
            if local_path.suffix == ".json":
                local_path.write_text(response.text, encoding="utf-8")
            else:
                local_path.write_bytes(response.content)

        return CacheResult(
            sucesso=True,
            mensagem="Assets históricos baixados dos releases.",
            fonte="github_releases",
        )

    def baixar_remoto(self) -> CacheResult:
        bootstrap = self.bootstrap_local_assets(force=True)
        if not bootstrap.sucesso:
            return bootstrap
        loaded_df = pd.read_parquet(self.arquivo_dados)
        return CacheResult(
            sucesso=True,
            mensagem=f"Baixado histórico remoto: {len(loaded_df)} registros",
            dados=loaded_df,
            fonte="github_releases",
        )

    def carregar(self, forcar_remoto: bool = False) -> CacheResult:
        if not forcar_remoto:
            valido, _ = self.cache_valido()
            if valido:
                resultado = self.carregar_local()
                if resultado.sucesso:
                    return resultado

        resultado = self.baixar_remoto()
        if not resultado.sucesso:
            return resultado
        return self.carregar_local()

    def extrair_periodo(self, periodo: str, **kwargs) -> CacheResult:
        raw_df = fetch_taxas_juros_historico_window(
            periodo,
            timeout=int(kwargs.get("timeout", REQUEST_TIMEOUT)),
        )
        normalized = normalize_taxas_juros_historico_frame(
            raw_df,
            run_id=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"),
        )
        validate_taxas_juros_historico_window(normalized, inicio_periodo_esperado=periodo)
        return CacheResult(
            sucesso=True,
            mensagem=f"Janela {periodo} extraída com {len(normalized)} linhas",
            dados=normalized,
            fonte="api",
        )

    def _validar_dados(self, dados: Any) -> Tuple[bool, str]:
        if dados is None:
            return False, "Dados são None"
        if not isinstance(dados, pd.DataFrame):
            return False, f"Esperado DataFrame, recebido {type(dados)}"
        if dados.empty:
            return False, "DataFrame vazio"
        for col in FACT_REQUIRED_COLUMNS:
            if col not in dados.columns:
                return False, f"Coluna obrigatória ausente: {col}"
        return True, "OK"

    def limpar_local(self) -> CacheResult:
        resultado = super().limpar_local()
        dim_paths = self.dimension_paths()
        extras_removidos: List[str] = []
        for path in [*dim_paths.values(), self.manifest_path]:
            if path.exists():
                path.unlink()
                extras_removidos.append(path.name)
        if self.staging_dir.exists():
            shutil.rmtree(self.staging_dir, ignore_errors=True)
            extras_removidos.append("staging/")
        if extras_removidos:
            return CacheResult(
                sucesso=True,
                mensagem=f"{resultado.mensagem}; extras removidos: {', '.join(extras_removidos)}",
                fonte="nenhum",
            )
        return resultado
