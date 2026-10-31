"""Shared, compact reading order for the committee page and the website."""
from __future__ import annotations

from html import escape
import math
import re
import unicodedata
from datetime import timedelta

from .financial_statement_style import (FONT_FAMILY, ACCENT as HEADER_BACKGROUND, GRID as LINE_COLOR,
                                        SECTION as SECTION_BACKGROUND, KEY_FILL, RULE, INK, MUTED, NEGATIVE,
                                        BAND, BAND_MUTED, BAND_NEGATIVE, MISSING,
                                        AMOUNT_PX, PERCENT_PX, PERIOD_MAX_PX, label_width, LABEL_MOBILE_PX)
from .prudential_analysis import Analysis, Cell, col_name


LABELS = {
    "liquid": "Ativos Líquidos", "restricted": "TVM Vinculados e Derivativos",
    "loans": "Empréstimos e Direitos Creditórios", "card": "Transações de Pagamento",
    "card_pdd": "(-) Provisão sobre Transações de Pagamento",
    "others": "Outros Créditos", "related": "A Receber de Sociedades Ligadas",
    "other_funding": "Empréstimos, Repasses e Demais Obrigações",
    "assets": "Ativo Total", "liabilities": "Passivo Exigível", "liab_equity": "Passivo + Patrimônio Líquido",
    "equity": "Patrimônio Líquido", "net": "Resultado Líquido (acum. no semestre)",
    "roe": "ROE (anualizado)", "basel": "Índice de Basileia",
}

# These controls remain in the detailed Balanço and validation sheets.
COMMITTEE_OMIT = {"liabilities", "liab_equity", "principal_capital", "tier1", "tier1_ratio", "capital", "rwa"}


# Lines that anchor the reading of each statement; every other row keeps its model style.
KEY_ROWS = {
    "Balanço": {"assets", "liabilities", "equity", "liab_equity", "net", "roe", "cet1", "basel"},
    "DRE": {"gross", "after_pdd", "operating", "net"},
    "Carteira 4.966": {"total", "gross", "pdd"},
}

# Accounting groups that open a new slide: (title, last row of the group).
PAGE_GROUPS = {
    "Balanço": (("Ativo", "assets"), ("Passivo e patrimônio", "liab_equity"), ("Resultado e capital", None)),
    "DRE": (("Intermediação financeira", "after_pdd"), ("Resultado operacional e líquido", None)),
    "Carteira 4.966": (("Composição e qualidade", "npl_ratio"), ("Carteira contábil e provisão", None)),
}

# Below this, a stored amount is floating-point residue, not a reported value.
ZERO_EPSILON = 1e-6
PERIODS_PER_PAGE = 4
DEFAULT_QUARTERS = 4
QUARTER_MONTHS = ("03", "06", "09", "12")


def row_tier(name: str, ident: str, style: str) -> str:
    return "key" if ident in KEY_ROWS.get(name, ()) else style


def period_chunks(periods, size: int = PERIODS_PER_PAGE):
    """Split a selection evenly, keeping every chunk within the page limit."""
    periods = list(periods)
    count = math.ceil(len(periods) / size) if periods else 0
    base, extra = divmod(len(periods), count) if count else (0, 0)
    chunks, start = [], 0
    for index in range(count):
        end = start + base + (index < extra)
        chunks.append(periods[start:end])
        start = end
    return chunks


def default_periods(available, today) -> list[str]:
    """Last four consecutive closed quarters with data, from the viewer's date.

    Monthly files stay selectable, but the default reads quarter over quarter. A
    closed quarter not yet published gives way to the latest one that is.
    """
    # A quarter closes on its last day: a month counts only once it has ended.
    tomorrow = today + timedelta(days=1)
    closed = f"{tomorrow.year}{tomorrow.month:02d}"
    quarters = sorted(p for p in available if p[4:] in QUARTER_MONTHS and p < closed)
    if not quarters:
        return sorted(available, reverse=True)[:DEFAULT_QUARTERS]
    year, month = int(quarters[-1][:4]), int(quarters[-1][4:])
    chain = []
    for _ in range(DEFAULT_QUARTERS):
        chain.append(f"{year}{month:02d}")
        month -= 3
        if month == 0:
            year, month = year - 1, 12
    return [p for p in chain if p in quarters]


def period_key_to_quarter(period: str) -> str | None:
    """Competência do menu Carteira 4.966 (trimestre/ano) para um fim de trimestre."""
    return f"{QUARTER_MONTHS.index(period[4:]) + 1}/{period[:4]}" if period[4:] in QUARTER_MONTHS else None


def with_band_gaps(rows):
    """Thin separators around the bands of a statement; None marks a separator."""
    spaced = []
    for row in rows:
        if row[-1] == "key" and spaced and spaced[-1] is not None:
            spaced.append(None)
        spaced.append(row)
        if row[-1] == "key" and row is not rows[-1]:
            spaced.append(None)
    return spaced


def committee_panel(analysis, name):
    """Committee rows of one statement: (ident, row, label, style, tier)."""
    sheet = analysis.sheets[name]
    return [(ident, row, label, sheet.cells[f"B{row}"].style, row_tier(name, ident, sheet.cells[f"B{row}"].style))
            for ident, row, label in display_rows(analysis, name, committee=True)]


def export_filename(analysis: Analysis) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", unicodedata.normalize("NFKD", institution_label(analysis.institution))
                  .encode("ascii", "ignore").decode()).strip("_").title()
    span = analysis.periods[0] if len(analysis.periods) == 1 else f"{analysis.periods[0]}_a_{analysis.periods[-1]}"
    return f"{slug}_Analise_Financeira_{span}"


def institution_label(name: str) -> str:
    return re.sub(r"\s*-\s*PRUDENCIAL\s*$", "", name, flags=re.I).strip()


def period_label(period: str) -> str:
    return f"{('jan','fev','mar','abr','mai','jun','jul','ago','set','out','nov','dez')[int(period[4:])-1]}/{period[2:4]}"


def display_rows(analysis: Analysis, name: str, *, committee: bool = False):
    sheet = analysis.sheets[name]
    for ident, row in analysis.rows[name].items():
        if row in sheet.hidden_rows or (committee and name == "Balanço" and ident in COMMITTEE_OMIT):
            continue
        label = sheet.cells[f"B{row}"].value
        if name == "Balanço":
            label = LABELS.get(ident, label)
        elif name == "DRE" and ident == "net":
            label = LABELS["net"]
        elif name == "DRE" and ident == "after_pdd":
            label = "Resultado Líquido da Intermediação"
        yield ident, row, label


def format_cell(cell: Cell | None) -> str:
    if cell is None or cell.value is None:
        return ""
    if cell.value == "N/D":
        return MISSING
    if not isinstance(cell.value, (int, float)) or not math.isfinite(cell.value):
        return str(cell.value)
    if "%" in (cell.fmt or ""):
        places = 2 if "0.00" in cell.fmt else 0
        value = cell.value * 100
        if round(value, places) == 0:
            value = 0
        return f"{value:.{places}f}%".replace(".", ",")
    if abs(cell.value) < ZERO_EPSILON:
        return "0"
    # Preserve small reported amounts without presenting a negative zero.
    if abs(cell.value) < .5:
        return "-<1" if cell.value < 0 else "<1"
    return f"{cell.value:,.0f}".replace(",", ".")


def value_tone(cell: Cell | None) -> str:
    """Visual class of a value: negative, zero and N/D never read the same."""
    value = None if cell is None else cell.value
    if value == "N/D":
        return "missing"
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        return ""
    if format_cell(cell) in {"0", "0%", "0,00%"}:
        return "zero"
    return "negative" if value < 0 else ""


def period_cells(sheet, row: int, index: int):
    """Amount and share of one period; an unavailable amount has no share to repeat."""
    amount = sheet.cells.get(f"{col_name(3 + 2 * index)}{row}")
    share = sheet.cells.get(f"{col_name(4 + 2 * index)}{row}")
    return amount, (None if amount is not None and amount.value == "N/D" else share)


def period_source(sheet, index: int) -> str:
    return str(sheet.cells[f"{col_name(3 + 2 * index)}5"].value).replace("COSIF ", "")


def render_statement_html(analysis: Analysis, name: str) -> str:
    sheet = analysis.sheets[name]
    count = len(analysis.periods)
    rows = list(display_rows(analysis, name))
    first_width = label_width(label for _, _, label in rows)
    block = AMOUNT_PX + PERCENT_PX
    parts = [f'''<style>
.tc-prudential {{ --label-width:{first_width}px; width:100%; max-width:calc(var(--label-width) + {count * PERIOD_MAX_PX}px); overflow:auto; max-height:76vh; margin:.1rem 0 .55rem; border:1px solid {LINE_COLOR}; border-radius:4px; background:#fff; }}
.tc-prudential:focus-visible {{ outline:2px solid {HEADER_BACKGROUND}; outline-offset:2px; }}
.tc-prudential table {{ width:100%; min-width:calc(var(--label-width) + {count * block}px); border-collapse:separate; border-spacing:0; table-layout:fixed; font:13.5px/1.25 {FONT_FAMILY}; color:{INK}; font-variant-numeric:tabular-nums lining-nums; }}
.tc-prudential th,.tc-prudential td {{ padding:4px 10px; border-bottom:1px solid {LINE_COLOR}; box-sizing:border-box; }}
.tc-prudential thead th {{ position:sticky; top:0; z-index:3; background:{HEADER_BACKGROUND}; color:#fff; text-align:right; height:42px; font-weight:600; border-bottom:0; vertical-align:middle; }}
.tc-prudential thead small {{ display:block; font-size:11px; line-height:1.2; margin-top:1px; font-weight:400; }}
.tc-prudential .label {{ position:sticky; left:0; z-index:2; background:#fff; text-align:left; font-weight:400; overflow-wrap:break-word; border-right:1px solid {LINE_COLOR}; }}
.tc-prudential thead .label {{ z-index:4; background:{HEADER_BACKGROUND}; font-weight:600; border-right:0; }}
.tc-prudential td {{ text-align:right; white-space:nowrap; }}
.tc-prudential .percent {{ color:{MUTED}; font-size:12px; padding-left:2px; border-right:1px solid {LINE_COLOR}; }}
.tc-prudential tr>:last-child {{ border-right:0; }}
.tc-prudential .indent .label {{ padding-left:22px; }}
.tc-prudential .detail .label {{ padding-left:34px; font-size:12.5px; font-style:italic; color:{MUTED}; }}
.tc-prudential .detail td {{ font-size:12.5px; font-style:italic; }}
.tc-prudential .ratio>* {{ font-style:italic; }}
.tc-prudential .bold>* {{ font-weight:600; }}
.tc-prudential .section>* {{ background:{SECTION_BACKGROUND}; font-weight:600; }}
.tc-prudential .total>* {{ background:{SECTION_BACKGROUND}; font-weight:700; border-top:1px solid {RULE}; }}
.tc-prudential .key>* {{ background:{BAND}; color:#fff; font-weight:700; font-style:normal; border-right-color:{BAND}; border-bottom-color:#fff; }}
.tc-prudential .key .percent {{ color:#fff; }}
.tc-prudential .key td.negative {{ color:{BAND_NEGATIVE}; }}
.tc-prudential .key td.zero,.tc-prudential .key td.missing {{ color:{BAND_MUTED}; }}
.tc-prudential td.negative {{ color:{NEGATIVE}; }}
.tc-prudential td.zero,.tc-prudential td.missing {{ color:#8E949B; font-weight:400; }}
.tc-prudential tbody tr:hover>* {{ background:#F6F7F8; }}
.tc-prudential tbody tr.key:hover>* {{ background:{BAND}; }}
.tc-prudential caption {{ position:absolute; width:1px; height:1px; overflow:hidden; clip-path:inset(50%); }}
@media(max-width:700px) {{ .tc-prudential {{ --label-width:{LABEL_MOBILE_PX}px; }} .tc-prudential table {{ font-size:13px; }} .tc-prudential th,.tc-prudential td {{ padding:4px 7px; }} .tc-prudential .indent .label {{ padding-left:14px; }} .tc-prudential .detail .label {{ padding-left:20px; }} }}
</style><div class="tc-prudential" role="region" tabindex="0" aria-label="{escape(name)}">
<table><caption>{escape(analysis.institution)} · {escape(name)} · R$ milhões</caption>
<colgroup><col style="width:var(--label-width)">''']
    parts += [f'<col><col style="width:{PERCENT_PX}px">' for _ in analysis.periods]
    parts.append('</colgroup><thead><tr><th class="label" scope="col">' + escape(name) + '<small>R$ milhões</small></th>')
    for i, period in enumerate(analysis.periods):
        parts.append(f'<th colspan="2" scope="colgroup">{period_label(period)}<small>{escape(period_source(sheet, i))}</small></th>')
    parts.append('</tr></thead><tbody>')
    for ident, row, label in rows:
        style = sheet.cells[f"B{row}"].style
        parts.append(f'<tr class="{row_tier(name, ident, style)}"><th class="label" scope="row">{escape(label)}</th>')
        for i, _ in enumerate(analysis.periods):
            amount, share = period_cells(sheet, row, i)
            for cell, kind in ((amount, "amount"), (share, "percent")):
                tone = value_tone(cell)
                classes = kind + (" " + tone if tone else "")
                parts.append(f'<td class="{classes}">{escape(format_cell(cell))}</td>')
        parts.append('</tr>')
    parts.append('</tbody></table></div>')
    scope = "tc-statement-" + {"Balanço": "balance", "DRE": "income", "Carteira 4.966": "portfolio"}[name]
    return ''.join(parts).replace(".tc-prudential", "." + scope).replace('class="tc-prudential"', 'class="tc-prudential ' + scope + '"')
