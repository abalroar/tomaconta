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
    ) == ["202603", "202602", "202601"]


def test_cosif_loader_keeps_bloprudencial_document_as_dimension_for_balance_accounts():
    df_4060 = app1._carregar_bloprud_conta_por_periodos(
        ("202512",),
        conta_cosif="6000000004",
        documento_bloprudencial="4060",
        loader_version="test_doc_4060",
    )
    df_4066 = app1._carregar_bloprud_conta_por_periodos(
        ("202512",),
        conta_cosif="6000000004",
        documento_bloprudencial="4066",
        loader_version="test_doc_4066",
    )

    original_4060 = df_4060[df_4060["Instituição"].astype(str).str.upper().str.contains("ORIGINAL", na=False)]
    original_4066 = df_4066[df_4066["Instituição"].astype(str).str.upper().str.contains("ORIGINAL", na=False)]

    assert "DOCUMENTO" in df_4060.columns
    assert set(original_4060["DOCUMENTO"].astype(str)) == {"4060"}
    assert set(original_4066["DOCUMENTO"].astype(str)) == {"4066"}
    assert round(float(original_4060["VALOR_CONTA"].iloc[0]), 2) == 1_792_476_703.73
    assert round(float(original_4066["VALOR_CONTA"].iloc[0]), 2) == 1_803_370_013.56


def test_bloprudencial_probe_candidates_continue_after_latest_local_period():
    candidatos = app1._candidatos_sondagem_bloprudencial(["202512"])

    assert candidatos[:3] == ("202601", "202602", "202603")


def test_fgc_required_periods_and_accumulated_formula_are_explicit():
    assert app1._periodos_requeridos_fgc("202509", "acumulado_semestral") == (
        ["202509"],
        "Acumulado semestral cru = 202509",
        None,
    )
    assert app1._periodos_requeridos_fgc("202509", "acumulado_anual") == (
        ["202506", "202509"],
        "Acumulado anual = 202506 + 202509",
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
    assert round(valor, 2) == round(-303_894_698.81, 2)
    assert componentes["periodo_base"] == ""

    valor_anual, componentes_anual, erro_anual = app1._calcular_valor_conta_bloprudencial(
        "202509",
        {"202506": -591_966_937.69, "202509": -303_894_698.81},
        "acumulado_anual",
    )
    assert erro_anual is None
    assert round(valor_anual, 2) == round(-591_966_937.69 + -303_894_698.81, 2)
    assert componentes_anual["periodo_base"] == "202506"

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
    assert app1._conta_bloprudencial_suporta_acumulacao(app1.COSIF_LUCRO_LIQUIDO_SINTETICO) is True
    assert app1._conta_bloprudencial_suporta_acumulacao("6100000007") is False
    assert app1._conta_bloprudencial_suporta_acumulacao("1000000009") is False
    assert app1._conta_bloprudencial_suporta_acumulacao("9000000000") is False
    assert app1._modos_disponiveis_conta_bloprudencial("8118500009", "202509") == [
        ("acumulado semestral cru", "acumulado_semestral"),
        ("acumulado anual", "acumulado_anual"),
        ("valor do trimestre", "trimestre"),
    ]
    assert app1._modos_disponiveis_conta_bloprudencial(app1.COSIF_LUCRO_LIQUIDO_SINTETICO, "202509") == [
        ("acumulado semestral cru", "acumulado_semestral"),
        ("acumulado anual", "acumulado_anual"),
    ]
    assert app1._modos_disponiveis_conta_bloprudencial("1000000009", "202509") == [
        ("saldo do período", "saldo_periodo"),
    ]
    assert app1._modos_disponiveis_conta_bloprudencial("6100000007", "202603") == [
        ("saldo do período", "saldo_periodo"),
    ]
    assert app1._modos_disponiveis_conta_bloprudencial("9000000000", "202603") == [
        ("saldo do período", "saldo_periodo"),
    ]


def test_bloprudencial_balance_loader_uses_prudential_name_and_deduplicates_raw_rows():
    df = app1._carregar_bloprud_conta_por_periodos(
        ("202512", "202601", "202602", "202603"),
        conta_cosif="6100000007",
        documento_bloprudencial="4060",
        loader_version="test_prudential_name_dedupe_610",
    )

    picpay = df[df["Instituição"].astype(str).eq("PICPAY - PRUDENCIAL")].sort_values("DATA_BASE")
    assert picpay["DATA_BASE"].tolist() == ["202512", "202601", "202602", "202603"]
    assert [round(float(v), 2) for v in picpay["VALOR_CONTA"].tolist()] == [
        1_463_704_444.67,
        2_480_376_659.68,
        2_480_378_997.33,
        2_480_384_920.71,
    ]

    cielo_dez25 = df[
        (df["DATA_BASE"].astype(str).eq("202512"))
        & (df["Instituição"].astype(str).eq("CIELO IP - PRUDENCIAL"))
    ]
    assert len(cielo_dez25) == 1
    assert round(float(cielo_dez25["VALOR_CONTA"].iloc[0]), 2) == 9_637_693_543.00


def test_lucro_liquido_cosif_netting_respects_positive_or_negative_debtor_sign():
    assert app1._calcular_lucro_liquido_cosif_raw(100.0, 30.0) == 70.0
    assert app1._calcular_lucro_liquido_cosif_raw(100.0, -30.0) == 70.0


def test_lucro_liquido_cosif_loader_nets_creditor_minus_debtor_magnitude():
    df = app1._carregar_lucro_liquido_cosif_por_periodos(
        ("202603",),
        documento_bloprudencial="4060",
        loader_version="test_lucro_liquido",
    )
    original = df[df["Instituição"].astype(str).str.upper().str.contains("ORIGINAL", na=False)]

    assert not original.empty
    row = original.iloc[0]
    assert row["CONTA"] == app1.COSIF_LUCRO_LIQUIDO_SINTETICO
    assert round(float(row["RESULTADO_CREDOR"]), 2) == 4_000_255_445.09
    assert round(float(row["RESULTADO_DEVEDOR"]), 2) == -3_891_527_400.43
    assert round(float(row["VALOR_CONTA"]), 2) == 108_728_044.66


def test_cdsfn_default_prefix_prefers_reference_matching_document_period():
    refs = [
        {"prefixo": "A", "raw": "A122025"},
        {"prefixo": "T", "raw": "T032026"},
        {"prefixo": "T", "raw": "T032025"},
    ]
    assert app1._prefixo_default_cdsfn(refs, ["202603"], ["A", "T"]) == "T"
    assert app1._prefixo_default_cdsfn(refs, ["202512"], ["A", "T"]) == "A"
