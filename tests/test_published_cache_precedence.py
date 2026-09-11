import json
import shutil

import pandas as pd

from utils.ifdata_cache.base import BaseCache, CacheConfig, CacheResult


class PublishedCache(BaseCache):
    def __init__(self, root):
        super().__init__(CacheConfig(nome="published", descricao="test", subdir="published",
                                   arquivo_dados="dados.parquet", arquivo_metadata="metadata.json",
                                   colunas_obrigatorias=["Período"]), root)

    def baixar_remoto(self):
        raise AssertionError("Bundle publicado deve funcionar sem rede ou release global")

    def extrair_periodo(self, periodo, **kwargs):
        return CacheResult(False, "not used")


def published_cache(tmp_path):
    cache = PublishedCache(tmp_path)
    data = pd.DataFrame({"Período": ["1/2026", "2/2026"], "valor": [1., 2.]})
    assert cache.salvar_local(data).sucesso
    metadata = json.loads(cache.arquivo_metadata_runtime.read_text())
    metadata["publication_id"] = "june-publication"
    cache.bundled_dir.mkdir(parents=True)
    shutil.copy2(cache.arquivo_dados_runtime, cache.bundled_dir / "dados.parquet")
    (cache.bundled_dir / "metadata.json").write_text(json.dumps(metadata))
    return cache


def test_cold_start_and_stale_runtime_use_published_bundle(tmp_path, monkeypatch):
    cache = published_cache(tmp_path)
    monkeypatch.setenv("TOMACONTA_RELEASE_TAG", "v2.0-cache")
    assert cache.arquivo_dados.parent == cache.bundled_dir  # runtime sem identidade publicada
    assert cache.carregar().dados.valor.tolist() == [1., 2.]
    cache.limpar_local()
    assert not cache.existe()
    assert cache.carregar().dados.valor.tolist() == [1., 2.]


def test_runtime_update_preserves_published_history_and_precedes_bundle(tmp_path):
    cache = published_cache(tmp_path)
    updated = pd.DataFrame({"Período": ["1/2026", "2/2026", "3/2026"], "valor": [1., 20., 30.]})
    assert cache.salvar_local(updated, fonte="api").sucesso
    assert cache.arquivo_dados == cache.arquivo_dados_runtime
    assert cache.carregar().dados.valor.tolist() == [1., 20., 30.]
    # Uma reconstrução incompleta não pode degradar a leitura publicada.
    assert cache.salvar_local(updated.iloc[:1], fonte="api").sucesso
    assert cache.carregar().dados.valor.tolist() == [1., 2.]


def test_download_of_legacy_release_does_not_shadow_bundle(tmp_path):
    cache = published_cache(tmp_path)
    old = pd.DataFrame({"Período": ["1/2026"], "valor": [999.]})
    assert cache.salvar_local(old, fonte="github_releases").sucesso
    assert cache.carregar().dados.valor.tolist() == [1., 2.]


def test_spb_all_datasets_survive_empty_or_stale_runtime(tmp_path, monkeypatch):
    from utils.ifdata_cache.spb_meios_pagamento import SPBMeiosPagamentoCache
    cache = SPBMeiosPagamentoCache(tmp_path)
    cache.bundled_dir.mkdir(parents=True)
    for key, path in cache.dataset_paths().items():
        pd.DataFrame({"trimestre": ["20262"], "valor": [26.]}).to_parquet(cache.bundled_dir / path.name)
        path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"trimestre": ["20261"], "valor": [99.]}).to_parquet(path)
    (cache.bundled_dir / "metadata.json").write_text(json.dumps({"publication_id": "june", "periodos": ["20262"]}))
    cache.arquivo_metadata_runtime.write_text(json.dumps({"periodos": ["20261"]}))
    monkeypatch.setenv("TOMACONTA_RELEASE_TAG", "v2.0-cache")
    def no_network(*args, **kwargs):
        raise AssertionError("Dados publicados devem sobreviver sem rede")
    monkeypatch.setattr("utils.ifdata_cache.spb_meios_pagamento.requests.get", no_network)
    for stale in (True, False):
        if not stale:
            shutil.rmtree(cache.cache_dir)
        assert cache.bootstrap_local_assets().sucesso
        for key in cache.dataset_paths():
            result = cache.carregar_dataset(key)
            assert result.sucesso
            assert result.dados.valor.tolist() == [26.]
