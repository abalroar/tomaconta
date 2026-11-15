"""Rebuild the affected quarter from unique official cells, preserving other quarters."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils.ifdata_cache.extractor import _calcular_metricas_derivadas, _deduplicate_reported_values, _normalizar_nome_coluna
from utils.ifdata_cache.derived_metrics import build_individual_derived_metrics
from utils.ifdata_cache.institutions import normalize_institution_code


PERIOD = "3/2025"
PUBLICATION = "tomaconta-individual-set25-dedup-20261010-v1"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def official_cells(path, report):
    raw = pd.DataFrame(json.loads(Path(path).read_text())["value"])
    if not raw["AnoMes"].eq("202509").all() or not raw["TipoInstituicao"].eq(3).all() or not raw["NumeroRelatorio"].astype(str).eq(str(report)).all():
        raise ValueError("Fonte oficial não corresponde ao trimestre/relatório/perímetro individual solicitado.")
    unique = _deduplicate_reported_values(raw)
    unique["NomeColuna"] = unique["NomeColuna"].map(_normalizar_nome_coluna)
    if unique.duplicated(["CodInst", "NomeColuna"]).any():
        raise ValueError("Fonte oficial contém indicadores ambíguos após normalizar os rótulos.")
    pivot = unique.pivot(index="CodInst", columns="NomeColuna", values="Saldo")
    audit = {"url": f"https://olinda.bcb.gov.br/olinda/servico/IFDATA/versao/v1/odata/IfDataValores(AnoMes=202509,TipoInstituicao=3,Relatorio='{report}')?$format=json&$top=500000",
             "sha256": digest(path), "bytes": Path(path).stat().st_size, "raw_records": len(raw),
             "unique_records": len(unique), "exact_duplicate_records": len(raw) - len(unique)}
    return pivot, audit


def repair_frame(original, official, *, summary=False):
    repaired = original.copy()
    selected = original["Período"].eq(PERIOD)
    codes = original.loc[selected, "CodInst"].map(normalize_institution_code)
    if codes.duplicated().any() or not set(codes).issubset(set(official.index)):
        raise ValueError("Cobertura de CodInst divergente para o trimestre a reparar.")
    incoming = official.reindex(codes).copy()
    incoming.index = original.index[selected]
    columns = [column for column in incoming if column in original]
    reconciliation = {}
    for column in columns:
        old, new = original.loc[selected, column], incoming[column]
        valid = old.notna() & new.notna()
        matched = np.isclose(old[valid].to_numpy(dtype=float), new[valid].to_numpy(dtype=float) * 3, rtol=0, atol=.01)
        if not matched.all():
            raise ValueError(f"{column}: valor publicado não reconcilia com as três cópias oficiais; reparo interrompido.")
        repaired.loc[selected, column] = new
        reconciliation[column] = {"comparable_cells": int(valid.sum()), "triple_matches": int(matched.sum()),
                                  "official_missing_cells": int(new.isna().sum())}
    if summary:
        frame = _calcular_metricas_derivadas(repaired.loc[selected].copy(), "202509")
        for column in frame:
            if column not in {"CodInst", "Instituição", "Período"}:
                repaired.loc[selected, column] = frame[column]
    pd.testing.assert_frame_equal(original.loc[~selected], repaired.loc[~selected])
    assert original[["CodInst", "Instituição", "Período"]].equals(repaired[["CodInst", "Instituição", "Período"]])
    return repaired, reconciliation


def write_cache(repo, name, frame, now, provenance, stats=None):
    bundle = repo / "data/bundled" / name
    metadata = json.loads((bundle / "metadata.json").read_text())
    frame.to_parquet(bundle / "dados.parquet", index=False)
    metadata.update(timestamp_salvamento=now, total_registros=len(frame), colunas=list(frame),
                    total_periodos=frame["Período"].nunique(), publication_id=PUBLICATION,
                    sha256=digest(bundle / "dados.parquet"))
    metadata.setdefault("extra", {})["official_cell_dedup_repair"] = provenance
    if stats is not None:
        metadata["extra"].update(denominador_zero_ou_nan=stats.denominador_zero_ou_nan,
                                  period_type=stats.period_type, periodos_detectados=stats.periodos_detectados,
                                  cache_origem_dre="dre_individual", cache_origem_principal="principal_individual",
                                  cache_origem_ativo="", cache_origem_carteira_instrumentos="", carteira_fonte=stats.carteira_fonte)
    (bundle / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    runtime = repo / "data/cache" / name
    runtime.mkdir(parents=True, exist_ok=True)
    for filename in ("dados.parquet", "metadata.json"):
        shutil.copyfile(bundle / filename, runtime / filename)
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--summary-json", type=Path, required=True)
    parser.add_argument("--dre-json", type=Path, required=True)
    parser.add_argument("--manifest-json", type=Path, required=True, help="Fresh copy of the complete published release manifest")
    args = parser.parse_args()
    repo = args.repo.resolve()
    now = datetime.now(timezone.utc).isoformat()
    summary_cells, summary_source = official_cells(args.summary_json, 1)
    dre_cells, dre_source = official_cells(args.dre_json, 4)
    principal_before = pd.read_parquet(repo / "data/bundled/principal_individual/dados.parquet")
    dre_before = pd.read_parquet(repo / "data/bundled/dre_individual/dados.parquet")
    derived_before = pd.read_parquet(repo / "data/bundled/derived_metrics_individual/dados.parquet")
    principal, principal_audit = repair_frame(principal_before, summary_cells, summary=True)
    dre, dre_audit = repair_frame(dre_before, dre_cells)
    derived, stats = build_individual_derived_metrics(dre, principal)
    if len(derived) != len(derived_before):
        raise ValueError("Rebuild individual mudou a cardinalidade de métricas; verificar a identidade antes de publicar.")
    provenance = {"period": PERIOD, "operation": "unique_official_cells_before_pivot", "verified_at_utc": now,
                  "sources": {"principal_individual": summary_source, "dre_individual": dre_source},
                  "individual_identity": "CodInst", "individual_scope": "Rel. 1 + Rel. 4; sem Rel. 2/16 prudencial"}
    manifest = json.loads(args.manifest_json.read_text())
    # Preserve unrelated release assets and gates from the fresh published manifest.
    metadata_by_name = {name: write_cache(repo, name, frame, now, provenance, stats if name == "derived_metrics_individual" else None)
                        for name, frame in (("principal_individual", principal), ("dre_individual", dre), ("derived_metrics_individual", derived))}
    manifest.update(generated_at_utc=now, run_id=PUBLICATION)
    manifest.setdefault("supplemental", {})["individual_set25_dedup"] = provenance
    assets = []
    for name, metadata in metadata_by_name.items():
        manifest["caches"][name].update(timestamp=now, sha256=metadata["sha256"], record_count=metadata["total_registros"],
                                        period_count=metadata["total_periodos"])
        for filename, suffix in (("dados.parquet", "dados.parquet"), ("metadata.json", "metadata.json")):
            path = repo / "data/bundled" / name / filename
            asset = f"{name}_{suffix}"
            manifest.setdefault("published_assets", {})[asset] = {"sha256": digest(path), "bytes": path.stat().st_size}
            assets.append({"asset": asset, "path": str(path.relative_to(repo)), "sha256": digest(path), "bytes": path.stat().st_size})
    manifest_path = repo / "data/cache/manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    assets.append({"asset": "manifest.json", "path": str(manifest_path.relative_to(repo)), "sha256": digest(manifest_path), "bytes": manifest_path.stat().st_size})
    audit = {**provenance, "publication_id": PUBLICATION, "principal_reconciliation": principal_audit,
             "dre_reconciliation": dre_audit, "other_quarters_preserved": True,
             "records": {name: metadata["total_registros"] for name, metadata in metadata_by_name.items()}, "assets": assets}
    (repo / "docs/ifdata_individual_set25_dedup_20261010.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"publication_id": PUBLICATION, "assets": assets}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
