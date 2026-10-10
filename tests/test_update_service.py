from datetime import date
from pathlib import Path
from threading import Thread
from types import SimpleNamespace

import pandas as pd
import pytest

from utils.ifdata_cache.base import CacheResult
from utils.ifdata_cache.release_ops import _assert_complete_update
from utils.ifdata_cache.update_service import (
    adapter_update_session,
    checkpoint_view,
    extract_taxas_window,
    prepare_run,
    resumable_run,
    run_adapter_update,
    run_quarterly_update,
    save_period_window,
)
from utils.ifdata_cache.update_state import (
    UpdateBusyError,
    UpdateRunStore,
    UpdateStateError,
    load_cache_update_result,
    mutation_lock,
    write_cache_update_result,
)


class ScriptedManager:
    """Confirms units through the same durable ledger/checkpoint API as manager."""

    def __init__(self, root, outcomes=()):
        self.base_dir = Path(root)
        self.outcomes = list(outcomes)
        self.calls = []
        self.confirmed = {}

    def extrair_periodos_com_salvamento(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        units = kwargs["execution_periods"]
        batch = kwargs["periodos"]
        run_id = kwargs["run_id"]
        confirmed = self.confirmed.setdefault(run_id, set())
        confirmed.update(outcome.get("confirmed", batch if outcome.get("success", True) else []))
        pending = [p for p in units if p not in confirmed]
        failed = {p: "timeout" for p in outcome.get("failed", []) if p in pending}
        status = "partial" if pending else "saved"
        if outcome.get("checkpoint_error") or outcome.get("persistence_error"):
            status = "failed"
        metadata = {
            "run_id": run_id, "cache_type": kwargs["tipo"], "execution_periods": units,
            "requested_periods": units, "extracted_periods": outcome.get("extracted", batch),
            "persisted_periods": [p for p in units if p in confirmed],
            "pending_periods": pending, "failed_periods": failed, "status": status,
        }
        for key in ("checkpoint_error", "persistence_error"):
            if outcome.get(key):
                metadata[key] = outcome[key]
        for index, period in enumerate(batch, 1):
            kwargs["callback_progresso"](index, len(batch), period)
        write_cache_update_result(self.base_dir, kwargs["tipo"], metadata)
        if confirmed and not outcome.get("skip_checkpoint"):
            kwargs["callback_checkpoint"](metadata)
        if outcome.get("raise"):
            raise outcome["raise"]
        return CacheResult(sucesso=outcome.get("success", True), mensagem=outcome.get("message", "batch result"),
                           metadata=metadata)


def test_resume_retains_original_periods_mode_options_and_batch_size(tmp_path):
    manager = ScriptedManager(tmp_path, [{}, {}])
    options = {"batch_size": 1, "intervalo_save": 2, "meses": [3, 6]}
    store, record = prepare_run(manager, "principal", ["202603", "202606"], "overwrite", options)
    _, first = run_quarterly_update(manager, store, record)
    assert first["status"] == "partial"
    resumed_store, resumed = prepare_run(
        manager, "principal", ["202612"], "rebuild", {"batch_size": 9, "intervalo_save": 50},
        resume_id=record["run_id"],
    )
    assert resumed["periods"] == ["202603", "202606"]
    assert resumed["mode"] == "overwrite"
    assert resumed["options"] == options
    _, final = run_quarterly_update(manager, resumed_store, resumed)
    assert final["status"] == "saved"
    assert [call["periodos"] for call in manager.calls] == [["202603"], ["202606"]]
    assert all(call["execution_periods"] == ["202603", "202606"] for call in manager.calls)
    assert all(call["modo"] == "overwrite" and call["intervalo_salvamento"] == 2 for call in manager.calls)
    assert manager.calls[0]["run_id"] == manager.calls[1]["run_id"] == record["run_id"]


def test_new_run_rejects_pending_same_cache_and_accepts_independent_cache(tmp_path):
    manager = ScriptedManager(tmp_path)
    _, principal = prepare_run(manager, "principal", ["202603"], "incremental", {})
    with pytest.raises(UpdateStateError, match="execução pendente"):
        prepare_run(manager, "principal", ["202606"], "rebuild", {})
    _, capital = prepare_run(manager, "capital", ["202603"], "incremental", {})
    assert capital["run_id"] != principal["run_id"]
    assert checkpoint_view(capital)["concluidos"] == []
    assert checkpoint_view(principal)["cache_tipo"] == "principal"
    with pytest.raises(UpdateStateError, match="não pode ser retomada"):
        prepare_run(manager, "capital", [], "incremental", {}, resume_id=principal["run_id"])


def test_partial_checkpoints_confirm_only_persisted_units_and_never_publish(tmp_path):
    manager = ScriptedManager(tmp_path, [{"success": False, "confirmed": ["202603"],
                                         "extracted": ["202603", "202606"], "failed": ["202606"]}])
    store, run = prepare_run(manager, "principal", ["202603", "202606"], "incremental", {})
    checkpoints, materializations, publications = [], [], []
    _, final = run_quarterly_update(
        manager, store, run, checkpoint_callback=checkpoints.append,
        materialize=lambda name: materializations.append(name),
        publish=lambda current, details: publications.append(current),
    )
    assert final["status"] == "partial"
    assert final["persisted_periods"] == ["202603"]
    assert final["extracted_periods"] == ["202603", "202606"]
    assert final["pending_periods"] == ["202606"]
    assert final["failed_periods"] == {"202606": "timeout"}
    assert all(checkpoint["concluidos"] == ["202603"] for checkpoint in checkpoints)
    assert materializations == publications == []
    with pytest.raises(ValueError, match="incompleta"):
        _assert_complete_update(tmp_path, "principal")


def test_successful_batch_with_remaining_plan_does_not_materialize_or_publish(tmp_path):
    manager = ScriptedManager(tmp_path, [{}])
    store, record = prepare_run(manager, "principal", ["202603", "202606"], "incremental", {"batch_size": 1})
    invoked = []
    result, final = run_quarterly_update(
        manager, store, record, materialize=lambda _: invoked.append("materialize"),
        publish=lambda *_: invoked.append("publish"),
    )
    assert result.sucesso is True
    assert final["status"] == "partial"
    assert final["pending_periods"] == ["202606"]
    assert invoked == []


def test_completed_plan_materializes_then_publishes_inside_shared_lock(tmp_path):
    manager = ScriptedManager(tmp_path, [{}])
    store, run = prepare_run(manager, "principal", ["202603"], "incremental", {})
    order, contention = [], []

    def competitor():
        try:
            with mutation_lock(tmp_path):
                contention.append("entered")
        except UpdateBusyError:
            contention.append("blocked")

    def materialize(name):
        order.append(("materialize", name))
        thread = Thread(target=competitor)
        thread.start()
        thread.join(timeout=5)
        assert not thread.is_alive()
        return [{"cache": "derived_metrics", "status": "ok"}]

    def publish(current, details):
        order.append(("publish", current["status"]))
        assert current["pending_periods"] == []
        assert details == [{"cache": "derived_metrics", "status": "ok"}]
        _assert_complete_update(tmp_path, "principal")
        return True, "uploaded and verified", {"published_caches": ["principal", "derived_metrics"]}

    _, final = run_quarterly_update(manager, store, run, materialize=materialize, publish=publish)
    assert order == [("materialize", "principal"), ("publish", "publishing")]
    assert contention == ["blocked"]
    assert final["status"] == "published"
    assert final["publication"]["published_caches"] == ["principal", "derived_metrics"]


def test_service_refuses_another_session_lock_before_any_extraction(tmp_path):
    manager = ScriptedManager(tmp_path, [{}])
    store, run = prepare_run(manager, "principal", ["202603"], "incremental", {})
    observed = []

    def compete():
        try:
            run_quarterly_update(manager, store, run)
        except UpdateBusyError:
            observed.append("blocked")

    with mutation_lock(tmp_path):
        thread = Thread(target=compete)
        thread.start()
        thread.join(timeout=5)
        assert not thread.is_alive()
    assert observed == ["blocked"]
    assert manager.calls == []
    assert store.load(run["run_id"])["status"] == "prepared"


def test_exception_after_checkpoint_preserves_confirmed_progress_for_resume(tmp_path):
    manager = ScriptedManager(tmp_path, [{"confirmed": ["202603"], "raise": OSError("interrupted")}, {}])
    store, run = prepare_run(manager, "principal", ["202603", "202606"], "incremental", {})
    with pytest.raises(OSError, match="interrupted"):
        run_quarterly_update(manager, store, run)
    interrupted = store.load(run["run_id"])
    assert interrupted["status"] == "failed"
    assert interrupted["persisted_periods"] == ["202603"]
    assert interrupted["pending_periods"] == ["202606"]
    _, final = run_quarterly_update(manager, store, interrupted)
    assert manager.calls[1]["periodos"] == ["202606"]
    assert final["status"] == "saved"


def test_failed_receipt_with_empty_pending_reconfirms_original_plan(tmp_path):
    manager = ScriptedManager(tmp_path, [{}])
    store, run = prepare_run(manager, "principal", ["202603"], "incremental", {})
    failed = store.record_result(run, {"persisted_periods": ["202603"], "status": "failed",
                                       "checkpoint_error": "disk full"})
    assert failed["pending_periods"] == []
    assert checkpoint_view(failed)["pendentes"] == ["202603"]
    assert resumable_run(failed, "principal") is True
    _, final = run_quarterly_update(manager, store, failed)
    assert manager.calls[0]["periodos"] == ["202603"]
    assert final["status"] == "saved"
    assert final["error"] is None


def test_confirmation_error_does_not_publish_even_when_all_data_saved(tmp_path):
    manager = ScriptedManager(tmp_path, [{"checkpoint_error": "disk full"}])
    store, run = prepare_run(manager, "principal", ["202603"], "incremental", {})
    publications = []
    _, final = run_quarterly_update(manager, store, run, publish=lambda *_: publications.append("called"))
    assert final["persisted_periods"] == ["202603"]
    assert final["status"] == "failed"
    assert final["error"] == "disk full"
    assert publications == []


def test_publication_failure_keeps_saved_data_available_for_publish_retry(tmp_path):
    manager = ScriptedManager(tmp_path, [{}])
    store, run = prepare_run(manager, "principal", ["202603"], "incremental", {})
    _, final = run_quarterly_update(
        manager, store, run, publish=lambda *_: (False, "GitHub unavailable", {"published_caches": []}),
    )
    assert final["status"] == "publish_failed"
    assert final["pending_periods"] == []
    assert final["error"] == "GitHub unavailable"
    assert resumable_run(final, "principal") is False
    _assert_complete_update(tmp_path, "principal")


@pytest.mark.parametrize("metadata", [
    {"finalized": False}, {"remaining_windows": 2}, {"failures": ["window"]}, {"truncado": True},
    {"failed_windows": ["window"]}, {"falhas": ["window"]}, {"failed_periods": {"202603": "failed"}},
    {"pending_periods": ["202603"]}, {"persistence_error": "disk"}, {"checkpoint_error": "disk"},
])
def test_partial_adapter_metadata_blocks_publication(tmp_path, metadata):
    manager = SimpleNamespace(base_dir=tmp_path)
    result = CacheResult(sucesso=True, mensagem="adapter returned", metadata=metadata)
    run_adapter_update(manager, "mercado_credito_sgs", lambda: result)
    ledger = load_cache_update_result(tmp_path, "mercado_credito_sgs")
    assert ledger["status"] != "saved"
    assert ledger["pending_periods"] == ["materialization"]
    with pytest.raises(ValueError, match="incompleta"):
        _assert_complete_update(tmp_path, "mercado_credito_sgs")


def test_adapter_success_confirms_one_opaque_unit(tmp_path):
    manager = SimpleNamespace(base_dir=tmp_path)
    result = CacheResult(sucesso=True, mensagem="saved", metadata={"finalized": True, "remaining_windows": 0})
    returned = run_adapter_update(manager, "spb_meios_pagamento", lambda: result)
    assert returned is result
    ledger = load_cache_update_result(tmp_path, "spb_meios_pagamento")
    assert ledger["status"] == "saved"
    assert ledger["persisted_periods"] == ["materialization"]
    _assert_complete_update(tmp_path, "spb_meios_pagamento")


def test_adapter_missing_confirmation_and_exception_remain_failed(tmp_path):
    manager = SimpleNamespace(base_dir=tmp_path)
    with adapter_update_session(manager, "mercado_credito_sgs"):
        pass
    assert load_cache_update_result(tmp_path, "mercado_credito_sgs")["status"] == "failed"
    with pytest.raises(OSError, match="source unavailable"):
        run_adapter_update(manager, "spb_meios_pagamento", lambda: (_ for _ in ()).throw(OSError("source unavailable")))
    assert load_cache_update_result(tmp_path, "spb_meios_pagamento")["pending_periods"] == ["materialization"]


class WindowCache:
    def __init__(self, root, previous, extracted=None, *, exists=True, saved_success=True):
        self.base_dir = root
        self.config = SimpleNamespace(nome="taxas_juros")
        self.previous = previous
        self.extracted = extracted
        self.exists = exists
        self.saved_success = saved_success
        self.saved = []

    def carregar_local(self):
        return self.previous

    def existe(self):
        return self.exists

    def extrair_completo(self, **kwargs):
        return self.extracted

    def salvar_local(self, data, **kwargs):
        self.saved.append((data.copy(), kwargs))
        return CacheResult(sucesso=self.saved_success, mensagem="saved" if self.saved_success else "disk error")


def test_taxas_window_preserves_dates_outside_selection_and_replaces_inside(tmp_path):
    old = pd.DataFrame({"Início Período": pd.to_datetime(["2026-01-05", "2026-02-02", "2026-03-02"]),
                        "Taxa": [1.0, 2.0, 3.0]})
    new = pd.DataFrame({"Início Período": pd.to_datetime(["2026-02-02", "2026-02-09"]), "Taxa": [20.0, 21.0]})
    cache = WindowCache(tmp_path, CacheResult(sucesso=True, mensagem="ok", dados=old),
                        CacheResult(sucesso=True, mensagem="ok", dados=new, metadata={"truncado": False}))
    result = extract_taxas_window(cache, date(2026, 2, 1), date(2026, 2, 28))
    data = result.dados.sort_values("Início Período").reset_index(drop=True)
    assert data["Taxa"].tolist() == [1.0, 20.0, 21.0, 3.0]
    assert len(cache.saved) == 1
    assert cache.saved[0][1]["info_extra"] == {"truncado": False}


@pytest.mark.parametrize("source_success,truncated", [(False, False), (True, True)])
def test_incomplete_taxas_response_never_overwrites_history(tmp_path, source_success, truncated):
    old = pd.DataFrame({"Início Período": ["2026-01-05"], "Taxa": [1.0]})
    cache = WindowCache(tmp_path, CacheResult(sucesso=True, mensagem="ok", dados=old),
                        CacheResult(sucesso=source_success, mensagem="source result", dados=old, metadata={"truncado": truncated}))
    result = extract_taxas_window(cache, date(2026, 2, 1), date(2026, 2, 28))
    assert result is cache.extracted
    assert cache.saved == []


def test_taxas_invalid_existing_dates_keep_history_untouched(tmp_path):
    old = pd.DataFrame({"Início Período": ["invalid date"], "Taxa": [1.0]})
    new = pd.DataFrame({"Início Período": ["2026-02-02"], "Taxa": [2.0]})
    cache = WindowCache(tmp_path, CacheResult(sucesso=True, mensagem="ok", dados=old), CacheResult(sucesso=True, mensagem="ok", dados=new))
    result = extract_taxas_window(cache, date(2026, 2, 1), date(2026, 2, 28))
    assert result.sucesso is False
    assert "Datas antigas inválidas" in result.mensagem
    assert cache.saved == []


def test_period_window_preserves_unselected_competences(tmp_path):
    old = pd.DataFrame({"Período": ["202601", "202602", "202603"], "Valor": [1, 2, 3]})
    new = pd.DataFrame({"Período": ["202602"], "Valor": [20]})
    cache = WindowCache(tmp_path, CacheResult(sucesso=True, mensagem="ok", dados=old))
    manager = SimpleNamespace(base_dir=tmp_path, get_cache=lambda _: cache,
                              salvar=lambda name, data, **kwargs: cache.salvar_local(data, **kwargs))
    result = save_period_window(manager, "bloprudencial", new, ["202602"], fonte="api")
    assert result.sucesso is True
    assert cache.saved[0][0].sort_values("Período")["Valor"].tolist() == [1, 20, 3]
