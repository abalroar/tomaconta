"""Fluxo real manager/persistência/serviço com fontes pequenas e determinísticas."""
import ast
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from utils.ifdata_cache.base import BaseCache, CacheConfig, CacheResult
from utils.ifdata_cache.diagnostics import max_period_from_values
from utils.ifdata_cache.manager import CacheManager
from utils.ifdata_cache.update_service import prepare_run, run_quarterly_update, save_period_window
from utils.ifdata_cache.update_state import UpdateRunStore, UpdateStateError, load_cache_update_result


class Source(BaseCache):
    def __init__(self, root):
        super().__init__(CacheConfig(nome="test_cache", descricao="Teste", subdir="test_cache",
                                     relatorio_tipo=1, colunas_obrigatorias=["Período"]), root)
        self.calls = []
        self.failing = set()

    def baixar_remoto(self):
        raise AssertionError("Fonte remota não deve ser usada")

    def extrair_periodo(self, period, **kwargs):
        self.calls.append(period)
        if period in self.failing:
            return CacheResult(False, "timeout")
        return CacheResult(True, "extraído", dados=pd.DataFrame({"Período": [period], "Valor": [2.0]}))


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    monkeypatch.setattr("utils.ifdata_cache.manager.time.sleep", lambda *_: None)
    manager = CacheManager.__new__(CacheManager)
    manager.base_dir = tmp_path
    source = Source(tmp_path)
    manager._caches = {"test_cache": source}
    source.salvar_local(pd.DataFrame({"Período": ["202512"], "Valor": [1.0]}))
    return manager, source


@pytest.mark.parametrize("periods", [["202601"], [], ["202601", "202603"], ["202601", None]])
def test_incomplete_monthly_window_keeps_previous_files_unchanged(pipeline, periods):
    manager, source = pipeline
    assert source.salvar_local(pd.DataFrame({
        "Período": ["202512", "202601", "202602"], "Valor": [1.0, 2.0, 3.0],
    })).sucesso
    before = (source.arquivo_dados_runtime.read_bytes(), source.arquivo_metadata_runtime.read_bytes())
    incomplete = pd.DataFrame({"Período": periods, "Valor": [20.0] * len(periods)})
    result = save_period_window(manager, "test_cache", incomplete, ["202601", "202602"], fonte="api")
    assert not result.sucesso
    assert (source.arquivo_dados_runtime.read_bytes(), source.arquivo_metadata_runtime.read_bytes()) == before
    assert source.carregar_local().dados["Valor"].tolist() == [1.0, 2.0, 3.0]


def test_real_batches_resume_failed_unit_preserve_history_and_publish_once(pipeline):
    manager, source = pipeline
    store, run = prepare_run(manager, "test_cache", ["202603", "202606"], "overwrite",
                             {"batch_size": 1, "intervalo_save": 1})
    publications = []
    def publish(record, details):
        publications.append(record["run_id"])
        return True, "verified", {"published_caches": ["test_cache"]}

    _, first = run_quarterly_update(manager, store, run, publish=publish)
    assert first["status"] == "partial"
    assert publications == []
    source.failing.add("202606")
    result, failed = run_quarterly_update(manager, store, first, publish=publish)
    assert not result.sucesso
    assert failed["persisted_periods"] == ["202603"]
    assert failed["pending_periods"] == ["202606"]
    assert publications == []
    source.failing.clear()
    _, frozen = prepare_run(manager, "test_cache", ["202609"], "rebuild", {"batch_size": 99}, resume_id=run["run_id"])
    result, final = run_quarterly_update(manager, store, frozen, publish=publish)
    assert result.sucesso
    assert final["status"] == "published"
    assert final["periods"] == ["202603", "202606"]
    assert final["mode"] == "overwrite"
    assert publications == [run["run_id"]]
    assert set(source.carregar_local().dados["Período"]) == {"202512", "202603", "202606"}
    assert load_cache_update_result(manager.base_dir, "test_cache")["status"] == "saved"
    # Uma segunda thread lançada com o mesmo registro antigo não rebaixa a conclusão.
    with pytest.raises(UpdateStateError, match="já encerrada"):
        run_quarterly_update(manager, store, run, publish=publish)
    assert store.load(run["run_id"])["status"] == "published"
    assert publications == [run["run_id"]]


def test_final_ledger_failure_is_reconfirmed_for_full_plan(pipeline, monkeypatch):
    from utils.ifdata_cache import update_state
    manager, source = pipeline
    store, run = prepare_run(manager, "test_cache", ["202603", "202606"], "incremental",
                             {"batch_size": 2, "intervalo_save": 1})
    original = update_state.write_cache_update_result
    def fail_final(root, name, metadata):
        if metadata["status"] == "saved":
            raise OSError("final ledger disk error")
        return original(root, name, metadata)
    monkeypatch.setattr(update_state, "write_cache_update_result", fail_final)
    result, failed = run_quarterly_update(manager, store, run)
    assert not result.sucesso
    assert failed["status"] == "failed"
    assert failed["pending_periods"] == []
    assert load_cache_update_result(manager.base_dir, "test_cache")["status"] == "extracting"
    monkeypatch.setattr(update_state, "write_cache_update_result", original)
    result, repaired = run_quarterly_update(manager, store, failed)
    assert result.sucesso
    assert repaired["status"] == "saved"
    assert source.calls == ["202603", "202606", "202603", "202606"]
    assert load_cache_update_result(manager.base_dir, "test_cache")["pending_periods"] == []


def app_helper(name, **globals):
    source = (Path(__file__).parents[1] / "app1.py").read_text()
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == name)
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), node], type_ignores=[])
    namespace = dict(globals)
    exec(compile(ast.fix_missing_locations(module), "app1.py", "exec"), namespace)
    return namespace[name]


@pytest.mark.parametrize("cache,old,new,key", [
    ("principal", "202512", "202606", "quarterly"),
    ("bloprudencial", "202606", "202608", "monthly"),
])
def test_publication_period_uses_preserved_latest_history(cache, old, new, key):
    expected = app_helper("_expected_periods_publicacao", max_period_from_values=max_period_from_values)
    manager = SimpleNamespace(info=lambda name: {"periodos": [old, new]})
    assert expected(manager, cache, [old]) == {key: new}


def test_checkpoint_controls_read_only_selected_cache(tmp_path):
    from utils.ifdata_cache.update_service import checkpoint_view, resumable_run
    store = UpdateRunStore(tmp_path)
    principal = store.create("principal", ["202603"])
    capital = store.create("capital", ["202606"])
    checkpoint = app_helper("_carregar_checkpoint_atualizacao", APP_DIR=tmp_path, UpdateRunStore=UpdateRunStore,
                            resumable_run=resumable_run, checkpoint_view=checkpoint_view)
    assert checkpoint("principal")["run_id"] == principal["run_id"]
    assert checkpoint("capital")["run_id"] == capital["run_id"]
    store.create("spb_meios_pagamento", ["materialization"])
    assert checkpoint("spb_meios_pagamento") == {}
