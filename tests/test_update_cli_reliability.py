"""Contratos dos CLIs de atualização, sem consultas ou publicação remotas."""

from argparse import Namespace
from pathlib import Path

import pytest

from tools import refresh_cache_backend, update_caches_cli
from utils.ifdata_cache.base import CacheResult
from utils.ifdata_cache.update_state import UpdateRunStore, is_update_running, mutation_lock


def cli_args(**overrides):
    values = dict(
        tipo=["principal"], all=False, list=False, modo="incremental", intervalo=4,
        periodos="202603", ano_inicial=None, mes_inicial=None,
        ano_final=None, mes_final=None, mensal_inicio=None, mensal_fim=None,
        force_refresh=False, scr_ano_inicial=None, scr_ano_final=None, spb_datasets=None,
    )
    values.update(overrides)
    return Namespace(**values)


def refresh_args(**overrides):
    values = dict(
        snapshot_label="test", reason="test", dry_run=True,
        ano_inicial=2026, mes_inicial="03", ano_final=2026, mes_final="06",
        mensal_inicio="202603", mensal_fim="202606", intervalo=4,
        batch_size=1, retry_max=1, retry_delay=0, publish=False, publish_only=False,
        modo="overwrite",
    )
    values.update(overrides)
    return Namespace(**values)


@pytest.mark.parametrize("overrides", [
    {"mensal_inicio": "202613"}, {"periodos": "202600"}, {"intervalo": 0},
    {"periodos": None}, {"spb_datasets": "dataset_inexistente"},
])
def test_update_cli_rejects_inputs_before_mutations(overrides, tmp_path):
    with pytest.raises(ValueError):
        update_caches_cli._validate_cli_inputs(cli_args(**overrides))
    assert not list(tmp_path.iterdir())


def test_unknown_cache_is_rejected_before_other_sources(tmp_path):
    class Manager:
        @staticmethod
        def listar_caches():
            return ["principal"]

    with pytest.raises(ValueError, match="desconhecidos"):
        update_caches_cli._validate_cli_inputs(cli_args(tipo=["principal", "unknown"]), Manager())


def test_monthly_plan_does_not_change_quarterly_selection(tmp_path, monkeypatch):
    calls = []

    class Manager:
        base_dir = tmp_path

        @staticmethod
        def listar_caches():
            return ["bloprudencial", "principal"]

    monkeypatch.setattr(update_caches_cli, "_extract_with_receipt", lambda manager, **kwargs: (
        calls.append((kwargs["tipo"], kwargs["periodos"])) or CacheResult(True, "ok")
    ))
    monkeypatch.setattr(update_caches_cli, "materialize_for_publication", lambda *args, **kwargs: [])
    args = cli_args(tipo=["bloprudencial", "principal"], mensal_inicio="202604", mensal_fim="202605")
    assert update_caches_cli._execute(args, Manager()) == 0
    assert calls == [("bloprudencial", ["202604", "202605"]), ("principal", ["202603"])]


def test_cli_receipt_keeps_failed_period_pending(tmp_path):
    class Manager:
        base_dir = tmp_path

        def extrair_periodos_com_salvamento(self, **kwargs):
            assert kwargs["execution_periods"] == ["202603", "202606"]
            info = {
                "run_id": kwargs["run_id"], "execution_periods": kwargs["execution_periods"],
                "requested_periods": kwargs["execution_periods"], "persisted_periods": ["202603"],
                "extracted_periods": ["202603"], "pending_periods": ["202606"],
                "failed_periods": {"202606": "timeout"}, "status": "partial",
            }
            kwargs["callback_checkpoint"](info)
            return CacheResult(False, "timeout", metadata=info)

    result = update_caches_cli._extract_with_receipt(
        Manager(), tipo="principal", periodos=["202603", "202606"],
        modo="incremental", intervalo_salvamento=1,
    )
    assert not result.sucesso
    receipt = UpdateRunStore(tmp_path).latest("principal")
    assert receipt["persisted_periods"] == ["202603"]
    assert receipt["pending_periods"] == ["202606"]
    assert receipt["status"] == "partial"


@pytest.mark.parametrize("overrides", [
    {"mensal_fim": "202613"}, {"batch_size": -1}, {"retry_max": -1},
    {"retry_delay": 61}, {"intervalo": 0}, {"ano_final": 2025},
])
def test_refresh_validation_precedes_snapshot_or_lock(tmp_path, overrides):
    with pytest.raises(ValueError):
        refresh_cache_backend._run_refresh(refresh_args(**overrides), tmp_path)
    assert not list(tmp_path.iterdir())


def test_refresh_dry_run_does_not_create_runtime_files(tmp_path):
    (tmp_path / "data" / "cache").mkdir(parents=True)
    assert refresh_cache_backend._run_refresh(refresh_args(), tmp_path) == 0
    assert not (tmp_path / "data" / "cache_versions").exists()
    assert not (tmp_path / "data" / "cache" / ".update.lock").exists()


def test_restore_preserves_active_lock_and_durable_receipts(tmp_path, monkeypatch):
    cache = tmp_path / "data" / "cache"
    snapshot = tmp_path / "data" / "cache_versions" / "prior"
    snapshot.mkdir(parents=True)
    (snapshot / "dataset.parquet").write_bytes(b"old")
    (snapshot / ".update.lock").write_text("stale")
    (snapshot / "update_runs").mkdir()
    (snapshot / "update_checkpoint.json").write_text("old checkpoint")
    (snapshot / "update_job_status.json").write_text("old status")
    monkeypatch.setattr(refresh_cache_backend, "_create_snapshot", lambda *args, **kwargs: Path("backup"))
    store = UpdateRunStore(tmp_path)
    run = store.create("principal", ["202603"], "incremental")
    (cache / "dataset.parquet").write_bytes(b"new")
    (cache / "update_checkpoint.json").write_text("current checkpoint")
    (cache / "update_job_status.json").write_text("current status")
    with mutation_lock(tmp_path):
        inode = (cache / ".update.lock").stat().st_ino
        refresh_cache_backend._restore_snapshot(tmp_path, "prior")
        assert is_update_running(tmp_path)
        assert (cache / ".update.lock").stat().st_ino == inode
    assert (cache / "dataset.parquet").read_bytes() == b"old"
    assert store.load(run["run_id"])["periods"] == ["202603"]
    assert not (cache / "update_checkpoint.json").exists()
    assert not (cache / "update_job_status.json").exists()
    events = list((tmp_path / "data" / "cache_versions" / "restores").glob("*.json"))
    assert len(events) == 1
    import json
    event = json.loads(events[0].read_text())
    assert event["snapshot_id"] == "prior"
    assert event["backup_path"] == "backup"
    assert event["receipts_preserved"] is True


def test_refresh_rebuild_retry_preserves_prior_batches_and_finishes_ledger(tmp_path, monkeypatch):
    import pandas as pd

    from utils.ifdata_cache.base import BaseCache, CacheConfig
    from utils.ifdata_cache.manager import CacheManager
    from utils.ifdata_cache.update_state import load_cache_update_result

    class Cache(BaseCache):
        def __init__(self):
            super().__init__(CacheConfig(nome="test_cache", descricao="Teste", subdir="test_cache",
                                         colunas_obrigatorias=["Período"], relatorio_tipo=1), tmp_path)
            self.calls = []

        def baixar_remoto(self):
            raise AssertionError("rede bloqueada")

        def extrair_periodo(self, period, **kwargs):
            self.calls.append(period)
            if period == "202606" and self.calls.count(period) == 1:
                return CacheResult(False, "timeout")
            return CacheResult(True, "extraído", dados=pd.DataFrame({"Período": [period], "Valor": [1.0]}))

    manager = CacheManager.__new__(CacheManager)
    manager.base_dir = tmp_path
    cache = Cache()
    manager._caches = {"test_cache": cache}
    assert cache.salvar_local(pd.DataFrame({"Período": ["202512"], "Valor": [9.0]})).sucesso
    monkeypatch.setattr(refresh_cache_backend, "DEFAULT_TIPOS", ["test_cache"])
    monkeypatch.setattr(refresh_cache_backend, "CacheManager", lambda **kwargs: manager)
    monkeypatch.setattr(refresh_cache_backend, "_materialize_post_refresh_assets", lambda *args: [])
    monkeypatch.setattr(refresh_cache_backend, "_build_publish_runtime_manifest", lambda *args, **kwargs: {"gates": {}})
    monkeypatch.setattr(refresh_cache_backend, "_placeholder_validations", lambda *args: {})
    monkeypatch.setattr(refresh_cache_backend, "_git_head", lambda *args: "test")
    monkeypatch.setattr("utils.ifdata_cache.manager.time.sleep", lambda *_: None)
    assert refresh_cache_backend._run_refresh(refresh_args(dry_run=False, modo="rebuild"), tmp_path) == 0
    assert cache.calls == ["202603", "202606", "202606"]
    assert set(cache.carregar_local().dados["Período"]) == {"202603", "202606"}
    ledger = load_cache_update_result(tmp_path, "test_cache")
    assert ledger["status"] == "saved"
    assert ledger["pending_periods"] == []
    receipt = UpdateRunStore(tmp_path).latest("test_cache")
    assert receipt["status"] == "saved"
    assert receipt["mode"] == "rebuild"


@pytest.mark.parametrize("metadata", [{"falhas": {"serie": "timeout"}}, {"truncado": True},
                                     {"remaining_windows": 1}, {"finalized": False}])
def test_special_cli_incomplete_result_keeps_history_and_blocks_publication(tmp_path, metadata):
    from utils.ifdata_cache.release_ops import _assert_complete_update
    from utils.ifdata_cache.update_state import load_cache_update_result

    path = tmp_path / "history.parquet"
    path.write_bytes(b"previous history")

    class Manager:
        base_dir = tmp_path

    result = update_caches_cli._materialize_with_receipt(
        Manager(), "mercado_credito_sgs", "overwrite",
        lambda: CacheResult(True, "resposta parcial", metadata=metadata),
    )
    assert not result.sucesso
    assert path.read_bytes() == b"previous history"
    assert load_cache_update_result(tmp_path, "mercado_credito_sgs")["pending_periods"] == ["materialization"]
    assert UpdateRunStore(tmp_path).latest("mercado_credito_sgs")["mode"] == "overwrite"
    with pytest.raises(ValueError, match="incompleta"):
        _assert_complete_update(tmp_path, "mercado_credito_sgs")


@pytest.mark.parametrize("mode", ["incremental", "overwrite", "rebuild"])
def test_special_cli_accepts_selected_spb_supplement_without_main_dataset(tmp_path, mode):
    from utils.ifdata_cache.update_state import load_cache_update_result

    supplemental = tmp_path / "atm.parquet"
    supplemental.write_bytes(b"validated native adapter output")
    manifest = tmp_path / "spb_manifest.json"
    manifest.write_text("{}")

    class Cache:
        manifest_path = manifest

        @staticmethod
        def dataset_paths():
            return {"atm": supplemental, "nucleo_trimestral": tmp_path / "missing_main.parquet"}

    class Manager:
        base_dir = tmp_path

        @staticmethod
        def get_cache(tipo):
            return Cache()

    result = update_caches_cli._materialize_with_receipt(
        Manager(), "spb_meios_pagamento", mode,
        lambda: CacheResult(True, "dataset materializado"), options={"datasets": ["atm"]},
    )
    assert result.sucesso
    assert load_cache_update_result(tmp_path, "spb_meios_pagamento")["status"] == "saved"
    receipt = UpdateRunStore(tmp_path).latest("spb_meios_pagamento")
    assert receipt["mode"] == mode
    assert receipt["options"]["modo"] == mode
