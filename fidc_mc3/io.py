"""Input/output helpers for FIDC MC3 scenarios and projections."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, is_dataclass
from datetime import date
from pathlib import Path
from typing import Any

from .contracts import CreditAssumptions, PeriodResult, ProjectionResult, ScenarioAssumptions, TrancheTerms


def scenario_from_dict(payload: dict[str, Any]) -> ScenarioAssumptions:
    credit_payload = dict(payload["credit"])
    tranche_payloads = payload["tranches"]
    as_of = payload["as_of_date"]
    if isinstance(as_of, str):
        as_of_date = date.fromisoformat(as_of)
    elif isinstance(as_of, date):
        as_of_date = as_of
    else:
        raise ValueError("as_of_date must be an ISO date string")

    return ScenarioAssumptions(
        case_id=str(payload["case_id"]),
        as_of_date=as_of_date,
        portfolio_principal=float(payload["portfolio_principal"]),
        projection_months=int(payload["projection_months"]),
        receivable_term_months=int(payload["receivable_term_months"]),
        revolving_months=int(payload["revolving_months"]),
        purchase_discount=float(payload["purchase_discount"]),
        cdi_annual=float(payload["cdi_annual"]),
        selic_annual=float(payload["selic_annual"]),
        servicing_fee_annual=float(payload["servicing_fee_annual"]),
        admin_fee_monthly=float(payload["admin_fee_monthly"]),
        cash_reserve_percent=float(payload["cash_reserve_percent"]),
        min_subordination=float(payload["min_subordination"]),
        credit=CreditAssumptions(
            gross_yield_monthly=float(credit_payload["gross_yield_monthly"]),
            default_rate_monthly=float(credit_payload["default_rate_monthly"]),
            recovery_rate=float(credit_payload["recovery_rate"]),
            recovery_lag_months=int(credit_payload["recovery_lag_months"]),
        ),
        tranches=tuple(
            TrancheTerms(
                name=str(item["name"]),
                share=float(item["share"]),
                seniority=int(item["seniority"]),
                annual_spread=float(item.get("annual_spread", 0.0)),
                amortization_start_month=int(item.get("amortization_start_month", 1)),
                residual=bool(item.get("residual", False)),
            )
            for item in tranche_payloads
        ),
        notes=tuple(str(item) for item in payload.get("notes", ())),
    )


def load_scenario(path: str | Path) -> ScenarioAssumptions:
    with Path(path).open("r", encoding="utf-8") as handle:
        return scenario_from_dict(json.load(handle))


def projection_to_rows(result: ProjectionResult) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    tranche_names = list(result.initial_tranche_balance)
    for period in result.periods:
        row = _period_base_row(period)
        for name in tranche_names:
            row[f"interest_due__{name}"] = period.tranche_interest_due.get(name, 0.0)
            row[f"interest_paid__{name}"] = period.tranche_interest_paid.get(name, 0.0)
            row[f"principal_paid__{name}"] = period.tranche_principal_paid.get(name, 0.0)
            row[f"closing_balance__{name}"] = period.closing_tranche_balance.get(name, 0.0)
        rows.append(row)
    return rows


def write_projection_artifacts(result: ProjectionResult, output_dir: str | Path) -> dict[str, Path]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows = projection_to_rows(result)
    projection_csv = out / "projection.csv"
    summary_json = out / "summary.json"
    cashflows_json = out / "tranche_cashflows.json"

    if rows:
        with projection_csv.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    else:
        projection_csv.write_text("", encoding="utf-8")

    summary_payload = {
        "scenario": _to_jsonable(result.scenario),
        "initial_tranche_balance": result.initial_tranche_balance,
        "metrics": result.metrics,
    }
    summary_json.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    cashflows_json.write_text(
        json.dumps(result.tranche_cashflows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {
        "projection_csv": projection_csv,
        "summary_json": summary_json,
        "cashflows_json": cashflows_json,
    }


def _period_base_row(period: PeriodResult) -> dict[str, Any]:
    return {
        "month": period.month,
        "period_start": period.period_start.isoformat(),
        "period_end": period.period_end.isoformat(),
        "opening_portfolio": period.opening_portfolio,
        "acquisitions_principal": period.acquisitions_principal,
        "scheduled_principal": period.scheduled_principal,
        "defaulted_principal": period.defaulted_principal,
        "principal_collections": period.principal_collections,
        "recoveries": period.recoveries,
        "net_credit_loss": period.net_credit_loss,
        "interest_collections": period.interest_collections,
        "closing_portfolio": period.closing_portfolio,
        "opening_cash": period.opening_cash,
        "selic_income": period.selic_income,
        "available_cash": period.available_cash,
        "fees_due": period.fees_due,
        "fees_paid": period.fees_paid,
        "reinvestment_purchase_price": period.reinvestment_purchase_price,
        "residual_distribution": period.residual_distribution,
        "ending_cash": period.ending_cash,
        "collateral_value": period.collateral_value,
        "residual_nav": period.residual_nav,
        "subordination_ratio": period.subordination_ratio,
        "waterfall_uses": period.waterfall_uses,
        "flags": "|".join(period.flags),
    }


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if is_dataclass(value):
        return _to_jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    return value
