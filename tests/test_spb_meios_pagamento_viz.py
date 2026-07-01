from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from utils.spb_meios_pagamento_viz import (
    build_line_figure,
    build_share_figure,
    compute_share,
    format_ano_mes_label,
    format_trimestre_label,
    melt_nucleo_spb,
)


def test_period_labels_match_dashboard_spec():
    assert format_ano_mes_label("202605") == "05-2026"
    assert format_trimestre_label("20251") == "mar-25"
    assert format_trimestre_label("20254") == "dez-25"


def test_melt_nucleo_monthly_adds_sortable_period_and_labels():
    raw = pd.DataFrame(
        {
            "ano_mes": ["202501", "202502"],
            "quantidadePix": [10, 20],
            "valorPix": [100, 200],
            "quantidadeTED": [5, 4],
            "valorTED": [50, 40],
        }
    ).rename(
        columns={
            "quantidadePix": "quantidade_pix",
            "valorPix": "valor_pix",
            "quantidadeTED": "quantidade_ted",
            "valorTED": "valor_ted",
        }
    )

    long_df = melt_nucleo_spb(raw, "ano_mes", "mensal")

    assert set(long_df["instrumento"]) == {"Pix", "TED"}
    assert set(long_df["periodo_label"]) == {"01-2025", "02-2025"}
    assert long_df["periodo_ordem"].min() == pd.Timestamp("2025-01-01")


def test_compute_share_sums_to_100_by_period():
    raw = pd.DataFrame(
        {
            "trimestre": ["20251", "20252"],
            "quantidade_pix": [80, 75],
            "quantidade_ted": [20, 25],
            "valor_pix": [40, 50],
            "valor_ted": [60, 50],
        }
    )
    long_df = melt_nucleo_spb(raw, "trimestre", "trimestral")

    share = compute_share(long_df, "Quantidade (mil)", ["Pix", "TED"])

    totals = share.groupby("periodo_label")["participacao"].sum().round(6).tolist()
    assert totals == [100.0, 100.0]


def test_figures_render_final_point_labels():
    raw = pd.DataFrame(
        {
            "ano_mes": ["202501", "202502"],
            "quantidade_pix": [10, 20],
            "quantidade_ted": [5, 4],
            "valor_pix": [100, 200],
            "valor_ted": [50, 40],
        }
    )
    long_df = melt_nucleo_spb(raw, "ano_mes", "mensal")

    line_fig = build_line_figure(
        long_df,
        tipo="Quantidade (mil)",
        instruments=["Pix", "TED"],
        title="Quantidade",
        yaxis_title="mil transações",
    )
    share_fig = build_share_figure(
        long_df,
        tipo="Quantidade (mil)",
        instruments=["Pix", "TED"],
        title="Participação",
    )

    assert line_fig.data[0].text[-1] == "20"
    assert share_fig.data[0].text[-1].endswith("%")
