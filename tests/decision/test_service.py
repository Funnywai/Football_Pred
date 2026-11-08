from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import MappingProxyType, SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from packages.db.models import (
    Competition,
    DecisionLog,
    MarketLine,
    Match,
    ModelPrediction,
    OddsSnapshot,
    PaperBet,
    SourceFetchRun,
    Team,
)
from packages.decision.service import decide_match
from packages.domain.enums import FetchRunStatus, MarketType, MatchStatus, Side, SnapshotKind
from packages.ingest.quality import QualityReport
from packages.ingest.quality import evaluate_quality as real_evaluate_quality
from packages.ledger.experiments import create_next_experiment
from packages.models.poisson import HadPrediction
from packages.shared.time import ensure_utc

D = Decimal
NOW = datetime(2026, 8, 15, 13, 30, tzinfo=UTC)
KICKOFF = NOW + timedelta(minutes=30)

SCORE_DISTRIBUTION = {
    (0, 0): D("0.20"),
    (1, 0): D("0.40"),
    (0, 1): D("0.25"),
    (1, 1): D("0.15"),
}
FIXED_PREDICTION = HadPrediction(
    p_home=D("0.40"),
    p_draw=D("0.35"),
    p_away=D("0.25"),
    score_distribution=MappingProxyType(SCORE_DISTRIBUTION),
    tail_mass=D("0"),
    score_grid_max=1,
    tail_handling="grid_complete",
)


@pytest.fixture()
def fixed_prediction(monkeypatch):
    def _predict_had(*_args, **_kwargs):
        return FIXED_PREDICTION

    monkeypatch.setattr("packages.decision.service.predict_had", _predict_had)
    return FIXED_PREDICTION


def _seed(
    session: Session,
    *,
    odds: dict[Side, str] | None = None,
    line_status: dict[Side, str] | None = None,
    snapshot_at: datetime = NOW,
    first_seen_at: datetime | None = NOW - timedelta(hours=1),
    competition_code: str = "EPL",
) -> tuple[Match, OddsSnapshot]:
    competition = Competition(
        code=competition_code,
        name="English Premier League",
        country="England",
        is_cup=False,
        football_data_code="PL",
    )
    home = Team(
        slug=f"home-{uuid.uuid4().hex}",
        name="Home",
        short_name="HOM",
        country="England",
    )
    away = Team(
        slug=f"away-{uuid.uuid4().hex}",
        name="Away",
        short_name="AWY",
        country="England",
    )
    session.add_all([competition, home, away])
    session.flush()
    match = Match(
        competition_id=competition.id,
        season="2025/26",
        kickoff_at=KICKOFF,
        first_seen_at=first_seen_at,
        home_team_id=home.id,
        away_team_id=away.id,
        status=MatchStatus.SCHEDULED,
        source_match_ids={"hkjc": "HK-1"},
        coverage_flags=[],
    )
    session.add(match)
    session.flush()
    snapshot = OddsSnapshot(
        match_id=match.id,
        market=MarketType.HAD,
        snapshot_kind=SnapshotKind.T30M,
        snapshot_at=snapshot_at,
        query_version="test-v1",
        payload_hash=f"hash-{uuid.uuid4().hex}",
        run_id="run-1",
    )
    session.add(snapshot)
    session.flush()
    prices = odds or {Side.H: "3.00", Side.D: "4.00", Side.A: "5.00"}
    statuses = line_status or {}
    for index, (side, price) in enumerate(prices.items()):
        session.add(
            MarketLine(
                snapshot_id=snapshot.id,
                odds_type=MarketType.HAD,
                condition_raw="0.0",
                line_index=index,
                side=side,
                odds_decimal=D(price),
                pool_status="SELLINGSTARTED",
                line_status=statuses.get(side, "AVAILABLE"),
                is_main=True,
                offer_early_settlement=False,
            )
        )
    session.flush()
    return match, snapshot


def _bet_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(PaperBet)) or 0


def _prediction_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(ModelPrediction)) or 0


def test_positive_edge_persists_predictions_and_places_one_capped_bet(
    session: Session, fixed_prediction
):
    match, snapshot = _seed(session)

    result = decide_match(session, match, snapshot, now=NOW)

    assert result.status == "bet"
    assert result.selected_side is Side.D
    assert result.expected_value == D("0.40")
    assert result.kelly_fraction > D(0)
    assert result.stake == D("200.00")
    assert result.paper_bet_id is not None
    assert result.reason == ""

    assert _prediction_count(session) == 3
    bet = session.execute(select(PaperBet)).scalar_one()
    assert bet.id == result.paper_bet_id
    assert bet.selection is Side.D
    assert bet.stake == D("200.00")
    assert bet.odds_decimal == D("4.0000")
    assert bet.analysis_run_key == f"poisson-v1:{match.id}:T-30m"
    assert bet.decision_slot_key == f"g1:{match.id}:T-30m"
    assert bet.bet_intent_key == f"g1:{match.id}:T-30m:HAD:0.0:D"
    assert bet.odds_snapshot_id == snapshot.id
    assert ensure_utc(bet.decision_at) == NOW


def test_challenger_lane_runs_alongside_g1_without_changing_g1(
    session: Session, fixed_prediction
):
    g1 = create_next_experiment(
        session,
        label="g1",
        model_version="poisson-v1",
        strategy_version="g1",
        lane="deterministic",
    )
    challenger = create_next_experiment(
        session,
        label="v2-market-shrunk",
        model_version="poisson-v2-shrunk",
        strategy_version="g1",
        lane="challenger",
    )
    match, snapshot = _seed(session)

    result = decide_match(session, match, snapshot, now=NOW)

    assert result.status == "bet"
    bets = {bet.experiment_id: bet for bet in session.scalars(select(PaperBet)).all()}
    assert set(bets) == {g1.id, challenger.id}
    assert bets[g1.id].selection is bets[challenger.id].selection
    assert bets[g1.id].decision_slot_key.startswith(f"g1:{g1.id}:")
    assert bets[challenger.id].decision_slot_key.startswith(f"g1:{challenger.id}:")
    model_versions = {
        row.model_version
        for row in session.scalars(select(ModelPrediction)).all()
    }
    assert model_versions == {"poisson-v1", "poisson-v2-shrunk"}
    assert _prediction_count(session) == 6


def test_challenger_failure_cannot_rollback_g1_bet(
    session: Session, fixed_prediction, monkeypatch
):
    g1 = create_next_experiment(
        session,
        label="g1",
        model_version="poisson-v1",
        strategy_version="g1",
        lane="deterministic",
    )
    _ = create_next_experiment(
        session,
        label="v2-market-shrunk",
        model_version="poisson-v2-shrunk",
        strategy_version="g1",
        lane="challenger",
    )
    match, snapshot = _seed(session)

    def _boom(*_args, **_kwargs):
        raise RuntimeError("challenger boom")

    monkeypatch.setattr("packages.decision.service.shrink_had_prediction", _boom)

    result = decide_match(session, match, snapshot, now=NOW)

    assert result.status == "bet"
    bets = session.scalars(select(PaperBet)).all()
    assert len(bets) == 1
    assert bets[0].experiment_id == g1.id


def test_no_edge_saves_predictions_but_places_no_bet(session: Session, fixed_prediction):
    match, snapshot = _seed(
        session,
        odds={Side.H: "2.00", Side.D: "2.50", Side.A: "3.50"},
    )

    result = decide_match(session, match, snapshot, now=NOW)

    assert result.status == "no_bet"
    assert result.reason.strip()
    assert result.selected_side is None
    assert result.stake is None
    assert result.paper_bet_id is None
    assert _prediction_count(session) == 3
    assert _bet_count(session) == 0


def test_stale_snapshot_is_skipped_without_a_bet(session: Session, fixed_prediction):
    match, snapshot = _seed(session, snapshot_at=NOW - timedelta(minutes=11))

    result = decide_match(session, match, snapshot, now=NOW)

    assert result.status in {"skipped", "no_bet"}
    assert "older than" in result.reason
    assert result.paper_bet_id is None
    assert _bet_count(session) == 0
    log = session.execute(select(DecisionLog)).scalar_one()
    assert log.status == "skipped"
    assert log.reason.strip()
    assert log.paper_bet_id is None


def test_failed_source_run_in_the_last_30_minutes_is_degraded(
    session: Session, fixed_prediction
):
    match, snapshot = _seed(session)
    session.add(
        SourceFetchRun(
            run_id="failed-run",
            source_name="hkjc",
            started_at=NOW,
            finished_at=NOW,
            status=FetchRunStatus.FAILED,
            params={},
        )
    )
    session.flush()

    result = decide_match(session, match, snapshot, now=NOW)

    assert result.status == "skipped"
    assert "source_degraded:hkjc" in result.reason
    assert result.paper_bet_id is None
    assert _bet_count(session) == 0
    assert session.execute(select(DecisionLog)).scalar_one().status == "skipped"


def test_old_failed_source_run_does_not_degrade_quality(
    session: Session, fixed_prediction
):
    match, snapshot = _seed(session)
    session.add(
        SourceFetchRun(
            run_id="old-failed-run",
            source_name="hkjc",
            started_at=NOW - timedelta(hours=1),
            finished_at=NOW - timedelta(minutes=31),
            status=FetchRunStatus.FAILED,
            params={},
        )
    )
    session.flush()

    result = decide_match(session, match, snapshot, now=NOW)

    assert result.status == "bet"
    assert _bet_count(session) == 1


def test_quality_veto_skips_before_fitting_the_model(
    session: Session, fixed_prediction, monkeypatch
):
    monkeypatch.setattr(
        "packages.decision.service.evaluate_quality",
        lambda _data: QualityReport(flags=(), veto_reasons=("odds_stale",)),
    )
    match, snapshot = _seed(session)

    result = decide_match(session, match, snapshot, now=NOW)

    assert result.status == "skipped"
    assert "odds_stale" in result.reason
    assert result.prediction is None
    assert _prediction_count(session) == 0
    assert _bet_count(session) == 0


def test_had_quality_input_does_not_require_lineups(
    session: Session, fixed_prediction, monkeypatch
):
    captured = {}

    def _capture(data):
        captured["input"] = data
        return real_evaluate_quality(data)

    monkeypatch.setattr("packages.decision.service.evaluate_quality", _capture)
    match, snapshot = _seed(session)

    result = decide_match(session, match, snapshot, now=NOW)

    quality_input = captured["input"]
    assert quality_input.requires_lineup is False
    assert quality_input.has_standard_lineup is False
    assert quality_input.has_predicted_lineup is False
    assert quality_input.has_xg is False
    assert result.status == "bet"
    assert _bet_count(session) == 1


def test_match_first_seen_after_decision_is_skipped(session: Session, fixed_prediction):
    match, snapshot = _seed(session, first_seen_at=NOW + timedelta(minutes=1))

    result = decide_match(session, match, snapshot, now=NOW)

    assert result.status in {"skipped", "no_bet"}
    assert result.reason.strip()
    assert result.paper_bet_id is None
    assert _bet_count(session) == 0


def test_missing_had_side_is_skipped_without_a_bet(session: Session, fixed_prediction):
    match, snapshot = _seed(
        session,
        odds={Side.H: "3.00", Side.A: "5.00"},
    )

    result = decide_match(session, match, snapshot, now=NOW)

    assert result.status == "skipped"
    assert "D" in result.reason
    assert result.paper_bet_id is None
    assert _bet_count(session) == 0


def test_suspended_had_line_is_skipped_without_a_bet(session: Session, fixed_prediction):
    match, snapshot = _seed(
        session,
        line_status={Side.D: "SUSPENDED"},
    )

    result = decide_match(session, match, snapshot, now=NOW)

    assert result.status == "skipped"
    assert result.reason.strip()
    assert result.paper_bet_id is None
    assert _bet_count(session) == 0


def test_odds_below_minimum_are_skipped_without_a_bet(session: Session, fixed_prediction):
    match, snapshot = _seed(
        session,
        odds={Side.H: "1.00", Side.D: "4.00", Side.A: "5.00"},
    )

    result = decide_match(session, match, snapshot, now=NOW)

    assert result.status == "skipped"
    assert result.reason.strip()
    assert result.paper_bet_id is None
    assert _bet_count(session) == 0


def test_non_epl_league_places_a_bet_when_default_policy_allows_it(
    session: Session, fixed_prediction
):
    match, snapshot = _seed(session, competition_code="LALIGA")

    result = decide_match(session, match, snapshot, now=NOW)

    assert result.status == "bet"
    assert result.prediction is not None
    assert result.paper_bet_id is not None
    assert result.stake == D("200.00")
    assert _prediction_count(session) == 3
    assert _bet_count(session) == 1
    log = session.execute(select(DecisionLog)).scalar_one()
    assert log.status == "bet"
    assert log.paper_bet_id == result.paper_bet_id
    assert log.prediction_count == 3


def test_ucl_places_a_bet_without_xg_when_default_policy_allows_it(
    session: Session, fixed_prediction
):
    match, snapshot = _seed(session, competition_code="UCL")

    result = decide_match(session, match, snapshot, now=NOW)

    assert result.status == "bet"
    assert result.prediction is not None
    assert result.paper_bet_id is not None
    assert result.stake == D("200.00")
    assert _prediction_count(session) == 3
    assert _bet_count(session) == 1
    log = session.execute(select(DecisionLog)).scalar_one()
    assert log.status == "bet"
    assert log.paper_bet_id == result.paper_bet_id
    assert log.prediction_count == 3


def test_non_enabled_competition_stays_prediction_only(
    session: Session, fixed_prediction, monkeypatch
):
    monkeypatch.setattr(
        "packages.decision.service.get_settings",
        lambda: SimpleNamespace(paper_competitions="EPL"),
    )
    match, snapshot = _seed(session, competition_code="LALIGA")

    result = decide_match(session, match, snapshot, now=NOW)

    assert result.status == "prediction_only"
    assert result.prediction is not None
    assert result.paper_bet_id is None
    assert result.stake is None
    assert _prediction_count(session) == 3
    assert _bet_count(session) == 0
    log = session.execute(select(DecisionLog)).scalar_one()
    assert log.status == "prediction_only"
    assert log.paper_bet_id is None
    assert log.prediction_count == 3


def test_duplicate_decision_reuses_predictions_and_paper_bet(
    session: Session, fixed_prediction
):
    match, snapshot = _seed(session)

    first = decide_match(session, match, snapshot, now=NOW)
    second = decide_match(session, match, snapshot, now=NOW)

    assert first.status == "bet"
    assert second.status == "bet"
    assert second.paper_bet_id == first.paper_bet_id
    assert second.stake == first.stake
    assert _bet_count(session) == 1
    assert _prediction_count(session) == 3


def test_decision_binds_active_experiment_and_epoch_key(
    session: Session, fixed_prediction
):
    experiment = create_next_experiment(
        session,
        label="epoch-test",
        model_version="poisson-v1",
        strategy_version="g2",
    )
    match, snapshot = _seed(session, competition_code="UCL")

    result = decide_match(session, match, snapshot, now=NOW)

    assert result.status == "bet"
    bet = session.execute(select(PaperBet)).scalar_one()
    log = session.execute(select(DecisionLog)).scalar_one()
    assert bet.experiment_id == experiment.id
    assert log.experiment_id == experiment.id
    assert bet.decision_slot_key == f"g1:{experiment.id}:{match.id}:T-30m"


def test_missing_snapshot_is_skipped_with_clear_reason(
    session: Session, fixed_prediction
):
    match, _ = _seed(session)

    result = decide_match(session, match, None, now=NOW)

    assert result.status == "skipped"
    assert "no odds snapshot" in result.reason
    log = session.execute(select(DecisionLog)).scalar_one()
    assert log.status == "skipped"
    assert "no odds snapshot" in log.reason
    assert log.paper_bet_id is None


def test_match_specific_result_absence_does_not_degrade_source(
    session: Session, fixed_prediction
):
    match, snapshot = _seed(session)
    session.add(
        SourceFetchRun(
            run_id="result-not-published",
            source_name="hkjc",
            started_at=NOW,
            finished_at=NOW,
            status=FetchRunStatus.FAILED,
            params={"operation": "match_results", "match_source_id": "50000000"},
            error_summary="match 50000000 not found in matchResults for 2026-08-15",
        )
    )
    session.flush()

    result = decide_match(session, match, snapshot, now=NOW)

    assert result.status in {"bet", "no_bet"}
    assert "source_degraded" not in result.reason
