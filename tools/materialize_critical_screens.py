#!/usr/bin/env python3
"""Materializa o cache curado usado por Snapshot e Peers."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from utils.ifdata_cache import materialize_critical_screens_cache


def main() -> int:
    parser = argparse.ArgumentParser(description="Materializa cache curado das telas críticas")
    parser.add_argument("--force", action="store_true", help="reconstrói mesmo se o cache já existir")
    parser.add_argument("--bundle", action="store_true", help="atualiza também o artefato bundled versionado")
    parser.add_argument(
        "--allow-remote-source-download",
        action="store_true",
        help="permite baixar caches-fonte do remoto durante a materialização (uso administrativo explícito)",
    )
    args = parser.parse_args()

    result = materialize_critical_screens_cache(
        force=args.force,
        save_bundled=args.bundle,
        allow_remote_source_download=args.allow_remote_source_download,
    )
    print(result.mensagem, flush=True)
    return 0 if result.sucesso else 1


if __name__ == "__main__":
    raise SystemExit(main())
