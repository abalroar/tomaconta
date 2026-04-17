import app1
import pandas as pd


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


def test_timer_begin_measurement_clears_stale_elapsed_for_same_signature():
    app1.st.session_state["peers_tabela_timer_state"] = {
        "signature": ("peers_tabela", ("ITAU - PRUDENCIAL",), ("4/2025",)),
        "elapsed": 266.15,
    }

    app1._timer_begin_measurement(
        "peers_tabela_timer_state",
        ("peers_tabela", ("ITAU - PRUDENCIAL",), ("4/2025",)),
    )

    assert app1.st.session_state["peers_tabela_timer_state"]["elapsed"] is None
