from datetime import UTC, datetime
from decimal import Decimal

import pytest

from packages.llm.aggregation.log_opinion import InsufficientAgentsError, aggregate_predictions
from packages.llm.domain import AgentPrediction, Outcome


def prediction(agent_id: str, h: str, d: str, a: str) -> AgentPrediction:
    return AgentPrediction(
        agent_id=agent_id,
        match_id="match-1",
        stage="T-30m",
        as_of=datetime(2026, 11, 3, 17, 15, tzinfo=UTC),
        probabilities={"H": Decimal(h), "D": Decimal(d), "A": Decimal(a)},
        confidence=Decimal("0.7"),
        data_quality=Decimal("0.8"),
        key_factors=[],
        evidence_refs=[],
        uncertainties=[],
        abstain=False,
        abstain_reason=None,
    )


def test_equal_weights_reproduce_identical_predictions() -> None:
    predictions = [
        prediction("a", "0.50", "0.25", "0.25"),
        prediction("b", "0.50", "0.25", "0.25"),
        prediction("c", "0.50", "0.25", "0.25"),
    ]
    result = aggregate_predictions(
        predictions,
        {"a": Decimal(1), "b": Decimal(1), "c": Decimal(1)},
    )

    assert result[Outcome.H] == pytest.approx(0.50, abs=1e-9)
    assert result[Outcome.D] == pytest.approx(0.25, abs=1e-9)
    assert result[Outcome.A] == pytest.approx(0.25, abs=1e-9)


def test_disagreeing_agents_produce_a_normalized_distribution() -> None:
    predictions = [
        prediction("a", "0.70", "0.20", "0.10"),
        prediction("b", "0.30", "0.40", "0.30"),
        prediction("c", "0.20", "0.30", "0.50"),
    ]
    result = aggregate_predictions(
        predictions,
        {"a": Decimal("0.5"), "b": Decimal("0.3"), "c": Decimal("0.2")},
    )

    assert float(sum(result.values())) == pytest.approx(1.0, abs=1e-9)
    assert all(0 <= value <= 1 for value in result.values())


def test_weighted_agent_dominates() -> None:
    predictions = [
        prediction("strong", "0.80", "0.10", "0.10"),
        prediction("weak_a", "0.20", "0.40", "0.40"),
        prediction("weak_b", "0.20", "0.40", "0.40"),
    ]
    result = aggregate_predictions(
        predictions,
        {"strong": Decimal("0.8"), "weak_a": Decimal("0.1"), "weak_b": Decimal("0.1")},
    )

    assert result[Outcome.H] > Decimal("0.60")


def test_abstaining_agents_are_excluded() -> None:
    predictions = [
        prediction("a", "0.50", "0.25", "0.25"),
        prediction("b", "0.50", "0.25", "0.25"),
        prediction("c", "0.50", "0.25", "0.25"),
        prediction("d", "0.99", "0.005", "0.005").model_copy(
            update={"abstain": True, "abstain_reason": "stale evidence"}
        ),
    ]
    result = aggregate_predictions(
        predictions,
        {"a": Decimal(1), "b": Decimal(1), "c": Decimal(1), "d": Decimal(1)},
    )

    assert result[Outcome.H] == pytest.approx(0.50, abs=1e-9)


def test_fewer_than_three_active_agents_fails_closed() -> None:
    predictions = [
        prediction("a", "0.50", "0.25", "0.25"),
        prediction("b", "0.50", "0.25", "0.25"),
    ]

    with pytest.raises(InsufficientAgentsError, match="at least 3"):
        aggregate_predictions(predictions, {"a": Decimal(1), "b": Decimal(1)})


def test_missing_weight_fails_closed() -> None:
    predictions = [
        prediction("a", "0.50", "0.25", "0.25"),
        prediction("b", "0.50", "0.25", "0.25"),
        prediction("c", "0.50", "0.25", "0.25"),
    ]

    with pytest.raises(ValueError, match="missing weight"):
        aggregate_predictions(predictions, {"a": Decimal(1), "b": Decimal(1)})


def test_zero_total_weight_fails_closed() -> None:
    predictions = [
        prediction("a", "0.50", "0.25", "0.25"),
        prediction("b", "0.50", "0.25", "0.25"),
        prediction("c", "0.50", "0.25", "0.25"),
    ]

    with pytest.raises(ValueError, match="positive"):
        aggregate_predictions(
            predictions,
            {"a": Decimal(0), "b": Decimal(0), "c": Decimal(0)},
        )


def test_duplicate_active_agent_ids_fail_closed() -> None:
    predictions = [
        prediction("a", "0.50", "0.25", "0.25"),
        prediction("a", "0.60", "0.20", "0.20"),
        prediction("b", "0.30", "0.40", "0.30"),
    ]

    with pytest.raises(ValueError, match="duplicate"):
        aggregate_predictions(predictions, {"a": Decimal(1), "b": Decimal(1)})
