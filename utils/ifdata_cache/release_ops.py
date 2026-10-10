"""Operações de materialização e publicação de releases de cache."""

from __future__ import annotations

from datetime import datetime, timezone
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import time
from typing import Any, Iterable, Mapping, Sequence
from uuid import uuid4

import requests

from .carteira_4966_quality import validate_carteira_4966_quality
from .base import CacheResult
from .critical_screens import CRITICAL_SOURCE_TYPES, materialize_critical_screens_cache
from .derived_metrics import materialize_derived_metrics_cache
from .diagnostics import (
    DEFAULT_GATE_SPECS, build_runtime_manifest, count_placeholder_names,
    evaluate_alignment_gates, normalize_period_reference, sha256_file,
)
from .release_config import ReleaseConfig, add_release_cache_buster, get_release_config
from .update_state import (
    UpdateRunStore, load_cache_update_result, mutation_lock, write_cache_update_result,
)
from .institution_registry import INSTITUTION_NAMED_CACHE_NAMES, validate_institution_names


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
        "sources": ("dre_individual", "principal_individual"),
        "gate": "dre_individual",
        "kwargs": {
            "derived_cache_name": "derived_metrics_individual",
            "dre_cache_name": "dre_individual",
            "principal_cache_name": "principal_individual",
            # O custo de crédito individual exige o denominador do Rel. 1
            # individual; o Rel. 2 prudencial não pode completar esse recorte.
            "ativo_cache_name": None,
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
    "cosif_4010",
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


class RemoteAssetHashMismatch(RuntimeError):
    """Os bytes remotos divergem do hash esperado para um asset específico."""


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

    if selected.intersection({"derived_metrics", *DERIVED_TARGET_SPECS["derived_metrics"]["sources"]}):
        targets.append("derived_metrics")

    if selected.intersection({"derived_metrics_individual", *DERIVED_TARGET_SPECS["derived_metrics_individual"]["sources"]}):
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


def _materialization_targets(cache_names: Iterable[str]) -> list[str]:
    """Fecha os consumidores das fontes obrigatórias, sem acrescentar fontes alheias."""
    scope = set(_unique_cache_names(cache_names))
    targets: set[str] = set()
    while True:
        previous = set(scope)
        targets.update(get_postprocess_targets(scope))
        scope.update(targets)
        for target in targets:
            scope.update(_sources_for_target(target))
        if scope == previous:
            return _sorted_cache_names(targets)


def validate_cache_quality(manager, cache_names: Iterable[str]) -> dict[str, dict[str, Any]]:
    """Valida identidade, cobertura e estrutura antes de publicar caches."""
    checks: dict[str, dict[str, Any]] = {}
    for cache_name in _sorted_cache_names(cache_names):
        spec = INDIVIDUAL_CACHE_QUALITY_SPECS.get(cache_name)
        frame_validator = CACHE_FRAME_QUALITY_VALIDATORS.get(cache_name)
        check_names = cache_name in INSTITUTION_NAMED_CACHE_NAMES
        if spec is None and frame_validator is None and not check_names:
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
        if check_names:
            names_valid, names_message = validate_institution_names(df)
            if not names_valid and spec is None and frame_validator is None:
                checks[cache_name] = {
                    "success": False, "message": names_message,
                    "record_count": len(df), "placeholder_count": count_placeholder_names(df),
                }
                continue
        if frame_validator is not None:
            check = dict(frame_validator(df))
            if check_names and not names_valid:
                check["success"] = False
                check["message"] = "; ".join(filter(None, [check.get("message"), names_message]))
            checks[cache_name] = check
            continue

        if spec is None:
            checks[cache_name] = {"success": True, "message": "ok", "record_count": len(df)}
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
        if check_names and not names_valid:
            failures.append(names_message)
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

        # A fonte selecionada precisa estar salva no runtime. Dependências podem
        # usar o bundle publicado, validado pela mesma leitura de dados/metadata.
        selected = cache_name in prefer_local
        runtime_exists = cache is not None and cache.existe()
        readable_exists = runtime_exists or (
            cache is not None and not selected
            and getattr(cache, "existe_leitura", cache.existe)()
        )
        if readable_exists:
            result = cache.carregar_local()
            resolve_paths = getattr(cache, "coherent_read_paths", None)
            if selected and result.sucesso and callable(resolve_paths):
                try:
                    data_path, _ = resolve_paths()
                    if data_path not in {cache.arquivo_dados_runtime, cache.arquivo_dados_pickle}:
                        raise ValueError("fonte atualizada não seleciona a geração de runtime")
                except (OSError, ValueError) as exc:
                    result = CacheResult(False, f"Fonte atualizada local indisponível: {exc}", fonte="nenhum")
            if not result.sucesso and cache_name not in prefer_local:
                forced_remote = True
                result = manager.carregar(cache_name, forcar_remoto=True)
        elif cache_name in prefer_local:
            details.append({"cache": cache_name, "status": "erro",
                            "message": "fonte atualizada local ausente; fallback remoto bloqueado",
                            "source": "nenhum", "forced_remote": False})
            failures.append(f"{cache_name}: fonte atualizada local ausente")
            continue
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
    save_bundled: bool = False,
) -> list[dict[str, Any]]:
    root = _operation_root(manager, base_dir)
    with mutation_lock(root, owner={"label": "materialização"}):
        return _materialize_for_publication(
            manager, cache_names=cache_names, base_dir=root,
            force=force, save_bundled=save_bundled,
        )


def _operation_root(manager=None, base_dir: Path | None = None) -> Path:
    return Path(base_dir or getattr(manager, "base_dir", Path(__file__).resolve().parents[2])).resolve()


def _materialize_for_publication(
    manager,
    *,
    cache_names: Iterable[str],
    base_dir: Path | None = None,
    force: bool = True,
    save_bundled: bool = False,
) -> list[dict[str, Any]]:
    root = Path(base_dir).resolve() if base_dir else Path(__file__).resolve().parents[2]
    selected = _unique_cache_names(cache_names)
    details: list[dict[str, Any]] = []
    run_store = UpdateRunStore(root)

    for target_name in _materialization_targets(selected):
        run = run_store.create(target_name, periods=["materialization"], mode="rebuild",
                               options={"sources": _sources_for_target(target_name)})
        run = run_store.finish(run, "extracting")
        pending_result = {"run_id": run["run_id"], "status": "extracting", "finalized": False,
                          "requested_periods": ["materialization"], "extracted_periods": [],
                          "persisted_periods": [], "pending_periods": ["materialization"],
                          "failed_periods": {}}
        write_cache_update_result(root, target_name, pending_result)
        source_details: list[dict[str, Any]] = []
        stage = "hydrate"
        success = False
        try:
            source_details, failures = _hydrate_source_caches(
                manager, _sources_for_target(target_name), local_first=selected,
            )
            if failures:
                raise ValueError("; ".join(failures))
            stage = "materialize"
            if target_name in DERIVED_TARGET_SPECS:
                result = materialize_derived_metrics_cache(
                    base_dir=root, manager=manager, force=force,
                    **DERIVED_TARGET_SPECS[target_name]["kwargs"],
                )
            else:
                result = materialize_critical_screens_cache(
                    base_dir=root, manager=manager, force=force, save_bundled=save_bundled,
                    allow_remote_source_download=False,
                )
            message = result.mensagem
            if not result.sucesso:
                raise ValueError(message)
            # A successful return is confirmed by the persisted output pair.
            for path, name in release_assets_for_cache(manager, target_name):
                if not sha256_file(path):
                    raise ValueError(f"asset materializado sem identidade: {name}")
            _assert_complete_metadata(manager.get_cache(target_name).arquivo_metadata, target_name)
            receipt = {**pending_result, "status": "saved", "finalized": True,
                       "extracted_periods": ["materialization"],
                       "persisted_periods": ["materialization"], "pending_periods": []}
            write_cache_update_result(root, target_name, receipt)
            run_store.record_result(run, receipt)
            success = True
        except Exception as exc:
            message = str(exc)
            failed_receipt = {**pending_result, "status": "failed",
                              "failed_periods": {"materialization": message}}
            try:
                write_cache_update_result(root, target_name, failed_receipt)
                run_store.record_result(run, failed_receipt)
            except Exception as receipt_exc:
                message += f"; confirmação da falha indisponível: {receipt_exc}"
        details.append({"cache": target_name, "stage": stage, "status": "ok" if success else "erro",
                        "message": message, "sources": source_details, "run_id": run["run_id"]})

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
    root = _operation_root(manager, base_dir)
    with mutation_lock(root, owner={"label": "diagnóstico de publicação"}):
        return _write_release_manifest(
            manager, base_dir=root, release_config=release_config,
            expected_periods=expected_periods, selected_caches=selected_caches,
            materialization_details=materialization_details, include_hashes=include_hashes,
        )


def _write_release_manifest(
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
    _write_json_atomic(manifest_path, payload)
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


def _publication_scope(selected_caches: Iterable[str]) -> tuple[list[str], list[str]]:
    selected = _sorted_cache_names(selected_caches)
    targets = _materialization_targets(selected)
    sources = [source for target in targets for source in _sources_for_target(target)]
    return _sorted_cache_names([*selected, *targets]), _sorted_cache_names(sources)


def _required_publication_gates(cache_names: Iterable[str]) -> list[str]:
    names = set(cache_names)
    return [
        key for key, spec in DEFAULT_GATE_SPECS.items()
        if names.intersection(spec["caches"])
    ]


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


def _validate_remote_manifest(payload: Any, release: ReleaseConfig, *, allow_empty: bool = False) -> dict[str, Any]:
    if payload == {} and allow_empty:
        return {"caches": {}, "release": release.to_dict()}
    if not isinstance(payload, Mapping) or not isinstance(payload.get("caches"), Mapping):
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
        metadata_bytes = bytearray() if str(asset_name or "").endswith("_metadata.json") else None
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            actual.update(chunk)
            if metadata_bytes is not None:
                metadata_bytes.extend(chunk)
        if metadata_bytes is not None:
            try:
                metadata = json.loads(metadata_bytes)
            except (ValueError, UnicodeDecodeError) as exc:
                raise RuntimeError(f"{cache_name}: metadata remota inválida; publicação bloqueada") from exc
            if not isinstance(metadata, Mapping):
                raise RuntimeError(f"{cache_name}: metadata remota inválida; publicação bloqueada")
        if actual.hexdigest() != digest:
            raise RemoteAssetHashMismatch(f"{cache_name}: hash remoto diverge do manifesto; publicação bloqueada")
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
                or section.get("truncado") is True
                or section.get("status") in {"partial", "failed", "erro"}):
            raise ValueError(f"{cache_name}: extração parcial; publicação bloqueada")
        for key in ("falhas", "failures", "erros", "failed_windows", "remaining_windows", "pendentes", "periodos_pendentes", "periodos_falhos", "pending_periods", "failed_periods", "persistence_error", "checkpoint_error", "callback_error"):
            if section.get(key):
                raise ValueError(f"{cache_name}: metadata registra {key}; publicação bloqueada")



def _assert_required_native_assets(manager, cache_name: str) -> None:
    """Exige o pacote declarado pelo adaptador, mesmo quando o coletor omite ausentes."""
    if cache_name not in {"taxas_juros_historico", "scr_data", "spb_meios_pagamento"}:
        return
    cache = manager.get_cache(cache_name)
    manifest_path = Path(cache.manifest_path)
    if not manifest_path.is_file():
        raise ValueError(f"{cache_name}: asset obrigatório ausente: {manifest_path.name}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{cache_name}: manifesto do adaptador inválido") from exc
    if not isinstance(manifest, Mapping):
        raise ValueError(f"{cache_name}: manifesto do adaptador inválido")
    required = []
    if cache_name == "spb_meios_pagamento":
        paths = cache.dataset_paths()
        declared = manifest.get("datasets")
        if not isinstance(declared, Mapping) or set(declared) - set(paths):
            raise ValueError(f"{cache_name}: datasets declarados no manifesto inválidos")
        required.extend(paths[key] for key in declared)
    else:
        required.extend(cache.dimension_paths().values())
        if cache_name == "scr_data":
            try:
                metadata = json.loads(cache.arquivo_metadata.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise ValueError(f"{cache_name}: metadata ausente ou inválida") from exc
            if not isinstance(metadata, Mapping):
                raise ValueError(f"{cache_name}: metadata inválida")
            sections = [metadata, metadata.get("extra"), metadata.get("info_extra")]
            for section in sections:
                if not isinstance(section, Mapping) or "anos_materializados" not in section:
                    continue
                years = section["anos_materializados"]
                if (not isinstance(years, list)
                        or any(not str(year).isdigit() or len(str(year)) != 4 for year in years)):
                    raise ValueError(f"{cache_name}: anos materializados declarados inválidos")
                required.extend(cache.annual_path(year) for year in years)
    for path in dict.fromkeys(Path(path) for path in required):
        if not path.is_file():
            raise ValueError(f"{cache_name}: asset obrigatório ausente: {path.name}")


def _assert_complete_update(root: Path, cache_name: str) -> None:
    result = load_cache_update_result(root, cache_name)
    if result and (
        result.get("status") != "saved"
        or any(result.get(key) for key in (
            "pending_periods", "failed_periods", "erros", "errors",
            "checkpoint_error", "persistence_error", "callback_error",
        ))
        or result.get("finalized") is False
    ):
        raise ValueError(f"{cache_name}: atualização registrada incompleta; publicação bloqueada")
    latest = UpdateRunStore(root).latest(cache_name)
    if not latest or latest.get("status") == "superseded":
        return
    status = latest.get("status")
    confirmation_errors = (latest.get("pending_periods") or latest.get("failed_periods")
                           or latest.get("checkpoint_error") or latest.get("persistence_error")
                           or latest.get("callback_error"))
    if (status in {"prepared", "extracting", "partial", "failed"} or confirmation_errors
            or (status in {"validating", "publishing", "publish_failed"} and not result)):
        raise ValueError(f"{cache_name}: execução registrada incompleta; publicação bloqueada")
    # A publishing failure may hold its error in the run receipt. With a complete
    # ledger this is a retryable publication error; extraction errors remain above.
    if latest.get("error") and status != "publish_failed":
        raise ValueError(f"{cache_name}: execução sem confirmação completa; publicação bloqueada")


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(path)
    finally:
        temp_path.unlink(missing_ok=True)


def _manifest_digest(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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
    """Fecha o pacote completo, preservando entradas de outras publicações.

    O chamador mantém mutation_lock durante materialização, preparação e upload.
    O candidato identifica as fontes reutilizadas, para bloquear alterações entre
    essas etapas antes da mutação remota.
    """
    root = _operation_root(manager, base_dir)
    with mutation_lock(root, owner={"label": "preparação de publicação"}):
        return _prepare_release_publication(
            manager, selected_caches=selected_caches,
            materialization_details=materialization_details, release_config=release_config,
            expected_periods=expected_periods, base_dir=root, token=token,
            remote_manifest=remote_manifest,
        )


def _prepare_release_publication(
    manager,
    *,
    selected_caches: Iterable[str],
    materialization_details: Sequence[Mapping[str, Any]] | None,
    release_config: ReleaseConfig | None,
    expected_periods: Mapping[str, str] | None,
    base_dir: Path,
    token: str | None,
    remote_manifest: Mapping[str, Any] | None,
) -> tuple[Path, dict[str, Any], list[str], list[tuple[Path, str]]]:
    release = release_config or get_release_config()
    selected = _sorted_cache_names(selected_caches)
    promised, sources = _publication_scope(selected)
    scope = _sorted_cache_names([*promised, *sources])
    if not selected:
        raise ValueError("nenhum cache selecionado para publicação")
    for name in scope:
        _assert_complete_update(base_dir, name)
        _assert_required_native_assets(manager, name)
    runtime = build_runtime_manifest(
        manager, cache_names=scope, release_config=release,
        expected_periods=expected_periods, include_hashes=True,
    )
    quality = validate_cache_quality(manager, scope)
    _, problems = get_publishable_bundle(
        selected, materialization_details=materialization_details,
        manifest_payload={**runtime, "quality_checks": quality},
    )
    # The diagnostic helper remains compatible. Publication closes every
    # promised derivative, source validation and alignment gate.
    detail_map = {str(item.get("cache")): item for item in materialization_details or []}
    for target in _materialization_targets(selected):
        detail = detail_map.get(target) or {}
        if detail.get("status") != "ok":
            problems.append(f"{target}: {detail.get('message') or 'materialização obrigatória ausente'}")
        for source in detail.get("sources") or []:
            if source.get("status") != "ok":
                problems.append(f"{target}: fonte {source.get('cache')}: {source.get('message') or 'falha'}")
    for name in scope:
        required = (name in INDIVIDUAL_CACHE_QUALITY_SPECS
                    or name in CACHE_FRAME_QUALITY_VALIDATORS
                    or name in INSTITUTION_NAMED_CACHE_NAMES)
        check = quality.get(name)
        if required and check is None:
            problems.append(f"{name}: validação de qualidade obrigatória ausente")
        elif check is not None and not check.get("success"):
            problems.append(f"{name}: {check.get('message') or 'falha de qualidade'}")
    for key in _required_publication_gates(scope):
        gate = runtime.get("gates", {}).get(key) or {}
        if not gate.get("success"):
            problems.append(f"{key}: {gate.get('message') or 'gate obrigatório ausente'}")
    if problems:
        raise ValueError("pacote não está pronto: " + "; ".join(dict.fromkeys(problems)))
    for name in scope:
        record = runtime.get("caches", {}).get(name) or {}
        if not record.get("exists") or not record.get("sha256") or not record.get("metadata_sha256"):
            raise ValueError(f"{name}: fonte local ausente ou sem identidade; publicação bloqueada")
        cache = manager.get_cache(name)
        _assert_complete_metadata(cache.arquivo_metadata, name)
        if (getattr(cache, "release_repo", release.repo), getattr(cache, "release_tag", release.tag)) != (release.repo, release.tag):
            raise ValueError(f"{name}: destino efetivo diverge do release selecionado")
        expected = (expected_periods or {}).get(name)
        if name in {"bloprudencial", "mercado_credito_sgs"}:
            expected = expected or (expected_periods or {}).get("monthly")
        if expected and record.get("max_period_ref") != normalize_period_reference(expected):
            raise ValueError(f"{name}: competência máxima difere do alvo {expected}")
    raw_previous = remote_manifest if remote_manifest is not None else _fetch_release_manifest(release, token)
    previous = _validate_remote_manifest(raw_previous, release, allow_empty=remote_manifest is not None)
    upload_caches = list(promised)
    reused_sources = []
    for name in sources:
        if name in upload_caches:
            continue
        local_record = runtime["caches"][name]
        remote_record = previous["caches"].get(name) or {}
        if remote_record.get("sha256") and remote_record["sha256"] != local_record["sha256"]:
            raise ValueError(
                f"{name}: fonte não selecionada diverge da publicação remota; "
                "atualize e publique essa fonte explicitamente antes de continuar"
            )
        source_assets = release_assets_for_cache(manager, name)
        can_reuse = False
        if remote_record.get("sha256") == local_record["sha256"] and len(source_assets) == 2:
            data_path, data_name = source_assets[0]
            metadata_path, metadata_name = source_assets[1]
            _confirm_remote_source(release, name, local_record["sha256"], token, data_name)
            remote_metadata_sha = remote_record.get("metadata_sha256")
            if remote_metadata_sha in {None, local_record["metadata_sha256"]}:
                try:
                    _confirm_remote_source(release, name, local_record["metadata_sha256"], token, metadata_name)
                    can_reuse = True
                except RemoteAssetHashMismatch:
                    # Legacy downloads can regenerate local metadata. Its pair
                    # is uploaded together with all consumers already prepared.
                    if remote_metadata_sha is not None:
                        raise
            if can_reuse:
                reused_sources.extend([
                    {"cache": name, "asset": data_name, "sha256": local_record["sha256"]},
                    {"cache": name, "asset": metadata_name, "sha256": local_record["metadata_sha256"]},
                ])
        if not can_reuse:
            upload_caches.append(name)
    additional_targets = set(get_postprocess_targets(upload_caches)) - set(promised)
    if additional_targets:
        raise ValueError("fontes locais divergentes exigem preparar pacote ampliado com: "
                         + ", ".join(sorted(additional_targets)))
    upload_caches = _sorted_cache_names(upload_caches)
    validation_assets = []
    for asset_path, asset_name in collect_release_assets(manager, scope):
        digest = sha256_file(asset_path)
        if not digest:
            raise ValueError(f"{asset_name}: asset local ausente")
        validation_assets.append({"name": asset_name, "path": str(asset_path.resolve()),
                                  "sha256": digest, "size_bytes": asset_path.stat().st_size})
    for name in scope:
        cache = manager.get_cache(name)
        record = runtime["caches"][name]
        if (sha256_file(Path(record["path"])) != record["sha256"]
                or sha256_file(cache.arquivo_metadata) != record["metadata_sha256"]):
            raise ValueError(f"{name}: fonte mudou durante validação; prepare o pacote novamente")
    assets = collect_release_assets(manager, upload_caches)
    validation_by_name = {item["name"]: item for item in validation_assets}
    asset_records = [{key: validation_by_name[name][key] for key in ("name", "sha256", "size_bytes")}
                     for _, name in assets]
    payload = deepcopy(previous)
    payload["caches"].update({name: runtime["caches"][name] for name in upload_caches})
    published_assets = dict(previous.get("published_assets") or {})
    for asset in asset_records:
        old_entry = published_assets.get(asset["name"])
        published_assets[asset["name"]] = {
            **(dict(old_entry) if isinstance(old_entry, Mapping) else {}),
            "sha256": asset["sha256"], "bytes": asset["size_bytes"],
        }
    expected_by_cache = dict(previous.get("expected_periods_by_cache") or {})
    for name in upload_caches:
        expected_by_cache[name] = runtime["caches"][name].get("max_period_ref") or None
    publication_id = uuid4().hex
    previous_expected = dict(previous.get("expected_periods") or {})
    proposed_expected = dict(expected_periods or {})
    if proposed_expected.get("quarterly"):
        proposed_gates = evaluate_alignment_gates(payload["caches"], expected_periods=proposed_expected)
        if all(gate.get("success") for gate in proposed_gates.values()):
            previous_expected["quarterly"] = proposed_expected["quarterly"]
    combined_gates = evaluate_alignment_gates(payload["caches"], expected_periods=previous_expected)
    payload.update({
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "publication_id": publication_id, "run_id": publication_id,
        "previous_publication_id": previous.get("publication_id"),
        "release": release.to_dict(), "expected_periods": previous_expected,
        "published_assets": published_assets, "expected_periods_by_cache": expected_by_cache,
        "publication_expected_periods": proposed_expected, "selected_caches": selected,
        "published_caches": upload_caches, "confirmed_source_assets": reused_sources,
        "postprocess_targets": _materialization_targets(selected),
        "materialization": list(materialization_details or []),
        "quality_checks": {**dict(previous.get("quality_checks") or {}), **quality},
        "gates": combined_gates,
        "summary": {"total_caches": len(payload["caches"]),
                    "present_caches": sum(bool(record.get("exists")) for record in payload["caches"].values()),
                    "total_gates": len(combined_gates),
                    "successful_gates": sum(bool(gate.get("success")) for gate in combined_gates.values())},
        "publication_assets": asset_records,
        "publication_validation": {"base_dir": str(base_dir), "caches": scope,
                                   "assets": validation_assets,
                                   "previous_manifest_sha256": _manifest_digest(raw_previous) if raw_previous else None},
        "runtime_diagnostics": runtime,
    })
    path = base_dir / "data" / "cache" / "publications" / publication_id / "manifest.json"
    _write_json_atomic(path, payload)
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


def _stream_response_digest(response) -> str:
    digest = hashlib.sha256()
    for chunk in response.iter_content(chunk_size=1024 * 1024):
        if chunk:
            digest.update(chunk)
    return digest.hexdigest()


def _verify_uploaded_asset(repo: str, asset_name: str, response, digest: str, token: str) -> None:
    try:
        uploaded = response.json()
    except ValueError:
        uploaded = {}
    if not isinstance(uploaded, Mapping):
        uploaded = {}
    declared_digest = str(uploaded.get("digest") or "")
    if declared_digest:
        if declared_digest != f"sha256:{digest}":
            raise RuntimeError(f"{asset_name}: hash retornado pelo GitHub diverge do pacote")
        return
    asset_id = uploaded.get("id")
    if not asset_id:
        raise RuntimeError(f"{asset_name}: GitHub não informou identidade para verificação do upload")
    headers = _github_headers(token)
    headers["Accept"] = "application/octet-stream"
    response = _request_with_retries(
        "GET", f"https://api.github.com/repos/{repo}/releases/assets/{asset_id}",
        headers=headers, timeout=120, stream=True,
    )
    try:
        if response.status_code != 200 or _stream_response_digest(response) != digest:
            raise RuntimeError(f"{asset_name}: conteúdo remoto não confirmou o hash publicado")
    finally:
        response.close()


def _assert_validation_unchanged(validation: Mapping[str, Any], root: Path) -> None:
    for name in validation.get("caches") or []:
        _assert_complete_update(root, name)
    for record in validation.get("assets") or []:
        if sha256_file(Path(record["path"])) != record.get("sha256"):
            raise ValueError(f"candidato mudou após validação: {record['name']}; prepare o pacote novamente")


def _assert_remote_manifest_unchanged(repo: str, tag: str, validation: Mapping[str, Any], token: str) -> None:
    expected_digest = validation.get("previous_manifest_sha256")
    release = ReleaseConfig(
        repo=repo, tag=tag, raw_repo=repo,
        release_base_url=f"https://github.com/{repo}/releases/download/{tag}",
        repo_source="publication", tag_source="publication", raw_repo_source="publication",
    )
    if expected_digest:
        current = _fetch_release_manifest(release, token)
        if _manifest_digest(current) != expected_digest:
            raise ValueError("manifesto remoto mudou desde a preparação; prepare o pacote novamente")


def upload_release_assets(
    *,
    repo: str,
    tag: str,
    assets: Sequence[tuple[Path, str]],
    token: str,
    base_dir: Path | None = None,
    expected_sha256: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Envia bytes validados e verifica os assets; o manifesto é enviado por último.

    A substituição de assets no release existente é sequencial. Um erro pode
    deixar assets parciais; o erro relata o que foi enviado e o manifesto não
    confirma o pacote até todos os demais assets serem verificados.
    """
    asset_paths: dict[str, Path] = {}
    for path, name in assets:
        if name in asset_paths:
            raise ValueError(f"asset duplicado: {name}")
        if Path(name).name != name or name in {"", ".", ".."}:
            raise ValueError(f"nome de asset inválido: {name}")
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(f"asset local ausente antes do upload: {name}")
        asset_paths[name] = path
    if not asset_paths:
        raise ValueError("nenhum asset selecionado para upload")
    manifest: dict[str, Any] = {}
    manifest_sha256 = None
    if "manifest.json" in asset_paths:
        manifest_bytes = asset_paths["manifest.json"].read_bytes()
        manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
        manifest = json.loads(manifest_bytes)
        if not isinstance(manifest, dict):
            raise ValueError("manifesto candidato inválido")
        identity = manifest.get("release") or {}
        if (identity.get("repo"), identity.get("tag")) != (repo, tag):
            raise ValueError("destino do manifesto candidato diverge do upload")
        if not isinstance(manifest.get("publication_assets"), list):
            raise ValueError("manifesto sem preflight de publicação; prepare o pacote novamente")
    validation = manifest.get("publication_validation") or {}
    candidate_root = validation.get("base_dir")
    root = _operation_root(base_dir=base_dir or (Path(candidate_root) if candidate_root else None))
    if candidate_root and root != Path(candidate_root).resolve():
        raise ValueError("diretório do upload diverge do pacote validado")
    with mutation_lock(root, owner={"label": "publicação no GitHub"}):
        _assert_validation_unchanged(validation, root)
        expected = dict(expected_sha256 or {})
        if manifest_sha256 is not None:
            if "manifest.json" in expected and expected["manifest.json"] != manifest_sha256:
                raise ValueError("hash esperado diverge do manifesto candidato")
            expected["manifest.json"] = manifest_sha256
        declared = {record["name"]: record["sha256"] for record in manifest.get("publication_assets", [])}
        if len(declared) != len(manifest.get("publication_assets", [])):
            raise ValueError("asset duplicado no manifesto candidato")
        if manifest and set(declared) != set(asset_paths) - {"manifest.json"}:
            raise ValueError("assets do upload divergem do pacote validado")
        for name, digest in declared.items():
            if name in expected and expected[name] != digest:
                raise ValueError(f"hash esperado diverge do manifesto: {name}")
            expected[name] = digest
        if set(expected) - set(asset_paths):
            raise ValueError("hash esperado informado para asset ausente")
        # Copy to private staging and hash the very file handle later sent to
        # GitHub, so an original path replacement cannot change reviewed bytes.
        with tempfile.TemporaryDirectory(prefix="tomaconta-publication-") as staging:
            staged: list[tuple[Path, str, str]] = []
            for name, original in asset_paths.items():
                target = Path(staging) / name
                digest = hashlib.sha256()
                with original.open("rb") as source, target.open("wb") as out:
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        digest.update(chunk)
                        out.write(chunk)
                actual = digest.hexdigest()
                if name in expected and actual != expected[name]:
                    raise ValueError(f"candidato mudou após validação: {name}; prepare o pacote novamente")
                staged.append((target, name, actual))
            staged.sort(key=lambda item: item[1] == "manifest.json")
            _assert_validation_unchanged(validation, root)
            return _upload_validated_assets(
                repo=repo, tag=tag, staged=staged, token=token,
                validation=validation, manifest=manifest, root=root,
            )


def _upload_validated_assets(
    *, repo: str, tag: str, staged: Sequence[tuple[Path, str, str]], token: str,
    validation: Mapping[str, Any], manifest: Mapping[str, Any], root: Path,
) -> dict[str, Any]:
    headers = _github_headers(token)
    response = _request_with_retries(
        "GET", f"https://api.github.com/repos/{repo}/releases/tags/{tag}",
        headers=headers, timeout=30,
    )
    if response.status_code != 200:
        detail = github_error_detail(response)
        hint = github_permission_hint(repo, response.status_code, detail)
        raise RuntimeError(f"release alvo indisponível em {repo}@{tag} (HTTP {response.status_code}) {detail}.{hint}")
    release_data = response.json()
    upload_url = str(release_data["upload_url"]).replace("{?name,label}", "")
    existing_assets = {asset["name"]: asset["id"] for asset in release_data.get("assets", [])}
    if manifest and not validation.get("previous_manifest_sha256") and "manifest.json" in existing_assets:
        raise ValueError("manifesto remoto surgiu após preparação de release vazio; prepare o pacote novamente")
    _assert_remote_manifest_unchanged(repo, tag, validation, token)
    uploaded: list[str] = []
    verified: list[str] = []
    manifest_written = False
    replaced: list[str] = []
    try:
        for path, asset_name, digest in staged:
            if asset_name == "manifest.json":
                _assert_validation_unchanged(validation, root)
                _assert_remote_manifest_unchanged(repo, tag, validation, token)
            asset_id = existing_assets.get(asset_name)
            if asset_id is not None:
                delete_resp = _request_with_retries(
                    "DELETE", f"https://api.github.com/repos/{repo}/releases/assets/{asset_id}",
                    headers=headers, timeout=30,
                )
                if delete_resp.status_code not in {204, 404}:
                    detail = github_error_detail(delete_resp)
                    hint = github_permission_hint(repo, delete_resp.status_code, detail)
                    raise RuntimeError(f"falha ao remover asset antigo {asset_name} ({delete_resp.status_code}) {detail}.{hint}")
                replaced.append(asset_name)
            upload_headers = _github_headers(token, content_type="application/octet-stream")
            upload_resp = None
            for attempt in range(1, 4):
                with path.open("rb") as handle:
                    actual = hashlib.sha256()
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        actual.update(chunk)
                    if actual.hexdigest() != digest:
                        raise ValueError(f"bytes preparados mudaram antes do envio: {asset_name}")
                    handle.seek(0)
                    try:
                        upload_resp = requests.post(
                            f"{upload_url}?name={asset_name}", headers=upload_headers,
                            data=handle, timeout=300,
                        )
                    except requests.exceptions.RequestException as exc:
                        if attempt >= 3:
                            raise RuntimeError(f"falha de rede ao publicar asset {asset_name}: {exc}") from exc
                        time.sleep(min(2 ** (attempt - 1), 4))
                        continue
                if upload_resp.status_code in {200, 201}:
                    break
                if upload_resp.status_code not in {408, 429, 500, 502, 503, 504} or attempt >= 3:
                    detail = github_error_detail(upload_resp)
                    hint = github_permission_hint(repo, upload_resp.status_code, detail)
                    raise RuntimeError(f"falha ao publicar asset {asset_name} ({upload_resp.status_code}) {detail}.{hint}")
                time.sleep(min(2 ** (attempt - 1), 4))
            uploaded.append(asset_name)
            if asset_name == "manifest.json":
                manifest_written = True
            _verify_uploaded_asset(repo, asset_name, upload_resp, digest, token)
            verified.append(asset_name)
    except (RuntimeError, ValueError, OSError, requests.exceptions.RequestException) as exc:
        suffix = (f" Envio incompleto. Assets enviados: {', '.join(uploaded) or 'nenhum'}; "
                  f"substituições iniciadas: {', '.join(replaced) or 'nenhuma'}; "
                  f"manifesto {'enviado sem confirmação' if manifest_written else 'não enviado'}. "
                  "O pacote e o uso pela aplicação não foram confirmados.")
        raise RuntimeError(str(exc) + suffix) from exc
    return {"repo": repo, "tag": tag, "assets": uploaded, "verified_assets": verified,
            "publication_verified": True, "manifest_verified": "manifest.json" in verified,
            "activation_confirmed": False}
