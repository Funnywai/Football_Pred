from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select

from app.cli import backfill
from app.config import Settings
from app.data.leagues import seed_leagues
from app.db.base import Base
from app.db.models import Match, MatchStat, OddsSnapshot, Result
from app.db.session import Database
from app.ml.dataset import load_training_rows
from app.providers.football_data.provider import HistoricalMatchRecord


class _FakeProvider:
    name = "football_data"

    def __init__(self, records: list[HistoricalMatchRecord]) -> None:
        self._records = records

    async def fetch_historical(self, year, divisions=None):
        return self._records


def _record() -> HistoricalMatchRecord:
    return HistoricalMatchRecord(
        division="E0",
        league_code="EPL",
        season_label="2010/11",
        match_date=date(2010, 8, 14),
        kickoff_time=datetime(2010, 8, 14, 15, 0, tzinfo=UTC),
        home_team_name="Manchester United",
        away_team_name="Liverpool",
        home_score=2,
        away_score=1,
        odds={"B365": {"open": [1.5, 4.0, 6.0], "close": [1.6, 3.8, 5.5]}},
    )


def _record_with_stats() -> HistoricalMatchRecord:
    return HistoricalMatchRecord(
        division="E0",
        league_code="EPL",
        season_label="2010/11",
        match_date=date(2010, 8, 14),
        kickoff_time=datetime(2010, 8, 14, 15, 0, tzinfo=UTC),
        home_team_name="Manchester United",
        away_team_name="Liverpool",
        home_score=2,
        away_score=1,
        odds={"B365": {"open": [1.5, 4.0, 6.0], "close": [1.6, 3.8, 5.5]}},
        home_shots=15,
        away_shots=9,
        home_sot=6,
        away_sot=3,
        home_xg=1.8,
        away_xg=0.9,
        home_corners=7,
        away_corners=4,
    )


async def _db(tmp_path) -> Database:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with db.session_factory() as session:
        await seed_leagues(session)
        await session.commit()
    return db


async def test_backfill_creates_matches_and_odds(tmp_path):
    db = await _db(tmp_path)
    try:
        total = await backfill(db.session_factory, _FakeProvider([_record()]), 2010, 2010, ["E0"])
        assert total == 1
        async with db.session_factory() as session:
            match = (await session.execute(select(Match))).scalar_one()
            assert match.hkjc_match_id is None
            assert match.status == "finished"
            snapshot = (await session.execute(select(OddsSnapshot))).scalar_one()
            assert snapshot.odds_type == "HAD"
            assert snapshot.source == "football_data"
            assert snapshot.payload["odds"]["B365"]["close"] == [1.6, 3.8, 5.5]
    finally:
        await db.dispose()


async def test_backfill_is_idempotent(tmp_path):
    db = await _db(tmp_path)
    try:
        provider = _FakeProvider([_record()])
        await backfill(db.session_factory, provider, 2010, 2010, ["E0"])
        await backfill(db.session_factory, provider, 2010, 2010, ["E0"])
        async with db.session_factory() as session:
            assert len((await session.execute(select(Match))).scalars().all()) == 1
            assert len((await session.execute(select(OddsSnapshot))).scalars().all()) == 1
            assert len((await session.execute(select(Result))).scalars().all()) == 1
    finally:
        await db.dispose()


async def test_backfill_creates_confirmed_results(tmp_path):
    db = await _db(tmp_path)
    try:
        await backfill(db.session_factory, _FakeProvider([_record()]), 2010, 2010, ["E0"])
        async with db.session_factory() as session:
            result = (await session.execute(select(Result))).scalar_one()
            assert result.home_score == 2
            assert result.away_score == 1
            assert result.source == "football_data"
            assert result.confirmed is True
            assert result.confirmed_at is not None
    finally:
        await db.dispose()


async def test_backfill_creates_match_stats_with_availability_guard(tmp_path):
    db = await _db(tmp_path)
    try:
        record = _record_with_stats()
        await backfill(db.session_factory, _FakeProvider([record]), 2010, 2010, ["E0"])
        async with db.session_factory() as session:
            stat = (await session.execute(select(MatchStat))).scalar_one()
            assert stat.source == "football_data"
            assert stat.home_shots == 15
            assert stat.away_shots == 9
            assert stat.home_sot == 6
            assert stat.away_sot == 3
            assert stat.home_xg == 1.8
            assert stat.away_xg == 0.9
            assert stat.home_corners == 7
            assert stat.away_corners == 4
            assert stat.available_at == record.kickoff_time + timedelta(hours=24)
    finally:
        await db.dispose()


async def test_backfill_match_stats_is_idempotent(tmp_path):
    db = await _db(tmp_path)
    try:
        provider = _FakeProvider([_record_with_stats()])
        await backfill(db.session_factory, provider, 2010, 2010, ["E0"])
        await backfill(db.session_factory, provider, 2010, 2010, ["E0"])
        async with db.session_factory() as session:
            assert len((await session.execute(select(MatchStat))).scalars().all()) == 1
    finally:
        await db.dispose()


async def test_backfill_without_stats_creates_no_match_stats(tmp_path):
    db = await _db(tmp_path)
    try:
        await backfill(db.session_factory, _FakeProvider([_record()]), 2010, 2010, ["E0"])
        async with db.session_factory() as session:
            assert (await session.execute(select(MatchStat))).scalars().all() == []
    finally:
        await db.dispose()


async def test_backfilled_history_is_usable_for_training(tmp_path):
    db = await _db(tmp_path)
    try:
        await backfill(db.session_factory, _FakeProvider([_record()]), 2010, 2010, ["E0"])
        async with db.session_factory() as session:
            rows = await load_training_rows(session, Settings(_env_file=None))
            assert [(row.home_score, row.away_score) for row in rows] == [(2, 1)]
    finally:
        await db.dispose()
