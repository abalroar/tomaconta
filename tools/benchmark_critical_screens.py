#!/usr/bin/env python3
"""Benchmark baseline para telas críticas (Peers/Rankings/DRE).

Uso:
  python tools/benchmark_critical_screens.py --repeats 5
"""

from __future__ import annotations

import argparse
import glob
import json
import statistics
import time
from pathlib import Path
from typing import Any, Callable


def _find_parquet_paths() -> dict[str, Path]:
    candidates = {
        "principal": ["data/cache/principal/dados.parquet", "data/cache/principal/*cache.parquet"],
        "passivo": ["data/cache/passivo/dados.parquet", "data/cache/passivo/*cache.parquet"],
        "dre": ["data/cache/dre/dados.parquet", "data/cache/dre/*cache.parquet"],
    }
    out: dict[str, Path] = {}
    for key, patterns in candidates.items():
        for pat in patterns:
            found = sorted(glob.glob(pat))
            if found:
                out[key] = Path(found[0])
                break
    return out


def _timeit(fn: Callable[[], Any], repeats: int) -> dict[str, float]:
    times = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        times.append(time.perf_counter() - t0)
    return {
        "min_s": min(times),
        "mediana_s": statistics.median(times),
        "max_s": max(times),
        "media_s": statistics.mean(times),
    }


def run(repeats: int) -> dict[str, Any]:
    try:
        import pandas as pd
    except Exception as exc:
        raise RuntimeError("pandas não disponível no ambiente") from exc

    try:
        import pyarrow.dataset as ds
    except Exception as exc:
        raise RuntimeError("pyarrow não disponível no ambiente") from exc

    paths = _find_parquet_paths()
    if "passivo" not in paths or "dre" not in paths:
        raise RuntimeError("arquivos parquet mínimos ausentes (passivo/dre)")

    df_probe = pd.read_parquet(paths["passivo"])
    if "Período" not in df_probe.columns or "Instituição" not in df_probe.columns:
        raise RuntimeError("passivo sem colunas mínimas de filtro (Período/Instituição)")

    periodo = str(df_probe["Período"].dropna().iloc[0])
    instituicao = str(df_probe["Instituição"].dropna().iloc[0])

    def peers_full_read_filter() -> int:
        df = pd.read_parquet(paths["passivo"])
        out = df[(df["Período"] == periodo) & (df["Instituição"] == instituicao)]
        return len(out)

    def peers_pyarrow_filter() -> int:
        dataset = ds.dataset(str(paths["passivo"]))
        table = dataset.to_table(
            filter=(ds.field("Período") == periodo) & (ds.field("Instituição") == instituicao)
        )
        return table.num_rows

    def rankings_like() -> int:
        df = pd.read_parquet(paths["passivo"])
        num_cols = [c for c in df.columns if c not in ("Instituição", "Período") and pd.api.types.is_numeric_dtype(df[c])]
        if not num_cols:
            return 0
        col = num_cols[0]
        latest = sorted(df["Período"].dropna().unique())[-1]
        out = df[df["Período"] == latest][["Instituição", col]].sort_values(col, ascending=False).head(15)
        return len(out)

    def dre_like() -> int:
        df = pd.read_parquet(paths["dre"])
        if "Período" not in df.columns:
            return 0
        latest = sorted(df["Período"].dropna().unique())[-1]
        out = df[df["Período"] == latest]
        return len(out)

    results = {
        "contexto": {
            "repeats": repeats,
            "paths": {k: str(v) for k, v in paths.items()},
            "filtro_probe": {"periodo": periodo, "instituicao": instituicao},
        },
        "benchmarks": {
            "peers_full_read_filter": _timeit(peers_full_read_filter, repeats),
            "peers_pyarrow_filter": _timeit(peers_pyarrow_filter, repeats),
            "rankings_like": _timeit(rankings_like, repeats),
            "dre_like": _timeit(dre_like, repeats),
        },
    }
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output", type=Path, default=Path("docs/baseline_critical_screens.json"))
    args = parser.parse_args()

    try:
        payload = run(args.repeats)
    except RuntimeError as exc:
        print(f"[WARN] baseline não executado: {exc}")
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[OK] baseline salvo em {args.output}")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
