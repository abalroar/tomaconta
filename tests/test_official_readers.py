"""Opt-in oficial: pin por render, isolamento do worker e zero fallback remoto."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import threading

import pandas as pd
import pytest

from utils.ifdata_cache import official_store as S
from utils.ifdata_cache.base import CacheResult
from utils.ifdata_cache.manager import CacheManager
from utils.ifdata_cache.principal import PrincipalCache
from utils.ifdata_cache.cosif_4010 import Cosif4010Cache, LOADER_VERSION, SOURCE_COLUMNS
from utils.ifdata_cache.taxas_juros_historico import TaxasJurosHistoricoCache, FACT_REQUIRED_COLUMNS, load_taxas_juros_historico_dimension
from utils.ifdata_cache.scr_data import SCRDataCache, FACT_COLUMNS, RESUMO_COLUMNS
from utils.ifdata_cache.spb_meios_pagamento import SPBMeiosPagamentoCache


@pytest.fixture(autouse=True)
def isolated_context(monkeypatch):
    token = S._READ_CONTEXT.set(None)
    writable = S._WRITABLE_CONTEXT.set(False)
    monkeypatch.delenv("TOMACONTA_OFFICIAL_STORE_DIR", raising=False)
    monkeypatch.delenv("TOMACONTA_IFDATA_REGISTRY_DIR", raising=False)
    yield
    S._READ_CONTEXT.reset(token)
    S._WRITABLE_CONTEXT.reset(writable)


def _artifacts(root, cache, frame, extras=None, metadata_extra=None):
    directory = root / "data/cache" / cache.config.subdir
    directory.mkdir(parents=True, exist_ok=True)
    data = directory / cache.config.arquivo_dados
    frame.to_parquet(data, index=False)
    metadata = {"total_registros": len(frame), "colunas": list(frame.columns),
                "timestamp_salvamento": "2000-01-01T00:00:00", **(metadata_extra or {})}
    meta = directory / cache.config.arquivo_metadata
    meta.write_text(json.dumps(metadata))
    mapping = {path.relative_to(root).as_posix(): path for path in (data, meta)}
    for name, content in (extras or {}).items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, pd.DataFrame):
            content.to_parquet(path, index=False)
        else:
            path.write_text(json.dumps(content))
        mapping[path.relative_to(root).as_posix()] = path
    return mapping


def _enable(monkeypatch, tmp_path, artifacts, *, app=None):
    store = S.LocalRevisionStore(tmp_path / "official")
    staged = store.stage(artifacts)
    store.activate(staged.revision_id, expected_parent=None)
    monkeypatch.setenv("TOMACONTA_OFFICIAL_STORE_DIR", str(store.root))
    app = app or tmp_path / "app"
    S.begin_official_read(app)
    return store, staged, app


def _frame(value=1):
    return pd.DataFrame({"Instituição": ["Banco Teste"], "Período": ["2/2026"], "Ativo Total": [value]})


def _forbidden(*args, **kwargs):
    raise AssertionError("Leitura oficial não pode travar, baixar ou escrever")


def test_official_reader_ignores_legacy_and_ttl_without_lock_or_network(monkeypatch, tmp_path):
    source = tmp_path / "source"
    mapping = _artifacts(source, PrincipalCache(source), _frame(10))
    _, revision, app = _enable(monkeypatch, tmp_path, mapping)
    # Runtime/bundle divergentes no projeto jamais eclipsam a revisão.
    for subdir in ("cache", "bundled"):
        directory = app / "data" / subdir / "principal"
        directory.mkdir(parents=True)
        _frame(999).to_parquet(directory / "dados.parquet")
    import utils.ifdata_cache.update_state as U
    monkeypatch.setattr(U, "mutation_lock", _forbidden)
    cache = PrincipalCache(app)
    monkeypatch.setattr(cache, "baixar_remoto", _forbidden)
    result = cache.carregar()
    assert result.sucesso and result.dados["Ativo Total"].tolist() == [10]
    assert cache.read_data_file == revision.resolve("data/cache/principal/dados.parquet")
    assert cache.get_info()["official_revision_id"] == revision.revision_id
    assert cache.coherent_read_paths()[1].parent == cache.read_data_file.parent
    assert not list(revision.root.rglob("*.lock"))


def test_render_pin_and_compat_manager_change_only_on_next_begin(monkeypatch, tmp_path):
    from utils.ifdata_cache import get_manager as get_cache_manager
    source = tmp_path / "source"
    mapping = _artifacts(source, PrincipalCache(source), _frame(10))
    store, first, app = _enable(monkeypatch, tmp_path, mapping)
    manager = get_cache_manager()
    other = tmp_path / "other"
    mapping2 = _artifacts(other, PrincipalCache(other), _frame(20))
    second = store.stage(mapping2, parent_revision=first.revision_id)
    store.activate(second.revision_id, expected_parent=first.revision_id)
    assert get_cache_manager() is manager
    assert manager.carregar("principal").dados["Ativo Total"].tolist() == [10]
    S.begin_official_read(app)
    fresh = get_cache_manager()
    assert fresh is not manager
    assert fresh.carregar("principal").dados["Ativo Total"].tolist() == [20]
    assert manager.get_cache("principal").read_data_file.is_relative_to(first.root)


def test_read_context_is_independent_between_threads(monkeypatch, tmp_path):
    mapping = _artifacts(tmp_path / "source", PrincipalCache(tmp_path / "source"), _frame(10))
    _, revision, app = _enable(monkeypatch, tmp_path, mapping)
    from utils.ifdata_cache import get_manager as get_cache_manager
    original = get_cache_manager()
    results = []
    def render():
        S.begin_official_read(app)
        results.append(get_cache_manager())
    thread = threading.Thread(target=render)
    thread.start()
    thread.join(timeout=5)
    assert not thread.is_alive() and len(results) == 1
    assert results[0] is not original
    assert results[0]._official_snapshot.revision_id == revision.revision_id


def test_explicit_worker_workspace_is_writable_even_with_official_pin(monkeypatch, tmp_path):
    mapping = _artifacts(tmp_path / "source", PrincipalCache(tmp_path / "source"), _frame(10))
    _, revision, _ = _enable(monkeypatch, tmp_path, mapping)
    worker = CacheManager(tmp_path / "worker")
    cache = worker.get_cache("principal")
    assert cache._official_snapshot is None
    assert worker.salvar("principal", _frame(30)).sucesso
    assert worker.carregar("principal").dados["Ativo Total"].tolist() == [30]
    assert PrincipalCache(tmp_path / "worker")._official_snapshot is None
    assert pd.read_parquet(revision.resolve("data/cache/principal/dados.parquet"))["Ativo Total"].tolist() == [10]


def test_cold_worker_construction_does_not_initialize_or_pin_official_store(monkeypatch, tmp_path):
    monkeypatch.setenv("TOMACONTA_OFFICIAL_STORE_DIR", str(tmp_path / "not-initialized"))
    manager = CacheManager(tmp_path / "worker")
    assert manager.get_cache("principal")._official_snapshot is None
    assert PrincipalCache(tmp_path / "worker")._official_snapshot is None
    assert not (tmp_path / "not-initialized").exists()


@pytest.mark.parametrize("root_kind", ["project", "snapshot", "cold_snapshot"])
def test_explicit_project_and_revision_roots_cannot_become_writable(monkeypatch, tmp_path, root_kind):
    source = tmp_path / "source"
    mapping = _artifacts(source, PrincipalCache(source), _frame())
    _, revision, app = _enable(monkeypatch, tmp_path, mapping)
    root = app if root_kind == "project" else revision.root
    if root_kind == "cold_snapshot":
        S._READ_CONTEXT.set(None)
    manager = CacheManager(root)
    assert manager._official_snapshot.revision_id == revision.revision_id
    with pytest.raises(S.OfficialReadOnlyError):
        manager.salvar("principal", _frame(77))
    with pytest.raises(S.OfficialReadOnlyError):
        manager.extrair_periodos_com_salvamento("principal", ["202606"])
    assert not list(revision.root.rglob("*.lock"))


def test_explicit_legacy_import_requires_writable_context(monkeypatch, tmp_path):
    monkeypatch.setenv("TOMACONTA_OFFICIAL_STORE_DIR", str(tmp_path / "not-initialized"))
    with S.writable_cache_context():
        manager = CacheManager(tmp_path / "legacy")
    assert manager._official_snapshot is None
    assert manager.salvar("principal", _frame()).sucesso


@pytest.mark.parametrize("action", ["save", "clean", "extract", "extract_save", "download", "force"])
def test_official_mutation_is_rejected_before_lock_or_http(monkeypatch, tmp_path, action):
    mapping = _artifacts(tmp_path / "source", PrincipalCache(tmp_path / "source"), _frame())
    _, revision, app = _enable(monkeypatch, tmp_path, mapping)
    manager = CacheManager()
    cache = manager.get_cache("principal")
    import utils.ifdata_cache.update_state as U
    monkeypatch.setattr(U, "mutation_lock", _forbidden)
    actions = {"save": lambda: cache.salvar_local(_frame()), "clean": cache.limpar_local,
               "extract": lambda: cache.extrair_periodo("202606"),
               "extract_save": lambda: manager.extrair_periodos_com_salvamento("principal", ["202606"]),
               "download": cache.baixar_remoto, "force": lambda: cache.carregar(forcar_remoto=True)}
    with pytest.raises(S.OfficialReadOnlyError):
        actions[action]()
    assert not list(revision.root.rglob("*.lock"))


def test_configured_missing_store_does_not_use_legacy(monkeypatch, tmp_path):
    monkeypatch.setenv("TOMACONTA_OFFICIAL_STORE_DIR", str(tmp_path / "empty"))
    with pytest.raises(S.StoreNotInitialized):
        S.begin_official_read(tmp_path / "app")
    assert not (tmp_path / "empty").exists()


def test_subset_snapshot_manager_info_reports_optional_absence_without_fallback(monkeypatch, tmp_path):
    source = tmp_path / "source"
    mapping = _artifacts(source, PrincipalCache(source), _frame())
    _, revision, app = _enable(monkeypatch, tmp_path, mapping)
    manager = CacheManager()
    infos = manager.info()
    assert len(infos) == len(manager.listar_caches())
    assert infos["principal"]["existe"]
    for key in ("cosif_4010", "taxas_juros_historico", "scr_data", "spb_meios_pagamento"):
        cache = manager.get_cache(key)
        assert cache is not None
        assert not infos[key]["existe"]
        assert infos[key]["official_cache_status"] == "absent"
        assert infos[key]["official_revision_id"] == revision.revision_id
        assert not cache.carregar().sucesso
        if hasattr(cache, "bootstrap_local_assets"):
            assert not cache.bootstrap_local_assets().sucesso


def test_partial_cache_is_distinguished_from_absence_and_cannot_download(monkeypatch, tmp_path):
    source = tmp_path / "source"
    mapping = _artifacts(source, PrincipalCache(source), _frame())
    mapping.pop("data/cache/principal/metadata.json")
    _, _, app = _enable(monkeypatch, tmp_path, mapping)
    cache = PrincipalCache(app)
    monkeypatch.setattr(cache, "baixar_remoto", _forbidden)
    assert cache.get_info()["official_cache_status"] == "partial"
    assert "erro_metadata" in cache.get_info()
    assert cache.carregar().metadata["official_cache_status"] == "partial"


def test_legacy_default_remains_writable_and_uses_original_root(tmp_path):
    cache = PrincipalCache(tmp_path)
    assert cache._official_snapshot is None and cache.base_dir == tmp_path
    assert cache.salvar_local(_frame(3)).sucesso
    assert cache.carregar_local().dados["Ativo Total"].tolist() == [3]


def test_special_bootstrap_and_dimension_reads_are_pure(monkeypatch, tmp_path):
    source = tmp_path / "source"
    taxas = TaxasJurosHistoricoCache(source)
    frame = pd.DataFrame([{name: "x" for name in FACT_REQUIRED_COLUMNS}])
    mapping = _artifacts(source, taxas, frame, extras={
        "historico_manifest.json": {}, "dim_parametros.parquet": pd.DataFrame({"id": [1]}),
        "dim_datas.parquet": pd.DataFrame({"id": [2]}), "dim_instituicoes.parquet": pd.DataFrame({"id": [3]}),
    })
    _, revision, app = _enable(monkeypatch, tmp_path, mapping)
    import utils.ifdata_cache.update_state as U
    monkeypatch.setattr(U, "mutation_lock", _forbidden)
    official = TaxasJurosHistoricoCache(app)
    assert official.bootstrap_local_assets().sucesso
    assert official.carregar().sucesso
    assert load_taxas_juros_historico_dimension(official, name="datas")["id"].tolist() == [2]
    with pytest.raises(S.OfficialReadOnlyError):
        official.bootstrap_local_assets(force=True)
    assert not list(revision.root.rglob("*.lock"))


def test_scr_annual_and_dimensions_use_pinned_revision_and_missing_year_fails_closed(monkeypatch, tmp_path):
    source = tmp_path / "source"
    cache = SCRDataCache(source)
    summary = pd.DataFrame([{key: "x" for key in RESUMO_COLUMNS}])
    fact = pd.DataFrame([{key: ("2026-06" if key == "data_base" else 1) for key in FACT_COLUMNS}])
    extras = {"historico_manifest.json": {}, "staging/annual/2026.parquet": fact,
              **{path.name: pd.DataFrame({"id": [index]}) for index, path in enumerate(cache.dimension_paths().values())}}
    mapping = _artifacts(source, cache, summary, extras)
    _, revision, app = _enable(monkeypatch, tmp_path, mapping)
    official = SCRDataCache(app)
    monkeypatch.setattr(official, "_baixar_asset", _forbidden)
    assert official.bootstrap_local_assets().sucesso
    assert len(official.carregar_detalhe(anos=[2026])) == 1
    assert set(official.carregar_dimensoes()) == {"produto", "porte", "geo", "segmento"}
    with pytest.raises(S.OfficialStoreError, match="não declarado"):
        official.carregar_detalhe(anos=[2025])
    assert not (revision.root / "data/cache/scr_data/staging/annual/2025.parquet").exists()


def test_spb_declared_extras_use_official_and_undeclared_extra_cannot_download(monkeypatch, tmp_path):
    source = tmp_path / "source"
    cache = SPBMeiosPagamentoCache(source)
    main = cache.config.arquivo_dados.removesuffix(".parquet")
    extra = next(key for key in cache.dataset_paths() if key != main)
    frame = pd.DataFrame({"trimestre": ["20262"]})
    mapping = _artifacts(source, cache, frame, extras={f"{extra}.parquet": frame,
                       "spb_manifest.json": {"datasets": {main: 1, extra: 1}}})
    _, _, app = _enable(monkeypatch, tmp_path, mapping)
    official = SPBMeiosPagamentoCache(app)
    assert official.bootstrap_local_assets().sucesso
    assert set(official.read_dataset_paths()) == {main, extra}
    assert official.carregar_dataset(extra).dados["trimestre"].tolist() == ["20262"]
    missing = next(key for key in cache.dataset_paths() if key not in {main, extra})
    with pytest.raises(S.OfficialStoreError, match="não declarado"):
        official.carregar_dataset(missing)


def test_cosif_override_paths_and_availability_remain_official(monkeypatch, tmp_path):
    source = tmp_path / "source"
    cache = Cosif4010Cache(source)
    row = dict.fromkeys(SOURCE_COLUMNS, "")
    row.update(DATA_BASE="202606", DOCUMENTO="4010", CNPJ="00000001", CONTA="3822000003", SALDO=1.0,
               NOME_INSTITUICAO="Banco Teste", NOME_CONGL="Grupo", **{"Período": "202606", "GRUPO_FONTE": "Bancos", "ARQUIVO_FONTE": "202606BANCOS.csv.zip"})
    mapping = _artifacts(source, cache, pd.DataFrame([row]), metadata_extra={"schema_version": LOADER_VERSION, "periodos": ["202606"]})
    data = source / "data/cache" / cache.config.subdir / cache.config.arquivo_dados
    metadata = source / "data/cache" / cache.config.subdir / cache.config.arquivo_metadata
    payload = json.loads(metadata.read_text())
    payload["sha256"] = hashlib.sha256(data.read_bytes()).hexdigest()
    metadata.write_text(json.dumps(payload))
    _, revision, app = _enable(monkeypatch, tmp_path, mapping)
    official = Cosif4010Cache(app)
    monkeypatch.setattr(official, "baixar_remoto", _forbidden)
    official.ensure_available()
    assert official.available_periods() == ["202606"]
    assert official.carregar().sucesso
    assert official.arquivo_dados.is_relative_to(revision.root)


def test_registry_and_catalog_are_pinned_without_remote_fallback(monkeypatch, tmp_path):
    from utils.ifdata_cache.institution_registry import save_registry, load_persisted_registry, extract_registry
    from utils.ifdata_cache.institutions import load_conglomerados_catalog
    source = tmp_path / "source"
    registry = save_registry(pd.DataFrame({"CodInst": ["C123"], "NomeInstituicao": ["Banco Teste"]}), "202606", source="fixture", base_dir=source)
    csv = source / "conglomerados.csv"
    csv.write_text("Conglomerado CDIGO 1234 NOME GRUPO TESTE TIPO PRUDENCIAL CNPJ 00000001 BANCO TESTE LIDER")
    mapping = {registry.relative_to(source).as_posix(): registry, "conglomerados.csv": csv}
    _, _, app = _enable(monkeypatch, tmp_path, mapping)
    monkeypatch.setenv("TOMACONTA_IFDATA_REGISTRY_DIR", str(tmp_path / "override"))
    assert load_persisted_registry("202606", app)["CodInst"].tolist() == ["C123"]
    assert load_persisted_registry("202606")["CodInst"].tolist() == ["C123"]
    assert load_conglomerados_catalog(app)[0]["nome"] == "GRUPO TESTE"
    with pytest.raises(S.OfficialStoreError):
        load_persisted_registry("202603", app)
    with pytest.raises(S.OfficialReadOnlyError):
        extract_registry("202606", _forbidden, base_dir=app)


def test_bloprudencial_raw_compat_reader_uses_official_parquet_without_http(monkeypatch, tmp_path):
    from utils.ifdata_cache.bloprudencial_cache import BloprudencialCache
    from utils.ifdata_cache import bloprudencial as B
    source = tmp_path / "source"
    cache = BloprudencialCache(source)
    frame = pd.DataFrame({"Período": ["202606", "202605"], "DATA_BASE": ["202606", "202605"],
                          "CONTA": ["3822000003", "3822000003"], "SALDO": [10.0, 20.0]})
    mapping = _artifacts(source, cache, frame)
    _, revision, app = _enable(monkeypatch, tmp_path, mapping)
    monkeypatch.setattr(B, "download_bloprudencial_zip", _forbidden)
    monkeypatch.setattr(B, "_ensure_dirs", _forbidden)
    assert B.load_bloprudencial_df("202606")["SALDO"].tolist() == [10.0]
    assert B.load_bloprudencial_df_cached("202605", cache_dir=str(app / "data/cache/bcb_bloprudencial"))["SALDO"].tolist() == [20.0]
    with pytest.raises(S.OfficialReadOnlyError):
        B.load_bloprudencial_df("202606", force_refresh=True)
    assert not list(revision.root.rglob("*.lock"))
