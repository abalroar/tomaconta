from __future__ import annotations

import pandas as pd
import pytest

from utils.ifdata_cache import extractor


def _patch_relatorio_16_sources(monkeypatch, raw_values: pd.DataFrame) -> None:
    monkeypatch.setattr(
        extractor,
        "extrair_cadastro",
        lambda periodo: pd.DataFrame(
            {
                "CodInst": ["C0080099"],
                "NomeInstituicao": ["ITAU - PRUDENCIAL"],
            }
        ),
    )
    monkeypatch.setattr(
        extractor,
        "extrair_valores",
        lambda periodo, relatorio, tipo_instituicao=1: raw_values.copy(),
    )
    monkeypatch.setattr(
        extractor,
        "_resolver_nomes_instituicoes",
        lambda frame, periodo: frame,
    )


def test_relatorio_16_exact_api_duplicates_are_not_summed(monkeypatch):
    unique_rows = pd.DataFrame(
        [
            {
                "CodInst": "C0080099",
                "Conta": "148834",
                "NomeColuna": "Inadimplência",
                "DescricaoColuna": "Carteira ativa inadimplida arrastada",
                "Saldo": 24_704_763_570.85,
            },
            {
                "CodInst": "C0080099",
                "Conta": "148840",
                "NomeColuna": "Total Geral",
                "DescricaoColuna": "Total da carteira",
                "Saldo": 1_131_308_055_305.44,
            },
        ]
    )
    raw_values = pd.concat([unique_rows, unique_rows, unique_rows], ignore_index=True)
    _patch_relatorio_16_sources(monkeypatch, raw_values)

    result = extractor.extrair_relatorio_completo("202509", 16)

    assert result is not None
    assert len(result) == 1
    assert result.iloc[0]["Inadimplência"] == pytest.approx(24_704_763_570.85)
    assert result.iloc[0]["Total Geral"] == pytest.approx(1_131_308_055_305.44)


def test_relatorio_16_conflicting_duplicate_key_aborts_extraction(monkeypatch):
    raw_values = pd.DataFrame(
        [
            {
                "CodInst": "C0080099",
                "Conta": "148834",
                "NomeColuna": "Inadimplência",
                "DescricaoColuna": "Carteira ativa inadimplida arrastada",
                "Saldo": 100.0,
            },
            {
                "CodInst": "C0080099",
                "Conta": "148834",
                "NomeColuna": "Inadimplência",
                "DescricaoColuna": "Carteira ativa inadimplida arrastada",
                "Saldo": 101.0,
            },
        ]
    )
    _patch_relatorio_16_sources(monkeypatch, raw_values)

    with pytest.raises(ValueError, match="duplicatas conflitantes.*C0080099/Inadimplência"):
        extractor.extrair_relatorio_completo("202509", 16)
