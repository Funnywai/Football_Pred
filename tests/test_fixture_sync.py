from datetime import UTC, date, datetime

from sqlalchemy import select

from app.config import Settings
from app.data.leagues import seed_leagues
from app.db.base import Base
from app.db.models import League, Match, Season, Team
from app.db.session import Database
from app.providers.base import FixtureRecord
from app.services.fixtures import FixtureSync, season_bounds, season_label_for


class _FakeProvider:
    name = "fake"

    def __init__(self, fixtures: list[FixtureRecord]) -> None:
        self._fixtures = fixtures

    async def fetch_leagues(self):
        return []

    async def fetch_fixtures(self, date_from, date_to):
        return self._fixtures

    async def fetch_odds(self, fixtures):
        return []

    async def fetch_results(self, date_from, date_to):
        return []


def _fixture(**overrides) -> FixtureRecord:
    base = {
        "source": "fake",
        "league_name": "English Premier League",
        "hkjc_tourn_id": "TOURN-EPL",
        "hkjc_match_id": "M-1001",
        "kickoff_time": datetime(2026, 10, 12, 11, 30, tzinfo=UTC),
        "status": "scheduled",
        "home_team_name_en": "Manchester United",
        "home_team_name_ch": "曼聯",
        "home_team_hkjc_id": "T-1",
        "away_team_name_en": "Liverpool",
        "away_team_name_ch": "利物浦",
        "away_team_hkjc_id": "T-2",
        "venue": "Old Trafford",
    }
    base.update(overrides)
    return FixtureRecord(**base)


async def _db(tmp_path) -> Database:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with db.session_factory() as session:
        await seed_leagues(session)
        await session.commit()
    return db


def test_season_label_and_bounds():
    assert season_label_for(datetime(2026, 10, 12, tzinfo=UTC)) == "2026/27"
    assert season_label_for(datetime(2026, 3, 1, tzinfo=UTC)) == "2025/26"
    assert season_bounds("2026/27") == (date(2026, 7, 1), date(2027, 6, 30))


async def test_fixture_sync_creates_match_teams_and_season(tmp_path):
    db = await _db(tmp_path)
    try:
        provider = _FakeProvider([_fixture()])
        sync = FixtureSync(db.session_factory, provider, Settings(_env_file=None))
        assert await sync.run(date(2026, 10, 12), date(2026, 10, 15)) == 1
        async with db.session_factory() as session:
            match = (await session.execute(select(Match))).scalar_one()
            assert match.hkjc_match_id == "M-1001"
            assert match.status == "scheduled"
            assert match.venue == "Old Trafford"
            season = (await session.execute(select(Season))).scalar_one()
            assert season.label == "2026/27"
            teams = (await session.execute(select(Team))).scalars().all()
            assert {team.hkjc_team_id for team in teams} == {"T-1", "T-2"}
            league = (await session.execute(select(League).where(League.code == "EPL"))).scalar_one()
            assert league.hkjc_tourn_id == "50071337"
    finally:
        await db.dispose()


async def test_fixture_sync_is_idempotent(tmp_path):
    db = await _db(tmp_path)
    try:
        provider = _FakeProvider([_fixture()])
        sync = FixtureSync(db.session_factory, provider, Settings(_env_file=None))
        await sync.run(date(2026, 10, 12), date(2026, 10, 15))
        await sync.run(date(2026, 10, 12), date(2026, 10, 15))
        async with db.session_factory() as session:
            matches = (await session.execute(select(Match))).scalars().all()
            assert len(matches) == 1
    finally:
        await db.dispose()


async def test_fixture_sync_skips_non_whitelisted_league(tmp_path):
    db = await _db(tmp_path)
    try:
        provider = _FakeProvider(
            [_fixture(hkjc_match_id="M-2001", league_name="Friendly Cup", hkjc_tourn_id="TOURN-FRIENDLY")]
        )
        sync = FixtureSync(db.session_factory, provider, Settings(_env_file=None))
        assert await sync.run(date(2026, 10, 12), date(2026, 10, 15)) == 0
        async with db.session_factory() as session:
            assert (await session.execute(select(Match))).scalars().all() == []
    finally:
        await db.dispose()


async def test_fixture_sync_matches_league_by_tourn_id_not_name(tmp_path):
    db = await _db(tmp_path)
    try:
        provider = _FakeProvider(
            [_fixture(league_name="Italian Division 1", hkjc_tourn_id="50072541")]
        )
        sync = FixtureSync(db.session_factory, provider, Settings(_env_file=None))
        assert await sync.run(date(2026, 10, 12), date(2026, 10, 15)) == 1
        async with db.session_factory() as session:
            match = (await session.execute(select(Match))).scalar_one()
            league = (
                await session.execute(select(League).where(League.id == match.league_id))
            ).scalar_one()
            assert league.code == "SERIEA"
    finally:
        await db.dispose()


async def test_seed_leagues_backfills_hkjc_tourn_id(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'seed.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        async with db.session_factory() as session:
            session.add(
                League(
                    code="EPL",
                    name_en="English Premier League",
                    name_ch=None,
                    country=None,
                    active=True,
                )
            )
            await session.commit()
        async with db.session_factory() as session:
            assert await seed_leagues(session) == 5
            await session.commit()
        async with db.session_factory() as session:
            league = (await session.execute(select(League).where(League.code == "EPL"))).scalar_one()
            assert league.hkjc_tourn_id == "50071337"
    finally:
        await db.dispose()


async def test_seed_leagues_seeds_bundesliga_and_ligue1_tourn_ids(tmp_path):
    db = await _db(tmp_path)
    try:
        async with db.session_factory() as session:
            leagues = {
                league.code: league
                for league in (await session.execute(select(League))).scalars().all()
            }
            assert leagues["BUNDESLIGA"].hkjc_tourn_id == "50072572"
            assert leagues["LIGUE1"].hkjc_tourn_id == "50072542"
    finally:
        await db.dispose()


async def test_fixture_sync_updates_existing_match(tmp_path):
    db = await _db(tmp_path)
    try:
        sync = FixtureSync(db.session_factory, _FakeProvider([_fixture()]), Settings(_env_file=None))
        await sync.run(date(2026, 10, 12), date(2026, 10, 15))
        updated = _fixture(status="live", venue="Anfield")
        sync2 = FixtureSync(db.session_factory, _FakeProvider([updated]), Settings(_env_file=None))
        await sync2.run(date(2026, 10, 12), date(2026, 10, 15))
        async with db.session_factory() as session:
            match = (await session.execute(select(Match))).scalar_one()
            assert match.status == "live"
            assert match.venue == "Anfield"
    finally:
        await db.dispose()
