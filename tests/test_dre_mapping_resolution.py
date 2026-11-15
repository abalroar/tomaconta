import pandas as pd
import pytest

import app1


def test_build_dre_consolidated_mapping_entries_includes_q4_2025_overrides():
    entries = {entry["label"]: entry for entry in app1._build_dre_consolidated_mapping_entries()}

    assert entries["Desp. Tributárias"]["sources_new_q4"] == ["Despesas Tributárias (r)"]
    assert entries["IR/CSLL"]["sources_new_q4"] == ["Imposto de Renda e Contribuição Social (x)"]
    assert entries["Lucro Líquido Período Acumulado"]["sources_new_q4"] == [
        "Lucro Líquido (z) = (w) + (x) + (y)"
    ]
    assert entries["Desp. JSCP Cooperativas"]["has_sources_new_q4"] is True
    assert entries["Desp. JSCP Cooperativas"]["sources_new_q4"] == []


def test_resolve_dre_entry_values_period_aware_handles_2025_q4_shift_and_unavailable_jscp():
    df = pd.DataFrame(
        [
            {
                "Periodo": "3/2025",
                "ano": 2025,
                "mes": 9,
                "Despesas Tributárias (s)": -100.0,
                "Despesas Tributárias (r)": pd.NA,
                "Despesas de Juros Sobre Capital Próprio de Cooperativas (r)": -7.0,
            },
            {
                "Periodo": "4/2025",
                "ano": 2025,
                "mes": 12,
                "Despesas Tributárias (s)": pd.NA,
                "Despesas Tributárias (r)": -150.0,
                "Despesas de Juros Sobre Capital Próprio de Cooperativas (r)": pd.NA,
            },
            {
                "Periodo": "4/2024",
                "ano": 2024,
                "mes": 12,
                "Despesas Tributárias (d5)": -90.0,
                "Juros Sobre Capital Social de Cooperativas (k)": -3.0,
            },
        ]
    )

    numericas = {col: pd.to_numeric(df[col], errors="coerce") for col in df.columns if col not in {"Periodo", "ano", "mes"}}
    source_to_column = {
        source: source
        for source in numericas.keys()
    }

    trib_entry = {
        "sources_old": ["Despesas Tributárias (d5)"],
        "sources_new": ["Despesas Tributárias (s)"],
        "sources_new_q4": ["Despesas Tributárias (r)"],
        "has_sources_new_q4": True,
    }
    trib_values = app1._resolve_dre_entry_values_period_aware(df, trib_entry, numericas, source_to_column)
    assert trib_values.tolist() == [-100.0, -150.0, -90.0]

    jscp_entry = {
        "sources_old": ["Juros Sobre Capital Social de Cooperativas (k)"],
        "sources_new": ["Despesas de Juros Sobre Capital Próprio de Cooperativas (r)"],
        "sources_new_q4": [],
        "has_sources_new_q4": True,
    }
    jscp_values = app1._resolve_dre_entry_values_period_aware(df, jscp_entry, numericas, source_to_column)
    assert jscp_values.iloc[0] == -7.0
    assert pd.isna(jscp_values.iloc[1])
    assert jscp_values.iloc[2] == -3.0


def test_2026_keeps_layout_introduced_in_december_2025():
    df = pd.DataFrame({"ano": [2026, 2026], "mes": [3, 6],
                       "Despesas Tributárias (s)": [-999., -999.],
                       "Despesas Tributárias (r)": [-100., 0.]})
    entry = next(e for e in app1._build_dre_consolidated_mapping_entries() if e["label"] == "Desp. Tributárias")
    sources = {c: c for c in df if c.startswith("Despesas")}
    values = app1._resolve_dre_entry_values_period_aware(df, entry, {c: df[c] for c in sources}, sources)
    assert values.tolist() == [-100., 0.]


@pytest.mark.parametrize("cache", ["dre", "dre_individual"])
def test_june_published_dre_exposes_reported_tax_and_net_income(cache):
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    df = pd.read_parquet(root / f"data/bundled/{cache}/dados.parquet")
    df = df[df["Período"].eq("2/2026")].copy()
    df["ano"], df["mes"] = 2026, 6
    entries = {e["label"]: e for e in app1._build_dre_consolidated_mapping_entries()}
    for label in ["Desp. Tributárias", "IR/CSLL", "Lucro Líquido Período Acumulado"]:
        entry = entries[label]
        sources = {s: app1._find_dre_source_column(df, s) for s in entry["sources_new_q4"]}
        assert all(sources.values())
        numeric = {col: pd.to_numeric(df[col], errors="coerce") for col in sources.values()}
        actual = app1._resolve_dre_entry_values_period_aware(df, entry, numeric, sources)
        expected = pd.concat(list(numeric.values()), axis=1).sum(axis=1, min_count=1)
        assert expected.notna().sum() > 1000
        pd.testing.assert_series_equal(actual, expected, check_names=False)
