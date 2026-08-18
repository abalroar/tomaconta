"""Identidade reproduzível dos artefatos parquet consumidos pelo app."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .diagnostics import max_period_from_values, sha256_file


def inspect_parquet_artifact(
    path: Path,
    *,
    metadata_path: Path | None = None,
    period_column: str = "Período",
) -> dict[str, Any]:
    """Retorna identidade, cardinalidade, competência e schema sem abrir o parquet inteiro."""
    artifact_path = Path(path).resolve()
    result: dict[str, Any] = {
        "path": str(artifact_path),
        "exists": artifact_path.exists(),
        "sha256": None,
        "size_bytes": 0,
        "mtime_utc": None,
        "rows": 0,
        "columns": [],
        "max_period": None,
        "schema_version": None,
    }
    if not artifact_path.exists():
        return result

    stat = artifact_path.stat()
    result["sha256"] = sha256_file(artifact_path)
    result["size_bytes"] = int(stat.st_size)
    result["mtime_utc"] = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()

    import pyarrow.dataset as ds
    import pyarrow.parquet as pq

    parquet_file = pq.ParquetFile(artifact_path)
    result["rows"] = int(parquet_file.metadata.num_rows)
    result["columns"] = list(parquet_file.schema_arrow.names)
    if period_column in result["columns"]:
        periods = ds.dataset(artifact_path, format="parquet").to_table(columns=[period_column])
        values = periods.column(period_column).to_pylist()
        result["max_period"] = max_period_from_values(values)

    metadata_file = Path(metadata_path).resolve() if metadata_path else None
    if metadata_file and metadata_file.exists():
        try:
            metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
        except Exception:
            metadata = {}
        extra = metadata.get("extra") if isinstance(metadata, Mapping) else {}
        if isinstance(extra, Mapping):
            result["schema_version"] = extra.get("schema_version")
    return result


def build_bundle_id(artifacts: Mapping[str, Mapping[str, Any]]) -> str:
    """Cria identificador curto e estável a partir dos hashes dos artefatos."""
    payload = [
        (str(name), str(info.get("sha256") or "missing"))
        for name, info in sorted(artifacts.items())
    ]
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"bundle-{digest[:12]}"


def artifact_content_token(path: Path) -> str:
    """Token de cache derivado do conteúdo, sem depender de mtime."""
    artifact_path = Path(path)
    digest = sha256_file(artifact_path)
    if not digest:
        return "missing"
    return f"sha256:{digest}:{artifact_path.stat().st_size}"
