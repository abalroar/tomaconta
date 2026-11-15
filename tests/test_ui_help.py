"""Ajuda acompanha o conceito, a fonte e as exceções dos cálculos exibidos."""
import pytest
from streamlit.testing.v1 import AppTest

from utils.glossary_catalog import MODULE_GUIDES, all_terms
from utils.ifdata_cache.metric_registry import get_metric_definition_by_label
from utils.peers_table_model import BY_KEY, get_metric
from utils.ui_help import MODULE_CAPTIONS, get_help_text


def test_every_module_has_reading_context_and_every_peer_metric_resolves():
    assert set(MODULE_CAPTIONS) == {g.name for g in MODULE_GUIDES}
    for key in BY_KEY:
        text = get_help_text(key, context="Peers")
        assert text and "Fonte:" in text, key
        assert "trimestral" in text.lower(), key
        assert "BCB BCB" not in text, key


@pytest.mark.parametrize("key", ["roe_ytd", "roe_quarter", "basel", "credit_balance", "default_ratio", "problem_assets"])
def test_audited_help_consumes_the_glossary_definition(key):
    term = next(t for t in all_terms() if t.key == key)
    assert get_help_text(term.title).startswith(term.definition)
    metric = get_metric_definition_by_label(term.title)
    assert metric.source_label in get_help_text(term.title)


def test_individual_metrics_do_not_inherit_prudential_formula_or_components():
    individual = get_metric("ROE Acumulado YTD (%)", "Individual")
    prudential = get_metric("ROE Acumulado YTD (%)", "Consolidada / Prudencial")
    assert "÷ PL atual" in individual.formula and "÷ média" in prudential.formula
    assert "PL atual da instituição" in individual.note
    assert "Fonte: BCB IFData Rel. 1" in individual.note
    assert "instituição individual" in individual.note
    assert "Captações publicadas" == get_metric("Core Funding*", "Individual").formula
    assert "captações do Relatório 1" in get_metric("Core Funding*", "Individual").note
    assert "indisponível" in get_metric("Índice de Basileia Total (%)", "Individual").note


def test_signed_peer_cost_and_expected_loss_baskets_are_qualified():
    for key in ("Custo de Crédito (%)", "Custo de Crédito / Receita de Crédito (%)"):
        note = get_metric(key, "Consolidada / Prudencial").note
        assert "sinal invertido" in note
        assert "reversão líquida gera sinal negativo" in note
    for key in ("Perda Esperada", "Perda Esperada / Estágio 3", "Perda Esperada / Carteira de Crédito*"):
        note = get_metric(key, "Consolidada / Prudencial").note
        assert "hedge e valor justo" in note
        assert "difere da PDD da Carteira 4.966" in note


def test_dre_semester_help_does_not_relabel_profit_as_ytd():
    text = get_help_text("Lucro líquido", context="DRE", include_source=False)
    assert "resultado final do período" in text
    assert "Resultado líquido de janeiro" not in text


def test_unknown_field_has_no_inferred_definition_or_source():
    assert get_help_text("campo não cadastrado 123xyz") == ""


@pytest.mark.parametrize("module", ["Contas COSIF", "Carteira 4.966", "Taxas de Juros por Produto", "Estatísticas Crédito BC"])
def test_source_disclosure_renders_from_shared_catalog(module):
    app = AppTest.from_string(f"from utils.ui_help import render_module_help\nrender_module_help({module!r})").run()
    assert not app.exception
    assert len(app.get("popover")) == 1
    assert any("data-base" in element.value.lower() for element in app.caption)


def test_dre_key_metric_tooltips_preserve_semester_and_stock_distinction():
    app = AppTest.from_string('''
import pandas as pd
import streamlit as st
from tabs.dre_ifdata_schema import _render_key_metrics
df = pd.DataFrame({"nome_canônico": ["net_income", "asset_total"], "valor_r_mil": [10, 100]})
_render_key_metrics(st, df)
''').run()
    assert not app.exception
    profit = next(m for m in app.metric if m.label == "Lucro líquido")
    asset = next(m for m in app.metric if m.label == "Ativo total")
    assert "acumulado no semestre" in profit.help
    assert "Saldo na data-base" in asset.help
