from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from decimal import Decimal

from packages.llm.domain import AgentPrediction, Outcome


class InsufficientAgentsError(ValueError):
    """Raised when fewer than three specialists can contribute."""


def aggregate_predictions(
    predictions: Sequence[AgentPrediction],
    weights: Mapping[str, Decimal],
) -> dict[Outcome, Decimal]:
    active = [prediction for prediction in predictions if not prediction.abstain]
    if len(active) < 3:
        raise InsufficientAgentsError("at least 3 active agents are required")

    active_weights: dict[str, Decimal] = {}
    seen_agent_ids: set[str] = set()
    for prediction in active:
        if prediction.agent_id in seen_agent_ids:
            raise ValueError(f"duplicate active agent id: {prediction.agent_id}")
        seen_agent_ids.add(prediction.agent_id)
        weight = weights.get(prediction.agent_id)
        if weight is None:
            raise ValueError(f"missing weight for agent {prediction.agent_id}")
        if weight < 0:
            raise ValueError("agent weights must be non-negative")
        active_weights[prediction.agent_id] = weight

    total_weight = sum(active_weights.values(), Decimal(0))
    if total_weight <= 0:
        raise ValueError("total agent weight must be positive")

    log_scores: dict[Outcome, float] = {outcome: 0.0 for outcome in Outcome}
    for prediction in active:
        normalized_weight = float(active_weights[prediction.agent_id] / total_weight)
        for outcome in Outcome:
            probability = float(prediction.probabilities[outcome.value])
            if probability <= 0:
                raise ValueError("probabilities must be strictly positive for log pooling")
            log_scores[outcome] += normalized_weight * math.log(probability)

    maximum = max(log_scores.values())
    exponentials = {
        outcome: math.exp(score - maximum) for outcome, score in log_scores.items()
    }
    total = sum(exponentials.values())
    return {
        outcome: Decimal(str(value / total))
        for outcome, value in exponentials.items()
    }
