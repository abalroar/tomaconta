"""Renderer compacto da inadimplência baseada no SCR.data.

Um card por linha, em largura total: com até nove séries no mesmo painel, dois
cards lado a lado deixavam cada um com metade da largura e as linhas coladas.
"""

from __future__ import annotations

from collections import defaultdict

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from tabs import scr_inadimplencia as scr_spec
from utils.sgs_credit_analytics import (
    ALTURA_COMPACTA,
    ITAU_BLACK,
    ITAU_ORANGE,
    LARGURA_LINHA_AGREGADO,
    LARGURA_LINHA_CONTEXTO,
    LARGURA_LINHA_FOCO,
    TAMANHO_ROTULO_PX,
    aplicar_estilo,
    encurtar_rotulo,
    formatar_numero,
    posicionar_rotulos_finais,
)


# Centroide do maior anel de cada UF, calculado a partir do geojson versionado
# em data/bundled/geo/uf_brasil.geojson. É onde o rótulo do mapa pousa.
CENTROIDES_UF = {
    "11": (-62.8412, -10.9105), "12": (-70.4746, -9.2147), "13": (-64.6533, -4.1535),
    "14": (-61.3897, 2.0845), "15": (-53.0732, -3.9831), "16": (-51.9690, 1.4437),
    "17": (-48.3296, -10.1478), "21": (-45.2903, -5.0798), "22": (-42.9697, -7.3862),
    "23": (-39.6119, -5.0940), "24": (-36.6720, -5.8380), "25": (-36.8326, -7.1220),
    "26": (-38.0057, -8.3279), "27": (-36.6225, -9.5161), "28": (-37.4429, -10.5805),
    "29": (-41.7210, -12.4757), "31": (-44.6743, -18.4553), "32": (-40.6747, -19.5744),
    "33": (-42.6631, -22.1927), "35": (-48.7339, -22.2653), "41": (-51.6182, -24.6351),
    "42": (-50.4724, -27.2464), "43": (-53.3157, -29.7100), "50": (-54.8452, -20.3278),
    "51": (-55.9124, -12.9492), "52": (-49.6251, -16.0408), "53": (-47.7998, -15.7815),
}

# UFs pequenas demais para caber o rótulo dentro: o texto sai para fora, com
# uma linha-guia curta ligando o rótulo ao estado.
ROTULO_DESLOCADO_UF = {
    "24": (-31.0, -5.4),   # RN
    "25": (-31.0, -7.2),   # PB
    "26": (-31.0, -9.0),   # PE
    "27": (-31.0, -10.8),  # AL
    "28": (-31.0, -12.6),  # SE
    "32": (-33.5, -19.6),  # ES
    "33": (-33.5, -23.4),  # RJ
    "53": (-40.5, -13.6),  # DF
}

MAPA_LON_RANGE_ROTULADO = (-74.5, -27.0)

# Escala do mapa dentro da família da casa: cinza claro -> laranja claro ->
# laranja-vivo -> laranja escuro. A escala "Oranges" da biblioteca começava em
# rgb(255,245,235), que some no papel branco, e terminava em marrom.
ESCALA_MAPA = [
    [0.00, "#EFEFEF"],
    [0.20, "#F7D9B4"],
    [0.45, "#F7B267"],
    [0.70, "#EC7000"],
    [1.00, "#8F3E00"],
]
COR_BORDA_UF = "#7A7A7A"


# =============================================================================
# CONSTRUTORES DE FIGURA
# =============================================================================
# Fora do render para que o deck completo consiga montá-las sem Streamlit.

def figura_painel(
    painel,
    quebra_spec,
    *,
    eixo_zero: bool = True,
    quebras_serie=(),
    rotulo_metrica: str = "",
) -> go.Figure:
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

    desenhadas = [n for n in painel.ordem_series if n in tabela.columns]
    # Em meia largura o nome vai para a ponta da linha já a partir da
    # terceira série: a legenda horizontal quebraria em duas fileiras.
    rotulo_direto = len(desenhadas) > 2
    for nome in desenhadas:
        serie = tabela[nome]
        validos = serie.dropna()
        cor = painel.cores.get(nome)
        tracejada = nome in painel.tracejadas
        agregado = nome == scr_spec.SERIE_TOTAL
        if agregado:
            largura = LARGURA_LINHA_AGREGADO
        elif nome == desenhadas[0]:
            largura = LARGURA_LINHA_FOCO
        else:
            largura = LARGURA_LINHA_CONTEXTO
        fig.add_trace(go.Scatter(
            x=tabela.index,
            y=serie.values,
            name=scr_spec.rotulo_serie(nome, quebra_spec),
            mode="lines",
            line=dict(
                color=cor,
                width=largura,
                dash="dash" if tracejada else "solid",
            ),
            connectgaps=False,
            cliponaxis=False,
            hovertemplate="%{x|%m/%Y}<br>%{y:.2%}<extra>%{fullData.name}</extra>",
        ))
        if not validos.empty:
            y_final = float(validos.iloc[-1])
            numero = scr_spec.formatar_percentual_2casas(y_final)
            rotulo = scr_spec.rotulo_serie(nome, quebra_spec)
            endpoints.append((
                pd.Timestamp(validos.index[-1]),
                y_final,
                f"{encurtar_rotulo(rotulo)}<br>{numero}" if rotulo_direto
                else numero,
                cor,
            ))

    aplicar_estilo(
        fig,
        title=painel.titulo,
        y_title=rotulo_metrica,
        height=ALTURA_COMPACTA,
        legenda=not rotulo_direto,
        rotulo_direto=rotulo_direto,
        compacto=True,
    )
    fig.update_yaxes(tickformat=".2%")
    posicionar_rotulos_finais(fig, [(endpoints, "y", None)])
    fig.update_yaxes(rangemode="tozero" if eixo_zero else "normal")
    scr_spec.marcar_quebras(fig, quebras_serie)
    fig.update_layout(meta={
        "chart_title": painel.titulo,
        "value_format": "0.00%",
        "value_scale": 1.0,
        "source": "fonte: Banco Central do Brasil · SCR.data",
    })
    return fig


def figura_por_uf(tabela: pd.DataFrame, rotulo_metrica: str) -> go.Figure:
    """A mesma variável do mapa, em barras — é o que vai para o PPTX.

    Mapa não existe como gráfico nativo do Office; esta barra carrega
    exatamente o que o mapa colore, na mesma métrica, e fica também na tela.
    """
    if tabela.empty:
        return go.Figure()
    ordenada = tabela.sort_values("valor", ascending=False, kind="stable")
    valores = ordenada["valor"].astype(float) * 100.0
    figura = go.Figure(go.Bar(
        x=ordenada["uf"].astype(str),
        y=valores,
        name=rotulo_metrica,
        marker_color=ITAU_ORANGE,
        text=[formatar_numero(valor, 2) for valor in valores],
        textposition="outside",
        textangle=0,
        textfont={"size": TAMANHO_ROTULO_PX, "color": ITAU_BLACK, "family": "Arial"},
        cliponaxis=False,
        hovertemplate="%{y:.2f}%<extra>%{x}</extra>",
    ))
    aplicar_estilo(
        figura,
        title=f"{rotulo_metrica} por UF",
        y_title=f"{rotulo_metrica} (%)",
        height=380,
        legenda=False,
    )
    figura.update_xaxes(tickmode="auto", tickvals=None, ticktext=None, tickangle=0)
    figura.update_layout(meta={
        "chart_title": f"{rotulo_metrica} por UF",
        "value_format": "0.00%",
        "value_scale": 0.01,
        "label_all_points": True,
        "source": "fonte: Banco Central do Brasil · SCR.data",
    })
    return figura


def figura_por_regiao(geo, *, rotulo_metrica: str, titulo: str) -> go.Figure:
    """Série da métrica por região, uma linha por macrorregião."""
    figura = go.Figure()
    endpoints: list[tuple[pd.Timestamp, float, str, str]] = []
    cores = scr_spec.cores_das_series(
        list(scr_spec.ORDEM_REGIOES), scr_spec.QUEBRAS_POR_KEY["regiao"]
    )
    for posicao, nome in enumerate(scr_spec.ORDEM_REGIOES):
        serie = geo["series"][geo["series"]["regiao"].astype(str) == nome]
        if serie.empty:
            continue
        x = pd.to_datetime(serie["data_base"].astype(str) + "-01")
        y = pd.to_numeric(serie["valor"], errors="coerce")
        cor = cores.get(nome, ITAU_ORANGE)
        figura.add_trace(go.Scatter(
            x=x, y=y, name=nome, mode="lines",
            line=dict(
                color=cor,
                width=LARGURA_LINHA_FOCO if posicao == 0 else LARGURA_LINHA_CONTEXTO,
            ),
            connectgaps=False, cliponaxis=False,
            hovertemplate="%{x|%m/%Y}<br>%{y:.2%}<extra>%{fullData.name}</extra>",
        ))
        validos = y.dropna()
        if not validos.empty:
            indice = validos.index[-1]
            valor_final = float(y.loc[indice])
            endpoints.append((
                pd.Timestamp(x.loc[indice]),
                valor_final,
                f"{encurtar_rotulo(nome)}<br>"
                f"{scr_spec.formatar_percentual_2casas(valor_final)}",
                cor,
            ))
    aplicar_estilo(
        figura, title=titulo, y_title=rotulo_metrica,
        height=ALTURA_COMPACTA, legenda=False, rotulo_direto=True, compacto=True,
    )
    figura.update_yaxes(tickformat=".2%")
    posicionar_rotulos_finais(figura, [(endpoints, "y", None)])
    scr_spec.marcar_quebras(figura, geo["quebras"])
    figura.update_layout(meta={
        "chart_title": titulo,
        "value_format": "0.00%",
        "value_scale": 1.0,
        "source": "fonte: Banco Central do Brasil · SCR.data",
    })
    return figura


def _memo_pptx(chave: str, construir):
    """Monta o deck só quando os filtros mudam.

    Antes o arquivo era remontado a cada interação, mesmo sem ninguém clicar em
    baixar: trocar um filtro reconstruía o deck inteiro antes de a tela
    responder.
    """
    memo = st.session_state.setdefault("_scr_pptx_memo", {})
    if memo.get("chave") != chave:
        memo["chave"] = chave
        memo["valor"] = construir()
    return memo["valor"]


def render_scr_inadimplencia(get_cache_manager) -> None:
    from utils import scr_data_query as scr_q
    from utils import scr_pptx_export as scr_pptx
    from utils.sgs_credit_analytics import formatar_competencia
    from utils.sgs_credit_pptx_export import exportar_figuras_pptx

    plotly_config = {"displayModeBar": "hover", "displaylogo": False, "responsive": True}

    from tabs.comentario_credito import render_comentario

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

    def _nota_metodologica() -> None:
        st.markdown(
            "- **Localização:** a UF vem do **CEP de residência da pessoa física "
            "ou da sede da pessoa jurídica** — não é o local onde o crédito foi "
            "concedido.\n"
            "- **Cálculo:** toda taxa é razão de somas (Σ numerador ÷ Σ carteira "
            "ativa do recorte), nunca média de percentuais entre UFs.\n"
            "- **Modalidade:** agregação conforme a equivalência oficial do painel "
            "SCR.data do Banco Central.\n"
            "- As definições completas estão em **Glossário > SCR.data**."
        )

    def _card_header(painel) -> None:
        titulo_col, info_col = st.columns([0.94, 0.06], vertical_alignment="top")
        with titulo_col:
            st.markdown(f"##### {painel.titulo}")
            st.caption(f"{painel.subtitulo} · {painel.fonte}")
        with info_col:
            with st.popover("i", help="Metodologia deste card"):
                st.markdown("**Metodologia**")
                _nota_metodologica()

    def _rotulos_do_mapa(mapa: pd.DataFrame) -> list[go.Scattergeo]:
        """Sigla e percentual desenhados sobre o mapa, sem depender do mouse."""
        if mapa.empty:
            return []
        dentro_lon, dentro_lat, dentro_txt = [], [], []
        fora_lon, fora_lat, fora_txt = [], [], []
        guia_lon, guia_lat = [], []
        for _, linha in mapa.iterrows():
            codigo = str(linha.get("codigo_ibge"))
            centro = CENTROIDES_UF.get(codigo)
            if centro is None:
                continue
            sigla = str(linha.get("uf") or "")
            valor = pd.to_numeric(linha.get("valor"), errors="coerce")
            if pd.isna(valor):
                continue
            texto = f"<b>{sigla}</b><br>{valor * 100:.2f}".replace(".", ",") + "%"
            deslocado = ROTULO_DESLOCADO_UF.get(codigo)
            if deslocado is None:
                dentro_lon.append(centro[0])
                dentro_lat.append(centro[1])
                dentro_txt.append(texto)
            else:
                fora_lon.append(deslocado[0])
                fora_lat.append(deslocado[1])
                fora_txt.append(texto)
                guia_lon.extend([centro[0], deslocado[0], None])
                guia_lat.extend([centro[1], deslocado[1], None])

        camadas = []
        if guia_lon:
            camadas.append(go.Scattergeo(
                lon=guia_lon, lat=guia_lat, mode="lines",
                line=dict(color=COR_BORDA_UF, width=0.7),
                hoverinfo="skip", showlegend=False,
            ))
        for lon, lat, txt, anchor in (
            (dentro_lon, dentro_lat, dentro_txt, "center"),
            (fora_lon, fora_lat, fora_txt, "left"),
        ):
            if lon:
                camadas.append(go.Scattergeo(
                    lon=lon, lat=lat, mode="text", text=txt,
                    textposition="middle center" if anchor == "center" else "middle right",
                    textfont=dict(size=10, color=ITAU_BLACK, family="Arial"),
                    hoverinfo="skip", showlegend=False,
                ))
        return camadas

    periodos_disponiveis = _periodos_disponiveis()
    if not periodos_disponiveis:
        # Diferente do SGS, o SCR.data não tem cópia versionada no repositório:
        # o grão completo passa de 10 MB por ano. Quando o download do release
        # falha não há de onde degradar, então pelo menos a mensagem diz o que
        # aconteceu e o que fazer, em vez de só "indisponível".
        st.error(
            "**Cache SCR.data indisponível.** As demais sub-abas de "
            "Inadimplência continuam funcionando: elas vêm do SGS, que tem "
            "cópia versionada no repositório. O SCR.data é baixado do GitHub "
            "Releases a cada partida e não tem cópia local de reserva — o grão "
            "completo passa de 10 MB por ano."
        )
        st.code(
            ".venv/bin/python tools/update_caches_cli.py --tipo scr_data --modo overwrite",
            language="bash",
        )
        st.caption(
            "Se o cache existe mas a aba não abre, o schema pode ser anterior "
            "ao das modalidades oficiais do BCB e precisa ser rematerializado."
        )
        return

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
            help=(
                "Mais recente usa a última competência publicada do SCR.data, "
                f"hoje {formatar_competencia(ultima_timestamp)}."
            ),
        )
    with filtro_cliente:
        cliente_opcao = st.selectbox(
            "Cliente", ["Total", "PF", "PJ"], index=0, key="scr_cliente"
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
    cliente = None if cliente_opcao == "Total" else cliente_opcao
    dados = scr_q.filtrar(base, cliente=cliente)
    if dados.empty:
        st.warning("Sem dados para os filtros selecionados.")
        return
    data_base = str(dados["data_base"].astype(str).max())
    rotulo_metrica = scr_q.METRICAS[_metrica].rotulo

    render_comentario("npl_faixa_renda", data_base_cache=data_base)

    st.caption(
        f"SCR.data · dados até **{formatar_competencia(f'{data_base}-01')}**. "
        "SGS e SCR.data têm calendários de publicação próprios e podem fechar em "
        "competências diferentes; o rodapé de cada card informa a sua."
    )

    aba_paineis, aba_regiao = st.tabs(["Painéis", "Brasil e regiões"])

    with aba_paineis:
        controle_quebra, controle_opcoes = st.columns([3, 1])
        quebras = [q for q in scr_spec.QUEBRAS if q.key != "segmento"]
        with controle_quebra:
            quebra_key = st.selectbox(
                "Comparar linhas por", [q.key for q in quebras],
                format_func=lambda chave: scr_spec.QUEBRAS_POR_KEY[chave].label,
                key="scr_pn_quebra",
            )
        with controle_opcoes:
            # Dois interruptores que quase nunca mudam não precisam ocupar a
            # barra de filtros junto dos quatro que mudam sempre.
            with st.popover("Exibição", help="Opções de exibição dos painéis"):
                incluir_total = st.toggle("Linha total", value=True, key="scr_pn_total")
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

        # Os avisos ficam visíveis, junto do controle que os causou, mas em uma
        # linha só: uma pilha de faixas amarelas para quatro painéis empurrava
        # os gráficos para fora da tela.
        mensagens = sorted({
            aviso["mensagem"]
            for avisos in avisos_por_painel.values()
            for aviso in avisos
        })
        if mensagens:
            st.caption("⚠︎ " + " · ".join(mensagens))

        painel_quebras = scr_spec._quebras(dados, _metrica) if not dados.empty else []

        if not paineis:
            st.info("Selecione ao menos uma modalidade.")
        else:
            chave = "|".join([
                "paineis", inicio, fim, str(cliente), _metrica, quebra_key,
                str(incluir_total), *produtos,
            ])

            def _construir_paineis():
                return scr_pptx.exportar_paineis_pptx(
                    paineis,
                    rotulo_serie_fn=lambda nome: scr_spec.rotulo_serie(nome, quebra_spec),
                    titulo_deck=f"SCR.data · {rotulo_metrica} · {data_base}",
                )

            try:
                blob, meta = _memo_pptx(chave, _construir_paineis)
                st.download_button(
                    f"Baixar {meta['paineis']} gráficos desta aba em PPTX",
                    data=blob,
                    file_name=f"scr_paineis_{data_base}.pptx",
                    mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                    key="scr_pn_pptx", width="stretch",
                    help="Gráficos Office nativos, editáveis; até 4 por slide.",
                )
            except Exception as exc:
                st.error(f"Falha ao montar o PPTX: {exc}")

            # Dois por linha. Esticado pela tela inteira o painel perde
            # sensibilidade vertical; o nome de cada série continua na ponta da
            # linha, que é o que mantém legível uma faixa de renda colada na
            # outra.
            for inicio_linha in range(0, len(paineis), 2):
                colunas = st.columns(2)
                for coluna, painel in zip(colunas, paineis[inicio_linha:inicio_linha + 2]):
                    with coluna:
                        _card_header(painel)
                        st.plotly_chart(
                            figura_painel(
                        painel, quebra_spec, eixo_zero=eixo_zero,
                        quebras_serie=painel_quebras,
                        rotulo_metrica=scr_q.METRICAS[_metrica].rotulo,
                    ),
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

        figura_ufs = figura_por_uf(geo["mapa"], rotulo_metrica)

        figura_regiao = figura_por_regiao(
            geo,
            rotulo_metrica=rotulo_metrica,
            titulo=f"{modalidade_regiao} por região",
        )

        chave_regiao = "|".join([
            "regiao", inicio, fim, str(cliente), _metrica, modalidade_regiao, nivel_geo,
        ])

        def _construir_regiao():
            return exportar_figuras_pptx(
                [figura_ufs, figura_regiao],
                titulo_deck=f"SCR.data · {modalidade_regiao} · {rotulo_metrica} · {data_base}",
            )

        blob_regiao, meta_regiao = _memo_pptx(chave_regiao, _construir_regiao)
        export_col, csv_col = st.columns(2)
        with export_col:
            st.download_button(
                f"Baixar {meta_regiao['paineis']} gráficos desta aba em PPTX",
                data=blob_regiao,
                file_name=f"scr_regiao_{data_base}.pptx",
                mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                key="scr_regiao_pptx", width="stretch",
                help=(
                    "Os dois gráficos abaixo, em formato Office nativo e editável. "
                    "O mapa não tem equivalente nativo no Office — a mesma métrica "
                    "vai como gráfico de barras por UF."
                ),
            )
        with csv_col:
            st.download_button(
                "Baixar dados (CSV)", data=dados_regiao.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"scr_data_{data_base}.csv", mime="text/csv", key="scr_download",
            )

        resumo_cols = st.columns([1, 1, 1, 0.3])
        resumo_cols[0].metric(
            "Carteira Brasil",
            scr_q.formatar_reais_de_mil(geo["carteira_brasil_rs_mil"]),
        )
        resumo_cols[1].metric(rotulo_metrica, _fmt(geo["media_brasil"]))
        resumo_cols[2].metric("Data-base", formatar_competencia(f"{data_base}-01"))
        with resumo_cols[3]:
            with st.popover("i", help="Como estes números são calculados"):
                st.markdown("**Metodologia**")
                _nota_metodologica()

        mapa_col, ranking_col = st.columns([1.5, 1])
        with mapa_col:
            titulo_mapa, info_mapa = st.columns([0.94, 0.06], vertical_alignment="center")
            with titulo_mapa:
                st.markdown(f"##### {rotulo_metrica} por UF")
            with info_mapa:
                with st.popover("i", help="Metodologia do mapa"):
                    st.markdown("**Metodologia**")
                    _nota_metodologica()
            geojson = scr_spec.carregar_geojson_uf()
            if geojson is not None and not geo["mapa"].empty:
                figura_mapa = px.choropleth(
                    geo["mapa"], geojson=geojson, locations="codigo_ibge",
                    featureidkey=geo["featureidkey"], color="valor",
                    color_continuous_scale=ESCALA_MAPA, hover_name="uf_nome",
                    hover_data={"codigo_ibge": False, "valor": ":.2%", "regiao": True},
                    labels={"valor": rotulo_metrica},
                )
                # Contorno em todas as UFs: sem ele, o estado de menor taxa se
                # confunde com o papel branco.
                figura_mapa.update_traces(
                    marker_line_color=COR_BORDA_UF, marker_line_width=0.5
                )
                if nivel_geo == "uf":
                    for camada in _rotulos_do_mapa(geo["mapa"]):
                        figura_mapa.add_trace(camada)
                figura_mapa.update_geos(
                    visible=False, projection_type=scr_spec.MAPA_PROJECAO,
                    lonaxis_range=list(
                        MAPA_LON_RANGE_ROTULADO if nivel_geo == "uf"
                        else scr_spec.MAPA_LON_RANGE
                    ),
                    lataxis_range=list(scr_spec.MAPA_LAT_RANGE),
                    bgcolor="rgba(0,0,0,0)",
                )
                figura_mapa.update_layout(
                    height=520, margin=dict(l=0, r=0, t=10, b=0),
                    coloraxis_colorbar=dict(
                        tickformat=".1%",
                        title=dict(text=rotulo_metrica, side="right"),
                    ),
                    font=dict(family="Arial", size=13, color=ITAU_BLACK),
                    showlegend=False,
                    paper_bgcolor="#FFFFFF",
                )
                st.plotly_chart(figura_mapa, width="stretch", config=plotly_config)
        with ranking_col:
            st.markdown("##### Ranking")
            st.caption("Mesma métrica e mesmo recorte do mapa.")
            ranking = geo["ranking"].copy()
            if not ranking.empty:
                ranking["taxa"] = ranking["valor"].map(_fmt)
                ranking["carteira"] = ranking["denominador"].map(
                    scr_q.formatar_reais_de_mil
                )
                st.dataframe(
                    ranking[[nivel_geo, "taxa", "carteira"]], hide_index=True,
                    width="stretch", height=520,
                    column_config={
                        nivel_geo: st.column_config.TextColumn(
                            "UF" if nivel_geo == "uf" else "Região"
                        ),
                        "taxa": st.column_config.TextColumn(rotulo_metrica),
                        "carteira": st.column_config.TextColumn("Carteira"),
                    },
                )

        st.markdown(f"##### {rotulo_metrica} por UF")
        st.caption("Mesma variável que o mapa colore — é este gráfico que vai no PPTX.")
        st.plotly_chart(figura_ufs, width="stretch", config=plotly_config)

        titulo_col, info_col = st.columns([0.94, 0.06], vertical_alignment="center")
        with titulo_col:
            st.markdown(f"##### **{modalidade_regiao}** por região")
        with info_col:
            with st.popover("i", help="Metodologia regional"):
                st.markdown("**Metodologia**")
                _nota_metodologica()
        st.plotly_chart(figura_regiao, width="stretch", config=plotly_config)
