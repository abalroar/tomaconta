"""Atualiza todas as fontes em sequência, uma por processo, e resume o resultado.

Cada etapa roda em processo próprio: a memória volta ao sistema entre elas e a falha de
uma fonte não interrompe as demais. Serve à tela, ao agendador e à linha de comando.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
FINANCIAL = "Análise financeira"
QUARTERLY_EXTRAS = ("passivo", "carteira_pf", "carteira_pj", "principal_individual", "dre_individual")
RATES_WINDOW_DAYS = 90
ATTEMPTS = 2


def build_plan(*, publish=False, today=None) -> list[dict]:
    """Etapas na ordem de execução. A primeira define o trimestre das demais."""
    today = today or date.today()
    financial = ["tools/update_financial_analysis.py"] + (["--publish"] if publish else [])
    cli = ["tools/update_caches_cli.py"]
    start = (today - timedelta(days=RATES_WINDOW_DAYS)).isoformat()
    return [
        {"name": FINANCIAL, "command": financial},
        {"name": "Demais relatórios do IF.data", "command": cli + [item for kind in QUARTERLY_EXTRAS for item in ("--tipo", kind)], "needs_quarter": True},
        {"name": "Séries de crédito (SGS)", "command": cli + ["--tipo", "mercado_credito_sgs"]},
        {"name": "Meios de pagamento (SPB)", "command": cli + ["--tipo", "spb_meios_pagamento"]},
        {"name": "SCR.data", "command": cli + ["--tipo", "scr_data", "--scr-ano-inicial", str(today.year - 1)]},
        {"name": "Taxas de juros", "command": cli + ["--tipo", "taxas_juros_historico", "--taxas-inicio", start, "--taxas-fim", today.isoformat()]},
    ]


def _write(path, payload):
    if path:
        temporary = Path(f"{path}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)


def _last_json(text):
    for line in reversed(text.splitlines()):
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                return None
    return None


def run_plan(root, plan, *, runner=subprocess.run, job_file=None, timeout=4 * 3600) -> dict:
    """Segue até o fim: uma revisão pendente ou uma fonte fora do ar não trava as outras."""
    root = Path(root)
    summary = {"started_at": datetime.now(timezone.utc).isoformat(), "steps": [], "status": "running"}
    quarter = None
    for index, step in enumerate(plan, 1):
        _write(job_file, {"pid": os.getpid(), "stage": f"Etapa {index} de {len(plan)}: {step['name']}", "running": True})
        command = [sys.executable, *step["command"]]
        if step["command"][0].endswith("update_financial_analysis.py"):
            command += ["--root", str(root)]
        if step.get("needs_quarter"):
            if not quarter:
                summary["steps"].append({"name": step["name"], "status": "skipped", "detail": "Trimestre não definido pela análise financeira."})
                continue
            command += ["--periodos", quarter]
        # Quedas de conexão em downloads grandes são comuns; só a análise financeira, que tem revisão, não repete.
        for attempt in range(1 if index == 1 else ATTEMPTS):
            try:
                done = runner(command, cwd=root, capture_output=True, text=True, timeout=timeout)
                code, output, error = done.returncode, done.stdout or "", done.stderr or ""
            except subprocess.TimeoutExpired:
                code, output, error = 1, "", f"Tempo limite de {timeout} s excedido"
            if code == 0:
                break
        result = _last_json(output) if index == 1 else None
        status = "ok" if code == 0 else "failed"
        detail = (error or output).strip().splitlines()[-1][:300] if code and (error or output).strip() else ""
        if result:
            status = {"needs_review": "needs_review", "failed": "failed"}.get(result.get("status"), "ok")
            detail = result.get("error") or result.get("status") or ""
            report = result.get("report")
            if report and Path(report).is_file():
                data = json.loads(Path(report).read_text(encoding="utf-8"))
                quarter = data.get("ifdata_period")
        summary["steps"].append({"name": step["name"], "status": status, "detail": detail})
    states = {step["status"] for step in summary["steps"]}
    summary["status"] = "failed" if states == {"failed"} else "partial" if states - {"ok"} else "ok"
    summary["finished_at"] = datetime.now(timezone.utc).isoformat()
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--publish", action="store_true", help="Publica a análise financeira na release ao concluir")
    parser.add_argument("--plan", action="store_true", help="Só mostra as etapas")
    parser.add_argument("--job-file", type=Path)
    args = parser.parse_args()
    plan = build_plan(publish=args.publish)
    if args.plan:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    summary = run_plan(args.root, plan, job_file=args.job_file)
    directory = args.root / "data/cache/financial_analysis_updates"
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    path = directory / f"tudo-{stamp}.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    _write(args.job_file, {"pid": os.getpid(), "stage": "Concluído", "running": False, "report": str(path), "status": summary["status"]})
    print(json.dumps({"status": summary["status"], "report": str(path)}, ensure_ascii=False))
    return 0 if summary["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
