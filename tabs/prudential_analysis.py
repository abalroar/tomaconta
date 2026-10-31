"""Compact prudential statements, using the portfolio table's visual language."""
from __future__ import annotations

from datetime import datetime
import hashlib
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from utils.ifdata_cache.bloprudencial_cache import load_bloprudencial_parquet_slice
from utils.ifdata_cache.revision_cache import revision_cache_data
from utils.prudential_analysis import build_analysis, text_id
from tabs.carteira_4966 import render_carteira_4966_html
from utils.prudential_presentation import default_periods, reference_note, export_filename, institution_label, period_label, render_statement_html
from utils.prudential_workbook import render_xlsx
from utils.prudential_pptx import render_pptx
from utils.prudential_nim import add_nim_rows, credit_balances, prior_periods, required_periods

MODEL_VERSION = "statement-v6"
SOURCES = ("bloprudencial", "ativo", "dre", "capital", "principal", "carteira_instrumentos")


def load_analysis(manager, code, periods):
    """Análise completa da seleção; usada pela aba e pelas exportações do Snapshot."""
    cache = manager.get_cache("bloprudencial")
    needed = required_periods(periods)
    cosif = load_bloprudencial_parquet_slice(cache, periodos_yyyymm=needed)
    cosif.attrs["prudential_provenance"] = {
        "filename": "bloprudencial/dados.parquet", "sha256": hashlib.sha256(cache.arquivo_dados.read_bytes()).hexdigest()}
    sources = {}
    for kind in SOURCES[1:]:
        result = manager.carregar(kind)
        if result.sucesso and result.dados is not None:
            sources[kind] = result.dados.copy()
            path = manager.get_cache(kind).arquivo_dados
            if path.is_file():
                sources[kind].attrs["prudential_provenance"] = {
                    "filename": f"{kind}/dados.parquet", "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    analysis = build_analysis(cosif, sources, code, periods)
    # A carteira média das NIMs usa dezembro anterior, mesmo fora da seleção.
    prior_credit = {}
    available = set(cosif[cosif.COD_CONGL.astype(str).eq(code)].DATA_BASE.map(text_id))
    missing = [p for p in prior_periods(analysis.periods) if p in available]
    if missing:
        prior_credit = credit_balances(build_analysis(cosif, sources, code, missing))
    add_nim_rows(analysis, prior_credit)
    return analysis


def render(manager, cache_token, *, portfolio_model=None, evolution_payload=None):
    """``portfolio_model`` e ``evolution_payload`` entregam as visões dos menus Carteira 4.966 e Evolução."""
    cache = manager.get_cache("bloprudencial")
    if cache is None or not cache.arquivo_dados.exists():
        st.info("Base prudencial indisponível. Consulte Atualizar Base.")
        return

    @revision_cache_data(show_spinner=False, max_entries=4)
    def catalog(token):
        path = manager.get_cache("bloprudencial").arquivo_dados
        frame = pd.read_parquet(path, columns=["COD_CONGL", "NOME_CONGL", "DATA_BASE"])
        frame["DATA_BASE"] = frame.DATA_BASE.map(text_id)
        return frame.drop_duplicates().sort_values("DATA_BASE")

    source_token = tuple((kind, cache_token(kind)) for kind in SOURCES)
    data = catalog(source_token)
    names = data.drop_duplicates("COD_CONGL", keep="last").set_index("COD_CONGL").NOME_CONGL.to_dict()
    codes = sorted(names, key=lambda code: names[code])
    default = next((i for i, code in enumerate(codes) if "ITAU" in names[code].upper()), 0)
    labels = {code: institution_label(name) for code, name in names.items()}
    repeated = pd.Series(labels).duplicated(keep=False).to_dict()
    left, right, export = st.columns([1.1, 2.7, .62], gap="small")
    with left:
        code = st.selectbox("Instituição", codes, index=default,
                            format_func=lambda c: labels[c] + (f" ({c})" if repeated[c] else ""),
                            key="prudential_excel_code")
    available = sorted(data.loc[data.COD_CONGL.eq(code), "DATA_BASE"].unique(), reverse=True)
    context = (code, tuple(available))
    if st.session_state.get("prudential_excel_period_context") != context:
        st.session_state["prudential_excel_periods"] = default_periods(available, datetime.now(ZoneInfo("America/Sao_Paulo")))
        st.session_state["prudential_excel_period_context"] = context
    with right:
        periods = st.multiselect("Períodos", available, key="prudential_excel_periods", max_selections=8,
                                format_func=period_label)
    if not periods:
        st.caption("Selecione um período.")
        return

    signature = hashlib.sha256(repr((MODEL_VERSION, code, sorted(periods), source_token)).encode()).hexdigest()
    saved = st.session_state.get("prudential_excel_result")
    if not saved or saved[0] != signature:
        try:
            with st.spinner("Carregando demonstrações…"):
                analysis = load_analysis(manager, code, periods)
                saved = (signature, analysis)
                st.session_state["prudential_excel_result"] = saved
        except (ValueError, KeyError, OSError) as exc:
            st.error("Não foi possível reconciliar esta seleção.")
            with st.expander("Detalhes da fonte"):
                st.write(str(exc))
            return
    _, analysis = saved
    def _evolution():
        return evolution_payload(code) if evolution_payload else None
    model = portfolio_model(code, sorted(periods)) if portfolio_model else None
    with export, st.container(key="tc_fin_export"):
        # The export button lines up with the fields, below their labels.
        st.markdown("""<style>.st-key-tc_fin_export { margin-top:1.75rem; }
.st-key-tc_fin_export [data-testid="stElementContainer"]:has(style) { display:none; }
@media(max-width:640px) { .st-key-tc_fin_export { margin-top:0; } }</style>""", unsafe_allow_html=True)
        with st.popover("Exportar", width="stretch"):
            filename = export_filename(analysis)
            def _extras():
                return {"portfolio": model, "evolution": _evolution()}
            st.download_button("Excel", data=lambda a=analysis: render_xlsx(a, **_extras()),
                               file_name=filename + ".xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               key=f"download_prudential_excel_{signature}", on_click="ignore", width="stretch")
            st.download_button("PowerPoint", data=lambda a=analysis: render_pptx(a, **_extras()),
                               file_name=filename + ".pptx",
                               mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                               key=f"download_prudential_pptx_{signature}", on_click="ignore", width="stretch")
    for tab, name in zip(st.tabs(["Balanço", "DRE", "Carteira 4.966"]), ["Balanço", "DRE", "Carteira 4.966"]):
        with tab:
            # A Carteira segue o menu Carteira 4.966: hierarquia, percentuais e variações.
            if name == "Carteira 4.966" and model is not None and model.periods:
                st.markdown(render_carteira_4966_html(model), unsafe_allow_html=True)
                if len(model.periods) < len(periods):
                    st.caption("Carteira 4.966: dado trimestral; competências mensais selecionadas não têm esta abertura.")
            else:
                st.markdown(render_statement_html(analysis, name), unsafe_allow_html=True)
    st.caption(("R$ milhões. DRE acumulada no ano. –: dado não disponível na fonte para o período. " + reference_note(analysis)).rstrip())
