"""Contracts for the FIDC MC3 projection engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from math import isfinite
from typing import Any


def _require_finite(name: str, value: float) -> None:
    if not isfinite(float(value)):
        raise ValueError(f"{name} must be finite")


def _require_ratio(name: str, value: float, *, allow_one: bool = True) -> None:
    _require_finite(name, value)
    upper_ok = float(value) <= 1.0 if allow_one else float(value) < 1.0
    if float(value) < 0.0 or not upper_ok:
        boundary = "<= 1" if allow_one else "< 1"
        raise ValueError(f"{name} must be >= 0 and {boundary}")


@dataclass(frozen=True, slots=True)
class TrancheTerms:
    """Economic terms for one quota class.

    Non-residual tranches accrue CDI plus spread and are paid in seniority
    order. The residual tranche receives remaining cash/NAV after liabilities.
    """

    name: str
    share: float
    seniority: int
    annual_spread: float = 0.0
    amortization_start_month: int = 1
    residual: bool = False

    def __post_init__(self) -> None:
        if not str(self.name).strip():
            raise ValueError("tranche name cannot be blank")
        _require_ratio("tranche share", self.share)
        _require_ratio("annual_spread", self.annual_spread, allow_one=False)
        if int(self.seniority) < 1:
            raise ValueError("seniority must be >= 1")
        if int(self.amortization_start_month) < 1:
            raise ValueError("amortization_start_month must be >= 1")


@dataclass(frozen=True, slots=True)
class CreditAssumptions:
    """Receivables credit and collection behavior."""

    gross_yield_monthly: float
    default_rate_monthly: float
    recovery_rate: float
    recovery_lag_months: int

    def __post_init__(self) -> None:
        _require_ratio("gross_yield_monthly", self.gross_yield_monthly, allow_one=False)
        _require_ratio("default_rate_monthly", self.default_rate_monthly, allow_one=False)
        _require_ratio("recovery_rate", self.recovery_rate)
        if int(self.recovery_lag_months) < 0:
            raise ValueError("recovery_lag_months must be >= 0")


@dataclass(frozen=True, slots=True)
class ScenarioAssumptions:
    """Complete set of model inputs for a deterministic MC3 case."""

    case_id: str
    as_of_date: date
    portfolio_principal: float
    projection_months: int
    receivable_term_months: int
    revolving_months: int
    purchase_discount: float
    cdi_annual: float
    selic_annual: float
    servicing_fee_annual: float
    admin_fee_monthly: float
    cash_reserve_percent: float
    min_subordination: float
    credit: CreditAssumptions
    tranches: tuple[TrancheTerms, ...]
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not str(self.case_id).strip():
            raise ValueError("case_id cannot be blank")
        for name, value in [
            ("portfolio_principal", self.portfolio_principal),
            ("admin_fee_monthly", self.admin_fee_monthly),
        ]:
            _require_finite(name, value)
            if float(value) < 0.0:
                raise ValueError(f"{name} must be >= 0")
        for name, value in [
            ("purchase_discount", self.purchase_discount),
            ("cdi_annual", self.cdi_annual),
            ("selic_annual", self.selic_annual),
            ("servicing_fee_annual", self.servicing_fee_annual),
            ("cash_reserve_percent", self.cash_reserve_percent),
            ("min_subordination", self.min_subordination),
        ]:
            _require_ratio(name, value, allow_one=False if name != "min_subordination" else True)
        if int(self.projection_months) < 1:
            raise ValueError("projection_months must be >= 1")
        if int(self.receivable_term_months) < 1:
            raise ValueError("receivable_term_months must be >= 1")
        if int(self.revolving_months) < 0:
            raise ValueError("revolving_months must be >= 0")
        if not self.tranches:
            raise ValueError("at least one tranche is required")


@dataclass(frozen=True, slots=True)
class PeriodResult:
    """One monthly projection row with source-of-cash and use-of-cash fields."""

    month: int
    period_start: date
    period_end: date
    opening_portfolio: float
    acquisitions_principal: float
    scheduled_principal: float
    defaulted_principal: float
    principal_collections: float
    recoveries: float
    net_credit_loss: float
    interest_collections: float
    closing_portfolio: float
    opening_cash: float
    selic_income: float
    available_cash: float
    fees_due: float
    fees_paid: float
    tranche_interest_due: dict[str, float]
    tranche_interest_paid: dict[str, float]
    tranche_principal_paid: dict[str, float]
    reinvestment_purchase_price: float
    residual_distribution: float
    closing_tranche_balance: dict[str, float]
    ending_cash: float
    collateral_value: float
    residual_nav: float
    subordination_ratio: float
    waterfall_uses: float
    flags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProjectionResult:
    """Projection output plus summary metrics and tranche cash flows."""

    scenario: ScenarioAssumptions
    initial_purchase_price: float
    initial_cash_reserve: float
    initial_funding: float
    initial_tranche_balance: dict[str, float]
    periods: tuple[PeriodResult, ...]
    metrics: dict[str, Any] = field(default_factory=dict)
    tranche_cashflows: dict[str, tuple[float, ...]] = field(default_factory=dict)
