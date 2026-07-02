#!/usr/bin/env python3
"""Run the FIDC MC3 projection from a JSON scenario file."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fidc_mc3 import build_projection, load_scenario, validate_projection, write_projection_artifacts


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a deterministic FIDC MC3 projection.")
    parser.add_argument(
        "--input",
        default="data/fidc_mc3/mc3_base_case.json",
        help="Path to the scenario JSON file.",
    )
    parser.add_argument(
        "--output-dir",
        default="outputs/fidc_mc3/latest",
        help="Directory where projection artifacts will be written.",
    )
    parser.add_argument(
        "--fail-on-warning",
        action="store_true",
        help="Return a non-zero exit code when validation warnings are present.",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    scenario = load_scenario(args.input)
    result = build_projection(scenario)
    issues = validate_projection(result)
    artifacts = write_projection_artifacts(result, args.output_dir)

    validation_path = Path(args.output_dir) / "validation.json"
    validation_path.write_text(
        json.dumps([asdict(issue) for issue in issues], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    artifacts["validation_json"] = validation_path

    print(json.dumps({"artifacts": {key: str(value) for key, value in artifacts.items()}, "metrics": result.metrics}, indent=2))

    severities = {issue.severity for issue in issues}
    if "error" in severities:
        return 2
    if args.fail_on_warning and "warning" in severities:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
