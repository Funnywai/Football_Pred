"""Paper-only agent ledger tests (Phase 2a): placement, settlement, API, CLI."""

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from ml_helpers import make_db, seed_context, seed_finished_match, seed_team
from sqlalchemy import select

from app.agents.ledger import (
    AGENT_LEDGER_JOB_ID,
    agent_bankroll_now,
    agent_equity_curve,
    agent_ledger_update,
    agent_summary,
    place_agent_bets,
)
from app.agents.risk import evaluate_risk
from app.api.main import create_app
from app.cli import main
from app.config import Settings
from app.db.models import (
    AgentBet,
    AgentDecision,
    IngestionRun,
    LedgerBet,
    ModelVersion,
    Prediction,
    ShadowLedgerBet,
)
from app.ml.value import kelly_fraction

KICKOFF = datetime.now(UTC) + timedelta(days=30)

HAD = {"lines": [{"combinations": [
    {"str": "H", "currentOdds": "2.1"}, {"str": "D", "currentOdds": "3.4"},
    {"str": "A", "currentOdds": "3.8"}]}]}


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


async def _seed_world(tmp_path) -> tuple:
    """Future-kickoff match (2:1 confirmed result) + champion; returns (db, match_id, version_id)."""
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
    db, match_id: int, version_id: int, *, outcome: str, prob: float, edge: float
) -> None:
    async with db.session_factory() as session:
        session.add(
            Prediction(
                match_id=match_id, target="1x2", outcome=outcome,
                model_version_id=version_id, prob=prob, implied_prob=0.45,
                edge=edge, fair_odds=1.0 / prob, market_odds=2.1,
                recommended_fraction=0.0,
            )
        )
        await session.commit()


async def _evaluate(db, settings: Settings | None = None):
    async with db.session_factory() as session:
        result = await evaluate_risk(session, settings or _settings())
        await session.commit()
    return result


async def _place(db, run_id: str, variant: str = "a_only") -> int:
    async with db.session_factory() as session:
        placed = await place_agent_bets(session, _settings(), run_id, variant)
        await session.commit()
    return placed


async def _bets(db) -> list[AgentBet]:
    async with db.session_factory() as session:
        return (
            await session.execute(select(AgentBet).order_by(AgentBet.id))
        ).scalars().all()


async def _client(db) -> httpx.AsyncClient:
    app = create_app(settings=Settings(_env_file=None, enable_scheduler=False), db=db)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_place_agent_bets_locks_decision_values(tmp_path) -> None:
    db, match_id, version_id = await _seed_world(tmp_path)
    try:
        await _add_prediction(db, match_id, version_id, outcome="H", prob=0.52, edge=0.05)
        await _add_prediction(db, match_id, version_id, outcome="D", prob=0.38, edge=0.03)
        await _add_prediction(db, match_id, version_id, outcome="A", prob=0.37, edge=0.02)
        risk = await _evaluate(db)
        assert await _place(db, risk.run_id) == 1

        async with db.session_factory() as session:
            decision = (
                await session.execute(
                    select(AgentDecision).where(AgentDecision.action == "bet")
                )
            ).scalar_one()
        bets = await _bets(db)
        assert len(bets) == 1
        bet = bets[0]
        assert bet.run_id == risk.run_id
        assert bet.match_id == match_id
        assert bet.model_version_id == version_id
        assert bet.target == "1x2"
        assert bet.outcome == decision.outcome == "H"
        assert bet.variant == "a_only"
        assert bet.line is None
        assert bet.odds == pytest.approx(decision.odds)
        assert bet.stake == pytest.approx(decision.stake)
        assert bet.stake == pytest.approx(
            float(int(1000 * kelly_fraction(0.52, 2.1) * 0.5))
        )
        assert bet.edge == pytest.approx(decision.edge)
        assert bet.kelly_multiplier == pytest.approx(0.5)
        assert bet.bankroll_at_place == pytest.approx(1000.0)
        assert bet.status == "pending"
        assert bet.settled_at is None
        assert bet.payout is None
        assert bet.profit is None

        async with db.session_factory() as session:
            assert (await session.execute(select(AgentDecision))).scalars().all()
            assert (await session.execute(select(LedgerBet))).scalars().all() == []
            assert (await session.execute(select(ShadowLedgerBet))).scalars().all() == []
    finally:
        await db.dispose()


async def test_one_bet_per_match_and_variant_and_idempotent(tmp_path) -> None:
    db, match_id, version_id = await _seed_world(tmp_path)
    try:
        await _add_prediction(db, match_id, version_id, outcome="H", prob=0.52, edge=0.05)
        risk = await _evaluate(db)
        assert await _place(db, risk.run_id, "a_only") == 1
        assert await _place(db, risk.run_id, "a_only") == 0
        async with db.session_factory() as session:
            session.add(
                AgentDecision(
                    run_id=risk.run_id,
                    match_id=match_id,
                    model_version_id=version_id,
                    target="1x2",
                    outcome="H",
                    action="bet",
                    stake=10.0,
                    odds=2.1,
                    edge=0.05,
                    agent="decision",
                    reason="approved",
                    input_snapshot={},
                )
            )
            await session.commit()
        assert await _place(db, risk.run_id, "abc") == 1
        assert await _place(db, risk.run_id, "abc") == 0

        bets = await _bets(db)
        assert len(bets) == 2
        assert [(bet.variant, bet.match_id) for bet in bets] == [
            ("a_only", match_id),
            ("abc", match_id),
        ]
        assert {bet.run_id for bet in bets} == {risk.run_id}
    finally:
        await db.dispose()


async def test_agent_ledger_update_settles_confirmed_results_and_tracks_job(tmp_path) -> None:
    db, match_id, version_id = await _seed_world(tmp_path)
    try:
        await _add_prediction(db, match_id, version_id, outcome="H", prob=0.52, edge=0.05)
        settings = _settings()
        assert await agent_ledger_update(db.session_factory, settings) == 1
        assert await agent_ledger_update(db.session_factory, settings) == 1

        bets = await _bets(db)
        assert len(bets) == 1
        bet = bets[0]
        stake = float(int(1000 * kelly_fraction(0.52, 2.1) * 0.5))
        assert bet.status == "won"
        assert bet.stake == pytest.approx(stake)
        assert bet.payout == pytest.approx(stake * 2.1)
        assert bet.profit == pytest.approx(stake * 2.1 - stake)
        assert bet.result_source == "hkjc"
        assert bet.settled_at is not None

        async with db.session_factory() as session:
            assert await agent_bankroll_now(session, settings, "a_only") == pytest.approx(
                1000.0 + stake * 2.1 - stake
            )
            runs = (
                await session.execute(
                    select(IngestionRun).where(IngestionRun.job == AGENT_LEDGER_JOB_ID)
                )
            ).scalars().all()
            assert len(runs) == 2
            assert {run.status for run in runs} == {"success"}
            assert [run.records_upserted for run in runs] == [1, 1]
            decision_runs = {
                row.run_id
                for row in (await session.execute(select(AgentDecision))).scalars().all()
            }
            assert len(decision_runs) == 2
    finally:
        await db.dispose()


async def test_agent_summary_and_equity_curve_are_variant_scoped(tmp_path) -> None:
    db, match_id, version_id = await _seed_world(tmp_path)
    try:
        await _add_prediction(db, match_id, version_id, outcome="H", prob=0.52, edge=0.05)
        settings = _settings()
        assert await agent_ledger_update(db.session_factory, settings) == 1
        assert await agent_ledger_update(db.session_factory, settings) == 1

        async with db.session_factory() as session:
            session.add(
                AgentBet(
                    run_id="abc-run", match_id=match_id, model_version_id=version_id,
                    target="1x2", outcome="A", variant="abc", odds=3.8, stake=50.0,
                    bankroll_at_place=1000.0, kelly_multiplier=0.5,
                )
            )
            await session.commit()

        stake = float(int(1000 * kelly_fraction(0.52, 2.1) * 0.5))
        profit = stake * 2.1 - stake
        async with db.session_factory() as session:
            a_only = await agent_summary(session, settings, "a_only")
            abc = await agent_summary(session, settings, "abc")
            a_curve = await agent_equity_curve(session, settings, "a_only")
            abc_curve = await agent_equity_curve(session, settings, "abc")
            assert await agent_bankroll_now(session, settings, "a_only") == pytest.approx(
                1000.0 + profit
            )
            assert await agent_bankroll_now(session, settings, "abc") == pytest.approx(950.0)

        assert a_only.n_bets == 1
        assert a_only.n_settled == 1
        assert a_only.n_open == 0
        assert a_only.realized_profit == pytest.approx(profit)
        assert a_only.bankroll == pytest.approx(1000.0 + profit)
        assert a_only.roi == pytest.approx(profit / stake)

        assert abc.n_bets == 1
        assert abc.n_settled == 0
        assert abc.n_open == 1
        assert abc.open_stakes == pytest.approx(50.0)
        assert abc.bankroll == pytest.approx(950.0)

        assert len(a_curve) == 3
        assert a_curve[0].bankroll == pytest.approx(1000.0)
        assert a_curve[-1].bankroll == pytest.approx(1000.0 + profit)
        assert len(abc_curve) == 2
        assert abc_curve[-1].bankroll == pytest.approx(950.0)
    finally:
        await db.dispose()


async def test_agent_api_default_variant_filters_and_rejects_invalid(tmp_path) -> None:
    db, match_id, version_id = await _seed_world(tmp_path)
    try:
        await _add_prediction(db, match_id, version_id, outcome="H", prob=0.52, edge=0.05)
        risk = await _evaluate(db)
        assert await _place(db, risk.run_id, "a_only") == 1
        async with db.session_factory() as session:
            session.add(
                AgentBet(
                    run_id="abc-run", match_id=match_id, model_version_id=version_id,
                    target="1x2", outcome="A", variant="abc", odds=3.8, stake=50.0,
                    bankroll_at_place=1000.0, kelly_multiplier=0.5,
                )
            )
            await session.commit()
        client = await _client(db)
        try:
            default = (await client.get("/agent/bets")).json()
            assert len(default) == 1
            assert default[0]["stake"] == pytest.approx(
                float(int(1000 * kelly_fraction(0.52, 2.1) * 0.5))
            )
            assert default[0]["home_team"] == "Home"
            assert default[0]["away_team"] == "Away"
            assert default[0]["status"] == "pending"
            assert "variant" not in default[0]

            abc = (await client.get("/agent/bets", params={"variant": "abc"})).json()
            assert len(abc) == 1
            assert abc[0]["outcome"] == "A"
            assert abc[0]["stake"] == pytest.approx(50.0)

            assert (
                await client.get("/agent/bets", params={"status": "won"})
            ).json() == []
            assert len(
                (await client.get("/agent/bets", params={"match_id": match_id})).json()
            ) == 1
            assert (
                await client.get("/agent/bets", params={"match_id": 999})
            ).json() == []
            assert len((await client.get("/agent/bets", params={"limit": 1})).json()) == 1
            assert (await client.get("/agent/bets", params={"limit": 0})).status_code == 422

            summary = (await client.get("/agent/summary")).json()
            assert summary["n_bets"] == 1
            assert summary["open_stakes"] == pytest.approx(
                float(int(1000 * kelly_fraction(0.52, 2.1) * 0.5))
            )
            abc_summary = (
                await client.get("/agent/summary", params={"variant": "abc"})
            ).json()
            assert abc_summary["n_bets"] == 1
            assert abc_summary["open_stakes"] == pytest.approx(50.0)

            curve = (await client.get("/agent/equity-curve")).json()
            assert len(curve) == 2
            assert curve[0]["bankroll"] == pytest.approx(1000.0)
            assert curve[-1]["bankroll"] == pytest.approx(
                1000.0 - float(int(1000 * kelly_fraction(0.52, 2.1) * 0.5))
            )

            for endpoint in ("/agent/bets", "/agent/summary", "/agent/equity-curve"):
                invalid = await client.get(endpoint, params={"variant": "nope"})
                assert invalid.status_code == 422
        finally:
            await client.aclose()
    finally:
        await db.dispose()


async def test_agent_decisions_include_match_context(tmp_path) -> None:
    db, match_id, version_id = await _seed_world(tmp_path)
    try:
        await _add_prediction(db, match_id, version_id, outcome="H", prob=0.52, edge=0.05)
        await _evaluate(db)
        client = await _client(db)
        try:
            rows = (await client.get("/agent/decisions")).json()
            assert len(rows) == 1
            row = rows[0]
            assert row["league_code"] == "EPL"
            assert row["home_team"] == "Home"
            assert row["away_team"] == "Away"
            assert row["agent"] == "risk"
            assert row["action"] == "bet"
            assert "input_snapshot" in row
        finally:
            await client.aclose()
    finally:
        await db.dispose()


async def test_agent_ledger_never_writes_production_or_shadow(tmp_path) -> None:
    db, match_id, version_id = await _seed_world(tmp_path)
    try:
        async with db.session_factory() as session:
            session.add(
                LedgerBet(
                    match_id=match_id, target="1x2", outcome="A",
                    model_version_id=version_id, odds=3.8, stake=20.0,
                    bankroll_at_place=1000.0, kelly_multiplier=0.5,
                )
            )
            session.add(
                ShadowLedgerBet(
                    match_id=match_id, target="1x2", outcome="D",
                    model_version_id=version_id, odds=3.4, stake=15.0,
                    bankroll_at_place=1000.0, kelly_multiplier=0.5,
                )
            )
            await session.commit()
        await _add_prediction(db, match_id, version_id, outcome="H", prob=0.52, edge=0.05)
        risk = await _evaluate(db)
        assert await _place(db, risk.run_id) == 1
        async with db.session_factory() as session:
            production = (await session.execute(select(LedgerBet))).scalars().all()
            shadow = (await session.execute(select(ShadowLedgerBet))).scalars().all()
        assert [(bet.outcome, bet.stake) for bet in production] == [("A", 20.0)]
        assert [(bet.outcome, bet.stake) for bet in shadow] == [("D", 15.0)]
        assert len(await _bets(db)) == 1
    finally:
        await db.dispose()


def test_cli_agent_ledger_smoke(
    tmp_path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = asyncio.run(make_db(tmp_path))
    try:
        monkeypatch.setattr("app.cli.Database", lambda _url: db)
        monkeypatch.setattr("app.cli.get_settings", lambda: _settings())
        main(["agent-ledger"])
        out = capsys.readouterr().out
        assert "agent-ledger complete: run recorded as agent_ledger_update" in out
        assert "agent book (a_only): bets=0 settled=0 open=0 bankroll=1000.00" in out

        async def _runs() -> list[IngestionRun]:
            async with db.session_factory() as session:
                return (
                    await session.execute(
                        select(IngestionRun).where(IngestionRun.job == AGENT_LEDGER_JOB_ID)
                    )
                ).scalars().all()

        runs = asyncio.run(_runs())
        assert len(runs) == 1
        assert runs[0].status == "success"
    finally:
        asyncio.run(db.dispose())
