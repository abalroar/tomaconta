"""Keep the scalar shortcut identical to the prior pandas conversion."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from utils.ifdata_cache import critical_screens as critical


def _legacy_coerce_numeric_value(value):
    if value is None or pd.isna(value):
        return None
    try:
        coerced = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    except Exception:
        return None
    if pd.isna(coerced):
        return None
    return float(coerced)


_CASES = [
    None, pd.NA, pd.NaT, True, False, np.bool_(True), np.bool_(False),
    0, 1, -1, 0.0, -0.0, 0.1, np.nan, np.inf, -np.inf,
    np.nextafter(0.0, 1.0), np.finfo(np.float64).max,
    np.finfo(np.float64).tiny,
    Decimal("0.1"), Decimal("-0"), Decimal("1E100"),
    Decimal("NaN"), Decimal("Infinity"),
    Fraction(1, 3), Fraction(4, 1), 1 + 2j, np.complex128(1 + 2j),
    "0", "-0", "0.1", "1.25", "1e100", "1,25", " 12.5 ",
    "N/D", "nan", "inf", "", b"1.25", object(),
    date(2025, 1, 1), datetime(2025, 1, 1), timedelta(days=1),
    pd.Timestamp("2025-01-01"), pd.Timedelta(days=1),
    np.datetime64("2025-01-01"), np.timedelta64(1, "D"),
    np.timedelta64(1, "ns"), np.timedelta64(1, "us"), np.timedelta64(1, "s"),
]
_CASES += [sign * (2**bits + offset)
           for bits in (53, 63, 64, 100, 1023, 1024)
           for offset in (-1, 0, 1, 12345)
           for sign in (-1, 1)]
_CASES += [dtype(value)
           for dtype in (np.int8, np.int16, np.int32, np.int64,
                         np.uint8, np.uint16, np.uint32, np.uint64)
           for value in (0, 1, np.iinfo(dtype).max)]
_CASES += [dtype(value)
           for dtype in (np.float16, np.float32, np.float64, np.longdouble)
           for value in (0, -0.0, 0.1, np.nan, np.inf, -np.inf)]


@pytest.mark.parametrize("value", _CASES, ids=lambda value: type(value).__name__)
def test_numeric_shortcut_matches_legacy_scalar_conversion(value):
    try:
        expected = _legacy_coerce_numeric_value(value)
    except Exception as error:
        with pytest.raises(type(error), match=str(error)):
            critical._coerce_numeric_value(value)
    else:
        actual = critical._coerce_numeric_value(value)
        if expected is None:
            assert actual is None
        else:
            assert type(actual) is type(expected) is float
            assert actual.hex() == expected.hex()


@pytest.mark.parametrize("value", [0, -1, 0.1, np.int64(12), np.uint64(2**64 - 1),
                                   np.float16(0.1), np.float32(0.1), np.float64(0.1)])
def test_common_numbers_do_not_construct_a_series(monkeypatch, value):
    def unexpected_series(*args, **kwargs):
        raise AssertionError("Common scalar conversion constructed a Series")

    monkeypatch.setattr(pd, "Series", unexpected_series)
    assert critical._coerce_numeric_value(value).hex() == float(value).hex()


def test_overflowing_integer_uses_legacy_fallback(monkeypatch):
    value = 2**4096
    expected = _legacy_coerce_numeric_value(value)
    original_series = pd.Series
    calls = []

    def observed_series(*args, **kwargs):
        calls.append(args)
        return original_series(*args, **kwargs)

    monkeypatch.setattr(pd, "Series", observed_series)
    assert critical._coerce_numeric_value(value) == expected
    assert len(calls) == 1


def _compare_complete_dataframes(monkeypatch, inputs):
    optimized = critical._coerce_numeric_value
    with monkeypatch.context() as original:
        original.setattr(critical, "_coerce_numeric_value", _legacy_coerce_numeric_value)
        expected = critical.build_critical_screens_dataframe(**inputs)
    assert critical._coerce_numeric_value is optimized
    actual = critical.build_critical_screens_dataframe(**inputs)
    pd.testing.assert_frame_equal(actual, expected, check_exact=True)
    return actual


def test_complete_multi_period_dataframe_matches_legacy_conversion(monkeypatch, tmp_path):
    periods = ["4/2023", "1/2024", "2/2024", "3/2024", "4/2024", "1/2025", "2/2025", "3/2025"]
    names = ["ITAU - PRUDENCIAL", "BRADESCO - PRUDENCIAL"]
    monkeypatch.setattr(critical, "build_institution_to_conglomerate_map", lambda root: {})
    frames = {key: [] for key in ("principal", "ativo", "passivo", "capital", "dre",
                                "carteira_pf", "carteira_pj", "carteira_instrumentos")}
    bloprud = []
    for institution_index, name in enumerate(names):
        for index, period in enumerate(periods):
            factor = float(index + 1 + institution_index)
            identity = {"Instituição": name, "Período": period}
            frames["principal"].append({**identity, "Ativo Total": factor * 1000,
                                       "Patrimônio Líquido": factor * 100,
                                       "Lucro Líquido Acumulado YTD": factor * 5,
                                       "Captações": factor * 400})
            frames["ativo"].append({**identity, "Disponibilidades (a)": factor * 10,
                                   "Aplicações Interfinanceiras de Liquidez (b)": "1.25",
                                   "Títulos e Valores Mobiliários (c)": None if index == 3 else factor * 30,
                                   "Valor Contábil Bruto (e1)": factor * 100,
                                   "Valor Contábil Bruto (f1)": factor * 20,
                                   "Valor Contábil Bruto (g1)": factor * 30,
                                   "Valor Contábil Bruto (h1)": factor * 40,
                                   "Operações de Crédito (d1)": factor * 120,
                                   "Perda Esperada (e2)": factor,
                                   "Perda Esperada (f2)": factor * 2,
                                   "Perda Esperada (g2)": factor * 3,
                                   "Perda Esperada (h2)": factor * 4})
            frames["passivo"].append({**identity,
                                     "Captações (e) = (a) + (b) + (c) + (d)": factor * 400,
                                     "Instrumentos de Dívida Elegíveis a Capital (h)": factor * 50,
                                     "Depósitos à Vista (a1)": factor * 10,
                                     "Depósitos de Poupança (a2)": factor * 20,
                                     "Depósitos Interfinanceiros (a3)": factor * 30,
                                     "Depósitos a Prazo (a4)": factor * 40,
                                     "Outros Depósitos (a5)": 0.0,
                                     "Depósitos Outros (a6)": np.nan})
            frames["capital"].append({**identity, "Capital Principal": factor * 12,
                                     "Capital Complementar": factor * 3,
                                     "Capital Nível II": factor * 2, "RWA Total": factor * 100})
            frames["dre"].append({**identity, "Resultado com Perda Esperada (f)": factor * -12,
                                 "Rendas de Operações de Crédito (c)": factor * 90,
                                 "Rendas de Arrendamento Financeiro (d)": factor * 10,
                                 "Rendas de Outras Operações com Características de Concessão de Crédito (e)": factor * 5,
                                 "Rendas de Aplicações Interfinanceiras de Liquidez (a)": factor * 8,
                                 "Rendas de Títulos e Valores Mobiliários (b)": factor * 7,
                                 "Despesas de Captações (g)": factor * 11})
            frames["carteira_pf"].append({**identity, "Total da Carteira PF": factor * 100})
            frames["carteira_pj"].append({**identity, "Total da Carteira PJ": factor * 200})
            frames["carteira_instrumentos"].append({**identity, "C4": factor * 10,
                                                  "C5": factor * 5, "Total Geral": factor * 400,
                                                  "Inadimplência": factor * 12,
                                                  "Ativos problemáticos": factor * 24})
            quarter, year = period.split("/")
            for account, amount in (("1490000004", 50), ("1890000006", 10),
                                    ("3311000002", 300), ("3312000001", 400), ("3313000000", 500)):
                bloprud.append({"DATA_BASE": f"{year}{int(quarter)*3:02}", "DOCUMENTO": 4060,
                                "NOME_INSTITUICAO": name, "NOME_CONGL": name,
                                "COD_CONGL": f"C000000{institution_index}",
                                "CONTA": account, "SALDO": factor * amount})
    inputs = {f"df_{key}": pd.DataFrame(rows) for key, rows in frames.items()}
    inputs.update(df_bloprudencial=pd.DataFrame(bloprud), base_dir=tmp_path)
    result = _compare_complete_dataframes(monkeypatch, inputs)
    assert len(result) == 16
    assert len(result.columns) >= 90
    assert result["CapitalDisponivel"].all()
    assert result["BloprudencialDisponivel"].any()


def test_real_bundle_slice_matches_legacy_conversion(monkeypatch, tmp_path):
    root = Path(__file__).resolve().parents[1]
    bundled = root / "data" / "bundled"
    periods = ["4/2023", "1/2024", "2/2024", "3/2024", "4/2024", "1/2025", "2/2025", "3/2025"]
    names = ["ITAU - PRUDENCIAL", "BRADESCO - PRUDENCIAL"]
    filters = [("Instituição", "in", names), ("Período", "in", periods)]
    frames = {f"df_{key}": pd.read_parquet(bundled / key / "dados.parquet", filters=filters)
              for key in ("principal", "ativo", "passivo", "capital", "dre",
                          "carteira_pf", "carteira_pj", "carteira_instrumentos")}
    monkeypatch.setattr(critical, "build_institution_to_conglomerate_map", lambda root: {})
    frames.update(df_bloprudencial=None, base_dir=tmp_path)
    result = _compare_complete_dataframes(monkeypatch, frames)
    assert len(result) == 16
    assert len(result.columns) >= 90
    assert result["Ativo Total"].notna().all()
    assert result["CapitalDisponivel"].all()
