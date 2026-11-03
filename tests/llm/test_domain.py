import json
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from packages.llm.domain import AgentPrediction, InvalidPredictionError, Outcome, Stage


def make_prediction(**overrides: object) -> AgentPrediction:
    values: dict[str, object] = {
        "agent_id": "market_agent",
        "match_id": "match-1",
        "stage": "T-30m",
        "as_of": datetime(2026, 11, 3, 17, 15, tzinfo=UTC),
        "probabilities": {"H": Decimal("0.46"), "D": Decimal("0.23"), "A": Decimal("0.31")},
        "confidence": Decimal("0.72"),
        "data_quality": Decimal("0.81"),
        "key_factors": ["Home odds shortened"],
        "evidence_refs": ["hkjc:50078957"],
        "uncertainties": ["No confirmed lineup"],
        "abstain": False,
        "abstain_reason": None,
    }
    values.update(overrides)
    return AgentPrediction.model_validate(values)


def test_valid_prediction_accepts_normalized_probabilities() -> None:
    prediction = make_prediction()

    assert prediction.stage == Stage.T30M
    assert sum(prediction.probabilities.values()) == Decimal("1.00")


def test_probabilities_must_sum_to_one() -> None:
    with pytest.raises(InvalidPredictionError, match="sum to 1"):
        make_prediction(
            probabilities={"H": Decimal("0.50"), "D": Decimal("0.30"), "A": Decimal("0.30")}
        )


def test_probabilities_must_contain_all_outcomes() -> None:
    with pytest.raises(InvalidPredictionError, match="H, D and A"):
        make_prediction(probabilities={"H": Decimal("1.0")})


def test_probabilities_cannot_be_negative() -> None:
    with pytest.raises(ValidationError):
        make_prediction(
            probabilities={"H": Decimal("-0.01"), "D": Decimal("0.51"), "A": Decimal("0.50")}
        )


def test_confidence_must_be_bounded() -> None:
    with pytest.raises(ValidationError):
        make_prediction(confidence=Decimal("1.01"))


def test_abstain_requires_reason() -> None:
    with pytest.raises(InvalidPredictionError, match="abstain_reason"):
        make_prediction(abstain=True, abstain_reason=None)


def test_outcome_values_are_stable() -> None:
    assert [outcome.value for outcome in Outcome] == ["H", "D", "A"]


def test_as_of_must_be_utc() -> None:
    with pytest.raises(ValidationError, match="UTC"):
        make_prediction(as_of=datetime(2026, 11, 4, 1, 15, tzinfo=timezone(timedelta(hours=8))))


def test_model_validate_json_rejects_probabilities_not_summing_to_one() -> None:
    payload = json.dumps(
        {
            "agent_id": "market_agent",
            "match_id": "match-1",
            "stage": "T-30m",
            "as_of": "2026-11-03T17:15:00Z",
            "probabilities": {"H": 0.50, "D": 0.30, "A": 0.30},
            "confidence": 0.72,
            "data_quality": 0.81,
        }
    )

    with pytest.raises(InvalidPredictionError, match="sum to 1"):
        AgentPrediction.model_validate_json(payload)
