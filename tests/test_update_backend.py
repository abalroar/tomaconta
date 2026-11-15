"""Integração entre fila, serviços de extração existentes e revisão oficial."""
import json
from http.server import ThreadingHTTPServer
import multiprocessing
import os
from pathlib import Path
import sqlite3
import threading
import time

import pandas as pd
import pytest

from utils.ifdata_cache.base import BaseCache, CacheConfig, CacheResult
from utils.ifdata_cache.durable_jobs import DurableJobQueue, JobLeaseError, run_worker
from utils.ifdata_cache.manager import CacheManager
from utils.ifdata_cache import official_store as official_read_context
from utils.ifdata_cache.official_store import LocalRevisionStore, RevisionConflict, begin_official_read
from utils.ifdata_cache.update_access import PermissionDenied, Principal, TokenIdentityVerifier
from utils.ifdata_cache.update_api import UpdateAPIClient, UpdateAPIError, handler_factory
from utils.ifdata_cache.update_backend import UpdateBackend, UpdateJobExecutor, collect_official_artifacts
from utils.ifdata_cache.update_state import UpdateRunStore, mutation_lock


ANALYST = Principal("analyst", frozenset({"read", "update", "publish", "restore"}))
READER = Principal("reader", frozenset({"read"}))
SPEC = {"cache_type": "balancetes", "periods": ["202603", "202606"], "mode": "overwrite",
        "options": {"batch_size": 1, "intervalo_save": 1}, "materialize": True, "publish": True}


class FakeSource(BaseCache):
    """Substitui exclusivamente a consulta externa; gravação e manager são reais."""
    def __init__(self, root):
        super().__init__(CacheConfig("balancetes", "Fixture", "balancetes", arquivo_dados="dados.parquet",
                        colunas_obrigatorias=["Período", "CodInst", "Valor"]), Path(root))

    def extrair_periodo(self, period, **kwargs):
        log = self.base_dir / "extractions.txt"
        with log.open("a") as handle:
            handle.write(period + "\n")
        return CacheResult(True, "Fonte fixture", pd.DataFrame({"Período": [period], "CodInst": [1],
                          "Valor": [int(period[-2:])]}), fonte="api")

    def baixar_remoto(self):
        raise AssertionError("A integração não deve baixar a base remotamente")


class FixtureManager(CacheManager):
    def _registrar_caches_padrao(self):
        self.registrar(FakeSource(self.base_dir))


def collector(manager, changed=()):
    return collect_official_artifacts(manager, changed=changed, validate_quality=False)


def setup_backend(tmp_path, lease=90):
    source = FixtureManager(tmp_path / "source")
    source.get_cache("balancetes").salvar_local(pd.DataFrame({"Período": ["202503"], "CodInst": [1], "Valor": [7]}))
    store = LocalRevisionStore(tmp_path / "official")
    initial = store.stage(collector(source), metadata={"action": "fixture_import"})
    store.activate(initial.revision_id, expected_parent=None)
    base = tmp_path / "service"
    backend = UpdateBackend(base, store, queue=DurableJobQueue(base, lease_seconds=lease))
    return backend, initial


def executor(backend, materializer=None):
    return UpdateJobExecutor(backend, manager_factory=FixtureManager,
                             materializer=materializer or (lambda *_: []), collector=collector)


def test_worker_promotes_one_revision_preserves_history_and_fixed_plan(tmp_path):
    backend, initial = setup_backend(tmp_path)
    job = backend.submit(SPEC, ANALYST, "request-1")
    assert backend.submit(SPEC, ANALYST, "request-1")["job_id"] == job["job_id"]
    assert backend.store.current().revision_id == initial.revision_id
    run_worker(backend.queue, executor(backend), once=True)
    finished = backend.get(job["job_id"], ANALYST)
    assert finished["status"] == "succeeded"
    assert finished["result"]["activated"] is True
    snapshot = backend.store.current()
    assert snapshot.revision_id == job["job_id"]
    data = pd.read_parquet(snapshot.resolve("data/cache/balancetes/dados.parquet"))
    assert dict(zip(data["Período"], data["Valor"])) == {"202503": 7, "202603": 3, "202606": 6}
    assert (backend.base_dir / "jobs" / job["job_id"] / "workspace/extractions.txt").read_text().splitlines() == SPEC["periods"]
    assert snapshot.parent_revision == initial.revision_id


def test_dependency_failure_keeps_official_and_retry_only_finalizes(tmp_path):
    backend, initial = setup_backend(tmp_path)
    job = backend.submit(SPEC, ANALYST, "materialization-failure")
    def fail_once(manager, kind):
        marker = manager.base_dir / "materialization-attempt.txt"
        if not marker.exists():
            marker.write_text("failed")
            raise ValueError("Dependência indisponível")
        return [{"cache": "consumer", "status": "ok"}]
    run_worker(backend.queue, executor(backend, fail_once), once=True)
    assert backend.get(job["job_id"], ANALYST)["status"] == "failed"
    assert backend.store.current().revision_id == initial.revision_id
    workspace = backend.base_dir / "jobs" / job["job_id"] / "workspace"
    before = (workspace / "extractions.txt").read_bytes()
    backend.retry(job["job_id"], ANALYST)
    run_worker(backend.queue, executor(backend, fail_once), once=True)
    assert backend.get(job["job_id"], ANALYST)["status"] == "succeeded"
    assert (workspace / "extractions.txt").read_bytes() == before
    assert backend.store.current().revision_id == job["job_id"]


def test_manual_publication_requires_validated_candidate_and_ownership(tmp_path):
    backend, initial = setup_backend(tmp_path)
    job = backend.submit({**SPEC, "publish": False}, ANALYST, "manual")
    with pytest.raises(ValueError):
        backend.publish(job["job_id"], ANALYST)
    run_worker(backend.queue, executor(backend), once=True)
    assert backend.store.current().revision_id == initial.revision_id
    with pytest.raises(PermissionDenied):
        backend.publish(job["job_id"], READER)
    with pytest.raises(PermissionDenied):
        backend.get(job["job_id"], Principal("another", ANALYST.permissions))
    assert backend.publish(job["job_id"], ANALYST)["activated"]
    backend.restore(initial.revision_id, job["job_id"], ANALYST)
    assert backend.store.current().revision_id == initial.revision_id


def test_rejected_update_permissions_and_unfrozen_windows(tmp_path):
    backend, _ = setup_backend(tmp_path)
    with pytest.raises(PermissionDenied):
        backend.submit(SPEC, READER, "denied")
    updater = Principal("updater", frozenset({"read", "update"}))
    with pytest.raises(PermissionDenied):
        backend.submit(SPEC, updater, "denied-publication")
    with pytest.raises(ValueError, match="dependências"):
        backend.submit({**SPEC, "materialize": False}, ANALYST, "unsafe")
    with pytest.raises(ValueError):
        backend.submit({**SPEC, "cache_type": "taxas_juros", "periods": [], "options": {}}, ANALYST, "unfrozen")


def test_staged_candidate_resume_does_not_reextract(tmp_path, monkeypatch):
    backend, initial = setup_backend(tmp_path)
    job = backend.submit(SPEC, ANALYST, "stage-crash")
    original = backend.store.activate
    def interrupted(*args, **kwargs):
        raise RuntimeError("Interrupção antes da promoção")
    monkeypatch.setattr(backend.store, "activate", interrupted)
    run_worker(backend.queue, executor(backend), once=True)
    assert backend.store.current().revision_id == initial.revision_id
    workspace = backend.base_dir / "jobs" / job["job_id"] / "workspace"
    calls = (workspace / "extractions.txt").read_bytes()
    monkeypatch.setattr(backend.store, "activate", original)
    backend.retry(job["job_id"], ANALYST)
    run_worker(backend.queue, executor(backend), once=True)
    assert backend.get(job["job_id"], ANALYST)["status"] == "succeeded"
    assert (workspace / "extractions.txt").read_bytes() == calls


def _crash_after_activation(base, store_dir):
    class CrashStore(LocalRevisionStore):
        def activate(self, *args, **kwargs):
            super().activate(*args, **kwargs)
            os._exit(7)
    backend = UpdateBackend(base, CrashStore(store_dir), queue=DurableJobQueue(base, lease_seconds=1))
    run_worker(backend.queue, executor(backend), once=True)


def test_worker_process_death_after_publication_reconciles_without_duplicate(tmp_path):
    backend, _ = setup_backend(tmp_path, lease=1)
    job = backend.submit(SPEC, ANALYST, "publication-crash")
    process = multiprocessing.get_context("spawn").Process(target=_crash_after_activation,
        args=(backend.base_dir, backend.store.root))
    process.start()
    process.join(15)
    assert not process.is_alive() and process.exitcode == 7
    assert backend.store.current().revision_id == job["job_id"]
    time.sleep(1.1)
    run_worker(backend.queue, executor(backend), once=True)
    final = backend.get(job["job_id"], ANALYST)
    assert final["status"] == "succeeded" and final["result"]["reconciled"]
    workspace = backend.base_dir / "jobs" / job["job_id"] / "workspace"
    assert (workspace / "extractions.txt").read_text().splitlines() == SPEC["periods"]


def test_collector_rejects_metadata_divergence_before_staging(tmp_path):
    backend, initial = setup_backend(tmp_path)
    manager = FixtureManager(tmp_path / "bad")
    cache = manager.get_cache("balancetes")
    cache.salvar_local(pd.DataFrame({"Período": ["202603"], "CodInst": [1], "Valor": [8]}))
    meta = json.loads(cache.arquivo_metadata.read_text())
    meta["total_registros"] = 2
    cache.arquivo_metadata.write_text(json.dumps(meta))
    with pytest.raises(ValueError):
        collector(manager)
    assert backend.store.current().revision_id == initial.revision_id


def _reserve_http_fixture_job_then_crash(base):
    queue = DurableJobQueue(base, lease_seconds=1)
    with mutation_lock(base):
        assert queue.claim("interrupted-http-worker") is not None
        os._exit(7)


def _complete_http_fixture_job(base, store_dir):
    # Spawned processes do not inherit pytest's socket patch.
    import socket

    original = socket.socket.connect
    def offline_connect(connection, address):
        if isinstance(address, tuple) and address[0] not in {"localhost", "127.0.0.1", "::1"}:
            raise AssertionError("O worker fixture tentou acessar rede externa")
        return original(connection, address)
    socket.socket.connect = offline_connect
    backend = UpdateBackend(base, LocalRevisionStore(store_dir), queue=DurableJobQueue(base, lease_seconds=1))
    finished = run_worker(backend.queue, executor(backend), worker_id="restarted-http-worker", once=True)
    assert finished and finished["status"] == "succeeded", finished


def test_real_http_job_survives_worker_crash_and_client_server_restart(tmp_path, monkeypatch):
    backend, initial = setup_backend(tmp_path, lease=1)
    token = "portable-http-fixture-credential"
    verifier = TokenIdentityVerifier({token: ANALYST})
    active_servers = []
    children = []
    read_context_token = official_read_context._READ_CONTEXT.set(None)

    def start_server(service):
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler_factory(service, verifier))
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
        thread.start()
        active_servers.append((server, thread))
        return UpdateAPIClient(f"http://127.0.0.1:{server.server_port}", token, timeout=2)

    try:
        client = start_server(backend)
        job = client.submit(SPEC, "http-durable-intent")
        assert job["subject"] == ANALYST.subject and job["status"] == "queued"
        assert client.submit(SPEC, "http-durable-intent")["job_id"] == job["job_id"]
        assert client.current() == {"revision_id": initial.revision_id}
        with pytest.raises(UpdateAPIError) as denied:
            UpdateAPIClient(client.url, "unrecognized-fixture-credential", timeout=2).get(job["job_id"])
        assert denied.value.status_code == 401

        monkeypatch.setenv("TOMACONTA_OFFICIAL_STORE_DIR", str(backend.store.root))
        reader_root = tmp_path / "reader-app"
        assert begin_official_read(reader_root).revision_id == initial.revision_id
        pinned_reader = FakeSource(reader_root)
        assert pinned_reader.carregar_local().dados["Período"].tolist() == ["202503"]

        crash = multiprocessing.get_context("spawn").Process(target=_reserve_http_fixture_job_then_crash,
                                                               args=(backend.base_dir,))
        children.append(crash)
        crash.start()
        crash.join(15)
        assert not crash.is_alive() and crash.exitcode == 7
        abandoned = backend.queue.get(job["job_id"])
        assert client.get(job["job_id"])["status"] == "running"

        # Close this HTTP server and discard its client/backend instances.
        server, thread = active_servers.pop()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()
        base, store_dir = backend.base_dir, backend.store.root
        del client, backend
        restarted = UpdateBackend(base, LocalRevisionStore(store_dir), queue=DurableJobQueue(base, lease_seconds=1))
        client = start_server(restarted)
        restored = client.get(job["job_id"])
        assert restored["execution_run_id"] == job["execution_run_id"]
        assert restored["spec"] == job["spec"]
        assert [item["job_id"] for item in client.list()] == [job["job_id"]]
        assert client.current() == {"revision_id": initial.revision_id}

        with sqlite3.connect(restarted.queue.path) as database:
            expired_token = database.execute("SELECT claim_token FROM jobs WHERE job_id=?", (job["job_id"],)).fetchone()[0]
        time.sleep(1.1)
        with pytest.raises(JobLeaseError):
            restarted.queue.ensure_claim(job["job_id"], abandoned["lease_owner"],
                                         expired_token)
        worker = multiprocessing.get_context("spawn").Process(target=_complete_http_fixture_job,
            args=(base, store_dir))
        children.append(worker)
        worker.start()
        worker.join(15)
        assert not worker.is_alive() and worker.exitcode == 0

        final = client.get(job["job_id"])
        assert final["status"] == "succeeded" and final["result"]["activated"]
        assert final["execution_run_id"] == job["execution_run_id"] and final["attempts"] == 2
        assert final["run"]["pending_periods"] == []
        assert final["run"]["persisted_periods"] == SPEC["periods"]
        assert client.current() == {"revision_id": job["job_id"]}
        assert restarted.store.current().parent_revision == initial.revision_id
        workspace = base / "jobs" / job["job_id"] / "workspace"
        assert (workspace / "extractions.txt").read_text().splitlines() == SPEC["periods"]
        assert pinned_reader.carregar_local().dados["Período"].tolist() == ["202503"]
        assert begin_official_read(reader_root).revision_id == job["job_id"]
        new_data = FakeSource(reader_root).carregar_local().dados
        assert dict(zip(new_data["Período"], new_data["Valor"])) == {"202503": 7, "202603": 3, "202606": 6}
        assert token not in json.dumps(final, ensure_ascii=False)
        for queue_file in restarted.queue.path.parent.glob("update_jobs.sqlite3*"):
            assert token.encode() not in queue_file.read_bytes()
    finally:
        for process in children:
            if process.is_alive():
                process.terminate()
            process.join(timeout=2)
        for server, thread in active_servers:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        official_read_context._READ_CONTEXT.reset(read_context_token)
