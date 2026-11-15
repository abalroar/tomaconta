"""Exporta uma vista (vistas.py) para Excel e PowerPoint com tabela e gráficos de linha nativos, editáveis.

Adaptado do gdes-bancos (src/gdes/exportar.py), sem importá-lo. Disposição 16:9 nos dois formatos: a tabela ocupa a
área inteira; um gráfico ocupa a área inteira, dois ficam em cima e embaixo, três ou quatro vão para os quatro cantos.
"""
from __future__ import annotations

import io

from . import config as C
from .vistas import Graf, Tab, Vista, fmt, texto

LINHA = {b: C.cor(b, "claro") for b in C.CORES}                  # cor de cada instituição nas séries e nos rótulos
FUNDO = {b: C.cor(b, "fundo").lstrip("#") for b in C.CORES}      # cabeçalho com o nome da instituição
CURTO = {k: v["curto"] for k, v in C.INSTITUICOES.items()}
CM = 360000                                 # EMU por centímetro
SLIDE_W, SLIDE_H = 33.867, 19.05            # 16:9 em cm
FMT_XL = {"mi": "#,##0;−#,##0", "pct1": "0.0%;−0.0%", "x1": '0.0"x"', "txt": "@"}
FMT_EIXO = {"mi": "#,##0", "pct1": "0%", "x1": '0.0"x"'}
RECUO = {"recuo": 1, "pct": 1}


def caixas(n: int, x0: float, y0: float, w: float, h: float, vao: float = 0.4) -> list[tuple]:
    if n <= 1:
        return [(x0, y0, w, h)]
    if n == 2:
        hh = (h - vao) / 2
        return [(x0, y0, w, hh), (x0, y0 + hh + vao, w, hh)]
    ww, hh = (w - vao) / 2, (h - vao) / 2
    return [(x0 + (ww + vao) * (i % 2), y0 + (hh + vao) * (i // 2), ww, hh) for i in range(min(n, 4))]


def _posicoes(g: Graf) -> dict[str, str]:
    """Rótulo do último ponto: à direita; quando duas linhas terminam coladas, uma vai acima e a outra abaixo."""
    fins = sorted((next(x for x in reversed(v) if x is not None), b) for b, v in g.series if any(x is not None for x in v))
    if not fins:
        return {}
    faixa = (fins[-1][0] - min(fins[0][0], 0)) or 1
    pos = {b: "r" for _, b in fins}
    for (v0, b0), (v1, b1) in zip(fins, fins[1:]):
        if (v1 - v0) / faixa < 0.07:
            pos[b0] = "b" if pos[b0] == "r" else pos[b0]
            pos[b1] = "t"
    return pos


def _ultimo(vals: list) -> int | None:
    idx = [i for i, x in enumerate(vals) if x is not None]
    return idx[-1] if idx else None


# ================================================================ Excel
def para_excel(v: Vista) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    wb.remove(wb.active)
    branco, cinza = Font(color="FFFFFF", bold=True), PatternFill("solid", fgColor="3F4350")
    if v.tabela is not None:
        t: Tab = v.tabela
        ws = wb.create_sheet("Tabela")
        ws.sheet_view.showGridLines = False
        ws.cell(1, 1, v.titulo).font = Font(bold=True, size=12)
        lin = 3
        if t.grupos:
            col = 2
            for i, (nome, n) in enumerate(t.grupos):
                if n > 1:
                    ws.merge_cells(start_row=lin, start_column=col, end_row=lin, end_column=col + n - 1)
                c = ws.cell(lin, col, nome)
                b = t.chaves[i] if i < len(t.chaves) else None
                c.fill, c.font, c.alignment = PatternFill("solid", fgColor=FUNDO[b] if b else "3F4350"), branco, Alignment(horizontal="center")
                col += n
            lin += 1
        c = ws.cell(lin, 1, t.canto)
        c.fill, c.font = cinza, branco
        for j, nome in enumerate(t.colunas):
            c = ws.cell(lin, 2 + j, nome)
            c.fill, c.font, c.alignment = cinza, branco, Alignment(horizontal="center")
        cab = lin
        lin += 1
        for l in t.linhas:
            if l.estilo == "sep":
                ws.row_dimensions[lin].height = 6
                lin += 1
                continue
            c = ws.cell(lin, 1, l.rotulo)
            c.alignment = Alignment(indent=RECUO.get(l.estilo, 0))
            fonte = Font(bold=l.estilo in ("forte", "grp"), color="5B616E" if l.estilo == "pct" else "000000",
                         size=10 if l.estilo == "pct" else 11)
            c.font = fonte
            if l.estilo != "grp":
                for j, cel in enumerate(l.cels):
                    x = ws.cell(lin, 2 + j, cel.v if cel.v is not None else t.vazio)
                    x.number_format, x.font = FMT_XL[cel.f], fonte
                    x.alignment = Alignment(horizontal="center", vertical="center")
            lin += 1
        ws.column_dimensions["A"].width = min(60, max(16, max((len(l.rotulo) for l in t.linhas), default=10) + 4))
        for j in range(len(t.colunas)):
            ws.column_dimensions[get_column_letter(2 + j)].width = max(9.5, max(len(c) for c in t.colunas) + 3)
        for k, txt in enumerate([v.nota, *v.notas]):
            n = ws.cell(lin + 1 + k, 1, txt)
            n.font, n.alignment = Font(italic=True, color="6C717B", size=9), Alignment(wrap_text=False, vertical="top")
        ws.freeze_panes = ws.cell(cab + 1, 2)
        ws.page_setup.orientation, ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = "landscape", 1, 0
        ws.sheet_properties.pageSetUpPr.fitToPage = True
    if v.graficos:
        _graficos_excel(wb, v)
    saida = io.BytesIO()
    wb.save(saida)
    return saida.getvalue()


def _graficos_excel(wb, v: Vista) -> None:
    from openpyxl.chart import LineChart, Reference
    from openpyxl.chart.label import DataLabel, DataLabelList
    from openpyxl.chart.layout import Layout, ManualLayout
    from openpyxl.chart.shapes import GraphicalProperties
    from openpyxl.chart.text import RichText
    from openpyxl.drawing.line import LineProperties
    from openpyxl.drawing.spreadsheet_drawing import AbsoluteAnchor
    from openpyxl.drawing.text import CharacterProperties, Paragraph, ParagraphProperties
    from openpyxl.drawing.xdr import XDRPoint2D, XDRPositiveSize2D
    from openpyxl.styles import Alignment, Font

    def fonte(tam: int, negrito: bool = False, cor: str = "16181D") -> RichText:
        cp = CharacterProperties(sz=tam * 100, b=negrito, solidFill=cor)
        return RichText(p=[Paragraph(pPr=ParagraphProperties(defRPr=cp), endParaRPr=cp)])

    wg = wb.create_sheet("Gráficos")
    wg.sheet_view.showGridLines = False
    wd = wb.create_sheet("Dados dos gráficos")
    wd.column_dimensions["A"].width = 12
    lin = 1
    grafs = v.graficos[:4]
    for g, (x, y, w, h) in zip(grafs, caixas(len(grafs), 0.3, 0.3, SLIDE_W, SLIDE_H)):
        wd.cell(lin, 1, g.titulo).font = Font(bold=True)
        wd.cell(lin + 1, 1, "Trimestre").font = Font(bold=True)
        for j, (b, vals) in enumerate(g.series):
            wd.cell(lin + 1, 2 + j, CURTO[b]).font = Font(bold=True)
            for i, val in enumerate(vals):
                wd.cell(lin + 2 + i, 2 + j, val).number_format = FMT_XL[g.formato]
        for i, cat in enumerate(g.categorias):
            wd.cell(lin + 2 + i, 1, cat)
        n, k = len(g.categorias), len(g.series)
        ch = LineChart()
        ch.add_data(Reference(wd, min_col=2, max_col=1 + k, min_row=lin + 1, max_row=lin + 1 + n), titles_from_data=True)
        ch.set_categories(Reference(wd, min_col=1, min_row=lin + 2, max_row=lin + 1 + n))
        ch.title, ch.style, ch.dispBlanksAs = g.titulo, 2, "gap"
        ch.title.tx.rich.p[0].pPr = ParagraphProperties(defRPr=CharacterProperties(sz=1200, b=True, solidFill="16181D"))
        ch.title.overlay = False
        ch.legend.position, ch.legend.txPr = "b", fonte(10, cor="5B616E")
        ch.x_axis.delete = ch.y_axis.delete = False
        ch.x_axis.txPr = ch.y_axis.txPr = fonte(9, cor="6C717B")
        ch.x_axis.graphicalProperties = GraphicalProperties(ln=LineProperties(solidFill="E3E5E9"))
        ch.y_axis.graphicalProperties = GraphicalProperties(ln=LineProperties(noFill=True))
        ch.y_axis.majorGridlines.spPr = GraphicalProperties(ln=LineProperties(solidFill="E3E5E9", w=6350))
        ch.y_axis.number_format = FMT_EIXO[g.formato]
        ch.y_axis.scaling.min = 0 if min((x for _, vs in g.series for x in vs if x is not None), default=0) >= 0 else None
        ch.layout = Layout(manualLayout=ManualLayout(x=0.02, y=0.12, w=0.88, h=0.7, xMode="edge", yMode="edge"))
        pos = _posicoes(g)
        for s, (b, vals) in zip(ch.series, g.series):
            cor = LINHA[b].lstrip("#")
            s.smooth = False
            s.graphicalProperties.line.solidFill, s.graphicalProperties.line.width = cor, 22225
            s.marker.symbol, s.marker.size = "circle", 5
            s.marker.graphicalProperties = GraphicalProperties(solidFill=cor, ln=LineProperties(solidFill=cor))
            u = _ultimo(vals)
            if u is not None:
                rot = DataLabel(idx=u, dLblPos=pos.get(b, "r"), showVal=True, showSerName=False, showCatName=False,
                                showLegendKey=False, showPercent=False, txPr=fonte(9, negrito=True, cor=cor))
                s.dLbls = DataLabelList(dLbl=[rot], showVal=False, showSerName=False, showCatName=False, showLegendKey=False, showPercent=False)
        ch.anchor = AbsoluteAnchor(pos=XDRPoint2D(int(x * CM), int(y * CM)), ext=XDRPositiveSize2D(int(w * CM), int(h * CM)))
        ch.width, ch.height = w, h
        wg.add_chart(ch)
        lin += n + 4
    for k, txt in enumerate([v.nota, *v.notas]):
        c = wd.cell(lin + 1 + k, 1, txt)
        c.font, c.alignment = Font(italic=True, color="6C717B", size=9), Alignment(wrap_text=False)


# ================================================================ PowerPoint
def para_pptx(v: Vista) -> bytes:
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
    from pptx.util import Cm, Emu, Pt

    prs = Presentation()
    prs.slide_width, prs.slide_height = Cm(SLIDE_W), Cm(SLIDE_H)
    margem, topo, base = 0.9, 2.0, 2.2              # cm: laterais, área do título, área da nota
    tinta, cinza_txt = RGBColor(0x16, 0x18, 0x1D), RGBColor(0x5B, 0x61, 0x6E)

    def slide_com_titulo(nota: str):
        s = prs.slides.add_slide(prs.slide_layouts[6])
        tb = s.shapes.add_textbox(Cm(margem), Cm(0.55), Cm(SLIDE_W - 2 * margem), Cm(1.1))
        p = tb.text_frame.paragraphs[0]
        p.text = v.titulo
        p.font.size, p.font.bold, p.font.color.rgb = Pt(18), True, tinta
        if nota:
            nb = s.shapes.add_textbox(Cm(margem), Cm(SLIDE_H - base + 0.1), Cm(SLIDE_W - 2 * margem), Cm(base - 0.2))
            nb.text_frame.word_wrap = True
            q = nb.text_frame.paragraphs[0]
            q.text = nota
            q.font.size, q.font.italic, q.font.color.rgb = Pt(6.5 if len(nota) < 1500 else 5.5), True, RGBColor(0x6C, 0x71, 0x7B)
        return s

    area = (margem, topo, SLIDE_W - 2 * margem, SLIDE_H - topo - base)

    if v.tabela is not None:
        for parte in _paginas(v.tabela):
            _slide_tabela(slide_com_titulo(_nota_da_pagina(v, parte)), parte, area)

    if v.graficos:
        _graficos_pptx(slide_com_titulo(v.nota_completa), v, area)
    saida = io.BytesIO()
    prs.save(saida)
    return saida.getvalue()


def _nota_da_pagina(v: Vista, t: Tab) -> str:
    """Fonte + só as notas cujas chamadas "(n)" aparecem nas linhas do slide, e as lacunas da fonte."""
    import re
    chamadas = {m for l in t.linhas for m in re.findall(r"\((\d+)\)$", l.rotulo)}
    escolhidas = [n for n in v.notas if not re.match(r"\(\d+\)", n) or re.match(r"\((\d+)\)", n).group(1) in chamadas]
    return " ".join([v.nota, *escolhidas])


def _paginas(t: Tab, max_linhas: int = 27) -> list[Tab]:
    """Tabela longa vira um slide por bloco (blocos pequenos dividem o slide), para o corpo não cair abaixo de 7 pt."""
    blocos, atual = [], []
    for l in t.linhas:
        if l.estilo == "sep":
            if atual:
                blocos.append(atual)
            atual = []
            continue
        atual.append(l)
    if atual:
        blocos.append(atual)
    paginas, pag = [], []
    for bl in blocos:
        if pag and len(pag) + 1 + len(bl) > max_linhas:
            paginas.append(pag)
            pag = []
        pag = pag + ([type(bl[0])("", [], "sep")] if pag else []) + bl
    if pag:
        paginas.append(pag)
    return [Tab(t.canto, t.colunas, ls, t.grupos, t.chaves, t.vazio) for ls in paginas]


def _slide_tabela(s, t: Tab, area: tuple) -> None:
    from pptx.dml.color import RGBColor
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
    from pptx.util import Cm, Emu, Pt

    tinta, cinza_txt = RGBColor(0x16, 0x18, 0x1D), RGBColor(0x5B, 0x61, 0x6E)
    if True:
        n_cab = 2 if t.grupos else 1
        n_lin, n_col = n_cab + len(t.linhas), 1 + len(t.colunas)
        x, y, w, h = area
        forma = s.shapes.add_table(n_lin, n_col, Cm(x), Cm(y), Cm(w), Cm(h))
        tab = forma.table
        # sem o estilo azul padrão do PowerPoint: "Sem estilo, sem grade"
        forma._element.graphic.graphicData.tbl.tblPr.find("{http://schemas.openxmlformats.org/drawingml/2006/main}tableStyleId").text = "{2D5ABB26-0587-4C30-8999-92F81FD0307C}"
        tab.first_row = tab.horz_banding = False
        seps = sum(1 for l in t.linhas if l.estilo == "sep")
        alt = h / (n_lin - seps * 0.65)
        pt = max(5.0, min(12.0, alt / 2.54 * 72 * 0.56))
        maior = max([len(l.rotulo) + 2 * RECUO.get(l.estilo, 0) for l in t.linhas] + [len(t.canto)])
        w1 = min(w * 0.30, max(w * 0.12, maior * pt * 0.5 / 72 * 2.54 + 0.3))
        larg_col = (w - w1) / (n_col - 1)
        mais_largo = max([len(c) for c in t.colunas] + [len(texto(c)) for l in t.linhas for c in l.cels])
        pt = max(4.5, min(pt, (larg_col - 0.14) / 2.54 * 72 / (mais_largo * 0.6)))
        w1 = min(w * 0.30, max(w * 0.12, maior * pt * 0.5 / 72 * 2.54 + 0.3))
        tab.columns[0].width = Cm(w1)
        for j in range(1, n_col):
            tab.columns[j].width = Emu(int(Cm(w - w1) / (n_col - 1)))

        def cel(i, j, s_, negrito=False, cor=tinta, alinh=PP_ALIGN.CENTER, fundo=None, tam=None, recuo=0):
            c = tab.cell(i, j)
            c.margin_left, c.margin_right, c.margin_top, c.margin_bottom = Cm(0.07), Cm(0.07), 0, 0
            c.vertical_anchor = MSO_ANCHOR.MIDDLE
            c.text_frame.word_wrap = False
            p = c.text_frame.paragraphs[0]
            p.text, p.alignment = " " * (3 * recuo) + s_, alinh
            p.font.size, p.font.bold, p.font.color.rgb = Pt(tam or pt), negrito, cor
            if fundo:
                c.fill.solid()
                c.fill.fore_color.rgb = RGBColor.from_string(fundo)
            else:
                c.fill.background()
            return c

        branco = RGBColor(0xFF, 0xFF, 0xFF)
        i = 0
        if t.grupos:
            cel(0, 0, "")
            j = 1
            for g_i, (nome, n) in enumerate(t.grupos):
                b = t.chaves[g_i] if g_i < len(t.chaves) else None
                cel(0, j, nome, True, branco, PP_ALIGN.CENTER, FUNDO[b] if b else "3F4350")
                if n > 1:
                    tab.cell(0, j).merge(tab.cell(0, j + n - 1))
                j += n
            i = 1
        cel(i, 0, t.canto, True, branco, PP_ALIGN.LEFT, "3F4350")
        for j, nome in enumerate(t.colunas):
            cel(i, 1 + j, nome, True, branco, PP_ALIGN.CENTER, "3F4350")
        for r in range(n_cab):
            tab.rows[r].height = Cm(alt)
        for k, l in enumerate(t.linhas):
            r = n_cab + k
            if l.estilo == "sep":
                tab.rows[r].height = Cm(alt * 0.35)
                for j in range(n_col):
                    cel(r, j, "", tam=1)
                continue
            tab.rows[r].height = Cm(alt)
            forte, fraco = l.estilo in ("forte", "grp"), l.estilo == "pct"
            cel(r, 0, l.rotulo, forte, cinza_txt if fraco else tinta, PP_ALIGN.LEFT, tam=pt * (0.92 if fraco else 1),
                recuo=RECUO.get(l.estilo, 0))
            for j in range(1, n_col):
                c = l.cels[j - 1] if j - 1 < len(l.cels) else None
                cel(r, j, "" if l.estilo == "grp" else texto(c), forte, cinza_txt if fraco else tinta, tam=pt * (0.92 if fraco else 1))


def _graficos_pptx(slide, v: Vista, area: tuple) -> None:
    from pptx.chart.data import CategoryChartData
    from pptx.dml.color import RGBColor
    from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION, XL_MARKER_STYLE, XL_TICK_LABEL_POSITION
    from pptx.util import Cm, Pt

    cinza, fio = RGBColor(0x6C, 0x71, 0x7B), RGBColor(0xE3, 0xE5, 0xE9)
    POS = {"r": XL_LABEL_POSITION.RIGHT, "t": XL_LABEL_POSITION.ABOVE, "b": XL_LABEL_POSITION.BELOW}
    grafs = v.graficos[:4]
    pequeno = len(grafs) > 2
    for g, (x, y, w, h) in zip(grafs, caixas(len(grafs), *area)):
        dados = CategoryChartData(number_format=FMT_XL[g.formato].split(";")[0])
        dados.categories = g.categorias
        for b, vals in g.series:
            dados.add_series(CURTO[b], vals)
        ch = slide.shapes.add_chart(XL_CHART_TYPE.LINE_MARKERS, Cm(x), Cm(y), Cm(w), Cm(h), dados).chart
        ch.font.size = Pt(9 if pequeno else 10)
        ch.has_title = True
        ch.chart_title.text_frame.text = g.titulo
        tp = ch.chart_title.text_frame.paragraphs[0]
        tp.font.size, tp.font.bold = Pt(11 if pequeno else 13), True
        ch.chart_title.include_in_layout = False
        ch.has_legend = True
        ch.legend.position, ch.legend.include_in_layout = XL_LEGEND_POSITION.BOTTOM, False
        ch.legend.font.size, ch.legend.font.color.rgb = Pt(9 if pequeno else 10), cinza
        ev, ec = ch.value_axis, ch.category_axis
        ev.has_major_gridlines = True
        ev.major_gridlines.format.line.color.rgb, ev.major_gridlines.format.line.width = fio, Pt(0.5)
        ev.format.line.fill.background()
        ev.tick_labels.font.size, ev.tick_labels.font.color.rgb = Pt(8 if pequeno else 9), cinza
        ev.tick_labels.number_format, ev.tick_labels.number_format_is_linked = FMT_EIXO[g.formato], False
        if min((val for _, vs in g.series for val in vs if val is not None), default=0) >= 0:
            ev.minimum_scale = 0
        ec.format.line.color.rgb = fio
        ec.tick_labels.font.size, ec.tick_labels.font.color.rgb = Pt(8 if pequeno else 9), cinza
        ec.tick_label_position = XL_TICK_LABEL_POSITION.LOW
        plot, pos = ch.plots[0], _posicoes(g)
        for s, (b, vals) in zip(plot.series, g.series):
            cor = RGBColor.from_string(LINHA[b].lstrip("#"))
            s.smooth = False
            s.format.line.color.rgb, s.format.line.width = cor, Pt(1.75)
            s.marker.style, s.marker.size = XL_MARKER_STYLE.CIRCLE, 5
            s.marker.format.fill.solid()
            s.marker.format.fill.fore_color.rgb = cor
            s.marker.format.line.color.rgb = cor
            i = _ultimo(vals)
            if i is None:
                continue
            rot = s.points[i].data_label                       # rótulo só no último ponto, no formato brasileiro
            rot.position = POS[pos.get(b, "r")]
            tf = rot.text_frame
            tf.text = fmt(vals[i], g.formato)
            tf.paragraphs[0].font.size, tf.paragraphs[0].font.bold = Pt(8 if pequeno else 9), True
            tf.paragraphs[0].font.color.rgb = cor
