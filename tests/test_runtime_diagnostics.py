import json
from types import SimpleNamespace

import pandas as pd
import pytest

from utils.ifdata_cache.diagnostics import (
    build_runtime_manifest,
    collect_cache_diagnostics,
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


@pytest.mark.parametrize("reference", [None, "", "202613", "000003", "inválido", "202601"])
def test_gate_requires_valid_competence_for_every_existing_member(reference):
    records = {
        "principal": {"exists": True, "max_period_ref": "202603"},
        "capital": {"exists": True, "max_period_ref": reference},
    }
    gate = evaluate_alignment_gates(records, gate_specs={
        "test": {"caches": ["principal", "capital"], "periodicity": "quarterly"},
    })["test"]
    assert not gate["success"]
    assert "capital" in gate["message"]


def test_gate_rejects_invalid_expected_competence():
    gate = evaluate_alignment_gates(
        {"principal": {"exists": True, "max_period_ref": "202603"}},
        gate_specs={"test": {"caches": ["principal"], "periodicity": "quarterly"}},
        expected_periods={"test": "202613"},
    )["test"]
    assert not gate["success"]
    assert "esperada inválida" in gate["message"]


def test_monthly_gate_accepts_real_month_outside_quarter_end():
    gate = evaluate_alignment_gates(
        {"bloprudencial": {"exists": True, "max_period_ref": "202601"}},
        gate_specs={"test": {"caches": ["bloprudencial"], "periodicity": "monthly"}},
    )["test"]
    assert gate["success"]


def test_diagnostics_uses_source_specific_release_destination(tmp_path):
    global_release = SimpleNamespace(repo="owner/global", tag="v2.0-cache")
    scr = _FakeCache(tmp_path, "scr_data", {"periodos": ["202607"]})
    scr.release_repo = "owner/scr"
    scr.release_tag = "v1.1-cache"
    principal = _FakeCache(tmp_path, "principal", {"periodos": ["1/2026"]})
    diagnostics = collect_cache_diagnostics(
        _FakeManager({"scr_data": scr, "principal": principal}), release_config=global_release,
    )
    assert diagnostics["scr_data"]["release_repo"] == "owner/scr"
    assert diagnostics["scr_data"]["release_tag"] == "v1.1-cache"
    assert diagnostics["scr_data"]["release_base_url"] == "https://github.com/owner/scr/releases/download/v1.1-cache"
    assert diagnostics["principal"]["release_repo"] == "owner/global"
    assert diagnostics["principal"]["release_tag"] == "v2.0-cache"
