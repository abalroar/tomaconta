#!/usr/bin/env python3
"""Materialize the Atlas PF/PJ credit cube from the existing SCR annual cache.

No network, raw-cache mutation or replacement financial formula. Uses the
published modalidade_bcb and utils.scr_data_query.agregar, retaining every
observed client/product cell, including the official de-para's PF labels in PJ.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from utils import scr_data_query as query
from utils.ifdata_cache import scr_data as scr

BALANCES = ["carteira_inadimplencia", "carteira_ativa"]
KEYS = ["data_base", "uf", "porte", "modalidade_bcb"]
SOURCE_URL = "https://www.bcb.gov.br/estabilidadefinanceira/scrdata"
METHOD_URL = "https://www.bcb.gov.br/pda/desig/metodologia_versao2.pdf"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def locate(cache: Path, year: int) -> Path:
    options = [cache / "staging/annual" / f"{year}.parquet", cache / f"scr_data_ano_{year}.parquet"]
    return next((path for path in options if path.is_file()), options[0])


def finite(value):
    value = float(value)
    return value if math.isfinite(value) else None


def write(path: Path, value):
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)
    return {"path": "data/" + path.name, "bytes": len(encoded), "sha256": hashlib.sha256(encoded).hexdigest()}


def check_reaggregation(frame, aggregated):
    """Check independently chosen cuts against the unchanged query module."""
    checks = []
    for by in [["data_base"], ["data_base", "uf"], ["data_base", "porte"],
               ["data_base", "modalidade_bcb"], ["data_base", "uf", "porte"],
               ["data_base", "uf", "modalidade_bcb"]]:
        cube_sum = aggregated.groupby(by, as_index=False, observed=True)[["numerador", "denominador"]].sum()
        original = query.agregar(frame, "inadimplencia", by=by)
        merged = cube_sum.merge(original, on=by, suffixes=("_cube", "_original"), validate="one_to_one")
        if len(merged) != len(cube_sum) or len(merged) != len(original):
            raise ValueError("Incompatible source/cube coverage")
        for field in ["numerador", "denominador"]:
            np.testing.assert_allclose(merged[field + "_cube"], merged[field + "_original"], rtol=2e-6, atol=.01)
        ratio = merged.numerador_cube.div(merged.denominador_cube).where(merged.denominador_cube > 0)
        checks.append({"groupBy": by, "cuts": len(merged),
                       "maxRateDifferencePP": finite(((ratio - merged.valor).abs() * 100).max())})
    return checks


def export_person(raw, person, months, ufs, source_files, source_meta, output):
    frame = query.filtrar(raw, cliente=person).copy()
    if frame.empty or frame[KEYS + BALANCES].isna().any().any():
        raise ValueError(f"{person}: missing source dimensions/balances or modalidade_bcb; restore schema-2 SCR annual assets")
    if (frame[BALANCES] < 0).any().any() or (frame.carteira_inadimplencia > frame.carteira_ativa).any():
        raise ValueError(f"{person}: incompatible balances")
    if set(frame.data_base.astype(str)) != set(months):
        raise ValueError(f"{person}: annual cache does not cover the requested complete month range")

    segments = query.ordem_portes(person)
    unknown_segments = set(frame.porte.astype(str)) - set(segments)
    if unknown_segments:
        raise ValueError(f"{person}: unrecognized source segments {sorted(unknown_segments)}")
    domain = list(scr.MODALIDADES_BCB_PF if person == "PF" else scr.MODALIDADES_BCB_PJ)
    present_products = set(frame.modalidade_bcb.astype(str))
    # The original official mapping assigns 0202/0203 to PF modalities even
    # where the client column is PJ. Retain and label them, never fold into Other.
    extras = [name for name in scr.MODALIDADES_BCB if name in present_products and name not in domain]
    products = domain + extras
    if present_products - set(products):
        raise ValueError(f"{person}: product outside the original official mapping")
    promoted = frame.copy()
    promoted[BALANCES] = promoted[BALANCES].astype("float64")
    aggregated = query.agregar(promoted, "inadimplencia", by=KEYS)
    lookups = [dict((value, i) for i, value in enumerate(values)) for values in
               [months, [uf["uf"] for uf in ufs], segments, products]]
    rows = [[lookups[0][str(row.data_base)], lookups[1][str(row.uf)], lookups[2][str(row.porte)],
             lookups[3][str(row.modalidade_bcb)], finite(row.numerador), finite(row.denominador)]
            for row in aggregated.itertuples(index=False)]
    rows.sort(key=lambda row: row[:4])
    expected = len(months) * len(ufs) * len(segments) * len(products)
    if len({tuple(row[:4]) for row in rows}) != len(rows):
        raise ValueError("Duplicate source coordinates")
    reaggregation = check_reaggregation(frame, aggregated)
    source_hashes = {item["asset"]: item["sha256"] for item in source_files}
    latest = query.agregar(promoted[promoted.data_base.astype(str).eq(months[-1])], "inadimplencia").iloc[0]
    checks = {"sourceRows": len(frame), "observedCells": len(rows), "expectedCells": expected,
              "absentCells": expected - len(rows), "zeroNumeratorCells": int(aggregated.numerador.eq(0).sum()),
              "zeroDenominatorCells": int(aggregated.denominador.eq(0).sum()),
              "originalQuery": reaggregation,
              "latest": {"month": months[-1], "numerator": finite(latest.numerador),
                         "denominator": finite(latest.denominador), "ratePct": finite(latest.valor * 100)}}
    doc = {
        "schemaVersion": 1, "source": "BCB · SCR.data", "sourceUrl": SOURCE_URL,
        "methodologyUrl": METHOD_URL, "equivalenceUrl": scr.SCR_EQUIVALENCIA_MODALIDADES_URL,
        "person": person, "unit": "R$ mil", "periodStart": months[0], "periodEnd": months[-1],
        "dims": {"person": person, "segmentKind": "income" if person == "PF" else "size",
                 "months": months, "ufs": ufs, "segments": segments, "products": products},
        "columns": ["monthIndex", "ufIndex", "segmentIndex", "productIndex", "numerator", "denominator"],
        "metric": {"id": "inadimplencia", "label": "Inadimplência", "numerator": "carteira_inadimplencia",
                   "denominator": "carteira_ativa", "formula": "sum(numerator) / sum(denominator)",
                   "displayMultiplier": 100, "description": query.METRICAS["inadimplencia"].descricao},
        "rows": rows,
        "missingPolicy": "Absent cells and nonpositive denominators are N/D; observed zero numerator with positive denominator is 0%. Aggregate balances before dividing.",
        "numericPolicy": "Source monetary values promoted to float64 before the unchanged query.agregar; original float32 cut totals may differ by rounding. Checks record these differences.",
        "perimeter": "UF do tomador, todos os segmentos de instituições e submodalidades residuais; cliente " + person,
        "notes": [
            "A localização é a UF do tomador; não é endereço de agência.",
            "As faixas de renda e porte seguem a classificação em cada competência; a composição dos tomadores pode mudar.",
            "A participação de uma modalidade usa como denominador toda a carteira do mesmo mês, cliente, faixa/porte e UF, mesmo quando uma modalidade está selecionada.",
            "Este universo SCR.data tem cobertura própria, distinta do saldo de crédito SGS.",
            "Os rótulos PF em cliente PJ são preservados conforme a nota 1 do de-para oficial (subdomínios 0202/0203); não houve reclassificação nesta camada.",
        ],
        "classificationExceptions": [{"product": name, "reason": "Nota 1 do de-para oficial: modalidade PF no cliente PJ"} for name in extras],
        "sourceFiles": source_files, "sourceMetadata": source_meta,
        "calculationModuleSha256": sha(ROOT / "utils/scr_data_query.py"),
        "classificationModuleSha256": sha(ROOT / "utils/ifdata_cache/scr_data.py"),
        "sourceRevision": hashlib.sha256(json.dumps(source_hashes, sort_keys=True).encode()).hexdigest(),
        "checks": checks,
    }
    asset = write(output / f"atlas-{person.lower()}.json", doc)
    return {"person": person, "asset": asset, "checks": checks}


def export_atlas(cache: Path, output: Path, start="2024-01", end=None):
    metadata_path = next((p for p in [cache / "metadata.json", cache / "scr_data_metadata.json"] if p.is_file()), None)
    if metadata_path is None:
        raise FileNotFoundError(f"SCR metadata absent in {cache}")
    metadata = json.loads(metadata_path.read_text())
    periods = sorted(metadata.get("periodos", []))
    end = end or metadata.get("periodo_final") or periods[-1]
    months = pd.period_range(start, end, freq="M").astype(str).tolist()
    if not months or set(months) - set(periods):
        raise ValueError("Requested Atlas window is absent from SCR metadata")
    paths = [locate(cache, year) for year in range(int(start[:4]), int(end[:4]) + 1)]
    raw = pd.concat([pd.read_parquet(path) for path in paths], ignore_index=True)
    raw = query.filtrar(raw, data_base_inicial=start, data_base_final=end)
    if "modalidade_bcb" not in raw or raw.modalidade_bcb.isna().any():
        raise ValueError("Atlas PF/PJ requires classified schema-2 SCR annual assets (modalidade_bcb). Restore v1.2-scr-cache; PJ classification must not be inferred without origem.")
    if not set(raw.cliente.astype(str)).issubset({"PF", "PJ"}):
        raise ValueError("Unknown SCR client type")
    source_files = [{"asset": f"scr_data_ano_{path.stem[-4:]}.parquet", "bytes": path.stat().st_size,
                     "sha256": sha(path)} for path in paths]
    source_meta = {key: metadata.get(key) for key in ["fonte", "schema_version", "timestamp_salvamento", "periodo_final", "unidade_monetaria"]}
    source_meta["metadataSha256"] = sha(metadata_path)
    ufs = [{"uf": row["uf"], "name": row["uf_nome"], "region": row["regiao"], "ibge": str(row["codigo_ibge"])}
           for row in scr.construir_dim_geo().to_dict("records")]
    if set(raw.uf.astype(str)) != {uf["uf"] for uf in ufs}:
        raise ValueError("Unexpected UF coverage")
    # A financial-validation failure must leave all previous assets intact.
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".atlas-", dir=output.parent) as temporary:
        staging = Path(temporary)
        results = [export_person(raw, person, months, ufs, source_files, source_meta, staging) for person in ["PF", "PJ"]]
        validation = {"schemaVersion": 1, "periodStart": months[0], "periodEnd": months[-1], "months": len(months),
                      "ufs": len(ufs), "persons": results}
        write(staging / "atlas-validation.json", validation)
        for name in ["atlas-pf.json", "atlas-pj.json", "atlas-validation.json"]:
            (staging / name).replace(output / name)
    return validation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--scr-cache", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--start", default="2024-01")
    parser.add_argument("--end")
    args = parser.parse_args()
    validation = export_atlas(args.scr_cache or args.root / "data/cache/scr_data",
                              args.output or args.root / "web/public/data", args.start, args.end)
    print(json.dumps({"periodStart": validation["periodStart"], "periodEnd": validation["periodEnd"],
                      "assets": [person["asset"] for person in validation["persons"]]}))


if __name__ == "__main__":
    main()
