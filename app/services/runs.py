import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import IngestionRun


async def track_run(
    session_factory: async_sessionmaker[AsyncSession],
    job: str,
    work: Callable[[AsyncSession], Awaitable[int]],
) -> int:
    """Run ``work`` inside one transaction and record an ingestion_runs row.

    Failures are recorded (status="failed") and re-raised so the scheduler can log them.
    """
    async with session_factory() as session:
        run = IngestionRun(job=job, started_at=datetime.now(UTC), status="running")
        session.add(run)
        await session.commit()
        run_id = run.id
    try:
        async with session_factory() as session:
            count = await work(session)
            await session.commit()
    except Exception as exc:
        async with session_factory() as session:
            failed = await session.get(IngestionRun, run_id)
            if failed is not None:
                failed.status = "failed"
                failed.finished_at = datetime.now(UTC)
                failed.error = f"{type(exc).__name__}: {exc}"
                await session.commit()
        raise
    async with session_factory() as session:
        finished = await session.get(IngestionRun, run_id)
        if finished is not None:
            finished.status = "success"
            finished.finished_at = datetime.now(UTC)
            finished.records_upserted = count
            await session.commit()
    return count


async def flag_manual_review(
    session_factory: async_sessionmaker[AsyncSession],
    job: str,
    match_ids: list[int],
) -> None:
    """Record unresolved matches for manual review. No-op when the list is empty."""
    if not match_ids:
        return
    now = datetime.now(UTC)
    async with session_factory() as session:
        session.add(
            IngestionRun(
                job=job,
                started_at=now,
                finished_at=now,
                status="flagged",
                records_upserted=len(match_ids),
                error=json.dumps({"unresolved_match_ids": match_ids}),
            )
        )
        await session.commit()
