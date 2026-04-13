from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from utils.ifdata_cache.taxas_juros import (
    fetch_taxas_juros_for_institutions,
    fetch_taxas_juros_scoped,
    reduce_taxas_juros_to_monthly_snapshot,
)


class _FakeResponse:
    def __init__(self, payload, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def json(self):
        return self._payload


def test_fetch_taxas_juros_scoped_applies_server_filters_and_renames(monkeypatch):
    calls = []
    responses = [
        _FakeResponse(
            {
                "value": [
                    {
                        "InicioPeriodo": "2026-03-23",
                        "FimPeriodo": "2026-03-27",
                        "Segmento": "PESSOA FÍSICA",
                        "Modalidade": "Aquisição de veículos - Prefixado",
                        "Posicao": 1,
                        "InstituicaoFinanceira": "Banco A",
                        "TaxaJurosAoMes": 1.23,
                        "TaxaJurosAoAno": 15.8,
                    },
                    {
                        "InicioPeriodo": "2026-03-23",
                        "FimPeriodo": "2026-03-27",
                        "Segmento": "PESSOA FÍSICA",
                        "Modalidade": "Aquisição de veículos - Prefixado",
                        "Posicao": 2,
                        "InstituicaoFinanceira": "Banco B",
                        "TaxaJurosAoMes": 1.35,
                        "TaxaJurosAoAno": 17.4,
                    },
                ]
            }
        ),
        _FakeResponse(
            {
                "value": [
                    {
                        "InicioPeriodo": "2026-03-17",
                        "FimPeriodo": "2026-03-21",
                        "Segmento": "PESSOA FÍSICA",
                        "Modalidade": "Aquisição de veículos - Prefixado",
                        "Posicao": 1,
                        "InstituicaoFinanceira": "Banco A",
                        "TaxaJurosAoMes": 1.21,
                        "TaxaJurosAoAno": 15.5,
                    }
                ]
            }
        ),
    ]

    def fake_get(url, timeout=None):
        calls.append({"url": url, "timeout": timeout})
        return responses[len(calls) - 1]

    monkeypatch.setattr("utils.ifdata_cache.taxas_juros.requests.get", fake_get)

    df, meta = fetch_taxas_juros_scoped(
        data_inicio="2026-03-01",
        data_fim="2026-03-31",
        segmento="PESSOA FÍSICA",
        modalidade="Aquisição de veículos - Prefixado",
        select_fields=["InicioPeriodo", "FimPeriodo", "Segmento", "Modalidade", "Posicao", "InstituicaoFinanceira", "TaxaJurosAoMes", "TaxaJurosAoAno"],
        page_size=2,
        max_pages=3,
        timeout=11,
    )

    assert len(calls) == 2
    assert "dataInicioPeriodo='2026-03-01'" in calls[0]["url"]
    assert "$top=2" in calls[0]["url"]
    assert "$skip=0" in calls[0]["url"]
    assert "Segmento%20eq%20'PESSOA%20F%C3%8DSICA'" in calls[0]["url"]
    assert "Modalidade%20eq%20'Aquisi%C3%A7%C3%A3o%20de%20ve%C3%ADculos%20-%20Prefixado'" in calls[0]["url"]
    assert "%20and%20" in calls[0]["url"]
    assert "+" not in calls[0]["url"]
    assert "$skip=2" in calls[1]["url"]

    assert list(df.columns) == [
        "Início Período",
        "Fim Período",
        "Segmento",
        "Produto",
        "Posição",
        "Instituição Financeira",
        "Taxa Mensal (%)",
        "Taxa Anual (%)",
    ]
    assert len(df) == 3
    assert str(df["Taxa Mensal (%)"].dtype) == "float32"
    assert str(df["Posição"].dtype) == "Int16"
    assert meta["rows_fetched"] == 3
    assert meta["pages_loaded"] == 2
    assert meta["hit_page_limit"] is False


def test_reduce_taxas_juros_to_monthly_snapshot_keeps_latest_point_per_bank():
    df = pd.DataFrame(
        {
            "Segmento": ["PESSOA FÍSICA"] * 4,
            "Produto": ["Cheque especial"] * 4,
            "Instituição Financeira": ["Banco A", "Banco A", "Banco A", "Banco B"],
            "Fim Período": pd.to_datetime(["2026-01-10", "2026-01-28", "2026-02-18", "2026-01-27"]),
            "Taxa Mensal (%)": [7.0, 6.8, 6.6, 8.1],
        }
    )

    reduced = reduce_taxas_juros_to_monthly_snapshot(df)

    assert len(reduced) == 3
    jan_banco_a = reduced[
        (reduced["Instituição Financeira"] == "Banco A")
        & (reduced["AnoMes"].astype(str) == "2026-01")
    ]
    assert len(jan_banco_a) == 1
    assert jan_banco_a.iloc[0]["Fim Período"] == pd.Timestamp("2026-01-28")


def test_fetch_taxas_juros_for_institutions_aggregates_small_scoped_calls(monkeypatch):
    calls = []

    def fake_scoped(**kwargs):
        calls.append(kwargs)
        banco = kwargs["instituicao"]
        frame = pd.DataFrame(
            {
                "Instituição Financeira": [banco],
                "Fim Período": pd.to_datetime(["2026-03-27"]),
                "Taxa Mensal (%)": [1.11 if banco == "Banco A" else 2.22],
            }
        )
        return frame, {
            "rows_fetched": 1,
            "rows_returned": 1,
            "pages_loaded": 1,
            "hit_page_limit": banco == "Banco B",
            "error": "",
        }

    monkeypatch.setattr("utils.ifdata_cache.taxas_juros.fetch_taxas_juros_scoped", fake_scoped)

    df, meta = fetch_taxas_juros_for_institutions(
        instituicoes=["Banco A", "Banco B"],
        data_inicio="2026-03-01",
        data_fim="2026-03-31",
        segmento="PESSOA FÍSICA",
        modalidade="Cheque especial - Prefixado",
        page_size=100,
        max_pages_per_institution=2,
        timeout=10,
    )

    assert len(calls) == 2
    assert calls[0]["instituicao"] == "Banco A"
    assert calls[1]["instituicao"] == "Banco B"
    assert len(df) == 2
    assert meta["rows_fetched"] == 2
    assert meta["rows_returned"] == 2
    assert meta["pages_loaded"] == 2
    assert meta["hit_page_limit"] is True
