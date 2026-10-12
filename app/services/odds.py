from datetime import UTC, date, datetime, timedelta

from sqlalchemy import and_, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.models import Match, OddsSnapshot
from app.providers.base import OddsRecord, Provider
from app.services.fixtures import FixtureSync
from app.services.runs import track_run


def snapshot_bucket(captured_at: datetime, interval_seconds: int) -> datetime:
    """Floor a timestamp to the sync interval so re-runs within a window are idempotent."""
    epoch = int(captured_at.timestamp())
    bucket = epoch - (epoch % interval_seconds)
    return datetime.fromtimestamp(bucket, tz=UTC)


class OddsSync:
    """Syncs fixtures, then stores one odds snapshot per (match, odds_type, inplay, bucket)."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        provider: Provider,
        settings: Settings,
    ) -> None:
        self._session_factory = session_factory
        self._provider = provider
        self._settings = settings
        self._fixture_sync = FixtureSync(session_factory, provider, settings)

    async def run(self, date_from: date, date_to: date) -> int:
        fixtures = await self._provider.fetch_fixtures(date_from, date_to)
        await self._fixture_sync.upsert(fixtures)
        records = await self._provider.fetch_odds(fixtures)
        return await track_run(
            self._session_factory,
            "sync_odds",
            lambda session: self._upsert_snapshots(session, records),
        )

    async def _upsert_snapshots(self, session: AsyncSession, records: list[OddsRecord]) -> int:
        count = 0
        for record in records:
            match = (
                await session.execute(
                    select(Match).where(Match.hkjc_match_id == record.match_hkjc_id)
                )
            ).scalar_one_or_none()
            if match is None:
                continue
            bucket = snapshot_bucket(record.captured_at, self._settings.sync_odds_interval)
            existing = (
                await session.execute(
                    select(OddsSnapshot).where(
                        OddsSnapshot.match_id == match.id,
                        OddsSnapshot.odds_type == record.odds_type,
                        OddsSnapshot.inplay == record.inplay,
                        OddsSnapshot.snapshot_bucket == bucket,
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                session.add(
                    OddsSnapshot(
                        match_id=match.id,
                        captured_at=record.captured_at,
                        snapshot_bucket=bucket,
                        source=self._provider.name,
                        inplay=record.inplay,
                        odds_type=record.odds_type,
                        payload=record.payload,
                    )
                )
            else:
                existing.captured_at = record.captured_at
                existing.payload = record.payload
            count += 1
        await session.flush()
        return count


COMPACT_KEEP_PER_GROUP = 3
COMPACT_MIN_AGE_HOURS = 6
DELETE_CHUNK = 500


def _raw_groups(keep: int):
    """``(match_id, odds_type, inplay)`` groups still holding a raw multi-row stream."""
    return (
        select(OddsSnapshot.match_id, OddsSnapshot.odds_type, OddsSnapshot.inplay)
        .group_by(OddsSnapshot.match_id, OddsSnapshot.odds_type, OddsSnapshot.inplay)
        .having(func.count() > keep)
        .subquery()
    )


async def _delete_ids(session_factory: async_sessionmaker[AsyncSession], ids: list[int]) -> int:
    if not ids:
        return 0
    deleted = 0
    async with session_factory() as session:
        for start in range(0, len(ids), DELETE_CHUNK):
            chunk = ids[start : start + DELETE_CHUNK]
            result = await session.execute(delete(OddsSnapshot).where(OddsSnapshot.id.in_(chunk)))
            deleted += result.rowcount or 0
        await session.commit()
    return deleted


async def compact_odds_snapshots(
    session_factory: async_sessionmaker[AsyncSession],
    lead_hours: int,
    now: datetime | None = None,
) -> int:
    """Collapse every finished match's HKJC snapshots to the anchors the readers need.

    Per ``(match_id, odds_type, inplay)`` it keeps the entry snapshot, the latest
    ``captured_at`` strictly before ``kickoff - lead_hours`` (the ML market prior)
    and the latest strictly before kickoff (the closing line CLV compares against).
    Only groups still holding a raw stream are considered, so this is incremental
    and re-running is a no-op; matches that have not finished are left untouched.
    """
    moment = now or datetime.now(UTC)
    groups = _raw_groups(COMPACT_KEEP_PER_GROUP)
    async with session_factory() as session:
        rows = (
            await session.execute(
                select(
                    OddsSnapshot.id,
                    OddsSnapshot.match_id,
                    OddsSnapshot.odds_type,
                    OddsSnapshot.inplay,
                    OddsSnapshot.captured_at,
                    Match.kickoff_time,
                )
                .join(
                    groups,
                    and_(
                        groups.c.match_id == OddsSnapshot.match_id,
                        groups.c.odds_type == OddsSnapshot.odds_type,
                        groups.c.inplay == OddsSnapshot.inplay,
                    ),
                )
                .join(Match, Match.id == OddsSnapshot.match_id)
                .where(OddsSnapshot.source == "hkjc")
                .where(Match.kickoff_time < moment - timedelta(hours=COMPACT_MIN_AGE_HOURS))
            )
        ).all()
    by_group: dict[tuple[int, str, bool], list] = {}
    for row in rows:
        by_group.setdefault((row.match_id, row.odds_type, row.inplay), []).append(row)
    keep: set[int] = set()
    for group in by_group.values():
        ordered = sorted(group, key=lambda row: row.captured_at)
        kickoff = ordered[0].kickoff_time
        prior_cutoff = kickoff - timedelta(hours=lead_hours)
        anchors = [ordered[0]]
        anchors += [row for row in ordered if row.captured_at < prior_cutoff][-1:]
        anchors += [row for row in ordered if row.captured_at < kickoff][-1:]
        keep.update(row.id for row in anchors)
    return await _delete_ids(session_factory, [row.id for row in rows if row.id not in keep])


async def prune_odds_snapshots(
    session_factory: async_sessionmaker[AsyncSession],
    retention_days: int,
    now: datetime | None = None,
) -> int:
    """Delete leftover rolling captures older than the retention window.

    Only rows whose ``(match_id, odds_type, inplay)`` group still holds a raw multi-row
    stream are eligible, so the compaction anchors survive indefinitely and the
    historical backfill (``source="football_data"``) stays untouched. This is a safety
    net: while compaction keeps up, it deletes nothing.
    """
    cutoff = (now or datetime.now(UTC)) - timedelta(days=retention_days)
    groups = _raw_groups(COMPACT_KEEP_PER_GROUP)
    async with session_factory() as session:
        ids = (
            await session.execute(
                select(OddsSnapshot.id)
                .join(
                    groups,
                    and_(
                        groups.c.match_id == OddsSnapshot.match_id,
                        groups.c.odds_type == OddsSnapshot.odds_type,
                        groups.c.inplay == OddsSnapshot.inplay,
                    ),
                )
                .where(OddsSnapshot.captured_at < cutoff)
                .where(OddsSnapshot.source != "football_data")
            )
        ).scalars().all()
    return await _delete_ids(session_factory, list(ids))
