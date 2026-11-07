#!/usr/bin/env python3
"""Publish exact-identity inputs and default snapshots for the original Python model.

Each Parquet is read once. Arbitrary 1–8 period selections are rebuilt by the
same financial Python modules in Pyodide; no sliced formulas or native defaults.
The final index is atomically replaced only after every selected entity succeeds.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
import gzip
import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from statements_bridge import (MODEL_VERSION, INPUT_VERSION, build_from_payload,
                               serialize_analysis, clean)
from utils.prudential_analysis import period_key
from utils.prudential_presentation import default_periods, period_label

ENGINE_MODULES = (
    "utils/prudential_analysis.py", "utils/prudential_nim.py",
    "utils/prudential_presentation.py", "utils/prudential_workbook.py",
    "utils/prudential_pptx.py", "utils/financial_statement_style.py",
    "utils/presentation_tables.py",
)
IFDATA = ("ativo", "dre", "capital", "principal", "carteira_instrumentos",
          "principal_individual", "dre_individual")


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(clean(value), ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    temporary = path.with_suffix(path.suffix + ".tmp")
    encoded = data.encode("utf-8")
    if path.suffix == ".gz":
        encoded = gzip.compress(encoded, compresslevel=9, mtime=0)
    temporary.write_bytes(encoded)
    temporary.replace(path)
    return len(encoded)


def compress_publication(output):
    """Convert a completed, indexed publication without rerunning the model.

    Every roundtrip is checked before the final index is replaced and the raw
    files from that index are removed. Only this publication's named files count.
    """
    output = Path(output)
    index_path = output / "statements/index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    raw_files = []
    for item in index["institutions"]:
        ident = item["id"]
        if ident != f"{item['scope']}-{item['code']}":
            raise ValueError("Identidade inválida no índice a comprimir")
        expected_path = f"data/statements/{ident}.json"
        expected_input = f"data/statements/inputs/{ident}.json"
        if item["path"] != expected_path or item["inputPath"] != expected_input:
            raise ValueError("A publicação já está comprimida ou tem caminhos incompatíveis")
        raw_snapshot = output / expected_path.removeprefix("data/")
        raw_input = output / expected_input.removeprefix("data/")
        snapshot = json.loads(raw_snapshot.read_text(encoding="utf-8"))
        inputs = json.loads(raw_input.read_text(encoding="utf-8"))
        snapshot["inputPath"] = expected_input + ".gz"
        for raw, value in ((raw_snapshot, snapshot), (raw_input, inputs)):
            compressed = raw.with_name(raw.name + ".gz")
            dump(compressed, value)
            if json.loads(gzip.decompress(compressed.read_bytes())) != value:
                raise ValueError(f"Compressão alterou conteúdo: {raw.name}")
            raw_files.append(raw)
        item["path"] += ".gz"
        item["inputPath"] += ".gz"
        item["inputBytes"] = raw_input.with_name(raw_input.name + ".gz").stat().st_size
        item["snapshotBytes"] = raw_snapshot.with_name(raw_snapshot.name + ".gz").stat().st_size
        item["inputSha256"] = hashlib.sha256(raw_input.with_name(raw_input.name + ".gz").read_bytes()).hexdigest()
        item["snapshotSha256"] = hashlib.sha256(raw_snapshot.with_name(raw_snapshot.name + ".gz").read_bytes()).hexdigest()
    index["transport"] = {"encoding": "gzip", "deterministic": True, "mtime": 0}
    dump(index_path, index)
    for raw in raw_files:
        raw.unlink()
    return index


def source_path(root, kind):
    """Use the published bundle unless an explicit source root is supplied."""
    path = root / "data" / "bundled" / kind / "dados.parquet"
    if not path.is_file():
        raise FileNotFoundError(f"Fonte publicada ausente: {path}")
    return path


def frame_packet(frame, provenance=None):
    # Object dtype avoids NaN reconstruction and keeps absent numeric cells null.
    cleaned = frame.astype(object).where(pd.notna(frame), None)
    constants = {column: cleaned[column].iloc[0] for column in cleaned.columns
                 if len(cleaned) and cleaned[column].nunique(dropna=False) == 1}
    variable = cleaned.drop(columns=list(constants))
    result = {"columns": list(variable.columns), "data": variable.values.tolist(),
              "constants": constants, "columnOrder": list(frame.columns)}
    if provenance:
        result["provenance"] = provenance
    return clean(result)


class Sources:
    def __init__(self, root):
        self.root, self.frames, self.indexes, self.provenance = root, {}, {}, {}
        metadata_path = source_path(root, "bloprudencial").with_name("metadata.json")
        self.decisions = json.loads(metadata_path.read_text(encoding="utf-8")).get("cosif_decisions", [])

    def load(self, kind):
        if kind not in self.frames:
            path = source_path(self.root, kind)
            frame = pd.read_parquet(path)
            self.frames[kind] = frame
            self.provenance[kind] = {"filename": f"{kind}/dados.parquet",
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "rows": len(frame)}
        return self.frames[kind]

    def entity(self, kind, code):
        frame = self.load(kind)
        key = {"bloprudencial": "COD_CONGL", "balancete_individual": "CNPJ"}.get(kind, "CodInst")
        if kind not in self.indexes:
            self.indexes[kind] = frame.groupby(key, sort=False, dropna=True).indices
        indices = self.indexes[kind].get(code)
        return frame.iloc[indices].copy() if indices is not None else frame.iloc[:0].copy()

    def catalog(self, scope):
        kind = "balancete_individual" if scope == "individual" else "bloprudencial"
        frame = self.load(kind)
        code, name = ("CNPJ", "NOME_INSTITUICAO") if scope == "individual" else ("COD_CONGL", "NOME_CONGL")
        result = frame[[code, name, "DATA_BASE"]].rename(columns={code: "code", name: "name", "DATA_BASE": "period"}).drop_duplicates()
        for column in result:
            result[column] = result[column].astype(str)
        if result.duplicated(["code", "period"]).any():
            raise ValueError(f"{scope}: identidade oficial ambígua na competência")
        return result.sort_values(["code", "period"])

    def payload(self, scope, code, records):
        individual = scope == "individual"
        kind = "balancete_individual" if individual else "bloprudencial"
        cosif = self.entity(kind, code)
        if individual:
            cosif = cosif.assign(DOCUMENTO="4010", COD_CONGL=cosif.CNPJ,
                                 NOME_CONGL=cosif.NOME_INSTITUICAO)
        fields = ([("principal", "principal_individual"), ("dre", "dre_individual")]
                  if individual else [(name, name) for name in IFDATA[:5]])
        sources = {}
        for field, source in fields:
            frame = self.entity(source, code)
            # Preserve the source attributes used by the original loader.
            provenance = self.provenance[source] if not individual else None
            sources[field] = frame_packet(frame, provenance)
        decisions = [item for item in self.decisions
                     if not item.get("code") or str(item["code"]) == code]
        # Decisions are the original account→row rules, scoped only when the
        # published decision itself declares a code. No new classifications.
        overrides = {item["account"]: item["row"] for item in decisions
                     if item.get("account") and item.get("row")}
        return {"schemaVersion": INPUT_VERSION, "modelVersion": MODEL_VERSION,
            "id": f"{scope}-{code}", "scope": scope, "code": code,
            "name": str(records.iloc[-1]["name"]),
            "periods": sorted(records.period.unique()),
            "cosif": frame_packet(cosif, self.provenance[kind] if not individual else None),
            "ifdata": sources, "overrides": overrides,
            "source": self.provenance[kind]}


def publish_engine(root, output):
    target = output / "statements" / "engine"
    target.mkdir(parents=True, exist_ok=True)
    modules = []
    for relative in (*ENGINE_MODULES, "utils/__init__.py", "bridge.py"):
        if relative == "bridge.py":
            content = Path(__file__).with_name("statements_bridge.py").read_bytes()
        else:
            content = (root / relative).read_bytes()
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        modules.append({"path": relative, "sha256": hashlib.sha256(content).hexdigest(), "size": len(content)})
    manifest = {"schemaVersion": 1, "modelVersion": MODEL_VERSION,
        "pyodide": {"version": "0.29.3", "indexURL": "https://cdn.jsdelivr.net/pyodide/v0.29.3/full/"},
        "packages": {"builtIn": ["pandas", "lxml", "pillow", "micropip"],
                     "pip": ["XlsxWriter==3.2.9", "python-pptx==0.6.23"]},
        "packageVersions": {"pandas": "2.3.3", "numpy": "2.2.5", "lxml": "6.0.2", "pillow": "11.3.0"},
        "bridge": "bridge.py", "modules": modules}
    dump(target / "manifest.json", manifest)
    return manifest


def analysis_crosswalk(sources, institutions, analysis_catalog=None):
    """Exact same-period official-code/source-name join; prudential only."""
    principal = sources.load("principal")
    critical = sources.load("critical_screens")
    left = principal[["CodInst", "Instituição", "Período"]].dropna(subset=["CodInst"]).drop_duplicates()
    left = left[left.CodInst.astype(str).str.startswith("C")]
    right = critical[["InstituiçãoRaw", "InstituiçãoKey", "Período"]].drop_duplicates()
    if left.duplicated(["CodInst", "Período"]).any() or right.duplicated(["InstituiçãoRaw", "Período"]).any():
        raise ValueError("Crosswalk: identidade ambígua na fonte")
    linked = left.merge(right, left_on=["Instituição", "Período"],
                        right_on=["InstituiçãoRaw", "Período"], validate="many_to_one")
    linked["period"] = linked["Período"].map(period_key)
    allowed = {item["id"]: item for item in institutions if item["scope"] == "prudential"}
    catalog_ids = ({item["id"] for item in analysis_catalog["institutions"]}
                   if analysis_catalog is not None else None)
    candidates = {}
    for row in linked.to_dict("records"):
        statement_id = "prudential-" + str(row["CodInst"])
        if statement_id not in allowed or row["period"] not in allowed[statement_id]["periods"]:
            continue
        ident = hashlib.sha256(str(row["InstituiçãoKey"]).encode()).hexdigest()[:16]
        if catalog_ids is not None and ident not in catalog_ids:
            continue
        candidates.setdefault(ident, []).append({"statementId": statement_id, "scope": "prudential",
            "code": str(row["CodInst"]), "effectivePeriod": row["period"],
            "institutionKey": str(row["InstituiçãoKey"]),
            "method": "CodInst + Instituição = InstituiçãoRaw na mesma competência"})
    result, ambiguous = {}, []
    for ident, matches in candidates.items():
        if len({item["statementId"] for item in matches}) > 1:
            ambiguous.append(ident)
        else:
            result[ident] = max(matches, key=lambda item: item["effectivePeriod"])
    return {"schemaVersion": 1, "links": result, "ambiguousAnalysisIds": sorted(ambiguous),
        "sources": {name: sources.provenance[name] for name in ("principal", "critical_screens")},
        "note": "Vínculo por código oficial e nome original exato na mesma competência. Sem correspondência entre perímetros."}


def export(root, output, *, scopes=("individual", "prudential"), codes=None, progress=print):
    root, output = Path(root), Path(output)
    if any((root / path).read_bytes() != (ROOT / path).read_bytes() for path in ENGINE_MODULES):
        raise ValueError("O diretório de fontes deve usar os mesmos módulos Python do exporter")
    sources = Sources(root)
    publish_engine(root, output)
    index = {"schemaVersion": 2, "modelVersion": MODEL_VERSION,
        "generatedAt": datetime.now(timezone.utc).isoformat(), "institutions": [],
        "scopes": {"individual": "Instituição individual · COSIF 4010",
                   "prudential": "Conglomerado prudencial · COSIF 4060/4066"},
        "unit": "R$ milhões", "percentUnit": "fraction", "maxPeriods": 8,
        "enginePath": "data/statements/engine/manifest.json", "sources": {},
        "selection": {"scopes": list(scopes), "codes": sorted(codes) if codes else None},
        "coverage": "selected" if codes else "all-source-identities",
        "transport": {"encoding": "gzip", "deterministic": True, "mtime": 0}}
    for scope in scopes:
        if scope not in {"individual", "prudential"}:
            raise ValueError(f"Perímetro inválido: {scope}")
        catalog = sources.catalog(scope)
        groups = list(catalog.groupby("code", sort=True))
        for at, (code, records) in enumerate(groups, 1):
            if codes and code not in codes:
                continue
            payload = sources.payload(scope, code, records)
            selected = sorted(default_periods(payload["periods"], date.today()))
            if not selected:
                selected = payload["periods"][-1:]
            analysis = build_from_payload(payload, selected)
            ident, periods = payload["id"], payload["periods"]
            input_path = f"data/statements/inputs/{ident}.json.gz"
            snapshot = {**serialize_analysis(analysis), "schemaVersion": 2, "id": ident,
                "scope": scope, "code": code, "name": payload["name"],
                "availablePeriods": periods, "defaultPeriods": selected,
                "periodLabels": {p: period_label(p) for p in periods},
                "inputPath": input_path, "source": payload["source"]}
            if scope == "individual":
                snapshot["cnpjBase"] = code
            input_bytes = dump(output / input_path.removeprefix("data/"), payload)
            snapshot_bytes = dump(output / "statements" / f"{ident}.json.gz", snapshot)
            index["institutions"].append({"id": ident, "scope": scope, "code": code,
                "name": payload["name"], "periods": periods, "latestPeriod": periods[-1],
                "defaultPeriods": selected, "path": f"data/statements/{ident}.json.gz",
                "inputPath": input_path, "inputBytes": input_bytes, "snapshotBytes": snapshot_bytes,
                "inputSha256": hashlib.sha256((output / input_path.removeprefix("data/")).read_bytes()).hexdigest(),
                "snapshotSha256": hashlib.sha256((output / "statements" / f"{ident}.json.gz").read_bytes()).hexdigest()})
            if at % 25 == 0 or at == len(groups):
                progress(f"{scope}: {at}/{len(groups)} · {code}")
        if scope == "individual":
            # Individual statements are complete; these large frames have no
            # role in the subsequent prudential or identity-crosswalk steps.
            for kind in ("balancete_individual", "principal_individual", "dre_individual"):
                sources.frames.pop(kind, None)
                sources.indexes.pop(kind, None)
    if codes and set(codes) - {item["code"] for item in index["institutions"]}:
        raise ValueError("Código solicitado ausente no catálogo de fontes")
    index["sources"] = sources.provenance.copy()
    index["counts"] = {scope: sum(item["scope"] == scope for item in index["institutions"]) for scope in scopes}
    analysis_path = output / "institutions.json"
    if not analysis_path.exists():
        analysis_path = root / "web/public/data/institutions.json"
    analysis_catalog = json.loads(analysis_path.read_text()) if analysis_path.exists() else None
    crosswalk = analysis_crosswalk(sources, index["institutions"], analysis_catalog)
    dump(output / "statements" / "crosswalk.json", crosswalk)
    index["crosswalkPath"] = "data/statements/crosswalk.json"
    # The index names only files produced in this invocation. Stale artifacts
    # from an interrupted or filtered run are never discovered or published.
    dump(output / "statements" / "index.json", index)
    return index


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=ROOT / "web/generated/data")
    parser.add_argument("--codes", nargs="*")
    parser.add_argument("--scopes", nargs="*", default=["individual", "prudential"])
    args = parser.parse_args()
    result = export(args.root, args.output, codes=args.codes, scopes=args.scopes)
    print(json.dumps(result["counts"], ensure_ascii=False))
