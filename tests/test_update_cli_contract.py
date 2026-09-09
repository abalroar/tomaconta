from argparse import Namespace
from types import SimpleNamespace

import pytest

from tools import update_caches_cli as U, refresh_cache_backend as B
from utils.ifdata_cache import release_ops as R


@pytest.mark.parametrize("module", [U, B])
@pytest.mark.parametrize("start,end", [("202413", "202501"), ("202400", "202501"), ("202502", "202501"), ("000001", "202501"), ("2024ab", "202501")])
def test_monthly_bounds_are_rejected_before_iteration(module, start, end):
    with pytest.raises(ValueError):
        module._gerar_periodos_mensais(start, end)


@pytest.mark.parametrize("module", [U, B])
def test_monthly_valid_year_boundary(module):
    assert module._gerar_periodos_mensais("202412", "202502") == ["202412", "202501", "202502"]


def args(**changes):
    result = dict(intervalo=1, mensal_inicio=None, mensal_fim=None, ano_inicial=None, mes_inicial=None,
                  ano_final=None, mes_final=None, scr_ano_inicial=None, scr_ano_final=None,
                  all=False, tipo=["principal"], periodos="202603", modo="incremental", force_refresh=False)
    result.update(changes)
    return Namespace(**result)


@pytest.mark.parametrize("changes", [
    {"periodos": "202604"}, {"periodos": "202613"},
    {"ano_inicial": 2026, "mes_inicial": "06", "ano_final": 2026, "mes_final": "03"},
    {"mensal_inicio": "202413"}, {"ano_inicial": 2026}, {"intervalo": 0},
])
def test_update_cli_invalid_input_does_not_call_manager(changes):
    class NoCalls:
        def __getattr__(self, name):
            raise AssertionError(f"operação prematura: {name}")
    with pytest.raises(ValueError):
        U._execute(args(**changes), NoCalls())


def test_refresh_invalid_bounds_do_not_snapshot_or_create_cache(tmp_path, monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("não deve escrever antes de validar")
    monkeypatch.setattr(B, "_create_snapshot", unexpected)
    with pytest.raises(ValueError):
        B._run_refresh(args(ano_inicial=2026, mes_inicial="06", ano_final=2026, mes_final="03"), tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_source_changes_trigger_all_derived_consumers():
    assert R.get_postprocess_targets(["ativo"]) == ["derived_metrics", "derived_metrics_individual", "critical_screens"]
    assert R.get_postprocess_targets(["carteira_instrumentos"]) == ["derived_metrics", "critical_screens"]


def test_shared_materializer_excludes_consolidated_carteira_from_individual(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(R, "_hydrate_source_caches", lambda *a, **kw: ([], []))
    monkeypatch.setattr(R, "materialize_derived_metrics_cache", lambda **kw: calls.append(kw) or SimpleNamespace(sucesso=True, mensagem="ok"))
    result = R.materialize_for_publication(object(), base_dir=tmp_path, cache_names=["dre_individual"], save_bundled=False)
    assert result[0]["status"] == "ok"
    assert calls[0]["carteira_instrumentos_cache_name"] is None


def test_refresh_backend_uses_shared_materialization(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(B, "materialize_for_publication", lambda manager, **kw: calls.append(kw) or [
        {"cache": "derived_metrics_individual", "status": "ok", "message": "ok"}
    ])
    result = B._materialize_post_refresh_assets(tmp_path, object())
    assert calls[0]["cache_names"] == B.DEFAULT_TIPOS
    assert result[0]["tipo"] == "derived_metrics_individual"
