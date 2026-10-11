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


async def prune_odds_snapshots(
    session_factory: async_sessionmaker[AsyncSession],
    retention_days: int,
    now: datetime | None = None,
) -> int:
    """Delete odds snapshots older than the retention window. Returns rows deleted."""
    cutoff = (now or datetime.now(UTC)) - timedelta(days=retention_days)
    async with session_factory() as session:
        result = await session.execute(
            delete(OddsSnapshot).where(OddsSnapshot.captured_at < cutoff)
        )
        await session.commit()
        return result.rowcount or 0
