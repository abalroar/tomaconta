"""Leitores da aplicação: revisão oficial pinada e ausência de fallback HTTP."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import app1
from utils.ifdata_cache import official_store as S
from utils.ifdata_cache.base import CacheResult
from utils.ifdata_cache.manager import CacheManager


@pytest.fixture(autouse=True)
def isolated_context(monkeypatch):
    token = S._READ_CONTEXT.set(None)
    monkeypatch.delenv("TOMACONTA_OFFICIAL_STORE_DIR", raising=False)
    yield
    S._READ_CONTEXT.reset(token)


def _forbidden(*args, **kwargs):
    raise AssertionError("Leitor oficial não pode baixar/publicar fallback")


def _revision(store, root, frames, *, parent=None, extra=None):
    manager = CacheManager(root)
    artifacts = {}
    for name, frame in frames.items():
        cache = manager.get_cache(name)
        result = cache.salvar_local(frame, fonte="fixture", info_extra=(extra or {}).get(name))
        assert result.sucesso, result.mensagem
        for path in (cache.arquivo_dados_runtime, cache.arquivo_metadata_runtime):
            artifacts[path.relative_to(root).as_posix()] = path
    catalog = root / "conglomerados.csv"
    catalog.write_text("Conglomerado CDIGO 1234 NOME GRUPO TESTE TIPO PRUDENCIAL CNPJ 00000001 BANCO TESTE LIDER")
    artifacts["conglomerados.csv"] = catalog
    return store.stage(artifacts, parent_revision=parent)


def _enable(monkeypatch, tmp_path, frames, *, extra=None):
    store = S.LocalRevisionStore(tmp_path / "store")
    first = _revision(store, tmp_path / "source", frames, extra=extra)
    store.activate(first.revision_id, expected_parent=None)
    app = tmp_path / "app"
    monkeypatch.setenv("TOMACONTA_OFFICIAL_STORE_DIR", str(store.root))
    monkeypatch.setattr(app1, "APP_DIR", app)
    S.begin_official_read(app)
    monkeypatch.setattr(app1.requests, "get", _forbidden)
    monkeypatch.setattr(app1, "_baixar_cache_release_base_cache", _forbidden)
    monkeypatch.setattr(app1, "_download_peers_individual_curated_cache", _forbidden)
    return store, first, app


def _principal(amount=10):
    return pd.DataFrame({"Instituição": ["Banco Teste"], "Período": ["1/2026"],
                         "CodInst": ["C1234"], "Ativo Total": [amount]})


def _carteira():
    periods = ["1/2025", "2/2025", "3/2025", "4/2025", "1/2026"]
    return pd.DataFrame({"Instituição": ["Banco Teste"] * 5, "Período": periods, "CodInst": ["C1234"] * 5,
        "C1": [10.0] * 5, "C2": [10.0] * 5, "C3": [10.0] * 5, "C4": [10.0] * 5, "C5": [60.0] * 5,
        "Carteira não Informada ou não se Aplica": [0.0] * 5, "Total Exterior": [0.0] * 5,
        "Total não Individualizado": [0.0] * 5, "Total Geral": [100.0] * 5,
        "Inadimplência": [2.0] * 5, "Ativos problemáticos": [3.0] * 5})


def test_remote_and_bundled_manifest_are_projected_from_same_official_revision(monkeypatch, tmp_path):
    _, first, _ = _enable(monkeypatch, tmp_path, {"principal": _principal()})
    remote = app1._carregar_manifest_release_cache("https://invalid.test/manifest.json")
    bundled = app1._carregar_manifest_bundled_cache("legacy-token")
    assert remote == bundled
    assert remote["official_revision_id"] == first.revision_id
    assert remote["caches"]["principal"]["sha256"] == first.manifest["files"]["data/cache/principal/dados.parquet"]["sha256"]
    assert remote["caches"]["principal"]["max_period"] == "202603"
    assert remote["caches"]["principal"]["period_count"] == 1
    assert "expected_periods" not in remote


def test_foreign_newer_manifest_cannot_trigger_official_refresh(monkeypatch, tmp_path):
    _, revision, _ = _enable(monkeypatch, tmp_path, {"principal": _principal()})
    manager = app1.get_cache_manager()
    result, status = app1._carregar_cache_com_freshness(manager, "principal", {
        "expected_periods": {"quarterly": "202612"}, "caches": {"principal": {"max_period": "202612", "period_count": 99}}})
    assert result.sucesso and result.dados["Ativo Total"].tolist() == [10]
    assert not status["stale"] and not status["remote_forced"]
    assert status["official_revision_id"] == revision.revision_id


def test_official_missing_cache_remains_missing_without_download(monkeypatch, tmp_path):
    _enable(monkeypatch, tmp_path, {"principal": _principal()})
    result, status = app1._carregar_cache_com_freshness(app1.get_cache_manager(), "dre_individual", {})
    assert not result.sucesso and not status["remote_forced"]
    out, status = app1._load_carteira_4966_data_impl({})
    assert out is None and not status["valid"]


def test_carteira_official_retains_quality_and_canonicalization(monkeypatch, tmp_path):
    _, revision, _ = _enable(monkeypatch, tmp_path, {"carteira_instrumentos": _carteira()})
    out, status = app1._load_carteira_4966_data_impl({"caches": {"carteira_instrumentos": {"sha256": "foreign", "period_count": 99}}})
    assert status["valid"] and status["integrity_verified"]
    assert status["quality_check"]["success"]
    assert status["official_revision_id"] == revision.revision_id
    assert len(out) == 5 and out["Total Geral"].tolist() == [100.0] * 5
    assert out["Instituição"].nunique() == 1


def test_carteira_official_quality_failure_does_not_activate_remote_fallback(monkeypatch, tmp_path):
    incomplete = _carteira().iloc[:4]
    _enable(monkeypatch, tmp_path, {"carteira_instrumentos": incomplete})
    out, status = app1._load_carteira_4966_data_impl({})
    assert out is None and not status["valid"]
    assert "202603" in status["missing_required_periods"]


def test_carteira_ativo_filter_reads_official_support(monkeypatch, tmp_path):
    ativo = pd.DataFrame({"Instituição": ["Banco Teste", "Banco Teste"], "Período": ["4/2025", "1/2026"], "CodInst": ["C1234", "C1234"], "Provisão": [1.0, 2.0]})
    _, revision, _ = _enable(monkeypatch, tmp_path, {"ativo": ativo})
    out, status = app1._load_carteira_4966_ativo_periods_impl({"caches": {"ativo": {"sha256": "foreign"}}}, ["1/2026"])
    assert out["Provisão"].tolist() == [2.0]
    assert status["valid"] and status["integrity_verified"]
    assert status["official_revision_id"] == revision.revision_id


def test_peers_official_does_not_accept_foreign_release_counts_or_download(monkeypatch, tmp_path):
    periods = [f"{quarter}/{year}" for year in range(2023, 2027) for quarter in range(1, 5)][:13]
    frame = pd.DataFrame({"Instituição": ["Banco Teste"] * 13, "Período": periods, "CodInst": ["1234"] * 13})
    _enable(monkeypatch, tmp_path, {"principal_individual": frame})
    out = app1._get_peers_individual_filters_context("old", "foreign", expected_period_count=99, expected_record_count=999)
    assert len(out["periodos_disponiveis"]) == 13 and len(out["bancos_todos"]) == 1
    assert "erro" not in out


def test_peers_official_failure_and_absence_are_reported_without_download(monkeypatch, tmp_path):
    _enable(monkeypatch, tmp_path, {"principal_individual": _principal()})
    out = app1._get_peers_individual_filters_context("current")
    assert not out["periodos_disponiveis"] and "controle" in out["erro"]


def test_resource_tokens_change_when_only_another_dataset_changes(monkeypatch, tmp_path):
    store, first, app = _enable(monkeypatch, tmp_path, {"principal": _principal()})
    token = app1._cache_version_token("principal")
    second = _revision(store, tmp_path / "source-2", {"principal": _principal(), "carteira_pf": _principal(20)}, parent=first.revision_id)
    store.activate(second.revision_id, expected_parent=first.revision_id)
    assert app1._cache_version_token("principal") == token
    S.begin_official_read(app)
    assert app1._cache_version_token("principal") != token
    assert second.revision_id in app1._cache_file_token("principal")


def test_bloprudencial_periods_use_only_official_metadata_without_bcb_probe(monkeypatch, tmp_path):
    frame = pd.DataFrame({"Período": ["202605", "202606"], "DATA_BASE": ["202605", "202606"]})
    _enable(monkeypatch, tmp_path, {"bloprudencial": frame})
    monkeypatch.setattr(app1, "_sondar_periodos_bloprudencial_bcb", _forbidden)
    assert app1._listar_periodos_bloprudencial_disponiveis("old") == ["202605", "202606"]


def test_optional_derived_readers_report_absence_without_recalculation(monkeypatch, tmp_path):
    _enable(monkeypatch, tmp_path, {"principal": _principal()})
    cache = app1.get_cache_manager().get_cache("derived_metrics")
    monkeypatch.setattr(app1, "materialize_derived_metrics_cache", _forbidden)
    assert app1._get_cache_data_mtime(cache) is None
    assert app1._load_cache_metadata(cache) == {}
    assert app1._published_bundle_status_for_ui() == ("bundle-indisponivel", [])
    out, error, metadata = app1.ensure_derived_metrics_cache()
    assert out is cache and "revisão oficial" in error and metadata == {}


def _derived():
    return pd.DataFrame({"Instituição": ["Banco Teste"] * len(app1.DERIVED_METRICS),
        "Período": ["1/2026"] * len(app1.DERIVED_METRICS),
        "Métrica": list(app1.DERIVED_METRICS), "Valor": [0.1] * len(app1.DERIVED_METRICS)})


def test_derived_revision_is_read_without_mtime_triggered_write(monkeypatch, tmp_path):
    _, revision, _ = _enable(monkeypatch, tmp_path,
        {"derived_metrics": _derived(), "principal": _principal()},
        extra={"derived_metrics": {"denominador_zero_ou_nan": {metric: 0 for metric in app1.DERIVED_METRICS}}})
    monkeypatch.setattr(app1, "materialize_derived_metrics_cache", _forbidden)
    monkeypatch.setattr(app1, "_get_cache_data_mtime", _forbidden)
    files_before = {path.relative_to(revision.root).as_posix(): path.read_bytes()
                    for path in revision.root.rglob("*") if path.is_file()}
    cache, error, metadata = app1.ensure_derived_metrics_cache()
    assert cache.existe() and error is None
    assert metadata["extra"]["denominador_zero_ou_nan"] == {metric: 0 for metric in app1.DERIVED_METRICS}
    assert app1._load_cache_metadata(cache) == metadata
    assert {path.relative_to(revision.root).as_posix(): path.read_bytes()
            for path in revision.root.rglob("*") if path.is_file()} == files_before


def test_derived_revision_keeps_existing_metric_completeness_gate(monkeypatch, tmp_path):
    _enable(monkeypatch, tmp_path, {"derived_metrics": _derived()},
        extra={"derived_metrics": {"denominador_zero_ou_nan": {app1.DERIVED_METRICS[0]: 0}}})
    monkeypatch.setattr(app1, "materialize_derived_metrics_cache", _forbidden)
    cache, error, metadata = app1.ensure_derived_metrics_cache()
    assert cache.existe() and "não contém todas" in error
    assert len(metadata["extra"]["denominador_zero_ou_nan"]) == 1


@pytest.mark.parametrize("name", ["_baixar_cache_release_base_cache", "_download_peers_individual_curated_cache", "_salvar_cache_fallback_local"])
def test_direct_download_and_save_helpers_are_blocked_before_http(monkeypatch, tmp_path, name):
    # Mantém os helpers reais para verificar os guards defensivos.
    source = tmp_path / "source"
    store = S.LocalRevisionStore(tmp_path / "store")
    first = _revision(store, source, {"principal": _principal()})
    store.activate(first.revision_id, expected_parent=None)
    monkeypatch.setenv("TOMACONTA_OFFICIAL_STORE_DIR", str(store.root))
    S.begin_official_read(tmp_path / "app")
    monkeypatch.setattr(app1.requests, "get", _forbidden)
    calls = {"_baixar_cache_release_base_cache": lambda: app1._baixar_cache_release_base_cache("principal", "https://invalid.test"),
             "_download_peers_individual_curated_cache": lambda: app1._download_peers_individual_curated_cache(expected_period_count=1, expected_record_count=1),
             "_salvar_cache_fallback_local": lambda: app1._salvar_cache_fallback_local(app1.get_cache_manager(), "principal", CacheResult(True, "fixture", _principal()))}
    with pytest.raises(S.OfficialReadOnlyError):
        calls[name]()
