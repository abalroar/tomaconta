"""Cockpit: uma linha por banco da carteira, com as métricas do Snapshot e uma tendência explicável."""
from __future__ import annotations

from html import escape
import re

import streamlit as st

from utils import cockpit_store
from utils.peers_table_model import short_bank

BASE = "Consolidada / Prudencial"
COVERAGE_MIN = 3
TREND_LIMIT = 2
MATERIAL = {"bps": 25.0, "p.p.": 5.0, "%": 2.0}
TREND_LABELS = {"up": "Melhorando", "down": "Piorando", "flat": "Estável", "na": "Sem dados"}
TREND_ORDER = {"down": 0, "flat": 1, "up": 2, "na": 3}
# Só o que tem leitura de crédito entra na tendência; saldos ficam de fora, pois crescer não é melhorar.
TREND_LABELS_METRICS = ("CET1", "Índice de Basileia", "Patrimônio Líquido", "ROE Ac. Anualizado", "Inadimplência >90 dias", "Cobertura dos vencidos >90 dias")


def metric_configs():
    """Mesmas definições do Snapshot, para valores, unidades e cores coincidirem."""
    return (
        {"label": "Ativo Total", "short": "Ativo", "format_key": "Ativo Total", "higher_is_better": True, "column": "Ativo Total", "comparison_basis": "trimestral"},
        {"label": "Carteira de Crédito", "short": "Carteira", "format_key": "Carteira de Crédito Bruta", "higher_is_better": True, "column": "Carteira de Crédito Bruta", "comparison_basis": "trimestral"},
        {"label": "Patrimônio Líquido", "short": "PL", "format_key": "Patrimônio Líquido", "higher_is_better": True, "column": "Patrimônio Líquido", "comparison_basis": "trimestral"},
        {"label": "Lucro Líquido Acum. YTD", "short": "Lucro YTD", "format_key": "Lucro Líquido Acumulado YTD", "higher_is_better": True, "column": "Lucro Líquido Acumulado YTD", "comparison": "yoy", "comparison_basis": "ytd"},
        {"label": "ROE Ac. Anualizado", "short": "ROE", "format_key": "ROE Ac. Anualizado (%)", "higher_is_better": True, "column": "ROE Ac. Anualizado (%)", "is_pct": True, "comparison": "yoy", "comparison_basis": "ytd", "coluna_origem": "ROE Ac. Anualizado (%)"},
        {"label": "Índice de Basileia", "short": "Basileia", "format_key": "Índice de Basileia", "higher_is_better": True, "column": "Índice de Basileia Total (%)", "is_pct": True, "show_bps": True, "comparison_basis": "trimestral"},
        {"label": "CET1", "short": "CET1", "format_key": "Índice de Capital Principal", "higher_is_better": True, "column": "Índice de Capital Principal (CET1)", "is_pct": True, "show_bps": True, "comparison_basis": "trimestral"},
        {"label": "Inadimplência >90 dias", "short": "Over 90", "format_key": "Inadimplência / Carteira Total", "higher_is_better": False, "favorable_direction": "down", "risk": "npl90", "is_pct": True, "comparison_basis": "trimestral"},
        {"label": "Cobertura dos vencidos >90 dias", "short": "PDD / Over 90", "format_key": "PDD / Inadimplência (arrasto)", "higher_is_better": True, "favorable_direction": "up", "risk": "coverage90", "is_pct": True, "comparison_basis": "trimestral"},
    )


def is_material(text):
    """Movimento pequeno não vota: um desvio de 12 bps não pesa como um de 885 bps."""
    found = re.search(r"([\d.]+(?:,\d+)?)\s*(bps|p\.p\.|%)", str(text))
    if not found or "<" in str(text):
        return False
    amount = float(found.group(1).replace(".", "").replace(",", "."))
    return amount >= MATERIAL[found.group(2)]


def trend(comparisons):
    """Saldo de sinais em 12 meses: cada métrica de crédito vota pela cor que já mostra na tela.

    ``comparisons`` traz, por métrica, o tom e o texto da variação. Menos de três métricas comparáveis
    não formam tendência. A regra é fixa e o motivo aparece junto, sem interpretação.
    """
    votes = [(label, *comparisons[label]) for label in TREND_LABELS_METRICS if comparisons.get(label)]
    if len(votes) < COVERAGE_MIN:
        return {"state": "na", "reason": "Menos de três métricas de crédito comparáveis em 12 meses."}
    worse = [f"{label} {text}" for label, tone, text in votes if tone == "attention" and is_material(text)]
    better = [f"{label} {text}" for label, tone, text in votes if tone == "favorable" and is_material(text)]
    balance = len(better) - len(worse)
    state = "up" if balance >= TREND_LIMIT else "down" if balance <= -TREND_LIMIT else "flat"
    parts = [f"Contra: {'; '.join(worse)}" if worse else "", f"A favor: {'; '.join(better)}" if better else ""]
    return {"state": state, "reason": " · ".join(part for part in parts if part) or "Sem variação relevante.", "better": len(better), "worse": len(worse)}


def build_row(bank, frame, api, spark_label):
    """Valores e comparações de um banco, na última data que ele publicou."""
    from utils.snapshot_data import snapshot_risk_maps
    periods = api["ordenar_periodos"](frame["Período"].dropna().astype(str).unique().tolist(), reverso=True)
    if not periods:
        return None
    current = periods[0]
    previous = api["_periodo_trimestre_anterior"](current, periods)
    year_ago = api["_periodo_ano_anterior"](current)
    year_ago = next((p for p in periods if year_ago and api["_periodos_equivalentes"](p, year_ago)), None)
    window = periods[:8]
    risk = snapshot_risk_maps(frame, bank, window, BASE)
    cells, comparisons, spark = {}, {}, []
    for base_cfg in metric_configs():
        cfg = dict(base_cfg)
        if cfg.get("risk"):
            cfg["serie"] = risk[cfg["risk"]]
            cfg["quality_by_period"] = risk["status"][cfg["risk"]]
        else:
            cfg["serie"] = api["_critical_metric_map"](frame, bank, window, cfg["column"])
        quarter = api["_snapshot_card_delta"](cfg, current, previous, "QoQ") if cfg.get("comparison") != "yoy" else None
        annual = api["_snapshot_card_delta"](cfg, current, year_ago, "YoY")
        shown = quarter or annual
        cells[cfg["label"]] = {"value": api["_formatar_valor_snapshot"](cfg, cfg["serie"].get(current)), "delta": shown["display"],
                               "tone": shown["tone"], "reference": "QoQ" if quarter else "YoY", "annual": annual["display"]}
        if annual.get("valido"):
            comparisons[cfg["label"]] = (annual["tone"], annual["display"].lstrip("↑↓ "))
        if cfg["label"] == spark_label:
            spark = [cfg["serie"].get(p) for p in reversed(window)]
    return {"bank": bank, "period": current, "cells": cells, "trend": trend(comparisons), "spark": spark, "spark_kind": "bars" if spark_label.startswith("Lucro") else "line"}


CSS = """<style>
.tc-cockpit-wrap { overflow-x:auto; border:1px solid #e5e7eb; border-radius:10px; }
.tc-cockpit { width:100%; border-collapse:collapse; font-family:'IBM Plex Sans',sans-serif; font-size:.8rem; }
.tc-cockpit th { background:#f8f9fa; color:#555b63; font-weight:500; text-align:right; padding:8px 10px; border-bottom:1px solid #e5e7eb; white-space:nowrap; }
.tc-cockpit td { padding:8px 10px; border-bottom:1px solid #f0f1f3; text-align:right; white-space:nowrap; font-variant-numeric:tabular-nums; }
.tc-cockpit tr:last-child td { border-bottom:0; }
.tc-cockpit th:first-child, .tc-cockpit td:first-child { position:sticky; left:0; background:#fff; text-align:left; white-space:normal; min-width:150px; max-width:190px; font-weight:500; color:#212529; }
.tc-cockpit th:first-child { background:#f8f9fa; }
.tc-cockpit .val { display:block; color:#212529; font-weight:500; }
.tc-cockpit .chg { display:block; font-size:.7rem; color:#666; }
.tc-cockpit .favorable { color:#16713B; } .tc-cockpit .attention { color:#B32624; }
.tc-cockpit .date { display:block; font-size:.68rem; color:#8a9099; font-weight:400; }
.tc-cockpit .trend { display:inline-block; padding:2px 8px; border-radius:10px; font-size:.72rem; font-weight:500; background:#f3f4f5; color:#555b63; }
.tc-cockpit .trend-up { background:#e8f4ec; color:#16713B; } .tc-cockpit .trend-down { background:#fbeaea; color:#B32624; }
.tc-cockpit .why { display:block; font-size:.68rem; color:#777d85; white-space:normal; min-width:170px; max-width:260px; text-align:left; margin-top:3px; }
.tc-cockpit td.trend-cell, .tc-cockpit th.trend-cell { text-align:left; }
</style>"""


def render_table(rows, latest, api):
    metrics = metric_configs()
    head = "".join(f"<th>{escape(cfg['short'])}</th>" for cfg in metrics)
    html = [CSS, '<div class="tc-cockpit-wrap"><table class="tc-cockpit"><thead><tr><th>Instituição</th><th class="trend-cell">Tendência</th><th>Evolução</th>', head, "</tr></thead><tbody>"]
    sparks = {"bars": api["_snap_sparkbars_svg"], "line": api["_snap_sparkline_svg"]}
    for row in rows:
        stale = f'<span class="date">{escape(api["periodo_para_exibicao"](row["period"]))}</span>' if row["period"] != latest else ""
        info = row["trend"]
        spark = sparks[row["spark_kind"]](row["spark"], width=70, height=22) if any(v is not None for v in row["spark"]) else "–"
        cells = "".join(
            f'<td><span class="val">{escape(row["cells"][cfg["label"]]["value"])}</span>'
            f'<span class="chg {row["cells"][cfg["label"]]["tone"]}" title="{escape(row["cells"][cfg["label"]]["reference"])}; 12 meses: {escape(row["cells"][cfg["label"]]["annual"])}">{escape(row["cells"][cfg["label"]]["delta"])}</span></td>'
            for cfg in metrics)
        html.append(f'<tr><td>{escape(short_bank(row["bank"]))}{stale}</td>'
                    f'<td class="trend-cell"><span class="trend trend-{info["state"]}">{TREND_LABELS[info["state"]]}</span><span class="why">{escape(info["reason"])}</span></td>'
                    f'<td>{spark}</td>{cells}</tr>')
    html.append("</tbody></table></div>")
    return "".join(html)


def _store(api):
    token = api["_obter_token_github"]()[0]
    return cockpit_store.GitHubStore(token) if token else cockpit_store.LocalStore(api["APP_DIR"])


@st.cache_data(ttl=30, show_spinner=False)
def _read_portfolios(_store_object, kind):
    return _store_object.read()[0]


def render(api):
    st.markdown("### Cockpit")
    if not api["_garantir_cache_telas_criticas"]("Cockpit"):
        return
    token = api["_cache_version_token"]("critical_screens")
    context = api["_get_peers_filters_context"](token)
    from tabs.peers_table import _identities
    identities = _identities(str(api["get_cache_manager"]().get_cache("principal").read_data_file), api["_cache_version_token"]("principal"))
    available = [bank for bank in api["ordenar_bancos_com_alias"](list(context.get("bancos_todos", ())), st.session_state.get("dict_aliases", {})) if identities.get(bank)]
    store = _store(api)
    try:
        payload = _read_portfolios(store, type(store).__name__)
    except Exception as exc:
        st.error(f"Não foi possível ler as carteiras: {exc}")
        return
    names = [item["nome"] for item in payload["carteiras"]]
    left, right = st.columns([1, 3], vertical_alignment="top")
    with left:
        name = st.selectbox("Seu nome", names, index=None, placeholder="Escolha ou digite um nome", accept_new_options=True, key="cockpit_name")
    name = cockpit_store.clean_name(name)
    existing = cockpit_store.find(payload, name) if name else None
    saved, gone = cockpit_store.resolve(existing, identities) if existing else ([], [])
    state_key = f"cockpit_banks_{name.casefold()}"
    with right:
        banks = st.multiselect("Instituições da carteira", available, default=saved, key=state_key, disabled=not name,
                               placeholder="Busque e marque as instituições", format_func=short_bank)
    if not name:
        st.caption("Qualquer pessoa pode criar, ver e alterar uma carteira. O histórico de alterações fica guardado no GitHub, que é público.")
        return
    if gone:
        st.warning("Fora da base atual: " + ", ".join(gone))
    changed = sorted(banks) != sorted(saved) or not existing
    actions = st.columns([1, 1, 4])
    if actions[0].button("Salvar carteira", type="primary", disabled=not banks or not changed, key="cockpit_save"):
        try:
            cockpit_store.save(store, lambda current: cockpit_store.upsert(current, name, banks, identities), f"Carteira de {name}")
            _read_portfolios.clear()
            st.toast("Carteira salva.")
            st.rerun()
        except Exception as exc:
            st.error(f"Não foi possível salvar: {exc}")
    if existing:
        with actions[1].popover("Excluir"):
            st.caption("O histórico guarda a versão anterior.")
            if st.button(f"Excluir a carteira de {existing['nome']}", key="cockpit_delete"):
                try:
                    cockpit_store.save(store, lambda current: cockpit_store.remove(current, name), f"Exclui carteira de {name}")
                    _read_portfolios.clear()
                    st.session_state.pop(state_key, None)
                    st.rerun()
                except Exception as exc:
                    st.error(f"Não foi possível excluir: {exc}")
    if not banks:
        return
    spark_label = st.segmented_control("Evolução", [cfg["label"] for cfg in metric_configs()], default="ROE Ac. Anualizado", key="cockpit_spark",
                                       format_func={cfg["label"]: cfg["short"] for cfg in metric_configs()}.get) or "ROE Ac. Anualizado"
    frame = api["_carregar_cache_relatorio_slice"]("critical_screens", token, instituicoes=tuple(banks))
    rows = []
    for bank in banks:
        data = frame[frame["Instituição"].astype(str).eq(bank)] if frame is not None and not frame.empty else None
        row = build_row(bank, data, api, spark_label) if data is not None and not data.empty else None
        if row:
            rows.append(row)
    if not rows:
        st.info("Sem dados para as instituições selecionadas.")
        return
    rows.sort(key=lambda row: (TREND_ORDER[row["trend"]["state"]], -row["trend"].get("worse", 0)))
    latest = api["ordenar_periodos"]([row["period"] for row in rows], reverso=True)[0]
    st.markdown(render_table(rows, latest, api), unsafe_allow_html=True)
    st.caption("Variação do trimestre; no lucro e no ROE, contra os mesmos meses do ano anterior. Passe o mouse para ver os 12 meses. "
               "Tendência: saldo de sinais em 12 meses de CET1, Basileia, PL, ROE, Over 90 e cobertura. Só contam movimentos de ao menos 25 bps, 5 p.p. ou 2%. Saldo de dois ou mais define melhorando ou piorando. "
               "É uma regra de leitura, não uma avaliação de crédito.")
