"""Execução recuperável da atualização, independente das telas do Streamlit."""
from __future__ import annotations

from typing import Callable, Mapping
from contextlib import contextmanager

from .update_state import (
    UpdateRunStore, UpdateStateError, mutation_lock, write_cache_update_result,
)


def resumable_run(record: Mapping, cache_type: str) -> bool:
    return bool(record.get("run_id") and record.get("cache_type") == cache_type
                and record.get("status") in {"prepared", "extracting", "partial", "failed"})


def checkpoint_view(record: Mapping) -> dict:
    """Formato compatível com os controles atuais, derivado do comprovante."""
    if not record:
        return {}
    pending = list(record.get("pending_periods") or [])
    # Uma falha na confirmação final precisa refazer a confirmação dos dados.
    if not pending and record.get("status") == "failed":
        pending = list(record["periods"])
    return {
        "run_id": record["run_id"], "cache_tipo": record["cache_type"],
        "periodos": list(record["periods"]),
        "concluidos": list(record["persisted_periods"]), "pendentes": pending,
        "modo": record["mode"], "options": dict(record["options"]),
        "timestamp": record["updated_at"],
    }


def prepare_run(manager, cache_type, periods, mode, options, *, resume_id=None):
    store = UpdateRunStore(manager.base_dir)
    with mutation_lock(manager.base_dir, owner={"cache_type": cache_type}):
        if resume_id:
            record = store.load(resume_id)
            if not resumable_run(record, cache_type):
                raise UpdateStateError("A execução selecionada não pode ser retomada.")
            return store, record
        previous = store.latest(cache_type)
        if resumable_run(previous, cache_type):
            raise UpdateStateError("Há uma execução pendente deste cache. Use retomar ou reiniciar extração.")
        return store, store.create(cache_type, periods, mode, options)


def finalize_saved_run(manager, store, record, *, materialize=None, publish=None):
    """Retoma validação/publicação sem consultar novamente períodos confirmados.

    A fila externa pode perder o processo depois do último salvamento. O
    comprovante e a confirmação do cache permitem repetir somente a etapa final.
    """
    from .base import CacheResult
    from .release_ops import _assert_complete_update

    with mutation_lock(manager.base_dir, owner={"run_id": record["run_id"]}):
        current = store.load(record["run_id"])
        if current.get("status") not in {"saved", "validating", "publishing", "publish_failed", "published"}:
            raise UpdateStateError("A extração ainda precisa ser concluída.")
        _assert_complete_update(manager.base_dir, current["cache_type"])
        if current["status"] == "published":
            return CacheResult(True, "Publicação já confirmada"), current
        try:
            current = store.finish(current, "validating", error=None)
            details = materialize(current["cache_type"]) if materialize else []
            failures = [str(item.get("message") or item.get("cache"))
                        for item in details or [] if item.get("status") != "ok"]
            if failures:
                raise UpdateStateError("Dependências incompletas: " + "; ".join(failures))
            if publish:
                current = store.finish(current, "publishing", error=None)
                success, message, context = publish(current, details)
                current = store.finish(current, "published" if success else "publish_failed",
                                       error=None if success else message,
                                       publication={"success": bool(success), "message": str(message),
                                                    **dict(context or {})})
            else:
                current = store.finish(current, "saved", error=None)
            return CacheResult(current["status"] in {"saved", "published"}, current.get("error") or "Dados confirmados"), current
        except Exception as exc:
            current = store.finish(store.load(record["run_id"]), "publish_failed", error=str(exc))
            raise


def run_quarterly_update(
    manager, store: UpdateRunStore, record: dict, *,
    progress_callback: Callable | None = None,
    save_callback: Callable | None = None,
    error_callback: Callable | None = None,
    checkpoint_callback: Callable | None = None,
    materialize: Callable | None = None,
    publish: Callable | None = None,
    extraction_options: Mapping | None = None,
):
    """Executa um lote do plano original e avança apenas confirmações duráveis.

    A trava cobre extração, gravação, dependências e publicação. Credenciais
    ficam apenas nas closures do chamador, fora do comprovante da execução.
    """
    current = dict(record)
    with mutation_lock(manager.base_dir, owner={"run_id": current["run_id"], "cache_type": current["cache_type"]}):
        current = store.load(current["run_id"])
        if not resumable_run(current, current["cache_type"]):
            raise UpdateStateError("Execução já encerrada; recarregue o status.")
        try:
            pending = list(current["pending_periods"])
            repair_confirmation = not pending and current["status"] == "failed"
            if not pending and current["status"] == "failed":
                pending = list(current["periods"])
            if not pending:
                raise UpdateStateError("A execução não possui unidades a confirmar.")
            options = current["options"]
            batch_size = len(pending) if repair_confirmation else int(options.get("batch_size") or len(pending))
            batch = pending[:max(batch_size, 1)]
            current["status"] = "extracting"
            current["error"] = None
            current = store.save(current)

            def checkpoint(metadata):
                nonlocal current
                current = store.record_result(current, metadata)
                current["status"] = "extracting"
                current = store.save(current)
                if checkpoint_callback:
                    checkpoint_callback(checkpoint_view(current))

            def progress(index, total, period):
                nonlocal current
                current["current_period"] = str(period)
                current["batch_total"] = total
                current = store.save(current)
                if progress_callback:
                    progress_callback(index, total, period)

            result = manager.extrair_periodos_com_salvamento(
                tipo=current["cache_type"], periodos=batch, modo=current["mode"],
                execution_periods=current["periods"], run_id=current["run_id"],
                intervalo_salvamento=int(options.get("intervalo_save") or 1),
                callback_progresso=progress, callback_salvamento=save_callback,
                callback_erro=error_callback, callback_checkpoint=checkpoint,
                dict_aliases=None,
                **dict(extraction_options or {}),
            )
            current = store.record_result(current, result.metadata or {})
            current["message"] = str(result.mensagem)
            current = store.save(current)
            if not result.sucesso or current.get("error"):
                status = "partial" if current["persisted_periods"] and current["pending_periods"] else "failed"
                current = store.finish(current, status, error=current.get("error") or result.mensagem)
            elif current["pending_periods"]:
                current = store.finish(current, "partial")
            else:
                current = store.finish(current, "saved")
            if checkpoint_callback:
                checkpoint_callback(checkpoint_view(current))
            if current["status"] != "saved":
                return result, current

            if materialize:
                current["status"] = "validating"
                current = store.save(current)
                details = materialize(current["cache_type"])
            else:
                details = []
            materialization_errors = [str(item.get("message") or item.get("cache"))
                                      for item in (details or []) if item.get("status") != "ok"]
            if materialization_errors and publish is None:
                current = store.finish(current, "publish_failed", error="Dependências incompletas: " + "; ".join(materialization_errors))
                return result, current
            if publish:
                current["status"] = "publishing"
                current = store.save(current)
                success, message, context = publish(current, details)
                current = store.finish(current, "published" if success else "publish_failed",
                                       error=None if success else message,
                                       publication={"success": bool(success), "message": str(message),
                                                    "published_caches": context.get("published_caches", [])})
            else:
                current = store.finish(current, "saved")
            return result, current
        except Exception as exc:
            latest = store.load(current["run_id"]) or current
            status = "publish_failed" if latest.get("status") in {"validating", "publishing"} else "failed"
            store.finish(latest, status, error=str(exc))
            raise


@contextmanager
def adapter_update_session(manager, cache_type: str, *, mode="incremental", options=None):
    """Registra adaptações mensais/históricas com staging próprio como uma unidade.

    O adapter só confirma essa unidade quando sua gravação e finalização terminam.
    Janelas restantes, truncamento ou falhas impedem a publicação.
    """
    store = UpdateRunStore(manager.base_dir)
    with mutation_lock(manager.base_dir, owner={"cache_type": cache_type}):
        record = store.create(cache_type, ["materialization"], mode=mode, options=options)
        record["status"] = "extracting"
        record = store.save(record)

        confirmed = False

        def confirm(result=None, error=None):
            nonlocal confirmed
            metadata = dict(getattr(result, "metadata", None) or {})
            success = bool(getattr(result, "sucesso", False)) and error is None
            failures = any(metadata.get(key) for key in (
                "remaining_windows", "failures", "failed_windows", "falhas", "erros",
                "pending_periods", "failed_periods", "persistence_error", "checkpoint_error", "callback_error",
            ))
            complete = (success and metadata.get("finalized", True)
                        and not failures and not metadata.get("truncado"))
            summary = {
                "run_id": record["run_id"], "requested_periods": ["materialization"],
                "extracted_periods": ["materialization"] if success else [],
                "persisted_periods": ["materialization"] if complete else [],
                "pending_periods": [] if complete else ["materialization"],
                "failed_periods": {} if complete else {"materialization": str(error or getattr(result, "mensagem", "Incompleto"))},
                "status": "saved" if complete else "partial" if success else "failed",
            }
            write_cache_update_result(manager.base_dir, cache_type, summary)
            updated = store.record_result(record, summary)
            store.finish(updated, summary["status"], error=None if complete else str(error or getattr(result, "mensagem", "Incompleto")))
            confirmed = True

        try:
            write_cache_update_result(manager.base_dir, cache_type, {
                "run_id": record["run_id"], "requested_periods": ["materialization"],
                "extracted_periods": [], "persisted_periods": [],
                "pending_periods": ["materialization"], "failed_periods": {}, "status": "extracting",
            })
            yield confirm
            if not confirmed:
                confirm(error="A atualização terminou sem confirmar sua gravação.")
        except Exception as exc:
            if not confirmed:
                confirm(error=exc)
            raise


def run_adapter_update(manager, cache_type: str, operation: Callable, *, mode="incremental", options=None):
    with adapter_update_session(manager, cache_type, mode=mode, options=options) as confirm:
        result = operation()
        confirm(result)
        return result


def save_period_window(manager, cache_type, data, periods, *, fonte, info_extra=None):
    """Grava uma janela mensal preservando as competências fora da seleção."""
    import pandas as pd
    from .base import CacheResult
    with mutation_lock(manager.base_dir, owner={"cache_type": cache_type}):
        requested = {str(period) for period in periods}
        if not requested or data is None or data.empty or "Período" not in data:
            return CacheResult(sucesso=False, mensagem="Janela vazia ou sem competência; base anterior preservada.")
        if data["Período"].isna().any():
            return CacheResult(sucesso=False, mensagem="Competência inválida na extração; base anterior preservada.")
        extracted = set(data["Período"].astype(str))
        if extracted != requested:
            missing = sorted(requested - extracted)
            unexpected = sorted(extracted - requested)
            return CacheResult(sucesso=False, mensagem=(
                f"Cobertura da janela incompleta ou divergente: faltantes={missing}; "
                f"fora da seleção={unexpected}. Base anterior preservada."
            ))
        cache = manager.get_cache(cache_type)
        previous = cache.carregar_local()
        if previous.sucesso and previous.dados is not None:
            if "Período" not in previous.dados or "Período" not in data:
                return CacheResult(sucesso=False, mensagem="Chave de competência ausente; base anterior preservada.")
            old = previous.dados
            outside = old[~old["Período"].astype(str).isin([str(p) for p in periods])]
            data = pd.concat([outside, data], ignore_index=True)
        elif getattr(cache, "existe_leitura", cache.existe)():
            return CacheResult(sucesso=False, mensagem="Base anterior ilegível; atualização interrompida.")
        return manager.salvar(cache_type, data, fonte=fonte, info_extra=info_extra)


def extract_taxas_window(cache, start, end, **callbacks):
    """Preserva datas fora da janela consultada e só grava uma resposta completa."""
    import pandas as pd
    from .base import CacheResult

    with mutation_lock(cache.base_dir, owner={"cache_type": cache.config.nome}):
        result = cache.extrair_completo(data_inicio=start, data_fim=end, **callbacks)
        if not result.sucesso or (result.metadata or {}).get("truncado"):
            result.sucesso = False
            return result
        previous = cache.carregar_local()
        data = result.dados
        if previous.sucesso and previous.dados is not None:
            old = previous.dados
            column = "Início Período"
            if column not in old or column not in data:
                return CacheResult(sucesso=False, mensagem="Coluna temporal ausente; histórico anterior preservado.")
            dates = pd.to_datetime(old[column], errors="coerce")
            if dates.isna().any():
                return CacheResult(sucesso=False, mensagem="Datas antigas inválidas; histórico anterior preservado.")
            end_dates = pd.to_datetime(old["Fim Período"], errors="coerce") if "Fim Período" in old else dates
            if end_dates.isna().any():
                return CacheResult(sucesso=False, mensagem="Datas antigas inválidas; histórico anterior preservado.")
            covered = (dates >= pd.Timestamp(start)) & (end_dates <= pd.Timestamp(end))
            outside = old[~covered]
            data = pd.concat([outside, data], ignore_index=True)
        elif getattr(cache, "existe_leitura", cache.existe)():
            return CacheResult(sucesso=False, mensagem="Histórico anterior ilegível; atualização interrompida.")
        saved = cache.salvar_local(data, fonte="api", info_extra=result.metadata)
        if not saved.sucesso:
            return saved
        result.dados = data
        return result
