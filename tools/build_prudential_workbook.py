"""Build a reusable prudential financial workbook from persisted sources."""
from __future__ import annotations

import argparse
import json
import hashlib
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

import pandas as pd

from utils.ifdata_cache.bloprudencial_cache import BloprudencialCache, load_bloprudencial_parquet_slice
from utils.ifdata_cache.bloprudencial_ingest import ingest_source
from utils.prudential_analysis import build_analysis
from utils.prudential_nim import required_periods
from utils.prudential_workbook import analysis_spec, render_xlsx


def load_local_sources(root,periods):
    cosif_cache=BloprudencialCache(root)
    cosif=load_bloprudencial_parquet_slice(cosif_cache,periodos_yyyymm=periods)
    cosif.attrs["prudential_provenance"]={"filename":"bloprudencial/dados.parquet","sha256":hashlib.sha256(cosif_cache.arquivo_dados.read_bytes()).hexdigest()}
    sources={}
    for kind in ["ativo","dre","capital","principal","carteira_instrumentos"]:
        # Select a coherent data/metadata pair, respecting published revisions.
        from utils.ifdata_cache import CacheManager
        cache=CacheManager(root).get_cache(kind)
        if cache is not None and cache.arquivo_dados.exists():
            sources[kind]=pd.read_parquet(cache.arquivo_dados)
            sources[kind].attrs["prudential_provenance"]={"filename":f"{kind}/dados.parquet","sha256":hashlib.sha256(cache.arquivo_dados.read_bytes()).hexdigest()}
    return cosif,sources


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,default=ROOT)
    parser.add_argument("--code",required=True,help="COD_CONGL / CodInst exato")
    parser.add_argument("--periods",nargs="+",required=True)
    parser.add_argument("--import-csv",type=Path,action="append",default=[])
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--spec-only",action="store_true")
    args=parser.parse_args()
    for path in args.import_csv:ingest_source(path,args.root)
    cosif,sources=load_local_sources(args.root,required_periods(args.periods))
    analysis=build_analysis(cosif,sources,args.code,args.periods)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.with_suffix(".spec.json").write_text(json.dumps(analysis_spec(analysis),ensure_ascii=False,indent=2,allow_nan=False))
    args.output.with_suffix(".validation.json").write_text(json.dumps(analysis.checks,ensure_ascii=False,indent=2,allow_nan=False))
    if not args.spec_only:args.output.write_bytes(render_xlsx(analysis))
    failures=[x for x in analysis.checks if x["status"]=="Divergência"]
    print(json.dumps({"institution":analysis.institution,"checks":len(analysis.checks),"differences":failures,
                      "unavailable_checks":sum(x["status"]=="N/D" for x in analysis.checks),"output":str(args.output)},ensure_ascii=False,indent=2))


if __name__=="__main__":main()
