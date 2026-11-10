"""Garantia / Obrigações em arranjos: fórmula, cobertura da base versionada e tabela."""
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from tabs.arranjo_garantias import build_rows, detail_view, money, percent, render_table, sort_rows
from utils import arranjo_garantias as model

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "data/bundled/bloprudencial/dados.parquet"


def _accounts(rows):
    return pd.DataFrame(rows, columns=["DATA_BASE", "COD_CONGL", "NOME_CONGL", "CONTA", "SALDO"]).assign(DOCUMENTO="4060")


def test_months_run_from_start_to_today_and_periods_shift_across_years():
    assert model.months("202411", date(2025, 2, 10)) == ["202411", "202412", "202501", "202502"]
    assert model.shift_period("202601", 1) == "202512"
    assert model.shift_period("202606", 12) == "202506"


def test_ratio_sums_the_three_obligations_and_ignores_clearing_and_memo_by_default():
    series = model.build_series(_accounts([
        ("202606", "C1", "A", "44160000", 400e6), ("202606", "C1", "A", "49901000", 90e6), ("202606", "C1", "A", "49903000", 10e6),
        ("202606", "C1", "A", "13616000", 100e6), ("202606", "C1", "A", "13615000", 50e6), ("202606", "C1", "A", "30977000", 70e6),
    ]))
    row = series.iloc[0]
    assert row.obrigacoes == 500e6 and row.garantia_total == 100e6 and row.controle == 70e6
    assert row.razao == pytest.approx(.20)
    assert model.build_series(_accounts([
        ("202606", "C1", "A", "44160000", 500e6), ("202606", "C1", "A", "13616000", 100e6), ("202606", "C1", "A", "13615000", 50e6),
    ]), include_clearing=True).iloc[0].razao == pytest.approx(.30)


def test_duplicate_keys_are_not_summed_and_immaterial_base_has_no_ratio():
    series = model.build_series(_accounts([
        ("202606", "C1", "A", "44160000", 300e6), ("202606", "C1", "A", "44160000", 300e6), ("202606", "C1", "A", "13616000", 30e6),
        ("202606", "C2", "B", "44160000", 30_000.0), ("202606", "C2", "B", "13616000", 14e6),
    ]))
    by_code = series.set_index("COD_CONGL")
    assert by_code.loc["C1", "obrigacoes"] == 300e6 and by_code.loc["C1", "razao"] == pytest.approx(.10)
    assert pd.isna(by_code.loc["C2", "razao"]) and by_code.loc["C2", "garantia_total"] == 14e6
    assert model.build_series(pd.DataFrame()).empty


def test_bundled_base_has_every_account_of_the_formula_and_reproduces_afinz():
    """Se o BCB renumerar uma conta, a fórmula deixa de achá-la: este teste avisa antes da tela."""
    accounts = model.load_accounts(SimpleNamespace(arquivo_dados=BUNDLE), today=date(2026, 11, 10))
    latest = accounts.DATA_BASE.max()
    assert accounts.DATA_BASE.min() == model.START and latest >= "202606"
    assert set(accounts[accounts.DATA_BASE.eq(latest)].CONTA) == set(model.ROLE_BY_ACCOUNT)
    afinz = model.build_series(accounts).query("COD_CONGL == 'C0083539'").set_index("DATA_BASE")
    assert afinz.loc["202606", "obrigacoes"] == pytest.approx(525_967_390.25, abs=1)
    assert afinz.loc["202606", "garantia_total"] == pytest.approx(119_100_656.88, abs=1)
    assert afinz.loc["202606", "razao"] == pytest.approx(.2264, abs=.0005)
    # Até jan/26 o colateral estava em 1.3.6.15; a opção de câmaras dá a série contínua.
    assert afinz.loc["202512", "garantia_total"] == 0
    wide = model.build_series(accounts, include_clearing=True).query("COD_CONGL == 'C0083539'").set_index("DATA_BASE")
    assert wide.loc["202512", "razao"] == pytest.approx(.1249, abs=.0005)
    table = model.detail_table(accounts, model.build_series(accounts), "C0083539")
    assert table.loc["Obrigações do arranjo", "202606"] == pytest.approx(table.iloc[:3]["202606"].sum())


def _series():
    rows = []
    for period, obligations, collateral in (("202506", 400e6, 40e6), ("202605", 500e6, 60e6), ("202606", 500e6, 100e6)):
        rows += [(period, "C1", "BANCO A - PRUDENCIAL", "44160000", obligations), (period, "C1", "BANCO A - PRUDENCIAL", "13616000", collateral)]
    rows += [("202605", "C2", "BANCO <B>", "44160000", 900e6), ("202606", "C3", "BANCO C", "13616000", 5e6)]
    return model.build_series(_accounts(rows))


def test_rows_compare_with_previous_month_and_twelve_months_and_sort_keeps_missing_last():
    rows = build_rows(_series(), ["C3", "C1", "C2"])
    first = next(row for row in rows if row["code"] == "C1")
    assert first["cells"]["razao"] == {"raw": pytest.approx(.2), "value": "20,0%", "delta": "↑ 8,0 p.p.", "tone": "favorable", "annual": "↑ 10,0 p.p."}
    assert first["cells"]["obrigacoes"]["delta"] == "estável" and first["cells"]["obrigacoes"]["tone"] == ""
    assert first["spark"][-2:] == [pytest.approx(.12), pytest.approx(.2)] and len(first["spark"]) == 12
    assert [row["code"] for row in sort_rows(rows, "razao")] == ["C1", "C2", "C3"]
    assert [row["code"] for row in sort_rows(rows, "razao", descending=False)] == ["C2", "C1", "C3"]


def test_table_escapes_names_marks_older_dates_and_formats_in_portuguese():
    rows = build_rows(_series(), ["C1", "C2"])
    html = render_table(rows, "202606", lambda values, **_: "<svg/>", "razao")
    assert "BANCO &lt;B&gt;" in html and "<B>" not in html
    assert '<span class="date">Mai/26</span>' in html and html.count('class="date"') == 1
    assert 'class="sorted"' in html and "R$ 500,0 mi" in html and "20,0%" in html
    assert money(1_234_500_000) == "R$ 1,2 bi" and money(None) == "N/D" and percent(float("nan")) == "N/D"


def test_detail_shows_latest_month_first_in_millions():
    series = _series()
    accounts = _accounts([("202605", "C1", "A", "44160000", 500e6), ("202606", "C1", "A", "44160000", 500e6), ("202606", "C1", "A", "13616000", 100e6)])
    view = detail_view(model.detail_table(accounts, series, "C1"))
    assert list(view.columns)[:2] == ["Jun/26", "Mai/26"]
    assert view.loc["Obrigações do arranjo", "Jun/26"] == "500,0" and view.loc["Garantia / Obrigações", "Jun/26"] == "20,0%"
