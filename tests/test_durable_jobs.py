from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import time

import pytest

from utils.ifdata_cache.durable_jobs import (
    DurableJobQueue, JobLeaseError, JobStateError, JobValidationError, run_worker,
)
from utils.ifdata_cache.update_state import UpdateRunStore, UpdateStateError, mutation_lock


PLAN = {"cache_type": "principal", "periods": ["202503", "202506"], "mode": "overwrite",
        "options": {"batch_size": 1}, "publish": False}


def _submit(queue, *, key="request-1", subject="analyst-1", spec=None):
    return queue.submit(spec or PLAN, subject, key)


def test_idempotency_is_scoped_to_subject_and_frozen_spec(tmp_path):
    queue = DurableJobQueue(tmp_path)
    job = _submit(queue)
    assert _submit(queue) == job
    assert _submit(queue, subject="analyst-2")["job_id"] != job["job_id"]
    with pytest.raises(JobStateError, match="outro plano"):
        _submit(queue, spec={**PLAN, "mode": "rebuild"})
    PLAN_COPY = {**PLAN, "periods": list(PLAN["periods"]), "options": dict(PLAN["options"])}
    second = _submit(queue, key="request-2", spec=PLAN_COPY)
    PLAN_COPY["periods"].append("202509")
    assert queue.get(second["job_id"])["spec"]["periods"] == PLAN["periods"]
    reopened = DurableJobQueue(tmp_path)
    assert reopened.get(job["job_id"]) == job
    assert {item["subject"] for item in reopened.list(subject="analyst-1")} == {"analyst-1"}
    assert "claim_token" not in reopened.get(job["job_id"])


@pytest.mark.parametrize("change", [
    {"cache_type": "critical_screens"}, {"cache_type": []}, {"mode": "completo"}, {"mode": []},
    {"periods": ["202504"]}, {"periods": ["202513"]}, {"periods": ["202503", "202503"]},
    {"periods": []}, {"publish": "true"}, {"command": "arbitrary-shell"},
    {"options": {"token": "NEVER_SAVE_THIS"}}, {"options": {"batch_size": True}},
    {"options": {"batch_size": 1001}}, {"options": {"start": "2025-02-30"}},
    {"options": {"start": "2025-04-01", "end": "2025-03-01"}},
    {"options": {"force_refresh": "yes"}}, {"options": {"years": [2025, "2026"]}},
    {"options": {"datasets": ["../escape"]}},
])
def test_invalid_plan_never_enters_durable_queue(tmp_path, change):
    queue = DurableJobQueue(tmp_path)
    with pytest.raises(JobValidationError):
        _submit(queue, spec={**PLAN, **change})
    assert queue.list() == []
    assert b"NEVER_SAVE_THIS" not in queue.path.read_bytes()


@pytest.mark.parametrize("cache_type,options,periods", [
    ("taxas_juros_historico", {"start": "2020-01-01", "end": "2025-03-31", "max_windows": 10000}, []),
    ("taxas_juros", {"start": "2025-01-01", "end": "2025-03-31"}, []),
    ("mercado_credito_sgs", {"start": "2025-01-01", "end": "2025-03-31"}, []),
    ("spb_meios_pagamento", {"datasets": ["cartoes", "intercambio"]}, []),
    ("scr_data", {"years": [2024, 2025]}, []),
    ("cosif_4010", {}, ["202501", "202502"]),
    ("bloprudencial", {}, ["202501"]),
])
def test_special_adapter_plan_is_persisted_without_credentials(tmp_path, cache_type, options, periods):
    job = _submit(DurableJobQueue(tmp_path), spec={"cache_type": cache_type, "periods": periods,
                                               "mode": "rebuild", "options": options})
    assert job["spec"]["options"] == options
    assert job["spec"]["periods"] == periods
    assert job["execution_run_id"] and job["execution_run_id"] != job["job_id"]


@pytest.mark.parametrize("cache_type", ["taxas_juros", "taxas_juros_historico", "mercado_credito_sgs"])
@pytest.mark.parametrize("options", [
    {}, {"start": "2025-01-01"}, {"end": "2025-03-31"},
    {"start": None, "end": "2025-03-31"}, {"start": "2025-01-01", "end": None},
    {"start": "2025-02-30", "end": "2025-03-31"},
    {"start": "2025-04-01", "end": "2025-03-31"},
])
def test_date_source_requires_a_valid_frozen_window_before_submission(tmp_path, cache_type, options):
    queue = DurableJobQueue(tmp_path)
    with pytest.raises(JobValidationError):
        queue.submit({"cache_type": cache_type, "periods": [], "options": options}, "analyst", "invalid-window")
    assert queue.list() == []


@pytest.mark.parametrize("cache_type,periods,options", [
    ("cosif_4010", [], {}), ("bloprudencial", [], {}), ("scr_data", [], {}),
    ("scr_data", [], {"years": []}),
    ("cosif_4010", ["202501"], {"batch_size": 1}),
    ("principal", ["202503"], {"start": "2025-01-01", "end": "2025-03-31"}),
    ("taxas_juros", [], {"start": "2025-01-01", "end": "2025-03-31", "max_windows": 10}),
    ("spb_meios_pagamento", [], {"datasets": ["unknown_dataset"]}),
    ("spb_meios_pagamento", [], {"datasets": ["cartoes", "cartoes"]}),
    ("spb_meios_pagamento", [], {"force_refresh": True}),
    ("scr_data", [], {"years": [2025], "meses_recentes": 12}),
    ("scr_data", ["202503"], {"years": [2025]}),
])
def test_source_specific_scope_rejects_missing_units_and_ignored_options(tmp_path, cache_type, periods, options):
    queue = DurableJobQueue(tmp_path)
    with pytest.raises(JobValidationError):
        queue.submit({"cache_type": cache_type, "periods": periods, "options": options}, "analyst", "invalid-source-plan")
    assert queue.list() == []


def test_empty_spb_selection_freezes_all_official_datasets_and_is_idempotent(tmp_path):
    from utils.ifdata_cache.spb_meios_pagamento import DATASETS

    queue = DurableJobQueue(tmp_path)
    spec = {"cache_type": "spb_meios_pagamento", "options": {"datasets": []}}
    first = queue.submit(spec, "analyst", "all-spb")
    assert first["spec"]["options"]["datasets"] == [dataset.key for dataset in DATASETS]
    assert len(first["spec"]["options"]["datasets"]) == 12
    assert spec["options"]["datasets"] == []
    assert queue.submit({"cache_type": "spb_meios_pagamento"}, "analyst", "all-spb") == first
    assert queue.submit({"cache_type": "spb_meios_pagamento", "options": {"datasets": None}},
                        "analyst", "all-spb") == first


def test_expired_claim_is_fenced_and_context_survives_reclaim(tmp_path):
    now = [100.0]
    queue = DurableJobQueue(tmp_path, lease_seconds=10, clock=lambda: now[0])
    submitted = _submit(queue)
    first = queue.claim("worker-1")
    assert queue.claim("worker-2") is None
    queue.update_context(first["job_id"], "worker-1", first["claim_token"],
                         {"expected_parent": None, "revision_id": first["job_id"]})
    now[0] = 105
    assert queue.heartbeat(first["job_id"], "worker-1", first["claim_token"])
    now[0] = 111
    assert queue.claim("worker-2") is None
    now[0] = 116
    second = queue.claim("worker-2")
    assert second["job_id"] == submitted["job_id"]
    assert second["execution_run_id"] == first["execution_run_id"]
    assert second["claim_token"] != first["claim_token"]
    assert second["context"] == {"expected_parent": None, "revision_id": first["job_id"]}
    assert second["attempts"] == 2
    assert not queue.heartbeat(first["job_id"], "worker-1", first["claim_token"])
    with pytest.raises(JobLeaseError):
        queue.finish(first["job_id"], "worker-1", first["claim_token"], "succeeded")
    with pytest.raises(JobLeaseError):
        queue.update_context(first["job_id"], "worker-1", first["claim_token"], {"expected_parent": "stale"})
    finished = queue.finish(second["job_id"], "worker-2", second["claim_token"], "succeeded", result={"rows": 2})
    assert finished["status"] == "succeeded"
    assert finished["result"] == {"rows": 2}
    assert "claim_token" not in finished


@pytest.mark.parametrize("operation", ["heartbeat", "context", "finish", "retry"])
def test_lease_is_checked_after_the_sqlite_write_transaction_is_acquired(tmp_path, monkeypatch, operation):
    now = [100.0]
    queue = DurableJobQueue(tmp_path, lease_seconds=10, clock=lambda: now[0])
    _submit(queue)
    claim = queue.claim("worker")
    assert claim["lease_expires_at"] == 110
    original_transaction = queue._transaction

    @contextmanager
    def acquired_after_expiry():
        with original_transaction() as database:
            # Simulates time elapsed waiting for another SQLite writer.
            now[0] = 120.0
            yield database

    monkeypatch.setattr(queue, "_transaction", acquired_after_expiry)
    args = (claim["job_id"], "worker", claim["claim_token"])
    if operation == "heartbeat":
        assert queue.heartbeat(*args) is False
    elif operation == "retry":
        assert queue.retry(claim["job_id"])["status"] == "queued"
        assert queue.get(claim["job_id"])["execution_run_id"] == claim["execution_run_id"]
        return
    else:
        with pytest.raises(JobLeaseError):
            if operation == "context":
                queue.update_context(*args, {"parent_revision": "expired-claim"})
            else:
                queue.finish(*args, "succeeded", result={"rows": 1})
    preserved = queue.get(claim["job_id"])
    assert preserved["status"] == "running" and preserved["lease_expires_at"] == 110
    assert preserved["context"] == {} and preserved["result"] is None


def test_claim_lease_starts_when_the_sqlite_write_transaction_is_acquired(tmp_path, monkeypatch):
    now = [100.0]
    queue = DurableJobQueue(tmp_path, lease_seconds=10, clock=lambda: now[0])
    _submit(queue)
    original_transaction = queue._transaction

    @contextmanager
    def acquired_later():
        with original_transaction() as database:
            now[0] = 120.0
            yield database

    monkeypatch.setattr(queue, "_transaction", acquired_later)
    claim = queue.claim("worker")
    assert claim["heartbeat_at"] == 120 and claim["lease_expires_at"] == 130
    queue.ensure_claim(claim["job_id"], "worker", claim["claim_token"])


def test_serial_worker_waits_for_interrupted_job_and_resumes_it_before_a_newer_job(tmp_path):
    now = [100.0]
    queue = DurableJobQueue(tmp_path, lease_seconds=10, clock=lambda: now[0])
    first = _submit(queue, key="interrupted")
    abandoned = queue.claim("interrupted-worker")
    store = UpdateRunStore(tmp_path)
    receipt = store.create(PLAN["cache_type"], PLAN["periods"], PLAN["mode"], PLAN["options"],
                           run_id=first["execution_run_id"])
    store.record_result(receipt, {"persisted_periods": ["202503"]})
    queue.update_context(first["job_id"], "interrupted-worker", abandoned["claim_token"],
                         {"parent_revision": "original-parent"})
    now[0] = 101
    newer = _submit(queue, key="later-intention")
    called = []

    def resume(job):
        called.append(job["job_id"])
        assert job["job_id"] == first["job_id"]
        assert job["context"] == {"parent_revision": "original-parent"}
        resumed = store.load(job["execution_run_id"])
        assert resumed["persisted_periods"] == ["202503"]
        assert resumed["pending_periods"] == ["202506"]
        store.record_result(resumed, {"persisted_periods": resumed["pending_periods"]})
        return {"status": "succeeded", "result": {"run_id": job["execution_run_id"]}}

    now[0] = 105
    assert run_worker(queue, resume, worker_id="replacement", once=True) is None
    assert called == []
    assert queue.get(newer["job_id"])["status"] == "queued"
    assert queue.get(newer["job_id"])["attempts"] == 0
    now[0] = 110
    finished = run_worker(queue, resume, worker_id="replacement", once=True)
    assert finished["job_id"] == first["job_id"] and finished["attempts"] == 2
    assert called == [first["job_id"]]
    assert queue.get(newer["job_id"])["status"] == "queued"
    next_job = run_worker(queue, lambda job: {"status": "succeeded"}, worker_id="replacement", once=True)
    assert next_job["job_id"] == newer["job_id"] and next_job["attempts"] == 1


def test_generic_claim_keeps_parallel_claim_behavior_by_default(tmp_path):
    queue = DurableJobQueue(tmp_path, clock=lambda: 100)
    first = _submit(queue, key="first")
    second = _submit(queue, key="second")
    assert queue.claim("worker-1")["job_id"] == first["job_id"]
    assert queue.claim("worker-2")["job_id"] == second["job_id"]


def test_retry_and_cancel_preserve_plan_run_and_owner_scope(tmp_path):
    queue = DurableJobQueue(tmp_path)
    job = _submit(queue)
    with pytest.raises(JobStateError):
        queue.cancel(job["job_id"], subject="other-analyst")
    cancelled = queue.cancel(job["job_id"], subject="analyst-1")
    assert cancelled["status"] == "cancelled"
    retried = queue.retry(job["job_id"], subject="analyst-1")
    assert retried["spec"] == job["spec"]
    assert retried["execution_run_id"] == job["execution_run_id"]
    running = queue.claim("worker")
    with pytest.raises(JobStateError):
        queue.cancel(job["job_id"])
    with pytest.raises(JobStateError):
        queue.retry(job["job_id"])
    queue.finish(job["job_id"], "worker", running["claim_token"], "partial", result={"remaining": 1})
    assert queue.retry(job["job_id"])["status"] == "queued"
    assert queue.get(job["job_id"])["execution_run_id"] == job["execution_run_id"]


def test_context_and_result_reject_secret_fields_before_writing(tmp_path):
    queue = DurableJobQueue(tmp_path)
    _submit(queue)
    job = queue.claim("worker")
    with pytest.raises(JobValidationError):
        queue.update_context(job["job_id"], "worker", job["claim_token"], {"token": "NO_CONTEXT_SECRET"})
    with pytest.raises(JobValidationError):
        queue.finish(job["job_id"], "worker", job["claim_token"], "succeeded", result={"password": "NO_RESULT_SECRET"})
    assert queue.get(job["job_id"])["status"] == "running"
    for file in queue.path.parent.glob("update_jobs.sqlite3*"):
        content = file.read_bytes()
        assert b"NO_CONTEXT_SECRET" not in content and b"NO_RESULT_SECRET" not in content


def test_preallocated_run_creation_is_idempotent_and_preserves_checkpoint(tmp_path):
    queue = DurableJobQueue(tmp_path)
    job = _submit(queue)
    store = UpdateRunStore(tmp_path)
    spec = job["spec"]
    first = store.create(spec["cache_type"], spec["periods"], spec["mode"], spec["options"],
                         run_id=job["execution_run_id"])
    partial = store.record_result(first, {"persisted_periods": ["202503"]})
    reopened = UpdateRunStore(tmp_path)
    again = reopened.create(spec["cache_type"], spec["periods"], spec["mode"], spec["options"],
                            run_id=job["execution_run_id"])
    assert again == partial
    with pytest.raises(UpdateStateError, match="outro plano"):
        store.create(spec["cache_type"], spec["periods"], "rebuild", spec["options"], run_id=job["execution_run_id"])
    with pytest.raises(UpdateStateError, match="Identificador"):
        store.create("principal", [], run_id="../escape")


def test_worker_lock_precedes_claim_and_covers_executor(tmp_path):
    queue = DurableJobQueue(tmp_path)
    _submit(queue)
    observed = []

    def executor(job):
        observed.append(queue.get(job["job_id"])["status"])
        # Other threads cannot mutate while this external worker owns the lock.
        def concurrent():
            try:
                with mutation_lock(tmp_path):
                    observed.append("unsafe")
            except Exception:
                observed.append("locked")
        other = threading.Thread(target=concurrent)
        other.start()
        other.join(timeout=2)
        return {"status": "succeeded", "result": {"run_id": job["execution_run_id"]}}

    finished = run_worker(queue, executor, worker_id="worker", once=True)
    assert finished["status"] == "succeeded"
    assert observed == ["running", "locked"]
    assert run_worker(queue, executor, worker_id="worker", once=True) is None


def test_worker_failure_is_durable_and_retry_keeps_same_receipt(tmp_path):
    queue = DurableJobQueue(tmp_path)
    original = _submit(queue)

    def fail(job):
        raise RuntimeError("source unavailable")

    failed = run_worker(queue, fail, worker_id="worker", once=True)
    assert failed["status"] == "failed"
    assert failed["error"] == "source unavailable"
    queue.retry(original["job_id"])
    success = run_worker(queue, lambda job: {"status": "succeeded", "result": {"run_id": job["execution_run_id"]}},
                         worker_id="worker", once=True)
    assert success["execution_run_id"] == original["execution_run_id"]
    assert success["attempts"] == 2


_BOOTSTRAP = """
import json, pathlib, sys, types
root = pathlib.Path(sys.argv[1])
for name, directory in [('utils', root / 'utils'), ('utils.ifdata_cache', root / 'utils/ifdata_cache')]:
    module = types.ModuleType(name)
    module.__path__ = [str(directory)]
    sys.modules[name] = module
from utils.ifdata_cache.durable_jobs import DurableJobQueue, run_worker
from utils.ifdata_cache.update_state import UpdateRunStore
"""


def test_two_processes_cannot_claim_the_same_live_job(tmp_path):
    queue = DurableJobQueue(tmp_path)
    job = _submit(queue)
    code = _BOOTSTRAP + """
queue = DurableJobQueue(sys.argv[2])
print('ready', flush=True)
sys.stdin.readline()
claimed = queue.claim(sys.argv[3])
print(json.dumps(claimed['job_id'] if claimed else None), flush=True)
"""
    root = Path(__file__).resolve().parents[1]
    workers = [subprocess.Popen([sys.executable, "-c", code, str(root), str(tmp_path), f"worker-{index}"],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
               for index in range(2)]
    try:
        for worker in workers:
            assert worker.stdout.readline().strip() == "ready"
        for worker in workers:
            worker.stdin.write("claim\n")
            worker.stdin.flush()
        claimed = []
        for worker in workers:
            output, error = worker.communicate(timeout=10)
            assert worker.returncode == 0, error
            claimed.append(json.loads(output.strip()))
        assert claimed.count(job["job_id"]) == 1
        assert claimed.count(None) == 1
    finally:
        for worker in workers:
            if worker.poll() is None:
                worker.kill()
                worker.wait()


def test_worker_process_death_releases_lock_and_resumes_confirmed_receipt(tmp_path):
    queue = DurableJobQueue(tmp_path, lease_seconds=10, clock=lambda: 100)
    job = _submit(queue)
    root = Path(__file__).resolve().parents[1]
    crashing = _BOOTSTRAP + """
import os
queue = DurableJobQueue(sys.argv[2], lease_seconds=10, clock=lambda: 100)
def executor(job):
    spec = job['spec']
    store = UpdateRunStore(queue.base_dir)
    record = store.create(spec['cache_type'], spec['periods'], spec['mode'], spec['options'], run_id=job['execution_run_id'])
    (queue.base_dir / 'confirmed-first.txt').write_text('persisted')
    store.record_result(record, {'persisted_periods': [spec['periods'][0]]})
    os._exit(7)
run_worker(queue, executor, worker_id='crashed-worker', once=True)
"""
    process = subprocess.run([sys.executable, "-c", crashing, str(root), str(tmp_path)], capture_output=True, text=True, timeout=10)
    assert process.returncode == 7, process.stderr
    assert queue.get(job["job_id"])["status"] == "running"
    resumed = _BOOTSTRAP + """
queue = DurableJobQueue(sys.argv[2], lease_seconds=10, clock=lambda: 111)
def executor(job):
    spec = job['spec']
    store = UpdateRunStore(queue.base_dir)
    record = store.create(spec['cache_type'], spec['periods'], spec['mode'], spec['options'], run_id=job['execution_run_id'])
    assert record['persisted_periods'] == ['202503']
    assert record['pending_periods'] == ['202506']
    assert (queue.base_dir / 'confirmed-first.txt').read_text() == 'persisted'
    record = store.record_result(record, {'persisted_periods': record['pending_periods']})
    return {'status': 'succeeded', 'result': {'persisted_periods': record['persisted_periods']}}
result = run_worker(queue, executor, worker_id='replacement-worker', once=True)
print(json.dumps(result), flush=True)
"""
    process = subprocess.run([sys.executable, "-c", resumed, str(root), str(tmp_path)], capture_output=True, text=True, timeout=10)
    assert process.returncode == 0, process.stderr
    result = json.loads(process.stdout)
    assert result["status"] == "succeeded"
    assert result["execution_run_id"] == job["execution_run_id"]
    assert result["result"]["persisted_periods"] == PLAN["periods"]
    assert result["attempts"] == 2


def test_heartbeat_keeps_long_external_operation_claimed(tmp_path):
    queue = DurableJobQueue(tmp_path, lease_seconds=1)
    _submit(queue)

    def executor(job):
        time.sleep(1.3)
        assert queue.claim("other-worker") is None
        queue.ensure_claim(job["job_id"], job["lease_owner"], job["claim_token"])
        return {"status": "succeeded"}

    assert run_worker(queue, executor, worker_id="worker", once=True)["status"] == "succeeded"


def test_plan_checksum_divergence_is_detected_without_overwrite(tmp_path):
    queue = DurableJobQueue(tmp_path)
    job = _submit(queue)
    with sqlite3.connect(queue.path) as database:
        database.execute("UPDATE jobs SET spec=? WHERE job_id=?", ('{"cache_type":"tampered"}', job["job_id"]))
    with pytest.raises(JobStateError, match="divergente"):
        queue.get(job["job_id"])
    with sqlite3.connect(queue.path) as database:
        assert database.execute("SELECT spec FROM jobs WHERE job_id=?", (job["job_id"],)).fetchone()[0] == '{"cache_type":"tampered"}'
