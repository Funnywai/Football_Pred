"""Paper ledger tests: settlement, placement, and read-time math (sub-system C)."""

from datetime import UTC, datetime

import pytest
from ml_helpers import make_db, seed_context, seed_finished_match, seed_team
from sqlalchemy import delete, select

from app.db.models import LedgerBet, ModelVersion, Result
from app.services.ledger import settle_bets

KICKOFF = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


async def _db_with_result(
    tmp_path, *, home_score: int, away_score: int
) -> tuple:
    """Seed one finished match (HKJC result confirmed) + a champion; return (db, match.id)."""
    db = await make_db(tmp_path)
    async with db.session_factory() as session:
        league, season = await seed_context(session)
        home = await seed_team(session, "Home")
        away = await seed_team(session, "Away")
        match = await seed_finished_match(
            session, league, season, home, away,
            match_id_label="M1", kickoff=KICKOFF,
            home_score=home_score, away_score=away_score,
        )
        session.add(
            ModelVersion(
                target="1x2", algorithm="lightgbm", params={}, metrics={},
                artifact_path="/tmp/m1.joblib", status="champion",
            )
        )
        await session.commit()
    return db, match.id


async def _add_bet(
    db,
    match_id: int,
    *,
    target: str = "1x2",
    outcome: str = "H",
    line: float | None = None,
    odds: float = 2.1,
    stake: float = 15.0,
) -> None:
    async with db.session_factory() as session:
        version = (await session.execute(select(ModelVersion))).scalar_one()
        session.add(
            LedgerBet(
                match_id=match_id, target=target, outcome=outcome,
                model_version_id=version.id, line=line,
                odds=odds, stake=stake, bankroll_at_place=1000.0, kelly_multiplier=0.5,
            )
        )
        await session.commit()


async def _the_bet(db) -> LedgerBet:
    async with db.session_factory() as session:
        return (await session.execute(select(LedgerBet))).scalar_one()


async def test_settle_won_1x2(tmp_path) -> None:
    db, match_id = await _db_with_result(tmp_path, home_score=2, away_score=1)
    await _add_bet(db, match_id, outcome="H")
    async with db.session_factory() as session:
        assert await settle_bets(session) == 1
        await session.commit()
    bet = await _the_bet(db)
    assert bet.status == "won"
    assert bet.payout == pytest.approx(15.0 * 2.1)
    assert bet.profit == pytest.approx(15.0 * 2.1 - 15.0)
    assert bet.settled_at is not None
    assert bet.result_source == "hkjc"


async def test_settle_lost_1x2(tmp_path) -> None:
    db, match_id = await _db_with_result(tmp_path, home_score=2, away_score=1)
    await _add_bet(db, match_id, outcome="A")
    async with db.session_factory() as session:
        assert await settle_bets(session) == 1
        await session.commit()
    bet = await _the_bet(db)
    assert bet.status == "lost"
    assert bet.payout == 0.0
    assert bet.profit == pytest.approx(-15.0)


async def test_settle_won_handicap(tmp_path) -> None:
    db, match_id = await _db_with_result(tmp_path, home_score=2, away_score=1)
    await _add_bet(db, match_id, target="handicap", outcome="H", line=-0.5)
    async with db.session_factory() as session:
        assert await settle_bets(session) == 1
        await session.commit()
    bet = await _the_bet(db)
    assert bet.status == "won"
    assert bet.payout == pytest.approx(15.0 * 2.1)


async def test_settle_lost_handicap(tmp_path) -> None:
    db, match_id = await _db_with_result(tmp_path, home_score=2, away_score=1)
    await _add_bet(db, match_id, target="handicap", outcome="A", line=-0.5)
    async with db.session_factory() as session:
        assert await settle_bets(session) == 1
        await session.commit()
    bet = await _the_bet(db)
    assert bet.status == "lost"


async def test_settle_push_handicap_whole_line(tmp_path) -> None:
    db, match_id = await _db_with_result(tmp_path, home_score=2, away_score=1)
    await _add_bet(db, match_id, target="handicap", outcome="H", line=-1.0)
    async with db.session_factory() as session:
        assert await settle_bets(session) == 1
        await session.commit()
    bet = await _the_bet(db)
    assert bet.status == "push"
    assert bet.payout == pytest.approx(15.0)
    assert bet.profit == 0.0


async def test_settle_idempotent(tmp_path) -> None:
    db, match_id = await _db_with_result(tmp_path, home_score=2, away_score=1)
    await _add_bet(db, match_id, outcome="H")
    async with db.session_factory() as session:
        assert await settle_bets(session) == 1
        await session.commit()
        assert await settle_bets(session) == 0
        await session.commit()
    assert (await _the_bet(db)).status == "won"


async def test_settle_without_result_stays_pending(tmp_path) -> None:
    db, match_id = await _db_with_result(tmp_path, home_score=2, away_score=1)
    await _add_bet(db, match_id, outcome="H")
    async with db.session_factory() as session:
        await session.execute(delete(Result).where(Result.match_id == match_id))
        await session.commit()
        assert await settle_bets(session) == 0
    assert (await _the_bet(db)).status == "pending"
