from __future__ import annotations

import ast
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from utils.glossary_catalog import (
    ESSENTIAL_KEYS, MODULE_GUIDES, READING_GUIDES, SOURCE_BY_KEY, all_terms,
    search_terms, technical_details,
)
from utils.ifdata_cache.metric_registry import get_metric_definition


APP_PATH = Path(__file__).resolve().parents[1] / "app1.py"


def _app():
    return AppTest.from_string("from tabs.glossary import render\nrender()").run()


def test_every_working_module_has_a_source_and_reading_guide():
    tree = ast.parse(APP_PATH.read_text())
    menus = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in ("MENU_PRINCIPAL", "MENU_BCB"):
                    menus[target.id] = ast.literal_eval(node.value)
    covered = {guide.name for guide in MODULE_GUIDES}
    assert set(menus["MENU_PRINCIPAL"] + menus["MENU_BCB"] + ["Atualizar Base"]) == covered
    assert all(guide.sources and guide.caution for guide in MODULE_GUIDES)


def test_catalog_has_definitions_and_resolved_sources_without_ambiguous_keys():
    terms = all_terms()
    assert len({term.key for term in terms}) == len(terms)
    assert set(ESSENTIAL_KEYS) <= {term.key for term in terms}
    assert all(term.definition and term.caution for term in terms)
    for item in (*terms, *READING_GUIDES, *MODULE_GUIDES):
        assert set(item.sources) <= SOURCE_BY_KEY.keys()


def test_audited_definitions_and_formulas_are_resolved_from_the_shared_registry():
    for term in all_terms():
        if term.metric_key:
            metric = get_metric_definition(term.metric_key)
            assert term.definition == metric.short_definition
            assert technical_details(term)["Fórmula / regra"] == metric.formula
            assert technical_details(term)["Quando fica N/D"] == metric.null_policy
    # A fonte do custo de crédito permanece a rubrica publicada; nenhum de-para é inferido.
    term = next(term for term in all_terms() if term.key == "credit_loss_cost")
    assert "f3" in technical_details(term)["Campos / contas"]
    assert "Sem de-para COSIF" in technical_details(term)["Observações"]


@pytest.mark.parametrize("query,key", [
    ("conglomerado PRUDENCIAL", "prudential"),
    ("provisao", "provision"),
    ("9011", "statements"),
    ("CET1", "cet1"),
    ("n/d", "missing"),
    ("arrasto", "default_balance"),
    ("f3", "credit_loss_cost"),
    ("PIX", "payment_volume"),
    ("conselho", "governance"),
])
def test_search_accepts_accents_acronyms_sources_and_module_names(query, key):
    assert key in {term.key for term in search_terms(query)}


def test_search_respects_topic_and_can_have_no_results():
    matches = search_terms("carteira", "Carteira e perdas")
    assert matches and all(term.topic == "Carteira e perdas" for term in matches)
    assert search_terms("termo que nao existe xyz123") == ()


def test_default_page_prioritizes_readable_definitions_and_keeps_formulas_in_popovers():
    app = _app()
    assert not app.exception
    assert [tab.label for tab in app.tabs] == [
        "Definições", "Fontes e escopo", "Cuidados de leitura", "Onde encontrar no app"]
    assert len(app.get("popover")) == len(ESSENTIAL_KEYS) + 1
    assert not app.dataframe
    text = " ".join(element.value for element in app.markdown)
    assert "Mapeamento de cachês" not in text
    assert "Instituição individual" in text and "Conglomerado prudencial" in text


def test_filtering_and_search_reset_result_page():
    app = _app()
    app.toggle(key="glossary_show_all").set_value(True).run()
    page = app.selectbox(key="glossary_page_number")
    assert len(page.options) > 1
    page.set_value(2).run()
    assert app.selectbox(key="glossary_page_number").value == 2
    app.text_input(key="glossary_query").set_value("estagio").run()
    assert not app.exception
    assert app.session_state["glossary_page_number"] == 1
    app.text_input(key="glossary_query").set_value("").run()
    assert app.selectbox(key="glossary_page_number").value == 1
    app.selectbox(key="glossary_topic").set_value("Governança").run()
    assert not app.exception
    assert "Conselho e diretoria" in " ".join(element.value for element in app.markdown)


def test_no_results_does_not_hide_sources_or_other_help():
    app = _app()
    app.text_input(key="glossary_query").set_value("xyz123semresultado").run()
    assert not app.exception
    assert any("Nenhum termo" in element.value for element in app.info)
    assert app.selectbox(key="glossary_source")
    assert app.selectbox(key="glossary_module")


def test_source_selection_distinguishes_accounting_documents_and_frequencies():
    app = _app()
    app.selectbox(key="glossary_source").set_value("cosif_prudential").run()
    text = " ".join(element.value for element in app.markdown)
    assert "4060 mensal; 4066 semestral" in text
    assert "4060 e 4066 representam documentos diferentes" in text
    app.selectbox(key="glossary_source").set_value("statements").run()
    assert not app.exception
    assert "Semestral e anual" in " ".join(element.value for element in app.markdown)


def test_reading_guide_distinguishes_historical_cutoffs_and_filter_remains_usable():
    app = _app()
    app.selectbox(key="glossary_guide").set_value("history").run()
    text = " ".join(element.value for element in app.markdown)
    assert all(cutoff in text for cutoff in ("mar/2014", "mar/2015", "mar/2025"))
    app.text_input(key="glossary_guide_query").set_value("2025").run()
    assert not app.exception
    app.text_input(key="glossary_guide_query").set_value("semresultadoxyz123").run()
    assert any("Nenhuma orientação" in element.value for element in app.info)
    app.text_input(key="glossary_guide_query").set_value("").run()
    assert app.selectbox(key="glossary_guide")
    assert not app.exception


def test_module_consultation_exposes_the_current_dre_and_cosif_sources():
    app = _app()
    app.selectbox(key="glossary_module").set_value("DRE (Ind. e Congl.)").run()
    assert "A tela consulta o BCB" in " ".join(element.value for element in app.markdown)
    app.selectbox(key="glossary_module").set_value("Contas COSIF").run()
    text = " ".join(element.value for element in app.markdown)
    assert "COSIF 4010" in text and "COSIF 4060 e 4066" in text
    assert not app.exception
