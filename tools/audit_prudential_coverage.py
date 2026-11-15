"""Exercise every institution/month in the consumed prudential cache."""
from __future__ import annotations

import argparse
from collections import Counter, deque
from concurrent.futures import ProcessPoolExecutor
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd

from tools.build_prudential_workbook import load_local_sources
from utils.ifdata_cache.bloprudencial_cache import BloprudencialCache
from utils.prudential_analysis import build_analysis
from utils.prudential_workbook import render_xlsx


def audit_institution(job):
    code, frame, sources, export, pptx = job
    rows = []
    available = sorted(frame.DATA_BASE.unique())
    size = min(8, len(available))
    comparative = [available[round(i*(len(available)-1)/max(1,size-1))] for i in range(size)]
    # Setembro e dezembro precisam do junho do ano; por isso a instituição inteira segue junto.
    selections = [(str(p), frame, [str(p)]) for p in sorted(frame.DATA_BASE.unique())]
    selections.append(("comparative", frame, comparative))
    for period, data, periods in selections:
        item = {"code": code, "period": period, "periods": periods, "source_rows": len(data)}
        try:
            analysis = build_analysis(data, sources, code, periods)
            item["name"] = analysis.institution
            item["checks"] = dict(Counter(c["status"] for c in analysis.checks))
            item["primary_checks"] = {c["check"]: c["status"] for c in analysis.checks
                                      if c["check"].startswith(("Balanço:", "DRE: resultado"))}
            item["differences"] = [c for c in analysis.checks if c["status"] == "Divergência"]
            item["missing"] = {name: sum(s.cells[f"C{r}"].value == "N/D" for r in analysis.rows[name].values())
                               for name, s in analysis.sheets.items() if name in analysis.rows}
            if export:
                payload = render_xlsx(analysis)
                with zipfile.ZipFile(BytesIO(payload)) as workbook:
                    assert workbook.testzip() is None
                    assert not any(b't="e"' in workbook.read(name) for name in workbook.namelist()
                                   if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"))
                item["xlsx_bytes"] = len(payload)
            if pptx and period == "comparative":
                from utils.prudential_pptx import render_pptx
                payload = render_pptx(analysis)
                with zipfile.ZipFile(BytesIO(payload)) as deck:
                    assert deck.testzip() is None
                    assert not any(name.startswith("ppt/media/") for name in deck.namelist())
                item["pptx_bytes"] = len(payload)
            item["generated"] = True
        except Exception as exc:
            item.update(generated=False, error=f"{type(exc).__name__}: {exc}")
        rows.append(item)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--xlsx", action="store_true")
    parser.add_argument("--pptx", action="store_true", help="Verify an eight-period native deck for every institution")
    args = parser.parse_args()
    start = time.monotonic()
    path = BloprudencialCache(args.root).arquivo_dados
    periods = sorted(pd.read_parquet(path, columns=["DATA_BASE"]).DATA_BASE.astype(str).unique())
    cosif, sources = load_local_sources(args.root, periods)
    sources_by_code = {kind: {code: group for code, group in frame.groupby("CodInst")} for kind, frame in sources.items()}
    jobs = ((code, group, {kind: groups.get(code, pd.DataFrame()) for kind, groups in sources_by_code.items()}, args.xlsx, args.pptx)
            for code, group in cosif.groupby("COD_CONGL", sort=True))
    results = []
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        # Bounded submissions work on the same Python versions as Streamlit.
        pending = deque()
        for _ in range(args.workers * 2):
            job = next(jobs, None)
            if job is not None: pending.append(pool.submit(audit_institution, job))
        i = 0
        while pending:
            rows = pending.popleft().result()
            i += 1
            results.extend(rows)
            if i % 20 == 0:
                print(json.dumps({"institutions": i, "pairs": len(results), "seconds": round(time.monotonic()-start)}), flush=True)
            job = next(jobs, None)
            if job is not None: pending.append(pool.submit(audit_institution, job))
    comparisons = [r for r in results if r["period"] == "comparative"]
    results = [r for r in results if r["period"] != "comparative"]
    summary = {"institutions": cosif.COD_CONGL.nunique(), "periods": periods, "pairs": len(results),
               "generated": sum(r["generated"] for r in results), "xlsx_verified": args.xlsx, "pptx_verified": args.pptx,
               "comparisons": len(comparisons), "comparisons_generated": sum(r["generated"] for r in comparisons),
               "duplicate_keys": int(cosif.duplicated(["COD_CONGL", "DATA_BASE", "DOCUMENTO", "CONTA"]).sum()),
               "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
               "seconds": round(time.monotonic()-start), "results": results, "comparative_results": comparisons}
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k not in {"results", "comparative_results"}}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
