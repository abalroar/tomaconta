"""Mapping between the rating model and existing app fields."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from utils.ifdata_cache import CacheManager, load_conglomerados_catalog, load_critical_screens_slice
from utils.ifdata_cache.institutions import normalize_institution_name
from utils.ifdata_cache.institutions import (
    build_institution_to_conglomerate_map,
    canonicalize_institution_name,
)


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


def _parse_display_period(period: str | None) -> tuple[int | None, int | None]:
    text = str(period or "").strip()
    if "/" not in text:
        return (None, None)
    part, year = text.split("/", 1)
    try:
        return (int(year), int(part))
    except ValueError:
        return (None, None)


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
    required_columns = [
        "Instituição",
        "Período",
        "Ativo Total",
        "Índice de Capital Principal (CET1)",
        "Índice de Basileia Total (%)",
        "ROE Ac. Anualizado (%)",
        "Core Funding",
        "Crédito / Captações",
        "Perda Esperada / Carteira de Crédito Bruta",
        "Ativos Estágio 2",
        "Ativos Estágio 3",
        "Carteira de Crédito Bruta",
        "Perda Esperada",
        "ConglomeradoId",
        "D-H / Carteira",
        "D-H / Carteira (%)",
        "D-H/Carteira",
        "D-H/Carteira (%)",
    ]
    previous_period = get_previous_year_same_period(str(period))
    periodos = [str(period)]
    if previous_period and previous_period not in periodos:
        periodos.append(previous_period)

    base = load_critical_screens_slice(base_dir=root, periodos=periodos, colunas=required_columns)
    if base is None or base.empty:
        return pd.DataFrame()

    current = base[base["Período"].astype(str) == str(period)].copy()
    if current.empty:
        return pd.DataFrame()

    carteira_ratios = _load_carteira_instrumentos_ratios(str(period), base_dir=root)
    if not carteira_ratios.empty:
        merge_cols = [col for col in ["Inadimplência / Carteira Total", "Ativos Problemáticos / Carteira Total"] if col in current.columns]
        if merge_cols:
            current = current.drop(columns=merge_cols, errors="ignore")
        current = current.merge(carteira_ratios, on="Instituição", how="left")

    previous = base[base["Período"].astype(str) == str(previous_period)].copy() if previous_period else pd.DataFrame()

    previous_cols = [
        "Instituição",
        "Core Funding",
        "Crédito / Captações",
        "ROE Ac. Anualizado (%)",
        "Perda Esperada / Carteira de Crédito Bruta",
        "Ativos Estágio 2",
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


def _safe_pct_change(current: Any, previous: Any) -> float | None:
    current_f = _safe_float(current)
    previous_f = _safe_float(previous)
    if current_f is None or previous_f is None:
        return None
    if previous_f == 0:
        if current_f > 0:
            return 1.0
        if current_f == 0:
            return 0.0
        return None
    return (current_f / previous_f) - 1.0


def _safe_abs_float(value: Any) -> float | None:
    num = _safe_float(value)
    if num is None:
        return None
    return abs(float(num))


def _pick_local_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    normalized = {normalize_institution_name(str(col)): str(col) for col in df.columns}
    for candidate in candidates:
        key = normalize_institution_name(candidate)
        if key in normalized:
            return normalized[key]
    return None


def _fast_canonicalize_institutions(
    instituicoes: pd.Series,
    *,
    catalog_map: dict[str, str],
    base_dir: Path | None = None,
) -> pd.Series:
    raw = instituicoes.astype(str).fillna("").str.strip()
    normalized = raw.map(normalize_institution_name)
    resolved = normalized.map(catalog_map)

    unresolved_mask = resolved.isna() | resolved.astype(str).str.strip().eq("")
    if unresolved_mask.any():
        fallback = [
            canonicalize_institution_name(nome, catalog_map=catalog_map, base_dir=base_dir)
            for nome in raw.loc[unresolved_mask].tolist()
        ]
        resolved.loc[unresolved_mask] = fallback

    return resolved.fillna(raw)


@lru_cache(maxsize=16)
def _load_carteira_instrumentos_ratios_cached(root_str: str, period: str) -> pd.DataFrame:
    root = Path(root_str)
    manager = CacheManager(root)
    result = manager.carregar("carteira_instrumentos")
    if not result.sucesso or result.dados is None or result.dados.empty:
        return pd.DataFrame(columns=["Instituição", "Inadimplência / Carteira Total", "Ativos Problemáticos / Carteira Total"])

    df = result.dados.copy()
    if "Período" not in df.columns:
        return pd.DataFrame(columns=["Instituição", "Inadimplência / Carteira Total", "Ativos Problemáticos / Carteira Total"])
    df = df[df["Período"].astype(str) == str(period)].copy()
    if df.empty:
        return pd.DataFrame(columns=["Instituição", "Inadimplência / Carteira Total", "Ativos Problemáticos / Carteira Total"])
    if "Instituição" not in df.columns:
        return pd.DataFrame(columns=["Instituição", "Inadimplência / Carteira Total", "Ativos Problemáticos / Carteira Total"])

    catalog_map = build_institution_to_conglomerate_map(root)
    df["Instituição"] = _fast_canonicalize_institutions(
        df["Instituição"],
        catalog_map=catalog_map,
        base_dir=root,
    )

    col_total = _pick_local_column(df, ["Total Geral"])
    col_inad = _pick_local_column(df, ["Inadimplência", "Inadimplencia"])
    col_prob = _pick_local_column(df, ["Ativos problemáticos", "Ativos problematicos"])
    if not col_total:
        return pd.DataFrame(columns=["Instituição", "Inadimplência / Carteira Total", "Ativos Problemáticos / Carteira Total"])

    total = pd.to_numeric(df[col_total], errors="coerce")
    inad = pd.to_numeric(df[col_inad], errors="coerce") if col_inad else pd.Series([pd.NA] * len(df), index=df.index, dtype="float64")
    prob = pd.to_numeric(df[col_prob], errors="coerce") if col_prob else pd.Series([pd.NA] * len(df), index=df.index, dtype="float64")
    out = pd.DataFrame(
        {
            "Instituição": df["Instituição"].astype(str),
            "Inadimplência / Carteira Total": inad.divide(total.where(total != 0)),
            "Ativos Problemáticos / Carteira Total": prob.divide(total.where(total != 0)),
        }
    )
    return out.drop_duplicates(subset=["Instituição"], keep="last").reset_index(drop=True)


def _load_carteira_instrumentos_ratios(period: str, base_dir: Path | None = None) -> pd.DataFrame:
    root = _project_root(base_dir)
    return _load_carteira_instrumentos_ratios_cached(str(root), str(period)).copy()


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
            "Notes": "Current period value, audited against the same quarter of the previous year.",
        },
        {
            "Model variable": "Asset quality",
            "Current app field": "Inadimplência / Carteira Total (Rel. 16) com proxy histórica calibrada quando a série ideal não existir",
            "Type": "exact_or_proxy",
            "Notes": "4T/2025+ usa Inadimplência / Carteira Total; períodos sem essa série usam proxy explícita e documentada no audit trail.",
        },
        {
            "Model variable": "Funding delta",
            "Current app field": "%Δ Core Funding vs same quarter previous year",
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
        "ROE Ac. Anualizado (%) (prev)": _safe_float(row.get("ROE Ac. Anualizado (%) (prev)")),
        "Core Funding": _safe_float(row.get("Core Funding")),
        "Core Funding (prev)": _safe_float(row.get("Core Funding (prev)")),
        "Crédito / Captações": _safe_float(row.get("Crédito / Captações")),
        "Perda Esperada / Carteira de Crédito Bruta": _safe_float(row.get("Perda Esperada / Carteira de Crédito Bruta")),
        "Perda Esperada / Carteira de Crédito Bruta (prev)": _safe_float(
            row.get("Perda Esperada / Carteira de Crédito Bruta (prev)")
        ),
        "Inadimplência / Carteira Total": _safe_float(row.get("Inadimplência / Carteira Total")),
        "Ativos Problemáticos / Carteira Total": _safe_float(row.get("Ativos Problemáticos / Carteira Total")),
        "Ativos Estágio 2": _safe_float(row.get("Ativos Estágio 2")),
        "Ativos Estágio 2 (prev)": _safe_float(row.get("Ativos Estágio 2 (prev)")),
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
            "display_label": "Ativo Total",
            "source_field": "Ativo Total",
            "source_kind": "exact",
            "note": "Ativo total do período selecionado.",
        },
        "roe": {
            "value": raw_inputs["ROE Ac. Anualizado (%)"],
            "display_label": "ROE Ac. Anualizado (%)",
            "source_field": "ROE Ac. Anualizado (%)",
            "source_kind": "exact",
            "note": "ROE acumulado anualizado do período, auditado contra o mesmo trimestre do ano anterior.",
            "components": {
                "current": raw_inputs["ROE Ac. Anualizado (%)"],
                "previous": raw_inputs["ROE Ac. Anualizado (%) (prev)"],
            },
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
            "note": "Índice de Capital Principal do período selecionado.",
        }
    elif basel is not None:
        mapped_inputs["cet1"] = {
            "value": basel,
            "display_label": "CET1",
            "source_field": "Índice de Basileia Total (%)",
            "source_kind": "fallback",
            "note": "CET1 indisponível no período; usando Índice de Basileia Total (%).",
        }
    else:
        mapped_inputs["cet1"] = {
            "value": None,
            "display_label": "CET1",
            "source_field": "",
            "source_kind": "missing",
            "note": "CET1 e Índice de Basileia Total (%) indisponíveis.",
        }

    current_core = raw_inputs["Core Funding"]
    previous_core = raw_inputs["Core Funding (prev)"]
    funding_delta = _safe_pct_change(current_core, previous_core)
    mapped_inputs["funding_delta"] = {
        "value": funding_delta,
        "display_label": "Variação % Core Funding",
        "source_field": "Core Funding",
        "source_kind": "transformed" if funding_delta is not None else "missing",
        "note": (
            "Calculado como variação percentual do Core Funding contra o mesmo trimestre do ano anterior. "
            "Quando a base comparativa é zero, a rotina classifica a direção da variação como não negativa."
            if funding_delta is not None and previous_core == 0
            else (
            "Calculado como variação percentual do Core Funding contra o mesmo trimestre do ano anterior."
            if funding_delta is not None
            else "Core Funding do período atual ou do mesmo trimestre do ano anterior indisponível."
            )
        ),
        "components": {"current": current_core, "previous": previous_core},
    }

    credito_capt = raw_inputs["Crédito / Captações"]
    mapped_inputs["funding_structural_ratio"] = {
        "value": credito_capt,
        "display_label": "Crédito / Captações",
        "source_field": "Crédito / Captações",
        "source_kind": "current_level" if credito_capt is not None else "missing",
        "note": (
            "Relação estrutural usada para graduar a penalização de funding."
            if credito_capt is not None
            else "Crédito / Captações indisponível."
        ),
    }

    year_ref, quarter_ref = _parse_display_period(period)
    inad_ratio = raw_inputs["Inadimplência / Carteira Total"]
    problematic_ratio = raw_inputs["Ativos Problemáticos / Carteira Total"]
    perda_ratio_abs = _safe_abs_float(raw_inputs["Perda Esperada / Carteira de Crédito Bruta"])
    legacy_dh_candidates = [
        "D-H / Carteira",
        "D-H / Carteira (%)",
        "D-H/Carteira",
        "D-H/Carteira (%)",
    ]
    legacy_dh_source = next(
        (candidate for candidate in legacy_dh_candidates if candidate in row and _safe_float(row.get(candidate)) is not None),
        None,
    )

    if inad_ratio is not None:
        mapped_inputs["asset_quality"] = {
            "value": inad_ratio,
            "display_label": "Qualidade da Carteira",
            "source_field": "Inadimplência / Carteira Total",
            "source_kind": "exact",
            "rule_set": "inad_ratio_exact",
            "note": (
                "Usa Inadimplência / Carteira Total do Rel. 16, a mesma base analítica da aba Carteira 4.966. "
                "Ativos Problemáticos / Carteira Total permanece disponível como referência complementar na auditoria."
            ),
            "components": {
                "inadimplencia_ratio": inad_ratio,
                "ativos_problematicos_ratio": problematic_ratio,
            },
        }
    elif legacy_dh_source is not None and year_ref is not None and year_ref <= 2024:
        mapped_inputs["asset_quality"] = {
            "value": _safe_float(row.get(legacy_dh_source)),
            "display_label": "Qualidade da Carteira",
            "source_field": legacy_dh_source,
            "source_kind": "exact_legacy",
            "rule_set": "legacy_dh_ratio",
            "note": "Usa D-H / Carteira como medida histórica de qualidade da carteira para períodos até 2024.",
        }
    elif perda_ratio_abs is not None and (year_ref == 2025 and quarter_ref in {1, 2, 3}):
        mapped_inputs["asset_quality"] = {
            "value": perda_ratio_abs,
            "display_label": "Qualidade da Carteira",
            "source_field": "|Perda Esperada / Carteira de Crédito Bruta|",
            "source_kind": "proxy",
            "rule_set": "proxy_loss_ratio",
            "note": (
                "Em mar/25, jun/25 e set/25, a série exata de Inadimplência / Carteira Total ainda não veio preenchida no Rel. 16 local. "
                "Nesses casos, o modelo usa a proxy calibrada "
                "|Perda Esperada / Carteira de Crédito Bruta| para preservar comparabilidade sem esconder a troca metodológica."
            ),
            "components": {
                "perda_esperada_ratio_abs": perda_ratio_abs,
                "inadimplencia_ratio_disponivel": inad_ratio,
                "ativos_problematicos_ratio_disponivel": problematic_ratio,
            },
        }
    else:
        missing_note = (
            "Até 2024, o ideal conceitual seria D-H / Carteira, mas essa série ainda não está integrada ao app; "
            "por isso o fator fica indisponível e o rating permanece incompleto."
            if year_ref is not None and year_ref <= 2024
            else (
                "Sem série exata de Inadimplência / Carteira Total e sem proxy calibrada utilizável para o período; "
                "o rating fica incompleto."
            )
        )
        mapped_inputs["asset_quality"] = {
            "value": None,
            "display_label": "Qualidade da Carteira",
            "source_field": "Inadimplência / Carteira Total",
            "source_kind": "missing",
            "rule_set": "inad_ratio_exact",
            "note": missing_note,
            "components": {
                "inadimplencia_ratio_disponivel": inad_ratio,
                "ativos_problematicos_ratio_disponivel": problematic_ratio,
                "perda_esperada_ratio_abs_disponivel": perda_ratio_abs,
            },
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
