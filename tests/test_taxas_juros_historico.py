from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from utils.ifdata_cache.taxas_juros_historico import (
    TaxasJurosHistoricoCache,
    _build_odata_url,
    normalize_taxas_juros_historico_frame,
)


def test_build_odata_url_encodes_spaces_as_percent_20():
    url = _build_odata_url(
        "https://example.com/odata/ConsultaUnificada",
        {
            "$format": "json",
            "$filter": "InicioPeriodo eq '2026-03-23' and codigoSegmento eq '1'",
        },
    )

    assert "%20and%20" in url
    assert "InicioPeriodo%20eq%20'2026-03-23'" in url
    assert "+" not in url


def test_normalize_taxas_juros_historico_frame_builds_institution_key_with_fallback():
    raw_df = pd.DataFrame(
        [
            {
                "InicioPeriodo": "2026-03-23",
                "FimPeriodo": "2026-03-27",
                "codigoSegmento": "1",
                "Segmento": "Pessoa Física",
                "codigoModalidade": "402101",
                "Modalidade": "Cheque especial",
                "Posicao": 1,
                "InstituicaoFinanceira": "Banco A",
                "TaxaJurosAoMes": 7.5,
                "TaxaJurosAoAno": 138.0,
                "cnpj8": "12345678",
            },
            {
                "InicioPeriodo": "2026-03-23",
                "FimPeriodo": "2026-03-27",
                "codigoSegmento": "1",
                "Segmento": "Pessoa Física",
                "codigoModalidade": "402101",
                "Modalidade": "Cheque especial",
                "Posicao": 2,
                "InstituicaoFinanceira": "Banco do Brasil",
                "TaxaJurosAoMes": 6.9,
                "TaxaJurosAoAno": 122.0,
                "cnpj8": "00000000",
            },
        ]
    )

    normalized = normalize_taxas_juros_historico_frame(raw_df, run_id="run-1")

    assert list(normalized["institution_key"]) == [
        "cnpj8:12345678",
        "nome:Banco do Brasil",
    ]
    assert list(normalized["institution_key_quality"]) == ["cnpj8", "name_fallback"]
    assert str(normalized["taxa_juros_ao_mes"].dtype) == "float32"
    assert str(normalized["posicao"].dtype) == "Int16"


def test_materialize_history_runs_in_chunks_and_finalizes(monkeypatch, tmp_path):
    cache = TaxasJurosHistoricoCache(tmp_path)

    df_datas = pd.DataFrame(
        {
            "inicio_periodo": pd.to_datetime(["2026-01-05", "2026-01-12"]),
            "fim_periodo": pd.to_datetime(["2026-01-09", "2026-01-16"]),
            "tipo_modalidade": ["D", "D"],
            "ano_inicio": pd.Series([2026, 2026], dtype="Int16"),
        }
    )
    df_parametros = pd.DataFrame(
        {
            "tipo_modalidade": ["D"],
            "codigo_segmento": ["1"],
            "segmento": ["Pessoa Física"],
            "codigo_modalidade": ["402101"],
            "modalidade": ["Cheque especial"],
        }
    )

    raw_by_window = {
        "2026-01-05": pd.DataFrame(
            [
                {
                    "InicioPeriodo": "2026-01-05",
                    "FimPeriodo": "2026-01-09",
                    "codigoSegmento": "1",
                    "Segmento": "Pessoa Física",
                    "codigoModalidade": "402101",
                    "Modalidade": "Cheque especial",
                    "Posicao": 1,
                    "InstituicaoFinanceira": "Banco A",
                    "TaxaJurosAoMes": 7.5,
                    "TaxaJurosAoAno": 138.0,
                    "cnpj8": "12345678",
                }
            ]
        ),
        "2026-01-12": pd.DataFrame(
            [
                {
                    "InicioPeriodo": "2026-01-12",
                    "FimPeriodo": "2026-01-16",
                    "codigoSegmento": "1",
                    "Segmento": "Pessoa Física",
                    "codigoModalidade": "402101",
                    "Modalidade": "Cheque especial",
                    "Posicao": 1,
                    "InstituicaoFinanceira": "Banco A",
                    "TaxaJurosAoMes": 7.4,
                    "TaxaJurosAoAno": 136.0,
                    "cnpj8": "12345678",
                }
            ]
        ),
    }

    monkeypatch.setattr(
        "utils.ifdata_cache.taxas_juros_historico.fetch_taxas_juros_datas_disponiveis",
        lambda session=None: df_datas.copy(),
    )
    monkeypatch.setattr(
        "utils.ifdata_cache.taxas_juros_historico.fetch_taxas_juros_parametros_consulta",
        lambda tipo_modalidade="D", session=None: df_parametros.copy(),
    )
    monkeypatch.setattr(
        "utils.ifdata_cache.taxas_juros_historico.fetch_taxas_juros_historico_window",
        lambda inicio_periodo, session=None, timeout=120: raw_by_window[inicio_periodo].copy(),
    )

    resultado_chunk = cache.materialize_history(
        data_inicio="2026-01-01",
        data_fim="2026-01-31",
        max_windows_per_run=1,
        reprocess_tail_windows=0,
    )
    assert resultado_chunk.sucesso is True
    assert resultado_chunk.metadata["finalized"] is False
    assert resultado_chunk.metadata["remaining_windows"] == 1
    assert cache.arquivo_dados.exists() is False

    resultado_final = cache.materialize_history(
        data_inicio="2026-01-01",
        data_fim="2026-01-31",
        max_windows_per_run=1,
        reprocess_tail_windows=0,
    )
    assert resultado_final.sucesso is True
    assert resultado_final.metadata["finalized"] is True
    assert resultado_final.metadata["total_registros"] == 2
    assert cache.arquivo_dados.exists() is True
    assert cache.dimension_paths()["parametros"].exists() is True
    assert cache.dimension_paths()["datas"].exists() is True
    assert cache.dimension_paths()["instituicoes"].exists() is True
