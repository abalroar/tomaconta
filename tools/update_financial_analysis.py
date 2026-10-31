"""Atualiza a análise financeira pelo BCB, com validação antes da promoção."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utils.ifdata_cache.financial_analysis_update import publish_update, update

__all__ = ["update", "main"]
TOKEN_NAMES = ("GITHUB_PAT", "GH_TOKEN", "GITHUB_TOKEN")


def _job_writer(path):
    """Estado que a tela acompanha; o processo continua mesmo sem ninguém olhando."""
    started = datetime.now(timezone.utc).isoformat()

    def write(stage, **extra):
        if path:
            temporary = Path(f"{path}.{os.getpid()}.tmp")
            temporary.write_text(json.dumps({"pid": os.getpid(), "stage": stage, "started_at": started, "running": True, **extra}, ensure_ascii=False))
            temporary.replace(path)
    return write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--data-base", help="YYYY-MM; omitido: última competência mensal publicada")
    parser.add_argument("--csv", type=Path, help="Arquivo BLOPRUDENCIAL já disponível")
    parser.add_argument("--offline", action="store_true", help="Valida o CSV com os relatórios IF.data já guardados")
    parser.add_argument("--check-only", action="store_true", help="Valida e guarda fontes sem promover a geração")
    parser.add_argument("--rules", type=Path, help="JSON com os limiares operacionais de validação")
    parser.add_argument("--decisions", type=Path, help="JSON com as respostas à revisão de contas")
    parser.add_argument("--publish", action="store_true", help="Envia a geração promovida à release (token em GITHUB_PAT, GH_TOKEN ou GITHUB_TOKEN)")
    parser.add_argument("--job-file", type=Path, help="Arquivo de estado para acompanhamento pela tela")
    args = parser.parse_args()
    if args.data_base and not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", args.data_base):
        parser.error("--data-base exige YYYY-MM")
    rules = json.loads(args.rules.read_text()) if args.rules else None
    decisions = json.loads(args.decisions.read_text(encoding="utf-8")) if args.decisions else None
    job = _job_writer(args.job_file)
    report, path = update(args.root, period=args.data_base.replace("-", "") if args.data_base else None,
                          csv=args.csv, offline=args.offline, check_only=args.check_only, rules=rules,
                          decisions=decisions, progress=job)
    if args.publish and report["status"] == "updated":
        job("Publicando na release")
        token = next((os.environ[name] for name in TOKEN_NAMES if os.environ.get(name)), None)
        try:
            if not token:
                raise ValueError("Token de publicação ausente")
            report["publication"] = {"status": "published", **publish_update(args.root, report, token)}
        except Exception as exc:
            report["publication"] = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str, allow_nan=False) + "\n")
    job("Concluído", running=False, report=str(path), status=report["status"])
    print(json.dumps({"status": report["status"], "period": report.get("period"), "changed": report["changed"],
                      "pending_review": report.get("pending_review"), "publication": report.get("publication"),
                      "report": str(path), "error": report.get("error")}, ensure_ascii=False))
    published_failed = (report.get("publication") or {}).get("status") == "failed"
    return 1 if report["status"] == "failed" or published_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
