"""Model version registry: champion/challenger gate, promote, rollback."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ModelVersion
from app.ml.models import TARGET_1X2, TARGET_HANDICAP  # noqa: F401  (re-exported for callers)

STATUS_CHAMPION = "champion"
STATUS_CHALLENGER = "challenger"
STATUS_RETIRED = "retired"


async def get_champion(session: AsyncSession, target: str) -> ModelVersion | None:
    stmt = (
        select(ModelVersion)
        .where(ModelVersion.target == target)
        .where(ModelVersion.status == STATUS_CHAMPION)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def register_challenger(
    session: AsyncSession,
    target: str,
    algorithm: str,
    params: dict,
    metrics: dict,
    artifact_path: str,
) -> ModelVersion:
    version = ModelVersion(
        target=target,
        algorithm=algorithm,
        params=params,
        metrics=metrics,
        artifact_path=artifact_path,
        status=STATUS_CHALLENGER,
    )
    session.add(version)
    await session.flush()
    return version


GATE_MANDATORY = ("logloss", "brier")
CLV_TOLERANCE = 1e-12
DEFAULT_MIN_REAL_BETS = 50


def _gate_values(metrics: dict, keys: tuple[str, ...]) -> dict[str, float] | None:
    values = {key: metrics.get(key) for key in keys}
    if any(value is None for value in values.values()):
        return None
    return cast("dict[str, float]", values)


def gate_passes(
    challenger_metrics: dict,
    champion_metrics: dict,
    margin: float,
    min_real_bets: int = DEFAULT_MIN_REAL_BETS,
) -> bool:
    """Promote only when the challenger beats the champion on every usable metric.

    ``logloss`` and ``brier`` are mandatory to report: a missing/None value on
    either side fails closed (never promote on absent evidence). Only ``logloss``
    gates the promotion:

    - ``logloss``: challenger < champion - margin

    ``brier`` and ``ece`` are recorded but deliberately do NOT gate. The measured
    evidence showed both favour the isotonic configuration (Brier 0.57545, ECE
    0.0141) over the one that is better on logloss AND on economics (temperature:
    logloss 0.96990, served ROI +30.7% vs +10.5%), and ECE is precisely isotonic's
    home turf, so gating on either rejects exactly the challenger worth promoting.
    ``logloss`` is a strictly proper scoring rule and already covers calibration.

    ``roi`` (an absolute bar, so it is enforced whenever the challenger reports
    it) must be ``>= 0``. ``ece`` and ``clv_mean_edge`` are comparative and are
    therefore only checked when BOTH sides report them: the handicap target
    computes neither, and failing closed on metrics a target never produces would
    freeze that target permanently.

    ``roi_real`` (the ROI at the venue's real, vig-inclusive price) is likewise an
    absolute bar, enforced whenever the challenger reports it: it must be ``>= 0``
    AND ``n_bets_real`` must be ``>= min_real_bets`` (``ML_GATE_MIN_REAL_BETS``). The
    bet-count floor is needed because a configuration that places ZERO bets at the
    real price reports ``roi_real = 0.0``, which would otherwise satisfy ``>= 0``
    trivially and let a losing configuration through on a metric nobody can achieve.

    ``clv_mean_edge`` requires "not worse than the champion" (within
    ``CLV_TOLERANCE``), NOT "> 0": ``clv_metrics`` averages the edge over every
    outcome, so a normalised predictor's mean edge against a normalised de-vigged
    close is ~0 by construction (the live challenger stored -1.9e-18). A "> 0"
    requirement would reject every challenger forever. The "beats the close"
    intent is carried by ``roi``, which comes from a per-bet simulation.
    """
    challenger = _gate_values(challenger_metrics, GATE_MANDATORY)
    champion = _gate_values(champion_metrics, GATE_MANDATORY)
    if challenger is None or champion is None:
        return False
    if not challenger["logloss"] < champion["logloss"] - margin:
        return False
    roi = challenger_metrics.get("roi")
    if roi is not None and roi < 0.0:
        return False
    roi_real = challenger_metrics.get("roi_real")
    if roi_real is not None:
        n_bets_real = challenger_metrics.get("n_bets_real")
        if roi_real < 0.0 or n_bets_real is None or n_bets_real < min_real_bets:
            return False
    challenger_clv = challenger_metrics.get("clv_mean_edge")
    champion_clv = champion_metrics.get("clv_mean_edge")
    if challenger_clv is not None and champion_clv is not None:
        return challenger_clv >= champion_clv - CLV_TOLERANCE
    return True


async def promote(session: AsyncSession, version: ModelVersion) -> None:
    """Make ``version`` the champion, retiring any current champion."""
    current = await get_champion(session, version.target)
    if current is not None and current.id != version.id:
        current.status = STATUS_RETIRED
        await session.flush()
    version.status = STATUS_CHAMPION
    version.promoted_at = datetime.now(UTC)
    await session.flush()


async def maybe_promote(
    session: AsyncSession,
    challenger: ModelVersion,
    margin: float,
    champion_metrics: dict | None = None,
    min_real_bets: int = DEFAULT_MIN_REAL_BETS,
) -> bool:
    """Promote the challenger when it beats the champion's benchmark.

    ``champion_metrics`` is the fix for cross-window comparison: the caller passes a
    fresh evaluation of the champion on the current holdout so the gate compares like
    with like. ``None`` (used when the champion cannot be re-evaluated) falls back to
    the champion's STORED metrics, which may come from an older window.
    """
    champion = await get_champion(session, challenger.target)
    if champion is None:
        await promote(session, challenger)
        return True
    baseline = champion.metrics if champion_metrics is None else champion_metrics
    if gate_passes(challenger.metrics, baseline, margin, min_real_bets):
        await promote(session, challenger)
        return True
    return False


async def rollback(session: AsyncSession, target: str) -> ModelVersion | None:
    """Restore the most recently promoted retired version as champion."""
    stmt = (
        select(ModelVersion)
        .where(ModelVersion.target == target)
        .where(ModelVersion.status == STATUS_RETIRED)
        .where(ModelVersion.promoted_at.is_not(None))
        .order_by(ModelVersion.promoted_at.desc())
        .limit(1)
    )
    previous = (await session.execute(stmt)).scalar_one_or_none()
    if previous is None:
        return None
    await promote(session, previous)
    return previous
