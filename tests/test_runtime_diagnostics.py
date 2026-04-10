import json

import pandas as pd

from utils.ifdata_cache.diagnostics import (
    build_runtime_manifest,
    count_placeholder_names,
    evaluate_alignment_gates,
    find_placeholder_rows,
    normalize_period_reference,
)


class _FakeCache:
    def __init__(self, tmp_path, name, metadata):
        self.arquivo_dados = tmp_path / f"{name}.parquet"
        self.arquivo_dados.write_bytes(b"fake-parquet")
        self.arquivo_dados_pickle = tmp_path / f"{name}.pkl"
        self.arquivo_metadata = tmp_path / f"{name}.json"
        self.arquivo_metadata.write_text(json.dumps(metadata), encoding="utf-8")
        self._info = {
            "nome": name,
            "existe": True,
            "fonte": metadata.get("fonte"),
            "timestamp_salvamento": metadata.get("timestamp_salvamento"),
            "total_periodos": metadata.get("total_periodos"),
            "periodos": metadata.get("periodos"),
            "total_registros": metadata.get("total_registros"),
        }

    def get_info(self):
        return dict(self._info)


class _FakeManager:
    def __init__(self, caches):
        self._caches = caches

    def listar_caches(self):
        return list(self._caches.keys())

    def get_cache(self, name):
        return self._caches.get(name)


def test_evaluate_alignment_gates_detects_desalinhamento():
    records = {
        "principal": {"exists": True, "max_period_ref": "202512"},
        "capital": {"exists": True, "max_period_ref": "202509"},
    }
    gates = evaluate_alignment_gates(
        records,
        gate_specs={
            "rankings": {
                "label": "Rankings",
                "caches": ["principal", "capital"],
                "periodicity": "quarterly",
            }
        },
        expected_periods={"quarterly": "202512"},
    )

    assert not gates["rankings"]["success"]
    assert "desalinhado" in gates["rankings"]["message"]


def test_build_runtime_manifest_reads_metadata_and_gate(tmp_path):
    metadata = {
        "fonte": "github_releases",
        "timestamp_salvamento": "2026-04-10T12:00:00",
        "periodos": ["3/2025", "4/2025"],
        "total_periodos": 2,
        "total_registros": 10,
    }
    manager = _FakeManager(
        {
            "critical_screens": _FakeCache(tmp_path, "critical_screens", metadata),
        }
    )

    manifest = build_runtime_manifest(
        manager,
        cache_names=["critical_screens"],
        expected_periods={"snapshot_peers": "202512"},
    )

    record = manifest["caches"]["critical_screens"]
    assert record["max_period"] == "4/2025"
    assert record["max_period_ref"] == "202512"
    assert manifest["gates"]["snapshot_peers"]["success"]


def test_placeholder_helpers_identify_remaining_placeholders():
    df = pd.DataFrame(
        {
            "Instituição": ["Banco A", "[IF 1234]", "[IF C999]"],
            "Valor": [1, 2, 3],
        }
    )

    assert normalize_period_reference("4/2025") == "202512"
    assert count_placeholder_names(df) == 2
    placeholders = find_placeholder_rows(df)
    assert placeholders["Instituição"].tolist() == ["[IF 1234]", "[IF C999]"]
