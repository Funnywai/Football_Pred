from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete, select
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


COMPACT_LOOKBACK_DAYS = 3
COMPACT_MIN_AGE_HOURS = 6
DELETE_CHUNK = 500


async def compact_odds_snapshots(
    session_factory: async_sessionmaker[AsyncSession],
    lead_hours: int,
    now: datetime | None = None,
    lookback_days: int = COMPACT_LOOKBACK_DAYS,
) -> int:
    """Collapse finished matches' HKJC snapshots to the anchors the readers need.

    Per ``(match_id, odds_type, inplay)`` it keeps the entry snapshot, the latest
    ``captured_at`` strictly before ``kickoff - lead_hours`` (the ML market prior)
    and the latest strictly before kickoff (the closing line CLV compares against).
    Every other snapshot — over 99% of the rolling stream — is deleted, so re-running
    is a no-op. Matches not yet finished (or older than ``lookback_days``, which the
    retention prune covers) are left untouched.
    """
    moment = now or datetime.now(UTC)
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
                .join(Match, Match.id == OddsSnapshot.match_id)
                .where(OddsSnapshot.source == "hkjc")
                .where(Match.kickoff_time >= moment - timedelta(days=lookback_days))
                .where(Match.kickoff_time < moment - timedelta(hours=COMPACT_MIN_AGE_HOURS))
            )
        ).all()
    groups: dict[tuple[int, str, bool], list] = {}
    for row in rows:
        groups.setdefault((row.match_id, row.odds_type, row.inplay), []).append(row)
    keep: set[int] = set()
    for group in groups.values():
        ordered = sorted(group, key=lambda row: row.captured_at)
        kickoff = ordered[0].kickoff_time
        prior_cutoff = kickoff - timedelta(hours=lead_hours)
        anchors = [ordered[0]]
        anchors += [row for row in ordered if row.captured_at < prior_cutoff][-1:]
        anchors += [row for row in ordered if row.captured_at < kickoff][-1:]
        keep.update(row.id for row in anchors)
    obsolete = [row.id for row in rows if row.id not in keep]
    if not obsolete:
        return 0
    deleted = 0
    async with session_factory() as session:
        for start in range(0, len(obsolete), DELETE_CHUNK):
            chunk = obsolete[start : start + DELETE_CHUNK]
            result = await session.execute(delete(OddsSnapshot).where(OddsSnapshot.id.in_(chunk)))
            deleted += result.rowcount or 0
        await session.commit()
    return deleted


async def prune_odds_snapshots(
    session_factory: async_sessionmaker[AsyncSession],
    retention_days: int,
    now: datetime | None = None,
) -> int:
    """Delete rolling odds snapshots older than the retention window. Returns rows deleted.

    Historical backfill captures (``source="football_data"``) are exempt: their
    ``captured_at`` is the kickoff time, so they always fall outside any retention
    window, yet they are the market priors the ML models train on.
    """
    cutoff = (now or datetime.now(UTC)) - timedelta(days=retention_days)
    async with session_factory() as session:
        result = await session.execute(
            delete(OddsSnapshot)
            .where(OddsSnapshot.captured_at < cutoff)
            .where(OddsSnapshot.source != "football_data")
        )
        await session.commit()
        return result.rowcount or 0
