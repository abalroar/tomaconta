from types import SimpleNamespace

import utils.ifdata_cache as cache_package
import utils.ifdata_cache.release_config as release_config_module
from utils.ifdata_cache.release_config import (
    build_release_asset_url,
    get_release_config,
)


def test_cache_manager_is_recreated_when_release_tag_changes(monkeypatch):
    active_tag = {"value": "v1-cache"}

    class DummyManager:
        pass

    monkeypatch.setattr(cache_package, "CacheManager", DummyManager)
    monkeypatch.setattr(
        release_config_module,
        "get_release_config",
        lambda: SimpleNamespace(tag=active_tag["value"]),
    )
    monkeypatch.setattr(cache_package, "_manager", None)
    monkeypatch.setattr(cache_package, "_manager_release_tag", None)

    first = cache_package.get_manager()
    assert cache_package.get_manager() is first

    active_tag["value"] = "v2-cache"
    assert cache_package.get_manager() is not first


def test_release_config_prefers_env_over_secrets(monkeypatch):
    monkeypatch.setenv("TOMACONTA_RELEASE_REPO", "org/repo-env")
    monkeypatch.setenv("TOMACONTA_RELEASE_TAG", "v9-cache")
    monkeypatch.setenv("TOMACONTA_RAW_REPO", "org/raw-env")

    cfg = get_release_config(
        secrets_provider={
            "TOMACONTA_RELEASE_REPO": "org/repo-secret",
            "TOMACONTA_RELEASE_TAG": "v1-secret",
            "TOMACONTA_RAW_REPO": "org/raw-secret",
        }
    )

    assert cfg.repo == "org/repo-env"
    assert cfg.tag == "v9-cache"
    assert cfg.raw_repo == "org/raw-env"
    assert cfg.repo_source == "env:TOMACONTA_RELEASE_REPO"
    assert cfg.tag_source == "env:TOMACONTA_RELEASE_TAG"
    assert cfg.release_base_url == "https://github.com/org/repo-env/releases/download/v9-cache"


def test_release_config_migrates_deprecated_tag_override(monkeypatch):
    monkeypatch.setenv("TOMACONTA_RELEASE_TAG", "v1.0-cache")

    cfg = get_release_config()

    assert cfg.tag == "v1.1-cache"
    assert cfg.tag_source == "migrated:env:TOMACONTA_RELEASE_TAG"


def test_release_config_falls_back_to_secrets(monkeypatch):
    monkeypatch.delenv("TOMACONTA_RELEASE_REPO", raising=False)
    monkeypatch.delenv("TOMACONTA_RELEASE_TAG", raising=False)
    monkeypatch.delenv("TOMACONTA_RAW_REPO", raising=False)

    cfg = get_release_config(
        secrets_provider={
            "TOMACONTA_RELEASE_REPO": "org/repo-secret",
            "TOMACONTA_RELEASE_TAG": "v2-secret",
            "TOMACONTA_RAW_REPO": "org/raw-secret",
        }
    )

    assert cfg.repo == "org/repo-secret"
    assert cfg.tag == "v2-secret"
    assert cfg.raw_repo == "org/raw-secret"
    assert cfg.repo_source == "secret:TOMACONTA_RELEASE_REPO"
    assert build_release_asset_url("principal_dados.parquet", repo=cfg.repo, tag=cfg.tag) == (
        "https://github.com/org/repo-secret/releases/download/v2-secret/principal_dados.parquet"
    )
