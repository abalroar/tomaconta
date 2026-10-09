from io import BytesIO
import base64
import ast
import json
from pathlib import Path
from unittest.mock import Mock
from types import SimpleNamespace
from zipfile import ZipFile

import pandas as pd
import pytest
from lxml import etree
from openpyxl import load_workbook
from pptx import Presentation

from utils.peers_table_model import BY_KEY, build_query, delta, reference, get_metric, methodology_rows
from utils.peers_table_exports import export_excel, export_powerpoint
from utils import peers_groups
from tabs.peers_table import table_html, calculation_rows


def sample(banks=("A", "B", "C"), periods=("4/2025", "1/2026", "2/2026"), metrics=("Ativo Total", "Custo de Crédito (%)", "Lucro Líquido Acumulado"), **overrides):
    rows, values = [], {}
    for b, bank in enumerate(banks):
        for p in (*periods, "2/2025", "4/2024", "1/2025"):
            rows.append({"Instituição": bank, "Período": p, "Ativo Total": 1e9*(b+1), "Lucro Líquido Acumulado YTD": 1e8, "Trace::Custo de Crédito::PDD Crédito Anualizada": -2e7, "Carteira de Crédito Bruta": 1e9})
            values.update({("Ativo Total", bank, p): 1e9*(b+1), ("Custo de Crédito (%)", bank, p): .02, ("Lucro Líquido Acumulado", bank, p): 1e8})
    df = pd.DataFrame(rows).drop_duplicates(["Instituição", "Período"])
    kwargs = dict(base="Consolidada / Prudencial", cache_token="abc", scale="R$ bilhões", mode="year", queried_at="09/10/2026")
    kwargs.update(overrides)
    return build_query(df, list(banks), list(periods), list(metrics), values, {}, **kwargs), df, values


def test_delta_baseline_units_rounding_and_ytd_guard():
    assert reference("1/2026", "quarter") == "4/2025"
    assert reference("2/2026", "year") == "2/2025"
    assert delta(.030843, .030776, BY_KEY["Custo de Crédito (%)"], "year") == ("up", "↑ +0,01 p.p.")
    assert delta(.03, .030001, BY_KEY["Custo de Crédito (%)"], "year") == ("flat", "= 0,00 p.p.")
    assert delta(3, -2, BY_KEY["Ativo Total"], "year")[0] is None
    assert delta(3, 2, BY_KEY["Lucro Líquido Acumulado"], "quarter")[1] == "YTD: janelas diferentes"


def test_query_preserves_sign_missing_components_order_and_effective_revision():
    q, df, values = sample()
    signed = df.copy()
    signed.loc[(signed.Instituição == "A") & (signed.Período == "2/2026"), "Trace::Custo de Crédito::PDD Crédito Anualizada"] = 2e7
    opts = dict(base=q["base"], cache_token=q["cache_token"], scale=q["scale"], mode=q["mode"], queried_at=q["queried_at"])
    newer = build_query(signed, q["banks"], q["periods"], q["metrics"], values, {}, **opts)
    assert next(c for c in newer["cells"] if c["metric"] == "Custo de Crédito (%)" and c["bank"] == "A" and c["period"] == "2/2026")["value"] == -.02
    assert newer["signature"] != q["signature"]
    assert build_query(df, list(reversed(q["banks"])), q["periods"], q["metrics"], values, {}, **opts)["signature"] != q["signature"]
    assert build_query(df, q["banks"], q["periods"], q["metrics"], values, {}, **{**opts,"queried_at":"tomorrow"})["signature"] == q["signature"]
    liquidity = build_query(df, ["A"], ["2/2026"], ["Ativos Líquidos"], {("Ativos Líquidos", "A", "2/2026"): 10}, {}, **opts)
    assert liquidity["cells"][0]["value"] is None
    assert "incompletos" in liquidity["cells"][0]["reason"]


def test_profit_memory_uses_displayed_result_and_table_has_nine_columns():
    q, df, _ = sample()
    memo = calculation_rows(q, df, "Lucro Líquido Acumulado", "A")
    result = memo[memo.Campo == "Resultado na tabela"]
    assert set(result.Valor) == {"0,10"}
    html = table_html(q)
    assert html.count('colspan="3"') == 3
    assert 'data-metric="Custo de Crédito (%)"' in html
    assert '<script>' not in table_html({**q, "banks": ["<script>alert(1)</script>"], "cells": [{**c, "bank": "<script>alert(1)</script>"} for c in q["cells"] if c["bank"] == "A"]})


def test_excel_is_numeric_percentage_missing_and_metadata_are_preserved():
    q, _, _ = sample()
    q["cells"][0]["value"] = None
    workbook = load_workbook(BytesIO(export_excel(q)))
    assert set(workbook.sheetnames) == {"Comparativo", "Dados e status", "Metodologia", "Consulta"}
    sheet = workbook["Comparativo"]
    assert sheet.cell(6, 3).value is None
    assert sheet.cell(6, 4).value == 1
    cost = next(r for r in range(1, sheet.max_row+1) if sheet.cell(r, 1).value == "Custo de crédito")
    assert sheet.cell(cost, 3).value == .02
    assert sheet.cell(cost, 3).number_format == "0.00%"
    metadata = {r[0].value: r[1].value for r in workbook["Consulta"] if r[0].value != "Campo"}
    assert metadata["banks"] == "['A', 'B', 'C']"


def test_powerpoint_table_is_native_three_by_three_and_paginated():
    q, _, _ = sample(metrics=tuple(BY_KEY))
    # Outros indicadores ficam N/D no fixture; continuam presentes e editáveis.
    data = export_powerpoint(q)
    prs = Presentation(BytesIO(data))
    assert len(prs.slides) == 3
    for slide in prs.slides:
        table = next(s.table for s in slide.shapes if s.has_table)
        assert len(table.columns) == 10
        assert len(table.rows) <= 12
        assert table.cell(0, 1).is_merge_origin
        assert table.cell(1, 3).text == "Jun/26"
        assert table.cell(2, 0).text_frame.paragraphs[1].font.size.pt == 9
        assert table.cell(2, 0).text_frame.paragraphs[1].font.bold is False
        assert all(s.top+s.height <= prs.slide_height for s in slide.shapes)
    with ZipFile(BytesIO(data)) as archive:
        assert not any(n.startswith("ppt/media/") for n in archive.namelist())


def test_native_line_chart_last_valid_label_bold_color_and_embedded_workbook():
    q, _, _ = sample(metrics=("Ativo Total",))
    for cell in q["cells"]:
        if cell["bank"] == "A" and cell["period"] == "2/2026":
            cell["value"] = None
    data = export_powerpoint(q, charts=True, chart_metrics=["Ativo Total"])
    ns = {"c":"http://schemas.openxmlformats.org/drawingml/2006/chart", "a":"http://schemas.openxmlformats.org/drawingml/2006/main"}
    with ZipFile(BytesIO(data)) as archive:
        assert any(n.startswith("ppt/embeddings/") for n in archive.namelist())
        chart = etree.fromstring(archive.read("ppt/charts/chart1.xml"))
        assert chart.xpath("count(.//c:lineChart)", namespaces=ns) == 1
        series = chart.xpath(".//c:lineChart/c:ser", namespaces=ns)
        labels = series[0].xpath(".//c:dLbl[c:idx/@val='1']", namespaces=ns)
        assert labels
        assert labels[0].xpath(".//a:defRPr[@b='1'] | .//a:rPr[@b='1']", namespaces=ns)
        assert labels[0].xpath(".//a:srgbClr[@val='174A7E']", namespaces=ns)
        assert chart.xpath(".//c:catAx", namespaces=ns)
        assert not chart.xpath(".//c:dateAx", namespaces=ns)
        assert chart.xpath(".//c:dispBlanksAs[@val='gap']", namespaces=ns)
    cols = export_powerpoint(q, charts=True, chart_metrics=["Ativo Total"], chart_type="column_stacked")
    with ZipFile(BytesIO(cols)) as archive:
        chart = etree.fromstring(archive.read("ppt/charts/chart1.xml"))
        assert chart.xpath(".//c:barChart/c:grouping[@val='clustered']", namespaces=ns)
        assert chart.xpath(".//c:barChart/c:ser[1]/c:dLbls/c:dLbl/c:dLblPos[@val='outEnd']", namespaces=ns)
        assert chart.xpath(".//c:barChart/c:ser[1]/c:dLbls/c:dLbl//a:srgbClr[@val='174A7E']", namespaces=ns)


def test_groups_identity_roundtrip_unavailable_members_and_overwrite_gate():
    blank = {"schema_version": 2, "groups": []}
    payload = peers_groups.upsert(blank, "Meus bancos", "Individual", ["A", "B"], {"A":"1", "B":"2"})
    assert peers_groups.resolve(payload["groups"][0], {"Novo nome A":"1"}) == (["Novo nome A"], ["B"])
    with pytest.raises(ValueError, match="Já existe"):
        peers_groups.upsert(payload, "Meus bancos", "Individual", ["A"], {"A":"1"})
    with pytest.raises(ValueError, match="Identidade"):
        peers_groups.upsert(blank, "Grupo", "Individual", ["A"], {})


def test_groups_github_conflict_and_readback_are_required():
    payload = peers_groups.upsert({"schema_version":2,"groups":[]}, "Teste", "Individual", ["A"], {"A":"1"})
    client = Mock()
    client.put.return_value.status_code = 200
    client.put.return_value.json.return_value = {"content":{"sha":"new"}}
    client.get.return_value.status_code = 200
    client.get.return_value.json.return_value = {"sha":"new", "content":base64.b64encode(json.dumps(payload).encode()).decode()}
    assert peers_groups.publish(payload, "org/repo", "main", "token", "old", client=client) == "new"
    assert client.put.call_args.kwargs["json"]["sha"] == "old"
    client.get.return_value.json.return_value["sha"] = "other"
    with pytest.raises(RuntimeError, match="confirmação"):
        peers_groups.publish(payload, "org/repo", "main", "token", "old", client=client)
    client.put.return_value.status_code = 409
    with pytest.raises(ValueError, match="mudou"):
        peers_groups.publish(payload, "org/repo", "main", "token", "old", client=client)


def test_invalid_groups_fail_with_actionable_validation():
    for group in ({"name": 4, "base": "Individual", "members": []}, {"name": "A", "base": [], "members": []}, {"name": "A", "base": "Individual", "members": [{"id": [], "label": "A"}]}):
        with pytest.raises(ValueError):
            peers_groups.validate({"schema_version": 2, "groups": [group]})


def test_schema_break_missing_june_and_duplicate_identity_are_explicit():
    q, df, values = sample(periods=("4/2025",), metrics=("Carteira de Crédito*",))
    assert q["cells"][0]["variation"] == "Quebra em 2025"
    q, df, values = sample(periods=("4/2026",), metrics=("Lucro Líquido Acumulado",))
    assert all(c["value"] is None for c in q["cells"])
    opts = dict(base=q["base"], cache_token=q["cache_token"], scale=q["scale"], mode=q["mode"], queried_at=q["queried_at"])
    with pytest.raises(ValueError, match="mais de um registro"):
        build_query(pd.concat([df, df.iloc[:1]]), q["banks"], q["periods"], q["metrics"], values, {}, **opts)


def test_excel_variations_keep_direction_color_and_values_numeric():
    q, _, _ = sample(metrics=("Ativo Total",))
    q["cells"][0].update(direction="up", variation="↑ +1,00 %")
    q["cells"][1].update(direction="down", variation="↓ −1,00 %")
    sheet = load_workbook(BytesIO(export_excel(q)))["Comparativo"]
    assert sheet.cell(6, 3).value == 1
    assert sheet.cell(7, 3).font.color.rgb == "FF16713B"
    assert sheet.cell(7, 4).font.color.rgb == "FFB32624"


def test_individual_definitions_and_funding_do_not_inherit_consolidated_formula():
    q, df, values = sample(periods=("4/2025",), metrics=("Core Funding*", "Custo de Crédito (%)"), base="Individual")
    df["Captações"] = 1e9
    opts = dict(base=q["base"], cache_token=q["cache_token"], scale=q["scale"], mode=q["mode"], queried_at=q["queried_at"])
    q = build_query(df, q["banks"], q["periods"], q["metrics"], values, {}, **opts)
    assert q["cells"][0]["value"] == 1e9
    assert q["cells"][0]["variation"] == "= 0,00 %"
    assert q["cells"][0]["source"] == "IFData Rel. 1 individual"
    assert q["cells"][-1]["value"] is None
    assert get_metric("Carteira de Crédito*", "Individual").label == "Carteira de crédito"
    assert get_metric("ROE Acumulado YTD (%)", "Individual").formula.endswith("PL atual")
    assert methodology_rows(q)[0]["Indicador"] == "Captações"
    assert "Captações" in table_html(q)


def test_deeplink_opens_once_and_allows_navigation_back_to_old_tab():
    tree = ast.parse(Path("app1.py").read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_aplicar_navegacao_inicial_mobile")
    state = {}
    namespace = {"st": SimpleNamespace(session_state=state), "_menu_query_param_inicial": lambda: "Peers (Tabela Nova)"}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "app1.py", "exec"), namespace)
    namespace["_aplicar_navegacao_inicial_mobile"]()
    assert state["menu_atual"] == "Peers (Tabela Nova)"
    state["menu_atual"] = "Peers (Tabela)"
    namespace["_aplicar_navegacao_inicial_mobile"]()
    assert state["menu_atual"] == "Peers (Tabela)"
