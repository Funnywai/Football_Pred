"""Pure evaluation metrics for the champion/challenger gate (numpy only)."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

_LABEL_TO_INDEX = {"H": 0, "D": 1, "A": 2}


def _label_indices(labels: Sequence[str] | Sequence[int]) -> np.ndarray:
    values = list(labels)
    if not values:
        return np.array([], dtype=int)
    if isinstance(values[0], str):
        return np.array([_LABEL_TO_INDEX[str(label)] for label in values], dtype=int)
    return np.asarray(values, dtype=int)


def expected_calibration_error(
    probs: Sequence[Sequence[float]] | np.ndarray,
    labels: Sequence[str] | Sequence[int],
    bins: int = 10,
) -> float:
    """Multiclass top-probability expected calibration error.

    Predictions are bucketed by their maximum predicted probability (``bins``
    equal-width buckets over [0, 1]); each bucket contributes
    ``|accuracy - mean confidence|`` weighted by its share of the samples.
    Returns 0.0 for empty input.
    """
    probabilities = np.asarray(probs, dtype=float)
    indices = _label_indices(labels)
    if probabilities.size == 0 or indices.size == 0:
        return 0.0
    confidence = probabilities.max(axis=1)
    predicted = probabilities.argmax(axis=1)
    correct = (predicted == indices).astype(float)
    bucket = np.minimum((confidence * bins).astype(int), bins - 1)
    total = len(confidence)
    error = 0.0
    for index in range(bins):
        mask = bucket == index
        count = int(mask.sum())
        if count == 0:
            continue
        accuracy = float(correct[mask].mean())
        mean_confidence = float(confidence[mask].mean())
        error += (count / total) * abs(accuracy - mean_confidence)
    return float(error)


def economic_backtest(
    probs: Sequence[Sequence[float]] | np.ndarray,
    market_probs: Sequence[Sequence[float]] | np.ndarray,
    labels: Sequence[str] | Sequence[int],
    threshold: float,
    exec_edge_buffer: float = 0.0,
) -> dict:
    """Flat 1-unit stake backtest over de-vigged market probabilities.

    A bet is placed on outcome ``j`` of match ``i`` when both
    ``probs[i, j] - market_probs[i, j] > threshold`` and
    ``probs[i, j] * (1 / market_probs[i, j]) > 1 + exec_edge_buffer``.

    The payout uses the de-vigged fair price ``1 / market_probs[i, j]`` as the
    reference price: a deliberately vig-free, documented approximation of the
    executable price (real books charge vig, so this overstates returns). Rows
    with missing (NaN) or non-positive market probabilities are skipped.

    Returns ``{"roi", "n_bets", "staked", "returned"}`` with
    ``roi = returned / staked - 1`` and ``roi = 0.0`` when there are no bets.
    """
    probabilities = np.asarray(probs, dtype=float)
    market = np.asarray(market_probs, dtype=float)
    indices = _label_indices(labels)
    if probabilities.size == 0 or market.size == 0 or indices.size == 0:
        return {"roi": 0.0, "n_bets": 0, "staked": 0.0, "returned": 0.0}
    valid = np.isfinite(probabilities) & np.isfinite(market) & (market > 0.0)
    price = 1.0 / np.where(valid, market, 1.0)
    bets = valid & (probabilities - market > threshold) & (
        probabilities * price > 1.0 + exec_edge_buffer
    )
    n_bets = int(bets.sum())
    if n_bets == 0:
        return {"roi": 0.0, "n_bets": 0, "staked": 0.0, "returned": 0.0}
    hits = bets & (indices[:, None] == np.arange(probabilities.shape[1])[None, :])
    staked = float(n_bets)
    returned = float(price[hits].sum())
    return {
        "roi": returned / staked - 1.0,
        "n_bets": n_bets,
        "staked": staked,
        "returned": returned,
    }
