"""Renderer Streamlit da análise de inadimplência baseada no SCR.data."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st


def render_scr_inadimplencia(get_cache_manager) -> None:
    # =========================================================================
    # ABA INADIMPLÊNCIA (SCR.data)
    # Fonte: ZIPs anuais do PDA/BCB (não há API). O cache `scr_data` agrega no
    # grão data_base x uf x segmento x cliente x porte x modalidade x
    # submodalidade e publica um slice por ano no release; esta aba só lê os
    # parquets já materializados e delega todo cálculo a utils/scr_data_query.
    # =========================================================================
    from tabs import scr_inadimplencia as scr_spec
    from utils import scr_data_query as scr_q
    from utils import scr_pptx_export as scr_pptx

    SCR_PLOTLY_CONFIG = {
        "displayModeBar": "hover",
        "displaylogo": False,
        "responsive": True,
    }
    SCR_PALETTE = list(scr_spec.PALETA_CATEGORICA)

    st.markdown(f"#### {scr_spec.TITLE}")
    st.caption(scr_spec.SUBTITLE)

    @st.cache_resource(show_spinner=False)
    def _scr_cache():
        mgr = get_cache_manager()
        return mgr.get_cache("scr_data") if mgr else None

    @st.cache_data(ttl=3600, show_spinner=False)
    def _scr_dimensoes() -> dict:
        cache_scr = _scr_cache()
        if cache_scr is None:
            return {}
        try:
            cache_scr.bootstrap_local_assets()
            return cache_scr.carregar_dimensoes()
        except Exception:
            return {}

    @st.cache_data(ttl=3600, show_spinner=False)
    def _scr_ultima_data_base() -> str | None:
        """Lê a última data-base do resumo, que é leve e sempre está presente."""
        cache_scr = _scr_cache()
        if cache_scr is None:
            return None
        try:
            cache_scr.bootstrap_local_assets()
            meta = cache_scr.get_info()
            periodos = meta.get("periodos") or []
            if periodos:
                return str(periodos[-1])
            resumo = pd.read_parquet(cache_scr.arquivo_dados, columns=["data_base"])
            return str(resumo["data_base"].astype(str).max())
        except Exception:
            return None

    @st.cache_data(ttl=3600, show_spinner="Carregando SCR.data (grão completo)...")
    def _scr_detalhe(anos: tuple[int, ...]) -> pd.DataFrame:
        cache_scr = _scr_cache()
        if cache_scr is None:
            return pd.DataFrame()
        try:
            return cache_scr.carregar_detalhe(anos=list(anos))
        except Exception as exc:
            st.error(f"Falha ao carregar os slices anuais do SCR.data: {exc}")
            return pd.DataFrame()

    @st.cache_data(ttl=3600, show_spinner="Carregando série completa (resumo por região)...")
    def _scr_resumo() -> pd.DataFrame:
        cache_scr = _scr_cache()
        if cache_scr is None:
            return pd.DataFrame()
        try:
            resultado = cache_scr.carregar()
            if resultado.sucesso and resultado.dados is not None:
                return resultado.dados
        except Exception as exc:
            st.error(f"Falha ao carregar o resumo do SCR.data: {exc}")
        return pd.DataFrame()

    @st.cache_data(ttl=86400, show_spinner=False)
    def _scr_salario_minimo(data_base: str) -> float | None:
        serie = scr_q.buscar_salario_minimo()
        if serie.empty:
            return None
        anteriores = serie[serie.index <= str(data_base)]
        if anteriores.empty:
            return None
        return float(anteriores.iloc[-1])

    def _scr_fmt(valor, formato="percentual") -> str:
        return scr_q.formatar_valor(valor, formato)

    def _scr_avisar_quebras(quebras: list) -> None:
        for quebra in quebras:
            st.warning(
                f"**Quebra de série em {quebra['data_base']} — {quebra['titulo']}.** "
                f"{quebra['descricao']}",
                icon="⚠️",
            )

    def _scr_marcar_quebras(fig, quebras: list):
        return scr_spec.marcar_quebras(fig, quebras)

    def _scr_layout(fig, *, altura=380, percentual=True, titulo_y=""):
        fig.update_layout(
            height=altura,
            margin=dict(l=10, r=10, t=40, b=10),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
            hovermode="x unified",
            yaxis_title=titulo_y,
            xaxis_title="",
        )
        if percentual:
            fig.update_yaxes(tickformat=".1%")
        return fig

    _scr_ultima = _scr_ultima_data_base()
    if not _scr_ultima:
        st.error(
            "Cache `scr_data` indisponível. Rode "
            "`python tools/update_caches_cli.py --tipo scr_data` para materializá-lo "
            "ou publique os assets no release."
        )
        st.stop()

    # ------------------------------------------------------------------
    # Barra de contexto
    # ------------------------------------------------------------------
    with st.container(key="scr_filtros", border=True):
        col_janela, col_cliente, col_metrica, col_segmento = st.columns([1.1, 1.0, 1.3, 1.4])

        with col_janela:
            _scr_serie_completa = st.toggle(
                "série completa",
                value=False,
                key="scr_serie_completa",
                help=(
                    f"Liga a série desde {scr_spec.PRIMEIRA_DATA_BASE} usando o resumo por "
                    "região (sem UF e sem segmento). Desligado, a aba usa o grão completo "
                    "da janela escolhida."
                ),
            )
            _scr_janela = st.selectbox(
                "janela",
                scr_spec.JANELAS_DISPONIVEIS,
                index=scr_spec.JANELAS_DISPONIVEIS.index(scr_spec.JANELA_PADRAO_MESES),
                format_func=lambda m: f"últimos {m} meses",
                key="scr_janela",
                disabled=_scr_serie_completa,
            )

        with col_cliente:
            _scr_cliente_opcao = st.radio(
                "tipo de cliente",
                ["PF + PJ", "PF", "PJ"],
                horizontal=True,
                key="scr_cliente",
            )

        with col_metrica:
            _scr_metrica = st.selectbox(
                "métrica",
                scr_q.METRICAS_PERCENTUAIS,
                index=scr_q.METRICAS_PERCENTUAIS.index(scr_q.METRICA_PADRAO),
                format_func=lambda chave: scr_q.METRICAS[chave].rotulo,
                key="scr_metrica",
            )
            st.caption(scr_q.METRICAS[_scr_metrica].descricao)

        with col_segmento:
            _scr_dims = _scr_dimensoes()
            _scr_segmentos_disp = (
                _scr_dims.get("segmento", pd.DataFrame()).get("segmento", pd.Series(dtype=str)).tolist()
                if _scr_dims else []
            )
            _scr_segmentos = st.multiselect(
                "segmento da instituição",
                _scr_segmentos_disp,
                default=[],
                key="scr_segmento",
                placeholder="todos os segmentos",
                disabled=_scr_serie_completa,
                help="Indisponível na série completa: o resumo não guarda o segmento.",
            )

    # ------------------------------------------------------------------
    # Carregamento
    # ------------------------------------------------------------------
    if _scr_serie_completa:
        _scr_base = _scr_resumo()
        _scr_tem_detalhe = False
        st.info(
            f"Série completa desde {scr_spec.PRIMEIRA_DATA_BASE}, a partir do resumo por "
            "região. As seções por UF e por segmento de instituição ficam indisponíveis "
            "neste modo — desligue *série completa* para voltar ao grão completo.",
            icon="🗓️",
        )
    else:
        _scr_anos = tuple(scr_q.anos_da_janela(_scr_ultima, _scr_janela))
        _scr_base = _scr_detalhe(_scr_anos)
        _scr_tem_detalhe = not _scr_base.empty
        _scr_ini, _scr_fim = scr_q.janela_de_data_bases(_scr_ultima, _scr_janela)
        _scr_base = scr_q.filtrar(_scr_base, data_base_inicial=_scr_ini, data_base_final=_scr_fim)

    if _scr_base.empty:
        st.warning("Nenhum dado do SCR.data disponível para o recorte selecionado.")
        st.stop()

    _scr_cliente_filtro = None if _scr_cliente_opcao == "PF + PJ" else _scr_cliente_opcao
    _scr_df = scr_q.filtrar(
        _scr_base,
        cliente=_scr_cliente_filtro,
        segmento=_scr_segmentos or None,
    )
    if _scr_df.empty:
        st.warning("Os filtros selecionados não deixaram nenhum registro.")
        st.stop()

    _scr_data_base = str(_scr_df["data_base"].astype(str).max())

    # ------------------------------------------------------------------
    # Seções
    # ------------------------------------------------------------------
    _scr_abas_visiveis = [
        secao for secao in scr_spec.SECOES
        if _scr_tem_detalhe or not secao.exige_detalhe
    ]
    _scr_abas = st.tabs([secao.label for secao in _scr_abas_visiveis])
    _scr_por_key = dict(zip([s.key for s in _scr_abas_visiveis], _scr_abas))

    # --- Painéis ------------------------------------------------------
    with _scr_por_key["paineis"]:
        st.caption(scr_spec.SECOES_POR_KEY["paineis"].resumo)

        _pn_c1, _pn_c2, _pn_c3 = st.columns([1.5, 1.1, 1.0])
        with _pn_c1:
            _pn_quebras = [
                q for q in scr_spec.QUEBRAS
                if (_scr_tem_detalhe or not q.exige_detalhe)
            ]
            _pn_quebra_key = st.selectbox(
                "quebra das linhas",
                [q.key for q in _pn_quebras],
                index=0,
                format_func=lambda k: scr_spec.QUEBRAS_POR_KEY[k].label,
                key="scr_pn_quebra",
            )
        with _pn_c2:
            _pn_nivel = st.radio(
                "nível de produto",
                ["submodalidade", "modalidade"],
                horizontal=True,
                key="scr_pn_nivel",
            )
        with _pn_c3:
            _pn_total = st.toggle(
                "linha `Todos`",
                value=True,
                key="scr_pn_total",
                help="O agregado do produto sem recorte, como referência.",
            )
            _pn_zero = st.toggle(
                "eixo a partir de zero",
                value=True,
                key="scr_pn_zero",
                help=(
                    "Ligado, os painéis ficam comparáveis entre si e a magnitude "
                    "é honesta. Desligado, cada painel amplia a própria variação."
                ),
            )

        _pn_spec = scr_spec.QUEBRAS_POR_KEY[_pn_quebra_key]
        _pn_cliente = _pn_spec.exige_cliente or _scr_cliente_filtro

        # Produtos candidatos, ordenados por carteira no último período.
        _pn_base_prod = scr_q.filtrar(
            _scr_df, cliente=_pn_cliente,
            data_base_inicial=_scr_data_base, data_base_final=_scr_data_base,
        )
        _pn_ranking_prod = scr_q.ranking(
            _pn_base_prod, _pn_nivel, "carteira_ativa", carteira_minima_rs_mil=0
        )
        _pn_opcoes = _pn_ranking_prod[_pn_nivel].astype(str).tolist()
        _pn_default = _pn_opcoes[:scr_spec.PAINEIS_POR_SLIDE]

        _pn_produtos = st.multiselect(
            "produtos (um painel por produto, 4 por slide no PPTX)",
            _pn_opcoes,
            default=_pn_default,
            key="scr_pn_produtos",
            help="Ordenados por tamanho de carteira no período final.",
        )

        _pn_faixas_disp = scr_spec.faixas_padrao(_pn_quebra_key)
        _pn_faixas = None
        if _pn_faixas_disp is not None:
            _pn_todas = (
                scr_q.ordem_portes(_pn_cliente or "PF")
                if _pn_spec.coluna == "porte"
                else list(_pn_faixas_disp)
            )
            _pn_faixas = st.multiselect(
                _pn_spec.label.lower(),
                _pn_todas,
                default=_pn_faixas_disp,
                key=f"scr_pn_faixas_{_pn_quebra_key}",
                format_func=lambda v: scr_spec.rotulo_serie(v, _pn_spec),
            )

        if not _pn_produtos:
            st.info("Escolha ao menos um produto para montar os painéis.")
        else:
            _pn_paineis = scr_spec.construir_paineis(
                _scr_df,
                produtos=_pn_produtos,
                nivel_produto=_pn_nivel,
                quebra=_pn_quebra_key,
                metrica=_scr_metrica,
                cliente=_pn_cliente,
                faixas=_pn_faixas,
                incluir_total=_pn_total,
            )

            if not _pn_paineis:
                st.warning("Nenhum painel com dados no recorte selecionado.")
            else:
                for _pn_aviso in scr_spec.avaliar_legibilidade(_pn_paineis):
                    _pn_texto = f"**{_pn_aviso['painel']}** — {_pn_aviso['mensagem']}"
                    if _pn_aviso["nivel"] == "alerta":
                        st.warning(_pn_texto, icon="⚠️")
                    else:
                        st.caption(f"ℹ️ {_pn_texto}")

                def _pn_figura(painel):
                    """Um quadrante em Plotly, no mesmo desenho do PPTX."""
                    fig = go.Figure()
                    _tab = painel.series.copy()
                    _tab["data_base"] = _tab["data_base"].astype(str)
                    _tab["serie"] = _tab["serie"].astype(str)
                    _tab = _tab.pivot_table(
                        index="data_base", columns="serie", values="valor",
                        aggfunc="first", observed=True,
                    ).sort_index()
                    _cats = [scr_pptx.rotulo_mes(i) for i in _tab.index]

                    for _nome in painel.ordem_series:
                        if _nome not in _tab.columns:
                            continue
                        _serie = _tab[_nome]
                        _validos = _serie.dropna()
                        _texto = [
                            scr_spec.formatar_percentual_2casas(v)
                            if (_validos.size and i == _serie.index.get_loc(_validos.index[-1]))
                            else ""
                            for i, v in enumerate(_serie)
                        ]
                        _eh_total = _nome in painel.tracejadas
                        fig.add_trace(go.Scatter(
                            x=_cats,
                            y=_serie.values,
                            name=scr_spec.rotulo_serie(_nome, _pn_spec),
                            mode="lines+text",
                            text=_texto,
                            textposition="middle right",
                            textfont=dict(
                                size=10, color=painel.cores.get(_nome),
                                family="Inter, Helvetica, Arial, sans-serif",
                            ),
                            line=dict(
                                color=painel.cores.get(_nome),
                                width=2.6 if _eh_total else 2.0,
                                dash="dash" if _eh_total else "solid",
                                shape="linear",
                            ),
                            hovertemplate="%{x}<br>%{y:.2%}<extra>%{fullData.name}</extra>",
                            connectgaps=False,
                        ))

                    fig.update_layout(
                        height=340,
                        margin=dict(l=8, r=64, t=6, b=4),
                        plot_bgcolor="#FFFFFF",
                        paper_bgcolor="#FFFFFF",
                        font=dict(
                            family="Inter, Helvetica, Arial, sans-serif",
                            size=11, color=scr_spec.COR_TEXTO,
                        ),
                        legend=dict(
                            orientation="h", yanchor="top", y=-0.16, x=0,
                            font=dict(size=10), title_text="",
                        ),
                        hovermode="x unified",
                        # Vírgula decimal, ponto de milhar: sem isso o eixo sai
                        # "3.50%" num material que é lido em português.
                        separators=",.",
                    )
                    fig.update_yaxes(
                        tickformat=".2%", showgrid=True,
                        rangemode="tozero" if _pn_zero else "normal",
                        gridcolor=scr_spec.COR_GRADE, gridwidth=1,
                        zeroline=False, linecolor=scr_spec.COR_GRADE,
                        ticks="", title_text="",
                    )
                    fig.update_xaxes(
                        showgrid=False, linecolor=scr_spec.COR_GRADE,
                        ticks="", title_text="", tickangle=-90,
                        nticks=10, automargin=True,
                    )
                    return fig

                for _pn_inicio in range(0, len(_pn_paineis), 2):
                    _pn_cols = st.columns(2)
                    for _pn_col, _pn_p in zip(_pn_cols, _pn_paineis[_pn_inicio:_pn_inicio + 2]):
                        with _pn_col:
                            st.markdown(
                                f"<div style='font-size:1.02rem;font-weight:600;"
                                f"color:{scr_spec.COR_PRETO};margin-bottom:.1rem'>"
                                f"{_pn_p.titulo}</div>"
                                f"<div style='font-size:.85rem;color:{scr_spec.COR_TEXTO}'>"
                                f"{_pn_p.subtitulo}</div>"
                                f"<div style='font-size:.72rem;color:#8F8F8F;"
                                f"margin-bottom:.25rem'>{_pn_p.fonte}</div>",
                                unsafe_allow_html=True,
                            )
                            st.plotly_chart(
                                _pn_figura(_pn_p),
                                use_container_width=True,
                                config=SCR_PLOTLY_CONFIG,
                            )

                st.markdown("---")
                _pn_ec1, _pn_ec2 = st.columns([1, 2])
                with _pn_ec1:
                    try:
                        _pn_blob, _pn_meta = scr_pptx.exportar_paineis_pptx(
                            _pn_paineis,
                            rotulo_serie_fn=lambda n: scr_spec.rotulo_serie(n, _pn_spec),
                            titulo_deck=(
                                f"{scr_q.METRICAS[_scr_metrica].rotulo} · "
                                f"{_pn_spec.subtitulo} · data-base {_scr_data_base}"
                            ),
                        )
                    except Exception as _pn_exc:  # noqa: BLE001
                        _pn_blob, _pn_meta = None, None
                        st.error(f"Falha ao montar o PPTX: {_pn_exc}")
                    if _pn_blob:
                        st.download_button(
                            "baixar PPTX (4 painéis por slide)",
                            data=_pn_blob,
                            file_name=f"scr_paineis_{_scr_data_base}.pptx",
                            mime=(
                                "application/vnd.openxmlformats-officedocument"
                                ".presentationml.presentation"
                            ),
                            key="scr_pn_pptx",
                            type="primary",
                        )
                with _pn_ec2:
                    if _pn_meta:
                        st.caption(
                            f"{_pn_meta['paineis']} painéis em {_pn_meta['slides']} slide(s), "
                            f"{_pn_meta['paineis_por_slide']} por slide em quadrantes iguais. "
                            "Gráficos nativos do Office (editáveis, com os dados embutidos), "
                            f"eixo e rótulos em `{_pn_meta['formato_percentual']}` e rótulo "
                            "apenas no último período de cada série."
                        )

    # --- Panorama -----------------------------------------------------
    with _scr_por_key["panorama"]:
        _pan = scr_spec.construir_panorama(_scr_df, metrica=_scr_metrica, data_base=_scr_data_base)

        _kpi_cols = st.columns(len(_pan["kpis"]))
        for _col, (_, _kpi) in zip(_kpi_cols, _pan["kpis"].iterrows()):
            _delta = scr_spec.formatar_delta_kpi(_kpi["delta_mm"], _kpi["formato"])
            _col.metric(
                _kpi["rotulo"],
                _scr_fmt(_kpi["valor"], _kpi["formato"]),
                delta=_delta,
                delta_color="inverse" if _kpi["formato"] == "percentual" else "normal",
            )

        _scr_avisar_quebras(_pan["quebras"])

        _fig = px.line(
            _pan["serie"],
            x="data_base",
            y="valor",
            color="recorte",
            color_discrete_sequence=SCR_PALETTE,
            markers=False,
        )
        _scr_marcar_quebras(_fig, _pan["quebras"])
        st.plotly_chart(
            _scr_layout(_fig, titulo_y=scr_q.METRICAS[_scr_metrica].rotulo),
            use_container_width=True,
            config=SCR_PLOTLY_CONFIG,
        )

        with st.expander("composição da carteira (a vencer x vencida)", expanded=False):
            _comp = _pan["composicao"].melt(
                id_vars="data_base", var_name="faixa", value_name="valor"
            )
            _fig_comp = px.bar(
                _comp,
                x="data_base",
                y="valor",
                color="faixa",
                color_discrete_sequence=SCR_PALETTE,
            )
            st.plotly_chart(
                _scr_layout(_fig_comp, percentual=False, titulo_y="R$ mil"),
                use_container_width=True,
                config=SCR_PLOTLY_CONFIG,
            )

    # --- Produto ------------------------------------------------------
    with _scr_por_key["produto"]:
        _col_nivel, _col_corte = st.columns([1, 1.4])
        with _col_nivel:
            _nivel = st.radio(
                "nível de produto",
                ["submodalidade", "modalidade"],
                horizontal=True,
                key="scr_nivel_produto",
            )
        with _col_corte:
            _corte_bi = st.slider(
                "carteira mínima no ranking (R$ bi)",
                0.0, 20.0,
                scr_spec.CARTEIRA_MINIMA_PADRAO_RS_MIL / 1e6,
                step=0.5,
                key="scr_corte_produto",
                help="Sem corte de materialidade a cauda longa domina o ranking.",
            )

        _prod = scr_spec.construir_por_produto(
            _scr_df,
            metrica=_scr_metrica,
            nivel=_nivel,
            data_base=_scr_data_base,
            carteira_minima_rs_mil=_corte_bi * 1e6,
        )

        if _prod["legado_ocultado"]:
            st.caption(f"ℹ️ {scr_spec.NOTA_LEGADO}")

        _rank = _prod["ranking"].copy()
        if _rank.empty:
            st.info("Nenhum produto acima do corte de carteira selecionado.")
        else:
            _rank["carteira"] = _rank["denominador"].map(scr_q.formatar_reais_de_mil)
            _fig_rank = px.bar(
                _rank.sort_values("valor"),
                x="valor",
                y=_nivel,
                orientation="h",
                color="valor",
                color_continuous_scale="Reds",
                custom_data=["carteira"],
            )
            _fig_rank.update_traces(
                hovertemplate="%{y}<br>%{x:.2%}<br>carteira %{customdata[0]}<extra></extra>"
            )
            _fig_rank.update_layout(
                height=max(360, 22 * len(_rank)),
                margin=dict(l=10, r=10, t=30, b=10),
                coloraxis_showscale=False,
                xaxis_tickformat=".1%",
                yaxis_title="",
                xaxis_title=scr_q.METRICAS[_scr_metrica].rotulo,
            )
            st.plotly_chart(_fig_rank, use_container_width=True, config=SCR_PLOTLY_CONFIG)

        if not _prod["series"].empty:
            st.markdown("**Evolução dos produtos no topo do ranking**")
            _fig_series = px.line(
                _prod["series"],
                x="data_base",
                y="valor",
                color=_nivel,
                color_discrete_sequence=SCR_PALETTE,
                facet_col=_nivel,
                facet_col_wrap=3,
                height=620,
            )
            _fig_series.for_each_annotation(
                lambda a: a.update(text=a.text.split("=")[-1][:38], font_size=11)
            )
            _fig_series.update_layout(
                showlegend=False, margin=dict(l=10, r=10, t=40, b=10)
            )
            _fig_series.update_yaxes(tickformat=".1%")
            st.plotly_chart(_fig_series, use_container_width=True, config=SCR_PLOTLY_CONFIG)

        if not _prod["heatmap"].empty:
            with st.expander("heatmap produto × data-base", expanded=False):
                _fig_hm = px.imshow(
                    _prod["heatmap"],
                    color_continuous_scale="Reds",
                    aspect="auto",
                    labels=dict(color=scr_q.METRICAS[_scr_metrica].rotulo),
                )
                _fig_hm.update_layout(height=420, margin=dict(l=10, r=10, t=30, b=10))
                st.plotly_chart(_fig_hm, use_container_width=True, config=SCR_PLOTLY_CONFIG)

    # --- Renda / porte ------------------------------------------------
    with _scr_por_key["renda"]:
        st.caption(scr_spec.NOTA_PORTE_COMPARTILHADO)
        _col_tipo, _col_idx = st.columns([1, 1])
        with _col_tipo:
            _porte_cliente = st.radio(
                "critério de porte",
                ["PF (faixa de renda)", "PJ (porte por faturamento)"],
                horizontal=True,
                key="scr_porte_cliente",
            )
        with _col_idx:
            _indexar = st.toggle(
                "indexar séries a 100 no início",
                value=False,
                key="scr_indexar_porte",
                help="Compara a dinâmica das faixas, e não o nível.",
            )

        _cliente_porte = "PF" if _porte_cliente.startswith("PF") else "PJ"
        _sm = _scr_salario_minimo(_scr_data_base) if _cliente_porte == "PF" else None
        _porte = scr_spec.construir_por_porte(
            _scr_df,
            cliente=_cliente_porte,
            metrica=_scr_metrica,
            data_base=_scr_data_base,
            salario_minimo=_sm,
            indexar_series=_indexar,
        )

        if _porte["barras"].empty:
            st.info(f"Sem dados de {_cliente_porte} no recorte selecionado.")
        else:
            _barras = _porte["barras"].copy()
            _barras["carteira"] = _barras["denominador"].map(scr_q.formatar_reais_de_mil)
            _fig_porte = px.bar(
                _barras,
                x="porte",
                y="valor",
                color="valor",
                color_continuous_scale="Reds",
                custom_data=["rotulo_faixa", "carteira"],
            )
            _fig_porte.update_traces(
                hovertemplate=(
                    "%{x}<br>%{y:.2%}<br>%{customdata[0]}<br>"
                    "carteira %{customdata[1]}<extra></extra>"
                )
            )
            _fig_porte.update_layout(
                height=400,
                margin=dict(l=10, r=10, t=30, b=10),
                coloraxis_showscale=False,
                yaxis_tickformat=".1%",
                xaxis_title="",
                yaxis_title=scr_q.METRICAS[_scr_metrica].rotulo,
            )
            st.plotly_chart(_fig_porte, use_container_width=True, config=SCR_PLOTLY_CONFIG)

            if _cliente_porte == "PF" and _sm:
                st.caption(
                    f"Faixas convertidas pelo salário mínimo de {_scr_data_base} "
                    f"(R$ {_sm:,.0f}, SGS 1619).".replace(",", ".")
                )

        if _cliente_porte == "PJ" and _porte["criterios_pj"] is not None:
            with st.expander("o que são micro, pequena, média e grande empresa", expanded=True):
                st.dataframe(
                    _porte["criterios_pj"],
                    hide_index=True,
                    use_container_width=True,
                    column_config={
                        "porte": st.column_config.TextColumn("porte", width="small"),
                        "criterio": st.column_config.TextColumn("critério (Anexos 24/25 do doc 3040)"),
                    },
                )
                st.caption(
                    "Os limites são nominais e nunca foram corrigidos por inflação "
                    "(LC 155/2016 e Lei 11.638/2007). Ao longo da série há migração "
                    "puramente inflacionária de porte: empresa que não cresceu em "
                    "termos reais sobe de faixa."
                )

        if not _porte["series"].empty:
            _coluna_valor = "valor_indexado" if _indexar else "valor"
            _fig_ps = px.line(
                _porte["series"],
                x="data_base",
                y=_coluna_valor,
                color="porte",
                color_discrete_sequence=SCR_PALETTE,
            )
            _scr_marcar_quebras(_fig_ps, _porte["quebras"])
            st.plotly_chart(
                _scr_layout(
                    _fig_ps,
                    altura=420,
                    percentual=not _indexar,
                    titulo_y="índice (100 = início)" if _indexar else scr_q.METRICAS[_scr_metrica].rotulo,
                ),
                use_container_width=True,
                config=SCR_PLOTLY_CONFIG,
            )

        if not _porte["cruzamento_produto"].empty:
            with st.expander("faixa × produto", expanded=False):
                _fig_cruz = px.imshow(
                    _porte["cruzamento_produto"],
                    color_continuous_scale="Reds",
                    aspect="auto",
                    labels=dict(color=scr_q.METRICAS[_scr_metrica].rotulo),
                )
                _fig_cruz.update_layout(height=460, margin=dict(l=10, r=10, t=30, b=10))
                st.plotly_chart(_fig_cruz, use_container_width=True, config=SCR_PLOTLY_CONFIG)

    # --- Região -------------------------------------------------------
    if "regiao" in _scr_por_key:
        with _scr_por_key["regiao"]:
            st.caption(scr_spec.NOTA_UF_CEP)
            _nivel_geo = st.radio(
                "nível geográfico",
                ["uf", "regiao"],
                horizontal=True,
                format_func=lambda v: "UF (27)" if v == "uf" else "Região (5)",
                key="scr_nivel_geo",
            )
            _geo = scr_spec.construir_por_regiao(
                _scr_df, metrica=_scr_metrica, data_base=_scr_data_base, nivel=_nivel_geo
            )

            _col_mapa, _col_rank = st.columns([1.3, 1])
            _geojson = scr_spec.carregar_geojson_uf()

            with _col_mapa:
                if _geojson is not None and not _geo["mapa"].empty:
                    _fig_mapa = px.choropleth(
                        _geo["mapa"],
                        geojson=_geojson,
                        locations="codigo_ibge",
                        featureidkey=_geo["featureidkey"],
                        color="valor",
                        color_continuous_scale="RdYlGn_r",
                        color_continuous_midpoint=_geo["media_brasil"],
                        hover_name="uf_nome",
                        hover_data={"codigo_ibge": False, "valor": ":.2%", "regiao": True},
                    )
                    _fig_mapa.update_geos(
                        visible=False,
                        projection_type=scr_spec.MAPA_PROJECAO,
                        lonaxis_range=list(scr_spec.MAPA_LON_RANGE),
                        lataxis_range=list(scr_spec.MAPA_LAT_RANGE),
                        bgcolor="rgba(0,0,0,0)",
                    )
                    _fig_mapa.update_layout(
                        height=460,
                        margin=dict(l=0, r=0, t=30, b=0),
                        coloraxis_colorbar=dict(tickformat=".1%", title=""),
                    )
                    st.plotly_chart(_fig_mapa, use_container_width=True, config=SCR_PLOTLY_CONFIG)
                    if _geo["media_brasil"] is not None:
                        st.caption(
                            "Escala ancorada na média Brasil de "
                            f"{_scr_fmt(_geo['media_brasil'])} em {_geo['data_base']}."
                        )
                else:
                    st.info(
                        "Malha de UFs indisponível (`data/bundled/geo/uf_brasil.geojson`). "
                        "O ranking ao lado cobre a mesma leitura."
                    )

            with _col_rank:
                _rank_geo = _geo["ranking"].copy()
                if not _rank_geo.empty:
                    _rank_geo["carteira"] = _rank_geo["denominador"].map(
                        scr_q.formatar_reais_de_mil
                    )
                    _rank_geo["taxa"] = _rank_geo["valor"].map(_scr_fmt)
                    st.dataframe(
                        _rank_geo[[_nivel_geo, "taxa", "carteira"]],
                        hide_index=True,
                        use_container_width=True,
                        height=460,
                        column_config={
                            _nivel_geo: st.column_config.TextColumn(
                                "UF" if _nivel_geo == "uf" else "região", width="small"
                            ),
                            "taxa": st.column_config.TextColumn(
                                scr_q.METRICAS[_scr_metrica].rotulo, width="small"
                            ),
                            "carteira": st.column_config.TextColumn("carteira"),
                        },
                    )

            _fig_geo = px.line(
                _geo["series"],
                x="data_base",
                y="valor",
                color="regiao",
                color_discrete_sequence=SCR_PALETTE,
            )
            _scr_marcar_quebras(_fig_geo, _geo["quebras"])
            st.plotly_chart(
                _scr_layout(_fig_geo, altura=400, titulo_y=scr_q.METRICAS[_scr_metrica].rotulo),
                use_container_width=True,
                config=SCR_PLOTLY_CONFIG,
            )

            if not _geo["cruzamento_porte"].empty:
                with st.expander("região × faixa de porte", expanded=False):
                    _fig_rp = px.imshow(
                        _geo["cruzamento_porte"],
                        color_continuous_scale="Reds",
                        aspect="auto",
                        labels=dict(color=scr_q.METRICAS[_scr_metrica].rotulo),
                    )
                    _fig_rp.update_layout(height=380, margin=dict(l=10, r=10, t=30, b=10))
                    st.plotly_chart(_fig_rp, use_container_width=True, config=SCR_PLOTLY_CONFIG)

    # --- Segmento -----------------------------------------------------
    if "segmento" in _scr_por_key:
        with _scr_por_key["segmento"]:
            _seg = scr_spec.construir_por_segmento(
                _scr_df,
                metrica=_scr_metrica,
                data_base=_scr_data_base,
                dim_segmento=_scr_dimensoes().get("segmento"),
            )

            _barras_seg = _seg["barras"].copy()
            if not _barras_seg.empty:
                _barras_seg["carteira"] = _barras_seg["denominador"].map(
                    scr_q.formatar_reais_de_mil
                )
                _fig_seg = px.bar(
                    _barras_seg,
                    x="segmento",
                    y="valor",
                    color="segmento",
                    color_discrete_sequence=SCR_PALETTE,
                    custom_data=["carteira"],
                )
                _fig_seg.update_traces(
                    hovertemplate="%{x}<br>%{y:.2%}<br>carteira %{customdata[0]}<extra></extra>"
                )
                _fig_seg.update_layout(
                    height=400,
                    margin=dict(l=10, r=10, t=30, b=10),
                    showlegend=False,
                    yaxis_tickformat=".1%",
                    xaxis_title="",
                    yaxis_title=scr_q.METRICAS[_scr_metrica].rotulo,
                )
                st.plotly_chart(_fig_seg, use_container_width=True, config=SCR_PLOTLY_CONFIG)

            _fig_seg_serie = px.line(
                _seg["series"],
                x="data_base",
                y="valor",
                color="segmento",
                color_discrete_sequence=SCR_PALETTE,
            )
            _scr_marcar_quebras(_fig_seg_serie, _seg["quebras"])
            st.plotly_chart(
                _scr_layout(_fig_seg_serie, altura=420, titulo_y=scr_q.METRICAS[_scr_metrica].rotulo),
                use_container_width=True,
                config=SCR_PLOTLY_CONFIG,
            )

            if not _seg["vigencia"].empty:
                st.caption(
                    "Cada segmento entra na série na data-base em que aparece na base: "
                    + " · ".join(
                        f"{linha['segmento']} desde {linha['primeira_data_base']}"
                        for _, linha in _seg["vigencia"].iterrows()
                        if pd.notna(linha["primeira_data_base"])
                    )
                )

    # ------------------------------------------------------------------
    # Rodapé
    # ------------------------------------------------------------------
    _scr_rodape = scr_spec.rodape(
        scr_q.filtrar(_scr_df, data_base_inicial=_scr_data_base, data_base_final=_scr_data_base),
        data_base=_scr_data_base,
    )
    st.markdown("---")
    _sup = _scr_rodape["supressao"]
    _share = _sup["share_carteira"]
    st.caption(
        f"Data-base {_scr_rodape['data_base']} · série disponível desde "
        f"{_scr_rodape['primeira_data_base_disponivel']} · "
        + (
            f"{_share:.1%} da carteira do recorte tem contagem de operações "
            "suprimida pelo BCB (o nº de operações fica subestimado)."
            if _share
            else "sem supressão de contagem no recorte."
        )
    )
    for _nota in _scr_rodape["notas"]:
        st.caption(_nota)
    st.caption(
        "Fontes: "
        + " · ".join(f"[{f['rotulo']}]({f['url']})" for f in _scr_rodape["fontes"])
    )

    _scr_export = _scr_df.copy()
    st.download_button(
        "baixar recorte visível (CSV)",
        data=_scr_export.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"scr_data_{_scr_data_base}.csv",
        mime="text/csv",
        key="scr_download",
    )
