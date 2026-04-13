"""Audit-trail rendering helpers for the reverse-engineered rating."""

from __future__ import annotations

from typing import Any, Mapping

import pandas as pd


def _fmt_number(value: Any, digits: int = 2) -> str:
    if value is None:
        return "N/A"
    try:
        num = float(value)
    except Exception:
        return str(value)
    return f"{num:,.{digits}f}"


def _fmt_pct(value: Any, digits: int = 2) -> str:
    if value is None:
        return "N/A"
    try:
        num = float(value)
    except Exception:
        return str(value)
    return f"{num * 100:.{digits}f}%"


def _fmt_currency(value: Any) -> str:
    if value is None:
        return "N/A"
    try:
        num = float(value)
    except Exception:
        return str(value)
    return f"R$ {num:,.2f}"


def build_audit_tables(calc_result: Mapping[str, Any]) -> dict[str, pd.DataFrame]:
    raw_inputs = dict(calc_result.get("raw_inputs") or {})
    mapped_inputs = dict(calc_result.get("mapped_inputs") or {})
    quantitative = dict(calc_result.get("quantitative_scores") or {})
    qualitative = dict(calc_result.get("qualitative_scores") or {})
    replacements = list(calc_result.get("replacements") or [])

    raw_rows = []
    for key, value in raw_inputs.items():
        raw_rows.append({"Field": key, "Value": value})

    mapped_rows = []
    for key, payload in mapped_inputs.items():
        mapped_rows.append(
            {
                "Model input": key,
                "Display": payload.get("display_label"),
                "Value": payload.get("value"),
                "Source field": payload.get("source_field"),
                "Source kind": payload.get("source_kind"),
                "Note": payload.get("note"),
            }
        )

    contribution_rows = []
    for key, payload in quantitative.items():
        contribution_rows.append(
            {
                "Block": "Quantitative",
                "Factor": key,
                "Bucket": payload.get("bucket"),
                "Score": payload.get("score"),
                "Note": payload.get("note"),
            }
        )
    for key, payload in qualitative.items():
        contribution_rows.append(
            {
                "Block": "Qualitative",
                "Factor": key,
                "Bucket": payload.get("answer_label"),
                "Score": payload.get("score"),
                "Note": payload.get("note"),
            }
        )

    return {
        "raw_inputs": pd.DataFrame(raw_rows),
        "mapped_inputs": pd.DataFrame(mapped_rows),
        "contributions": pd.DataFrame(contribution_rows),
        "replacements": pd.DataFrame(replacements),
    }


def build_audit_trail_markdown(calc_result: Mapping[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Rating audit trail")
    lines.append("")
    lines.append(f"- Institution: {calc_result.get('institution_name') or 'N/A'}")
    lines.append(f"- Institution ID: {calc_result.get('institution_id') or 'N/A'}")
    lines.append(f"- Period: {calc_result.get('period') or 'N/A'}")
    previous_period = calc_result.get("previous_period") or "N/A"
    lines.append(f"- Previous period used for deltas: {previous_period}")
    lines.append(f"- Status: {calc_result.get('status') or 'N/A'}")
    lines.append("")

    lines.append("## Raw data used")
    raw_inputs = dict(calc_result.get("raw_inputs") or {})
    for key, value in raw_inputs.items():
        formatter = _fmt_number
        if "Ativo Total" in key or "Core Funding" in key or "Carteira" in key or "Perda Esperada" in key:
            formatter = _fmt_currency
        if "(%)" in key or "Crédito / Captações" in key or "Índice" in key or "ROE" in key:
            formatter = _fmt_pct
        lines.append(f"- {key} = {formatter(value)}")
    lines.append("")

    lines.append("## Derived classifications")
    size_bucket = calc_result.get("size_bucket") or {}
    lines.append(f"- size_bucket = {size_bucket.get('key') or 'N/A'}")
    lines.append(f"- starting_score = {calc_result.get('starting_score')}")
    for factor, payload in (calc_result.get("quantitative_scores") or {}).items():
        lines.append(f"- {factor}_bucket = {payload.get('bucket')}")
    lines.append("")

    lines.append("## Score contributions")
    lines.append(f"- starting_score = {calc_result.get('starting_score')}")
    for factor, payload in (calc_result.get("quantitative_scores") or {}).items():
        lines.append(f"- P({factor}) = {float(payload.get('score', 0.0)):+.2f}")
    for factor, payload in (calc_result.get("qualitative_scores") or {}).items():
        lines.append(f"- P({factor.upper()}) = {float(payload.get('score', 0.0)):+.2f}")
    lines.append("")

    lines.append("## Final arithmetic")
    raw_score = calc_result.get("raw_final_score")
    rounded_score = calc_result.get("rounded_final_score")
    final_score = calc_result.get("final_numeric_rating")
    lines.append(f"- raw_final_score = {_fmt_number(raw_score, 4)}")
    lines.append(f"- rounded_final_score = {rounded_score}")
    lines.append(f"- bounded_final_score = {final_score}")
    secondary_label = calc_result.get("secondary_label")
    if secondary_label:
        lines.append(f"- secondary_label = {secondary_label}")
    if calc_result.get("hard_floor_applied"):
        lines.append("- hard_floor = applied")
    lines.append("")

    lines.append("## Data replacement disclosure")
    replacements = list(calc_result.get("replacements") or [])
    for item in replacements:
        lines.append(
            f"- {item.get('display_label')}: [{item.get('source_kind')}] "
            f"{item.get('source_field')} -> {item.get('note')}"
        )
    lines.append("")
    lines.append(f"## Coefficient version")
    lines.append(f"- {calc_result.get('weights_version')}")
    lines.append(f"- {calc_result.get('weights_disclosure')}")
    return "\n".join(lines)
