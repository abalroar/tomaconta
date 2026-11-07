"""Portable Excel renderer for the Streamlit runtime (Python-only hosting).

The financial model is engine-independent. XlsxWriter is already part of the
application's deployment; the workbook stores the same independently calculated values alongside its
editable formulas. Native Excel and an independent recalculation verify the output.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from io import BytesIO
import math

import xlsxwriter

from .prudential_analysis import Analysis, col_name
from .prudential_presentation import (PERIODS_PER_PAGE, ZERO_EPSILON, committee_panel, reference_note, display_rows, institution_label, period_chunks,
                                      row_tier)
from .financial_statement_style import (FONT, INK, MUTED, GRID, RULE, ACCENT, NEGATIVE, BAND_NEGATIVE, BAND_MUTED, MISSING,
                                        EXCEL_STYLES as STYLES, excel_amount_width, excel_label_width,
                                        excel_number_format, excel_visible_format)

STATEMENTS = ("Balanço", "DRE", "Carteira 4.966")
COMMITTEE_PERIODS = 2
COMMITTEE_ROW = 15
HEADER_ROWS = 6
PERCENT_WIDTH = 5.8
# A4 in points, inside the margins, with a safety allowance for Excel's own rounding.
PRINT_SAFETY = .95
A4_LANDSCAPE = (842 - 44, 595 - 58)
A4_PORTRAIT = (595 - 44, 842 - 66)
MIN_SCALE = 60


def analysis_spec(analysis: Analysis) -> dict:
    return asdict(analysis)


def _column_points(*widths):
    # Measured on Excel for Mac, the widest renderer: about 6.6pt per column unit.
    return sum(widths) * 6.6


def _print_scale(width_points, height_points, page):
    fit = min(page[0] / width_points, page[1] / height_points) * PRINT_SAFETY
    return max(MIN_SCALE, min(100, int(fit * 100)))


def _is_percent(number_format):
    return "%" in (number_format or "")


def _value_kind(number_format):
    """Amounts, whole-percent shares and two-decimal ratios follow different display rules."""
    if not _is_percent(number_format):
        return "money"
    return "ratio" if "0.00" in number_format else "share"


def _runs(cells):
    """Compress cells into A1 ranges, per column, for one conditional format."""
    by_column, ranges = {}, []
    for row, column in sorted(set(cells)):
        by_column.setdefault(column, []).append(row)
    for column, rows in by_column.items():
        start = previous = rows[0]
        for row in rows[1:] + [None]:
            if row != previous + 1 if row is not None else True:
                ranges.append(f"{col_name(column + 1)}{start + 1}:{col_name(column + 1)}{previous + 1}")
                start = row
            previous = row
    return ranges


def _value_rules(wb, ws, cells, *, band=False):
    """Negative, zero and N/D stay distinct; values remain numeric and editable."""
    red, muted = (BAND_NEGATIVE, BAND_MUTED) if band else (NEGATIVE, "#8E949B")
    def rule(ranges, criteria, value, stop=False, **cfg):
        if not ranges:
            return
        options = {"type": "cell", "criteria": criteria, "format": wb.add_format(cfg), "stop_if_true": stop}
        if isinstance(value, tuple):
            options.update(minimum=value[0], maximum=value[1])
        else:
            options["value"] = value
        ws.conditional_format(ranges[0], {**options, "multi_range": " ".join(ranges)})
    runs = {kind: _runs((r, c) for r, c, k in cells if k == kind) for kind in ("money", "share", "ratio")}
    every = runs["money"] + runs["share"] + runs["ratio"]
    # Literal formats need both sections: Excel prefixes a sign to a single-section format.
    rule(every, "==", '"N/D"', stop=True, font_color=muted, num_format=f';;;"{MISSING}"')
    rule(runs["money"], "between", (-ZERO_EPSILON, ZERO_EPSILON), stop=True, font_color=muted, num_format='"0";"0"')
    rule(runs["money"], "between", (-.4999999, -ZERO_EPSILON), stop=True, font_color=red, num_format='"<1";"-<1"')
    rule(runs["money"], "between", (ZERO_EPSILON, .4999999), stop=True, num_format='"<1";"-<1"')
    rule(runs["share"], "between", (-.00499999, .00499999), stop=True, font_color=muted, num_format='"0%";"0%"')
    rule(every, "<", 0, font_color=red)


def _committee_sheet(wb, fmt, analysis):
    committee = wb.add_worksheet("Comitê")
    committee.hide_gridlines(2)
    committee.set_zoom(90)
    committee.set_default_row(COMMITTEE_ROW)
    committee.freeze_panes("C7" if len(analysis.periods) <= COMMITTEE_PERIODS else "C3")
    committee.set_column(0, 0, 1.5)
    shown = min(COMMITTEE_PERIODS, len(analysis.periods))
    panel_columns = 1 + 2 * shown
    right_start = 1 + panel_columns + 1
    end_col = right_start + panel_columns - 1
    panels = {name: committee_panel(analysis, name) for name in ("Balanço", "DRE")}
    body_rows = max(map(len, panels.values()))
    page_rows = HEADER_ROWS + body_rows + 3
    amounts = {name: excel_amount_width(c.value for key, c in analysis.sheets[name].cells.items()
                                        if key[0] != "B" and not _is_percent(c.fmt) and c.formula) for name in panels}
    widths = {}
    for name, start_col in (("Balanço", 1), ("DRE", right_start)):
        label = excel_label_width(row[2] for row in panels[name] if row)
        committee.set_column(start_col, start_col, label)
        widths[name] = label
        for i in range(shown):
            committee.set_column(start_col + 1 + 2 * i, start_col + 1 + 2 * i, amounts[name])
            committee.set_column(start_col + 2 + 2 * i, start_col + 2 + 2 * i, PERCENT_WIDTH)
    committee.set_column(1 + panel_columns, 1 + panel_columns, 2)
    title = wb.add_format({"font_name": FONT, "font_size": 14, "bold": True, "font_color": INK, "valign": "vcenter",
                           "bottom": 2, "bottom_color": ACCENT})
    light, band, page_breaks = [], [], []
    offsets = range(0, len(analysis.periods), COMMITTEE_PERIODS)
    for offset in offsets:
        top = (offset // COMMITTEE_PERIODS) * page_rows
        if top:
            page_breaks.append(top)
        committee.merge_range(top + 1, 1, top + 1, end_col, f"{analysis.scope_label} | Balanço e DRE", title)
        committee.set_row(top + 1, 24)
        committee.set_row(top + 2, 7)
        for name, start_col in (("Balanço", 1), ("DRE", right_start)):
            sheet = analysis.sheets[name]
            last_col = start_col + panel_columns - 1
            committee.merge_range(top + 3, start_col, top + 3, last_col, f"{institution_label(analysis.institution)} · {name}", fmt("band", left=True))
            committee.write(top + 4, start_col, "Fonte", fmt("source", left=True))
            committee.write(top + 5, start_col, "R$ milhões", fmt("band", left=True))
            for i, period in enumerate(analysis.periods[offset:offset + COMMITTEE_PERIODS]):
                c = start_col + 1 + 2 * i
                committee.merge_range(top + 4, c, top + 4, c + 1, sheet.cells[f"{col_name(3 + 2 * (offset + i))}5"].value, fmt("source"))
                committee.merge_range(top + 5, c, top + 5, c + 1, datetime(int(period[:4]), int(period[4:]), 1), fmt("header", "[$-416]mmm-yy"))
            for target_row, row in enumerate(panels[name], top + HEADER_ROWS):
                if row is None:
                    continue
                ident, source_row, label, style, tier = row
                look = "band" if tier == "key" else style
                committee.write(target_row, start_col, label, fmt(look))
                for i in range(shown):
                    for extra in range(2):
                        if offset + i >= len(analysis.periods):
                            continue
                        source_col = col_name(3 + 2 * (offset + i) + extra)
                        cell = sheet.cells.get(f"{source_col}{source_row}")
                        # Subaccounts carry amounts only, as in the committee model.
                        if name == "Balanço" and extra == 1 and (style in {"indent", "detail"} or ident == "net"):
                            cell = None
                        destination = start_col + 1 + 2 * i + extra
                        f = fmt(look, excel_visible_format(cell.fmt) if cell else None, True, edge=extra == 1, share=extra == 1)
                        if cell is not None and cell.value is not None:
                            committee.write_formula(target_row, destination, f"='{name}'!{source_col}{source_row}", f, cell.value)
                            (band if tier == "key" else light).append((target_row, destination, _value_kind(cell.fmt)))
                        else:
                            committee.write_blank(target_row, destination, None, f)
        note_row = top + HEADER_ROWS + body_rows + 1
        committee.merge_range(note_row, 1, note_row, end_col, f"Fonte: Banco Central, {analysis.source_label} e IF.data. R$ milhões. DRE acumulada no ano. " + f"{MISSING}: dado não disponível. {reference_note(analysis)}".rstrip(), fmt("note"))
        if reference_note(analysis):
            committee.set_row(note_row, 38)
    _value_rules(wb, committee, light)
    _value_rules(wb, committee, band, band=True)
    width_points = _column_points(*widths.values(), 2, *[PERCENT_WIDTH] * (2 * shown), *[a for a in amounts.values() for _ in range(shown)])
    committee.set_landscape()
    committee.set_paper(9)
    committee.set_print_scale(_print_scale(width_points, COMMITTEE_ROW * (page_rows - 1) + 24, A4_LANDSCAPE))
    if page_breaks:
        committee.set_h_pagebreaks(page_breaks)
    committee.set_margins(.3, .3, .35, .45)
    committee.center_horizontally()
    committee.print_area(1, 1, len(offsets) * page_rows - 1, end_col)
    committee.set_footer("&L&9Toma Conta · Banco Central&R&9&P / &N", {"margin": .2})
    committee.set_tab_color(ACCENT)


def _statement_page_setup(ws, analysis, sheet, height_points):
    ws.set_tab_color(ACCENT)
    ws.set_portrait()
    ws.set_paper(9)
    chunks = period_chunks(analysis.periods)
    widest = max(map(len, chunks))
    label = sheet.widths["B"]
    amount = sheet.widths["C"]
    width_points = _column_points(label, *[amount, PERCENT_WIDTH] * widest)
    ws.set_print_scale(_print_scale(width_points, height_points, A4_PORTRAIT))
    breaks, column = [], 2
    for chunk in chunks[:-1]:
        column += 2 * len(chunk)
        breaks.append(column)
    if breaks:
        ws.set_v_pagebreaks(breaks)
    ws.set_margins(.3, .3, .4, .5)
    ws.center_horizontally()
    ws.print_area(sheet.print_area)
    ws.repeat_rows(1, 5)
    ws.repeat_columns("A:B")
    ws.set_footer("&L&9Toma Conta · Banco Central&R&9&P / &N", {"margin": .2})


def _portfolio_sheet(wb, fmt, analysis, model):
    """The Carteira 4.966 menu's reading: same rows and values, without the deltas."""
    from tabs.carteira_4966 import GROUP_SPECS, ROW_SPECS, MetricCell
    ws = wb.add_worksheet("Carteira")
    ws.hide_gridlines(2)
    ws.set_tab_color(ACCENT)
    ws.set_default_row(15.75)
    ws.set_column(0, 0, 1.5)
    ws.set_column(1, 1, excel_label_width(spec.label for spec in ROW_SPECS))
    periods = list(model.periods)
    ws.set_column(2, 1 + 2 * len(periods), 9.5)
    last = 1 + 2 * len(periods)
    ws.merge_range(1, 1, 1, last, institution_label(analysis.institution), fmt("title"))
    ws.set_row(1, 22)
    ws.merge_range(2, 1, 2, last, f"Carteira 4.966 · {analysis.scope_label} · R$ milhões", fmt("note"))
    ws.write(4, 1, "R$ milhões", fmt("header", left=True))
    ws.write(5, 1, "", fmt("header"))
    for i, period in enumerate(periods):
        ws.merge_range(4, 2 + 2 * i, 4, 3 + 2 * i, model.period_labels.get(period, period), fmt("header"))
        ws.write(5, 2 + 2 * i, "R$ mm", fmt("header"))
        ws.write(5, 3 + 2 * i, "%", fmt("header"))
    row = 6
    money, ratio = '#,##0;-#,##0;0', '0.00%;-0.00%;0.00%'
    cells = []
    for group in GROUP_SPECS:
        specs = [spec for spec in ROW_SPECS if spec.group == group.key]
        if not specs:
            continue
        ws.merge_range(row, 1, row, last, group.label or "", fmt("section"))
        row += 1
        for spec in specs:
            look = "bold" if spec.emphasis else "body"
            ws.write(row, 1, spec.label, fmt(look))
            for i, period in enumerate(periods):
                value = model.cells.get(spec.key, {}).get(period, MetricCell(None))
                if spec.layout == "paired":
                    pairs = [(2 + 2 * i, value.primary, False), (3 + 2 * i, value.secondary, True)]
                else:
                    pairs = [(3 + 2 * i if spec.layout == "percent_span" else 2 + 2 * i, value.primary, spec.layout == "percent_span")]
                    ws.write_blank(row, 2 + 2 * i if spec.layout == "percent_span" else 3 + 2 * i, None, fmt(look, None, True, edge=spec.layout != "percent_span"))
                for column, number, percent in pairs:
                    number_format = excel_visible_format(ratio if percent else money)
                    f = fmt(look, number_format, True, edge=percent)
                    if number is None:
                        ws.write_string(row, column, "N/D", f)
                    else:
                        # O modelo guarda reais; a tela e esta aba mostram R$ milhões.
                        ws.write_number(row, column, number if percent else number / 1e6, f)
                    cells.append((row, column, "ratio" if percent else "money"))
            row += 1
    _value_rules(wb, ws, cells)
    ws.freeze_panes(6, 2)
    ws.set_portrait()
    ws.set_paper(9)
    ws.center_horizontally()
    ws.print_area(1, 1, row, last)
    # Up to four periods fit one page; longer selections continue with the labels repeated.
    if len(periods) <= PERIODS_PER_PAGE:
        ws.fit_to_pages(1, 1)
    else:
        ws.set_print_scale(_print_scale(_column_points(excel_label_width(s.label for s in ROW_SPECS), *[9.5] * (2 * PERIODS_PER_PAGE)), row * 15.75, A4_PORTRAIT))
        column, breaks = 2, []
        for chunk in period_chunks(periods)[:-1]:
            column += 2 * len(chunk)
            breaks.append(column)
        ws.set_v_pagebreaks(breaks)
        ws.repeat_columns("A:B")
        ws.repeat_rows(4, 5)
    ws.set_footer("&L&9Toma Conta · Banco Central&R&9&P / &N", {"margin": .2})


def _evolution_sheet(wb, fmt, analysis, evolution):
    """Same series and indicators as the Evolução tab, in the axis scale shown there."""
    from .evolucao_visual import SERIES, axis_scale, METRIC_LABELS, period_label as evolution_period
    ws = wb.add_worksheet("Evolução")
    ws.hide_gridlines(2)
    ws.set_tab_color(ACCENT)
    ws.set_default_row(15.75)
    frame, table, periods = evolution["df_graph"], evolution["df_show"], list(evolution["periods"])
    ws.set_column(0, 0, 1.5)
    ws.set_column(1, 1, 32)
    ws.set_column(2, 1 + len(periods), 10)
    ws.merge_range(1, 1, 1, 1 + len(periods), institution_label(analysis.institution), fmt("title"))
    ws.set_row(1, 22)
    ws.merge_range(2, 1, 2, 1 + len(periods), "Evolução · BCB IFData · Lucro acumulado no ano", fmt("note"))
    ws.write(4, 1, "Indicador", fmt("header", left=True))
    for i, period in enumerate(periods):
        ws.write(4, 2 + i, evolution_period(period), fmt("header"))
    row = 5
    cells = []
    for column, name, _, axis, _ in SERIES:
        divisor, unit, decimals = axis_scale(frame, axis)
        ws.write(row, 1, f"{name} ({unit})", fmt("body"))
        number_format = excel_visible_format("#,##0.0;-#,##0.0;0.0" if decimals else "#,##0;-#,##0;0")
        for i, value in enumerate(frame[column].tolist()):
            if value is None or value != value:
                ws.write_string(row, 2 + i, "N/D", fmt("body", number_format, True))
            else:
                ws.write_number(row, 2 + i, float(value) / divisor, fmt("body", number_format, True))
            cells.append((row, 2 + i, "money" if decimals == 0 else "ratio"))
        row += 1
    for _, line in table.iterrows():
        metric = str(line["Métrica"])
        ws.write(row, 1, METRIC_LABELS.get(metric, metric), fmt("body"))
        for i, period in enumerate(periods):
            text = str(line[period])
            ws.write_string(row, 2 + i, MISSING if text.startswith("-") and len(text) <= 2 else text, fmt("body", None, True))
        row += 1
    _value_rules(wb, ws, cells)
    ws.freeze_panes(5, 2)
    ws.set_landscape()
    ws.set_paper(9)
    ws.fit_to_pages(1, 1)
    ws.center_horizontally()
    ws.print_area(1, 1, row, 1 + len(periods))


def render_xlsx(analysis: Analysis, *, portfolio=None, evolution=None) -> bytes:
    buffer = BytesIO()
    wb = xlsxwriter.Workbook(buffer, {"in_memory": True, "strings_to_formulas": False, "strings_to_urls": False})
    wb.set_properties({"title": f"{analysis.institution} — Análise financeira", "author": "Toma Conta",
                       "comments": f"BCB {analysis.source_label} e IFData. Fórmulas e fontes preservadas no arquivo."})
    wb.set_calc_mode("auto")
    formats = {}

    def fmt(style, number_format=None, numeric=False, *, edge=False, share=False, left=False, wrap=False):
        key = (style, number_format, numeric, edge, share, left, wrap)
        if key not in formats:
            cfg = {"font_name": FONT, "font_size": 10, "font_color": INK, "valign": "vcenter", **STYLES[style]}
            if numeric:
                # A right-aligned indent would break the vertical reading of the amounts.
                cfg.pop("indent", None)
                cfg["align"] = "right"
            if number_format:
                cfg["num_format"] = excel_number_format(number_format)
            if left:
                cfg["align"] = "left"
            if wrap:
                cfg["text_wrap"] = True
            if share:
                cfg["font_size"] = 9
                if style != "band":
                    cfg["font_color"] = MUTED
            if edge:
                cfg.update(right=1, right_color=GRID)
            if style not in {"band", "header", "title", "note", "source", "technical", "key"} and "bottom" not in cfg:
                cfg.update(bottom=1, bottom_color=GRID)
            formats[key] = wb.add_format(cfg)
        return formats[key]

    # Each committee page follows the supplied photograph: two statements,
    # two periods, editable references. Long selections continue on new pages.
    _committee_sheet(wb, fmt, analysis)
    for name, s in analysis.sheets.items():
        if name == "Carteira 4.966":
            if portfolio is not None and portfolio.periods:
                _portfolio_sheet(wb, fmt, analysis, portfolio)
            if evolution is not None:
                _evolution_sheet(wb, fmt, analysis, evolution)
        ws = wb.add_worksheet(name)
        if name == "Carteira 4.966" and not analysis.has_portfolio:
            ws.hide()
        ws.hide_gridlines(2)
        ws.set_zoom(100 if name in STATEMENTS else 85)
        statement = name in STATEMENTS
        ws.set_default_row(15.75 if statement else 20)
        rows = {}
        height_points = 0
        widths = dict(s.widths)
        heights = dict(s.heights)
        if statement:
            rows = {r: (ident, label) for ident, r, label in display_rows(analysis, name)}
            amount = excel_amount_width(c.value for address, c in s.cells.items() if address[0] != "B" and c.formula and not _is_percent(c.fmt))
            widths["A"], widths["B"] = 1.5, excel_label_width(label for _, label in rows.values())
            for i in range(len(analysis.periods)):
                widths[col_name(3 + 2 * i)], widths[col_name(4 + 2 * i)] = amount, PERCENT_WIDTH
            for row in heights:
                if row in rows or row > 6:
                    heights[row] = 15.75
            heights.update({2: 22, 3: 15, 5: 15, 6: 18})
            height_points = sum(heights.get(r, 15.75) for r in range(2, s.last_row + 1) if r not in s.hidden_rows)
            s = _with_widths(s, widths)
        for col, width in widths.items():
            ws.set_column(f"{col}:{col}", width)
        for row, height in heights.items():
            ws.set_row(row - 1, height, options={"hidden": row in s.hidden_rows})
        for row in s.hidden_rows:
            ws.set_row(row - 1, heights.get(row, 19), options={"hidden": True, "level": 1})
        # On a selection split across pages, the account column repeats alone: a merged
        # title or note would print cut at its width, so those wrap inside the column.
        unmerged = set()
        if statement and len(period_chunks(analysis.periods)) > 1:
            unmerged = {address for address, cell in s.cells.items() if cell.style in {"title", "note"}}
            label_units = widths["B"]
            for address in unmerged:
                row = int(address[1:])
                # The note always takes the same source sentence, longer than the model's placeholder.
                factor, line, length = (1.5, 19, len(str(s.cells[address].value))) if s.cells[address].style == "title" else (1.1, 12.5, 110)
                heights[row] = max(heights.get(row, 15), line * math.ceil(length * factor / label_units))
                ws.set_row(row - 1, heights[row])
        for merged in s.merges:
            anchor = merged.split(":")[0]
            if anchor in unmerged:
                continue
            cell = s.cells[anchor]
            ws.merge_range(merged, "", fmt(cell.style, cell.fmt))
        labels = {f"B{r}": label for r, (_, label) in rows.items()}
        if statement:
            labels["B3"] = f"{name} · {analysis.scope_label} · R$ milhões"
            labels["B5"] = "Fonte"
            labels["B6"] = "R$ milhões"
            note = "DRE acumulada no ano. " if name == "DRE" else ""
            labels.update({address: f"Fonte: Banco Central, {analysis.source_label} e IF.data. R$ milhões. {note}{MISSING}: dado não disponível. {reference_note(analysis) if name == 'DRE' else ''}".rstrip()
                           for address, cell in s.cells.items() if cell.style == "note" and address != "B3"})
        values = []
        for address, cell in s.cells.items():
            numeric = isinstance(cell.value, (int, float)) or cell.value == "N/D" or cell.formula is not None
            row_number = int("".join(ch for ch in address if ch.isdigit()))
            letters = "".join(ch for ch in address if ch.isalpha())
            ident = rows.get(row_number, (None,))[0]
            look = "key" if statement and ident and row_tier(name, ident, cell.style) == "key" else cell.style
            number_format = excel_visible_format(cell.fmt) if statement else cell.fmt
            share = statement and ident is not None and letters != "B" and (ord(letters[-1]) - ord("C")) % 2 == 1
            header_label = statement and address in {"B5", "B6"}
            style = fmt(look, number_format, numeric, edge=share, share=share, left=header_label, wrap=address in unmerged) if statement else fmt(look, number_format, numeric)
            if cell.formula:
                ws.write_formula(address, cell.formula, style, cell.value)
            elif cell.fmt == "[$-416]mmm-yy" and isinstance(cell.value, str):
                ws.write_datetime(address, datetime.fromisoformat(cell.value), style)
            elif isinstance(cell.value, str):
                ws.write_string(address, labels.get(address, cell.value), style)
            else:
                ws.write(address, cell.value, style)
            if statement and ident is not None and letters != "B":
                column = sum((ord(ch) - 64) * 26 ** i for i, ch in enumerate(reversed(letters))) - 1
                values.append((row_number - 1, column, _value_kind(cell.fmt)))
        ws.freeze_panes(s.freeze)
        if name in {"Dados COSIF", "Dados IFData", "Mapa COSIF"}:
            ws.autofilter(0, 0, s.last_row - 1, s.last_col - 1)
            ws.set_row(0, 26)
        if name == "Validações":
            ws.conditional_format(1, 4, len(analysis.checks), 4, {"type": "text", "criteria": "containing", "value": "Divergência", "format": wb.add_format({"bg_color": "#FCE4D6", "font_color": "#9C0006", "bold": True})})
        if statement:
            light = [v for v in values if not _is_band(rows, v[0] + 1, name, s)]
            band = [v for v in values if _is_band(rows, v[0] + 1, name, s)]
            _value_rules(wb, ws, light)
            _value_rules(wb, ws, band, band=True)
            _statement_page_setup(ws, analysis, s, height_points)
            # With the menu's view available, the calculated sheet stays auditable behind it.
            if name == "Carteira 4.966" and portfolio is not None and portfolio.periods:
                ws.hide()
        else:
            ws.hide()
            ws.set_landscape()
            ws.fit_to_pages(1, 0)
    wb.close()
    return buffer.getvalue()


def _is_band(rows, row, name, sheet):
    ident = rows.get(row, (None,))[0]
    return bool(ident) and row_tier(name, ident, sheet.cells[f"B{row}"].style) == "key"


def _with_widths(sheet, widths):
    """Layout-only copy: the analysis keeps its own sheet definition."""
    from dataclasses import replace
    return replace(sheet, widths=widths)
