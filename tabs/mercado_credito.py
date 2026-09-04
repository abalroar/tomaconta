"""Página Streamlit do mercado de crédito agregado (SGS/BCB).

A largura do card acompanha o que ele desenha. Barra empilhada ocupa a linha
inteira, porque a fatia precisa de altura para caber o rótulo. Gráfico de
linhas próximas — inadimplência, taxas, situação das famílias — vai a dois por
linha: esticado pela tela toda, o gráfico perde sensibilidade vertical e as
séries se colam. O nome de cada série continua na ponta da linha nos dois casos.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextvars import ContextVar

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from utils.sgs_credit_analytics import (
    TAMANHO_ROTULO_BARRA_PX,
    _valid_trace_dates,
    bar_line_figure,
    build_ipca_index,
    coverage_ratio,
    derive_credit_totals,
    formatar_competencia,
    line_figure,
    real_yoy,
    shares,
    stacked_figure,
    sum_columns,
    to_wide,
    yoy_pp,
)
from tabs.comentario_credito import render_comentario
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
NPL_SUBSECTIONS = (
    "Pré Inad e Inad",
    "Cobertura e Provisionamento",
    "Inad por Faixa de Renda",
)

PLOTLY_CONFIG = {"displayModeBar": "hover", "displaylogo": False, "responsive": True}
_EXPORT_FIGURES: ContextVar[list[go.Figure] | None] = ContextVar(
    "sgs_credit_export_figures", default=None
)
# Em modo silencioso as funções de render montam as figuras e não desenham
# nada. É como o deck completo reúne as cinco abas de Crédito SFN sem que o
# usuário precise abrir uma por uma.
_SILENCIOSO: ContextVar[bool] = ContextVar("sgs_credit_silencioso", default=False)

# Ordem das abas no deck completo: a mesma da tela, área por área e submenu
# por submenu. A chave é a do comentário em data/comentarios_credito_bc.json.
SECOES_DECK = (
    ("Concessões", "concessoes", "_render_concessoes"),
    ("Crédito SFN · Estoque de Crédito Total", "credito_estoque", "_render_credit_stock"),
    ("Crédito SFN · Por Tomador", "credito_tomador", "_render_credit_borrower"),
    ("Crédito SFN · Por Produto", "credito_produto", "_render_credit_product"),
    ("Crédito SFN · Por Tipo de Empresa", "credito_empresa", "_render_credit_company"),
    ("Crédito SFN · Por Controle", "credito_controle", "_render_credit_control"),
    ("Situação dos Agentes", "situacao", "_render_situation"),
    ("Inadimplência · Pré-inadimplência e inadimplência", "npl_pre_inad", "_render_npl_pre"),
    ("Inadimplência · Cobertura e provisionamento", "npl_cobertura", "_render_npl_cobertura"),
    ("Inadimplência · Inadimplência por faixa de renda", "npl_faixa_renda", None),
    ("Taxas de Juros e Spread", "taxas", "_render_rates"),
)
SECOES_CREDITO_DECK = tuple(
    (titulo.split(" · ")[-1], chave)
    for titulo, chave, _ in SECOES_DECK
    if titulo.startswith("Crédito SFN")
)


def _available(wide: pd.DataFrame, aliases: Sequence[str]) -> bool:
    return bool(set(aliases).intersection(wide.columns))


def _competencia_do_card(fig: go.Figure) -> pd.Timestamp | None:
    """Última competência com dado efetivamente desenhado neste card."""
    datas = _valid_trace_dates(fig)
    return max(datas) if datas else None


def _chart(fig: go.Figure, key: str) -> None:
    if _SILENCIOSO.get():
        colecionador = _EXPORT_FIGURES.get()
        if colecionador is not None and fig.data:
            colecionador.append(fig)
        return
    meta = fig.layout.meta if isinstance(fig.layout.meta, dict) else {}
    raw_title = meta.get("chart_title") or getattr(fig.layout.title, "text", None)
    title = (
        raw_title.strip()
        if isinstance(raw_title, str)
        and raw_title.strip()
        and raw_title.strip().lower() != "undefined"
        else "Gráfico"
    )
    source_aliases = meta.get("source_aliases", [])
    title_column, info_column = st.columns([0.96, 0.04], vertical_alignment="center")
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
    collector = _EXPORT_FIGURES.get()
    if collector is not None:
        collector.append(fig)
    # O tema Plotly do app converte ``title=None`` no texto literal
    # ``undefined``. Uma string vazia remove o título interno com segurança;
    # o título visível do card permanece no cabeçalho acima do gráfico.
    fig.update_layout(title_text="")
    st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG, key=key)
    # A competência real deste card, e não a do seletor: séries diferentes
    # fecham em meses diferentes e dois cards vizinhos podiam terminar em
    # jun/26 e jul/26 sem nada dizer isso.
    competencia = _competencia_do_card(fig)
    if competencia is not None:
        st.caption(f"dados até {formatar_competencia(competencia)}")


def _leitura(
    chave: str, wide: pd.DataFrame, aliases: Sequence[str] | None = None
) -> None:
    """Card de leitura dos dados, com a competência do cache para conferência.

    ``aliases`` restringe a competência às séries que a página desenha. Sem
    isso, uma página cujas séries fecham antes do resto do cache — como
    comprometimento de renda — seria marcada como desatualizada sem estar.
    """
    if _SILENCIOSO.get():
        return
    quadro = wide
    if aliases:
        colunas = [alias for alias in aliases if alias in wide.columns]
        if colunas:
            quadro = wide[colunas].dropna(how="all")
    datas = pd.DatetimeIndex(quadro.index).dropna()
    base = datas.max().strftime("%Y-%m") if len(datas) else None
    render_comentario(chave, data_base_cache=base)


def _cards_em_grade(cards: Sequence[tuple[go.Figure, str]], colunas: int = 2) -> None:
    """Distribui cards em linhas de ``colunas``.

    Largura total é boa para barra empilhada, onde a fatia precisa de altura,
    e ruim para linhas próximas: esticado pela tela inteira, o gráfico perde
    sensibilidade vertical e as séries se colam. Os cards de inadimplência
    voltam a dois por linha, mantendo o nome de cada série na ponta da linha.
    """
    if _SILENCIOSO.get():
        for figura, chave in cards:
            _chart(figura, chave)
        return
    for inicio in range(0, len(cards), colunas):
        faixa = cards[inicio:inicio + colunas]
        grade = st.columns(colunas)
        for coluna, (figura, chave) in zip(grade, faixa):
            with coluna:
                _chart(figura, chave)


def _competencias_por_fonte(wide: pd.DataFrame) -> dict[str, pd.Timestamp]:
    """Última competência de cada bloco de séries do cache SGS."""
    resultado: dict[str, pd.Timestamp] = {}
    for rotulo, colunas in {
        "crédito, taxas e inadimplência": [
            c for c in wide.columns
            if c.startswith(("saldo_", "concessoes_", "taxa_", "spread_", "inad_", "pre_inad_", "provisao_"))
        ],
        "endividamento das famílias": [
            c for c in wide.columns
            if c.startswith(("comprometimento_", "endividamento_"))
        ],
    }.items():
        if not colunas:
            continue
        validos = wide[colunas].dropna(how="all")
        if not validos.empty:
            resultado[rotulo] = pd.Timestamp(validos.index[-1])
    return resultado


def _period_filter(wide: pd.DataFrame) -> pd.DataFrame:
    if wide.empty:
        return wide
    # CDI e Selic podem trazer o mês corrente antes das séries de crédito. A
    # janela acompanha a última competência fechada das séries analíticas.
    analytical_columns = [
        column for column in wide.columns if column not in {"cdi_aa", "selic_aa"}
    ]
    analytical = wide[analytical_columns].dropna(how="all") if analytical_columns else wide
    periods = pd.DatetimeIndex(analytical.index).dropna().sort_values().unique()
    if periods.empty:
        periods = pd.DatetimeIndex(wide.index).dropna().sort_values().unique()
    latest = pd.Timestamp(periods[-1])
    target_start = latest - pd.DateOffset(months=11)
    default_start_period = pd.Timestamp(
        periods[min(int(periods.searchsorted(target_start, side="left")), len(periods) - 1)]
    )
    start_options = [pd.Timestamp(period) for period in reversed(periods)]
    start_column, end_column = st.columns(2)
    with start_column:
        start = st.selectbox(
            "Período inicial",
            start_options,
            index=start_options.index(default_start_period),
            format_func=formatar_competencia,
            key="sgs_credit_period_start",
        )
    end_options: list[str | pd.Timestamp] = [
        "Mais recente",
        *[pd.Timestamp(period) for period in reversed(periods) if period >= start],
    ]
    stored_end = st.session_state.get("sgs_credit_period_end")
    if stored_end != "Mais recente" and stored_end not in end_options:
        st.session_state["sgs_credit_period_end"] = "Mais recente"
    with end_column:
        end = st.selectbox(
            "Período final",
            end_options,
            index=0,
            format_func=lambda value: value if isinstance(value, str) else formatar_competencia(value),
            key="sgs_credit_period_end",
            help=(
                "Mais recente usa a última competência fechada das séries de crédito. "
                "Cada card mostra no rodapé a competência que ele efetivamente alcança."
            ),
        )
    filtered = _filter_period_range(
        wide,
        pd.Timestamp(start),
        latest if end == "Mais recente" else pd.Timestamp(end),
    )
    return filtered


def _period_filter_silencioso(wide: pd.DataFrame) -> pd.DataFrame:
    """Mesma janela do seletor, sem desenhar o seletor de novo.

    O deck é montado antes das abas e não pode duplicar os controles.
    """
    if wide.empty:
        return wide
    analiticas = [c for c in wide.columns if c not in {"cdi_aa", "selic_aa"}]
    periodos = pd.DatetimeIndex(
        (wide[analiticas] if analiticas else wide).dropna(how="all").index
    ).dropna().sort_values().unique()
    if not len(periodos):
        return wide
    fim = pd.Timestamp(periodos[-1])
    guardado = st.session_state.get("sgs_credit_period_start")
    inicio = pd.Timestamp(guardado) if guardado is not None else pd.Timestamp(
        periodos[min(
            int(periodos.searchsorted(fim - pd.DateOffset(months=11), side="left")),
            len(periodos) - 1,
        )]
    )
    guardado_fim = st.session_state.get("sgs_credit_period_end")
    if guardado_fim is not None and not isinstance(guardado_fim, str):
        fim = pd.Timestamp(guardado_fim)
    return _filter_period_range(wide, inicio, fim)


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
    _leitura("concessoes", wide)
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
            # Barra de largura total comporta rótulo em todo mês e um corpo
            # de fonte maior sem apertar nada.
            rotular_todos=True,
            tamanho_rotulo=TAMANHO_ROTULO_BARRA_PX,
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
    for title, volume, term in cards:
        _chart(
            bar_line_figure(wide, bar_alias=volume, line_alias=term, title=title),
            f"sgs_concessoes_{volume}",
        )


def _render_credit_stock(wide: pd.DataFrame) -> None:
    _leitura("credito_estoque", wide)
    expanded = [
        "credito_ampliado_emprestimos",
        "credito_ampliado_titulos",
        "credito_ampliado_divida_externa",
    ]
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
    _leitura("credito_tomador", wide)
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
    # Barra à esquerda, linha à direita na fileira de baixo: a coluna esquerda
    # do slide fica com os dois empilhados, a direita com os dois de linha.
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
    _leitura("credito_produto", wide)
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
    _leitura("credito_empresa", wide)
    aliases = ["saldo_pj_mpme", "saldo_pj_grande"]
    total = sum_columns(wide, aliases)
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


def _render_credit_control(wide: pd.DataFrame) -> None:
    _leitura("credito_controle", wide)
    aliases = ["saldo_controle_publico", "saldo_controle_privado_nacional", "saldo_controle_estrangeiro"]
    total = sum_columns(wide, aliases)
    participation = shares(wide, aliases, total)
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


def _render_npl_pre(wide: pd.DataFrame) -> None:
    """Cards de pré-inadimplência e inadimplência, sem o seletor de sub-aba."""
    _render_npl_cards(wide, "Pré Inad e Inad")


def _render_npl_cobertura(wide: pd.DataFrame) -> None:
    _render_npl_cards(wide, "Cobertura e Provisionamento")


def _figuras_da_secao(chave_render: str, wide: pd.DataFrame) -> list[go.Figure]:
    """Monta as figuras de uma aba sem desenhar nada na tela."""
    figuras: list[go.Figure] = []
    token_silencio = _SILENCIOSO.set(True)
    token_figuras = _EXPORT_FIGURES.set(figuras)
    try:
        globals()[chave_render](wide)
    finally:
        _EXPORT_FIGURES.reset(token_figuras)
        _SILENCIOSO.reset(token_silencio)
    return figuras


def _figuras_da_subsecao(nome: str, wide: pd.DataFrame) -> list[go.Figure]:
    """Compatibilidade: uma aba de Crédito SFN pelo nome curto."""
    alvo = next(
        render for titulo, _, render in SECOES_DECK
        if render and titulo.split(" · ")[-1] == nome
    )
    return _figuras_da_secao(alvo, wide)


def _figuras_faixa_de_renda(get_cache_manager) -> list[go.Figure]:
    """Painéis por faixa de renda e a visão regional, do cache do SCR.data.

    O deck leva todas as modalidades PF disponíveis, e não só as quatro que a
    tela abre por padrão. O mapa fica de fora: coroplético não existe como
    gráfico nativo do Office. A mesma métrica vai como barra por UF.
    """
    from tabs import scr_inadimplencia as scr_spec
    from tabs.scr_inadimplencia_view import (
        figura_painel,
        figura_por_regiao,
        figura_por_uf,
    )
    from utils import scr_data_query as scr_q

    manager = get_cache_manager() if get_cache_manager else None
    cache = manager.get_cache("scr_data") if manager else None
    if cache is None:
        return []
    periodos = sorted(str(p) for p in (cache.get_info().get("periodos") or []))
    if not periodos:
        return []
    fim = pd.Timestamp(f"{periodos[-1]}-01")
    inicio = fim - pd.DateOffset(months=scr_spec.JANELA_PADRAO_MESES - 1)
    base = cache.carregar_detalhe(anos=list(range(inicio.year, fim.year + 1)))
    base = scr_q.filtrar(
        base,
        data_base_inicial=inicio.strftime("%Y-%m"),
        data_base_final=fim.strftime("%Y-%m"),
    )
    if base.empty:
        return []
    data_base = str(base["data_base"].astype(str).max())
    metrica = scr_q.METRICA_PADRAO
    rotulo = scr_q.METRICAS[metrica].rotulo
    quebra = scr_spec.QUEBRAS_POR_KEY["renda"]
    cliente = quebra.exige_cliente

    presentes = base["modalidade_bcb"].astype(str).unique().tolist()
    modalidades = scr_spec.modalidades_bcb_disponiveis(cliente, presentes=presentes)
    paineis = scr_spec.construir_paineis(
        base, produtos=modalidades, nivel_produto="modalidade_bcb",
        quebra="renda", metrica=metrica, cliente=cliente,
        faixas=scr_spec.faixas_padrao("renda"), incluir_total=True,
    )
    quebras_serie = scr_spec._quebras(base, metrica)
    figuras = [
        figura_painel(
            painel, quebra, eixo_zero=True,
            quebras_serie=quebras_serie, rotulo_metrica=rotulo,
        )
        for painel in paineis
    ]

    if modalidades:
        regiao = scr_q.filtrar(base, modalidade_bcb=modalidades[0])
        geo = scr_spec.construir_por_regiao(
            regiao, metrica=metrica, data_base=data_base, nivel="uf"
        )
        figuras.append(figura_por_uf(geo["mapa"], rotulo))
        figuras.append(figura_por_regiao(
            geo, rotulo_metrica=rotulo,
            titulo=f"{modalidades[0]} por região",
        ))
    return [figura for figura in figuras if figura.data]


def _deck_completo(wide: pd.DataFrame, get_cache_manager) -> tuple[bytes, dict]:
    from utils.comentarios_credito import carregar, comentario
    from utils.sgs_credit_pptx_export import exportar_deck_secoes_pptx

    documento = carregar()
    secoes = []
    for titulo, chave, render in SECOES_DECK:
        if render:
            figuras = _figuras_da_secao(render, wide)
        else:
            figuras = _figuras_faixa_de_renda(get_cache_manager)
        if not figuras:
            continue
        leitura = comentario(chave, documento=documento)
        secoes.append((
            titulo,
            (leitura.texto, "Fontes: " + " · ".join(leitura.fontes))
            if leitura is not None and not leitura.vazio
            else None,
            figuras,
        ))
    datas = pd.DatetimeIndex(wide.index).dropna()
    competencia = formatar_competencia(datas.max()) if len(datas) else "N/D"
    return exportar_deck_secoes_pptx(
        secoes,
        titulo_deck="Estatísticas Crédito BC",
        subtitulo_capa=f"Séries do SGS e do SCR.data · janela até {competencia}",
        rodape_capa="fonte: Banco Central do Brasil · BCData/SGS e SCR.data",
    )


def _botao_deck_completo(wide: pd.DataFrame, get_cache_manager) -> None:
    """Todas as abas em um arquivo, com a leitura dos dados de cada uma."""
    datas = pd.DatetimeIndex(wide.index).dropna()
    chave = "|".join([
        "deck_completo",
        str(datas.min()) if len(datas) else "",
        str(datas.max()) if len(datas) else "",
    ])
    memo = st.session_state.setdefault("_deck_completo_memo", {})
    if memo.get("chave") != chave:
        memo["chave"] = chave
        memo["erro"] = ""
        with st.spinner("Montando o deck completo..."):
            try:
                memo["valor"] = _deck_completo(wide, get_cache_manager)
            except Exception as exc:  # noqa: BLE001 - a seção continua sem o deck
                memo["valor"] = None
                memo["erro"] = str(exc)
    if not memo.get("valor"):
        st.caption(f"Deck completo indisponível: {memo.get('erro') or 'sem gráficos'}")
        return
    blob, meta = memo["valor"]
    st.download_button(
        f"Baixar deck completo ({meta['paineis']} gráficos, {meta['slides']} slides)",
        data=blob,
        file_name="estatisticas_credito_bc.pptx",
        mime=(
            "application/vnd.openxmlformats-officedocument."
            "presentationml.presentation"
        ),
        key="sgs_deck_completo",
        width="stretch",
        help=(
            "Todas as abas em um arquivo, na ordem da tela, com a leitura dos "
            "dados de cada uma acima dos gráficos."
        ),
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
    _leitura(
        "situacao",
        wide,
        ["comprometimento_juros", "comprometimento_amortizacao", "endividamento_renda"],
    )
    commitment = wide.copy()
    if {"comprometimento_juros", "comprometimento_amortizacao"}.issubset(commitment.columns):
        commitment["comprometimento_total_derivado"] = sum_columns(
            commitment, ["comprometimento_juros", "comprometimento_amortizacao"]
        )
    employment = wide[[column for column in ["desocupacao"] if column in wide.columns]].copy()
    employment_change = _yoy_pp_frame(wide, ["desocupacao"])
    if "desocupacao" in employment_change:
        employment["retomada_emprego_derivada"] = employment_change["desocupacao"]
    employment.attrs["source_aliases"] = ["desocupacao"]
    _cards_em_grade([
        (
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
                compacto=True,
                # Endividamento roda a 49,8% da renda e achatava as demais
                # séries, entre 5% e 29%, na base do gráfico.
                secundarios=["endividamento_renda"],
                y_title_secundario="% da renda",
            ),
            "sgs_comprometimento",
        ),
        (
            line_figure(
                employment,
                ["desocupacao", "retomada_emprego_derivada"],
                title="Taxa de desocupação e velocidade de retomada do emprego",
                y_title="% / variação YoY em p.p.",
                labels={"retomada_emprego_derivada": "Variação YoY da desocupação"},
                compacto=True,
            ),
            "sgs_emprego",
        ),
    ])


def _render_npl(wide: pd.DataFrame, get_cache_manager=None) -> None:
    selected = st.segmented_control(
        "Visão de inadimplência",
        NPL_SUBSECTIONS,
        default=NPL_SUBSECTIONS[0],
        key="sgs_npl_subsection",
    )
    if selected == "Inad por Faixa de Renda":
        if get_cache_manager is None:
            st.error("Gerenciador do cache SCR.data indisponível.")
            return
        from tabs.scr_inadimplencia_view import render_scr_inadimplencia

        render_scr_inadimplencia(get_cache_manager)
        return
    _render_npl_cards(_period_filter(wide), selected)


def _render_npl_cards(wide: pd.DataFrame, selected: str) -> None:
    """Cards de uma sub-aba de inadimplência, sem o seletor.

    Separado do render para que o deck completo monte as duas sub-abas sem
    passar pelo controle de tela.
    """
    if selected == "Cobertura e Provisionamento":
        _leitura("npl_cobertura", wide)
        provision = ["provisao_sfn", "provisao_publico", "provisao_privado_nacional", "provisao_estrangeiro"]
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
        _cards_em_grade([
            (
                line_figure(
                    wide, provision,
                    title="Nível de provisão",
                    y_title="% da carteira total",
                    suffix="%",
                    compacto=True,
                ),
                "sgs_provisao",
            ),
            (
                line_figure(
                    coverage, list(pairs),
                    title="Nível de cobertura (>90 dias)",
                    y_title="% da carteira inadimplente",
                    labels={
                        "cobertura_sfn_derivada": "SFN",
                        "cobertura_publico_derivada": "Público",
                        "cobertura_privado_nacional_derivada": "Privado nacional",
                        "cobertura_estrangeiro_derivada": "Estrangeiro",
                    },
                    suffix="%",
                    compacto=True,
                ),
                "sgs_cobertura",
            ),
        ])
        return

    _leitura("npl_pre_inad", wide)
    aggregate = [
        "pre_inad_livre_pf", "inad_livre_pf", "pre_inad_livre_pj",
        "inad_livre_pj", "pre_inad_livre_total", "inad_livre_total",
    ]
    pf_pre = [
        "pre_inad_livre_pf_nao_consignado", "pre_inad_livre_pf_cheque",
        "pre_inad_livre_pf_cartao_total", "pre_inad_livre_pf_cartao_rotativo",
        "pre_inad_livre_pf_cartao_parcelado", "pre_inad_livre_pf_veiculos",
        "pre_inad_livre_pf_consignado", "pre_inad_direcionado_pf_imobiliario",
    ]
    pj_pre = [
        "pre_inad_livre_pj_conta_garantida", "pre_inad_livre_pj_capital_giro",
        "pre_inad_livre_pj_duplicatas",
    ]
    pf_npl = [
        "inad_livre_pf_nao_consignado", "inad_livre_pf_cheque", "inad_livre_pf_cartao_total",
        "inad_livre_pf_cartao_rotativo", "inad_livre_pf_cartao_parcelado", "inad_livre_pf_veiculos",
        "inad_livre_pf_consignado", "inad_direcionado_pf_imobiliario",
    ]
    pj_npl = [
        "inad_livre_pj_conta_garantida", "inad_livre_pj_capital_giro",
        "inad_livre_pj_duplicatas",
    ]
    # Primeiro o panorama; depois as pré-inadimplências juntas (PF, PJ) e as
    # inadimplências juntas (PF, PJ). O leitor compara pré com pré e inad com
    # inad sem atravessar a página.
    cards = [
        (
            line_figure(
                wide, aggregate,
                title="Pré-inadimplência (15–90d) e inadimplência (>90d) — recursos livres",
                y_title="% da carteira", suffix="%", compacto=True,
            ),
            "sgs_npl_aggregate",
        ),
    ]
    _cards_em_grade(cards)
    _cards_em_grade([
        (
            line_figure(
                wide, pf_pre, title="Produtos PF — pré-inadimplência",
                y_title="% da carteira", suffix="%", compacto=True,
            ),
            "sgs_npl_pf_pre",
        ),
        (
            line_figure(
                wide, pj_pre, title="Produtos PJ — pré-inadimplência",
                y_title="% da carteira", suffix="%", compacto=True,
            ),
            "sgs_npl_pj_pre",
        ),
        (
            line_figure(
                wide, pf_npl, title="Produtos PF — inadimplência",
                y_title="% da carteira", suffix="%", compacto=True,
            ),
            "sgs_npl_pf_inad",
        ),
        (
            line_figure(
                wide, pj_npl, title="Produtos PJ — inadimplência",
                y_title="% da carteira", suffix="%", compacto=True,
                # Desconto de recebíveis roda a 1% enquanto capital de giro
                # roda a 4%: no eixo único ele fica colado na base.
                secundarios=["inad_livre_pj_duplicatas"],
                y_title_secundario="% da carteira",
            ),
            "sgs_npl_pj_inad",
        ),
    ])


def _render_rates(wide: pd.DataFrame) -> None:
    # O benchmark CDI pode entrar no mês corrente antes das taxas de crédito.
    # O card termina na última competência publicada das taxas principais.
    referencias = [
        column for column in ("taxa_pf_livre", "taxa_pj_livre")
        if column in wide.columns
    ]
    if referencias:
        validas = wide[referencias].dropna(how="all")
        if not validas.empty:
            wide = wide.loc[wide.index <= validas.index.max()].copy()
    _leitura("taxas", wide)
    # Cartão rotativo roda a ~450% a.a. e imobiliário a ~11%: no mesmo eixo
    # linear, metade das séries vira uma linha reta colada na base. Os cards
    # são separados por ordem de grandeza da taxa.
    cards = [
        (
            "Taxa média PF — crédito com garantia",
            ["taxa_pf_imobiliario", "taxa_pf_veiculos", "taxa_pf_consignado"],
        ),
        (
            "Taxa média PF — crédito sem garantia",
            ["taxa_pf_cartao_total", "taxa_pf_nao_consignado", "taxa_pf_cheque"],
        ),
        ("Cartão — taxa média e parcelado", ["taxa_pf_cartao_total", "taxa_pf_cartao_parcelado"]),
        ("Cartão — rotativo", ["taxa_pf_cartao_rotativo"]),
        ("Taxa média PJ", ["taxa_pj_conta_garantida", "taxa_pj_capital_giro", "taxa_pj_duplicatas"]),
        ("Taxa e spread agregados", ["taxa_pf_livre", "spread_pf_livre", "taxa_pj_livre", "spread_pj_livre", "cdi_aa"]),
    ]
    aliases_yoy = ["taxa_pf_livre", "spread_pf_livre", "taxa_pj_livre", "spread_pj_livre"]
    cards.append(
        (
            "Ritmo de crescimento da taxa média e do spread médio",
            aliases_yoy,
        )
    )
    grade = [
        (
            line_figure(
                _yoy_pp_frame(wide, aliases) if title.startswith("Ritmo") else wide,
                aliases,
                title=title,
                y_title="variação YoY (p.p.)" if title.startswith("Ritmo") else "% a.a. / p.p.",
                suffix="" if title.startswith("Ritmo") else "%",
                compacto=True,
            ),
            f"sgs_rates_{posicao}",
        )
        for posicao, (title, aliases) in enumerate(cards)
    ]
    _cards_em_grade(grade)


def _render_glossary(frame: pd.DataFrame, metadata: Mapping | None) -> None:
    st.markdown("#### Glossário e metodologia")
    glossary_section = st.segmented_control(
        "Conteúdo do glossário",
        ("Indicadores SGS", "SCR.data"),
        default="Indicadores SGS",
        key="sgs_credit_glossary_section",
    )
    if glossary_section == "SCR.data":
        st.markdown("##### Conceitos oficiais do SCR.data")
        st.markdown(
            "- **Carteira ativa:** soma dos valores a vencer e vencidos das operações "
            "abrangidas pelo SCR. Na visão regional, **Carteira (R$ bi)** é o total "
            "da carteira da modalidade na UF, independentemente de a operação estar "
            "inadimplente. É o denominador das taxas.\n"
            "- **Inadimplência:** carteira integral das operações com alguma parcela "
            "em atraso superior a 90 dias, dividida pela carteira de todas as operações.\n"
            "- **Ativo problemático:** carteira das operações classificadas como ativos "
            "problemáticos dividida pela carteira total. Desde 2025, o BCB considera "
            "a classificação informada pelas instituições na característica especial 19.\n"
            "- **Localização:** a UF decorre do CEP de residência da pessoa física ou "
            "da sede da pessoa jurídica.\n"
            "- **Participação da UF:** carteira ativa da UF dividida pela carteira ativa "
            "do Brasil, após os mesmos filtros de cliente e modalidade."
        )
        st.markdown("##### Escopo, periodicidade e limites")
        st.markdown(
            "O BCB atualiza o relatório mensalmente, no último dia útil, com divulgação "
            "cerca de 30 dias após o fechamento. O documento 3040 cobre operações de "
            "crédito cursadas no país acima do limite de identificação do SCR: R$ 1 mil "
            "até mai/2016 e R$ 200 desde jun/2016. Saldos de dependências ou controladas "
            "no exterior ficam fora da publicação. Recortes com até 15 operações têm a "
            "contagem protegida; os valores monetários permanecem no agregado publicado."
        )
        st.markdown("##### Comparabilidade")
        st.markdown(
            "Os totais podem divergir do IF.data, do COSIF e de outras estatísticas do "
            "BCB por diferenças de documento, cobertura, tolerância de remessa e tratamento "
            "de agregações com poucas operações. Para dados consolidados de crédito, o BCB "
            "orienta consultar a Nota para a Imprensa e o SGS."
        )
        st.markdown(
            "**Fontes oficiais:** [SCR.data](https://www.bcb.gov.br/estabilidadefinanceira/scrdata) · "
            "[Metodologia](https://www.bcb.gov.br/content/estabilidadefinanceira/scr/scr.data/scr_data_metodologia.pdf) · "
            "[Documento 3040](https://www.bcb.gov.br/estabilidadefinanceira/scrdoc3040)"
        )
        return

    rows = [
        ("Crescimento real em 12 meses", "(Xₜ / índice IPCAₜ) ÷ (Xₜ₋₁₂ / índice IPCAₜ₋₁₂) − 1", "%"),
        ("Variação de taxa/spread", "xₜ − xₜ₋₁₂", "p.p."),
        ("Participação", "componente ÷ total", "%"),
        ("Cobertura", "provisão / carteira ÷ inadimplência / carteira", "%"),
        ("Pré-inadimplência", "Operações com atraso entre 15 e 90 dias", "% da carteira"),
        ("Inadimplência", "Operações com atraso superior a 90 dias", "% da carteira"),
        ("Comprometimento total", "amortização do principal + juros", "% da renda"),
        ("Outros — mix PF/PJ", "resíduo entre o total e os produtos explicitamente classificados", "% da carteira"),
        ("Crédito em % do PIB", "aguarda validação da série mensal de PIB usada no workbook histórico", "% do PIB"),
        ("MPMe", "receita bruta até R$ 300 milhões ou ativos totais até R$ 240 milhões", "classificação"),
    ]
    st.dataframe(
        pd.DataFrame(rows, columns=["Indicador", "Definição / fórmula", "Unidade"]),
        hide_index=True,
        width="stretch",
    )

    st.markdown("##### Leitura dos gráficos")
    st.markdown(
        "- **Cores:** a paleta de linhas tem cinco cores, todas com pelo menos "
        "3:1 de contraste sobre o branco e distância perceptual (ΔE) acima de 27 "
        "entre si. Da sexta série em diante a cor repete e o **traço tracejado** "
        "passa a distinguir.\n"
        "- **Espessura:** linha grossa é a série em foco, tracejada é o agregado, "
        "fina é contexto.\n"
        "- **Rótulos:** tamanho único de 12 px, sempre na horizontal. Fatia de "
        "barra que não comporta o rótulo nesse tamanho fica sem rótulo — o valor "
        "continua no tooltip — em vez de receber um texto encolhido ou deitado.\n"
        "- **Competência:** o rodapé de cada card informa a última competência "
        "que aquele card efetivamente alcança, que nem sempre é a do seletor."
    )

    latest = pd.to_datetime(frame["data"], errors="coerce").max()
    latest_label = latest.strftime("%m/%Y") if pd.notna(latest) else "N/D"
    source = (metadata or {}).get("fonte") or "BCData/SGS"
    st.markdown("##### Fontes, cache e critérios de leitura")
    st.markdown(
        f"- **SGS:** Banco Central do Brasil · última observação no cache: "
        f"**{latest_label}** · origem do cache: **{source}**.\n"
        "- **SCR.data:** dados do documento 3040, operação a operação; "
        "podem divergir do IF.data e dos balancetes COSIF. Tem calendário de "
        "publicação próprio e costuma ficar um mês atrás do SGS.\n"
        "- **Localização SCR:** a UF vem do CEP do tomador.\n"
        "- **Porte SCR:** PF usa faixa de renda; PJ usa faturamento. Os critérios "
        "não devem ser combinados no mesmo eixo.\n"
        "- **Sigilo SCR:** contagens iguais ou inferiores ao limite de divulgação "
        "podem ser suprimidas pelo BCB."
    )


@st.cache_data(ttl=3600, show_spinner=False)
def _competencia_publicada_no_bcb() -> str | None:
    """Última competência que o BCB já publicou, para comparar com o cache.

    Consulta leve, de uma série só. Falha em silêncio: o aviso simplesmente
    não aparece se o BCB estiver fora do ar.
    """
    from utils.ifdata_cache.sgs_credit import ultima_competencia_publicada

    return ultima_competencia_publicada()


def _aviso_de_defasagem(wide: pd.DataFrame) -> None:
    cache_ate = pd.DatetimeIndex(wide.index).max() if len(wide.index) else None
    if cache_ate is None:
        return
    try:
        publicada = _competencia_publicada_no_bcb()
    except Exception:
        return
    if not publicada:
        return
    publicada_ts = pd.Timestamp(f"{publicada}-01")
    if publicada_ts.to_period("M") > pd.Timestamp(cache_ate).to_period("M"):
        st.warning(
            f"O Banco Central já publicou **{formatar_competencia(publicada_ts)}**; "
            f"o cache desta seção está em **{formatar_competencia(cache_ate)}**. "
            "Rode a atualização em *Atualizar Base* para trazer o mês novo.",
            icon=":material/update:",
        )


def render_mercado_credito(cache, *, get_cache_manager=None) -> None:
    st.markdown(
        """
        <style>
        div[data-testid="stMarkdownContainer"] h4 { font-size: 1.42rem; }
        div[data-testid="stMarkdownContainer"] h5 { font-size: 1.18rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )
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

    # As duas fontes da seção têm calendários diferentes, e dentro do próprio
    # SGS o bloco de endividamento das famílias sai depois do de crédito.
    competencias = _competencias_por_fonte(full_wide)
    if competencias:
        st.caption(
            "Competência no cache · "
            + " · ".join(
                f"{rotulo}: **{formatar_competencia(data)}**"
                for rotulo, data in competencias.items()
            )
        )
    _aviso_de_defasagem(full_wide)

    selected = st.segmented_control(
        "Área",
        MAIN_SECTIONS,
        default=MAIN_SECTIONS[0],
        key="sgs_credit_main_section",
    )
    # Os dois downloads ficam num popover: dois botões primários no topo
    # competiam com o conteúdo e ocupavam uma faixa inteira da página.
    _, coluna_export = st.columns([0.82, 0.18])
    with coluna_export:
        with st.popover("Exportar", width="stretch"):
            export_slot = st.empty()
            _botao_deck_completo(
                _period_filter_silencioso(full_wide), get_cache_manager
            )
    figuras: list[go.Figure] = []
    token = _EXPORT_FIGURES.set(figuras)
    try:
        if selected == "Crédito SFN":
            _render_credit(_period_filter(full_wide))
        elif selected == "Situação dos Agentes":
            _render_situation(_period_filter(full_wide))
        elif selected == "Inadimplência e Provisionamento":
            _render_npl(full_wide, get_cache_manager)
        elif selected == "Taxas de Juros e Spread":
            _render_rates(_period_filter(full_wide))
        elif selected == "Glossário":
            _render_glossary(result.dados, result.metadata)
        else:
            _render_concessoes(_period_filter(full_wide))
    finally:
        _EXPORT_FIGURES.reset(token)

    if figuras:
        from utils.sgs_credit_pptx_export import exportar_figuras_pptx

        detalhe = ""
        if selected == "Crédito SFN":
            detalhe = str(st.session_state.get("sgs_credit_subsection") or "")
        elif selected == "Inadimplência e Provisionamento":
            detalhe = str(st.session_state.get("sgs_npl_subsection") or "")
        pagina = " · ".join(item for item in (selected, detalhe) if item)
        blob, meta_export = exportar_figuras_pptx(
            figuras,
            titulo_deck=f"{TITLE} · {pagina}",
        )
        with export_slot.container():
            st.download_button(
                f"Baixar {meta_export['paineis']} gráficos desta aba em PPTX",
                data=blob,
                file_name="estatisticas_credito_bc.pptx",
                mime=(
                    "application/vnd.openxmlformats-officedocument."
                    "presentationml.presentation"
                ),
                key=f"sgs_pptx_{selected}_{detalhe}",
                width="stretch",
                help=(
                    "Gráficos Office nativos e editáveis, "
                    f"até {meta_export['paineis_por_slide']} por slide."
                ),
            )
