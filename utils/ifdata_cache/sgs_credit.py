"""Cache Parquet mensal das séries SGS do módulo Mercado de Crédito."""

from __future__ import annotations

import calendar
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

import pandas as pd
import requests

from ..sgs_credit_providers import SeriesProvider, default_providers
from ..sgs_credit_registry import SGS_SERIES, SeriesSpec, bcb_series, get_series
from .base import BaseCache, CacheConfig, CacheResult
from .release_config import add_release_cache_buster, build_release_asset_url, get_release_config


SGS_CREDIT_CONFIG = CacheConfig(
    nome="mercado_credito_sgs",
    descricao="Mercado de Crédito - séries temporais mensais SGS/BCB",
    subdir="mercado_credito_sgs",
    arquivo_dados="dados.parquet",
    arquivo_metadata="metadata.json",
    github_url_base=None,
    max_idade_horas=24.0 * 35,
    colunas_obrigatorias=[
        "data", "codigo", "serie", "nome_oficial", "valor", "unidade", "frequencia", "provedor"
    ],
    api_url="https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados",
)


def _month_end(value: date) -> date:
    return date(value.year, value.month, calendar.monthrange(value.year, value.month)[1])


def _add_months(value: date, months: int) -> date:
    offset = value.year * 12 + value.month - 1 + months
    year, month_index = divmod(offset, 12)
    day = min(value.day, calendar.monthrange(year, month_index + 1)[1])
    return date(year, month_index + 1, day)


def _windows(start: date, end: date, months: int = 120) -> Iterable[tuple[date, date]]:
    cursor = date(start.year, start.month, 1)
    while cursor <= end:
        window_end = min(_month_end(_add_months(cursor, months - 1)), end)
        yield cursor, window_end
        cursor = _add_months(cursor, months)


# Série de referência para a sonda de frescor: saldo total de crédito com
# recursos livres, mensal, publicada junto com o restante do bloco de crédito.
SERIE_REFERENCIA_FRESCOR = "saldo_livre_total"


def ultima_competencia_publicada(
    alias: str = SERIE_REFERENCIA_FRESCOR,
    *,
    provider: SeriesProvider | None = None,
    meses: int = 4,
) -> str | None:
    """Última competência que o BCB já publicou, no formato ``YYYY-MM``.

    Uma consulta só, de uma série só, sobre os últimos meses — o suficiente
    para comparar com o cache e avisar quando existe mês novo lá fora. O app
    nunca comparava o cache com a fonte, então um mês inteiro podia passar sem
    ninguém perceber que o parquet ficou para trás.

    Devolve ``None`` em qualquer falha: o aviso some, a seção continua.
    """
    try:
        spec = get_series(alias)
    except KeyError:
        return None
    fetcher = provider or default_providers().get(spec.provider)
    if fetcher is None:
        return None
    fim = date.today()
    inicio = _add_months(date(fim.year, fim.month, 1), -max(meses, 1))
    try:
        frame = fetcher.fetch(spec, inicio, fim)
    except Exception:
        return None
    if frame is None or frame.empty or "data" not in frame.columns:
        return None
    datas = pd.to_datetime(frame["data"], errors="coerce").dropna()
    if datas.empty:
        return None
    return datas.max().strftime("%Y-%m")


def _decorate(frame: pd.DataFrame, spec: SeriesSpec) -> pd.DataFrame:
    result = frame.copy()
    result["codigo"] = int(spec.code) if spec.code is not None else pd.NA
    result["serie"] = spec.alias
    result["nome_oficial"] = spec.official_name
    result["unidade"] = spec.unit
    result["frequencia"] = spec.frequency
    result["provedor"] = spec.provider
    return result[
        ["data", "codigo", "serie", "nome_oficial", "valor", "unidade", "frequencia", "provedor"]
    ]


class SGSCreditCache(BaseCache):
    """Materializa séries de provedores registrados em um fato longo."""

    def __init__(
        self,
        base_dir: Path,
        *,
        providers: Mapping[str, SeriesProvider] | None = None,
    ):
        release = get_release_config()
        config = replace(SGS_CREDIT_CONFIG, github_url_base=release.release_base_url)
        super().__init__(config, base_dir)
        self.providers = dict(providers or default_providers())

    def _fetch_series(self, spec: SeriesSpec, start: date, end: date) -> pd.DataFrame:
        provider = self.providers.get(spec.provider)
        if provider is None:
            raise RuntimeError(f"Provedor não registrado: {spec.provider} ({spec.alias})")
        frames = [provider.fetch(spec, part_start, part_end) for part_start, part_end in _windows(start, end)]
        non_empty = [frame for frame in frames if not frame.empty]
        if not non_empty:
            return _decorate(pd.DataFrame(columns=["data", "valor"]), spec)
        return _decorate(pd.concat(non_empty, ignore_index=True), spec)

    def materialize_history(
        self,
        *,
        start: date | str = date(2011, 1, 1),
        end: date | str | None = None,
        aliases: Sequence[str] | None = None,
        overwrite: bool = False,
        max_workers: int = 6,
        progress_callback: Callable[[float, str], None] | None = None,
    ) -> CacheResult:
        start_date = pd.Timestamp(start).date()
        end_date = pd.Timestamp(end or date.today()).date()
        if start_date > end_date:
            return CacheResult(False, "Data inicial posterior à data final", fonte="nenhum")

        specs = [get_series(alias) for alias in aliases] if aliases else list(bcb_series())
        previous = pd.DataFrame()
        if not overwrite and self.existe():
            loaded = self.carregar_local()
            if loaded.sucesso and loaded.dados is not None:
                previous = loaded.dados

        frames: list[pd.DataFrame] = []
        failures: list[dict[str, str]] = []
        with ThreadPoolExecutor(max_workers=max(1, min(max_workers, 8))) as executor:
            pending = {
                executor.submit(self._fetch_series, spec, start_date, end_date): spec
                for spec in specs
            }
            completed = 0
            for future in as_completed(pending):
                spec = pending[future]
                completed += 1
                try:
                    frames.append(future.result())
                except Exception as exc:
                    failures.append({"serie": spec.alias, "codigo": str(spec.code), "erro": str(exc)})
                if progress_callback:
                    progress_callback(completed / len(specs), f"{completed}/{len(specs)} — {spec.label}")

        fresh = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        combined = pd.concat([previous, fresh], ignore_index=True) if not previous.empty else fresh
        if combined.empty:
            return CacheResult(False, "Nenhuma série foi extraída", metadata={"falhas": failures}, fonte="nenhum")
        combined["data"] = pd.to_datetime(combined["data"], errors="coerce")
        combined = (
            combined.dropna(subset=["data", "valor"])
            .drop_duplicates(subset=["data", "serie"], keep="last")
            .sort_values(["serie", "data"])
            .reset_index(drop=True)
        )
        combined["codigo"] = pd.to_numeric(combined["codigo"], errors="coerce").astype("Int32")
        combined["valor"] = pd.to_numeric(combined["valor"], errors="coerce").astype("Float64")

        saved = self.salvar_local(
            combined,
            fonte="BCData/SGS",
            info_extra={
                "inicio_solicitado": start_date.isoformat(),
                "fim_solicitado": end_date.isoformat(),
                # `series_no_arquivo` descreve o parquet salvo; `series_da_rodada`
                # descreve o pedido desta execução. Um campo só reportava o
                # pedido, então uma atualização incremental de 3 séries deixava
                # o metadado dizendo "3" num arquivo de 130.
                "series_no_arquivo": int(combined["serie"].nunique()),
                "series_da_rodada": len(specs),
                "series_solicitadas": int(combined["serie"].nunique()),
                "series_com_dados": int(combined["serie"].nunique()),
                "falhas": failures,
                "registry_size": len(SGS_SERIES),
            },
        )
        if saved.sucesso and self.arquivo_metadata.exists():
            metadata = saved.metadata or {}
            periods = sorted(combined["data"].dt.strftime("%Y%m").unique().tolist())
            metadata["periodos"] = periods
            metadata["total_periodos"] = len(periods)
            metadata["series"] = int(combined["serie"].nunique())
            self.arquivo_metadata.write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            saved.metadata = metadata
        saved.sucesso = saved.sucesso and not failures
        saved.mensagem = (
            f"{combined['serie'].nunique()} séries e {len(combined)} observações materializadas"
            + (f"; {len(failures)} falha(s)" if failures else "")
        )
        return saved

    def baixar_remoto(self) -> CacheResult:
        data_url = add_release_cache_buster(
            build_release_asset_url(f"{self.config.nome}_dados.parquet"),
            self.config.nome,
            "parquet",
        )
        metadata_url = add_release_cache_buster(
            build_release_asset_url(f"{self.config.nome}_metadata.json"),
            self.config.nome,
            "metadata",
        )
        no_cache_headers = {"Cache-Control": "no-cache", "Pragma": "no-cache"}
        try:
            data_response = requests.get(data_url, timeout=120, headers=no_cache_headers)
            if data_response.status_code != 200:
                return CacheResult(False, f"Asset SGS remoto indisponível ({data_response.status_code})", fonte="nenhum")
            frame = pd.read_parquet(BytesIO(data_response.content))
            metadata = None
            metadata_response = requests.get(metadata_url, timeout=30, headers=no_cache_headers)
            if metadata_response.status_code == 200:
                metadata = metadata_response.json()
            return CacheResult(
                True,
                f"Cache SGS remoto carregado: {len(frame)} observações",
                dados=frame,
                metadata=metadata,
                fonte="github_releases",
            )
        except Exception as exc:
            return CacheResult(False, f"Falha ao baixar cache SGS remoto: {exc}", fonte="nenhum")

    def carregar(self, forcar_remoto: bool = False) -> CacheResult:
        result = super().carregar(forcar_remoto=forcar_remoto)
        if result.sucesso and result.fonte == "github_releases" and result.metadata:
            self.arquivo_metadata_runtime.write_text(
                json.dumps(result.metadata, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        return result

    def extrair_periodo(self, periodo: str, **kwargs) -> CacheResult:
        try:
            month = pd.Period(str(periodo), freq="M")
        except Exception:
            return CacheResult(False, "Período SGS deve ser YYYYMM ou YYYY-MM", fonte="nenhum")
        aliases = kwargs.get("aliases")
        specs = [get_series(alias) for alias in aliases] if aliases else list(bcb_series())
        frames = []
        failures = []
        for spec in specs:
            try:
                frames.append(self._fetch_series(spec, month.start_time.date(), month.end_time.date()))
            except Exception as exc:
                failures.append(f"{spec.alias}: {exc}")
        frames = [frame for frame in frames if not frame.empty]
        if not frames:
            return CacheResult(False, f"Sem dados para {periodo}: {'; '.join(failures[:3])}", fonte="nenhum")
        result = pd.concat(frames, ignore_index=True)
        return CacheResult(
            not failures,
            f"{len(result)} observações extraídas para {periodo}",
            dados=result,
            metadata={"falhas": failures},
            fonte="api",
        )
