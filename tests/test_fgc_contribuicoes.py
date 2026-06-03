from pathlib import Path

import app1


APP_PATH = Path(__file__).resolve().parents[1] / "app1.py"


def _app_source() -> str:
    return APP_PATH.read_text(encoding="utf-8")


def test_fgc_period_discovery_scans_monthly_bloprudencial_csv_cache():
    source = _app_source()
    assert '"bcb_bloprudencial" / "csv"' in source
    assert '"bcb_bloprudencial" / "zips"' in source
    assert "_sondar_periodos_bloprudencial_bcb" in source


def test_cosif_period_selector_defaults_latest_and_previous():
    periodos_desc = ["202603", "202602", "202601", "202512"]

    assert app1._default_periodos_cosif(periodos_desc, 2) == ["202603", "202602"]
    assert app1._default_periodos_cosif(periodos_desc, 1) == ["202603"]
    assert app1._normalizar_periodos_cosif_selecionados(
        ["202601", "202603", "202602"],
        periodos_desc,
    ) == ["202603", "202602"]


def test_bloprudencial_probe_candidates_continue_after_latest_local_period():
    candidatos = app1._candidatos_sondagem_bloprudencial(["202512"])

    assert candidatos[:3] == ("202601", "202602", "202603")


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


def test_cosif_temporal_comparison_returns_delta_and_percent():
    resultado, erro = app1._comparar_valores_conta_bloprudencial(
        "202603",
        "202512",
        {"202603": 150.0, "202512": 100.0},
        "saldo_periodo",
    )
    assert erro is None
    assert resultado["Valor Atual"] == 150.0
    assert resultado["Valor Anterior"] == 100.0
    assert resultado["Variação"] == 50.0
    assert resultado["Variação %"] == 50.0


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


def test_cdsfn_default_prefix_prefers_reference_matching_document_period():
    refs = [
        {"prefixo": "A", "raw": "A122025"},
        {"prefixo": "T", "raw": "T032026"},
        {"prefixo": "T", "raw": "T032025"},
    ]
    assert app1._prefixo_default_cdsfn(refs, ["202603"], ["A", "T"]) == "T"
    assert app1._prefixo_default_cdsfn(refs, ["202512"], ["A", "T"]) == "A"
