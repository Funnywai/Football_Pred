from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import MappingProxyType

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.db.models import (
    Competition,
    DecisionLog,
    MarketLine,
    Match,
    OddsSnapshot,
    Team,
)
from packages.decision.coverage import coverage_for_window, run_decision_reconciliation
from packages.decision.service import decide_match
from packages.domain.enums import MarketType, MatchStatus, Side, SnapshotKind
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
    monkeypatch.setattr(
        "packages.decision.service.predict_had",
        lambda *_args, **_kwargs: FIXED_PREDICTION,
    )
    return FIXED_PREDICTION


def _seed(
    session: Session,
    *,
    code: str = "EPL",
    kickoff_at: datetime = KICKOFF,
    odds: dict[Side, str] | None = None,
    with_snapshot: bool = True,
) -> tuple[Match, OddsSnapshot | None]:
    suffix = uuid.uuid4().hex
    competition = Competition(
        code=code,
        name=f"{code} competition",
        country="England",
        is_cup=False,
        football_data_code=code[:2],
    )
    home = Team(
        slug=f"home-{suffix}",
        name="Home",
        short_name="HOM",
        country="England",
    )
    away = Team(
        slug=f"away-{suffix}",
        name="Away",
        short_name="AWY",
        country="England",
    )
    session.add_all([competition, home, away])
    session.flush()
    match = Match(
        competition_id=competition.id,
        season="2025/26",
        kickoff_at=kickoff_at,
        first_seen_at=NOW - timedelta(hours=1),
        home_team_id=home.id,
        away_team_id=away.id,
        status=MatchStatus.SCHEDULED,
        source_match_ids={"hkjc": "HK-1"},
        coverage_flags=[],
    )
    session.add(match)
    session.flush()
    if not with_snapshot:
        return match, None
    snapshot = OddsSnapshot(
        match_id=match.id,
        market=MarketType.HAD,
        snapshot_kind=SnapshotKind.T30M,
        snapshot_at=NOW,
        query_version="test-v1",
        payload_hash=f"hash-{suffix}",
        run_id="run-1",
    )
    session.add(snapshot)
    session.flush()
    prices = odds or {Side.H: "3.00", Side.D: "4.00", Side.A: "5.00"}
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
                line_status="AVAILABLE",
                is_main=True,
                offer_early_settlement=False,
            )
        )
    session.flush()
    return match, snapshot


def _logs(session: Session) -> list[DecisionLog]:
    return list(session.scalars(select(DecisionLog)))


def test_bet_path_writes_one_bet_log_with_predictions_and_paper_bet(
    session: Session, fixed_prediction
):
    match, snapshot = _seed(session)

    result = decide_match(session, match, snapshot, now=NOW)

    assert result.status == "bet"
    logs = _logs(session)
    assert len(logs) == 1
    log = logs[0]
    assert log.match_id == match.id
    assert log.decision_slot_key == f"g1:{match.id}:T-30m"
    assert log.snapshot_id == snapshot.id
    assert ensure_utc(log.decision_at) == NOW
    assert log.status == "bet"
    assert log.reason == ""
    assert log.model_version == FIXED_PREDICTION.model_version
    assert log.prediction_count == 3
    assert log.paper_bet_id == result.paper_bet_id
    assert log.paper_bet_id is not None


def test_no_bet_path_writes_a_log_with_a_reason_and_predictions(
    session: Session, fixed_prediction
):
    match, snapshot = _seed(
        session,
        odds={Side.H: "2.00", Side.D: "2.50", Side.A: "3.50"},
    )

    result = decide_match(session, match, snapshot, now=NOW)

    assert result.status == "no_bet"
    log = session.execute(select(DecisionLog)).scalar_one()
    assert log.status == "no_bet"
    assert log.reason.strip()
    assert log.prediction_count == 3
    assert log.paper_bet_id is None
    assert log.snapshot_id == snapshot.id


def test_missing_snapshot_writes_a_skipped_log_without_predictions(
    session: Session, fixed_prediction
):
    match, snapshot = _seed(session, with_snapshot=False)

    result = decide_match(session, match, snapshot, now=NOW)

    assert result.status == "skipped"
    log = session.execute(select(DecisionLog)).scalar_one()
    assert log.status == "skipped"
    assert log.reason.strip()
    assert log.prediction_count == 0
    assert log.paper_bet_id is None
    assert log.snapshot_id is None
    assert ensure_utc(log.decision_at) == NOW


def test_non_epl_match_writes_a_skipped_log(session: Session, fixed_prediction):
    match, snapshot = _seed(session, code="UCL")

    result = decide_match(session, match, snapshot, now=NOW)

    assert result.status == "skipped"
    log = session.execute(select(DecisionLog)).scalar_one()
    assert log.status == "skipped"
    assert log.reason.strip()
    assert log.prediction_count == 0
    assert log.snapshot_id == snapshot.id


def test_duplicate_decide_match_calls_update_one_log_row(
    session: Session, fixed_prediction
):
    match, snapshot = _seed(session)

    first = decide_match(session, match, snapshot, now=NOW)
    second = decide_match(session, match, snapshot, now=NOW)

    assert first.status == second.status == "bet"
    logs = _logs(session)
    assert len(logs) == 1
    assert logs[0].status == "bet"
    assert logs[0].paper_bet_id == first.paper_bet_id == second.paper_bet_id

    decide_match(session, match, None, now=NOW)

    logs = _logs(session)
    assert len(logs) == 1
    assert logs[0].status == "bet"
    assert logs[0].paper_bet_id == first.paper_bet_id


def _set_odds(session: Session, snapshot: OddsSnapshot, odds: dict[Side, str]) -> None:
    lines = session.scalars(
        select(MarketLine).where(MarketLine.snapshot_id == snapshot.id)
    ).all()
    for line in lines:
        line.odds_decimal = D(odds[line.side])
    session.flush()


NO_EDGE_ODDS = {Side.H: "2.00", Side.D: "2.50", Side.A: "3.50"}


def test_bet_log_is_never_downgraded_to_no_bet(session: Session, fixed_prediction):
    match, snapshot = _seed(session)
    bet_result = decide_match(session, match, snapshot, now=NOW)
    assert bet_result.status == "bet"

    _set_odds(session, snapshot, NO_EDGE_ODDS)
    retry = decide_match(session, match, snapshot, now=NOW)

    assert retry.status == "no_bet"
    log = session.execute(select(DecisionLog)).scalar_one()
    assert log.status == "bet"
    assert log.paper_bet_id == bet_result.paper_bet_id


def test_bet_log_is_never_downgraded_to_skipped(session: Session, fixed_prediction):
    match, snapshot = _seed(session)
    bet_result = decide_match(session, match, snapshot, now=NOW)

    retry = decide_match(session, match, None, now=NOW)

    assert retry.status == "skipped"
    log = session.execute(select(DecisionLog)).scalar_one()
    assert log.status == "bet"
    assert log.paper_bet_id == bet_result.paper_bet_id


def test_no_bet_log_upgrades_to_bet(session: Session, fixed_prediction):
    match, snapshot = _seed(session, odds=NO_EDGE_ODDS)
    first = decide_match(session, match, snapshot, now=NOW)
    assert first.status == "no_bet"

    _set_odds(session, snapshot, {Side.H: "3.00", Side.D: "4.00", Side.A: "5.00"})
    second = decide_match(session, match, snapshot, now=NOW)

    assert second.status == "bet"
    assert len(_logs(session)) == 1
    log = _logs(session)[0]
    assert log.status == "bet"
    assert log.paper_bet_id == second.paper_bet_id


def test_skipped_log_upgrades_to_no_bet(session: Session, fixed_prediction):
    match, snapshot = _seed(session, odds=NO_EDGE_ODDS)

    first = decide_match(session, match, None, now=NOW)
    assert first.status == "skipped"
    second = decide_match(session, match, snapshot, now=NOW)

    assert second.status == "no_bet"
    assert len(_logs(session)) == 1
    log = _logs(session)[0]
    assert log.status == "no_bet"
    assert log.paper_bet_id is None
    assert log.reason.strip()


def test_non_t30m_log_does_not_satisfy_coverage(session: Session, fixed_prediction):
    match, _ = _seed(session, kickoff_at=NOW + timedelta(minutes=20), with_snapshot=False)
    session.add(
        DecisionLog(
            match_id=match.id,
            decision_slot_key=f"g1:{match.id}:T-24h",
            decision_at=NOW,
            status="skipped",
            reason="other trigger",
            prediction_count=0,
        )
    )
    session.flush()

    coverage = coverage_for_window(
        session,
        start=NOW,
        end=NOW + timedelta(hours=1),
    )

    assert coverage.eligible == 1
    assert coverage.logged == 0
    assert coverage.missing_match_ids == (match.id,)
    assert coverage.counts_by_status == {}


def test_coverage_detects_missing_match_then_sees_it_after_reconciliation(
    session: Session, fixed_prediction
):
    kickoff = NOW + timedelta(minutes=20)
    match, _ = _seed(session, kickoff_at=kickoff, with_snapshot=False)

    before = coverage_for_window(
        session,
        start=NOW,
        end=NOW + timedelta(hours=1),
    )

    assert before.eligible == 1
    assert before.logged == 0
    assert before.missing_match_ids == (match.id,)
    assert before.counts_by_status == {}

    summary = run_decision_reconciliation(session, now=NOW)

    assert summary.reconciled == 1
    assert summary.errors == 0
    after = coverage_for_window(
        session,
        start=NOW,
        end=NOW + timedelta(hours=1),
    )
    assert after.eligible == 1
    assert after.logged == 1
    assert after.missing_match_ids == ()
    assert after.counts_by_status == {"skipped": 1}


def test_reconciliation_logs_a_scheduled_epl_match_with_no_snapshot(
    session: Session, fixed_prediction
):
    kickoff = NOW + timedelta(minutes=20)
    match, _ = _seed(session, kickoff_at=kickoff, with_snapshot=False)

    summary = run_decision_reconciliation(session, now=NOW)

    assert summary.reconciled == 1
    assert summary.errors == 0
    log = session.execute(select(DecisionLog)).scalar_one()
    assert log.match_id == match.id
    assert log.status == "skipped"
    assert log.reason.strip()
    assert log.prediction_count == 0


def test_reconciliation_uses_the_latest_t30m_snapshot(session: Session, fixed_prediction):
    match, snapshot = _seed(session, kickoff_at=NOW + timedelta(minutes=20))

    summary = run_decision_reconciliation(session, now=NOW)

    assert summary.reconciled == 1
    assert summary.errors == 0
    log = session.execute(select(DecisionLog)).scalar_one()
    assert log.match_id == match.id
    assert log.snapshot_id == snapshot.id
    assert log.status == "bet"


def test_reconciliation_reruns_an_old_skip_once_a_t30m_snapshot_exists(
    session: Session, fixed_prediction
):
    match, snapshot = _seed(session, kickoff_at=NOW + timedelta(minutes=20))
    session.add(
        DecisionLog(
            match_id=match.id,
            decision_slot_key=f"g1:{match.id}:T-30m",
            decision_at=NOW - timedelta(minutes=10),
            status="skipped",
            reason="no snapshot yet",
            prediction_count=0,
        )
    )
    session.flush()

    summary = run_decision_reconciliation(session, now=NOW)

    assert summary.reconciled == 1
    log = session.execute(select(DecisionLog)).scalar_one()
    assert log.status == "bet"
    assert log.snapshot_id == snapshot.id

    again = run_decision_reconciliation(session, now=NOW)
    assert again.reconciled == 0


def test_reconciliation_does_not_rerun_a_skip_with_a_snapshot(
    session: Session, fixed_prediction
):
    match, snapshot = _seed(session, kickoff_at=NOW + timedelta(minutes=20))
    session.add(
        DecisionLog(
            match_id=match.id,
            decision_slot_key=f"g1:{match.id}:T-30m",
            snapshot_id=snapshot.id,
            decision_at=NOW - timedelta(minutes=10),
            status="skipped",
            reason="quality veto",
            prediction_count=0,
        )
    )
    session.flush()

    summary = run_decision_reconciliation(session, now=NOW)

    assert summary.reconciled == 0
    log = session.execute(select(DecisionLog)).scalar_one()
    assert log.status == "skipped"
