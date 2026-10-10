"""Acabamento comum das abas de trabalho; não altera gráficos nem exportações."""
import streamlit as st


WORKSPACE_CSS = """
<style>
/* A página Sobre conserva a apresentação aprovada. Esta folha só é inserida
   nas demais abas. Os seletores abaixo usam widgets nativos e nomes estáveis. */
.header-logo {margin-top:0;}
.header-logo img {width:104px;}
.header-brand-copy {margin-top:0!important;}
.header-brand-title {font-size:2.15rem!important; line-height:1.1; font-weight:500!important; margin-bottom:.25rem!important;}
.header-brand-subtitle {font-size:1rem!important; line-height:1.4; font-weight:400!important;}
.header-brand-author {font-size:.78rem!important; color:#647180!important; margin-bottom:.2rem!important;}
div[data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .header-logo) {gap:.15rem;}

.stMain [data-testid="stHeadingWithActionElements"] h2 {font-size:1.8rem; line-height:1.25;}
.stMain [data-testid="stHeadingWithActionElements"] h3 {font-size:1.5rem; line-height:1.3;}
.stMain [data-testid="stHeadingWithActionElements"] h4 {font-size:1.15rem; line-height:1.35;}
.stMain [data-testid="stMarkdownContainer"] > p {font-weight:400!important; line-height:1.5;}
.stMain [data-testid="stWidgetLabel"] p {font-weight:500!important; font-size:.88rem; color:#3d4b59;}
.stMain [data-testid="stCaptionContainer"] {opacity:1!important;}
.stMain [data-testid="stCaptionContainer"] p {font-weight:400!important; color:#596775; font-size:.82rem; line-height:1.45;}
.stMain [data-testid="stCaptionContainer"] strong {font-weight:600;}
.stMain [data-testid="stRadio"] label p,
.stMain [data-testid="stCheckbox"] label p,
.stMain [data-testid="stToggle"] label p {font-weight:400!important;}
.stMain [data-baseweb="select"] div {font-weight:400!important;}
.stMain [data-testid="stTextInput"] input,
.stMain [data-testid="stNumberInput"] input,
.stMain [data-testid="stTextArea"] textarea {font-weight:400!important;}
.stMain [data-testid="stSelectbox"] [data-baseweb="select"] > div,
.stMain [data-testid="stMultiSelect"] [data-baseweb="select"] > div {border-color:#dbe2e8; border-radius:6px;}
.stMain [data-testid="stSelectbox"] [data-baseweb="select"]:focus-within > div,
.stMain [data-testid="stMultiSelect"] [data-baseweb="select"]:focus-within > div {border-color:#1f77b4;}

.stMain [data-testid="stButton"] button,
.stMain [data-testid="stDownloadButton"] button,
.stMain [data-testid="stPopover"] > div > button {border-radius:6px; min-height:36px;}
.stMain [data-testid="stButton"] button p,
.stMain [data-testid="stDownloadButton"] button p {font-weight:500!important;}
.stMain button:focus-visible,
.stMain a:focus-visible,
.stMain summary:focus-visible {outline:2px solid #1f77b4; outline-offset:3px;}

.stMain [data-testid="stExpander"] {margin-top:.4rem!important; border-color:#dbe2e8; border-radius:8px;}
.stMain [data-testid="stExpander"] summary {padding:.6rem .85rem!important; border-radius:8px; background:#fafbfc; min-height:40px;}
.stMain [data-testid="stExpander"] summary p {font-weight:500!important; font-size:.88rem;}
.stMain [data-testid="stExpanderDetails"] {padding:.8rem 1rem;}
.stMain [data-testid="stTabs"] [role="tab"] p {font-weight:500!important; font-size:.9rem;}
.stMain [data-testid="stTabs"] [role="tab"] {padding:.5rem .85rem;}
.stMain [data-testid="stDataFrame"] {border:1px solid #dbe2e8; border-radius:8px;}
.stMain [data-testid="stAlert"] {border-radius:8px;}

.stMain [data-testid="stMetric"] {box-shadow:none; border:1px solid #e1e7ec; background:#f8fafb; border-radius:8px; padding:14px 16px;}
.stMain [data-testid="stMetricLabel"] p {font-weight:500!important; color:#596775;}
.stMain [data-testid="stMetricValue"] {font-size:1.75rem; font-weight:500!important; font-variant-numeric:tabular-nums;}
.stMain .snap-card__label {font-weight:500!important; font-size:.76rem; color:#596775;}
.stMain .snap-card__value {font-weight:500!important; font-variant-numeric:tabular-nums;}
.stMain .snap-card__delta {font-weight:400!important;}
.stMain .snap-card__delta-label {color:#647180;}
.stMain .snap-section {font-weight:500!important;}
.stMain .titulo-card {font-weight:600!important;}

@media (hover:hover) and (pointer:fine) {
  .stMain [data-testid="stExpander"] summary:hover {background:#f2f6f9;}
}
@media (max-width:700px) {
  .header-logo img {width:84px;}
  .header-brand-title {font-size:1.85rem!important;}
  .header-brand-subtitle {font-size:.9rem!important;}
  .stMain [data-testid="stMetricValue"] {font-size:1.5rem;}
}
</style>
"""


def render_rankings_data_labels_toggle(indicator_label: str) -> bool:
    """Mantém a escolha no indicador atual e habilita labels ao trocar indicador."""
    key = "ranking_data_labels_toggle"
    indicator_key = "ranking_data_labels_last_indicator"
    if key not in st.session_state or st.session_state.get(indicator_key) != indicator_label:
        st.session_state[key] = True
        st.session_state[indicator_key] = indicator_label
    return st.toggle(
        "Exibir valores", key=key,
        help="Mostra/oculta os valores diretamente nas barras do gráfico.",
    )
