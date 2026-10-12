from datetime import UTC, date, datetime

import httpx
from sqlalchemy import select

from app.api.main import create_app
from app.config import Settings
from app.data.leagues import seed_leagues
from app.db.base import Base
from app.db.models import League, Match, OddsSnapshot, Result, Season, Team
from app.db.session import Database


async def _db(tmp_path) -> Database:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return db


async def _seed(db: Database) -> int:
    async with db.session_factory() as session:
        await seed_leagues(session)
        league = (await session.execute(select(League).where(League.code == "EPL"))).scalar_one()
        season = Season(
            league_id=league.id, label="2026/27", start_date=date(2026, 7, 1), end_date=date(2027, 6, 30)
        )
        home = Team(name_en="Manchester United", name_ch="曼聯", hkjc_team_id="T-1", aliases=[])
        away = Team(name_en="Liverpool", name_ch="利物浦", hkjc_team_id="T-2", aliases=[])
        session.add_all([season, home, away])
        await session.flush()
        match = Match(
            season_id=season.id,
            league_id=league.id,
            hkjc_match_id="M-1001",
            kickoff_time=datetime(2026, 10, 12, 11, 30, tzinfo=UTC),
            status="finished",
            home_team_id=home.id,
            away_team_id=away.id,
            venue="Old Trafford",
        )
        session.add(match)
        await session.flush()
        session.add(
            OddsSnapshot(
                match_id=match.id,
                captured_at=datetime(2026, 10, 12, 9, 0, tzinfo=UTC),
                snapshot_bucket=datetime(2026, 10, 12, 9, 0, tzinfo=UTC),
                source="hkjc",
                inplay=False,
                odds_type="HAD",
                payload={"home": 2.1},
            )
        )
        session.add(
            OddsSnapshot(
                match_id=match.id,
                captured_at=datetime(2026, 10, 12, 9, 10, tzinfo=UTC),
                snapshot_bucket=datetime(2026, 10, 12, 9, 10, tzinfo=UTC),
                source="hkjc",
                inplay=False,
                odds_type="HAD",
                payload={"home": 2.2},
            )
        )
        session.add(
            Result(
                match_id=match.id,
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
        return match.id


async def _client(db: Database) -> httpx.AsyncClient:
    app = create_app(settings=Settings(_env_file=None, enable_scheduler=False), db=db)
    app.state.db = db
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_health(tmp_path):
    db = await _db(tmp_path)
    try:
        async with await _client(db) as client:
            response = await client.get("/health")
            assert response.status_code == 200
            assert response.json() == {"status": "ok"}
    finally:
        await db.dispose()


async def test_list_matches(tmp_path):
    db = await _db(tmp_path)
    try:
        await _seed(db)
        async with await _client(db) as client:
            response = await client.get("/matches")
            assert response.status_code == 200
            body = response.json()
            assert len(body) == 1
            assert body[0]["league_code"] == "EPL"
            assert body[0]["home_team"]["name_ch"] == "曼聯"
            assert body[0]["status"] == "finished"
    finally:
        await db.dispose()


async def test_list_matches_filters_by_league(tmp_path):
    db = await _db(tmp_path)
    try:
        await _seed(db)
        async with await _client(db) as client:
            response = await client.get("/matches", params={"league": "LALIGA"})
            assert response.json() == []
    finally:
        await db.dispose()


async def test_match_odds_returns_latest_per_type(tmp_path):
    db = await _db(tmp_path)
    try:
        match_id = await _seed(db)
        async with await _client(db) as client:
            response = await client.get(f"/matches/{match_id}/odds")
            body = response.json()
            assert len(body) == 1
            assert body[0]["odds_type"] == "HAD"
            assert body[0]["payload"] == {"home": 2.2}
    finally:
        await db.dispose()


async def test_match_odds_history_returns_all(tmp_path):
    db = await _db(tmp_path)
    try:
        match_id = await _seed(db)
        async with await _client(db) as client:
            response = await client.get(f"/matches/{match_id}/odds", params={"history": "true"})
            assert len(response.json()) == 2
    finally:
        await db.dispose()


async def test_match_odds_404(tmp_path):
    db = await _db(tmp_path)
    try:
        async with await _client(db) as client:
            response = await client.get("/matches/999/odds")
            assert response.status_code == 404
    finally:
        await db.dispose()


async def test_list_results(tmp_path):
    db = await _db(tmp_path)
    try:
        await _seed(db)
        async with await _client(db) as client:
            response = await client.get("/results")
            body = response.json()
            assert len(body) == 1
            assert body[0]["home_score"] == 0
            assert body[0]["source"] == "hkjc"
            assert body[0]["ttl_corner"] == 9
            assert body[0]["league_code"] == "EPL"
    finally:
        await db.dispose()
