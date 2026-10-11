from copy import deepcopy
from datetime import date, datetime

import pytest

from utils.ifdata_cache.durable_jobs import JobValidationError
from utils.ifdata_cache.update_app_bridge import (
    ExternalUpdateBridge, ExternalUpdateConfigurationError, build_external_spec,
    external_bridge_from_env, job_checkpoint_view, job_status_view,
)


def _job(cache="principal", status="running", created=100, run=None):
    return {"job_id": "a" * 32, "execution_run_id": "b" * 32, "status": status,
            "created_at": created, "updated_at": created + 1,
            "spec": {"cache_type": cache, "periods": ["202503", "202506"],
                     "mode": "overwrite", "options": {"batch_size": 1}},
            "run": run or {}, "result": {}, "error": None}


class FakeClient:
    def __init__(self, jobs=()):
        self.jobs = list(jobs)
        self.calls = []

    def list(self):
        return deepcopy(self.jobs)

    def submit(self, spec, key):
        self.calls.append(("submit", deepcopy(spec), key))
        return {"job_id": "submitted"}

    def retry(self, job_id):
        self.calls.append(("retry", job_id))
        return {"job_id": job_id, "status": "queued"}

    def cancel(self, job_id):
        self.calls.append(("cancel", job_id))
        return {"job_id": job_id, "status": "cancelled"}

    def publish(self, job_id):
        self.calls.append(("publish", job_id))
        return {"revision_id": job_id, "activated": True}


def test_bridge_is_disabled_by_default_and_incomplete_config_fails_closed():
    assert external_bridge_from_env({}) is None
    assert external_bridge_from_env({"GITHUB_TOKEN": "unrelated", "GH_TOKEN": "unrelated"}) is None
    for configuration in ({"TOMACONTA_UPDATE_API_URL": "https://service.test"},
                          {"TOMACONTA_UPDATE_API_TOKEN": "private"}):
        with pytest.raises(ExternalUpdateConfigurationError, match="URL e token"):
            external_bridge_from_env(configuration)


def test_factory_keeps_backend_token_outside_spec_and_checkpoint():
    calls = []
    client = FakeClient([_job(status="failed")])

    def factory(url, token, *, timeout):
        calls.append((url, token, timeout))
        return client

    bridge = external_bridge_from_env({"TOMACONTA_UPDATE_API_URL": "https://service.test",
                                       "TOMACONTA_UPDATE_API_TOKEN": "PRIVATE_BACKEND_TOKEN"}, client_factory=factory)
    bridge.submit("principal", ["202503"], "incremental", idempotency_key="stable-key")
    assert calls == [("https://service.test", "PRIVATE_BACKEND_TOKEN", 30)]
    assert "PRIVATE_BACKEND_TOKEN" not in repr(client.calls)
    assert "PRIVATE_BACKEND_TOKEN" not in repr(bridge.checkpoint("principal"))


def test_external_spec_normalizes_dates_and_retains_requested_options():
    options = {"start": date(2020, 1, 1), "end": datetime(2025, 6, 30, 15),
               "max_windows": 100, "reprocess_tail": 20}
    spec = build_external_spec("taxas_juros_historico", [], "rebuild", options, publish=True)
    assert spec["options"] == {"start": "2020-01-01", "end": "2025-06-30",
                               "max_windows": 100, "reprocess_tail": 20}
    assert isinstance(options["start"], date)
    assert spec["publish"] and spec["materialize"]
    with pytest.raises(JobValidationError):
        build_external_spec("principal", ["202503"], "incremental", {"token": "NEVER_SAVE"})


@pytest.mark.parametrize("cache_type,periods,options", [
    ("taxas_juros", [], {"start": date(2025, 1, 1)}),
    ("taxas_juros_historico", [], {"start": date(2025, 1, 1), "end": None}),
    ("mercado_credito_sgs", [], {"start": date(2025, 4, 1), "end": date(2025, 3, 31)}),
    ("cosif_4010", [], {}), ("bloprudencial", [], {}), ("scr_data", [], {}),
    ("principal", ["202503"], {"datasets": ["cartoes"]}),
])
def test_invalid_native_plan_is_rejected_before_any_api_call(cache_type, periods, options):
    client = FakeClient()
    with pytest.raises(JobValidationError):
        ExternalUpdateBridge(client).submit(cache_type, periods, "incremental", options,
                                            idempotency_key="bad-window")
    assert client.calls == []


def test_empty_spb_selection_is_a_fixed_complete_plan_in_the_api_request():
    from utils.ifdata_cache.spb_meios_pagamento import DATASETS

    client = FakeClient()
    ExternalUpdateBridge(client).submit("spb_meios_pagamento", [], "overwrite", {"datasets": []},
                                        idempotency_key="all-spb")
    assert client.calls[0][1]["options"]["datasets"] == [dataset.key for dataset in DATASETS]


def test_current_status_selects_the_requested_cache():
    pf = _job("carteira_pf", created=90, run={"status": "extracting", "current_period": "202506",
                                            "persisted_periods": ["202503"], "pending_periods": ["202506"]})
    principal = _job("principal", status="succeeded", created=100)
    bridge = ExternalUpdateBridge(FakeClient([pf, principal]))
    status = bridge.current_status("carteira_pf")
    assert status["cache_tipo"] == "carteira_pf"
    assert status["current"] == "extraindo 06/2025"
    assert status["progress"] == .5 and status["running"]
    assert bridge.current_status("principal")["current"] == "concluído"
    assert bridge.current_status("dre") == {}


def test_expired_worker_lease_shows_awaiting_recovery_without_claiming_completion():
    job = _job(run={"status": "extracting", "persisted_periods": ["202503"],
                   "pending_periods": ["202506"]})
    job["lease_expires_at"] = 105
    status = job_status_view(job, now=106)
    assert status["current"] == "aguardando retomada pelo executor"
    assert status["progress"] == .5 and status["running"]


@pytest.mark.parametrize("phase,current", [
    ("validating", "dados salvos; recalculando dependências"),
    ("publishing", "publicando pacote consistente"),
])
def test_completed_extraction_keeps_running_until_validation_and_publication_end(phase, current):
    job = _job(run={"status": phase, "persisted_periods": ["202503", "202506"], "pending_periods": []})
    status = job_status_view(job)
    assert status["running"] and status["progress"] == 1.0 and status["current"] == current


def test_retry_checkpoint_retains_frozen_plan_and_exact_pending_periods():
    job = _job(status="partial", run={"status": "partial", "persisted_periods": ["202503"],
                                      "pending_periods": ["202506"]})
    bridge = ExternalUpdateBridge(FakeClient([job]))
    checkpoint = bridge.checkpoint("principal")
    assert checkpoint["job_id"] == job["job_id"]
    assert checkpoint["periodos"] == ["202503", "202506"]
    assert checkpoint["concluidos"] == ["202503"] and checkpoint["pendentes"] == ["202506"]
    assert checkpoint["modo"] == "overwrite" and checkpoint["options"] == {"batch_size": 1}
    assert bridge.retry(job["job_id"])["status"] == "queued"
    assert bridge.client.calls == [("retry", job["job_id"])]


@pytest.mark.parametrize("job_error,receipt_error,expected", [
    ("Falha ao consultar 06/2025", None, "parcial: Falha ao consultar 06/2025"),
    (None, "Falha ao confirmar a gravação", "parcial: Falha ao confirmar a gravação"),
    (None, None, "parcial"),
])
def test_partial_status_explains_the_failure_and_preserves_confirmed_progress(job_error, receipt_error, expected):
    job = _job(status="partial", run={"status": "partial", "persisted_periods": ["202503"],
                                      "pending_periods": ["202506"], "error": receipt_error})
    job["error"] = job_error
    status = job_status_view(job)
    assert status["current"] == expected
    assert status["progress"] == .5 and not status["running"]
    assert job_checkpoint_view(job)["pendentes"] == ["202506"]


def test_failed_finalization_is_resumable_without_inventing_pending_extraction():
    job = _job(status="failed", run={"status": "publish_failed", "persisted_periods": ["202503", "202506"],
                                     "pending_periods": [], "error": "dependency failed"})
    checkpoint = job_checkpoint_view(job)
    assert checkpoint["job_id"] and checkpoint["pendentes"] == []
    assert checkpoint["concluidos"] == job["spec"]["periods"]
    assert job_status_view(job)["current"] == "erro: dependency failed"


def test_failed_confirmation_retries_full_original_plan():
    job = _job(status="failed", run={"status": "failed", "persisted_periods": ["202503", "202506"],
                                     "pending_periods": [], "error": "checkpoint failed"})
    assert job_checkpoint_view(job)["pendentes"] == job["spec"]["periods"]


def test_native_materialization_does_not_become_a_calendar_period():
    job = _job("taxas_juros_historico", status="failed", run={"status": "failed", "periods": ["materialization"],
              "persisted_periods": [], "pending_periods": ["materialization"]})
    job["spec"]["periods"] = []
    job["spec"]["options"] = {"start": "2020-01-01", "end": "2025-06-30"}
    checkpoint = job_checkpoint_view(job)
    assert checkpoint["periodos"] == checkpoint["pendentes"] == []
    assert checkpoint["job_id"] and checkpoint["options"]["end"] == "2025-06-30"


def test_publish_and_cancel_call_the_backend_without_starting_a_worker():
    client = FakeClient()
    bridge = ExternalUpdateBridge(client)
    assert bridge.publish("job")["activated"]
    assert bridge.cancel("queued")["status"] == "cancelled"
    assert client.calls == [("publish", "job"), ("cancel", "queued")]


def test_backend_errors_propagate_without_local_fallback():
    class FailedClient:
        def list(self):
            raise ConnectionError("backend unavailable")

    with pytest.raises(ConnectionError, match="backend unavailable"):
        ExternalUpdateBridge(FailedClient()).current_status("principal")
