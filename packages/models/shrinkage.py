from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from decimal import Decimal
from types import MappingProxyType

from packages.domain.enums import Side
from packages.models.poisson import HadPrediction

CHALLENGER_MODEL_VERSION = "poisson-v2-shrunk"
HAD_SIDES: tuple[Side, Side, Side] = (Side.H, Side.D, Side.A)
_PROBABILITY_TOLERANCE = Decimal("1e-9")
_ZERO = Decimal(0)


def _outcome(score: tuple[int, int]) -> Side:
    home, away = score
    if home > away:
        return Side.H
    if home < away:
        return Side.A
    return Side.D


def proportional_devig(
    odds: Mapping[Side, Decimal],
) -> dict[Side, Decimal] | None:
    """Return proportional de-vig probabilities, or None for invalid odds."""
    if set(odds) != set(HAD_SIDES):
        return None
    inverse: dict[Side, Decimal] = {}
    for side in HAD_SIDES:
        value = odds[side]
        if not value.is_finite() or value <= Decimal(1):
            return None
        inverse[side] = Decimal(1) / value
    total = sum(inverse.values(), _ZERO)
    if not total.is_finite() or total <= _ZERO:
        return None
    probabilities = {side: inverse[side] / total for side in HAD_SIDES}
    if abs(sum(probabilities.values(), _ZERO) - Decimal(1)) > _PROBABILITY_TOLERANCE:
        return None
    return probabilities


def shrink_had_prediction(
    prediction: HadPrediction,
    odds: Mapping[Side, Decimal],
    weight: Decimal = Decimal("0.50"),
) -> HadPrediction | None:
    """Blend HAD probabilities with de-vigged market probabilities.

    The score distribution is reweighted by H/D/A outcome so EV, Kelly and
    settlement continue to use the same score-level contract as g1.
    """
    if not weight.is_finite() or weight < _ZERO or weight > Decimal(1):
        return None
    market = proportional_devig(odds)
    if market is None:
        return None
    model = {
        Side.H: prediction.p_home,
        Side.D: prediction.p_draw,
        Side.A: prediction.p_away,
    }
    blended = {
        side: weight * model[side] + (Decimal(1) - weight) * market[side]
        for side in HAD_SIDES
    }
    if any(value <= _ZERO for value in blended.values()):
        return None
    if abs(sum(blended.values(), _ZERO) - Decimal(1)) > _PROBABILITY_TOLERANCE:
        return None

    old_totals = {side: _ZERO for side in HAD_SIDES}
    for score, probability in prediction.score_distribution.items():
        old_totals[_outcome(score)] += probability
    scaled: dict[tuple[int, int], Decimal] = {}
    for score, probability in prediction.score_distribution.items():
        side = _outcome(score)
        old = old_totals[side]
        if old <= _ZERO:
            return None
        scaled[score] = probability * blended[side] / old
    scaled_total = sum(scaled.values(), _ZERO)
    if abs(scaled_total - Decimal(1)) > _PROBABILITY_TOLERANCE:
        return None
    return replace(
        prediction,
        p_home=blended[Side.H],
        p_draw=blended[Side.D],
        p_away=blended[Side.A],
        score_distribution=MappingProxyType(scaled),
        model_version=CHALLENGER_MODEL_VERSION,
        tail_handling="market_shrunk",
    )
