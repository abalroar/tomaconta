"""Mapping between the rating model and existing app fields."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from utils.ifdata_cache import CacheManager, load_conglomerados_catalog, load_critical_screens_slice
from utils.ifdata_cache.institutions import normalize_institution_name


def _project_root(base_dir: Path | None = None) -> Path:
    if base_dir is not None:
        return Path(base_dir).resolve()
    return Path(__file__).resolve().parents[1]


def _period_sort_key(period: str) -> tuple[int, int]:
    text = str(period or "").strip()
    if "/" not in text:
        return (0, 0)
    part, year = text.split("/", 1)
    try:
        return (int(year), int(part))
    except ValueError:
        return (0, 0)


def period_to_display_label(period: str) -> str:
    text = str(period or "").strip()
    if "/" not in text:
        return text
    part, year = text.split("/", 1)
    mapping = {"1": "03", "2": "06", "3": "09", "4": "12"}
    month = mapping.get(part.strip(), part.strip().zfill(2))
    return f"{month}/{year.strip()}"


def get_previous_year_same_period(period: str) -> str | None:
    text = str(period or "").strip()
    if "/" not in text:
        return None
    part, year = text.split("/", 1)
    try:
        quarter = int(part)
        year_int = int(year)
    except ValueError:
        return None
    return f"{quarter}/{year_int - 1}"


def _load_critical_screens_metadata(base_dir: Path | None = None) -> dict[str, Any]:
    root = _project_root(base_dir)
    manager = CacheManager(root)
    cache = manager.get_cache("critical_screens")
    if cache is None or not cache.arquivo_metadata.exists():
        return {}
    try:
        return json.loads(cache.arquivo_metadata.read_text(encoding="utf-8"))
    except Exception:
        return {}


def list_available_rating_periods(base_dir: Path | None = None) -> list[str]:
    metadata = _load_critical_screens_metadata(base_dir)
    periods = [str(item).strip() for item in (metadata.get("periodos") or []) if str(item).strip()]
    return sorted(set(periods), key=_period_sort_key, reverse=True)


def _institution_code_map(base_dir: Path | None = None) -> dict[str, str]:
    root = _project_root(base_dir)
    mapping: dict[str, str] = {}
    for item in load_conglomerados_catalog(root):
        name = str(item.get("nome") or "").strip()
        code = str(item.get("codigo") or "").strip()
        if name and code:
            mapping[normalize_institution_name(name)] = code
    return mapping


def load_rating_input_dataframe(period: str, base_dir: Path | None = None) -> pd.DataFrame:
    root = _project_root(base_dir)
    current = load_critical_screens_slice(base_dir=root, periodos=[str(period)])
    if current is None or current.empty:
        return pd.DataFrame()

    previous_period = get_previous_year_same_period(str(period))
    previous = (
        load_critical_screens_slice(base_dir=root, periodos=[previous_period])
        if previous_period
        else pd.DataFrame()
    )

    previous_cols = [
        "Instituição",
        "Core Funding",
        "Crédito / Captações",
        "Perda Esperada / Carteira de Crédito Bruta",
        "Ativos Estágio 3",
        "Carteira de Crédito Bruta",
        "Perda Esperada",
    ]
    available_previous_cols = [col for col in previous_cols if col in previous.columns]
    if not previous.empty and available_previous_cols:
        previous = previous[available_previous_cols].copy()
        rename_map = {
            col: f"{col} (prev)"
            for col in previous.columns
            if col != "Instituição"
        }
        previous = previous.rename(columns=rename_map)
        merged = current.merge(previous, on="Instituição", how="left")
    else:
        merged = current.copy()

    code_map = _institution_code_map(root)
    merged["ConglomeradoId"] = (
        merged["Instituição"].astype(str).map(lambda value: code_map.get(normalize_institution_name(value), ""))
    )
    merged["Período Selecionado"] = str(period)
    merged["Período Anterior"] = previous_period or ""
    return merged


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        num = float(value)
    except Exception:
        return None
    if pd.isna(num):
        return None
    return num


def _safe_ratio(num: Any, den: Any) -> float | None:
    num_f = _safe_float(num)
    den_f = _safe_float(den)
    if num_f is None or den_f is None or den_f == 0:
        return None
    return num_f / den_f


def build_variable_mapping_table() -> pd.DataFrame:
    rows = [
        {
            "Model variable": "Total assets",
            "Current app field": "Ativo Total",
            "Type": "exact",
            "Notes": "Curated prudential field from critical_screens.",
        },
        {
            "Model variable": "CET1",
        "Current app field": "Índice de Capital Principal (CET1)",
        "Type": "exact",
        "Notes": "If missing, the app uses Índice de Basileia Total (%).",
        },
        {
            "Model variable": "RoE",
            "Current app field": "ROE Ac. Anualizado (%)",
            "Type": "exact",
            "Notes": "Uses the current curated profitability field already exposed in Snapshot/Peers.",
        },
        {
            "Model variable": "NPL Creation",
            "Current app field": "Perda Esperada / Carteira de Crédito Bruta",
            "Type": "current level",
            "Notes": "Current carteira-quality indicator used in the model.",
        },
        {
            "Model variable": "Funding delta",
            "Current app field": "Current Core Funding - same quarter previous year Core Funding",
            "Type": "transformed",
            "Notes": "Current period against the same quarter of the previous year.",
        },
        {
            "Model variable": "Structural funding ratio",
            "Current app field": "Crédito / Captações",
            "Type": "current level",
            "Notes": "Current structural funding ratio used in the model.",
        },
    ]
    return pd.DataFrame(rows)


def map_rating_inputs(record: Mapping[str, Any]) -> dict[str, Any]:
    row = dict(record)
    institution = str(row.get("Instituição") or "").strip()
    period = str(row.get("Período") or row.get("Período Selecionado") or "").strip()
    previous_period = str(row.get("Período Anterior") or get_previous_year_same_period(period) or "").strip()

    raw_inputs = {
        "institution_name": institution,
        "institution_id": str(row.get("ConglomeradoId") or "").strip(),
        "period": period,
        "previous_period": previous_period,
        "Ativo Total": _safe_float(row.get("Ativo Total")),
        "Índice de Capital Principal (CET1)": _safe_float(row.get("Índice de Capital Principal (CET1)")),
        "Índice de Basileia Total (%)": _safe_float(row.get("Índice de Basileia Total (%)")),
        "ROE Ac. Anualizado (%)": _safe_float(row.get("ROE Ac. Anualizado (%)")),
        "Core Funding": _safe_float(row.get("Core Funding")),
        "Core Funding (prev)": _safe_float(row.get("Core Funding (prev)")),
        "Crédito / Captações": _safe_float(row.get("Crédito / Captações")),
        "Perda Esperada / Carteira de Crédito Bruta": _safe_float(row.get("Perda Esperada / Carteira de Crédito Bruta")),
        "Perda Esperada / Carteira de Crédito Bruta (prev)": _safe_float(
            row.get("Perda Esperada / Carteira de Crédito Bruta (prev)")
        ),
        "Ativos Estágio 3": _safe_float(row.get("Ativos Estágio 3")),
        "Ativos Estágio 3 (prev)": _safe_float(row.get("Ativos Estágio 3 (prev)")),
        "Carteira de Crédito Bruta": _safe_float(row.get("Carteira de Crédito Bruta")),
        "Carteira de Crédito Bruta (prev)": _safe_float(row.get("Carteira de Crédito Bruta (prev)")),
        "Perda Esperada": _safe_float(row.get("Perda Esperada")),
        "Perda Esperada (prev)": _safe_float(row.get("Perda Esperada (prev)")),
    }

    mapped_inputs: dict[str, dict[str, Any]] = {
        "total_assets": {
            "value": raw_inputs["Ativo Total"],
            "display_label": "Total assets",
            "source_field": "Ativo Total",
            "source_kind": "exact",
            "note": "Using the curated Ativo Total field.",
        },
        "roe": {
            "value": raw_inputs["ROE Ac. Anualizado (%)"],
            "display_label": "RoE",
            "source_field": "ROE Ac. Anualizado (%)",
            "source_kind": "exact",
            "note": "Using the curated ROE Ac. Anualizado (%) field.",
        },
    }

    cet1 = raw_inputs["Índice de Capital Principal (CET1)"]
    basel = raw_inputs["Índice de Basileia Total (%)"]
    if cet1 is not None:
        mapped_inputs["cet1"] = {
            "value": cet1,
            "display_label": "CET1",
            "source_field": "Índice de Capital Principal (CET1)",
            "source_kind": "exact",
            "note": "Using the current CET1 field.",
        }
    elif basel is not None:
        mapped_inputs["cet1"] = {
            "value": basel,
            "display_label": "CET1",
            "source_field": "Índice de Basileia Total (%)",
            "source_kind": "fallback",
            "note": "CET1 is missing for this institution/period. Using Índice de Basileia Total (%).",
        }
    else:
        mapped_inputs["cet1"] = {
            "value": None,
            "display_label": "CET1",
            "source_field": "",
            "source_kind": "missing",
            "note": "CET1 and total Basel ratio are both unavailable.",
        }

    current_core = raw_inputs["Core Funding"]
    previous_core = raw_inputs["Core Funding (prev)"]
    funding_delta = None
    if current_core is not None and previous_core is not None:
        funding_delta = current_core - previous_core
    mapped_inputs["funding_delta"] = {
        "value": funding_delta,
        "display_label": "Funding delta",
        "source_field": "Core Funding",
        "source_kind": "transformed" if funding_delta is not None else "missing",
        "note": (
            "Computed as current Core Funding minus same quarter previous year Core Funding."
            if funding_delta is not None
            else "Current or comparison-period Core Funding is unavailable."
        ),
        "components": {"current": current_core, "previous": previous_core},
    }

    credito_capt = raw_inputs["Crédito / Captações"]
    mapped_inputs["funding_structural_ratio"] = {
        "value": credito_capt,
        "display_label": "Structural funding ratio",
        "source_field": "Crédito / Captações",
        "source_kind": "current_level" if credito_capt is not None else "missing",
        "note": (
            "Using the current Crédito / Captações field."
            if credito_capt is not None
            else "Crédito / Captações is unavailable."
        ),
    }

    npl_exact_candidates = ["NPL Creation", "NPL Creation (%)", "NPL Criação", "NPL Criação (%)"]
    exact_source = next((candidate for candidate in npl_exact_candidates if candidate in row and _safe_float(row.get(candidate)) is not None), None)
    if exact_source is not None:
        mapped_inputs["npl_creation"] = {
            "value": _safe_float(row.get(exact_source)),
            "display_label": "NPL Creation",
            "source_field": exact_source,
            "source_kind": "exact",
            "note": "Using an exact NPL Creation field found in the dataset.",
        }
    else:
        current_loss_ratio = raw_inputs["Perda Esperada / Carteira de Crédito Bruta"]
        if current_loss_ratio is not None:
            mapped_inputs["npl_creation"] = {
                "value": current_loss_ratio,
                "display_label": "NPL Creation",
                "source_field": "Perda Esperada / Carteira de Crédito Bruta",
                "source_kind": "current_level",
                "note": "Using the current carteira-quality ratio available for the period.",
            }
        else:
            current_stage3_ratio = _safe_ratio(
                raw_inputs["Ativos Estágio 3"],
                raw_inputs["Carteira de Crédito Bruta"],
            )
            mapped_inputs["npl_creation"] = {
                "value": current_stage3_ratio,
                "display_label": "NPL Creation",
                "source_field": "Ativos Estágio 3 / Carteira de Crédito Bruta",
                "source_kind": "fallback" if current_stage3_ratio is not None else "missing",
                "note": (
                    "Using the current Stage 3 / Carteira ratio."
                    if current_stage3_ratio is not None
                    else "No NPL input is available for this institution/period."
                ),
            }

    disclosures = []
    for item in mapped_inputs.values():
        kind = str(item.get("source_kind") or "")
        note = str(item.get("note") or "").strip()
        source_field = str(item.get("source_field") or "").strip() or "not available"
        disclosures.append(
            {
                "display_label": str(item.get("display_label") or ""),
                "source_field": source_field,
                "source_kind": kind or "missing",
                "note": note or "No additional note.",
            }
        )

    missing_inputs = [
        key
        for key, item in mapped_inputs.items()
        if item.get("value") is None
    ]

    return {
        "institution_id": raw_inputs["institution_id"],
        "institution_name": institution,
        "period": period,
        "previous_period": previous_period,
        "raw_inputs": raw_inputs,
        "mapped_inputs": mapped_inputs,
        "replacements": disclosures,
        "missing_inputs": missing_inputs,
    }
