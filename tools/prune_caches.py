"""Limpa arquivos de operação. Por padrão só lista; apaga apenas com --apply.

Nunca toca nas bases nem nas fontes arquivadas: atua em relatórios antigos,
envios manuais e áreas temporárias que uma execução interrompida deixou para trás.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
REPORTS = "data/cache/financial_analysis_updates"


def candidates(root, *, keep_reports=30, older_than_days=7, now=None) -> list[Path]:
    """Caminhos removíveis: relatórios além dos mais recentes, envios e temporários antigos."""
    root = Path(root)
    directory = root / REPORTS
    if not directory.is_dir():
        return []
    limit = (now or datetime.now(timezone.utc)) - timedelta(days=older_than_days)
    old = lambda path: datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) < limit
    reports = sorted(directory.glob("[0-9]*T*.json"), key=lambda path: path.name)
    found = reports[:-keep_reports] if keep_reports else list(reports)
    found += [path for path in directory.glob("financial-analysis-*") if path.is_dir() and old(path)]
    uploads = directory / "uploads"
    if uploads.is_dir():
        found += [path for path in uploads.iterdir() if old(path)]
    return found


def size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file()) if path.is_dir() else path.stat().st_size


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--keep-reports", type=int, default=30)
    parser.add_argument("--older-than-days", type=int, default=7)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    found = candidates(args.root, keep_reports=args.keep_reports, older_than_days=args.older_than_days)
    total = sum(size(path) for path in found)
    for path in found:
        print(path)
        if args.apply:
            shutil.rmtree(path) if path.is_dir() else path.unlink()
    print(f"{len(found)} item(ns), {total / 1e6:.1f} MB{' removidos' if args.apply else ' (use --apply para remover)'}")


if __name__ == "__main__":
    main()
