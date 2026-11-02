from __future__ import annotations

import math
from collections.abc import Sequence
from decimal import Decimal

from packages.payoff.returns import (
    ReturnDistribution,
    expected_value,
    return_multiple,
)

DEFAULT_MAX_FRACTION = Decimal("0.99")
DEFAULT_TOLERANCE = Decimal("1e-9")
MAX_ITERATIONS = 200


def _objective(returns: Sequence[tuple[float, float]], fraction: float) -> float:
    return sum(
        probability * math.log1p(fraction * return_value)
        for probability, return_value in returns
    )


def kelly_fraction(
    distribution: ReturnDistribution,
    odds: Decimal,
    max_fraction: Decimal = DEFAULT_MAX_FRACTION,
    tolerance: Decimal = DEFAULT_TOLERANCE,
) -> Decimal:
    if not max_fraction.is_finite() or max_fraction < Decimal(0) or max_fraction >= Decimal(1):
        raise ValueError("max_fraction must be in [0, 1)")
    if not tolerance.is_finite() or tolerance < Decimal(0):
        raise ValueError("tolerance must be non-negative")
    for probability in distribution.values():
        if not probability.is_finite() or probability < 0:
            raise ValueError("distribution probabilities must be finite and non-negative")
    if expected_value(distribution, odds) <= Decimal(0):
        return Decimal(0)
    returns = [
        (float(probability), float(return_multiple(outcome, odds)))
        for outcome, probability in distribution.items()
        if probability > 0
    ]
    if not returns:
        return Decimal(0)
    low = 0.0
    high = float(max_fraction)
    if high <= 0.0:
        return Decimal(0)
    width = float(tolerance)
    for _ in range(MAX_ITERATIONS):
        if high - low <= width:
            break
        third = (high - low) / 3.0
        left = low + third
        right = high - third
        if _objective(returns, left) < _objective(returns, right):
            low = left
        else:
            high = right
    fraction = Decimal(str((low + high) / 2.0))
    if fraction <= tolerance:
        return Decimal(0)
    return min(fraction, max_fraction)
