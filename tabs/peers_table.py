"""Nova aba Peers: comparação tabular, cálculo sob clique e exports sob demanda."""
from __future__ import annotations

from datetime import datetime
from html import escape
import hmac
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from utils import peers_groups
from utils.peers_table_model import BY_KEY, METRICS, DEFAULT_METRICS, INDIVIDUAL_METRICS, get_metric, BASELINES, SCALES, COLORS, build_query, required_periods, period_sort, period_label, short_bank, format_value, number, methodology_rows
from utils.peers_table_exports import export_excel, export_powerpoint, export_png


TABLE_CSS = """
.peers-grid {overflow:auto;max-height:640px; font-family:Calibri,Arial,sans-serif; color:#222; background:white;}
table {border-collapse:separate;border-spacing:0;width:100%;font-size:13px;}
th,td {border-right:1px solid #e2e2e2;border-bottom:1px solid #dedede;padding:7px 5px;text-align:right;white-space:nowrap;}
thead th {position:sticky;top:0;z-index:2;background:#f4f4f4;text-align:center;font-weight:600;}
thead tr:nth-child(2) th {top:var(--bank-header-height,32px);}
thead tr:first-child th {border-top:1px solid #d1d1d1;}
th.row-label,td.row-label {position:sticky;left:0;text-align:left;background:white;min-width:160px;max-width:205px;white-space:normal;z-index:1;}
thead th.row-label {background:#f4f4f4;z-index:3;}
.section td {background:#eceff1!important;font-weight:600;padding:5px 8px;border-right:0;text-align:left;}
.metric {font:inherit;color:inherit;background:transparent;border:0;text-align:left;padding:0;cursor:pointer;}
.metric:hover {text-decoration:underline;} .metric:focus-visible {outline:2px solid #174a7e;outline-offset:3px;}
.selected td:first-child {background:#edf3f8;}
.unit {font-size:11px;color:#666;min-width:45px;text-align:center;}
.value {font-variant-numeric:tabular-nums;display:block;min-width:54px;}
.delta {font-size:11px;display:block;color:#666;margin-top:2px;font-variant-numeric:tabular-nums;white-space:normal;}
.up {color:#16713b;} .down {color:#b32624;} .bank-start {border-left:1px solid #b8b8b8;}
@media(pointer:coarse) {.metric{min-height:38px;}}
"""
TABLE_JS = """
export default function(component) {
 const {data,parentElement,setStateValue} = component;
 const root=parentElement.querySelector('.peers-grid');
 root.innerHTML=data.html;
 root.style.setProperty('--bank-header-height',root.querySelector('thead tr:first-child').getBoundingClientRect().height+'px');
 root.querySelectorAll('button[data-metric]').forEach(button=>{
  button.onclick=()=>setStateValue('metric',button.dataset.metric===data.selected?null:button.dataset.metric);
 });
}
"""


@st.cache_resource(show_spinner=False)
def _component():
    return st.components.v2.component("peers_comparison_grid", html='<div class="peers-grid"></div>', css=TABLE_CSS, js=TABLE_JS)


def table_html(query, selected=None):
    cells = {(c["metric"], c["bank"], c["period"]): c for c in query["cells"]}
    count = len(query["periods"])
    html = ['<table aria-label="Comparação de peers"><thead><tr><th class="row-label" rowspan="2">Indicador</th><th rowspan="2">Unidade</th>']
    for bank in query["banks"]:
        html.append(f'<th class="bank-start" colspan="{count}" title="{escape(bank, quote=True)}">{escape(short_bank(bank))}</th>')
    html.append('</tr><tr>')
    for bank in query["banks"]:
        for i, p in enumerate(query["periods"]):
            html.append(f'<th class="{"bank-start" if i == 0 else ""}">{period_label(p)}</th>')
    html.append('</tr></thead><tbody>')
    section = None
    for key in query["metrics"]:
        metric = get_metric(key, query["base"])
        if metric.section != section:
            html.append(f'<tr class="section"><td colspan="{2+len(query["banks"])*count}">{escape(metric.section)}</td></tr>')
            section = metric.section
        html.append(f'<tr class="{"selected" if key == selected else ""}"><td class="row-label"><button type="button" class="metric" data-metric="{escape(key, quote=True)}" aria-label="Ver cálculo de {escape(metric.label, quote=True)}" aria-pressed="{str(key == selected).lower()}">{escape(metric.label)}</button></td><td class="unit">{escape(query["scale"] if metric.unit == "R$" else metric.unit)}</td>')
        for bank in query["banks"]:
            for i, p in enumerate(query["periods"]):
                cell = cells[key, bank, p]
                tooltip = f"{bank}; {period_label(p)}; {cell['source']}; {cell['status']}"
                if cell["reference"]:
                    tooltip += f"; base {period_label(cell['reference'])}: {format_value(cell['reference_value'], metric, query['scale'])}"
                if cell["reason"]:
                    tooltip += "; " + cell["reason"]
                html.append(f'<td class="{"bank-start" if i == 0 else ""}" title="{escape(tooltip, quote=True)}"><span class="value">{escape(cell["display"])}</span><span class="delta {cell["direction"] or ""}">{escape(cell["variation"])}</span></td>')
        html.append('</tr>')
    html.append('</tbody></table>')
    return ''.join(html)


@st.cache_data(ttl=60, show_spinner=False)
def _remote_groups():
    try:
        payload, sha = peers_groups.read_remote()
        return payload, sha, ""
    except Exception:
        return None, None, "Não foi possível consultar a revisão remota dos grupos."


@st.cache_data(show_spinner=False)
def _identities(path, token):
    """CodInst só é usado quando a identidade de um nome é inequívoca."""
    import pyarrow.parquet as pq
    if not Path(path).exists():
        return {}
    schema = pq.read_schema(path).names
    if not {"CodInst", "Instituição"}.issubset(schema):
        return {}
    df = pd.read_parquet(path, columns=["CodInst", "Instituição"]).dropna().drop_duplicates()
    result = {}
    for name, group in df.groupby("Instituição"):
        ids = group.CodInst.astype(str).str.strip().unique()
        if len(ids) == 1 and ids[0] and ids[0] != "None":
            result[str(name)] = ids[0]
    return result


def _load_context(api, individual):
    if not individual:
        if not api["_garantir_cache_telas_criticas"]("Peers (Tabela Nova)"):
            return {}, {}
        context = api["_get_peers_filters_context"](api["_cache_version_token"]("critical_screens"))
        manager = api["get_cache_manager"]()
        cache = manager.get_cache("principal")
        identities = _identities(str(cache.read_data_file), api["_cache_version_token"]("principal"))
    else:
        manifest = api["_carregar_manifest_release_cache"](f"{api['_PEERS_INDIVIDUAL_RELEASE_BASE_URL']}/manifest.json")
        quality = (manifest.get("quality_checks") or {}).get("principal_individual") or {}
        info = (manifest.get("caches") or {}).get("principal_individual") or {}
        context = api["_get_peers_individual_filters_context"](api["_cache_version_token"]("principal_individual"), api["_manifest_generated_token_cache"](manifest), int(quality.get("period_count") or 0), int(info.get("record_count") or 0))
        identities = {name: codes[0] for name, codes in context.get("nome_para_codinsts", {}).items() if len(codes) == 1}
    return context, identities


def calculation_rows(query, df, key, bank):
    """Mostra componentes existentes e o resultado exato da consulta, inclusive N/D."""
    metric = get_metric(key, query["base"])
    prefixes = {
        "Ativos Líquidos": "Trace::Ativos Líquidos::", "Carteira de Crédito*": "Trace::Carteira::",
        "Depósitos Totais": "Trace::Depósitos Totais::", "Core Funding*": "Trace::Core Funding::",
        "Custo de Crédito (%)": "Trace::Custo de Crédito::", "Custo de Crédito / Receita de Crédito (%)": "Trace::Custo de Crédito::",
    }
    if key.startswith("Perda Esperada"):
        prefixes[key] = "Trace::Perda Esperada::"
    source_columns = {"Core Funding*": "Captações" if query["base"] == "Individual" else "Core Funding", "Carteira de Crédito*": "Carteira de Crédito" if query["base"] == "Individual" else "Carteira de Crédito Bruta", "Lucro Líquido Acumulado": "Lucro Líquido Acumulado YTD", "Patrimônio Líquido (PL)": "Patrimônio Líquido", "ROE Acumulado YTD (%)": "ROE Ac. YTD an. (%)" if query["base"] == "Individual" else "ROE Ac. Anualizado (%)"}
    columns = [c for c in df if c.startswith(prefixes.get(key, "!"))]
    columns += [c for c in [None if key.startswith("Custo") else source_columns.get(key, key), "Carteira de Crédito Bruta" if "Custo" in key or "Carteira" in key else None, "Patrimônio Líquido" if "ROE" in key or "/ PL" in key else None] if c and c in df and c not in columns]
    from tabs.peers_config import PEERS_RATIO_COMPONENTS
    for col in PEERS_RATIO_COMPONENTS.get(key, ()):
        if col in df and col not in columns:
            columns.append(col)
    if "ROE" in key and "Lucro Líquido Acumulado YTD" in df and "Lucro Líquido Acumulado YTD" not in columns:
        columns.append("Lucro Líquido Acumulado YTD")
    result = []
    for p in query["periods"]:
        matches = df[(df["Instituição"].astype(str) == bank) & (df["Período"].astype(str) == p)]
        row = matches.iloc[0] if not matches.empty else {}
        for col in columns:
            value = row.get(col)
            if number(value) is not None:
                display = format_value(value, metric, query["scale"]) if col == source_columns.get(key, key) and metric.unit != "R$" else format_value(value, BY_KEY["Ativo Total"], query["scale"])
            else:
                display = "N/D" if value is None or pd.isna(value) else str(value)
            result.append({"Período": period_label(p), "Campo": col.removeprefix("Trace::"), "Valor": display, "Unidade": query["scale"] if col != source_columns.get(key, key) or metric.unit == "R$" else metric.unit})
        cell = next(c for c in query["cells"] if c["metric"] == key and c["bank"] == bank and c["period"] == p)
        if "ROE" in key and query["base"] != "Individual":
            year, quarter = period_sort(p)
            december = df[(df["Instituição"].astype(str) == bank) & (df["Período"].astype(str) == f"4/{year-1}")]
            pl = december.iloc[0].get("Patrimônio Líquido") if not december.empty else None
            result.append({"Período": period_label(p), "Campo": "PL de dezembro anterior", "Valor": format_value(pl, BY_KEY["Ativo Total"], query["scale"]), "Unidade": query["scale"]})
            result.append({"Período": period_label(p), "Campo": "Fator de anualização", "Valor": f"{4/quarter:.4g}", "Unidade": "x"})
        result.append({"Período": period_label(p), "Campo": "Resultado na tabela", "Valor": cell["display"], "Unidade": query["scale"] if metric.unit == "R$" else metric.unit})
        if cell["reason"]:
            result.append({"Período": period_label(p), "Campo": "Motivo de indisponibilidade", "Valor": cell["reason"], "Unidade": ""})
    return pd.DataFrame(result)


def _groups_editor(api, base, banks, identities, shared, shared_sha, remote_error):
    with st.expander("Grupos de peers", expanded=False):
        st.caption("Grupos compartilhados: arquivo versionado da aplicação. Grupos pessoais: sessão atual, com exportação e importação de JSON.")
        if st.session_state.get("peers_new_group_notice"):
            st.success(st.session_state["peers_new_group_notice"])
        if remote_error:
            st.caption(remote_error)
        name = st.text_input("Nome do grupo", key="peers_new_group_name")
        replace = st.checkbox("Substituir grupo existente", key="peers_new_replace")
        if st.button("Salvar grupo pessoal", key="peers_new_save_personal", disabled=not banks):
            try:
                st.session_state["peers_new_personal"] = peers_groups.upsert(st.session_state.get("peers_new_personal", {"schema_version": 2, "groups": []}), name, base, banks, identities, replace=replace)
                st.session_state["peers_new_group_notice"] = "Grupo salvo na sessão. Baixe o JSON para conservar uma cópia."
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
        personal = st.session_state.get("peers_new_personal", {"schema_version": 2, "groups": []})
        st.download_button("Baixar grupos pessoais", data=json.dumps(personal, ensure_ascii=False, indent=2), file_name="meus_peers.json", mime="application/json", key="peers_new_groups_download", on_click="ignore")
        uploaded = st.file_uploader("Importar grupos pessoais", type=["json"], key="peers_new_groups_upload")
        if uploaded is not None and st.button("Aplicar arquivo de grupos", key="peers_new_groups_apply"):
            try:
                st.session_state["peers_new_personal"] = peers_groups.validate(json.loads(uploaded.getvalue()))
                st.session_state["peers_new_group_notice"] = "Grupos importados na sessão."
                st.rerun()
            except (ValueError, UnicodeDecodeError) as exc:
                st.error(str(exc))
        try:
            admin_key = str(st.secrets.get("PEERS_GROUPS_ADMIN_KEY") or "")
        except Exception:
            admin_key = ""
        if admin_key:
            password = st.text_input("Chave de administração dos grupos", type="password", key="peers_new_admin_password")
            if st.button("Publicar grupo compartilhado no GitHub", key="peers_new_publish_group", disabled=not banks):
                if not hmac.compare_digest(password, admin_key):
                    st.error("Chave de administração inválida.")
                else:
                    token, _ = api["_obter_token_github"]()
                    try:
                        if not token:
                            raise ValueError("Publicação indisponível: credencial GitHub não configurada.")
                        # Obtém a revisão atual imediatamente antes da edição.
                        latest, sha = peers_groups.read_remote(token=token)
                        payload = peers_groups.upsert(latest or shared, name, base, banks, identities, replace=replace)
                        peers_groups.publish(payload, "abalroar/tomaconta", "main", token, sha)
                        _remote_groups.clear()
                        st.success("Grupo publicado e confirmado no GitHub.")
                    except Exception as exc:
                        st.error(str(exc))


def render(api):
    st.markdown("### Peers (Tabela Nova)")
    base = st.segmented_control("Base das demonstrações", ["Consolidada / Prudencial", "Individual"], default="Consolidada / Prudencial", key="peers_new_base") or "Consolidada / Prudencial"
    individual = base == "Individual"
    context, identities = _load_context(api, individual)
    available = list(context.get("bancos_todos", ()))
    available_periods = sorted(context.get("periodos_disponiveis", ()), key=period_sort, reverse=True)
    if not available or not available_periods:
        st.warning("A base selecionada não tem instituições e períodos disponíveis.")
        return
    remote, shared_sha, remote_error = _remote_groups()
    shared = remote or peers_groups.read_local(api["APP_DIR"])
    personal = st.session_state.get("peers_new_personal", {"schema_version": 2, "groups": []})
    groups = {g["name"] + " (compartilhado)": g for g in shared["groups"] if g["base"] == base}
    groups.update({g["name"] + " (pessoal)": g for g in personal["groups"] if g["base"] == base})
    group_col, banks_col = st.columns([1, 2])
    with group_col:
        selected_group = st.selectbox("Grupo de peers", ["Seleção manual", *groups], index=1 if groups else 0, key="peers_new_group_" + base)
    default = [b for b in ("ITAU - PRUDENCIAL", "BRADESCO - PRUDENCIAL", "SANTANDER - PRUDENCIAL") if b in available] or available[:1]
    bank_key = "peers_new_banks_" + base
    group_signature = (base, selected_group, tuple(m["id"] for m in groups.get(selected_group, {}).get("members", ())))
    missing = []
    if selected_group in groups:
        members, missing = peers_groups.resolve(groups[selected_group], identities)
        if st.session_state.get("peers_new_group_applied") != group_signature:
            st.session_state[bank_key] = members
    st.session_state["peers_new_group_applied"] = group_signature
    st.session_state[bank_key] = [b for b in st.session_state.get(bank_key, default) if b in available]
    with banks_col:
        banks = st.multiselect("Instituições", sorted(available), key=bank_key)
    if missing:
        st.warning("Integrantes indisponíveis: " + ", ".join(missing))
    if selected_group in groups and banks != members:
        st.caption("Grupo modificado na seleção atual.")
    pcol, dcol, ucol = st.columns([2, 2, 1])
    periods_key = "peers_new_periods_" + base
    st.session_state[periods_key] = [p for p in st.session_state.get(periods_key, available_periods[:3]) if p in available_periods]
    with pcol:
        periods = st.multiselect("Competências (até 3)", available_periods, key=periods_key, max_selections=3, format_func=period_label)
    with dcol:
        mode = st.selectbox("Variação em relação a", list(BASELINES), format_func=BASELINES.get, key="peers_new_baseline")
    with ucol:
        scale = st.selectbox("Valores monetários", list(SCALES), index=1, key="peers_new_scale")
    # A posição dos downloads permanece imediatamente abaixo dos filtros.
    export_container = st.container()
    with st.expander("Opções da tabela e dos gráficos", expanded=False):
        metrics = st.multiselect("Indicadores na tabela", list(BY_KEY), default=list(INDIVIDUAL_METRICS if individual else DEFAULT_METRICS), format_func=lambda k: get_metric(k, base).label, key="peers_new_metrics_" + base)
        chart_key = "peers_new_chart_metrics_" + base
        if chart_key in st.session_state:
            st.session_state[chart_key] = [k for k in st.session_state[chart_key] if k in metrics]
        chart_metrics = st.multiselect("Indicadores nos gráficos", metrics, default=[k for k in ("Custo de Crédito (%)", "ROE Acumulado YTD (%)") if k in metrics], format_func=lambda k: get_metric(k, base).label, key=chart_key)
        chart_type = st.selectbox("Tipo de gráfico", ["line", "column_stacked"], format_func=lambda x: "Linhas" if x == "line" else "Colunas", key="peers_new_chart_type")
        # Colunas de instituições são agrupadas, não empilhadas (ajuste no exporter).
        colors = {}
        cols = st.columns(min(3, max(1, len(banks))))
        for i, bank in enumerate(banks):
            with cols[i % len(cols)]:
                colors[bank] = st.color_picker(short_bank(bank), COLORS[i % len(COLORS)], key="peers_new_color_" + bank)
    if not banks or not periods or not metrics:
        st.info("Selecione instituições, competências e indicadores para montar a tabela.")
        _groups_editor(api, base, banks, identities, shared, shared_sha, remote_error)
        return
    metrics = [m.key for m in METRICS if m.key in metrics]
    periods = sorted(periods, key=period_sort)
    extended = required_periods(periods, mode)
    cache_name = "principal_individual" if individual else "critical_screens"
    cache_token = api["_cache_version_token"](cache_name)
    codes = tuple(identities[b] for b in banks if b in identities) if individual else ()
    df = api["_carregar_cache_relatorio_slice"](cache_name, cache_token, extended, tuple(sorted(banks)), tuple(sorted(codes)))
    if individual:
        df = api["_apply_peers_individual_display_names"](df, context.get("codinst_para_nome", {}))
    prepare = api["_preparar_metricas_extra_peers_individual_from_slice" if individual else "_preparar_metricas_extra_peers_from_slice"]
    extra = prepare(df, banks, extended)
    values, columns, _, _, _, _ = api["_montar_tabela_peers"](df, banks, list(extended), extra_values_precomputed=extra, allow_capital_fallback=not individual)
    statuses = api["_build_peers_status_lookup"](df_base=df, bancos=banks, periodos=periods, valores=values, colunas_usadas=columns)
    query = build_query(df, banks, periods, metrics, values, statuses, base=base, cache_token=cache_token, scale=scale, mode=mode, queried_at=datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y %H:%M %Z"))
    previous = st.session_state.get("peers_new_query")
    if previous and previous["signature"] == query["signature"]:
        query["queried_at"] = previous["queried_at"]
    st.session_state["peers_new_query"] = query
    with export_container:
        download_cols = st.columns(4)
        options = [("Excel", lambda: export_excel(query), "xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"), ("PowerPoint · tabela", lambda: export_powerpoint(query), "pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"), ("PowerPoint · gráficos", lambda: export_powerpoint(query, charts=True, chart_metrics=chart_metrics, colors=colors, chart_type=chart_type), "pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"), ("PNG", lambda: export_png(query), "png", "image/png")]
        for i, (label, make, ext, mime) in enumerate(options):
            with download_cols[i]:
                st.download_button(label, data=make, file_name=f"peers_{'graficos' if i == 2 else 'tabela'}_{query['signature'][:10]}.{ext}", mime=mime, key="peers_new_download_" + str(i), on_click="ignore", disabled=i == 2 and not chart_metrics, width="stretch")
    selected = st.session_state.get("peers_new_selected_metric")
    if selected not in metrics:
        selected = None
    result = _component()(data={"html": table_html(query, selected), "selected": selected}, default={"metric": None}, on_metric_change=lambda: None, key="peers_new_grid")
    clicked = getattr(result, "metric", None)
    if clicked in metrics:
        selected = clicked
    else:
        selected = None
    if st.session_state.get("peers_new_selected_metric") != selected:
        st.session_state["peers_new_selected_metric"] = selected
        st.rerun()
    st.caption(f"{len(banks)} instituições; {', '.join(period_label(p) for p in periods)}; {base}. Verde: aumento. Vermelho: queda. Direção da variação.")
    st.caption("Fonte: BCB IFData / Cadoc 4060 conforme indicador. Clique no indicador para abrir seu cálculo.")
    if selected:
        metric = get_metric(selected, query["base"])
        with st.expander("Cálculo: " + metric.label, expanded=True):
            st.write(metric.formula)
            if st.session_state.get("peers_new_calculation_bank") not in banks:
                st.session_state["peers_new_calculation_bank"] = banks[0]
            bank = st.selectbox("Instituição para memória de cálculo", banks, format_func=short_bank, key="peers_new_calculation_bank")
            memo = calculation_rows(query, df, selected, bank)
            st.dataframe(memo[memo["Campo"] == "Resultado na tabela"][["Período", "Valor", "Unidade"]], hide_index=True, width="stretch")
            with st.expander("Componentes e fonte", expanded=False):
                st.caption(metric.source + ". " + metric.note)
                st.dataframe(memo[memo["Campo"] != "Resultado na tabela"], hide_index=True, width="stretch")
    with st.expander("Metodologia e cobertura", expanded=False):
        st.dataframe(pd.DataFrame(methodology_rows(query)), hide_index=True, width="stretch")
        coverage = [{"Indicador": get_metric(key, base).label, "Competência": period_label(p), "Disponíveis": sum(c["value"] is not None for c in query["cells"] if c["metric"] == key and c["period"] == p), "Selecionadas": len(banks)} for key in metrics for p in periods]
        st.dataframe(pd.DataFrame(coverage), hide_index=True, width="stretch")
        st.caption(f"Consulta: {query['queried_at']}. Identificador: {query['signature'][:12]}. N/D preserva ausência de fonte, componente ou denominador.")
        st.download_button("Baixar consulta e rastreabilidade", json.dumps(query, ensure_ascii=False, indent=2), file_name="peers_consulta.json", mime="application/json", on_click="ignore", key="peers_new_query_download")
    _groups_editor(api, base, banks, identities, shared, shared_sha, remote_error)
