from pathlib import Path

import pandas as pd
import pyarrow.dataset as ds
import pytest

from utils.ifdata_cache import institutions


def _legacy_canonicalize_dataframe(
    df, *, catalog_map=None, base_dir=None, name_column="Instituição", extra_frames=(),
):
    if df is None or df.empty or name_column not in df.columns:
        return df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
    catalog = (catalog_map if catalog_map is not None
               else institutions.build_institution_to_conglomerate_map(base_dir))
    out = df.copy()
    code_to_name = institutions.build_code_to_name_map(out, *list(extra_frames))
    code_columns = [col for col in ("CodInst", "COD_INST", "cod_inst", "CODINST") if col in out.columns]

    def resolve(row):
        raw_name = str(row.get(name_column) or "").strip()
        code_key = ""
        for code_col in code_columns:
            code_val = row.get(code_col)
            if pd.isna(code_val):
                continue
            code_key = institutions.normalize_institution_code(code_val)
            if code_key:
                break
        nome_base = raw_name
        if (institutions.is_placeholder_institution_name(raw_name)
                or institutions.parece_codigo_instituicao(raw_name)) and code_key:
            nome_base = (code_to_name.get(code_key)
                         or institutions.resolver_nome_instituicao(code_key, raw_name))
        return institutions.canonicalize_institution_name(nome_base, catalog_map=catalog, base_dir=base_dir)

    out[name_column] = out.apply(resolve, axis=1)
    return out


def test_local_name_cache_preserves_repeated_distinct_and_missing_names(monkeypatch):
    frame = pd.DataFrame({
        "Instituição": ["Banco Alfa", "Banco Alfa", "  Banco Alfa  ", "Banco Beta", "", None,
                        "BANCO XP", "BANCO XP"],
        "Período": pd.Series(["1/2024"] * 8, dtype="string"),
        "Valor": pd.Series([1, 2, 3, 4, 5, 6, 7, 8], dtype="Int64"),
    }, index=[4, 1, 1, 5, 9, 10, 11, 12])
    frame.attrs["source"] = "BCB"
    catalog = {"BANCO ALFA": "ALFA - PRUDENCIAL", "BANCO BETA": "BETA - PRUDENCIAL",
               "BANCO XP HOLDING": "XP - PRUDENCIAL",
               "BANCO XP INVESTIMENTOS": "XP INVESTIMENTOS - PRUDENCIAL"}
    original_frame = frame.copy(deep=True)
    expected = _legacy_canonicalize_dataframe(frame, catalog_map=catalog)
    original = institutions.canonicalize_institution_name
    calls = []

    def observed(name, **kwargs):
        calls.append(name)
        return original(name, **kwargs)

    monkeypatch.setattr(institutions, "canonicalize_institution_name", observed)
    result = institutions.canonicalize_institution_dataframe(frame, catalog_map=catalog)
    pd.testing.assert_frame_equal(result, expected, check_exact=True)
    pd.testing.assert_frame_equal(frame, original_frame, check_exact=True)
    assert result.attrs == expected.attrs == frame.attrs
    assert calls == ["Banco Alfa", "Banco Beta", "", "BANCO XP"]


def test_cache_key_uses_resolved_name_after_code_and_placeholder_resolution(monkeypatch):
    frame = pd.DataFrame({
        "CodInst": ["C001", "C002", "C003", "C004", "C001", "C002", "C003", "C004"],
        "Instituição": ["[IF 123]"] * 8,
        "Valor": [1.25] * 8,
    })
    extra = pd.DataFrame({"CodInst": ["C001", "C002"],
                          "Instituição": ["Banco Alfa", "Banco Beta"]})
    fallback_names = {"C003": "Banco Gama", "C004": "Banco Delta"}
    monkeypatch.setattr(institutions, "resolver_nome_instituicao",
                        lambda code, raw: fallback_names[code])
    catalog = {f"BANCO {name.upper()}": f"{name.upper()} - PRUDENCIAL"
               for name in ("Alfa", "Beta", "Gama", "Delta")}
    expected = _legacy_canonicalize_dataframe(frame, catalog_map=catalog, extra_frames=[extra])
    original = institutions.canonicalize_institution_name
    calls = []

    def observed(name, **kwargs):
        calls.append(name)
        return original(name, **kwargs)

    monkeypatch.setattr(institutions, "canonicalize_institution_name", observed)
    result = institutions.canonicalize_institution_dataframe(frame, catalog_map=catalog, extra_frames=[extra])
    pd.testing.assert_frame_equal(result, expected, check_exact=True)
    assert result["Instituição"].tolist() == [f"{name.upper()} - PRUDENCIAL"
                                            for name in ("Alfa", "Beta", "Gama", "Delta") * 2]
    assert calls == ["Banco Alfa", "Banco Beta", "Banco Gama", "Banco Delta"]


def test_cache_is_scoped_to_one_dataframe_invocation():
    frame = pd.DataFrame({"Instituição": ["Banco Alfa", "Banco Alfa"]})
    catalog = {"BANCO ALFA": "ALFA ANTIGO - PRUDENCIAL"}
    first = institutions.canonicalize_institution_dataframe(frame, catalog_map=catalog)
    assert first["Instituição"].tolist() == ["ALFA ANTIGO - PRUDENCIAL"] * 2
    catalog["BANCO ALFA"] = "ALFA NOVO - PRUDENCIAL"
    second = institutions.canonicalize_institution_dataframe(frame, catalog_map=catalog)
    pd.testing.assert_frame_equal(second, _legacy_canonicalize_dataframe(frame, catalog_map=catalog), check_exact=True)
    assert second["Instituição"].tolist() == ["ALFA NOVO - PRUDENCIAL"] * 2


@pytest.mark.parametrize("dtype", ["string", "category"])
def test_custom_name_column_and_extension_dtype_match_legacy(dtype):
    frame = pd.DataFrame({
        "NomeInstituicao": pd.Series(["[IF 123]", "Banco Alfa", "Banco Beta"], dtype=dtype),
        "CodInst": pd.Series([123, 123, None], dtype="Int64"),
        "Valor": pd.Series([1.25, None, 2.5], dtype="Float64"),
    })
    catalog = {"BANCO ALFA": "ALFA - PRUDENCIAL", "BANCO BETA": "BETA - PRUDENCIAL"}
    kwargs = {"catalog_map": catalog, "name_column": "NomeInstituicao"}
    pd.testing.assert_frame_equal(institutions.canonicalize_institution_dataframe(frame, **kwargs),
                                  _legacy_canonicalize_dataframe(frame, **kwargs), check_exact=True)


def test_nan_and_pandas_na_keep_legacy_behavior():
    frame = pd.DataFrame({"Instituição": [float("nan"), "Banco Alfa", float("nan")]})
    actual = institutions.canonicalize_institution_dataframe(frame, catalog_map={})
    pd.testing.assert_frame_equal(actual, _legacy_canonicalize_dataframe(frame, catalog_map={}), check_exact=True)
    assert actual["Instituição"].tolist() == ["nan", "Banco Alfa", "nan"]
    with_na = pd.DataFrame({"Instituição": ["Banco Alfa", pd.NA]})
    with pytest.raises(TypeError, match="boolean value of NA is ambiguous"):
        _legacy_canonicalize_dataframe(with_na, catalog_map={})
    with pytest.raises(TypeError, match="boolean value of NA is ambiguous"):
        institutions.canonicalize_institution_dataframe(with_na, catalog_map={})


def test_real_root_catalog_dataframe_matches_legacy(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    dataset = ds.dataset(root / "data/bundled/principal/dados.parquet", format="parquet")
    selector = dataset.to_table(columns=["Instituição", "Período"]).to_pandas()
    period_count = selector["Período"].nunique()
    coverage = selector.groupby("Instituição")["Período"].nunique()
    names = sorted(coverage[coverage == period_count].index.astype(str).tolist())[:12]
    assert len(names) == 12
    frame = dataset.to_table(filter=ds.field("Instituição").isin(names)).to_pandas()
    catalog = institutions.build_institution_to_conglomerate_map(root)
    assert catalog
    expected = _legacy_canonicalize_dataframe(frame, catalog_map=catalog, base_dir=root)
    original = institutions.canonicalize_institution_name
    calls = []

    def observed(name, **kwargs):
        calls.append(name)
        return original(name, **kwargs)

    monkeypatch.setattr(institutions, "canonicalize_institution_name", observed)
    actual = institutions.canonicalize_institution_dataframe(frame, catalog_map=catalog, base_dir=root)
    pd.testing.assert_frame_equal(actual, expected, check_exact=True)
    assert len(actual) == 12 * period_count
    assert len(calls) == len(set(calls)) == 12
