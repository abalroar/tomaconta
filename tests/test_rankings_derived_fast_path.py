import inspect
from pathlib import Path

import pandas as pd

import app1


ROOT = Path(__file__).resolve().parents[1]
METRICS = (
    "Custo de Crédito (%)",
    "Custo de Crédito / Receita de Crédito (%)",
    "Ativos Problemáticos / Carteira Total",
)


def test_rankings_derived_pivot_does_not_repeat_fuzzy_name_normalization():
    source = inspect.getsource(app1._get_rankings_derivadas_pivot)
    assert "_normalizar_instituicoes_rankings_leve(df_out)" not in source
    assert 'df_out["Instituição"].str.strip()' in source


def test_valid_derived_keys_already_match_curated_bundle():
    derived = pd.read_parquet(
        ROOT / "data/bundled/derived_metrics/dados.parquet",
        columns=["Instituição", "Período", "Métrica", "Valor"],
    )
    critical = pd.read_parquet(
        ROOT / "data/bundled/critical_screens/dados.parquet",
        columns=["Instituição", "Período"],
    )
    derived = derived[
        derived["Métrica"].astype(str).isin(METRICS)
        & pd.to_numeric(derived["Valor"], errors="coerce").notna()
    ]
    derived_keys = set(
        derived[["Instituição", "Período"]].astype(str).itertuples(index=False, name=None)
    )
    critical_keys = set(
        critical[["Instituição", "Período"]].astype(str).itertuples(index=False, name=None)
    )
    assert derived_keys <= critical_keys
