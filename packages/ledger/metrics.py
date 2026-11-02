from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal


def roi(total_stake: Decimal, total_payout: Decimal) -> Decimal:
    if total_stake <= Decimal(0):
        return Decimal(0)
    return (total_payout - total_stake) / total_stake


def clv(bet_odds: Decimal, closing_odds: Decimal | None) -> Decimal | None:
    if closing_odds is None or closing_odds <= Decimal(0):
        return None
    return bet_odds / closing_odds - Decimal(1)


def brier_score(probability: Decimal, outcome: int) -> Decimal:
    if outcome not in (0, 1):
        raise ValueError("outcome must be 0 or 1")
    if not probability.is_finite() or probability < Decimal(0) or probability > Decimal(1):
        raise ValueError("probability must be between 0 and 1")
    return (probability - Decimal(outcome)) ** 2


def max_drawdown(equity_curve: Sequence[Decimal]) -> Decimal:
    if not equity_curve:
        return Decimal(0)
    peak = equity_curve[0]
    worst = Decimal(0)
    for value in equity_curve:
        peak = max(peak, value)
        if peak > Decimal(0):
            drawdown = (peak - value) / peak
            worst = max(worst, drawdown)
    return worst


def bankroll_curve(
    initial: Decimal,
    settled: Sequence[tuple[Decimal, Decimal]],
) -> list[Decimal]:
    balance = initial
    curve = [balance]
    for stake, payout in settled:
        balance = balance - stake + payout
        curve.append(balance)
    return curve
