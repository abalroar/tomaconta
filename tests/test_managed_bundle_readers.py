import json
from pathlib import Path
from threading import Event, Thread

import pandas as pd
import pytest

from utils.ifdata_cache.critical_screens import (
    CRITICAL_SCREENS_SCHEMA_VERSION,
    CriticalScreensCache,
    load_critical_screens_slice,
)
from utils.ifdata_cache.derived_metrics import (
    DerivedMetricsCache,
    DerivedMetricsIndividualCache,
    load_derived_metrics_slice,
)
from utils.ifdata_cache.principal import PrincipalCache, PrincipalIndividualCache


READERS = [PrincipalCache, DerivedMetricsCache, CriticalScreensCache]


def frame(value=1.0, periods=("1/2026",)):
    return pd.DataFrame([
        {"Instituição": "Banco A", "InstituiçãoKey": "Banco A", "Período": period,
         "Métrica": "M", "Valor": value, "Unidade": "%", "Ativo Total": value}
        for period in periods
    ])


def bundle(cache, data, publication_id="published-v1"):
    cache.bundled_dir.mkdir(parents=True, exist_ok=True)
    data.to_parquet(cache.bundled_data_file, index=False)
    metadata = {"publication_id": publication_id, "periodos": data["Período"].unique().tolist(),
                "total_periodos": data["Período"].nunique(), "total_registros": len(data),
                "colunas": list(data.columns), "fonte": "published",
                "extra": {"schema_version": CRITICAL_SCREENS_SCHEMA_VERSION}}
    cache.bundled_metadata_file.write_text(json.dumps(metadata), encoding="utf-8")
    return metadata


@pytest.mark.parametrize("factory", READERS)
@pytest.mark.parametrize("old_publication", [None, "previous-publication"])
def test_unknown_or_old_runtime_never_supersedes_current_publication(tmp_path, factory, old_publication):
    cache = factory(tmp_path)
    bundle(cache, frame(2.0))
    cache.arquivo_dados_runtime.parent.mkdir(parents=True, exist_ok=True)
    frame(1.0).to_parquet(cache.arquivo_dados_runtime, index=False)
    runtime_metadata = {"periodos": ["1/2026"], "fonte": "unmanaged"}
    if old_publication:
        runtime_metadata["baseline_publication_id"] = old_publication
    cache.arquivo_metadata_runtime.write_text(json.dumps(runtime_metadata), encoding="utf-8")
    assert cache.read_data_file == cache.bundled_data_file
    assert cache.read_metadata_file == cache.bundled_metadata_file
    assert pd.read_parquet(cache.read_data_file)["Valor"].tolist() == [2.0]
    assert json.loads(cache.read_metadata_file.read_text())["fonte"] == "published"


@pytest.mark.parametrize("factory", READERS)
def test_new_managed_generation_is_used_with_its_paired_metadata(tmp_path, factory):
    cache = factory(tmp_path)
    bundle(cache, frame(2.0))
    updated = frame(3.0, periods=("1/2026", "2/2026"))
    result = cache.salvar_local(updated, fonte="api", info_extra={"schema_version": CRITICAL_SCREENS_SCHEMA_VERSION})
    assert result.sucesso, result.mensagem
    assert result.metadata["baseline_publication_id"] == "published-v1"
    assert cache.read_data_file == cache.arquivo_dados_runtime
    assert cache.read_metadata_file == cache.arquivo_metadata_runtime
    metadata = json.loads(cache.read_metadata_file.read_text())
    assert metadata["fonte"] == "api"
    assert metadata["total_registros"] == len(pd.read_parquet(cache.read_data_file)) == 2
    assert metadata["integridade"] == result.metadata["integridade"]


@pytest.mark.parametrize("factory", READERS)
def test_runtime_missing_published_periods_cannot_replace_full_bundle(tmp_path, factory):
    cache = factory(tmp_path)
    bundle(cache, frame(2.0, periods=("1/2026", "2/2026")))
    result = cache.salvar_local(frame(3.0), fonte="api")
    assert result.sucesso, result.mensagem
    assert cache.read_data_file == cache.bundled_data_file
    assert cache.read_metadata_file == cache.bundled_metadata_file
    assert pd.read_parquet(cache.read_data_file)["Período"].tolist() == ["1/2026", "2/2026"]


@pytest.mark.parametrize("factory", READERS)
def test_new_code_publication_displaces_previous_managed_baseline(tmp_path, factory):
    cache = factory(tmp_path)
    bundle(cache, frame(2.0), publication_id="published-v1")
    assert cache.salvar_local(frame(3.0), fonte="api").sucesso
    bundle(cache, frame(4.0), publication_id="published-v2")
    assert cache.read_data_file == cache.bundled_data_file
    assert cache.read_metadata_file == cache.bundled_metadata_file
    assert pd.read_parquet(cache.read_data_file)["Valor"].tolist() == [4.0]


def test_derived_slice_reads_current_managed_metric_without_formula_changes(tmp_path):
    cache = DerivedMetricsCache(tmp_path)
    bundle(cache, frame(2.0))
    assert cache.salvar_local(frame(3.0), fonte="derivado").sucesso
    result = load_derived_metrics_slice(cache, periodos=["1/2026"], instituicoes=["Banco A"], metricas=["M"])
    assert result["Valor"].tolist() == [3.0]


def test_principal_filtered_reader_uses_current_managed_source(tmp_path):
    cache = PrincipalCache(tmp_path)
    bundle(cache, frame(2.0))
    assert cache.salvar_local(frame(3.0), fonte="api").sucesso
    result = pd.read_parquet(cache.read_data_file, columns=["Período", "Ativo Total"],
                             filters=[("Período", "in", ["1/2026"])])
    assert result["Ativo Total"].tolist() == [3.0]


def test_critical_slice_does_not_bootstrap_over_valid_managed_generation(tmp_path, monkeypatch):
    import utils.ifdata_cache.critical_screens as critical
    cache = CriticalScreensCache(tmp_path)
    bundle(cache, frame(2.0))
    assert cache.salvar_local(frame(3.0), fonte="materialized",
                              info_extra={"schema_version": CRITICAL_SCREENS_SCHEMA_VERSION}).sucesso
    monkeypatch.setattr(critical, "build_institution_to_conglomerate_map", lambda root: {})
    monkeypatch.setattr(CriticalScreensCache, "bootstrap_local_from_bundle",
                        lambda self: pytest.fail("managed generation must remain active"))
    result = load_critical_screens_slice(base_dir=tmp_path, periodos=["1/2026"], colunas=["Ativo Total"])
    assert result["Ativo Total"].tolist() == [3.0]
    assert cache.read_metadata_file == cache.arquivo_metadata_runtime


@pytest.mark.parametrize("factory", [PrincipalIndividualCache, DerivedMetricsIndividualCache])
def test_individual_reader_keeps_its_existing_runtime_contract(tmp_path, factory):
    cache = factory(tmp_path)
    assert cache.salvar_local(frame(3.0), fonte="api").sucesso
    assert cache.read_data_file == cache.arquivo_dados_runtime
    assert cache.read_metadata_file == cache.arquivo_metadata_runtime


@pytest.mark.parametrize("factory", READERS)
def test_fast_reader_recovers_interrupted_promotion_before_resolving_paths(tmp_path, factory, monkeypatch):
    import utils.ifdata_cache.base as base
    cache = factory(tmp_path)
    bundle(cache, frame(1.0))
    assert cache.salvar_local(frame(2.0), fonte="api").sucesso
    replace = base.os.replace
    interrupt = [True]

    def interrupted_replace(source, target):
        if Path(target) == cache.arquivo_metadata_runtime and interrupt[0]:
            interrupt[0] = False
            raise KeyboardInterrupt("process stopped between data and metadata")
        return replace(source, target)

    monkeypatch.setattr(base.os, "replace", interrupted_replace)
    with pytest.raises(KeyboardInterrupt):
        cache.salvar_local(frame(3.0), fonte="api")
    assert cache._transaction_file.exists()
    data_path = cache.read_data_file
    metadata_path = cache.read_metadata_file
    assert not cache._transaction_file.exists()
    assert pd.read_parquet(data_path)["Valor"].tolist() == [2.0]
    assert json.loads(metadata_path.read_text())["integridade"]["sha256"] == cache._sha256(data_path)


@pytest.mark.parametrize("factory", READERS)
def test_fast_reader_snapshot_remains_readable_after_busy_promotion_commits(tmp_path, factory, monkeypatch):
    import utils.ifdata_cache.base as base
    cache = factory(tmp_path)
    bundle(cache, frame(1.0))
    assert cache.salvar_local(frame(2.0), fonte="api").sucesso
    replace = base.os.replace
    promoting, release = Event(), Event()
    results = []

    def hold_metadata_promotion(source, target):
        if Path(target) == cache.arquivo_metadata_runtime:
            promoting.set()
            if not release.wait(timeout=10):
                raise RuntimeError("test promotion timeout")
        return replace(source, target)

    monkeypatch.setattr(base.os, "replace", hold_metadata_promotion)
    writer = Thread(target=lambda: results.append(cache.salvar_local(frame(3.0), fonte="api")))
    writer.start()
    try:
        assert promoting.wait(timeout=10)
        old_data = cache.read_data_file
        old_metadata = cache.read_metadata_file
        assert old_data != cache.arquivo_dados_runtime
        assert pd.read_parquet(old_data)["Valor"].tolist() == [2.0]
        assert json.loads(old_metadata.read_text())["integridade"]["sha256"] == cache._sha256(old_data)
    finally:
        release.set()
        writer.join(timeout=10)
    assert not writer.is_alive()
    assert results[0].sucesso, results[0].mensagem
    assert old_data.exists() and old_metadata.exists()
    assert pd.read_parquet(old_data)["Valor"].tolist() == [2.0]
    assert pd.read_parquet(cache.read_data_file)["Valor"].tolist() == [3.0]
