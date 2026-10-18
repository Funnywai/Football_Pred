"""Read-only operational endpoints (``/ops/*``).

Additive to the nine data routes in ``app.api.routes``: process identity, live
scheduler jobs, recent ingestion runs, the in-memory log tail, and data freshness.
Every route is GET-only and issues no writes.
"""

import logging
import os
import time
import tomllib
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app import log_buffer
from app.api.ops_data import alembic_revision, data_snapshot, iso_or_none, safe_rollback
from app.db.models import IngestionRun

router = APIRouter(prefix="/ops", tags=["ops"])

_PROCESS_START = time.monotonic()

# Scheduler job ids do not match the persisted ``ingestion_runs.job`` strings one-to-one:
# ``settle_results`` fans out into two tracked runs (``app/services/results.py``), and
# ``prune_odds`` never calls ``track_run`` (``app/scheduler.py``), so its ``last_run`` is
# always null.
JOB_RUN_KEYS: dict[str, list[str]] = {
    "sync_odds": ["sync_odds"],
    "settle_results": ["settle_results_hkjc", "settle_results_fallback"],
    "prune_odds": [],
    "ledger_update": ["ledger_update"],
    "clv_update": ["clv_update"],
    "ml_predict": ["ml_predict"],
    "ml_retrain": ["ml_retrain"],
}

_LEVELS: dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def _read_app_version() -> str:
    try:
        with (Path(__file__).resolve().parents[2] / "pyproject.toml").open("rb") as handle:
            data = tomllib.load(handle)
        return str(data["project"]["version"])
    except (OSError, ValueError, KeyError, TypeError):
        return "unknown"


_APP_VERSION = _read_app_version()


async def get_session(request: Request):
    async with request.app.state.db.session_factory() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def _last_run(session: AsyncSession, keys: list[str]) -> dict[str, object] | None:
    if not keys:
        return None
    row = (
        await session.execute(
            select(IngestionRun)
            .where(IngestionRun.job.in_(keys))
            .order_by(IngestionRun.started_at.desc(), IngestionRun.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return {
        "status": row.status,
        "finished_at": iso_or_none(row.finished_at),
        "records_upserted": row.records_upserted,
        "error": row.error,
    }


@router.get("/status")
async def ops_status(request: Request, session: SessionDep) -> dict[str, object]:
    db_ok = True
    try:
        await session.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001  (spec: any probe failure must yield db_ok=false, never a 500)
        db_ok = False
        await safe_rollback(session)
    return {
        "app_version": _APP_VERSION,
        "git_sha": os.environ.get("GIT_SHA", "unknown"),
        # A dead connection must not be probed again: skip the alembic read when the probe failed.
        "alembic_revision": await alembic_revision(session) if db_ok else None,
        "uptime_seconds": time.monotonic() - _PROCESS_START,
        "db_ok": db_ok,
        "scheduler_enabled": bool(request.app.state.settings.enable_scheduler),
    }


@router.get("/jobs")
async def ops_jobs(request: Request, session: SessionDep) -> dict[str, list[dict[str, object]]]:
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is None:
        return {"jobs": []}
    jobs: list[dict[str, object]] = []
    for job in scheduler.get_jobs():
        jobs.append(
            {
                "id": job.id,
                "trigger": str(job.trigger),
                "next_run_time": iso_or_none(job.next_run_time),
                "pending": bool(job.pending),
                "last_run": await _last_run(session, JOB_RUN_KEYS.get(job.id, [])),
            }
        )
    return {"jobs": jobs}


@router.get("/runs")
async def ops_runs(session: SessionDep, limit: int = 50) -> dict[str, list[dict[str, object]]]:
    clamped = max(1, min(limit, 200))
    rows = (
        await session.execute(
            select(IngestionRun)
            .order_by(IngestionRun.started_at.desc(), IngestionRun.id.desc())
            .limit(clamped)
        )
    ).scalars().all()
    return {
        "runs": [
            {
                "id": row.id,
                "job": row.job,
                "started_at": iso_or_none(row.started_at),
                "finished_at": iso_or_none(row.finished_at),
                "status": row.status,
                "records_upserted": row.records_upserted,
                "error": row.error,
            }
            for row in rows
        ]
    }


@router.get("/logs")
async def ops_logs(limit: int = 100, level: str | None = None) -> dict[str, list[dict[str, str]]]:
    min_level: int | None = None
    if level is not None:
        min_level = _LEVELS.get(level.upper())
        if min_level is None:
            raise HTTPException(status_code=422, detail=f"unknown level: {level}")
    return {"logs": log_buffer.snapshot(limit, min_level)}


@router.get("/data")
async def ops_data(session: SessionDep) -> dict[str, object]:
    return await data_snapshot(session)
