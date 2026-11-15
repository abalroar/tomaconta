from hashlib import sha256
from io import BytesIO
import json
from unittest.mock import Mock

import pandas as pd
import pytest
import requests

from utils.individual_release_cache import ensure_individual_release_cache
from utils.ifdata_cache.base import CacheResult
from utils.ifdata_cache.principal import PrincipalCache, PRINCIPAL_INDIVIDUAL_CONFIG
from utils.ifdata_cache.derived_metrics import DerivedMetricsCache, DERIVED_INDIVIDUAL_CACHE_CONFIG


RELEASE = "https://github.com/abalroar/tomaconta/releases/download/v1.1-cache"


def principal(tmp_path):
    return PrincipalCache(tmp_path, config=PRINCIPAL_INDIVIDUAL_CONFIG, repo_prefix="principal_individual")


def derived(tmp_path):
    return DerivedMetricsCache(tmp_path, config=DERIVED_INDIVIDUAL_CACHE_CONFIG)


@pytest.fixture(params=[principal, derived], ids=["principal", "derived"])
def cache(request, tmp_path):
    return request.param(tmp_path)


def frame_for(cache, value=1.0):
    common = {"Instituição": ["BANCO A S.A."], "Período": ["2/2026"]}
    if cache.config.nome == "principal_individual":
        return pd.DataFrame({**common, "Ativo Total": [value]})
    return pd.DataFrame({**common, "Métrica": ["Desp Captação / Captação"], "Valor": [value], "Unidade": ["%"]})


def released_bytes(frame):
    buffer = BytesIO()
    frame.to_parquet(buffer, index=False, compression="gzip")
    return buffer.getvalue()


def manifest(cache, raw, **extra):
    return {"cache": cache.config.nome, "exists": True, "sha256": sha256(raw).hexdigest(),
            "record_count": 1, "max_period": "2/2026", **extra}


def seed(cache, value=1.0):
    assert cache.salvar_local(frame_for(cache, value), fonte="old_local").sucesso
    return cache.arquivo_dados_runtime.read_bytes(), cache.arquivo_metadata_runtime.read_bytes()


def mocked_download(monkeypatch, raw):
    response = Mock(content=raw)
    response.raise_for_status.return_value = None
    get = Mock(return_value=response)
    monkeypatch.setattr("utils.individual_release_cache.requests.get", get)
    return get


def assert_unchanged(cache, original):
    assert cache.arquivo_dados_runtime.read_bytes() == original[0]
    assert cache.arquivo_metadata_runtime.read_bytes() == original[1]


def test_same_cardinality_and_period_with_new_hash_forces_published_revision(cache, monkeypatch):
    old_bytes, _ = seed(cache, 1.0)
    new = released_bytes(frame_for(cache, 2.0))
    assert sha256(old_bytes).digest() != sha256(new).digest()
    get = mocked_download(monkeypatch, new)
    path = ensure_individual_release_cache(cache, manifest(cache, new), RELEASE)
    assert path == cache.read_data_file
    assert path.read_bytes() == new
    value_column = "Ativo Total" if cache.config.nome == "principal_individual" else "Valor"
    assert pd.read_parquet(path)[value_column].tolist() == [2.0]
    get.assert_called_once()
    url = get.call_args.args[0]
    assert f"/{cache.config.nome}_dados.parquet?" in url
    assert sha256(new).hexdigest() in url
    assert get.call_args.kwargs["timeout"] == 120
    metadata = json.loads(cache.arquivo_metadata_runtime.read_text())
    assert metadata["extra"]["release_asset_sha256"] == sha256(new).hexdigest()


def test_identical_hash_uses_existing_source_without_network(cache, monkeypatch):
    original = seed(cache)
    get = mocked_download(monkeypatch, b"must not be downloaded")
    assert ensure_individual_release_cache(cache, manifest(cache, original[0]), RELEASE) == cache.read_data_file
    get.assert_not_called()
    assert_unchanged(cache, original)


def test_wrong_download_hash_never_overwrites_current_cache(cache, monkeypatch):
    original = seed(cache)
    expected = released_bytes(frame_for(cache, 2.0))
    mocked_download(monkeypatch, b"different source")
    with pytest.raises(ValueError, match="SHA-256"):
        ensure_individual_release_cache(cache, manifest(cache, expected), RELEASE)
    assert_unchanged(cache, original)


def test_http_failure_does_not_serve_or_replace_old_source(cache, monkeypatch):
    original = seed(cache)
    get = Mock(side_effect=requests.RequestException("source unavailable"))
    monkeypatch.setattr("utils.individual_release_cache.requests.get", get)
    with pytest.raises(requests.RequestException):
        ensure_individual_release_cache(cache, manifest(cache, released_bytes(frame_for(cache, 2.0))), RELEASE)
    assert_unchanged(cache, original)


@pytest.mark.parametrize("problem", ["invalid_parquet", "invalid_schema", "wrong_size", "wrong_record_count"])
def test_matching_hash_still_requires_valid_source_and_manifest_contract(cache, monkeypatch, problem):
    original = seed(cache)
    raw = b"not parquet" if problem == "invalid_parquet" else released_bytes(
        pd.DataFrame({"unrelated": [1]}) if problem == "invalid_schema" else frame_for(cache, 2.0))
    info = manifest(cache, raw)
    if problem == "wrong_size":
        info["size_bytes"] = len(raw) + 1
    elif problem == "wrong_record_count":
        info["record_count"] = 2
    mocked_download(monkeypatch, raw)
    with pytest.raises(ValueError):
        ensure_individual_release_cache(cache, info, RELEASE)
    assert_unchanged(cache, original)


def test_failed_save_in_staging_does_not_replace_old_data_or_metadata(cache, monkeypatch):
    original = seed(cache)
    raw = released_bytes(frame_for(cache, 2.0))
    mocked_download(monkeypatch, raw)

    def failed_save(staged, *args, **kwargs):
        staged.arquivo_dados_runtime.write_bytes(b"partial serializer output")
        return CacheResult(False, "save failed", fonte="nenhum")

    monkeypatch.setattr(type(cache), "salvar_local", failed_save)
    with pytest.raises(ValueError, match="save failed"):
        ensure_individual_release_cache(cache, manifest(cache, raw), RELEASE)
    assert_unchanged(cache, original)


def test_original_asset_bytes_are_preserved_after_metadata_serialization(cache, monkeypatch):
    frame = frame_for(cache, 2.0)
    raw = released_bytes(frame)
    seed(cache)
    # Gzip and the serializer's default compression encode identical rows differently.
    serialized = BytesIO()
    frame.to_parquet(serialized, index=False)
    assert serialized.getvalue() != raw
    get = mocked_download(monkeypatch, raw)
    info = {"cache": cache.config.nome, "files": {"parquet": {
        "asset_name": f"{cache.config.nome}_dados.parquet", "sha256": sha256(raw).hexdigest(), "size_bytes": len(raw)}}}
    assert ensure_individual_release_cache(cache, info, RELEASE).read_bytes() == raw
    assert ensure_individual_release_cache(cache, info, RELEASE).read_bytes() == raw
    assert get.call_count == 1
    loaded = cache.carregar_local()
    assert loaded.sucesso, loaded.mensagem
    integrity = json.loads(cache.arquivo_metadata_runtime.read_text())["integridade"]
    assert integrity["sha256"] == sha256(raw).hexdigest()
    assert integrity["tamanho_bytes"] == len(raw)


@pytest.mark.parametrize("manifest_publication_id", [None, "release-new"])
def test_verified_release_replaces_protected_old_bundle(cache, monkeypatch, manifest_publication_id):
    old_frame = frame_for(cache, 1.0)
    cache.bundled_dir.mkdir(parents=True, exist_ok=True)
    old_frame.to_parquet(cache.bundled_dir / cache.config.arquivo_dados, index=False)
    (cache.bundled_dir / cache.config.arquivo_metadata).write_text(json.dumps({
        "publication_id": "bundled-old", "periodos": ["2/2026"],
        "total_registros": 1, "colunas": list(old_frame.columns), "formato": "parquet",
    }))
    seed(cache, 0.5)
    assert cache.read_data_file.parent == cache.bundled_dir
    raw = released_bytes(frame_for(cache, 2.0))
    get = mocked_download(monkeypatch, raw)
    info = manifest(cache, raw, publication_id=manifest_publication_id)

    activated = ensure_individual_release_cache(cache, info, RELEASE)

    assert activated == cache.arquivo_dados_runtime
    assert activated.read_bytes() == raw
    metadata = json.loads(cache.arquivo_metadata_runtime.read_text())
    assert metadata.get("publication_id") == manifest_publication_id
    assert metadata["baseline_publication_id"] == "bundled-old"
    assert metadata["integridade"]["sha256"] == sha256(raw).hexdigest()
    assert metadata["extra"]["release_asset_sha256"] == sha256(raw).hexdigest()
    loaded = cache.carregar_local()
    assert loaded.sucesso, loaded.mensagem
    value_column = "Ativo Total" if cache.config.nome == "principal_individual" else "Valor"
    assert loaded.dados[value_column].tolist() == [2.0]
    assert ensure_individual_release_cache(cache, info, RELEASE) == activated
    get.assert_called_once()


def test_verified_release_missing_bundled_period_never_promotes(cache, monkeypatch):
    original = seed(cache)
    cache.bundled_dir.mkdir(parents=True, exist_ok=True)
    older_frame = frame_for(cache)
    older_frame["Período"] = "1/2026"
    older_frame.to_parquet(cache.bundled_dir / cache.config.arquivo_dados, index=False)
    (cache.bundled_dir / cache.config.arquivo_metadata).write_text(json.dumps({
        "publication_id": "bundled-old", "periodos": ["1/2026", "2/2026"],
    }))
    raw = released_bytes(frame_for(cache, 2.0))
    mocked_download(monkeypatch, raw)
    with pytest.raises(ValueError, match="não cobre os períodos"):
        ensure_individual_release_cache(cache, manifest(cache, raw), RELEASE)
    assert_unchanged(cache, original)


def test_missing_hash_or_wrong_cache_identity_blocks_before_network(cache, monkeypatch):
    original = seed(cache)
    get = mocked_download(monkeypatch, b"unverified")
    with pytest.raises(ValueError, match="SHA-256"):
        ensure_individual_release_cache(cache, {"cache": cache.config.nome}, RELEASE)
    with pytest.raises(ValueError, match="não corresponde"):
        ensure_individual_release_cache(cache, {"cache": "principal", "sha256": sha256(original[0]).hexdigest()}, RELEASE)
    get.assert_not_called()
    assert_unchanged(cache, original)
