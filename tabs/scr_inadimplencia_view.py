"""Renderer compacto da inadimplência baseada no SCR.data."""

from __future__ import annotations

from collections import defaultdict

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st


def render_scr_inadimplencia(get_cache_manager) -> None:
    from tabs import scr_inadimplencia as scr_spec
    from utils import scr_data_query as scr_q
    from utils import scr_pptx_export as scr_pptx
    from utils.sgs_credit_analytics import (
        _add_last_line_labels,
        _valid_trace_dates,
        eixo_datas_adaptativo,
        formatar_competencia,
    )
    from utils.sgs_credit_pptx_export import exportar_figuras_pptx

    plotly_config = {"displayModeBar": "hover", "displaylogo": False, "responsive": True}
    palette = list(scr_spec.PALETA_CATEGORICA)

    st.markdown(f"#### {scr_spec.TITLE}")
    st.caption("Inadimplência e ativo problemático por modalidade, renda e região.")

    @st.cache_resource(show_spinner=False)
    def _cache():
        manager = get_cache_manager()
        return manager.get_cache("scr_data") if manager else None

    @st.cache_data(ttl=3600, show_spinner=False)
    def _periodos_disponiveis() -> tuple[str, ...]:
        cache = _cache()
        if cache is None:
            return ()
        try:
            resultado = cache.bootstrap_local_assets()
            if not resultado.sucesso:
                return ()
            periodos = cache.get_info().get("periodos") or []
            if periodos:
                return tuple(sorted(str(periodo) for periodo in periodos))
            datas = pd.read_parquet(cache.arquivo_dados, columns=["data_base"])
            return tuple(sorted(datas["data_base"].astype(str).unique()))
        except Exception:
            return ()

    @st.cache_data(ttl=3600, show_spinner="Carregando SCR.data...")
    def _detalhe(anos: tuple[int, ...]) -> pd.DataFrame:
        cache = _cache()
        if cache is None:
            return pd.DataFrame()
        try:
            return cache.carregar_detalhe(anos=list(anos))
        except Exception as exc:
            st.error(f"Falha ao carregar o SCR.data: {exc}")
            return pd.DataFrame()

    def _fmt(valor: float | None) -> str:
        return scr_q.formatar_valor(valor, "percentual")

    def _marcar_quebras(fig: go.Figure, quebras: list[dict]) -> go.Figure:
        return scr_spec.marcar_quebras(fig, quebras)

    def _layout(fig: go.Figure, *, altura: int = 390) -> go.Figure:
        datas = _valid_trace_dates(fig)
        tickvals, ticktext = eixo_datas_adaptativo(datas)
        tickangle = (
            -35
            if any(
                (right - left).days <= 45
                for left, right in zip(tickvals, tickvals[1:])
            )
            else 0
        )
        fig.update_layout(
            height=altura,
            margin=dict(l=10, r=70, t=24, b=12),
            paper_bgcolor="#FFFFFF",
            plot_bgcolor="#FFFFFF",
            font=dict(family="Arial", size=13, color=scr_spec.COR_TEXTO),
            legend=dict(orientation="h", yanchor="top", y=-0.13, x=0, font=dict(size=11)),
            hovermode="x unified",
            separators=",.",
            yaxis_title=scr_q.METRICAS[_metrica].rotulo,
        )
        fig.update_yaxes(
            tickformat=".2%", showgrid=True, gridcolor=scr_spec.COR_GRADE,
            zeroline=False, tickfont=dict(size=11),
        )
        fig.update_xaxes(
            showgrid=False,
            tickmode="array" if tickvals else "auto",
            tickvals=tickvals or None,
            ticktext=ticktext or None,
            tickangle=tickangle,
            tickfont=dict(size=11),
        )
        return fig

    def _figura_painel(painel, quebra_spec, eixo_zero: bool) -> go.Figure:
        fig = go.Figure()
        endpoints: list[tuple[pd.Timestamp, float, str, str]] = []
        tabela = painel.series.copy()
        tabela["data_base"] = pd.to_datetime(
            tabela["data_base"].astype(str) + "-01", errors="coerce"
        )
        tabela["serie"] = tabela["serie"].astype(str)
        tabela = tabela.pivot_table(
            index="data_base", columns="serie", values="valor",
            aggfunc="first", observed=True,
        ).sort_index()

        for nome in painel.ordem_series:
            if nome not in tabela.columns:
                continue
            serie = tabela[nome]
            validos = serie.dropna()
            cor = painel.cores.get(nome)
            fig.add_trace(go.Scatter(
                x=tabela.index,
                y=serie.values,
                name=scr_spec.rotulo_serie(nome, quebra_spec),
                mode="lines",
                line=dict(
                    color=cor,
                    width=2.8 if nome in painel.tracejadas else 2.2,
                    dash="dash" if nome in painel.tracejadas else "solid",
                ),
                connectgaps=False,
                cliponaxis=False,
                hovertemplate="%{x|%m/%Y}<br>%{y:.2%}<extra>%{fullData.name}</extra>",
            ))
            if not validos.empty:
                x_final = pd.Timestamp(validos.index[-1])
                y_final = float(validos.iloc[-1])
                endpoints.append(
                    (
                        x_final,
                        y_final,
                        scr_spec.formatar_percentual_2casas(y_final),
                        cor,
                    )
                )

        _add_last_line_labels(fig, endpoints, plot_height=255)
        _layout(fig, altura=355)
        fig.update_yaxes(rangemode="tozero" if eixo_zero else "normal")
        fig.update_layout(meta={
            "chart_title": painel.titulo,
            "source": "fonte: Banco Central do Brasil · SCR.data",
        })
        return fig

    def _card_header(painel, avisos: list[dict]) -> None:
        titulo_col, info_col = st.columns([0.91, 0.09], vertical_alignment="top")
        with titulo_col:
            st.markdown(f"##### {painel.titulo}")
            st.caption(f"{painel.subtitulo} · {painel.fonte}")
        with info_col:
            with st.popover("i", help="Fonte e alertas deste card"):
                st.markdown("**Metodologia**")
                st.markdown(
                    "Modalidade agregada conforme a equivalência oficial do painel "
                    "SCR.data do Banco Central."
                )
                if avisos:
                    st.markdown("**Alertas de legibilidade**")
                    for aviso in avisos:
                        st.markdown(f"- {aviso['mensagem']}")
                else:
                    st.caption("Sem alertas de legibilidade neste recorte.")

    def _figura_export_ufs(tabela: pd.DataFrame) -> go.Figure:
        if tabela.empty:
            return go.Figure()
        exportacao = tabela.sort_values(
            ["ordem_regiao", "participacao_carteira"],
            ascending=[True, False],
            kind="stable",
        )
        figura = go.Figure(go.Bar(
            x=exportacao["uf"].astype(str),
            y=exportacao["participacao_carteira"].astype(float) * 100.0,
            name="Participação",
            marker_color=scr_spec.COR_LARANJA,
        ))
        figura.update_layout(
            yaxis_title="% da carteira Brasil",
            meta={
                "chart_title": "Participação de cada UF na carteira Brasil",
                "value_format": "0.0%",
                "value_scale": 0.01,
                "label_all_points": True,
                "source": "fonte: Banco Central do Brasil · SCR.data",
            },
        )
        return figura

    periodos_disponiveis = _periodos_disponiveis()
    if not periodos_disponiveis:
        st.error("Cache SCR.data indisponível ou com schema anterior ao das modalidades oficiais.")
        return
    ultima = periodos_disponiveis[-1]

    periodos_timestamp = [pd.Timestamp(f"{periodo}-01") for periodo in periodos_disponiveis]
    ultima_timestamp = periodos_timestamp[-1]
    inicio_padrao_alvo = ultima_timestamp - pd.DateOffset(
        months=scr_spec.JANELA_PADRAO_MESES - 1
    )
    posicao_inicio = min(
        int(pd.DatetimeIndex(periodos_timestamp).searchsorted(inicio_padrao_alvo, side="left")),
        len(periodos_timestamp) - 1,
    )
    inicio_padrao = periodos_timestamp[posicao_inicio]
    opcoes_inicio = list(reversed(periodos_timestamp))

    filtro_inicio, filtro_fim, filtro_cliente, filtro_metrica = st.columns(
        [1, 1, 1, 1.35]
    )
    with filtro_inicio:
        inicio_selecionado = st.selectbox(
            "Período inicial",
            opcoes_inicio,
            index=opcoes_inicio.index(inicio_padrao),
            format_func=formatar_competencia,
            key="scr_period_start",
        )
    opcoes_fim: list[str | pd.Timestamp] = [
        "Mais recente",
        *[
            periodo for periodo in reversed(periodos_timestamp)
            if periodo >= inicio_selecionado
        ],
    ]
    fim_guardado = st.session_state.get("scr_period_end")
    if fim_guardado != "Mais recente" and fim_guardado not in opcoes_fim:
        st.session_state["scr_period_end"] = "Mais recente"
    with filtro_fim:
        fim_selecionado = st.selectbox(
            "Período final",
            opcoes_fim,
            index=0,
            format_func=lambda valor: (
                valor if isinstance(valor, str) else formatar_competencia(valor)
            ),
            key="scr_period_end",
        )
    with filtro_cliente:
        cliente_opcao = st.radio(
            "Cliente", ["PF + PJ", "PF", "PJ"], horizontal=True, key="scr_cliente"
        )
    with filtro_metrica:
        _metrica = st.selectbox(
            "Métrica", scr_q.METRICAS_PERCENTUAIS,
            index=scr_q.METRICAS_PERCENTUAIS.index(scr_q.METRICA_PADRAO),
            format_func=lambda chave: scr_q.METRICAS[chave].rotulo, key="scr_metrica",
        )

    fim_timestamp = (
        ultima_timestamp if fim_selecionado == "Mais recente" else fim_selecionado
    )
    anos = tuple(range(inicio_selecionado.year, fim_timestamp.year + 1))
    base = _detalhe(anos)
    inicio = inicio_selecionado.strftime("%Y-%m")
    fim = fim_timestamp.strftime("%Y-%m")
    base = scr_q.filtrar(base, data_base_inicial=inicio, data_base_final=fim)
    cliente = None if cliente_opcao == "PF + PJ" else cliente_opcao
    dados = scr_q.filtrar(base, cliente=cliente)
    if dados.empty:
        st.warning("Sem dados para os filtros selecionados.")
        return
    data_base = str(dados["data_base"].astype(str).max())

    aba_paineis, aba_regiao = st.tabs(["Painéis", "Brasil e regiões"])

    with aba_paineis:
        controle_quebra, controle_total, controle_zero = st.columns([1.6, 0.8, 0.9])
        quebras = [q for q in scr_spec.QUEBRAS if q.key != "segmento"]
        with controle_quebra:
            quebra_key = st.selectbox(
                "Comparar linhas por", [q.key for q in quebras],
                format_func=lambda chave: scr_spec.QUEBRAS_POR_KEY[chave].label,
                key="scr_pn_quebra",
            )
        with controle_total:
            incluir_total = st.toggle("Linha total", value=True, key="scr_pn_total")
        with controle_zero:
            eixo_zero = st.toggle("Eixo em zero", value=True, key="scr_pn_zero")

        quebra_spec = scr_spec.QUEBRAS_POR_KEY[quebra_key]
        cliente_painel = quebra_spec.exige_cliente or cliente
        base_produtos = scr_q.filtrar(
            dados, cliente=cliente_painel,
            data_base_inicial=data_base, data_base_final=data_base,
        )
        presentes = base_produtos["modalidade_bcb"].astype(str).unique().tolist()
        opcoes = scr_spec.modalidades_bcb_disponiveis(cliente_painel, presentes=presentes)
        produtos = st.multiselect(
            "Modalidades", opcoes, default=opcoes[:scr_spec.PAINEIS_POR_SLIDE],
            key="scr_pn_produtos",
            help="Classificação agregada do filtro Modalidade no SCR.data.",
        )

        paineis = scr_spec.construir_paineis(
            dados, produtos=produtos, nivel_produto="modalidade_bcb",
            quebra=quebra_key, metrica=_metrica, cliente=cliente_painel,
            faixas=scr_spec.faixas_padrao(quebra_key), incluir_total=incluir_total,
        ) if produtos else []

        avisos_por_painel: dict[str, list[dict]] = defaultdict(list)
        for aviso in scr_spec.avaliar_legibilidade(paineis):
            avisos_por_painel[aviso["painel"]].append(aviso)

        if not paineis:
            st.info("Selecione ao menos uma modalidade.")
        else:
            try:
                blob, meta = scr_pptx.exportar_paineis_pptx(
                    paineis,
                    rotulo_serie_fn=lambda nome: scr_spec.rotulo_serie(nome, quebra_spec),
                    titulo_deck=f"SCR.data · {scr_q.METRICAS[_metrica].rotulo} · {data_base}",
                )
                st.download_button(
                    "Baixar PPTX desta aba", data=blob,
                    file_name=f"scr_paineis_{data_base}.pptx",
                    mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                    key="scr_pn_pptx", type="primary",
                    help=f"{meta['paineis']} cards Office nativos; até 4 por slide.",
                )
            except Exception as exc:
                st.error(f"Falha ao montar o PPTX: {exc}")

            for inicio_painel in range(0, len(paineis), 2):
                colunas = st.columns(2)
                for coluna, painel in zip(colunas, paineis[inicio_painel:inicio_painel + 2]):
                    with coluna:
                        _card_header(painel, avisos_por_painel[painel.titulo])
                        st.plotly_chart(
                            _figura_painel(painel, quebra_spec, eixo_zero),
                            width="stretch", config=plotly_config,
                        )

    with aba_regiao:
        opcoes_regiao = scr_spec.modalidades_bcb_disponiveis(
            cliente, presentes=dados["modalidade_bcb"].astype(str).unique().tolist()
        )
        filtro_modalidade, filtro_geo = st.columns([2.1, 1])
        with filtro_modalidade:
            modalidade_regiao = st.selectbox(
                "Modalidade", opcoes_regiao, key="scr_regiao_modalidade"
            )
        with filtro_geo:
            nivel_geo = st.radio(
                "Recorte", ["uf", "regiao"], horizontal=True,
                format_func=lambda valor: "UF" if valor == "uf" else "Região",
                key="scr_nivel_geo",
            )

        dados_regiao = scr_q.filtrar(dados, modalidade_bcb=modalidade_regiao)
        geo = scr_spec.construir_por_regiao(
            dados_regiao, metrica=_metrica, data_base=data_base, nivel=nivel_geo
        )

        resumo_brasil, resumo_metrica, resumo_data = st.columns(3)
        resumo_brasil.metric(
            "Carteira Brasil",
            scr_q.formatar_reais_de_mil(geo["carteira_brasil_rs_mil"]),
        )
        resumo_metrica.metric(
            scr_q.METRICAS[_metrica].rotulo,
            _fmt(geo["media_brasil"]),
        )
        resumo_data.metric("Data-base", formatar_competencia(f"{data_base}-01"))

        mapa_col, ranking_col = st.columns([1.35, 1])
        with mapa_col:
            geojson = scr_spec.carregar_geojson_uf()
            if geojson is not None and not geo["mapa"].empty:
                figura_mapa = px.choropleth(
                    geo["mapa"], geojson=geojson, locations="codigo_ibge",
                    featureidkey=geo["featureidkey"], color="valor",
                    color_continuous_scale="Oranges", hover_name="uf_nome",
                    hover_data={"codigo_ibge": False, "valor": ":.2%", "regiao": True},
                )
                figura_mapa.update_geos(
                    visible=False, projection_type=scr_spec.MAPA_PROJECAO,
                    lonaxis_range=list(scr_spec.MAPA_LON_RANGE),
                    lataxis_range=list(scr_spec.MAPA_LAT_RANGE),
                    bgcolor="rgba(0,0,0,0)",
                )
                figura_mapa.update_layout(
                    height=430, margin=dict(l=0, r=0, t=10, b=0),
                    coloraxis_colorbar=dict(tickformat=".1%", title=""),
                    font=dict(size=13),
                )
                st.plotly_chart(figura_mapa, width="stretch", config=plotly_config)
        with ranking_col:
            ranking = geo["ranking"].copy()
            if not ranking.empty:
                ranking["taxa"] = ranking["valor"].map(_fmt)
                ranking["carteira"] = ranking["denominador"].map(
                    scr_q.formatar_reais_de_mil
                )
                st.dataframe(
                    ranking[[nivel_geo, "taxa", "carteira"]], hide_index=True,
                    width="stretch", height=430,
                    column_config={
                        nivel_geo: st.column_config.TextColumn(
                            "UF" if nivel_geo == "uf" else "Região"
                        ),
                        "taxa": st.column_config.TextColumn(
                            scr_q.METRICAS[_metrica].rotulo
                        ),
                        "carteira": st.column_config.TextColumn("Carteira"),
                    },
                )

        figura_regiao = go.Figure()
        endpoints_regiao: list[tuple[pd.Timestamp, float, str, str]] = []
        for posicao, nome in enumerate(scr_spec.ORDEM_REGIOES):
            serie = geo["series"][geo["series"]["regiao"].astype(str) == nome]
            if serie.empty:
                continue
            x = pd.to_datetime(serie["data_base"].astype(str) + "-01")
            y = pd.to_numeric(serie["valor"], errors="coerce")
            cor = palette[posicao % len(palette)]
            figura_regiao.add_trace(go.Scatter(
                x=x, y=y, name=nome, mode="lines", line=dict(color=cor, width=2.3),
                hovertemplate="%{x|%m/%Y}<br>%{y:.2%}<extra>%{fullData.name}</extra>",
            ))
            validos = y.dropna()
            if not validos.empty:
                indice = validos.index[-1]
                endpoints_regiao.append(
                    (
                        pd.Timestamp(x.loc[indice]),
                        float(y.loc[indice]),
                        scr_spec.formatar_percentual_2casas(float(y.loc[indice])),
                        cor,
                    )
                )
        _add_last_line_labels(figura_regiao, endpoints_regiao, plot_height=285)
        _marcar_quebras(figura_regiao, geo["quebras"])
        _layout(figura_regiao, altura=390)
        figura_regiao.update_layout(meta={
            "chart_title": f"{modalidade_regiao} por região",
            "value_format": "0.00%",
            "value_scale": 1.0,
            "source": "fonte: Banco Central do Brasil · SCR.data",
        })

        titulo_col, info_col = st.columns([0.94, 0.06])
        with titulo_col:
            st.markdown(f"##### **{modalidade_regiao}** por região")
        with info_col:
            with st.popover("i", help="Metodologia regional"):
                st.markdown(
                    "A UF corresponde ao CEP do tomador. A taxa é a razão entre "
                    "a soma da carteira inadimplida e a soma da carteira ativa. "
                    "As definições completas estão em **Glossário > SCR.data**."
                )
        st.plotly_chart(figura_regiao, width="stretch", config=plotly_config)

        figura_ufs_export = _figura_export_ufs(geo["mapa"])
        blob_regiao, meta_regiao = exportar_figuras_pptx(
            [figura_ufs_export, figura_regiao],
            titulo_deck=f"SCR.data · {modalidade_regiao} · {data_base}",
        )
        export_col, csv_col = st.columns(2)
        with export_col:
            st.download_button(
                "Baixar PPTX desta aba", data=blob_regiao,
                file_name=f"scr_regiao_{data_base}.pptx",
                mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                key="scr_regiao_pptx", type="primary",
                help=f"{meta_regiao['paineis']} gráficos Office nativos.",
            )
        with csv_col:
            st.download_button(
                "Baixar dados (CSV)", data=dados_regiao.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"scr_data_{data_base}.csv", mime="text/csv", key="scr_download",
            )
