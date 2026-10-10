import app1
import pandas as pd
import pytest
import re
from xml.etree import ElementTree


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), float("-inf"), pd.NA, "sem dado"])
def test_snapshot_formats_missing_or_invalid_values_as_nd(value):
    for cfg in ({"format_key": "Ativo Total"}, {"format_key": "Desp Captação / Captação", "is_pct": True}):
        assert app1._formatar_valor_snapshot(cfg, value) == "N/D"


@pytest.mark.parametrize("label,key", [
    ("Crédito / Captações", "Carteira de Crédito/Core Funding (%)"),
    ("Custo anualizado de captação", "Desp Captação / Captação"),
])
def test_snapshot_funding_zero_is_a_value_and_missing_data_keeps_its_marker(label, key):
    cfg = {"label": label, "format_key": key, "is_pct": True, "serie": {"2/2026": 0.0}}
    assert app1._formatar_valor_snapshot(cfg, 0.0) == "0,00%"
    marker, _ = app1._snapshot_metric_status_note(label=label, periodo_ref="2/2026", valor_atual=0.0)
    assert marker == ""
    zero_html = app1._render_snap_card(cfg, "2/2026", None, None)
    assert 'snap-card__value">0,00%</span>' in zero_html
    assert "snap-card__status-mark" not in zero_html

    cfg.update(serie={"2/2026": None}, status_marker="†", status_note="Fonte indisponível.")
    missing_html = app1._render_snap_card(cfg, "2/2026", None, None)
    assert 'snap-card__value">N/D<span class="snap-card__status-mark' in missing_html
    assert "†</span>" in missing_html
    assert app1._formatar_valor_snapshot({"format_key": "Carteira de Crédito Bruta"}, 0.0) == "R$ 0MM"


def test_snapshot_metric_status_note_identifies_prudential_and_capital_unavailability():
    marker_basileia, note_basileia = app1._snapshot_metric_status_note(
        label="Índice de Basileia",
        periodo_ref="4/2025",
        valor_atual=None,
        capital_disp_map={"4/2025": False},
    )
    marker_est3, note_est3 = app1._snapshot_metric_status_note(
        label="Perda Esperada / Estágio 3",
        periodo_ref="4/2025",
        valor_atual=None,
        qual_status_map={"4/2025": "source_structurally_unavailable"},
    )
    marker_credito, note_credito = app1._snapshot_metric_status_note(
        label="Crédito / Captações",
        periodo_ref="4/2025",
        valor_atual=None,
        core_status_map={"4/2025": "missing_required_component"},
    )

    assert marker_basileia == "†"
    assert "rel. 5" in note_basileia.lower()

    assert marker_est3 == "†"
    assert "4060" in note_est3.lower()

    assert marker_credito == "†"
    assert "componente" in note_credito.lower()


def test_render_snap_card_appends_status_marker_and_note_to_tooltip():
    html = app1._render_snap_card(
        {
            "label": "Índice de Basileia",
            "format_key": "Índice de Basileia",
            "serie": {"4/2025": None},
            "source": "BCB IFData Rel. 5 — (CP+CC+N2) ÷ RWA Total",
            "status_marker": "†",
            "status_note": "Sem registro utilizável no Rel. 5 para a instituição/período; o indicador permanece indisponível.",
        },
        periodo_atual="4/2025",
        periodo_qoq=None,
        periodo_yoy=None,
    )

    assert "snap-card__status-mark" in html
    assert "†" in html
    assert "Rel. 5" in html


def test_snapshot_metric_status_note_falls_back_to_generic_curated_unavailability():
    marker, note = app1._snapshot_metric_status_note(
        label="Ativo Total",
        periodo_ref="4/2025",
        valor_atual=None,
    )

    assert marker == "†"
    assert "cache curado" in note.lower()


def test_snapshot_metric_status_note_identifies_missing_carteira_components():
    marker, note = app1._snapshot_metric_status_note(
        label="Carteira de Crédito",
        periodo_ref="4/2025",
        valor_atual=None,
        carteira_status_map={"4/2025": "missing_required_component"},
    )

    assert marker == "†"
    assert "rel. 2" in note.lower()
    assert "componente" in note.lower()


@pytest.mark.parametrize("label,is_pct", [
    ("Carteira de Crédito", False), ("Crédito / Captações", True), ("Perda Esperada / Carteira", True),
])
def test_snapshot_numeric_net_portfolio_fallback_has_visible_scope_caveat_and_neutral_delta(label, is_pct):
    current, old = (.0225, .0218) if is_pct else (1.1e9, 1e9)
    marker, note = app1._snapshot_metric_status_note(
        label=label, periodo_ref="2/2026", valor_atual=current,
        carteira_status_map={"2/2026": "fallback_net_components"},
    )
    assert marker == "‡"
    assert "base líquida" in note
    assert "e+f+g+h" in note
    assert "duas datas" in note
    cfg = {
        "label": label, "is_pct": is_pct, "serie": {"2/2026": current, "1/2026": old},
        "status_marker": marker, "status_note": note,
        "quality_by_period": {"2/2026": {"reliable": False, "reason": note}, "1/2026": {"reliable": True}},
    }
    payload = app1._snapshot_card_delta(cfg, "2/2026", "1/2026", "QoQ")
    assert payload["valido"] and payload["direction"] == "up"
    assert payload["current"] == current
    assert payload["tone"] == "neutral"
    rendered = app1._render_snap_card(cfg, "2/2026", "1/2026", None)
    assert "‡</span>" in rendered and "base líquida" in rendered


def test_render_snap_card_explicitly_labels_trimestral_and_ytd_bases():
    html_trim = app1._render_snap_card(
        {
            "label": "Crédito / Captações",
            "format_key": "Carteira de Crédito/Core Funding (%)",
            "serie": {"4/2025": 0.60, "3/2025": 0.59, "4/2024": 0.68},
            "comparison_basis": "trimestral",
            "is_pct": True,
        },
        periodo_atual="4/2025",
        periodo_qoq="3/2025",
        periodo_yoy="4/2024",
    )
    html_ytd = app1._render_snap_card(
        {
            "label": "Lucro Líquido Acum. YTD",
            "format_key": "Lucro Líquido Acumulado YTD",
            "serie": {"4/2025": 100.0, "4/2024": 80.0},
            "comparison": "yoy",
            "comparison_basis": "ytd",
        },
        periodo_atual="4/2025",
        periodo_qoq="3/2025",
        periodo_yoy="4/2024",
    )

    assert "QoQ trimestral" in html_trim
    assert "YoY trimestral" in html_trim
    assert "YoY YTD" in html_ytd


def test_snapshot_rates_use_bps_and_negative_monetary_base_is_not_growth():
    for label, meta in app1.SNAPSHOT_METRICS.items():
        assert app1._snap_metric_delta_meta({"label":label,"is_pct":True}) == (meta["tipo_delta"],"dec")
    assert app1._snap_delta_calc(.1477,.1518,"bps","dec")["suffix"] == "−41 bps"
    assert app1._snap_metric_delta_meta({"label":"Perda Esperada / Estágio 3","is_pct":True}) == ("pp","dec")
    assert app1._snap_delta_calc(1.935,1.931,"pp","dec")["suffix"] == "+0,40 p.p."
    assert app1._snap_metric_delta_meta({"label":"Proporção sem política explícita","is_pct":True}) == ("pp","dec")
    assert app1._snap_metric_delta_meta({"label":"Perda Esperada / Carteira","is_pct":True}) == ("pp","dec")
    assert not app1._snap_delta_calc(-50,-100)["valido"]
    assert "≤ 0" in app1._snap_delta_calc(-50,-100)["motivo"]
    html=app1._snap_delta_html(-.01,-.02,"QoQ",False,"bps","dec")
    assert "↑" in html
    assert "+100 bps" in html


def test_small_monetary_delta_keeps_visible_sign_and_precision():
    assert app1._snap_delta_calc(100.04,100)["suffix"] == "+0,04%"


@pytest.mark.parametrize("label,is_pct", [
    ("Ativo Total", False),
    ("Carteira de Crédito", False),
    ("Patrimônio Líquido", False),
    ("Lucro Líquido Trimestral", False),
    ("Crédito / Captações", True),
    ("Perda Esperada / Carteira", True),
])
def test_snapshot_contextual_movements_keep_direction_without_credit_judgment(label, is_pct):
    cfg = {
        "label": label, "is_pct": is_pct, "higher_is_better": True,
        "serie": {"2/2026": 1.1, "1/2026": 1.0},
    }
    result = app1._snapshot_card_delta(cfg, "2/2026", "1/2026", "QoQ")
    assert result["tone"] == "neutral"
    assert result["direction"] == "up"
    assert result["display"].startswith("↑ +")


@pytest.mark.parametrize("label,current,reference,display,tone", [
    ("Índice de Basileia", .1477, .1518, "↓ −41 bps", "attention"),
    ("ROE trim. anualizado", .1518, .1477, "↑ +41 bps", "favorable"),
    ("Perda Esperada / Estágio 3", 1.935, 1.971, "↓ −3,60 p.p.", "attention"),
    ("Inadimplência >90 dias", .0225, .0218, "↑ +7 bps", "attention"),
    ("Cobertura dos vencidos >90 dias", 1.935, 1.931, "↑ +0,40 p.p.", "favorable"),
])
def test_snapshot_credit_tones_and_units_are_shared_with_export_payload(label, current, reference, display, tone):
    cfg = {"label": label, "is_pct": True, "serie": {"2/2026": current, "1/2026": reference}}
    result = app1._snapshot_card_delta(cfg, "2/2026", "1/2026", "QoQ")
    assert result["display"] == display
    assert result["tone"] == tone
    assert result["current"] == current
    assert result["reference"] == reference


@pytest.mark.parametrize("current,reference,display,tone", [
    (.01, .02, "↓ −100 bps", "favorable"),
    (.02, .01, "↑ +100 bps", "attention"),
    (-.01, -.02, "↑ +100 bps", "attention"),
    (-.02, -.01, "↓ −100 bps", "favorable"),
    (0, .01, "↓ −100 bps", "favorable"),
])
def test_funding_cost_compares_economic_cost_and_preserves_signed_reversals(current, reference, display, tone):
    cfg = {
        "label": "Custo anualizado de captação", "is_pct": True,
        "higher_is_better": False, "normalize_negative_risk": False,
        "serie": {"2/2026": current, "1/2026": reference},
    }
    payload = app1._snapshot_card_delta(cfg, "2/2026", "1/2026", "QoQ")
    assert payload["display"] == display
    assert payload["tone"] == tone
    assert payload["current"] == current
    assert payload["reference"] == reference


@pytest.mark.parametrize("status", ["warning", "critical"])
def test_snapshot_reference_quality_alert_keeps_delta_and_neutralizes_credit_tone(status):
    cfg = {
        "label": "Inadimplência >90 dias", "is_pct": True,
        "serie": {"2/2026": .0225, "1/2026": .0218},
        "quality_by_period": {
            "2/2026": {"status": "available", "reason": "", "reliable": True},
            "1/2026": {"status": status, "reason": "Fonte da referência requer validação.", "reliable": False},
        },
    }
    payload = app1._snapshot_card_delta(cfg, "2/2026", "1/2026", "QoQ")
    assert payload["valido"]
    assert payload["current"] == .0225
    assert payload["reference"] == .0218
    assert payload["display"] == "↑ +7 bps"
    assert payload["tone"] == "neutral"
    assert "referência" in payload["reason"].lower()
    rendered = app1._render_snap_card(cfg, "2/2026", "1/2026", None, sparkline_values=[.0218, .0225])
    assert _card_spark_svg(rendered).findall("circle")[-1].get("fill") not in {"#16713B", "#B32624"}


def _card_spark_svg(rendered):
    match = re.search(r"<svg\b.*?</svg>", rendered, re.S)
    assert match is not None
    return ElementTree.fromstring(match.group())


@pytest.mark.parametrize("label,old,current,endpoint", [
    ("Inadimplência >90 dias", .0218, .0225, "#B32624"),
    ("Inadimplência >90 dias", .0225, .0218, "#16713B"),
    ("Cobertura dos vencidos >90 dias", 1.931, 1.935, "#16713B"),
    ("Cobertura dos vencidos >90 dias", 1.935, 1.931, "#B32624"),
])
def test_snapshot_spark_endpoint_encodes_credit_direction_without_recoloring_history(label, old, current, endpoint):
    cfg = {"label": label, "is_pct": True, "serie": {"2/2026": current, "1/2026": old}, "subtitle": "Conceito de arrasto"}
    html = app1._render_snap_card(cfg, "2/2026", "1/2026", None, sparkline_values=[old, current])
    svg = _card_spark_svg(html)
    assert svg.findall("circle")[-1].get("fill") == endpoint
    assert all(line.get("stroke") != endpoint for line in svg.findall("polyline"))
    assert "Conceito de arrasto" in html
    assert "snap-card--improved" not in html and "snap-card--worsened" not in html


def test_snapshot_spark_does_not_color_an_older_point_as_the_missing_current_period():
    svg = ElementTree.fromstring(app1._snap_sparkline_svg([.0218, .0225, None], accent="#B32624"))
    assert svg.findall("circle")[-1].get("fill") != "#B32624"
    bars = ElementTree.fromstring(app1._snap_sparkbars_svg([.0218, .0225, None], accent="#B32624"))
    assert all(bar.get("fill") != "#B32624" for bar in bars.findall("rect"))


def test_ytd_card_keeps_history_endpoint_neutral_even_with_favorable_annual_comparison():
    cfg = {
        "label": "ROE Ac. Anualizado", "is_pct": True, "comparison_basis": "ytd", "comparison": "yoy",
        "serie": {"2/2026": .16, "1/2026": .10, "2/2025": .15},
    }
    annual = app1._snapshot_card_delta(cfg, "2/2026", "2/2025", "YoY YTD")
    assert annual["display"] == "↑ +100 bps"
    assert annual["tone"] == "favorable"
    quarterly = app1._snapshot_card_delta(cfg, "2/2026", "1/2026", "QoQ YTD")
    assert quarterly["tone"] == "neutral"
    assert not quarterly["valido"]
    rendered = app1._render_snap_card(cfg, "2/2026", "1/2026", "2/2025", sparkline_values=[.10, .16], sparkline_type="bars")
    assert all(bar.get("fill") not in {"#16713B", "#B32624"} for bar in _card_spark_svg(rendered).findall("rect"))


def _individual_scope_fixture():
    from utils.snapshot_data import individual_snapshot_frame
    bank = "BANCO A S.A."
    source = pd.DataFrame({
        "Instituição": bank, "Período": ["1/2026", "2/2026"],
        "Patrimônio Líquido": [100e6, 200e6], "Lucro Líquido": [10e6, 25e6],
        "Captações": 600e6, "Carteira de Crédito": 500e6,
    })
    return bank, individual_snapshot_frame(source, bank)


@pytest.mark.parametrize("label,column,expected", [
    ("ROE trim. anualizado", "ROE trimestral anualizado (%)", "30,00%"),
    ("ROE Ac. Anualizado", "ROE Ac. Anualizado (%)", "25,00%"),
])
def test_individual_roe_metadata_and_memory_use_current_legal_entity_equity(label, column, expected):
    bank, frame = _individual_scope_fixture()
    cfg = app1._snapshot_scope_metadata({
        "label": label, "format_key": column, "is_pct": True,
        "source": "Fonte prudencial com PL médio que deve ser substituída",
        "serie": frame.set_index("Período")[column].to_dict(),
    }, "Individual")
    assert cfg["scope"] == "Individual"
    assert "PL atual" in cfg["source"]
    assert "lucro individual" in cfg["source"]
    assert "PL médio" not in cfg["source"]
    memo = app1._build_memoria_calculo_snapshot(frame, bank, label, "2/2026", "1/2026", None, metric_cfg=cfg, base="Individual")
    current = memo[memo["Período"] == "Jun/26"]
    equity = current[current["Campo/Conta"] == "Patrimônio Líquido"].iloc[0]
    assert equity["Valor"] == "R$ 200,00 MM"
    assert equity["Fonte"] == "IFData Rel. 1 individual"
    assert "PL atual" in equity["Transformação"]
    assert current[current["Etapa"] == "Resultado renderizado"]["Valor"].tolist() == [expected]
    assert memo["Filtro"].str.contains("Individual").all()
    provenance = app1._build_provenance_html([cfg])
    assert "Individual" in provenance and "PL atual" in provenance
    assert "Fonte prudencial" not in provenance and "PL Médio" not in provenance


def test_individual_credit_funding_memory_identifies_rel1_balances_and_individual_denominator():
    bank, frame = _individual_scope_fixture()
    cfg = app1._snapshot_scope_metadata({
        "label": "Crédito / Captações", "format_key": "Carteira de Crédito/Core Funding (%)", "is_pct": True,
        "serie": frame.set_index("Período")["Crédito / Captações"].to_dict(),
    }, "Individual")
    assert "Rel. 1 individual" in cfg["source"]
    assert "não é o core funding do grupo" in cfg["source"]
    memo = app1._build_memoria_calculo_snapshot(frame, bank, cfg["label"], "2/2026", None, None, metric_cfg=cfg, base="Individual")
    assert set(memo.loc[memo.Etapa == "Componente", "Campo/Conta"]) == {"Carteira de Crédito Bruta", "Captações"}
    assert set(memo.loc[memo.Etapa == "Componente", "Fonte"]) == {"IFData Rel. 1 individual"}
    assert memo.loc[memo.Etapa == "Resultado renderizado", "Valor"].tolist() == ["83,33%"]


@pytest.mark.parametrize("label", [
    "Índice de Basileia", "CET1", "Perda Esperada / Estágio 3", "Perda Esperada / Carteira",
    "Inadimplência >90 dias", "Cobertura dos vencidos >90 dias",
])
def test_individual_unsupported_risk_metadata_memory_and_provenance_preserve_nd(label):
    bank, frame = _individual_scope_fixture()
    cfg = app1._snapshot_scope_metadata({"label": label, "is_pct": True, "serie": {"2/2026": None}}, "Individual")
    assert cfg["scope"] == "Individual"
    assert cfg["source_label"] == "Individual · fonte indisponível"
    assert "N/D na base Individual" in cfg["source"]
    assert "mesmo perímetro" in cfg["source"]
    memo = app1._build_memoria_calculo_snapshot(frame, bank, label, "2/2026", None, None, metric_cfg=cfg, base="Individual")
    assert memo["Etapa"].tolist() == ["Resultado renderizado"]
    assert memo["Valor"].tolist() == ["N/D"]
    assert "N/D na base Individual" in memo["Transformação"].iloc[0]
    provenance = app1._build_provenance_html([cfg])
    assert "Individual · fonte indisponível" in provenance
    assert "N/D na base Individual" in provenance
    assert "mesmo perímetro" in provenance


@pytest.mark.parametrize("raw,economic,expected_raw,expected_economic", [
    (-.02, .02, "-2,00%", "2,00%"),
    (.01, -.01, "1,00%", "-1,00%"),
    (0, 0, "0,00%", "0,00%"),
    (None, None, "N/D", "N/D"),
])
def test_funding_cost_memory_keeps_accounting_input_and_inverted_economic_sign(raw, economic, expected_raw, expected_economic):
    bank, frame = _individual_scope_fixture()
    frame["Desp Captação / Captação"] = raw
    cfg = app1._snapshot_scope_metadata({
        "label": "Custo anualizado de captação", "format_key": "Desp Captação / Captação", "is_pct": True,
        "serie": {"2/2026": economic}, "normalize_negative_risk": False,
    }, "Individual")
    memo = app1._build_memoria_calculo_snapshot(frame, bank, cfg["label"], "2/2026", None, None, metric_cfg=cfg, base="Individual")
    assert memo.loc[memo.Etapa == "Componente", "Valor"].tolist() == [expected_raw]
    assert memo.loc[memo.Etapa == "Resultado renderizado", "Valor"].tolist() == [expected_economic]
    assert "sinal invertido" in memo.loc[memo.Etapa == "Componente", "Transformação"].iloc[0]
    provenance = app1._build_provenance_html([cfg])
    assert "Rel. 4 e Rel. 1 individuais" in provenance
    assert "receitas ou reversões" in provenance


@pytest.mark.parametrize("label,key,columns,rendered", [
    ("Inadimplência >90 dias", "Inadimplência / Carteira Total", {"Inadimplência 4.966": 2.25e6, "Carteira Total 4.966": 100e6}, "2,25%"),
    ("Cobertura dos vencidos >90 dias", "PDD / Inadimplência (arrasto)", {
        "Inadimplência 4.966": 2.25e6,
        **{f"Trace::Perda Esperada::Perda Esperada ({part}2)": -value * 1e6 for part, value in zip("efgh", [2.0, 1.0, 1.0, .35375])},
        "Trace::Perda Esperada::Hedge de Valor Justo (e3)": -99e6,
    }, "193,50%"),
])
def test_arrasto_memory_and_provenance_identify_exact_rel16_denominator_and_expected_loss_components(label, key, columns, rendered):
    bank, period = "BANCO A - PRUDENCIAL", "2/2026"
    frame = pd.DataFrame([{"Instituição": bank, "Período": period, **columns}])
    source = "IFData Rel. 16: vencidos por arrasto ÷ Total Geral" if key == "Inadimplência / Carteira Total" else "IFData Rel. 2: |e2 + f2 + g2 + h2| ÷ vencidos por arrasto do Rel. 16"
    cfg = app1._snapshot_scope_metadata({
        "label": label, "format_key": key, "is_pct": True,
        "source": source, "definition": "Arrasto: saldo integral das operações; fonte trimestral desde mar/2025.",
        "serie": {period: .0225 if key == "Inadimplência / Carteira Total" else 1.935},
    }, "Consolidada / Prudencial")
    memo = app1._build_memoria_calculo_snapshot(frame, bank, label, period, None, None, metric_cfg=cfg)
    assert set(memo.loc[memo.Etapa == "Componente", "Campo/Conta"]) == set(columns) - {"Trace::Perda Esperada::Hedge de Valor Justo (e3)"}
    assert not memo["Campo/Conta"].str.contains("Hedge|Ajuste a Valor Justo").any()
    assert memo.loc[memo.Etapa == "Resultado renderizado", "Valor"].tolist() == [rendered]
    provenance = app1._build_provenance_html([cfg])
    assert "Consolidada / Prudencial" in provenance
    assert "arrasto" in provenance and "Rel. 16" in provenance
    assert "mar/2025" in provenance
    assert cfg["source_label"] in provenance


def test_snapshot_delta_presentation_can_explicitly_neutralize_an_alerted_comparison():
    neutral = app1._snap_delta_presentation(.16, .15, "QoQ", delta_kind="bps", scale="dec", favorable_direction=None)
    alerted = app1._snap_delta_presentation(.16, .15, "QoQ", delta_kind="bps", scale="dec", favorable_direction="up", reliable=False)
    assert neutral["display"] == alerted["display"] == "↑ +100 bps"
    assert neutral["tone"] == alerted["tone"] == "neutral"
    invalid = app1._snap_delta_presentation(.16, None, "QoQ", delta_kind="bps", scale="dec")
    assert invalid["display"] == "—"
    assert invalid["reason"] == "período anterior sem dado"
    assert not invalid["valido"]


@pytest.mark.parametrize("label", ["Carteira de Crédito", "Crédito / Captações", "Perda Esperada / Carteira"])
def test_snapshot_blocks_deltas_that_cross_the_2025_accounting_basis_change(label):
    cfg = {"label": label, "is_pct": label != "Carteira de Crédito", "serie": {"1/2025": 1.1, "4/2024": 1.0}}
    result = app1._snapshot_card_delta(cfg, "1/2025", "4/2024", "QoQ")
    assert result["display"] == "Quebra em 2025"
    assert result["tone"] == "neutral"
    assert result["direction"] is None
    assert not result["valido"]
    assert "2025" in result["reason"]
    html = app1._render_snap_card(cfg, "1/2025", "4/2024", None)
    assert "Quebra em 2025" in html


def test_snapshot_card_help_opens_by_touch_or_keyboard_and_retains_its_source():
    html = app1._render_snap_card(
        {"label": "Ativo Total", "format_key": "Ativo Total", "serie": {"2/2026": 1200},
         "source": "BCB IFData Rel. 1 — Balanço Patrimonial"},
        "2/2026", None, None,
    )
    assert '<details class="snap-card__info">' in html
    assert '<summary aria-label="Ajuda: Ativo Total"' in html
    assert "aria-controls=" in html
    assert "BCB IFData Rel. 1 — Balanço Patrimonial" in html
    assert "snap-card--improved" not in html
    assert "snap-card--worsened" not in html


def test_snapshot_sparkline_preserves_missing_quarters_without_drawing_a_bridge():
    svg = ElementTree.fromstring(app1._snap_sparkline_svg([100, 200, None, 300, 400]))
    lines = svg.findall("polyline")
    assert len(lines) == 2
    first_x = [float(point.split(",")[0]) for point in lines[0].get("points").split()]
    second_x = [float(point.split(",")[0]) for point in lines[1].get("points").split()]
    assert first_x == [0, 20]
    assert second_x == [60, 80]
    assert not app1._snap_sparkline_svg([None, 100, float("nan")])


def test_snapshot_sparkbars_preserves_an_empty_quarter_slot():
    svg = ElementTree.fromstring(app1._snap_sparkbars_svg([100, None, 200]))
    bars = svg.findall("rect")
    assert len(bars) == 2
    assert float(bars[0].get("x")) == 0
    assert float(bars[1].get("x")) > 40
    assert not app1._snap_sparkbars_svg([100, float("inf"), None])


def test_snapshot_rounding_and_small_rate_changes_are_not_audit_errors():
    cfg=[{"label":"Índice de Basileia","is_pct":True,"serie":{"1/2026":.147769,"4/2025":.1518}}]
    assert app1._audit_deltas_snapshot(cfg,"1/2026","4/2025",None) == []
    cfg[0]["serie"]["1/2026"] = .151801
    assert app1._snap_delta_calc(.151801,.1518,"bps","dec")["suffix"] == "+<1 bp"
    assert app1._audit_deltas_snapshot(cfg,"1/2026","4/2025",None) == []


def test_snapshot_audit_detects_the_rendered_delta_instead_of_recomputing_it_twice(monkeypatch):
    cfg=[{"label":"Índice de Basileia","is_pct":True,"serie":{"1/2026":.1477,"4/2025":.1518}}]
    assert app1._audit_deltas_snapshot(cfg,"1/2026","4/2025",None) == []
    original=app1._snap_delta_calc
    def wrong_suffix(*args,**kwargs):
        return {**original(*args,**kwargs),"suffix":"-410,00 bps"}
    monkeypatch.setattr(app1,"_snap_delta_calc",wrong_suffix)
    findings=app1._audit_deltas_snapshot(cfg,"1/2026","4/2025",None)
    assert len(findings) == 1
    assert findings[0]["Delta esperado (bruto)"] == pytest.approx(-41)


def test_cosif_signed_balance_keeps_absolute_difference_with_relative_nd():
    result,error=app1._comparar_valores_conta_bloprudencial("202602","202601",{"202601":-100,"202602":-50},"saldo_periodo")
    assert error is None
    assert result["Variação"] == 50
    assert result["Variação %"] is None


def test_carregar_cache_relatorio_slice_uses_specialized_critical_screens_loader(monkeypatch):
    esperado = pd.DataFrame(
        [
            {
                "Instituição": "ITAU - PRUDENCIAL",
                "Período": "4/2025",
                "Carteira de Crédito Bruta": 1200.0,
                "Core Funding": 2000.0,
                "Crédito / Captações": 0.6,
            }
        ]
    )
    chamadas = {}

    def fake_load_critical_screens_slice(*, base_dir=None, periodos=None, instituicoes=None):
        chamadas["base_dir"] = base_dir
        chamadas["periodos"] = periodos
        chamadas["instituicoes"] = instituicoes
        return esperado.copy()

    monkeypatch.setattr(app1, "load_critical_screens_slice", fake_load_critical_screens_slice)
    app1._carregar_cache_relatorio_slice.clear()

    resultado = app1._carregar_cache_relatorio_slice(
        "critical_screens",
        "token",
        periodos=("4/2025",),
        instituicoes=("ITAU - PRUDENCIAL",),
    )

    assert resultado.equals(esperado)
    assert chamadas["periodos"] == ["4/2025"]
    assert "ITAU - PRUDENCIAL" in chamadas["instituicoes"]


def test_get_peers_filters_context_uses_lightweight_context_loader(monkeypatch):
    esperado = {
        "bancos_todos": ("ITAU - PRUDENCIAL", "BB - PRUDENCIAL"),
        "periodos_disponiveis": ("3/2025", "4/2025"),
    }

    def fake_context_loader(*, base_dir=None):
        return esperado

    def fail_if_slice_called(*args, **kwargs):  # pragma: no cover - regressão defensiva
        raise AssertionError("slice pesado não deveria ser usado para montar os filtros da Peers")

    monkeypatch.setattr(app1, "load_critical_screens_filters_context", fake_context_loader)
    monkeypatch.setattr(app1, "_carregar_cache_relatorio_slice", fail_if_slice_called)
    app1._get_peers_filters_context.clear()

    resultado = app1._get_peers_filters_context("token")

    assert resultado == esperado




def test_garantir_cache_telas_criticas_fails_fast_when_runtime_would_materialize(monkeypatch):
    mensagens = []

    monkeypatch.setattr(app1, "get_cache_manager", lambda: object())
    monkeypatch.setattr(
        app1,
        "get_critical_screens_runtime_status",
        lambda manager=None: {
            "cache": None,
            "local_ready": False,
            "bundle_ready": False,
            "bundle_newer_than_local": False,
            "can_materialize_from_local_sources": True,
            "missing_local_source_caches": [],
            "mode": "materialize_local",
            "message": "artefato curado ausente; fontes locais completas permitem rematerialização explícita",
        },
    )
    monkeypatch.setattr(app1.st, "error", lambda msg: mensagens.append(("error", str(msg))))
    monkeypatch.setattr(app1.st, "caption", lambda msg: mensagens.append(("caption", str(msg))))

    def _fail_if_materialize(*args, **kwargs):  # pragma: no cover - regressão defensiva
        raise AssertionError("runtime não deve iniciar materialização pesada de critical_screens")

    monkeypatch.setattr(app1, "materialize_critical_screens_cache", _fail_if_materialize)

    ok = app1._garantir_cache_telas_criticas("Tabela de Peers")

    assert ok is False
    assert any("indisponível para runtime" in texto.lower() for tipo, texto in mensagens if tipo == "error")
    assert any("desabilitada no runtime" in texto.lower() for tipo, texto in mensagens if tipo == "caption")
