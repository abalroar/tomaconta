"""Garantias de Arranjo: uma linha por conglomerado, com a razão Garantia / Obrigações mês a mês."""
from __future__ import annotations

from html import escape
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import streamlit as st

from tabs.cockpit import CSS
from utils import arranjo_garantias as model
from utils.cosif_view import period_label
from utils.peers_table_model import short_bank

MENU = "Garantias de Arranjo"
ALL_WITH_COLLATERAL = "Todas com garantia registrada"
COLUMN_KEYS = (model.OBLIGATIONS, "garantia_total", model.RATIO, model.MEMO)


def columns(sources=model.DEFAULT_SOURCES):
    """A coluna da garantia leva o nome da rubrica escolhida."""
    return ((model.OBLIGATIONS, "Obrigações"), ("garantia_total", model.source_label(sources)),
            (model.RATIO, "Garantia / Obrigações"), (model.MEMO, "Garantias (controle)"))


def source_help(sources) -> str:
    """Texto do botão de informação: conta, origem e uso no cálculo."""
    chosen = [source for source in model.SOURCES if source.key in set(sources)]
    lines = [f"**{source.label}** · COSIF {source.code}, {source.account}. {source.reading}" for source in chosen]
    lines.append("**Origem:** balancete prudencial do BCB, documento 4060, mensal, saldo em reais na data-base.")
    numerator = " + ".join(source.code for source in chosen)
    lines.append(f"**Cálculo:** Garantia / Obrigações = ({numerator}) ÷ (4.4.1.60 + 4.9.9.01 + 4.9.9.03). "
                 "Sem razão quando as obrigações ficam abaixo de R$ 1 milhão.")
    lines.append(f"**Garantias (controle):** {model.MEMO_READING}")
    return "\n\n".join(lines)
SPARK_MONTHS = 12
CHART_DEFAULT = 5


def money(value) -> str:
    if value is None or pd.isna(value):
        return "N/D"
    scaled, unit = (value / 1e9, "bi") if abs(value) >= 1e9 else (value / 1e6, "mi")
    return f"R$ {scaled:,.1f} {unit}".replace(",", "_").replace(".", ",").replace("_", ".")


def percent(value) -> str:
    if value is None or pd.isna(value):
        return "N/D"
    return f"{value * 100:,.1f}%".replace(",", "_").replace(".", ",").replace("_", ".")


def _delta(column, now, before):
    """Variação em p.p. para a razão e em % para saldos; só a razão ganha cor."""
    if now is None or before is None or pd.isna(now) or pd.isna(before):
        return "–", ""
    if column == model.RATIO:
        change = (now - before) * 100
        if abs(change) < .05:
            return "estável", ""
        text = f"{abs(change):.1f}".replace(".", ",")
        return (f"↑ {text} p.p.", "favorable") if change > 0 else (f"↓ {text} p.p.", "attention")
    if not before:
        return "–", ""
    change = (now / before - 1) * 100
    if abs(change) < .05:
        return "estável", ""
    return f"{'↑' if change > 0 else '↓'} {abs(change):.1f}%".replace(".", ","), ""


def build_rows(series: pd.DataFrame, codes) -> list[dict]:
    """Cada conglomerado na última competência que publicou, contra o mês anterior e 12 meses antes."""
    rows = []
    for code in codes:
        own = series[series.COD_CONGL.eq(code)].set_index("DATA_BASE")
        if own.empty:
            continue
        period = own.index.max()
        current = own.loc[period]
        month = own.loc[model.shift_period(period, 1)] if model.shift_period(period, 1) in own.index else None
        year = own.loc[model.shift_period(period, 12)] if model.shift_period(period, 12) in own.index else None
        cells = {}
        for column in COLUMN_KEYS:
            show = percent if column == model.RATIO else money
            delta, tone = _delta(column, current[column], None if month is None else month[column])
            # Conta de controle zerada é ausência de registro, não garantia nula.
            shown = "–" if column == model.MEMO and not current[column] else show(current[column])
            cells[column] = {"raw": None if pd.isna(current[column]) else float(current[column]), "value": shown,
                             "delta": delta, "tone": tone, "annual": _delta(column, current[column], None if year is None else year[column])[0]}
        window = [model.shift_period(period, back) for back in range(SPARK_MONTHS - 1, -1, -1)]
        spark = [None if p not in own.index or pd.isna(own.loc[p, model.RATIO]) else float(own.loc[p, model.RATIO]) for p in window]
        rows.append({"code": code, "name": str(current.NOME_CONGL), "period": period, "cells": cells, "spark": spark})
    return rows


def sort_rows(rows, column, descending=True):
    """Valor ausente vai para o fim em qualquer direção."""
    known = [row for row in rows if row["cells"][column]["raw"] is not None]
    missing = [row for row in rows if row["cells"][column]["raw"] is None]
    return sorted(known, key=lambda row: row["cells"][column]["raw"], reverse=descending) + missing


def render_table(rows, latest, sparkline, highlight=None, sources=model.DEFAULT_SOURCES) -> str:
    mark = lambda column: ' class="sorted"' if column == highlight else ""
    head = "".join(f"<th{mark(column)}>{escape(label)}</th>" for column, label in columns(sources))
    html = [CSS, '<div class="tc-cockpit-wrap"><table class="tc-cockpit"><thead><tr><th>Instituição</th><th>Evolução · Garantia / Obrigações</th>', head, "</tr></thead><tbody>"]
    for row in rows:
        stale = f'<span class="date">{escape(period_label(row["period"]))}</span>' if row["period"] != latest else ""
        spark = sparkline(row["spark"], width=90, height=22) if sum(v is not None for v in row["spark"]) >= 2 else "–"
        cells = "".join(
            f'<td{mark(column)}><span class="val">{escape(row["cells"][column]["value"])}</span>'
            f'<span class="chg {row["cells"][column]["tone"]}" title="No mês; 12 meses: {escape(row["cells"][column]["annual"])}">{escape(row["cells"][column]["delta"])}</span></td>'
            for column in COLUMN_KEYS)
        html.append(f'<tr><td>{escape(short_bank(row["name"]))}{stale}</td><td>{spark}</td>{cells}</tr>')
    html.append("</tbody></table></div>")
    return "".join(html)


def detail_view(table: pd.DataFrame) -> pd.DataFrame:
    """R$ milhões com uma casa; a razão em percentual. Mês mais recente à esquerda."""
    view = table[sorted(table.columns, reverse=True)].copy().astype(object)
    for index in view.index:
        ratio = index == "Garantia / Obrigações"
        view.loc[index] = [percent(v) if ratio else ("N/D" if pd.isna(v) else f"{v / 1e6:,.1f}".replace(",", "_").replace(".", ",").replace("_", ".")) for v in table.loc[index, view.columns]]
    view.columns = [period_label(p) for p in view.columns]
    view.index.name = "R$ milhões"
    return view


def ratio_figure(series: pd.DataFrame, codes, names):
    import plotly.graph_objects as go
    fig = go.Figure()
    for code in codes:
        own = series[series.COD_CONGL.eq(code) & series[model.RATIO].notna()]
        fig.add_trace(go.Scatter(x=pd.to_datetime(own.DATA_BASE, format="%Y%m"), y=own[model.RATIO], mode="lines+markers",
                                 name=short_bank(names[code]), hovertemplate="%{x|%b/%y}: %{y:.1%}<extra>" + escape(short_bank(names[code])) + "</extra>"))
    fig.update_layout(height=340, margin=dict(l=8, r=8, t=8, b=8), yaxis=dict(tickformat=".0%", rangemode="tozero", title=None),
                      xaxis=dict(tickformat="%b/%y", title=None), legend=dict(orientation="h", y=-.18), hovermode="x unified",
                      font=dict(family="IBM Plex Sans, sans-serif", size=12), plot_bgcolor="#fff")
    fig.update_yaxes(gridcolor="#eef0f2")
    return fig


@st.cache_data(show_spinner=False, max_entries=2)
def _accounts(path: str, token: str) -> pd.DataFrame:
    # O token muda com o conteúdo do parquet: base atualizada, série recalculada.
    return model.load_accounts(SimpleNamespace(arquivo_dados=Path(path)))


def _portfolios(api) -> dict[str, list[str]]:
    """Carteiras salvas no Cockpit, por código oficial. Falha de leitura só esconde o atalho."""
    try:
        from tabs.cockpit import _read_portfolios, _store
        store = _store(api)
        payload = _read_portfolios(store, type(store).__name__)
        return {item["nome"]: [str(member["id"]) for member in item.get("membros", [])] for item in payload["carteiras"]}
    except Exception:
        return {}


def render(api):
    from utils.ui_help import render_module_help
    st.markdown(f"### {MENU}")
    render_module_help(MENU)
    cache = api["get_cache_manager"]().get_cache("bloprudencial")
    if cache is None or not cache.arquivo_dados.exists():
        st.info("Base prudencial indisponível. Consulte Atualizar Base.")
        return
    accounts = _accounts(str(cache.arquivo_dados), api["_cache_version_token"]("bloprudencial"))
    if accounts.empty:
        st.info("A base prudencial ainda não traz as contas de arranjo, publicadas a partir de jan/2025.")
        return
    top = st.columns([1.3, 3.2], vertical_alignment="top")
    portfolios = _portfolios(api)
    with top[0]:
        choice = st.selectbox("Recorte", [ALL_WITH_COLLATERAL, *portfolios], key="arranjo_recorte",
                              help="As carteiras são as salvas no Cockpit.")
        pick, info = st.columns([5, 1], vertical_alignment="bottom")
        chosen = pick.pills("Fonte da garantia", [source.key for source in model.SOURCES], selection_mode="multi",
                            default=list(model.DEFAULT_SOURCES), key="arranjo_fontes", format_func=lambda key: model.SOURCE_BY_KEY[key].short)
        sources = tuple(source.key for source in model.SOURCES if source.key in set(chosen or ())) or model.DEFAULT_SOURCES
        with info.popover("i", help="Conta COSIF, origem e uso no cálculo"):
            st.markdown(source_help(sources))
    source_name = model.source_label(sources)
    signature = "-".join(sources)
    labels = dict(columns(sources))
    series = model.build_series(accounts, sources=sources)
    latest = series.DATA_BASE.max()
    names = series.drop_duplicates("COD_CONGL", keep="last").set_index("COD_CONGL").NOME_CONGL.to_dict()
    relevant = series[series[model.OBLIGATIONS].gt(0) | series.garantia_total.gt(0) | series[model.MEMO].gt(0)].COD_CONGL.unique()
    options = sorted(relevant, key=lambda code: names[code])
    wanted = model.with_collateral(series, latest) if choice == ALL_WITH_COLLATERAL else portfolios[choice]
    default = [code for code in wanted if code in options]
    with top[1]:
        codes = st.multiselect("Instituições", options, default=default, key=f"arranjo_codes_{choice}_{signature}",
                               format_func=lambda code: short_bank(names[code]), placeholder="Busque e marque as instituições")
    if choice != ALL_WITH_COLLATERAL and len(default) < len(wanted):
        st.caption(f"{len(wanted) - len(default)} instituição(ões) da carteira sem contas de arranjo no balancete prudencial.")
    if not codes:
        st.info("Selecione ao menos uma instituição.")
        return
    order_col, direction_col, _ = st.columns([1.4, 1.2, 3], vertical_alignment="bottom")
    order = order_col.selectbox("Ordenar por", list(COLUMN_KEYS), key="arranjo_ordem", format_func=labels.get)
    direction = direction_col.segmented_control("Direção", ["Maior → menor", "Menor → maior"], default="Maior → menor",
                                                key="arranjo_direcao", label_visibility="collapsed") or "Maior → menor"
    rows = sort_rows(build_rows(series, codes), order, direction == "Maior → menor")
    behind = sum(row["period"] != latest for row in rows)
    st.markdown(f"**Data-base: {escape(period_label(latest))}** · comparada com {escape(period_label(model.shift_period(latest, 1)))} (mês)"
                + (f" · {behind} instituição(ões) com data anterior, indicada na linha" if behind else ""))
    st.markdown(f"Razão calculada com **{escape(source_name)}** ({' + '.join(model.SOURCE_BY_KEY[key].code for key in sources)}).")
    st.markdown(render_table(rows, latest, api["_snap_sparkline_svg"], order, sources), unsafe_allow_html=True)
    export = model.export_frame(accounts, series, [row["code"] for row in rows], sources)
    st.download_button("Exportar obrigações (Excel)", model.to_excel(export), file_name=f"obrigacoes_arranjo_{latest}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="arranjo_excel",
                       help="Uma linha por instituição da tabela, em R$ milhões, com as três contas de obrigação e as rubricas de garantia.")
    st.caption("Obrigações: 4.4.1.60 + 4.9.9.01 + 4.9.9.03. " + source_name + ": " + " + ".join(model.SOURCE_BY_KEY[key].code for key in sources)
               + ". Garantias (controle): 3.0.9.77, publicada desde fev/2026 e fora da razão. "
               "Balancete prudencial 4060, mensal, desde jan/2025. A razão não é calculada com obrigações abaixo de R$ 1 milhão. "
               "Evolução: últimos 12 meses. Passe o mouse na variação para ver os 12 meses. "
               "O balancete não identifica o beneficiário da garantia nem garantias prestadas por terceiros, como fianças.")

    st.markdown("#### Ao longo do tempo")
    with_ratio = [row["code"] for row in sort_rows(rows, model.OBLIGATIONS) if any(v is not None for v in row["spark"])]
    charted = st.multiselect("Instituições no gráfico", with_ratio, default=with_ratio[:CHART_DEFAULT], key=f"arranjo_grafico_{choice}_{signature}",
                             format_func=lambda code: short_bank(names[code]))
    if charted:
        st.plotly_chart(ratio_figure(series, charted, names), width="stretch", config={"displayModeBar": False})

    st.markdown("#### Memória de cálculo")
    code = st.selectbox("Instituição", [row["code"] for row in rows], key="arranjo_detalhe", format_func=lambda item: short_bank(names[item]))
    table = model.detail_table(accounts, series, code)
    st.dataframe(detail_view(table), width="stretch")
    history = (table / 1.0).rename(columns=period_label)
    st.download_button("Baixar CSV (R$)", history.to_csv(sep=";", decimal=",").encode("utf-8-sig"),
                       file_name=f"garantias_arranjo_{code}.csv", mime="text/csv", key="arranjo_csv")
