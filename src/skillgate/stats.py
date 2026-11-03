"""Small, dependency-free statistics used by the gate.

Old and new versions are compared on the *same* cases, so only the cases where
they disagree carry information: b = new passes and old fails, c = old passes
and new fails. Under "no real difference" each disagreement is a fair coin flip,
which gives an exact sign test (McNemar's test) with nothing to tune.
"""

from __future__ import annotations

from math import comb, sqrt


def binom_tail(k: int, n: int) -> float:
    """P(X >= k) for X ~ Binomial(n, 1/2), computed exactly."""
    if k <= 0:
        return 1.0
    if k > n:
        return 0.0
    return sum(comb(n, i) for i in range(k, n + 1)) / 2**n


def p_better(b: int, c: int) -> float:
    """One-sided p-value that the new version is better (b wins, c losses)."""
    return binom_tail(b, b + c) if b + c else 1.0


def p_worse(b: int, c: int) -> float:
    """One-sided p-value that the new version is worse."""
    return binom_tail(c, b + c) if b + c else 1.0


def wilson_lower(passes: int, n: int, z: float = 1.96) -> float:
    """Lower end of the Wilson score interval for a pass rate (0.0 when n == 0)."""
    if n == 0:
        return 0.0
    p = passes / n
    centre = p + z * z / (2 * n)
    spread = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (centre - spread) / (1 + z * z / n))
