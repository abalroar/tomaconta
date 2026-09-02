"""Página Streamlit do mercado de crédito agregado (SGS/BCB)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from utils.sgs_credit_analytics import (
    bar_line_figure,
    build_ipca_index,
    coverage_ratio,
    derive_credit_totals,
    line_figure,
    real_yoy,
    shares,
    stacked_figure,
    sum_columns,
    to_wide,
    yoy_pp,
)
from utils.sgs_credit_registry import SGS_SERIES


TITLE = "Estatísticas Crédito BC"
SUBTITLE = "Séries mensais agregadas do Sistema Gerenciador de Séries Temporais do Banco Central"
MAIN_SECTIONS = (
    "Concessões",
    "Crédito SFN",
    "Situação dos Agentes",
    "Inadimplência e Provisionamento",
    "Taxas de Juros e Spread",
    "Glossário",
)
CREDIT_SUBSECTIONS = (
    "Estoque de Crédito Total",
    "Por Tomador",
    "Por Produto",
    "Por Tipo de Empresa",
    "Por Controle",
)
NPL_SUBSECTIONS = ("Pré Inad e Inad", "Cobertura e Provisionamento", "Inadimplência SCR")

PLOTLY_CONFIG = {"displayModeBar": "hover", "displaylogo": False, "responsive": True}


def _available(wide: pd.DataFrame, aliases: Sequence[str]) -> bool:
    return bool(set(aliases).intersection(wide.columns))


def _chart(fig: go.Figure, key: str) -> None:
    title = fig.layout.title.text or "Gráfico"
    meta = fig.layout.meta if isinstance(fig.layout.meta, dict) else {}
    source_aliases = meta.get("source_aliases", [])
    title_column, info_column = st.columns([0.92, 0.08], vertical_alignment="center")
    with title_column:
        st.markdown(f"##### {title}")
    with info_column:
        with st.popover("i", help="Séries do BCB usadas neste gráfico"):
            st.markdown("**Séries BCB/SGS**")
            if source_aliases:
                for alias in source_aliases:
                    spec = SGS_SERIES[alias]
                    name = spec.official_name
                    if spec.metadata_url:
                        st.markdown(f"- **SGS {spec.code}**: [{name}]({spec.metadata_url})")
                    else:
                        st.markdown(f"- **{spec.label}**: {name}")
            else:
                st.caption("Indicador derivado das séries exibidas no card.")
    if not fig.data:
        st.info("Séries deste card ainda não estão disponíveis no cache.")
        return
    fig.update_layout(title=None, margin={**fig.layout.margin.to_plotly_json(), "t": 42})
    st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG, key=key)


def _period_filter(wide: pd.DataFrame) -> pd.DataFrame:
    if wide.empty:
        return wide
    periods = pd.DatetimeIndex(wide.index).dropna().sort_values().unique()
    latest = pd.Timestamp(periods[-1])
    target_start = latest - pd.DateOffset(years=10)
    default_start = int(periods.searchsorted(target_start, side="left"))
    start_column, end_column = st.columns(2)
    with start_column:
        start = st.selectbox(
            "Período inicial",
            list(periods),
            index=min(default_start, len(periods) - 1),
            format_func=lambda value: pd.Timestamp(value).strftime("%m/%Y"),
            key="sgs_credit_period_start",
        )
    end_options: list[str | pd.Timestamp] = ["Mais recente", *[pd.Timestamp(p) for p in periods if p >= start]]
    stored_end = st.session_state.get("sgs_credit_period_end")
    if stored_end != "Mais recente" and stored_end not in end_options:
        st.session_state["sgs_credit_period_end"] = "Mais recente"
    with end_column:
        end = st.selectbox(
            "Período final",
            end_options,
            index=0,
            format_func=lambda value: value if isinstance(value, str) else value.strftime("%m/%Y"),
            key="sgs_credit_period_end",
            help="Mais recente preserva a última observação disponível de cada série, mesmo quando as defasagens diferem.",
        )
    filtered = _filter_period_range(
        wide,
        pd.Timestamp(start),
        None if end == "Mais recente" else pd.Timestamp(end),
    )
    if end == "Mais recente":
        st.caption("Período final: última observação disponível de cada série.")
    return filtered


def _filter_period_range(
    wide: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp | None,
) -> pd.DataFrame:
    """Recorta a exibição e mantém a história completa para cálculos defasados."""
    mask = wide.index >= start
    if end is not None:
        mask &= wide.index <= end
    filtered = wide.loc[mask].copy()
    filtered.attrs["full_history"] = wide.attrs.get("full_history", wide)
    return filtered


def _real_growth_frame(wide: pd.DataFrame, aliases: Sequence[str]) -> pd.DataFrame:
    history = wide.attrs.get("full_history", wide)
    if "ipca_mensal" not in history.columns:
        return pd.DataFrame(index=wide.index)
    ipca_index = build_ipca_index(history["ipca_mensal"])
    result = pd.DataFrame(index=history.index)
    for alias in aliases:
        if alias in history.columns:
            result[alias] = real_yoy(history[alias], ipca_index)
        elif alias in wide.columns:
            result.loc[wide.index, alias] = real_yoy(wide[alias], ipca_index.reindex(wide.index))
    result.attrs["source_aliases"] = [
        *[alias for alias in aliases if alias in SGS_SERIES],
        "ipca_mensal",
    ]
    return result.reindex(wide.index)


def _yoy_pp_frame(wide: pd.DataFrame, aliases: Sequence[str]) -> pd.DataFrame:
    history = wide.attrs.get("full_history", wide)
    result = pd.DataFrame(index=history.index)
    for alias in aliases:
        if alias in history.columns:
            result[alias] = yoy_pp(history[alias])
    result.attrs["source_aliases"] = [alias for alias in aliases if alias in SGS_SERIES]
    return result.reindex(wide.index)


def _render_concessoes(wide: pd.DataFrame) -> None:
    st.markdown("#### Concessões")
    components = [
        "concessoes_sa_livre_pj",
        "concessoes_sa_direcionado_pj",
        "concessoes_sa_livre_pf",
        "concessoes_sa_direcionado_pf",
    ]
    total = sum_columns(wide, components)
    _chart(
        stacked_figure(
            wide,
            components,
            title="Desembolsos ajustados sazonalmente",
            y_title="R$ bi",
            scale=0.001,
            total=total,
        ),
        "sgs_concessoes_sa",
    )

    cards = [
        ("Concessões PJ — recursos livres", "concessoes_livre_pj", "prazo_livre_pj"),
        ("Concessões PJ — recursos direcionados", "concessoes_direcionado_pj", "prazo_direcionado_pj"),
        ("Consignado total", "concessoes_livre_pf_consignado", "prazo_livre_pf_consignado"),
        ("Crédito pessoal não consignado", "concessoes_livre_pf_nao_consignado", "prazo_livre_pf_nao_consignado"),
        ("Veículos", "concessoes_livre_pf_veiculos", "prazo_livre_pf_veiculos"),
        ("Cartão de crédito", "concessoes_livre_pf_cartao", "prazo_livre_pf_cartao_parcelado"),
        ("Crédito imobiliário", "concessoes_direcionado_pf_imobiliario", "prazo_direcionado_pf_imobiliario"),
    ]
    for row_start in range(0, len(cards), 2):
        columns = st.columns(2)
        for column, (title, volume, term) in zip(columns, cards[row_start : row_start + 2]):
            with column:
                _chart(
                    bar_line_figure(wide, bar_alias=volume, line_alias=term, title=title),
                    f"sgs_concessoes_{volume}",
                )


def _render_credit_stock(wide: pd.DataFrame) -> None:
    expanded = [
        "credito_ampliado_emprestimos",
        "credito_ampliado_titulos",
        "credito_ampliado_divida_externa",
    ]
    col1, col2 = st.columns(2)
    with col1:
        _chart(
            stacked_figure(
                wide,
                expanded,
                title="Composição do saldo de crédito ampliado",
                y_title="R$ bi",
                scale=0.001,
                total=wide.get("credito_ampliado_total"),
            ),
            "sgs_credito_ampliado",
        )
    components = ["saldo_livre_pj", "saldo_livre_pf", "saldo_direcionado_pj", "saldo_direcionado_pf"]
    with col2:
        _chart(
            stacked_figure(
                wide,
                components,
                title="Estoque de crédito total do SFN",
                y_title="R$ bi",
                scale=0.001,
                total=wide.get("saldo_sfn_total_derivado"),
            ),
            "sgs_credito_sfn",
        )
    growth = _real_growth_frame(wide, expanded + ["credito_ampliado_total"])
    growth_column, _ = st.columns(2)
    with growth_column:
        _chart(
            line_figure(
                growth,
                expanded + ["credito_ampliado_total"],
                title="Ritmo de evolução do estoque de crédito",
                y_title="Δ YoY real (%)",
                suffix="%",
            ),
            "sgs_credito_ampliado_real",
        )


def _render_credit_borrower(wide: pd.DataFrame) -> None:
    components = ["saldo_livre_pf", "saldo_direcionado_pf", "saldo_livre_pj", "saldo_direcionado_pj"]
    _chart(
        stacked_figure(
            wide,
            components,
            title="Evolução do saldo de crédito por tipo de tomador",
            y_title="R$ bi",
            scale=0.001,
            total=wide.get("saldo_sfn_total_derivado"),
        ),
        "sgs_tomador_saldo",
    )
    col1, col2 = st.columns(2)
    with col1:
        pf = _real_growth_frame(wide, ["saldo_livre_pf", "saldo_direcionado_pf", "saldo_pf_total"])
        _chart(
            line_figure(
                pf,
                ["saldo_livre_pf", "saldo_direcionado_pf", "saldo_pf_total"],
                title="Crescimento da carteira PF total",
                y_title="Δ YoY real (%)",
                suffix="%",
            ),
            "sgs_tomador_pf_growth",
        )
    with col2:
        pj = _real_growth_frame(wide, ["saldo_livre_pj", "saldo_direcionado_pj", "saldo_pj_total"])
        _chart(
            line_figure(
                pj,
                ["saldo_livre_pj", "saldo_direcionado_pj", "saldo_pj_total"],
                title="Crescimento da carteira PJ total",
                y_title="Δ YoY real (%)",
                suffix="%",
            ),
            "sgs_tomador_pj_growth",
        )
    participation = shares(wide, components, wide.get("saldo_sfn_total_derivado"))
    _chart(
        stacked_figure(
            participation,
            components,
            title="Participação do tipo de tomador",
            y_title="% do crédito total",
            total=pd.Series(100.0, index=participation.index),
            percent=True,
        ),
        "sgs_tomador_participacao",
    )
    st.caption("A versão em % do PIB permanece pendente da validação da série mensal de PIB usada no workbook original.")


def _mix_with_residual(
    wide: pd.DataFrame,
    aliases: Sequence[str],
    *,
    total_alias: str,
    residual_alias: str,
) -> pd.DataFrame:
    result = wide.copy()
    if total_alias in result.columns:
        named = sum_columns(result, aliases)
        result[residual_alias] = (result[total_alias] - named).where(lambda value: value >= 0)
    mixed = shares(result, [*aliases, residual_alias], result.get(total_alias))
    mixed.attrs["source_aliases"] = [*aliases, total_alias]
    return mixed


def _render_credit_product(wide: pd.DataFrame) -> None:
    pf_products = [
        "saldo_livre_pf_cheque",
        "saldo_livre_pf_pessoal_nao_consignado",
        "saldo_livre_pf_consignado",
        "saldo_livre_pf_veiculos",
        "saldo_livre_pf_cartao_total",
        "saldo_direcionado_pf_rural",
        "saldo_direcionado_pf_imobiliario",
        "saldo_direcionado_pf_bndes",
        "saldo_direcionado_pf_microcredito",
    ]
    pf_mix = _mix_with_residual(
        wide, pf_products, total_alias="saldo_pf_total", residual_alias="outros_pf_derivado"
    )
    pj_products = [
        "saldo_livre_pj_duplicatas",
        "saldo_livre_pj_capital_giro",
        "saldo_livre_pj_conta_garantida",
        "saldo_livre_pj_aquisicao_bens",
        "saldo_livre_pj_acc",
        "saldo_livre_pj_exportacao",
        "saldo_direcionado_pj_rural",
        "saldo_direcionado_pj_imobiliario",
        "saldo_direcionado_pj_bndes",
    ]
    pj_mix = _mix_with_residual(
        wide, pj_products, total_alias="saldo_pj_total", residual_alias="outros_pj_derivado"
    )
    labels = {"outros_pf_derivado": "Outros", "outros_pj_derivado": "Outros"}
    col1, col2 = st.columns(2)
    with col1:
        _chart(
            stacked_figure(
                pf_mix,
                [*pf_products, "outros_pf_derivado"],
                title="Mix da carteira PF",
                y_title="% da carteira PF",
                labels=labels,
                total=pd.Series(100.0, index=pf_mix.index),
                percent=True,
            ),
            "sgs_mix_pf",
        )
    with col2:
        _chart(
            stacked_figure(
                pj_mix,
                [*pj_products, "outros_pj_derivado"],
                title="Mix da carteira PJ",
                y_title="% da carteira PJ",
                labels=labels,
                total=pd.Series(100.0, index=pj_mix.index),
                percent=True,
            ),
            "sgs_mix_pj",
        )

    col1, col2 = st.columns(2)
    with col1:
        growth_pf = _real_growth_frame(wide, pf_products)
        _chart(
            line_figure(
                growth_pf,
                pf_products,
                title="Crescimento por produto PF",
                y_title="Δ YoY real (%)",
                suffix="%",
            ),
            "sgs_produto_pf_growth",
        )
    with col2:
        growth_pj = _real_growth_frame(wide, pj_products)
        _chart(
            line_figure(
                growth_pj,
                pj_products,
                title="Crescimento por produto PJ",
                y_title="Δ YoY real (%)",
                suffix="%",
            ),
            "sgs_produto_pj_growth",
        )

    card_aliases = [
        "saldo_livre_pf_cartao_rotativo",
        "saldo_livre_pf_cartao_parcelado",
        "saldo_livre_pf_cartao_vista",
    ]
    card_growth = _real_growth_frame(wide, card_aliases)
    _chart(
        line_figure(
            card_growth,
            card_aliases,
            title="Crescimento do estoque de cartão",
            y_title="Δ YoY real (%)",
            suffix="%",
        ),
        "sgs_cartao_growth",
    )

    history = wide.attrs.get("full_history", wide)
    directed = pd.DataFrame(index=history.index)
    for product, aliases in {
        "rural_total_derivado": ["saldo_direcionado_pf_rural", "saldo_direcionado_pj_rural"],
        "imobiliario_total_derivado": ["saldo_direcionado_pf_imobiliario", "saldo_direcionado_pj_imobiliario"],
        "bndes_total_derivado": ["saldo_direcionado_pf_bndes", "saldo_direcionado_pj_bndes"],
    }.items():
        directed[product] = sum_columns(history, aliases)
    if "ipca_mensal" in history:
        ipca_index = build_ipca_index(history["ipca_mensal"])
        directed_growth = directed.apply(lambda values: real_yoy(values, ipca_index)).reindex(wide.index)
        directed_growth.attrs["source_aliases"] = [
            "saldo_direcionado_pf_rural", "saldo_direcionado_pj_rural",
            "saldo_direcionado_pf_imobiliario", "saldo_direcionado_pj_imobiliario",
            "saldo_direcionado_pf_bndes", "saldo_direcionado_pj_bndes", "ipca_mensal",
        ]
    else:
        directed_growth = pd.DataFrame(index=wide.index)
    _chart(
        line_figure(
            directed_growth,
            list(directed.columns),
            title="Produtos direcionados PF + PJ",
            y_title="Δ YoY real (%)",
            labels={
                "rural_total_derivado": "Rural total",
                "imobiliario_total_derivado": "Imobiliário total",
                "bndes_total_derivado": "BNDES total",
            },
            suffix="%",
        ),
        "sgs_direcionados_growth",
    )


def _render_credit_company(wide: pd.DataFrame) -> None:
    aliases = ["saldo_pj_mpme", "saldo_pj_grande"]
    total = sum_columns(wide, aliases)
    col1, col2 = st.columns(2)
    with col1:
        _chart(
            stacked_figure(
                wide,
                aliases,
                title="Saldo da carteira PJ por tipo de empresa",
                y_title="R$ bi",
                scale=0.001,
                total=total,
            ),
            "sgs_empresa_saldo",
        )
    with col2:
        participation = shares(wide, aliases, total)
        _chart(
            stacked_figure(
                participation,
                aliases,
                title="Participação por tipo de empresa",
                y_title="% do crédito PJ",
                total=pd.Series(100.0, index=participation.index),
                percent=True,
            ),
            "sgs_empresa_share",
        )
    growth_source = wide.attrs.get("full_history", wide).copy()
    growth_source["saldo_pj_porte_total_derivado"] = sum_columns(growth_source, aliases)
    growth = _real_growth_frame(
        growth_source, ["saldo_pj_mpme", "saldo_pj_grande", "saldo_pj_porte_total_derivado"]
    ).reindex(wide.index)
    _chart(
        line_figure(
            growth,
            ["saldo_pj_mpme", "saldo_pj_grande", "saldo_pj_porte_total_derivado"],
            title="Ritmo de crescimento por tipo de empresa",
            y_title="Δ YoY real (%)",
            labels={"saldo_pj_porte_total_derivado": "PJ total"},
            suffix="%",
        ),
        "sgs_empresa_growth",
    )
    st.caption("MPMe: receita bruta até R$ 300 milhões ou ativos totais até R$ 240 milhões, conforme o glossário histórico.")


def _render_credit_control(wide: pd.DataFrame) -> None:
    aliases = ["saldo_controle_publico", "saldo_controle_privado_nacional", "saldo_controle_estrangeiro"]
    total = sum_columns(wide, aliases)
    participation = shares(wide, aliases, total)
    col1, col2 = st.columns(2)
    with col1:
        _chart(
            stacked_figure(
                participation,
                aliases,
                title="Mix do saldo de crédito SFN por controle",
                y_title="% do crédito total",
                total=pd.Series(100.0, index=participation.index),
                percent=True,
            ),
            "sgs_controle_share",
        )
    with col2:
        source = wide.attrs.get("full_history", wide).copy()
        source["saldo_controle_total_derivado"] = sum_columns(source, aliases)
        growth = _real_growth_frame(
            source, [*aliases, "saldo_controle_total_derivado"]
        ).reindex(wide.index)
        _chart(
            line_figure(
                growth,
                [*aliases, "saldo_controle_total_derivado"],
                title="Ritmo de crescimento por controle",
                y_title="Δ YoY real (%)",
                labels={"saldo_controle_total_derivado": "Total SFN"},
                suffix="%",
            ),
            "sgs_controle_growth",
        )


def _render_credit(wide: pd.DataFrame) -> None:
    selected = st.segmented_control(
        "Visão do crédito",
        CREDIT_SUBSECTIONS,
        default=CREDIT_SUBSECTIONS[0],
        key="sgs_credit_subsection",
    )
    if selected == "Por Tomador":
        _render_credit_borrower(wide)
    elif selected == "Por Produto":
        _render_credit_product(wide)
    elif selected == "Por Tipo de Empresa":
        _render_credit_company(wide)
    elif selected == "Por Controle":
        _render_credit_control(wide)
    else:
        _render_credit_stock(wide)


def _render_situation(wide: pd.DataFrame) -> None:
    commitment = wide.copy()
    if {"comprometimento_juros", "comprometimento_amortizacao"}.issubset(commitment.columns):
        commitment["comprometimento_total_derivado"] = sum_columns(
            commitment, ["comprometimento_juros", "comprometimento_amortizacao"]
        )
    commitment_column, employment_column = st.columns(2)
    with commitment_column:
        _chart(
            line_figure(
                commitment,
                [
                    "comprometimento_amortizacao",
                    "comprometimento_juros",
                    "comprometimento_total_derivado",
                    "comprometimento_servico_ex_habitacional",
                    "endividamento_renda",
                ],
                title="Comprometimento de renda das famílias",
                y_title="% da renda",
                labels={"comprometimento_total_derivado": "Comprometimento total"},
                suffix="%",
            ),
            "sgs_comprometimento",
        )
    employment = wide[[column for column in ["desocupacao"] if column in wide.columns]].copy()
    employment_change = _yoy_pp_frame(wide, ["desocupacao"])
    if "desocupacao" in employment_change:
        employment["retomada_emprego_derivada"] = employment_change["desocupacao"]
    employment.attrs["source_aliases"] = ["desocupacao"]
    with employment_column:
        _chart(
            line_figure(
                employment,
                ["desocupacao", "retomada_emprego_derivada"],
                title="Taxa de desocupação e velocidade de retomada do emprego",
                y_title="% / variação YoY em p.p.",
                labels={"retomada_emprego_derivada": "Variação YoY da desocupação"},
            ),
            "sgs_emprego",
        )


def _render_npl(wide: pd.DataFrame, get_cache_manager=None) -> None:
    selected = st.segmented_control(
        "Visão de inadimplência",
        NPL_SUBSECTIONS,
        default=NPL_SUBSECTIONS[0],
        key="sgs_npl_subsection",
    )
    if selected == "Inadimplência SCR":
        if get_cache_manager is None:
            st.error("Gerenciador do cache SCR.data indisponível.")
            return
        from tabs.scr_inadimplencia_view import render_scr_inadimplencia

        render_scr_inadimplencia(get_cache_manager)
        return
    wide = _period_filter(wide)
    if selected == "Cobertura e Provisionamento":
        provision = ["provisao_sfn", "provisao_publico", "provisao_privado_nacional", "provisao_estrangeiro"]
        provision_column, coverage_column = st.columns(2)
        with provision_column:
            _chart(
                line_figure(
                    wide,
                    provision,
                    title="Nível de provisão",
                    y_title="% da carteira total",
                    suffix="%",
                ),
                "sgs_provisao",
            )
        coverage = pd.DataFrame(index=wide.index)
        pairs = {
            "cobertura_sfn_derivada": ("provisao_sfn", "inad_total"),
            "cobertura_publico_derivada": ("provisao_publico", "inad_publico"),
            "cobertura_privado_nacional_derivada": ("provisao_privado_nacional", "inad_privado_nacional"),
            "cobertura_estrangeiro_derivada": ("provisao_estrangeiro", "inad_estrangeiro"),
        }
        for alias, (provision_alias, npl_alias) in pairs.items():
            if {provision_alias, npl_alias}.issubset(wide.columns):
                coverage[alias] = coverage_ratio(wide[provision_alias], wide[npl_alias])
        coverage.attrs["source_aliases"] = [item for pair in pairs.values() for item in pair]
        with coverage_column:
            _chart(
                line_figure(
                    coverage,
                    list(pairs),
                    title="Nível de cobertura (>90 dias)",
                    y_title="% da carteira inadimplente",
                    labels={
                        "cobertura_sfn_derivada": "SFN",
                        "cobertura_publico_derivada": "Público",
                        "cobertura_privado_nacional_derivada": "Privado nacional",
                        "cobertura_estrangeiro_derivada": "Estrangeiro",
                    },
                    suffix="%",
                ),
                "sgs_cobertura",
            )
        return

    aggregate = ["pre_inad_livre_pf", "inad_livre_pf", "pre_inad_livre_pj", "inad_livre_pj", "pre_inad_livre_total", "inad_livre_total"]
    aggregate_column, _ = st.columns(2)
    with aggregate_column:
        _chart(
            line_figure(
                wide,
                aggregate,
                title="Pré-inadimplência (15–90d) e inadimplência (>90d) — recursos livres",
                y_title="% da carteira",
                suffix="%",
            ),
            "sgs_npl_aggregate",
        )
    pf_pre = [
        "pre_inad_livre_pf_nao_consignado", "pre_inad_livre_pf_cheque",
        "pre_inad_livre_pf_cartao_total", "pre_inad_livre_pf_cartao_rotativo",
        "pre_inad_livre_pf_cartao_parcelado", "pre_inad_livre_pf_veiculos",
        "pre_inad_livre_pf_consignado", "pre_inad_direcionado_pf_imobiliario",
    ]
    pf_npl = [
        "inad_livre_pf_nao_consignado", "inad_livre_pf_cheque", "inad_livre_pf_cartao_total",
        "inad_livre_pf_cartao_rotativo", "inad_livre_pf_cartao_parcelado", "inad_livre_pf_veiculos",
        "inad_livre_pf_consignado", "inad_direcionado_pf_imobiliario",
    ]
    pj_pre = ["pre_inad_livre_pj_conta_garantida", "pre_inad_livre_pj_capital_giro", "pre_inad_livre_pj_duplicatas"]
    pj_npl = ["inad_livre_pj_conta_garantida", "inad_livre_pj_capital_giro", "inad_livre_pj_duplicatas"]
    for row_start, (title_left, left, title_right, right) in enumerate(
        [
            ("Produtos PF — pré-inadimplência", pf_pre, "Produtos PF — inadimplência", pf_npl),
            ("Produtos PJ — pré-inadimplência", pj_pre, "Produtos PJ — inadimplência", pj_npl),
        ]
    ):
        col1, col2 = st.columns(2)
        with col1:
            _chart(line_figure(wide, left, title=title_left, y_title="% da carteira", suffix="%"), f"sgs_npl_left_{row_start}")
        with col2:
            _chart(line_figure(wide, right, title=title_right, y_title="% da carteira", suffix="%"), f"sgs_npl_right_{row_start}")


def _render_rates(wide: pd.DataFrame) -> None:
    cards = [
        (
            "Taxa média PF",
            ["taxa_pf_consignado", "taxa_pf_veiculos", "taxa_pf_imobiliario", "taxa_pf_cheque", "taxa_pf_nao_consignado", "taxa_pf_cartao_total"],
        ),
        ("Cartão", ["taxa_pf_cartao_total", "taxa_pf_cartao_rotativo", "taxa_pf_cartao_parcelado"]),
        ("Taxa média PJ", ["taxa_pj_conta_garantida", "taxa_pj_duplicatas", "taxa_pj_capital_giro"]),
        ("Taxa e spread agregados", ["taxa_pf_livre", "spread_pf_livre", "taxa_pj_livre", "spread_pj_livre", "cdi_aa"]),
    ]
    for row_start in range(0, len(cards), 2):
        cols = st.columns(2)
        for col, (title, aliases) in zip(cols, cards[row_start : row_start + 2]):
            with col:
                _chart(
                    line_figure(wide, aliases, title=title, y_title="% a.a. / p.p.", suffix="%"),
                    f"sgs_rates_{row_start}_{title}",
                )
    aliases = ["taxa_pf_livre", "spread_pf_livre", "taxa_pj_livre", "spread_pj_livre"]
    changes = _yoy_pp_frame(wide, aliases)
    _chart(
        line_figure(
            changes,
            aliases,
            title="Ritmo de crescimento da taxa média e do spread médio",
            y_title="variação YoY (p.p.)",
        ),
        "sgs_rates_yoy_pp",
    )


def _render_glossary() -> None:
    st.markdown("#### Glossário e metodologia")
    rows = [
        ("Crescimento real em 12 meses", "(Xₜ / índice IPCAₜ) ÷ (Xₜ₋₁₂ / índice IPCAₜ₋₁₂) − 1", "%"),
        ("Variação de taxa/spread", "xₜ − xₜ₋₁₂", "p.p."),
        ("Participação", "componente ÷ total", "%"),
        ("Cobertura", "provisão / carteira ÷ inadimplência / carteira", "%"),
        ("Pré-inadimplência", "Operações com atraso entre 15 e 90 dias", "% da carteira"),
        ("Inadimplência", "Operações com atraso superior a 90 dias", "% da carteira"),
        ("Comprometimento total", "amortização do principal + juros", "% da renda"),
        ("Outros — mix PF/PJ", "resíduo entre o total e os produtos explicitamente classificados", "% da carteira"),
    ]
    st.dataframe(
        pd.DataFrame(rows, columns=["Indicador", "Definição / fórmula", "Unidade"]),
        hide_index=True,
        width="stretch",
    )


def _render_source_footer(frame: pd.DataFrame, metadata: Mapping | None) -> None:
    latest = pd.to_datetime(frame["data"], errors="coerce").max()
    latest_label = latest.strftime("%m/%Y") if pd.notna(latest) else "N/D"
    source = (metadata or {}).get("fonte") or "BCData/SGS"
    st.caption(
        f"Fonte: Banco Central do Brasil — BCData/SGS · última observação disponível no cache: {latest_label} · origem do cache: {source}."
    )


def render_mercado_credito(cache, *, get_cache_manager=None) -> None:
    st.markdown(f"### {TITLE}")
    st.caption(SUBTITLE)
    if cache is None:
        st.error("Cache `mercado_credito_sgs` não registrado.")
        return
    result = cache.carregar()
    if not result.sucesso or result.dados is None or result.dados.empty:
        st.warning("O cache SGS ainda não foi materializado ou publicado.")
        st.code(
            ".venv/bin/python tools/update_caches_cli.py --tipo mercado_credito_sgs --modo overwrite",
            language="bash",
        )
        if result.mensagem:
            st.caption(result.mensagem)
        return

    full_wide = derive_credit_totals(to_wide(result.dados))
    selected = st.segmented_control(
        "Área",
        MAIN_SECTIONS,
        default=MAIN_SECTIONS[0],
        key="sgs_credit_main_section",
    )
    if selected == "Crédito SFN":
        _render_credit(_period_filter(full_wide))
    elif selected == "Situação dos Agentes":
        _render_situation(_period_filter(full_wide))
    elif selected == "Inadimplência e Provisionamento":
        _render_npl(full_wide, get_cache_manager)
    elif selected == "Taxas de Juros e Spread":
        _render_rates(_period_filter(full_wide))
    elif selected == "Glossário":
        _render_glossary()
    else:
        _render_concessoes(_period_filter(full_wide))

    _render_source_footer(result.dados, result.metadata)
