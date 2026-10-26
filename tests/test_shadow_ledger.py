"""Shadow paper ledger tests: selection rule, isolation, and derived bankroll."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from ml_helpers import make_db, seed_context, seed_finished_match, seed_team
from sqlalchemy import delete, select

from app.cli import main
from app.config import Settings
from app.db.models import (
    IngestionRun,
    LedgerBet,
    Match,
    ModelVersion,
    OddsSnapshot,
    Prediction,
    Result,
    ShadowLedgerBet,
)
from app.services.ledger import (
    equity_curve,
    place_shadow_bets,
    settle_bets,
    shadow_ledger_update,
)
from app.services.ledger import summary as ledger_summary

KICKOFF = datetime.now(UTC) + timedelta(days=30)

HAD = {"lines": [{"combinations": [
    {"str": "H", "currentOdds": "2.1"}, {"str": "D", "currentOdds": "3.4"},
    {"str": "A", "currentOdds": "3.8"}]}]}
EXEC_NO_H = {"lines": [{"combinations": [
    {"str": "D", "currentOdds": "3.4"}, {"str": "A", "currentOdds": "3.8"}]}]}


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


async def _seed_shadow_world(tmp_path) -> tuple:
    """A future match with a champion and a valid HKJC HAD snapshot."""
    db = await make_db(tmp_path)
    async with db.session_factory() as session:
        league, season = await seed_context(session)
        home = await seed_team(session, "Home")
        away = await seed_team(session, "Away")
        match = await seed_finished_match(
            session, league, season, home, away,
            match_id_label="M1", kickoff=KICKOFF,
            home_score=2, away_score=1, had_payload=HAD,
        )
        version = ModelVersion(
            target="1x2", algorithm="lightgbm", params={}, metrics={},
            artifact_path="/tmp/m1.joblib", status="champion",
        )
        session.add(version)
        await session.commit()
        return db, match.id, version.id


async def _add_prediction(
    db,
    match_id: int,
    version_id: int,
    *,
    outcome: str,
    prob: float,
    edge: float,
    recommended_fraction: float = 0.0,
) -> None:
    async with db.session_factory() as session:
        session.add(
            Prediction(
                match_id=match_id, target="1x2", outcome=outcome,
                model_version_id=version_id, prob=prob, implied_prob=0.45,
                edge=edge, fair_odds=1.0 / prob, market_odds=2.1,
                recommended_fraction=recommended_fraction,
            )
        )
        await session.commit()


async def _add_exec_snapshot(db, match_id: int, payload: dict) -> None:
    """A fresher HKJC HAD snapshot captured shortly before kickoff."""
    async with db.session_factory() as session:
        kickoff = (
            await session.execute(select(Match.kickoff_time).where(Match.id == match_id))
        ).scalar_one()
        captured = kickoff - timedelta(hours=2)
        session.add(
            OddsSnapshot(
                match_id=match_id,
                captured_at=captured,
                snapshot_bucket=captured,
                source="hkjc",
                inplay=False,
                odds_type="HAD",
                payload=payload,
            )
        )
        await session.commit()


async def _add_shadow_bet(
    db,
    match_id: int,
    version_id: int,
    *,
    outcome: str = "H",
    odds: float = 2.1,
    stake: float = 10.0,
    status: str = "pending",
    profit: float | None = None,
) -> None:
    now = datetime.now(UTC)
    async with db.session_factory() as session:
        session.add(
            ShadowLedgerBet(
                match_id=match_id, target="1x2", outcome=outcome,
                model_version_id=version_id, odds=odds, stake=stake,
                bankroll_at_place=1000.0, kelly_multiplier=0.5,
                status=status, payout=None if profit is None else stake + profit,
                profit=profit, settled_at=None if status == "pending" else now,
            )
        )
        await session.commit()


async def _shadow_bets(db) -> list[ShadowLedgerBet]:
    async with db.session_factory() as session:
        return (await session.execute(select(ShadowLedgerBet))).scalars().all()


async def test_places_one_bet_per_match_highest_positive_signal_edge(tmp_path) -> None:
    db, match_id, version_id = await _seed_shadow_world(tmp_path)
    try:
        await _add_prediction(db, match_id, version_id, outcome="H", prob=0.52, edge=0.05)
        await _add_prediction(db, match_id, version_id, outcome="D", prob=0.38, edge=0.10)
        await _add_prediction(db, match_id, version_id, outcome="A", prob=0.37, edge=0.12)
        async with db.session_factory() as session:
            assert await place_shadow_bets(session, _settings()) == 1
            await session.commit()
        bets = await _shadow_bets(db)
        assert len(bets) == 1
        assert bets[0].outcome == "A"
        assert bets[0].status == "pending"
    finally:
        await db.dispose()


async def test_ignores_candidates_with_non_positive_signal_edge(tmp_path) -> None:
    db, match_id, version_id = await _seed_shadow_world(tmp_path)
    try:
        await _add_prediction(db, match_id, version_id, outcome="H", prob=0.52, edge=0.0)
        await _add_prediction(db, match_id, version_id, outcome="D", prob=0.38, edge=-0.01)
        async with db.session_factory() as session:
            assert await place_shadow_bets(session, _settings()) == 0
        assert await _shadow_bets(db) == []
    finally:
        await db.dispose()


async def test_skips_negative_execution_kelly_and_bets_next_candidate(tmp_path) -> None:
    db, match_id, version_id = await _seed_shadow_world(tmp_path)
    try:
        # Highest signal edge, but the execution price makes Kelly zero.
        await _add_prediction(db, match_id, version_id, outcome="A", prob=0.20, edge=0.30)
        # Lower signal edge but still positive Kelly at the executable price.
        await _add_prediction(db, match_id, version_id, outcome="H", prob=0.52, edge=0.05)
        async with db.session_factory() as session:
            assert await place_shadow_bets(session, _settings()) == 1
            await session.commit()
        bets = await _shadow_bets(db)
        assert [bet.outcome for bet in bets] == ["H"]
    finally:
        await db.dispose()


async def test_no_bet_without_a_pre_kickoff_hkjc_price(tmp_path) -> None:
    db, match_id, version_id = await _seed_shadow_world(tmp_path)
    try:
        async with db.session_factory() as session:
            await session.execute(delete(OddsSnapshot).where(OddsSnapshot.odds_type == "HAD"))
            await session.commit()
        await _add_prediction(db, match_id, version_id, outcome="H", prob=0.52, edge=0.05)
        async with db.session_factory() as session:
            assert await place_shadow_bets(session, _settings()) == 0
        assert await _shadow_bets(db) == []
    finally:
        await db.dispose()


async def test_no_bet_when_latest_snapshot_lacks_the_outcome(tmp_path) -> None:
    db, match_id, version_id = await _seed_shadow_world(tmp_path)
    try:
        await _add_exec_snapshot(db, match_id, EXEC_NO_H)
        await _add_prediction(db, match_id, version_id, outcome="H", prob=0.52, edge=0.05)
        async with db.session_factory() as session:
            assert await place_shadow_bets(session, _settings()) == 0
        assert await _shadow_bets(db) == []
    finally:
        await db.dispose()


async def test_stake_uses_shadow_only_bankroll_and_production_rules(tmp_path) -> None:
    db, match_id, version_id = await _seed_shadow_world(tmp_path)
    try:
        async with db.session_factory() as session:
            league, season = await seed_context(session, code="L2")
            home = await seed_team(session, "PrevHome")
            away = await seed_team(session, "PrevAway")
            settled_match = await seed_finished_match(
                session, league, season, home, away,
                match_id_label="P1", kickoff=datetime.now(UTC) - timedelta(days=5),
                home_score=1, away_score=0,
            )
            open_match = await seed_finished_match(
                session, league, season, home, away,
                match_id_label="P2", kickoff=datetime.now(UTC) - timedelta(days=4),
                home_score=0, away_score=1,
            )
            await session.commit()
            settled_match_id = settled_match.id
            open_match_id = open_match.id
        await _add_shadow_bet(
            db, settled_match_id, version_id, status="won", stake=10.0, profit=100.0
        )
        await _add_shadow_bet(
            db, open_match_id, version_id, status="pending", stake=20.0
        )
        await _add_prediction(db, match_id, version_id, outcome="H", prob=0.52, edge=0.05)
        async with db.session_factory() as session:
            assert await place_shadow_bets(session, _settings()) == 1
            await session.commit()
        placed = next(bet for bet in await _shadow_bets(db) if bet.match_id == match_id)
        # Derived from shadow rows only: 1000 + 100 settled profit − 20 open stake.
        assert placed.bankroll_at_place == pytest.approx(1080.0)
        # floor(1080 × kelly(0.52, 2.1) × 0.5) = floor(45.16) = 45
        assert placed.stake == pytest.approx(45.0)
        assert placed.kelly_multiplier == pytest.approx(0.5)
        assert placed.odds == pytest.approx(2.1)
    finally:
        await db.dispose()


async def test_shadow_settlement_never_touches_production_bets(tmp_path) -> None:
    db, match_id, version_id = await _seed_shadow_world(tmp_path)
    try:
        await _add_shadow_bet(db, match_id, version_id, outcome="H", stake=10.0)
        async with db.session_factory() as session:
            session.add(
                LedgerBet(
                    match_id=match_id, target="1x2", outcome="H",
                    model_version_id=version_id, odds=2.1, stake=15.0,
                    bankroll_at_place=1000.0, kelly_multiplier=0.5,
                )
            )
            await session.commit()
        async with db.session_factory() as session:
            result = (
                await session.execute(
                    select(Result).where(Result.match_id == match_id)
                )
            ).scalar_one()
            result.confirmed = False
            await session.commit()
        async with db.session_factory() as session:
            assert await settle_bets(session, ShadowLedgerBet) == 0
            await session.commit()
        async with db.session_factory() as session:
            result = (
                await session.execute(
                    select(Result).where(Result.match_id == match_id)
                )
            ).scalar_one()
            result.confirmed = True
            await session.commit()
        async with db.session_factory() as session:
            assert await settle_bets(session, ShadowLedgerBet) == 1
            await session.commit()
        shadow = (await _shadow_bets(db))[0]
        assert shadow.status == "won"
        assert shadow.result_source == "hkjc"
        async with db.session_factory() as session:
            production = (await session.execute(select(LedgerBet))).scalars().all()
        assert [bet.status for bet in production] == ["pending"]
    finally:
        await db.dispose()


async def test_summary_and_equity_curve_are_book_scoped(tmp_path) -> None:
    db, match_id, version_id = await _seed_shadow_world(tmp_path)
    try:
        async with db.session_factory() as session:
            league, season = await seed_context(session, code="L2")
            home = await seed_team(session, "OtherHome")
            away = await seed_team(session, "OtherAway")
            other = await seed_finished_match(
                session, league, season, home, away,
                match_id_label="O1", kickoff=datetime.now(UTC) - timedelta(days=3),
                home_score=1, away_score=1,
            )
            session.add(
                LedgerBet(
                    match_id=match_id, target="1x2", outcome="H",
                    model_version_id=version_id, odds=2.1, stake=10.0,
                    bankroll_at_place=1000.0, kelly_multiplier=0.5,
                    status="won", payout=20.0, profit=10.0,
                    settled_at=datetime.now(UTC),
                )
            )
            await session.commit()
            other_id = other.id
        await _add_shadow_bet(
            db, other_id, version_id, status="won", stake=10.0, profit=20.0
        )
        settings = _settings()
        async with db.session_factory() as session:
            production = await ledger_summary(session, settings)
            shadow = await ledger_summary(session, settings, ShadowLedgerBet)
            production_curve = await equity_curve(session, settings)
            shadow_curve = await equity_curve(session, settings, ShadowLedgerBet)
        assert production.n_bets == 1 and production.realized_profit == pytest.approx(10.0)
        assert production.bankroll == pytest.approx(1010.0)
        assert shadow.n_bets == 1 and shadow.realized_profit == pytest.approx(20.0)
        assert shadow.bankroll == pytest.approx(1020.0)
        assert production_curve[-1].bankroll == pytest.approx(1010.0)
        assert shadow_curve[-1].bankroll == pytest.approx(1020.0)
    finally:
        await db.dispose()


async def test_shadow_ledger_update_tracks_job_and_leaves_production_alone(tmp_path) -> None:
    db, match_id, version_id = await _seed_shadow_world(tmp_path)
    try:
        await _add_prediction(db, match_id, version_id, outcome="H", prob=0.52, edge=0.05)
        async with db.session_factory() as session:
            session.add(
                LedgerBet(
                    match_id=match_id, target="1x2", outcome="A",
                    model_version_id=version_id, odds=3.8, stake=15.0,
                    bankroll_at_place=1000.0, kelly_multiplier=0.5,
                )
            )
            await session.commit()
        processed = await shadow_ledger_update(db.session_factory, _settings())
        assert processed == 1
        assert len(await _shadow_bets(db)) == 1
        async with db.session_factory() as session:
            runs = (await session.execute(select(IngestionRun))).scalars().all()
            production = (await session.execute(select(LedgerBet))).scalars().all()
        assert [run.job for run in runs] == ["shadow_ledger_update"]
        assert runs[0].records_upserted == 1
        assert [bet.status for bet in production] == ["pending"]
    finally:
        await db.dispose()


def test_cli_shadow_ledger_runs_one_cycle(
    tmp_path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = asyncio.run(make_db(tmp_path))
    try:
        monkeypatch.setattr("app.cli.Database", lambda _url: db)
        monkeypatch.setattr("app.cli.get_settings", lambda: _settings())
        main(["shadow-ledger"])
        out = capsys.readouterr().out
        assert "shadow-ledger complete: 0 bet(s) settled or placed" in out

        async def _jobs() -> list[str]:
            async with db.session_factory() as session:
                rows = (await session.execute(select(IngestionRun))).scalars().all()
                return [row.job for row in rows]

        assert asyncio.run(_jobs()) == ["shadow_ledger_update"]
    finally:
        asyncio.run(db.dispose())
