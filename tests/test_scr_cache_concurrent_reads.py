"""Leitura SCR durante atualização de outra fonte e retry da UI."""

from __future__ import annotations

import ast
from contextlib import contextmanager
import json
from pathlib import Path
from types import SimpleNamespace
import threading

import pandas as pd
import pytest
import streamlit as st

from utils.ifdata_cache import scr_data as S
from utils.ifdata_cache.update_state import mutation_lock


def _summary(period="2026-06"):
    dimensions = {
        "data_base": period, "regiao": "Sudeste", "cliente": "PF",
        "porte": "Até 1 salário mínimo", "modalidade": "Empréstimos",
        "submodalidade": "Cheque especial", "modalidade_bcb": "PF - Outros créditos",
    }
    return pd.DataFrame([{**{column: 0.0 for column in S.METRIC_COLUMNS}, **dimensions}],
                        columns=S.RESUMO_COLUMNS)


def _seed(cache, *, managed=False):
    cache._garantir_diretorio()
    _summary().to_parquet(cache.arquivo_dados_runtime, index=False)
    metadata = {"total_registros": 1, "periodos": ["2026-06"], "schema_version": 2}
    cache.arquivo_metadata_runtime.write_text(json.dumps(metadata))
    cache.manifest_path.write_text(json.dumps({"anos": {}, "falhas": {}}))
    for key, path in cache.dimension_paths().items():
        data = (pd.DataFrame({"modalidade": ["Empréstimos"], "submodalidade": ["Cheque especial"],
                              "modalidade_bcb": ["PF - Outros créditos"]})
                if key == "produto" else pd.DataFrame({key: ["válido"]}))
        data.to_parquet(path, index=False)
    if managed:
        saved = cache.salvar_arquivo_local(cache.arquivo_dados_runtime, metadata)
        assert saved.sucesso, saved.mensagem


@contextmanager
def _other_update(base_dir):
    ready, release = threading.Event(), threading.Event()

    def hold():
        with mutation_lock(base_dir, owner={"cache_type": "carteira_pf"}):
            ready.set()
            assert release.wait(10)

    thread = threading.Thread(target=hold)
    thread.start()
    assert ready.wait(5)
    try:
        yield
    finally:
        release.set()
        thread.join(5)
        assert not thread.is_alive()


@pytest.mark.parametrize("managed", [False, True])
def test_complete_scr_generation_remains_readable_during_other_update(tmp_path, monkeypatch, managed):
    cache = S.SCRDataCache(tmp_path)
    _seed(cache, managed=managed)
    monkeypatch.setattr("requests.get", lambda *a, **k: pytest.fail("Leitura local tentou baixar"))

    with _other_update(tmp_path):
        result = cache.bootstrap_local_assets()

    assert result.sucesso, result.mensagem
    assert result.fonte == "cache_local"
    assert result.metadata["periodos"] == ["2026-06"]


def test_cold_start_blocked_by_other_update_can_retry_after_lock_release(tmp_path, monkeypatch):
    cache = S.SCRDataCache(tmp_path)
    with _other_update(tmp_path):
        first = cache.bootstrap_local_assets()
        assert not first.sucesso
        assert "atualização em andamento" in first.mensagem
        assert not cache.arquivo_dados_runtime.exists()

    payloads = {}
    source = tmp_path / "remote.parquet"
    _summary().to_parquet(source, index=False)
    payloads[cache.github_release_parquet_url] = source.read_bytes()
    payloads[cache.github_release_metadata_url] = json.dumps(
        {"total_registros": 1, "periodos": ["2026-06"], "schema_version": 2}).encode()
    payloads[cache.github_release_manifest_url] = b'{"anos": {}, "falhas": {}}'
    for key in cache.dimension_paths():
        frame = (pd.DataFrame({"modalidade": ["Empréstimos"], "submodalidade": ["Cheque especial"],
                               "modalidade_bcb": ["PF - Outros créditos"]})
                 if key == "produto" else pd.DataFrame({key: ["válido"]}))
        frame.to_parquet(source, index=False)
        payloads[f"{cache.release_base_url}/scr_data_dim_{key}.parquet"] = source.read_bytes()
    monkeypatch.setattr("requests.get", lambda url, **kwargs: SimpleNamespace(
        status_code=200, content=payloads[url]))

    second = cache.bootstrap_local_assets()
    assert second.sucesso, second.mensagem
    assert second.fonte == "github_releases"
    assert cache.bootstrap_local_assets().metadata["periodos"] == ["2026-06"]


@pytest.mark.parametrize("invalid", ["dimension", "manifest", "identity"])
def test_partial_or_corrupt_local_assets_do_not_bypass_busy_download(tmp_path, invalid):
    cache = S.SCRDataCache(tmp_path)
    _seed(cache, managed=True)
    if invalid == "dimension":
        cache.dimension_paths()["porte"].unlink()
    elif invalid == "manifest":
        cache.manifest_path.unlink()
    else:
        metadata = json.loads(cache.arquivo_metadata_runtime.read_text())
        metadata["integridade"]["sha256"] = "0" * 64
        cache.arquivo_metadata_runtime.write_text(json.dumps(metadata))

    with _other_update(tmp_path):
        result = cache.bootstrap_local_assets()
    assert not result.sucesso
    assert "atualização em andamento" in result.mensagem


def test_force_download_does_not_report_existing_generation_as_refresh(tmp_path):
    cache = S.SCRDataCache(tmp_path)
    _seed(cache)
    with _other_update(tmp_path):
        result = cache.bootstrap_local_assets(force=True)
    assert not result.sucesso


def test_scr_bootstrap_reads_previous_complete_generation_during_promotion(tmp_path, monkeypatch):
    cache = S.SCRDataCache(tmp_path)
    _seed(cache, managed=True)
    candidate = tmp_path / "next.parquet"
    _summary("2026-07").to_parquet(candidate, index=False)
    entered, release = threading.Event(), threading.Event()
    original = S.os.replace
    outcomes = []

    def pause_before_metadata(source, target):
        if Path(target) == cache.arquivo_metadata_runtime:
            entered.set()
            assert release.wait(10)
        return original(source, target)

    # S.os is the same module used by Base's transaction promotion.
    import os
    monkeypatch.setattr(os, "replace", pause_before_metadata)

    def save():
        outcomes.append(cache.salvar_arquivo_local(candidate,
            {"total_registros": 1, "periodos": ["2026-07"], "schema_version": 2}))

    thread = threading.Thread(target=save)
    thread.start()
    assert entered.wait(5)
    try:
        result = cache.bootstrap_local_assets()
        assert result.sucesso, result.mensagem
        assert result.metadata["periodos"] == ["2026-06"]
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive()
    assert outcomes[0].sucesso, outcomes[0].mensagem
    assert cache.bootstrap_local_assets().metadata["periodos"] == ["2026-07"]


def _period_reader(fake_cache, monkeypatch):
    source = Path(__file__).resolve().parents[1] / "tabs" / "scr_inadimplencia_view.py"
    tree = ast.parse(source.read_text())
    node = next(node for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef) and node.name == "_periodos_disponiveis")
    namespace = {"st": st, "pd": pd, "_cache": lambda: fake_cache}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"), namespace)
    reader = namespace["_periodos_disponiveis"]
    reader.clear()
    monkeypatch.setattr(pd, "read_parquet", lambda *a, **k: pd.DataFrame({"data_base": []}))
    return reader


def test_streamlit_period_reader_does_not_cache_transient_bootstrap_failure(monkeypatch):
    calls = []

    def bootstrap():
        calls.append(True)
        return S.CacheResult(len(calls) > 1, "Já existe uma atualização em andamento",
                             metadata={"periodos": ["2026-06"]} if len(calls) > 1 else {})

    cache = SimpleNamespace(bootstrap_local_assets=bootstrap,
                            get_info=lambda: pytest.fail("Deveria usar metadata da geração lida"))
    reader = _period_reader(cache, monkeypatch)
    try:
        with pytest.raises(RuntimeError, match="atualização em andamento"):
            reader()
        assert reader() == ("2026-06",)
        assert reader() == ("2026-06",)
        assert len(calls) == 2
    finally:
        reader.clear()


def test_streamlit_period_reader_does_not_cache_incomplete_empty_generation(monkeypatch):
    metadata = {}
    cache = SimpleNamespace(
        bootstrap_local_assets=lambda: S.CacheResult(True, "local", metadata=metadata),
        get_info=lambda: {}, arquivo_dados=Path("unused.parquet"))
    reader = _period_reader(cache, monkeypatch)
    try:
        with pytest.raises(RuntimeError, match="sem competências"):
            reader()
        metadata["periodos"] = ["2026-06"]
        assert reader() == ("2026-06",)
    finally:
        reader.clear()
