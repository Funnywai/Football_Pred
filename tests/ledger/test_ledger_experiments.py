from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select

from packages.db.models import Match, PaperBet
from packages.domain.enums import MarketType, Side
from packages.ledger.experiments import active_experiment, create_next_experiment
from packages.ledger.service import LedgerService, PlaceBetRequest

D = Decimal
NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


def _match(session) -> Match:
    match = Match(
        competition_id=uuid.uuid4(),
        season="2026/27",
        kickoff_at=NOW,
        home_team_id=uuid.uuid4(),
        away_team_id=uuid.uuid4(),
        status="scheduled",
        source_match_ids={},
        coverage_flags=[],
    )
    session.add(match)
    session.flush()
    return match


def _request(match_id, slot: str) -> PlaceBetRequest:
    return PlaceBetRequest(
        match_id=match_id,
        market=MarketType.HAD,
        line_key="0.0",
        selection=Side.H,
        odds_decimal=D("2.00"),
        stake=D("100.00"),
        analysis_run_key=f"analysis-{slot}",
        decision_slot_key=slot,
        bet_intent_key=f"intent-{slot}",
        decision_at=NOW,
    )


def test_new_experiment_archives_old_baseline_and_scopes_roi(session):
    first = create_next_experiment(
        session,
        label="baseline",
        model_version="poisson-v1",
        strategy_version="g1",
    )
    assert active_experiment(session).id == first.id
    ledger_first = LedgerService(session, experiment_id=first.id)
    bet = ledger_first.place_bet(_request(_match(session).id, "first-slot"))
    assert bet.experiment_id == first.id
    assert ledger_first.summary().pending_count == 1

    second = create_next_experiment(
        session,
        label="poisson-v2-g2",
        model_version="poisson-v2",
        strategy_version="g2",
    )
    assert second.id != first.id
    assert active_experiment(session).id == second.id

    ledger_second = LedgerService(session, experiment_id=second.id)
    assert ledger_second.summary().pending_count == 0
    assert ledger_first.summary().pending_count == 1

    rows = session.scalars(select(PaperBet)).all()
    assert {row.experiment_id for row in rows} == {first.id}


def test_lanes_keep_independent_active_experiments(session):
    deterministic = create_next_experiment(
        session,
        label="deterministic",
        model_version="poisson-v1",
        strategy_version="g1",
        lane="deterministic",
    )
    llm = create_next_experiment(
        session,
        label="llm",
        model_version="llm-ensemble-v1",
        strategy_version="llm-g1",
        lane="llm",
    )

    assert active_experiment(session, "deterministic").id == deterministic.id
    assert active_experiment(session, "llm").id == llm.id
    assert deterministic.is_active is True
    assert llm.is_active is True
