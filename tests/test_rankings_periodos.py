"""Períodos oferecidos pela aba Rankings devem refletir o parquet, não o metadata.

`salvar_local()` reescreve `metadata["periodos"]` a cada download remoto ou
extração parcial; em modo substituição a lista passa a conter apenas os períodos
daquela execução. Antes, o dropdown de Rankings lia esse metadata e sumia com
períodos que existiam no dataset — assimetria em relação a Snapshot/Peers, que
consomem o artefato bundled de `critical_screens`.
"""

import json
from types import SimpleNamespace

import pandas as pd

import app1


PERIODOS_COMPLETOS = ["3/2025", "4/2025", "1/2026"]


def _cache_falso(tmp_path, periodos_dados, periodos_metadata=None, coluna="Período"):
    arquivo_dados = tmp_path / "dados.parquet"
    arquivo_metadata = tmp_path / "metadata.json"
    if periodos_dados is not None:
        pd.DataFrame(
            {
                "Instituição": [f"Banco {i}" for i in range(len(periodos_dados))],
                coluna: list(periodos_dados),
                "Ativo Total": [1.0] * len(periodos_dados),
            }
        ).to_parquet(arquivo_dados, index=False)
    arquivo_metadata.write_text(
        json.dumps({"periodos": list(periodos_metadata or [])}), encoding="utf-8"
    )
    return SimpleNamespace(arquivo_dados=arquivo_dados, arquivo_metadata=arquivo_metadata)


def test_le_periodos_do_parquet_ignorando_metadata_truncado(tmp_path):
    cache = _cache_falso(tmp_path, PERIODOS_COMPLETOS, periodos_metadata=["3/2025"])
    assert app1._periodos_do_parquet_cache(cache) == tuple(sorted(PERIODOS_COMPLETOS))


def test_aceita_grafia_sem_acento(tmp_path):
    cache = _cache_falso(tmp_path, PERIODOS_COMPLETOS, coluna="Periodo")
    assert app1._periodos_do_parquet_cache(cache) == tuple(sorted(PERIODOS_COMPLETOS))


def test_sem_parquet_retorna_vazio(tmp_path):
    cache = _cache_falso(tmp_path, None, periodos_metadata=PERIODOS_COMPLETOS)
    assert app1._periodos_do_parquet_cache(cache) == ()
    assert app1._periodos_do_parquet_cache(None) == ()


def test_contexto_de_filtros_prefere_parquet(tmp_path, monkeypatch):
    cache = _cache_falso(tmp_path, PERIODOS_COMPLETOS, periodos_metadata=["3/2025"])
    monkeypatch.setattr(
        app1,
        "get_cache_manager",
        lambda: SimpleNamespace(get_cache=lambda nome: cache if nome == "principal" else None),
    )
    app1._get_rankings_filters_context.clear()

    contexto = app1._get_rankings_filters_context("token-parquet", ())

    assert "1/2026" in contexto["periodos_disponiveis"]
    assert app1._periodo_mais_recente(list(contexto["periodos_disponiveis"])) == "1/2026"


def test_contexto_de_filtros_usa_metadata_quando_nao_ha_parquet(tmp_path, monkeypatch):
    cache = _cache_falso(tmp_path, None, periodos_metadata=PERIODOS_COMPLETOS)
    monkeypatch.setattr(
        app1,
        "get_cache_manager",
        lambda: SimpleNamespace(get_cache=lambda nome: cache if nome == "principal" else None),
    )
    app1._get_rankings_filters_context.clear()

    contexto = app1._get_rankings_filters_context("token-metadata", ())

    assert contexto["periodos_disponiveis"] == tuple(sorted(PERIODOS_COMPLETOS))


def test_contexto_do_scatter_tambem_prefere_parquet(tmp_path, monkeypatch):
    """Scatter tinha a mesma dependência do metadata para montar o seletor."""
    cache = _cache_falso(tmp_path, PERIODOS_COMPLETOS, periodos_metadata=["3/2025"])
    monkeypatch.setattr(
        app1,
        "get_cache_manager",
        lambda: SimpleNamespace(get_cache=lambda nome: cache if nome == "principal" else None),
    )
    app1._get_scatter_filters_context.clear()

    contexto = app1._get_scatter_filters_context("token-scatter", ())

    assert "1/2026" in contexto["periodos"]
