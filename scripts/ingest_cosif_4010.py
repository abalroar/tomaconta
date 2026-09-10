#!/usr/bin/env python3
"""Ingere meses 4010 completos, preserva os demais meses e prepara o bundle."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from utils.ifdata_cache.cosif_4010 import Cosif4010Cache, validate_frame


def ingest(cache: Cosif4010Cache, periods: list[str], *, raw_dir=None, refresh=False, bundle=False):
    parts, sources = [], {}
    if cache.arquivo_dados.exists():
        existing = pd.read_parquet(cache.arquivo_dados)
        validate_frame(existing)
        parts.append(existing.loc[~existing["Período"].isin(periods)])
        metadata = json.loads(cache.arquivo_metadata.read_text())
        sources.update(metadata.get("extra", {}).get("fontes_por_periodo", {}))
    # Nenhum mês é persistido se algum dos grupos solicitados falhar.
    for period in sorted(set(periods)):
        kwargs = {"force_refresh": refresh}
        if raw_dir is not None:
            kwargs["cache_dir"] = raw_dir
        result = cache.extrair_periodo(period, **kwargs)
        if not result.sucesso:
            raise RuntimeError(result.mensagem)
        parts.append(result.dados)
        sources[period] = result.metadata["fontes"]
    data = pd.concat(parts, ignore_index=True).sort_values(
        ["DATA_BASE", "CNPJ", "CONTA"], kind="stable").reset_index(drop=True)
    validate_frame(data)
    result = cache.salvar_local(data, "bcb_cosif", {"fontes_por_periodo": sources})
    if not result.sucesso:
        raise RuntimeError(result.mensagem)
    if bundle:
        cache.bundled_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cache.arquivo_dados_runtime, cache.bundled_dir / "dados.parquet")
        shutil.copy2(cache.arquivo_metadata_runtime, cache.bundled_dir / "metadata.json")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("periodos", nargs="+", help="Competências YYYYMM (ex.: 202606)")
    parser.add_argument("--base-dir", type=Path, default=ROOT)
    parser.add_argument("--raw-dir", type=Path)
    parser.add_argument("--force-refresh", action="store_true")
    parser.add_argument("--bundle", action="store_true", help="Promove os dados para data/bundled/cosif_4010")
    args = parser.parse_args()
    result = ingest(Cosif4010Cache(args.base_dir), args.periodos, raw_dir=args.raw_dir,
                    refresh=args.force_refresh, bundle=args.bundle)
    print(json.dumps({key: result.metadata[key] for key in
                     ("total_registros", "periodos", "sha256", "cobertura")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
