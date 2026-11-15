"""Portable entry points for the unchanged financial model and native renderers.

This module runs in CPython and Pyodide. It needs no Streamlit, cache or Parquet.
Amounts/formulas remain owned by utils.prudential_*; JSON only transports inputs.
"""
from __future__ import annotations

import json
import math

import pandas as pd

from utils.prudential_analysis import build_analysis, period_key
from utils.prudential_nim import (add_nim_rows, apply_average_roe, credit_balances,
                                  equity_balances, prior_periods, required_periods)
from utils.prudential_presentation import (PAGE_GROUPS, display_rows, format_cell,
    period_cells, period_source, reference_note, row_tier, value_tone, export_filename)

MODEL_VERSION = "statement-v6"
INPUT_VERSION = 2


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [clean(v) for v in value]
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if hasattr(value, "item"):
        return clean(value.item())
    return value


def _decode(value):
    return json.loads(value) if isinstance(value, str) else value


def _frame(packet):
    frame = pd.DataFrame(packet["data"], columns=packet["columns"])
    for column, value in packet.get("constants", {}).items():
        frame[column] = value
    if packet.get("columnOrder"):
        frame = frame[packet["columnOrder"]]
    if packet.get("provenance"):
        frame.attrs["prudential_provenance"] = packet["provenance"]
    return frame


def build_from_payload(payload, periods):
    """Reproduce load_analysis with already extracted, exact-identity sources."""
    payload, periods = _decode(payload), _decode(periods)
    if payload.get("schemaVersion") != INPUT_VERSION:
        raise ValueError("Versão de fontes de demonstrações incompatível")
    if payload.get("modelVersion") != MODEL_VERSION:
        raise ValueError("Versão do modelo de demonstrações incompatível")
    if payload.get("scope") not in {"prudential", "individual"}:
        raise ValueError("Perímetro de demonstrações inválido")
    code, scope = payload["code"], payload["scope"]
    if payload["id"] != f"{scope}-{code}":
        raise ValueError("Identidade de demonstrações inconsistente")
    if not isinstance(periods, list) or not 1 <= len(periods) <= 8:
        raise ValueError("Selecione de uma a oito competências")
    selected = [period_key(p) for p in periods]
    if len(selected) != len(set(selected)):
        raise ValueError("Competência selecionada duplicada")
    if set(selected) - set(payload["periods"]):
        raise ValueError("Competência fora da cobertura desta instituição")
    selected.sort()
    cosif = _frame(payload["cosif"])
    if set(cosif["COD_CONGL"].astype(str)) != {code}:
        raise ValueError("Fonte COSIF contém outra identidade")
    # The original loader supplies exactly the selected periods plus context.
    cosif = cosif[cosif.DATA_BASE.astype(str).isin(required_periods(selected))].copy()
    sources = {}
    for kind, packet in payload["ifdata"].items():
        frame = _frame(packet)
        if "CodInst" not in frame or set(frame.CodInst.astype(str)) - {code}:
            raise ValueError("Fonte IF.data contém outra identidade")
        sources[kind] = frame
    kwargs = ({"result_doc": "4010", "scope_label": "Instituição individual",
               "source_label": "COSIF 4010", "has_portfolio": False}
              if scope == "individual" else {})
    overrides = payload.get("overrides") or {}
    analysis = build_analysis(cosif, sources, code, selected, overrides=overrides, **kwargs)
    available = set(cosif.DATA_BASE.astype(str))
    missing = [p for p in prior_periods(analysis.periods) if p in available]
    prior_credit, prior_equity = {}, {}
    if missing:
        prior = build_analysis(cosif, sources, code, missing, overrides=overrides, **kwargs)
        prior_credit, prior_equity = credit_balances(prior), equity_balances(prior)
    add_nim_rows(analysis, prior_credit)
    if scope == "prudential":
        apply_average_roe(analysis, prior_equity)
    return analysis


def serialize_cell(cell):
    if cell is None:
        return {"value": None, "display": "–", "state": "missing"}
    value = clean(cell.value)
    valid = isinstance(value, (int, float)) and not isinstance(value, bool)
    return {"value": value if valid else None, "display": format_cell(cell) or "–",
            "state": "value" if valid else "missing", "format": cell.fmt,
            "formula": cell.formula, "tone": value_tone(cell), "style": cell.style}


def serialize_analysis(analysis):
    tables = []
    for name in analysis.rows:
        sheet, rows = analysis.sheets[name], []
        for ident, row, label in display_rows(analysis, name):
            style = sheet.cells[f"B{row}"].style
            rows.append({"id": ident, "label": label, "style": style,
                "tier": row_tier(name, ident, style), "sourceRow": row,
                "cells": {p: {"amount": serialize_cell(period_cells(sheet, row, i)[0]),
                              "share": serialize_cell(period_cells(sheet, row, i)[1])}
                          for i, p in enumerate(analysis.periods)}})
        tables.append({"name": name, "rows": rows,
            "sources": {p: period_source(sheet, i) for i, p in enumerate(analysis.periods)},
            "pageGroups": PAGE_GROUPS.get(name, ())})
    return clean({"periods": analysis.periods, "tables": tables, "checks": analysis.checks,
        "limitations": analysis.limitations, "reference": analysis.reference,
        "referenceNote": reference_note(analysis), "unit": "R$ milhões",
        "percentUnit": "fraction", "modelVersion": MODEL_VERSION,
        "filename": export_filename(analysis)})


def analyze(payload_json, periods_json):
    payload = _decode(payload_json)
    result = serialize_analysis(build_from_payload(payload, periods_json))
    result.update({key: payload[key] for key in ("id", "scope", "code", "name")})
    return json.dumps(result,
                      ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def export_native(payload_json, periods_json, format):
    analysis = build_from_payload(payload_json, periods_json)
    if format == "xlsx":
        from utils.prudential_workbook import render_xlsx
        return render_xlsx(analysis)
    if format == "pptx":
        from utils.prudential_pptx import render_pptx
        result = render_pptx(analysis)
        return result[0] if isinstance(result, tuple) else result
    raise ValueError("Formato de exportação de demonstrações inválido")
