"""Especificação da visão "Inadimplência SCR".

O módulo é intencionalmente independente de Streamlit: a mesma especificação de
seções alimenta o render da aba, os testes e eventuais exportações, evitando que
regra de leitura (ordem das faixas, corte de materialidade, marcação de quebra
de série) fique escondida dentro do bloco de UI.

As funções ``construir_*`` recebem o fato já filtrado e devolvem DataFrames
prontos para plotagem. Toda taxa vem de ``utils.scr_data_query``, que a calcula
como razão de somas.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd

from utils import scr_data_query as Q
from utils.ifdata_cache.scr_data import (
    ORDEM_REGIOES,
    ORDEM_SEGMENTOS,
    PORTE_INDISPONIVEL,
    PORTE_PJ_CRITERIO,
    PORTE_PJ_ORDEM,
    PRIMEIRA_DATA_BASE,
    SCR_METODOLOGIA_URL,
    SCR_PAGINA_URL,
    SUBMODALIDADES_LEGADO,
    UF_IBGE,
    UF_NOME,
)

TITLE = "Inadimplência do crédito (SCR)"
SUBTITLE = (
    "Carteira, inadimplência e ativo problemático por faixa de renda, produto, "
    "região e segmento de instituição — SCR.data do Banco Central"
)

MENU_LABEL = "Inadimplência SCR"
CACHE_NAME = "scr_data"

# Janela default da aba. O grão completo é carregado por ano; 36 meses cobrem
# três safras sem estourar o cold start do Streamlit Cloud.
JANELA_PADRAO_MESES = 36
JANELAS_DISPONIVEIS = (12, 24, 36, 60)

# Corte de materialidade default dos rankings, em R$ mil (= R$ 1 bi).
CARTEIRA_MINIMA_PADRAO_RS_MIL = 1_000_000.0

GEOJSON_UF_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "bundled" / "geo" / "uf_brasil.geojson"
)
GEOJSON_FEATURE_KEY = "properties.codarea"

# Enquadramento fixo do Brasil. `fitbounds="locations"` depende do tamanho do
# container no primeiro paint e sai errado dentro de coluna do Streamlit.
MAPA_LON_RANGE = (-74.5, -33.5)
MAPA_LAT_RANGE = (-34.5, 6.5)
MAPA_PROJECAO = "mercator"


# =============================================================================
# ESPECIFICAÇÃO DAS SEÇÕES
# =============================================================================

@dataclass(frozen=True)
class SecaoSpec:
    """Uma seção da aba, com o que a UI precisa para montá-la."""

    key: str
    label: str
    resumo: str
    dimensoes: Sequence[str] = field(default_factory=tuple)
    exige_detalhe: bool = False
    nota: str = ""


SECOES: tuple[SecaoSpec, ...] = (
    SecaoSpec(
        key="paineis",
        label="Painéis",
        resumo=(
            "Um painel por produto, uma linha por faixa do recorte escolhido "
            "(renda, região, segmento), no tempo. É a visão de trabalho da aba "
            "e a que vai para o PPTX, quatro por slide."
        ),
        dimensoes=("modalidade", "submodalidade", "porte", "regiao", "segmento"),
        nota=(
            "A linha `Todos` é o agregado do produto sem recorte — a referência "
            "contra a qual as faixas se leem."
        ),
    ),
    SecaoSpec(
        key="panorama",
        label="Panorama",
        resumo=(
            "Visão geral do sistema: carteira, inadimplência, ativo problemático "
            "e atraso curto, com a série desde jul/2012 e a quebra PF/PJ."
        ),
        dimensoes=("data_base", "cliente"),
    ),
    SecaoSpec(
        key="produto",
        label="Por produto",
        resumo=(
            "Inadimplência por produto, sem recorte de renda. Alterna entre as "
            "13 modalidades e as 55 submodalidades."
        ),
        dimensoes=("modalidade", "submodalidade"),
        nota=(
            "Rankings aplicam corte de carteira mínima e escondem submodalidades "
            "residuais de migração de leiaute."
        ),
    ),
    SecaoSpec(
        key="renda",
        label="Por faixa de renda / porte",
        resumo=(
            "PF por faixa de renda em salários mínimos; PJ por porte de "
            "faturamento. Nunca no mesmo eixo — são critérios diferentes."
        ),
        dimensoes=("porte", "cliente"),
        nota=(
            "Os limites de faturamento PJ são nominais e nunca foram corrigidos "
            "por inflação, o que empurra empresas de faixa ao longo da série."
        ),
    ),
    SecaoSpec(
        key="regiao",
        label="Por região",
        resumo=(
            "Mapa e ranking por UF, séries por região. A UF vem do CEP do "
            "tomador, não da agência que concedeu o crédito."
        ),
        dimensoes=("uf", "regiao"),
        exige_detalhe=True,
    ),
    SecaoSpec(
        key="segmento",
        label="Por segmento de IF",
        resumo=(
            "Fintechs (SCD/SEP) e instituições de pagamento contra bancos, "
            "cooperativas e financeiras."
        ),
        dimensoes=("segmento",),
        exige_detalhe=True,
        nota="Cada segmento só entra no gráfico a partir da data-base em que aparece na base.",
    ),
)

SECOES_POR_KEY: Dict[str, SecaoSpec] = {secao.key: secao for secao in SECOES}


# =============================================================================
# NOTAS E RODAPÉ
# =============================================================================

NOTA_UF_CEP = (
    "A UF vem do CEP de residência da pessoa física ou da sede da pessoa "
    "jurídica — não é o local onde o crédito foi concedido."
)

NOTA_DIVERGENCIA = (
    "Os números divergem do IF.data e dos balancetes COSIF por construção: o "
    "SCR.data é montado a partir do documento 3040, operação a operação, e o "
    "próprio BCB declara margem de tolerância contra os demonstrativos contábeis."
)

NOTA_PORTE_COMPARTILHADO = (
    "PF e PJ compartilham a coluna de porte na origem. Filtre o tipo de cliente "
    "antes de ler qualquer corte por faixa."
)

NOTA_LEGADO = (
    "`Cartão de crédito - não migrado` é resíduo de migração de leiaute, não um "
    "produto comercial: em jun/2026 tinha 77% de inadimplência sobre R$ 69 bi. "
    "Fica visível para o total fechar, mas sai dos rankings por padrão."
)

FONTES = (
    {"rotulo": "SCR.data — página oficial", "url": SCR_PAGINA_URL},
    {"rotulo": "Metodologia (versão 2)", "url": SCR_METODOLOGIA_URL},
)


def tabela_criterios_pj() -> pd.DataFrame:
    """Critérios de porte PJ, para o card fixo da seção de renda."""
    return pd.DataFrame(
        [{"porte": porte, "criterio": PORTE_PJ_CRITERIO[porte]} for porte in PORTE_PJ_ORDEM]
    )


def rodape(df: pd.DataFrame, *, data_base: Optional[str] = None) -> Dict[str, Any]:
    """Metadados de rodapé do recorte visível."""
    supressao = Q.resumo_supressao(df)
    data_bases = (
        sorted(df["data_base"].astype(str).unique()) if not df.empty else []
    )
    return {
        "data_base": data_base or (data_bases[-1] if data_bases else None),
        "data_base_inicial": data_bases[0] if data_bases else None,
        "primeira_data_base_disponivel": PRIMEIRA_DATA_BASE,
        "linhas": int(len(df)),
        "supressao": supressao,
        "notas": [NOTA_UF_CEP, NOTA_DIVERGENCIA, NOTA_PORTE_COMPARTILHADO],
        "fontes": [dict(fonte) for fonte in FONTES],
    }


# =============================================================================
# SEÇÃO 1 — PANORAMA
# =============================================================================

def construir_panorama(
    df: pd.DataFrame,
    *,
    metrica: str = Q.METRICA_PADRAO,
    data_base: Optional[str] = None,
) -> Dict[str, Any]:
    """KPIs, série total e série quebrada por tipo de cliente."""
    serie_total = Q.serie_temporal(df, metrica)
    serie_total["recorte"] = "Total"

    serie_cliente = Q.serie_temporal(df, metrica, by=["cliente"])
    serie_cliente = serie_cliente.rename(columns={"cliente": "recorte"})

    composicao = Q.agregar(df, "carteira_ativa", by=["data_base"])
    for coluna, rotulo in (
        ("vencido_de_15_ate_90_dias", "Vencido 15–90d"),
        ("vencido_acima_de_90_dias", "Vencido > 90d"),
    ):
        parcial = df.groupby("data_base", as_index=False, observed=True)[coluna].sum()
        composicao = composicao.merge(parcial, on="data_base", how="left")
    composicao["A vencer"] = (
        composicao["valor"]
        - composicao["vencido_de_15_ate_90_dias"]
        - composicao["vencido_acima_de_90_dias"]
    )

    return {
        "kpis": Q.kpis(df, data_base=data_base),
        "serie": pd.concat([serie_total, serie_cliente], ignore_index=True),
        "composicao": composicao.rename(
            columns={
                "vencido_de_15_ate_90_dias": "Vencido 15–90d",
                "vencido_acima_de_90_dias": "Vencido > 90d",
            }
        )[["data_base", "A vencer", "Vencido 15–90d", "Vencido > 90d"]],
        "quebras": _quebras(df, metrica),
    }


# =============================================================================
# SEÇÃO 2 — PRODUTO
# =============================================================================

def construir_por_produto(
    df: pd.DataFrame,
    *,
    metrica: str = Q.METRICA_PADRAO,
    nivel: str = "submodalidade",
    data_base: Optional[str] = None,
    carteira_minima_rs_mil: float = CARTEIRA_MINIMA_PADRAO_RS_MIL,
    destaques: Optional[Sequence[str]] = None,
    limite_series: int = 8,
) -> Dict[str, Any]:
    """Ranking na data-base, séries dos produtos escolhidos e heatmap."""
    if nivel not in ("modalidade", "submodalidade"):
        raise ValueError("nivel deve ser 'modalidade' ou 'submodalidade'")

    referencia = data_base or _ultima_data_base(df)
    recorte = Q.filtrar(df, data_base_inicial=referencia, data_base_final=referencia)

    ranking = Q.ranking(
        recorte,
        nivel,
        metrica,
        carteira_minima_rs_mil=carteira_minima_rs_mil,
    )

    escolhidos = list(destaques) if destaques else (
        ranking[nivel].astype(str).head(limite_series).tolist()
    )
    series = Q.serie_temporal(
        Q.filtrar(df, **{nivel: escolhidos}) if escolhidos else df.iloc[0:0],
        metrica,
        by=[nivel],
    )

    heatmap = Q.matriz(
        Q.filtrar(df, **{nivel: escolhidos}) if escolhidos else df.iloc[0:0],
        nivel,
        "data_base",
        metrica,
        ordem_linhas=escolhidos,
    )

    return {
        "nivel": nivel,
        "data_base": referencia,
        "ranking": ranking,
        "destaques": escolhidos,
        "series": series,
        "heatmap": heatmap,
        "legado_ocultado": sorted(
            set(recorte["submodalidade"].astype(str)) & set(SUBMODALIDADES_LEGADO)
        ) if "submodalidade" in recorte.columns else [],
        "quebras": _quebras(df, metrica),
    }


# =============================================================================
# SEÇÃO 3 — RENDA / PORTE
# =============================================================================

def construir_por_porte(
    df: pd.DataFrame,
    *,
    cliente: str = "PF",
    metrica: str = Q.METRICA_PADRAO,
    data_base: Optional[str] = None,
    salario_minimo: Optional[float] = None,
    indexar_series: bool = False,
    nivel_produto: str = "submodalidade",
    limite_produtos: int = 12,
) -> Dict[str, Any]:
    """Barras por faixa, séries por faixa e cruzamento faixa × produto.

    A ordem das barras é a da renda/faturamento, nunca a do valor: é a monotonia
    (e a quebra dela no topo da renda) que se quer enxergar.
    """
    base = Q.filtrar(df, cliente=cliente)
    referencia = data_base or _ultima_data_base(base)
    ordem = Q.ordem_portes(cliente)

    barras = Q.agregar(
        Q.filtrar(base, data_base_inicial=referencia, data_base_final=referencia),
        metrica,
        by=["porte"],
    )
    barras = Q.ordenar_categorico(barras, "porte", ordem).reset_index(drop=True)

    if cliente.upper() == "PF":
        rotulos = Q.rotular_faixas_em_reais(salario_minimo)
        barras["rotulo_faixa"] = barras["porte"].astype(str).map(
            lambda p: rotulos.get(p, p)
        )
    else:
        barras["rotulo_faixa"] = barras["porte"].astype(str).map(
            lambda p: PORTE_PJ_CRITERIO.get(p, "")
        )

    series = Q.serie_temporal(base, metrica, by=["porte"])
    series = Q.ordenar_categorico(series, "porte", ordem).reset_index(drop=True)
    if indexar_series:
        series = _indexar(series, chave="porte")

    produtos = (
        Q.ranking(
            Q.filtrar(base, data_base_inicial=referencia, data_base_final=referencia),
            nivel_produto,
            "carteira_ativa",
            carteira_minima_rs_mil=0,
            limite=limite_produtos,
        )[nivel_produto]
        .astype(str)
        .tolist()
    )
    cruzamento = Q.matriz(
        Q.filtrar(
            base,
            data_base_inicial=referencia,
            data_base_final=referencia,
            **{nivel_produto: produtos},
        ),
        "porte",
        nivel_produto,
        metrica,
        ordem_linhas=ordem,
        ordem_colunas=produtos,
    )

    return {
        "cliente": cliente.upper(),
        "data_base": referencia,
        "ordem": ordem,
        "barras": barras,
        "series": series,
        "cruzamento_produto": cruzamento,
        "criterios_pj": tabela_criterios_pj() if cliente.upper() == "PJ" else None,
        "salario_minimo": salario_minimo,
        "indexado": indexar_series,
        "quebras": _quebras(df, metrica),
    }


# =============================================================================
# SEÇÃO 4 — REGIÃO
# =============================================================================

def _area_assinada(anel: Sequence[Sequence[float]]) -> float:
    """Área pela fórmula do trapézio. Positiva = sentido horário em (lon, lat)."""
    total = 0.0
    n = len(anel)
    for i in range(n):
        x1, y1 = anel[i][0], anel[i][1]
        x2, y2 = anel[(i + 1) % n][0], anel[(i + 1) % n][1]
        total += (x2 - x1) * (y2 + y1)
    return total


def _reorientar_para_d3(geojson: Dict[str, Any]) -> Dict[str, Any]:
    """Inverte os anéis para a convenção de winding do d3-geo.

    A RFC 7946 manda o anel exterior anti-horário; o d3-geo, que o Plotly usa
    nos traces ``geo``, usa a convenção oposta e trata um anel anti-horário como
    o *complemento* do polígono. Com a malha do IBGE (que segue a RFC) o mapa
    saía como um retângulo preenchido com o formato do estado recortado como
    buraco. O arquivo em ``data/bundled`` fica no padrão; a inversão acontece
    aqui, na fronteira com o Plotly.
    """

    def orientar(anel, *, horario: bool):
        return anel if (_area_assinada(anel) > 0) == horario else anel[::-1]

    def corrigir(poligono):
        # Exterior horário, buracos anti-horários — o inverso da RFC.
        return [orientar(poligono[0], horario=True)] + [
            orientar(anel, horario=False) for anel in poligono[1:]
        ]

    for feature in geojson.get("features", []):
        geometria = feature.get("geometry") or {}
        tipo = geometria.get("type")
        if tipo == "Polygon":
            geometria["coordinates"] = corrigir(geometria["coordinates"])
        elif tipo == "MultiPolygon":
            geometria["coordinates"] = [
                corrigir(poligono) for poligono in geometria["coordinates"]
            ]
    return geojson


def carregar_geojson_uf() -> Optional[Dict[str, Any]]:
    """Malha das UFs para o coroplético; ``None`` se o arquivo não estiver lá."""
    if not GEOJSON_UF_PATH.exists():
        return None
    try:
        bruto = json.loads(GEOJSON_UF_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return _reorientar_para_d3(bruto)


def construir_por_regiao(
    df: pd.DataFrame,
    *,
    metrica: str = Q.METRICA_PADRAO,
    data_base: Optional[str] = None,
    nivel: str = "uf",
) -> Dict[str, Any]:
    """Mapa por UF, ranking com carteira ao lado e séries por região."""
    if nivel not in ("uf", "regiao"):
        raise ValueError("nivel deve ser 'uf' ou 'regiao'")

    base = Q.adicionar_regiao(df)
    referencia = data_base or _ultima_data_base(base)
    recorte = Q.filtrar(base, data_base_inicial=referencia, data_base_final=referencia)

    mapa = Q.agregar(recorte, metrica, by=["uf"])
    if not mapa.empty:
        mapa["uf_nome"] = mapa["uf"].astype(str).map(UF_NOME)
        mapa["regiao"] = mapa["uf"].astype(str).map(
            lambda uf: Q.REGIAO_POR_UF.get(uf, "")
        )
        # O código IBGE em texto é o que casa com `properties.codarea` do geojson.
        mapa["codigo_ibge"] = mapa["uf"].astype(str).map(
            lambda uf: f"{UF_IBGE[uf]}" if uf in UF_IBGE else None
        )

    media_brasil = Q.agregar(recorte, metrica)
    referencia_brasil = (
        float(media_brasil["valor"].iloc[0])
        if not media_brasil.empty and pd.notna(media_brasil["valor"].iloc[0])
        else None
    )

    ranking = Q.ranking(recorte, nivel, metrica, carteira_minima_rs_mil=0)
    series = Q.serie_temporal(base, metrica, by=["regiao"])
    series = Q.ordenar_categorico(series, "regiao", ORDEM_REGIOES).reset_index(drop=True)

    cruzamento_porte = Q.matriz(recorte, "regiao", "porte", metrica, ordem_linhas=ORDEM_REGIOES)

    return {
        "nivel": nivel,
        "data_base": referencia,
        "mapa": mapa,
        "geojson_disponivel": GEOJSON_UF_PATH.exists(),
        "featureidkey": GEOJSON_FEATURE_KEY,
        "media_brasil": referencia_brasil,
        "ranking": ranking,
        "series": series,
        "cruzamento_porte": cruzamento_porte,
        "nota": NOTA_UF_CEP,
        "quebras": _quebras(df, metrica),
    }


# =============================================================================
# SEÇÃO 5 — SEGMENTO
# =============================================================================

def construir_por_segmento(
    df: pd.DataFrame,
    *,
    metrica: str = Q.METRICA_PADRAO,
    data_base: Optional[str] = None,
    dim_segmento: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    """Comparativo entre segmentos, respeitando quando cada um entra na base.

    Fintech (SCD/SEP) e instituição de pagamento não existem no começo da série;
    plotar zero antes disso sugeriria carteira nula em vez de ausência de dado.
    """
    referencia = data_base or _ultima_data_base(df)
    recorte = Q.filtrar(df, data_base_inicial=referencia, data_base_final=referencia)

    barras = Q.agregar(recorte, metrica, by=["segmento"])
    barras = Q.ordenar_categorico(barras, "segmento", ORDEM_SEGMENTOS).reset_index(drop=True)

    series = Q.serie_temporal(df, metrica, by=["segmento"])
    series = Q.ordenar_categorico(series, "segmento", ORDEM_SEGMENTOS).reset_index(drop=True)

    vigencia = _vigencia_segmentos(df, dim_segmento)

    return {
        "data_base": referencia,
        "barras": barras,
        "series": series,
        "vigencia": vigencia,
        "quebras": _quebras(df, metrica),
    }


def _vigencia_segmentos(
    df: pd.DataFrame, dim_segmento: Optional[pd.DataFrame]
) -> pd.DataFrame:
    """Primeira data-base de cada segmento, da dimensão ou do próprio fato."""
    if dim_segmento is not None and not dim_segmento.empty:
        colunas = [c for c in ("segmento", "primeira_data_base") if c in dim_segmento.columns]
        if len(colunas) == 2:
            return dim_segmento[colunas].copy()
    if df.empty or "segmento" not in df.columns:
        return pd.DataFrame(columns=["segmento", "primeira_data_base"])
    return (
        df.groupby("segmento", as_index=False, observed=True)["data_base"]
        .min()
        .rename(columns={"data_base": "primeira_data_base"})
    )


# =============================================================================
# APOIO À RENDERIZAÇÃO
# =============================================================================

def formatar_delta_kpi(delta: Optional[float], formato: str, *, sufixo: str = "m/m") -> Optional[str]:
    """Rótulo de variação de um KPI.

    Percentual varia em pontos percentuais; nível varia em percentual relativo.
    A vírgula decimal é aplicada só no número — trocar todo ponto da string
    transformaria "p.p." em "p,p,".
    """
    if delta is None or pd.isna(delta):
        return None
    if formato == "percentual":
        numero = f"{delta * 100:+.2f}".replace(".", ",")
        return f"{numero} p.p. {sufixo}"
    numero = f"{delta * 100:+.1f}".replace(".", ",")
    return f"{numero}% {sufixo}"


def marcar_quebras(fig, quebras: Sequence[Dict[str, str]]):
    """Marca as quebras de série no eixo temporal de uma figura Plotly.

    A linha entra sem ``annotation_text``: com eixo categórico (as data-bases
    são strings ``YYYY-MM``), o ``add_vline`` do Plotly tenta calcular a média
    de ``x0`` e ``x1`` para posicionar a anotação e estoura com ``TypeError``.
    O rótulo vai por ``add_annotation``, que aceita categoria.
    """
    for quebra in quebras:
        fig.add_vline(
            x=quebra["data_base"],
            line_dash="dot",
            line_color="#94a3b8",
        )
        fig.add_annotation(
            x=quebra["data_base"],
            y=1.0,
            yref="paper",
            yanchor="bottom",
            text=quebra["data_base"],
            showarrow=False,
            font=dict(size=10, color="#64748b"),
        )
    return fig


# =============================================================================
# AUXILIARES
# =============================================================================

def _ultima_data_base(df: pd.DataFrame) -> Optional[str]:
    if df.empty or "data_base" not in df.columns:
        return None
    return str(df["data_base"].astype(str).max())


def _quebras(df: pd.DataFrame, metrica: Any) -> List[Dict[str, str]]:
    if df.empty or "data_base" not in df.columns:
        return []
    datas = df["data_base"].astype(str)
    return Q.quebras_no_intervalo(datas.min(), datas.max(), metrica)


def _indexar(series: pd.DataFrame, *, chave: str) -> pd.DataFrame:
    """Reindexa cada série para 100 na primeira data-base em que tem valor.

    Serve para comparar dinâmica entre faixas cujos níveis são muito diferentes.
    """
    out = series.copy()
    out["valor_indexado"] = pd.NA
    for grupo, bloco in out.groupby(chave, observed=True):
        validos = bloco["valor"].dropna()
        if validos.empty or validos.iloc[0] == 0:
            continue
        out.loc[bloco.index, "valor_indexado"] = bloco["valor"] / validos.iloc[0] * 100
    return out


def descrever_secoes() -> pd.DataFrame:
    """Tabela das seções, para documentação e para o teste de contrato."""
    return pd.DataFrame(
        [
            {
                "key": secao.key,
                "label": secao.label,
                "resumo": secao.resumo,
                "dimensoes": ", ".join(secao.dimensoes),
                "exige_detalhe": secao.exige_detalhe,
                "nota": secao.nota,
            }
            for secao in SECOES
        ]
    )


# =============================================================================
# PAINÉIS COMPARATIVOS (produto × recorte × tempo)
# =============================================================================
#
# Esta é a visão de trabalho da aba: um painel por produto, uma linha por faixa
# de recorte (renda, região, segmento), a série no tempo. É o formato dos
# quadrantes usados nos decks — e o mesmo que o export para PPTX reproduz.

# Paleta Itaú BBA. Laranja institucional, preto e cinzas; nada fora disso.
COR_LARANJA = "#EC7000"
COR_PRETO = "#111111"
COR_CINZA_ESCURO = "#4B4B4B"
COR_CINZA_MEDIO = "#8F8F8F"
COR_CINZA_CLARO = "#C9C9C9"
COR_GRADE = "#E6E6E6"
COR_TEXTO = "#3C3C3C"

# Rampa para dimensões ORDENADAS (faixas de renda, porte). Vai do laranja, que
# sinaliza o grupo sob estresse, aos cinzas escuros. É monotônica em luminosidade
# para que a ordem da renda seja lida no próprio gradiente.
RAMPA_ORDENADA = [
    "#EC7000", "#F0913A", "#F5B478", "#CFCFCF", "#A6A6A6", "#7D7D7D", "#545454",
]

# Paleta para dimensões SEM ordem natural (região, segmento, produto).
PALETA_CATEGORICA = [
    "#EC7000", "#111111", "#8F8F8F", "#F5B478",
    "#4B4B4B", "#C25C00", "#C9C9C9", "#6F6F6F",
]

# O agregado ganha preto tracejado: distingue-se do fim da rampa sem sair da paleta.
SERIE_TOTAL = "Todos"
COR_TOTAL = COR_PRETO
DASH_TOTAL = "dash"

# As sete faixas que entram por padrão. "Sem rendimento" e "Indisponível" ficam
# de fora: somam pouca carteira e roubam duas cores de um gráfico que já tem
# sete linhas. Continuam disponíveis por opção explícita.
PORTE_PF_FAIXAS_PRINCIPAIS = [
    "Até 1 salário mínimo",
    "Mais de 1 a 2 salários mínimos",
    "Mais de 2 a 3 salários mínimos",
    "Mais de 3 a 5 salários mínimos",
    "Mais de 5 a 10 salários mínimos",
    "Mais de 10 a 20 salários mínimos",
    "Acima de 20 salários mínimos",
]

# Rótulo curto para a legenda, no padrão do deck ("Até 1", "1 a 2", ...).
ROTULO_FAIXA_CURTO = {
    "Sem rendimento": "Sem renda",
    "Até 1 salário mínimo": "Até 1",
    "Mais de 1 a 2 salários mínimos": "1 a 2",
    "Mais de 2 a 3 salários mínimos": "2 a 3",
    "Mais de 3 a 5 salários mínimos": "3 a 5",
    "Mais de 5 a 10 salários mínimos": "5 a 10",
    "Mais de 10 a 20 salários mínimos": "10 a 20",
    "Acima de 20 salários mínimos": "Acima 20",
    PORTE_INDISPONIVEL: "Indisp.",
}


@dataclass(frozen=True)
class QuebraSpec:
    """Uma dimensão pela qual as linhas de um painel podem ser quebradas."""

    key: str
    coluna: str
    label: str
    subtitulo: str
    ordenada: bool
    exige_cliente: Optional[str] = None
    exige_detalhe: bool = False


QUEBRAS: tuple[QuebraSpec, ...] = (
    QuebraSpec(
        key="renda",
        coluna="porte",
        label="Faixa de renda (salários mínimos)",
        subtitulo="Por Faixa Salário Mínimo",
        ordenada=True,
        exige_cliente="PF",
    ),
    QuebraSpec(
        key="porte_pj",
        coluna="porte",
        label="Porte da empresa (faturamento)",
        subtitulo="Por Porte de Faturamento",
        ordenada=True,
        exige_cliente="PJ",
    ),
    QuebraSpec(
        key="regiao",
        coluna="regiao",
        label="Região",
        subtitulo="Por Região",
        ordenada=True,
    ),
    QuebraSpec(
        key="uf",
        coluna="uf",
        label="Unidade da federação",
        subtitulo="Por UF",
        ordenada=False,
        exige_detalhe=True,
    ),
    QuebraSpec(
        key="segmento",
        coluna="segmento",
        label="Segmento da instituição",
        subtitulo="Por Segmento de IF",
        ordenada=False,
        exige_detalhe=True,
    ),
    QuebraSpec(
        key="cliente",
        coluna="cliente",
        label="Tipo de cliente (PF/PJ)",
        subtitulo="Por Tipo de Cliente",
        ordenada=False,
    ),
    QuebraSpec(
        key="nenhuma",
        coluna="",
        label="Sem quebra (só o total)",
        subtitulo="Total",
        ordenada=False,
    ),
)

QUEBRAS_POR_KEY: Dict[str, QuebraSpec] = {q.key: q for q in QUEBRAS}

# Título curto de cada métrica, no padrão do deck.
TITULO_CURTO_METRICA = {
    "inadimplencia": "Inad (> 90 d)",
    "ativo_problematico": "Ativo problemático",
    "atraso_15_90": "Atraso 15–90 d",
    "vencido_90": "Vencido > 90 d",
}

# Quantos painéis cabem num slide, em quadrantes.
PAINEIS_POR_SLIDE = 4


@dataclass(frozen=True)
class PainelSpec:
    """Um quadrante: título, subtítulo, séries no tempo e cores."""

    titulo: str
    subtitulo: str
    fonte: str
    produto: str
    series: pd.DataFrame          # colunas: data_base, serie, valor, denominador
    ordem_series: Sequence[str]
    cores: Dict[str, str]
    tracejadas: Sequence[str]
    metrica: str
    carteira_final_rs_mil: float


def rotulo_serie(valor: str, quebra: QuebraSpec) -> str:
    """Rótulo curto para a legenda, sem perder o sentido."""
    if quebra.coluna == "porte":
        return ROTULO_FAIXA_CURTO.get(valor, valor)
    return valor


def cores_das_series(
    ordem: Sequence[str], quebra: QuebraSpec
) -> Dict[str, str]:
    """Atribui cores respeitando a natureza da dimensão.

    Dimensão ordenada recebe a rampa (a ordem vira gradiente); dimensão
    categórica recebe a paleta qualitativa. O agregado ``Todos`` é sempre preto.
    """
    cores: Dict[str, str] = {}
    categorias = [item for item in ordem if item != SERIE_TOTAL]
    base = RAMPA_ORDENADA if quebra.ordenada else PALETA_CATEGORICA

    if quebra.ordenada and len(categorias) > len(base):
        # Mais faixas que degraus: reamostra a rampa para não repetir cor.
        passo = (len(base) - 1) / max(len(categorias) - 1, 1)
        escolhidas = [base[min(int(round(i * passo)), len(base) - 1)] for i in range(len(categorias))]
    else:
        escolhidas = [base[i % len(base)] for i in range(len(categorias))]

    for nome, cor in zip(categorias, escolhidas):
        cores[nome] = cor
    if SERIE_TOTAL in ordem:
        cores[SERIE_TOTAL] = COR_TOTAL
    return cores


def _ordem_da_quebra(
    quebra: QuebraSpec, valores_presentes: Sequence[str], cliente: Optional[str]
) -> List[str]:
    """Ordem de exibição das séries, pela natureza da dimensão."""
    presentes = list(dict.fromkeys(str(v) for v in valores_presentes))
    if quebra.coluna == "porte":
        alvo = Q.ordem_portes(cliente or quebra.exige_cliente or "PF")
    elif quebra.coluna == "regiao":
        alvo = list(ORDEM_REGIOES)
    elif quebra.coluna == "segmento":
        alvo = list(ORDEM_SEGMENTOS)
    elif quebra.coluna == "cliente":
        alvo = ["PF", "PJ"]
    else:
        return sorted(presentes)
    ordenados = [v for v in alvo if v in presentes]
    return ordenados + sorted(v for v in presentes if v not in alvo)


def construir_paineis(
    df: pd.DataFrame,
    *,
    produtos: Sequence[str],
    nivel_produto: str = "submodalidade",
    quebra: str = "renda",
    metrica: str = Q.METRICA_PADRAO,
    cliente: Optional[str] = None,
    faixas: Optional[Sequence[str]] = None,
    incluir_total: bool = True,
) -> List[PainelSpec]:
    """Um painel por produto, uma linha por faixa do recorte escolhido.

    ``incluir_total`` acrescenta a linha ``Todos`` — o agregado do produto sem
    recorte, que é a referência contra a qual as faixas se leem.
    """
    if nivel_produto not in ("modalidade", "submodalidade"):
        raise ValueError("nivel_produto deve ser 'modalidade' ou 'submodalidade'")
    spec = QUEBRAS_POR_KEY.get(quebra)
    if spec is None:
        raise ValueError(f"quebra desconhecida: {quebra!r}")

    definicao = Q.obter_metrica(metrica)
    cliente_efetivo = cliente or spec.exige_cliente
    base = Q.filtrar(df, cliente=cliente_efetivo)
    if spec.coluna == "regiao":
        base = Q.adicionar_regiao(base)

    paineis: List[PainelSpec] = []
    for produto in produtos:
        recorte = Q.filtrar(base, **{nivel_produto: produto})
        if recorte.empty:
            continue

        partes: List[pd.DataFrame] = []
        if spec.coluna:
            quebrado = Q.serie_temporal(recorte, definicao, by=[spec.coluna])
            quebrado = quebrado.rename(columns={spec.coluna: "serie"})
            quebrado["serie"] = quebrado["serie"].astype(str)
            if faixas:
                quebrado = quebrado[quebrado["serie"].isin([str(f) for f in faixas])]
            partes.append(quebrado)

        if incluir_total or not spec.coluna:
            total = Q.serie_temporal(recorte, definicao)
            total["serie"] = SERIE_TOTAL
            partes.append(total)

        if not partes:
            continue
        series = pd.concat(partes, ignore_index=True)
        series = series[["data_base", "serie", "valor", "denominador"]]

        presentes = [s for s in series["serie"].unique() if s != SERIE_TOTAL]
        ordem = _ordem_da_quebra(spec, presentes, cliente_efetivo)
        if SERIE_TOTAL in set(series["serie"]):
            ordem = [*ordem, SERIE_TOTAL]

        ultima = series["data_base"].astype(str).max()
        carteira = float(
            series[(series["data_base"].astype(str) == ultima) & (series["serie"] == SERIE_TOTAL)]
            ["denominador"].sum()
        ) if SERIE_TOTAL in set(series["serie"]) else float(
            series[series["data_base"].astype(str) == ultima]["denominador"].sum()
        )

        paineis.append(PainelSpec(
            titulo=f"{TITULO_CURTO_METRICA.get(definicao.chave, definicao.rotulo)} - {produto}",
            subtitulo=f"{spec.subtitulo} - % carteira",
            fonte="fonte: Banco Central do Brasil",
            produto=produto,
            series=series.reset_index(drop=True),
            ordem_series=ordem,
            cores=cores_das_series(ordem, spec),
            tracejadas=[SERIE_TOTAL] if SERIE_TOTAL in ordem else [],
            metrica=definicao.chave,
            carteira_final_rs_mil=carteira,
        ))
    return paineis


def faixas_padrao(quebra: str) -> Optional[List[str]]:
    """Faixas exibidas por padrão em cada quebra."""
    if quebra == "renda":
        return list(PORTE_PF_FAIXAS_PRINCIPAIS)
    if quebra == "porte_pj":
        return list(PORTE_PJ_ORDEM)
    if quebra == "regiao":
        return list(ORDEM_REGIOES)
    return None


# =============================================================================
# LEGIBILIDADE
# =============================================================================

# Abaixo desta distância, dois rótulos do último ponto se sobrepõem na tela.
DISTANCIA_MINIMA_ROTULOS_PP = 0.0015   # 0,15 p.p.
# Abaixo desta amplitude, as linhas ficam achatadas e o painel não informa.
AMPLITUDE_MINIMA_PP = 0.005            # 0,5 p.p.
MAXIMO_SERIES_LEGIVEL = 8
CARTEIRA_MINIMA_CONFIAVEL_RS_MIL = 500_000.0   # R$ 500 mi


def avaliar_legibilidade(paineis: Sequence[PainelSpec]) -> List[Dict[str, str]]:
    """Aponta o que vai atrapalhar a leitura antes do usuário descobrir sozinho.

    Não bloqueia nada: devolve avisos com o painel afetado e o que fazer.
    """
    avisos: List[Dict[str, str]] = []

    for painel in paineis:
        series = painel.series
        n = len(painel.ordem_series)
        if n > MAXIMO_SERIES_LEGIVEL:
            avisos.append({
                "painel": painel.titulo,
                "nivel": "alerta",
                "mensagem": (
                    f"{n} linhas no mesmo painel. Acima de {MAXIMO_SERIES_LEGIVEL} as cores "
                    "deixam de ser distinguíveis; remova faixas ou separe em dois painéis."
                ),
            })

        validos = series["valor"].dropna()
        if validos.empty:
            avisos.append({
                "painel": painel.titulo,
                "nivel": "alerta",
                "mensagem": "Sem dados no recorte — o painel sai vazio.",
            })
            continue

        amplitude = float(validos.max() - validos.min())
        if amplitude < AMPLITUDE_MINIMA_PP:
            avisos.append({
                "painel": painel.titulo,
                "nivel": "info",
                "mensagem": (
                    f"As séries variam só {amplitude * 100:.2f} p.p. entre si. "
                    "As linhas vão aparecer coladas; considere outro recorte."
                ),
            })

        if painel.carteira_final_rs_mil < CARTEIRA_MINIMA_CONFIAVEL_RS_MIL:
            avisos.append({
                "painel": painel.titulo,
                "nivel": "info",
                "mensagem": (
                    f"Carteira de {Q.formatar_reais_de_mil(painel.carteira_final_rs_mil)} "
                    "no último período. Taxas sobre base pequena oscilam muito."
                ),
            })

        colisoes = rotulos_sobrepostos(painel)
        if colisoes:
            avisos.append({
                "painel": painel.titulo,
                "nivel": "info",
                "mensagem": (
                    "Rótulos do último ponto quase colados em "
                    + "; ".join(f"{a} e {b}" for a, b in colisoes[:3])
                    + ". No PPTX eles podem se sobrepor — ajuste manualmente se for para o deck."
                ),
            })

    return avisos


def rotulos_sobrepostos(painel: PainelSpec) -> List[tuple[str, str]]:
    """Pares de séries cujo rótulo final fica perto demais para caber."""
    ultima = painel.series["data_base"].astype(str).max()
    fim = painel.series[painel.series["data_base"].astype(str) == ultima]
    pontos = [
        (str(linha["serie"]), float(linha["valor"]))
        for _, linha in fim.iterrows()
        if pd.notna(linha["valor"])
    ]
    pontos.sort(key=lambda item: item[1])
    return [
        (pontos[i][0], pontos[i + 1][0])
        for i in range(len(pontos) - 1)
        if abs(pontos[i + 1][1] - pontos[i][1]) < DISTANCIA_MINIMA_ROTULOS_PP
    ]


def formatar_percentual_2casas(valor: Optional[float]) -> str:
    """Percentual com duas decimais e vírgula, para rótulos e eixos."""
    if valor is None or pd.isna(valor):
        return "—"
    return f"{valor * 100:.2f}%".replace(".", ",")
