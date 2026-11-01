"""Plano único de atualização e limpeza dos arquivos de operação."""
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
from types import SimpleNamespace

from tools.prune_caches import candidates
from tools.update_all import build_plan, run_plan


def test_plan_covers_every_domain_in_order_and_publishes_only_on_request():
    plan = build_plan(today=date(2026, 10, 31))
    assert [step["name"] for step in plan][0] == "Análise financeira"
    joined = " ".join(item for step in plan for item in step["command"])
    for kind in ("passivo", "dre_individual", "mercado_credito_sgs", "spb_meios_pagamento", "scr_data", "taxas_juros_historico"):
        assert kind in joined
    assert "--publish" not in joined and "--publish" in build_plan(publish=True)[0]["command"]
    assert "2026-08-02" in joined


def _runner(results, calls):
    def run(command, **kwargs):
        calls.append(command)
        return results.pop(0)
    return run


def test_a_failing_source_does_not_stop_the_others_and_quarter_flows_on(tmp_path):
    report = tmp_path / "r.json"
    report.write_text(json.dumps({"ifdata_period": "202606"}))
    calls = []
    results = [SimpleNamespace(returncode=0, stdout=json.dumps({"status": "updated", "report": str(report)}), stderr=""),
               SimpleNamespace(returncode=1, stdout="", stderr="queda"),
               SimpleNamespace(returncode=1, stdout="", stderr="fonte fora do ar"),
               SimpleNamespace(returncode=0, stdout="ok", stderr="")]
    plan = [{"name": "Análise financeira", "command": ["tools/update_financial_analysis.py"]},
            {"name": "B", "command": ["x"], "needs_quarter": True}, {"name": "C", "command": ["y"]}]
    summary = run_plan(tmp_path, plan, runner=_runner(results, calls))
    assert [step["status"] for step in summary["steps"]] == ["ok", "failed", "ok"] and summary["status"] == "partial"
    assert len(calls) == 4 and calls[1][-2:] == ["--periodos", "202606"] and summary["steps"][1]["detail"] == "fonte fora do ar"


def test_pending_review_is_reported_and_quarter_steps_wait_for_a_defined_quarter(tmp_path):
    results = [SimpleNamespace(returncode=0, stdout=json.dumps({"status": "needs_review"}), stderr=""), SimpleNamespace(returncode=0, stdout="", stderr="")]
    plan = [{"name": "Análise financeira", "command": ["tools/update_financial_analysis.py"]},
            {"name": "B", "command": ["x"], "needs_quarter": True}, {"name": "C", "command": ["y"]}]
    summary = run_plan(tmp_path, plan, runner=_runner(results, []))
    assert [step["status"] for step in summary["steps"]] == ["needs_review", "skipped", "ok"]


def test_prune_only_selects_operation_files_and_never_the_bases(tmp_path):
    reports = tmp_path / "data/cache/financial_analysis_updates"
    (reports / "uploads").mkdir(parents=True)
    for day in range(1, 5):
        (reports / f"2026010{day}T000000-a.json").write_text("{}")
    (reports / "job.json").write_text("{}")
    upload = reports / "uploads/antigo.csv"; upload.write_text("x")
    temporary = reports / "financial-analysis-x"; temporary.mkdir()
    base = tmp_path / "data/cache/dre/dados.parquet"; base.parent.mkdir(parents=True); base.write_text("x")
    old = (datetime.now(timezone.utc) - timedelta(days=30)).timestamp()
    os.utime(upload, (old, old)); os.utime(temporary, (old, old))
    found = {path.name for path in candidates(tmp_path, keep_reports=2)}
    assert found == {"20260101T000000-a.json", "20260102T000000-a.json", "antigo.csv", "financial-analysis-x"}


def test_admin_password_is_not_in_the_source_code():
    source = Path("app1.py").read_text(encoding="utf-8")
    assert "SENHA_ADMIN =" not in source and "TOMACONTA_ADMIN_PASSWORD" in source


def test_a_dropped_connection_gets_one_more_attempt(tmp_path):
    results = [SimpleNamespace(returncode=1, stdout="", stderr="IncompleteRead"), SimpleNamespace(returncode=0, stdout="", stderr="")]
    plan = [{"name": "Análise financeira", "command": ["tools/update_financial_analysis.py"]}, {"name": "SCR", "command": ["y"]}]
    summary = run_plan(tmp_path, plan[1:] and [{"name": "Primeira", "command": ["a"]}, *plan[1:]],
                       runner=_runner([SimpleNamespace(returncode=0, stdout="", stderr=""), *results], []))
    assert summary["steps"][1]["status"] == "ok" and summary["status"] == "ok"
