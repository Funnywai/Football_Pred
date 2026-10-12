import pytest
from sqlalchemy import select

from app.data.leagues import seed_leagues
from app.db.base import Base
from app.db.models import IngestionRun, League
from app.db.session import Database
from app.services.runs import flag_manual_review, track_run


async def _db(tmp_path) -> Database:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return db


async def test_track_run_records_success(tmp_path):
    db = await _db(tmp_path)
    try:
        async def work(session) -> int:
            return 7

        count = await track_run(db.session_factory, "sync_odds", work)
        assert count == 7
        async with db.session_factory() as session:
            run = (await session.execute(select(IngestionRun))).scalar_one()
            assert run.job == "sync_odds"
            assert run.status == "success"
            assert run.records_upserted == 7
            assert run.finished_at is not None
    finally:
        await db.dispose()


async def test_track_run_records_failure(tmp_path):
    db = await _db(tmp_path)
    try:
        async def work(session) -> int:
            raise ValueError("boom")

        with pytest.raises(ValueError):
            await track_run(db.session_factory, "settle_results", work)
        async with db.session_factory() as session:
            run = (await session.execute(select(IngestionRun))).scalar_one()
            assert run.status == "failed"
            assert "ValueError" in (run.error or "")
    finally:
        await db.dispose()


async def test_flag_manual_review_writes_row(tmp_path):
    db = await _db(tmp_path)
    try:
        await flag_manual_review(db.session_factory, "manual_review", [11, 22])
        async with db.session_factory() as session:
            run = (await session.execute(select(IngestionRun))).scalar_one()
            assert run.job == "manual_review"
            assert run.status == "flagged"
            assert run.records_upserted == 2
            assert "11" in (run.error or "")
    finally:
        await db.dispose()


async def test_flag_manual_review_noop_when_empty(tmp_path):
    db = await _db(tmp_path)
    try:
        await flag_manual_review(db.session_factory, "manual_review", [])
        async with db.session_factory() as session:
            assert (await session.execute(select(IngestionRun))).scalars().all() == []
    finally:
        await db.dispose()


async def test_seed_leagues_is_idempotent(tmp_path):
    db = await _db(tmp_path)
    try:
        async with db.session_factory() as session:
            assert await seed_leagues(session) == 6
            await session.commit()
        async with db.session_factory() as session:
            assert await seed_leagues(session) == 0
            await session.commit()
            leagues = (await session.execute(select(League))).scalars().all()
            assert {league.code for league in leagues} == {
                "EPL",
                "LALIGA",
                "SERIEA",
                "BUNDESLIGA",
                "LIGUE1",
                "UCL",
            }
    finally:
        await db.dispose()
