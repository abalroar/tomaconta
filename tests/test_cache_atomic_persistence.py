import hashlib
import json
import os
import pickle
import threading

import pandas as pd
import pytest

from utils.ifdata_cache.base import BaseCache, CacheConfig, CacheResult
from utils.ifdata_cache.update_state import mutation_lock


class AtomicCache(BaseCache):
    def __init__(self, root):
        super().__init__(CacheConfig(
            nome="atomic_test", descricao="atomic persistence", subdir="atomic_test",
            arquivo_dados="dados.parquet", colunas_obrigatorias=["Periodo", "CodInst"],
        ), root)

    def baixar_remoto(self):
        return CacheResult(False, "not used")

    def extrair_periodo(self, periodo, **kwargs):
        return CacheResult(False, "not used")


class AtomicExtraCache(AtomicCache):
    def _runtime_paths(self):
        return [*super()._runtime_paths(), self.cache_dir / "dimension.parquet", self.cache_dir / "manifest.json"]


def frame(value=10):
    return pd.DataFrame({"Periodo": ["202606"], "CodInst": ["000001"], "valor": [value]})


def seeded(tmp_path):
    cache = AtomicCache(tmp_path)
    assert cache.salvar_local(frame()).sucesso
    return cache


def current_bytes(cache):
    return {path.name: path.read_bytes() for path in cache._runtime_paths() if path.exists()}


def test_new_generation_is_reread_and_has_paired_integrity(tmp_path):
    cache = AtomicCache(tmp_path)
    data = frame().set_axis([9])
    saved = cache.salvar_local(data, fonte="api", info_extra={"periodo": "202606"})
    assert saved.sucesso
    assert saved.dados is data
    metadata = json.loads(cache.arquivo_metadata_runtime.read_text())
    integrity = metadata["integridade"]
    assert integrity["sha256"] == hashlib.sha256(cache.arquivo_dados_runtime.read_bytes()).hexdigest()
    assert json.loads(cache._integrity_file.read_text()) == integrity
    assert metadata["extra"] == {"periodo": "202606"}
    pd.testing.assert_frame_equal(cache.carregar_local().dados, data.reset_index(drop=True))
    assert not cache._transaction_file.exists()


def test_failed_data_staging_preserves_previous_bytes(tmp_path, monkeypatch):
    cache = seeded(tmp_path)
    previous = current_bytes(cache)

    def truncate_then_fail(data, path, **kwargs):
        path.write_bytes(b"partial parquet")
        raise OSError("disk full")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", truncate_then_fail)
    assert not cache.salvar_local(frame(99)).sucesso
    assert current_bytes(cache) == previous
    assert cache.carregar_local().dados.valor.tolist() == [10]


def test_failed_metadata_serialization_preserves_previous_generation(tmp_path):
    cache = seeded(tmp_path)
    previous = current_bytes(cache)
    assert not cache.salvar_local(frame(99), info_extra={"invalid": object()}).sucesso
    assert current_bytes(cache) == previous
    assert not cache._transaction_file.exists()


def test_candidate_content_change_is_rejected_before_promotion(tmp_path, monkeypatch):
    cache = seeded(tmp_path)
    previous = current_bytes(cache)
    real_write = pd.DataFrame.to_parquet

    def corrupt_candidate(data, path, **kwargs):
        return real_write(data.assign(valor=999), path, **kwargs)

    monkeypatch.setattr(pd.DataFrame, "to_parquet", corrupt_candidate)
    assert not cache.salvar_local(frame(99)).sucesso
    assert current_bytes(cache) == previous


def test_failure_between_data_and_metadata_promotion_rolls_back(tmp_path, monkeypatch):
    cache = seeded(tmp_path)
    previous = current_bytes(cache)
    real_replace = os.replace
    failed = False

    def fail_metadata_once(source, destination):
        nonlocal failed
        if destination == cache.arquivo_metadata_runtime and not failed:
            failed = True
            raise OSError("metadata promotion failed")
        return real_replace(source, destination)

    monkeypatch.setattr("utils.ifdata_cache.base.os.replace", fail_metadata_once)
    assert not cache.salvar_local(frame(99)).sucesso
    assert current_bytes(cache) == previous
    assert cache.carregar_local().dados.valor.tolist() == [10]
    assert not cache._transaction_file.exists()


def test_interrupted_promotion_is_recovered_on_next_load(tmp_path, monkeypatch):
    cache = seeded(tmp_path)
    previous = current_bytes(cache)
    real_replace = os.replace

    def interrupt_before_metadata(source, destination):
        if destination == cache.arquivo_metadata_runtime:
            raise KeyboardInterrupt("process interrupted")
        return real_replace(source, destination)

    with monkeypatch.context() as patch:
        patch.setattr("utils.ifdata_cache.base.os.replace", interrupt_before_metadata)
        with pytest.raises(KeyboardInterrupt):
            cache.salvar_local(frame(99))
    assert cache._transaction_file.exists()
    assert cache.arquivo_dados_runtime.read_bytes() != previous["dados.parquet"]
    loaded = AtomicCache(tmp_path).carregar_local()
    assert loaded.sucesso
    assert loaded.dados.valor.tolist() == [10]
    assert current_bytes(cache) == previous
    assert not cache._transaction_file.exists()


def test_first_save_interruption_does_not_adopt_uncommitted_data(tmp_path, monkeypatch):
    cache = AtomicCache(tmp_path)
    real_replace = os.replace

    def interrupt_before_metadata(source, destination):
        if destination == cache.arquivo_metadata_runtime:
            raise KeyboardInterrupt
        return real_replace(source, destination)

    with monkeypatch.context() as patch:
        patch.setattr("utils.ifdata_cache.base.os.replace", interrupt_before_metadata)
        with pytest.raises(KeyboardInterrupt):
            cache.salvar_local(frame(99))
    assert not cache.carregar_local().sucesso
    assert not cache.existe()
    assert not cache.arquivo_metadata_runtime.exists()


def test_interrupted_rollback_can_be_repeated(tmp_path, monkeypatch):
    cache = seeded(tmp_path)
    previous = current_bytes(cache)
    real_replace = os.replace

    def interrupt_rollback(source, destination):
        if destination == cache.arquivo_metadata_runtime and ".restore-" not in source.name:
            raise OSError("promotion failed")
        if destination == cache.arquivo_dados_runtime and ".restore-" in source.name:
            raise KeyboardInterrupt("rollback interrupted")
        return real_replace(source, destination)

    with monkeypatch.context() as patch:
        patch.setattr("utils.ifdata_cache.base.os.replace", interrupt_rollback)
        with pytest.raises(KeyboardInterrupt):
            cache.salvar_local(frame(99))
    assert cache._transaction_file.exists()
    assert cache.carregar_local().sucesso
    assert current_bytes(cache) == previous


def test_corrupt_recovery_snapshot_fails_safely(tmp_path, monkeypatch):
    cache = seeded(tmp_path)
    real_replace = os.replace

    def interrupt_before_metadata(source, destination):
        if destination == cache.arquivo_metadata_runtime:
            raise KeyboardInterrupt
        return real_replace(source, destination)

    with monkeypatch.context() as patch:
        patch.setattr("utils.ifdata_cache.base.os.replace", interrupt_before_metadata)
        with pytest.raises(KeyboardInterrupt):
            cache.salvar_local(frame(99))
    journal = json.loads(cache._transaction_file.read_text())
    (cache.cache_dir / journal["directory"] / "previous" / "dados.parquet").write_bytes(b"damaged")
    assert not cache.carregar_local().sucesso
    assert cache._transaction_file.exists()


def test_managed_metadata_missing_or_mismatched_is_not_synthesized(tmp_path):
    cache = seeded(tmp_path)
    metadata = cache.arquivo_metadata_runtime.read_bytes()
    cache.arquivo_metadata_runtime.unlink()
    assert not cache.carregar_local().sucesso
    assert not cache.arquivo_metadata_runtime.exists()
    cache.arquivo_metadata_runtime.write_bytes(metadata)
    frame(99).to_parquet(cache.arquivo_dados_runtime, index=False)
    assert not cache.carregar_local().sucesso
    assert not cache.cache_valido()[0]


def test_legacy_metadata_missing_stays_readable_without_writing(tmp_path):
    cache = AtomicCache(tmp_path)
    cache._garantir_diretorio()
    frame().to_parquet(cache.arquivo_dados_runtime, index=False)
    result = cache.carregar_local()
    assert result.sucesso
    assert result.metadata["total_registros"] == 1
    assert result.metadata["periodos"] == ["202606"]
    assert not cache.arquivo_metadata_runtime.exists()


def test_legacy_pickle_uses_its_runtime_metadata(tmp_path):
    cache = AtomicCache(tmp_path)
    cache._garantir_diretorio()
    with cache.arquivo_dados_pickle.open("wb") as handle:
        pickle.dump(frame(), handle)
    cache.arquivo_metadata_runtime.write_text(json.dumps({"total_registros": 1, "formato": "pickle"}))
    cache.bundled_dir.mkdir(parents=True)
    (cache.bundled_dir / "metadata.json").write_text(json.dumps({"total_registros": 999}))
    result = cache.carregar_local()
    assert result.sucesso
    assert result.metadata["formato"] == "pickle"
    assert cache.arquivo_metadata == cache.arquivo_metadata_runtime


def test_pickle_fallback_replaces_stale_parquet_and_back(tmp_path, monkeypatch):
    cache = seeded(tmp_path)

    def no_parquet(*args, **kwargs):
        raise ImportError("no parquet engine")

    with monkeypatch.context() as patch:
        patch.setattr(pd.DataFrame, "to_parquet", no_parquet)
        result = cache.salvar_local(frame(99))
    assert result.sucesso
    assert not cache.arquivo_dados_runtime.exists()
    assert cache.arquivo_dados_pickle.exists()
    assert cache.carregar_local().dados.valor.tolist() == [99]
    assert cache.salvar_local(frame(100)).sucesso
    assert cache.arquivo_dados_runtime.exists()
    assert not cache.arquivo_dados_pickle.exists()
    assert cache.carregar_local().dados.valor.tolist() == [100]


def test_read_stays_available_during_other_thread_update_lock(tmp_path):
    cache = seeded(tmp_path)
    entered = threading.Event()
    release = threading.Event()

    def updating():
        with mutation_lock(tmp_path):
            entered.set()
            assert release.wait(5)

    thread = threading.Thread(target=updating)
    thread.start()
    try:
        assert entered.wait(5)
        loaded = cache.carregar_local()
        assert loaded.sucesso
        assert loaded.dados.valor.tolist() == [10]
        assert cache.get_info()["total_registros"] == 1
        assert not cache.limpar_local().sucesso
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive()


def test_read_during_promotion_uses_previous_immutable_snapshot(tmp_path, monkeypatch):
    cache = seeded(tmp_path)
    entered = threading.Event()
    release = threading.Event()
    real_replace = os.replace
    results = []

    def pause_after_data_replace(source, destination):
        result = real_replace(source, destination)
        if destination == cache.arquivo_dados_runtime and ".restore-" not in source.name:
            entered.set()
            assert release.wait(5)
        return result

    monkeypatch.setattr("utils.ifdata_cache.base.os.replace", pause_after_data_replace)
    thread = threading.Thread(target=lambda: results.append(cache.salvar_local(frame(99))))
    thread.start()
    try:
        assert entered.wait(5)
        assert cache._transaction_file.exists()
        loaded = cache.carregar_local()
        assert loaded.sucesso
        assert loaded.dados.valor.tolist() == [10]
    finally:
        release.set()
        thread.join(5)
    assert results[0].sucesso
    assert cache.carregar_local().dados.valor.tolist() == [99]


def test_streamed_pair_and_auxiliaries_roll_back_together(tmp_path, monkeypatch):
    cache = AtomicExtraCache(tmp_path)
    assert cache.salvar_local(frame()).sucesso
    dimension = cache.cache_dir / "dimension.parquet"
    manifest = cache.cache_dir / "manifest.json"
    frame(10).to_parquet(dimension, index=False)
    manifest.write_text('{"version": "old"}')
    previous = current_bytes(cache)
    candidate = tmp_path / "candidate.parquet"
    extra = tmp_path / "extra.parquet"
    manifest_candidate = tmp_path / "manifest-candidate.json"
    frame(99).to_parquet(candidate, index=False)
    frame(99).to_parquet(extra, index=False)
    manifest_candidate.write_text('{"version": "new"}')
    real_replace = os.replace
    failed = False

    def fail_metadata_once(source, destination):
        nonlocal failed
        if destination == cache.arquivo_metadata_runtime and not failed:
            failed = True
            raise OSError("failure after auxiliaries were replaced")
        return real_replace(source, destination)

    monkeypatch.setattr("utils.ifdata_cache.base.os.replace", fail_metadata_once)
    result = cache.salvar_arquivo_local(candidate, {"total_registros": 1}, {
        dimension: extra, manifest: manifest_candidate,
    })
    assert not result.sucesso
    assert current_bytes(cache) == previous
    assert cache.carregar_local().dados.valor.tolist() == [10]


def test_auxiliary_only_contract_works_without_main_dataset(tmp_path):
    cache = AtomicExtraCache(tmp_path)
    candidate = tmp_path / "extra.parquet"
    frame().to_parquet(candidate, index=False)
    dimension = cache.cache_dir / "dimension.parquet"
    result = cache.salvar_arquivos_auxiliares({dimension: candidate})
    assert result.sucesso
    assert pd.read_parquet(dimension).valor.tolist() == [10]
    assert not cache.existe()
    assert not cache.arquivo_metadata_runtime.exists()


def test_sgs_overwrite_preserves_history_outside_requested_window(tmp_path, monkeypatch):
    from utils.ifdata_cache.sgs_credit import SGSCreditCache, _decorate
    from utils.sgs_credit_registry import bcb_series

    spec = list(bcb_series())[0]
    cache = SGSCreditCache(tmp_path)
    prior = _decorate(pd.DataFrame({"data": pd.to_datetime(["2025-01-01"]), "valor": [10.0]}), spec)
    assert cache.salvar_local(prior).sucesso
    fresh = _decorate(pd.DataFrame({"data": pd.to_datetime(["2026-01-01"]), "valor": [99.0]}), spec)
    monkeypatch.setattr(cache, "_fetch_series", lambda *args: fresh)
    result = cache.materialize_history(start="2026-01-01", end="2026-01-31", aliases=[spec.alias], overwrite=True)
    assert result.sucesso
    loaded = cache.carregar_local()
    assert loaded.dados.sort_values("data").valor.tolist() == [10.0, 99.0]
    assert loaded.metadata["periodos"] == ["202501", "202601"]


def test_sgs_series_failure_keeps_previous_generation(tmp_path, monkeypatch):
    from utils.ifdata_cache.sgs_credit import SGSCreditCache, _decorate
    from utils.sgs_credit_registry import bcb_series

    spec = list(bcb_series())[0]
    cache = SGSCreditCache(tmp_path)
    prior = _decorate(pd.DataFrame({"data": pd.to_datetime(["2025-01-01"]), "valor": [10.0]}), spec)
    assert cache.salvar_local(prior).sucesso
    previous = current_bytes(cache)

    def fail_series(*args):
        raise OSError("API failure")

    monkeypatch.setattr(cache, "_fetch_series", fail_series)
    result = cache.materialize_history(start="2026-01-01", end="2026-01-31", aliases=[spec.alias], overwrite=True)
    assert not result.sucesso
    assert current_bytes(cache) == previous
    assert cache.carregar_local().dados.valor.tolist() == [10.0]
