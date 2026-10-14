"""Aggregate queries and shared shaping helpers for the ``/ops/*`` routes."""

from datetime import datetime

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base
from app.db.models import (
    IngestionRun,
    League,
    LedgerBet,
    Match,
    MatchFeature,
    ModelVersion,
    OddsSnapshot,
    Prediction,
    Result,
    Season,
    Team,
)

_TABLE_MODELS: dict[str, type[Base]] = {
    "leagues": League,
    "seasons": Season,
    "teams": Team,
    "matches": Match,
    "odds_snapshots": OddsSnapshot,
    "results": Result,
    "predictions": Prediction,
    "match_features": MatchFeature,
    "model_versions": ModelVersion,
    "ledger_bets": LedgerBet,
    "ingestion_runs": IngestionRun,
}


def iso_or_none(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


async def safe_rollback(session: AsyncSession) -> None:
    """Roll back without ever raising: a rollback on a dead connection can itself fail."""
    try:
        await session.rollback()
    except Exception:  # noqa: BLE001, S110  (cleanup must never mask the original failure)
        pass


async def alembic_revision(session: AsyncSession) -> str | None:
    try:
        row = (await session.execute(text("SELECT version_num FROM alembic_version"))).first()
    except Exception:  # noqa: BLE001  (connect-time OSError is not SQLAlchemyError)
        await safe_rollback(session)
        return None
    return str(row[0]) if row is not None else None


async def data_snapshot(session: AsyncSession) -> dict[str, object]:
    table_counts: dict[str, int] = {}
    for name, model in _TABLE_MODELS.items():
        count = (await session.execute(select(func.count()).select_from(model))).scalar_one()
        table_counts[name] = int(count)

    odds_total = (
        await session.execute(select(func.count()).select_from(OddsSnapshot))
    ).scalar_one()
    odds_last = (await session.execute(select(func.max(OddsSnapshot.captured_at)))).scalar_one()
    groups = (
        await session.execute(
            select(
                OddsSnapshot.source,
                OddsSnapshot.odds_type,
                OddsSnapshot.inplay,
                func.count(),
                func.max(OddsSnapshot.captured_at),
            )
            .group_by(OddsSnapshot.source, OddsSnapshot.odds_type, OddsSnapshot.inplay)
            .order_by(OddsSnapshot.source, OddsSnapshot.odds_type, OddsSnapshot.inplay)
        )
    ).all()

    features_count = (
        await session.execute(select(func.count()).select_from(MatchFeature))
    ).scalar_one()
    features_last = (await session.execute(select(func.max(MatchFeature.built_at)))).scalar_one()

    results_total = (await session.execute(select(func.count()).select_from(Result))).scalar_one()
    results_confirmed = (
        await session.execute(
            select(func.count()).select_from(Result).where(Result.confirmed.is_(True))
        )
    ).scalar_one()
    results_payout = (
        await session.execute(
            select(func.count()).select_from(Result).where(Result.payout_confirmed.is_(True))
        )
    ).scalar_one()
    results_last = (await session.execute(select(func.max(Result.confirmed_at)))).scalar_one()

    versions = (
        await session.execute(
            select(ModelVersion).order_by(ModelVersion.created_at.desc(), ModelVersion.id.desc())
        )
    ).scalars().all()
    model_created_last = (
        await session.execute(select(func.max(ModelVersion.created_at)))
    ).scalar_one()
    model_promoted_last = (
        await session.execute(select(func.max(ModelVersion.promoted_at)))
    ).scalar_one()

    return {
        "table_counts": table_counts,
        "odds": {
            "total": int(odds_total),
            "last_captured_at": iso_or_none(odds_last),
            "by_source_type": [
                {
                    "source": source,
                    "odds_type": odds_type,
                    "inplay": bool(inplay),
                    "count": int(count),
                    "max_captured_at": iso_or_none(max_captured),
                }
                for source, odds_type, inplay, count, max_captured in groups
            ],
        },
        "match_features": {"count": int(features_count), "max_built_at": iso_or_none(features_last)},
        "results": {
            "total": int(results_total),
            "confirmed": int(results_confirmed),
            "payout_confirmed": int(results_payout),
            "max_confirmed_at": iso_or_none(results_last),
        },
        "model_versions": [
            {
                "id": version.id,
                "target": version.target,
                "algorithm": version.algorithm,
                "status": version.status,
                "params": version.params,
                "metrics": version.metrics,
                "artifact_path": version.artifact_path,
                "created_at": iso_or_none(version.created_at),
                "promoted_at": iso_or_none(version.promoted_at),
            }
            for version in versions
        ],
        "alembic_revision": await alembic_revision(session),
        "last_arrived": {
            "odds_captured_at": iso_or_none(odds_last),
            "features_built_at": iso_or_none(features_last),
            "results_confirmed_at": iso_or_none(results_last),
            "model_created_at": iso_or_none(model_created_last),
            "model_promoted_at": iso_or_none(model_promoted_last),
        },
    }
