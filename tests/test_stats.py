import pytest
from mcpbench.stats import wilson_interval


def test_zero_total():
    assert wilson_interval(0, 0) == (0.0, 0.0)


def test_all_hits_interval_below_one():
    lo, hi = wilson_interval(5, 5)
    assert lo > 0.0
    assert hi <= 1.0


def test_no_hits_interval_above_zero():
    lo, hi = wilson_interval(0, 5)
    assert lo >= 0.0
    assert hi < 1.0


def test_known_n5_k4_value():
    # hand-verified Wilson interval for k=4, n=5, z=1.96
    lo, hi = wilson_interval(4, 5)
    assert lo == pytest.approx(0.3754, abs=1e-3)
    assert hi == pytest.approx(0.9640, abs=1e-3)


def test_wider_interval_at_smaller_n():
    lo5, hi5 = wilson_interval(4, 5)
    lo50, hi50 = wilson_interval(40, 50)
    assert (hi5 - lo5) > (hi50 - lo50)
