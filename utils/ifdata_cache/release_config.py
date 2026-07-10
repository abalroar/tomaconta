"""Resolução compartilhada de configuração de release/cache."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import os
import time
from typing import Any, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


DEFAULT_RELEASE_REPO = "abalroar/tomaconta"
DEFAULT_RELEASE_TAG = "v1.1-cache"
DEFAULT_RAW_REPO = "abalroar/tomaconta"


@dataclass(frozen=True)
class ReleaseConfig:
    repo: str
    tag: str
    raw_repo: str
    release_base_url: str
    repo_source: str
    tag_source: str
    raw_repo_source: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def _normalize_value(value: Any, fallback: str) -> str:
    texto = str(value or "").strip()
    return texto or fallback


def _read_optional_secret(
    secrets_provider: Mapping[str, Any] | Any | None,
    key: str,
) -> str | None:
    if secrets_provider is None:
        return None
    try:
        if isinstance(secrets_provider, Mapping):
            value = secrets_provider.get(key)
        else:
            value = secrets_provider.get(key)
    except Exception:
        return None
    texto = str(value or "").strip()
    return texto or None


def _resolve_value(
    *,
    env_key: str,
    default: str,
    secrets_provider: Mapping[str, Any] | Any | None = None,
) -> tuple[str, str]:
    env_value = os.getenv(env_key)
    if env_value and env_value.strip():
        return env_value.strip(), f"env:{env_key}"

    secret_value = _read_optional_secret(secrets_provider, env_key)
    if secret_value:
        return secret_value, f"secret:{env_key}"

    return default, "default"


def resolve_release_repo(
    secrets_provider: Mapping[str, Any] | Any | None = None,
    default: str = DEFAULT_RELEASE_REPO,
) -> str:
    return _resolve_value(
        env_key="TOMACONTA_RELEASE_REPO",
        default=default,
        secrets_provider=secrets_provider,
    )[0]


def resolve_release_tag(
    secrets_provider: Mapping[str, Any] | Any | None = None,
    default: str = DEFAULT_RELEASE_TAG,
) -> str:
    return _resolve_value(
        env_key="TOMACONTA_RELEASE_TAG",
        default=default,
        secrets_provider=secrets_provider,
    )[0]


def resolve_raw_repo(
    secrets_provider: Mapping[str, Any] | Any | None = None,
    default: str = DEFAULT_RAW_REPO,
) -> str:
    return _resolve_value(
        env_key="TOMACONTA_RAW_REPO",
        default=default,
        secrets_provider=secrets_provider,
    )[0]


def build_release_base_url(
    repo: str | None = None,
    tag: str | None = None,
    *,
    secrets_provider: Mapping[str, Any] | Any | None = None,
) -> str:
    resolved_repo = _normalize_value(repo, resolve_release_repo(secrets_provider=secrets_provider))
    resolved_tag = _normalize_value(tag, resolve_release_tag(secrets_provider=secrets_provider))
    return f"https://github.com/{resolved_repo}/releases/download/{resolved_tag}"


def build_release_asset_url(
    asset_name: str,
    *,
    repo: str | None = None,
    tag: str | None = None,
    secrets_provider: Mapping[str, Any] | Any | None = None,
) -> str:
    return f"{build_release_base_url(repo, tag, secrets_provider=secrets_provider)}/{asset_name}"


def add_release_cache_buster(url: str, *parts: Any) -> str:
    """Adiciona query string para evitar asset antigo em cache/CDN do GitHub Releases."""
    parsed = urlsplit(str(url))
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    token_parts = [str(part).strip() for part in parts if str(part or "").strip()]
    token_parts.append(str(int(time.time() // 60)))
    query["cache_bust"] = "|".join(token_parts)
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode(query),
            parsed.fragment,
        )
    )


def get_release_config(
    secrets_provider: Mapping[str, Any] | Any | None = None,
) -> ReleaseConfig:
    repo, repo_source = _resolve_value(
        env_key="TOMACONTA_RELEASE_REPO",
        default=DEFAULT_RELEASE_REPO,
        secrets_provider=secrets_provider,
    )
    tag, tag_source = _resolve_value(
        env_key="TOMACONTA_RELEASE_TAG",
        default=DEFAULT_RELEASE_TAG,
        secrets_provider=secrets_provider,
    )
    raw_repo, raw_repo_source = _resolve_value(
        env_key="TOMACONTA_RAW_REPO",
        default=DEFAULT_RAW_REPO,
        secrets_provider=secrets_provider,
    )
    return ReleaseConfig(
        repo=repo,
        tag=tag,
        raw_repo=raw_repo,
        release_base_url=build_release_base_url(repo, tag),
        repo_source=repo_source,
        tag_source=tag_source,
        raw_repo_source=raw_repo_source,
    )
