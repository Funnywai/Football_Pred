from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from packages.db.models import (
    CalibrationMetric,
    Competition,
    DecisionLog,
    Match,
    ModelPrediction,
    ModelVersion,
    PaperBet,
    Settlement,
    StrategyVersion,
    Team,
    WeightSnapshot,
)
from packages.domain.enums import (
    BetStatus,
    MarketType,
    MatchStatus,
    SettlementSource,
    Side,
)
from packages.feedback.service import (
    build_calibration_report,
    ensure_model_version,
    ensure_strategy_version,
    record_weight_snapshot,
)

DECISION_AT = datetime(2026, 11, 1, 13, 0, tzinfo=UTC)
SETTLED_AT = datetime(2026, 11, 1, 16, 0, tzinfo=UTC)


def _competition(session) -> Competition:
    competition = Competition(
        code="EPL",
        name="English Premier League",
        country="England",
        is_cup=False,
        football_data_code="PL",
    )
    session.add(competition)
    session.flush()
    return competition


def _seed_settled_bet(
    session,
    competition: Competition,
    *,
    status: BetStatus,
    probability: str,
    payout: str,
    stake: str = "10.00",
    clv: str | None = "0.05",
) -> None:
    suffix = uuid.uuid4().hex
    home = Team(slug=f"home-{suffix}", name="Home", short_name="HOM", country="England")
    away = Team(slug=f"away-{suffix}", name="Away", short_name="AWY", country="England")
    session.add_all([home, away])
    session.flush()
    match = Match(
        competition_id=competition.id,
        season="2026/27",
        kickoff_at=DECISION_AT,
        home_team_id=home.id,
        away_team_id=away.id,
        status=MatchStatus.FINISHED,
        source_match_ids={},
        coverage_flags=[],
    )
    session.add(match)
    session.flush()
    slot = f"g1:{match.id}:T-30m"
    bet = PaperBet(
        match_id=match.id,
        market=MarketType.HAD,
        line_key="0.0",
        selection=Side.H,
        odds_decimal=Decimal("2.0000"),
        stake=Decimal(stake),
        bankroll_before=Decimal("10000.00"),
        placed_at=DECISION_AT,
        status=status,
        analysis_run_key=f"analysis-{suffix}",
        decision_slot_key=slot,
        bet_intent_key=f"intent-{suffix}",
        decision_at=DECISION_AT,
    )
    session.add(bet)
    session.flush()
    session.add(
        Settlement(
            paper_bet_id=bet.id,
            result_status=status,
            payout=Decimal(payout),
            payout_unrounded=Decimal(payout),
            clv=Decimal(clv) if clv is not None else None,
            brier_score=None,
            settled_at=SETTLED_AT,
            provisional=False,
            source=SettlementSource.HKJC_CONFIRMED,
        )
    )
    session.add(
        DecisionLog(
            match_id=match.id,
            decision_slot_key=slot,
            decision_at=DECISION_AT,
            status="bet",
            reason="",
            model_version="poisson-v1",
            prediction_count=3,
        )
    )
    session.add(
        ModelPrediction(
            match_id=match.id,
            market=MarketType.HAD,
            line_key="0.0",
            outcome=Side.H,
            probability=Decimal(probability),
            score_distribution={},
            return_distribution=None,
            decision_at=DECISION_AT,
            model_version="poisson-v1",
            analysis_run_key=f"analysis-{suffix}",
        )
    )
    session.flush()


def test_ensure_model_and_strategy_versions_are_idempotent(session):
    model = ensure_model_version(
        session,
        "poisson-v1",
        "poisson",
        {"half_life_days": 90},
        {"start": "2024-07", "end": "2026-10"},
        {"brier": "0.21"},
    )
    again = ensure_model_version(
        session,
        "poisson-v1",
        "poisson",
        {"half_life_days": 60},
        {"start": "2025-07", "end": "2026-10"},
        {"brier": "0.2"},
    )

    assert again.id == model.id
    assert session.query(ModelVersion).count() == 1
    assert model.params == {"half_life_days": 60}
    assert model.validation_metrics == {"brier": "0.2"}

    strategy = ensure_strategy_version(session, "g1", "poisson-v1", {"kelly": "0.25"})
    repeated = ensure_strategy_version(session, "g1", "poisson-v1", {"kelly": "0.2"})
    assert repeated.id == strategy.id
    assert session.query(StrategyVersion).count() == 1
    assert strategy.policy_params == {"kelly": "0.2"}


def test_ensure_does_not_downgrade_a_promoted_version(session):
    model = ensure_model_version(session, "poisson-v1", "poisson", {}, {}, {})
    model.status = "production"
    session.flush()

    ensure_model_version(session, "poisson-v1", "poisson", {}, {}, {})
    assert model.status == "production"

    strategy = ensure_strategy_version(session, "g1", "poisson-v1", {})
    strategy.status = "production"
    session.flush()

    ensure_strategy_version(session, "g1", "poisson-v1", {})
    assert strategy.status == "production"


def test_record_weight_snapshot_persists_the_rationale(session):
    snapshot = record_weight_snapshot(
        session,
        "g1",
        {"time_decay": "0.94"},
        "research-only candidate",
        evaluation_period="2026-10",
    )

    assert isinstance(snapshot, WeightSnapshot)
    assert session.query(WeightSnapshot).count() == 1
    assert snapshot.weights == {"time_decay": "0.94"}
    assert snapshot.reason == "research-only candidate"
    assert snapshot.evaluation_period == "2026-10"


def test_build_calibration_report_computes_all_metrics(session):
    competition = _competition(session)
    _seed_settled_bet(
        session,
        competition,
        status=BetStatus.WON,
        probability="0.600000",
        payout="20.00",
    )

    metrics = build_calibration_report(session, time_block="2026-11")

    assert len(metrics) == 1
    metric = session.query(CalibrationMetric).one()
    assert metric.model_version == "poisson-v1"
    assert metric.strategy_version == "g1"
    assert metric.competition == "EPL"
    assert metric.market == "HAD"
    assert metric.time_block == "2026-11"
    assert metric.sample_count == 1
    assert metric.brier == Decimal("0.160000")
    assert metric.log_loss == Decimal("0.510826")
    assert metric.roi == Decimal("1.000000")
    assert metric.clv == Decimal("0.050000")

    bucket = metric.calibration[6]
    assert bucket["count"] == 1
    assert bucket["mean_predicted"] == "0.600000"
    assert bucket["observed_win_rate"] == "1.000000"


def test_build_calibration_report_upserts_instead_of_duplicating(session):
    competition = _competition(session)
    _seed_settled_bet(
        session,
        competition,
        status=BetStatus.WON,
        probability="0.600000",
        payout="20.00",
    )

    build_calibration_report(session, time_block="2026-11")
    build_calibration_report(session, time_block="2026-11")

    assert session.query(CalibrationMetric).count() == 1


def test_calibration_scoring_skips_void_and_push_but_keeps_roi(session):
    competition = _competition(session)
    _seed_settled_bet(
        session,
        competition,
        status=BetStatus.WON,
        probability="0.600000",
        payout="20.00",
    )
    _seed_settled_bet(
        session,
        competition,
        status=BetStatus.VOID,
        probability="0.700000",
        payout="10.00",
    )
    _seed_settled_bet(
        session,
        competition,
        status=BetStatus.PUSH,
        probability="0.800000",
        payout="10.00",
    )

    build_calibration_report(session, time_block="2026-11")
    metric = session.query(CalibrationMetric).one()

    assert metric.sample_count == 3
    assert metric.brier == Decimal("0.160000")
    assert metric.log_loss == Decimal("0.510826")
    assert metric.roi == Decimal("0.333333")
    assert metric.clv == Decimal("0.050000")
    scored = sum(bucket["count"] for bucket in metric.calibration)
    assert scored == 1


def test_calibration_report_skips_bets_without_a_prediction(session):
    competition = _competition(session)
    _seed_settled_bet(
        session,
        competition,
        status=BetStatus.WON,
        probability="0.600000",
        payout="20.00",
    )
    prediction = session.query(ModelPrediction).one()
    session.delete(prediction)
    session.flush()

    assert build_calibration_report(session, time_block="2026-11") == []
    assert session.query(CalibrationMetric).count() == 0
