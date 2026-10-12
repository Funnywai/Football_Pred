"""Model version registry: champion/challenger gate, promote, rollback."""

from __future__ import annotations

from datetime import UTC, datetime

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


def gate_passes(challenger_metrics: dict, champion_metrics: dict, margin: float) -> bool:
    """Promote only when the challenger is at least ``margin`` better on Brier and
    its CLV mean edge is not worse (missing CLV on either side passes)."""
    challenger_brier = challenger_metrics.get("brier")
    champion_brier = champion_metrics.get("brier")
    if challenger_brier is None or champion_brier is None:
        return False
    if challenger_brier >= champion_brier - margin:
        return False
    challenger_clv = challenger_metrics.get("clv_mean_edge")
    champion_clv = champion_metrics.get("clv_mean_edge")
    return not (
        challenger_clv is not None and champion_clv is not None and challenger_clv < champion_clv
    )


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
) -> bool:
    """Promote the challenger when it beats the champion's benchmark.

    ``champion_metrics`` overrides the champion's STORED metrics with a fresh
    evaluation on the current holdout (fix #6) so the gate never compares two
    different time windows; ``None`` keeps the legacy stored-metrics behaviour.
    """
    champion = await get_champion(session, challenger.target)
    if champion is None:
        await promote(session, challenger)
        return True
    baseline = champion.metrics if champion_metrics is None else champion_metrics
    if gate_passes(challenger.metrics, baseline, margin):
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
