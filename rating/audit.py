"""Audit-trail rendering helpers for the rating model."""

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
    lines.append("# Memória de cálculo do rating")
    lines.append("")
    lines.append(f"- Instituição: {calc_result.get('institution_name') or 'N/A'}")
    lines.append(f"- Período: {calc_result.get('period') or 'N/A'}")
    previous_period = calc_result.get("previous_period") or "N/A"
    lines.append(f"- Base de comparação do funding: {previous_period}")
    lines.append(f"- Status: {calc_result.get('status') or 'N/A'}")
    missing_quantitative = list(calc_result.get("missing_quantitative_inputs") or [])
    if missing_quantitative:
        mapped_inputs = dict(calc_result.get("mapped_inputs") or {})
        missing_labels = [
            str(mapped_inputs.get(key, {}).get("display_label") or key)
            for key in missing_quantitative
        ]
        lines.append(f"- Inputs quantitativos faltantes: {', '.join(missing_labels)}")
    lines.append("")

    lines.append("## Dados brutos usados")
    raw_inputs = dict(calc_result.get("raw_inputs") or {})
    for key, value in raw_inputs.items():
        formatter = _fmt_number
        if "Ativo Total" in key or "Core Funding" in key or "Carteira" in key or "Perda Esperada" in key:
            formatter = _fmt_currency
        if "(%)" in key or "Crédito / Captações" in key or "Índice" in key or "ROE" in key:
            formatter = _fmt_pct
        lines.append(f"- {key} = {formatter(value)}")
    lines.append("")

    lines.append("## Classificações derivadas")
    size_bucket = calc_result.get("size_bucket") or {}
    lines.append(f"- size_bucket = {size_bucket.get('key') or 'N/A'}")
    lines.append(f"- starting_score = {calc_result.get('starting_score')}")
    for factor, payload in (calc_result.get("quantitative_scores") or {}).items():
        lines.append(f"- {factor}_bucket = {payload.get('bucket')}")
    lines.append("")

    lines.append("## Contribuições")
    lines.append(f"- starting_score = {calc_result.get('starting_score')}")
    for factor, payload in (calc_result.get("quantitative_scores") or {}).items():
        lines.append(f"- P({factor}) = {float(payload.get('score', 0.0)):+.2f}")
    for factor, payload in (calc_result.get("qualitative_scores") or {}).items():
        lines.append(f"- P({factor.upper()}) = {float(payload.get('score', 0.0)):+.2f}")
    lines.append("")

    lines.append("## Resultado final")
    raw_score = calc_result.get("raw_final_score")
    rounded_score = calc_result.get("rounded_final_score")
    final_score = calc_result.get("final_numeric_rating")
    lines.append(f"- raw_final_score = {_fmt_number(raw_score, 4)}")
    lines.append(f"- rounded_final_score = {rounded_score}")
    lines.append(f"- bounded_final_score = {final_score}")
    if calc_result.get("hard_floor_applied"):
        lines.append("- hard_floor = applied")
    lines.append("")

    lines.append("## Origem dos inputs")
    replacements = list(calc_result.get("replacements") or [])
    for item in replacements:
        display_label = item.get("display_label") or "N/A"
        source_field = item.get("source_field") or "N/A"
        source_kind = item.get("source_kind") or "N/A"
        note = item.get("note") or ""
        line = f"- {display_label}: {source_field} [{source_kind}]"
        if note:
            line += f" | {note}"
        lines.append(line)
    lines.append("")
    lines.append("## Versão da tabela de pesos")
    lines.append(f"- {calc_result.get('weights_version')}")
    lines.append(f"- {calc_result.get('weights_disclosure')}")
    return "\n".join(lines)
