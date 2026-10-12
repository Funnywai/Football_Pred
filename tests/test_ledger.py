"""Paper ledger tests: settlement, placement, and read-time math (sub-system C)."""

from datetime import UTC, datetime, timedelta

import pytest
from ml_helpers import make_db, seed_context, seed_finished_match, seed_team
from sqlalchemy import delete, select

from app.config import Settings
from app.db.models import LedgerBet, ModelVersion, OddsSnapshot, Prediction, Result
from app.services.ledger import _size_stake, place_bets, settle_bets

KICKOFF = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)

HAD = {"lines": [{"combinations": [
    {"str": "H", "currentOdds": "2.1"}, {"str": "D", "currentOdds": "3.4"},
    {"str": "A", "currentOdds": "3.8"}]}]}
HDC = {"lines": [{"condition": "-0.5", "main": True, "combinations": [
    {"str": "H", "currentOdds": "2.0"}, {"str": "A", "currentOdds": "1.9"}]}]}


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


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_size_stake_fractional_kelly_and_cap() -> None:
    settings = _settings()
    # 6% fraction × 0.5 multiplier on HKD 1000 = HKD 30
    assert _size_stake(1000.0, 0.06, settings) == pytest.approx(30.0)
    # rounding to 2dp: 1234 × 0.05 × 0.5 = 30.85
    assert _size_stake(1234.0, 0.05, settings) == pytest.approx(30.85)
    # cap is downward-only: 25% × 0.5 = 125 > cap 50 → capped at 50
    assert _size_stake(1000.0, 0.25, settings) == pytest.approx(50.0)
    # below the HKD 10 minimum → skipped (never raised to the minimum)
    assert _size_stake(1000.0, 0.01, settings) is None
    # cap itself below the minimum (100 × 5% = 5) → skipped
    assert _size_stake(100.0, 0.6, settings) is None


async def _seed_matches_with_champion(tmp_path, *, n: int = 2) -> tuple:
    """n finished matches with HAD/HDC snapshots + one champion; return (db, match ids)."""
    db = await make_db(tmp_path)
    async with db.session_factory() as session:
        league, season = await seed_context(session)
        teams = [await seed_team(session, f"T{i}") for i in range(3)]
        match_ids = []
        for i in range(n):
            match = await seed_finished_match(
                session, league, season, teams[i % 3], teams[(i + 1) % 3],
                match_id_label=f"M{i}", kickoff=KICKOFF + timedelta(days=i),
                home_score=2, away_score=1, had_payload=HAD, hdc_payload=HDC,
            )
            match_ids.append(match.id)
        session.add(
            ModelVersion(
                target="1x2", algorithm="lightgbm", params={}, metrics={},
                artifact_path="/tmp/m1.joblib", status="champion",
            )
        )
        await session.commit()
    return db, match_ids


async def _champion_version_id(db) -> int:
    async with db.session_factory() as session:
        return (
            (await session.execute(select(ModelVersion))).scalar_one().id
        )


async def _add_prediction(
    db,
    match_id: int,
    version_id: int,
    *,
    target: str = "1x2",
    outcome: str = "H",
    market_odds: float = 2.1,
    fraction: float = 0.06,
    edge: float = 0.05,
) -> None:
    async with db.session_factory() as session:
        session.add(
            Prediction(
                match_id=match_id, target=target, outcome=outcome,
                model_version_id=version_id, prob=0.5, implied_prob=0.45,
                edge=edge, fair_odds=2.0, market_odds=market_odds,
                recommended_fraction=fraction,
            )
        )
        await session.commit()


async def test_place_sizes_and_locks_fields(tmp_path) -> None:
    db, match_ids = await _seed_matches_with_champion(tmp_path, n=1)
    version = await _champion_version_id(db)
    await _add_prediction(db, match_ids[0], version)
    async with db.session_factory() as session:
        assert await place_bets(session, _settings()) == 1
        await session.commit()
    bet = await _the_bet(db)
    assert bet.stake == pytest.approx(30.0)
    assert bet.odds == pytest.approx(2.1)
    assert bet.edge == pytest.approx(0.05)
    assert bet.kelly_multiplier == pytest.approx(0.5)
    assert bet.bankroll_at_place == pytest.approx(1000.0)
    assert bet.status == "pending"
    assert bet.model_version_id == version


async def test_place_handicap_locks_recomputed_line(tmp_path) -> None:
    db, match_ids = await _seed_matches_with_champion(tmp_path, n=1)
    version = await _champion_version_id(db)
    await _add_prediction(
        db, match_ids[0], version, target="handicap", outcome="A",
        market_odds=1.9, fraction=0.08,
    )
    async with db.session_factory() as session:
        assert await place_bets(session, _settings()) == 1
        await session.commit()
    bet = await _the_bet(db)
    assert bet.line == pytest.approx(-0.5)
    assert bet.odds == pytest.approx(1.9)


async def test_place_skips_handicap_without_line(tmp_path) -> None:
    db, match_ids = await _seed_matches_with_champion(tmp_path, n=1)
    version = await _champion_version_id(db)
    async with db.session_factory() as session:
        await session.execute(
            delete(OddsSnapshot).where(OddsSnapshot.odds_type == "HDC")
        )
        await session.commit()
    await _add_prediction(
        db, match_ids[0], version, target="handicap", outcome="A",
        market_odds=1.9, fraction=0.08,
    )
    async with db.session_factory() as session:
        assert await place_bets(session, _settings()) == 0
    async with db.session_factory() as session:
        rows = (await session.execute(select(LedgerBet))).scalars().all()
        assert rows == []


async def test_place_idempotent_and_non_champion_never_bet(tmp_path) -> None:
    db, match_ids = await _seed_matches_with_champion(tmp_path, n=2)
    version = await _champion_version_id(db)
    await _add_prediction(db, match_ids[0], version)
    await _add_prediction(db, match_ids[1], version)
    await _add_prediction(db, match_ids[0], version, outcome="D", fraction=0.0)
    async with db.session_factory() as session:
        session.add(
            ModelVersion(
                target="1x2", algorithm="lightgbm", params={}, metrics={},
                artifact_path="/tmp/m2.joblib", status="retired",
            )
        )
        await session.commit()
        retired_id = (
            (await session.execute(
                select(ModelVersion).where(ModelVersion.status == "retired")
            ))
            .scalar_one()
            .id
        )
    # a retired version's stale row on an already-bet key must not re-bet
    await _add_prediction(db, match_ids[0], retired_id)
    async with db.session_factory() as session:
        assert await place_bets(session, _settings()) == 2
        await session.commit()
        assert await place_bets(session, _settings()) == 0
