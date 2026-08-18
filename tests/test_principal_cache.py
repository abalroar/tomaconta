from pathlib import Path

import pandas as pd

from utils.ifdata_cache.base import CacheResult
from utils.ifdata_cache.principal import PrincipalCache


def test_principal_consolidated_reader_prefers_versioned_bundle(tmp_path: Path):
    cache = PrincipalCache(tmp_path, repo_prefix="principal")
    cache.arquivo_dados_runtime.parent.mkdir(parents=True, exist_ok=True)
    cache.bundled_data_file.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"Período": ["4/2025"]}).to_parquet(cache.arquivo_dados_runtime, index=False)
    pd.DataFrame({"Período": ["1/2026"]}).to_parquet(cache.bundled_data_file, index=False)

    assert cache.arquivo_dados == cache.arquivo_dados_runtime
    assert cache.read_data_file == cache.bundled_data_file
    assert pd.read_parquet(cache.read_data_file)["Período"].tolist() == ["1/2026"]


def test_principal_individual_reader_keeps_runtime_sem_bundle(tmp_path: Path):
    cache = PrincipalCache(tmp_path, repo_prefix="principal_individual")
    cache.arquivo_dados_runtime.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"Período": ["4/2025"]}).to_parquet(cache.arquivo_dados_runtime, index=False)

    assert cache.read_data_file == cache.arquivo_dados_runtime


def test_principal_cache_prefers_release_parquet_over_raw(monkeypatch, tmp_path: Path):
    cache = PrincipalCache(tmp_path, repo_prefix="principal")
    calls = []

    def fake_release(self):
        calls.append("release")
        return CacheResult(
            sucesso=True,
            mensagem="release ok",
            dados=pd.DataFrame({"Período": ["4/2025"]}),
            fonte="github_releases",
        )

    def fake_raw(self):
        calls.append("raw")
        return CacheResult(
            sucesso=True,
            mensagem="raw ok",
            dados=pd.DataFrame({"Período": ["3/2025"]}),
            fonte="github_repo",
        )

    monkeypatch.setattr(PrincipalCache, "_baixar_parquet_release", fake_release)
    monkeypatch.setattr(PrincipalCache, "_baixar_parquet_repo", fake_raw)
    monkeypatch.setattr(
        PrincipalCache,
        "_baixar_pickle_releases",
        lambda self, url, repo_nome="": CacheResult(False, "pickle fail", fonte="nenhum"),
    )

    result = cache.baixar_remoto()

    assert result.sucesso
    assert result.fonte == "github_releases"
    assert calls == ["release"]


def test_principal_cache_falls_back_to_raw_repo_when_release_fails(monkeypatch, tmp_path: Path):
    cache = PrincipalCache(tmp_path, repo_prefix="principal")
    calls = []

    def fake_release(self):
        calls.append("release")
        return CacheResult(False, "release fail", fonte="nenhum")

    def fake_raw(self):
        calls.append("raw")
        return CacheResult(
            sucesso=True,
            mensagem="raw ok",
            dados=pd.DataFrame({"Período": ["3/2025"]}),
            fonte="github_repo",
        )

    monkeypatch.setattr(PrincipalCache, "_baixar_parquet_release", fake_release)
    monkeypatch.setattr(PrincipalCache, "_baixar_parquet_repo", fake_raw)
    monkeypatch.setattr(
        PrincipalCache,
        "_baixar_pickle_releases",
        lambda self, url, repo_nome="": CacheResult(False, "pickle fail", fonte="nenhum"),
    )

    result = cache.baixar_remoto()

    assert result.sucesso
    assert result.fonte == "github_repo"
    assert calls == ["release", "raw"]
