"""Odds de-vigging (multiplicative method, v1)."""

from __future__ import annotations

from collections.abc import Sequence


def implied_probs(odds: Sequence[float]) -> list[float]:
    """Raw implied probabilities ``1 / odds`` (they sum to the overround)."""
    probs: list[float] = []
    for value in odds:
        if value <= 0:
            raise ValueError(f"odds must be positive, got {value!r}")
        probs.append(1.0 / value)
    return probs


def overround(odds: Sequence[float]) -> float:
    """Sum of raw implied probabilities (>= 1 for a real book)."""
    return sum(implied_probs(odds))


def devig_multiplicative(odds: Sequence[float]) -> list[float]:
    """Remove the overround multiplicatively so fair probabilities sum to 1."""
    implied = implied_probs(odds)
    total = sum(implied)
    if total <= 0:
        raise ValueError("implied probability sum must be positive")
    return [value / total for value in implied]
