"""Export dos painéis do SCR para PPTX com gráficos nativos do Office.

Nativo importa: o gráfico sai como ``<c:lineChart>`` de verdade, com os dados
embutidos numa planilha do próprio arquivo. Quem receber o deck consegue mudar
cor, escala, série e até os números sem voltar aqui — o que uma imagem colada
não permite.

Layout: quatro painéis por slide, em quadrantes de tamanho igual, no formato dos
decks. Cada quadrante tem título, subtítulo, fonte e o gráfico.

Duas exigências de leitura que o módulo garante:

* **Rótulo apenas no último período.** Os demais pontos ficam sem rótulo. Isso é
  feito ponto a ponto, com ``showVal`` no último — o valor continua vindo do
  dado, então segue correto se alguém editar a série no Office.
* **Percentual com duas casas** no eixo de valores e nos rótulos, via
  ``numFmt`` ``0.00%``. Os valores são gravados como fração (0,0463), que é o
  que o formato percentual do Office espera.
"""

from __future__ import annotations

from io import BytesIO
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd
from lxml import etree
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import (
    XL_CHART_TYPE,
    XL_DATA_LABEL_POSITION,
    XL_LEGEND_POSITION,
    XL_TICK_MARK,
)
from pptx.enum.dml import MSO_LINE_DASH_STYLE
from pptx.enum.text import PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

from .sgs_credit_analytics import eixo_datas_adaptativo, formatar_competencia

# Slide 16:9.
SLIDE_LARGURA = Inches(13.333)
SLIDE_ALTURA = Inches(7.5)

MARGEM = Inches(0.38)
GUTTER_H = Inches(0.30)
GUTTER_V = Inches(0.34)
TOPO_CONTEUDO = Inches(0.30)

ALTURA_TITULO = Inches(0.30)
ALTURA_SUBTITULO = Inches(0.24)
ALTURA_FONTE = Inches(0.20)

FONTE_TITULO_PT = 13
FONTE_SUBTITULO_PT = 10
FONTE_FONTE_PT = 7.5
FONTE_EIXO_PT = 8
FONTE_LEGENDA_PT = 8
FONTE_ROTULO_PT = 8

COR_TITULO = RGBColor(0x11, 0x11, 0x11)
COR_SUBTITULO = RGBColor(0x3C, 0x3C, 0x3C)
COR_FONTE = RGBColor(0x8F, 0x8F, 0x8F)
COR_EIXO = RGBColor(0x6F, 0x6F, 0x6F)
COR_GRADE = RGBColor(0xE6, 0xE6, 0xE6)

FORMATO_PERCENTUAL = "0.00%"
LARGURA_LINHA_PT = 1.75
LARGURA_LINHA_TOTAL_PT = 2.25

PAINEIS_POR_SLIDE = 4


def rotulo_mes(data_base: str) -> str:
    """``2026-06`` -> ``Jun/26``, no padrão dos eixos do deck."""
    texto = str(data_base)
    try:
        ano, mes = texto.split("-")[:2]
        return formatar_competencia(pd.Timestamp(year=int(ano), month=int(mes), day=1))
    except (ValueError, IndexError):
        return texto


def _hex_para_rgb(cor: str) -> RGBColor:
    limpo = str(cor).lstrip("#")
    return RGBColor(int(limpo[0:2], 16), int(limpo[2:4], 16), int(limpo[4:6], 16))


def _caixa_texto(
    slide,
    *,
    left: Emu,
    top: Emu,
    width: Emu,
    height: Emu,
    texto: str,
    tamanho: float,
    cor: RGBColor,
    negrito: bool = False,
) -> None:
    caixa = slide.shapes.add_textbox(left, top, width, height)
    quadro = caixa.text_frame
    quadro.word_wrap = True
    quadro.margin_left = quadro.margin_right = 0
    quadro.margin_top = quadro.margin_bottom = 0
    paragrafo = quadro.paragraphs[0]
    paragrafo.alignment = PP_ALIGN.LEFT
    corrida = paragrafo.add_run()
    corrida.text = texto
    corrida.font.size = Pt(tamanho)
    corrida.font.bold = negrito
    corrida.font.color.rgb = cor


def _definir_intervalo_rotulos(category_axis, total_categorias: int) -> int:
    """Mantém todas as categorias; os meses intermediários têm rótulo vazio."""
    intervalo = 1
    elemento = category_axis._element
    for tag in ("c:tickLblSkip", "c:tickMarkSkip"):
        no = elemento.find(qn(tag))
        if no is None:
            no = etree.SubElement(elemento, qn(tag))
        no.set("val", str(intervalo))
    return intervalo


def _rotular_apenas_ultimo_ponto(
    serie, indice_ultimo: int, formato_numero: str = FORMATO_PERCENTUAL
) -> None:
    """Liga o rótulo só no último ponto da série.

    Usa ``showVal`` em vez de texto literal: o rótulo continua ligado ao dado,
    então quem editar a série no Office vê o número acompanhar.
    """
    if indice_ultimo < 0:
        return
    dLbl = serie.points[indice_ultimo].data_label._get_or_add_dLbl()

    formato = dLbl.find(qn("c:numFmt"))
    if formato is None:
        formato = etree.Element(qn("c:numFmt"))
        dLbl.insert(0, formato)
    formato.set("formatCode", formato_numero)
    formato.set("sourceLinked", "0")

    mostrar = {
        "c:showLegendKey": "0",
        "c:showVal": "1",
        "c:showCatName": "0",
        "c:showSerName": "0",
        "c:showPercent": "0",
        "c:showBubbleSize": "0",
    }
    for tag, valor in mostrar.items():
        no = dLbl.find(qn(tag))
        if no is None:
            no = etree.SubElement(dLbl, qn(tag))
        no.set("val", valor)


def _rotular_todos_os_pontos(
    serie, total: int, formato_numero: str = FORMATO_PERCENTUAL
) -> None:
    for indice in range(total):
        _rotular_apenas_ultimo_ponto(serie, indice, formato_numero)


def _posicoes_escalonadas_rotulos(
    tabela: pd.DataFrame, ordem: Sequence[str]
) -> Dict[str, XL_DATA_LABEL_POSITION]:
    """Alterna acima/abaixo quando os pontos finais formam um aglomerado."""
    finais: List[Tuple[str, float]] = []
    for nome in ordem:
        validos = pd.to_numeric(tabela[nome], errors="coerce").dropna()
        if not validos.empty:
            finais.append((nome, float(validos.iloc[-1])))
    if len(finais) < 2:
        return {nome: XL_DATA_LABEL_POSITION.RIGHT for nome, _ in finais}

    valores = [valor for _, valor in finais]
    amplitude = max(valores) - min(valores)
    referencia = max(abs(valor) for valor in valores) or 1.0
    distancia_minima = max(amplitude * 0.10, referencia * 0.012)
    ordenados = sorted(finais, key=lambda item: item[1], reverse=True)
    posicoes = {nome: XL_DATA_LABEL_POSITION.RIGHT for nome, _ in ordenados}

    inicio = 0
    while inicio < len(ordenados):
        fim = inicio + 1
        while (
            fim < len(ordenados)
            and abs(ordenados[fim - 1][1] - ordenados[fim][1]) <= distancia_minima
        ):
            fim += 1
        grupo = ordenados[inicio:fim]
        if len(grupo) > 1:
            alternativas = (
                (XL_DATA_LABEL_POSITION.ABOVE, XL_DATA_LABEL_POSITION.RIGHT)
                if len(grupo) == 2
                else (
                    XL_DATA_LABEL_POSITION.ABOVE,
                    XL_DATA_LABEL_POSITION.RIGHT,
                    XL_DATA_LABEL_POSITION.BELOW,
                )
            )
            for posicao, (nome, _) in enumerate(grupo):
                posicoes[nome] = alternativas[posicao % len(alternativas)]
        inicio = fim
    return posicoes


def _estilizar_eixos(
    chart, total_categorias: int, formato_numero: str = FORMATO_PERCENTUAL
) -> None:
    eixo_valor = chart.value_axis
    eixo_valor.tick_labels.number_format = formato_numero
    eixo_valor.tick_labels.number_format_is_linked = False
    eixo_valor.tick_labels.font.size = Pt(FONTE_EIXO_PT)
    eixo_valor.tick_labels.font.color.rgb = COR_EIXO
    eixo_valor.has_major_gridlines = True
    eixo_valor.major_gridlines.format.line.color.rgb = COR_GRADE
    eixo_valor.major_gridlines.format.line.width = Pt(0.5)
    eixo_valor.format.line.color.rgb = COR_GRADE
    eixo_valor.major_tick_mark = XL_TICK_MARK.NONE
    eixo_valor.minor_tick_mark = XL_TICK_MARK.NONE

    eixo_categoria = chart.category_axis
    eixo_categoria.tick_labels.font.size = Pt(FONTE_EIXO_PT)
    eixo_categoria.tick_labels.font.color.rgb = COR_EIXO
    eixo_categoria.has_major_gridlines = False
    eixo_categoria.format.line.color.rgb = COR_GRADE
    eixo_categoria.major_tick_mark = XL_TICK_MARK.NONE
    eixo_categoria.minor_tick_mark = XL_TICK_MARK.NONE
    _definir_intervalo_rotulos(eixo_categoria, total_categorias)


def _adicionar_painel(
    slide,
    painel: Any,
    *,
    left: Emu,
    top: Emu,
    width: Emu,
    height: Emu,
    rotulo_serie_fn,
) -> Dict[str, Any]:
    """Desenha um quadrante: título, subtítulo, fonte e gráfico nativo."""
    _caixa_texto(
        slide, left=left, top=top, width=width, height=ALTURA_TITULO,
        texto=painel.titulo, tamanho=FONTE_TITULO_PT, cor=COR_TITULO, negrito=True,
    )
    _caixa_texto(
        slide, left=left, top=top + ALTURA_TITULO, width=width, height=ALTURA_SUBTITULO,
        texto=painel.subtitulo, tamanho=FONTE_SUBTITULO_PT, cor=COR_SUBTITULO,
    )
    _caixa_texto(
        slide, left=left, top=top + ALTURA_TITULO + ALTURA_SUBTITULO,
        width=width, height=ALTURA_FONTE,
        texto=painel.fonte, tamanho=FONTE_FONTE_PT, cor=COR_FONTE,
    )

    topo_grafico = top + ALTURA_TITULO + ALTURA_SUBTITULO + ALTURA_FONTE
    altura_grafico = height - (ALTURA_TITULO + ALTURA_SUBTITULO + ALTURA_FONTE)

    # `data_base` e `serie` chegam como categóricas com TODAS as categorias da
    # série histórica. Sem virar texto antes, o pivot recria as data-bases
    # ausentes como linhas vazias e o eixo do gráfico ganha meses fantasma.
    plano = painel.series.copy()
    plano["data_base"] = plano["data_base"].astype(str)
    plano["serie"] = plano["serie"].astype(str)
    tabela = plano.pivot_table(
        index="data_base", columns="serie", values="valor", aggfunc="first",
        observed=True,
    ).sort_index()
    ordem_categorias = getattr(painel, "ordem_categorias", None)
    if ordem_categorias:
        presentes = [categoria for categoria in ordem_categorias if categoria in tabela.index]
        tabela = tabela.reindex(presentes)
    indices = [str(idx) for idx in tabela.index]
    meses_validos = all(
        len(indice) >= 7 and indice[4] == "-" and indice[5:7].isdigit()
        for indice in indices
    )
    if meses_validos:
        datas = [pd.Timestamp(f"{indice[:7]}-01") for indice in indices]
        selecionadas, _ = eixo_datas_adaptativo(datas)
        meses_selecionados = {data.strftime("%Y-%m") for data in selecionadas}
        categorias = [
            rotulo_mes(indice) if indice[:7] in meses_selecionados else "\u00a0"
            for indice in indices
        ]
    else:
        categorias = indices

    dados = CategoryChartData()
    dados.categories = categorias
    ordem = [s for s in painel.ordem_series if s in tabela.columns]
    for nome in ordem:
        coluna = tabela[nome]
        valores = [None if pd.isna(v) else float(v) for v in coluna]
        dados.add_series(rotulo_serie_fn(nome), valores)

    tipo_grafico = getattr(painel, "tipo_grafico", "line")
    chart_type = (
        XL_CHART_TYPE.COLUMN_STACKED
        if tipo_grafico == "column_stacked"
        else XL_CHART_TYPE.LINE
    )
    formato_numero = getattr(painel, "formato_numero", FORMATO_PERCENTUAL)
    grafico = slide.shapes.add_chart(
        chart_type, left, topo_grafico, width, altura_grafico, dados
    ).chart
    grafico.has_title = False

    grafico.has_legend = True
    grafico.legend.position = XL_LEGEND_POSITION.BOTTOM
    grafico.legend.include_in_layout = False
    grafico.legend.font.size = Pt(FONTE_LEGENDA_PT)
    grafico.legend.font.color.rgb = COR_EIXO

    plot = grafico.plots[0]
    plot.has_data_labels = False

    indice_ultimo = len(categorias) - 1
    posicoes_rotulos = _posicoes_escalonadas_rotulos(tabela, ordem)
    for posicao, nome in enumerate(ordem):
        serie = plot.series[posicao]
        serie.smooth = False
        cor = _hex_para_rgb(painel.cores.get(nome, "#8F8F8F"))
        eh_total = nome in painel.tracejadas
        if tipo_grafico == "column_stacked":
            serie.format.fill.solid()
            serie.format.fill.fore_color.rgb = cor
            serie.format.line.color.rgb = cor
        else:
            linha = serie.format.line
            linha.color.rgb = cor
            linha.width = Pt(LARGURA_LINHA_TOTAL_PT if eh_total else LARGURA_LINHA_PT)
            if eh_total:
                linha.dash_style = MSO_LINE_DASH_STYLE.DASH

        coluna = tabela[nome]
        ultimo_valido = indice_ultimo
        while ultimo_valido >= 0 and pd.isna(coluna.iloc[ultimo_valido]):
            ultimo_valido -= 1
        rotular_todos = bool(getattr(painel, "rotular_todos_pontos", False))
        if rotular_todos:
            _rotular_todos_os_pontos(serie, len(coluna), formato_numero)
            indices_rotulados = [
                indice for indice, valor in enumerate(coluna) if pd.notna(valor)
            ]
        else:
            _rotular_apenas_ultimo_ponto(serie, ultimo_valido, formato_numero)
            indices_rotulados = [ultimo_valido] if ultimo_valido >= 0 else []
        for indice_rotulo in indices_rotulados:
            rotulo = serie.points[indice_rotulo].data_label
            if not rotular_todos:
                rotulo.position = posicoes_rotulos.get(
                    nome, XL_DATA_LABEL_POSITION.RIGHT
                )
            rotulo.font.size = Pt(FONTE_ROTULO_PT)
            rotulo.font.bold = True
            rotulo.font.color.rgb = _hex_para_rgb(painel.cores.get(nome, "#8F8F8F"))

    _estilizar_eixos(grafico, len(categorias), formato_numero)

    return {
        "titulo": painel.titulo,
        "series": len(ordem),
        "categorias": len(categorias),
        "rotulos": len(ordem),
    }


def exportar_paineis_pptx(
    paineis: Sequence[Any],
    *,
    rotulo_serie_fn=None,
    titulo_deck: Optional[str] = None,
) -> Tuple[bytes, Dict[str, Any]]:
    """Monta o PPTX com quatro painéis por slide e devolve os bytes.

    ``rotulo_serie_fn`` traduz o nome cru da série para o rótulo da legenda
    (por exemplo, "Mais de 1 a 2 salários mínimos" -> "1 a 2").
    """
    if not paineis:
        raise ValueError("nenhum painel para exportar")

    rotulo_serie_fn = rotulo_serie_fn or (lambda nome: nome)

    prs = Presentation()
    prs.slide_width = SLIDE_LARGURA
    prs.slide_height = SLIDE_ALTURA
    layout_branco = prs.slide_layouts[6]

    largura_quadrante = Emu(int((SLIDE_LARGURA - 2 * MARGEM - GUTTER_H) / 2))
    altura_quadrante = Emu(
        int((SLIDE_ALTURA - 2 * MARGEM - TOPO_CONTEUDO - GUTTER_V) / 2)
    )

    resumo: List[Dict[str, Any]] = []
    slides = 0
    for inicio in range(0, len(paineis), PAINEIS_POR_SLIDE):
        bloco = paineis[inicio:inicio + PAINEIS_POR_SLIDE]
        slide = prs.slides.add_slide(layout_branco)
        slides += 1

        if titulo_deck:
            _caixa_texto(
                slide, left=MARGEM, top=Inches(0.16),
                width=Emu(int(SLIDE_LARGURA - 2 * MARGEM)), height=Inches(0.3),
                texto=titulo_deck, tamanho=11, cor=COR_SUBTITULO,
            )

        for posicao, painel in enumerate(bloco):
            coluna, linha = posicao % 2, posicao // 2
            left = Emu(int(MARGEM + coluna * (largura_quadrante + GUTTER_H)))
            top = Emu(int(MARGEM + TOPO_CONTEUDO + linha * (altura_quadrante + GUTTER_V)))
            resumo.append(_adicionar_painel(
                slide, painel,
                left=left, top=top,
                width=largura_quadrante, height=altura_quadrante,
                rotulo_serie_fn=rotulo_serie_fn,
            ))

    buffer = BytesIO()
    prs.save(buffer)
    return buffer.getvalue(), {
        "slides": slides,
        "paineis": len(paineis),
        "paineis_por_slide": PAINEIS_POR_SLIDE,
        "formato_percentual": FORMATO_PERCENTUAL,
        "detalhe": resumo,
    }
