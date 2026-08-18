from pathlib import Path

import pandas as pd

from utils.ifdata_cache.artifact_identity import build_bundle_id, inspect_parquet_artifact


def test_inspect_parquet_artifact_reports_hash_rows_period_and_schema(tmp_path: Path):
    parquet = tmp_path / "dados.parquet"
    metadata = tmp_path / "metadata.json"
    pd.DataFrame(
        {
            "Instituição": ["A", "B"],
            "Período": ["4/2025", "1/2026"],
            "Valor": [1.0, 2.0],
        }
    ).to_parquet(parquet, index=False)
    metadata.write_text('{"extra":{"schema_version":5}}', encoding="utf-8")

    identity = inspect_parquet_artifact(parquet, metadata_path=metadata)

    assert identity["exists"] is True
    assert len(identity["sha256"]) == 64
    assert identity["rows"] == 2
    assert identity["max_period"] == "1/2026"
    assert identity["schema_version"] == 5


def test_build_bundle_id_is_stable_and_changes_with_content_hash():
    first = build_bundle_id({"a": {"sha256": "1"}, "b": {"sha256": "2"}})
    reordered = build_bundle_id({"b": {"sha256": "2"}, "a": {"sha256": "1"}})
    changed = build_bundle_id({"a": {"sha256": "1"}, "b": {"sha256": "3"}})

    assert first == reordered
    assert first.startswith("bundle-")
    assert first != changed
