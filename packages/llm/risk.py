from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.db.models import BankrollAccount, LedgerExperiment, Match
from packages.domain.enums import MarketType, Side
from packages.feedback.service import ensure_model_version, ensure_strategy_version
from packages.ledger.experiments import active_experiment, create_next_experiment
from packages.ledger.service import LedgerService, PlaceBetRequest
from packages.llm.research import MainAgentDecision
from packages.shared.config import get_settings
from packages.shared.time import ensure_utc, utc_now

LLM_ASSISTANT_MODEL_VERSION = "llm-assistant-v2"
LLM_ASSISTANT_STRATEGY_VERSION = "llm-assistant-g1"
LLM_ASSISTANT_LABEL = "llm-assistant-v2"
MAX_SINGLE_BET_FRACTION = Decimal("0.02")
MIN_STAKE = Decimal("1.00")
_MAX_ODDS_AGE_SECONDS = 600
_HAD_SIDES = {"H": Side.H, "D": Side.D, "A": Side.A}


@dataclass(frozen=True, slots=True)
class RiskOutcome:
    accepted: bool
    reason: str
    selection: str | None = None
    stake: Decimal | None = None
    odds: Decimal | None = None
    paper_bet_id: uuid.UUID | None = None
    bankroll: Decimal | None = None


def llm_research_experiment(session: Session) -> LedgerExperiment:
    existing = active_experiment(session, "llm")
    if (
        existing is not None
        and existing.label == LLM_ASSISTANT_LABEL
        and existing.model_version == LLM_ASSISTANT_MODEL_VERSION
        and existing.strategy_version == LLM_ASSISTANT_STRATEGY_VERSION
    ):
        return existing
    _ = ensure_model_version(
        session,
        LLM_ASSISTANT_MODEL_VERSION,
        "llm_research_assistant",
        {"mode": "assistant", "roles": 7, "evidence": "frozen"},
        {},
        {},
    )
    _ = ensure_strategy_version(
        session,
        LLM_ASSISTANT_STRATEGY_VERSION,
        LLM_ASSISTANT_MODEL_VERSION,
        {"stake_cap": "0.02", "min_stake": "1.00", "selection": "main_agent"},
        "research",
    )
    return create_next_experiment(
        session,
        label=LLM_ASSISTANT_LABEL,
        model_version=LLM_ASSISTANT_MODEL_VERSION,
        strategy_version=LLM_ASSISTANT_STRATEGY_VERSION,
        initial_bankroll=get_settings().initial_bankroll,
        lane="llm",
    )


def apply_research_risk(
    session: Session,
    *,
    match: Match,
    packet: dict[str, Any],
    decision: MainAgentDecision,
    stage: str,
) -> RiskOutcome:
    if decision.abstain:
        return RiskOutcome(False, "main agent abstained")
    if decision.recommended_side not in _HAD_SIDES:
        return RiskOutcome(False, "invalid recommended side")
    if ensure_utc(match.kickoff_at) <= utc_now():
        return RiskOutcome(False, "match already kicked off")

    market = packet.get("market")
    quality = packet.get("quality")
    if not isinstance(market, dict) or not isinstance(quality, dict):
        return RiskOutcome(False, "market evidence missing")
    odds_age = quality.get("odds_age_seconds")
    if not isinstance(odds_age, int) or odds_age > _MAX_ODDS_AGE_SECONDS:
        return RiskOutcome(False, "odds are stale or unavailable")
    odds_raw = market.get("odds")
    if not isinstance(odds_raw, dict):
        return RiskOutcome(False, "odds missing")
    odds = _decimal(odds_raw.get(decision.recommended_side))
    if odds is None or odds <= Decimal(1):
        return RiskOutcome(False, "selected odds are invalid")
    line_status = market.get("line_status")
    pool_status = market.get("pool_status")
    if isinstance(line_status, dict) and line_status.get(decision.recommended_side) != "AVAILABLE":
        return RiskOutcome(False, "selected line is not available")
    if isinstance(pool_status, dict) and pool_status.get(decision.recommended_side) != "SELLINGSTARTED":
        return RiskOutcome(False, "selected pool is not selling")
    snapshot_raw = market.get("snapshot_id")
    if not snapshot_raw:
        return RiskOutcome(False, "odds snapshot missing")

    experiment = llm_research_experiment(session)
    ledger = LedgerService(session, experiment_id=experiment.id)
    available = ledger.available_bankroll()
    if available <= 0:
        return RiskOutcome(False, "no available bankroll", bankroll=available)
    account = session.scalar(
        select(BankrollAccount).where(
            BankrollAccount.account_id == experiment.account_id
        )
    )
    reserved = Decimal(str(account.reserved_stake)) if account is not None else Decimal(0)
    exposure_cap = (
        Decimal(str(experiment.initial_bankroll))
        * get_settings().max_total_exposure_fraction
    )
    exposure_room = max(Decimal(0), exposure_cap - reserved)
    stake = min(
        available * decision.recommended_stake_pct,
        available * MAX_SINGLE_BET_FRACTION,
        available,
        exposure_room,
    ).quantize(Decimal("0.01"))
    if stake < MIN_STAKE:
        return RiskOutcome(False, "stake below minimum", bankroll=available)

    selection = _HAD_SIDES[decision.recommended_side]
    slot_key = f"llm-assistant:{experiment.id}:{match.id}:{stage}"
    intent_key = f"{slot_key}:{MarketType.HAD.value}:0.0:{selection.value}"
    try:
        bet = ledger.place_bet(
            PlaceBetRequest(
                match_id=match.id,
                market=MarketType.HAD,
                line_key="0.0",
                selection=selection,
                odds_decimal=odds,
                stake=stake,
                analysis_run_key=f"{LLM_ASSISTANT_MODEL_VERSION}:{match.id}:{stage}",
                decision_slot_key=slot_key,
                bet_intent_key=intent_key,
                decision_at=utc_now(),
                odds_snapshot_id=uuid.UUID(str(snapshot_raw)),
            )
        )
    except Exception as exc:  # noqa: BLE001 - risk decisions must be recorded
        return RiskOutcome(False, f"ledger rejected: {exc}", bankroll=available)
    return RiskOutcome(
        True,
        "accepted",
        selection=decision.recommended_side,
        stake=stake,
        odds=odds,
        paper_bet_id=bet.id,
        bankroll=available,
    )


def _decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        parsed = Decimal(str(value))
    except (ValueError, ArithmeticError):
        return None
    return parsed if parsed.is_finite() else None
