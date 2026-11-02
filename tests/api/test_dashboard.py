from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

import packages.db.models  # noqa: F401
from apps.api.main import create_app
from packages.db.base import Base
from packages.db.models import (
    BankrollAccount,
    CalibrationMetric,
    Competition,
    DecisionLog,
    MarketLine,
    Match,
    ModelPrediction,
    ModelVersion,
    OddsSnapshot,
    PaperBet,
    RawPayload,
    Settlement,
    SourceFetchRun,
    StrategyVersion,
    Team,
    WeightSnapshot,
)
from packages.domain.enums import (
    BetStatus,
    FetchRunStatus,
    MarketType,
    MatchStatus,
    SettlementSource,
    Side,
    SnapshotKind,
)
from packages.shared.config import Settings

D = Decimal
NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("FP_INITIAL_BANKROLL", "10000.00")
    database_path = tmp_path / "dashboard.db"
    settings = Settings(database_url=f"sqlite+pysqlite:///{database_path}")
    application = create_app(settings)
    Base.metadata.create_all(application.state.engine)
    yield application
    application.state.engine.dispose()


@pytest.fixture()
def client(app):
    return TestClient(app)


def _seed(app) -> dict[str, object]:
    session = app.state.session_factory()
    try:
        competition = Competition(
            code="EPL", name="Premier League", country="England", football_data_code="E0"
        )
        home = Team(slug="home-fc", name="Home FC", short_name="HOM", country="England")
        away = Team(slug="away-fc", name="Away FC", short_name="AWY", country="England")
        session.add_all([competition, home, away])
        session.flush()

        first_kickoff = NOW + timedelta(days=1)
        second_kickoff = NOW + timedelta(days=2)
        first = Match(
            competition_id=competition.id,
            season="2026/27",
            kickoff_at=first_kickoff,
            home_team_id=home.id,
            away_team_id=away.id,
            status=MatchStatus.SCHEDULED,
            source_match_ids={},
            coverage_flags=[],
        )
        second = Match(
            competition_id=competition.id,
            season="2026/27",
            kickoff_at=second_kickoff,
            home_team_id=away.id,
            away_team_id=home.id,
            status=MatchStatus.SCHEDULED,
            source_match_ids={},
            coverage_flags=[],
        )
        session.add_all([first, second])
        session.flush()

        decision_at = first_kickoff - timedelta(minutes=30)
        snapshot = OddsSnapshot(
            match_id=first.id,
            market=MarketType.HAD,
            snapshot_kind=SnapshotKind.T30M,
            snapshot_at=decision_at,
            query_version="test",
            payload_hash="hash-odds",
            run_id="run-odds",
        )
        session.add(snapshot)
        session.flush()
        for index, (side, odds) in enumerate(
            ((Side.H, "2.50"), (Side.D, "3.20"), (Side.A, "4.00"))
        ):
            session.add(
                MarketLine(
                    snapshot_id=snapshot.id,
                    odds_type=MarketType.HAD,
                    condition_raw="0.0",
                    line_index=index,
                    side=side,
                    odds_decimal=D(odds),
                    pool_status="SELLINGSTARTED",
                    line_status="AVAILABLE",
                    is_main=True,
                )
            )

        analysis_run_key = f"poisson-v1:{first.id}:T-30m"
        for side, probability in (
            (Side.H, "0.500000"),
            (Side.D, "0.300000"),
            (Side.A, "0.200000"),
        ):
            session.add(
                ModelPrediction(
                    match_id=first.id,
                    market=MarketType.HAD,
                    line_key="0.0",
                    outcome=side,
                    probability=D(probability),
                    score_distribution={},
                    decision_at=decision_at,
                    model_version="poisson-v1",
                    analysis_run_key=analysis_run_key,
                )
            )

        bet = PaperBet(
            match_id=first.id,
            market=MarketType.HAD,
            line_key="0.0",
            selection=Side.H,
            odds_decimal=D("2.50"),
            stake=D("100.00"),
            bankroll_before=D("10000.00"),
            placed_at=decision_at,
            status=BetStatus.WON,
            analysis_run_key=analysis_run_key,
            decision_slot_key=f"g1:{first.id}:T-30m",
            bet_intent_key=f"g1:{first.id}:T-30m:HAD:0.0:H",
            decision_at=decision_at,
        )
        session.add(bet)
        session.flush()

        session.add(
            DecisionLog(
                match_id=first.id,
                decision_slot_key=f"g1:{first.id}:T-30m",
                snapshot_id=snapshot.id,
                decision_at=decision_at,
                status="bet",
                reason="positive edge",
                model_version="poisson-v1",
                prediction_count=3,
                paper_bet_id=bet.id,
            )
        )
        session.add(
            Settlement(
                paper_bet_id=bet.id,
                result_status=BetStatus.WON,
                payout=D("250.00"),
                payout_unrounded=D("250.000000"),
                clv=D("0.050000"),
                brier_score=D("0.250000"),
                settled_at=first_kickoff + timedelta(hours=2),
                provisional=False,
                source=SettlementSource.HKJC_CONFIRMED,
            )
        )
        session.add(
            BankrollAccount(
                account_id="paper",
                currency="HKD",
                bankroll_balance=D("10150.00"),
                reserved_stake=D("0.00"),
            )
        )
        session.add(
            CalibrationMetric(
                model_version="poisson-v1",
                strategy_version="g1",
                competition="EPL",
                market="HAD",
                time_block="t-30m",
                sample_count=10,
                brier=D("0.210000"),
                log_loss=D("0.420000"),
                roi=D("0.150000"),
                clv=D("0.010000"),
                calibration=[],
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.add(
            SourceFetchRun(
                run_id="run-hkjc-1",
                source_name="hkjc",
                started_at=NOW - timedelta(minutes=5),
                finished_at=NOW,
                status=FetchRunStatus.SUCCEEDED,
                request_count=3,
                error_count=1,
                error_summary="timeout on one endpoint",
                params={},
            )
        )
        session.add(
            RawPayload(
                source_name="hkjc",
                source_url="https://example.test",
                fetched_at=NOW,
                schema_version="v1",
                payload_hash="hash-raw",
                body={},
            )
        )
        session.add(
            ModelVersion(
                version="poisson-v1",
                family="poisson",
                params={"window": 20},
                training_window={},
                validation_metrics={"brier": 0.2},
                status="active",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.add(
            StrategyVersion(
                version="g1",
                model_version="poisson-v1",
                policy_params={"min_edge": "0.03"},
                status="active",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.add(
            WeightSnapshot(
                strategy_version="g1",
                weights={"form": "0.5"},
                reason="initial",
                evaluation_period="2026-10",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.commit()
        return {"match_id": first.id, "bet_id": bet.id, "decision_at": decision_at}
    finally:
        session.close()


def test_overview_contract(app, client):
    seeded = _seed(app)
    response = client.get("/dashboard/overview")
    assert response.status_code == 200
    payload = response.json()

    assert payload["health"] == {
        "api": "ok",
        "database": "up",
        "redis": "not_configured",
    }
    assert payload["bankroll"] == {
        "initial": "10000.00",
        "balance": "10150.00",
        "reserved": "0.00",
        "available": "10150.00",
        "currency": "HKD",
    }
    assert D(payload["ledger"]["total_stake"]) == D("100.00")
    assert D(payload["ledger"]["total_payout"]) == D("250.00")
    assert D(payload["ledger"]["roi"]) == D("1.5")
    assert payload["ledger"]["settled_bets"] == 1
    assert payload["ledger"]["pending_bets"] == 0
    assert D(payload["ledger"]["max_drawdown"]) == D("0")

    assert payload["counts"] == {
        "matches": 2,
        "predictions": 3,
        "bets": 1,
        "settlements": 1,
        "decisions": 1,
    }
    assert next(
        fixture["match_id"] for fixture in payload["next_fixtures"]
    ) == str(seeded["match_id"])
    assert payload["next_fixtures"][0]["competition"] == "EPL"
    assert payload["next_fixtures"][0]["status"] == "scheduled"

    assert len(payload["latest_calibration"]) == 1
    metric = payload["latest_calibration"][0]
    assert metric["model_version"] == "poisson-v1"
    assert metric["strategy_version"] == "g1"
    assert metric["sample_count"] == 10
    assert D(metric["brier"]) == D("0.21")

    assert payload["latest_sources"] == [
        {
            "source_name": "hkjc",
            "status": "succeeded",
            "finished_at": payload["latest_sources"][0]["finished_at"],
            "error_count": 1,
        }
    ]
    assert payload["latest_sources"][0]["finished_at"] is not None


def test_predictions_contract(app, client):
    seeded = _seed(app)
    response = client.get("/dashboard/predictions?limit=50")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    row = payload[0]
    assert row["match_id"] == str(seeded["match_id"])
    assert row["competition"] == "EPL"
    assert float(row["probabilities"]["H"]) == 0.5
    assert float(row["probabilities"]["D"]) == 0.3
    assert float(row["probabilities"]["A"]) == 0.2
    assert float(row["odds"]["H"]) == 2.5
    assert float(row["ev"]["H"]) == pytest.approx(0.25)
    assert float(row["ev"]["D"]) == pytest.approx(0.3 * 3.2 - 1)
    assert row["model_version"] == "poisson-v1"
    assert row["decision_status"] == "bet"
    assert row["decision_reason"] == "positive edge"
    assert row["decision_at"]


def test_predictions_missing_decision_log_reports_pending(app, client):
    seeded = _seed(app)
    session = app.state.session_factory()
    try:
        session.query(DecisionLog).delete()
        session.commit()
    finally:
        session.close()
    row = client.get("/dashboard/predictions").json()[0]
    assert row["decision_status"] == "pending"
    assert row["decision_reason"] == ""
    assert row["match_id"] == str(seeded["match_id"])


def test_bets_contract(app, client):
    seeded = _seed(app)
    response = client.get("/dashboard/bets?limit=100")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    row = payload[0]
    assert row["bet_id"] == str(seeded["bet_id"])
    assert row["match_id"] == str(seeded["match_id"])
    assert row["selection"] == "H"
    assert row["line_key"] == "0.0"
    assert float(row["odds"]) == 2.5
    assert float(row["stake"]) == 100.0
    assert row["status"] == "won"
    assert float(row["payout"]) == 250.0
    assert float(row["profit"]) == 150.0
    assert float(row["clv"]) == 0.05
    assert float(row["brier"]) == 0.25
    assert row["model_version"] == "poisson-v1"
    assert row["settled_at"] is not None


def test_equity_contract(app, client):
    _seed(app)
    response = client.get("/dashboard/equity")
    assert response.status_code == 200
    payload = response.json()
    assert payload["initial"] == "10000.00"
    assert payload["points"][0] == {"t": None, "bankroll": "10000.00"}
    assert len(payload["points"]) == 2
    assert D(payload["points"][-1]["bankroll"]) == D("10150.00")
    assert payload["points"][-1]["t"] is not None


def test_calibration_contract(app, client):
    _seed(app)
    response = client.get("/dashboard/calibration")
    assert response.status_code == 200
    payload = response.json()
    assert payload["models"][0]["version"] == "poisson-v1"
    assert payload["models"][0]["family"] == "poisson"
    assert payload["models"][0]["params"] == {"window": 20}
    assert payload["strategies"][0]["version"] == "g1"
    assert payload["strategies"][0]["model_version"] == "poisson-v1"
    assert len(payload["metrics"]) == 1
    assert payload["metrics"][0]["model_version"] == "poisson-v1"
    assert payload["weight_snapshots"][0]["strategy_version"] == "g1"


def test_technical_contract(app, client):
    seeded = _seed(app)
    response = client.get("/dashboard/technical")
    assert response.status_code == 200
    payload = response.json()
    assert payload["alembic_revision"] is None
    assert payload["database"] == "up"
    assert payload["redis"] == "not_configured"
    assert payload["counts"] == {
        "matches": 2,
        "predictions": 3,
        "bets": 1,
        "settlements": 1,
        "decisions": 1,
        "raw_payloads": 1,
        "source_runs": 1,
    }
    assert payload["sources"][0]["run_id"] == "run-hkjc-1"
    assert payload["sources"][0]["status"] == "succeeded"
    assert payload["decisions"][0]["match_id"] == str(seeded["match_id"])
    assert payload["decisions"][0]["status"] == "bet"
    assert payload["latest_odds"]["market"] == "HAD"
    assert payload["latest_odds"]["match_id"] == str(seeded["match_id"])
    assert payload["paper_forward"] is None


def test_empty_database_returns_zeros(app, client):
    overview = client.get("/dashboard/overview")
    assert overview.status_code == 200
    payload = overview.json()
    assert payload["counts"] == {
        "matches": 0,
        "predictions": 0,
        "bets": 0,
        "settlements": 0,
        "decisions": 0,
    }
    assert payload["bankroll"]["balance"] == "10000.00"
    assert payload["next_fixtures"] == []
    assert payload["latest_calibration"] == []
    assert payload["latest_sources"] == []
    assert client.get("/dashboard/predictions").json() == []
    assert client.get("/dashboard/bets").json() == []
    assert client.get("/dashboard/equity").json() == {
        "initial": "10000.00",
        "points": [{"t": None, "bankroll": "10000.00"}],
    }
    calibration = client.get("/dashboard/calibration").json()
    assert calibration == {
        "models": [],
        "strategies": [],
        "metrics": [],
        "weight_snapshots": [],
    }
    technical = client.get("/dashboard/technical").json()
    assert technical["counts"] == {
        "matches": 0,
        "predictions": 0,
        "bets": 0,
        "settlements": 0,
        "decisions": 0,
        "raw_payloads": 0,
        "source_runs": 0,
    }
    assert technical["latest_odds"] == {
        "snapshot_at": None,
        "market": "HAD",
        "match_id": None,
    }
