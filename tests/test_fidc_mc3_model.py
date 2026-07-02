import json
from pathlib import Path

import pytest

from fidc_mc3 import build_projection, load_scenario, projection_to_rows, scenario_from_dict
from fidc_mc3.validation import validate_projection, validate_scenario


SCENARIO_PATH = Path("data/fidc_mc3/mc3_base_case.json")


def _base_result():
    scenario = load_scenario(SCENARIO_PATH)
    return build_projection(scenario)


def test_mc3_base_case_has_valid_structure_and_projection():
    scenario = load_scenario(SCENARIO_PATH)
    result = build_projection(scenario)

    assert validate_scenario(scenario) == ()
    assert validate_projection(result) == ()
    assert len(result.periods) == scenario.projection_months


def test_mc3_principal_reconciles_across_revolving_cohorts():
    result = _base_result()

    assert result.metrics["principal_reconciliation_gap"] == pytest.approx(0.0, abs=1e-6)
    for period in result.periods:
        assert period.principal_collections + period.defaulted_principal == pytest.approx(
            period.scheduled_principal,
            abs=1e-6,
        )


def test_mc3_waterfall_never_uses_more_cash_than_available():
    result = _base_result()

    for period in result.periods:
        assert period.waterfall_uses <= period.available_cash + 1e-6
        assert period.ending_cash >= -1e-6
        assert all(balance >= -1e-6 for balance in period.closing_tranche_balance.values())


def test_mc3_subordination_and_loss_metrics_are_explicit():
    result = _base_result()

    assert result.metrics["min_subordination_ratio"] >= result.scenario.min_subordination
    assert result.metrics["subordination_breach_count"] == 0
    assert result.metrics["total_net_credit_loss"] == pytest.approx(
        result.metrics["total_defaulted_principal"] * (1.0 - result.scenario.credit.recovery_rate),
        abs=1e-6,
    )


def test_mc3_tranche_funding_and_returns_are_reconciled():
    result = _base_result()

    assert sum(result.initial_tranche_balance.values()) == pytest.approx(result.initial_funding, abs=1e-6)
    assert result.initial_tranche_balance["SEN"] == pytest.approx(68_950_000.0)
    assert result.metrics["weighted_average_life_months"]["SEN"] == pytest.approx(13.0)
    assert result.metrics["tranche_irr_annual"]["SEN"] == pytest.approx(0.126417, abs=1e-6)
    assert result.metrics["tranche_irr_annual"]["MEZZ"] == pytest.approx(0.1562925, abs=1e-6)
    assert result.metrics["tranche_irr_annual"]["SUB"] > result.metrics["tranche_irr_annual"]["MEZZ"]


def test_mc3_projection_rows_flatten_tranche_columns_for_audit_exports():
    result = _base_result()
    rows = projection_to_rows(result)

    assert rows
    first = rows[0]
    assert first["month"] == 1
    assert "interest_paid__SEN" in first
    assert "principal_paid__MEZZ" in first
    assert "closing_balance__SUB" in first
    assert first["flags"] == ""


def test_mc3_validation_catches_broken_tranche_share_sum():
    payload = json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))
    payload["tranches"][0]["share"] = 0.71
    scenario = scenario_from_dict(payload)

    issues = validate_scenario(scenario)

    assert [issue.code for issue in issues] == ["tranche_share_sum"]
    assert issues[0].severity == "error"
