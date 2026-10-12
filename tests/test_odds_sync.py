from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select

from app.config import Settings
from app.data.leagues import seed_leagues
from app.db.base import Base
from app.db.models import OddsSnapshot
from app.db.session import Database
from app.providers.base import FixtureRecord, OddsRecord
from app.services.odds import OddsSync, prune_odds_snapshots, snapshot_bucket


class _FakeProvider:
    name = "fake"

    def __init__(self, fixtures: list[FixtureRecord], odds: list[OddsRecord]) -> None:
        self._fixtures = fixtures
        self._odds = odds

    async def fetch_leagues(self):
        return []

    async def fetch_fixtures(self, date_from, date_to):
        return self._fixtures

    async def fetch_odds(self, fixtures):
        return self._odds

    async def fetch_results(self, date_from, date_to):
        return []


class _HistoricalProvider(_FakeProvider):
    name = "football_data"


def _fixture() -> FixtureRecord:
    return FixtureRecord(
        source="fake",
        league_name="English Premier League",
        hkjc_tourn_id="TOURN-EPL",
        hkjc_match_id="M-1001",
        kickoff_time=datetime(2026, 10, 12, 11, 30, tzinfo=UTC),
        home_team_name_en="Manchester United",
        home_team_name_ch="曼聯",
        home_team_hkjc_id="T-1",
        away_team_name_en="Liverpool",
        away_team_name_ch="利物浦",
        away_team_hkjc_id="T-2",
    )


def _odds(captured_at: datetime) -> list[OddsRecord]:
    return [
        OddsRecord(match_hkjc_id="M-1001", odds_type="HAD", inplay=False, captured_at=captured_at, payload={"v": 1}),
        OddsRecord(match_hkjc_id="M-1001", odds_type="HDC", inplay=False, captured_at=captured_at, payload={"v": 1}),
    ]


async def _db(tmp_path) -> Database:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with db.session_factory() as session:
        await seed_leagues(session)
        await session.commit()
    return db


def test_snapshot_bucket_floors_to_interval():
    captured = datetime(2026, 10, 12, 12, 7, 30, tzinfo=UTC)
    assert snapshot_bucket(captured, 600) == datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
    assert snapshot_bucket(captured, 900) == datetime(2026, 10, 12, 12, 0, tzinfo=UTC)


async def test_odds_sync_inserts_snapshots(tmp_path):
    db = await _db(tmp_path)
    try:
        captured = datetime(2026, 10, 12, 12, 7, 30, tzinfo=UTC)
        provider = _FakeProvider([_fixture()], _odds(captured))
        sync = OddsSync(db.session_factory, provider, Settings(_env_file=None))
        assert await sync.run(date(2026, 10, 12), date(2026, 10, 15)) == 2
        async with db.session_factory() as session:
            snapshots = (await session.execute(select(OddsSnapshot))).scalars().all()
            assert len(snapshots) == 2
            assert {s.odds_type for s in snapshots} == {"HAD", "HDC"}
            assert all(s.snapshot_bucket == datetime(2026, 10, 12, 12, 0, tzinfo=UTC) for s in snapshots)
    finally:
        await db.dispose()


async def test_odds_sync_is_idempotent_within_bucket(tmp_path):
    db = await _db(tmp_path)
    try:
        captured = datetime(2026, 10, 12, 12, 7, 30, tzinfo=UTC)
        provider = _FakeProvider([_fixture()], _odds(captured))
        sync = OddsSync(db.session_factory, provider, Settings(_env_file=None))
        await sync.run(date(2026, 10, 12), date(2026, 10, 15))
        await sync.run(date(2026, 10, 12), date(2026, 10, 15))
        async with db.session_factory() as session:
            assert len((await session.execute(select(OddsSnapshot))).scalars().all()) == 2
    finally:
        await db.dispose()


async def test_odds_sync_new_bucket_adds_rows(tmp_path):
    db = await _db(tmp_path)
    try:
        first = datetime(2026, 10, 12, 12, 7, 30, tzinfo=UTC)
        second = datetime(2026, 10, 12, 12, 17, 30, tzinfo=UTC)
        sync = OddsSync(db.session_factory, _FakeProvider([_fixture()], _odds(first)), Settings(_env_file=None))
        await sync.run(date(2026, 10, 12), date(2026, 10, 15))
        sync2 = OddsSync(db.session_factory, _FakeProvider([_fixture()], _odds(second)), Settings(_env_file=None))
        await sync2.run(date(2026, 10, 12), date(2026, 10, 15))
        async with db.session_factory() as session:
            assert len((await session.execute(select(OddsSnapshot))).scalars().all()) == 4
    finally:
        await db.dispose()


async def test_prune_keeps_historical_training_snapshots(tmp_path):
    db = await _db(tmp_path)
    try:
        historical = datetime(2010, 8, 14, 12, 7, tzinfo=UTC)
        provider = _HistoricalProvider([_fixture()], _odds(historical))
        await OddsSync(db.session_factory, provider, Settings(_env_file=None)).run(
            date(2026, 10, 12), date(2026, 10, 15)
        )
        deleted = await prune_odds_snapshots(
            db.session_factory, retention_days=120, now=datetime(2026, 10, 12, tzinfo=UTC)
        )
        assert deleted == 0
        async with db.session_factory() as session:
            assert len((await session.execute(select(OddsSnapshot))).scalars().all()) == 2
    finally:
        await db.dispose()


async def test_prune_odds_snapshots_removes_old_rows(tmp_path):
    db = await _db(tmp_path)
    try:
        first = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
        for minutes in (0, 10, 20, 30):
            sync = OddsSync(
                db.session_factory,
                _FakeProvider([_fixture()], _odds(first + timedelta(minutes=minutes))),
                Settings(_env_file=None),
            )
            await sync.run(date(2026, 10, 12), date(2026, 10, 15))
        async with db.session_factory() as session:
            assert len((await session.execute(select(OddsSnapshot))).scalars().all()) == 8
        deleted = await prune_odds_snapshots(
            db.session_factory, retention_days=30, now=first + timedelta(days=60)
        )
        assert deleted == 8
        async with db.session_factory() as session:
            assert (await session.execute(select(OddsSnapshot))).scalars().all() == []
    finally:
        await db.dispose()
