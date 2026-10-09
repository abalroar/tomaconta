#!/usr/bin/env python3
"""Audita identidades dos caches IFData; --repair corrige somente nomes ausentes."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from utils.ifdata_cache.institution_registry import (
    INSTITUTION_NAMED_CACHE_NAMES, registry_name_map, unresolved_name,
)
from utils.ifdata_cache.institutions import normalize_institution_code


def audit(root: Path) -> list[dict]:
    items = []
    for tier in ("cache", "bundled"):
        for name in sorted(INSTITUTION_NAMED_CACHE_NAMES):
            path = root / "data" / tier / name / "dados.parquet"
            if not path.exists():
                continue
            parquet = pq.ParquetFile(path)
            columns = [c for c in ("CodInst", "Instituição", "Período") if c in parquet.schema_arrow.names]
            bad_periods = Counter()
            for batch in parquet.iter_batches(columns=columns, batch_size=65536):
                frame = batch.to_pandas()
                if "Instituição" in frame:
                    mask = frame["Instituição"].astype("string").map(unresolved_name)
                    if mask.any():
                        bad_periods.update(frame.loc[mask, "Período"].astype(str).value_counts().to_dict())
            items.append({"cache": name, "tier": tier, "path": str(path.relative_to(root)),
                          "records": parquet.metadata.num_rows, "unresolved": sum(bad_periods.values()),
                          "unresolved_by_period": dict(bad_periods)})
    return items


def repair(root: Path, registry_file: Path) -> list[dict]:
    registries = {}
    files = sorted(registry_file.glob("*.json")) if registry_file.is_dir() else [registry_file]
    for file in files:
        payload = json.loads(file.read_text())
        encoded = json.dumps(payload["records"], ensure_ascii=False, sort_keys=True).encode()
        if hashlib.sha256(encoded).hexdigest() != payload["sha256_records"]:
            raise ValueError("Checksum do cadastro divergente")
        registry = pd.DataFrame(payload["records"])
        mapping = registry_name_map(registry)
        periodo = payload["periodo"]
        if not re.fullmatch(r"\d{4}(03|06|09|12)", periodo):
            raise ValueError("Competência do cadastro inválida")
        display = f"{int(periodo[4:]) // 3}/{periodo[:4]}"
        registries[display] = (payload, mapping, hashlib.sha256(file.read_bytes()).hexdigest())
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = root / "data/cache_versions" / f"identity-{stamp}"
    repaired = []
    candidates = [item for item in audit(root) if item["unresolved"]]
    prepared = []
    # Toda a cobertura é verificada antes de modificar o primeiro arquivo.
    for item in candidates:
        if not set(item["unresolved_by_period"]).issubset(registries):
            raise ValueError(f"Cadastro não cobre os períodos de {item['path']}")
        path = root / item["path"]
        original = pd.read_parquet(path)
        mask = original["Instituição"].astype("string").map(unresolved_name)
        source = original.loc[mask]
        if "CodInst" in source:
            codes = source["CodInst"].map(normalize_institution_code)
        else:
            # Derivados antigos preservaram a chave exata no próprio placeholder.
            codes = source["Instituição"].astype("string").str.extract(r"^\[IF ([A-Za-z0-9]+)\]$", expand=False)
            if codes.isna().any():
                raise ValueError(f"Identidade sem CodInst recuperável em {item['path']}")
        resolved = pd.Series(index=source.index, dtype="object")
        for display in item["unresolved_by_period"]:
            selection = source["Período"].astype(str).eq(display)
            names = codes.loc[selection].map(registries[display][1])
            if names.isna().any():
                raise ValueError(f"Cadastro não cobre os códigos de {display} em {item['path']}")
            resolved.loc[selection] = names
        corrected = original.copy()
        if isinstance(corrected["Instituição"].dtype, pd.CategoricalDtype):
            additions = set(resolved) - set(corrected["Instituição"].cat.categories)
            corrected["Instituição"] = corrected["Instituição"].cat.add_categories(sorted(additions))
        corrected.loc[mask, "Instituição"] = resolved
        pd.testing.assert_frame_equal(original.drop(columns="Instituição"), corrected.drop(columns="Instituição"))
        prepared.append((item, path, corrected, mask))
    for item, path, corrected, mask in prepared:
        temporary = path.with_suffix(".identity.tmp.parquet")
        corrected.to_parquet(temporary, index=False)
        pd.testing.assert_frame_equal(pd.read_parquet(temporary), corrected)
        before_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        after_hash = hashlib.sha256(temporary.read_bytes()).hexdigest()
        backup_path = backup / item["tier"] / item["cache"]
        backup_path.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup_path / path.name)
        metadata_path = path.with_name("metadata.json")
        metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
        if metadata_path.exists():
            shutil.copy2(metadata_path, backup_path / metadata_path.name)
        used = [registries[p] for p in item["unresolved_by_period"]]
        periods = sorted(p["periodo"] for p, _, _ in used)
        details = {"periodos": periods, "names_repaired": int(mask.sum()),
                   "registry_sha256_by_period": {p["periodo"]: sha for p, _, sha in used},
                   "source": "; ".join(dict.fromkeys(p["source"] for p, _, _ in used)),
                   "before_sha256": before_hash, "after_sha256": after_hash,
                   "numeric_values_unchanged": True, "repaired_at_utc": stamp}
        metadata.setdefault("extra", {})["institution_identity_repair"] = details
        if item["tier"] == "bundled" and metadata.get("publication_id"):
            metadata["publication_id"] += f".identity-{periods[-1]}-v1"
        meta_temp = metadata_path.with_suffix(".identity.tmp.json")
        meta_temp.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
        temporary.replace(path)
        meta_temp.replace(metadata_path)
        repaired.append({**item, **details, "backup": str(backup_path)})
    return repaired


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--repair", action="store_true")
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.repair and not args.registry:
        parser.error("--repair exige --registry com o cadastro oficial validado ou seu diretório")
    result = {"before": audit(args.root)}
    if args.repair:
        result["repairs"] = repair(args.root, args.registry)
        result["after"] = audit(args.root)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n")
    print(rendered)
