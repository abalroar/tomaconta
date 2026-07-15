from types import SimpleNamespace

import pandas as pd
import pytest

from utils.ifdata_cache.carteira_4966_quality import (
    CARTEIRA_4966_REQUIRED_PERIODS,
    validate_carteira_4966_quality,
)
from utils.ifdata_cache.release_ops import (
    get_publishable_bundle,
    validate_cache_quality,
)


PERIOD_LABELS = {
    "202503": "1/2025",
    "202506": "2/2025",
    "202509": "3/2025",
    "202512": "4/2025",
    "202603": "1/2026",
}


def _quality_frame(*, rows_per_period: int = 20) -> pd.DataFrame:
    rows = []
    for period in CARTEIRA_4966_REQUIRED_PERIODS:
        for institution in range(rows_per_period):
            rows.append(
                {
                    "CodInst": f"{institution:08d}",
                    "Instituição": f"Banco {institution}",
                    "Período": PERIOD_LABELS[period],
                    "C1": 10_000_000.0,
                    "C2": 10_000_000.0,
                    "C3": 10_000_000.0,
                    "C4": 10_000_000.0,
                    "C5": 40_000_000.0,
                    "Carteira não Informada ou não se Aplica": 5_000_000.0,
                    "Total Exterior": 10_000_000.0,
                    "Total não Individualizado": 5_000_000.0,
                    "Total Geral": 100_000_000.0,
                    "Inadimplência": 10_000_000.0,
                    "Ativos problemáticos": 20_000_000.0,
                }
            )
    return pd.DataFrame(rows)


class _QualityCache:
    def __init__(self, frame: pd.DataFrame):
        self.frame = frame

    def carregar_local(self):
        return SimpleNamespace(
            sucesso=True,
            dados=self.frame,
            mensagem="ok",
            fonte="cache_local",
        )


class _QualityManager:
    def __init__(self, frame: pd.DataFrame):
        self.cache = _QualityCache(frame)

    def get_cache(self, cache_name: str):
        return self.cache if cache_name == "carteira_instrumentos" else None


def test_complete_asset_passes_prepublication_gate():
    result = validate_carteira_4966_quality(_quality_frame())

    assert result["success"] is True
    assert result["message"] == "ok"
    assert result["missing_periods"] == []
    assert result["duplicate_identity_count"] == 0
    assert result["structural_anomaly_count"] == 0
    assert all(value == pytest.approx(1.0) for value in result["coverage"].values())
    assert all(
        details["coverage"]["Inadimplência"] == pytest.approx(1.0)
        for details in result["coverage_by_period"].values()
    )


def test_zero_percent_historical_backfill_is_rejected():
    frame = _quality_frame()
    historical = frame["Período"].isin(["1/2025", "2/2025", "3/2025"])
    frame.loc[historical, ["Inadimplência", "Ativos problemáticos"]] = None

    result = validate_carteira_4966_quality(frame)

    assert result["success"] is False
    assert result["coverage_by_period"]["202503"]["coverage"]["Inadimplência"] == 0.0
    assert result["coverage"]["Inadimplência"] == pytest.approx(0.40)
    assert "202503 Inadimplência: cobertura 0.0%" in result["message"]
    assert "Ativos problemáticos" in result["message"]


def test_residual_five_percent_absence_is_allowed():
    frame = _quality_frame(rows_per_period=20)
    for period_label in PERIOD_LABELS.values():
        row_index = frame.index[frame["Período"].eq(period_label)][0]
        frame.loc[row_index, ["Inadimplência", "Ativos problemáticos"]] = None

    result = validate_carteira_4966_quality(frame)

    assert result["success"] is True
    assert result["coverage"]["Inadimplência"] == pytest.approx(0.95)
    assert result["coverage"]["Ativos problemáticos"] == pytest.approx(0.95)
    assert all(
        details["coverage"]["Inadimplência"] == pytest.approx(0.95)
        for details in result["coverage_by_period"].values()
    )


def test_materially_incomplete_total_coverage_is_rejected():
    frame = _quality_frame(rows_per_period=100)
    for period_label in PERIOD_LABELS.values():
        period_indexes = frame.index[frame["Período"].eq(period_label)]
        frame.loc[
            period_indexes[1:],
            [
                "C1",
                "C2",
                "C3",
                "C4",
                "C5",
                "Carteira não Informada ou não se Aplica",
                "Total Exterior",
                "Total não Individualizado",
                "Total Geral",
                "Inadimplência",
                "Ativos problemáticos",
            ],
        ] = None

    result = validate_carteira_4966_quality(frame)

    assert result["success"] is False
    assert result["coverage_by_period"]["202503"]["reporting_population_coverage"] == pytest.approx(0.01)
    assert "202503 população reportante: cobertura 1.0%; mínimo 75%" in result["message"]


def test_total_is_required_within_reporting_population():
    frame = _quality_frame()
    for period_label in PERIOD_LABELS.values():
        period_indexes = frame.index[frame["Período"].eq(period_label)]
        frame.loc[period_indexes[:3], "Total Geral"] = None

    result = validate_carteira_4966_quality(frame)

    assert result["success"] is False
    assert result["coverage_by_period"]["202503"]["coverage"]["Total Geral"] == pytest.approx(0.85)
    assert "202503 Total Geral: cobertura 85.0%; mínimo 90%" in result["message"]


def test_missing_classification_component_is_rejected():
    frame = _quality_frame()
    frame["C1"] = None

    result = validate_carteira_4966_quality(frame)

    assert result["success"] is False
    assert result["coverage_by_period"]["202503"]["coverage"]["C1"] == 0.0
    assert "202503 C1: cobertura 0.0%; mínimo 50%" in result["message"]


def test_old_asset_missing_latest_required_period_is_rejected():
    frame = _quality_frame()
    frame = frame[frame["Período"].ne("1/2026")].copy()

    result = validate_carteira_4966_quality(frame)

    assert result["success"] is False
    assert result["missing_periods"] == ["202603"]
    assert "períodos obrigatórios ausentes: 202603" in result["message"]


def test_duplicate_identity_is_rejected_and_domain_outliers_are_warnings():
    duplicate = _quality_frame()
    duplicate = pd.concat([duplicate, duplicate.iloc[[0]]], ignore_index=True)
    duplicate_result = validate_carteira_4966_quality(duplicate)

    assert duplicate_result["success"] is False
    assert duplicate_result["duplicate_identity_count"] == 1
    assert "CodInst/Período duplicada" in duplicate_result["message"]

    anomalous = _quality_frame()
    anomalous.loc[anomalous.index[0], "Inadimplência"] = 150_000_000.0
    anomalous.loc[anomalous.index[1], "Ativos problemáticos"] = -1.0
    anomaly_result = validate_carteira_4966_quality(anomalous)

    assert anomaly_result["success"] is True
    assert anomaly_result["exceeds_total_count"]["Inadimplência"] == 1
    assert anomaly_result["negative_metric_count"]["Ativos problemáticos"] == 1
    assert anomaly_result["structural_anomaly_count"] == 0
    assert anomaly_result["warning_anomaly_count"] == 2
    assert any("acima do Total Geral" in warning for warning in anomaly_result["warnings"])
    assert any("negativo" in warning for warning in anomaly_result["warnings"])


def test_release_quality_integration_blocks_incomplete_asset():
    incomplete = _quality_frame()
    incomplete.loc[
        incomplete["Período"].isin(["1/2025", "2/2025", "3/2025"]),
        ["Inadimplência", "Ativos problemáticos"],
    ] = None
    manager = _QualityManager(incomplete)

    checks = validate_cache_quality(manager, ["carteira_instrumentos"])
    publishable, warnings = get_publishable_bundle(
        ["carteira_instrumentos"],
        manifest_payload={"quality_checks": checks},
    )

    assert checks["carteira_instrumentos"]["success"] is False
    assert publishable == []
    assert any("carteira_instrumentos" in warning for warning in warnings)


def test_release_quality_integration_accepts_complete_asset():
    manager = _QualityManager(_quality_frame())

    checks = validate_cache_quality(manager, ["carteira_instrumentos"])

    assert checks["carteira_instrumentos"]["success"] is True
