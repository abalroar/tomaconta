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

# Limites de sanidade para o cruzamento entre Relatório 2 e Relatório 16.
# A tolerância evita classificar como erro diferenças residuais de arredondamento
# quando PDD e carteira são praticamente iguais.
PDD_ATTENTION_RATIO = 0.55
PDD_UNRELIABLE_RELATIVE_TOLERANCE = 0.001
PDD_UNRELIABLE_ABSOLUTE_TOLERANCE = 1.0


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
    percent_decimals: int = 2
    help_text: str = ""


@dataclass(frozen=True)
class GroupSpec:
    key: str
    label: Optional[str]


@dataclass(frozen=True)
class MetricCell:
    primary: Optional[float]
    secondary: Optional[float] = None


@dataclass(frozen=True)
class QualityIssue:
    period: str
    severity: str
    code: str
    pdd_value: Optional[float]
    portfolio_value: Optional[float]
    ratio: Optional[float]


@dataclass
class Carteira4966Model:
    periods: tuple[str, ...]
    period_labels: Mapping[str, str]
    base_period: Optional[str]
    base_value: Optional[float]
    qoq: Mapping[str, Optional[float]]
    cells: Mapping[str, Mapping[str, MetricCell]]
    quality_issues: tuple[QualityIssue, ...] = ()

    @property
    def missing_provision_periods(self) -> tuple[str, ...]:
        provision = self.cells.get("provision", {})
        return tuple(
            period
            for period in self.periods
            if provision.get(period) is None or provision[period].primary is None
        )

    def pdd_quality_issue(self, period: str) -> Optional[QualityIssue]:
        issues = [issue for issue in self.quality_issues if issue.period == period]
        if not issues:
            return None
        return sorted(
            issues,
            key=lambda issue: 0 if issue.severity == "critical" else 1,
        )[0]


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
        percent_decimals=2,
        help_text=(
            "Inadimplência do Relatório 16: operações a vencer e vencidas que "
            "possuem alguma parcela vencida há mais de 90 dias."
        ),
    ),
    RowSpec(
        "provision",
        "PDD (Perda Esperada)",
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
        "PDD / Carteira Total (%)",
        "provision",
        "percent_span",
        "provision",
        "total_general",
        "Carteira total do mesmo período",
        percent_decimals=2,
        help_text="Provisão total dividida pela carteira total do mesmo período.",
    ),
    RowSpec(
        "provision_over_c5",
        "PDD / C5 (%)",
        "provision",
        "percent_span",
        "provision",
        "c5",
        "C5 do mesmo período",
        help_text="Provisão total dividida por C5 no mesmo período.",
    ),
    RowSpec(
        "provision_over_delinquency",
        "PDD / Créditos vencidos acima de 90 dias (%)",
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
        "Variável": "PDD (Perda Esperada)",
        "Definição": (
            "Magnitude da soma de Perda Esperada (e2), (f2), (g2) e (h2). "
            "Não inclui Hedge de Valor Justo nem Ajuste a Valor Justo."
        ),
        "Fonte": "BCB IFData, Relatório 2 Ativo, Conglomerado Prudencial",
    },
    {
        "Variável": "PDD / Carteira Total (%)",
        "Definição": (
            "PDD dividida pelo Total Geral do Relatório 16 no mesmo período. "
            "Razões acima de 55% recebem atenção. A PDD que superar a carteira além "
            "da tolerância equivalente ao maior entre R$ 1 e 0,1% da Carteira Total "
            "é sinalizada como não confiável."
        ),
        "Fonte": "Cruzamento BCB IFData, Relatórios 2 e 16",
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
    if num is None or den is None or den <= 0:
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
    values: list[float] = []
    for candidate in EXPECTED_LOSS_COLUMNS:
        column = _resolve_column(frame, (candidate,))
        if column is None:
            return None
        value = _numeric(row.get(column))
        if value is None:
            return None
        values.append(value)
    return abs(float(sum(values)))


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


def _build_pdd_quality_issues(
    metrics_by_period: Mapping[str, Mapping[str, Optional[float]]],
    periods: Sequence[str],
) -> tuple[QualityIssue, ...]:
    issues: list[QualityIssue] = []
    for period in periods:
        metrics = metrics_by_period.get(period, {})
        pdd_value = _numeric(metrics.get("provision"))
        portfolio_value = _numeric(metrics.get("total_general"))
        if pdd_value is None or portfolio_value is None:
            continue

        if portfolio_value < 0:
            issues.append(
                QualityIssue(
                    period=period,
                    severity="critical",
                    code="negative_portfolio",
                    pdd_value=pdd_value,
                    portfolio_value=portfolio_value,
                    ratio=None,
                )
            )
            continue

        if portfolio_value == 0:
            if pdd_value > 0:
                issues.append(
                    QualityIssue(
                        period=period,
                        severity="critical",
                        code="pdd_with_zero_portfolio",
                        pdd_value=pdd_value,
                        portfolio_value=portfolio_value,
                        ratio=None,
                    )
                )
            continue

        ratio = pdd_value / portfolio_value
        excess_tolerance = max(
            PDD_UNRELIABLE_ABSOLUTE_TOLERANCE,
            portfolio_value * PDD_UNRELIABLE_RELATIVE_TOLERANCE,
        )
        if pdd_value - portfolio_value > excess_tolerance:
            issues.append(
                QualityIssue(
                    period=period,
                    severity="critical",
                    code="pdd_exceeds_portfolio",
                    pdd_value=pdd_value,
                    portfolio_value=portfolio_value,
                    ratio=ratio,
                )
            )
        elif ratio > PDD_ATTENTION_RATIO:
            issues.append(
                QualityIssue(
                    period=period,
                    severity="warning",
                    code="high_pdd_ratio",
                    pdd_value=pdd_value,
                    portfolio_value=portfolio_value,
                    ratio=ratio,
                )
            )
    return tuple(issues)


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
        for candidate in EXPECTED_LOSS_COLUMNS
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

    valid_base_periods = []
    for period in ordered_periods:
        total_general = _numeric(metrics_by_period.get(period, {}).get("total_general"))
        if total_general is not None and total_general > 0:
            valid_base_periods.append(period)
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
        quality_issues=_build_pdd_quality_issues(metrics_by_period, ordered_periods),
    )


def _format_number_ptbr(value: float, decimals: int = 0) -> str:
    rendered = f"{value:,.{decimals}f}"
    return rendered.replace(",", "X").replace(".", ",").replace("X", ".")


def format_brl_millions(value: Optional[float]) -> str:
    number = _numeric(value)
    return "N/D" if number is None else _format_number_ptbr(number / 1_000_000, 0)


def _format_brl_millions_for_alert(value: Optional[float]) -> str:
    number = _numeric(value)
    if number is None:
        return "N/D"
    millions = number / 1_000_000
    magnitude = abs(millions)
    if magnitude >= 100:
        decimals = 0
    elif magnitude >= 10:
        decimals = 1
    elif magnitude >= 1:
        decimals = 2
    else:
        decimals = 3
    return _format_number_ptbr(millions, decimals)


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


def _excel_percentage_format_code(decimals: int = 2) -> str:
    decimals = max(0, int(decimals))
    return "0%" if decimals == 0 else f"0.{('0' * decimals)}%"


def quality_issue_message(issue: QualityIssue) -> str:
    period_label = format_period_label(issue.period)
    pdd_label = _format_brl_millions_for_alert(issue.pdd_value)
    portfolio_label = _format_brl_millions_for_alert(issue.portfolio_value)
    if issue.code == "pdd_exceeds_portfolio":
        return (
            f"{period_label}: PDD de R$ {pdd_label} mi equivale a "
            f"{format_percentage(issue.ratio, 1)} da Carteira Total de R$ {portfolio_label} mi. "
            "Como a PDD supera a carteira, o cruzamento foi sinalizado como não confiável."
        )
    if issue.code == "pdd_with_zero_portfolio":
        return (
            f"{period_label}: há PDD de R$ {pdd_label} mi, mas a Carteira Total está zerada. "
            "A razão não pode ser calculada e o cruzamento foi sinalizado como não confiável."
        )
    if issue.code == "negative_portfolio":
        return (
            f"{period_label}: a Carteira Total é negativa (R$ {portfolio_label} mi). "
            "O denominador deve ser validado no Relatório 16 antes do uso."
        )
    return (
        f"{period_label}: PDD de R$ {pdd_label} mi equivale a "
        f"{format_percentage(issue.ratio, 1)} da Carteira Total de R$ {portfolio_label} mi. "
        f"A razão ultrapassa o limiar de atenção de {format_percentage(PDD_ATTENTION_RATIO, 0)}."
    )


def quality_issues_dataframe(model: Carteira4966Model) -> pd.DataFrame:
    columns = [
        "Período",
        "Severidade",
        "Checagem",
        "PDD (R$ mm)",
        "Carteira Total (R$ mm)",
        "PDD / Carteira Total (%)",
        "Diagnóstico",
    ]
    rows = []
    for issue in model.quality_issues:
        rows.append(
            {
                "Período": model.period_labels.get(issue.period, format_period_label(issue.period)),
                "Severidade": "Não confiável" if issue.severity == "critical" else "Atenção",
                "Checagem": issue.code,
                "PDD (R$ mm)": (
                    None if issue.pdd_value is None else issue.pdd_value / 1_000_000
                ),
                "Carteira Total (R$ mm)": (
                    None
                    if issue.portfolio_value is None
                    else issue.portfolio_value / 1_000_000
                ),
                "PDD / Carteira Total (%)": (
                    None if issue.ratio is None else issue.ratio * 100
                ),
                "Diagnóstico": quality_issue_message(issue),
            }
        )
    return pd.DataFrame(rows, columns=columns)


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
.tc-4966-table .tc-4966-quality-warning {
  color: #654c00;
  background: #fff4cc;
  font-weight: 700;
}
.tc-4966-table .tc-4966-quality-critical {
  color: #9f231b;
  background: #fde8e7;
  font-weight: 750;
}
.tc-4966-quality-badge { margin-left: 4px; font-style: normal; }
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
                    quality_issue = (
                        model.pdd_quality_issue(period)
                        if spec.key == "provision_over_portfolio"
                        else None
                    )
                    quality_class = (
                        f" tc-4966-quality-{quality_issue.severity}"
                        if quality_issue is not None
                        else ""
                    )
                    quality_badge = (
                        '<span class="tc-4966-quality-badge" '
                        'aria-label="Alerta de confiabilidade">⚠</span>'
                        if quality_issue is not None
                        else ""
                    )
                    cell_title = (
                        quality_issue_message(quality_issue)
                        if quality_issue is not None
                        else _cell_title(spec, cell)
                    )
                    parts.append(
                        f'<td class="tc-4966-period-end{missing}{quality_class}" colspan="2" '
                        f'title="{html.escape(cell_title, quote=True)}">'
                        f'{html.escape(rendered)}{quality_badge}</td>'
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


def build_carteira_4966_raw_excel(
    model: Carteira4966Model,
    carteira_source: Optional[pd.DataFrame] = None,
    ativo_source: Optional[pd.DataFrame] = None,
) -> bytes:
    """Exporta dados auditáveis com percentuais Excel em escala decimal.

    A tabela de auditoria do Streamlit usa pontos percentuais para facilitar a
    leitura. No arquivo, esses campos voltam à escala decimal e recebem formato
    percentual nativo. Assim, 3,91% é gravado como ``0,0391`` com ``0.00%``.
    """

    output = BytesIO()
    audit = model_to_audit_dataframe(model).copy()
    quality = quality_issues_dataframe(model).copy()

    audit_percent_columns = [
        column for column in audit.columns if str(column).endswith(" (%)")
    ]
    for column in audit_percent_columns:
        audit[column] = pd.to_numeric(audit[column], errors="coerce") / 100.0

    quality_percent_columns = [
        column for column in quality.columns if str(column).endswith(" (%)")
    ]
    for column in quality_percent_columns:
        quality[column] = pd.to_numeric(quality[column], errors="coerce") / 100.0

    carteira_export = (
        carteira_source.copy()
        if isinstance(carteira_source, pd.DataFrame)
        else pd.DataFrame()
    )
    ativo_export = (
        ativo_source.copy()
        if isinstance(ativo_source, pd.DataFrame)
        else pd.DataFrame()
    )
    if ativo_export.empty:
        ativo_export = pd.DataFrame(
            {
                "Status": [
                    "Dados de provisão indisponíveis para a instituição e os períodos selecionados."
                ]
            }
        )

    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        if not quality.empty:
            quality.to_excel(writer, index=False, sheet_name="Alertas qualidade")
        audit.to_excel(writer, index=False, sheet_name="Modelo calculado")
        carteira_export.to_excel(writer, index=False, sheet_name="Rel16 Carteira")
        ativo_export.to_excel(writer, index=False, sheet_name="Rel2 Ativo")

        workbook = writer.book
        header_format = workbook.add_format(
            {
                "bold": True,
                "font_color": "#FFFFFF",
                "bg_color": "#24262D",
                "border": 1,
                "border_color": "#C9CBD0",
                "valign": "vcenter",
                "text_wrap": True,
            }
        )
        percent_format = workbook.add_format(
            {"num_format": _excel_percentage_format_code(2), "align": "right"}
        )
        number_format = workbook.add_format(
            {"num_format": "#,##0.00", "align": "right"}
        )

        def style_sheet(
            sheet_name: str,
            frame: pd.DataFrame,
            *,
            percent_columns: Sequence[str] = (),
        ) -> None:
            worksheet = writer.sheets[sheet_name]
            for column_index, column_name in enumerate(frame.columns):
                worksheet.write(0, column_index, column_name, header_format)
                content_lengths = [
                    len(str(value))
                    for value in frame[column_name].dropna().head(100)
                ]
                width = min(
                    max([len(str(column_name)), *content_lengths], default=12) + 2,
                    60,
                )
                width = max(width, 14)
                if column_name in percent_columns:
                    worksheet.set_column(column_index, column_index, max(width, 18))
                    for row_index, value in enumerate(frame[column_name], start=1):
                        number = _finite_number(value)
                        if number is None:
                            worksheet.write_blank(
                                row_index,
                                column_index,
                                None,
                                percent_format,
                            )
                        else:
                            worksheet.write_number(
                                row_index,
                                column_index,
                                number,
                                percent_format,
                            )
                elif str(column_name).endswith("(R$ mm)"):
                    worksheet.set_column(
                        column_index,
                        column_index,
                        max(width, 18),
                        number_format,
                    )
                else:
                    worksheet.set_column(column_index, column_index, width)
            worksheet.freeze_panes(1, 0)
            worksheet.set_row(0, 30)
            if len(frame.index) > 0 and len(frame.columns) > 0:
                worksheet.autofilter(
                    0,
                    0,
                    len(frame.index),
                    len(frame.columns) - 1,
                )
            worksheet.hide_gridlines(2)

        if not quality.empty:
            style_sheet(
                "Alertas qualidade",
                quality,
                percent_columns=quality_percent_columns,
            )
        style_sheet(
            "Modelo calculado",
            audit,
            percent_columns=audit_percent_columns,
        )
        style_sheet("Rel16 Carteira", carteira_export)
        style_sheet("Rel2 Ativo", ativo_export)

    output.seek(0)
    return output.getvalue()


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
    percent_decimals = sorted({spec.percent_decimals for spec in ROW_SPECS})
    percent_formats = {
        decimals: workbook.add_format(
            {
                "align": "right",
                "valign": "vcenter",
                "num_format": _excel_percentage_format_code(decimals),
                **border,
            }
        )
        for decimals in percent_decimals
    }
    percent_span_formats = {
        decimals: workbook.add_format(
            {
                **border,
                "align": "center",
                "valign": "vcenter",
                "num_format": _excel_percentage_format_code(decimals),
                "bottom": 3,
                "bottom_color": "#C9CBD0",
            }
        )
        for decimals in percent_decimals
    }
    missing_fmt = workbook.add_format(
        {
            "align": "center",
            "valign": "vcenter",
            "italic": True,
            "font_color": "#6D7077",
            **border,
        }
    )
    quality_warning_fmt = workbook.add_format(
        {
            **border,
            "bold": True,
            "font_color": "#654C00",
            "bg_color": "#FFF4CC",
            "align": "center",
            "valign": "vcenter",
            "num_format": _excel_percentage_format_code(
                ROW_BY_KEY["provision_over_portfolio"].percent_decimals
            ),
            "bottom": 3,
            "bottom_color": "#C9CBD0",
        }
    )
    quality_critical_fmt = workbook.add_format(
        {
            **border,
            "bold": True,
            "font_color": "#9F231B",
            "bg_color": "#FDE8E7",
            "align": "center",
            "valign": "vcenter",
            "num_format": _excel_percentage_format_code(
                ROW_BY_KEY["provision_over_portfolio"].percent_decimals
            ),
            "bottom": 3,
            "bottom_color": "#C9CBD0",
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
                            percent_formats[spec.percent_decimals],
                        )
                elif spec.layout == "currency_span":
                    value = "N/D" if cell.primary is None else cell.primary / 1_000_000
                    cell_format = missing_fmt if cell.primary is None else currency_bold_fmt
                    worksheet.merge_range(row_index, column, row_index, column + 1, value, cell_format)
                else:
                    value = "N/D" if cell.primary is None else cell.primary
                    quality_issue = (
                        model.pdd_quality_issue(period)
                        if spec.key == "provision_over_portfolio"
                        else None
                    )
                    if quality_issue is not None:
                        cell_format = (
                            quality_critical_fmt
                            if quality_issue.severity == "critical"
                            else quality_warning_fmt
                        )
                    else:
                        if cell.primary is None:
                            cell_format = missing_fmt
                        else:
                            cell_format = percent_span_formats[spec.percent_decimals]
                    worksheet.merge_range(row_index, column, row_index, column + 1, value, cell_format)
                    if quality_issue is not None:
                        worksheet.write_comment(
                            row_index,
                            column,
                            quality_issue_message(quality_issue),
                            {"author": "Toma Conta"},
                        )
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

    if model.quality_issues:
        alerts = workbook.add_worksheet("Alertas qualidade")
        alert_header = workbook.add_format(
            {
                "bold": True,
                "font_color": "#FFFFFF",
                "bg_color": "#9F231B",
                "align": "left",
                **border,
            }
        )
        alert_text = workbook.add_format({"text_wrap": True, "valign": "top", **border})
        alert_number = workbook.add_format(
            {"num_format": "#,##0.00", "valign": "top", **border}
        )
        alert_percent = workbook.add_format(
            {
                "num_format": _excel_percentage_format_code(
                    ROW_BY_KEY["provision_over_portfolio"].percent_decimals
                ),
                "valign": "top",
                **border,
            }
        )
        alert_headers = (
            "Período",
            "Severidade",
            "Checagem",
            "PDD (R$ mm)",
            "Carteira Total (R$ mm)",
            "PDD / Carteira Total (%)",
            "Diagnóstico",
        )
        for column, header in enumerate(alert_headers):
            alerts.write(0, column, header, alert_header)
        for row, issue in enumerate(model.quality_issues, start=1):
            alerts.write(row, 0, model.period_labels.get(issue.period, issue.period), alert_text)
            alerts.write(
                row,
                1,
                "Não confiável" if issue.severity == "critical" else "Atenção",
                alert_text,
            )
            alerts.write(row, 2, issue.code, alert_text)
            if issue.pdd_value is None:
                alerts.write_blank(row, 3, None, alert_number)
            else:
                alerts.write_number(row, 3, issue.pdd_value / 1_000_000, alert_number)
            if issue.portfolio_value is None:
                alerts.write_blank(row, 4, None, alert_number)
            else:
                alerts.write_number(
                    row,
                    4,
                    issue.portfolio_value / 1_000_000,
                    alert_number,
                )
            if issue.ratio is None:
                alerts.write(row, 5, "N/D", alert_text)
            else:
                alerts.write_number(row, 5, issue.ratio, alert_percent)
            alerts.write(row, 6, quality_issue_message(issue), alert_text)
        alerts.set_column(0, 0, 12)
        alerts.set_column(1, 2, 18)
        alerts.set_column(3, 5, 23)
        alerts.set_column(6, 6, 90)
        alerts.set_default_row(42)
        alerts.freeze_panes(1, 0)
        alerts.autofilter(0, 0, len(model.quality_issues), len(alert_headers) - 1)
        alerts.hide_gridlines(2)

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
