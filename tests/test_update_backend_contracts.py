"""Contratos nativos do worker: parâmetros, fontes fixas e pacote completo."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
from types import SimpleNamespace
from uuid import uuid4
import weakref

import pandas as pd
import pytest

from utils.ifdata_cache.base import BaseCache, CacheConfig, CacheResult
from utils.ifdata_cache.durable_jobs import DurableJobQueue, run_worker
from utils.ifdata_cache.manager import CacheManager
from utils.ifdata_cache.official_store import LocalRevisionStore
from utils.ifdata_cache.update_access import Principal
from utils.ifdata_cache.update_backend import (
    LocalOnlySourcesManager, UpdateBackend, UpdateJobExecutor,
    assert_adapter_complete, collect_official_artifacts,
)


ANALYST = Principal("contract-analyst", {"read", "update", "publish", "restore"})
FRAME = pd.DataFrame({"Período": ["202606"], "CodInst": [1], "Valor": [7]})


class ContractCache(BaseCache):
    def __init__(self, root, name):
        super().__init__(CacheConfig(name, "Contrato", name, arquivo_dados="dados.parquet",
                         colunas_obrigatorias=list(FRAME.columns)), Path(root))
        self.manifest_path = self.cache_dir / "native_manifest.json"

    def baixar_remoto(self):
        raise AssertionError("Uma fonte importada não pode ser substituída pelo GitHub")

    def extrair_periodo(self, period, **kwargs):
        raise AssertionError("A fixture nativa não executa consultas de períodos")

    def dimension_paths(self):
        return {key: self.cache_dir / f"dim_{key}.parquet" for key in ("first", "second")}

    def annual_path(self, year):
        return self.cache_dir / f"{year}.parquet"

    def dataset_paths(self):
        return {"main": self.arquivo_dados_runtime,
                "declared": self.cache_dir / "declared.parquet",
                "optional": self.cache_dir / "optional.parquet"}

    def extra_release_assets(self):
        paths = {self.manifest_path}
        if self.config.nome == "spb_meios_pagamento":
            paths.add(self.dataset_paths()["declared"])
        elif self.config.nome in {"scr_data", "taxas_juros_historico"}:
            paths.update(self.dimension_paths().values())
            if self.config.nome == "scr_data":
                paths.add(self.annual_path(2026))
        else:
            return []
        # Reproduz o coletor nativo legado, que pode omitir extras ausentes.
        return [(path, f"{self.config.nome}_{path.name}") for path in sorted(paths) if path.is_file()]


class ContractManager(CacheManager):
    names = ("balancetes", "scr_data")

    def _registrar_caches_padrao(self):
        for name in self.names:
            self.registrar(ContractCache(self.base_dir, name))


def _save_native(cache):
    extra = {"anos_materializados": ["2026"]} if cache.config.nome == "scr_data" else {}
    assert cache.salvar_local(FRAME.copy(), info_extra=extra).sucesso
    if cache.config.nome == "spb_meios_pagamento":
        manifest = {"datasets": {"main": 1, "declared": 1}}
        paths = [cache.dataset_paths()["declared"]]
    else:
        manifest = {"finalized": True}
        paths = list(cache.dimension_paths().values())
        if cache.config.nome == "scr_data":
            paths.append(cache.annual_path(2026))
    cache.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    for path in paths:
        pd.DataFrame({"Valor": [1]}).to_parquet(path, index=False)


def _collect(manager, changed=()):
    return collect_official_artifacts(manager, changed=changed, validate_quality=False)


@pytest.mark.parametrize("kind,mode,options,expected", [
    ("scr_data", "overwrite", {"years": [2024, 2025, 2026]},
     {"ano_inicial": 2024, "ano_final": 2026, "overwrite": True}),
    ("scr_data", "incremental", {"years": [2026]},
     {"ano_inicial": 2026, "ano_final": 2026, "overwrite": False}),
    ("mercado_credito_sgs", "overwrite", {"start": "2026-06-01", "end": "2026-06-30"},
     {"start": "2026-06-01", "end": "2026-06-30", "overwrite": True}),
    ("spb_meios_pagamento", "rebuild", {"datasets": ["nucleo_trimestral"]},
     {"datasets": ["nucleo_trimestral"], "overwrite": True}),
])
def test_special_adapter_preserves_native_parameters(kind, mode, options, expected):
    calls = []
    result = CacheResult(True, "Completo", metadata={"finalized": True})
    cache = SimpleNamespace(materialize_history=lambda **kwargs: calls.append(kwargs) or result)
    manager = SimpleNamespace(get_cache=lambda name: cache)
    assert UpdateJobExecutor._special_update(manager, {
        "cache_type": kind, "mode": mode, "options": options, "periods": [],
    }) is result
    assert calls == [expected]


def test_rates_history_resumes_chunks_with_identical_native_plan(tmp_path):
    calls = []
    checkpoint = tmp_path / "checkpoint.json"
    final = CacheResult(True, "Concluído", metadata={"finalized": True})

    def materialize(**kwargs):
        calls.append(kwargs)
        checkpoint.write_text(json.dumps({"completed_windows": ["2026-06-01"]}))
        return CacheResult(True, "Parcial", metadata={"finalized": False}) if len(calls) == 1 else final

    manager = SimpleNamespace(get_cache=lambda _: SimpleNamespace(
        materialize_history=materialize, checkpoint_path=checkpoint))
    spec = {"cache_type": "taxas_juros_historico", "mode": "overwrite", "periods": [],
            "options": {"start": "2026-06-01", "end": "2026-06-30", "max_windows": 1, "reprocess_tail": 4}}
    assert UpdateJobExecutor._special_update(manager, spec) is final
    expected = {"data_inicio": "2026-06-01", "data_fim": "2026-06-30", "overwrite": True,
                "max_windows_per_run": 1, "reprocess_tail_windows": 4}
    assert calls == [expected, expected]


def test_cosif_preserves_individual_periods_and_refresh_without_bundle(monkeypatch):
    import scripts.ingest_cosif_4010 as ingestion
    calls = []
    cache = object()
    result = CacheResult(True, "Completo")
    monkeypatch.setattr(ingestion, "ingest", lambda *args, **kwargs: calls.append((args, kwargs)) or result)
    manager = SimpleNamespace(get_cache=lambda _: cache)
    periods = ["202605", "202606"]
    assert UpdateJobExecutor._special_update(manager, {"cache_type": "cosif_4010", "mode": "overwrite",
            "periods": periods, "options": {}}) is result
    assert calls == [((cache, periods), {"refresh": True})]


def test_rates_daily_preserves_exact_dates(monkeypatch):
    import utils.ifdata_cache.update_service as service
    calls = []
    cache = object()
    result = CacheResult(True, "Completo")
    monkeypatch.setattr(service, "extract_taxas_window", lambda *args: calls.append(args) or result)
    assert UpdateJobExecutor._special_update(SimpleNamespace(get_cache=lambda _: cache), {
        "cache_type": "taxas_juros", "mode": "overwrite", "periods": [],
        "options": {"start": "2026-06-01", "end": "2026-06-30"},
    }) is result
    assert calls == [(cache, "2026-06-01", "2026-06-30")]


@pytest.mark.parametrize("metadata", [
    {"finalized": False}, {"remaining_windows": 1}, {"failures": [{"erro": "fonte"}]},
    {"falhas": {"2026": "incompleto"}}, {"truncado": True},
    {"persistence_error": "gravação"}, {"checkpoint_error": "confirmação"},
    {"callback_error": "retorno"}, {"extra": {"pending_periods": ["202606"]}},
])
def test_partial_new_adapter_result_cannot_certify_healthy_previous_generation(metadata):
    with pytest.raises(ValueError):
        assert_adapter_complete(CacheResult(True, "Base anterior intacta", metadata=metadata))


def test_worker_partial_native_result_keeps_previous_official_revision(tmp_path, monkeypatch):
    manager = ContractManager(tmp_path / "source")
    _save_native(manager.get_cache("scr_data"))
    store = LocalRevisionStore(tmp_path / "official")
    initial = store.stage(_collect(manager))
    store.activate(initial.revision_id, expected_parent=None)
    backend = UpdateBackend(tmp_path / "service", store)
    job = backend.submit({"cache_type": "scr_data", "mode": "overwrite", "periods": [],
                          "options": {"years": [2026]}}, ANALYST, "partial-native")
    monkeypatch.setattr(UpdateJobExecutor, "_special_update", staticmethod(lambda *_:
        CacheResult(True, "Ainda faltam unidades", metadata={"finalized": False})))
    worker = UpdateJobExecutor(backend, manager_factory=ContractManager,
                              materializer=lambda *_: [], collector=_collect)
    run_worker(backend.queue, worker, once=True)
    final = backend.get(job["job_id"], ANALYST)
    assert final["status"] == "failed"
    assert store.current().revision_id == initial.revision_id
    assert not (store.root / "revisions" / job["job_id"]).exists()


@pytest.mark.parametrize("name,missing", [
    ("taxas_juros_historico", "dimension"), ("scr_data", "dimension"),
    ("scr_data", "annual"), ("spb_meios_pagamento", "declared"),
    ("spb_meios_pagamento", "manifest"),
])
def test_official_collector_blocks_missing_native_contract_even_if_extra_collector_omits_it(tmp_path, name, missing):
    cache = ContractCache(tmp_path, name)
    _save_native(cache)
    paths = {"dimension": cache.dimension_paths()["second"], "annual": cache.annual_path(2026),
             "declared": cache.dataset_paths()["declared"], "manifest": cache.manifest_path}
    paths[missing].unlink()
    manager = SimpleNamespace(base_dir=tmp_path, listar_caches=lambda: [name], get_cache=lambda _: cache)
    with pytest.raises(ValueError, match="obrigatório ausente"):
        _collect(manager, changed=[name])


def test_collector_never_omits_the_requested_cache_when_its_fact_is_missing(tmp_path):
    manager = ContractManager(tmp_path)
    assert manager.get_cache("balancetes").salvar_local(FRAME.copy()).sucesso
    _save_native(manager.get_cache("scr_data"))
    manager.get_cache("scr_data").arquivo_dados_runtime.unlink()
    with pytest.raises(ValueError):
        _collect(manager, changed=["scr_data"])


def test_unselected_undeclared_spb_dataset_is_not_required(tmp_path):
    cache = ContractCache(tmp_path, "spb_meios_pagamento")
    _save_native(cache)
    assert not cache.dataset_paths()["optional"].exists()
    manager = SimpleNamespace(base_dir=tmp_path, listar_caches=lambda: [cache.config.nome], get_cache=lambda _: cache)
    artifacts = _collect(manager, changed=[cache.config.nome])
    assert "data/cache/spb_meios_pagamento/declared.parquet" in artifacts
    assert "data/cache/spb_meios_pagamento/optional.parquet" not in artifacts


def test_local_source_facade_ignores_expiration_and_denies_remote(tmp_path, monkeypatch):
    manager = ContractManager(tmp_path)
    cache = manager.get_cache("balancetes")
    assert cache.salvar_local(FRAME.copy()).sucesso
    monkeypatch.setattr(cache, "cache_valido", lambda: (False, "Cache expirado"))
    local = LocalOnlySourcesManager(manager)
    pd.testing.assert_frame_equal(local.carregar("balancetes").dados, FRAME)
    assert local.base_dir == manager.base_dir
    assert not local.carregar("balancetes", forcar_remoto=True).sucesso
    assert not local.carregar("ausente").sucesso


@pytest.mark.parametrize("kind,options", [
    ("scr_data", {"years": [2022, 2024]}),
    ("spb_meios_pagamento", {"datasets": ["nucleo_trimestral", "desconhecido"]}),
])
def test_backend_rejects_native_selection_that_would_be_silently_expanded_or_ignored(tmp_path, kind, options):
    backend = UpdateBackend(tmp_path, LocalRevisionStore(tmp_path / "official"),
                            queue=DurableJobQueue(tmp_path))
    with pytest.raises(ValueError):
        backend.submit({"cache_type": kind, "mode": "overwrite", "options": options}, ANALYST, "invalid-selection")
    assert backend.queue.list(subject=ANALYST.subject) == []


@pytest.mark.parametrize("name", ["taxas_juros_historico", "scr_data", "spb_meios_pagamento"])
def test_collector_reads_native_assets_from_the_same_bundled_generation(tmp_path, name):
    cache = ContractCache(tmp_path, name)
    _save_native(cache)
    shutil.copytree(cache.cache_dir, cache.bundled_dir)
    cache.arquivo_dados_runtime.unlink()
    # Um auxiliar diferente no runtime não pode substituir o auxiliar do bundle.
    auxiliary = cache.dataset_paths()["declared"] if name == "spb_meios_pagamento" else cache.dimension_paths()["first"]
    pd.DataFrame({"Valor": [999]}).to_parquet(auxiliary, index=False)
    manager = SimpleNamespace(base_dir=tmp_path, listar_caches=lambda: [name], get_cache=lambda _: cache)
    before = {path: path.read_bytes() for path in cache.bundled_dir.rglob("*") if path.is_file()}
    artifacts = _collect(manager, changed=[name])
    assert all(path.is_relative_to(cache.bundled_dir) for path in artifacts.values())
    logical = f"data/cache/{name}/{auxiliary.name}"
    assert pd.read_parquet(artifacts[logical])["Valor"].tolist() == [1]
    assert {path: path.read_bytes() for path in before} == before
    if name == "scr_data":
        assert f"data/cache/{name}/2026.parquet" in artifacts


@pytest.mark.parametrize("name", ["taxas_juros_historico", "scr_data", "spb_meios_pagamento"])
def test_missing_bundled_native_asset_cannot_use_an_asset_from_runtime(tmp_path, name):
    cache = ContractCache(tmp_path, name)
    _save_native(cache)
    shutil.copytree(cache.cache_dir, cache.bundled_dir)
    cache.arquivo_dados_runtime.unlink()
    auxiliary = cache.dataset_paths()["declared"] if name == "spb_meios_pagamento" else cache.dimension_paths()["first"]
    (cache.bundled_dir / auxiliary.name).unlink()
    assert auxiliary.is_file()
    manager = SimpleNamespace(base_dir=tmp_path, listar_caches=lambda: [name], get_cache=lambda _: cache)
    with pytest.raises(ValueError, match="obrigatório ausente"):
        _collect(manager, changed=[name])


@pytest.mark.parametrize("section", [None, "extra", "info_extra"])
@pytest.mark.parametrize("artifact", ["metadata", "manifest"])
def test_native_generation_partial_flags_block_even_with_every_file_present(tmp_path, section, artifact):
    cache = ContractCache(tmp_path, "spb_meios_pagamento")
    _save_native(cache)
    path = cache.arquivo_metadata if artifact == "metadata" else cache.manifest_path
    payload = json.loads(path.read_text())
    flags = {"finalized": False, "pending_periods": ["materialization"]}
    if section is None:
        payload.update(flags)
    else:
        payload[section] = {**(payload.get(section) or {}), **flags}
    path.write_text(json.dumps(payload))
    manager = SimpleNamespace(base_dir=tmp_path, listar_caches=lambda: [cache.config.nome], get_cache=lambda _: cache)
    with pytest.raises(ValueError):
        _collect(manager, changed=[cache.config.nome])


def test_adapter_result_info_extra_partial_is_never_confirmed():
    with pytest.raises(ValueError):
        assert_adapter_complete(CacheResult(True, "Parcial", metadata={"info_extra": {"finalized": False}}))


def test_list_of_100_jobs_with_2000_units_is_bounded_and_get_keeps_every_unit(tmp_path, monkeypatch):
    import utils.ifdata_cache.update_backend as module
    from utils.ifdata_cache.update_api import MAX_RESPONSE_JSON_BYTES
    from utils.ifdata_cache.update_app_bridge import ExternalUpdateBridge, job_checkpoint_view, job_status_view

    # Listas compartilhadas na fixture mantêm o teste pequeno; o JSON representa
    # exatamente 100 planos independentes com 2000 unidades cada.
    periods = [f"{1900 + index // 12}{index % 12 + 1:02d}" for index in range(2000)]
    persisted, pending = periods[:1000], periods[1000:]
    receipt = {"status": "partial", "periods": periods, "requested_periods": periods,
               "extracted_periods": persisted, "persisted_periods": persisted,
               "pending_periods": pending, "error": "e" * 4000, "current_period": pending[0],
               "publication": {"message": "m" * 4000}}
    jobs = [{"job_id": uuid4().hex, "execution_run_id": uuid4().hex, "subject": ANALYST.subject,
             "status": "partial", "created_at": index, "updated_at": index + 1, "error": "e" * 4000,
             "spec": {"cache_type": "bloprudencial", "mode": "overwrite", "periods": periods,
                      "options": {"batch_size": 1000}},
             "result": {"pending_periods": pending, "materialization": [{"detail": "x" * 12000}]}}
            for index in range(100)]
    by_id = {job["job_id"]: job for job in jobs}

    class Queue:
        def list(self, subject):
            assert subject == ANALYST.subject
            return jobs

        def get(self, job_id):
            return by_id.get(job_id)

    class Receipts:
        def __init__(self, _workspace):
            pass

        def load(self, _run_id):
            return receipt

    backend = UpdateBackend(tmp_path, SimpleNamespace(find_publication=lambda _: None), queue=Queue())
    for job in jobs:
        (tmp_path / "jobs" / job["job_id"] / "workspace").mkdir(parents=True)
    monkeypatch.setattr(module, "UpdateRunStore", Receipts)
    summaries = backend.list(ANALYST)
    encoded = json.dumps(summaries, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    assert len(summaries) == 100 and len(encoded) < MAX_RESPONSE_JSON_BYTES
    assert all(job["summary"] is True and "periods" not in job["spec"] for job in summaries)
    assert summaries[-1]["run"]["total_periods"] == 2000
    assert summaries[-1]["run"]["persisted_count"] == 1000
    assert summaries[-1]["run"]["pending_count"] == 1000
    assert len(summaries[-1]["error"]) == 256
    detail = backend.get(jobs[-1]["job_id"], ANALYST)
    assert detail["spec"]["periods"] == periods
    assert detail["run"]["pending_periods"] == pending
    assert detail["result"]["materialization"] == jobs[-1]["result"]["materialization"]
    assert "summary" not in detail

    class Client:
        gets = []

        def list(self):
            return backend.list(ANALYST)

        def get(self, job_id):
            self.gets.append(job_id)
            return backend.get(job_id, ANALYST)

    client = Client()
    bridge = ExternalUpdateBridge(client)
    assert bridge.current_status("bloprudencial") == job_status_view(detail)
    assert bridge.current_status("bloprudencial")["progress"] == .5
    assert bridge.checkpoint("bloprudencial") == job_checkpoint_view(detail)
    assert bridge.checkpoint("bloprudencial")["pendentes"] == pending
    assert client.gets == [jobs[-1]["job_id"]] * 4


@pytest.mark.parametrize("field", ["run_id", "subject"])
@pytest.mark.parametrize("operation", ["worker", "manual_publish"])
def test_candidate_requires_server_run_identity_and_subject(tmp_path, field, operation):
    manager = ContractManager(tmp_path / "source")
    assert manager.get_cache("balancetes").salvar_local(FRAME.copy()).sucesso
    store = LocalRevisionStore(tmp_path / "official")
    initial = store.stage(_collect(manager))
    store.activate(initial.revision_id, expected_parent=None)
    backend = UpdateBackend(tmp_path / "service", store)
    submitted = backend.submit({"cache_type": "balancetes", "periods": ["202606"],
                                "mode": "overwrite", "options": {}}, ANALYST, "candidate-identity")
    job = backend.queue.claim("fixture-worker")
    assert job["job_id"] == submitted["job_id"]
    context = {"parent_revision": initial.revision_id, "revision_id": job["job_id"]}
    backend.queue.update_context(job["job_id"], job["lease_owner"], job["claim_token"], context)
    metadata = {"job_id": job["job_id"], "run_id": job["execution_run_id"], "subject": job["subject"]}
    metadata[field] = "different-server-identity"
    candidate = store.stage(_collect(manager), parent_revision=initial.revision_id,
                            revision_id=job["job_id"], metadata=metadata)
    if operation == "worker":
        worker = UpdateJobExecutor(backend, manager_factory=ContractManager,
                                  materializer=lambda *_: [], collector=_collect)
        with pytest.raises(ValueError, match="identidade"):
            worker(job)
    else:
        backend.queue.finish(job["job_id"], job["lease_owner"], job["claim_token"], "succeeded",
                             result={"revision_id": candidate.revision_id, "parent_revision": initial.revision_id})
        with pytest.raises(ValueError, match="identidade"):
            backend.publish(job["job_id"], ANALYST)
    assert store.current().revision_id == initial.revision_id


def test_quality_preflight_releases_previous_frame_before_loading_the_next_cache(monkeypatch):
    from utils.ifdata_cache import release_ops as release
    frames = []

    class Cache:
        def carregar_local(self):
            assert not frames or frames[-1]() is None
            frame = pd.DataFrame({"CodInst": [1], "Instituição": ["BANCO EXEMPLO"], "Período": ["202606"]})
            frames.append(weakref.ref(frame))
            return CacheResult(True, "Completo", dados=frame)

    manager = SimpleNamespace(get_cache=lambda _: Cache())
    monkeypatch.setattr(release, "validate_institution_names", lambda frame: (True, "ok"))
    checks = release.validate_cache_quality(manager, ["principal", "capital"])
    assert all(check["success"] for check in checks.values())
    assert len(frames) == 2 and all(reference() is None for reference in frames)
