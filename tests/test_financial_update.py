"""Revisão de contas, decisão de linha e atualização por etapas."""
import json

import pandas as pd
import pytest

from tests.test_prudential_analysis import simple_sources  # noqa: F401
from utils.ifdata_cache.financial_analysis_review import account_changes, new_decisions, pending_items, row_jumps
from utils.prudential_analysis import dre_definitions, dre_row_for


def frame(rows):
    return pd.DataFrame([{"DATA_BASE": p, "DOCUMENTO": d, "COD_CONGL": c, "CONTA": a, "NOME_CONTA": n, "SALDO": s} for p, d, c, a, n, s in rows])


BASE = [("202605", "4060", "C1", "8199200005", "Provisão", -5e9), ("202605", "4060", "C1", "1110000006", "Caixa", 1e9),
        ("202605", "4060", "C1", "3000000007", "Compensação", 9e12)]


@pytest.mark.parametrize("code,row", [("8199200005", "provision"), ("8197000009", "other_exp"), ("7191500002", "sale"),
                                      ("8172700005", "people"), ("7940000001", "tax_income"), ("7500000006", None)])
def test_row_follows_the_longest_prefix(code, row):
    assert dre_row_for(code) == row


def test_recoded_provision_stops_for_review_and_decision_restores_the_row():
    now = [("202606", "4060", "C1", "8197000009", "Nova", -5e9), ("202606", "4060", "C1", "1110000006", "Caixa", 1e9)]
    items = account_changes(frame(BASE + now), "202606")
    by_kind = {item["kind"]: item for item in items}
    assert by_kind["nova"]["account"] == "8197000009" and by_kind["nova"]["row"] == "other_exp" and by_kind["nova"]["blocking"]
    assert by_kind["sumiu"]["row"] == "provision" and by_kind["sumiu"]["blocking"]
    assert pending_items(items, {by_kind["nova"]["id"]: {"row": "provision"}}) == [by_kind["sumiu"]["id"]]
    rules = {ident: rule for ident, _, _, rule in dre_definitions({"8197000009": "provision"})}
    assert ("8197000009", 1) in rules["provision"] and ("8197000009", -1) in rules["other_exp"]


def test_compensation_small_accounts_and_code_format_do_not_stop():
    now = [("202606", "4060", "C1", "3090000000", "Comp", 9e12), ("202606", "4060", "C1", "8197000009", "Pequena", -1e6),
           ("202606", "4060", "C1", "81992005", "Provisão oito dígitos", -5e9), ("202606", "4060", "C1", "1110000006", "Caixa", 1e9)]
    items = account_changes(frame(BASE + now), "202606")
    assert not pending_items(items, {})
    assert [item["account"] for item in items if item["kind"] == "nova"] == ["8197000009"]


def test_semester_close_is_expected_only_for_result_accounts_after_the_close():
    july = account_changes(frame(BASE[:2] + [("202607", "4060", "C1", "1110000006", "Caixa", 1e9)]), "202607")
    august = account_changes(frame(BASE[:2] + [("202608", "4060", "C1", "1110000006", "Caixa", 1e9)]), "202608")
    assert not july[0]["blocking"] and august[0]["blocking"]


def test_rename_is_visible_without_stopping():
    now = [("202606", "4060", "C1", "8199200005", "Outro nome", -5e9), ("202606", "4060", "C1", "1110000006", "Caixa", 1e9)]
    item = next(item for item in account_changes(frame(BASE + now), "202606") if item["kind"] == "renomeada")
    assert item["previous_name"] == "Provisão" and not item["blocking"]


@pytest.mark.parametrize("current,previous,flag", [(-100, -90, False), (100, -90, True), (-400, -100, True), (-20, -100, True), (0, 0, False)])
def test_row_jump(current, previous, flag):
    assert bool(row_jumps({"provision": [current, previous]}, "202606")) is flag


def test_decision_records_the_account_and_rejects_unknown_rows():
    recorded = new_decisions({"nova:4060:8197000009": {"row": "provision"}, "salto:provision:202606": {"row": None}}, "202606", "run")
    assert [item["account"] for item in recorded] == ["8197000009", None]
    with pytest.raises(ValueError):
        new_decisions({"nova:4060:8197000009": {"row": "x"}}, "202606", "run")
    with pytest.raises(ValueError):
        dre_definitions({"8197000009": "x"})


def test_full_flow_holds_review_then_applies_and_keeps_the_decision(tmp_path, monkeypatch, simple_sources):
    from tools import update_financial_analysis as cli
    from utils.ifdata_cache import BloprudencialCache
    monkeypatch.setattr("utils.ifdata_cache.release_ops.materialize_for_publication", lambda *args, **kwargs: [])
    root = tmp_path / "repo"; root.mkdir()
    path = tmp_path / "source.csv"
    simple_sources.rename(columns={"DATA_BASE": "#DATA_BASE"}).to_csv(path, sep=";", decimal=",", index=False)
    assert cli.update(root, csv=path, offline=True)[0]["status"] == "updated"
    # Mês seguinte com uma conta de resultado inédita, compensada para os totais fecharem.
    following = simple_sources.assign(DATA_BASE="202607")
    extra = following[following.DOCUMENTO.eq("4060")].iloc[:1].assign(CONTA="8197000009", NOME_CONTA="Nova", SALDO=-2e8)
    offset = following[following.DOCUMENTO.eq("4060")].iloc[:1].assign(CONTA="7197000000", NOME_CONTA="Par", SALDO=2e8)
    following = pd.concat([following, extra, offset])
    for account, change in (("8000000002", -2e8), ("8100000005", -2e8), ("7000000003", 2e8), ("7100000006", 2e8)):
        following.loc[following.DOCUMENTO.eq("4060") & following.CONTA.eq(account), "SALDO"] += change
    following.rename(columns={"DATA_BASE": "#DATA_BASE"}).to_csv(path, sep=";", decimal=",", index=False)
    active = BloprudencialCache(root).arquivo_dados
    before = active.read_bytes()
    checked, _ = cli.update(root, csv=path, offline=True, check_only=True)
    assert checked["status"] == "validated", checked
    assert checked["pending_review"] and active.read_bytes() == before
    held, _ = cli.update(root, csv=path, offline=True)
    assert held["status"] == "needs_review" and active.read_bytes() == before
    answers = {item: {"row": "provision"} if item.endswith("8197000009") else {"row": None} for item in held["pending_review"]}
    applied, _ = cli.update(root, csv=path, offline=True, decisions=answers)
    assert applied["status"] == "updated", applied
    cache = BloprudencialCache(root)
    assert cache.row_overrides() == {"8197000009": "provision"}


def test_decisions_survive_a_later_plain_save(tmp_path):
    from utils.ifdata_cache import BloprudencialCache
    cache = BloprudencialCache(tmp_path)
    data = pd.DataFrame({"DATA_BASE": ["202606"], "Período": ["202606"], "SALDO": [1.0]})
    decision = [{"account": "8197000009", "row": "provision"}]
    assert cache.salvar_local(data, fonte="teste", metadata_extra={"cosif_decisions": decision}).sucesso
    assert cache.salvar_local(data, fonte="teste").sucesso
    assert cache.cosif_decisions() == decision


def test_panel_marks_a_killed_process_as_interrupted_and_reads_the_latest_report(tmp_path):
    from tabs.financial_update_panel import _reports_dir, job_state, latest_report
    directory = _reports_dir(tmp_path)
    (directory / "job.json").write_text(json.dumps({"pid": 99999999, "stage": "x", "running": True}))
    assert job_state(tmp_path)["interrupted"]
    (directory / "20260101T000000-a.json").write_text('{"status": "failed"}')
    (directory / "20260201T000000-b.json").write_text('{"status": "updated"}')
    (directory / "decisions.json").write_text("{}")
    assert latest_report(tmp_path)[0]["status"] == "updated"


def test_installed_source_enters_runtime_with_its_own_signature(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import hashlib
    from utils.ifdata_cache import financial_analysis_update as subject
    source = tmp_path / "dados.parquet"; source.write_bytes(b"bytes")
    metadata = tmp_path / "metadata.json"; metadata.write_text('{"sha256": "antiga", "integridade": {}, "periodos": ["202606"]}')
    saved = []
    cache = SimpleNamespace(existe=lambda: False, existe_leitura=lambda: True, arquivo_dados=source, arquivo_metadata=metadata,
                            salvar_arquivo_local=lambda path, data: saved.append(data) or SimpleNamespace(sucesso=True, mensagem=""))
    monkeypatch.setattr("utils.ifdata_cache.release_ops._publication_scope", lambda names: (["a"], []))
    subject.activate_installed_sources(SimpleNamespace(get_cache=lambda name: cache), ["a"])
    assert saved == [{"sha256": hashlib.sha256(b"bytes").hexdigest(), "periodos": ["202606"]}]


def _published(frame, decisions=None):
    from hashlib import sha256
    from io import BytesIO
    from unittest.mock import Mock
    buffer = BytesIO()
    frame.to_parquet(buffer, index=False)
    raw = buffer.getvalue()
    def fake_get(url, **kwargs):
        response = Mock(status_code=200, content=raw)
        response.raise_for_status = lambda: None
        response.json = lambda: {"cosif_decisions": decisions or []}
        return response
    info = {"cache": "bloprudencial", "exists": True, "sha256": sha256(raw).hexdigest(), "record_count": len(frame), "max_period_ref": str(frame.DATA_BASE.max())}
    return info, fake_get, sha256(raw).hexdigest()


def _cosif(*periods):
    return pd.DataFrame([{"DATA_BASE": period, "Período": period, "DOCUMENTO": "4060", "COD_CONGL": "C1", "CONTA": "1000000009", "SALDO": 1.0} for period in periods])


def test_newer_published_month_replaces_the_installed_base_with_its_decisions(tmp_path, monkeypatch):
    from hashlib import sha256
    from utils.ifdata_cache import BloprudencialCache
    from utils.individual_release_cache import ensure_published_bloprudencial
    cache = BloprudencialCache(tmp_path)
    assert cache.salvar_local(_cosif("202606"), fonte="teste").sucesso
    decision = [{"id": "nova:4060:8197000009", "account": "8197000009", "row": "provision"}]
    info, fake_get, digest = _published(_cosif("202606", "202607"), decision)
    monkeypatch.setattr("utils.individual_release_cache.requests.get", fake_get)
    assert ensure_published_bloprudencial(cache, info, "https://exemplo/release") is True
    assert sha256(cache.read_data_file.read_bytes()).hexdigest() == digest
    assert cache.row_overrides() == {"8197000009": "provision"}
    # Uma nova sessão enxerga a mesma competência e não baixa de novo.
    monkeypatch.setattr("utils.individual_release_cache.requests.get", lambda *a, **k: pytest.fail("sem download"))
    fresh = BloprudencialCache(tmp_path)
    assert ensure_published_bloprudencial(fresh, info, "https://exemplo/release") is False
    assert pd.read_parquet(fresh.arquivo_dados).DATA_BASE.max() == "202607"


def test_older_or_equal_release_never_replaces_the_installed_base(tmp_path, monkeypatch):
    from utils.ifdata_cache import BloprudencialCache
    from utils.individual_release_cache import ensure_published_bloprudencial
    cache = BloprudencialCache(tmp_path)
    assert cache.salvar_local(_cosif("202606"), fonte="teste").sucesso
    before = cache.read_data_file.read_bytes()
    monkeypatch.setattr("utils.individual_release_cache.requests.get", lambda *a, **k: pytest.fail("sem download"))
    for period in ("202606", "202605"):
        assert ensure_published_bloprudencial(cache, {"max_period_ref": period, "sha256": "0" * 64}, "https://exemplo/release") is False
    assert cache.read_data_file.read_bytes() == before
