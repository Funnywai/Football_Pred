from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.base import Base
from app.db.models import (
    IngestionRun,
    League,
    Match,
    ModelVersion,
    OddsSnapshot,
    Result,
    Season,
    Team,
)
from app.db.session import Database


async def _seed(db: Database) -> dict[str, int]:
    async with db.session_factory() as session:
        league = League(
            code="EPL",
            name_en="English Premier League",
            name_ch="英格蘭超級聯賽",
            country="England",
        )
        session.add(league)
        await session.flush()
        season = Season(
            league_id=league.id,
            label="2026/27",
            start_date=date(2026, 7, 1),
            end_date=date(2027, 6, 30),
        )
        home = Team(
            name_en="Manchester United",
            name_ch="曼聯",
            hkjc_team_id="T1",
            aliases=["Man Utd", "曼聯"],
        )
        away = Team(name_en="Liverpool", name_ch="利物浦", hkjc_team_id="T2", aliases=["Liverpool FC"])
        session.add_all([season, home, away])
        await session.flush()
        match = Match(
            season_id=season.id,
            league_id=league.id,
            hkjc_match_id="M1",
            kickoff_time=datetime(2026, 10, 12, 19, 30, tzinfo=UTC),
            home_team_id=home.id,
            away_team_id=away.id,
            venue="Old Trafford",
            round="Round 8",
        )
        session.add(match)
        await session.commit()
        return {
            "league": league.id,
            "season": season.id,
            "home": home.id,
            "away": away.id,
            "match": match.id,
        }


async def test_models_create_and_roundtrip(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    try:
        async with db.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        ids = await _seed(db)
        async with db.session_factory() as session:
            team = (await session.execute(select(Team).where(Team.id == ids["home"]))).scalar_one()
            assert team.aliases == ["Man Utd", "曼聯"]
            assert team.external_ids == {}
            match = (await session.execute(select(Match).where(Match.id == ids["match"]))).scalar_one()
            assert match.status == "scheduled"
            assert match.kickoff_time == datetime(2026, 10, 12, 19, 30, tzinfo=UTC)
    finally:
        await db.dispose()


async def test_odds_snapshot_unique_bucket(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    try:
        async with db.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        ids = await _seed(db)
        bucket = datetime(2026, 10, 12, 19, 30, tzinfo=UTC)
        async with db.session_factory() as session:
            session.add(
                OddsSnapshot(
                    match_id=ids["match"],
                    captured_at=bucket,
                    snapshot_bucket=bucket,
                    source="hkjc",
                    inplay=False,
                    odds_type="HAD",
                    payload={"home": 2.1},
                )
            )
            await session.commit()
        async with db.session_factory() as session:
            session.add(
                OddsSnapshot(
                    match_id=ids["match"],
                    captured_at=bucket,
                    snapshot_bucket=bucket,
                    source="hkjc",
                    inplay=False,
                    odds_type="HAD",
                    payload={"home": 2.2},
                )
            )
            with pytest.raises(IntegrityError):
                await session.commit()
    finally:
        await db.dispose()


async def test_result_unique_per_match(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    try:
        async with db.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        ids = await _seed(db)
        async with db.session_factory() as session:
            session.add(
                Result(
                    match_id=ids["match"],
                    home_score=2,
                    away_score=1,
                    source="hkjc",
                    confirmed=True,
                    payout_confirmed=True,
                    confirmed_at=datetime(2026, 10, 12, 21, 45, tzinfo=UTC),
                    raw={"homeResult": "2"},
                )
            )
            await session.commit()
        async with db.session_factory() as session:
            session.add(
                Result(
                    match_id=ids["match"],
                    home_score=0,
                    away_score=0,
                    source="football_data",
                    confirmed=False,
                    payout_confirmed=False,
                    raw={},
                )
            )
            with pytest.raises(IntegrityError):
                await session.commit()
    finally:
        await db.dispose()


async def test_ml_models_create_and_roundtrip(tmp_path) -> None:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    try:
        async with db.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with db.session_factory() as session:
            session.add(
                ModelVersion(
                    target="1x2",
                    algorithm="lightgbm",
                    params={"n": 1},
                    metrics={"brier": 0.2},
                    artifact_path="/tmp/m1.joblib",
                    status="challenger",
                )
            )
            await session.commit()
        async with db.session_factory() as session:
            version = (await session.execute(select(ModelVersion))).scalar_one()
            assert version.status == "challenger"
            assert version.metrics["brier"] == 0.2
    finally:
        await db.dispose()


async def test_ingestion_run_defaults(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    try:
        async with db.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with db.session_factory() as session:
            run = IngestionRun(
                job="sync_odds",
                started_at=datetime(2026, 10, 12, 12, 0, tzinfo=UTC),
                status="running",
            )
            session.add(run)
            await session.commit()
            assert run.records_upserted == 0
            assert run.finished_at is None
            assert run.error is None
    finally:
        await db.dispose()
