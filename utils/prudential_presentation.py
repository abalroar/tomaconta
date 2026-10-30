"""Shared, compact reading order for the committee page and the website."""
from __future__ import annotations

from html import escape
import math
import re

from .comparison_table_style import FONT_FAMILY, HEADER_BACKGROUND, LINE_COLOR, SECTION_BACKGROUND
from .prudential_analysis import Analysis, Cell, col_name


LABELS = {
    "liquid": "Ativos Líquidos", "restricted": "TVM Vinculados e Derivativos",
    "loans": "Empréstimos e Direitos Creditórios", "card": "Transações de Pagamento",
    "card_pdd": "(-) Provisão sobre Transações de Pagamento",
    "others": "Outros Créditos", "related": "A Receber de Sociedades Ligadas",
    "other_funding": "Empréstimos, Repasses e Demais Obrigações",
    "equity": "Patrimônio Líquido", "net": "Resultado Líquido (acum. no semestre)",
    "roe": "ROE (anualizado)", "basel": "Índice de Basileia",
}

# These controls remain in the detailed Balanço and validation sheets.
COMMITTEE_OMIT = {"liabilities", "liab_equity", "principal_capital", "tier1", "tier1_ratio", "capital", "rwa"}


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
        yield ident, row, label


def format_cell(cell: Cell | None) -> str:
    if cell is None or cell.value is None:
        return ""
    if not isinstance(cell.value, (int, float)) or not math.isfinite(cell.value):
        return str(cell.value)
    if "%" in (cell.fmt or ""):
        places = 2 if "0.00" in cell.fmt else 0
        value = cell.value * 100
        if round(value, places) == 0:
            value = 0
        return f"{value:.{places}f}%".replace(".", ",")
    # Preserve small reported amounts without presenting a negative zero.
    if 0 < abs(cell.value) < .5:
        return "−<1" if cell.value < 0 else "<1"
    return f"{cell.value:,.0f}".replace(",", ".")


def render_statement_html(analysis: Analysis, name: str) -> str:
    sheet = analysis.sheets[name]
    period_width = 165 * len(analysis.periods)
    parts = [f'''<style>
.tc-prudential {{ --label-width:360px; width:100%; overflow:auto; max-height:74vh; margin:.2rem 0 1rem; border:1px solid {LINE_COLOR}; background:#fff; }}
.tc-prudential:focus-visible {{ outline:2px solid #1f77b4; outline-offset:2px; }}
.tc-prudential table {{ width:100%; min-width:calc(var(--label-width) + {period_width}px); border-collapse:separate; border-spacing:0; table-layout:fixed; font:14px/1.3 {FONT_FAMILY}; color:#222; font-variant-numeric:tabular-nums; }}
.tc-prudential th,.tc-prudential td {{ padding:7px 12px; border-bottom:1px solid #ededed; box-sizing:border-box; }}
.tc-prudential thead th {{ position:sticky; top:0; z-index:3; background:{HEADER_BACKGROUND}; color:white; text-align:center; height:56px; font-weight:600; }}
.tc-prudential thead small {{ display:block; font-size:11px; margin-top:3px; font-weight:400; opacity:.92; }}
.tc-prudential .label {{ position:sticky; left:0; z-index:2; background:#fff; text-align:left; font-weight:400; }}
.tc-prudential thead .label {{ z-index:4; background:{HEADER_BACKGROUND}; font-weight:600; }}
.tc-prudential td {{ text-align:right; white-space:nowrap; }}
.tc-prudential .percent {{ color:#73777e; font-size:12px; border-right:1px solid {LINE_COLOR}; }}
.tc-prudential .indent .label {{ padding-left:28px; }}
.tc-prudential .detail .label {{ padding-left:40px; font-size:13px; font-style:italic; }}
.tc-prudential .bold>* {{ font-weight:600; }}
.tc-prudential .section>* {{ background:{SECTION_BACKGROUND}; font-weight:600; }}
.tc-prudential .total>* {{ background:#f4f5f6; font-weight:700; border-top:1px solid #c9cdd1; border-bottom:1px solid #c9cdd1; }}
.tc-prudential .negative {{ color:#b32624; }}
.tc-prudential .missing {{ color:#90949a; font-size:12px; }}
.tc-prudential tbody tr:hover>* {{ background:#f6f8fa; }}
.tc-prudential caption {{ position:absolute; width:1px; height:1px; overflow:hidden; clip-path:inset(50%); }}
@media(max-width:700px) {{ .tc-prudential {{ --label-width:210px; }} .tc-prudential table {{ font-size:13px; }} .tc-prudential th,.tc-prudential td {{ padding:7px 9px; }} }}
</style><div class="tc-prudential" role="region" tabindex="0" aria-label="{escape(name)}">
<table><caption>{escape(analysis.institution)} · {escape(name)} · R$ milhões</caption>
<colgroup><col style="width:var(--label-width)">''']
    parts += ['<col style="width:105px"><col style="width:60px">' for _ in analysis.periods]
    parts.append('</colgroup><thead><tr><th class="label" scope="col">' + escape(name) + '<small>R$ milhões</small></th>')
    for i, period in enumerate(analysis.periods):
        source = str(sheet.cells[f"{col_name(3+2*i)}5"].value).replace("COSIF ", "")
        parts.append(f'<th colspan="2" scope="colgroup">{period_label(period)}<small>{escape(source)}</small></th>')
    parts.append('</tr></thead><tbody>')
    for ident, row, label in display_rows(analysis, name):
        style = sheet.cells[f"B{row}"].style
        parts.append(f'<tr class="{style}"><th class="label" scope="row">{escape(label)}</th>')
        for i, _ in enumerate(analysis.periods):
            for j in range(2):
                cell = sheet.cells.get(f"{col_name(3+2*i+j)}{row}")
                value = None if cell is None else cell.value
                cls = "percent" if j else "amount"
                if isinstance(value, (int, float)) and value < 0: cls += " negative"
                if value == "N/D": cls += " missing"
                parts.append(f'<td class="{cls}">{escape(format_cell(cell))}</td>')
        parts.append('</tr>')
    parts.append('</tbody></table></div>')
    return ''.join(parts)
