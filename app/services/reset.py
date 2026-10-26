"""Scoped, dry-run-first reset of paper/shadow ledger state.

The reset only deletes rows from paper-trading tables; it never touches
production money. Bankroll is derived from ``ledger_bets``, so deleting those
rows restores ``settings.ledger_initial_bankroll``. The caller owns the
transaction: this module never commits.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from sqlalchemy import delete, func, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.base import Base
from app.db.models import (
    ClvRecord,
    IngestionRun,
    LedgerBet,
    Match,
    MatchFeature,
    ModelVersion,
    OddsSnapshot,
    Prediction,
    Result,
    ShadowLedgerBet,
)

ALL_TABLES: tuple[str, ...] = (
    "clv_records",
    "ledger_bets",
    "shadow_ledger_bets",
    "predictions",
    "match_features",
    "model_versions",
    "ingestion_runs",
    "odds_snapshots",
    "results",
    "matches",
)

_TABLES: dict[str, type[Base]] = {
    "clv_records": ClvRecord,
    "ledger_bets": LedgerBet,
    "shadow_ledger_bets": ShadowLedgerBet,
    "predictions": Prediction,
    "match_features": MatchFeature,
    "model_versions": ModelVersion,
    "ingestion_runs": IngestionRun,
    "odds_snapshots": OddsSnapshot,
    "results": Result,
    "matches": Match,
}


class ResetError(RuntimeError):
    """A reset precondition failed; nothing was deleted."""


@dataclass
class ResetPlan:
    """Which tables a reset touches, in FK-safe deletion order."""

    include_history: bool
    include_runs: bool
    keep_models: bool
    counts: dict[str, int] = field(default_factory=dict)

    def scoped_tables(self) -> tuple[str, ...]:
        names = [
            "clv_records",
            "ledger_bets",
            "shadow_ledger_bets",
            "predictions",
            "match_features",
        ]
        if not self.keep_models:
            names.append("model_versions")
        if self.include_runs:
            names.append("ingestion_runs")
        if self.include_history:
            names.extend(["odds_snapshots", "results", "matches"])
        return tuple(names)

    def kept_tables(self) -> tuple[str, ...]:
        scoped = set(self.scoped_tables())
        return tuple(name for name in ALL_TABLES if name not in scoped)


async def _table_exists(session: AsyncSession, name: str) -> bool:
    connection = await session.connection()
    return await connection.run_sync(lambda sync: sa_inspect(sync).has_table(name))


async def _count(session: AsyncSession, name: str) -> int:
    if name == "clv_records" and not await _table_exists(session, name):
        return 0
    stmt = select(func.count()).select_from(_TABLES[name])
    return int((await session.execute(stmt)).scalar_one())


async def inspect(
    session: AsyncSession,
    include_history: bool = False,
    include_runs: bool = False,
    keep_models: bool = False,
) -> dict[str, int]:
    """Return row counts for every reset-relevant table without deleting anything."""
    plan = ResetPlan(include_history, include_runs, keep_models)
    plan.counts = {name: await _count(session, name) for name in ALL_TABLES}
    return plan.counts


async def reset(
    session: AsyncSession,
    settings: Settings,
    *,
    include_history: bool,
    include_runs: bool,
    keep_models: bool,
) -> dict[str, int]:
    """Delete the scoped rows in FK-safe order and return the deleted counts.

    No commit happens here; the caller commits only after the whole reset
    succeeds. ``settings`` is accepted so callers share one signature with the
    rest of the ledger services (bankroll itself is derived from the rows).
    """
    del settings
    plan = ResetPlan(include_history, include_runs, keep_models)
    deleted: dict[str, int] = {}
    for name in plan.scoped_tables():
        if name == "clv_records" and not await _table_exists(session, name):
            deleted[name] = 0
            continue
        result = await session.execute(delete(_TABLES[name]))
        deleted[name] = int(cast("CursorResult[tuple[object, ...]]", result).rowcount or 0)
    return deleted


async def reset_shadow(session: AsyncSession) -> int:
    """Delete only shadow ledger bets; the caller owns the transaction."""
    result = await session.execute(delete(ShadowLedgerBet))
    return int(cast("CursorResult[tuple[object, ...]]", result).rowcount or 0)


def artifact_file_count(directory: str | Path) -> int:
    """Count files under the model artifact directory without deleting anything."""
    path = Path(directory)
    if not path.is_dir():
        return 0
    return sum(1 for candidate in path.rglob("*") if candidate.is_file())


def backup_database(database_url: str, destination: str | Path) -> None:
    """Run ``pg_dump`` before a destructive reset.

    Raises ``ResetError`` when pg_dump is unavailable or fails, so the caller
    can abort before deleting anything.
    """
    if not database_url.startswith("postgresql"):
        raise ResetError("pg_dump backup requires a PostgreSQL DATABASE_URL")
    url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    try:
        _ = subprocess.run(
            ["pg_dump", "--dbname", url, "--file", str(destination)],
            check=True,
        )
    except FileNotFoundError as exc:
        raise ResetError("pg_dump is not installed or not on PATH; nothing was deleted") from exc
    except subprocess.CalledProcessError as exc:
        raise ResetError(
            f"pg_dump failed with exit code {exc.returncode}; nothing was deleted"
        ) from exc
