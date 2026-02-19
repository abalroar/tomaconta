#!/usr/bin/env python3
"""Agrega métricas de usabilidade da aba Peers (Tabela) a partir dos logs.

Entrada esperada: linhas de log contendo:
- [PEERS_PERF] { ... tempos por etapa ... }
- [ROE_TRACE] { ... contexto/inputs do ROE ... }

Exemplo:
  python tools/measure_peers_usability.py --log-file streamlit.log
"""

from __future__ import annotations

import argparse
import ast
import json
import statistics
from pathlib import Path
from typing import Any

PEERS_PREFIX = "[PEERS_PERF]"
ROE_PREFIX = "[ROE_TRACE]"

DEFAULT_INTERACTIVE_STAGES = [
    "a_leitura_dados_brutos",
    "a_leitura_cache_slices",
    "b_filtros_alias_periodo_banco",
    "c_joins_mapeamentos_metricas_extra",
    "d_calculo_metricas_colunas_derivadas",
    "e_formatacao",
    "f_render_tabela",
]


def _parse_payload_from_line(prefix: str, line: str) -> dict[str, Any] | None:
    idx = line.find(prefix)
    if idx < 0:
        return None
    tail = line[idx + len(prefix):].strip()
    if not tail:
        return None
    try:
        obj = ast.literal_eval(tail)
    except Exception:
        return None
    if isinstance(obj, dict):
        return obj
    return None


def _summary(values: list[float]) -> dict[str, float]:
    if not values:
        return {"n": 0, "min_s": 0.0, "p50_s": 0.0, "p95_s": 0.0, "max_s": 0.0, "mean_s": 0.0}
    values_sorted = sorted(values)
    p95_idx = max(0, min(len(values_sorted) - 1, int(round((len(values_sorted) - 1) * 0.95))))
    return {
        "n": len(values_sorted),
        "min_s": round(values_sorted[0], 3),
        "p50_s": round(statistics.median(values_sorted), 3),
        "p95_s": round(values_sorted[p95_idx], 3),
        "max_s": round(values_sorted[-1], 3),
        "mean_s": round(statistics.mean(values_sorted), 3),
    }


def _build_roe_consistency_report(roe_events: list[dict[str, Any]]) -> dict[str, Any]:
    peers = [e for e in roe_events if e.get("contexto", "").startswith("peers")]
    scatter = [e for e in roe_events if e.get("contexto", "").startswith("scatter")]

    def _pick_latest(events: list[dict[str, Any]]) -> dict[str, Any] | None:
        return events[-1] if events else None

    latest_peers = _pick_latest(peers)
    latest_scatter = _pick_latest(scatter)

    same_target = False
    delta = None
    if latest_peers and latest_scatter:
        same_target = (
            latest_peers.get("instituicao") == latest_scatter.get("instituicao")
            and latest_peers.get("periodo") == latest_scatter.get("periodo")
        )
        rp = latest_peers.get("roe_recalculado")
        rs = latest_scatter.get("roe_recalculado")
        if rp is not None and rs is not None:
            delta = round(float(rp) - float(rs), 10)

    return {
        "samples": len(roe_events),
        "latest_peers": latest_peers,
        "latest_scatter": latest_scatter,
        "same_target": same_target,
        "delta_roe_recalculado": delta,
    }


def run(log_file: Path, sla_seconds: float) -> dict[str, Any]:
    if not log_file.exists():
        raise FileNotFoundError(f"log file não encontrado: {log_file}")

    peers_events: list[dict[str, Any]] = []
    roe_events: list[dict[str, Any]] = []

    for line in log_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        perf_payload = _parse_payload_from_line(PEERS_PREFIX, line)
        if perf_payload:
            peers_events.append(perf_payload)
            continue
        roe_payload = _parse_payload_from_line(ROE_PREFIX, line)
        if roe_payload:
            roe_events.append(roe_payload)

    stage_values: dict[str, list[float]] = {}
    interactive_totals: list[float] = []
    export_totals: list[float] = []

    for ev in peers_events:
        for k, v in ev.items():
            try:
                stage_values.setdefault(k, []).append(float(v))
            except Exception:
                pass

        interactive_total = 0.0
        for stage in DEFAULT_INTERACTIVE_STAGES:
            if stage in ev:
                interactive_total += float(ev[stage])
        interactive_totals.append(interactive_total)

        export_totals.append(float(ev.get("g_preparo_export", 0.0) or 0.0))

    stage_summary = {stage: _summary(vals) for stage, vals in sorted(stage_values.items())}
    total_summary = _summary(interactive_totals)
    export_summary = _summary(export_totals)

    bottlenecks = sorted(
        [
            {"stage": stage, "mean_s": info["mean_s"], "p95_s": info["p95_s"]}
            for stage, info in stage_summary.items()
            if stage != "g_preparo_export"
        ],
        key=lambda x: x["mean_s"],
        reverse=True,
    )[:5]

    sla_pass = total_summary["p95_s"] <= sla_seconds if total_summary["n"] > 0 else False

    report = {
        "input": {
            "log_file": str(log_file),
            "samples_peers_perf": len(peers_events),
            "samples_roe_trace": len(roe_events),
            "sla_interactive_seconds": sla_seconds,
        },
        "interactive_total": total_summary,
        "export_total": export_summary,
        "stages": stage_summary,
        "top_bottlenecks": bottlenecks,
        "sla_pass": sla_pass,
        "roe_consistency": _build_roe_consistency_report(roe_events),
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log-file", type=Path, required=True)
    parser.add_argument("--sla-seconds", type=float, default=3.0)
    parser.add_argument("--output", type=Path, default=Path("docs/peers_usability_report.json"))
    args = parser.parse_args()

    report = run(args.log_file, args.sla_seconds)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"[OK] relatório salvo em {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
