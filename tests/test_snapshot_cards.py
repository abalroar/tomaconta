import app1
import pandas as pd
import pytest
from xml.etree import ElementTree


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
    assert app1._snap_delta_calc(1.935,1.931,"pp","dec")["suffix"] == "+0,4 p.p."
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
    ("Perda Esperada / Estágio 3", 1.935, 1.971, "↓ −3,6 p.p.", "attention"),
    ("Desp. Anualizada Captação / Volume Captação", -.01, -.02, "↑ +100 bps", "favorable"),
])
def test_snapshot_credit_tones_and_units_are_shared_with_export_payload(label, current, reference, display, tone):
    cfg = {"label": label, "is_pct": True, "serie": {"2/2026": current, "1/2026": reference}}
    result = app1._snapshot_card_delta(cfg, "2/2026", "1/2026", "QoQ")
    assert result["display"] == display
    assert result["tone"] == tone
    assert result["current"] == current
    assert result["reference"] == reference


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
