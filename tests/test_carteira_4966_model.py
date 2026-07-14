from io import BytesIO

import openpyxl
import pandas as pd
import pytest

from tabs.carteira_4966 import (
    EXPECTED_LOSS_COLUMNS,
    ROW_SPECS,
    TITLE,
    build_carteira_4966_excel,
    build_carteira_4966_model,
    format_brl_millions,
    format_percentage,
    model_to_audit_dataframe,
    render_carteira_4966_html,
)


MM = 1_000_000.0


def _carteira_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Instituição": ["BANCO TESTE - PRUDENCIAL"] * 4,
            "Período": ["1/2025", "2/2025", "4/2025", "1/2026"],
            "C1": [10, 12, 20, 22],
            "C2": [10, 12, 20, 22],
            "C3": [10, 12, 20, 22],
            "C4": [20, 24, 40, 44],
            "C5": [50, 60, 100, 110],
            "Total não Individualizado": [5, 6, 10, 11],
            "Carteira não Informada ou não se Aplica": [10, 12, 20, 22],
            "Total Exterior": [20, 24, 40, 44],
            "Total Geral": [135, 162, 270, 297],
            "Inadimplência": [10, None, 30, 33],
        }
    ).assign(
        **{
            column: lambda frame, column=column: frame[column] * MM
            for column in [
                "C1",
                "C2",
                "C3",
                "C4",
                "C5",
                "Total não Individualizado",
                "Carteira não Informada ou não se Aplica",
                "Total Exterior",
                "Total Geral",
                "Inadimplência",
            ]
        }
    )


def _ativo_frame() -> pd.DataFrame:
    rows = []
    for period, multiplier in zip(["1/2025", "2/2025", "4/2025", "1/2026"], [1, 1.2, 2, 2.2]):
        row = {
            "Instituição": "BANCO TESTE - PRUDENCIAL",
            "Período": period,
            EXPECTED_LOSS_COLUMNS[0]: -10 * multiplier * MM,
            EXPECTED_LOSS_COLUMNS[1]: -2 * multiplier * MM,
            EXPECTED_LOSS_COLUMNS[2]: -3 * multiplier * MM,
            EXPECTED_LOSS_COLUMNS[3]: -5 * multiplier * MM,
            "Hedge de Valor Justo (e3)": 100 * multiplier * MM,
            "Ajuste a Valor Justo (g4)": 50 * multiplier * MM,
        }
        rows.append(row)
    return pd.DataFrame(rows)


def _model():
    return build_carteira_4966_model(
        _carteira_frame(),
        _ativo_frame(),
        ["1/2026", "1/2025", "4/2025", "2/2025"],
    )


def test_model_uses_latest_q4_as_common_base_and_period_specific_ratios():
    model = _model()

    assert model.periods == ("1/2025", "2/2025", "4/2025", "1/2026")
    assert model.base_period == "4/2025"
    assert model.base_value == pytest.approx(270 * MM)
    assert model.cells["total_portfolio"]["1/2025"].secondary == pytest.approx(135 / 270)
    assert model.cells["c5"]["1/2025"].secondary == pytest.approx(50 / 270)
    assert model.cells["delinquency"]["1/2025"].secondary == pytest.approx(10 / 135)
    assert model.cells["delinquency"]["2/2025"].primary is None
    assert model.cells["delinquency"]["2/2025"].secondary is None
    assert model.qoq["2/2025"] == pytest.approx(162 / 135 - 1)
    assert model.qoq["1/2026"] == pytest.approx(297 / 270 - 1)


def test_provision_is_literal_expected_loss_and_excludes_hedge_and_fair_value():
    model = _model()

    provision = model.cells["provision"]["4/2025"].primary
    assert provision == pytest.approx(40 * MM)
    assert model.cells["provision_over_portfolio"]["4/2025"].primary == pytest.approx(40 / 270)
    assert model.cells["provision_over_c5"]["4/2025"].primary == pytest.approx(40 / 100)
    assert model.cells["provision_over_delinquency"]["4/2025"].primary == pytest.approx(40 / 30)


def test_missing_source_and_zero_denominator_stay_distinct_from_published_zero():
    carteira = _carteira_frame().query("`Período` == '1/2025'").copy()
    carteira.loc[:, "C5"] = 0.0
    carteira.loc[:, "Inadimplência"] = 0.0
    carteira.loc[:, "Total Geral"] = 0.0
    ativo = _ativo_frame().query("`Período` == '1/2025'").copy()
    for column in EXPECTED_LOSS_COLUMNS:
        ativo.loc[:, column] = 0.0

    model = build_carteira_4966_model(carteira, ativo, ["1/2025"])

    assert model.cells["provision"]["1/2025"].primary == 0.0
    assert model.cells["provision_over_portfolio"]["1/2025"].primary is None
    assert model.cells["provision_over_c5"]["1/2025"].primary is None
    assert model.cells["provision_over_delinquency"]["1/2025"].primary is None

    without_ativo = build_carteira_4966_model(carteira, pd.DataFrame(), ["1/2025"])
    assert without_ativo.missing_provision_periods == ("1/2025",)


def test_without_q4_the_latest_displayed_period_becomes_the_base():
    model = build_carteira_4966_model(
        _carteira_frame(),
        _ativo_frame(),
        ["1/2025", "2/2025"],
    )

    assert model.base_period == "2/2025"
    assert model.cells["total_portfolio"]["2/2025"].secondary == pytest.approx(1.0)


def test_html_has_exact_structure_hatched_highlight_and_missing_marker():
    model = _model()
    rendered = render_carteira_4966_html(model)

    assert TITLE in rendered
    assert "repeating-linear-gradient" in rendered
    assert 'role="region"' in rendered
    assert 'tabindex="0"' in rendered
    assert rendered.count('<tbody data-group=') == 3
    assert 'colspan="2"' in rendered
    assert "Vencidos acima de 90 dias (conceito de arrasto)" in rendered
    assert "N/D" in rendered
    assert "&gt;" not in rendered
    assert "—" not in rendered


def test_audit_dataframe_scales_only_currency_values_to_millions():
    audit = model_to_audit_dataframe(_model()).set_index("Indicador")

    assert audit.loc["Carteira total", "Dez/25 (R$ mm)"] == pytest.approx(270)
    assert audit.loc["Carteira total", "Dez/25 (%)"] == pytest.approx(100)
    assert audit.loc["Provisão do banco", "Dez/25 (R$ mm)"] == pytest.approx(40)
    assert audit.loc["Provisão total / C5", "Dez/25 (%)"] == pytest.approx(40)
    assert format_brl_millions(1_234_567_890) == "1.235"


def test_percentage_format_preserves_rates_below_half_percent():
    assert format_percentage(0.0049, 1) == "0,5%"
    assert format_percentage(0.0005, 1) == "0,1%"
    assert format_percentage(-0.0001, 0) == "0%"


def test_excel_matches_row_spec_order_units_and_hatched_marker():
    workbook = openpyxl.load_workbook(BytesIO(build_carteira_4966_excel(_model())), data_only=True)

    assert workbook.sheetnames == ["Modelo 4966", "Glossário"]
    sheet = workbook["Modelo 4966"]
    assert sheet["B1"].value == TITLE
    assert sheet["A5"].fill.patternType is not None

    labels = [sheet.cell(row=row, column=2).value for row in range(1, sheet.max_row + 1)]
    rendered_rows = [label for label in labels if label in {spec.label for spec in ROW_SPECS}]
    assert rendered_rows == [spec.label for spec in ROW_SPECS]

    carteira_row = labels.index("Carteira total") + 1
    provision_row = labels.index("Provisão do banco") + 1
    provision_ratio_row = labels.index("Provisão total / Carteira") + 1
    assert sheet.cell(carteira_row, 7).value == pytest.approx(270)
    assert sheet.cell(carteira_row, 8).value == pytest.approx(1.0)
    assert sheet.cell(provision_row, 7).value == pytest.approx(40)
    assert sheet.cell(provision_row, 7).number_format == "#,##0"
    assert sheet.cell(provision_ratio_row, 2).border.left.style is not None
    assert sheet.cell(provision_ratio_row, 3).border.left.style is not None
    assert sheet.cell(provision_ratio_row, 4).border.right.style is not None
