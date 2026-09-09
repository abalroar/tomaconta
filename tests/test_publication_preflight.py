import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from utils.ifdata_cache import release_ops as R
from utils.ifdata_cache.diagnostics import build_runtime_manifest
from utils.ifdata_cache.release_config import get_release_config


class Cache:
    def __init__(self, root, name):
        self.arquivo_dados = root / name / "dados.parquet"
        self.arquivo_dados.parent.mkdir()
        self.arquivo_dados_pickle = self.arquivo_dados.with_suffix(".pkl")
        self.arquivo_metadata = self.arquivo_dados.with_name("metadata.json")
        pd.DataFrame({"Período": ["1/2026"], "Valor": [1]}).to_parquet(self.arquivo_dados)
        self.arquivo_metadata.write_text(json.dumps({"periodos": ["1/2026"], "total_registros": 1}))

    def get_info(self):
        return {"existe": self.arquivo_dados.exists(), "periodos": ["1/2026"]}


class Manager:
    def __init__(self, root):
        self.base_dir = root
        self.caches = {name: Cache(root, name) for name in R.PUBLISH_ORDER}

    def get_cache(self, name):
        return self.caches.get(name)

    def listar_caches(self):
        return list(self.caches)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    # No real HTTP is allowed, including an accidental remote fallback.
    def unexpected_network(*args, **kwargs):
        raise AssertionError("rede não permitida neste teste")
    monkeypatch.setattr(R.requests, "request", unexpected_network)
    monkeypatch.setattr(R.requests, "post", unexpected_network)
    manager = Manager(tmp_path)
    release = get_release_config()
    remote = build_runtime_manifest(manager, release_config=release, include_hashes=True)
    remote["expected_periods"] = {"quarterly": "202512", "monthly": "202512"}
    remote["untouched_extension"] = {"owner": "other-publisher"}
    remote["caches"]["external_cache"] = {"sha256": "external", "max_period_ref": "202512"}
    confirmations = []
    monkeypatch.setattr(R, "_confirm_remote_source", lambda *args: confirmations.append(args[1]))
    monkeypatch.setattr(R, "validate_cache_quality", lambda _manager, names: {
        name: {"success": True, "message": "ok"} for name in names
        if name in R.INDIVIDUAL_CACHE_QUALITY_SPECS or name in R.CACHE_FRAME_QUALITY_VALIDATORS
    })
    return manager, release, remote, confirmations


def details(selected):
    return [{"cache": target, "status": "ok", "message": "ok"} for target in R.get_postprocess_targets(selected)]


def prepare(setup, selected, **kwargs):
    manager, release, remote, _ = setup
    return R.prepare_release_publication(
        manager, selected_caches=selected, materialization_details=details(selected),
        release_config=release, remote_manifest=remote, **kwargs,
    )


def test_independent_monthly_package_preserves_global_manifest(setup):
    manager, _, remote, confirmations = setup
    path, manifest, names, assets = prepare(setup, ["mercado_credito_sgs"], expected_periods={"monthly": "202603"})
    assert path.exists()
    assert names == ["mercado_credito_sgs"]
    assert manifest["expected_periods"] == remote["expected_periods"]
    assert manifest["publication_expected_periods"] == {"monthly": "202603"}
    assert manifest["caches"]["dre"] == remote["caches"]["dre"]
    assert manifest["caches"]["external_cache"] == remote["caches"]["external_cache"]
    assert manifest["untouched_extension"] == remote["untouched_extension"]
    assert [name for _, name in assets] == ["mercado_credito_sgs_dados.parquet", "mercado_credito_sgs_metadata.json", "manifest.json"]
    assert confirmations == []
    assert not (manager.base_dir / "data/cache/manifest.json").exists()


def test_required_materialization_failure_blocks_before_any_http_or_upload(setup, monkeypatch):
    manager, release, remote, _ = setup
    uploads = []
    monkeypatch.setattr(R, "upload_release_assets", lambda **kwargs: uploads.append(kwargs))
    with pytest.raises(ValueError, match="materialização obrigatória ausente"):
        _, _, _, assets = R.prepare_release_publication(
            manager, selected_caches=["principal"], materialization_details=[],
            release_config=release, remote_manifest=remote,
        )
        R.upload_release_assets(repo=release.repo, tag=release.tag, assets=assets, token="fake")
    assert uploads == []
    assert not (manager.base_dir / "data/cache/publications").exists()


def test_required_gate_missing_blocks_package(setup, monkeypatch):
    original = R.build_runtime_manifest
    def missing_gate(*args, **kwargs):
        payload = original(*args, **kwargs)
        payload["gates"].pop("rankings")
        return payload
    monkeypatch.setattr(R, "build_runtime_manifest", missing_gate)
    with pytest.raises(ValueError, match="rankings: gate obrigatório ausente"):
        prepare(setup, ["principal"])


def test_sources_are_confirmed_by_hash_before_reuse(setup):
    _, _, _, confirmations = setup
    _, manifest, names, _ = prepare(setup, ["principal"], expected_periods={"quarterly": "202603"})
    assert names == ["principal", "derived_metrics", "critical_screens"]
    assert "ativo" in confirmations and "dre" in confirmations
    assert {entry["cache"] for entry in manifest["confirmed_source_assets"]} == set(confirmations)


def test_changed_source_requires_its_other_consumers_before_upload(setup):
    manager, _, _, _ = setup
    pd.DataFrame({"Período": ["1/2026"], "Valor": [2]}).to_parquet(manager.get_cache("ativo").arquivo_dados)
    with pytest.raises(ValueError, match="derived_metrics_individual"):
        prepare(setup, ["principal"])


def test_changed_source_is_uploaded_when_all_consumers_are_prepared(setup):
    manager, _, _, _ = setup
    pd.DataFrame({"Período": ["1/2026"], "Valor": [2]}).to_parquet(manager.get_cache("passivo").arquivo_dados)
    _, manifest, names, assets = prepare(setup, ["principal"])
    assert "passivo" in names
    assert "passivo_dados.parquet" in [name for _, name in assets]
    assert manifest["caches"]["passivo"]["sha256"] == hashlib.sha256(manager.get_cache("passivo").arquivo_dados.read_bytes()).hexdigest()


def test_quarterly_reference_does_not_advance_with_old_unrelated_individual(setup):
    _, _, remote, _ = setup
    for name in ("principal_individual", "dre_individual", "derived_metrics_individual"):
        remote["caches"][name]["max_period_ref"] = "202512"
    _, manifest, _, _ = prepare(setup, ["principal"], expected_periods={"quarterly": "202603"})
    assert manifest["expected_periods"]["quarterly"] == "202512"


@pytest.mark.parametrize("remote", [{}, {"caches": {}}, {"caches": {"x": {}}, "release": {"repo": "wrong", "tag": "wrong"}}])
def test_unavailable_or_wrong_remote_manifest_blocks_global_write(setup, remote):
    manager, release, _, _ = setup
    with pytest.raises(ValueError, match="manifesto remoto"):
        R.prepare_release_publication(manager, selected_caches=["mercado_credito_sgs"], release_config=release, remote_manifest=remote)
    assert not (manager.base_dir / "data/cache/publications").exists()


def test_unavailable_remote_service_blocks_global_write(setup, monkeypatch):
    manager, release, _, _ = setup
    monkeypatch.setattr(R, "_request_with_retries", lambda *a, **kw: SimpleNamespace(status_code=503))
    with pytest.raises(RuntimeError, match="manifesto remoto indisponível"):
        R.prepare_release_publication(manager, selected_caches=["mercado_credito_sgs"], release_config=release)
    assert not (manager.base_dir / "data/cache/publications").exists()


@pytest.mark.parametrize("extra", [{"falhas": ["1"]}, {"remaining_windows": 1}, {"finalized": False}])
def test_partial_source_metadata_blocks_publication(setup, extra):
    manager, _, _, _ = setup
    manager.get_cache("mercado_credito_sgs").arquivo_metadata.write_text(json.dumps({"periodos": ["1/2026"], "extra": extra}))
    with pytest.raises(ValueError, match="publicação bloqueada"):
        prepare(setup, ["mercado_credito_sgs"])


def test_extra_assets_are_preserved(setup):
    manager, _, _, _ = setup
    extra = manager.base_dir / "dimension.parquet"
    extra.write_bytes(b"dimension")
    manager.get_cache("mercado_credito_sgs").extra_release_assets = lambda: [(extra, "sgs_dimension.parquet")]
    _, manifest, _, assets = prepare(setup, ["mercado_credito_sgs"])
    assert "sgs_dimension.parquet" in [name for _, name in assets]
    assert any(item["name"] == "sgs_dimension.parquet" for item in manifest["publication_assets"])


def test_network_confirmation_rejects_content_different_from_manifest(monkeypatch):
    response = SimpleNamespace(status_code=200, iter_content=lambda **kwargs: [b"wrong"], close=lambda: None)
    monkeypatch.setattr(R, "_request_with_retries", lambda *args, **kwargs: response)
    with pytest.raises(RuntimeError, match="hash remoto diverge"):
        R._confirm_remote_source(get_release_config(), "ativo", hashlib.sha256(b"expected").hexdigest(), None)


def test_monthly_source_missing_target_blocks_publication(setup):
    with pytest.raises(ValueError, match="alvo mensal"):
        prepare(setup, ["mercado_credito_sgs"], expected_periods={"monthly": "202606"})


def test_changed_candidate_blocks_upload_before_remote_mutation(setup):
    manager, release, _, _ = setup
    _, _, _, assets = prepare(setup, ["mercado_credito_sgs"])
    manager.get_cache("mercado_credito_sgs").arquivo_dados.write_bytes(b"changed after review")
    with pytest.raises(ValueError, match="candidato mudou"):
        R.upload_release_assets(repo=release.repo, tag=release.tag, assets=assets, token="fake")


def test_missing_candidate_blocks_upload_before_remote_mutation(setup):
    manager, release, _, _ = setup
    _, _, _, assets = prepare(setup, ["mercado_credito_sgs"])
    manager.get_cache("mercado_credito_sgs").arquivo_dados.unlink()
    with pytest.raises(FileNotFoundError, match="antes do upload"):
        R.upload_release_assets(repo=release.repo, tag=release.tag, assets=assets, token="fake")


@pytest.mark.parametrize("cache_name,result", [
    ("principal", {"status": "partial", "pending_periods": ["202603"]}),
    ("ativo", {"status": "extracting"}),
    ("capital", {"status": "saved", "failed_periods": {"202603": "falhou"}}),
    ("dre", {"status": "saved", "checkpoint_error": "disk"}),
    ("bloprudencial", {"status": "saved", "persistence_error": "disk"}),
])
def test_pending_result_of_any_source_blocks_publish_only(setup, cache_name, result):
    from utils.ifdata_cache.update_state import write_cache_update_result
    manager, _, _, _ = setup
    write_cache_update_result(manager.base_dir, cache_name, result)
    with pytest.raises(ValueError, match=f"{cache_name}: atualização registrada incompleta"):
        prepare(setup, ["principal"])


def test_corrupt_cache_update_result_blocks_publication(setup):
    from utils.ifdata_cache.update_state import UpdateStateError
    manager, _, _, _ = setup
    path = manager.base_dir / "data/cache/update_results/mercado_credito_sgs.json"
    path.parent.mkdir(parents=True)
    path.write_text("{corrupt")
    with pytest.raises(UpdateStateError, match="publicação bloqueada"):
        prepare(setup, ["mercado_credito_sgs"])


def test_saved_cache_update_result_allows_publication(setup):
    from utils.ifdata_cache.update_state import write_cache_update_result
    manager, _, _, _ = setup
    write_cache_update_result(manager.base_dir, "mercado_credito_sgs", {
        "status": "saved", "pending_periods": [], "failed_periods": {},
    })
    assert prepare(setup, ["mercado_credito_sgs"])[2] == ["mercado_credito_sgs"]


@pytest.mark.parametrize("status", ["prepared", "extracting", "partial", "failed"])
def test_special_adapter_incomplete_run_blocks_even_without_manager_ledger(setup, status):
    from utils.ifdata_cache.update_state import UpdateRunStore
    manager, _, _, _ = setup
    store = UpdateRunStore(manager.base_dir)
    record = store.create("mercado_credito_sgs", periods=[])
    record["status"] = status
    store.save(record)
    with pytest.raises(ValueError, match="execução registrada incompleta"):
        prepare(setup, ["mercado_credito_sgs"])


@pytest.mark.parametrize("status", ["saved", "ready_to_publish", "validating", "publishing", "published", "publish_failed"])
def test_prepared_special_adapter_allows_publication_retry(setup, status):
    from utils.ifdata_cache.update_state import UpdateRunStore
    manager, _, _, _ = setup
    store = UpdateRunStore(manager.base_dir)
    record = store.create("mercado_credito_sgs", periods=[])
    record["status"] = status
    store.save(record)
    assert prepare(setup, ["mercado_credito_sgs"])[2] == ["mercado_credito_sgs"]


def test_corrupt_special_adapter_run_blocks_and_preserves_evidence(setup):
    from utils.ifdata_cache.update_state import UpdateRunStore, UpdateStateError
    manager, _, _, _ = setup
    store = UpdateRunStore(manager.base_dir)
    record = store.create("mercado_credito_sgs", periods=[])
    path = store.root / record["run_id"] / "run.json"
    path.write_text("{corrupt")
    with pytest.raises(UpdateStateError, match="ilegível"):
        prepare(setup, ["mercado_credito_sgs"])
    assert path.read_text() == "{corrupt"
