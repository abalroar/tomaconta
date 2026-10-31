"""Deterministic refresh and accounting gates for the financial-analysis product."""
from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
from uuid import uuid4

import pandas as pd
import requests

from .bloprudencial import download_bloprudencial_zip, extract_bloprudencial_csv
from .bloprudencial_cache import row_overrides
from .bloprudencial_ingest import KEY, ingest_source, normalize_cache, read_source
from .balancete_individual import QUARTER_ENDS, adopt_file
from .financial_analysis_review import REVIEW_MATERIAL_BRL, WATCHED_ROWS, account_changes, new_decisions, pending_items, row_jumps
from ..prudential_analysis import Accounts, build_analysis, period_key

INDIVIDUAL = "balancete_individual"
SOURCES = ("bloprudencial", "ativo", "dre", "capital", "principal", "carteira_instrumentos")
DEFAULT_RULES = {"rounding_brl": 1.0, "anomaly_relative": .50, "anomaly_material_brl": 1_000_000.0,
                 "review_material_brl": REVIEW_MATERIAL_BRL}


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


def validate_candidate(cosif, sources, period, *, rules=None, overrides=None):
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
    watched = {ident: [0.0, 0.0] for ident in WATCHED_ROWS}
    for code, frame in incoming.groupby("COD_CONGL", sort=True):
        institution_sources = {kind: groups.get(str(code), pd.DataFrame()) for kind, groups in grouped_sources.items()}
        institution_history = previous[previous.COD_CONGL.eq(code)]
        # A DRE de setembro e dezembro acumula o fechamento de junho, que está no histórico.
        analysis = build_analysis(pd.concat([frame, institution_history]), institution_sources, code, [period], overrides=overrides)
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
        for name, identifiers in {"Balanço": ("assets", "equity"), "DRE": ("net",)}.items():
            comparable = institution_history
            if name == "DRE":
                comparable = comparable[comparable.DATA_BASE.str[4:].eq(period[4:])]
            if comparable.empty:
                continue
            comparison_period = comparable.DATA_BASE.max()
            before = build_analysis(institution_history, institution_sources, code, [comparison_period], overrides=overrides)
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
            if name == "DRE":
                # O total do sistema, na mesma janela do ano anterior, revela conta que mudou de linha.
                for ident in WATCHED_ROWS:
                    now = analysis.sheets[name].cells[f"C{analysis.rows[name][ident]}"].value
                    then = before.sheets[name].cells[f"C{before.rows[name][ident]}"].value
                    if isinstance(now, (int, float)) and isinstance(then, (int, float)):
                        watched[ident][0] += now
                        watched[ident][1] += then
    report["review"] = account_changes(cosif, period, material=rules["review_material_brl"], overrides=overrides) + row_jumps(watched, period)
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


def refresh_individual(candidate, live, period, workspace, overrides):
    """Traz o 4010 do fim de trimestre e aplica as mesmas regras em todas as instituições."""
    if period[4:] not in QUARTER_ENDS:
        return {"status": "not_quarter_end"}
    cache = candidate.get_cache(INDIVIDUAL)
    result = cache.extrair_periodo(period, cache_dir=Path(workspace) / "data/cache/bcb_cosif_4010", force_refresh=True)
    if not result.sucesso:
        # Publicações têm calendários próprios: a análise prudencial não espera o arquivo individual.
        return {"status": "unavailable", "message": result.mensagem}
    incoming = result.dados
    original = live.get_cache(INDIVIDUAL)
    changed = period not in original.available_periods() or not same_data(original.load_period(period), incoming)
    if changed:
        cache.add_period(incoming)
    return {"status": "changed" if changed else "unchanged", "institutions": int(incoming.CNPJ.nunique()),
            "rows": len(incoming), "review": individual_review(cache, period, overrides)}


def individual_review(cache, period, overrides):
    """Contas novas ou sumidas no sistema e divergência contábil em qualquer instituição."""
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    table = pq.read_table(cache.arquivo_dados, columns=["DATA_BASE", "CONTA"])
    earlier = sorted(p for p in pc.unique(table.column("DATA_BASE")).to_pylist() if p < period)
    known = pc.unique(table.filter(pc.less(table.column("DATA_BASE"), period)).column("CONTA")).to_pylist()
    current = cache.load_period(period)
    frames = [current]
    if earlier:
        frames.append(cache.load_period(earlier[-1]))
    frames.append(pd.DataFrame({"DATA_BASE": "000000", "CNPJ": "", "CONTA": known, "NOME_CONTA": "", "SALDO": 0.0}))
    compact = pd.concat(frames, ignore_index=True)[["DATA_BASE", "CNPJ", "CONTA", "NOME_CONTA", "SALDO"]]
    items = account_changes(compact.assign(DOCUMENTO="4010", COD_CONGL=compact.CNPJ), period, overrides=overrides)
    needed = [p for p in (f"{period[:4]}06",) if int(period[4:]) > 6 and p in earlier]
    window = current if not needed else pd.concat([current, cache.load_period(needed[0])], ignore_index=True)
    window = window.assign(DOCUMENTO="4010", COD_CONGL=window.CNPJ, NOME_CONGL=window.NOME_INSTITUICAO)
    failed = []
    for code, frame in window.groupby("COD_CONGL", sort=True):
        if not frame.DATA_BASE.eq(period).any():
            continue
        analysis = build_analysis(frame, {}, code, [period], overrides=overrides, result_doc="4010", has_portfolio=False)
        if any(check["status"] == "Divergência" and check["check"].startswith(("Balanço:", "DRE: resultado", "Subcontas"))
               and abs(check["difference"]) > DEFAULT_RULES["rounding_brl"] + .0001 for check in analysis.checks):
            failed.append(code)
    if failed:
        items.append({"id": f"divergencia:4010:{period}", "kind": "divergencia", "document": "4010", "account": None,
                      "name": f"{len(failed)} instituição(ões): " + ", ".join(failed[:10]), "previous_name": None,
                      "total_brl": 0.0, "institutions": len(failed), "row": None, "row_label": None,
                      "result_account": False, "blocking": True})
    return items


def latest_period(cache):
    """Última competência já carregada, lida só da coluna de data."""
    if not cache.existe_leitura():
        return None
    return str(pd.read_parquet(cache.arquivo_dados, columns=["DATA_BASE"]).DATA_BASE.astype(str).max())


def update(root, *, period=None, csv=None, offline=False, check_only=False, rules=None, decisions=None, progress=None):
    """Baixa, confere e, sem pendência de revisão, promove a nova geração como um todo.

    ``decisions`` responde à revisão de contas: {id do item: {"row": linha da DRE ou None}}.
    """
    from . import CacheManager
    from .official_store import store_from_env, writable_cache_context
    from .release_ops import materialize_for_publication, validate_cache_quality
    from .update_backend import LocalOnlySourcesManager, assert_adapter_complete, collect_official_artifacts
    from .update_state import mutation_lock

    progress = progress or (lambda stage: None)
    root = Path(root).resolve()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8]
    report_dir = root / "data/cache/financial_analysis_updates"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{run_id}.json"
    report = {"run_id": run_id, "status": "running", "requested_period": period, "changed": [], "sources": [],
              "check_only": check_only, "csv": str(csv) if csv else None}
    old_env = {key: os.environ.get(key) for key in ("TOMACONTA_IFDATA_WEB_DIR", "TOMACONTA_IFDATA_SOURCE", "TOMACONTA_IFDATA_REGISTRY_DIR")}
    try:
        # Pin/copy the complete read generation under the existing mutation lock.
        with mutation_lock(root, owner={"label": "análise financeira"}):
            live = CacheManager(root)
            store = store_from_env(root)
            parent = store.current() if store else None
            live_cosif = live.get_cache("bloprudencial")
            report["previous_max_period"] = latest_period(live_cosif)
            existing_decisions = live_cosif.cosif_decisions()
            baseline = collect_official_artifacts(live, validate_quality=False) if any(live.get_cache(k).existe_leitura() for k in live.listar_caches()) else {}
            with tempfile.TemporaryDirectory(prefix="financial-analysis-", dir=report_dir) as temporary, writable_cache_context():
                workspace = Path(temporary)
                for logical, path in baseline.items():
                    destination = workspace / logical
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, destination)
                candidate = CacheManager(workspace)
                progress("Baixando a publicação do BCB")
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
                recorded = new_decisions(decisions, period, run_id)
                all_decisions = existing_decisions + recorded
                overrides = row_overrides(all_decisions)
                report["ingestion"] = ingest_source(Path(csv), workspace, decisions=all_decisions)
                report["sources"] = list(archive_sources(workspace, root))
                if not offline:
                    progress("Atualizando os relatórios do IF.data")
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
                        from .ifdata_web import get_web_source
                        get_web_source.cache_clear()
                        for kind in SOURCES[1:]:
                            result = candidate.extrair_periodos_com_salvamento(kind, [quarter], modo="overwrite", force_refresh=True)
                            assert_adapter_complete(result)
                    else:
                        report["ifdata_period"] = None
                report["sources"] = list(archive_sources(workspace, root))
                progress("Conferindo as contas e os totais")
                data = pd.read_parquet(candidate.get_cache("bloprudencial").arquivo_dados)
                sources = {kind: pd.read_parquet(candidate.get_cache(kind).arquivo_dados)
                           for kind in SOURCES[1:] if candidate.get_cache(kind).existe_leitura()}
                report["source_quality"] = validate_cache_quality(candidate, list(sources))
                if any(not item["success"] for item in report["source_quality"].values()):
                    raise ValueError("Qualidade das fontes reprovada; geração anterior preservada")
                report["validation"] = validate_candidate(data, sources, period, rules=rules, overrides=overrides)
                if not offline:
                    progress("Conferindo os balancetes individuais")
                    report["individual"] = refresh_individual(candidate, live, period, workspace, overrides)
                    report["validation"]["review"] += report["individual"].pop("review", [])
                # A newly published IF.data quarter may precede the COSIF month.
                quarter = report.get("ifdata_period")
                if quarter and quarter != period and data.DATA_BASE.astype(str).eq(quarter).any():
                    report["ifdata_validation"] = validate_candidate(data, sources, quarter, rules=rules, overrides=overrides)
                if any(report[key]["errors"] for key in ("validation", "ifdata_validation") if key in report):
                    raise ValueError("Conferência contábil reprovada; geração anterior preservada")
                for kind in SOURCES:
                    source = candidate.get_cache(kind)
                    if not source.existe_leitura():
                        continue
                    original = live.get_cache(kind)
                    if not original.existe_leitura() or not same_data(pd.read_parquet(original.arquivo_dados), pd.read_parquet(source.arquivo_dados)):
                        report["changed"].append(kind)
                if report.get("individual", {}).get("status") == "changed":
                    report["changed"].append(INDIVIDUAL)
                if recorded and "bloprudencial" not in report["changed"]:
                    report["changed"].append("bloprudencial")
                report["pending_review"] = pending_items(report["validation"]["review"], {item["id"] for item in all_decisions})
                if check_only:
                    report["status"] = "validated"
                elif report["pending_review"]:
                    report["status"] = "needs_review"
                elif not report["changed"]:
                    report["status"] = "unchanged"
                else:
                    progress("Recalculando as bases dependentes")
                    details = materialize_for_publication(LocalOnlySourcesManager(candidate), cache_names=[kind for kind in report["changed"] if kind != INDIVIDUAL], base_dir=workspace)
                    report["materialization"] = details
                    if any(item["status"] != "ok" for item in details):
                        raise ValueError("Materialização incompleta; geração anterior preservada")
                    names = report["changed"] + [item["cache"] for item in details]
                    progress("Gravando a nova geração")
                    if store:
                        artifacts = collect_official_artifacts(candidate, validate_quality=True)
                        revision = store.stage(artifacts, parent_revision=parent.revision_id if parent else None,
                                               metadata={"action": "financial_analysis", "run_id": run_id, "period": period})
                        store.activate(revision.revision_id, expected_parent=parent.revision_id if parent else None,
                                       actor={"subject": "financial-analysis"})
                        report["revision_id"] = revision.revision_id
                    else:
                        # O histórico individual é promovido como arquivo, sem passar por pandas.
                        if INDIVIDUAL in names:
                            source = candidate.get_cache(INDIVIDUAL)
                            adopt_file(live.get_cache(INDIVIDUAL), source.arquivo_dados, source.arquivo_metadata)
                        promote_legacy(live, candidate, [name for name in names if name != INDIVIDUAL])
                    report["promoted"] = list(dict.fromkeys(names))
                    report["status"] = "updated"
    except Exception as exc:
        report.update(status="failed", error=f"{type(exc).__name__}: {exc}")
    finally:
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        from .ifdata_web import get_web_source
        get_web_source.cache_clear()
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str, allow_nan=False) + "\n")
    return report, report_path


def activate_installed_sources(manager, names):
    """As travas de publicação olham o runtime; fontes só instaladas com o código entram nele sem mudar bytes."""
    from .release_ops import _publication_scope
    promised, sources = _publication_scope(names)
    for name in dict.fromkeys([*promised, *sources]):
        cache = manager.get_cache(name)
        if cache.existe() or not cache.existe_leitura():
            continue
        source = Path(cache.arquivo_dados)
        metadata = json.loads(cache.arquivo_metadata.read_text(encoding="utf-8"))
        metadata.pop("integridade", None)
        # A assinatura da cópia instalada é a dos seus próprios bytes.
        metadata["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
        result = cache.salvar_arquivo_local(source, metadata)
        if not result.sucesso:
            raise ValueError(f"{name}: {result.mensagem}")


def publish_update(root, report, token):
    """Envia a geração promovida à release; sem isso, ela se perde no próximo reboot da nuvem."""
    from . import CacheManager
    from .release_config import get_release_config
    from .release_ops import prepare_release_publication, upload_release_assets
    from .update_state import mutation_lock

    manager = CacheManager(Path(root))
    release = get_release_config()
    with mutation_lock(manager.base_dir, owner={"label": "publicação de bases"}):
        activate_installed_sources(manager, report["promoted"])
        _, manifest, published, assets = prepare_release_publication(
            manager, selected_caches=report["promoted"], release_config=release,
            expected_periods={"monthly": report["period"]},
            materialization_details=report.get("materialization"), token=token)
        upload_release_assets(repo=release.repo, tag=release.tag, assets=assets, token=token, base_dir=manager.base_dir,
                              expected_sha256={item["name"]: item["sha256"] for item in manifest["publication_assets"]})
    return {"repo": release.repo, "tag": release.tag, "caches": list(published)}


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
