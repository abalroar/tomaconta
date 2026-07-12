"""Diagnóstico operacional e gates de alinhamento dos caches."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

import pandas as pd

from .release_config import ReleaseConfig, get_release_config


PLACEHOLDER_IF_PATTERN = re.compile(r"^\[IF\s+[A-Za-z0-9]+\]$", re.IGNORECASE)

DEFAULT_GATE_SPECS = {
    "snapshot_peers": {
        "label": "Snapshot/Peers",
        "caches": ["critical_screens"],
        "periodicity": "quarterly",
    },
    "rankings": {
        "label": "Rankings",
        "caches": ["principal", "capital"],
        "periodicity": "quarterly",
    },
    "dre_consolidado": {
        "label": "DRE Conglomerado",
        "caches": ["dre", "principal", "derived_metrics"],
        "periodicity": "quarterly",
    },
    "dre_individual": {
        "label": "DRE Individual",
        "caches": ["dre_individual", "principal_individual", "derived_metrics_individual"],
        "periodicity": "quarterly",
    },
}


def period_sort_key(periodo: Any) -> tuple[int, int, str]:
    texto = str(periodo or "").strip()
    if not texto:
        return (-1, -1, "")

    if "/" in texto:
        esquerda, direita = (parte.strip() for parte in texto.split("/", 1))
        if esquerda.isdigit() and direita.isdigit():
            ano = int(direita)
            idx = int(esquerda)
            if 1 <= idx <= 4:
                return (ano, idx * 3, texto)
            return (ano, idx, texto)

    digitos = re.sub(r"\D", "", texto)
    if len(digitos) >= 6:
        return (int(digitos[:4]), int(digitos[4:6]), texto)

    match = re.search(r"(\d{2})(\d{4})$", texto)
    if match:
        mes, ano = match.groups()
        return (int(ano), int(mes), texto)

    return (0, 0, texto)


def normalize_period_reference(periodo: Any) -> str:
    texto = str(periodo or "").strip()
    if not texto:
        return ""
    ano, mes, _ = period_sort_key(texto)
    if ano <= 0 or mes <= 0:
        return texto
    return f"{ano}{mes:02d}"


def max_period_from_values(periodos: Sequence[Any] | None) -> str | None:
    if not periodos:
        return None
    valores = [str(periodo).strip() for periodo in periodos if str(periodo or "").strip()]
    if not valores:
        return None
    return max(valores, key=period_sort_key)


def load_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def max_period_from_metadata(metadata: Mapping[str, Any] | None) -> str | None:
    if not metadata:
        return None
    periodos = metadata.get("periodos")
    if isinstance(periodos, list):
        return max_period_from_values(periodos)
    extra = metadata.get("extra")
    if isinstance(extra, Mapping):
        for chave in ("periodos_materializados", "periodos_detectados"):
            valores = extra.get(chave)
            if isinstance(valores, list):
                return max_period_from_values(valores)
    return None


def sha256_file(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_placeholder_rows(
    df: pd.DataFrame | None,
    *,
    name_column: str = "Instituição",
    max_rows: int = 50,
) -> pd.DataFrame:
    if df is None or df.empty or name_column not in df.columns:
        return pd.DataFrame()
    mask = df[name_column].astype(str).str.match(PLACEHOLDER_IF_PATTERN, na=False)
    if not mask.any():
        return pd.DataFrame(columns=df.columns)
    return df.loc[mask].head(max_rows).copy()


def count_placeholder_names(
    df: pd.DataFrame | None,
    *,
    name_column: str = "Instituição",
) -> int:
    if df is None or df.empty or name_column not in df.columns:
        return 0
    return int(df[name_column].astype(str).str.match(PLACEHOLDER_IF_PATTERN, na=False).sum())


def collect_cache_diagnostics(
    manager,
    *,
    cache_names: Sequence[str] | None = None,
    release_config: ReleaseConfig | None = None,
    include_hashes: bool = False,
) -> dict[str, dict[str, Any]]:
    if manager is None:
        return {}

    release = release_config or get_release_config()
    cache_list = list(cache_names or manager.listar_caches())
    diagnostics: dict[str, dict[str, Any]] = {}

    for cache_name in cache_list:
        cache = manager.get_cache(cache_name)
        if cache is None:
            diagnostics[cache_name] = {
                "cache": cache_name,
                "exists": False,
                "message": "cache não configurado",
            }
            continue

        info = cache.get_info()
        metadata = load_json_file(cache.arquivo_metadata)
        max_period = max_period_from_metadata(metadata) or max_period_from_values(info.get("periodos") or [])
        diagnostics[cache_name] = {
            "cache": cache_name,
            "exists": bool(info.get("existe")),
            "source": metadata.get("fonte") or info.get("fonte") or "indisponível",
            "timestamp": metadata.get("timestamp_salvamento") or info.get("timestamp_salvamento"),
            "max_period": max_period,
            "max_period_ref": normalize_period_reference(max_period),
            "period_count": metadata.get("total_periodos") or info.get("total_periodos") or 0,
            "record_count": metadata.get("total_registros") or info.get("total_registros") or 0,
            "path": str(cache.arquivo_dados if cache.arquivo_dados.exists() else cache.arquivo_dados_pickle),
            "metadata_path": str(cache.arquivo_metadata),
            "sha256": (
                sha256_file(cache.arquivo_dados if cache.arquivo_dados.exists() else cache.arquivo_dados_pickle)
                if include_hashes
                else None
            ),
            "release_repo": release.repo,
            "release_tag": release.tag,
            "release_base_url": release.release_base_url,
        }
    return diagnostics


def evaluate_alignment_gates(
    cache_records: Mapping[str, Mapping[str, Any]],
    *,
    gate_specs: Mapping[str, Mapping[str, Any]] | None = None,
    expected_periods: Mapping[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    specs = gate_specs or DEFAULT_GATE_SPECS
    expected = dict(expected_periods or {})
    output: dict[str, dict[str, Any]] = {}

    for gate_key, spec in specs.items():
        caches = list(spec.get("caches") or [])
        gate_records = {
            cache_name: dict(cache_records.get(cache_name) or {})
            for cache_name in caches
        }
        missing = [nome for nome, record in gate_records.items() if not record.get("exists")]
        actual_refs = {
            nome: record.get("max_period_ref") or ""
            for nome, record in gate_records.items()
        }
        actual_values = {
            valor
            for valor in actual_refs.values()
            if valor
        }
        expected_raw = expected.get(gate_key) or expected.get(spec.get("periodicity", ""))
        expected_ref = normalize_period_reference(expected_raw) if expected_raw else ""

        success = not missing and len(actual_values) == 1
        if expected_ref:
            success = success and actual_values == {expected_ref}

        if missing:
            message = f"caches ausentes: {', '.join(missing)}"
        elif not actual_values:
            message = "período máximo indisponível nas metadata locais"
        elif len(actual_values) > 1:
            message = "desalinhado: períodos máximos diferentes entre caches"
        elif expected_ref and actual_values != {expected_ref}:
            atual = next(iter(actual_values))
            message = f"esperado {expected_ref}, encontrado {atual}"
        else:
            atual = next(iter(actual_values), "")
            message = f"alinhado em {atual}" if atual else "alinhado"

        output[gate_key] = {
            "label": spec.get("label", gate_key),
            "success": success,
            "expected_period": expected_raw or None,
            "expected_period_ref": expected_ref or None,
            "message": message,
            "caches": gate_records,
        }
    return output


def build_runtime_manifest(
    manager,
    *,
    cache_names: Sequence[str] | None = None,
    release_config: ReleaseConfig | None = None,
    expected_periods: Mapping[str, str] | None = None,
    include_hashes: bool = False,
) -> dict[str, Any]:
    release = release_config or get_release_config()
    cache_records = collect_cache_diagnostics(
        manager,
        cache_names=cache_names,
        release_config=release,
        include_hashes=include_hashes,
    )
    gates = evaluate_alignment_gates(cache_records, expected_periods=expected_periods)
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "release": release.to_dict(),
        "caches": cache_records,
        "gates": gates,
        "summary": {
            "total_caches": len(cache_records),
            "present_caches": sum(1 for record in cache_records.values() if record.get("exists")),
            "successful_gates": sum(1 for gate in gates.values() if gate.get("success")),
            "total_gates": len(gates),
        },
    }
