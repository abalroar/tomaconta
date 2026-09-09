"""Small, testable execution helpers for Atualizar Base, without Streamlit imports."""
from __future__ import annotations

from typing import Any, Callable, Mapping

from utils.ifdata_cache.update_state import UpdateRunStore, mutation_lock

from utils.ifdata_cache.update_catalog import QUARTERLY_CACHES, publication_status

STATUS_LABELS = {
    "prepared": "Preparada", "extracting": "Extraindo", "partial": "Parcial",
    "failed": "Falhou", "saved": "Salva localmente", "validating": "Validando dependências",
    "ready_to_publish": "Pronta para publicar", "publishing": "Publicando",
    "publish_failed": "Dados preparados; publicação falhou", "published": "Publicação concluída",
}


def resumable_run(record: Mapping[str, Any], cache_type: str) -> bool:
    return bool(
        record.get("run_id") and record.get("cache_type") == cache_type
        and record.get("pending_periods")
        and record.get("status") in {"prepared", "partial", "failed", "extracting"}
        and cache_type in QUARTERLY_CACHES
    )


def execution_options(record: Mapping[str, Any]) -> dict:
    """Only the frozen plan determines a resumed execution."""
    return {
        "cache_type": record["cache_type"],
        "periods": list(record.get("periods") or []),
        "mode": record["mode"],
        "options": dict(record.get("options") or {}),
    }


def invalid_date_range(start, end) -> bool:
    return start is None or end is None or start > end


def remote_status(local: Mapping, remote: Mapping) -> str:
    return publication_status(local, remote)


def run_quarterly_update(
    manager, store: UpdateRunStore, record: dict, *,
    progress_callback: Callable | None = None,
    save_callback: Callable | None = None,
    error_callback: Callable | None = None,
    materialize: Callable | None = None,
    publish: Callable | None = None,
):
    """Execute one saved batch; only confirmed writes advance the checkpoint.

    Callbacks receive no credentials. Publication closures may hold a token in
    memory; it must never be copied into the record or options.
    """
    current = dict(record)
    with mutation_lock(manager.base_dir, owner={"run_id": current["run_id"], "cache_type": current["cache_type"]}):
        try:
            current = store.load(current["run_id"])
            pending = list(current.get("pending_periods") or [])
            if not pending:
                return None, current
            options = current.get("options") or {}
            batch_size = int(options.get("batch_size") or len(pending))
            batch = pending[:max(batch_size, 1)]
            mode = current["mode"]
            # A full rebuild clears the prior generation once, before its first
            # successful batch. Subsequent batches merge their confirmed data.
            if mode == "rebuild" and current.get("persisted_periods"):
                mode = "incremental"
            current["status"] = "extracting"
            current = store.save(current)

            def checkpoint(metadata):
                nonlocal current
                current = store.record_result(current, metadata)
                current["status"] = "extracting"
                current = store.save(current)

            def progress(index, total, period):
                nonlocal current
                current["current_period"] = str(period)
                current["batch_total"] = total
                current = store.save(current)
                if progress_callback:
                    progress_callback(index, total, period)

            result = manager.extrair_periodos_com_salvamento(
                tipo=current["cache_type"], periodos=batch, modo=mode,
                execution_periods=current["periods"],
                intervalo_salvamento=int(options.get("intervalo_save") or 1),
                callback_progresso=progress, callback_salvamento=save_callback,
                callback_erro=error_callback, callback_checkpoint=checkpoint,
                dict_aliases=None,
            )
            current = store.record_result(current, result.metadata or {})
            current["message"] = str(result.mensagem)
            current = store.save(current)
            if current.get("pending_periods"):
                status = "partial" if current.get("persisted_periods") else "failed"
                return result, store.finish(current, status, error=None if result.sucesso else result.mensagem)
            if not result.sucesso or current.get("error"):
                return result, store.finish(current, "failed", error=current.get("error") or result.mensagem)
            if publish is None:
                return result, store.finish(current, "saved")
            current["status"] = "validating"
            current = store.save(current)
            details = materialize(current["cache_type"]) if materialize else []
            current["status"] = "publishing"
            current = store.save(current)
            success, message, context = publish(current, details)
            publication = {"success": bool(success), "message": message,
                           "published_caches": context.get("published_caches", [])}
            current = store.finish(current, "published" if success else "publish_failed", publication=publication)
            return result, current
        except Exception as exc:
            latest = store.load(current["run_id"]) or current
            status = "publish_failed" if latest.get("status") in {"validating", "publishing"} else "failed"
            store.finish(latest, status, error=str(exc))
            raise


def record_adapter_result(store: UpdateRunStore, record: dict, result, *, finalized=True) -> dict:
    """Adapters keep their own staging; this is a durable UI receipt."""
    metadata = dict(getattr(result, "metadata", None) or {})
    success = bool(getattr(result, "sucesso", False))
    status = "saved" if success and finalized else "partial" if success else "failed"
    record["message"] = str(getattr(result, "mensagem", ""))
    # Keep compact diagnostics and never persist source responses or raw data.
    record["summary"] = {key: metadata[key] for key in (
        "remaining_windows", "processed_this_run", "total_registros", "total_periodos", "series", "finalized"
    ) if key in metadata}
    record = store.save(record)
    return store.finish(record, status, error=None if success else record["message"])


def fetch_remote_cache_status(destinations, request_get) -> dict:
    """Read each effective release once; HTTP errors remain unknown, never absent."""
    result = {"caches": {}, "releases": {}, "release_existe": True, "manifesto": {"existe": False}}
    groups = {}
    for name, repo, tag, stem in destinations:
        groups.setdefault((repo, tag), []).append((name, stem))
    for (repo, tag), names in groups.items():
        release = {"repo": repo, "tag": tag, "manifest": {}, "assets": []}
        try:
            response = request_get(f"https://api.github.com/repos/{repo}/releases/tags/{tag}", timeout=10)
            if response.status_code != 200:
                raise RuntimeError(f"Consulta do release retornou HTTP {response.status_code}")
            payload = response.json()
            assets = payload.get("assets", [])
            release["assets"] = assets
            manifest_asset = next((item for item in assets if item.get("name") == "manifest.json"), None)
            if manifest_asset and manifest_asset.get("browser_download_url"):
                manifest_response = request_get(manifest_asset["browser_download_url"], timeout=10)
                if manifest_response.status_code == 200:
                    release["manifest"] = manifest_response.json()
                    result["manifesto"]["existe"] = True
            for name, stem in names:
                data_assets = [item for item in assets if str(item.get("name", "")).startswith(f"{stem}_")
                               and str(item.get("name", "")).endswith((".parquet", ".pkl", ".csv", ".zip"))
                               and not any(len(other_stem) > len(stem) and str(item.get("name", "")).startswith(f"{other_stem}_")
                                           for _, other_stem in names)]
                entry = (release["manifest"].get("caches") or {}).get(name) or {}
                size = sum(int(item.get("size") or 0) for item in data_assets)
                result["caches"][name] = {
                    "existe": bool(data_assets), "sha256": entry.get("sha256"),
                    "tamanho": size, "tamanho_fmt": f"{size / 1024 / 1024:.1f} MB",
                    "repo": repo, "tag": tag,
                }
        except Exception as exc:
            result["release_existe"] = False
            release["error"] = str(exc)
            for name, _ in names:
                result["caches"][name] = {"existe": False, "verification_error": str(exc), "repo": repo, "tag": tag}
        result["releases"][f"{repo}@{tag}"] = release
    result["erro"] = "; ".join(r["error"] for r in result["releases"].values() if r.get("error"))
    return result
