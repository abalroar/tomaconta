from types import SimpleNamespace

import pandas as pd
import pytest

import app1
from utils.ifdata_cache.critical_screens import resolve_core_funding_value


@pytest.mark.parametrize("code,bank,captacoes,instrumentos", [
    ("C0080099", "ITAU - PRUDENCIAL", 2096587810506.68, 40613001144.77),
    ("C0080075", "BRADESCO - PRUDENCIAL", 1506252150513.63, 54714526343.68),
    ("C0080185", "SANTANDER - PRUDENCIAL", 943495537547.93, 28318507475.77),
])
def test_passivo_slice_keeps_dec25_placeholder_and_excludes_other_perimeters(
    tmp_path, monkeypatch, code, bank, captacoes, instrumentos,
):
    path = tmp_path / "passivo.parquet"
    pd.DataFrame([
        {"CodInst": code, "Instituição": f"[IF {code}]", "Período": "4/2025",
         "Captações": captacoes, "Instrumentos": instrumentos},
        {"CodInst": "INDIVIDUAL", "Instituição": bank, "Período": "4/2025",
         "Captações": 999, "Instrumentos": 999},
        {"CodInst": code, "Instituição": bank, "Período": "3/2025",
         "Captações": 123, "Instrumentos": 123},
        {"CodInst": None, "Instituição": bank, "Período": "4/2024",
         "Captações": 456, "Instrumentos": None},
    ]).to_parquet(path, index=False)
    manager = SimpleNamespace(get_cache=lambda report: (
        SimpleNamespace(arquivo_dados=path) if report == "passivo" else None
    ))
    monkeypatch.setattr(app1, "get_cache_manager", lambda: manager)
    app1._carregar_cache_relatorio_slice.clear()
    displayed = app1._carregar_passivo_evolucao_slice(
        str(path), ("4/2024", "4/2025"), bank, (code,),
    )
    assert len(displayed) == 2
    assert set(displayed["Instituição"]) == {bank}
    assert displayed.loc[displayed["Período"].eq("4/2024"), "Captações"].item() == 456
    current = displayed[displayed["Período"].eq("4/2025")]
    resolved = resolve_core_funding_value(
        year_ref=2025, captacoes_value=current["Captações"].sum(min_count=1),
        instrumentos_value=current["Instrumentos"].sum(min_count=1),
    )
    assert resolved["value"] == pytest.approx(captacoes + instrumentos)
    assert resolved["source_kind"] == "official_components"
    app1._carregar_cache_relatorio_slice.clear()


def test_core_funding_keeps_missing_required_component_unavailable():
    resolved = resolve_core_funding_value(
        year_ref=2025, captacoes_value=2096587810506.68, instrumentos_value=float("nan"),
    )
    assert resolved["value"] is None
    assert resolved["source_kind"] == "missing_required_component"
