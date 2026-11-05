from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from packages.db.base import Base
from packages.db.models import (
    Competition,
    MarketLine,
    Match,
    ModelPrediction,
    OddsSnapshot,
    PaperBet,
    Settlement,
    Team,
)
from packages.domain.enums import (
    BetStatus,
    MarketType,
    MatchStatus,
    SettlementSource,
    Side,
    SnapshotKind,
)
from packages.evaluation.report import SCHEMA_VERSION, build_evaluation_report
from packages.ledger.experiments import create_next_experiment

D = Decimal
NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
DECISION_AT = NOW - timedelta(minutes=30)


def _session():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)()


def _seed(session) -> tuple[Match, uuid.UUID]:
    competition = Competition(
        code="EPL",
        name="Premier League",
        country="England",
        football_data_code="E0",
    )
    home = Team(slug="report-home", name="Home", short_name="HOM", country="England")
    away = Team(slug="report-away", name="Away", short_name="AWY", country="England")
    session.add_all([competition, home, away])
    session.flush()
    match = Match(
        competition_id=competition.id,
        season="2026/27",
        kickoff_at=NOW,
        home_team_id=home.id,
        away_team_id=away.id,
        status=MatchStatus.FINISHED,
        home_goals_90=2,
        away_goals_90=1,
        result_available_at=NOW + timedelta(hours=2),
        source_match_ids={},
        coverage_flags=[],
    )
    session.add(match)
    session.flush()
    snapshot = OddsSnapshot(
        match_id=match.id,
        market=MarketType.HAD,
        snapshot_kind=SnapshotKind.T30M,
        snapshot_at=DECISION_AT,
        query_version="test-v1",
        payload_hash="report-hash",
        run_id="report-run",
    )
    session.add(snapshot)
    session.flush()
    for index, (side, price) in enumerate(
        ((Side.H, "2.50"), (Side.D, "3.20"), (Side.A, "4.00"))
    ):
        session.add(
            MarketLine(
                snapshot_id=snapshot.id,
                odds_type=MarketType.HAD,
                condition_raw="0.0",
                line_index=index,
                side=side,
                odds_decimal=D(price),
                pool_status="SELLINGSTARTED",
                line_status="AVAILABLE",
                is_main=True,
                offer_early_settlement=False,
            )
        )
    for side, probability in (
        (Side.H, "0.500000"),
        (Side.D, "0.300000"),
        (Side.A, "0.200000"),
    ):
        session.add(
            ModelPrediction(
                match_id=match.id,
                market=MarketType.HAD,
                line_key="0.0",
                outcome=side,
                probability=D(probability),
                score_distribution={},
                decision_at=DECISION_AT,
                model_version="poisson-v1",
                analysis_run_key=f"poisson-v1:{match.id}:T-30m",
            )
        )
    experiment = create_next_experiment(
        session,
        label="report-baseline",
        model_version="poisson-v1",
        strategy_version="g1",
    )
    bet = PaperBet(
        experiment_id=experiment.id,
        match_id=match.id,
        market=MarketType.HAD,
        line_key="0.0",
        selection=Side.H,
        odds_decimal=D("2.50"),
        stake=D("100.00"),
        bankroll_before=D("10000.00"),
        placed_at=DECISION_AT,
        status=BetStatus.WON,
        analysis_run_key=f"poisson-v1:{match.id}:T-30m",
        decision_slot_key=f"g1:{experiment.id}:{match.id}:T-30m",
        bet_intent_key=f"g1:{experiment.id}:{match.id}:T-30m:HAD:0.0:H",
        decision_at=DECISION_AT,
    )
    session.add(bet)
    session.flush()
    session.add(
        Settlement(
            paper_bet_id=bet.id,
            result_status=BetStatus.WON,
            payout=D("250.00"),
            payout_unrounded=D("250.000000"),
            clv=D("0.050000"),
            brier_score=D("0.250000"),
            settled_at=NOW + timedelta(hours=2),
            provisional=False,
            source=SettlementSource.HKJC_CONFIRMED,
        )
    )
    # A finished match without an audit timestamp must be surfaced, not guessed.
    session.add(
        Match(
            competition_id=competition.id,
            season="2026/27",
            kickoff_at=NOW + timedelta(days=1),
            home_team_id=away.id,
            away_team_id=home.id,
            status=MatchStatus.FINISHED,
            home_goals_90=0,
            away_goals_90=0,
            source_match_ids={},
            coverage_flags=[],
        )
    )
    session.commit()
    return match, experiment.id


def test_report_scores_model_against_same_time_market():
    engine, session = _session()
    try:
        _match, experiment_id = _seed(session)
        report = build_evaluation_report(session, now=NOW)

        assert report["schema_version"] == SCHEMA_VERSION
        model = report["models"][0]
        assert model["model_version"] == "poisson-v1"
        assert model["competition"] == "EPL"
        assert model["matches"] == 1
        assert model["market_matches"] == 1
        assert D(model["model"]["brier"]) == D("0.380000")
        assert D(model["market"]["brier"]) > 0
        assert model["delta_brier"] is not None
        assert report["bets"][0]["experiment_id"] == str(experiment_id)
        assert report["bets"][0]["roi"] == "1.5"
        assert report["bets"][0]["settlement_coverage"] == "1"
        assert report["bets"][0]["clv_coverage"] == "1"
        assert report["bets"][0]["missing_settlements"] == 0
        assert report["bets"][0]["pending_stake"] == "0"
        assert report["integrity"]["duplicate_bet_slots"] == 0
        assert report["integrity"]["settled_bets_missing_settlement"] == 0
        assert report["universe"]["finished_matches"] == 2
        assert report["integrity"]["finished_matches_missing_result_available_at"] == 1
        assert report["integrity"]["result_timestamp_coverage"] == "0.5"
        assert report["integrity"]["predictions_after_kickoff"] == 0
        assert model["model"]["brier_ci95"] is None
        assert model["delta_ci95"]["brier"] is None
        assert model["policy_controls"]["3%"]["bets"] == 1
        assert model["policy_controls"]["3%"]["wins"] == 1
        assert D(model["policy_controls"]["3%"]["roi"]) == D("1.5")
    finally:
        session.close()
        engine.dispose()
