"""Deterministic refresh and accounting gates for the financial-analysis product."""
from __future__ import annotations

from datetime import date
import hashlib
import json
import math
from pathlib import Path

import pandas as pd
import requests

from .bloprudencial import download_bloprudencial_zip, extract_bloprudencial_csv
from .bloprudencial_ingest import KEY, normalize_cache
from ..prudential_analysis import Accounts, build_analysis, period_key

SOURCES = ("bloprudencial", "ativo", "dre", "capital", "principal", "carteira_instrumentos")
DEFAULT_RULES = {"rounding_brl": 1.0, "anomaly_relative": .50, "anomaly_material_brl": 1_000_000.0}


def discover_source(root, period=None, *, today=None):
    """A missing month is skipped only on 404; access/server errors remain errors."""
    today = today or date.today()
    current = today.year * 12 + today.month - 2  # last closed calendar month
    candidates = [period] if period else [f"{(current-i)//12:04d}{(current-i)%12+1:02d}" for i in range(18)]
    for candidate in candidates:
        try:
            archive = download_bloprudencial_zip(candidate, root, force_refresh=True, timeout=45)
            return candidate, extract_bloprudencial_csv(archive, Path(root) / "csv")
        except requests.HTTPError as exc:
            if exc.response is None or exc.response.status_code != 404 or period:
                raise
    raise ValueError("Nenhuma competência publicada nos últimos 18 meses")


def same_data(left, right):
    if set(left.columns) != set(right.columns) or len(left) != len(right):
        return False
    columns = sorted(left.columns)
    a = pd.util.hash_pandas_object(left[columns], index=False).sort_values().to_numpy()
    b = pd.util.hash_pandas_object(right[columns], index=False).sort_values().to_numpy()
    return bool((a == b).all())


def validate_candidate(cosif, sources, period, *, rules=None):
    """Keep source/perimeter differences in the report; block broken accounting."""
    rules = {**DEFAULT_RULES, **(rules or {})}
    if any(not math.isfinite(float(v)) or float(v) < 0 for v in rules.values()):
        raise ValueError("Limiares de validação inválidos")
    cosif = normalize_cache(cosif)
    if cosif.duplicated(KEY).any():
        raise ValueError("Chaves COSIF duplicadas")
    incoming = cosif[cosif.DATA_BASE.eq(period)]
    if incoming.empty:
        raise ValueError("Competência solicitada ausente do CSV")
    for kind, frame in sources.items():
        if frame.empty:
            continue
        if not {"CodInst", "Período"}.issubset(frame.columns):
            raise ValueError(f"{kind}: chave de instituição/período ausente")
        selected = frame[frame["Período"].map(period_key).eq(period)]
        if selected.duplicated(["CodInst", "Período"]).any() or selected.CodInst.isna().any() or selected.CodInst.astype(str).str.strip().eq("").any():
            raise ValueError(f"{kind}: chave de instituição/período inválida")
        numbers = selected.select_dtypes(include="number")
        if ((numbers == float("inf")) | (numbers == float("-inf"))).any().any():
            raise ValueError(f"{kind}: valor não finito")
    report = {"period": period, "institutions": incoming.COD_CONGL.nunique(),
              "errors": [], "warnings": [], "checks": 0, "rules": rules}
    grouped_sources = {kind: {str(code): frame for code, frame in data.groupby("CodInst")}
                       for kind, data in sources.items() if not data.empty}
    previous = cosif[cosif.DATA_BASE.lt(period)]
    for code, frame in incoming.groupby("COD_CONGL", sort=True):
        institution_sources = {kind: groups.get(str(code), pd.DataFrame()) for kind, groups in grouped_sources.items()}
        analysis = build_analysis(frame, institution_sources, code, [period])
        documents = set(frame.DOCUMENTO)
        preferred = "4066" if "4066" in documents else "4060"
        accounts = Accounts(frame[frame.DOCUMENTO.eq(preferred)])
        missing = [prefix for prefix in ("1", "4", "6") if not accounts.select(prefix)[0]]
        if missing:
            report["errors"].append({"code": code, "check": "Grupos patrimoniais obrigatórios", "missing": missing})
        for check in analysis.checks:
            report["checks"] += 1
            if check["status"] == "OK":
                continue
            name, difference = check["check"], check["difference"]
            critical = name.startswith(("Balanço:", "DRE: resultado", "Carteira: C1–C5"))
            # Absence of a report (e.g. monthly IF.data) is data availability.
            required = name.startswith(("Balanço: Ativo", "Balanço: composição", "DRE: resultado"))
            blocking = (check["status"] == "N/D" and required) or (
                check["status"] == "Divergência" and critical and abs(difference) > rules["rounding_brl"] + .0001)
            if check["status"] == "Divergência" and name.startswith("Subcontas") and abs(difference) > rules["rounding_brl"] + .0001:
                blocking = True
            target = "errors" if blocking else "warnings"
            report[target].append({"code": code, **check})
        institution_history = previous[previous.COD_CONGL.eq(code)]
        for name, identifiers in {"Balanço": ("assets", "equity"), "DRE": ("net",)}.items():
            comparable = institution_history
            if name == "DRE":
                comparable = comparable[(comparable.DATA_BASE.str[4:].astype(int)-1).mod(6).eq((int(period[4:])-1) % 6)]
            if comparable.empty:
                continue
            comparison_period = comparable.DATA_BASE.max()
            old = comparable[comparable.DATA_BASE.eq(comparison_period)]
            before = build_analysis(old, institution_sources, code, [comparison_period])
            changes = []
            for ident in identifiers:
                now = analysis.sheets[name].cells[f"C{analysis.rows[name][ident]}"].value
                then = before.sheets[name].cells[f"C{before.rows[name][ident]}"].value
                if isinstance(now, (int, float)) and isinstance(then, (int, float)):
                    material = abs(now-then)*1e6 >= rules["anomaly_material_brl"]
                    if material and (not then or abs((now-then)/then) >= rules["anomaly_relative"]):
                        changes.append({"metric": ident, "previous": then, "current": now, "unit": "BRL million"})
            if changes:
                report["warnings"].append({"code": code, "check": "Variação material", "previous_period": comparison_period, "values": changes})
    return report


def archive_sources(candidate, root):
    """Retain source bytes and hashes, including for rejected candidates."""
    for directory in ("bcb_bloprudencial/sources", "bcb_ifdata_web", "institution_registry"):
        origin = Path(candidate) / "data/cache" / directory
        if not origin.exists():
            continue
        for path in origin.rglob("*"):
            if not path.is_file():
                continue
            content = path.read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            target = Path(root) / "data/cache/financial_analysis_sources" / digest[:2] / digest
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.write_bytes(content)
            if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise ValueError("Falha na guarda da fonte")
            yield {"name": path.relative_to(candidate).as_posix(), "sha256": digest,
                   "archive": target.relative_to(root).as_posix(), "bytes": len(content)}


def promote_legacy(manager, candidate, names):
    """Use each cache's recoverable transaction, restoring earlier writes on error."""
    from .update_state import mutation_lock
    backups, promoted = {}, []
    with mutation_lock(manager.base_dir, owner={"label": "análise financeira"}):
        for name in names:
            cache = manager.get_cache(name)
            if cache.existe_leitura():
                backups[name] = (pd.read_parquet(cache.arquivo_dados), json.loads(cache.arquivo_metadata.read_text()))
        try:
            for name in names:
                source = candidate.get_cache(name)
                metadata = json.loads(source.arquivo_metadata.read_text())
                result = manager.get_cache(name).salvar_local(pd.read_parquet(source.arquivo_dados),
                    fonte=metadata.get("fonte", "api"), metadata_extra=metadata)
                if not result.sucesso:
                    raise ValueError(f"{name}: {result.mensagem}")
                promoted.append(name)
        except Exception:
            for name in reversed(promoted):
                if name in backups:
                    frame, metadata = backups[name]
                    result = manager.get_cache(name).salvar_local(frame, fonte=metadata.get("fonte", "api"), metadata_extra=metadata)
                    if not result.sucesso:
                        raise RuntimeError(f"Falha ao restaurar {name}: {result.mensagem}")
                else:
                    cache = manager.get_cache(name)
                    # Only new files created by this promotion are removed.
                    for path in (cache.arquivo_dados_runtime, cache.arquivo_metadata_runtime, cache._integrity_file):
                        path.unlink(missing_ok=True)
            raise
