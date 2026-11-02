import uuid
from datetime import timedelta
from decimal import Decimal

import pytest

from packages.db.models import (
    MarketLine,
    Match,
    OddsSnapshot,
    PaperBet,
    RawPayload,
    Settlement,
)
from packages.domain.enums import MarketType, Side, SnapshotKind
from packages.domain.errors import InsufficientBankrollError
from packages.ingest.dry_run import KICKOFF, SNAPSHOT_AT, run_dry_run
from packages.ingest.pipeline import PipelineError
from packages.ledger.service import LedgerService, PlaceBetRequest
from packages.shared.time import ensure_utc


def test_dry_run_produces_a_winning_had_bet(session):
    result = run_dry_run(session)
    assert result.settlement_status == "won"
    assert result.payout == Decimal("200.00")
    assert result.roi == Decimal(1)
    assert result.clv is not None
    assert abs(result.clv - Decimal("0.111111")) < Decimal("0.000001")


def test_dry_run_is_idempotent(session):
    first = run_dry_run(session)
    second = run_dry_run(session)
    assert first.bet_id == second.bet_id
    assert first.match_id == second.match_id
    assert session.query(Match).count() == 1
    assert session.query(PaperBet).count() == 1


def test_dry_run_produces_only_one_had_bet(session):
    result = run_dry_run(session)
    assert result.settlement_status == "won"
    assert session.query(PaperBet).count() == 1
    assert session.query(PaperBet).one().market is MarketType.HAD


def test_duplicate_worker_retry_does_not_create_second_bet(session):
    first = run_dry_run(session)
    second = run_dry_run(session)
    assert first.bet_id == second.bet_id
    assert session.query(PaperBet).count() == 1
    assert session.query(Settlement).count() == 1


def test_dry_run_does_not_require_llm_or_hdc_hil(session):
    result = run_dry_run(session)
    assert result.settlement_status == "won"
    assert session.query(PaperBet).one().market is MarketType.HAD
    snapshots = session.query(OddsSnapshot).all()
    assert len(snapshots) == 1
    assert snapshots[0].market is MarketType.HAD
    assert snapshots[0].snapshot_kind is SnapshotKind.T30M
    assert {line.odds_type for line in session.query(MarketLine).all()} == {
        MarketType.HAD
    }


def test_dry_run_freezes_the_t_30m_decision_time(session):
    run_dry_run(session)
    bet = session.query(PaperBet).one()
    assert ensure_utc(bet.decision_at) == SNAPSHOT_AT
    assert ensure_utc(bet.placed_at) == SNAPSHOT_AT
    assert ensure_utc(bet.decision_at) == KICKOFF - timedelta(minutes=30)
    assert bet.analysis_run_key
    assert bet.decision_slot_key.endswith(":T-30m")
    assert bet.bet_intent_key.endswith(":HAD:0.0:H")
    match = session.query(Match).one()
    assert ensure_utc(match.kickoff_at) == KICKOFF
    assert ensure_utc(match.first_seen_at) <= SNAPSHOT_AT


def test_dry_run_retry_reuses_the_decision_snapshot(session):
    first = run_dry_run(session)
    bet = session.query(PaperBet).one()
    snapshot = session.query(OddsSnapshot).one()
    second = run_dry_run(session)
    assert first.bet_id == second.bet_id
    assert session.query(OddsSnapshot).count() == 1
    assert bet.odds_snapshot_id == snapshot.id


def test_dry_run_retry_does_not_duplicate_raw_payloads(session):
    run_dry_run(session)
    first_count = session.query(RawPayload).count()
    assert first_count == 2
    run_dry_run(session)
    assert session.query(RawPayload).count() == first_count


def test_worker_retry_with_same_bet_intent_returns_existing_bet(session):
    result = run_dry_run(session)
    bet = session.query(PaperBet).one()
    ledger = LedgerService(session)
    retried = ledger.place_bet(
        PlaceBetRequest(
            match_id=bet.match_id,
            market=MarketType.HAD,
            line_key="0.0",
            selection=Side.H,
            odds_decimal=Decimal("2.00"),
            stake=Decimal("100.00"),
            analysis_run_key=bet.analysis_run_key,
            decision_slot_key=bet.decision_slot_key,
            bet_intent_key=bet.bet_intent_key,
            decision_at=SNAPSHOT_AT,
            odds_snapshot_id=bet.odds_snapshot_id,
        )
    )
    assert retried.id == bet.id
    assert retried.id == uuid.UUID(result.bet_id)
    assert session.query(PaperBet).count() == 1


def test_second_decision_cannot_overspend_cash_available(session):
    run_dry_run(session)
    bet = session.query(PaperBet).one()
    ledger = LedgerService(session)
    available = ledger.available_bankroll()
    assert available > 0

    with pytest.raises(InsufficientBankrollError):
        ledger.place_bet(
            PlaceBetRequest(
                match_id=bet.match_id,
                market=MarketType.HAD,
                line_key="0.0",
                selection=Side.A,
                odds_decimal=Decimal("3.80"),
                stake=available + Decimal("0.01"),
                analysis_run_key="second-analysis",
                decision_slot_key="second-slot",
                bet_intent_key="second-intent",
                decision_at=SNAPSHOT_AT,
            )
        )

    assert session.query(PaperBet).count() == 1
    assert ledger.available_bankroll() == available
    assert ledger.available_bankroll() >= 0


def test_dry_run_refuses_evidence_observed_after_the_frozen_decision(
    session, monkeypatch
):
    import packages.ingest.dry_run as dry_run_module

    monkeypatch.setattr(
        dry_run_module,
        "FETCHED_AT",
        SNAPSHOT_AT + timedelta(seconds=1),
    )
    with pytest.raises(PipelineError, match="evidence gate"):
        run_dry_run(session)
    assert session.query(PaperBet).count() == 0
    assert session.query(OddsSnapshot).count() == 1


def test_dry_run_fails_closed_when_raw_evidence_is_missing(session, monkeypatch):
    from types import SimpleNamespace

    import packages.ingest.pipeline as pipeline_module

    monkeypatch.setattr(
        pipeline_module,
        "persist_raw_payload",
        lambda *args, **kwargs: SimpleNamespace(id=None),
    )
    with pytest.raises(PipelineError, match="raw payload"):
        run_dry_run(session)
    assert session.query(PaperBet).count() == 0
    assert session.query(OddsSnapshot).count() == 1
    assert session.query(RawPayload).count() == 0


def test_dry_run_is_documented_as_engineering_not_llm_evidence():
    doc = (run_dry_run.__doc__ or "").lower()
    assert "engineering" in doc
    assert "settlement" in doc
    assert "not llm evidence" in doc
