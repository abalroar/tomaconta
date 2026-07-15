"""Gate de qualidade pré-publicação para o Relatório 16 (Carteira 4.966).

O gate é deliberadamente independente de Streamlit e do pipeline de extração.
Ele recebe o DataFrame que será publicado e devolve um dicionário serializável,
adequado para o manifesto de release e para uso em testes/rotinas operacionais.
"""

from __future__ import annotations

import math
import re
from typing import Any, Iterable

import pandas as pd


CARTEIRA_4966_REQUIRED_PERIODS = (
    "202503",
    "202506",
    "202509",
    "202512",
    "202603",
)
CARTEIRA_4966_IDENTITY_COLUMNS = ("CodInst", "Período")
CARTEIRA_4966_CLASSIFICATION_COLUMNS = (
    "Instituição",
    "C1",
    "C2",
    "C3",
    "C4",
    "C5",
    "Carteira não Informada ou não se Aplica",
    "Total Exterior",
    "Total não Individualizado",
)
CARTEIRA_4966_TOTAL_COLUMN = "Total Geral"
CARTEIRA_4966_METRIC_COLUMNS = (
    "Inadimplência",
    "Ativos problemáticos",
)
CARTEIRA_4966_REQUIRED_COLUMNS = (
    *CARTEIRA_4966_IDENTITY_COLUMNS,
    *CARTEIRA_4966_CLASSIFICATION_COLUMNS,
    CARTEIRA_4966_TOTAL_COLUMN,
    *CARTEIRA_4966_METRIC_COLUMNS,
)
CARTEIRA_4966_NUMERIC_COLUMNS = (
    *CARTEIRA_4966_CLASSIFICATION_COLUMNS[1:],
    CARTEIRA_4966_TOTAL_COLUMN,
    *CARTEIRA_4966_METRIC_COLUMNS,
)
CARTEIRA_4966_MINIMUM_COVERAGE = 0.90
CARTEIRA_4966_MINIMUM_REPORTING_POPULATION_COVERAGE = 0.75
CARTEIRA_4966_MINIMUM_TOTAL_COVERAGE = 0.90
CARTEIRA_4966_MINIMUM_CLASSIFICATION_COVERAGE = 0.50


def _normalize_period(value: object) -> str:
    """Converte representações trimestrais usuais para ``YYYYMM``."""

    if value is None or pd.isna(value):
        return ""
    if isinstance(value, pd.Timestamp):
        return f"{value.year:04d}{value.month:02d}"

    if isinstance(value, (int, float)):
        try:
            numeric_value = float(value)
            if math.isfinite(numeric_value) and numeric_value.is_integer():
                value = str(int(numeric_value))
        except (TypeError, ValueError):
            pass

    text = str(value).strip()
    if not text:
        return ""

    quarter_match = re.fullmatch(r"([1-4])\s*/\s*(\d{4})", text)
    if quarter_match:
        quarter, year = int(quarter_match.group(1)), int(quarter_match.group(2))
        return f"{year:04d}{quarter * 3:02d}"

    year_quarter_match = re.fullmatch(
        r"(?:Q([1-4])\s*[/\-]?\s*(\d{4})|(\d{4})\s*Q([1-4]))",
        text,
        flags=re.IGNORECASE,
    )
    if year_quarter_match:
        if year_quarter_match.group(1):
            quarter, year = int(year_quarter_match.group(1)), int(year_quarter_match.group(2))
        else:
            year, quarter = int(year_quarter_match.group(3)), int(year_quarter_match.group(4))
        return f"{year:04d}{quarter * 3:02d}"

    compact = re.fullmatch(r"(\d{4})[-/]?(\d{2})(?:[-/]?\d{2})?", text)
    if compact:
        year, month = int(compact.group(1)), int(compact.group(2))
        if month in {3, 6, 9, 12}:
            return f"{year:04d}{month:02d}"
    return ""


def _normalize_codinst(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    if not text:
        return ""
    try:
        number = float(text)
        if math.isfinite(number) and number.is_integer():
            return str(int(number))
    except (TypeError, ValueError):
        pass
    return text


def _published_mask(series: pd.Series) -> pd.Series:
    return series.notna() & series.astype(str).str.strip().ne("")


def _finite_numeric(series: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Retorna valores numéricos, máscara finita e máscara publicada inválida."""

    numeric = pd.to_numeric(series, errors="coerce")
    finite = numeric.notna() & numeric.map(
        lambda value: bool(math.isfinite(float(value))) if pd.notna(value) else False
    )
    invalid_published = _published_mask(series) & ~finite
    return numeric, finite, invalid_published


def _coverage(valid_count: int, eligible_count: int) -> float:
    return float(valid_count / eligible_count) if eligible_count else 0.0


def _period_label(period: str) -> str:
    return str(period)


def validate_carteira_4966_quality(
    frame: pd.DataFrame | None,
    *,
    required_periods: Iterable[str] = CARTEIRA_4966_REQUIRED_PERIODS,
    minimum_coverage: float = CARTEIRA_4966_MINIMUM_COVERAGE,
    minimum_reporting_population_coverage: float = CARTEIRA_4966_MINIMUM_REPORTING_POPULATION_COVERAGE,
    minimum_total_coverage: float = CARTEIRA_4966_MINIMUM_TOTAL_COVERAGE,
    minimum_classification_coverage: float = CARTEIRA_4966_MINIMUM_CLASSIFICATION_COVERAGE,
) -> dict[str, Any]:
    """Valida cobertura, identidade e sanidade estrutural do asset 4.966.

    A população reportante (linhas com ao menos um valor numérico) é comparada
    ao cadastro do período; dentro dela, ``Total Geral`` deve ter cobertura
    mínima. Os componentes da carteira, ``Inadimplência`` e ``Ativos
    problemáticos`` são medidos nas linhas com ``Total Geral`` positivo. Esses
    universos preservam instituições legitimamente sem carteira, mas impedem a
    publicação de um período ou componente materialmente incompleto. Valores
    publicados não numéricos nunca são aceitos.
    """

    expected_periods = tuple(dict.fromkeys(str(period) for period in required_periods))
    threshold = float(minimum_coverage)
    reporting_population_threshold = float(minimum_reporting_population_coverage)
    total_threshold = float(minimum_total_coverage)
    classification_threshold = float(minimum_classification_coverage)
    failures: list[str] = []
    warnings: list[str] = []

    for parameter_name, parameter_value in (
        ("minimum_coverage", threshold),
        ("minimum_reporting_population_coverage", reporting_population_threshold),
        ("minimum_total_coverage", total_threshold),
        ("minimum_classification_coverage", classification_threshold),
    ):
        if not 0.0 <= parameter_value <= 1.0:
            raise ValueError(f"{parameter_name} deve estar entre 0 e 1")

    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return {
            "success": False,
            "message": "cache local indisponível ou vazio",
            "record_count": 0,
            "target_record_count": 0,
            "minimum_coverage": threshold,
            "minimum_reporting_population_coverage": reporting_population_threshold,
            "minimum_total_coverage": total_threshold,
            "minimum_classification_coverage": classification_threshold,
            "required_periods": list(expected_periods),
            "present_periods": [],
            "missing_periods": list(expected_periods),
            "missing_columns": list(CARTEIRA_4966_REQUIRED_COLUMNS),
            "duplicate_identity_count": 0,
            "structural_anomaly_count": 0,
            "coverage_by_period": {},
            "warnings": [],
        }

    missing_columns = sorted(set(CARTEIRA_4966_REQUIRED_COLUMNS) - set(frame.columns))
    if missing_columns:
        failures.append(f"colunas ausentes: {', '.join(missing_columns)}")
        return {
            "success": False,
            "message": "; ".join(failures),
            "record_count": int(len(frame)),
            "target_record_count": 0,
            "minimum_coverage": threshold,
            "minimum_reporting_population_coverage": reporting_population_threshold,
            "minimum_total_coverage": total_threshold,
            "minimum_classification_coverage": classification_threshold,
            "required_periods": list(expected_periods),
            "present_periods": [],
            "missing_periods": list(expected_periods),
            "missing_columns": missing_columns,
            "duplicate_identity_count": 0,
            "structural_anomaly_count": 0,
            "coverage_by_period": {},
            "warnings": [],
        }

    working = frame.copy()
    working["_quality_period"] = working["Período"].map(_normalize_period)
    working["_quality_codinst"] = working["CodInst"].map(_normalize_codinst)

    period_published = _published_mask(working["Período"])
    invalid_period_count = int((period_published & working["_quality_period"].eq("")).sum())
    missing_identity_count = int(
        (
            working["_quality_codinst"].eq("")
            | ~period_published
            | ~_published_mask(working["Instituição"])
        ).sum()
    )
    duplicate_identity_count = int(
        working.loc[
            working["_quality_codinst"].ne("") & working["_quality_period"].ne("")
        ].duplicated(subset=["_quality_codinst", "_quality_period"]).sum()
    )

    if missing_identity_count:
        failures.append(
            f"{missing_identity_count} linha(s) sem CodInst/Instituição/Período"
        )
    if invalid_period_count:
        failures.append(f"{invalid_period_count} período(s) em formato inválido")
    if duplicate_identity_count:
        failures.append(
            f"{duplicate_identity_count} chave(s) CodInst/Período duplicada(s)"
        )

    present_periods = sorted(
        set(working["_quality_period"]) & set(expected_periods)
    )
    missing_periods = [period for period in expected_periods if period not in present_periods]
    if missing_periods:
        failures.append(
            "períodos obrigatórios ausentes: " + ", ".join(missing_periods)
        )

    target = working[working["_quality_period"].isin(expected_periods)].copy()
    numeric: dict[str, pd.Series] = {}
    finite: dict[str, pd.Series] = {}
    invalid_numeric_count: dict[str, int] = {}
    for column in CARTEIRA_4966_NUMERIC_COLUMNS:
        values, valid_mask, invalid_published = _finite_numeric(target[column])
        numeric[column] = values
        finite[column] = valid_mask
        invalid_numeric_count[column] = int(invalid_published.sum())
        if invalid_numeric_count[column]:
            failures.append(
                f"{column}: {invalid_numeric_count[column]} valor(es) publicado(s) não numérico(s)"
            )

    negative_total_count = int(
        (finite[CARTEIRA_4966_TOTAL_COLUMN] & numeric[CARTEIRA_4966_TOTAL_COLUMN].lt(0)).sum()
    )
    if negative_total_count:
        warnings.append(f"Total Geral: {negative_total_count} valor(es) negativo(s)")

    negative_metric_count: dict[str, int] = {}
    exceeds_total_count: dict[str, int] = {}
    total_values = numeric[CARTEIRA_4966_TOTAL_COLUMN]
    total_valid = finite[CARTEIRA_4966_TOTAL_COLUMN]
    for column in CARTEIRA_4966_METRIC_COLUMNS:
        metric_values = numeric[column]
        metric_valid = finite[column]
        negative_metric_count[column] = int((metric_valid & metric_values.lt(0)).sum())
        comparable = metric_valid & total_valid & total_values.ge(0)
        tolerance = total_values.abs().mul(1e-9).clip(lower=1.0)
        exceeds_total_count[column] = int(
            (comparable & metric_values.gt(total_values + tolerance)).sum()
        )
        if negative_metric_count[column]:
            warnings.append(
                f"{column}: {negative_metric_count[column]} valor(es) negativo(s)"
            )
        if exceeds_total_count[column]:
            warnings.append(
                f"{column}: {exceeds_total_count[column]} valor(es) acima do Total Geral"
            )

    coverage_by_period: dict[str, dict[str, Any]] = {}
    classification_columns = CARTEIRA_4966_CLASSIFICATION_COLUMNS[1:]
    coverage_columns = (
        CARTEIRA_4966_TOTAL_COLUMN,
        *classification_columns,
        *CARTEIRA_4966_METRIC_COLUMNS,
    )
    overall_valid_counts = {column: 0 for column in coverage_columns}
    overall_denominators = {column: 0 for column in overall_valid_counts}
    reporting_population = pd.Series(False, index=target.index, dtype=bool)
    for column in CARTEIRA_4966_NUMERIC_COLUMNS:
        reporting_population |= finite[column]
    total_eligible = finite[CARTEIRA_4966_TOTAL_COLUMN] & numeric[
        CARTEIRA_4966_TOTAL_COLUMN
    ].gt(0)
    overall_reporting_count = 0
    overall_period_rows = 0

    for period in expected_periods:
        period_mask = target["_quality_period"].eq(period)
        period_rows = int(period_mask.sum())
        total_valid_count = int((period_mask & total_valid).sum())
        reporting_count = int((period_mask & reporting_population).sum())
        eligible_count = int((period_mask & total_eligible).sum())
        reporting_population_coverage = _coverage(reporting_count, period_rows)
        period_details: dict[str, Any] = {
            "record_count": period_rows,
            "reporting_count": reporting_count,
            "reporting_population_coverage": reporting_population_coverage,
            "numeric_total_count": total_valid_count,
            "eligible_total_count": eligible_count,
            "valid_counts": {
                CARTEIRA_4966_TOTAL_COLUMN: total_valid_count,
            },
            "coverage": {},
        }

        total_coverage = _coverage(total_valid_count, reporting_count)
        period_details["coverage"][CARTEIRA_4966_TOTAL_COLUMN] = total_coverage
        overall_valid_counts[CARTEIRA_4966_TOTAL_COLUMN] += total_valid_count
        overall_denominators[CARTEIRA_4966_TOTAL_COLUMN] += reporting_count
        overall_reporting_count += reporting_count
        overall_period_rows += period_rows
        if period_rows and reporting_population_coverage < reporting_population_threshold:
            failures.append(
                f"{_period_label(period)} população reportante: cobertura "
                f"{reporting_population_coverage:.1%}; mínimo "
                f"{reporting_population_threshold:.0%}"
            )
        if period_rows and not eligible_count:
            failures.append(
                f"{_period_label(period)}: nenhuma linha com Total Geral numérico e positivo"
            )
        if reporting_count and total_coverage < total_threshold:
            failures.append(
                f"{_period_label(period)} {CARTEIRA_4966_TOTAL_COLUMN}: cobertura "
                f"{total_coverage:.1%}; mínimo {total_threshold:.0%}"
            )

        for column in classification_columns:
            valid_count = int((period_mask & total_eligible & finite[column]).sum())
            column_coverage = _coverage(valid_count, eligible_count)
            period_details["valid_counts"][column] = valid_count
            period_details["coverage"][column] = column_coverage
            overall_valid_counts[column] += valid_count
            overall_denominators[column] += eligible_count
            if eligible_count and column_coverage < classification_threshold:
                failures.append(
                    f"{_period_label(period)} {column}: cobertura "
                    f"{column_coverage:.1%}; mínimo {classification_threshold:.0%}"
                )

        for column in CARTEIRA_4966_METRIC_COLUMNS:
            valid_count = int((period_mask & total_eligible & finite[column]).sum())
            column_coverage = _coverage(valid_count, eligible_count)
            period_details["valid_counts"][column] = valid_count
            period_details["coverage"][column] = column_coverage
            overall_valid_counts[column] += valid_count
            overall_denominators[column] += eligible_count
            if eligible_count and column_coverage < threshold:
                failures.append(
                    f"{_period_label(period)} {column}: cobertura "
                    f"{column_coverage:.1%}; mínimo {threshold:.0%}"
                )

        coverage_by_period[period] = period_details

    coverage = {
        column: _coverage(overall_valid_counts[column], overall_denominators[column])
        for column in overall_valid_counts
    }
    reporting_population_coverage = _coverage(
        overall_reporting_count, overall_period_rows
    )
    if overall_period_rows and reporting_population_coverage < reporting_population_threshold:
        failures.append(
            "população reportante: cobertura agregada "
            f"{reporting_population_coverage:.1%}; mínimo "
            f"{reporting_population_threshold:.0%}"
        )
    aggregate_thresholds = {
        CARTEIRA_4966_TOTAL_COLUMN: total_threshold,
        **{column: classification_threshold for column in classification_columns},
        **{column: threshold for column in CARTEIRA_4966_METRIC_COLUMNS},
    }
    for column, column_threshold in aggregate_thresholds.items():
        value = coverage[column]
        if overall_denominators[column] and value < column_threshold:
            failures.append(
                f"{column}: cobertura agregada {value:.1%}; mínimo {column_threshold:.0%}"
            )

    structural_anomaly_count = int(
        missing_identity_count
        + invalid_period_count
        + duplicate_identity_count
        + sum(invalid_numeric_count.values())
    )
    warning_anomaly_count = int(
        negative_total_count
        + sum(negative_metric_count.values())
        + sum(exceeds_total_count.values())
    )

    # Mantém a mensagem determinística e sem repetições quando uma falha de
    # cobertura aparece tanto no período quanto no agregado.
    failures = list(dict.fromkeys(failures))
    return {
        "success": not failures,
        "message": "; ".join(failures) if failures else "ok",
        "record_count": int(len(frame)),
        "target_record_count": int(len(target)),
        "minimum_coverage": threshold,
        "minimum_reporting_population_coverage": reporting_population_threshold,
        "minimum_total_coverage": total_threshold,
        "minimum_classification_coverage": classification_threshold,
        "required_periods": list(expected_periods),
        "present_periods": present_periods,
        "missing_periods": missing_periods,
        "missing_columns": missing_columns,
        "duplicate_identity_count": duplicate_identity_count,
        "missing_identity_count": missing_identity_count,
        "invalid_period_count": invalid_period_count,
        "invalid_numeric_count": invalid_numeric_count,
        "negative_total_count": negative_total_count,
        "negative_metric_count": negative_metric_count,
        "exceeds_total_count": exceeds_total_count,
        "structural_anomaly_count": structural_anomaly_count,
        "warning_anomaly_count": warning_anomaly_count,
        "warnings": list(dict.fromkeys(warnings)),
        "reporting_population_coverage": reporting_population_coverage,
        "coverage": coverage,
        "coverage_by_period": coverage_by_period,
    }
