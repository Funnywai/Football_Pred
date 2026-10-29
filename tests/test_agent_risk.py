"""Deterministic risk-agent tests: selection rules, audit rows, API, and CLI."""

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from ml_helpers import make_db, seed_context, seed_finished_match, seed_team
from sqlalchemy import select

from app.agents.risk import evaluate_risk
from app.api.main import create_app
from app.cli import main
from app.config import Settings
from app.db.models import (
    AgentDecision,
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
EXEC_NO_H = {"lines": [{"combinations": [
    {"str": "D", "currentOdds": "3.4"}, {"str": "A", "currentOdds": "3.8"}]}]}
HAD_HIGH_A = {"lines": [{"combinations": [
    {"str": "H", "currentOdds": "1.5"}, {"str": "D", "currentOdds": "5.0"},
    {"str": "A", "currentOdds": "6.0"}]}]}


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


async def _seed_world(tmp_path, had_payload: dict | None = HAD) -> tuple:
    db = await make_db(tmp_path)
    async with db.session_factory() as session:
        league, season = await seed_context(session)
        home = await seed_team(session, "Home")
        away = await seed_team(session, "Away")
        match = await seed_finished_match(
            session, league, season, home, away,
            match_id_label="M1", kickoff=KICKOFF,
            home_score=2, away_score=1, had_payload=had_payload,
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


async def _run(db, settings: Settings | None = None):
    async with db.session_factory() as session:
        summary = await evaluate_risk(session, settings or _settings())
        await session.commit()
    return summary


async def _decisions(db) -> list[AgentDecision]:
    async with db.session_factory() as session:
        return (
            await session.execute(select(AgentDecision).order_by(AgentDecision.id))
        ).scalars().all()


async def _client(db) -> httpx.AsyncClient:
    app = create_app(settings=Settings(_env_file=None, enable_scheduler=False), db=db)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_one_bet_per_match_logs_all_three_candidates(tmp_path) -> None:
    db, match_id, version_id = await _seed_world(tmp_path)
    try:
        await _add_prediction(db, match_id, version_id, outcome="H", prob=0.52, edge=0.05)
        await _add_prediction(db, match_id, version_id, outcome="D", prob=0.38, edge=0.03)
        await _add_prediction(db, match_id, version_id, outcome="A", prob=0.37, edge=0.02)
        summary = await _run(db)
        assert summary.matches_considered == 1
        assert summary.candidates_evaluated == 3
        assert summary.bets_allowed == 1
        assert summary.no_bets == 2
        assert summary.total_stake == pytest.approx(41.0)
        rows = await _decisions(db)
        assert len(rows) == 3
        assert {row.outcome for row in rows} == {"H", "D", "A"}
        bet = next(row for row in rows if row.action == "bet")
        assert bet.outcome == "H"
        assert bet.stake == pytest.approx(
            float(int(1000 * kelly_fraction(0.52, 2.1) * 0.5))
        )
        assert {row.run_id for row in rows} == {summary.run_id}
        assert {row.agent for row in rows} == {"risk"}
        assert all(row.confidence is None for row in rows)
        assert all(
            {"model_probs", "market_odds", "market_probs", "execution_edge",
             "stake_fraction", "kickoff_time", "model_version_id", "evaluated_at"}
            <= row.input_snapshot.keys()
            for row in rows
        )
        assert all(
            "one bet per match" in row.reason for row in rows if row.action == "no_bet"
        )
    finally:
        await db.dispose()


async def test_highest_eligible_candidate_wins_after_higher_edge_rejected(tmp_path) -> None:
    db, match_id, version_id = await _seed_world(tmp_path)
    try:
        await _add_prediction(db, match_id, version_id, outcome="A", prob=0.20, edge=0.30)
        await _add_prediction(db, match_id, version_id, outcome="D", prob=0.38, edge=0.10)
        await _add_prediction(db, match_id, version_id, outcome="H", prob=0.52, edge=0.05)
        summary = await _run(db)
        assert summary.bets_allowed == 1
        rows = await _decisions(db)
        bet = next(row for row in rows if row.action == "bet")
        assert bet.outcome == "D"
        rejected = next(row for row in rows if row.outcome == "A")
        assert rejected.action == "no_bet"
        assert "execution edge" in rejected.reason
        assert next(row for row in rows if row.outcome == "H").action == "no_bet"
    finally:
        await db.dispose()


@pytest.mark.parametrize(
    ("had_payload", "outcome", "prob", "reason"),
    [
        (None, "H", 0.52, "no pre-kickoff HKJC HAD price"),
        (EXEC_NO_H, "H", 0.52, "HKJC HAD price"),
        (HAD, "H", 0.46, "execution edge"),
        (HAD, "A", 0.258, "kelly fraction"),
        (HAD_HIGH_A, "A", 0.20, "above agent max"),
        (HAD, "H", 0.480, "stake below minimum"),
    ],
)
async def test_rule_rejection_logs_no_bet(
    tmp_path, had_payload: dict | None, outcome: str, prob: float, reason: str
) -> None:
    db, match_id, version_id = await _seed_world(tmp_path, had_payload=had_payload)
    try:
        await _add_prediction(db, match_id, version_id, outcome=outcome, prob=prob, edge=0.05)
        summary = await _run(db)
        assert summary.bets_allowed == 0
        assert summary.no_bets == 1
        row = (await _decisions(db))[0]
        assert row.action == "no_bet"
        assert reason in row.reason
        assert row.stake is None
    finally:
        await db.dispose()


async def test_agent_never_writes_ledger_tables(tmp_path) -> None:
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
        summary = await _run(db)
        assert summary.bets_allowed == 1
        async with db.session_factory() as session:
            production = (await session.execute(select(LedgerBet))).scalars().all()
            shadow = (await session.execute(select(ShadowLedgerBet))).scalars().all()
        assert [(bet.outcome, bet.stake) for bet in production] == [("A", 20.0)]
        assert [(bet.outcome, bet.stake) for bet in shadow] == [("D", 15.0)]
        assert len(await _decisions(db)) == 1
    finally:
        await db.dispose()


async def test_api_filters_and_order(tmp_path) -> None:
    db, match_id, version_id = await _seed_world(tmp_path)
    try:
        await _add_prediction(db, match_id, version_id, outcome="H", prob=0.52, edge=0.05)
        await _add_prediction(db, match_id, version_id, outcome="D", prob=0.38, edge=0.03)
        await _add_prediction(db, match_id, version_id, outcome="A", prob=0.37, edge=0.02)
        await _run(db)
        client = await _client(db)
        try:
            response = await client.get("/agent/decisions")
            assert response.status_code == 200
            rows = response.json()
            assert len(rows) == 3
            assert rows == sorted(rows, key=lambda row: row["id"], reverse=True)
            assert len((await client.get("/agent/decisions?action=bet")).json()) == 1
            assert len((await client.get("/agent/decisions?action=no_bet")).json()) == 2
            assert len((await client.get(f"/agent/decisions?match_id={match_id}")).json()) == 3
            assert (await client.get("/agent/decisions?match_id=999")).json() == []
            assert len((await client.get("/agent/decisions?agent=risk")).json()) == 3
            assert (await client.get("/agent/decisions?agent=other")).json() == []
            assert len((await client.get("/agent/decisions?limit=1")).json()) == 1
            assert (await client.get("/agent/decisions?limit=0")).status_code == 422
            assert (await client.get("/agent/decisions?limit=501")).status_code == 422
            assert {row["league_code"] for row in rows} == {"EPL"}
            assert {row["home_team"] for row in rows} == {"Home"}
            assert {row["away_team"] for row in rows} == {"Away"}
        finally:
            await client.aclose()
    finally:
        await db.dispose()


async def test_api_default_limit_is_100(tmp_path) -> None:
    db, match_id, version_id = await _seed_world(tmp_path)
    try:
        now = datetime.now(UTC)
        async with db.session_factory() as session:
            session.add_all(
                [
                    AgentDecision(
                        run_id=f"run-{index}", match_id=match_id,
                        model_version_id=version_id, target="1x2", outcome="H",
                        action="no_bet", reason="bulk", input_snapshot={},
                        evaluated_at=now,
                    )
                    for index in range(120)
                ]
            )
            await session.commit()
        client = await _client(db)
        try:
            assert len((await client.get("/agent/decisions")).json()) == 100
            assert len((await client.get("/agent/decisions?limit=500")).json()) == 120
        finally:
            await client.aclose()
    finally:
        await db.dispose()


def test_cli_agent_evaluate_smoke(
    tmp_path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = asyncio.run(make_db(tmp_path))
    try:
        monkeypatch.setattr("app.cli.Database", lambda _url: db)
        monkeypatch.setattr("app.cli.get_settings", lambda: _settings())
        main(["agent-evaluate"])
        out = capsys.readouterr().out
        assert "agent-evaluate complete: run_id=" in out
        assert "matches=0 candidates=0 bets=0 no_bets=0 total_stake=0" in out

        async def _count() -> int:
            async with db.session_factory() as session:
                return len((await session.execute(select(AgentDecision))).scalars().all())

        assert asyncio.run(_count()) == 0
    finally:
        asyncio.run(db.dispose())
