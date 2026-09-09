"""Operações de materialização e publicação de releases de cache."""

from __future__ import annotations

from datetime import datetime, timezone
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time
from typing import Any, Iterable, Mapping, Sequence
from uuid import uuid4

import requests

from .carteira_4966_quality import validate_carteira_4966_quality
from .critical_screens import CRITICAL_SOURCE_TYPES, materialize_critical_screens_cache
from .derived_metrics import materialize_derived_metrics_cache
from .diagnostics import (
    DEFAULT_GATE_SPECS, build_runtime_manifest, count_placeholder_names,
    evaluate_alignment_gates, normalize_period_reference, sha256_file,
)
from .release_config import ReleaseConfig, add_release_cache_buster, get_release_config
from .update_state import UpdateRunStore, load_cache_update_result


DERIVED_TARGET_SPECS = {
    "derived_metrics": {
        "sources": ("dre", "principal", "ativo", "carteira_instrumentos"),
        "gate": "dre_consolidado",
        "kwargs": {
            "derived_cache_name": "derived_metrics",
            "dre_cache_name": "dre",
            "principal_cache_name": "principal",
            "carteira_instrumentos_cache_name": "carteira_instrumentos",
        },
    },
    "derived_metrics_individual": {
        "sources": ("dre_individual", "principal_individual", "ativo"),
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

    if selected & {"principal", "dre", "ativo", "carteira_instrumentos", "derived_metrics"}:
        targets.append("derived_metrics")

    if selected & {"principal_individual", "dre_individual", "ativo", "derived_metrics_individual"}:
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


def _publication_scope(selected_caches: Iterable[str]) -> tuple[list[str], list[str]]:
    selected = _sorted_cache_names(selected_caches)
    targets = get_postprocess_targets(selected)
    sources = [source for target in targets for source in _sources_for_target(target)]
    return _sorted_cache_names([*selected, *targets]), _sorted_cache_names(sources)


def _required_publication_gates(cache_names: Iterable[str]) -> list[str]:
    names = set(cache_names)
    return [
        key for key, spec in DEFAULT_GATE_SPECS.items()
        if names.intersection(spec["caches"])
    ]


def get_publishable_bundle(
    selected_caches: Iterable[str],
    *,
    materialization_details: Sequence[Mapping[str, Any]] | None = None,
    manifest_payload: Mapping[str, Any] | None = None,
) -> tuple[list[str], list[str]]:
    """Retorna o pacote inteiro ou nenhuma publicação; gates ausentes bloqueiam."""
    selected_caches = _sorted_cache_names(selected_caches)
    promised, sources = _publication_scope(selected_caches)
    if not promised:
        return [], ["nenhum cache selecionado"]
    payload = manifest_payload or {}
    warnings: list[str] = []
    quality_map = dict(payload.get("quality_checks") or {})
    for cache_name in _sorted_cache_names([*promised, *sources]):
        required = cache_name in INDIVIDUAL_CACHE_QUALITY_SPECS or cache_name in CACHE_FRAME_QUALITY_VALIDATORS
        check = quality_map.get(cache_name)
        if required and check is None:
            warnings.append(f"{cache_name}: validação de qualidade obrigatória ausente")
        elif check is not None and not bool(check.get("success")):
            warnings.append(f"{cache_name}: {check.get('message') or 'falha de qualidade'}")

    detail_map = {
        str(item.get("cache")): item for item in (materialization_details or []) if item.get("cache")
    }
    for target_name in get_postprocess_targets(selected_caches):
        failed_sources = [
            name for name in _sources_for_target(target_name)
            if name in quality_map and not quality_map[name].get("success")
        ]
        if failed_sources:
            warnings.append(f"{target_name}: fonte(s) reprovada(s): {', '.join(failed_sources)}")
        detail = detail_map.get(target_name) or {}
        if detail.get("status") != "ok":
            warnings.append(f"{target_name}: {detail.get('message') or 'materialização obrigatória ausente'}")

    gates = dict(payload.get("gates") or {})
    for key in _required_publication_gates(promised):
        gate = gates.get(key)
        if not gate or not gate.get("success"):
            warnings.append(f"{key}: {(gate or {}).get('message') or 'gate obrigatório ausente'}")
    return ([], warnings) if warnings else (promised, [])


def _fetch_release_manifest(release: ReleaseConfig, token: str | None = None) -> dict[str, Any]:
    url = add_release_cache_buster(f"{release.release_base_url}/manifest.json", "publication-plan")
    headers = {"Cache-Control": "no-cache", "Pragma": "no-cache"}
    if token:
        headers.update(_github_headers(token))
    response = _request_with_retries("GET", url, headers=headers, timeout=60)
    if response.status_code != 200:
        raise RuntimeError(
            f"manifesto remoto indisponível em {release.repo}@{release.tag} "
            f"(HTTP {response.status_code}); publicação bloqueada para preservar o manifesto global"
        )
    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError("manifesto remoto inválido; publicação bloqueada") from exc


def _validate_remote_manifest(payload: Any, release: ReleaseConfig) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("caches"), Mapping) or not payload["caches"]:
        raise ValueError("manifesto remoto ausente/inválido; publicação bloqueada para preservar entradas existentes")
    identity = payload.get("release") or {}
    if not isinstance(identity, Mapping):
        raise ValueError("identidade do manifesto remoto inválida")
    if identity.get("repo") != release.repo or identity.get("tag") != release.tag:
        raise ValueError("destino do manifesto remoto diverge do pacote; publicação bloqueada")
    if not isinstance(payload.get("expected_periods", {}), Mapping):
        raise ValueError("expected_periods do manifesto remoto inválido")
    if any(not isinstance(value, Mapping) for value in payload["caches"].values()):
        raise ValueError("entrada de cache inválida no manifesto remoto")
    return deepcopy(dict(payload))


def _confirm_remote_source(release: ReleaseConfig, cache_name: str, digest: str, token: str | None, asset_name: str | None = None) -> None:
    headers = {"Cache-Control": "no-cache", "Pragma": "no-cache"}
    if token:
        headers.update(_github_headers(token))
    url = add_release_cache_buster(
        f"{release.release_base_url}/{asset_name or f'{cache_name}_dados.parquet'}", digest, "source-proof",
    )
    response = _request_with_retries("GET", url, headers=headers, timeout=120, stream=True)
    try:
        if response.status_code != 200:
            raise RuntimeError(f"{cache_name}: fonte remota indisponível para confirmação; publicação bloqueada")
        actual = hashlib.sha256()
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            actual.update(chunk)
        if actual.hexdigest() != digest:
            raise RuntimeError(f"{cache_name}: hash remoto diverge do manifesto; publicação bloqueada")
    finally:
        response.close()


def _assert_complete_metadata(path: Path, cache_name: str) -> None:
    try:
        metadata = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{cache_name}: metadata ausente ou inválida") from exc
    if not isinstance(metadata, Mapping):
        raise ValueError(f"{cache_name}: metadata inválida")
    sections = [metadata]
    if isinstance(metadata.get("extra"), Mapping):
        sections.append(metadata["extra"])
    for section in sections:
        if (section.get("finalized") is False or section.get("partial") is True
                or section.get("status") in {"partial", "failed", "erro"}):
            raise ValueError(f"{cache_name}: extração parcial; publicação bloqueada")
        for key in ("falhas", "failures", "erros", "failed_windows", "remaining_windows", "pendentes", "periodos_pendentes", "periodos_falhos", "pending_periods", "failed_periods"):
            if section.get(key):
                raise ValueError(f"{cache_name}: metadata registra {key}; publicação bloqueada")


def prepare_release_publication(
    manager,
    *,
    selected_caches: Iterable[str],
    materialization_details: Sequence[Mapping[str, Any]] | None = None,
    release_config: ReleaseConfig | None = None,
    expected_periods: Mapping[str, str] | None = None,
    base_dir: Path | None = None,
    token: str | None = None,
    remote_manifest: Mapping[str, Any] | None = None,
) -> tuple[Path, dict[str, Any], list[str], list[tuple[Path, str]]]:
    """Valida/fecha o pacote e prepara manifesto global sem executar upload.

    Fontes já publicadas são confirmadas pelo conteúdo; as demais integram o
    upload. Derivados adicionais exigidos por essa inclusão precisam estar prontos.
    O chamador mantém mutation_lock durante materialização, preparação e upload.
    """
    root = Path(base_dir or getattr(manager, "base_dir", Path(__file__).resolve().parents[2])).resolve()
    release = release_config or get_release_config()
    selected = _sorted_cache_names(selected_caches)
    promised, sources = _publication_scope(selected)
    scope = _sorted_cache_names([*promised, *sources])
    if not selected:
        raise ValueError("nenhum cache selecionado para publicação")
    run_store = UpdateRunStore(root)
    for name in scope:
        latest_run = run_store.latest(name)
        if latest_run and (
            latest_run.get("status") in {"prepared", "extracting", "partial", "failed"}
            or latest_run.get("pending_periods") or latest_run.get("failed_periods")
        ):
            raise ValueError(f"{name}: execução registrada incompleta; publicação bloqueada")
        saved_result = load_cache_update_result(root, name)
        if saved_result and (
            saved_result.get("status") != "saved"
            or any(saved_result.get(key) for key in (
                "pending_periods", "failed_periods", "erros", "checkpoint_error", "persistence_error",
            ))
        ):
            raise ValueError(f"{name}: atualização registrada incompleta; publicação bloqueada")
    runtime = build_runtime_manifest(
        manager, cache_names=scope, release_config=release,
        expected_periods=expected_periods, include_hashes=True,
    )
    for name in selected:
        if name in {"bloprudencial", "mercado_credito_sgs"}:
            expected = (expected_periods or {}).get("monthly")
            record = runtime.get("caches", {}).get(name) or {}
            if expected and record.get("max_period_ref") != normalize_period_reference(expected):
                raise ValueError(f"{name}: competência máxima difere do alvo mensal {expected}")
    quality = validate_cache_quality(manager, scope)
    validation_payload = {**runtime, "quality_checks": quality}
    eligible, problems = get_publishable_bundle(
        selected, materialization_details=materialization_details, manifest_payload=validation_payload,
    )
    if not eligible:
        raise ValueError("pacote não está pronto: " + "; ".join(problems))
    for name in scope:
        record = runtime.get("caches", {}).get(name) or {}
        if not record.get("exists") or not record.get("sha256"):
            raise ValueError(f"{name}: fonte local ausente ou sem identidade; publicação bloqueada")
        cache = manager.get_cache(name)
        _assert_complete_metadata(cache.arquivo_metadata, name)
        cache_tag = getattr(cache, "release_tag", release.tag)
        cache_repo = getattr(cache, "release_repo", release.repo)
        if (cache_repo, cache_tag) != (release.repo, release.tag):
            raise ValueError(f"{name}: destino efetivo diverge do release selecionado")
    previous = _validate_remote_manifest(
        remote_manifest if remote_manifest is not None else _fetch_release_manifest(release, token), release,
    )
    upload_caches = list(promised)
    reused_sources = []
    for name in sources:
        if name in upload_caches:
            continue
        digest = runtime["caches"][name]["sha256"]
        old_digest = (previous["caches"].get(name) or {}).get("sha256")
        if old_digest == digest:
            source_asset_name = release_assets_for_cache(manager, name)[0][1]
            _confirm_remote_source(release, name, digest, token, source_asset_name)
            reused_sources.append({"cache": name, "sha256": digest})
        else:
            upload_caches.append(name)
    additional_targets = set(get_postprocess_targets(upload_caches)) - set(promised)
    if additional_targets:
        raise ValueError(
            "fontes locais divergentes (" + ", ".join(sorted(set(upload_caches) - set(promised)))
            + ") exigem preparar/publicar pacote ampliado com: " + ", ".join(sorted(additional_targets))
        )
    upload_caches = _sorted_cache_names(upload_caches)
    assets = collect_release_assets(manager, upload_caches)
    asset_records = []
    for path, name in assets:
        digest = sha256_file(path)
        if not digest:
            raise ValueError(f"{name}: asset local ausente")
        asset_records.append({"name": name, "sha256": digest, "size_bytes": path.stat().st_size})

    payload = deepcopy(previous)
    payload["caches"].update({name: runtime["caches"][name] for name in upload_caches})
    previous_expected = dict(previous.get("expected_periods") or {})
    proposed_expected = dict(expected_periods or {})
    # O alvo global trimestral só avança quando TODOS os seus gates fecham no
    # manifesto combinado. Publicações mensais preservam a referência trimestral.
    if proposed_expected.get("quarterly"):
        combined_gates = evaluate_alignment_gates(payload["caches"], expected_periods=proposed_expected)
        if all(gate.get("success") for gate in combined_gates.values()):
            previous_expected["quarterly"] = proposed_expected["quarterly"]
    # monthly global também pertence a mais de uma fonte. O alvo desta operação
    # fica em publication_expected_periods, sem reescrever o de fontes alheias.
    combined_gates = evaluate_alignment_gates(payload["caches"], expected_periods=previous_expected)
    payload.update({
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "release": release.to_dict(),
        "expected_periods": previous_expected,
        "publication_expected_periods": proposed_expected,
        "selected_caches": selected,
        "published_caches": upload_caches,
        "confirmed_source_assets": reused_sources,
        "postprocess_targets": get_postprocess_targets(selected),
        "materialization": list(materialization_details or []),
        "quality_checks": {**dict(previous.get("quality_checks") or {}), **quality},
        "gates": combined_gates,
        "summary": {
            "total_caches": len(payload["caches"]),
            "present_caches": sum(bool(record.get("exists")) for record in payload["caches"].values()),
            "total_gates": len(combined_gates),
            "successful_gates": sum(bool(gate.get("success")) for gate in combined_gates.values()),
        },
        "publication_assets": asset_records,
        "runtime_diagnostics": runtime,
    })
    path = root / "data" / "cache" / "publications" / uuid4().hex / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=False)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    assets.append((path, "manifest.json"))
    return path, payload, upload_caches, assets


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
    # Validate the complete input before the first remote mutation. Prepared
    # manifests bind each file to its reviewed digest; a changed candidate must
    # be prepared again, never uploaded under the old manifest.
    asset_paths = {}
    for path, name in assets:
        if name in asset_paths:
            raise ValueError(f"asset duplicado: {name}")
        if not path.is_file():
            raise FileNotFoundError(f"asset local ausente antes do upload: {name}")
        asset_paths[name] = path
    if "manifest.json" in asset_paths:
        manifest = json.loads(asset_paths["manifest.json"].read_text(encoding="utf-8"))
        for record in manifest.get("publication_assets", []):
            path = asset_paths.get(record["name"])
            if path is None or sha256_file(path) != record.get("sha256"):
                raise ValueError(f"candidato mudou após validação: {record['name']}; prepare o pacote novamente")

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
