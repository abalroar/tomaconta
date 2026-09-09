import json
from pathlib import Path
import subprocess
import sys
from threading import Thread

import pytest

from utils.ifdata_cache.update_state import (
    UpdateBusyError, UpdateRunStore, UpdateStateError, get_update_lock_info,
    is_update_running, mutation_lock,
)


def test_new_run_never_reuses_another_cache_checkpoint(tmp_path):
    store = UpdateRunStore(tmp_path)
    first = store.create("principal", ["202603", "202606"], "incremental")
    first = store.record_result(first, {"persisted_periods": ["202603"], "status": "partial"})
    second = store.create("capital", ["202603", "202606"], "incremental")
    assert second["pending_periods"] == ["202603", "202606"]
    assert store.latest("principal")["run_id"] == first["run_id"]
    assert store.latest("capital")["run_id"] == second["run_id"]


def test_resume_plan_immutable_and_results_accumulate_only_confirmed_units(tmp_path):
    store = UpdateRunStore(tmp_path)
    record = store.create("principal", ["202603", "202606"], "overwrite", {"intervalo_save": 1})
    record = store.record_result(record, {
        "persisted_periods": ["202603"], "failed_periods": {"202606": "timeout"},
        "extracted_periods": ["202603"], "status": "partial",
    })
    assert record["status"] == "partial"
    for key, replacement in (("mode", "rebuild"), ("periods", ["202606"]), ("options", {"intervalo_save": 2})):
        changed = dict(record, **{key: replacement})
        with pytest.raises(UpdateStateError):
            store.save(changed)
    resumed = store.record_result(record, {"persisted_periods": ["202606"], "status": "saved"})
    assert resumed["persisted_periods"] == ["202603", "202606"]
    assert resumed["pending_periods"] == []
    assert resumed["failed_periods"] == {}
    assert resumed["status"] == "saved"


def test_pending_or_checkpoint_failure_cannot_be_reported_as_published(tmp_path):
    store = UpdateRunStore(tmp_path)
    record = store.create("dre", ["202603"], "incremental")
    with pytest.raises(UpdateStateError, match="pendências"):
        store.finish(record, "published")
    record = store.record_result(record, {
        "persisted_periods": ["202603"], "status": "partial", "checkpoint_error": "disk full",
    })
    assert record["status"] == "failed"
    assert record["error"] == "disk full"


def test_stale_receipt_cannot_erase_confirmed_progress(tmp_path):
    store = UpdateRunStore(tmp_path)
    stale = store.create("principal", ["202603", "202606"], "incremental")
    store.record_result(stale, {"persisted_periods": ["202603"], "status": "partial"})
    with pytest.raises(UpdateStateError, match="comprovante mudou"):
        store.save(stale)
    assert store.load(stale["run_id"])["persisted_periods"] == ["202603"]


def test_corrupt_record_is_preserved_and_not_interpreted_as_empty(tmp_path):
    store = UpdateRunStore(tmp_path)
    record = store.create("principal", [], "incremental")
    path = store.root / record["run_id"] / "run.json"
    path.write_text('{"invalid":')
    with pytest.raises(UpdateStateError, match="ilegível"):
        store.latest()
    assert path.read_text() == '{"invalid":'
    with pytest.raises(UpdateStateError, match="Identificador"):
        store.load("../../outside")


def test_atomic_record_write_failure_keeps_previous_checkpoint(tmp_path, monkeypatch):
    store = UpdateRunStore(tmp_path)
    record = store.create("principal", ["202603"], "incremental")
    def fail_replace(*args):
        raise OSError("disk full")
    monkeypatch.setattr("utils.ifdata_cache.update_state.os.replace", fail_replace)
    with pytest.raises(UpdateStateError, match="Falha ao gravar"):
        store.record_result(record, {"persisted_periods": ["202603"], "status": "saved"})
    assert store.load(record["run_id"])["pending_periods"] == ["202603"]
    assert not list((store.root / record["run_id"]).glob("*.tmp"))


def test_lock_reentrant_same_thread_and_rejects_other_thread(tmp_path):
    attempts = []
    def competing_writer():
        attempts.append(is_update_running(tmp_path))
        try:
            with mutation_lock(tmp_path):
                attempts.append("entered")
        except UpdateBusyError:
            attempts.append("blocked")
    assert not is_update_running(tmp_path)
    with mutation_lock(tmp_path, owner={"cache_type": "principal", "label": "Extraindo"}):
        with mutation_lock(tmp_path):
            assert is_update_running(tmp_path)
            assert get_update_lock_info(tmp_path)["cache_type"] == "principal"
        thread = Thread(target=competing_writer)
        thread.start()
        thread.join(timeout=5)
        assert not thread.is_alive()
    assert attempts == [True, "blocked"]
    assert not is_update_running(tmp_path)
    assert get_update_lock_info(tmp_path) == {}


def test_os_lock_rejects_separate_process_then_releases(tmp_path):
    code = """
import sys
from utils.ifdata_cache.update_state import mutation_lock, UpdateBusyError
try:
    with mutation_lock(sys.argv[1]):
        print('entered')
except UpdateBusyError:
    print('blocked')
"""
    with mutation_lock(tmp_path):
        result = subprocess.run([sys.executable, "-c", code, str(tmp_path)], capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "blocked"
    result = subprocess.run([sys.executable, "-c", code, str(tmp_path)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "entered"


def test_stale_job_file_does_not_hold_lock_and_credentials_are_rejected(tmp_path):
    path = tmp_path / "data" / "cache" / ".update.lock"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"pid": 999999, "running": True}))
    assert not is_update_running(tmp_path)
    store = UpdateRunStore(tmp_path)
    with pytest.raises(UpdateStateError, match="Credenciais"):
        store.create("principal", [], "incremental", {"nested": {"gh_token": "test-secret"}})
    assert not list(store.root.glob("*/run.json"))
