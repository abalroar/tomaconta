from __future__ import annotations

import sys
import zipfile
from io import BytesIO
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from utils.spb_meios_pagamento_viz import (
    build_line_figure,
    build_spb_native_pptx,
    build_spb_pptx,
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


def test_native_pptx_contains_powerpoint_chart_parts():
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

    pptx_bytes = build_spb_native_pptx(
        title="Dados de Meios de Pagamento - BCB",
        charts=[
            {
                "title": "Núcleo mensal - quantidade",
                "long_df": long_df,
                "tipo": "Quantidade (mil)",
                "instruments": ["Pix", "TED"],
                "yaxis_title": "mil transações",
            },
            {
                "title": "Participação mensal - quantidade",
                "long_df": long_df,
                "tipo": "Quantidade (mil)",
                "instruments": ["Pix", "TED"],
                "yaxis_title": "% do total selecionado",
                "share": True,
            },
        ],
        summaries={
            "Quantidade": compute_share(long_df, "Quantidade (mil)", ["Pix", "TED"]).rename(
                columns={"instrumento": "Instrumento", "valor": "Valor", "participacao": "Participação", "periodo_label": "Período"}
            )[["Período", "Instrumento", "Valor", "Participação"]],
        },
        source_note="Fonte: BCB",
    )

    with zipfile.ZipFile(BytesIO(pptx_bytes)) as pptx_zip:
        chart_parts = [name for name in pptx_zip.namelist() if name.startswith("ppt/charts/chart") and name.endswith(".xml")]
        slide_parts = [name for name in pptx_zip.namelist() if name.startswith("ppt/slides/slide") and name.endswith(".xml")]
        slide_xml = b"\n".join(pptx_zip.read(name) for name in slide_parts)

    assert len(chart_parts) == 2
    assert len(slide_parts) == 4
    assert b"Imagem do gr" not in slide_xml
    assert "Plano de melhorias aplicado".encode("utf-8") not in slide_xml
    assert "Manter mensal e trimestral separados".encode("utf-8") not in slide_xml


def test_legacy_pptx_export_fails_instead_of_placeholder_when_image_missing():
    with pytest.raises(RuntimeError, match="build_spb_native_pptx"):
        build_spb_pptx(
            title="Dados de Meios de Pagamento - BCB",
            figures={"Núcleo mensal - quantidade": None},
            summaries={},
            source_note="Fonte: BCB",
        )
