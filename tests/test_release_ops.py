import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from utils.ifdata_cache.release_config import ReleaseConfig
from utils.ifdata_cache.release_ops import (
    _hydrate_source_caches,
    collect_release_assets,
    get_postprocess_targets,
    get_publishable_bundle,
    upload_release_assets,
    write_release_manifest,
)


class _FakeCache:
    def __init__(self, base_dir: Path, name: str):
        self.arquivo_dados = base_dir / f"{name}_dados.parquet"
        self.arquivo_dados.write_bytes(b"parquet-data")
        self.arquivo_dados_pickle = base_dir / f"{name}_cache.pkl"
        self.arquivo_metadata = base_dir / f"{name}_metadata.json"
        self.arquivo_metadata.write_text(json.dumps({"cache": name}), encoding="utf-8")


class _FakeManager:
    def __init__(self, base_dir: Path, names: list[str]):
        self.base_dir = base_dir
        self._caches = {name: _FakeCache(base_dir, name) for name in names}

    def get_cache(self, cache_name: str):
        return self._caches.get(cache_name)


class _HydrateCache:
    def __init__(self, *, exists: bool = True, local_success: bool = True, name: str = "cache"):
        self._exists = exists
        self._local_success = local_success
        self.name = name
        self.local_loads = 0

    def existe(self):
        return self._exists

    def carregar_local(self):
        self.local_loads += 1
        if self._local_success:
            return SimpleNamespace(
                sucesso=True,
                dados={"cache": self.name, "origin": "local"},
                mensagem="local ok",
                fonte="cache_local",
            )
        return SimpleNamespace(
            sucesso=False,
            dados=None,
            mensagem="local falhou",
            fonte="nenhum",
        )


class _HydrateManager:
    def __init__(self, caches):
        self._caches = caches
        self.calls = []

    def get_cache(self, cache_name: str):
        return self._caches.get(cache_name)

    def carregar(self, cache_name: str, forcar_remoto: bool = False):
        self.calls.append((cache_name, forcar_remoto))
        return SimpleNamespace(
            sucesso=True,
            dados={"cache": cache_name, "origin": "remote"},
            mensagem="remoto ok",
            fonte="github_releases",
        )


class _Response:
    def __init__(self, status_code: int, payload=None, text: str = "", headers: dict | None = None):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.headers = headers or {}
        self.content = json.dumps(payload).encode("utf-8") if payload is not None else text.encode("utf-8")

    def json(self):
        if self._payload is None:
            raise ValueError("sem json")
        return self._payload


def test_get_postprocess_targets_maps_base_caches():
    assert get_postprocess_targets(["principal"]) == ["derived_metrics", "critical_screens"]
    assert get_postprocess_targets(["dre_individual"]) == ["derived_metrics_individual"]
    assert get_postprocess_targets(["bloprudencial"]) == ["critical_screens"]


def test_get_publishable_bundle_skips_failed_gate_targets():
    publishable, warnings = get_publishable_bundle(
        ["principal"],
        materialization_details=[
            {"cache": "derived_metrics", "status": "ok", "message": "ok"},
            {"cache": "critical_screens", "status": "ok", "message": "ok"},
        ],
        manifest_payload={
            "gates": {
                "dre_consolidado": {"success": False, "message": "esperado 202512, encontrado 202509"},
                "snapshot_peers": {"success": True, "message": "alinhado em 202512"},
            }
        },
    )

    assert publishable == ["principal", "critical_screens"]
    assert warnings == ["derived_metrics: esperado 202512, encontrado 202509"]


def test_hydrate_source_caches_prefers_existing_local_sources():
    principal = _HydrateCache(name="principal")
    capital = _HydrateCache(name="capital")
    manager = _HydrateManager({"principal": principal, "capital": capital})

    details, failures = _hydrate_source_caches(
        manager,
        ["principal", "capital"],
        local_first=["principal"],
    )

    assert failures == []
    assert manager.calls == []
    assert principal.local_loads == 1
    assert capital.local_loads == 1
    assert {item["cache"]: item["forced_remote"] for item in details} == {
        "principal": False,
        "capital": False,
    }


def test_hydrate_source_caches_falls_back_to_remote_when_local_missing():
    manager = _HydrateManager({"capital": _HydrateCache(name="capital", exists=False)})

    details, failures = _hydrate_source_caches(manager, ["capital"])

    assert failures == []
    assert manager.calls == [("capital", True)]
    assert details[0]["source"] == "github_releases"
    assert details[0]["forced_remote"] is True


def test_write_manifest_and_collect_assets(tmp_path: Path, monkeypatch):
    manager = _FakeManager(tmp_path, ["principal", "critical_screens"])
    release = ReleaseConfig(
        repo="abalroar/tomaconta",
        tag="v2.0-cache",
        raw_repo="abalroar/tomaconta",
        release_base_url="https://github.com/abalroar/tomaconta/releases/download/v2.0-cache",
        repo_source="test",
        tag_source="test",
        raw_repo_source="test",
    )

    monkeypatch.setattr(
        "utils.ifdata_cache.release_ops.build_runtime_manifest",
        lambda *args, **kwargs: {
            "caches": {"principal": {"exists": True}},
            "gates": {"snapshot_peers": {"success": True, "message": "ok"}},
            "summary": {"total_caches": 1},
        },
    )

    manifest_path, payload = write_release_manifest(
        manager,
        base_dir=tmp_path,
        release_config=release,
        expected_periods={"quarterly": "202512"},
        selected_caches=["principal"],
        materialization_details=[{"cache": "critical_screens", "status": "ok", "message": "ok"}],
        include_hashes=False,
    )

    assert manifest_path.exists()
    assert payload["selected_caches"] == ["principal"]
    assert payload["postprocess_targets"] == ["derived_metrics", "critical_screens"]
    assert payload["expected_periods"] == {"quarterly": "202512"}

    assets = collect_release_assets(
        manager,
        ["principal", "critical_screens"],
        manifest_path=manifest_path,
    )
    asset_names = [asset_name for _, asset_name in assets]
    assert asset_names == [
        "principal_dados.parquet",
        "principal_metadata.json",
        "critical_screens_dados.parquet",
        "critical_screens_metadata.json",
        "manifest.json",
    ]


def test_upload_release_assets_explains_fine_grained_pat_permission_error(tmp_path: Path, monkeypatch):
    asset_path = tmp_path / "spb_meios_pagamento_dados.parquet"
    asset_path.write_bytes(b"parquet-data")

    def fake_request(method, url, **kwargs):
        assert method == "GET"
        return _Response(
            200,
            {
                "upload_url": "https://uploads.github.com/repos/abalroar/tomaconta/releases/1/assets{?name,label}",
                "assets": [],
            },
        )

    def fake_post(url, **kwargs):
        return _Response(
            403,
            {
                "message": "Resource not accessible by personal access token",
                "documentation_url": "https://docs.github.com/rest",
            },
        )

    monkeypatch.setattr("utils.ifdata_cache.release_ops.requests.request", fake_request)
    monkeypatch.setattr("utils.ifdata_cache.release_ops.requests.post", fake_post)

    with pytest.raises(RuntimeError) as excinfo:
        upload_release_assets(
            repo="abalroar/tomaconta",
            tag="v2.0-cache",
            assets=[(asset_path, "spb_meios_pagamento_dados.parquet")],
            token="token-readonly",
        )

    message = str(excinfo.value)
    assert "Resource not accessible by personal access token" in message
    assert "Contents: Read and write" in message
    assert "GITHUB_PAT" in message
