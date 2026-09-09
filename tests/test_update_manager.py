"""Regressões pela entrada pública de atualização, sem acesso à rede."""

from unittest.mock import Mock

import pandas as pd
import pytest

from utils.ifdata_cache.base import BaseCache, CacheConfig, CacheResult
from utils.ifdata_cache.manager import CacheManager, gerar_periodos_trimestrais
from utils.ifdata_cache.update_state import load_cache_update_result


def test_quarterly_window_is_bounded_and_accepts_inverted_form():
    assert gerar_periodos_trimestrais(2028, '03', 2025, '12') == []
    assert gerar_periodos_trimestrais(2025, '12', 2026, '06') == ['202512', '202603', '202606']
    with pytest.raises(ValueError, match='Meses trimestrais'):
        gerar_periodos_trimestrais(2026, '01', 2026, '06')


def frame(period, value=1.0, *, column="Período"):
    return pd.DataFrame({"Instituição": ["Banco A"], column: [period], "Valor": [value]})


class FakeCache(BaseCache):
    def __init__(self, root):
        super().__init__(CacheConfig(
            nome="test_cache", descricao="Teste", subdir="test_cache",
            colunas_obrigatorias=["Período"], relatorio_tipo=1,
        ), root)
        self.extracted = []
        self.responses = {}
        self.save_calls = 0
        self.fail_save_at = None

    def baixar_remoto(self):
        raise AssertionError("Atualização não deve baixar cache remoto")

    def extrair_periodo(self, period, **kwargs):
        self.extracted.append(period)
        result = self.responses.get(period)
        if isinstance(result, Exception):
            raise result
        if result is not None:
            return result
        quarter = int(period[4:]) // 3
        return CacheResult(True, "extraído", frame(f"{quarter}/{period[:4]}", 2.0))

    def salvar_local(self, *args, **kwargs):
        self.save_calls += 1
        if self.save_calls == self.fail_save_at:
            return CacheResult(False, "disco sem espaço")
        return super().salvar_local(*args, **kwargs)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr("requests.sessions.Session.request", Mock(side_effect=AssertionError("rede bloqueada")))
    monkeypatch.setattr("utils.ifdata_cache.manager.time.sleep", lambda *_: None)
    manager = CacheManager.__new__(CacheManager)
    manager.base_dir = tmp_path
    cache = FakeCache(tmp_path)
    manager._caches = {"test_cache": cache}
    return manager, cache


def update(manager, periods=None, **kwargs):
    return manager.extrair_periodos_com_salvamento(
        "test_cache", periods if periods is not None else ["202603"], **kwargs,
    )


def test_full_execution_keeps_unprocessed_batches_pending_after_another_run(setup):
    manager, cache = setup
    plan = ["202603", "202606", "202609"]
    assert update(manager, ["202603"], execution_periods=plan).sucesso
    ledger = load_cache_update_result(manager.base_dir, cache.config.nome)
    assert ledger["status"] == "partial"
    assert ledger["pending_periods"] == ["202606", "202609"]
    assert update(manager, ["202612"]).sucesso
    ledger = load_cache_update_result(manager.base_dir, cache.config.nome)
    assert ledger["status"] == "partial"
    assert ledger["pending_periods"] == ["202606", "202609"]
    assert update(manager, ["202606", "202609"], execution_periods=plan).sucesso
    assert load_cache_update_result(manager.base_dir, cache.config.nome)["status"] == "saved"


@pytest.mark.parametrize("plan", [["202606"], ["202603", "202613"], []])
def test_invalid_full_execution_prevents_work(setup, plan):
    manager, cache = setup
    assert not update(manager, ["202603"], execution_periods=plan).sucesso
    assert cache.extracted == []


@pytest.mark.parametrize("mode", ["incremental", "overwrite"])
@pytest.mark.parametrize("source", ["runtime", "bundled"])
def test_preserves_history_from_readable_base(setup, mode, source):
    manager, cache = setup
    original = frame("4/2025")
    if source == "runtime":
        assert cache.salvar_local(original).sucesso
    else:
        cache.bundled_dir.mkdir(parents=True)
        original.to_parquet(cache.bundled_dir / cache.config.arquivo_dados, index=False)
    result = update(manager, modo=mode)
    assert result.sucesso
    assert set(cache.carregar_local().dados["Período"]) == {"4/2025", "1/2026"}
    assert result.metadata["status"] == "saved"
    assert result.metadata["persisted_periods"] == ["202603"]
    if source == "bundled":
        assert pd.read_parquet(cache.bundled_dir / cache.config.arquivo_dados).equals(original)


def test_rebuild_is_explicit(setup):
    manager, cache = setup
    cache.salvar_local(frame("4/2025"))
    result = update(manager, modo="rebuild")
    assert result.sucesso
    assert cache.carregar_local().dados["Período"].tolist() == ["1/2026"]


def test_unreadable_existing_base_blocks_before_extraction(setup):
    manager, cache = setup
    cache.cache_dir.mkdir(parents=True)
    cache.arquivo_dados_runtime.write_bytes(b"parquet incompleto")
    result = update(manager)
    assert not result.sucesso
    assert "ilegível" in result.mensagem
    assert not cache.extracted
    assert cache.save_calls == 0
    assert cache.arquivo_dados_runtime.read_bytes() == b"parquet incompleto"


@pytest.mark.parametrize("kwargs", [
    {"modo": "replace"}, {"intervalo_salvamento": 0}, {"intervalo_salvamento": True},
    {"periods": []}, {"periods": ["202613"]}, {"periods": ["000003"]},
    {"periods": ["202601"]}, {"periods": ["2026-03"]}, {"periods": ["202600"]},
])
def test_invalid_request_has_no_extraction_or_save(setup, kwargs):
    manager, cache = setup
    result = update(manager, **kwargs)
    assert not result.sucesso
    assert result.metadata["status"] == "failed"
    assert not cache.extracted
    assert cache.save_calls == 0


def test_periods_are_deduplicated_and_final_save_is_not_repeated(setup):
    manager, cache = setup
    callback = Mock()
    checkpoint = Mock()
    result = update(manager, ["202603", " 202603 "], intervalo_salvamento=1,
                    callback_salvamento=callback, callback_checkpoint=checkpoint)
    assert result.sucesso
    assert cache.extracted == ["202603"]
    assert cache.save_calls == 1
    assert callback.call_count == checkpoint.call_count == 1
    assert checkpoint.call_args.args[0]["persisted_periods"] == ["202603"]


@pytest.mark.parametrize("interval", [1, 4])
def test_save_failure_is_not_reported_as_saved(setup, interval):
    manager, cache = setup
    cache.fail_save_at = 1
    callback = Mock()
    checkpoint = Mock()
    result = update(manager, intervalo_salvamento=interval,
                    callback_salvamento=callback, callback_checkpoint=checkpoint)
    assert not result.sucesso
    assert result.dados is None
    assert result.metadata["extracted_periods"] == ["202603"]
    assert result.metadata["persisted_periods"] == []
    assert result.metadata["pending_periods"] == ["202603"]
    assert "disco sem espaço" in result.metadata["failed_periods"]["202603"]
    callback.assert_not_called()
    checkpoint.assert_not_called()


def test_save_failure_keeps_previously_confirmed_checkpoint(setup):
    manager, cache = setup
    cache.fail_save_at = 2
    result = update(manager, ["202603", "202606", "202609"], intervalo_salvamento=1)
    assert not result.sucesso
    assert result.metadata["status"] == "partial"
    assert result.metadata["persisted_periods"] == ["202603"]
    assert result.metadata["pending_periods"] == ["202606", "202609"]
    assert cache.extracted == ["202603", "202606"]
    assert cache.carregar_local().dados["Período"].tolist() == ["1/2026"]


def test_failed_period_preserves_previous_period_and_other_periods_are_saved(setup):
    manager, cache = setup
    cache.salvar_local(frame("1/2026", 8.0))
    cache.responses["202603"] = RuntimeError("API indisponível")
    result = update(manager, ["202603", "202606"])
    assert not result.sucesso
    assert result.metadata["status"] == "partial"
    assert result.metadata["persisted_periods"] == ["202606"]
    assert result.metadata["pending_periods"] == ["202603"]
    assert result.metadata["failed_periods"] == {"202603": "API indisponível"}
    data = cache.carregar_local().dados.set_index("Período")
    assert data.loc["1/2026", "Valor"] == 8.0
    assert data.loc["2/2026", "Valor"] == 2.0


@pytest.mark.parametrize("bad_data", [frame("4/2025"), pd.DataFrame(), frame(None)])
def test_invalid_extracted_frame_never_replaces_history(setup, bad_data):
    manager, cache = setup
    cache.salvar_local(frame("1/2026", 8.0))
    cache.responses["202603"] = CacheResult(True, "resultado inválido", bad_data)
    before = cache.arquivo_dados_runtime.read_bytes()
    result = update(manager)
    assert not result.sucesso
    assert result.metadata["persisted_periods"] == []
    assert cache.arquivo_dados_runtime.read_bytes() == before


def test_period_aliases_replace_same_competence_without_duplicate(setup):
    manager, cache = setup
    cache.salvar_local(pd.concat([frame("202512", column="Periodo"), frame("202603", column="Periodo")]))
    assert update(manager).sucesso
    saved = cache.carregar_local().dados
    assert saved.columns.tolist().count("Período") == 1
    assert "Periodo" not in saved.columns
    assert len(saved) == 2


def test_checkpoint_failure_is_explicit_and_stops_execution(setup):
    manager, cache = setup
    checkpoint = Mock(side_effect=OSError("manifesto indisponível"))
    callback = Mock()
    result = update(manager, ["202603", "202606"], intervalo_salvamento=1,
                    callback_checkpoint=checkpoint, callback_salvamento=callback)
    assert not result.sucesso
    assert result.metadata["status"] == "partial"
    assert result.metadata["persisted_periods"] == ["202603"]
    assert cache.extracted == ["202603"]
    assert "checkpoint" in result.mensagem
    assert "manifesto indisponível" in result.mensagem
    assert result.metadata["checkpoint_error"] == "manifesto indisponível"
    callback.assert_not_called()


def test_failed_final_checkpoint_cannot_claim_complete_success(setup):
    manager, cache = setup
    result = update(manager, callback_checkpoint=Mock(side_effect=OSError("checkpoint indisponível")))
    assert not result.sucesso
    assert result.metadata["pending_periods"] == []
    assert result.metadata["status"] == "partial"
    assert result.metadata["checkpoint_error"] == "checkpoint indisponível"
    assert cache.carregar_local().sucesso


def test_progress_callback_keeps_zero_based_contract(setup):
    manager, _ = setup
    progress = Mock()
    assert update(manager, ["202603", "202606"], callback_progresso=progress).sucesso
    assert [call.args for call in progress.call_args_list] == [
        (0, 2, "202603"), (1, 2, "202606"),
    ]


def test_individual_placeholders_are_rejected_before_save(setup):
    manager, cache = setup
    cache.config.nome = "principal_individual"
    data = frame("1/2026")
    data["Instituição"] = "[IF 123]"
    cache.responses["202603"] = CacheResult(True, "nomes incompletos", data)
    result = update(manager)
    assert not result.sucesso
    assert "não resolvido" in result.mensagem
    assert result.metadata["persisted_periods"] == []
    assert cache.save_calls == 0


def test_cache_ledger_preserves_all_pending_units_across_partial_resumes(setup):
    manager, cache = setup
    cache.responses["202603"] = RuntimeError("falha março")
    cache.responses["202609"] = RuntimeError("falha setembro")
    assert not update(manager, ["202603", "202606", "202609"]).sucesso
    ledger = load_cache_update_result(manager.base_dir, cache.config.nome)
    assert ledger["status"] == "partial"
    assert ledger["pending_periods"] == ["202603", "202609"]
    assert ledger["persisted_periods"] == ["202606"]

    del cache.responses["202603"]
    resumed = update(manager, ["202603"])
    assert resumed.sucesso
    assert resumed.metadata["requested_periods"] == ["202603"]
    ledger = load_cache_update_result(manager.base_dir, cache.config.nome)
    assert ledger["status"] == "partial"
    assert ledger["pending_periods"] == ["202609"]
    assert ledger["failed_periods"] == {"202609": "falha setembro"}
    assert ledger["requested_periods"] == ["202603", "202606", "202609"]

    del cache.responses["202609"]
    assert update(manager, ["202609"]).sucesso
    ledger = load_cache_update_result(manager.base_dir, cache.config.nome)
    assert ledger["status"] == "saved"
    assert ledger["pending_periods"] == []
    assert ledger["failed_periods"] == {}
    assert ledger["persisted_periods"] == ["202603", "202606", "202609"]


def test_unrelated_success_does_not_clear_previous_cache_pending_units(setup):
    manager, cache = setup
    cache.responses["202603"] = RuntimeError("pendente")
    assert not update(manager, ["202603"]).sucesso
    assert update(manager, ["202606"]).sucesso
    ledger = load_cache_update_result(manager.base_dir, cache.config.nome)
    assert ledger["status"] == "partial"
    assert ledger["pending_periods"] == ["202603"]


def test_completed_ledger_starts_new_operation_without_old_requested_units(setup):
    manager, cache = setup
    assert update(manager, ["202603"]).sucesso
    assert update(manager, ["202606"]).sucesso
    ledger = load_cache_update_result(manager.base_dir, cache.config.nome)
    assert ledger["requested_periods"] == ["202606"]
    assert ledger["status"] == "saved"


def test_cache_ledger_is_marked_before_extraction(setup, monkeypatch):
    manager, cache = setup
    extract = cache.extrair_periodo
    def check_before_extract(period, **kwargs):
        ledger = load_cache_update_result(manager.base_dir, cache.config.nome)
        assert ledger["status"] == "extracting"
        assert ledger["pending_periods"] == ["202603"]
        return extract(period, **kwargs)
    monkeypatch.setattr(cache, "extrair_periodo", check_before_extract)
    assert update(manager).sucesso


def test_initial_cache_ledger_failure_prevents_any_extraction(setup, monkeypatch):
    manager, cache = setup
    monkeypatch.setattr("utils.ifdata_cache.update_state.write_cache_update_result",
                        Mock(side_effect=OSError("ledger indisponível")))
    result = update(manager)
    assert not result.sucesso
    assert result.metadata["checkpoint_error"] == "ledger indisponível"
    assert not cache.extracted
    assert cache.save_calls == 0


@pytest.mark.parametrize("fail_from", [2, 3])
def test_cache_ledger_write_failure_never_leaves_saved_marker(setup, monkeypatch, fail_from):
    from utils.ifdata_cache.update_state import write_cache_update_result

    manager, cache = setup
    calls = 0
    def fail_ledger(root, name, metadata):
        nonlocal calls
        calls += 1
        if calls >= fail_from:
            raise OSError("ledger cheio")
        return write_cache_update_result(root, name, metadata)
    monkeypatch.setattr("utils.ifdata_cache.update_state.write_cache_update_result", fail_ledger)
    result = update(manager)
    assert not result.sucesso
    assert result.metadata["checkpoint_error"] == "ledger cheio"
    assert result.metadata["persisted_periods"] == ["202603"]
    ledger = load_cache_update_result(manager.base_dir, cache.config.nome)
    assert ledger["status"] == "extracting"
    assert cache.carregar_local().sucesso


def test_corrupt_cache_ledger_is_preserved_and_blocks_extraction(setup):
    manager, cache = setup
    assert update(manager).sucesso
    cache.extracted.clear()
    path = manager.base_dir / "data" / "cache" / "update_results" / f"{cache.config.nome}.json"
    path.write_text("{quebrado")
    result = update(manager, ["202606"])
    assert not result.sucesso
    assert result.metadata["checkpoint_error"]
    assert not cache.extracted
    assert path.read_text() == "{quebrado"
