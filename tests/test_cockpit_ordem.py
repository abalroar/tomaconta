"""Ordenação do Cockpit."""
from tabs.cockpit import ORDER_PORTFOLIO, ORDER_TREND, metric_configs, render_table, sort_rows


def row(bank, ativo, state="flat", worse=0):
    cells = {cfg["label"]: {"value": "x", "delta": "—", "tone": "neutral", "reference": "QoQ", "annual": "—", "raw": None} for cfg in metric_configs()}
    cells["Ativo Total"]["raw"] = ativo
    return {"bank": bank, "period": "2/2026", "spark": [None], "spark_kind": "line", "cells": cells, "trend": {"state": state, "reason": "r", "worse": worse}}


ROWS = [row("A", 10, "up"), row("B", None, "down", 1), row("C", 30, "down", 3), row("D", 0, "flat")]


def names(rows):
    return [item["bank"] for item in rows]


def test_metric_order_goes_both_ways_and_missing_stays_last():
    assert names(sort_rows(ROWS, "Ativo Total")) == ["C", "A", "D", "B"]
    assert names(sort_rows(ROWS, "Ativo Total", False)) == ["D", "A", "C", "B"]


def test_trend_puts_the_worst_first_and_portfolio_keeps_the_saved_order():
    assert names(sort_rows(ROWS, ORDER_TREND)) == ["C", "B", "D", "A"]
    assert names(sort_rows(ROWS, ORDER_PORTFOLIO)) == ["A", "B", "C", "D"]


def test_table_marks_the_sorted_column_and_names_the_chart():
    api = {"_snap_sparkbars_svg": None, "_snap_sparkline_svg": None, "periodo_para_exibicao": str}
    html = render_table(ROWS[:1], "2/2026", api, "Ativo Total", "Ativo")
    assert '<th class="sorted">Ativo</th>' in html and "Evolução · Ativo" in html


def test_rename_keeps_the_banks_and_refuses_an_existing_name():
    import pytest
    from utils import cockpit_store as store
    ids = {"A": "C1", "B": "C2"}
    data = store.upsert(store.upsert(store.empty(), "Mizael", ["A"], ids), "Natalia", ["B"], ids)
    renamed = store.rename(data, "mizael", "Mizael Silva")
    assert [m["id"] for m in store.find(renamed, "Mizael Silva")["membros"]] == ["C1"] and store.find(renamed, "Mizael") is None
    assert store.find(store.rename(data, "mizael", "MIZAEL"), "mizael")["nome"] == "MIZAEL"
    with pytest.raises(ValueError, match="Já existe"):
        store.rename(data, "Mizael", "natalia")
