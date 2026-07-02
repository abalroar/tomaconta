"""Validation checks for MC3 assumptions and projection outputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .contracts import ProjectionResult, ScenarioAssumptions

Severity = Literal["error", "warning", "info"]
TOLERANCE = 1e-4


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    severity: Severity
    code: str
    message: str
    period: int | None = None


def validate_scenario(scenario: ScenarioAssumptions) -> tuple[ValidationIssue, ...]:
    issues: list[ValidationIssue] = []
    share_sum = sum(tranche.share for tranche in scenario.tranches)
    if abs(share_sum - 1.0) > TOLERANCE:
        issues.append(
            ValidationIssue(
                "error",
                "tranche_share_sum",
                f"Tranche shares must sum to 1.0; got {share_sum:.8f}.",
            )
        )

    names = [tranche.name for tranche in scenario.tranches]
    duplicate_names = sorted({name for name in names if names.count(name) > 1})
    if duplicate_names:
        issues.append(
            ValidationIssue(
                "error",
                "duplicate_tranche_names",
                f"Duplicate tranche names: {', '.join(duplicate_names)}.",
            )
        )

    residual = [tranche for tranche in scenario.tranches if tranche.residual]
    if len(residual) != 1:
        issues.append(
            ValidationIssue(
                "error",
                "residual_tranche_count",
                f"Exactly one residual tranche is required; got {len(residual)}.",
            )
        )
    elif residual[0].share + TOLERANCE < scenario.min_subordination:
        issues.append(
            ValidationIssue(
                "warning",
                "initial_subordination_below_minimum",
                (
                    f"Residual share {residual[0].share:.2%} is below the minimum "
                    f"subordination covenant {scenario.min_subordination:.2%}."
                ),
            )
        )

    if scenario.revolving_months > scenario.projection_months:
        issues.append(
            ValidationIssue(
                "error",
                "revolving_after_projection",
                "revolving_months cannot exceed projection_months.",
            )
        )

    min_projection = scenario.revolving_months + scenario.receivable_term_months
    if scenario.projection_months < min_projection:
        issues.append(
            ValidationIssue(
                "warning",
                "short_projection_horizon",
                (
                    "Projection horizon may end before all post-revolving receivables amortize: "
                    f"projection={scenario.projection_months}, minimum_check={min_projection}."
                ),
            )
        )

    for tranche in scenario.tranches:
        if tranche.amortization_start_month > scenario.projection_months and not tranche.residual:
            issues.append(
                ValidationIssue(
                    "warning",
                    "amortization_starts_after_projection",
                    f"{tranche.name} amortization starts after the projection horizon.",
                )
            )

    return tuple(issues)


def validate_projection(result: ProjectionResult) -> tuple[ValidationIssue, ...]:
    issues: list[ValidationIssue] = list(validate_scenario(result.scenario))
    metric_gap = float(result.metrics.get("principal_reconciliation_gap", 0.0))
    if abs(metric_gap) > TOLERANCE:
        issues.append(
            ValidationIssue(
                "error",
                "principal_reconciliation_gap",
                f"Acquired principal less scheduled principal less ending portfolio = {metric_gap:.6f}.",
            )
        )

    for period in result.periods:
        if period.ending_cash < -TOLERANCE:
            issues.append(
                ValidationIssue(
                    "error",
                    "negative_cash",
                    f"Ending cash is negative: {period.ending_cash:.6f}.",
                    period=period.month,
                )
            )
        if period.residual_nav < -TOLERANCE:
            issues.append(
                ValidationIssue(
                    "error",
                    "negative_residual_nav",
                    f"Residual NAV is negative: {period.residual_nav:.6f}.",
                    period=period.month,
                )
            )
        if period.waterfall_uses - period.available_cash > TOLERANCE:
            issues.append(
                ValidationIssue(
                    "error",
                    "waterfall_uses_exceed_sources",
                    (
                        f"Waterfall uses {period.waterfall_uses:.6f} exceed "
                        f"available cash {period.available_cash:.6f}."
                    ),
                    period=period.month,
                )
            )
        if (
            period.month <= result.scenario.revolving_months
            and period.subordination_ratio + TOLERANCE < result.scenario.min_subordination
        ):
            issues.append(
                ValidationIssue(
                    "warning",
                    "subordination_below_minimum",
                    (
                        f"Subordination {period.subordination_ratio:.2%} is below "
                        f"minimum {result.scenario.min_subordination:.2%}."
                    ),
                    period=period.month,
                )
            )
        for name, balance in period.closing_tranche_balance.items():
            if balance < -TOLERANCE:
                issues.append(
                    ValidationIssue(
                        "error",
                        "negative_tranche_balance",
                        f"{name} closing balance is negative: {balance:.6f}.",
                        period=period.month,
                    )
                )

    if result.periods:
        last = result.periods[-1]
        liability_balances = [
            balance
            for name, balance in last.closing_tranche_balance.items()
            if not any(tranche.name == name and tranche.residual for tranche in result.scenario.tranches)
        ]
        if any(balance > TOLERANCE for balance in liability_balances):
            issues.append(
                ValidationIssue(
                    "warning",
                    "liability_balance_after_projection",
                    "One or more liability tranches remain outstanding at final projection month.",
                    period=last.month,
                )
            )

    return tuple(issues)
