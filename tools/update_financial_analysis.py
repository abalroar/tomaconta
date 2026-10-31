"""Atualiza a análise financeira pelo BCB, com validação antes da promoção."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd
import requests

from utils.ifdata_cache import CacheManager
from utils.ifdata_cache.bloprudencial_ingest import ingest_source, read_source
from utils.ifdata_cache.financial_analysis_update import (
    SOURCES, archive_sources, discover_source, promote_legacy, same_data, validate_candidate,
)
from utils.ifdata_cache.official_store import store_from_env, writable_cache_context
from utils.ifdata_cache.update_backend import LocalOnlySourcesManager, assert_adapter_complete, collect_official_artifacts
from utils.ifdata_cache.release_ops import materialize_for_publication, validate_cache_quality
from utils.ifdata_cache.update_state import mutation_lock


def update(root, *, period=None, csv=None, offline=False, check_only=False, rules=None):
    root = Path(root).resolve()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8]
    report_dir = root / "data/cache/financial_analysis_updates"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{run_id}.json"
    report = {"run_id": run_id, "status": "running", "requested_period": period, "changed": [], "sources": []}
    old_env = {key: os.environ.get(key) for key in ("TOMACONTA_IFDATA_WEB_DIR", "TOMACONTA_IFDATA_SOURCE", "TOMACONTA_IFDATA_REGISTRY_DIR")}
    try:
        # Pin/copy the complete read generation under the existing mutation lock.
        with mutation_lock(root, owner={"label": "análise financeira"}):
            live = CacheManager(root)
            store = store_from_env(root)
            parent = store.current() if store else None
            baseline = collect_official_artifacts(live, validate_quality=False) if any(live.get_cache(k).existe_leitura() for k in live.listar_caches()) else {}
            with tempfile.TemporaryDirectory(prefix="financial-analysis-", dir=report_dir) as temporary, writable_cache_context():
                workspace = Path(temporary)
                for logical, path in baseline.items():
                    destination = workspace / logical
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, destination)
                candidate = CacheManager(workspace)
                if csv:
                    _, source_info = read_source(Path(csv))
                    if period and period != source_info["period"]:
                        raise ValueError("Data-base solicitada diverge do arquivo")
                    period = source_info["period"]
                elif offline:
                    raise ValueError("--offline exige --csv")
                else:
                    period, csv = discover_source(workspace / "data/cache/bcb_bloprudencial", period)
                report["period"] = period
                report["ingestion"] = ingest_source(Path(csv), workspace)
                report["sources"] = list(archive_sources(workspace, root))
                if not offline:
                    response = requests.get("https://www3.bcb.gov.br/ifdata/rest/relatorios2025a2030", timeout=(15, 45))
                    response.raise_for_status()
                    catalog = response.json()
                    published = sorted(str(item["dt"]) for item in catalog if str(item["dt"]) <= period)
                    # Publication calendars differ. Refresh the latest available quarter
                    # even when the selected COSIF month itself is not a quarter end.
                    if published:
                        quarter = published[-1]
                        report["ifdata_period"] = quarter
                        os.environ["TOMACONTA_IFDATA_WEB_DIR"] = str(workspace / "data/cache/bcb_ifdata_web")
                        os.environ["TOMACONTA_IFDATA_SOURCE"] = "web"
                        os.environ["TOMACONTA_IFDATA_REGISTRY_DIR"] = str(workspace / "data/cache/institution_registry")
                        from utils.ifdata_cache.ifdata_web import get_web_source
                        get_web_source.cache_clear()
                        for kind in SOURCES[1:]:
                            result = candidate.extrair_periodos_com_salvamento(kind, [quarter], modo="overwrite", force_refresh=True)
                            assert_adapter_complete(result)
                    else:
                        report["ifdata_period"] = None
                report["sources"] = list(archive_sources(workspace, root))
                data = pd.read_parquet(candidate.get_cache("bloprudencial").arquivo_dados)
                sources = {kind: pd.read_parquet(candidate.get_cache(kind).arquivo_dados)
                           for kind in SOURCES[1:] if candidate.get_cache(kind).existe_leitura()}
                report["source_quality"] = validate_cache_quality(candidate, list(sources))
                if any(not item["success"] for item in report["source_quality"].values()):
                    raise ValueError("Qualidade das fontes reprovada; geração anterior preservada")
                report["validation"] = validate_candidate(data, sources, period, rules=rules)
                # A newly published IF.data quarter may precede the COSIF month.
                quarter = report.get("ifdata_period")
                if quarter and quarter != period and data.DATA_BASE.astype(str).eq(quarter).any():
                    report["ifdata_validation"] = validate_candidate(data, sources, quarter, rules=rules)
                if any(report[key]["errors"] for key in ("validation", "ifdata_validation") if key in report):
                    raise ValueError("Conferência contábil reprovada; geração anterior preservada")
                for kind in SOURCES:
                    source = candidate.get_cache(kind)
                    if not source.existe_leitura():
                        continue
                    original = live.get_cache(kind)
                    if not original.existe_leitura() or not same_data(pd.read_parquet(original.arquivo_dados), pd.read_parquet(source.arquivo_dados)):
                        report["changed"].append(kind)
                if check_only or not report["changed"]:
                    report["status"] = "validated" if check_only else "unchanged"
                else:
                    details = materialize_for_publication(LocalOnlySourcesManager(candidate), cache_names=report["changed"], base_dir=workspace)
                    report["materialization"] = details
                    if any(item["status"] != "ok" for item in details):
                        raise ValueError("Materialização incompleta; geração anterior preservada")
                    names = report["changed"] + [item["cache"] for item in details]
                    if store:
                        artifacts = collect_official_artifacts(candidate, validate_quality=True)
                        revision = store.stage(artifacts, parent_revision=parent.revision_id if parent else None,
                                               metadata={"action": "financial_analysis", "run_id": run_id, "period": period})
                        store.activate(revision.revision_id, expected_parent=parent.revision_id if parent else None,
                                       actor={"subject": "financial-analysis-cli"})
                        report["revision_id"] = revision.revision_id
                    else:
                        promote_legacy(live, candidate, names)
                    report["status"] = "updated"
    except Exception as exc:
        report.update(status="failed", error=f"{type(exc).__name__}: {exc}")
    finally:
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        from utils.ifdata_cache.ifdata_web import get_web_source
        get_web_source.cache_clear()
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str, allow_nan=False) + "\n")
    return report, report_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--data-base", help="YYYY-MM; omitido: última competência mensal publicada")
    parser.add_argument("--csv", type=Path, help="Arquivo BLOPRUDENCIAL já disponível")
    parser.add_argument("--offline", action="store_true", help="Valida o CSV com os relatórios IF.data já guardados")
    parser.add_argument("--check-only", action="store_true", help="Valida e guarda fontes sem promover a geração")
    parser.add_argument("--rules", type=Path, help="JSON com os limiares operacionais de validação")
    args = parser.parse_args()
    if args.data_base and not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", args.data_base):
        parser.error("--data-base exige YYYY-MM")
    rules = json.loads(args.rules.read_text()) if args.rules else None
    report, path = update(args.root, period=args.data_base.replace("-", "") if args.data_base else None,
                          csv=args.csv, offline=args.offline, check_only=args.check_only, rules=rules)
    print(json.dumps({"status": report["status"], "period": report.get("period"), "changed": report["changed"],
                      "report": str(path), "error": report.get("error")}, ensure_ascii=False))
    return 1 if report["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
