import pytest

from skillgate.stats import binom_tail, p_better, p_worse, wilson_lower


def test_binom_tail_is_exact():
    assert binom_tail(0, 5) == 1.0
    assert binom_tail(3, 3) == 1 / 8
    assert binom_tail(4, 3) == 0.0
    assert binom_tail(2, 4) == pytest.approx(11 / 16)


def test_sign_test_only_counts_disagreements():
    assert p_better(5, 0) == 1 / 32
    assert p_worse(0, 5) == 1 / 32
    assert p_better(0, 0) == p_worse(0, 0) == 1.0
    assert p_better(3, 1) > 0.05  # 3 wins to 1 loss is not evidence


def test_wilson_lower():
    assert wilson_lower(0, 0) == 0.0
    assert wilson_lower(50, 50) == pytest.approx(0.92865, abs=1e-4)
    assert wilson_lower(46, 50) < 0.9 < 46 / 50  # 92% on 50 cases is not yet proof of 90%
