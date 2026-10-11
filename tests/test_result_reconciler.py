from datetime import UTC, date, datetime

from sqlalchemy import select

from app.config import Settings
from app.data.leagues import seed_leagues
from app.db.base import Base
from app.db.models import IngestionRun, League, Match, Result, Season, Team
from app.db.session import Database
from app.providers.base import ResultRecord
from app.services.results import ResultReconciler


class _FakeProvider:
    name = "fake"

    def __init__(self, results: list[ResultRecord]) -> None:
        self._results = results

    async def fetch_leagues(self):
        return []

    async def fetch_fixtures(self, date_from, date_to):
        return []

    async def fetch_odds(self, fixtures):
        return []

    async def fetch_results(self, date_from, date_to):
        return self._results


async def _db(tmp_path) -> Database:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return db


async def _seed_match(db: Database, kickoff: datetime) -> int:
    async with db.session_factory() as session:
        await seed_leagues(session)
        league = (await session.execute(select(League).where(League.code == "EPL"))).scalar_one()
        season = Season(
            league_id=league.id, label="2026/27", start_date=date(2026, 7, 1), end_date=date(2027, 6, 30)
        )
        home = Team(name_en="Manchester United", name_ch="曼聯", hkjc_team_id="T-1", aliases=["Man Utd"])
        away = Team(name_en="Liverpool", name_ch="利物浦", hkjc_team_id="T-2", aliases=[])
        session.add_all([season, home, away])
        await session.flush()
        match = Match(
            season_id=season.id,
            league_id=league.id,
            hkjc_match_id="M-1001",
            kickoff_time=kickoff,
            status="finished",
            home_team_id=home.id,
            away_team_id=away.id,
        )
        session.add(match)
        await session.commit()
        return match.id


async def test_hkjc_result_is_upserted(tmp_path):
    db = await _db(tmp_path)
    try:
        now = datetime(2026, 10, 12, 22, 0, tzinfo=UTC)
        await _seed_match(db, datetime(2026, 10, 12, 11, 30, tzinfo=UTC))
        hkjc = _FakeProvider(
            [
                ResultRecord(
                    match_hkjc_id="M-1001",
                    home_score=0,
                    away_score=0,
                    ttl_corner=9,
                    source="hkjc",
                    confirmed=True,
                    payout_confirmed=True,
                    raw={"homeResult": "0"},
                )
            ]
        )
        reconciler = ResultReconciler(db.session_factory, hkjc, _FakeProvider([]), Settings(_env_file=None))
        assert await reconciler.run(now=now) == 1
        async with db.session_factory() as session:
            result = (await session.execute(select(Result))).scalar_one()
            assert result.source == "hkjc"
            assert result.confirmed is True
            assert result.ttl_corner == 9
            assert result.payout_confirmed is True
            assert result.confirmed_at is not None
    finally:
        await db.dispose()


async def test_fallback_result_is_upserted_when_hkjc_misses(tmp_path):
    db = await _db(tmp_path)
    try:
        now = datetime(2026, 10, 12, 22, 0, tzinfo=UTC)
        await _seed_match(db, datetime(2026, 10, 12, 11, 30, tzinfo=UTC))
        fallback = _FakeProvider(
            [
                ResultRecord(
                    match_date=date(2026, 10, 12),
                    home_team_name="Man Utd",
                    away_team_name="Liverpool",
                    home_score=2,
                    away_score=1,
                    source="football_data",
                )
            ]
        )
        reconciler = ResultReconciler(db.session_factory, _FakeProvider([]), fallback, Settings(_env_file=None))
        assert await reconciler.run(now=now) == 1
        async with db.session_factory() as session:
            result = (await session.execute(select(Result))).scalar_one()
            assert result.source == "football_data"
            assert result.confirmed is False
            assert result.ttl_corner is None
            assert result.home_score == 2
    finally:
        await db.dispose()


async def test_unresolved_after_48h_is_flagged(tmp_path):
    db = await _db(tmp_path)
    try:
        now = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
        match_id = await _seed_match(db, datetime(2026, 10, 12, 11, 30, tzinfo=UTC))
        reconciler = ResultReconciler(
            db.session_factory, _FakeProvider([]), _FakeProvider([]), Settings(_env_file=None)
        )
        await reconciler.run(now=now)
        async with db.session_factory() as session:
            runs = (
                await session.execute(select(IngestionRun).where(IngestionRun.job == "manual_review"))
            ).scalars().all()
            assert len(runs) == 1
            assert runs[0].status == "flagged"
            assert str(match_id) in (runs[0].error or "")
    finally:
        await db.dispose()


async def test_hkjc_overwrites_football_data_row(tmp_path):
    db = await _db(tmp_path)
    try:
        now = datetime(2026, 10, 12, 22, 0, tzinfo=UTC)
        match_id = await _seed_match(db, datetime(2026, 10, 12, 11, 30, tzinfo=UTC))
        async with db.session_factory() as session:
            session.add(
                Result(
                    match_id=match_id,
                    home_score=9,
                    away_score=9,
                    source="football_data",
                    confirmed=False,
                    payout_confirmed=False,
                    raw={},
                )
            )
            await session.commit()
        hkjc = _FakeProvider(
            [
                ResultRecord(
                    match_hkjc_id="M-1001",
                    home_score=0,
                    away_score=0,
                    ttl_corner=9,
                    source="hkjc",
                    confirmed=True,
                    payout_confirmed=True,
                )
            ]
        )
        reconciler = ResultReconciler(db.session_factory, hkjc, _FakeProvider([]), Settings(_env_file=None))
        await reconciler.run(now=now)
        async with db.session_factory() as session:
            result = (await session.execute(select(Result))).scalar_one()
            assert result.source == "hkjc"
            assert result.home_score == 0
            assert result.confirmed is True
    finally:
        await db.dispose()


async def test_fallback_upsert_skips_existing_hkjc_row(tmp_path):
    db = await _db(tmp_path)
    try:
        match_id = await _seed_match(db, datetime(2026, 10, 12, 11, 30, tzinfo=UTC))
        async with db.session_factory() as session:
            session.add(
                Result(
                    match_id=match_id,
                    home_score=0,
                    away_score=0,
                    ttl_corner=9,
                    source="hkjc",
                    confirmed=True,
                    payout_confirmed=True,
                    raw={},
                )
            )
            await session.commit()
        reconciler = ResultReconciler(
            db.session_factory, _FakeProvider([]), _FakeProvider([]), Settings(_env_file=None)
        )
        record = ResultRecord(
            match_date=date(2026, 10, 12),
            home_team_name="Man Utd",
            away_team_name="Liverpool",
            home_score=5,
            away_score=5,
            source="football_data",
        )
        async with db.session_factory() as session:
            count = await reconciler._upsert_fallback(session, [record], [match_id])
            await session.commit()
        assert count == 0
        async with db.session_factory() as session:
            result = (await session.execute(select(Result))).scalar_one()
            assert result.source == "hkjc"
            assert result.home_score == 0
    finally:
        await db.dispose()
