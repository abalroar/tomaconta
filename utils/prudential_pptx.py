"""Editable financial statements using Snapshot's native PowerPoint tables."""
from __future__ import annotations

from io import BytesIO
import json

from .financial_statement_style import KEY_FILL, NEGATIVE, RULE, SECTION
from .presentation_tables import _slide, _table, _cell, _font, _text, _WIDTH, _HEIGHT, _MARGIN, _CONTENT, _MUTED
from .prudential_presentation import (PAGE_GROUPS, display_rows, format_cell, institution_label, period_cells,
                                      period_chunks, period_label, period_source, row_tier, value_tone)

MAX_ROWS = 21
TABLE_TOP = 1.24
HEADER_HEIGHT = .50
BODY_HEIGHT = 5.20
ROW_FLOOR = BODY_HEIGHT / MAX_ROWS
ROW_CEILING = .38
# Amount and share of a period read as one block, whatever the number of periods.
PERIOD_WIDTH = {1: 3.2, 2: 2.8, 3: 2.4, 4: 2.05}
PERCENT_WIDTH = .62
CELL_PADDING = .015
ZERO_COLOR = "8E949B"


def row_height(label, style):
    # Calibri 12pt: only a label longer than the narrowest column takes a second line.
    width = 62 - (3 if style == "indent" else 6 if style == "detail" else 0)
    return ROW_FLOOR if len(label) <= width else ROW_FLOOR * 1.7


def _accounting_groups(analysis, name):
    rows, groups, start = list(display_rows(analysis, name)), [], 0
    for title, last in PAGE_GROUPS[name]:
        end = next((i + 1 for i, row in enumerate(rows) if row[0] == last), len(rows))
        if rows[start:end]:
            groups.append((title, rows[start:end]))
        start = end
    return groups


def _paginate_group(sheet, rows):
    pages, page, height = [], [], 0
    for index, row in enumerate(rows):
        style = sheet.cells[f"B{row[1]}"].style
        h = row_height(row[2], style)
        # A parent account travels with its subaccounts, so no slide opens on them.
        reserve, following_count = 0, 0
        if style not in {"indent", "detail"}:
            for following in rows[index + 1:]:
                next_style = sheet.cells[f"B{following[1]}"].style
                if next_style not in {"indent", "detail"}:
                    break
                reserve += row_height(following[2], next_style)
                following_count += 1
        if reserve + h > BODY_HEIGHT or following_count >= MAX_ROWS:
            reserve, following_count = 0, 0
        if page and (len(page) + 1 + following_count > MAX_ROWS or height + h + reserve > BODY_HEIGHT):
            pages.append(page)
            page, height = [], 0
        page.append(row)
        height += h
    if page:
        pages.append(page)
    return pages


def paginate_rows(analysis, name):
    """Slides of one statement as (accounting group title, rows)."""
    sheet = analysis.sheets[name]
    slides = []
    for title, rows in _accounting_groups(analysis, name):
        pages = _paginate_group(sheet, rows)
        slides += [(title + (f" ({part}/{len(pages)})" if len(pages) > 1 else ""), page)
                   for part, page in enumerate(pages, 1)]
    return slides


def _edge(cell, side, color, width=6350):
    """Restyle one border already created by the shared cell helper."""
    node = cell._tc.get_or_add_tcPr().find(f"{{http://schemas.openxmlformats.org/drawingml/2006/main}}{side}")
    node.set("w", str(width))
    node.find("*/*").set("val", color.lstrip("#"))


def _value_color(cell, default):
    return {"negative": NEGATIVE, "missing": ZERO_COLOR, "zero": ZERO_COLOR}.get(value_tone(cell), default)


def _statement_table(slide, analysis, name, rows, periods, offset):
    from pptx.enum.text import PP_ALIGN
    from pptx.util import Inches, Pt

    sheet = analysis.sheets[name]
    block = PERIOD_WIDTH[len(periods)]
    widths = [_CONTENT - block * len(periods)] + [w for _ in periods for w in (block - PERCENT_WIDTH, PERCENT_WIDTH)]
    styles = [sheet.cells[f"B{r}"].style for _, r, _ in rows]
    base = min(ROW_CEILING, BODY_HEIGHT / max(1, sum(row_height(row[2], s) / ROW_FLOOR for row, s in zip(rows, styles))))
    heights = [HEADER_HEIGHT] + [base * row_height(row[2], s) / ROW_FLOOR for row, s in zip(rows, styles)]
    table = _table(slide, len(rows) + 1, 1 + 2 * len(periods), TABLE_TOP, heights, widths)
    _cell(table.cell(0, 0), "R$ milhões", header=True, size=12)
    for i, period in enumerate(periods):
        cell = table.cell(0, 1 + 2 * i)
        cell.merge(table.cell(0, 2 + 2 * i))
        _cell(cell, period_label(period), header=True, centered=True, size=12)
        paragraph = cell.text_frame.add_paragraph()
        paragraph.text = period_source(sheet, offset + i)
        _font(paragraph, 9, color="FFFFFF", centered=True)
    for target, ((ident, source_row, label), style) in enumerate(zip(rows, styles), 1):
        tier = row_tier(name, ident, style)
        bold = tier in {"key", "section", "total", "bold"}
        background = KEY_FILL if tier == "key" else SECTION if tier in {"section", "total"} else None
        size = 11 if tier == "detail" else 12
        label_cell = table.cell(target, 0)
        _cell(label_cell, label, size=size, bold=bold, background=background, color=_MUTED if tier == "detail" else "24282E")
        label_cell.margin_left = Inches(.09 + {"indent": .16, "detail": .30}.get(tier, 0))
        label_cell.margin_top = label_cell.margin_bottom = Inches(CELL_PADDING)
        label_cell.text_frame.paragraphs[0].font.italic = tier in {"detail", "ratio"}
        cells = [label_cell]
        for i, _ in enumerate(periods):
            amount, share = period_cells(sheet, source_row, offset + i)
            for j, cell in enumerate((amount, share)):
                target_cell = table.cell(target, 1 + 2 * i + j)
                _cell(target_cell, format_cell(cell), size=10 if j else size, bold=bold,
                      color=_value_color(cell, _MUTED if j else "24282E"), background=background)
                target_cell.text_frame.paragraphs[0].alignment = PP_ALIGN.RIGHT
                target_cell.margin_left = Inches(.02)
                target_cell.margin_top = target_cell.margin_bottom = Inches(CELL_PADDING)
                cells.append(target_cell)
                if j == 0:
                    _edge(target_cell, "lnL", "E8EAED")
        if tier in {"key", "total"}:
            for cell in cells:
                if target > 1:  # The first row already sits under the header band.
                    _edge(cell, "lnT", RULE, 9525)
                if tier == "key":
                    _edge(cell, "lnB", RULE, 9525)
    return table


def render_pptx(analysis) -> bytes:
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(_WIDTH), Inches(_HEIGHT)
    prs.core_properties.title = f"{institution_label(analysis.institution)} · Análise financeira"
    prs.core_properties.author = "Toma Conta"
    institution = institution_label(analysis.institution)
    chunks = period_chunks(analysis.periods)
    for name in ("Balanço", "DRE", "Carteira 4.966"):
        note = "Resultado acumulado no semestre. " if name == "DRE" else ""
        for group, rows in paginate_rows(analysis, name):
            offset = 0
            for periods in chunks:
                span = " / ".join(period_label(p) for p in periods)
                slide = _slide(prs, f"{name} · {group}", f"{institution}  ·  Conglomerado prudencial  ·  {span}", len(prs.slides) + 1)
                _statement_table(slide, analysis, name, rows, periods, offset)
                _text(slide, _MARGIN, 7.04, _CONTENT, .22,
                      f"Fonte: Banco Central, COSIF 4060/4066 e IF.data. R$ milhões. {note}N/D: dado não disponível.", 9, color=_MUTED)
                slide.notes_slide.notes_text_frame.text = json.dumps({
                    "institution": analysis.code, "periods": periods, "statement": name,
                    "rows": [row[0] for row in rows], "methodology": analysis.limitations,
                }, ensure_ascii=False, default=str)
                offset += len(periods)
    output = BytesIO()
    prs.save(output)
    return output.getvalue()
