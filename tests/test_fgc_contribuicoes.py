from pathlib import Path

import app1


APP_PATH = Path(__file__).resolve().parents[1] / "app1.py"


def _app_source() -> str:
    return APP_PATH.read_text(encoding="utf-8")


def test_fgc_period_discovery_scans_monthly_bloprudencial_csv_cache():
    source = _app_source()
    assert '"bcb_bloprudencial" / "csv"' in source
    assert '"bcb_bloprudencial" / "zips"' in source


def test_fgc_required_periods_and_accumulated_formula_are_explicit():
    assert app1._periodos_requeridos_fgc("202509", "acumulado_semestral") == (
        ["202506", "202509"],
        "Acumulado semestral = 202509 + 202506",
        None,
    )
    assert app1._periodos_requeridos_fgc("202509", "saldo_periodo") == (
        ["202509"],
        "Saldo do período = 202509",
        None,
    )
    assert app1._periodos_requeridos_fgc("202512", "trimestre") == (
        ["202509", "202512"],
        "Trimestre = 202512 - 202509",
        None,
    )


def test_fgc_value_reconstruction_matches_semester_and_quarter_rules():
    valor, componentes, erro = app1._calcular_valor_conta_bloprudencial(
        "202509",
        {"202506": -591_966_937.69, "202509": -303_894_698.81},
        "acumulado_semestral",
    )
    assert erro is None
    assert round(valor, 2) == round(-591_966_937.69 + -303_894_698.81, 2)
    assert componentes["periodo_base"] == "202506"

    valor_tri, componentes_tri, erro_tri = app1._calcular_valor_conta_bloprudencial(
        "202512",
        {"202509": -303_894_698.81, "202512": -616_359_344.26},
        "trimestre",
    )
    assert erro_tri is None
    assert round(valor_tri, 2) == round(-616_359_344.26 - (-303_894_698.81), 2)
    assert componentes_tri["periodo_base"] == "202509"

    valor_saldo, _, erro_saldo = app1._calcular_valor_conta_bloprudencial(
        "202509",
        {"202509": 123.45},
        "saldo_periodo",
    )
    assert erro_saldo is None
    assert valor_saldo == 123.45


def test_fgc_only_enables_accumulated_modes_for_result_accounts():
    assert app1._conta_bloprudencial_suporta_acumulacao("8118500009") is True
    assert app1._conta_bloprudencial_suporta_acumulacao("1000000009") is False
    assert app1._modos_disponiveis_conta_bloprudencial("8118500009", "202509") == [
        ("acumulado semestral", "acumulado_semestral"),
        ("valor do trimestre", "trimestre"),
    ]
    assert app1._modos_disponiveis_conta_bloprudencial("1000000009", "202509") == [
        ("saldo do período", "saldo_periodo"),
    ]
