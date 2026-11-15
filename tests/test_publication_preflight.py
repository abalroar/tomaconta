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
        if (name in R.INDIVIDUAL_CACHE_QUALITY_SPECS or name in R.CACHE_FRAME_QUALITY_VALIDATORS
            or name in R.INSTITUTION_NAMED_CACHE_NAMES)
    })
    return manager, release, remote, confirmations


def details(selected):
    return [{"cache": target, "status": "ok", "message": "ok"} for target in R._materialization_targets(selected)]


def prepare(setup, selected, **kwargs):
    manager, release, remote, _ = setup
    return R.prepare_release_publication(
        manager, selected_caches=selected, materialization_details=details(selected),
        release_config=release, remote_manifest=remote, **kwargs,
    )


def native_cache(setup, name):
    manager, _, _, _ = setup
    cache = Cache(manager.base_dir, name)
    manager.caches[name] = cache
    cache.manifest_path = cache.arquivo_dados.with_name("native_manifest.json")
    extras = {}
    if name == "spb_meios_pagamento":
        paths = {"main": cache.arquivo_dados,
                 "declared": cache.arquivo_dados.with_name("declared.parquet"),
                 "optional": cache.arquivo_dados.with_name("optional.parquet")}
        cache.dataset_paths = lambda: paths
        cache.manifest_path.write_text(json.dumps({"datasets": {"main": 1, "declared": 1}}))
        extras[paths["declared"]] = f"{name}_declared.parquet"
    else:
        paths = {key: cache.arquivo_dados.with_name(f"dim_{key}.parquet")
                 for key in ("first", "second")}
        cache.dimension_paths = lambda: paths
        cache.manifest_path.write_text(json.dumps({"finalized": True}))
        extras.update({path: f"{name}_dim_{key}.parquet" for key, path in paths.items()})
        if name == "scr_data":
            cache.annual_path = lambda year: cache.arquivo_dados.with_name(f"{year}.parquet")
            metadata = json.loads(cache.arquivo_metadata.read_text())
            metadata["anos_materializados"] = ["2026"]
            cache.arquivo_metadata.write_text(json.dumps(metadata))
            extras[cache.annual_path("2026")] = "scr_data_ano_2026.parquet"
    for path in extras:
        pd.DataFrame({"Valor": [1]}).to_parquet(path)
    extras[cache.manifest_path] = f"{name}_manifest.json"
    # Match the native legacy collector: absent extras are silently omitted.
    cache.extra_release_assets = lambda: [(path, asset) for path, asset in extras.items() if path.exists()]
    return cache


@pytest.mark.parametrize("name", ["taxas_juros_historico", "scr_data"])
def test_missing_native_dimension_blocks_publication_even_if_collector_omits_it(setup, name):
    cache = native_cache(setup, name)
    cache.dimension_paths()["second"].unlink()
    with pytest.raises(ValueError, match="asset obrigatório ausente: dim_second.parquet"):
        prepare(setup, [name])


@pytest.mark.parametrize("name", ["taxas_juros_historico", "scr_data", "spb_meios_pagamento"])
def test_missing_native_manifest_blocks_publication(setup, name):
    cache = native_cache(setup, name)
    cache.manifest_path.unlink()
    with pytest.raises(ValueError, match="asset obrigatório ausente: native_manifest.json"):
        prepare(setup, [name])


@pytest.mark.parametrize("section", [None, "extra", "info_extra"])
def test_scr_declared_annual_asset_is_mandatory(setup, section):
    cache = native_cache(setup, "scr_data")
    if section:
        metadata = json.loads(cache.arquivo_metadata.read_text())
        metadata[section] = {"anos_materializados": metadata.pop("anos_materializados")}
        cache.arquivo_metadata.write_text(json.dumps(metadata))
    cache.annual_path("2026").unlink()
    with pytest.raises(ValueError, match="asset obrigatório ausente: 2026.parquet"):
        prepare(setup, ["scr_data"])


def test_missing_spb_declared_dataset_blocks_publication(setup):
    cache = native_cache(setup, "spb_meios_pagamento")
    cache.dataset_paths()["declared"].unlink()
    with pytest.raises(ValueError, match="asset obrigatório ausente: declared.parquet"):
        prepare(setup, ["spb_meios_pagamento"])


@pytest.mark.parametrize("datasets", [[], {"unknown": 1}])
def test_spb_declared_dataset_keys_must_be_known(setup, datasets):
    cache = native_cache(setup, "spb_meios_pagamento")
    cache.manifest_path.write_text(json.dumps({"datasets": datasets}))
    with pytest.raises(ValueError, match="datasets declarados no manifesto inválidos"):
        prepare(setup, ["spb_meios_pagamento"])


def test_spb_does_not_require_undeclared_optional_dataset(setup):
    cache = native_cache(setup, "spb_meios_pagamento")
    assert not cache.dataset_paths()["optional"].exists()
    _, _, names, assets = prepare(setup, ["spb_meios_pagamento"])
    assert names == ["spb_meios_pagamento"]
    assert "spb_meios_pagamento_declared.parquet" in [name for _, name in assets]


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


def test_legacy_manifest_sections_keep_unrelated_entries_and_update_published_hashes(setup):
    _, _, remote, _ = setup
    remote["published_assets"] = {
        "mercado_credito_sgs_dados.parquet": {"sha256": "old-data", "bytes": 1, "owner": "sgs"},
        "mercado_credito_sgs_metadata.json": {"sha256": "old-metadata", "bytes": 2},
        "principal_dados.parquet": {"sha256": "unchanged", "bytes": 3},
        "external.parquet": {"sha256": "external", "bytes": 4},
    }
    remote["expected_periods_by_cache"] = {"mercado_credito_sgs": "202512", "principal": "202512", "external": "202401"}
    remote["publication_id"] = "legacy-publication"
    remote["run_id"] = "legacy-run"
    path, payload, _, _ = prepare(setup, ["mercado_credito_sgs"])
    for asset in payload["publication_assets"]:
        record = payload["published_assets"][asset["name"]]
        assert record["sha256"] == asset["sha256"]
        assert record["bytes"] == asset["size_bytes"]
    assert payload["published_assets"]["mercado_credito_sgs_dados.parquet"]["owner"] == "sgs"
    assert payload["published_assets"]["principal_dados.parquet"] == remote["published_assets"]["principal_dados.parquet"]
    assert payload["published_assets"]["external.parquet"] == remote["published_assets"]["external.parquet"]
    assert payload["expected_periods_by_cache"] == {"mercado_credito_sgs": "202603", "principal": "202512", "external": "202401"}
    assert payload["previous_publication_id"] == "legacy-publication"
    assert payload["publication_id"] != "legacy-publication"
    assert payload["run_id"] != "legacy-run"
    assert payload["publication_id"] == payload["run_id"] == path.parent.name


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


def test_monthly_publication_prepares_other_consumers_of_required_sources(setup):
    manager, _, _, _ = setup
    pd.DataFrame({"Período": ["1/2026"], "Valor": [2]}).to_parquet(manager.get_cache("ativo").arquivo_dados)
    _, payload, names, _ = prepare(setup, ["bloprudencial", "ativo"])
    assert names == ["ativo", "bloprudencial", "derived_metrics", "critical_screens"]
    assert payload["postprocess_targets"] == ["derived_metrics", "critical_screens"]


def test_changed_source_is_uploaded_when_all_consumers_are_prepared(setup):
    manager, _, _, _ = setup
    pd.DataFrame({"Período": ["1/2026"], "Valor": [2]}).to_parquet(manager.get_cache("passivo").arquivo_dados)
    _, manifest, names, assets = prepare(setup, ["principal", "passivo"])
    assert "passivo" in names
    assert "passivo_dados.parquet" in [name for _, name in assets]
    assert manifest["caches"]["passivo"]["sha256"] == hashlib.sha256(manager.get_cache("passivo").arquivo_dados.read_bytes()).hexdigest()


def test_old_protected_bundle_cannot_replace_unselected_retified_remote_source(setup, monkeypatch):
    from utils.ifdata_cache.principal import PrincipalCache

    manager, release, remote, confirmations = setup
    cache = PrincipalCache(manager.base_dir)
    manager.caches["principal"] = cache
    frame = pd.DataFrame({"Período": ["1/2026"], "Valor": [1]})
    for directory in (cache.bundled_dir, cache.cache_dir):
        directory.mkdir(parents=True)
        frame.to_parquet(directory / "dados.parquet")
        metadata = {"periodos": ["1/2026"], "total_registros": 1}
        if directory == cache.bundled_dir:
            metadata["publication_id"] = "old-publication"
        (directory / "metadata.json").write_text(json.dumps(metadata))
    assert cache.arquivo_dados == cache.bundled_data_file
    remote["caches"]["principal"]["sha256"] = hashlib.sha256(b"retified remote source").hexdigest()
    mutations = []
    monkeypatch.setattr(R, "upload_release_assets", lambda **kwargs: mutations.append(kwargs))
    with pytest.raises(ValueError, match="principal: fonte não selecionada diverge.*explicitamente"):
        _, _, _, assets = prepare(setup, ["bloprudencial"])
        R.upload_release_assets(repo=release.repo, tag=release.tag, assets=assets, token="fake")
    assert confirmations == mutations == []
    assert not (manager.base_dir / "data/cache/publications").exists()


def test_quarterly_reference_does_not_advance_with_old_unrelated_individual(setup):
    _, _, remote, _ = setup
    for name in ("principal_individual", "dre_individual", "derived_metrics_individual"):
        remote["caches"][name]["max_period_ref"] = "202512"
    _, manifest, _, _ = prepare(setup, ["principal"], expected_periods={"quarterly": "202603"})
    assert manifest["expected_periods"]["quarterly"] == "202512"


@pytest.mark.parametrize("remote", [{"caches": {}}, {"caches": []}, {"caches": {"x": {}}, "release": {"repo": "wrong", "tag": "wrong"}}])
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


@pytest.mark.parametrize("extra", [
    {"falhas": ["1"]}, {"remaining_windows": 1}, {"finalized": False}, {"truncado": True},
    {"persistence_error": "disk"}, {"checkpoint_error": "disk"}, {"callback_error": "disk"},
])
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


@pytest.mark.parametrize("content", [b"{malformed", b"[]"])
def test_network_confirmation_rejects_invalid_metadata_before_legacy_hash_fallback(monkeypatch, content):
    response = SimpleNamespace(status_code=200, iter_content=lambda **kwargs: [content], close=lambda: None)
    monkeypatch.setattr(R, "_request_with_retries", lambda *args, **kwargs: response)
    with pytest.raises(RuntimeError, match="metadata remota inválida"):
        R._confirm_remote_source(get_release_config(), "ativo", hashlib.sha256(b"expected").hexdigest(), None,
                                 "ativo_metadata.json")


def test_monthly_source_missing_target_blocks_publication(setup):
    with pytest.raises(ValueError, match="alvo"):
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


def test_known_empty_manifest_initializes_closed_package_without_losing_sources(setup):
    manager, release, _, _ = setup
    _, manifest, names, _ = R.prepare_release_publication(
        manager, selected_caches=["principal"], materialization_details=details(["principal"]),
        release_config=release, remote_manifest={},
    )
    assert set(names) == set(R._publication_scope(["principal"])[0] + R._publication_scope(["principal"])[1])
    assert manifest["publication_validation"]["previous_manifest_sha256"] is None


def test_legacy_source_without_metadata_hash_reuses_only_after_both_byte_confirmations(setup, monkeypatch):
    manager, _, remote, _ = setup
    remote["caches"]["passivo"].pop("metadata_sha256")
    confirmations = []
    monkeypatch.setattr(R, "_confirm_remote_source",
                        lambda release, name, digest, token, asset_name: confirmations.append((name, asset_name, digest)))
    _, payload, names, _ = prepare(setup, ["bloprudencial"])
    assert "passivo" not in names
    assert names == ["bloprudencial", "derived_metrics", "critical_screens"]
    source = manager.get_cache("passivo")
    expected = {"passivo_dados.parquet": R.sha256_file(source.arquivo_dados),
                "passivo_metadata.json": R.sha256_file(source.arquivo_metadata)}
    assert {asset_name: digest for name, asset_name, digest in confirmations if name == "passivo"} == expected
    assert {item["asset"]: item["sha256"] for item in payload["confirmed_source_assets"] if item["cache"] == "passivo"} == expected


def test_legacy_remote_metadata_mismatch_includes_pair_with_all_consumers(setup, monkeypatch):
    manager, _, remote, _ = setup
    remote["caches"]["passivo"].pop("metadata_sha256")

    def confirm(release, name, digest, token, asset_name):
        if asset_name == "passivo_metadata.json":
            raise R.RemoteAssetHashMismatch("passivo: hash remoto diverge do manifesto; publicação bloqueada")

    monkeypatch.setattr(R, "_confirm_remote_source", confirm)
    _, payload, names, assets = prepare(setup, ["bloprudencial"])
    assert names == ["passivo", "bloprudencial", "derived_metrics", "critical_screens"]
    assert {name for _, name in assets}.issuperset({"passivo_dados.parquet", "passivo_metadata.json",
                                                  "derived_metrics_dados.parquet", "critical_screens_dados.parquet"})
    assert payload["caches"]["external_cache"] == remote["caches"]["external_cache"]
    assert payload["caches"]["passivo"]["metadata_sha256"] == R.sha256_file(manager.get_cache("passivo").arquivo_metadata)


@pytest.mark.parametrize("asset_name", ["passivo_dados.parquet", "passivo_metadata.json"])
def test_remote_http_failure_never_becomes_implicit_source_replacement(setup, monkeypatch, asset_name):
    _, _, remote, _ = setup
    remote["caches"]["passivo"].pop("metadata_sha256")

    def confirm(release, name, digest, token, requested_asset):
        if requested_asset == asset_name:
            raise RuntimeError("fonte remota indisponível")

    monkeypatch.setattr(R, "_confirm_remote_source", confirm)
    with pytest.raises(RuntimeError, match="fonte remota indisponível"):
        prepare(setup, ["bloprudencial"])


def test_remote_data_hash_mismatch_is_never_swallowed_by_legacy_metadata_fallback(setup, monkeypatch):
    _, _, remote, _ = setup
    remote["caches"]["passivo"].pop("metadata_sha256")

    def confirm(release, name, digest, token, asset_name):
        if asset_name == "passivo_dados.parquet":
            raise R.RemoteAssetHashMismatch("passivo: hash remoto diverge")

    monkeypatch.setattr(R, "_confirm_remote_source", confirm)
    with pytest.raises(R.RemoteAssetHashMismatch, match="hash remoto diverge"):
        prepare(setup, ["bloprudencial"])


def test_reused_source_change_blocks_upload_before_http(setup):
    manager, release, _, _ = setup
    _, _, _, assets = prepare(setup, ["principal"])
    manager.get_cache("dre").arquivo_metadata.write_text('{"periodos": ["2/2026"]}')
    with pytest.raises(ValueError, match="candidato mudou.*dre_metadata"):
        R.upload_release_assets(repo=release.repo, tag=release.tag, assets=assets, token="fake")


@pytest.mark.parametrize("cache_name,result", [
    ("principal", {"status": "partial", "pending_periods": ["202603"]}),
    ("ativo", {"status": "extracting"}),
    ("capital", {"status": "partial", "failed_periods": {"202603": "falhou"}}),
    ("dre", {"status": "failed", "checkpoint_error": "disk"}),
    ("bloprudencial", {"status": "failed", "persistence_error": "disk"}),
])
def test_pending_result_of_any_source_blocks_publish_only(setup, cache_name, result):
    from utils.ifdata_cache.update_state import write_cache_update_result
    manager, _, _, _ = setup
    payload = {"requested_periods": ["202603"], "persisted_periods": [],
               "pending_periods": ["202603"], "failed_periods": {}, **result}
    write_cache_update_result(manager.base_dir, cache_name, payload)
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
        "status": "saved", "requested_periods": ["202603"], "persisted_periods": ["202603"],
        "pending_periods": [], "failed_periods": {},
    })
    assert prepare(setup, ["mercado_credito_sgs"])[2] == ["mercado_credito_sgs"]


@pytest.mark.parametrize("status", ["prepared", "extracting", "partial", "failed"])
def test_latest_incomplete_run_blocks_even_with_previous_saved_ledger(setup, status):
    from utils.ifdata_cache.update_state import UpdateRunStore, write_cache_update_result
    manager, _, _, _ = setup
    write_cache_update_result(manager.base_dir, "mercado_credito_sgs", {
        "status": "saved", "requested_periods": ["202603"], "persisted_periods": ["202603"],
        "pending_periods": [], "failed_periods": {},
    })
    store = UpdateRunStore(manager.base_dir)
    record = store.create("mercado_credito_sgs", periods=["202606"])
    store.finish(record, status)
    with pytest.raises(ValueError, match="execução registrada incompleta"):
        prepare(setup, ["mercado_credito_sgs"])


@pytest.mark.parametrize("status", ["validating", "publishing", "publish_failed"])
def test_complete_ledger_allows_publication_retry_status(setup, status):
    from utils.ifdata_cache.update_state import UpdateRunStore, write_cache_update_result
    manager, _, _, _ = setup
    store = UpdateRunStore(manager.base_dir)
    record = store.create("mercado_credito_sgs", periods=["202603"])
    receipt = {"status": "saved", "run_id": record["run_id"],
               "requested_periods": ["202603"], "persisted_periods": ["202603"],
               "pending_periods": [], "failed_periods": {}}
    write_cache_update_result(manager.base_dir, "mercado_credito_sgs", receipt)
    record = store.record_result(record, receipt)
    store.finish(record, status, error="network" if status == "publish_failed" else None)
    assert prepare(setup, ["mercado_credito_sgs"])[2] == ["mercado_credito_sgs"]


def test_superseded_old_receipt_does_not_block_complete_ledger(setup):
    from utils.ifdata_cache.update_state import UpdateRunStore, write_cache_update_result
    manager, _, _, _ = setup
    store = UpdateRunStore(manager.base_dir)
    old = store.create("mercado_credito_sgs", periods=["202603"])
    write_cache_update_result(manager.base_dir, "mercado_credito_sgs", {
        "status": "saved", "requested_periods": ["202603"], "persisted_periods": ["202603"],
        "pending_periods": [], "failed_periods": {},
    })
    store.finish(old, "superseded")
    assert prepare(setup, ["mercado_credito_sgs"])[2] == ["mercado_credito_sgs"]


def test_successful_materialization_replaces_failed_target_ledger(setup, monkeypatch):
    from utils.ifdata_cache.update_state import load_cache_update_result, write_cache_update_result
    manager, _, _, _ = setup
    write_cache_update_result(manager.base_dir, "derived_metrics", {
        "status": "failed", "requested_periods": ["materialization"], "persisted_periods": [],
        "pending_periods": ["materialization"], "failed_periods": {"materialization": "old error"},
    })
    monkeypatch.setattr(R, "_hydrate_source_caches", lambda *args, **kwargs: ([], []))
    result = SimpleNamespace(sucesso=True, mensagem="saved")
    monkeypatch.setattr(R, "materialize_derived_metrics_cache", lambda **kwargs: result)
    monkeypatch.setattr(R, "materialize_critical_screens_cache", lambda **kwargs: result)
    output = R.materialize_for_publication(manager, cache_names=["principal"], base_dir=manager.base_dir)
    assert all(item["status"] == "ok" for item in output)
    receipt = load_cache_update_result(manager.base_dir, "derived_metrics")
    assert receipt["status"] == "saved"
    assert receipt["pending_periods"] == []
    assert receipt["persisted_periods"] == ["materialization"]
    assert prepare(setup, ["principal"])[2] == ["principal", "derived_metrics", "critical_screens"]


def test_failed_materialization_keeps_target_pending(setup, monkeypatch):
    from utils.ifdata_cache.update_state import load_cache_update_result
    manager, _, _, _ = setup
    monkeypatch.setattr(R, "_hydrate_source_caches", lambda *args, **kwargs: ([], ["dre: failed"]))
    output = R.materialize_for_publication(manager, cache_names=["principal"], base_dir=manager.base_dir)
    assert all(item["status"] == "erro" for item in output)
    receipt = load_cache_update_result(manager.base_dir, "derived_metrics")
    assert receipt["status"] == "failed"
    assert receipt["pending_periods"] == ["materialization"]
    with pytest.raises(ValueError, match="atualização registrada incompleta"):
        prepare(setup, ["principal"])


def test_selfservice_materialization_keeps_bundle_sync_explicit(setup, monkeypatch):
    manager, _, _, _ = setup
    monkeypatch.setattr(R, "_hydrate_source_caches", lambda *args, **kwargs: ([], []))
    result = SimpleNamespace(sucesso=True, mensagem="saved")
    monkeypatch.setattr(R, "materialize_derived_metrics_cache", lambda **kwargs: result)
    calls = []

    def critical(**kwargs):
        calls.append(kwargs)
        return result

    monkeypatch.setattr(R, "materialize_critical_screens_cache", critical)
    output = R.materialize_for_publication(manager, cache_names=["bloprudencial"])
    assert all(item["status"] == "ok" for item in output)
    assert len(calls) == 1
    assert calls[0]["save_bundled"] is False


class Response:
    def __init__(self, status, payload=None, content=b""):
        self.status_code, self.payload, self.content = status, payload, content
        self.text = content.decode("utf-8", errors="replace")

    def json(self):
        if self.payload is None:
            raise ValueError("no json")
        return self.payload

    def iter_content(self, **kwargs):
        yield self.content

    def close(self):
        pass


def upload_network(monkeypatch, remote_manifest, *, post_hook=None):
    uploads = []
    mutations = []

    def request(method, url, **kwargs):
        if method == "DELETE":
            mutations.append(url)
            return Response(204)
        assert method == "GET"
        return Response(200, {"upload_url": "https://uploads.example/assets{?name,label}", "assets": []})

    def post(url, **kwargs):
        name = url.split("name=", 1)[1]
        content = kwargs["data"].read()
        uploads.append((name, content))
        if post_hook is not None:
            result = post_hook(name, content)
            if result is not None:
                return result
        return Response(201, {"id": len(uploads), "digest": "sha256:" + hashlib.sha256(content).hexdigest()})

    monkeypatch.setattr(R.requests, "request", request)
    monkeypatch.setattr(R.requests, "post", post)
    monkeypatch.setattr(R, "_fetch_release_manifest", lambda *args: remote_manifest)
    return uploads, mutations


def test_upload_reorders_manifest_last_and_confirms_all_content(setup, monkeypatch):
    _, release, remote, _ = setup
    _, manifest, _, assets = prepare(setup, ["mercado_credito_sgs"])
    uploads, _ = upload_network(monkeypatch, remote)
    result = R.upload_release_assets(repo=release.repo, tag=release.tag,
                                    assets=list(reversed(assets)), token="fake")
    assert uploads[-1][0] == "manifest.json"
    assert result["manifest_verified"] is True
    assert result["verified_assets"] == result["assets"]
    assert result["activation_confirmed"] is False
    assert json.loads(uploads[-1][1]) == manifest


def test_upload_failure_stops_before_manifest_and_reports_partial_assets(setup, monkeypatch):
    _, release, remote, _ = setup
    _, _, _, assets = prepare(setup, ["mercado_credito_sgs"])
    hook = lambda name, content: Response(403, {"message": "blocked"}) if name.endswith("metadata.json") else None
    uploads, _ = upload_network(monkeypatch, remote, post_hook=hook)
    with pytest.raises(RuntimeError, match="Envio incompleto.*manifesto não enviado"):
        R.upload_release_assets(repo=release.repo, tag=release.tag, assets=assets, token="fake")
    assert [name for name, _ in uploads] == ["mercado_credito_sgs_dados.parquet", "mercado_credito_sgs_metadata.json"]


def test_digest_mismatch_stops_before_manifest(setup, monkeypatch):
    _, release, remote, _ = setup
    _, _, _, assets = prepare(setup, ["mercado_credito_sgs"])
    uploads, _ = upload_network(monkeypatch, remote,
                                post_hook=lambda name, content: Response(201, {"id": 1, "digest": "sha256:wrong"}))
    with pytest.raises(RuntimeError, match="hash retornado.*manifesto não enviado"):
        R.upload_release_assets(repo=release.repo, tag=release.tag, assets=assets, token="fake")
    assert [name for name, _ in uploads] == ["mercado_credito_sgs_dados.parquet"]


def test_source_replacement_during_upload_uses_staged_bytes_and_blocks_manifest(setup, monkeypatch):
    manager, release, remote, _ = setup
    _, _, _, assets = prepare(setup, ["mercado_credito_sgs"])
    metadata = manager.get_cache("mercado_credito_sgs").arquivo_metadata
    original = metadata.read_bytes()

    def mutate(name, content):
        if name.endswith("dados.parquet"):
            metadata.write_bytes(b"changed while posting data")

    uploads, _ = upload_network(monkeypatch, remote, post_hook=mutate)
    with pytest.raises(RuntimeError, match="candidato mudou.*manifesto não enviado"):
        R.upload_release_assets(repo=release.repo, tag=release.tag, assets=assets, token="fake")
    assert uploads[1] == ("mercado_credito_sgs_metadata.json", original)
    assert "manifest.json" not in [name for name, _ in uploads]


def test_concurrent_remote_manifest_change_blocks_before_mutation(setup, monkeypatch):
    _, release, remote, _ = setup
    _, _, _, assets = prepare(setup, ["mercado_credito_sgs"])
    uploads, mutations = upload_network(monkeypatch, {**remote, "another_publication": True})
    with pytest.raises(ValueError, match="manifesto remoto mudou"):
        R.upload_release_assets(repo=release.repo, tag=release.tag, assets=assets, token="fake")
    assert uploads == mutations == []


def test_uploaded_asset_fallback_reads_remote_bytes(monkeypatch):
    monkeypatch.setattr(R, "_request_with_retries", lambda *args, **kwargs: Response(200, content=b"verified"))
    R._verify_uploaded_asset("repo/name", "sample.parquet", Response(201, {"id": 42}),
                             hashlib.sha256(b"verified").hexdigest(), "fake")
