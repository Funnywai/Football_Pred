from decimal import Decimal

from packages.domain.enums import Side
from packages.models.poisson import HadPrediction
from packages.models.shrinkage import (
    CHALLENGER_MODEL_VERSION,
    proportional_devig,
    shrink_had_prediction,
)

D = Decimal


def _prediction() -> HadPrediction:
    return HadPrediction(
        p_home=D("0.60"),
        p_draw=D("0.25"),
        p_away=D("0.15"),
        score_distribution={
            (1, 0): D("0.60"),
            (0, 0): D("0.25"),
            (0, 1): D("0.15"),
        },
        tail_mass=D("0"),
        score_grid_max=10,
        tail_handling="truncated_renormalized",
    )


def test_proportional_devig_sums_to_one():
    market = proportional_devig(
        {Side.H: D("4.00"), Side.D: D("3.00"), Side.A: D("2.00")}
    )
    assert market is not None
    assert sum(market.values()) == D("1.000000000000000000000000000")


def test_proportional_devig_rejects_missing_or_invalid_odds():
    assert proportional_devig({Side.H: D("2.00")}) is None
    assert proportional_devig(
        {Side.H: D("1.00"), Side.D: D("3.00"), Side.A: D("3.00")}
    ) is None


def test_shrink_reallocates_score_distribution():
    result = shrink_had_prediction(
        _prediction(),
        {Side.H: D("2.00"), Side.D: D("4.00"), Side.A: D("4.00")},
    )
    assert result is not None
    assert result.model_version == CHALLENGER_MODEL_VERSION
    assert result.p_home == D("0.55")
    assert result.p_draw == D("0.25")
    assert result.p_away == D("0.20")
    assert result.score_distribution[(1, 0)] == D("0.55")
    assert result.score_distribution[(0, 0)] == D("0.25")
    assert result.score_distribution[(0, 1)] == D("0.20")


def test_shrink_rejects_invalid_weight():
    assert shrink_had_prediction(
        _prediction(),
        {Side.H: D("2.00"), Side.D: D("4.00"), Side.A: D("4.00")},
        D("1.01"),
    ) is None
