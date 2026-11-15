"""Página inicial: catálogo atual e estimativa automática de desenvolvimento."""
from __future__ import annotations

from html import escape
from pathlib import Path
from urllib.parse import urlencode

import plotly.graph_objects as go
import streamlit as st

from utils.about_catalog import MODULES, METRIC_GROUPS, OPERATIONS, STEPS, STACK
from utils.development_hours import EstimateCache, TZ_BR, load_config, parse_datetime
from utils.sgs_credit_analytics import ITAU_ORANGE

ROOT = Path(__file__).resolve().parents[1]

ABOUT_CSS = """
<style>
.st-key-about_content .module-grid {grid-template-columns:repeat(auto-fit,minmax(min(100%,280px),1fr));}
.st-key-about_content a.module-chip {text-decoration:none; color:inherit; transition:none; box-shadow:none; min-height:88px;}
.st-key-about_content a.module-chip:hover {transform:none; border-color:#1f77b4; box-shadow:none;}
.st-key-about_content a.module-chip:focus-visible {outline:2px solid #1f77b4; outline-offset:3px;}
.st-key-about_content .module-desc {-webkit-line-clamp:unset; display:block;}
.st-key-about_content .module-top {align-items:flex-start;}
.st-key-about_content .module-title {font-size:.95rem;}
.st-key-about_content .metrics-grid {grid-template-columns:repeat(auto-fit,minmax(min(100%,240px),1fr));}
.dev-hours-summary {display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); border:1px solid #dedede; border-radius:8px; background:white; overflow:hidden;}
.dev-hours-item {padding:14px 16px; border-right:1px solid #e8e8e8;}
.dev-hours-item:last-child {border-right:0;}
.dev-hours-label {font-size:.82rem; color:#555; line-height:1.35; margin-bottom:6px;}
.dev-hours-value {font-size:1.5rem; font-weight:600; color:#222; white-space:nowrap; font-variant-numeric:tabular-nums;}
.dev-hours-total {background:#f6f7f8;}
@media(max-width:700px) {.dev-hours-summary {grid-template-columns:repeat(2,minmax(0,1fr));} .dev-hours-item{border-bottom:1px solid #e8e8e8;} .dev-hours-total {grid-column:1/-1;} .dev-hours-value{font-size:1.3rem;}}
</style>
"""


def format_hours(value):
    if value is None:
        return "—"
    return f"{value:,.1f}".replace(",", "~").replace(".", ",").replace("~", ".") + " h"


def format_date(value, *, time=False):
    date = parse_datetime(value)
    if date is None:
        return "—"
    if len(str(value)) == 10 and not time:
        return date.strftime("%d/%m/%Y")
    return date.astimezone(TZ_BR).strftime("%d/%m/%Y %H:%M" if time else "%d/%m/%Y")


def summary_html(snapshot):
    snapshot = snapshot or {}
    items = (
        ("Total estimado", format_hours(snapshot.get("total_horas"))),
        ("Horas entre commits", format_hours(snapshot.get("horas_base_commits"))),
        ("Overhead de sessão", format_hours(snapshot.get("horas_overhead"))),
        ("Sessões de trabalho", str(snapshot.get("total_sessoes", "—"))),
        ("Sessão média", format_hours(snapshot.get("sessao_media_horas"))),
    )
    return '<div class="dev-hours-summary" role="group" aria-label="Resumo da estimativa">' + "".join(
        f'<div class="dev-hours-item {"dev-hours-total" if index == 0 else ""}"><div class="dev-hours-label">{escape(label)}</div><div class="dev-hours-value">{escape(value)}</div></div>'
        for index, (label, value) in enumerate(items)
    ) + "</div>"


def weekly_figure(snapshot):
    rows = snapshot.get("esforco_semanal", [])
    dates = [row["semana_inicio"] for row in rows]
    tooltips = [
        f"Semana de {format_date(row['semana_inicio'])}<br>{row['sessoes']} sessões · Total: {format_hours(row['total_horas'])}<br>Entre commits: {format_hours(row['horas_commits'])}<br>Overhead: {format_hours(row['horas_overhead'])}"
        for row in rows
    ]
    fig = go.Figure()
    for name, column, color in (("Horas entre commits", "horas_commits", "#222222"), ("Overhead de sessão", "horas_overhead", ITAU_ORANGE)):
        fig.add_bar(name=name, x=dates, y=[row[column] for row in rows], marker_color=color, customdata=tooltips, hovertemplate="%{customdata}<extra></extra>")
    tick_rows = rows[::max(1, (len(rows) + 7) // 8)]
    fig.update_layout(
        template="plotly_white", barmode="stack", height=290, separators=",.",
        margin=dict(l=12, r=12, t=40, b=15), font=dict(family="Calibri, Arial, sans-serif", color="#333", size=12),
        legend=dict(orientation="h", x=0, y=1.15, traceorder="normal"),
        xaxis=dict(title=None, type="date", tickvals=[row["semana_inicio"] for row in tick_rows], ticktext=[row["label_semana"] for row in tick_rows], fixedrange=True),
        yaxis=dict(title="Horas estimadas", rangemode="tozero", fixedrange=True, gridcolor="#ededed"),
        bargap=.2,
    )
    return fig


@st.cache_resource(show_spinner=False)
def _estimate_cache():
    return EstimateCache(ROOT / "data/dev_hours_cache.json", ROOT / "data/cache/development_hours/estimate.json")


def render_investment(*, cache=None, token=None, config=None):
    cache = cache or _estimate_cache()
    config = config or load_config(ROOT / "data/dev_hours_config.json")
    initial = cache.status(config, token)

    @st.fragment(run_every="3s" if initial.refreshing else "60s")
    def investment():
        status = cache.status(config, token)
        if initial.refreshing != status.refreshing:
            st.rerun()
        snapshot = status.snapshot or {}
        st.markdown("### Investimento de Desenvolvimento")
        view = st.segmented_control("Visualização da estimativa", ("Resumo", "Por semana"), default="Resumo", key="about_hours_view", selection_mode="single", label_visibility="collapsed") or "Resumo"
        if view == "Resumo":
            st.markdown(summary_html(snapshot), unsafe_allow_html=True)
        elif snapshot.get("esforco_semanal"):
            st.plotly_chart(weekly_figure(snapshot), width="stretch", config={"displayModeBar": False}, key="about_hours_weekly")
            st.caption(f"Total estimado: {format_hours(snapshot.get('total_horas'))}")
        else:
            st.caption("O histórico semanal será exibido após a consulta automática.")
        if snapshot:
            st.caption(
                f"{format_date(snapshot.get('primeiro_commit'))} a {format_date(snapshot.get('ultimo_commit'))} · "
                f"{snapshot.get('total_commits', '—'):,} commits únicos".replace(",", ".")
                + f" · cálculo em {format_date(snapshot.get('calculado_em'), time=True)}"
            )
        if status.refreshing:
            st.caption("Atualizando o histórico do GitHub em segundo plano. O último cálculo permanece disponível.")
        elif status.error:
            st.caption(f"{status.error} O último cálculo foi mantido. Nova tentativa automática em 15 minutos enquanto esta página estiver aberta, ou no próximo acesso após esse prazo.")
        else:
            st.caption("Atualização automática a cada 24 horas, ao acessar esta página ou enquanto ela permanecer aberta.")
        with st.expander("Metodologia e fontes", expanded=False):
            parameters = snapshot.get("parametros") or config
            st.markdown(
                f"Commits separados por até **{parameters['limiar_sessao_min']} minutos** pertencem à mesma sessão. "
                f"Somamos o intervalo entre o primeiro e o último commit de cada sessão e **{parameters['overhead_sessao_min']} minutos de overhead** por sessão. "
                "Uma sessão com um único commit contribui apenas com o overhead."
            )
            st.caption("Esta é uma estimativa por atividade no GitHub. Commits não registram toda a duração do trabalho; o overhead é uma hipótese para leitura, preparação, revisão e testes.")
            st.caption(
                "Usamos as datas de autoria e uma linha do tempo conjunta dos repositórios. "
                + ("Commits de merge são incluídos. " if parameters["incluir_merges"] else "Commits de merge são excluídos pelo número de pais. ")
                + "Duplicatas são removidas pelo SHA ou pela combinação de data e mensagem. Cada sessão é atribuída à semana em que começou; semanas sem atividade aparecem com zero."
            )
            sources = snapshot.get("fontes", [])
            if sources:
                for source in sources:
                    repo = source["repositorio"]
                    aliases = [name for name in source["nomes_consultados"] if name.casefold() != repo.casefold()]
                    suffix = f" · nome anterior: {', '.join(aliases)}" if aliases else ""
                    st.markdown(f"[{repo}](https://github.com/{repo}) · {source['commits_considerados']:,} commits considerados".replace(",", ".") + suffix)
                st.caption(f"{snapshot.get('commits_duplicados', 0):,} commits repetidos entre históricos foram desconsiderados.".replace(",", "."))
            else:
                st.caption("Repositórios: " + ", ".join(config["repositorios"]))
            interval = snapshot.get("faixa_estimativa_horas")
            if interval:
                st.caption(f"Sensibilidade do overhead: {format_hours(interval['min'])} sem overhead; {format_hours(interval['max'])} com {max(60, parameters['overhead_sessao_min'])} min por sessão. Essa faixa é um cenário de cálculo, sem interpretação de intervalo estatístico.")
            st.caption("O cálculo só é substituído após a consulta completa. Falhas de rede ou limites de API preservam o resultado e sua data. A atualização em execução é salva no cache local do servidor.")

    investment()


def render(api):
    st.markdown(ABOUT_CSS, unsafe_allow_html=True)
    with st.container(key="about_content"):
        st.markdown("## Sobre a plataforma")
        st.markdown("O **toma.conta** reúne dados oficiais do Banco Central para analisar instituições financeiras, o mercado de crédito e os meios de pagamento, com filtros reproduzíveis e exportações para relatórios.")
        cards = "".join(
            f'<a class="module-chip" href="?{urlencode({"menu": module.label})}" target="_self"><div class="module-top"><span class="module-title">{escape(module.label)}</span><span class="module-pill">{escape(module.category)}</span></div><div class="module-desc">{escape(module.description)}</div></a>'
            for module in MODULES
        )
        st.markdown(f'<div class="modules-panel"><div class="modules-header"><div class="modules-kicker">Módulos de análise</div><div class="modules-sub">Selecione um módulo para abrir a consulta</div></div><div class="module-grid">{cards}</div></div>', unsafe_allow_html=True)
        metric_cards = "".join(
            f'<div class="metrics-card"><div class="metrics-kicker">{escape(title)}</div><ul class="metrics-list">' + "".join(f"<li>{escape(item)}</li>" for item in items) + "</ul></div>"
            for title, items in METRIC_GROUPS
        )
        st.markdown(f'<div class="metrics-panel"><div class="metrics-title">Indicadores e métricas disponíveis</div><div class="metrics-grid">{metric_cards}</div></div>', unsafe_allow_html=True)
        st.caption("A disponibilidade varia por instituição, data-base, documento e perímetro. IFData é trimestral; SCR.data e séries de crédito SGS são mensais; COSIF, demonstrações e pagamentos seguem o calendário de cada documento. Consulte o Glossário e Fontes e leitura nas abas para escolher a base adequada.")
        ops_cards = "".join(f'<div class="ops-card"><div class="ops-title">{escape(title)}</div><div class="ops-desc">{escape(description)}</div></div>' for title, description in OPERATIONS)
        st.markdown(f'<div class="ops-panel"><div class="metrics-title">Recursos operacionais</div><div class="ops-grid">{ops_cards}</div></div>', unsafe_allow_html=True)
        render_investment(token=api["_obter_token_github"]()[0])
        st.markdown("---")
        steps = "".join(f'<li class="steps-item"><div class="steps-num">{index}</div><div class="steps-text"><strong>{escape(title)}</strong>. {escape(description)}</div></li>' for index, (title, description) in enumerate(STEPS, 1))
        st.markdown(f'<div class="steps-panel"><div class="metrics-title">Como utilizar</div><ul class="steps-list">{steps}</ul></div>', unsafe_allow_html=True)
        with st.expander("Stack tecnológica e fontes", expanded=False):
            rows = "".join(f"<tr><td><strong>{escape(component)}</strong></td><td>{escape(function)}</td></tr>" for component, function in STACK)
            st.markdown(f'<div class="stack-panel"><table><thead><tr><th>Componente</th><th>Função</th></tr></thead><tbody>{rows}</tbody></table></div>', unsafe_allow_html=True)
        st.caption("Desenvolvido por Matheus Prates, CFA | Ferramenta open-source para análise de instituições financeiras brasileiras")
