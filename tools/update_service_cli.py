#!/usr/bin/env python3
"""Entrada portátil para API, worker, importação e exportação das bases."""
from __future__ import annotations

import argparse
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from utils.ifdata_cache.durable_jobs import run_worker
from utils.ifdata_cache.official_store import LocalRevisionStore
from utils.ifdata_cache.update_backend import UpdateBackend, UpdateJobExecutor, bootstrap_official_store


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, type=Path, help="volume persistente da fila e workspaces")
    parser.add_argument("--store-dir", required=True, type=Path, help="volume persistente das revisões oficiais")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="API; worker executado em outro processo")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", default=8787, type=int)
    worker = sub.add_parser("worker")
    worker.add_argument("--once", action="store_true", help="processar no máximo um job")
    bootstrap = sub.add_parser("import-legacy", help="importação inicial validada")
    bootstrap.add_argument("--source-dir", required=True, type=Path)
    export = sub.add_parser("export", help="backup independente, com hashes")
    export.add_argument("--destination", required=True, type=Path)
    export.add_argument("--revision")
    args = parser.parse_args(argv)
    store = LocalRevisionStore(args.store_dir.resolve())
    backend = UpdateBackend(args.data_dir.resolve(), store)
    if args.command == "serve":
        from utils.ifdata_cache.update_access import TokenIdentityVerifier
        from utils.ifdata_cache.update_api import handler_factory
        verifier = TokenIdentityVerifier.from_env()
        # Escuta externa somente por opção explícita; TLS fica no proxy da instituição.
        server = ThreadingHTTPServer((args.host, args.port), handler_factory(backend, verifier))
        server.daemon_threads = True
        print(f"API de atualização em {args.host}:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    elif args.command == "worker":
        run_worker(backend.queue, UpdateJobExecutor(backend), once=args.once)
    elif args.command == "import-legacy":
        snapshot = bootstrap_official_store(args.source_dir, store, actor={"subject": "local-operator"})
        print(f"Revisão inicial ativada: {snapshot.revision_id}")
    else:
        snapshot = args.revision or store.current()
        if snapshot is None:
            parser.error("Nenhuma revisão oficial para exportar")
        print(store.export(snapshot, args.destination))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
