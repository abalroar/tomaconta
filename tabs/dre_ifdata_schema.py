from __future__ import annotations

import io
import json
import math
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

import numpy as np
import pandas as pd
import plotly.graph_objects as go


DEFAULT_MAPPING_PATH = Path("data/dre_gerencial_mapping.json")
ABS_TOLERANCE = 1.0
REL_TOLERANCE = 1e-4

STATUS_OK = "OK"
STATUS_ATTENTION = "atenção"
STATUS_ERROR = "erro"
STATUS_NOT_TESTABLE = "não testável por ausência de coluna"
STATUS_AMBIGUOUS = "ambíguo"
STATUS_NO_SOURCE = "sem fonte identificada"


@dataclass(frozen=True)
class ResolvedValue:
    canonical_name: str
    display_name: str
    value: Optional[float]
    status: str
    source_columns: tuple[str, ...] = ()
    source_group: str = ""
    formula: str = ""
    observations: str = ""
    missing_value: bool = False
    ambiguous: bool = False


def normalize_column_names(columns: Sequence[Any]) -> dict[str, str]:
    """Retorna de-para entre coluna original e chave normalizada para matching."""
    return {str(col): _normalize_key(str(col)) for col in columns}


def load_mapping_config(path: Path | str = DEFAULT_MAPPING_PATH) -> dict[str, Any]:
    mapping_path = Path(path)
    if mapping_path.exists():
        return json.loads(mapping_path.read_text(encoding="utf-8"))
    return _fallback_mapping_config()


def load_parquet_files(files_or_paths: Sequence[Any]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for item in files_or_paths:
        if item is None:
            continue
        source_name = getattr(item, "name", None) or str(item)
        try:
            if isinstance(item, (str, Path)):
                df_item = pd.read_parquet(Path(item))
            else:
                item.seek(0)
                df_item = pd.read_parquet(item)
        except Exception as exc:
            raise ValueError(f"Não foi possível ler parquet '{source_name}': {exc}") from exc
        df_item = df_item.copy()
        df_item["__arquivo_origem"] = str(source_name)
        df_item["__linha_origem"] = np.arange(len(df_item), dtype="int64")
        frames.append(df_item)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True, sort=False)


def inspect_schema(df: pd.DataFrame, sample_size: int = 5) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    total_rows = len(df)
    normalized = normalize_column_names(df.columns)
    for pos, col in enumerate(df.columns, start=1):
        serie = df[col]
        non_null = int(serie.notna().sum())
        numeric = pd.to_numeric(serie, errors="coerce")
        numeric_non_null = int(numeric.notna().sum())
        is_numeric = bool(numeric_non_null > 0 and numeric_non_null >= max(1, non_null * 0.5))
        sample_values = [
            str(v)[:80]
            for v in serie.dropna().head(sample_size).tolist()
        ]
        row = {
            "posição": pos,
            "coluna_original": str(col),
            "nome_normalizado": normalized[str(col)],
            "dtype": str(serie.dtype),
            "não_nulos": non_null,
            "cobertura_%": (non_null / total_rows * 100.0) if total_rows else 0.0,
            "valores_distintos": int(serie.nunique(dropna=True)) if total_rows else 0,
            "parece_numérica": is_numeric,
            "amostra": " | ".join(sample_values),
        }
        if is_numeric:
            valid = numeric.dropna()
            row.update(
                {
                    "mín": float(valid.min()) if not valid.empty else np.nan,
                    "mediana": float(valid.median()) if not valid.empty else np.nan,
                    "máx": float(valid.max()) if not valid.empty else np.nan,
                    "% positivos": float((valid > 0).mean() * 100.0) if not valid.empty else np.nan,
                    "% negativos": float((valid < 0).mean() * 100.0) if not valid.empty else np.nan,
                }
            )
        else:
            row.update({"mín": np.nan, "mediana": np.nan, "máx": np.nan, "% positivos": np.nan, "% negativos": np.nan})
        rows.append(row)
    return pd.DataFrame(rows)


def build_mapping_candidates(df: pd.DataFrame, config: Mapping[str, Any]) -> dict[str, Any]:
    columns = [str(c) for c in df.columns]
    normalized = normalize_column_names(columns)
    norm_to_columns: dict[str, list[str]] = {}
    for col, key in normalized.items():
        norm_to_columns.setdefault(key, []).append(col)

    identifier_matches = {
        item["canonical_name"]: _match_identifier(df, item, norm_to_columns)
        for item in config.get("identifiers", [])
        if isinstance(item, Mapping) and item.get("canonical_name")
    }

    rubric_matches: dict[str, dict[str, Any]] = {}
    used_columns: set[str] = set()
    candidate_rows: list[dict[str, Any]] = []
    for entry in config.get("rubrics", []):
        if not isinstance(entry, Mapping) or not entry.get("canonical_name"):
            continue
        canonical = str(entry["canonical_name"])
        group_matches = []
        for source_group in _source_groups(entry):
            matched = _match_source_group(columns, source_group, entry, norm_to_columns)
            used_columns.update(matched["columns"])
            group_matches.append(matched)

        all_cols = _unique_keep_order([col for g in group_matches for col in g["columns"]])
        status = STATUS_OK if all_cols else STATUS_NO_SOURCE
        if all_cols and _has_multiple_period_families_with_columns(group_matches):
            status = STATUS_ATTENTION

        candidate_rows.append(
            {
                "grupo": entry.get("group", ""),
                "nome_canônico": canonical,
                "rubrica": entry.get("display_name", canonical),
                "tipo_linha": entry.get("line_type", ""),
                "tipo_rubrica": entry.get("rubric_type", ""),
                "sinal_esperado": entry.get("expected_sign", ""),
                "status_mapeamento": status,
                "colunas_origem": ", ".join(all_cols),
                "grupos_fonte": "; ".join(
                    f"{g['name']}: {', '.join(g['columns']) or 'sem match'}"
                    for g in group_matches
                ),
                "observações": (
                    "Múltiplas famílias de layout encontradas; a seleção por período/valor será validada linha a linha."
                    if status == STATUS_ATTENTION
                    else ""
                ),
            }
        )
        rubric_matches[canonical] = {
            "entry": dict(entry),
            "groups": group_matches,
            "columns": tuple(all_cols),
            "status": status,
        }

    for canonical, match in identifier_matches.items():
        if match.get("column"):
            used_columns.add(str(match["column"]))

    unmapped_relevant = _find_unmapped_relevant_columns(df, used_columns)
    return {
        "identifier_matches": identifier_matches,
        "rubric_matches": rubric_matches,
        "candidate_table": pd.DataFrame(candidate_rows),
        "unmapped_relevant": unmapped_relevant,
        "normalized_columns": normalized,
    }


def validate_mapping(
    df: pd.DataFrame,
    mapping_result: Mapping[str, Any],
    config: Mapping[str, Any],
    *,
    sample_size: int = 2000,
) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    identities = list(config.get("identities", []))
    if not identities:
        return pd.DataFrame()
    needed = _identity_canonical_names(identities)
    sample = df.head(sample_size).copy()
    canonical = canonicalize_dataframe(sample, mapping_result, config, canonical_names=needed)
    rows: list[dict[str, Any]] = []
    for identity in identities:
        target = str(identity.get("target") or "")
        components = [str(c) for c in identity.get("components", [])]
        optional = set(str(c) for c in identity.get("optional_components", []))
        if target not in canonical.columns:
            rows.append(_identity_summary_row(identity, STATUS_NOT_TESTABLE, None, None, None, "alvo ausente na amostra"))
            continue
        component_cols = [c for c in components if c in canonical.columns]
        required_missing_cols = [c for c in components if c not in canonical.columns and c not in optional]
        if not component_cols:
            rows.append(_identity_summary_row(identity, STATUS_NOT_TESTABLE, None, None, None, "componentes ausentes na amostra"))
            continue
        target_series = pd.to_numeric(canonical[target], errors="coerce")
        comp_sum = canonical[component_cols].apply(pd.to_numeric, errors="coerce").sum(axis=1, min_count=1)
        valid_mask = target_series.notna() & comp_sum.notna()
        if not valid_mask.any():
            rows.append(_identity_summary_row(identity, STATUS_NOT_TESTABLE, None, None, None, "sem linhas com alvo e componentes"))
            continue
        diff = target_series[valid_mask] - comp_sum[valid_mask]
        scale = pd.concat([target_series[valid_mask].abs(), comp_sum[valid_mask].abs()], axis=1).max(axis=1)
        tolerance = np.maximum(ABS_TOLERANCE, scale * REL_TOLERANCE)
        ok_mask = diff.abs() <= tolerance
        ok_rate = float(ok_mask.mean())
        max_abs_diff = float(diff.abs().max())
        median_abs_diff = float(diff.abs().median())
        if ok_rate >= 0.98 and not required_missing_cols:
            status = STATUS_OK
        elif ok_rate >= 0.90:
            status = STATUS_ATTENTION
        else:
            status = STATUS_ERROR
        note = ""
        if required_missing_cols:
            status = STATUS_ATTENTION if status == STATUS_OK else status
            note = "componentes obrigatórios sem coluna: " + ", ".join(required_missing_cols)
        rows.append(_identity_summary_row(identity, status, ok_rate, max_abs_diff, median_abs_diff, note))
    return pd.DataFrame(rows)


def canonicalize_dataframe(
    df: pd.DataFrame,
    mapping_result: Mapping[str, Any],
    config: Mapping[str, Any],
    *,
    canonical_names: Optional[Sequence[str]] = None,
) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    names = list(canonical_names or [r.get("canonical_name") for r in config.get("rubrics", [])])
    names = [str(n) for n in names if n]

    id_matches = mapping_result.get("identifier_matches", {})
    out = pd.DataFrame(index=df.index)
    for canonical_id, out_col in [("institution", "institution"), ("period", "period"), ("institution_code", "institution_code")]:
        source_col = (id_matches.get(canonical_id) or {}).get("column")
        if source_col in df.columns:
            out[out_col] = df[source_col]

    out["__arquivo_origem"] = df["__arquivo_origem"] if "__arquivo_origem" in df.columns else ""
    out["__linha_origem"] = df["__linha_origem"] if "__linha_origem" in df.columns else df.index

    for idx, row in df.iterrows():
        period_meta = parse_period_metadata(row.get((id_matches.get("period") or {}).get("column")))
        for canonical in names:
            resolved = resolve_canonical_value(row, canonical, mapping_result, period_meta)
            out.loc[idx, canonical] = resolved.value if resolved.value is not None else np.nan
            out.loc[idx, f"{canonical}__status"] = resolved.status
    return out.reset_index(drop=True)


def calculate_dre(
    row: pd.Series,
    mapping_result: Mapping[str, Any],
    config: Mapping[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    id_matches = mapping_result.get("identifier_matches", {})
    period_col = (id_matches.get("period") or {}).get("column")
    period_meta = parse_period_metadata(row.get(period_col))

    resolved: dict[str, ResolvedValue] = {}
    for entry in config.get("rubrics", []):
        canonical = str(entry.get("canonical_name") or "")
        if canonical:
            resolved[canonical] = resolve_canonical_value(row, canonical, mapping_result, period_meta)

    validation_df = validate_dre_identities(resolved, config)
    validation_by_target = {
        str(item.get("target")): item
        for item in validation_df.to_dict("records")
        if item.get("target")
    }

    rows: list[dict[str, Any]] = []
    for entry in config.get("rubrics", []):
        if not entry.get("include_in_dre", False):
            continue
        canonical = str(entry.get("canonical_name") or "")
        resolved_value = resolved.get(canonical)
        if resolved_value is None:
            continue

        value = resolved_value.value
        line_type = str(entry.get("line_type") or "direta")
        status = resolved_value.status
        source_columns = list(resolved_value.source_columns)
        formula = resolved_value.formula
        observations = resolved_value.observations

        identity_row = validation_by_target.get(canonical)
        if identity_row:
            if identity_row.get("status") in {STATUS_OK, STATUS_ATTENTION, STATUS_ERROR}:
                status = _combine_status(status, str(identity_row.get("status")))
            if identity_row.get("formula"):
                formula = identity_row.get("formula") or formula
            if identity_row.get("observações"):
                observations = _append_note(observations, str(identity_row.get("observações")))

        if value is None and identity_row:
            derived = _derive_from_identity(identity_row, resolved)
            if derived is not None:
                value, deriv_sources, deriv_missing = derived
                line_type = "derivada"
                source_columns = deriv_sources
                formula = str(identity_row.get("formula") or "")
                status = STATUS_ATTENTION if deriv_missing else STATUS_OK
                observations = _append_note(
                    observations,
                    (
                        "Valor derivado dos componentes disponíveis; componentes ausentes tratados como zero apenas nesta derivação: "
                        + ", ".join(deriv_missing)
                    )
                    if deriv_missing
                    else "Valor derivado porque o subtotal publicado não foi localizado."
                )

        if value is None and status in {STATUS_NO_SOURCE, STATUS_NOT_TESTABLE}:
            line_type = "manual sem fonte" if line_type != "informativa" else "informativa"

        rows.append(
            _dre_row(
                group=str(entry.get("group") or ""),
                rubric=str(entry.get("display_name") or canonical),
                canonical_name=canonical,
                value=value,
                line_type=line_type,
                source_columns=source_columns,
                formula=formula,
                status=status,
                observations=observations or str(entry.get("description") or ""),
            )
        )

    for item in config.get("ambiguous_lines", []):
        rows.append(
            _dre_row(
                group=str(item.get("group") or "LINHAS SEM FONTE OU AMBIGUAS"),
                rubric=str(item.get("display_name") or ""),
                canonical_name="",
                value=None,
                line_type="manual sem fonte",
                source_columns=[],
                formula="",
                status=STATUS_NO_SOURCE,
                observations=str(item.get("note") or "Sem fonte clara no IFData carregado."),
            )
        )

    dre_df = pd.DataFrame(rows)
    alerts_df = _build_alerts(dre_df, validation_df, mapping_result)
    return dre_df, validation_df, alerts_df


def validate_dre_identities(
    resolved: Mapping[str, ResolvedValue],
    config: Mapping[str, Any],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for identity in config.get("identities", []):
        target = str(identity.get("target") or "")
        target_resolved = resolved.get(target)
        components = [str(c) for c in identity.get("components", [])]
        optional = set(str(c) for c in identity.get("optional_components", []))

        if target_resolved is None or target_resolved.value is None:
            derived = _derive_from_identity(identity, resolved)
            if derived is None:
                rows.append(
                    {
                        "id": identity.get("id", ""),
                        "validação": identity.get("label", ""),
                        "target": target,
                        "status": STATUS_NOT_TESTABLE,
                        "valor_publicado": np.nan,
                        "valor_calculado": np.nan,
                        "diferença": np.nan,
                        "tolerância": np.nan,
                        "formula": identity.get("formula_text", ""),
                        "observações": "subtotal alvo ausente e componentes insuficientes para derivação",
                    }
                )
                continue
            derived_value, _, missing = derived
            rows.append(
                {
                    "id": identity.get("id", ""),
                    "validação": identity.get("label", ""),
                    "target": target,
                    "status": STATUS_NOT_TESTABLE,
                    "valor_publicado": np.nan,
                    "valor_calculado": derived_value,
                    "diferença": np.nan,
                    "tolerância": np.nan,
                    "formula": identity.get("formula_text", ""),
                    "observações": "subtotal publicado ausente; derivável parcialmente" + (f"; ausentes: {', '.join(missing)}" if missing else ""),
                }
            )
            continue

        component_values: list[float] = []
        missing_required: list[str] = []
        missing_optional: list[str] = []
        ambiguous_components: list[str] = []
        for component in components:
            comp_resolved = resolved.get(component)
            if comp_resolved is None or comp_resolved.value is None:
                if component in optional:
                    missing_optional.append(component)
                else:
                    missing_required.append(component)
                continue
            if comp_resolved.ambiguous:
                ambiguous_components.append(component)
            component_values.append(float(comp_resolved.value))

        if not component_values:
            status = STATUS_NOT_TESTABLE
            calculated = np.nan
            diff = np.nan
            tolerance = np.nan
            note = "componentes ausentes"
        else:
            calculated = float(np.sum(component_values))
            diff = float(target_resolved.value - calculated)
            scale = max(abs(float(target_resolved.value)), abs(calculated), 1.0)
            tolerance = max(ABS_TOLERANCE, scale * REL_TOLERANCE)
            closes = abs(diff) <= tolerance
            if closes and not missing_required and not ambiguous_components:
                status = STATUS_OK
            elif ambiguous_components:
                status = STATUS_AMBIGUOUS
            elif closes:
                status = STATUS_ATTENTION
            else:
                status = STATUS_ERROR if not missing_required else STATUS_ATTENTION
            notes = []
            if missing_required:
                notes.append("componentes obrigatórios ausentes: " + ", ".join(missing_required))
            if missing_optional:
                notes.append("componentes opcionais ausentes: " + ", ".join(missing_optional))
            if ambiguous_components:
                notes.append("componentes ambíguos: " + ", ".join(ambiguous_components))
            note = "; ".join(notes)

        rows.append(
            {
                "id": identity.get("id", ""),
                "validação": identity.get("label", ""),
                "target": target,
                "status": status,
                "valor_publicado": target_resolved.value,
                "valor_calculado": calculated,
                "diferença": diff,
                "tolerância": tolerance,
                "formula": identity.get("formula_text", ""),
                "observações": note,
            }
        )
    return pd.DataFrame(rows)


def resolve_canonical_value(
    row: pd.Series,
    canonical_name: str,
    mapping_result: Mapping[str, Any],
    period_meta: Optional[Mapping[str, Any]] = None,
) -> ResolvedValue:
    rubric_match = (mapping_result.get("rubric_matches") or {}).get(canonical_name)
    if not rubric_match:
        return ResolvedValue(canonical_name, canonical_name, None, STATUS_NO_SOURCE, observations="rubrica não configurada")

    entry = rubric_match.get("entry", {})
    display_name = str(entry.get("display_name") or canonical_name)
    groups = list(rubric_match.get("groups") or [])
    evaluated = [_evaluate_group(row, group, period_meta) for group in groups]
    with_values = [g for g in evaluated if g.get("has_value")]
    if not with_values:
        any_columns = _unique_keep_order([col for g in evaluated for col in g.get("columns", [])])
        status = STATUS_NOT_TESTABLE if any_columns else STATUS_NO_SOURCE
        obs = "colunas encontradas, mas sem valor para a linha selecionada" if any_columns else "nenhuma coluna fonte encontrada"
        return ResolvedValue(
            canonical_name,
            display_name,
            None,
            status,
            source_columns=tuple(any_columns),
            formula=_entry_formula(entry, any_columns),
            observations=obs,
            missing_value=True,
        )

    preferred = [g for g in with_values if g.get("period_valid")]
    selected_candidates = preferred or with_values
    values = [float(g["value"]) for g in selected_candidates if g.get("value") is not None and not pd.isna(g.get("value"))]
    source_columns = _unique_keep_order([col for g in selected_candidates for col in g.get("used_columns", [])])
    source_group = "; ".join([str(g.get("name") or "") for g in selected_candidates])

    if not values:
        return ResolvedValue(
            canonical_name,
            display_name,
            None,
            STATUS_NOT_TESTABLE,
            source_columns=tuple(source_columns),
            source_group=source_group,
            formula=_entry_formula(entry, source_columns),
            observations="fontes encontradas, mas valores não numéricos ou vazios",
            missing_value=True,
        )

    if len(values) == 1 or _all_close(values):
        value = float(values[0])
        status = STATUS_OK
        observations = ""
        group_statuses = [str(g.get("status") or "") for g in selected_candidates]
        if any(s == STATUS_AMBIGUOUS for s in group_statuses):
            status = STATUS_AMBIGUOUS
            observations = "grupo de fonte contém múltiplos valores conflitantes"
        elif not preferred and any(g.get("valid_for") for g in with_values):
            status = STATUS_ATTENTION
            observations = "valor obtido fora da regra de período configurada"
        sign_note = _sign_validation_note(value, str(entry.get("expected_sign") or "mixed"))
        if sign_note:
            status = _combine_status(status, STATUS_ATTENTION)
            observations = _append_note(observations, sign_note)
        return ResolvedValue(
            canonical_name,
            display_name,
            value,
            status,
            source_columns=tuple(source_columns),
            source_group=source_group,
            formula=_entry_formula(entry, source_columns),
            observations=observations,
            ambiguous=status == STATUS_AMBIGUOUS,
        )

    return ResolvedValue(
        canonical_name,
        display_name,
        None,
        STATUS_AMBIGUOUS,
        source_columns=tuple(source_columns),
        source_group=source_group,
        formula=_entry_formula(entry, source_columns),
        observations="múltiplas fontes candidatas com valores diferentes; valor não usado no cálculo",
        ambiguous=True,
    )


def format_currency(value: Any, *, scale: str = "mm", decimals: int = 1, parentheses: bool = False) -> str:
    if value is None or pd.isna(value):
        return ""
    number = float(value)
    if scale == "mm":
        number = number / 1000.0
    sign = number < 0
    abs_value = abs(number)
    formatted = f"{abs_value:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if sign and parentheses:
        return f"(R$ {formatted})"
    prefix = "-R$ " if sign else "R$ "
    return f"{prefix}{formatted}"


def export_to_excel(
    dre_df: pd.DataFrame,
    validation_df: pd.DataFrame,
    mapping_df: pd.DataFrame,
    alerts_df: pd.DataFrame,
    schema_df: Optional[pd.DataFrame] = None,
) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        dre_df.to_excel(writer, index=False, sheet_name="DRE")
        validation_df.to_excel(writer, index=False, sheet_name="Validacoes")
        mapping_df.to_excel(writer, index=False, sheet_name="De-para")
        alerts_df.to_excel(writer, index=False, sheet_name="Alertas")
        if schema_df is not None and not schema_df.empty:
            schema_df.to_excel(writer, index=False, sheet_name="Schema")
    return output.getvalue()


def execution_plan_markdown() -> str:
    return """
1. Leitura: o app aceita upload de um ou mais parquets ou usa caches locais, concatena as bases e preserva arquivo/linha de origem.
2. Diagnóstico: cada coluna é inspecionada por posição, nome normalizado, tipo, cobertura, amostras, estatísticas e distribuição de sinais.
3. Mapeamento: o JSON `data/dre_gerencial_mapping.json` define hipóteses iniciais por aliases, letras, famílias de layout e regras de período; o parquet real sempre prevalece.
4. Validação: subtotais são comparados com componentes quando alvo e componentes existem, com tolerância para arredondamento; ausência, conflito e ambiguidade são estados explícitos.
5. Montagem: a DRE usa valores publicados quando reconciliáveis e só deriva subtotais quando a fonte direta está ausente ou não testável.
6. Interface: a aba mostra schema, de-para, DRE, validações, alertas, gráficos e exportação Excel sem fórmulas de planilha.
7. Hipóteses pendentes: escala original tratada como R$ mil para exibição em R$ MM; sinais não são invertidos automaticamente; linhas sem fonte clara permanecem vazias.
"""


def render_streamlit_app() -> None:
    import streamlit as st

    st.markdown("### DRE gerencial rastreável")
    st.caption("A camada abaixo diagnostica o parquet antes de montar a DRE. Nenhum sinal é invertido e nenhuma linha sem fonte clara recebe valor.")

    config = load_mapping_config()
    with st.expander("Plano de execução", expanded=True):
        st.markdown(execution_plan_markdown())

    source_mode = st.radio(
        "Fonte dos dados",
        ["Cache local", "Upload parquet"],
        horizontal=True,
        key="dre_schema_source_mode",
    )

    files_or_paths: list[Any] = []
    if source_mode == "Upload parquet":
        uploaded_files = st.file_uploader(
            "Arquivos parquet do IFData",
            type=["parquet"],
            accept_multiple_files=True,
            key="dre_schema_upload",
        )
        files_or_paths = list(uploaded_files or [])
    else:
        local_options = _discover_local_parquet_options()
        if not local_options:
            st.warning("Nenhum parquet local encontrado em `data/cache`.")
            return
        default_paths = [p for p in local_options if str(p).endswith("data/cache/dre/dados.parquet")]
        selected_paths = st.multiselect(
            "Parquets locais",
            options=local_options,
            default=default_paths or local_options[:1],
            format_func=lambda p: str(p),
            key="dre_schema_local_paths",
        )
        files_or_paths = list(selected_paths)

    if not files_or_paths:
        st.info("Selecione pelo menos um arquivo parquet.")
        return

    try:
        df = _load_parquets_for_ui(files_or_paths)
    except Exception as exc:
        st.error(str(exc))
        return
    if df.empty:
        st.warning("Os parquets carregados não possuem linhas.")
        return

    schema_df = inspect_schema(df)
    mapping_result = build_mapping_candidates(df, config)
    mapping_df = mapping_result["candidate_table"]
    global_validation = validate_mapping(df, mapping_result, config)
    id_matches = mapping_result.get("identifier_matches", {})
    inst_col = (id_matches.get("institution") or {}).get("column")
    period_col = (id_matches.get("period") or {}).get("column")

    top_metrics = st.columns(4)
    top_metrics[0].metric("Linhas", f"{len(df):,}".replace(",", "."))
    top_metrics[1].metric("Colunas", f"{len(df.columns):,}".replace(",", "."))
    top_metrics[2].metric("Rubricas mapeadas", int((mapping_df["status_mapeamento"] != STATUS_NO_SOURCE).sum()) if not mapping_df.empty else 0)
    top_metrics[3].metric("Alertas globais", int((global_validation.get("status", pd.Series(dtype=str)) != STATUS_OK).sum()) if not global_validation.empty else 0)

    tab_schema, tab_mapping, tab_dre, tab_validation, tab_charts, tab_export = st.tabs(
        ["Schema", "De-para", "DRE", "Validações", "Gráficos", "Exportação"]
    )

    with tab_schema:
        st.markdown("#### Diagnóstico do schema encontrado")
        st.dataframe(schema_df, hide_index=True, use_container_width=True)
        st.markdown("#### Identificadores inferidos")
        st.dataframe(pd.DataFrame(_identifier_rows(id_matches)), hide_index=True, use_container_width=True)

    with tab_mapping:
        st.markdown("#### De-para e hipóteses de mapeamento")
        st.dataframe(mapping_df, hide_index=True, use_container_width=True)
        unmapped = mapping_result.get("unmapped_relevant")
        if isinstance(unmapped, pd.DataFrame) and not unmapped.empty:
            st.markdown("#### Colunas não mapeadas possivelmente relevantes")
            st.dataframe(unmapped, hide_index=True, use_container_width=True)
        else:
            st.caption("Nenhuma coluna não mapeada relevante foi detectada pelos heurísticos simples.")

    if not inst_col or not period_col:
        with tab_dre:
            st.error("Não foi possível identificar claramente colunas de instituição e período. Revise o de-para antes de montar a DRE.")
        with tab_validation:
            st.dataframe(global_validation, hide_index=True, use_container_width=True)
        return

    selected_row = _render_selection_controls(st, df, inst_col, period_col)
    if selected_row is None:
        return

    dre_df, validation_df, alerts_df = calculate_dre(selected_row, mapping_result, config)
    display_dre = _prepare_dre_display(dre_df)

    with tab_dre:
        st.markdown("#### DRE gerencial")
        _render_context_caption(st, selected_row, inst_col, period_col)
        _render_key_metrics(st, dre_df)
        negative_red = st.toggle("Destacar negativos em vermelho", value=True, key="dre_schema_negative_red")
        styled = display_dre.style
        if negative_red and "valor_r_mm" in display_dre.columns:
            styled = styled.map(_negative_red_style, subset=["valor_r_mm"])
        st.dataframe(styled, hide_index=True, use_container_width=True)
        with st.expander("Valores numéricos e auditoria completa", expanded=False):
            st.dataframe(dre_df, hide_index=True, use_container_width=True)

    with tab_validation:
        st.markdown("#### Validação da DRE selecionada")
        st.dataframe(validation_df, hide_index=True, use_container_width=True)
        st.markdown("#### Inconsistências e alertas")
        if alerts_df.empty:
            st.success("Nenhum alerta material na DRE selecionada.")
        else:
            st.dataframe(alerts_df, hide_index=True, use_container_width=True)
        st.markdown("#### Validação global amostral do mapeamento")
        st.dataframe(global_validation, hide_index=True, use_container_width=True)

    with tab_charts:
        _render_charts(st, df, mapping_result, config, selected_row, inst_col, period_col)

    with tab_export:
        st.markdown("#### Exportar")
        excel_bytes = export_to_excel(dre_df, validation_df, mapping_df, alerts_df, schema_df)
        inst_label = _safe_filename(str(selected_row.get(inst_col, "instituicao")))
        period_label = _safe_filename(str(selected_row.get(period_col, "periodo")))
        st.download_button(
            "Baixar DRE em Excel",
            data=excel_bytes,
            file_name=f"dre_gerencial_{inst_label}_{period_label}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="dre_schema_download_excel",
        )
        st.download_button(
            "Baixar DRE em CSV",
            data=dre_df.to_csv(index=False).encode("utf-8"),
            file_name=f"dre_gerencial_{inst_label}_{period_label}.csv",
            mime="text/csv",
            key="dre_schema_download_csv",
        )


def _load_parquets_for_ui(files_or_paths: Sequence[Any]) -> pd.DataFrame:
    local_paths = [Path(p) for p in files_or_paths if isinstance(p, (str, Path))]
    if len(local_paths) == len(files_or_paths):
        return _load_local_parquet_paths_cached(_local_cache_signature(local_paths))
    return load_parquet_files(files_or_paths)


def _local_cache_signature(paths: Sequence[Path]) -> tuple[tuple[str, float, int], ...]:
    signature = []
    for path in paths:
        stat = path.stat()
        signature.append((str(path), float(stat.st_mtime), int(stat.st_size)))
    return tuple(signature)


def _load_local_parquet_paths_cached(signature: tuple[tuple[str, float, int], ...]) -> pd.DataFrame:
    return load_parquet_files([item[0] for item in signature])


try:
    import streamlit as _st_for_cache

    _load_local_parquet_paths_cached = _st_for_cache.cache_data(ttl=900, show_spinner=False)(_load_local_parquet_paths_cached)
except Exception:
    pass


def _discover_local_parquet_options() -> list[Path]:
    preferred = [
        Path("data/cache/dre/dados.parquet"),
        Path("data/cache/dre_individual/dados.parquet"),
        Path("data/cache/principal/dados.parquet"),
        Path("data/cache/principal_individual/dados.parquet"),
    ]
    options = [p for p in preferred if p.exists()]
    for path in sorted(Path("data/cache").glob("*/dados.parquet")):
        if path not in options:
            options.append(path)
    return options


def _render_selection_controls(st, df: pd.DataFrame, inst_col: str, period_col: str) -> Optional[pd.Series]:
    st.markdown("#### Seleção da DRE")
    institutions = sorted(df[inst_col].dropna().astype(str).unique().tolist())
    if not institutions:
        st.error("A coluna inferida como instituição não possui valores.")
        return None
    default_idx = _default_institution_index(institutions)
    col_inst, col_period = st.columns([2, 1])
    with col_inst:
        institution = st.selectbox(
            "Instituição",
            institutions,
            index=default_idx,
            key="dre_schema_institution",
        )
    filtered_inst = df[df[inst_col].astype(str) == str(institution)].copy()
    periods = _sort_period_values(filtered_inst[period_col].dropna().unique().tolist())
    if not periods:
        st.error("Não há período para a instituição selecionada.")
        return None
    with col_period:
        period = st.selectbox(
            "Data / período",
            periods,
            index=len(periods) - 1,
            format_func=lambda value: str(value),
            key="dre_schema_period",
        )
    selected = filtered_inst[filtered_inst[period_col].astype(str) == str(period)].copy()
    if selected.empty:
        st.warning("Não há registro para a combinação selecionada.")
        return None
    if len(selected) > 1:
        st.warning("Há múltiplas linhas para a mesma instituição e período. Nenhuma agregação automática será feita.")
        selected = selected.copy()
        selected["_registro_ui"] = selected.apply(
            lambda r: f"{r.get('__arquivo_origem', 'arquivo')} | linha {r.get('__linha_origem', r.name)}",
            axis=1,
        )
        row_label = st.selectbox(
            "Registro específico",
            selected["_registro_ui"].tolist(),
            key="dre_schema_duplicate_row",
        )
        return selected[selected["_registro_ui"] == row_label].iloc[0]
    return selected.iloc[0]


def _render_context_caption(st, row: pd.Series, inst_col: str, period_col: str) -> None:
    source = row.get("__arquivo_origem", "")
    source_line = row.get("__linha_origem", "")
    st.caption(
        f"Instituição: {row.get(inst_col)} | Período: {row.get(period_col)} | "
        f"Origem: {source} linha {source_line}"
    )


def _render_key_metrics(st, dre_df: pd.DataFrame) -> None:
    lookup = {str(r["nome_canônico"]): r for _, r in dre_df.iterrows()}
    metrics = [
        ("Resultado intermediação", "intermediation_result"),
        ("Resultado antes tributos", "pretax_result"),
        ("Lucro líquido", "net_income"),
        ("Ativo total", "asset_total"),
    ]
    cols = st.columns(len(metrics))
    for col, (label, canonical) in zip(cols, metrics):
        row = lookup.get(canonical)
        value = row.get("valor_r_mil") if row is not None else None
        col.metric(label, format_currency(value, scale="mm"))


def _render_charts(st, df: pd.DataFrame, mapping_result: Mapping[str, Any], config: Mapping[str, Any], selected_row: pd.Series, inst_col: str, period_col: str) -> None:
    st.markdown("#### Composições da DRE selecionada")
    row_series = selected_row
    dre_df, _, _ = calculate_dre(row_series, mapping_result, config)
    canonical_lookup = {str(r["nome_canônico"]): r for _, r in dre_df.iterrows()}

    revenue_names = ["revenue_credit", "revenue_tvm", "revenue_interbank", "revenue_leasing", "revenue_other_credit", "derivatives_result", "other_intermediation_result"]
    expense_names = ["funding_expense", "expected_loss_total", "eligible_debt_expense"]
    col_rev, col_exp = st.columns(2)
    with col_rev:
        fig_rev = _bar_from_canonicals(canonical_lookup, revenue_names, "Receitas / resultados de intermediação")
        if fig_rev:
            st.plotly_chart(fig_rev, use_container_width=True)
        else:
            st.info("Sem componentes suficientes para composição da receita de intermediação.")
    with col_exp:
        fig_exp = _bar_from_canonicals(canonical_lookup, expense_names, "Despesas de intermediação")
        if fig_exp:
            st.plotly_chart(fig_exp, use_container_width=True)
        else:
            st.info("Sem componentes suficientes para composição das despesas de intermediação.")

    fig_waterfall = _waterfall_figure(canonical_lookup)
    if fig_waterfall:
        st.plotly_chart(fig_waterfall, use_container_width=True)

    st.markdown("#### Evolução temporal")
    institution = str(selected_row.get(inst_col))
    inst_df = df[df[inst_col].astype(str) == institution].copy()
    needed = ["net_income", "intermediation_result", "asset_total"]
    canon = canonicalize_dataframe(inst_df, mapping_result, config, canonical_names=needed)
    if "period" not in canon.columns or canon.empty:
        st.info("Sem série temporal para a instituição selecionada.")
    else:
        canon["_sort"] = canon["period"].map(lambda v: parse_period_metadata(v).get("sort_key", 0))
        canon = canon.sort_values("_sort")
        fig_ts = go.Figure()
        for col_name, label in [
            ("net_income", "Lucro líquido"),
            ("intermediation_result", "Resultado de intermediação"),
            ("asset_total", "Ativo total"),
        ]:
            if col_name in canon.columns and pd.to_numeric(canon[col_name], errors="coerce").notna().any():
                fig_ts.add_trace(
                    go.Scatter(
                        x=canon["period"].astype(str),
                        y=pd.to_numeric(canon[col_name], errors="coerce") / 1000.0,
                        mode="lines+markers",
                        name=label,
                    )
                )
        if fig_ts.data:
            fig_ts.update_layout(height=420, yaxis_title="R$ MM", margin=dict(l=10, r=10, t=35, b=10))
            st.plotly_chart(fig_ts, use_container_width=True)
        else:
            st.info("Sem valores suficientes para evolução temporal.")

    st.markdown("#### Comparação entre instituições")
    period_value = selected_row.get(period_col)
    period_df = df[df[period_col].astype(str) == str(period_value)].copy()
    institutions = sorted(period_df[inst_col].dropna().astype(str).unique().tolist())
    default_compare = [institution] if institution in institutions else institutions[:1]
    selected_compare = st.multiselect(
        "Instituições para comparação",
        institutions,
        default=default_compare,
        key="dre_schema_compare_institutions",
    )
    if selected_compare:
        compare_df = period_df[period_df[inst_col].astype(str).isin(selected_compare)].copy()
        canon_compare = canonicalize_dataframe(compare_df, mapping_result, config, canonical_names=["net_income", "intermediation_result", "asset_total"])
        if not canon_compare.empty and "institution" in canon_compare.columns:
            long = canon_compare.melt(
                id_vars=["institution"],
                value_vars=[c for c in ["net_income", "intermediation_result", "asset_total"] if c in canon_compare.columns],
                var_name="métrica",
                value_name="valor_r_mil",
            )
            label_map = {
                "net_income": "Lucro líquido",
                "intermediation_result": "Resultado intermediação",
                "asset_total": "Ativo total",
            }
            long["métrica"] = long["métrica"].map(label_map)
            long["valor_r_mm"] = pd.to_numeric(long["valor_r_mil"], errors="coerce") / 1000.0
            long = long.dropna(subset=["valor_r_mm"])
            if not long.empty:
                fig_cmp = go.Figure()
                for metric in long["métrica"].dropna().unique():
                    sub = long[long["métrica"] == metric]
                    fig_cmp.add_trace(go.Bar(x=sub["institution"], y=sub["valor_r_mm"], name=metric))
                fig_cmp.update_layout(barmode="group", height=420, yaxis_title="R$ MM", margin=dict(l=10, r=10, t=35, b=10))
                st.plotly_chart(fig_cmp, use_container_width=True)
            else:
                st.info("Sem valores para comparar no período selecionado.")


def _bar_from_canonicals(canonical_lookup: Mapping[str, Mapping[str, Any]], names: Sequence[str], title: str) -> Optional[go.Figure]:
    rows = []
    for name in names:
        row = canonical_lookup.get(name)
        if not row:
            continue
        value = row.get("valor_r_mil")
        if value is None or pd.isna(value):
            continue
        rows.append((str(row.get("rubrica") or name), float(value) / 1000.0))
    if not rows:
        return None
    fig = go.Figure(go.Bar(x=[r[0] for r in rows], y=[r[1] for r in rows], marker_color="#1f77b4"))
    fig.update_layout(title=title, height=380, yaxis_title="R$ MM", margin=dict(l=10, r=10, t=45, b=80))
    return fig


def _waterfall_figure(canonical_lookup: Mapping[str, Mapping[str, Any]]) -> Optional[go.Figure]:
    steps = [
        ("Intermediação", "intermediation_result"),
        ("Transações pgto", "payment_result"),
        ("Outras operacionais", "operating_other_result"),
        ("IR/CS", "income_tax_social_contribution"),
        ("Participações", "profit_participation"),
    ]
    x: list[str] = []
    y: list[float] = []
    measure: list[str] = []
    for label, canonical in steps:
        row = canonical_lookup.get(canonical)
        value = row.get("valor_r_mil") if row else None
        if value is None or pd.isna(value):
            continue
        x.append(label)
        y.append(float(value) / 1000.0)
        measure.append("relative")
    net = canonical_lookup.get("net_income")
    net_value = net.get("valor_r_mil") if net else None
    if net_value is None or pd.isna(net_value) or not x:
        return None
    x.append("Lucro líquido")
    y.append(float(net_value) / 1000.0)
    measure.append("total")
    fig = go.Figure(
        go.Waterfall(
            x=x,
            y=y,
            measure=measure,
            increasing={"marker": {"color": "#0f9d58"}},
            decreasing={"marker": {"color": "#d93025"}},
            totals={"marker": {"color": "#111111"}},
        )
    )
    fig.update_layout(title="Waterfall simplificado até lucro líquido", height=420, yaxis_title="R$ MM", margin=dict(l=10, r=10, t=45, b=30))
    return fig


def _prepare_dre_display(dre_df: pd.DataFrame) -> pd.DataFrame:
    out = dre_df.copy()
    out["valor_r_mm"] = pd.to_numeric(out["valor_r_mil"], errors="coerce") / 1000.0
    out["valor_formatado"] = out["valor_r_mil"].apply(lambda v: format_currency(v, scale="mm", parentheses=True))
    columns = [
        "grupo",
        "rubrica",
        "valor_formatado",
        "valor_r_mil",
        "valor_r_mm",
        "tipo_linha",
        "colunas_origem",
        "formula_usada",
        "status_validacao",
        "observações",
    ]
    return out[[c for c in columns if c in out.columns]]


def _negative_red_style(value: Any) -> str:
    try:
        return "color: #b00020;" if float(value) < 0 else ""
    except Exception:
        return ""


def _dre_row(
    *,
    group: str,
    rubric: str,
    canonical_name: str,
    value: Optional[float],
    line_type: str,
    source_columns: Sequence[str],
    formula: str,
    status: str,
    observations: str,
) -> dict[str, Any]:
    return {
        "grupo": group,
        "rubrica": rubric,
        "nome_canônico": canonical_name,
        "valor_r_mil": float(value) if value is not None and not pd.isna(value) else np.nan,
        "valor_r_mm": (float(value) / 1000.0) if value is not None and not pd.isna(value) else np.nan,
        "tipo_linha": line_type,
        "colunas_origem": ", ".join(source_columns),
        "formula_usada": formula,
        "status_validacao": status,
        "observações": observations,
    }


def _derive_from_identity(identity: Mapping[str, Any], resolved: Mapping[str, ResolvedValue]) -> Optional[tuple[float, list[str], list[str]]]:
    values: list[float] = []
    sources: list[str] = []
    missing: list[str] = []
    optional = set(str(c) for c in identity.get("optional_components", []))
    for component in identity.get("components", []):
        component_name = str(component)
        comp = resolved.get(component_name)
        if comp is None or comp.value is None:
            if component_name not in optional:
                missing.append(component_name)
            continue
        values.append(float(comp.value))
        sources.extend(list(comp.source_columns))
    if not values:
        return None
    return float(np.sum(values)), _unique_keep_order(sources), missing


def _build_alerts(dre_df: pd.DataFrame, validation_df: pd.DataFrame, mapping_result: Mapping[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for _, row in dre_df.iterrows():
        status = str(row.get("status_validacao") or "")
        if status and status != STATUS_OK:
            rows.append(
                {
                    "tipo": "linha_dre",
                    "item": row.get("rubrica"),
                    "status": status,
                    "observação": row.get("observações"),
                }
            )
    for _, row in validation_df.iterrows():
        status = str(row.get("status") or "")
        if status and status != STATUS_OK:
            rows.append(
                {
                    "tipo": "identidade",
                    "item": row.get("validação"),
                    "status": status,
                    "observação": row.get("observações"),
                }
            )
    unmapped = mapping_result.get("unmapped_relevant")
    if isinstance(unmapped, pd.DataFrame) and not unmapped.empty:
        rows.append(
            {
                "tipo": "schema",
                "item": "colunas não mapeadas",
                "status": STATUS_ATTENTION,
                "observação": f"{len(unmapped)} colunas parecem relevantes e ficaram fora do de-para.",
            }
        )
    return pd.DataFrame(rows)


def _evaluate_group(row: pd.Series, group: Mapping[str, Any], period_meta: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    columns = [c for c in group.get("columns", []) if c in row.index]
    values: list[float] = []
    used_columns: list[str] = []
    for col in columns:
        value = _coerce_float(row.get(col))
        if value is None:
            continue
        values.append(value)
        used_columns.append(col)
    if not values:
        return {
            "name": group.get("name", ""),
            "columns": columns,
            "used_columns": [],
            "has_value": False,
            "value": None,
            "status": STATUS_NOT_TESTABLE if columns else STATUS_NO_SOURCE,
            "period_valid": _period_valid(group.get("valid_for"), period_meta),
            "valid_for": group.get("valid_for"),
        }
    combine = str(group.get("combine") or "sum")
    status = STATUS_OK
    if combine == "coalesce":
        if len(values) == 1 or _all_close(values):
            value = float(values[0])
        else:
            value = None
            status = STATUS_AMBIGUOUS
    else:
        value = float(np.sum(values))
    return {
        "name": group.get("name", ""),
        "columns": columns,
        "used_columns": used_columns,
        "has_value": value is not None,
        "value": value,
        "status": status,
        "period_valid": _period_valid(group.get("valid_for"), period_meta),
        "valid_for": group.get("valid_for"),
    }


def _match_identifier(df: pd.DataFrame, item: Mapping[str, Any], norm_to_columns: Mapping[str, list[str]]) -> dict[str, Any]:
    aliases = [str(a) for a in item.get("aliases", [])]
    for alias in aliases:
        cols = norm_to_columns.get(_normalize_key(alias), [])
        if cols:
            return {"column": cols[0], "method": "alias", "confidence": "alta", "reason": alias}

    terms = [_normalize_key(t) for t in item.get("semantic_terms", []) if str(t).strip()]
    candidates = []
    for col in df.columns:
        key = _normalize_key(str(col))
        if any(term and term in key for term in terms):
            score = _identifier_score(df[col], item.get("canonical_name"))
            candidates.append((score, str(col)))
    if candidates:
        candidates.sort(reverse=True)
        return {"column": candidates[0][1], "method": "semântico", "confidence": "média", "reason": ", ".join(item.get("semantic_terms", []))}
    return {"column": None, "method": "", "confidence": "baixa", "reason": "não encontrado"}


def _match_source_group(
    columns: Sequence[str],
    source_group: Mapping[str, Any],
    entry: Mapping[str, Any],
    norm_to_columns: Mapping[str, list[str]],
) -> dict[str, Any]:
    matched: list[str] = []
    methods: list[str] = []
    for alias in source_group.get("aliases", []):
        cols = norm_to_columns.get(_normalize_key(str(alias)), [])
        for col in cols:
            if col not in matched:
                matched.append(col)
                methods.append("alias")

    if not matched:
        semantic_terms = [_normalize_key(t) for t in entry.get("semantic_terms", []) if str(t).strip()]
        for col in columns:
            key = _normalize_key(str(col))
            if semantic_terms and all(term in key for term in semantic_terms):
                matched.append(str(col))
                methods.append("semântico")

    if not matched and (entry.get("allow_letter_fallback") or source_group.get("allow_letter_fallback")):
        expected_letters = set(str(v).lower().strip() for v in entry.get("letters", []) if str(v).strip())
        if expected_letters:
            for col in columns:
                letters = set(_extract_column_letters(str(col)))
                if letters & expected_letters:
                    matched.append(str(col))
                    methods.append("letra")

    return {
        "name": str(source_group.get("name") or "fonte"),
        "columns": _unique_keep_order(matched),
        "combine": str(source_group.get("combine") or "sum"),
        "valid_for": source_group.get("valid_for"),
        "methods": tuple(_unique_keep_order(methods)),
    }


def _find_unmapped_relevant_columns(df: pd.DataFrame, used_columns: set[str]) -> pd.DataFrame:
    relevant_terms = [
        "resultado",
        "renda",
        "receita",
        "despesa",
        "lucro",
        "perda",
        "provisao",
        "tribut",
        "particip",
        "deriv",
        "capta",
        "credito",
    ]
    rows: list[dict[str, Any]] = []
    for col in df.columns:
        col_str = str(col)
        if col_str in used_columns or col_str.startswith("__"):
            continue
        key = _normalize_key(col_str)
        if not any(term in key for term in relevant_terms):
            continue
        numeric = pd.to_numeric(df[col], errors="coerce")
        coverage = float(numeric.notna().mean() * 100.0) if len(df) else 0.0
        if coverage <= 0:
            continue
        rows.append(
            {
                "coluna_original": col_str,
                "cobertura_numérica_%": coverage,
                "amostra": " | ".join(str(v)[:70] for v in df[col].dropna().head(3).tolist()),
                "motivo": "nome sugere rubrica financeira, mas não entrou no mapeamento",
            }
        )
    return pd.DataFrame(rows)


def _source_groups(entry: Mapping[str, Any]) -> list[dict[str, Any]]:
    groups = entry.get("source_groups")
    if isinstance(groups, list) and groups:
        return [dict(g) for g in groups if isinstance(g, Mapping)]
    return [
        {
            "name": "default",
            "combine": entry.get("combine", "sum"),
            "aliases": entry.get("aliases", []),
            "valid_for": entry.get("valid_for"),
        }
    ]


def _identity_canonical_names(identities: Sequence[Mapping[str, Any]]) -> list[str]:
    names: list[str] = []
    for identity in identities:
        target = str(identity.get("target") or "")
        if target:
            names.append(target)
        names.extend(str(c) for c in identity.get("components", []) if str(c))
    return _unique_keep_order(names)


def _identity_summary_row(identity: Mapping[str, Any], status: str, ok_rate: Optional[float], max_abs_diff: Optional[float], median_abs_diff: Optional[float], note: str) -> dict[str, Any]:
    return {
        "id": identity.get("id", ""),
        "validação": identity.get("label", ""),
        "target": identity.get("target", ""),
        "status": status,
        "fechamento_%": ok_rate * 100.0 if ok_rate is not None else np.nan,
        "diferença_abs_máxima": max_abs_diff if max_abs_diff is not None else np.nan,
        "diferença_abs_mediana": median_abs_diff if median_abs_diff is not None else np.nan,
        "formula": identity.get("formula_text", ""),
        "observações": note,
    }


def _entry_formula(entry: Mapping[str, Any], source_columns: Sequence[str]) -> str:
    if entry.get("formula"):
        return str(entry.get("formula"))
    if not source_columns:
        return ""
    return " + ".join(f"[{col}]" for col in source_columns)


def _sign_validation_note(value: float, expected_sign: str) -> str:
    if expected_sign in {"positive", "positive_or_zero"} and value < -ABS_TOLERANCE:
        return "sinal observado negativo, diferente do esperado; o valor não foi invertido"
    if expected_sign in {"negative", "negative_or_zero"} and value > ABS_TOLERANCE:
        return "sinal observado positivo, diferente do esperado; o valor não foi invertido"
    return ""


def _period_valid(valid_for: Any, period_meta: Optional[Mapping[str, Any]]) -> bool:
    if not valid_for:
        return True
    if not period_meta:
        return True
    year = period_meta.get("year")
    quarter = period_meta.get("quarter")
    if year is None:
        return True
    if "min_year" in valid_for and int(year) < int(valid_for["min_year"]):
        return False
    if "max_year" in valid_for and int(year) > int(valid_for["max_year"]):
        return False
    years = valid_for.get("years")
    if years and int(year) not in {int(y) for y in years}:
        return False
    quarters = valid_for.get("quarters")
    if quarters and quarter is not None and int(quarter) not in {int(q) for q in quarters}:
        return False
    return True


def parse_period_metadata(value: Any) -> dict[str, Any]:
    if value is None or pd.isna(value):
        return {"year": None, "quarter": None, "month": None, "sort_key": 0}
    if isinstance(value, pd.Timestamp):
        month = int(value.month)
        quarter = int(math.ceil(month / 3))
        year = int(value.year)
        return {"year": year, "quarter": quarter, "month": month, "sort_key": year * 100 + month}
    text = str(value).strip()
    dt = pd.to_datetime(text, errors="coerce", dayfirst=True)
    if pd.notna(dt) and not re.fullmatch(r"\d{1,2}/\d{4}", text):
        month = int(dt.month)
        quarter = int(math.ceil(month / 3))
        year = int(dt.year)
        return {"year": year, "quarter": quarter, "month": month, "sort_key": year * 100 + month}
    digits = re.sub(r"\D", "", text)
    if re.fullmatch(r"\d{6}", digits):
        year = int(digits[:4])
        month = int(digits[4:6])
        if 1 <= month <= 12:
            quarter = int(math.ceil(month / 3))
            return {"year": year, "quarter": quarter, "month": month, "sort_key": year * 100 + month}
    match = re.fullmatch(r"(\d{1,2})\s*[/.-]\s*(\d{4})", text)
    if match:
        part = int(match.group(1))
        year = int(match.group(2))
        if 1 <= part <= 4:
            month = part * 3
            return {"year": year, "quarter": part, "month": month, "sort_key": year * 100 + month}
        if 1 <= part <= 12:
            quarter = int(math.ceil(part / 3))
            return {"year": year, "quarter": quarter, "month": part, "sort_key": year * 100 + part}
    return {"year": None, "quarter": None, "month": None, "sort_key": 0}


def _sort_period_values(values: Sequence[Any]) -> list[Any]:
    return sorted(values, key=lambda value: (parse_period_metadata(value).get("sort_key", 0), str(value)))


def _coerce_float(value: Any) -> Optional[float]:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned == "":
            return None
        cleaned = cleaned.replace("R$", "").replace(" ", "")
        if "," in cleaned and "." in cleaned:
            cleaned = cleaned.replace(".", "").replace(",", ".")
        elif "," in cleaned:
            cleaned = cleaned.replace(",", ".")
        value = cleaned
    try:
        result = float(value)
    except Exception:
        return None
    if math.isnan(result):
        return None
    return result


def _identifier_score(series: pd.Series, canonical_name: str) -> float:
    non_null = series.dropna()
    if non_null.empty:
        return 0.0
    if canonical_name == "period":
        parsed = non_null.head(100).map(lambda v: parse_period_metadata(v).get("sort_key", 0))
        return float((parsed > 0).mean()) + float(non_null.nunique() > 1)
    if canonical_name == "institution":
        return float(non_null.astype(str).str.len().median()) / 100.0 + float(non_null.nunique() > 1)
    return float(non_null.nunique() > 1)


def _identifier_rows(id_matches: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for key, value in id_matches.items():
        rows.append(
            {
                "identificador": key,
                "coluna_origem": value.get("column"),
                "método": value.get("method"),
                "confiança": value.get("confidence"),
                "motivo": value.get("reason"),
            }
        )
    return rows


def _default_institution_index(institutions: Sequence[str]) -> int:
    preferred_terms = ["ITAU", "ITAÚ", "BANCO DO BRASIL", "BRADESCO", "SANTANDER"]
    upper_values = [str(v).upper() for v in institutions]
    for term in preferred_terms:
        for idx, value in enumerate(upper_values):
            if term in value:
                return idx
    return 0


def _normalize_key(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    return re.sub(r"[^a-z0-9]+", "", text)


def _extract_column_letters(value: str) -> list[str]:
    return [match.lower() for match in re.findall(r"\(([a-z]{1,3}\d*)\)", value, flags=re.IGNORECASE)]


def _unique_keep_order(values: Sequence[Any]) -> list[Any]:
    out: list[Any] = []
    seen: set[Any] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _all_close(values: Sequence[float]) -> bool:
    if not values:
        return True
    first = float(values[0])
    for value in values[1:]:
        scale = max(abs(first), abs(float(value)), 1.0)
        if abs(first - float(value)) > max(ABS_TOLERANCE, scale * REL_TOLERANCE):
            return False
    return True


def _combine_status(current: str, incoming: str) -> str:
    severity = {
        STATUS_OK: 0,
        STATUS_NOT_TESTABLE: 1,
        STATUS_NO_SOURCE: 1,
        STATUS_ATTENTION: 2,
        STATUS_AMBIGUOUS: 3,
        STATUS_ERROR: 4,
    }
    return incoming if severity.get(incoming, 0) > severity.get(current, 0) else current


def _append_note(existing: str, note: str) -> str:
    if not note:
        return existing or ""
    if not existing:
        return note
    return f"{existing}; {note}"


def _has_multiple_period_families_with_columns(group_matches: Sequence[Mapping[str, Any]]) -> bool:
    with_cols = [g for g in group_matches if g.get("columns")]
    valid_rules = [g.get("valid_for") for g in with_cols if g.get("valid_for")]
    return len(valid_rules) > 1


def _safe_filename(value: str) -> str:
    text = unicodedata.normalize("NFKD", value)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("_")
    return text[:80] or "arquivo"


def _fallback_mapping_config() -> dict[str, Any]:
    return {
        "version": "fallback",
        "identifiers": [
            {"canonical_name": "institution", "display_name": "Instituição", "aliases": ["Instituição", "Instituicao"]},
            {"canonical_name": "period", "display_name": "Período", "aliases": ["Período", "Periodo", "Data"]},
        ],
        "rubrics": [
            {
                "canonical_name": "net_income",
                "group": "LUCRO LÍQUIDO",
                "display_name": "Lucro líquido do período",
                "line_type": "direta",
                "rubric_type": "subtotal",
                "expected_sign": "mixed",
                "include_in_dre": True,
                "source_groups": [{"name": "fallback", "combine": "sum", "aliases": ["Lucro Líquido", "Lucro Líquido Acumulado YTD"]}],
            }
        ],
        "identities": [],
        "ambiguous_lines": [],
    }
