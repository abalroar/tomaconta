"""Consulta do glossário em linguagem direta, com detalhes sob demanda."""
from __future__ import annotations

import math

import streamlit as st

from utils.glossary_catalog import (
    ESSENTIAL_KEYS, MODULE_GUIDES, READING_GUIDES, SOURCES, SOURCE_BY_KEY,
    GlossaryTerm, SourceGuide, all_terms, matches_query, search_terms, technical_details,
)


PAGE_SIZE = 8
GLOSSARY_CSS = """
<style>
.st-key-glossary_page [data-testid="stMarkdownContainer"] > p {max-width:78ch;}
.st-key-glossary_page [data-testid="stCaptionContainer"] p {max-width:88ch;}
.st-key-glossary_page [class*="st-key-glossary_term_"] {padding:.6rem 0;}
.st-key-glossary_page [class*="st-key-glossary_term_"] h3 {font-size:1.15rem; line-height:1.35;}
.st-key-glossary_page [data-testid="stPopover"] > div > button {
    min-height:36px; font-size:.82rem; color:#1f77b4;
}
@media (max-width:700px) {
    .st-key-glossary_page [data-testid="stPopover"] > div > button {min-height:44px;}
}
</style>
"""


def _source_links(source_keys: tuple[str, ...]) -> None:
    for key in source_keys:
        source = SOURCE_BY_KEY[key]
        st.markdown(f"**{source.name}**")
        st.write(f"{source.frequency}. {source.scope}")
        for label, url in source.links:
            st.markdown(f"[{label}]({url})")


def _render_term(term: GlossaryTerm) -> None:
    with st.container(key=f"glossary_term_{term.key}"):
        st.subheader(term.title, anchor=f"glossary-{term.key}")
        st.write(term.definition)
        st.caption(f"Ao interpretar: {term.caution}")
        with st.popover("Fórmula e fonte"):
            st.markdown(f"**{term.title}**")
            if term.example:
                st.markdown(f"**Exemplo:** {term.example}")
            for label, value in technical_details(term).items():
                st.markdown(f"**{label}:** {value}")
            if term.modules:
                st.markdown(f"**Onde aparece:** {', '.join(term.modules)}")
            if term.sources:
                _source_links(term.sources)
            else:
                st.caption("Convenção de leitura do app. Confira a fonte do indicador na tela em que ele aparece.")


def _render_definitions() -> None:
    terms = all_terms()
    search_col, topic_col = st.columns([3, 2])
    with search_col:
        query = st.text_input("Buscar termo, sigla ou assunto", key="glossary_query",
                              placeholder="Ex.: COSIF, ROE, provisão, 9011, Pix")
    topics = ("Todos os temas", *dict.fromkeys(term.topic for term in terms))
    with topic_col:
        topic = st.selectbox("Tema", topics, key="glossary_topic")

    is_browsing = not query.strip() and topic == "Todos os temas"
    show_all = st.toggle("Explorar todos os termos", key="glossary_show_all", disabled=not is_browsing,
                         help="Sem busca ou filtro, alterna entre os conceitos essenciais e o índice completo.")
    if is_browsing and not show_all:
        by_key = {term.key: term for term in terms}
        matches = tuple(by_key[key] for key in ESSENTIAL_KEYS)
        st.caption("Comece por estes conceitos. Use a busca ou escolha um tema para consultar o restante do glossário.")
    else:
        matches = search_terms(query, topic)
        suffix = "termo encontrado" if len(matches) == 1 else "termos encontrados"
        st.caption(f"{len(matches)} {suffix}. A busca inclui siglas, fontes, fórmulas e nomes das abas.")

    if not matches:
        st.info("Nenhum termo encontrado. Tente uma sigla, uma palavra mais curta ou selecione Todos os temas.")
        return

    # Resetar antes de criar o widget evita conservar uma página inválida ao filtrar.
    signature = (query, topic, show_all)
    if st.session_state.get("glossary_results_signature") != signature:
        st.session_state["glossary_results_signature"] = signature
        st.session_state["glossary_page_number"] = 1
    page_count = math.ceil(len(matches) / PAGE_SIZE)
    page = 1
    if page_count > 1:
        page = st.selectbox("Página dos resultados", range(1, page_count + 1),
                            format_func=lambda number: f"{number} de {page_count}", key="glossary_page_number")
        start = (page - 1) * PAGE_SIZE
        st.caption(f"Exibindo {start + 1} a {min(start + PAGE_SIZE, len(matches))} de {len(matches)} termos.")
    for term in matches[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]:
        _render_term(term)


def _render_source_details(source: SourceGuide) -> None:
    st.subheader(source.name, anchor=f"source-{source.key}")
    st.write(source.description)
    st.markdown(f"**Frequência dos dados:** {source.frequency}")
    st.markdown(f"**Escopo:** {source.scope}")
    st.markdown(f"**Quando a fonte publica:** {source.publication}")
    st.markdown(f"**Como aparece no app:** {source.in_app}")
    st.markdown(f"**Cuidados de leitura:** {source.caution}")
    for label, url in source.links:
        st.markdown(f"[{label}]({url})")


def _render_sources() -> None:
    st.write("Cada base tem uma unidade de observação e um calendário próprio. "
             "Consulte a fonte para entender o que entra no número e a defasagem esperada.")
    key = st.selectbox("Escolha a fonte", tuple(SOURCE_BY_KEY),
                       format_func=lambda value: SOURCE_BY_KEY[value].name, key="glossary_source")
    _render_source_details(SOURCE_BY_KEY[key])
    with st.expander("Comparar periodicidades das fontes"):
        # Três colunas curtas; a descrição de escopo fica na consulta acima.
        st.table([{"Fonte": source.name, "Frequência": source.frequency,
                   "Unidade de observação": {
                       "ifdata": "Instituição ou grupo", "ifdata_credit": "Carteira por instituição ou grupo",
                       "cosif_4010": "Conta por instituição", "cosif_prudential": "Conta por conglomerado",
                       "statements": "Demonstração individual", "scr": "Recorte agregado de operações",
                       "sgs": "Mercado ou segmento", "rates": "Instituição e produto",
                       "payments": "Instrumento, canal ou infraestrutura", "registry": "Pessoa jurídica e vínculos",
                   }[source.key]} for source in SOURCES])
    st.caption("As frequências e os prazos acima descrevem as fontes. "
               "A competência efetivamente carregada deve ser conferida na aba consultada ou em Atualizar Base.")


def _render_reading_guides() -> None:
    query = st.text_input("Buscar uma dúvida de leitura", key="glossary_guide_query",
                          placeholder="Ex.: 2025, trimestre, unidades, inadimplência")
    guides = tuple(guide for guide in READING_GUIDES if matches_query(
        query, guide.title, guide.explanation, guide.example))
    if not guides:
        st.info("Nenhuma orientação encontrada. Tente outro assunto ou limpe a busca.")
        return
    selected_key = st.selectbox("Dúvida de leitura", tuple(guide.key for guide in guides),
                                format_func=lambda key: next(guide.title for guide in guides if guide.key == key),
                                key="glossary_guide")
    guide = next(guide for guide in guides if guide.key == selected_key)
    st.subheader(guide.title, anchor=f"reading-{guide.key}")
    st.write(guide.explanation)
    st.markdown(f"**Exemplo de leitura:** {guide.example}")
    with st.popover("Consultar as fontes desta orientação"):
        _source_links(guide.sources)


def _render_modules() -> None:
    modules = {module.name: module for module in MODULE_GUIDES}
    name = st.selectbox("Escolha a aba do app", tuple(modules), key="glossary_module")
    module = modules[name]
    st.subheader(module.name, anchor="glossary-module")
    st.write(module.purpose)
    st.markdown(f"**Ao usar esta aba:** {module.caution}")
    st.markdown("#### Fontes usadas")
    for source_key in module.sources:
        source = SOURCE_BY_KEY[source_key]
        st.markdown(f"**{source.name}** · {source.frequency}")
        st.write(source.scope)
    related = tuple(term for term in all_terms() if name in term.modules)
    if related:
        st.markdown("#### Termos para consultar")
        st.write(" · ".join(term.title for term in related))
        st.caption("Use a busca em Definições para abrir o conceito, a fórmula e as ressalvas.")


def render() -> None:
    st.markdown(GLOSSARY_CSS, unsafe_allow_html=True)
    with st.container(key="glossary_page"):
        st.markdown("## Glossário")
        st.write("Definições para entender os indicadores, escolher a fonte "
                 "e comparar os dados do Toma Conta.")
        definitions, sources, guides, modules = st.tabs(
            ["Definições", "Fontes e escopo", "Cuidados de leitura", "Onde encontrar no app"])
        with definitions:
            _render_definitions()
        with sources:
            _render_sources()
        with guides:
            _render_reading_guides()
        with modules:
            _render_modules()
