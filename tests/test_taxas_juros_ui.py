from __future__ import annotations

import ast
import textwrap
from functools import lru_cache
from pathlib import Path


APP_PATH = Path(__file__).resolve().parents[1] / "app1.py"
TAXAS_ROUTE_MARKER = 'elif menu == "Taxas de Juros por Produto":'
NEXT_ROUTE_MARKER = 'elif menu == "Meios de Pagamento (SPB)":'


@lru_cache(maxsize=1)
def _app_source() -> str:
    return APP_PATH.read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def _app_tree() -> ast.Module:
    return ast.parse(_app_source())


@lru_cache(maxsize=1)
def _taxas_route_source() -> str:
    source = _app_source()
    start = source.index(TAXAS_ROUTE_MARKER)
    end = source.index(NEXT_ROUTE_MARKER, start)
    return source[start:end]


@lru_cache(maxsize=1)
def _taxas_route_tree() -> ast.Module:
    # The route begins with an ``elif`` in the app. Its body is valid as a
    # standalone module after removing that first line and its indentation.
    body = _taxas_route_source().split("\n", 1)[1]
    return ast.parse(textwrap.dedent(body))


def _qualified_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _qualified_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _calls(name: str) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(_taxas_route_tree())
        if isinstance(node, ast.Call) and _qualified_name(node.func) == name
    ]


def _constant_string_sequences() -> set[tuple[str, ...]]:
    sequences: set[tuple[str, ...]] = set()
    for node in ast.walk(_taxas_route_tree()):
        if not isinstance(node, (ast.List, ast.Tuple)):
            continue
        if all(isinstance(item, ast.Constant) and isinstance(item.value, str) for item in node.elts):
            sequences.add(tuple(item.value for item in node.elts))
    return sequences


def _literal_dicts() -> list[dict[object, object]]:
    dictionaries: list[dict[object, object]] = []
    for node in ast.walk(_taxas_route_tree()):
        if not isinstance(node, ast.Dict):
            continue
        if not all(isinstance(key, ast.Constant) for key in node.keys):
            continue
        if not all(isinstance(value, ast.Constant) for value in node.values):
            continue
        dictionaries.append(
            {
                key.value: value.value
                for key, value in zip(node.keys, node.values)
            }
        )
    return dictionaries


def _first_constant_string(call: ast.Call) -> str | None:
    if call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
        return call.args[0].value
    return None


def _keyword_constant(call: ast.Call, keyword_name: str):
    for keyword in call.keywords:
        if keyword.arg == keyword_name and isinstance(keyword.value, ast.Constant):
            return keyword.value.value
    return None


def _with_context_label(node: ast.With, call_name: str) -> str | None:
    for item in node.items:
        context_expr = item.context_expr
        if isinstance(context_expr, ast.Call) and _qualified_name(context_expr.func) == call_name:
            return _first_constant_string(context_expr)
    return None


def _assigned_call_names() -> dict[str, set[str]]:
    assignments: dict[str, set[str]] = {}
    for node in ast.walk(_taxas_route_tree()):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        call_name = _qualified_name(node.value.func)
        for target in node.targets:
            if isinstance(target, ast.Name):
                assignments.setdefault(target.id, set()).add(call_name)
    return assignments


def _assigns_call_to(node: ast.AST, target_name: str, call_name: str) -> bool:
    return any(
        isinstance(candidate, ast.Assign)
        and isinstance(candidate.value, ast.Call)
        and _qualified_name(candidate.value.func) == call_name
        and any(
            isinstance(target, ast.Name) and target.id == target_name
            for target in candidate.targets
        )
        for candidate in ast.walk(node)
    )


def test_taxas_preserves_rate_and_monthly_visualization_options():
    sequences = _constant_string_sequences()

    assert ("Taxa Mensal (%)", "Taxa Anual (%)") in sequences
    assert ("Linha comparativa", "Painéis por banco", "Ranking atual") in sequences

    line_calls = _calls("px.line")
    bar_calls = _calls("px.bar")
    assert any(_keyword_constant(call, "facet_col") == "Instituição Financeira" for call in line_calls)
    assert any(
        _keyword_constant(call, "orientation") == "h"
        and _keyword_constant(call, "y") == "Instituição Financeira"
        for call in bar_calls
    )


def test_taxas_preserves_daily_series_and_recent_detail():
    source = _taxas_route_source()
    sequences = _constant_string_sequences()
    assignments = _assigned_call_names()
    call_names = {
        _qualified_name(node.func)
        for node in ast.walk(_taxas_route_tree())
        if isinstance(node, ast.Call)
    }

    assert "Série diária" in source
    assert assignments["fig_daily_beta"] == {"px.line"}
    assert {
        "_buscar_taxas_beta_diario_3m_cache",
        "_montar_taxas_beta_diario_3m_live",
    }.issubset(call_names)

    assert "Detalhe recente" in source
    assert "60 dias" in source
    assert ("Último ponto da semana", "Todos os pontos disponíveis") in sequences
    assert assignments["fig_recent_beta"] == {"px.line"}
    assert {
        "_buscar_taxas_beta_detalhe_recente_cache",
        "_buscar_taxas_beta_detalhe_recente",
    }.issubset(call_names)


def test_taxas_replaces_operational_cards_with_compact_base_context():
    source = _taxas_route_source()
    metric_labels = {_first_constant_string(call) for call in _calls("st.metric")}
    secondary_panel_labels = {
        _first_constant_string(call)
        for widget_name in ("st.expander", "st.popover")
        for call in _calls(widget_name)
    }

    assert "Compare taxas mensais e anuais publicadas pelo Banco Central." in source
    assert "Fonte" in source
    assert "BCB" in source
    assert "Base até" in source
    assert "Cobertura" in source
    assert "Sobre a base" in secondary_panel_labels
    assert "Mini-glossário" not in secondary_panel_labels

    assert "Linhas carregadas" not in metric_labels
    assert "Pontos mensais" not in metric_labels
    assert "Fonte atual: cache histórico consolidado." not in source
    assert "Fonte em uso: cache histórico consolidado." not in source


def test_taxas_hides_operational_telemetry_outside_diagnostic_mode():
    cache_status_function = next(
        node
        for node in ast.walk(_app_tree())
        if isinstance(node, ast.FunctionDef)
        and node.name == "_render_cache_status_por_aba"
    )
    cache_guard = next(
        node
        for node in cache_status_function.body
        if isinstance(node, ast.If)
        and "Taxas de Juros por Produto" in ast.unparse(node.test)
    )
    cache_condition = ast.unparse(cache_guard.test)
    assert "modo_diagnostico" in cache_condition
    assert any(isinstance(node, ast.Return) for node in cache_guard.body)

    timer_guards = [
        node
        for node in ast.walk(_app_tree())
        if isinstance(node, ast.If)
        and "Taxas de Juros por Produto" in ast.unparse(node.test)
        and "modo_diagnostico" in ast.unparse(node.test)
        and _assigns_call_to(node, "timer_box_menu", "st.empty")
    ]
    assert len(timer_guards) == 1


def test_taxas_resets_institutions_only_when_segment_or_product_changes():
    context_assignment = next(
        node
        for node in ast.walk(_taxas_route_tree())
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "contexto_bancos_beta"
            for target in node.targets
        )
    )
    assert ast.unparse(context_assignment.value) == "(segmento_beta, str(produto_beta_valor))"

    context_guard = next(
        node
        for node in ast.walk(_taxas_route_tree())
        if isinstance(node, ast.If)
        and ast.unparse(node.test) == "contexto_bancos_anterior_beta != contexto_bancos_beta"
    )
    reset_branch = "\n".join(ast.unparse(node) for node in context_guard.body)
    assert "bancos_estado_beta = bancos_default_beta" in reset_branch
    assert "tj_beta_bancos_contexto" in reset_branch

    preserve_branch = context_guard.orelse[0]
    assert isinstance(preserve_branch, ast.If)
    assert ast.unparse(preserve_branch.test) == "isinstance(bancos_estado_original_beta, list)"
    assert "bancos_estado_beta = bancos_estado_original_beta" in ast.unparse(preserve_branch)


def test_taxas_kpis_describe_extremes_within_the_selection():
    source = _taxas_route_source()

    assert "Menor taxa entre as selecionadas" in source
    assert "Maior taxa entre as selecionadas" in source
    assert "Melhor taxa atual" not in source
    assert "Pior taxa atual" not in source
    assert len(_calls("_render_taxas_beta_kpi_strip")) == 1


def test_taxas_groups_the_existing_exports_in_one_secondary_section():
    export_sections = [
        node
        for node in ast.walk(_taxas_route_tree())
        if isinstance(node, ast.With)
        and _with_context_label(node, "st.expander") == "Dados e exportações"
    ]

    assert len(export_sections) == 1
    download_calls = [
        node
        for node in ast.walk(export_sections[0])
        if isinstance(node, ast.Call)
        and _qualified_name(node.func) == "st.download_button"
    ]
    assert len(download_calls) == 3


def test_taxas_charts_share_the_professional_plotly_finish():
    source = _taxas_route_source()
    plotly_configs = [
        config
        for config in _literal_dicts()
        if "displaylogo" in config or "displayModeBar" in config
    ]

    assert "IBM Plex Sans" in source
    assert "gridcolor" in source
    assert any(config.get("displaylogo") is False for config in plotly_configs)
    assert any(config.get("displayModeBar") == "hover" for config in plotly_configs)
