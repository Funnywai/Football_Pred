import pytest

from app.ml.deviq import devig_multiplicative, implied_probs, overround


def test_implied_probs() -> None:
    assert implied_probs([2.0, 4.0]) == [0.5, 0.25]


def test_implied_probs_rejects_nonpositive() -> None:
    with pytest.raises(ValueError):
        implied_probs([0.0])


def test_overround_and_devig() -> None:
    odds = [2.1, 3.4, 3.8]
    assert overround(odds) > 1.0
    fair = devig_multiplicative(odds)
    assert len(fair) == 3
    assert abs(sum(fair) - 1.0) < 1e-9
    # favourite keeps the largest fair probability
    assert fair.index(max(fair)) == 0
