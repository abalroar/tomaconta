#!/usr/bin/env python3
"""Benchmark local para as telas críticas Snapshot e Peers."""

from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import app1  # noqa: E402
from utils.ifdata_cache import CacheManager, load_critical_screens_slice  # noqa: E402
from utils.ifdata_cache.critical_screens import (  # noqa: E402
    _load_bloprud_periods,
    build_critical_screens_dataframe,
)


PEERS_INSTITUICAO = "ITAU - PRUDENCIAL"
PEERS_PERIODOS = ["1/2025", "2/2025", "3/2025"]
PEERS_METRICAS = [
    "Ativos Líquidos",
    "Carteira de Crédito*",
    "Perda Esperada",
    "Depósitos Totais",
    "Core Funding*",
    "Perda Esperada / Estágio 3",
    "Perda Esperada / Carteira de Crédito*",
    "Índice de Capital Principal (CET1)",
    "Índice de Basileia Total (%)",
]

SNAPSHOT_INSTITUICAO = "A27 IP - PRUDENCIAL"
SNAPSHOT_PERIODOS = ["1/2025", "2/2025", "3/2025"]
SNAPSHOT_METRICAS = [
    "Índice de Capital Principal (CET1)",
    "Índice de Basileia Total (%)",
    "Perda Esperada",
    "Perda Esperada / Estágio 3",
    "Perda Esperada / Carteira de Crédito*",
    "CapitalDisponivel",
    "BloprudencialDisponivel",
    "QualidadeCarteiraDisponivel",
]

SOURCE_CACHE_TYPES = [
    "principal",
    "ativo",
    "passivo",
    "capital",
    "carteira_pf",
    "carteira_pj",
    "carteira_instrumentos",
]


def _benchmark(label: str, fn, repeat: int = 3):
    timings = []
    result = None
    for _ in range(repeat):
        t0 = time.perf_counter()
        result = fn()
        timings.append(time.perf_counter() - t0)
    return {
        "label": label,
        "min_s": min(timings),
        "avg_s": statistics.mean(timings),
        "max_s": max(timings),
        "result": result,
    }


def _load_sources(manager: CacheManager, periodos: list[str]) -> dict[str, pd.DataFrame]:
    loaded = {}
    for cache_name in SOURCE_CACHE_TYPES:
        resultado = manager.carregar(cache_name)
        if not resultado.sucesso or resultado.dados is None:
            raise RuntimeError(f"{cache_name}: {resultado.mensagem}")
        df = resultado.dados
        loaded[cache_name] = df[df["Período"].astype(str).isin(periodos)].copy()
    return loaded


def _build_on_demand(manager: CacheManager, periodos: list[str]) -> pd.DataFrame:
    loaded = _load_sources(manager, periodos)
    return build_critical_screens_dataframe(
        df_principal=loaded["principal"],
        df_ativo=loaded["ativo"],
        df_passivo=loaded["passivo"],
        df_capital=loaded["capital"],
        df_carteira_pf=loaded["carteira_pf"],
        df_carteira_pj=loaded["carteira_pj"],
        df_carteira_instrumentos=loaded["carteira_instrumentos"],
        df_bloprudencial=_load_bloprud_periods(PROJECT_ROOT, periodos),
        base_dir=PROJECT_ROOT,
    )


def _build_legacy_strict(manager: CacheManager, instituicao: str, periodos: list[str]) -> pd.DataFrame:
    loaded = _load_sources(manager, periodos)
    strict = {}
    for cache_name, df in loaded.items():
        sub = df
        if "Instituição" in sub.columns:
            sub = sub[sub["Instituição"].astype(str).eq(instituicao)].copy()
        strict[cache_name] = sub
    return build_critical_screens_dataframe(
        df_principal=strict["principal"],
        df_ativo=strict["ativo"],
        df_passivo=strict["passivo"],
        df_capital=strict["capital"],
        df_carteira_pf=strict["carteira_pf"],
        df_carteira_pj=strict["carteira_pj"],
        df_carteira_instrumentos=strict["carteira_instrumentos"],
        df_bloprudencial=_load_bloprud_periods(PROJECT_ROOT, periodos),
        base_dir=PROJECT_ROOT,
    )


def _load_materialized(instituicao: str, periodos: list[str]) -> pd.DataFrame:
    return load_critical_screens_slice(
        base_dir=PROJECT_ROOT,
        periodos=periodos,
        instituicoes=[instituicao],
    )


def _summarize_metric_presence(df: pd.DataFrame, instituicao: str, periodos: list[str], metricas: list[str]) -> dict[str, list[str]]:
    missing = {}
    rec = df[(df["Instituição"].astype(str) == instituicao) & (df["Período"].astype(str).isin(periodos))].copy()
    for periodo in periodos:
        row = rec[rec["Período"].astype(str) == periodo]
        faltantes = []
        for metrica in metricas:
            if row.empty or metrica not in row.columns:
                faltantes.append(metrica)
                continue
            valor = row.iloc[0][metrica]
            if pd.isna(valor):
                faltantes.append(metrica)
        missing[periodo] = faltantes
    return missing


def _print_benchmark(title: str, bench: dict) -> None:
    print(
        f"{title}: min={bench['min_s']:.4f}s avg={bench['avg_s']:.4f}s max={bench['max_s']:.4f}s",
        flush=True,
    )


def _benchmark_peers_server_path() -> dict:
    periodos_sel = app1.ordenar_periodos(PEERS_PERIODOS, reverso=True)
    periodos_base = {app1._periodo_ano_anterior(p) for p in periodos_sel}
    periodos_dez = {
        app1._periodo_dez_ano_anterior(p)
        for p in list(periodos_sel) + list(periodos_base)
    }
    periodos_ext = tuple(sorted({p for p in list(periodos_sel) + sorted(periodos_base) + sorted(periodos_dez) if p}))
    instituicoes = tuple(sorted([PEERS_INSTITUICAO]))
    critical_token = app1._cache_version_token("critical_screens")

    sub = {}

    t0 = time.perf_counter()
    app1._get_peers_filters_context(critical_token)
    sub["context_curado_s"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    df = app1._carregar_cache_relatorio_slice(
        "critical_screens",
        critical_token,
        periodos_ext,
        instituicoes,
    )
    sub["slice_curado_s"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    extra = app1._preparar_metricas_extra_peers_from_slice(df, [PEERS_INSTITUICAO], periodos_ext)
    sub["extra_from_slice_s"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    valores, colunas_usadas, faltas, delta_flags, delta_context, tooltips = app1._montar_tabela_peers(
        df,
        [PEERS_INSTITUICAO],
        periodos_sel,
        perf={},
        extra_values_precomputed=extra,
        allow_capital_fallback=False,
    )
    sub["montar_tabela_s"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    html = app1._render_peers_table_html(
        [PEERS_INSTITUICAO],
        periodos_sel,
        valores,
        colunas_usadas,
        delta_flags,
        delta_context,
        tooltips,
    )
    sub["render_html_s"] = time.perf_counter() - t0
    sub["html_len"] = len(html)
    sub["faltas"] = sorted(faltas)
    return sub


def main() -> int:
    manager = CacheManager(PROJECT_ROOT)

    print("## Peers", flush=True)
    peers_legacy = _benchmark(
        "legacy_strict",
        lambda: _build_legacy_strict(manager, PEERS_INSTITUICAO, PEERS_PERIODOS),
        repeat=2,
    )
    peers_ondemand = _benchmark(
        "ondemand_canonical",
        lambda: _build_on_demand(manager, PEERS_PERIODOS),
        repeat=2,
    )
    peers_curated = _benchmark(
        "materialized_slice",
        lambda: _load_materialized(PEERS_INSTITUICAO, PEERS_PERIODOS),
        repeat=5,
    )
    _print_benchmark("legacy_strict", peers_legacy)
    _print_benchmark("ondemand_canonical", peers_ondemand)
    _print_benchmark("materialized_slice", peers_curated)
    print("peers_server_path_curated=", _benchmark_peers_server_path(), flush=True)
    print(
        "missing_legacy_strict=",
        _summarize_metric_presence(peers_legacy["result"], PEERS_INSTITUICAO, PEERS_PERIODOS, PEERS_METRICAS),
        flush=True,
    )
    print(
        "missing_materialized=",
        _summarize_metric_presence(peers_curated["result"], PEERS_INSTITUICAO, PEERS_PERIODOS, PEERS_METRICAS),
        flush=True,
    )

    print("\n## Snapshot", flush=True)
    snapshot_ondemand = _benchmark(
        "ondemand_canonical",
        lambda: _build_on_demand(manager, SNAPSHOT_PERIODOS),
        repeat=2,
    )
    snapshot_curated = _benchmark(
        "materialized_slice",
        lambda: _load_materialized(SNAPSHOT_INSTITUICAO, SNAPSHOT_PERIODOS),
        repeat=5,
    )
    _print_benchmark("ondemand_canonical", snapshot_ondemand)
    _print_benchmark("materialized_slice", snapshot_curated)
    print(
        "missing_materialized=",
        _summarize_metric_presence(snapshot_curated["result"], SNAPSHOT_INSTITUICAO, SNAPSHOT_PERIODOS, SNAPSHOT_METRICAS),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
