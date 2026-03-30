#!/usr/bin/env python3
"""Refresh completo dos caches IFData com versionamento e rollback.

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
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from utils.ifdata_cache import CacheManager, gerar_periodos_trimestrais

DEFAULT_TIPOS = [
    "principal",
    "capital",
    "ativo",
    "passivo",
    "dre",
    "carteira_pf",
    "carteira_pj",
    "carteira_instrumentos",
    "bloprudencial",
]


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


def _run_refresh(args: argparse.Namespace, base_dir: Path) -> int:
    _create_snapshot(
        base_dir=base_dir,
        label=args.snapshot_label,
        reason=args.reason,
        dry_run=args.dry_run,
    )

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
        _print(f"[REFRESH] {tipo}: {len(periodos)} períodos (overwrite)")

        if args.dry_run:
            detalhes.append({"tipo": tipo, "periodos": len(periodos), "status": "dry-run"})
            continue

        kwargs = {}
        if tipo == "bloprudencial":
            kwargs["cache_dir"] = "data/cache/bcb_bloprudencial"
            kwargs["force_refresh"] = True

        result = manager.extrair_periodos_com_salvamento(
            tipo=tipo,
            periodos=periodos,
            modo="overwrite",
            intervalo_salvamento=args.intervalo,
            **kwargs,
        )

        detalhes.append(
            {
                "tipo": tipo,
                "status": "ok" if result.sucesso else "erro",
                "mensagem": result.mensagem,
                "periodos": len(periodos),
            }
        )

        if not result.sucesso:
            _print(f"[ERRO] {tipo}: {result.mensagem}")
            return 1

    summary = {
        "executed_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": _git_head(base_dir),
        "modo": "overwrite",
        "tipos": DEFAULT_TIPOS,
        "periodo_trimestral": {
            "inicio": f"{args.ano_inicial}{args.mes_inicial}",
            "fim": f"{args.ano_final}{args.mes_final}",
        },
        "periodo_mensal": {
            "inicio": args.mensal_inicio,
            "fim": args.mensal_fim,
        },
        "detalhes": detalhes,
    }

    manifest_path = base_dir / "data" / "cache_versions" / "last_refresh_manifest.json"
    if not args.dry_run:
        _save_manifest(manifest_path, summary)
    _print(f"[OK] refresh completo finalizado. Manifest: {manifest_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Refresh completo de cache com snapshot versionado")
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
