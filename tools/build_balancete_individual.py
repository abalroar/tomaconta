"""Monta o histórico de balancetes individuais a partir dos arquivos do BCB."""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pyarrow as pa

from utils.ifdata_cache.balancete_individual import BalanceteIndividualCache, QUARTER_ENDS, statement_rows, write_table, COLUMNS, file_metadata
from utils.ifdata_cache.cosif_4010 import Cosif4010Cache


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inicio", default="202303")
    parser.add_argument("--fim", required=True)
    parser.add_argument("--zips", type=Path, help="Pasta para guardar os arquivos baixados")
    args = parser.parse_args()
    periods = [f"{year}{month}" for year in range(int(args.inicio[:4]), int(args.fim[:4]) + 1) for month in QUARTER_ENDS
               if args.inicio <= f"{year}{month}" <= args.fim]
    source = Cosif4010Cache(ROOT)
    tables = []
    for period in periods:
        result = source.extrair_periodo(period, **({"cache_dir": args.zips} if args.zips else {}))
        if not result.sucesso:
            raise SystemExit(f"{period}: {result.mensagem}")
        rows = statement_rows(result.dados)
        print(period, len(rows), rows.CNPJ.nunique(), flush=True)
        tables.append(pa.Table.from_pandas(rows[COLUMNS], preserve_index=False))
    cache = BalanceteIndividualCache(ROOT)
    with tempfile.TemporaryDirectory(prefix="balancete-", dir=ROOT / "data") as directory:
        candidate = Path(directory) / "dados.parquet"
        write_table(tables, candidate)
        result = cache.salvar_arquivo_local(candidate, file_metadata(candidate))
    if not result.sucesso:
        raise SystemExit(result.mensagem)
    target = ROOT / "data/bundled/balancete_individual"
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(cache.arquivo_dados_runtime, target / "dados.parquet")
    shutil.copy2(cache.arquivo_metadata_runtime, target / "metadata.json")
    print(target, (target / "dados.parquet").stat().st_size)


if __name__ == "__main__":
    main()
