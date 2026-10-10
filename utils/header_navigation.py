"""Navegação agrupada, com popovers nativos e adaptação à largura disponível."""
from collections.abc import Callable
from html import escape

import streamlit as st


NAVIGATION_GROUPS = (
    ("Instituições", (
        "Snapshot", "Rankings", "Tabela de Peers", "Evolução", "Scatter Plot",
        "Conselho e Diretoria",
    )),
    ("Contábil e crédito", (
        "DRE (Ind. e Congl.)", "Balanço, DRE e DMPL (Ind.)", "Contas COSIF",
        "Carteira 4.966",
    )),
    ("Mercado", (
        "Estatísticas Crédito BC", "Taxas de Juros por Produto",
        "Meios de Pagamento (SPB)",
    )),
    ("Ajuda e dados", ("Glossário", "Sobre", "Atualizar Base")),
)


HEADER_NAVIGATION_CSS = """
<style>
[data-testid="stMainBlockContainer"] {padding-top: 4rem !important;}
.st-key-header_navigation {
    container-type: inline-size;
    container-name: tc-navigation;
    padding: 4px 0 12px;
    border-bottom: 1px solid #e3e9ee;
    flex-wrap: nowrap;
    justify-content: space-between;
    gap: 20px;
}
.tc-nav-brand {
    display: flex;
    align-items: center;
    gap: 9px;
    height: 44px;
    white-space: nowrap;
}
.tc-nav-brand img {width: 38px; height: 38px; object-fit: contain;}
.tc-nav-brand span {
    font-family: 'IBM Plex Sans', sans-serif;
    font-size: 1.35rem;
    font-weight: 500;
    color: #1f77b4;
    line-height: 1.1;
}
.st-key-header_navigation > [data-testid="stLayoutWrapper"]:has(> .st-key-header_nav_mobile) {display: none;}
.st-key-header_navigation > [data-testid="stLayoutWrapper"]:has(> .st-key-header_nav_desktop) {margin-left: auto;}
.stMain .st-key-header_navigation [data-testid="stPopoverButton"] {
    min-height: 44px;
    border: 0;
    border-radius: 6px;
    padding: 8px 12px;
    color: #475461;
    background: transparent;
    white-space: nowrap;
}
.stMain .st-key-header_navigation [data-testid="stPopoverButton"] p {
    font-size: .88rem;
    font-weight: 400;
    white-space: nowrap;
}
.stMain .st-key-header_nav_group_active [data-testid="stPopoverButton"] {
    color: #1f77b4;
    background: #edf4f9;
}
.stMain .st-key-header_nav_group_active [data-testid="stPopoverButton"] p {font-weight: 500;}
[data-testid="stPopoverBody"]:has([class*="st-key-header_navigation_menu_"]) {
    padding: 10px;
    border: 1px solid #dce4eb;
    border-radius: 10px;
    box-shadow: 0 8px 24px rgba(31, 50, 68, .10);
    width: min(340px, calc(100vw - 32px));
    max-height: 72vh;
    max-height: 72dvh;
    overflow-y: auto;
    overscroll-behavior: contain;
    -webkit-overflow-scrolling: touch;
}
[class*="st-key-header_navigation_menu_"] {gap: 3px;}
[class*="st-key-header_navigation_menu_"] [data-testid="stVerticalBlock"] {gap: 3px;}
[class*="st-key-header_navigation_menu_"] [data-testid="stButton"] > button {
    min-height: 44px;
    width: 100%;
    padding: 9px 12px;
    justify-content: flex-start;
    text-align: left;
    border: 0;
    border-radius: 6px;
    background: transparent;
    color: #344452;
}
[class*="st-key-header_navigation_menu_"] [data-testid="stButton"] > button > div {justify-content: flex-start;}
[class*="st-key-header_navigation_menu_"] [data-testid="stButton"] > button p {
    font-size: .9rem;
    font-weight: 400;
    white-space: normal;
    line-height: 1.35;
    text-align: left;
}
[class*="st-key-header_navigation_menu_"] [data-testid="stButton"] > button[data-testid="stBaseButton-primary"] {
    color: #1f77b4;
    background: #edf4f9;
}
.tc-nav-section-label {
    margin: 8px 12px 3px;
    font-size: .75rem;
    font-weight: 500;
    color: #697887;
}
.st-key-header_navigation button:focus-visible,
[class*="st-key-header_navigation_menu_"] button:focus-visible {
    outline: 2px solid #1f77b4;
    outline-offset: 2px;
}
.st-key-header_navigation button:active,
[class*="st-key-header_navigation_menu_"] button:active {background: #e4edf4;}
@media (hover: hover) and (pointer: fine) {
    .stMain .st-key-header_navigation [data-testid="stPopoverButton"]:hover,
    [class*="st-key-header_navigation_menu_"] button:hover {background: #f0f5f8;}
}
/* The content width also accounts for an expanded sidebar and browser zoom. */
@container tc-navigation (max-width: 760px) {
    .st-key-header_navigation > [data-testid="stLayoutWrapper"]:has(> .st-key-header_nav_desktop) {display: none;}
    .st-key-header_navigation > [data-testid="stLayoutWrapper"]:has(> .st-key-header_nav_mobile) {display: flex; margin-left: auto;}
}
/* Fallback for browsers without container queries. */
@media (max-width: 820px) {
    .st-key-header_navigation > [data-testid="stLayoutWrapper"]:has(> .st-key-header_nav_desktop) {display: none;}
    .st-key-header_navigation > [data-testid="stLayoutWrapper"]:has(> .st-key-header_nav_mobile) {display: flex; margin-left: auto;}
}
</style>
"""


def _render_destinations(prefix: str, labels: tuple[str, ...], current: str,
                         on_navigate: Callable[[str], None]) -> None:
    for index, label in enumerate(labels):
        st.button(
            label,
            key=f"header_nav_{prefix}_{index}",
            type="primary" if label == current else "tertiary",
            width="stretch",
            on_click=on_navigate,
            args=(label,),
        )


def render_header_navigation(current: str, logo_base64: str,
                             on_navigate: Callable[[str], None], revision: int = 0) -> None:
    """Remonta só o cabeçalho após selecionar uma aba, fechando o popover."""
    st.html(HEADER_NAVIGATION_CSS)
    # Alternating block positions unmount the open native popover on navigation.
    # A container key alone does not reset the popover's frontend open state.
    if revision % 2:
        st.empty()
    with st.container(key="header_navigation_instance"):
        with st.container(key="header_navigation", horizontal=True,
                          vertical_alignment="center", gap="small"):
            logo = (f'<img src="data:image/png;base64,{escape(logo_base64, quote=True)}" '
                    'alt="" aria-hidden="true" />') if logo_base64 else ""
            with st.container(key="header_nav_brand", width="content"):
                st.html(f'<div class="tc-nav-brand">{logo}<span>toma.conta</span></div>',
                        width="content")
            with st.container(key="header_nav_desktop", width="content", horizontal=True,
                              vertical_alignment="center", gap="small"):
                for index, (group, labels) in enumerate(NAVIGATION_GROUPS):
                    group_key = "header_nav_group_active" if current in labels else f"header_nav_group_{index}"
                    with st.container(key=group_key, width="content"):
                        with st.popover(group, type="tertiary"):
                            with st.container(key=f"header_navigation_menu_desktop_{index}"):
                                _render_destinations(f"desktop_{index}", labels, current, on_navigate)
            with st.container(key="header_nav_mobile", width="content"):
                with st.popover("Menu", icon=":material/menu:", type="tertiary"):
                    with st.container(key="header_navigation_menu_mobile"):
                        for index, (group, labels) in enumerate(NAVIGATION_GROUPS):
                            st.html(f'<p class="tc-nav-section-label">{escape(group)}</p>')
                            _render_destinations(f"mobile_{index}", labels, current, on_navigate)
