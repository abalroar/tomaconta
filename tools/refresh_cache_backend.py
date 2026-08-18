#!/usr/bin/env python3
"""Refresh ou republicação dos caches IFData com versionamento e rollback.

Fluxo padrão:
1) Cria snapshot versionado de data/cache em data/cache_versions/<versao>
2) Faz refresh completo em modo overwrite via CacheManager
3) Gera manifest com detalhes para auditoria e rollback

Rollback:
- --restore-snapshot <versao>: restaura snapshot para data/cache
"""

from __future__ import annotations

import argparse
import json
import os
import time
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from utils.ifdata_cache import CacheManager, gerar_periodos_trimestrais
from utils.ifdata_cache import (
    describe_support_window,
    filter_supported_periods,
    materialize_critical_screens_cache,
)
from utils.ifdata_cache.derived_metrics import materialize_derived_metrics_cache
from utils.ifdata_cache.diagnostics import (
    build_runtime_manifest,
    count_placeholder_names,
    find_placeholder_rows,
)
from utils.ifdata_cache.release_config import get_release_config
from utils.ifdata_cache.release_ops import upload_release_assets

DEFAULT_TIPOS = [
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
]

DERIVED_SPECS = [
    {
        "tipo": "derived_metrics",
        "dre_cache_name": "dre",
        "principal_cache_name": "principal",
    },
    {
        "tipo": "derived_metrics_individual",
        "dre_cache_name": "dre_individual",
        "principal_cache_name": "principal_individual",
    },
]

PUBLISH_CACHE_NAMES = DEFAULT_TIPOS + [spec["tipo"] for spec in DERIVED_SPECS] + ["critical_screens"]


def _print(msg: str) -> None:
    print(msg, flush=True)


def _now_tag() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _safe_label(label: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in ("-", "_") else "-" for c in label.strip())
    return cleaned.strip("-") or "snapshot"


def _git_head(base_dir: Path) -> str:
    try:
        out = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=base_dir, text=True)
        return out.strip()
    except Exception:
        return "desconhecido"


def _version_name(label: str) -> str:
    return f"{_now_tag()}_{_safe_label(label)}"


def _cache_paths(base_dir: Path) -> tuple[Path, Path]:
    return base_dir / "data" / "cache", base_dir / "data" / "cache_versions"


def _save_manifest(path: Path, payload: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def _chunked(values: List[str], batch_size: int) -> Iterable[List[str]]:
    if batch_size <= 0:
        yield values
        return
    for i in range(0, len(values), batch_size):
        yield values[i : i + batch_size]


def _is_expected_no_data_error(message: str | None) -> bool:
    texto = str(message or "").strip().lower()
    if not texto:
        return False
    marcadores_ok = (
        "sem dados",
        "nenhum período extraído com sucesso",
        "nenhum periodo extraido com sucesso",
        "nenhuma variável encontrada após filtro",
        "nenhuma variavel encontrada apos filtro",
    )
    if not any(marcador in texto for marcador in marcadores_ok):
        return False
    marcadores_fatais = (
        "timeout",
        "timed out",
        "connection",
        "conex",
        "dns",
        "ssl",
        "proxy",
        "403",
        "404",
        "429",
        "500",
        "502",
        "503",
        "504",
    )
    return not any(marcador in texto for marcador in marcadores_fatais)


def _create_snapshot(base_dir: Path, label: str, reason: str, dry_run: bool = False) -> Path:
    cache_dir, versions_dir = _cache_paths(base_dir)
    versions_dir.mkdir(parents=True, exist_ok=True)
    version = _version_name(label)
    target = versions_dir / version

    if not cache_dir.exists():
        raise FileNotFoundError(f"Diretório de cache não encontrado: {cache_dir}")

    _print(f"[SNAPSHOT] criando: {target}")
    if not dry_run:
        shutil.copytree(cache_dir, target)

    manifest = {
        "version": version,
        "label": label,
        "reason": reason,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": _git_head(base_dir),
        "source": str(cache_dir.relative_to(base_dir)),
        "type": "backup",
    }

    if not dry_run:
        _save_manifest(target / "manifest.json", manifest)

    _print(f"[SNAPSHOT] pronto: {version}")
    return target


def _restore_snapshot(base_dir: Path, version: str, dry_run: bool = False) -> None:
    cache_dir, versions_dir = _cache_paths(base_dir)
    source = versions_dir / version

    if not source.exists():
        raise FileNotFoundError(f"Snapshot não encontrado: {source}")

    rollback_label = f"before-restore-{version}"
    _create_snapshot(base_dir, rollback_label, reason=f"auto-backup before restore {version}", dry_run=dry_run)

    _print(f"[RESTORE] restaurando snapshot {version} para {cache_dir}")
    if not dry_run:
        if cache_dir.exists():
            shutil.rmtree(cache_dir)
        shutil.copytree(source, cache_dir)

    _print("[RESTORE] concluído")


def _gerar_periodos_mensais(inicio: str, fim: str) -> List[str]:
    if len(inicio) != 6 or len(fim) != 6:
        raise ValueError("mensal-inicio/mensal-fim devem ser YYYYMM")

    ai, mi = int(inicio[:4]), int(inicio[4:6])
    af, mf = int(fim[:4]), int(fim[4:6])
    if (ai, mi) > (af, mf):
        raise ValueError("mensal-inicio deve ser <= mensal-fim")

    out = []
    a, m = ai, mi
    while (a, m) <= (af, mf):
        out.append(f"{a}{m:02d}")
        if m == 12:
            a, m = a + 1, 1
        else:
            m += 1

    return out


def _github_token() -> tuple[str | None, str]:
    for key in ("GITHUB_PAT", "GH_TOKEN", "GITHUB_TOKEN"):
        value = os.getenv(key)
        if value and value.strip():
            return value.strip(), key
    return None, ""


def _release_assets_for_cache(manager: CacheManager, cache_name: str) -> list[tuple[Path, str]]:
    cache = manager.get_cache(cache_name)
    if cache is None:
        raise ValueError(f"cache não configurado: {cache_name}")
    data_path = (
        cache.arquivo_dados_runtime
        if cache.arquivo_dados_runtime.exists()
        else cache.arquivo_dados_pickle
    )
    if not data_path.exists():
        raise FileNotFoundError(f"arquivo de dados runtime ausente para {cache_name}: {data_path}")
    metadata_path = cache.arquivo_metadata_runtime
    if not metadata_path.exists():
        raise FileNotFoundError(f"metadata runtime ausente para {cache_name}: {metadata_path}")
    data_asset = f"{cache_name}_dados.parquet" if data_path.suffix == ".parquet" else f"{cache_name}_cache.pkl"
    return [
        (data_path, data_asset),
        (metadata_path, f"{cache_name}_metadata.json"),
    ]


def _materialize_post_refresh_assets(base_dir: Path, manager: CacheManager) -> list[dict]:
    detalhes: list[dict] = []

    for spec in DERIVED_SPECS:
        result = materialize_derived_metrics_cache(
            base_dir=base_dir,
            manager=manager,
            derived_cache_name=spec["tipo"],
            dre_cache_name=spec["dre_cache_name"],
            principal_cache_name=spec["principal_cache_name"],
            force=True,
        )
        detalhes.append(
            {
                "tipo": spec["tipo"],
                "status": "ok" if result.sucesso else "erro",
                "mensagem": result.mensagem,
                "periodos": 0,
                "periodos_ignorados": [],
                "lotes": 1,
                "lotes_ok": 1 if result.sucesso else 0,
            }
        )
        if not result.sucesso:
            return detalhes

    result_curado = materialize_critical_screens_cache(
        base_dir=base_dir,
        manager=manager,
        force=True,
        save_bundled=True,
    )
    detalhes.append(
        {
            "tipo": "critical_screens",
            "status": "ok" if result_curado.sucesso else "erro",
            "mensagem": result_curado.mensagem,
            "periodos": 0,
            "periodos_ignorados": [],
            "lotes": 1,
            "lotes_ok": 1 if result_curado.sucesso else 0,
        }
    )
    return detalhes


def _placeholder_validations(manager: CacheManager) -> dict[str, dict]:
    validations: dict[str, dict] = {}
    for cache_name in ("principal", "capital"):
        result = manager.carregar(cache_name)
        if not result.sucesso or result.dados is None:
            validations[cache_name] = {
                "success": False,
                "count": None,
                "message": result.mensagem,
                "examples": [],
            }
            continue
        placeholders = find_placeholder_rows(result.dados, max_rows=20)
        count = count_placeholder_names(result.dados)
        validations[cache_name] = {
            "success": count == 0,
            "count": count,
            "message": "ok" if count == 0 else f"{count} placeholder(s) remanescente(s)",
            "examples": placeholders.to_dict("records") if not placeholders.empty else [],
        }
    return validations


def _build_publish_runtime_manifest(
    manager: CacheManager,
    *,
    release_config,
    expected_periods: dict[str, str],
) -> dict:
    """Descreve somente caches cujos assets esta CLI publica."""
    return build_runtime_manifest(
        manager,
        cache_names=PUBLISH_CACHE_NAMES,
        release_config=release_config,
        expected_periods=expected_periods,
        include_hashes=True,
    )


def _run_refresh(args: argparse.Namespace, base_dir: Path) -> int:
    pre_snapshot = _create_snapshot(
        base_dir=base_dir,
        label=args.snapshot_label,
        reason=args.reason,
        dry_run=args.dry_run,
    )
    run_id = _version_name(f"run-{args.snapshot_label}")

    periodos_tri = gerar_periodos_trimestrais(
        args.ano_inicial,
        args.mes_inicial,
        args.ano_final,
        args.mes_final,
    )
    periodos_mensais = _gerar_periodos_mensais(args.mensal_inicio, args.mensal_fim)

    manager = CacheManager(base_dir=base_dir)
    detalhes = []

    for tipo in DEFAULT_TIPOS:
        periodos = periodos_mensais if tipo == "bloprudencial" else periodos_tri
        action = "REUSE" if args.publish_only else "REFRESH"
        _print(
            f"[{action}] {tipo}: {len(periodos)} períodos "
            f"(lotes={args.batch_size if args.batch_size > 0 else 'auto'} retries={args.retry_max})"
        )

        if args.dry_run:
            detalhes.append(
                {
                    "tipo": tipo,
                    "periodos": len(periodos),
                    "status": "dry-run",
                    "lotes": len(list(_chunked(periodos, args.batch_size))),
                }
            )
            continue

        if args.publish_only:
            try:
                assets = _release_assets_for_cache(manager, tipo)
                detalhes.append(
                    {
                        "tipo": tipo,
                        "periodos": len(periodos),
                        "status": "reuse",
                        "mensagem": "cache runtime existente reutilizado",
                        "lotes": 0,
                        "lotes_ok": 0,
                        "assets_runtime": [str(path.relative_to(base_dir)) for path, _ in assets],
                    }
                )
            except Exception as exc:
                detalhes.append(
                    {
                        "tipo": tipo,
                        "periodos": len(periodos),
                        "status": "erro",
                        "mensagem": str(exc),
                        "lotes": 0,
                        "lotes_ok": 0,
                    }
                )
                _print(f"[ERRO] {tipo}: {exc}")
                break
            continue

        periodos, periodos_ignorados = filter_supported_periods(tipo, periodos)
        if periodos_ignorados:
            _print(
                f"[SKIP] {tipo}: ignorando {len(periodos_ignorados)} período(s) fora da janela suportada "
                f"({describe_support_window(tipo)}): {', '.join(periodos_ignorados[:6])}"
            )
        if not periodos:
            detalhes.append(
                {
                    "tipo": tipo,
                    "status": "skip",
                    "mensagem": f"nenhum período suportado ({describe_support_window(tipo)})",
                    "periodos": 0,
                    "periodos_ignorados": periodos_ignorados,
                    "lotes": 0,
                    "lotes_ok": 0,
                }
            )
            continue

        kwargs = {}
        if tipo == "bloprudencial":
            kwargs["cache_dir"] = "data/cache/bcb_bloprudencial"
            kwargs["force_refresh"] = True

        total_lotes = 0
        lotes_ok = 0
        lotes_skip = 0
        lotes_skip_detalhes = []
        modo_lote = "overwrite"
        erro_fatal = None
        for periodos_lote in _chunked(periodos, args.batch_size):
            total_lotes += 1
            tentativas = args.retry_max + 1
            erro_lote = None
            for tentativa in range(1, tentativas + 1):
                _print(
                    f"[LOTE] {tipo} {total_lotes}: períodos {periodos_lote[0]}..{periodos_lote[-1]} "
                    f"(tentativa {tentativa}/{tentativas}, modo={modo_lote})"
                )
                result = manager.extrair_periodos_com_salvamento(
                    tipo=tipo,
                    periodos=periodos_lote,
                    modo=modo_lote,
                    intervalo_salvamento=args.intervalo,
                    **kwargs,
                )

                if result.sucesso:
                    lotes_ok += 1
                    modo_lote = "incremental"
                    erro_lote = None
                    break

                erro_lote = result.mensagem
                _print(f"[ERRO] lote {tipo} {total_lotes}: {erro_lote}")
                if tentativa < tentativas and args.retry_delay > 0:
                    _print(f"[RETRY] aguardando {args.retry_delay}s para nova tentativa")
                    time.sleep(args.retry_delay)

            if erro_lote:
                if _is_expected_no_data_error(erro_lote):
                    lotes_skip += 1
                    lotes_skip_detalhes.append(
                        {
                            "lote": total_lotes,
                            "periodos": list(periodos_lote),
                            "mensagem": erro_lote,
                        }
                    )
                    _print(
                        f"[SKIP] lote {tipo} {total_lotes}: sem dados publicados para "
                        f"{periodos_lote[0]}..{periodos_lote[-1]}"
                    )
                    continue
                erro_fatal = erro_lote
                break

        if erro_fatal:
            status_tipo = "erro"
            mensagem_tipo = erro_fatal
        elif lotes_ok == 0:
            status_tipo = "skip"
            mensagem_tipo = "todos os lotes retornaram sem dados publicados"
        else:
            status_tipo = "ok"
            mensagem_tipo = "concluído em lotes"

        detalhes.append(
            {
                "tipo": tipo,
                "status": status_tipo,
                "mensagem": mensagem_tipo,
                "periodos": len(periodos),
                "periodos_ignorados": periodos_ignorados,
                "lotes": total_lotes,
                "lotes_ok": lotes_ok,
                "lotes_skip": lotes_skip,
                "lotes_skip_detalhes": lotes_skip_detalhes,
            }
        )

        if erro_fatal:
            _print(f"[ERRO] {tipo}: {erro_fatal}")
            break

    release_config = get_release_config()
    expected_periods = {
        "quarterly": f"{args.ano_final}{args.mes_final}",
        "monthly": args.mensal_fim,
    }
    publication = {
        "requested": bool(args.publish),
        "repo": release_config.repo,
        "tag": release_config.tag,
        "status": "skip" if not args.publish else "pending",
        "assets": [],
    }
    summary = {
        "run_id": run_id,
        "executed_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": _git_head(base_dir),
        "modo": "publish-only" if args.publish_only else "overwrite",
        "snapshot_pre": pre_snapshot.name,
        "snapshot_post": None,
        "tipos_extraidos": [] if args.publish_only else DEFAULT_TIPOS,
        "tipos_reutilizados": DEFAULT_TIPOS if args.publish_only else [],
        "tipos_materializados": [spec["tipo"] for spec in DERIVED_SPECS] + ["critical_screens"],
        "release": release_config.to_dict(),
        "expected_periods": expected_periods,
        "periodo_trimestral": {
            "inicio": f"{args.ano_inicial}{args.mes_inicial}",
            "fim": f"{args.ano_final}{args.mes_final}",
        },
        "periodo_mensal": {
            "inicio": args.mensal_inicio,
            "fim": args.mensal_fim,
        },
        "detalhes": detalhes,
        "runtime_manifest": {},
        "placeholder_validations": {},
        "publication": publication,
        "status": "ok" if all(d["status"] in {"ok", "reuse", "dry-run", "skip"} for d in detalhes) else "erro",
    }

    manifest_path = base_dir / "data" / "cache_versions" / "last_refresh_manifest.json"
    run_manifest_path = base_dir / "data" / "cache_versions" / "runs" / f"{run_id}.json"
    global_manifest_path = base_dir / "data" / "cache" / "manifest.json"

    if not args.dry_run and summary["status"] == "ok":
        post_refresh_details = _materialize_post_refresh_assets(base_dir, manager)
        detalhes.extend(post_refresh_details)
        if any(item["status"] == "erro" for item in post_refresh_details):
            summary["status"] = "erro"

    if not args.dry_run and summary["status"] == "ok":
        summary["runtime_manifest"] = _build_publish_runtime_manifest(
            manager,
            release_config=release_config,
            expected_periods={"quarterly": expected_periods["quarterly"]},
        )
        summary["placeholder_validations"] = _placeholder_validations(manager)

        gates_ok = all(gate.get("success") for gate in summary["runtime_manifest"].get("gates", {}).values())
        placeholders_ok = all(
            check.get("success")
            for check in summary["placeholder_validations"].values()
        )
        if not gates_ok:
            summary["status"] = "erro"
        if not placeholders_ok:
            summary["status"] = "erro"

        global_manifest = {
            "run_id": run_id,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "git_head": _git_head(base_dir),
            "release": release_config.to_dict(),
            "expected_periods": expected_periods,
            "caches": summary["runtime_manifest"].get("caches", {}),
            "gates": summary["runtime_manifest"].get("gates", {}),
            "placeholder_validations": summary["placeholder_validations"],
        }
        _save_manifest(global_manifest_path, global_manifest)

        if summary["status"] == "ok" and args.publish:
            token, token_source = _github_token()
            if not token:
                summary["status"] = "erro"
                publication["status"] = "erro"
                publication["message"] = "token GitHub ausente para publicação"
            else:
                try:
                    assets: list[tuple[Path, str]] = []
                    for cache_name in PUBLISH_CACHE_NAMES:
                        assets.extend(_release_assets_for_cache(manager, cache_name))
                    assets.append((global_manifest_path, "manifest.json"))
                    upload_result = upload_release_assets(
                        repo=release_config.repo,
                        tag=release_config.tag,
                        assets=assets,
                        token=token,
                    )
                    publication["status"] = "ok"
                    publication["token_source"] = token_source
                    publication["assets"] = upload_result["assets"]
                except Exception as exc:
                    summary["status"] = "erro"
                    publication["status"] = "erro"
                    publication["message"] = str(exc)

    if not args.dry_run and summary["status"] == "ok":
        post_snapshot = _create_snapshot(
            base_dir=base_dir,
            label=f"post-{args.snapshot_label}",
            reason=f"snapshot após {'republicação' if args.publish_only else 'refresh completo'} (run={run_id})",
            dry_run=args.dry_run,
        )
        summary["snapshot_post"] = post_snapshot.name

    if not args.dry_run:
        _save_manifest(manifest_path, summary)
        _save_manifest(run_manifest_path, summary)

    if summary["status"] == "ok":
        operation = "republicação" if args.publish_only else "refresh completo"
        _print(f"[OK] {operation} finalizada. Manifest: {manifest_path}")
        _print(f"[OK] snapshot anterior: {summary['snapshot_pre']} | snapshot novo: {summary['snapshot_post']}")
        return 0

    _print(f"[ERRO] refresh terminou com falhas. Manifest: {manifest_path}")
    _print(f"[ERRO] use --restore-snapshot {summary['snapshot_pre']} para rollback rápido")
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Refresh ou republicação de cache com snapshot versionado")
    parser.add_argument("--restore-snapshot", help="restaura versão específica de data/cache_versions")
    parser.add_argument("--list-snapshots", action="store_true", help="lista snapshots disponíveis")

    parser.add_argument("--snapshot-label", default="pre-overwrite", help="rótulo legível do snapshot")
    parser.add_argument("--reason", default="refresh completo via backend", help="motivo do snapshot")

    parser.add_argument("--ano-inicial", type=int)
    parser.add_argument("--mes-inicial", choices=["03", "06", "09", "12"])
    parser.add_argument("--ano-final", type=int)
    parser.add_argument("--mes-final", choices=["03", "06", "09", "12"])

    parser.add_argument("--mensal-inicio", help="YYYYMM")
    parser.add_argument("--mensal-fim", help="YYYYMM")

    parser.add_argument("--intervalo", type=int, default=4, help="salvar a cada N períodos")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=6,
        help="número de períodos por lote (0 para processar tudo de uma vez)",
    )
    parser.add_argument("--retry-max", type=int, default=2, help="repetições por lote em caso de erro")
    parser.add_argument("--retry-delay", type=int, default=3, help="segundos entre tentativas")
    parser.add_argument("--publish", action="store_true", help="publica os artefatos válidos no GitHub Release configurado")
    parser.add_argument(
        "--publish-only",
        action="store_true",
        help=(
            "reutiliza caches runtime existentes, rematerializa derivados, executa gates e publica; "
            "não consulta as fontes"
        ),
    )
    parser.add_argument("--dry-run", action="store_true", help="simula sem alterar arquivos")
    return parser


def _list_snapshots(base_dir: Path) -> int:
    _, versions_dir = _cache_paths(base_dir)
    if not versions_dir.exists():
        _print("Nenhum snapshot encontrado.")
        return 0

    entries = sorted([p for p in versions_dir.iterdir() if p.is_dir()], reverse=True)
    if not entries:
        _print("Nenhum snapshot encontrado.")
        return 0

    _print("Snapshots disponíveis:")
    for entry in entries:
        _print(f"- {entry.name}")
    return 0


def main() -> int:
    args = build_parser().parse_args()
    base_dir = _project_root()

    if args.list_snapshots:
        return _list_snapshots(base_dir)

    if args.restore_snapshot:
        _restore_snapshot(base_dir, args.restore_snapshot, dry_run=args.dry_run)
        return 0

    if args.publish_only and not (args.publish or args.dry_run):
        raise SystemExit("--publish-only exige --publish, exceto quando combinado com --dry-run")

    required = [
        args.ano_inicial,
        args.mes_inicial,
        args.ano_final,
        args.mes_final,
        args.mensal_inicio,
        args.mensal_fim,
    ]
    if any(v is None for v in required):
        raise SystemExit(
            "Para refresh completo, informe: --ano-inicial --mes-inicial --ano-final --mes-final --mensal-inicio --mensal-fim"
        )

    return _run_refresh(args, base_dir)


if __name__ == "__main__":
    raise SystemExit(main())
