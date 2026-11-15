"""Visões imobiliárias no mesmo catálogo de cards e exportadores de Crédito BC."""
from __future__ import annotations

from hashlib import sha256
import json

import pandas as pd
import streamlit as st

from utils.mercado_imobiliario import CHARTS, FACT_COLUMNS, METHODOLOGY_URL, SOURCE_URL, SECTIONS, figures_for_section


def load_frame(get_cache_manager):
    manager = get_cache_manager() if get_cache_manager else None
    cache = manager.get_cache("mercado_imobiliario") if manager else None
    if cache is None:
        return pd.DataFrame(columns=FACT_COLUMNS), {}, "Cache Mercado Imobiliário não registrado."
    result = cache.carregar()
    if not result.sucesso or result.dados is None:
        return pd.DataFrame(columns=FACT_COLUMNS), result.metadata or {}, result.mensagem
    return result.dados, result.metadata or {}, ""


def deck_sections(frame, *, uf="br", months=12, start=None, end=None):
    sections, coverage = [], []
    for section in SECTIONS:
        figures, checks = figures_for_section(frame, section, uf=uf, months=months, start=start, end=end)
        coverage.extend(checks)
        missing = [item["Seção"].split(" · ")[-1] for item in checks if item["Situação"] != "Incluída"]
        text = "Histórico de Risco da Operação até dezembro/2024." if section.startswith("Estoque") else ""
        if missing:
            text += " Sem dados no recorte: " + ", ".join(missing) + "."
        sections.append(("Mercado Imobiliário · " + section,
                         (text.strip(), "Fonte: BCB · Olinda/MercadoImobiliario") if text.strip() else None, figures))
    return sections, coverage


GLOSSARY = (
    "Contratação: valores contratados e liberados; taxa anual ponderada pelo valor contratado; LTV é uma mediana disponível para PF.\n\n"
    "Estoque: carteira inclui valores a vencer, vencidos e em prejuízo. Inadimplência é percentual; ativos problemáticos são saldos em reais. "
    "Risco da Operação é histórico até dezembro/2024 e utiliza a classificação AA–D ou mais. Parcela é mediana, disponível para PF.\n\n"
    "Imóveis: tipo, dormitórios, implantação e garantia são contagens. Área, avaliação e compra são medianas. "
    "Usa-se a série nacional publicada; medianas e taxas não são somadas entre estados.\n\n"
    "Publicação mensal; defasagem informada pelo BCB de 60 dias para crédito e 90 dias para imóveis. "
    "As séries de imóveis estão sujeitas a revisão e a atrasos de registro. BNDU excluído."
)


def glossary_section():
    return ("Glossário · Mercado Imobiliário", (GLOSSARY, "Fonte: Banco Central do Brasil · Olinda/MercadoImobiliario · Metodologia do BCB"), [])


def render(get_cache_manager):
    from tabs.mercado_credito import _cards_em_grade

    frame, metadata, error = load_frame(get_cache_manager)
    if frame.empty:
        st.warning("Mercado Imobiliário ainda não está disponível nesta base. Atualize essa fonte em Atualizar Base.")
        if error:
            st.caption(error)
        return None
    ends = {label: frame.loc[frame["grafico"].str.startswith(prefix), "data"].max()
            for label, prefix in (("Contratação e Estoque", ("contratacao_", "estoque_")), ("Imóveis", "imoveis_"))}
    st.caption("Competência no cache · " + " · ".join(f"{label}: **{value:%m/%Y}**" for label, value in ends.items() if pd.notna(value)))
    selected = st.segmented_control("Visão do Mercado Imobiliário", SECTIONS, default=SECTIONS[0], key="imob_section")
    left, right = st.columns(2)
    with left:
        ufs = ["br", *sorted(set(frame["uf"]) - {"br", "na"})]
        if st.session_state.get("imob_uf") not in ufs:
            st.session_state["imob_uf"] = "br"
        uf = st.selectbox("Abrangência", ufs, format_func=lambda value: "Brasil" if value == "br" else value.upper(), key="imob_uf")
    with right:
        window = st.selectbox("Período", ("Últimos 12 meses", "Últimos 24 meses", "Série completa", "Intervalo"), key="imob_window")
    months = 12 if window == "Últimos 12 meses" else 24 if window == "Últimos 24 meses" else None
    start, end = None, None
    if window == "Intervalo":
        periods = sorted(frame["data"].unique())
        a, b = st.columns(2)
        with a:
            start = st.selectbox("Período inicial", periods, index=max(0, len(periods) - 12), format_func=lambda value: pd.Timestamp(value).strftime("%m/%Y"), key="imob_start")
        with b:
            end = st.selectbox("Período final", [p for p in periods if p >= start], index=len([p for p in periods if p >= start]) - 1,
                               format_func=lambda value: pd.Timestamp(value).strftime("%m/%Y"), key="imob_end")
    if selected.startswith("Estoque"):
        st.caption("Risco da Operação: série histórica até dez/2024. Na janela móvel, cada gráfico usa sua própria última competência.")
    if selected == "Imóveis":
        st.caption("Os registros de imóveis têm defasagem de 90 dias e estão sujeitos a revisões e atrasos de registro.")
    options = {"uf": uf, "months": months, "start": start, "end": end}
    figures, coverage = figures_for_section(frame, selected, **options)
    pending = []
    for fig in figures:
        card = (fig, "imob_" + fig.layout.meta["chart_key"])
        if fig.layout.barmode == "stack":
            if pending:
                _cards_em_grade(pending, colunas=2); pending = []
            _cards_em_grade([card], colunas=1)
        else:
            pending.append(card)
            if len(pending) == 2:
                _cards_em_grade(pending, colunas=2); pending = []
    if pending:
        _cards_em_grade(pending, colunas=2)
    for check in coverage:
        if check["Situação"] != "Incluída":
            st.info(check["Seção"].split(" · ")[-1] + ": sem dados no recorte selecionado.")
    with st.expander("Conceitos e fontes do Mercado Imobiliário"):
        st.markdown(GLOSSARY)
        st.markdown(f"[Página do BCB]({SOURCE_URL}) · [Metodologia]({METHODOLOGY_URL})")
        st.dataframe(pd.DataFrame(coverage).drop(columns=["erro"]), hide_index=True, width="stretch")
    return {"frame": frame, "metadata": metadata, "options": options}


def render_download(context):
    """Arquivo da seção inteira, sem exigir a visita às cinco visões."""
    from utils.sgs_credit_pptx_export import exportar_deck_secoes_pptx

    if not context:
        return
    signature = sha256(pd.util.hash_pandas_object(context["frame"], index=True).values.tobytes()
                       + json.dumps(context["options"], sort_keys=True, default=str).encode()).hexdigest()
    memo = st.session_state.setdefault("imob_deck", {})
    if memo.get("signature") != signature:
        memo.clear(); memo["signature"] = signature
    if st.button("Gerar PPTX de Mercado Imobiliário", key="imob_generate", width="stretch"):
        try:
            with st.spinner("Preparando os gráficos editáveis..."):
                sections, coverage = deck_sections(context["frame"], **context["options"])
                complete = all(item["Situação"] == "Incluída" for item in coverage)
                if not any(item["Gráficos"] for item in coverage):
                    raise ValueError("Sem dados no recorte selecionado.")
                blob, meta = exportar_deck_secoes_pptx([*sections, glossary_section()],
                    titulo_deck="Mercado Imobiliário" + ("" if complete else " · exportação parcial"),
                    subtitulo_capa="Contratação, Estoque e Imóveis · " + context["options"]["uf"].upper(),
                    rodape_capa="Fonte: BCB · Olinda/MercadoImobiliario · competências indicadas em cada gráfico")
                memo["value"] = (blob, meta, complete)
                memo.pop("error", None)
        except Exception as exc:
            memo["error"] = str(exc)
    if memo.get("error"):
        st.error(memo["error"])
    if memo.get("value"):
        blob, meta, complete = memo["value"]
        if not complete:
            st.warning("Arquivo parcial: há gráficos sem dados no recorte.")
        st.download_button(f"Baixar Mercado Imobiliário ({meta['paineis']} gráficos)", blob,
            file_name="mercado_imobiliario" + ("" if complete else "_parcial") + ".pptx",
            mime="application/vnd.openxmlformats-officedocument.presentationml.presentation", key="imob_download", width="stretch")
