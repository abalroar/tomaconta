"""Modelo de apresentacao da classificacao de carteira da Resolucao 4.966.

O modulo e intencionalmente independente de Streamlit. A mesma especificacao
de linhas alimenta HTML, auditoria e Excel, evitando diferencas de formula,
ordem ou unidade entre os tres artefatos.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import html
import math
import re
import unicodedata
from typing import Mapping, Optional, Sequence

import pandas as pd


TITLE = "Classificação da Carteira de Crédito Modelo 4966"

CLASSIFICATION_COLUMNS = ("C1", "C2", "C3", "C4", "C5")

# A solicitacao e literal: somente as colunas chamadas Perda Esperada na
# tabela Ativo. Hedge de Valor Justo e Ajuste a Valor Justo nao integram esta
# metrica, embora outra metrica canonica do produto os inclua.
EXPECTED_LOSS_COLUMNS = (
    "Perda Esperada (e2)",
    "Perda Esperada (f2)",
    "Perda Esperada (g2)",
    "Perda Esperada (h2)",
)


@dataclass(frozen=True)
class RowSpec:
    key: str
    label: str
    group: str
    layout: str
    value_key: str
    denominator_key: Optional[str] = None
    denominator_label: str = ""
    emphasis: bool = False
    percent_decimals: int = 0
    help_text: str = ""


@dataclass(frozen=True)
class GroupSpec:
    key: str
    label: Optional[str]


@dataclass(frozen=True)
class MetricCell:
    primary: Optional[float]
    secondary: Optional[float] = None


@dataclass
class Carteira4966Model:
    periods: tuple[str, ...]
    period_labels: Mapping[str, str]
    base_period: Optional[str]
    base_value: Optional[float]
    qoq: Mapping[str, Optional[float]]
    cells: Mapping[str, Mapping[str, MetricCell]]

    @property
    def missing_provision_periods(self) -> tuple[str, ...]:
        provision = self.cells.get("provision", {})
        return tuple(
            period
            for period in self.periods
            if provision.get(period) is None or provision[period].primary is None
        )


GROUP_SPECS = (
    GroupSpec("classification", "Em R$mm"),
    GroupSpec("delinquency", "Carteira por dias em atraso em R$mm"),
    GroupSpec("provision", None),
)

ROW_SPECS = (
    RowSpec(
        "total_portfolio",
        "Carteira total",
        "classification",
        "paired",
        "total_general",
        "base_total",
        "Carteira total do período-base",
        emphasis=True,
        help_text=(
            "Total Geral do Relatório 16. O percentual usa uma base comum para permitir "
            "a leitura empilhada da composição e do crescimento da carteira."
        ),
    ),
    *(
        RowSpec(
            column.lower(),
            column,
            "classification",
            "paired",
            column.lower(),
            "base_total",
            "Carteira total do período-base",
            help_text=f"{column} do Relatório 16 dividido pela base comum da carteira total.",
        )
        for column in CLASSIFICATION_COLUMNS
    ),
    RowSpec(
        "total_not_individualized",
        "Total não individualizado",
        "classification",
        "paired",
        "total_not_individualized",
        "base_total",
        "Carteira total do período-base",
        help_text="Total não individualizado do Relatório 16.",
    ),
    RowSpec(
        "not_informed",
        "Carteira não informada ou não se aplica",
        "classification",
        "paired",
        "not_informed",
        "base_total",
        "Carteira total do período-base",
        help_text="Carteira não informada ou não aplicável no Relatório 16.",
    ),
    RowSpec(
        "delinquency",
        "Vencidos acima de 90 dias (conceito de arrasto)",
        "delinquency",
        "paired",
        "delinquency",
        "total_general",
        "Carteira total do mesmo período",
        emphasis=True,
        percent_decimals=1,
        help_text=(
            "Inadimplência do Relatório 16: operações a vencer e vencidas que "
            "possuem alguma parcela vencida há mais de 90 dias."
        ),
    ),
    RowSpec(
        "provision",
        "Provisão do banco",
        "provision",
        "currency_span",
        "provision",
        emphasis=True,
        help_text=(
            "Magnitude da soma das colunas Perda Esperada e2, f2, g2 e h2 "
            "da tabela Ativo, visão Conglomerado Prudencial."
        ),
    ),
    RowSpec(
        "provision_over_portfolio",
        "Provisão total / Carteira",
        "provision",
        "percent_span",
        "provision",
        "total_general",
        "Carteira total do mesmo período",
        help_text="Provisão total dividida pela carteira total do mesmo período.",
    ),
    RowSpec(
        "provision_over_c5",
        "Provisão total / C5",
        "provision",
        "percent_span",
        "provision",
        "c5",
        "C5 do mesmo período",
        help_text="Provisão total dividida por C5 no mesmo período.",
    ),
    RowSpec(
        "provision_over_delinquency",
        "Provisão total / Créditos vencidos acima de 90 dias",
        "provision",
        "percent_span",
        "provision",
        "delinquency",
        "Vencidos acima de 90 dias do mesmo período",
        help_text="Provisão total dividida pelos vencidos acima de 90 dias no mesmo período.",
    ),
)

ROW_BY_KEY = {spec.key: spec for spec in ROW_SPECS}

GLOSSARY_ROWS = (
    {
        "Variável": "Carteira total",
        "Definição": (
            "Total Geral do Relatório 16: C1 a C5, carteira não informada, "
            "Total Exterior e total não individualizado."
        ),
        "Fonte": "BCB IFData, Relatório 16, Conglomerado Prudencial",
    },
    {
        "Variável": "% da base comum",
        "Definição": (
            "Valor dividido pela carteira total do último quarto trimestre exibido; "
            "na ausência de quarto trimestre, usa o período exibido mais recente."
        ),
        "Fonte": "Cálculo do modelo 4966",
    },
    {
        "Variável": "Vencidos acima de 90 dias (conceito de arrasto)",
        "Definição": (
            "Operações a vencer e vencidas que possuem alguma parcela vencida há mais de 90 dias. "
            "O percentual usa a carteira total do mesmo período."
        ),
        "Fonte": "BCB IFData, Relatório 16, coluna Inadimplência",
    },
    {
        "Variável": "Provisão do banco",
        "Definição": (
            "Magnitude da soma de Perda Esperada (e2), (f2), (g2) e (h2). "
            "Não inclui Hedge de Valor Justo nem Ajuste a Valor Justo."
        ),
        "Fonte": "BCB IFData, Relatório 2 Ativo, Conglomerado Prudencial",
    },
    {
        "Variável": "Total Geral do Relatório 16",
        "Definição": (
            "Reconcilia C1 a C5, carteira não informada, Total Exterior e total não individualizado. "
            "Total Exterior não é mostrado nesta visão por seguir o escopo solicitado."
        ),
        "Fonte": "BCB IFData, Relatório 16",
    },
)


def _normalize_label(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _resolve_column(frame: Optional[pd.DataFrame], candidates: Sequence[str]) -> Optional[str]:
    if frame is None:
        return None
    normalized = {_normalize_label(column): str(column) for column in frame.columns}
    for candidate in candidates:
        resolved = normalized.get(_normalize_label(candidate))
        if resolved:
            return resolved
    return None


def _finite_number(value: object) -> Optional[float]:
    if value is None:
        return None
    try:
        number = float(pd.to_numeric(value, errors="coerce"))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _numeric(value: object) -> Optional[float]:
    number = _finite_number(value)
    if number is None:
        return None
    return 0.0 if abs(number) < 0.005 else number


def _sum_available(values: Sequence[object]) -> Optional[float]:
    numbers = [number for value in values if (number := _numeric(value)) is not None]
    return float(sum(numbers)) if numbers else None


def _safe_ratio(numerator: object, denominator: object) -> Optional[float]:
    num = _numeric(numerator)
    den = _numeric(denominator)
    if num is None or den is None or den == 0:
        return None
    ratio = num / den
    return ratio if math.isfinite(ratio) else None


def _period_sort_key(period: str) -> tuple[int, int, str]:
    match = re.fullmatch(r"\s*(\d{1,2})\s*/\s*(\d{4})\s*", str(period or ""))
    if not match:
        return (0, 0, str(period))
    quarter, year = int(match.group(1)), int(match.group(2))
    return (year, quarter, str(period))


def format_period_label(period: str) -> str:
    match = re.fullmatch(r"\s*(\d{1,2})\s*/\s*(\d{4})\s*", str(period or ""))
    if not match:
        return str(period)
    quarter, year = int(match.group(1)), int(match.group(2))
    month = {1: "Mar", 2: "Jun", 3: "Set", 4: "Dez"}.get(quarter, f"T{quarter}")
    return f"{month}/{str(year)[-2:]}"


def _previous_period(period: str) -> Optional[str]:
    match = re.fullmatch(r"\s*(\d{1,2})\s*/\s*(\d{4})\s*", str(period or ""))
    if not match:
        return None
    quarter, year = int(match.group(1)), int(match.group(2))
    return f"{quarter - 1}/{year}" if quarter > 1 else f"4/{year - 1}"


def _best_row_for_period(
    frame: Optional[pd.DataFrame],
    period: str,
    relevant_columns: Sequence[str],
) -> Optional[pd.Series]:
    if frame is None or frame.empty:
        return None
    period_column = _resolve_column(frame, ("Período", "Periodo"))
    if not period_column:
        return None
    matches = frame[frame[period_column].astype(str).str.strip().eq(str(period).strip())].copy()
    if matches.empty:
        return None
    usable = [column for column in relevant_columns if column in matches.columns]
    if len(matches) > 1 and usable:
        scores = matches[usable].notna().sum(axis=1)
        matches = matches.assign(_completeness=scores).sort_values("_completeness", kind="stable")
    return matches.iloc[-1]


def _expected_loss_from_row(row: Optional[pd.Series], frame: Optional[pd.DataFrame]) -> Optional[float]:
    if row is None or frame is None:
        return None
    precomputed = _resolve_column(frame, ("Perda Esperada",))
    if precomputed:
        value = _numeric(row.get(precomputed))
        return abs(value) if value is not None else None
    resolved = [
        column
        for candidate in EXPECTED_LOSS_COLUMNS
        if (column := _resolve_column(frame, (candidate,))) is not None
    ]
    value = _sum_available([row.get(column) for column in resolved])
    return abs(value) if value is not None else None


def _metrics_for_row(row: Optional[pd.Series], frame: Optional[pd.DataFrame]) -> dict[str, Optional[float]]:
    def get(*candidates: str) -> Optional[float]:
        column = _resolve_column(frame, candidates)
        return _numeric(row.get(column)) if row is not None and column else None

    components = {key.lower(): get(key) for key in CLASSIFICATION_COLUMNS}
    classified = _sum_available(list(components.values()))
    return {
        **components,
        "classified": classified,
        "total_not_individualized": get("Total não Individualizado", "Total nao Individualizado"),
        "not_informed": get(
            "Carteira não Informada ou não se Aplica",
            "Carteira nao Informada ou nao se Aplica",
        ),
        "total_external": get("Total Exterior"),
        "total_general": get("Total Geral"),
        "delinquency": get("Inadimplência", "Inadimplencia"),
    }


def build_carteira_4966_model(
    carteira: pd.DataFrame,
    ativo: Optional[pd.DataFrame],
    periods: Sequence[str],
    *,
    base_period: Optional[str] = None,
) -> Carteira4966Model:
    """Constroi os valores brutos e ratios do modelo 4966.

    ``carteira`` e ``ativo`` devem estar previamente recortados para uma unica
    instituicao. Caso o matching com Ativo falhe, a carteira continua disponivel
    e as linhas de provisao permanecem N/D.
    """

    ordered_periods = tuple(sorted(dict.fromkeys(str(period) for period in periods), key=_period_sort_key))
    carteira_relevant = [
        column
        for candidates in (
            *[(column,) for column in CLASSIFICATION_COLUMNS],
            ("Total não Individualizado",),
            ("Carteira não Informada ou não se Aplica",),
            ("Total Exterior",),
            ("Total Geral",),
            ("Inadimplência",),
        )
        if (column := _resolve_column(carteira, candidates)) is not None
    ]
    ativo_relevant = [
        column
        for candidate in ("Perda Esperada", *EXPECTED_LOSS_COLUMNS)
        if (column := _resolve_column(ativo, (candidate,))) is not None
    ]

    all_carteira_periods = set(ordered_periods)
    period_column = _resolve_column(carteira, ("Período", "Periodo"))
    if period_column:
        all_carteira_periods.update(carteira[period_column].dropna().astype(str).tolist())

    metrics_by_period: dict[str, dict[str, Optional[float]]] = {}
    for period in sorted(all_carteira_periods, key=_period_sort_key):
        carteira_row = _best_row_for_period(carteira, period, carteira_relevant)
        metrics_by_period[period] = _metrics_for_row(carteira_row, carteira)

    provision_by_period: dict[str, Optional[float]] = {}
    for period in ordered_periods:
        ativo_row = _best_row_for_period(ativo, period, ativo_relevant)
        provision_by_period[period] = _expected_loss_from_row(ativo_row, ativo)
        metrics_by_period.setdefault(period, {})["provision"] = provision_by_period[period]

    valid_base_periods = [
        period
        for period in ordered_periods
        if _numeric(metrics_by_period.get(period, {}).get("total_general")) not in (None, 0)
    ]
    selected_base = None
    if base_period in valid_base_periods:
        selected_base = str(base_period)
    else:
        fourth_quarters = [period for period in valid_base_periods if _period_sort_key(period)[1] == 4]
        if fourth_quarters:
            selected_base = max(fourth_quarters, key=_period_sort_key)
        elif valid_base_periods:
            selected_base = max(valid_base_periods, key=_period_sort_key)
    base_value = (
        _numeric(metrics_by_period[selected_base].get("total_general"))
        if selected_base is not None
        else None
    )

    qoq: dict[str, Optional[float]] = {}
    for period in ordered_periods:
        current = metrics_by_period.get(period, {}).get("total_general")
        previous = metrics_by_period.get(_previous_period(period) or "", {}).get("total_general")
        qoq[period] = _safe_ratio(current, previous)
        if qoq[period] is not None:
            qoq[period] -= 1.0

    cells: dict[str, dict[str, MetricCell]] = {spec.key: {} for spec in ROW_SPECS}
    for spec in ROW_SPECS:
        for period in ordered_periods:
            metrics = metrics_by_period.get(period, {})
            value = _numeric(metrics.get(spec.value_key))
            if spec.layout == "paired":
                denominator = (
                    base_value
                    if spec.denominator_key == "base_total"
                    else metrics.get(spec.denominator_key or "")
                )
                cells[spec.key][period] = MetricCell(value, _safe_ratio(value, denominator))
            elif spec.layout == "currency_span":
                cells[spec.key][period] = MetricCell(value)
            elif spec.layout == "percent_span":
                cells[spec.key][period] = MetricCell(
                    _safe_ratio(value, metrics.get(spec.denominator_key or ""))
                )
            else:
                raise ValueError(f"Layout de linha não suportado: {spec.layout}")

    return Carteira4966Model(
        periods=ordered_periods,
        period_labels={period: format_period_label(period) for period in ordered_periods},
        base_period=selected_base,
        base_value=base_value,
        qoq=qoq,
        cells=cells,
    )


def _format_number_ptbr(value: float, decimals: int = 0) -> str:
    rendered = f"{value:,.{decimals}f}"
    return rendered.replace(",", "X").replace(".", ",").replace("X", ".")


def format_brl_millions(value: Optional[float]) -> str:
    number = _numeric(value)
    return "N/D" if number is None else _format_number_ptbr(number / 1_000_000, 0)


def format_percentage(value: Optional[float], decimals: int = 0) -> str:
    # Percentuais chegam como frações. Não aplique aqui o limiar monetário de
    # `_numeric`, pois 0,0049 representa 0,49%, e não um resíduo desprezível.
    number = _finite_number(value)
    if number is None:
        return "N/D"
    percentage = number * 100
    if round(percentage, decimals) == 0:
        percentage = 0.0
    return f"{_format_number_ptbr(percentage, decimals)}%"


def _cell_title(spec: RowSpec, cell: MetricCell, *, secondary: bool = False) -> str:
    if secondary or spec.layout == "percent_span":
        is_missing = (
            (spec.layout == "paired" and cell.secondary is None)
            or (spec.layout == "percent_span" and cell.primary is None)
        )
        if is_missing:
            return "Dado ou denominador indisponível"
        return spec.denominator_label
    if cell.primary is None:
        return "Dado indisponível na fonte"
    return f"Valor bruto: R$ {_format_number_ptbr(cell.primary, 2)}"


def render_carteira_4966_html(model: Carteira4966Model) -> str:
    """Renderiza tabela HTML acessivel, responsiva e isolada por namespace CSS."""

    min_width = max(700, 254 + len(model.periods) * 136)
    base_label = model.period_labels.get(model.base_period or "", "N/D")
    parts = [
        """
<style>
.tc-4966-region {
  --tc-ink: #24262d;
  --tc-ink-soft: #555961;
  --tc-line: #c9cbd0;
  --tc-line-strong: #72767e;
  --tc-surface: #ffffff;
  --tc-surface-soft: #f2f3f4;
  --tc-highlight: #e4c900;
  width: 100%;
  overflow-x: auto;
  margin: .75rem 0 1rem;
  border: 1px solid var(--tc-line);
  border-radius: 4px;
  background: var(--tc-surface);
  outline: none;
}
.tc-4966-region:focus-visible { box-shadow: 0 0 0 3px rgba(255, 90, 0, .28); }
.tc-4966-table {
  width: 100%;
  table-layout: fixed;
  border-collapse: separate;
  border-spacing: 0;
  color: var(--tc-ink);
  background: var(--tc-surface);
  font-size: 13px;
  font-variant-numeric: tabular-nums lining-nums;
}
.tc-4966-table caption {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
.tc-4966-table th, .tc-4966-table td {
  box-sizing: border-box;
  border-right: 1px solid var(--tc-line);
  border-bottom: 1px solid var(--tc-line);
  padding: 7px 5px;
  vertical-align: middle;
}
.tc-4966-table thead th {
  color: #f8f8f8;
  background: var(--tc-ink);
  text-align: center;
  font-weight: 650;
  white-space: nowrap;
}
.tc-4966-table thead .tc-4966-qoq { color: #d8d9dc; font-size: 11px; font-weight: 500; }
.tc-4966-table thead .tc-4966-subhead { background: #444850; color: #f5f5f5; font-size: 11px; }
.tc-4966-table .tc-4966-marker {
  position: sticky;
  left: 0;
  z-index: 3;
  width: 14px;
  min-width: 14px;
  padding: 0;
  border-right: 1px solid #a28f00;
  background-color: var(--tc-highlight);
  background-image: repeating-linear-gradient(135deg, rgba(116, 99, 0, .35) 0 2px, transparent 2px 6px);
}
.tc-4966-table thead .tc-4966-marker { z-index: 5; background-color: var(--tc-highlight); }
.tc-4966-table .tc-4966-label {
  position: sticky;
  left: 14px;
  z-index: 2;
  min-width: 220px;
  max-width: 260px;
  background: var(--tc-surface);
  text-align: left;
  font-weight: 500;
}
.tc-4966-table thead .tc-4966-label { z-index: 4; background: var(--tc-ink); }
.tc-4966-table td { min-width: 0; text-align: right; white-space: nowrap; }
.tc-4966-table .tc-4966-period-end { border-right: 2px solid var(--tc-line-strong); }
.tc-4966-table .tc-4966-section-label {
  background: var(--tc-surface-soft);
  color: var(--tc-ink-soft);
  text-align: left;
  font-size: 12px;
  font-weight: 650;
  letter-spacing: .01em;
}
.tc-4966-table tbody + tbody tr:first-child > :not(.tc-4966-marker) { border-top: 9px solid var(--tc-surface); }
.tc-4966-table .tc-4966-emphasis { font-weight: 700; }
.tc-4966-table .tc-4966-ratio-row .tc-4966-label { padding-left: 20px; color: var(--tc-ink-soft); }
.tc-4966-table .tc-4966-ratio-row td { border-bottom-style: dotted; }
.tc-4966-table .tc-4966-missing { color: #6d7077; font-style: italic; }
.tc-4966-table tr:last-child > * { border-bottom: 0; }
.tc-4966-table tr > *:last-child { border-right: 0; }
@media (max-width: 768px) {
  .tc-4966-table { font-size: 12px; }
  .tc-4966-table th, .tc-4966-table td { padding: 7px 8px; }
  .tc-4966-table .tc-4966-label { min-width: 220px; max-width: 260px; }
}
</style>
""",
        (
            f'<div class="tc-4966-region" role="region" tabindex="0" '
            f'aria-label="{html.escape(TITLE, quote=True)}">'
            f'<table class="tc-4966-table" style="min-width:{min_width}px">'
            f'<caption>{html.escape(TITLE)}. Valores em milhões de reais.</caption>'
            '<colgroup><col style="width:14px"><col style="width:240px">'
            + "".join('<col style="width:68px"><col style="width:68px">' for _ in model.periods)
            + "</colgroup><thead><tr>"
            '<th class="tc-4966-marker" rowspan="3" aria-hidden="true"></th>'
            '<th class="tc-4966-label" rowspan="3" scope="col">Indicador</th>'
        ),
    ]

    for period in model.periods:
        qoq_value = model.qoq.get(period)
        qoq_text = "QoQ: N/D" if qoq_value is None else f"QoQ: {format_percentage(qoq_value, 0)}"
        parts.append(
            f'<th class="tc-4966-qoq tc-4966-period-end" colspan="2" scope="colgroup">'
            f'{html.escape(qoq_text)}</th>'
        )
    parts.append("</tr><tr>")
    for period in model.periods:
        parts.append(
            f'<th class="tc-4966-period-end" colspan="2" scope="colgroup">'
            f'{html.escape(model.period_labels[period])}</th>'
        )
    parts.append("</tr><tr>")
    for _ in model.periods:
        parts.append('<th class="tc-4966-subhead" scope="col">R$ mm</th>')
        parts.append(
            f'<th class="tc-4966-subhead tc-4966-period-end" scope="col" '
            f'title="Base comum: {html.escape(base_label, quote=True)}">% base</th>'
        )
    parts.append("</tr></thead>")

    for group in GROUP_SPECS:
        parts.append(f'<tbody data-group="{html.escape(group.key, quote=True)}">')
        if group.label:
            section_id = f"tc-4966-group-{group.key}"
            parts.append(
                '<tr class="tc-4966-section">'
                '<td class="tc-4966-marker" aria-hidden="true"></td>'
                f'<th id="{section_id}" class="tc-4966-section-label" '
                f'colspan="{1 + len(model.periods) * 2}">{html.escape(group.label)}</th></tr>'
            )

        group_rows = [spec for spec in ROW_SPECS if spec.group == group.key]
        for spec in group_rows:
            row_classes = []
            if spec.emphasis:
                row_classes.append("tc-4966-emphasis-row")
            if spec.layout == "percent_span":
                row_classes.append("tc-4966-ratio-row")
            parts.append(f'<tr class="{" ".join(row_classes)}">')
            parts.append('<td class="tc-4966-marker" aria-hidden="true"></td>')
            label_classes = "tc-4966-label" + (" tc-4966-emphasis" if spec.emphasis else "")
            parts.append(
                f'<th class="{label_classes}" scope="row" '
                f'title="{html.escape(spec.help_text, quote=True)}">{html.escape(spec.label)}</th>'
            )
            for period in model.periods:
                cell = model.cells[spec.key][period]
                if spec.layout == "paired":
                    primary = format_brl_millions(cell.primary)
                    secondary = format_percentage(cell.secondary, spec.percent_decimals)
                    primary_class = " tc-4966-missing" if cell.primary is None else ""
                    secondary_class = " tc-4966-missing" if cell.secondary is None else ""
                    primary_title = html.escape(_cell_title(spec, cell), quote=True)
                    secondary_title = html.escape(
                        _cell_title(spec, cell, secondary=True),
                        quote=True,
                    )
                    parts.append(
                        f'<td class="{primary_class.strip()}" title="{primary_title}">'
                        f'{html.escape(primary)}</td>'
                    )
                    parts.append(
                        f'<td class="tc-4966-period-end{secondary_class}" '
                        f'title="{secondary_title}">'
                        f'{html.escape(secondary)}</td>'
                    )
                elif spec.layout == "currency_span":
                    rendered = format_brl_millions(cell.primary)
                    missing = " tc-4966-missing" if cell.primary is None else ""
                    parts.append(
                        f'<td class="tc-4966-period-end{missing}" colspan="2" '
                        f'title="{html.escape(_cell_title(spec, cell), quote=True)}">{html.escape(rendered)}</td>'
                    )
                else:
                    rendered = format_percentage(cell.primary, spec.percent_decimals)
                    missing = " tc-4966-missing" if cell.primary is None else ""
                    parts.append(
                        f'<td class="tc-4966-period-end{missing}" colspan="2" '
                        f'title="{html.escape(_cell_title(spec, cell), quote=True)}">{html.escape(rendered)}</td>'
                    )
            parts.append("</tr>")
        parts.append("</tbody>")

    parts.append("</table></div>")
    return "".join(parts)


def model_to_audit_dataframe(model: Carteira4966Model) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for spec in ROW_SPECS:
        if spec.layout == "paired":
            unit = "R$ milhões + %"
        elif spec.layout == "currency_span":
            unit = "R$ milhões"
        else:
            unit = "%"
        row: dict[str, object] = {
            "Indicador": spec.label,
            "Unidade": unit,
            "Denominador": spec.denominator_label or "Não se aplica",
        }
        for period in model.periods:
            label = model.period_labels[period]
            cell = model.cells[spec.key][period]
            if spec.layout == "paired":
                row[f"{label} (R$ mm)"] = None if cell.primary is None else cell.primary / 1_000_000
                row[f"{label} (%)"] = None if cell.secondary is None else cell.secondary * 100
            elif spec.layout == "currency_span":
                row[f"{label} (R$ mm)"] = None if cell.primary is None else cell.primary / 1_000_000
            else:
                row[f"{label} (%)"] = None if cell.primary is None else cell.primary * 100
        rows.append(row)
    return pd.DataFrame(rows)


def build_carteira_4966_excel(model: Carteira4966Model) -> bytes:
    """Gera o workbook visual usando a mesma ROW_SPECS da tela."""

    import xlsxwriter

    output = BytesIO()
    workbook = xlsxwriter.Workbook(output, {"in_memory": True})
    worksheet = workbook.add_worksheet("Modelo 4966")
    last_column = 1 + len(model.periods) * 2

    border = {"border": 1, "border_color": "#C9CBD0"}
    title_fmt = workbook.add_format(
        {"bold": True, "font_size": 15, "font_color": "#374151", "align": "left", "valign": "vcenter"}
    )
    header_fmt = workbook.add_format(
        {
            "bold": True,
            "font_color": "#FFFFFF",
            "bg_color": "#24262D",
            "align": "center",
            "valign": "vcenter",
            **border,
        }
    )
    qoq_fmt = workbook.add_format(
        {
            "font_color": "#D8D9DC",
            "bg_color": "#24262D",
            "align": "center",
            "valign": "vcenter",
            "font_size": 9,
            **border,
        }
    )
    subheader_fmt = workbook.add_format(
        {
            "bold": True,
            "font_color": "#FFFFFF",
            "bg_color": "#444850",
            "align": "center",
            "valign": "vcenter",
            "font_size": 9,
            **border,
        }
    )
    marker_fmt = workbook.add_format(
        {"pattern": 7, "fg_color": "#E4C900", "bg_color": "#9F8B00", "border": 1, "border_color": "#A28F00"}
    )
    section_fmt = workbook.add_format(
        {"bold": True, "font_color": "#555961", "bg_color": "#F2F3F4", "align": "left", "valign": "vcenter", **border}
    )
    label_fmt = workbook.add_format({"align": "left", "valign": "vcenter", **border})
    label_bold_fmt = workbook.add_format({"bold": True, "align": "left", "valign": "vcenter", **border})
    label_ratio_fmt = workbook.add_format(
        {
            **border,
            "align": "left",
            "valign": "vcenter",
            "indent": 1,
            "bottom": 3,
            "bottom_color": "#C9CBD0",
        }
    )
    currency_fmt = workbook.add_format({"align": "right", "valign": "vcenter", "num_format": "#,##0", **border})
    currency_bold_fmt = workbook.add_format(
        {
            "bold": True,
            "align": "right",
            "valign": "vcenter",
            "num_format": "#,##0",
            **border,
        }
    )
    percent_fmt = workbook.add_format({"align": "right", "valign": "vcenter", "num_format": "0%", **border})
    percent_one_fmt = workbook.add_format({"align": "right", "valign": "vcenter", "num_format": "0.0%", **border})
    percent_span_fmt = workbook.add_format(
        {
            **border,
            "align": "center",
            "valign": "vcenter",
            "num_format": "0%",
            "bottom": 3,
            "bottom_color": "#C9CBD0",
        }
    )
    missing_fmt = workbook.add_format(
        {
            "align": "center",
            "valign": "vcenter",
            "italic": True,
            "font_color": "#6D7077",
            **border,
        }
    )

    worksheet.merge_range(0, 1, 0, last_column, TITLE, title_fmt)
    worksheet.set_row(0, 24)
    worksheet.merge_range(1, 0, 3, 0, "", marker_fmt)
    worksheet.merge_range(1, 1, 3, 1, "Indicador", header_fmt)

    column = 2
    for period in model.periods:
        qoq_value = model.qoq.get(period)
        qoq_text = "QoQ: N/D" if qoq_value is None else f"QoQ: {format_percentage(qoq_value, 0)}"
        worksheet.merge_range(1, column, 1, column + 1, qoq_text, qoq_fmt)
        worksheet.merge_range(2, column, 2, column + 1, model.period_labels[period], header_fmt)
        worksheet.write(3, column, "R$ mm", subheader_fmt)
        worksheet.write(3, column + 1, "% base", subheader_fmt)
        column += 2

    row_index = 4
    for group_index, group in enumerate(GROUP_SPECS):
        if group_index > 0:
            worksheet.set_row(row_index, 6)
            worksheet.write_blank(row_index, 0, None, marker_fmt)
            row_index += 1
        if group.label:
            worksheet.write_blank(row_index, 0, None, marker_fmt)
            worksheet.merge_range(row_index, 1, row_index, last_column, group.label, section_fmt)
            row_index += 1

        for spec in (item for item in ROW_SPECS if item.group == group.key):
            worksheet.write_blank(row_index, 0, None, marker_fmt)
            if spec.layout == "percent_span":
                label_format = label_ratio_fmt
            elif spec.emphasis:
                label_format = label_bold_fmt
            else:
                label_format = label_fmt
            worksheet.write(row_index, 1, spec.label, label_format)
            if spec.help_text:
                worksheet.write_comment(row_index, 1, spec.help_text, {"author": "Toma Conta"})
            column = 2
            for period in model.periods:
                cell = model.cells[spec.key][period]
                if spec.layout == "paired":
                    if cell.primary is None:
                        worksheet.write(row_index, column, "N/D", missing_fmt)
                    else:
                        worksheet.write_number(
                            row_index,
                            column,
                            cell.primary / 1_000_000,
                            currency_bold_fmt if spec.emphasis else currency_fmt,
                        )
                    if cell.secondary is None:
                        worksheet.write(row_index, column + 1, "N/D", missing_fmt)
                    else:
                        worksheet.write_number(
                            row_index,
                            column + 1,
                            cell.secondary,
                            percent_one_fmt if spec.percent_decimals else percent_fmt,
                        )
                elif spec.layout == "currency_span":
                    value = "N/D" if cell.primary is None else cell.primary / 1_000_000
                    cell_format = missing_fmt if cell.primary is None else currency_bold_fmt
                    worksheet.merge_range(row_index, column, row_index, column + 1, value, cell_format)
                else:
                    value = "N/D" if cell.primary is None else cell.primary
                    cell_format = missing_fmt if cell.primary is None else percent_span_fmt
                    worksheet.merge_range(row_index, column, row_index, column + 1, value, cell_format)
                column += 2
            row_index += 1

    worksheet.set_column(0, 0, 2.5)
    worksheet.set_column(1, 1, 49)
    worksheet.set_column(2, last_column, 13)
    worksheet.freeze_panes(4, 2)
    worksheet.hide_gridlines(2)
    worksheet.set_landscape()
    worksheet.fit_to_pages(1, 1)
    worksheet.set_margins(0.25, 0.25, 0.5, 0.5)

    glossary = workbook.add_worksheet("Glossário")
    gloss_header = workbook.add_format(
        {"bold": True, "font_color": "#FFFFFF", "bg_color": "#24262D", "align": "left", **border}
    )
    gloss_text = workbook.add_format({"text_wrap": True, "valign": "top", **border})
    headers = ("Variável", "Definição", "Fonte")
    for column, header in enumerate(headers):
        glossary.write(0, column, header, gloss_header)
    for row, item in enumerate(GLOSSARY_ROWS, start=1):
        for column, header in enumerate(headers):
            glossary.write(row, column, item[header], gloss_text)
    glossary.set_column(0, 0, 40)
    glossary.set_column(1, 1, 95)
    glossary.set_column(2, 2, 55)
    glossary.set_default_row(38)
    glossary.freeze_panes(1, 0)
    glossary.hide_gridlines(2)

    workbook.close()
    output.seek(0)
    return output.getvalue()
