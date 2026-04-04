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
