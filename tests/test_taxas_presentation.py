from __future__ import annotations

import ast
from io import BytesIO
from pathlib import Path

import pandas as pd
import plotly.express as px

from utils.taxas_juros_presentation import (
    assinatura_figuras_taxas,
    figura_taxas_para_exportar,
    formatar_planilhas_taxas,
)


def test_export_context_copies_the_selected_chart_and_preserves_daily_gaps():
    frame = pd.DataFrame({
        "data": pd.to_datetime(["2026-06-01", "2026-06-02", "2026-06-03"]),
        "taxa": [1.2, float("nan"), 0.0],
    })
    original = px.line(frame, x="data", y="taxa")
    exported = figura_taxas_para_exportar(
        original, titulo="Série diária", subtitulo="Taxa mensal", diaria=True,
    )
    assert original.layout.meta is None
    assert len(exported.data[0].x) == 3
    assert pd.isna(exported.data[0].y[1])
    assert exported.data[0].y[2] == 0
    assert exported.layout.meta["formato_data"] == "diaria"
    assert "ConsultaUnificada" in exported.layout.meta["source"]


def test_download_signature_changes_for_revision_colors_and_scope():
    original = px.line(x=["2026-01", "2026-02", "2026-03"], y=[1.0, 1.2, 1.4])
    revision = px.line(x=["2026-01", "2026-02", "2026-03"], y=[1.0, 1.3, 1.4])
    signature = assinatura_figuras_taxas([original])
    assert assinatura_figuras_taxas([original]) == signature
    assert assinatura_figuras_taxas([revision]) != signature
    revision = px.line(x=["2026-01", "2026-02", "2026-03"], y=[1.0, 1.2, 1.4])
    revision.update_traces(line_color="#123456")
    assert assinatura_figuras_taxas([revision]) != signature
    assert assinatura_figuras_taxas([original, revision]) != signature


def _excel_functions():
    source = (Path(__file__).resolve().parents[1] / "app1.py").read_text()
    tree = ast.parse(source)
    names = {
        "_build_taxas_beta_ranking_excel", "_build_taxas_beta_daily_excel",
        "_build_taxas_beta_monthly_excel", "_build_taxas_beta_daily_matrix",
        "_build_taxas_beta_monthly_matrix", "_sanitizar_nome_aba_excel_taxas_beta",
    }
    functions = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name in names]
    module = ast.Module(body=functions, type_ignores=[])
    env = {
        "pd": pd, "BytesIO": BytesIO, "List": list, "re": __import__("re"),
        "_formatar_modalidade_beta": lambda value: value,
        "formatar_planilhas_taxas": formatar_planilhas_taxas,
    }
    exec(compile(module, "<taxas excel>", "exec"), env)
    return env


def test_excel_finish_preserves_dates_order_missing_and_zero():
    funcs = _excel_functions()
    frame = pd.DataFrame({
        "Instituição Financeira": ["Banco A", "Banco A", "Banco B", "Banco B"],
        "Fim Período": pd.to_datetime(["2026-01-09", "2026-02-13"] * 2),
        "Taxa Mensal (%)": [0.0, 1.25, float("nan"), 2.5],
    })
    common = dict(segmento="PESSOA JURÍDICA", produto="Capital de giro", tipo_taxa="Taxa Mensal (%)", bancos_ordem=["Banco B", "Banco A"])
    monthly = funcs["_build_taxas_beta_monthly_excel"](**common, janela_meses=2, df_mensal=frame)
    daily = funcs["_build_taxas_beta_daily_excel"](**common, anchor_date="2026-02-13", window_start="2026-01-09", df_daily=frame)
    for content, dates in [(monthly, ["01/2026", "02/2026"]), (daily, ["09/01/2026", "13/02/2026"])]:
        workbook = pd.ExcelFile(BytesIO(content))
        assert workbook.sheet_names == ["contexto", "Capital de giro"]
        values = pd.read_excel(workbook, sheet_name="Capital de giro")
        assert list(values.columns) == ["Instituição Financeira", *dates]
        assert values.iloc[:, 0].tolist() == ["Banco B", "Banco A"]
        assert pd.isna(values.iloc[0, 1])
        assert values.iloc[1, 1] == 0.0
        assert values.iloc[:, 2].tolist() == [2.5, 1.25]
