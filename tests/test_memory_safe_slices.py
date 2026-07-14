from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from utils.ifdata_cache.bloprudencial_cache import load_bloprudencial_parquet_slice
from utils.ifdata_cache.diagnostics import load_institution_pairs_for_diagnostic
from utils.ifdata_cache.taxas_juros_historico import load_taxas_juros_historico_slice
from utils.ifdata_cache.taxas_juros_historico import load_taxas_juros_historico_monthly_slice


def test_diagnostic_pairs_are_projected_deduplicated_across_batches(tmp_path):
    parquet_path = tmp_path / "diagnostico.parquet"
    pd.DataFrame(
        {
            "codinst ": [1, 2, 1, 3, 2],
            "Instituicao": ["Banco A", "Banco B", "Banco A", "[IF 3]", "Banco B"],
            "metrica_pesada": ["x" * 10_000] * 5,
        }
    ).to_parquet(parquet_path, index=False, row_group_size=2)
    cache = SimpleNamespace(
        arquivo_dados=parquet_path,
        arquivo_dados_pickle=tmp_path / "ausente.pkl",
    )

    pairs, code_column, name_column, detail = load_institution_pairs_for_diagnostic(cache, batch_size=1)

    assert code_column == "codinst "
    assert name_column == "Instituicao"
    assert pairs.to_dict("records") == [
        {"codinst ": 1, "Instituicao": "Banco A"},
        {"codinst ": 2, "Instituicao": "Banco B"},
        {"codinst ": 3, "Instituicao": "[IF 3]"},
    ]
    assert detail == {
        "carregado": True,
        "registros": 5,
        "coluna_codigo": "codinst ",
        "coluna_nome": "Instituicao",
        "motivo": "",
    }


def test_diagnostic_pairs_prioritize_ifdata_columns(tmp_path):
    parquet_path = tmp_path / "diagnostico-prioridade.parquet"
    pd.DataFrame(
        {
            "CodInst": [1],
            "COD_CONGL": ["C00000001"],
            "Instituição": ["Banco IFData"],
            "NOME_CONGL": ["Conglomerado"],
        }
    ).to_parquet(parquet_path, index=False)
    cache = SimpleNamespace(arquivo_dados=parquet_path, arquivo_dados_pickle=tmp_path / "ausente.pkl")

    pairs, code_column, name_column, _ = load_institution_pairs_for_diagnostic(cache)

    assert (code_column, name_column) == ("CodInst", "Instituição")
    assert pairs.to_dict("records") == [{"CodInst": 1, "Instituição": "Banco IFData"}]


def test_diagnostic_pairs_never_materialize_pickle_fallback(tmp_path):
    pickle_path = tmp_path / "cache.pkl"
    pickle_path.write_bytes(b"nao deve ser lido")
    cache = SimpleNamespace(arquivo_dados=tmp_path / "ausente.parquet", arquivo_dados_pickle=pickle_path)

    pairs, code_column, name_column, detail = load_institution_pairs_for_diagnostic(cache)

    assert pairs.empty
    assert code_column is None and name_column is None
    assert detail["motivo"] == "somente pickle disponível; leitura integral bloqueada para proteger memória"


def test_bloprudencial_slice_filters_before_pandas_materialization(tmp_path):
    parquet_path = tmp_path / "bloprudencial.parquet"
    pd.DataFrame(
        [
            [202603, 4060, 6100000007, "Conta A", "Banco A", "Congl A", 10.0],
            [202603, 4066, 6100000007, "Conta A", "Banco A", "Congl A", 20.0],
            [202602, 4060, 6100000007, "Conta A", "Banco A", "Congl A", 30.0],
            [202603, 4060, 6200000008, "Conta B", "Banco B", "Congl B", 40.0],
        ],
        columns=[
            "DATA_BASE",
            "DOCUMENTO",
            "CONTA",
            "NOME_CONTA",
            "NOME_INSTITUICAO",
            "NOME_CONGL",
            "SALDO",
        ],
    ).to_parquet(parquet_path, index=False)
    cache = SimpleNamespace(arquivo_dados=parquet_path)

    result = load_bloprudencial_parquet_slice(
        cache,
        periodos_yyyymm=("202603",),
        contas_cosif=("6100000007",),
        documentos=("4060",),
        columns=("DATA_BASE", "DOCUMENTO", "CONTA", "NOME_CONTA", "SALDO"),
        batch_size=2,
    )

    assert result.to_dict("records") == [
        {
            "DATA_BASE": 202603,
            "DOCUMENTO": 4060,
            "CONTA": 6100000007,
            "NOME_CONTA": "Conta A",
            "SALDO": 10.0,
        }
    ]


def test_bloprudencial_slice_accepts_legacy_string_codes(tmp_path):
    parquet_path = tmp_path / "bloprudencial-string.parquet"
    pd.DataFrame(
        {
            "Data_Base": ["2026-03-31", "2026-02-28"],
            "Documento": ["4.060", "4.060"],
            "Conta": ["6.100.000.007", "6.100.000.007"],
            "Nome_Conta": ["Conta A", "Conta A"],
        }
    ).to_parquet(parquet_path, index=False)
    cache = SimpleNamespace(arquivo_dados=parquet_path)

    result = load_bloprudencial_parquet_slice(
        cache,
        periodos_yyyymm=("202603",),
        contas_cosif=("6100000007",),
        documentos=("4060",),
        columns=("Data_Base", "Documento", "Conta", "Nome_Conta"),
        batch_size=1,
    )

    assert len(result) == 1
    assert result.iloc[0]["Data_Base"] == "2026-03-31"


def test_bloprudencial_slice_does_not_bypass_missing_document_filter(tmp_path):
    parquet_path = tmp_path / "bloprudencial-sem-documento.parquet"
    pd.DataFrame(
        {
            "DATA_BASE": [202603],
            "CONTA": [6100000007],
            "NOME_CONTA": ["Conta A"],
        }
    ).to_parquet(parquet_path, index=False)
    cache = SimpleNamespace(arquivo_dados=parquet_path)

    result = load_bloprudencial_parquet_slice(
        cache,
        periodos_yyyymm=("202603",),
        documentos=("4060",),
        columns=("DATA_BASE", "CONTA", "NOME_CONTA"),
    )

    assert result.empty


def test_taxas_slice_applies_all_filters_and_projection(tmp_path):
    parquet_path = tmp_path / "taxas.parquet"
    pd.DataFrame(
        {
            "codigo_segmento": ["1", "1", "2"],
            "codigo_modalidade": ["A", "A", "A"],
            "institution_key": ["bank:a", "bank:b", "bank:a"],
            "instituicao_nome_observado": ["Banco A", "Banco B", "Banco A"],
            "inicio_periodo": pd.to_datetime(["2026-01-01", "2025-01-01", "2026-01-01"]),
            "fim_periodo": pd.to_datetime(["2026-01-07", "2025-01-07", "2026-01-07"]),
            "taxa_juros_ao_mes": [1.0, 2.0, 3.0],
        }
    ).to_parquet(parquet_path, index=False)
    cache = SimpleNamespace(arquivo_dados=parquet_path)

    result = load_taxas_juros_historico_slice(
        cache,
        codigo_segmento="1",
        codigo_modalidade="A",
        institution_keys=["bank:a"],
        fim_periodo_min="2026-01-01",
        columns=["institution_key", "fim_periodo", "taxa_juros_ao_mes"],
    )

    assert list(result.columns) == ["institution_key", "fim_periodo", "taxa_juros_ao_mes"]
    assert result["institution_key"].tolist() == ["bank:a"]
    assert result["taxa_juros_ao_mes"].tolist() == [1.0]


def test_taxas_slice_never_falls_back_to_full_pandas_read(monkeypatch, tmp_path):
    parquet_path = tmp_path / "taxas.parquet"
    pd.DataFrame(
        {
            "codigo_segmento": ["1"],
            "codigo_modalidade": ["A"],
        }
    ).to_parquet(parquet_path, index=False)
    cache = SimpleNamespace(arquivo_dados=parquet_path)

    import pyarrow.dataset as ds

    monkeypatch.setattr(ds, "dataset", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("boom")))

    def _forbidden_full_read(*args, **kwargs):
        raise AssertionError("pd.read_parquet integral não pode ser usado como fallback")

    monkeypatch.setattr(pd, "read_parquet", _forbidden_full_read)

    with pytest.raises(RuntimeError, match="leitura integral foi bloqueada"):
        load_taxas_juros_historico_slice(
            cache,
            codigo_segmento="1",
            codigo_modalidade="A",
        )


def test_taxas_monthly_slice_keeps_last_observation_per_bank_and_month(tmp_path):
    parquet_path = tmp_path / "taxas-monthly.parquet"
    pd.DataFrame(
        {
            "codigo_segmento": ["1", "1", "1", "1"],
            "codigo_modalidade": ["A", "A", "A", "A"],
            "segmento": ["PF", "PF", "PF", "PF"],
            "modalidade": ["Produto", "Produto", "Produto", "Produto"],
            "instituicao_nome_observado": ["Banco A", "Banco A", "Banco B", "Banco A"],
            "fim_periodo": pd.to_datetime(["2026-01-07", "2026-01-28", "2026-01-21", "2026-02-04"]),
            "taxa_juros_ao_mes": [1.0, 1.2, 2.0, 1.3],
        }
    ).to_parquet(parquet_path, index=False, row_group_size=2)
    cache = SimpleNamespace(arquivo_dados=parquet_path)

    result = load_taxas_juros_historico_monthly_slice(
        cache,
        codigo_segmento="1",
        codigo_modalidade="A",
        fim_periodo_min="2026-01-01",
        columns=[
            "codigo_segmento",
            "codigo_modalidade",
            "segmento",
            "modalidade",
            "instituicao_nome_observado",
            "fim_periodo",
            "taxa_juros_ao_mes",
        ],
        batch_size=1,
    )

    assert result[["instituicao_nome_observado", "fim_periodo", "taxa_juros_ao_mes"]].to_dict("records") == [
        {
            "instituicao_nome_observado": "Banco B",
            "fim_periodo": pd.Timestamp("2026-01-21"),
            "taxa_juros_ao_mes": 2.0,
        },
        {
            "instituicao_nome_observado": "Banco A",
            "fim_periodo": pd.Timestamp("2026-01-28"),
            "taxa_juros_ao_mes": 1.2,
        },
        {
            "instituicao_nome_observado": "Banco A",
            "fim_periodo": pd.Timestamp("2026-02-04"),
            "taxa_juros_ao_mes": 1.3,
        },
    ]
