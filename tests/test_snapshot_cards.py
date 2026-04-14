import app1


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
