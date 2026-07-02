"""Monthly projection engine for a clean FIDC MC3 case."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from math import isclose
from typing import Any

from .contracts import PeriodResult, ProjectionResult, ScenarioAssumptions, TrancheTerms
from .rates import annual_to_monthly, annualize_monthly_return, cdi_plus_spread_monthly, periodic_irr

TOLERANCE = 1e-6


@dataclass(slots=True)
class _ReceivableCohort:
    principal: float
    outstanding: float
    start_month: int
    term_months: int

    def due_in_month(self, month: int) -> float:
        elapsed = month - self.start_month
        if elapsed < 0 or elapsed >= self.term_months or self.outstanding <= TOLERANCE:
            return 0.0
        level_principal = self.principal / self.term_months
        return min(level_principal, self.outstanding)


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, _month_end_day(year, month))
    return date(year, month, day)


def _month_end_day(year: int, month: int) -> int:
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    return (next_month - timedelta(days=1)).day


def _sorted_liabilities(tranches: tuple[TrancheTerms, ...]) -> list[TrancheTerms]:
    return sorted((item for item in tranches if not item.residual), key=lambda item: (item.seniority, item.name))


def _residual_tranche(tranches: tuple[TrancheTerms, ...]) -> TrancheTerms | None:
    residual = [item for item in tranches if item.residual]
    return residual[0] if residual else None


def build_projection(scenario: ScenarioAssumptions) -> ProjectionResult:
    """Build a deterministic monthly cash-flow projection.

    The engine keeps the economic mechanics explicit:
    fees -> tranche interest -> revolving reinvestment -> liability principal ->
    residual distribution. Reinvestment is constrained by available cash and
    target collateral balance; liability payments are constrained by cash.
    """

    initial_purchase_price = scenario.portfolio_principal * (1.0 - scenario.purchase_discount)
    initial_cash_reserve = scenario.portfolio_principal * scenario.cash_reserve_percent
    initial_funding = initial_purchase_price + initial_cash_reserve
    initial_tranche_balance = {
        tranche.name: initial_funding * tranche.share
        for tranche in scenario.tranches
    }

    liabilities = _sorted_liabilities(scenario.tranches)
    residual = _residual_tranche(scenario.tranches)
    liability_balances = {
        tranche.name: initial_tranche_balance[tranche.name]
        for tranche in liabilities
    }
    cashflows: dict[str, list[float]] = {
        tranche.name: [-initial_tranche_balance[tranche.name]]
        for tranche in scenario.tranches
    }

    cohorts = [
        _ReceivableCohort(
            principal=scenario.portfolio_principal,
            outstanding=scenario.portfolio_principal,
            start_month=1,
            term_months=scenario.receivable_term_months,
        )
    ]
    recovery_schedule: dict[int, float] = {}
    cash = initial_cash_reserve
    periods: list[PeriodResult] = []

    selic_monthly = annual_to_monthly(scenario.selic_annual)
    servicing_fee_monthly = annual_to_monthly(scenario.servicing_fee_annual)

    for month in range(1, scenario.projection_months + 1):
        period_start = _add_months(scenario.as_of_date, month - 1)
        period_end = _add_months(scenario.as_of_date, month)
        opening_portfolio = sum(cohort.outstanding for cohort in cohorts)

        scheduled_principal = 0.0
        defaulted_principal = 0.0
        principal_collections = 0.0
        interest_collections = 0.0
        for cohort in list(cohorts):
            due = cohort.due_in_month(month)
            if due <= TOLERANCE:
                continue
            defaulted = due * scenario.credit.default_rate_monthly
            collected = due - defaulted
            scheduled_principal += due
            defaulted_principal += defaulted
            principal_collections += collected
            interest_collections += cohort.outstanding * scenario.credit.gross_yield_monthly * (
                1.0 - scenario.credit.default_rate_monthly
            )
            cohort.outstanding = max(0.0, cohort.outstanding - due)

            recovery_month = month + scenario.credit.recovery_lag_months
            if recovery_month <= scenario.projection_months:
                recovery_schedule[recovery_month] = recovery_schedule.get(recovery_month, 0.0) + (
                    defaulted * scenario.credit.recovery_rate
                )

        cohorts = [cohort for cohort in cohorts if cohort.outstanding > TOLERANCE]
        recoveries = recovery_schedule.pop(month, 0.0)
        net_credit_loss = defaulted_principal * (1.0 - scenario.credit.recovery_rate)

        opening_cash = cash
        selic_income = opening_cash * selic_monthly
        available_cash = opening_cash + principal_collections + interest_collections + recoveries + selic_income

        fees_due = scenario.admin_fee_monthly + (opening_portfolio * servicing_fee_monthly)
        fees_paid = min(available_cash, fees_due)
        available_after_fees = available_cash - fees_paid

        tranche_interest_due: dict[str, float] = {}
        tranche_interest_paid: dict[str, float] = {}
        for tranche in liabilities:
            rate = cdi_plus_spread_monthly(scenario.cdi_annual, tranche.annual_spread)
            due_interest = liability_balances[tranche.name] * rate
            paid_interest = min(available_after_fees, due_interest)
            tranche_interest_due[tranche.name] = due_interest
            tranche_interest_paid[tranche.name] = paid_interest
            available_after_fees -= paid_interest
            unpaid_interest = due_interest - paid_interest
            if unpaid_interest > TOLERANCE:
                liability_balances[tranche.name] += unpaid_interest

        acquisitions_principal = 0.0
        reinvestment_purchase_price = 0.0
        if month <= scenario.revolving_months:
            target_portfolio = scenario.portfolio_principal
            portfolio_before_reinvestment = sum(cohort.outstanding for cohort in cohorts)
            replenishment_need = max(0.0, target_portfolio - portfolio_before_reinvestment)
            max_affordable_principal = available_after_fees / (1.0 - scenario.purchase_discount)
            acquisitions_principal = max(0.0, min(replenishment_need, max_affordable_principal))
            reinvestment_purchase_price = acquisitions_principal * (1.0 - scenario.purchase_discount)
            if acquisitions_principal > TOLERANCE:
                cohorts.append(
                    _ReceivableCohort(
                        principal=acquisitions_principal,
                        outstanding=acquisitions_principal,
                        start_month=month + 1,
                        term_months=scenario.receivable_term_months,
                    )
                )
            available_after_fees -= reinvestment_purchase_price

        tranche_principal_paid: dict[str, float] = {}
        if month > scenario.revolving_months:
            for tranche in liabilities:
                payment = 0.0
                if month >= tranche.amortization_start_month:
                    payment = min(available_after_fees, liability_balances[tranche.name])
                    liability_balances[tranche.name] -= payment
                    available_after_fees -= payment
                tranche_principal_paid[tranche.name] = payment
        else:
            tranche_principal_paid = {tranche.name: 0.0 for tranche in liabilities}

        residual_distribution = 0.0
        if residual is not None and all(balance <= TOLERANCE for balance in liability_balances.values()):
            residual_distribution = max(0.0, available_after_fees)
            available_after_fees -= residual_distribution

        ending_cash = max(0.0, available_after_fees)
        if isclose(ending_cash, 0.0, abs_tol=TOLERANCE):
            ending_cash = 0.0
        cash = ending_cash

        closing_portfolio = sum(cohort.outstanding for cohort in cohorts)
        collateral_value = closing_portfolio * (1.0 - scenario.purchase_discount) + ending_cash
        debt_balance = sum(max(0.0, value) for value in liability_balances.values())
        residual_nav = collateral_value - debt_balance
        subordination_ratio = residual_nav / collateral_value if collateral_value > TOLERANCE else 1.0

        for tranche in liabilities:
            cashflows[tranche.name].append(
                tranche_interest_paid.get(tranche.name, 0.0) + tranche_principal_paid.get(tranche.name, 0.0)
            )
        if residual is not None:
            cashflows[residual.name].append(residual_distribution)

        flags: list[str] = []
        if month <= scenario.revolving_months and subordination_ratio < scenario.min_subordination:
            flags.append("subordination_below_minimum")
        if fees_paid + TOLERANCE < fees_due:
            flags.append("fee_shortfall")
        for tranche in liabilities:
            if tranche_interest_paid.get(tranche.name, 0.0) + TOLERANCE < tranche_interest_due.get(tranche.name, 0.0):
                flags.append(f"interest_shortfall:{tranche.name}")

        closing_tranche_balance = dict(liability_balances)
        if residual is not None:
            closing_tranche_balance[residual.name] = residual_nav

        waterfall_uses = (
            fees_paid
            + sum(tranche_interest_paid.values())
            + sum(tranche_principal_paid.values())
            + reinvestment_purchase_price
            + residual_distribution
        )
        periods.append(
            PeriodResult(
                month=month,
                period_start=period_start,
                period_end=period_end,
                opening_portfolio=opening_portfolio,
                acquisitions_principal=acquisitions_principal,
                scheduled_principal=scheduled_principal,
                defaulted_principal=defaulted_principal,
                principal_collections=principal_collections,
                recoveries=recoveries,
                net_credit_loss=net_credit_loss,
                interest_collections=interest_collections,
                closing_portfolio=closing_portfolio,
                opening_cash=opening_cash,
                selic_income=selic_income,
                available_cash=available_cash,
                fees_due=fees_due,
                fees_paid=fees_paid,
                tranche_interest_due=tranche_interest_due,
                tranche_interest_paid=tranche_interest_paid,
                tranche_principal_paid=tranche_principal_paid,
                reinvestment_purchase_price=reinvestment_purchase_price,
                residual_distribution=residual_distribution,
                closing_tranche_balance=closing_tranche_balance,
                ending_cash=ending_cash,
                collateral_value=collateral_value,
                residual_nav=residual_nav,
                subordination_ratio=subordination_ratio,
                waterfall_uses=waterfall_uses,
                flags=tuple(flags),
            )
        )

    if residual is not None and periods:
        terminal_nav = max(0.0, periods[-1].residual_nav)
        if terminal_nav > TOLERANCE:
            cashflows[residual.name][-1] += terminal_nav

    metrics = _build_metrics(
        scenario=scenario,
        periods=periods,
        initial_funding=initial_funding,
        initial_tranche_balance=initial_tranche_balance,
        cashflows=cashflows,
    )
    return ProjectionResult(
        scenario=scenario,
        initial_purchase_price=initial_purchase_price,
        initial_cash_reserve=initial_cash_reserve,
        initial_funding=initial_funding,
        initial_tranche_balance=initial_tranche_balance,
        periods=tuple(periods),
        metrics=metrics,
        tranche_cashflows={name: tuple(values) for name, values in cashflows.items()},
    )


def _build_metrics(
    *,
    scenario: ScenarioAssumptions,
    periods: list[PeriodResult],
    initial_funding: float,
    initial_tranche_balance: dict[str, float],
    cashflows: dict[str, list[float]],
) -> dict[str, Any]:
    total_reinvestment = sum(period.acquisitions_principal for period in periods)
    total_acquired_principal = scenario.portfolio_principal + total_reinvestment
    total_scheduled_principal = sum(period.scheduled_principal for period in periods)
    ending_portfolio = periods[-1].closing_portfolio if periods else scenario.portfolio_principal
    principal_reconciliation_gap = total_acquired_principal - total_scheduled_principal - ending_portfolio

    liability_tranches = _sorted_liabilities(scenario.tranches)
    weighted_average_life_months: dict[str, float | None] = {}
    for tranche in liability_tranches:
        beginning_balance = initial_tranche_balance[tranche.name]
        weighted_principal = sum(
            period.month * period.tranche_principal_paid.get(tranche.name, 0.0)
            for period in periods
        )
        total_principal = sum(period.tranche_principal_paid.get(tranche.name, 0.0) for period in periods)
        weighted_average_life_months[tranche.name] = (
            weighted_principal / beginning_balance
            if beginning_balance > TOLERANCE and total_principal > TOLERANCE
            else None
        )

    tranche_irr_annual: dict[str, float | None] = {}
    for name, flows in cashflows.items():
        monthly_irr = periodic_irr(flows)
        tranche_irr_annual[name] = annualize_monthly_return(monthly_irr)

    min_subordination = min((period.subordination_ratio for period in periods), default=1.0)
    total_waterfall_sources = sum(period.available_cash for period in periods)
    total_waterfall_uses = sum(period.waterfall_uses + period.ending_cash for period in periods)

    return {
        "case_id": scenario.case_id,
        "initial_funding": initial_funding,
        "initial_purchase_price": scenario.portfolio_principal * (1.0 - scenario.purchase_discount),
        "initial_cash_reserve": scenario.portfolio_principal * scenario.cash_reserve_percent,
        "total_acquired_principal": total_acquired_principal,
        "total_reinvestment_principal": total_reinvestment,
        "total_scheduled_principal": total_scheduled_principal,
        "ending_portfolio": ending_portfolio,
        "principal_reconciliation_gap": principal_reconciliation_gap,
        "total_defaulted_principal": sum(period.defaulted_principal for period in periods),
        "total_recoveries": sum(period.recoveries for period in periods),
        "total_net_credit_loss": sum(period.net_credit_loss for period in periods),
        "total_interest_collections": sum(period.interest_collections for period in periods),
        "total_fees_paid": sum(period.fees_paid for period in periods),
        "total_residual_distribution": sum(period.residual_distribution for period in periods),
        "min_subordination_ratio": min_subordination,
        "subordination_breach_count": sum(
            1 for period in periods if period.subordination_ratio + TOLERANCE < scenario.min_subordination
        ),
        "weighted_average_life_months": weighted_average_life_months,
        "tranche_irr_annual": tranche_irr_annual,
        "total_waterfall_sources": total_waterfall_sources,
        "total_waterfall_uses_plus_ending_cash": total_waterfall_uses,
    }
