"""Operações de materialização e publicação de releases de cache."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any, Iterable, Mapping, Sequence

import requests

from .carteira_4966_quality import validate_carteira_4966_quality
from .critical_screens import CRITICAL_SOURCE_TYPES, materialize_critical_screens_cache
from .derived_metrics import materialize_derived_metrics_cache
from .diagnostics import build_runtime_manifest, count_placeholder_names
from .release_config import ReleaseConfig, get_release_config


DERIVED_TARGET_SPECS = {
    "derived_metrics": {
        "sources": ("dre", "principal", "carteira_instrumentos"),
        "gate": "dre_consolidado",
        "kwargs": {
            "derived_cache_name": "derived_metrics",
            "dre_cache_name": "dre",
            "principal_cache_name": "principal",
            "carteira_instrumentos_cache_name": "carteira_instrumentos",
        },
    },
    "derived_metrics_individual": {
        "sources": ("dre_individual", "principal_individual"),
        "gate": "dre_individual",
        "kwargs": {
            "derived_cache_name": "derived_metrics_individual",
            "dre_cache_name": "dre_individual",
            "principal_cache_name": "principal_individual",
            # Não existe Relatório 16 individual: a métrica de ativos problemáticos
            # fica N/D na base individual em vez de herdar o consolidado.
            "carteira_instrumentos_cache_name": None,
        },
    },
}

CRITICAL_TRIGGER_CACHES = set(CRITICAL_SOURCE_TYPES) | {"bloprudencial", "critical_screens"}

PUBLISH_ORDER = [
    "principal",
    "principal_individual",
    "capital",
    "ativo",
    "passivo",
    "dre",
    "dre_individual",
    "carteira_pf",
    "carteira_pj",
    "carteira_instrumentos",
    "bloprudencial",
    "mercado_credito_sgs",
    "derived_metrics",
    "derived_metrics_individual",
    "critical_screens",
]

INDIVIDUAL_CACHE_MIN_PERIODS = 13
INDIVIDUAL_CACHE_QUALITY_SPECS = {
    "principal_individual": {"min_periods": INDIVIDUAL_CACHE_MIN_PERIODS},
    "dre_individual": {"min_periods": INDIVIDUAL_CACHE_MIN_PERIODS},
}

CACHE_FRAME_QUALITY_VALIDATORS = {
    "carteira_instrumentos": validate_carteira_4966_quality,
}


def _unique_cache_names(cache_names: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for cache_name in cache_names:
        nome = str(cache_name or "").strip()
        if not nome or nome in seen:
            continue
        seen.add(nome)
        output.append(nome)
    return output


def _sorted_cache_names(cache_names: Iterable[str]) -> list[str]:
    order_map = {cache_name: idx for idx, cache_name in enumerate(PUBLISH_ORDER)}
    return sorted(
        _unique_cache_names(cache_names),
        key=lambda cache_name: (order_map.get(cache_name, 999), cache_name),
    )


def get_postprocess_targets(cache_names: Iterable[str]) -> list[str]:
    selected = set(_unique_cache_names(cache_names))
    targets: list[str] = []

    if selected & {"principal", "dre", "derived_metrics"}:
        targets.append("derived_metrics")

    if selected & {"principal_individual", "dre_individual", "derived_metrics_individual"}:
        targets.append("derived_metrics_individual")

    if selected & CRITICAL_TRIGGER_CACHES:
        targets.append("critical_screens")

    return _sorted_cache_names(targets)


def _sources_for_target(target_name: str) -> list[str]:
    if target_name in DERIVED_TARGET_SPECS:
        return list(DERIVED_TARGET_SPECS[target_name]["sources"])
    if target_name == "critical_screens":
        return _sorted_cache_names(CRITICAL_TRIGGER_CACHES - {"critical_screens"})
    return []


def validate_cache_quality(manager, cache_names: Iterable[str]) -> dict[str, dict[str, Any]]:
    """Valida identidade, cobertura e estrutura antes de publicar caches."""
    checks: dict[str, dict[str, Any]] = {}
    for cache_name in _sorted_cache_names(cache_names):
        spec = INDIVIDUAL_CACHE_QUALITY_SPECS.get(cache_name)
        frame_validator = CACHE_FRAME_QUALITY_VALIDATORS.get(cache_name)
        if spec is None and frame_validator is None:
            continue

        cache = manager.get_cache(cache_name) if manager else None
        if cache is None:
            checks[cache_name] = {
                "success": False,
                "message": "cache não configurado",
                "period_count": 0,
                "placeholder_count": 0,
            }
            continue

        result = cache.carregar_local()
        if not result.sucesso or result.dados is None:
            checks[cache_name] = {
                "success": False,
                "message": result.mensagem or "cache local indisponível",
                "period_count": 0,
                "placeholder_count": 0,
            }
            continue

        df = result.dados
        if frame_validator is not None:
            checks[cache_name] = frame_validator(df)
            continue

        if df.empty:
            checks[cache_name] = {
                "success": False,
                "message": result.mensagem or "cache local indisponível",
                "period_count": 0,
                "placeholder_count": 0,
            }
            continue

        required = {"CodInst", "Instituição", "Período"}
        missing = sorted(required - set(df.columns))
        period_count = int(df["Período"].dropna().astype(str).nunique()) if "Período" in df.columns else 0
        placeholder_count = count_placeholder_names(df)
        duplicate_count = (
            int(df.duplicated(subset=["CodInst", "Período"]).sum())
            if {"CodInst", "Período"}.issubset(df.columns)
            else 0
        )
        unstable_name_count = (
            int((df.groupby("CodInst", dropna=False)["Instituição"].nunique(dropna=False) > 1).sum())
            if {"CodInst", "Instituição"}.issubset(df.columns)
            else 0
        )
        min_periods = int(spec["min_periods"])
        failures = []
        if missing:
            failures.append(f"colunas ausentes: {', '.join(missing)}")
        if period_count < min_periods:
            failures.append(f"cobertura insuficiente: {period_count} períodos; mínimo {min_periods}")
        if placeholder_count:
            failures.append(f"{placeholder_count} nome(s) placeholder")
        if duplicate_count:
            failures.append(f"{duplicate_count} chave(s) CodInst/Período duplicada(s)")
        if unstable_name_count:
            failures.append(f"{unstable_name_count} CodInst(s) com rótulos históricos inconsistentes")

        checks[cache_name] = {
            "success": not failures,
            "message": "; ".join(failures) if failures else "ok",
            "period_count": period_count,
            "minimum_period_count": min_periods,
            "placeholder_count": placeholder_count,
            "duplicate_identity_count": duplicate_count,
            "unstable_name_count": unstable_name_count,
            "record_count": int(len(df)),
        }
    return checks


def _hydrate_source_caches(
    manager,
    cache_names: Iterable[str],
    *,
    local_first: Iterable[str] = (),
) -> tuple[list[dict[str, Any]], list[str]]:
    prefer_local = set(_unique_cache_names(local_first))
    details: list[dict[str, Any]] = []
    failures: list[str] = []

    for cache_name in _sorted_cache_names(cache_names):
        cache = manager.get_cache(cache_name) if manager else None
        forced_remote = False

        # Para materialização/publicação consistente, sempre preferimos a fonte
        # local quando ela já existe. Isso evita misturar um cache recém-atualizado
        # com dependências antigas baixadas do release remoto.
        if cache is not None and cache.existe():
            result = cache.carregar_local()
            if not result.sucesso and cache_name not in prefer_local:
                forced_remote = True
                result = manager.carregar(cache_name, forcar_remoto=True)
        else:
            forced_remote = cache_name not in prefer_local
            result = manager.carregar(cache_name, forcar_remoto=forced_remote)

        ok = bool(result.sucesso and result.dados is not None)
        details.append(
            {
                "cache": cache_name,
                "status": "ok" if ok else "erro",
                "message": result.mensagem,
                "source": result.fonte,
                "forced_remote": forced_remote,
            }
        )
        if not ok:
            failures.append(f"{cache_name}: {result.mensagem}")

    return details, failures


def materialize_for_publication(
    manager,
    *,
    cache_names: Iterable[str],
    base_dir: Path | None = None,
    force: bool = True,
    save_bundled: bool = True,
) -> list[dict[str, Any]]:
    root = Path(base_dir).resolve() if base_dir else Path(__file__).resolve().parents[2]
    selected = _unique_cache_names(cache_names)
    details: list[dict[str, Any]] = []

    for target_name in get_postprocess_targets(selected):
        source_details, failures = _hydrate_source_caches(
            manager,
            _sources_for_target(target_name),
            local_first=selected,
        )

        if failures:
            details.append(
                {
                    "cache": target_name,
                    "stage": "hydrate",
                    "status": "erro",
                    "message": "; ".join(failures),
                    "sources": source_details,
                }
            )
            continue

        if target_name in DERIVED_TARGET_SPECS:
            result = materialize_derived_metrics_cache(
                base_dir=root,
                manager=manager,
                force=force,
                **DERIVED_TARGET_SPECS[target_name]["kwargs"],
            )
        else:
            result = materialize_critical_screens_cache(
                base_dir=root,
                manager=manager,
                force=force,
                save_bundled=save_bundled,
                allow_remote_source_download=False,
            )

        details.append(
            {
                "cache": target_name,
                "stage": "materialize",
                "status": "ok" if result.sucesso else "erro",
                "message": result.mensagem,
                "sources": source_details,
            }
        )

    return details


def write_release_manifest(
    manager,
    *,
    base_dir: Path | None = None,
    release_config: ReleaseConfig | None = None,
    expected_periods: Mapping[str, str] | None = None,
    selected_caches: Iterable[str] = (),
    materialization_details: Sequence[Mapping[str, Any]] | None = None,
    include_hashes: bool = True,
) -> tuple[Path, dict[str, Any]]:
    root = Path(base_dir).resolve() if base_dir else Path(__file__).resolve().parents[2]
    release = release_config or get_release_config()
    runtime_manifest = build_runtime_manifest(
        manager,
        release_config=release,
        expected_periods=expected_periods,
        include_hashes=include_hashes,
    )
    selected = _sorted_cache_names(selected_caches)
    postprocess_targets = get_postprocess_targets(selected)
    quality_scope = [*selected, *postprocess_targets]
    for target_name in postprocess_targets:
        quality_scope.extend(_sources_for_target(target_name))
    quality_checks = validate_cache_quality(
        manager,
        quality_scope,
    )
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "release": release.to_dict(),
        "expected_periods": dict(expected_periods or {}),
        "selected_caches": selected,
        "postprocess_targets": postprocess_targets,
        "materialization": list(materialization_details or []),
        "quality_checks": quality_checks,
        "caches": runtime_manifest.get("caches", {}),
        "gates": runtime_manifest.get("gates", {}),
        "summary": runtime_manifest.get("summary", {}),
    }
    manifest_path = root / "data" / "cache" / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path, payload


def get_publishable_bundle(
    selected_caches: Iterable[str],
    *,
    materialization_details: Sequence[Mapping[str, Any]] | None = None,
    manifest_payload: Mapping[str, Any] | None = None,
) -> tuple[list[str], list[str]]:
    selected = _sorted_cache_names(selected_caches)
    warnings: list[str] = []
    quality_map = dict((manifest_payload or {}).get("quality_checks") or {})
    failed_quality = {
        cache_name
        for cache_name, check in quality_map.items()
        if not bool((check or {}).get("success"))
    }
    publishable = [cache_name for cache_name in selected if cache_name not in failed_quality]
    for cache_name in selected:
        if cache_name in failed_quality:
            check = quality_map.get(cache_name) or {}
            warnings.append(f"{cache_name}: {check.get('message') or 'falha de qualidade'}")
    detail_map = {
        str(item.get("cache")): item
        for item in (materialization_details or [])
        if item.get("cache")
    }
    gate_map = dict((manifest_payload or {}).get("gates") or {})

    for target_name in get_postprocess_targets(selected):
        failed_sources = [source for source in _sources_for_target(target_name) if source in failed_quality]
        if failed_sources:
            warnings.append(
                f"{target_name}: fonte(s) reprovada(s) no gate de qualidade: {', '.join(failed_sources)}"
            )
            continue
        detail = detail_map.get(target_name) or {}
        if detail.get("status") != "ok":
            if detail.get("message"):
                warnings.append(f"{target_name}: {detail['message']}")
            continue

        gate_key = None
        if target_name in DERIVED_TARGET_SPECS:
            gate_key = str(DERIVED_TARGET_SPECS[target_name]["gate"])
        elif target_name == "critical_screens":
            gate_key = "snapshot_peers"

        gate = gate_map.get(gate_key) if gate_key else None
        if gate_key and gate and not gate.get("success"):
            warnings.append(f"{target_name}: {gate.get('message')}")
            continue

        publishable.append(target_name)

    return _sorted_cache_names(publishable), warnings


def release_assets_for_cache(manager, cache_name: str) -> list[tuple[Path, str]]:
    cache = manager.get_cache(cache_name)
    if cache is None:
        raise ValueError(f"cache não configurado: {cache_name}")

    data_path = cache.arquivo_dados if cache.arquivo_dados.exists() else cache.arquivo_dados_pickle
    if not data_path.exists():
        raise FileNotFoundError(f"arquivo de dados ausente para {cache_name}: {data_path}")
    if not cache.arquivo_metadata.exists():
        raise FileNotFoundError(f"metadata ausente para {cache_name}: {cache.arquivo_metadata}")

    data_asset = f"{cache_name}_dados.parquet" if data_path.suffix == ".parquet" else f"{cache_name}_cache.pkl"
    assets = [
        (data_path, data_asset),
        (cache.arquivo_metadata, f"{cache_name}_metadata.json"),
    ]
    extra_assets_fn = getattr(cache, "extra_release_assets", None)
    if callable(extra_assets_fn):
        for path, asset_name in extra_assets_fn():
            if not path.exists():
                raise FileNotFoundError(f"asset extra ausente para {cache_name}: {path}")
            assets.append((path, asset_name))
    return assets


def collect_release_assets(
    manager,
    cache_names: Iterable[str],
    *,
    manifest_path: Path | None = None,
) -> list[tuple[Path, str]]:
    assets: list[tuple[Path, str]] = []
    for cache_name in _sorted_cache_names(cache_names):
        assets.extend(release_assets_for_cache(manager, cache_name))
    if manifest_path is not None:
        assets.append((manifest_path, "manifest.json"))
    return assets


def _request_with_retries(
    method: str,
    url: str,
    *,
    max_attempts: int = 3,
    retryable_statuses: Iterable[int] = (408, 429, 500, 502, 503, 504),
    **kwargs,
):
    attempt = 0
    while True:
        attempt += 1
        try:
            response = requests.request(method, url, **kwargs)
        except requests.exceptions.RequestException:
            if attempt >= max_attempts:
                raise
            time.sleep(min(2 ** (attempt - 1), 4))
            continue

        if response.status_code in set(retryable_statuses) and attempt < max_attempts:
            time.sleep(min(2 ** (attempt - 1), 4))
            continue
        return response


def _github_headers(token: str, *, content_type: str | None = None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def github_error_detail(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:300].strip()

    if not isinstance(payload, Mapping):
        return response.text[:300].strip()

    parts = []
    message = str(payload.get("message") or "").strip()
    documentation_url = str(payload.get("documentation_url") or "").strip()
    if message:
        parts.append(message)
    if documentation_url:
        parts.append(f"docs: {documentation_url}")
    return " | ".join(parts)[:300]


def github_permission_hint(repo: str, status_code: int, detail: str) -> str:
    normalized = detail.lower()
    if status_code == 403 and (
        "resource not accessible by personal access token" in normalized
        or "fine-grained personal access token" in normalized
        or "contents" in normalized
    ):
        return (
            f" Ação: configure um `GITHUB_PAT`/`GH_TOKEN` com permissão `Contents: Read and write` "
            f"para `{repo}` (ou PAT clássico com escopo `repo`) e remova/atualize tokens somente leitura."
        )
    if status_code == 403:
        return (
            f" Ação: confira se o token tem escrita em releases/assets de `{repo}` "
            "(fine-grained PAT: `Contents: Read and write`; PAT clássico: `repo`)."
        )
    return ""


def upload_release_assets(
    *,
    repo: str,
    tag: str,
    assets: Sequence[tuple[Path, str]],
    token: str,
) -> dict[str, Any]:
    headers = _github_headers(token)

    release_url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
    response = _request_with_retries("GET", release_url, headers=headers, timeout=30)
    if response.status_code != 200:
        detalhe = github_error_detail(response)
        hint = github_permission_hint(repo, response.status_code, detalhe)
        raise RuntimeError(
            f"release alvo indisponível em {repo}@{tag} (HTTP {response.status_code}) {detalhe}.{hint}"
        )

    release_data = response.json()
    upload_url = str(release_data["upload_url"]).replace("{?name,label}", "")
    existing_assets = {asset["name"]: asset["id"] for asset in release_data.get("assets", [])}
    uploaded: list[str] = []

    for path, asset_name in assets:
        asset_id = existing_assets.get(asset_name)
        if asset_id is not None:
            delete_url = f"https://api.github.com/repos/{repo}/releases/assets/{asset_id}"
            delete_resp = _request_with_retries("DELETE", delete_url, headers=headers, timeout=30)
            if delete_resp.status_code not in {204, 404}:
                detalhe = github_error_detail(delete_resp)
                hint = github_permission_hint(repo, delete_resp.status_code, detalhe)
                raise RuntimeError(
                    f"falha ao remover asset antigo {asset_name} ({delete_resp.status_code}) {detalhe}.{hint}"
                )

        upload_headers = _github_headers(token, content_type="application/octet-stream")
        upload_resp = None
        for attempt in range(1, 4):
            with path.open("rb") as handle:
                try:
                    upload_resp = requests.post(
                        f"{upload_url}?name={asset_name}",
                        headers=upload_headers,
                        data=handle,
                        timeout=300,
                    )
                except requests.exceptions.RequestException as exc:
                    if attempt >= 3:
                        raise RuntimeError(f"falha de rede ao publicar asset {asset_name}: {exc}") from exc
                    time.sleep(min(2 ** (attempt - 1), 4))
                    continue

            if upload_resp.status_code in {200, 201}:
                break
            if upload_resp.status_code not in {408, 429, 500, 502, 503, 504} or attempt >= 3:
                detalhe = github_error_detail(upload_resp)
                hint = github_permission_hint(repo, upload_resp.status_code, detalhe)
                raise RuntimeError(
                    f"falha ao publicar asset {asset_name} ({upload_resp.status_code}) {detalhe}.{hint}"
                )
            time.sleep(min(2 ** (attempt - 1), 4))

        uploaded.append(asset_name)

    return {"repo": repo, "tag": tag, "assets": uploaded}
