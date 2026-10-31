"""Editable financial statements using Snapshot's native PowerPoint tables."""
from __future__ import annotations

from io import BytesIO
import json
import math

from .financial_statement_style import NEGATIVE, SECTION
from .presentation_tables import _slide, _table, _cell, _text, _WIDTH, _HEIGHT, _MARGIN, _CONTENT, _MUTED
from .prudential_analysis import col_name
from .prudential_presentation import display_rows, format_cell, institution_label, period_label

MAX_ROWS = 16
MAX_PERIODS = 3
LABEL_WIDTH = 4.35
BODY_HEIGHT = 5.05


def row_height(label, style):
    # Native Calibri 13pt: allow a second line before shrinking any text.
    width = 51 - (4 if style == "indent" else 8 if style == "detail" else 0)
    return .30 if len(label) <= width else .46 if len(label) <= width * 2 else .62


def paginate_rows(analysis, name):
    rows = list(display_rows(analysis, name))
    sheet = analysis.sheets[name]
    pages, page, height = [], [], 0
    for index, row in enumerate(rows):
        style = sheet.cells[f"B{row[1]}"].style
        h = row_height(row[2], style)
        reserve = 0
        following_count = 0
        if style in {"section", "bold", "total"}:
            for following in rows[index + 1:]:
                next_style = sheet.cells[f"B{following[1]}"].style
                if next_style not in {"indent", "detail"}:
                    break
                reserve += row_height(following[2], next_style)
                following_count += 1
        if reserve + h > BODY_HEIGHT or following_count >= MAX_ROWS:
            reserve, following_count = 0, 0
        if page and (len(page) + following_count >= MAX_ROWS or height + h + reserve > BODY_HEIGHT):
            pages.append(page)
            page, height = [], 0
        page.append(row)
        height += h
    if page:
        pages.append(page)
    return pages


def render_pptx(analysis) -> bytes:
    from pptx import Presentation
    from pptx.enum.text import PP_ALIGN
    from pptx.util import Inches

    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(_WIDTH), Inches(_HEIGHT)
    prs.core_properties.title = f"{institution_label(analysis.institution)} · Análise financeira"
    prs.core_properties.author = "Toma Conta"
    for name in ("Balanço", "DRE", "Carteira 4.966"):
        sheet = analysis.sheets[name]
        pages = paginate_rows(analysis, name)
        for offset in range(0, len(analysis.periods), MAX_PERIODS):
            periods = analysis.periods[offset:offset + MAX_PERIODS]
            for part, rows in enumerate(pages, 1):
                title = name + (f" · {part}/{len(pages)}" if len(pages) > 1 else "")
                subtitle = f"{institution_label(analysis.institution)} · Conglomerado prudencial · " + " / ".join(period_label(p) for p in periods)
                slide = _slide(prs, title, subtitle, len(prs.slides) + 1)
                numeric = (_CONTENT - LABEL_WIDTH) / len(periods)
                widths = [LABEL_WIDTH] + [w for _ in periods for w in (numeric * .67, numeric * .33)]
                heights = [.57] + [row_height(label, sheet.cells[f"B{r}"].style) for _, r, label in rows]
                table = _table(slide, len(rows) + 1, 1 + 2 * len(periods), 1.30, heights, widths)
                _cell(table.cell(0, 0), "R$ milhões", header=True, size=13)
                for i, period in enumerate(periods):
                    source = str(sheet.cells[f"{col_name(3+2*(offset+i))}5"].value).replace("COSIF ", "")
                    cell = table.cell(0, 1 + 2*i)
                    cell.merge(table.cell(0, 2 + 2*i))
                    _cell(cell, f"{period_label(period)} · {source}", header=True, centered=True, size=12)
                for target, (ident, source_row, label) in enumerate(rows, 1):
                    style = sheet.cells[f"B{source_row}"].style
                    bold = style in {"section", "total", "bold"}
                    background = SECTION if style in {"section", "total"} else None
                    label_cell = table.cell(target, 0)
                    _cell(label_cell, label, size=12 if style == "detail" else 13, bold=bold, background=background)
                    label_cell.margin_left = Inches(.09 + (.15 if style == "indent" else .30 if style == "detail" else 0))
                    for i, _ in enumerate(periods):
                        for j in range(2):
                            cell = sheet.cells.get(f"{col_name(3+2*(offset+i)+j)}{source_row}")
                            value = cell.value if cell else None
                            color = NEGATIVE if isinstance(value, (int, float)) and math.isfinite(value) and value < 0 else _MUTED if j or value == "N/D" else "24282E"
                            target_cell = table.cell(target, 1 + 2*i + j)
                            _cell(target_cell, format_cell(cell), size=11 if j else 14, bold=bold, color=color, background=background)
                            target_cell.text_frame.paragraphs[0].alignment = PP_ALIGN.RIGHT
                _text(slide, _MARGIN, 7.04, _CONTENT, .22,
                      "Fonte: Banco Central · COSIF 4060/4066 e IF.data. N/D: dado não disponível.", 9, color=_MUTED)
                slide.notes_slide.notes_text_frame.text = json.dumps({
                    "institution": analysis.code, "periods": periods, "statement": name,
                    "rows": [row[0] for row in rows], "methodology": analysis.limitations,
                }, ensure_ascii=False, default=str)
    output = BytesIO()
    prs.save(output)
    return output.getvalue()
