import json
import sys
from pathlib import Path

import pandas as pd

CANON_PATH = Path("202509BLOPRUDENCIAL 2.CSV")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def read_blo(path: Path) -> pd.DataFrame:
    with path.open("r", encoding="latin-1", errors="replace") as f:
        for i, line in enumerate(f):
            if line.startswith("#DATA_BASE"):
                header_idx = i
                break
        else:
            raise ValueError(f"Header #DATA_BASE not found in {path}")
    df = pd.read_csv(path, sep=";", encoding="latin-1", skiprows=header_idx, decimal=",")
    df = df.rename(columns={"#DATA_BASE": "DATA_BASE"})
    df["CONTA"] = df["CONTA"].astype(str)
    return df


def load_cache_parquet() -> pd.DataFrame:
    parquet_path = Path("data/cache/bloprudencial/dados.parquet")
    if parquet_path.exists():
        return pd.read_parquet(parquet_path)
    return pd.DataFrame()


def main():
    from utils.balanco_4060 import (
        build_mapping_table,
        build_schema_from_rules,
        default_schema_rules,
        normalize_conta_10,
    )

    df_cache = load_cache_parquet()
    if df_cache is not None and not df_cache.empty:
        df = df_cache
        fonte = "parquet_cache"
    else:
        df = read_blo(CANON_PATH)
        fonte = "csv_local"

    df = normalize_conta_10(df)
    rules = default_schema_rules()
    schema = build_schema_from_rules(df, rules)

    Path("data/balanco_4060_schema.json").write_text(
        json.dumps(schema, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    map_df = build_mapping_table(df, schema)
    map_df.to_csv("data/balanco_4060_schema_table.csv", index=False)

    print(f"Fonte: {fonte}")
    print(f"Schema rows: {len(schema)}")
    print(f"Mapping rows: {len(map_df)}")


if __name__ == "__main__":
    main()
