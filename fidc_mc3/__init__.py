"""Clean FIDC MC3 modeling layer."""

from .contracts import (
    CreditAssumptions,
    PeriodResult,
    ProjectionResult,
    ScenarioAssumptions,
    TrancheTerms,
)
from .engine import build_projection
from .io import load_scenario, projection_to_rows, scenario_from_dict, write_projection_artifacts
from .validation import ValidationIssue, validate_projection, validate_scenario

__all__ = [
    "CreditAssumptions",
    "PeriodResult",
    "ProjectionResult",
    "ScenarioAssumptions",
    "TrancheTerms",
    "ValidationIssue",
    "build_projection",
    "load_scenario",
    "projection_to_rows",
    "scenario_from_dict",
    "validate_projection",
    "validate_scenario",
    "write_projection_artifacts",
]
