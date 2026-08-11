"""Camada de dados de Rankings — testada sem executar a UI do monólito."""

import json
from types import SimpleNamespace

import pandas as pd

from tabs import rankings_data


def _cache(tmp_path, periodos=None, metadata=None, coluna="Período", nome="dados.parquet"):
    dados = tmp_path / nome
    meta = tmp_path / "metadata.json"
    if periodos is not None:
        pd.DataFrame({coluna: list(periodos), "Valor": [1.0] * len(periodos)}).to_parquet(
            dados, index=False
        )
    if metadata is not None:
        meta.write_text(json.dumps(metadata), encoding="utf-8")
    return SimpleNamespace(arquivo_dados=dados, arquivo_metadata=meta)


def test_periodos_saem_do_parquet_e_vem_ordenados_sem_duplicatas(tmp_path):
    cache = _cache(tmp_path, ["4/2025", "1/2026", "4/2025", "3/2025"])
    assert rankings_data.periodos_do_parquet(cache) == ("1/2026", "3/2025", "4/2025")


def test_periodos_aceitam_grafia_sem_acento(tmp_path):
    cache = _cache(tmp_path, ["1/2026"], coluna="Periodo")
    assert rankings_data.periodos_do_parquet(cache) == ("1/2026",)


def test_periodos_sem_arquivo_ou_sem_cache(tmp_path):
    assert rankings_data.periodos_do_parquet(None) == ()
    assert rankings_data.periodos_do_parquet(_cache(tmp_path)) == ()


def test_mais_recente_usa_ordem_cronologica_nao_textual():
    # Ordem textual colocaria "4/2025" à frente de "1/2026".
    assert rankings_data.periodo_mais_recente(["1/2026", "4/2025", "3/2025"]) == "1/2026"
    assert rankings_data.periodo_mais_recente(["202509", "202603"]) == "202603"
    assert rankings_data.periodo_mais_recente([]) is None


def test_cobertura_reporta_parquet_e_metadata(tmp_path):
    cache = _cache(
        tmp_path,
        ["3/2025", "4/2025", "1/2026"],
        metadata={
            "total_registros": 62061,
            "fonte": "api",
            "timestamp_salvamento": "2026-06-22T15:10:21.643393",
            # Metadata truncado de propósito: não pode contaminar a cobertura.
            "periodos": ["3/2025"],
        },
    )
    info = rankings_data.cobertura_do_cache("principal", cache)

    assert info["existe"] is True
    assert info["total_periodos"] == 3
    assert info["periodo_mais_recente"] == "1/2026"
    assert info["total_registros"] == 62061
    assert info["atualizado_em"] == "2026-06-22T15:10:21"


def test_cobertura_de_cache_ausente(tmp_path):
    info = rankings_data.cobertura_do_cache("principal", _cache(tmp_path))
    assert info["existe"] is False
    assert info["total_periodos"] == 0
    assert info["periodo_mais_recente"] is None
    assert info["origem"] == "indisponivel"


def test_origem_distingue_bundled_de_runtime(tmp_path):
    runtime = tmp_path / "data" / "cache" / "principal"
    bundled = tmp_path / "data" / "bundled" / "principal"
    runtime.mkdir(parents=True)
    bundled.mkdir(parents=True)
    assert rankings_data.origem_do_cache(_cache(runtime, ["1/2026"])) == "runtime"
    assert rankings_data.origem_do_cache(_cache(bundled, ["1/2026"])) == "bundled"
