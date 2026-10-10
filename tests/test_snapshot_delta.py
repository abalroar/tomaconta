import pytest
import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "utils" / "snapshot_delta.py"
spec = importlib.util.spec_from_file_location("snapshot_delta", MODULE_PATH)
snapshot_delta = importlib.util.module_from_spec(spec)
assert spec is not None and spec.loader is not None
import sys
sys.modules["snapshot_delta"] = snapshot_delta
spec.loader.exec_module(snapshot_delta)

compute_delta = snapshot_delta.compute_delta


def test_compute_delta_pp_decimal_scale_for_roe_trimestral():
    assert compute_delta(0.2138, 0.2142, "pp", "dec") == pytest.approx(-0.04, abs=0.001)


def test_compute_delta_pp_percent_scale():
    assert compute_delta(21.38, 21.42, "pp", "pct") == pytest.approx(-0.04, abs=0.001)


def test_compute_delta_bps_decimal_scale():
    assert compute_delta(0.1640, 0.1653, "bps", "dec") == pytest.approx(-13.0, abs=0.001)


def test_compute_delta_pct_change():
    assert compute_delta(228.7, 217.5, "pct", "pct") == pytest.approx(5.1494, abs=0.001)


def test_credito_captacoes_qoq_escala_dec():
    # Set/25 = 0.4340, Jun/25 = 0.4097 → +2,43 p.p.
    assert compute_delta(0.4340, 0.4097, "pp", "dec") == pytest.approx(2.43, abs=0.01)


def test_credito_captacoes_yoy_escala_dec():
    # Set/25 = 0.4340, Set/24 = 0.6746 → -24,06 p.p.
    assert compute_delta(0.4340, 0.6746, "pp", "dec") == pytest.approx(-24.06, abs=0.01)


def test_roe_trim_qoq_escala_dec():
    # Set/25 = 0.1596, Jun/25 = 0.1534 → +0,62 p.p.
    assert compute_delta(0.1596, 0.1534, "pp", "dec") == pytest.approx(0.62, abs=0.01)


@pytest.mark.parametrize("current,base,expected", [(2.25,2.18,7),(14.77,15.18,-41),(187.41,193.54,-613),(0,2.18,-218),(-2,-3,100)])
def test_rate_differences_keep_scale_sign_and_allow_zero_or_negative_rates(current,base,expected):
    assert compute_delta(current, base, "bps", "pct") == pytest.approx(expected)
    assert compute_delta(current/100, base/100, "bps", "dec") == pytest.approx(expected)


@pytest.mark.parametrize("base", [0, -1, -100])
def test_relative_growth_requires_positive_base_but_absolute_difference_remains_available(base):
    assert compute_delta(50, base, "pct") is None
    assert compute_delta(50, base, "absolute") == 50-base


@pytest.mark.parametrize("bad", [float("inf"),float("-inf"),float("nan"),None])
def test_nonfinite_inputs_never_become_numeric_deltas(bad):
    for kind in ("bps","pp","pct","absolute"):
        assert compute_delta(bad, 1, kind) is None
        assert compute_delta(1, bad, kind) is None


def test_monetary_growth_and_multiple_difference_use_distinct_units():
    assert compute_delta(110,100,"pct") == pytest.approx(10)
    assert compute_delta(11,10,"absolute") == 1
    assert compute_delta(-50,100,"pct") == pytest.approx(-150)
