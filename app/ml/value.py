"""Value detection: edge, fair odds, Kelly fraction, CLV metrics."""

from __future__ import annotations


def edge(model_prob: float, fair_prob: float) -> float:
    """Model probability minus the de-vigged market probability."""
    return model_prob - fair_prob


def fair_odds(model_prob: float) -> float:
    """Decimal odds implied by the model probability (inf when prob <= 0)."""
    if model_prob <= 0:
        return float("inf")
    return 1.0 / model_prob


def is_value(edge_value: float, threshold: float) -> bool:
    """A value bet is flagged when the edge strictly exceeds the threshold."""
    return edge_value > threshold


def kelly_fraction(model_prob: float, odds: float) -> float:
    """Kelly stake fraction ``f = (b*p - q) / b`` clamped to [0, 1]."""
    b = odds - 1.0
    if b <= 0:
        return 0.0
    p = min(max(model_prob, 0.0), 1.0)
    q = 1.0 - p
    fraction = (b * p - q) / b
    return min(max(fraction, 0.0), 1.0)


def clv_metrics(
    model_probs_by_match: dict[int, dict[str, float]],
    closing_probs_by_match: dict[int, dict[str, float]],
) -> dict[str, float | int | None]:
    """Beat-the-closing-line metrics over matches present in both mappings.

    For every outcome shared by a match's model probabilities and its HKJC
    closing de-vigged probabilities, the model "beats the close" when
    ``model_prob >= closing_prob``. Returns the beat fraction, the mean edge and
    the number of comparisons; ``None``/0 when no match has closing data (the
    normal case until HKJC history accumulates).
    """
    beats: list[float] = []
    edges: list[float] = []
    for match_id, model_probs in model_probs_by_match.items():
        closing = closing_probs_by_match.get(match_id)
        if not closing:
            continue
        for outcome, model_prob in model_probs.items():
            closing_prob = closing.get(outcome)
            if closing_prob is None:
                continue
            beats.append(1.0 if model_prob >= closing_prob else 0.0)
            edges.append(model_prob - closing_prob)
    if not beats:
        return {"clv_fraction": None, "clv_mean_edge": None, "clv_n": 0}
    return {
        "clv_fraction": sum(beats) / len(beats),
        "clv_mean_edge": sum(edges) / len(edges),
        "clv_n": len(beats),
    }
