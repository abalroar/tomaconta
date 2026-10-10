from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from utils.ifdata_cache.spb_meios_pagamento import (
    DATASETS,
    SPBMeiosPagamentoCache,
    _build_function_url,
    _normalize_dataset,
    _spec_by_key,
)


def test_build_function_url_uses_function_import_syntax_with_quoted_value():
    url = _build_function_url("INTERCAMDA", "trimestre", "19001")

    assert url == (
        "https://olinda.bcb.gov.br/olinda/servico/MPV_DadosAbertos/versao/v1/odata/"
        "INTERCAMDA(trimestre=@trimestre)?@trimestre='19001'&$format=json"
    )


def test_normalize_dataset_renames_casts_and_sorts_by_period():
    spec = _spec_by_key("intercambio")
    records = [
        {
            "trimestre": "20242",
            "produto": "Crédito",
            "bandeira": "Visa",
            "funcaoCartao": "Crédito",
            "formacaptura": "POS",
            "segmento": "PF",
            "numeroparcelas": "1",
            "valorTransacoes": "1000.5",
            "qtdTransacoes": "10",
            "tarifaIntercambioPonderada": "1.23",
        },
        {
            "trimestre": "20241",
            "produto": "Débito",
            "bandeira": "Master",
            "funcaoCartao": "Débito",
            "formacaptura": "ECOM",
            "segmento": "PJ",
            "numeroparcelas": "0",
            "valorTransacoes": "500.0",
            "qtdTransacoes": "5",
            "tarifaIntercambioPonderada": "0.65",
        },
    ]

    df = _normalize_dataset(records, spec)

    assert list(df["trimestre"]) == ["20241", "20242"]
    assert str(df["tarifa_intercambio_ponderada"].dtype) == "Float64"
    assert df.loc[0, "tarifa_intercambio_ponderada"] == 0.65
    assert str(df["bandeira"].dtype) == "string"


def test_normalize_dataset_returns_empty_frame_with_expected_columns_when_no_records():
    spec = _spec_by_key("desconto")
    df = _normalize_dataset([], spec)

    assert df.empty
    assert list(df.columns) == list(spec.rename.values())


def test_dataset_paths_covers_all_12_datasets_and_main_key_points_to_arquivo_dados(tmp_path):
    cache = SPBMeiosPagamentoCache(tmp_path)
    paths = cache.dataset_paths()

    assert len(paths) == len(DATASETS) == 12
    assert paths["nucleo_trimestral"] == cache.arquivo_dados
    assert paths["intercambio"] == cache.cache_dir / "intercambio.parquet"


def test_materialize_history_downloads_only_selected_datasets(monkeypatch, tmp_path):
    cache = SPBMeiosPagamentoCache(tmp_path)

    df_nucleo = pd.DataFrame({"trimestre": ["20241"], "valor_pix": [1.0]})
    df_intercambio = pd.DataFrame({"trimestre": ["20241"], "tarifa_intercambio_ponderada": [1.5]})

    def fake_fetch(spec, *, session=None, timeout=120):
        if spec.key == "nucleo_trimestral":
            return df_nucleo.copy()
        if spec.key == "intercambio":
            return df_intercambio.copy()
        raise AssertionError(f"dataset inesperado solicitado: {spec.key}")

    monkeypatch.setattr(
        "utils.ifdata_cache.spb_meios_pagamento._fetch_dataset_history",
        fake_fetch,
    )

    resultado = cache.materialize_history(datasets=["nucleo_trimestral", "intercambio"])

    assert resultado.sucesso is True
    assert cache.arquivo_dados.exists() is True
    assert (cache.cache_dir / "intercambio.parquet").exists() is True
    assert (cache.cache_dir / "desconto.parquet").exists() is False
    assert resultado.metadata["datasets"] == {"nucleo_trimestral": 1, "intercambio": 1}


def test_materialize_history_skips_already_materialized_dataset_unless_overwrite(monkeypatch, tmp_path):
    cache = SPBMeiosPagamentoCache(tmp_path)
    cache._garantir_diretorio()
    # O skip confirma um parquet legível; arquivo truncado deve ser reextraído.
    pd.DataFrame({"trimestre": ["20241"], "tarifa_intercambio_ponderada": [1.0]}).to_parquet(
        cache.cache_dir / "intercambio.parquet", index=False,
    )

    calls = []

    def fake_fetch(spec, *, session=None, timeout=120):
        calls.append(spec.key)
        return pd.DataFrame({"trimestre": ["20241"], "tarifa_intercambio_ponderada": [1.0]})

    monkeypatch.setattr(
        "utils.ifdata_cache.spb_meios_pagamento._fetch_dataset_history",
        fake_fetch,
    )

    resultado_skip = cache.materialize_history(datasets=["intercambio"], overwrite=False)
    assert resultado_skip.sucesso is True
    assert calls == []
    assert resultado_skip.metadata["datasets"] == {}

    resultado_overwrite = cache.materialize_history(datasets=["intercambio"], overwrite=True)
    assert resultado_overwrite.sucesso is True
    assert calls == ["intercambio"]


def test_materialize_history_reports_failures_without_raising(monkeypatch, tmp_path):
    cache = SPBMeiosPagamentoCache(tmp_path)

    def fake_fetch(spec, *, session=None, timeout=120):
        if spec.key == "desconto":
            raise RuntimeError("falha de rede simulada")
        return pd.DataFrame({"trimestre": ["20241"], "valor_pix": [1.0]})

    monkeypatch.setattr(
        "utils.ifdata_cache.spb_meios_pagamento._fetch_dataset_history",
        fake_fetch,
    )

    resultado = cache.materialize_history(datasets=["nucleo_trimestral", "desconto"])

    assert resultado.sucesso is False
    assert resultado.metadata["failures"] == [{"dataset": "desconto", "erro": "falha de rede simulada"}]
    # Nenhum dataset do pacote parcial deve tornar-se a versão ativa.
    assert cache.arquivo_dados.exists() is False


def _seed_complete_spb_bundle(cache):
    cache.bundled_dir.mkdir(parents=True, exist_ok=True)
    bundled_bytes = {}
    for spec in DATASETS:
        data = pd.DataFrame({
            spec.period_column: ["202401" if spec.period_column == "ano_mes" else "20241"],
            "valor_preservado": [1.0],
        })
        path = cache.bundled_dir / cache.dataset_paths()[spec.key].name
        data.to_parquet(path, index=False)
        bundled_bytes[spec.key] = path.read_bytes()
    (cache.bundled_dir / cache.config.arquivo_metadata).write_text(
        json.dumps({"total_registros": 1, "colunas": ["trimestre", "valor_preservado"]}),
        encoding="utf-8",
    )
    return bundled_bytes


def test_materialize_subset_promotes_all_declared_bundled_datasets_without_changing_bytes(monkeypatch, tmp_path):
    cache = SPBMeiosPagamentoCache(tmp_path)
    bundled_bytes = _seed_complete_spb_bundle(cache)
    updated = pd.DataFrame({"trimestre": ["20242"], "tarifa_intercambio_ponderada": [1.5]})
    calls = []

    def fake_fetch(spec, *, session=None, timeout=120):
        calls.append(spec.key)
        assert spec.key == "intercambio"
        return updated.copy()

    monkeypatch.setattr("utils.ifdata_cache.spb_meios_pagamento._fetch_dataset_history", fake_fetch)
    result = cache.materialize_history(datasets=["intercambio"])

    assert result.sucesso
    assert calls == ["intercambio"]
    manifest = json.loads(cache.manifest_path.read_text(encoding="utf-8"))
    assert set(manifest["datasets"]) == {spec.key for spec in DATASETS}
    for key in manifest["datasets"]:
        path = cache.dataset_paths()[key]
        assert path.exists()
        assert len(pd.read_parquet(path)) == manifest["datasets"][key]
        assert (cache.bundled_dir / path.name).read_bytes() == bundled_bytes[key]
        if key != "intercambio":
            assert path.read_bytes() == bundled_bytes[key]
    pd.testing.assert_frame_equal(pd.read_parquet(cache.dataset_paths()["intercambio"]), updated)


def test_materialize_subset_failure_preserves_complete_bundled_generation(monkeypatch, tmp_path):
    cache = SPBMeiosPagamentoCache(tmp_path)
    bundled_bytes = _seed_complete_spb_bundle(cache)

    def fake_fetch(spec, *, session=None, timeout=120):
        if spec.key == "desconto":
            raise RuntimeError("falha de rede simulada")
        return pd.DataFrame({"trimestre": ["20242"], "tarifa_intercambio_ponderada": [1.5]})

    monkeypatch.setattr("utils.ifdata_cache.spb_meios_pagamento._fetch_dataset_history", fake_fetch)
    result = cache.materialize_history(datasets=["intercambio", "desconto"])

    assert not result.sucesso
    assert not cache.manifest_path.exists()
    for key, runtime_path in cache.dataset_paths().items():
        assert not runtime_path.exists()
        assert cache.read_dataset_paths()[key].read_bytes() == bundled_bytes[key]


def test_materialize_history_unknown_dataset_key_is_silently_ignored(tmp_path):
    cache = SPBMeiosPagamentoCache(tmp_path)

    resultado = cache.materialize_history(datasets=["dataset_que_nao_existe"])

    assert resultado.sucesso is False
    assert "Nenhum dataset" in resultado.mensagem


def test_extra_release_assets_includes_only_existing_non_main_parquets_and_manifest(tmp_path):
    cache = SPBMeiosPagamentoCache(tmp_path)
    cache._garantir_diretorio()
    (cache.cache_dir / "intercambio.parquet").write_bytes(b"")
    cache.manifest_path.write_text("{}", encoding="utf-8")

    extras = cache.extra_release_assets()
    extra_names = {name for _, name in extras}

    assert f"{cache.config.nome}_intercambio.parquet" in extra_names
    assert f"{cache.config.nome}_manifest.json" in extra_names
    assert f"{cache.config.nome}_desconto.parquet" not in extra_names
    assert f"{cache.config.nome}_nucleo_trimestral.parquet" not in extra_names


def test_carregar_dataset_unknown_key_returns_failure(tmp_path):
    cache = SPBMeiosPagamentoCache(tmp_path)

    resultado = cache.carregar_dataset("dataset_invalido")

    assert resultado.sucesso is False
    assert "desconhecido" in resultado.mensagem


def test_carregar_dataset_reads_local_parquet_when_present(tmp_path):
    cache = SPBMeiosPagamentoCache(tmp_path)
    cache._garantir_diretorio()
    df = pd.DataFrame({"trimestre": ["20241"], "tarifa_intercambio_ponderada": [1.0]})
    df.to_parquet(cache.cache_dir / "intercambio.parquet", index=False)

    resultado = cache.carregar_dataset("intercambio")

    assert resultado.sucesso is True
    assert resultado.fonte == "cache_local"
    assert list(resultado.dados["trimestre"]) == ["20241"]
