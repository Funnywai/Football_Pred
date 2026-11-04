from __future__ import annotations

import uuid
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy.orm import Session

from packages.db.models import PaperBet
from packages.domain.enums import MarketType, Side
from packages.ledger.experiments import ensure_lane_experiment
from packages.ledger.service import LedgerService, PlaceBetRequest
from packages.shared.time import ensure_utc

MIN_EDGE = Decimal("0.03")
FRACTIONAL_KELLY = Decimal("0.25")
MAX_STAKE_FRACTION = Decimal("0.02")
MIN_STAKE = Decimal("1.00")
_MONEY_QUANTUM = Decimal("0.01")
LLM_STRATEGY_VERSION = "llm-g1"
LLM_EXPERIMENT_LABEL = "llm-baseline"
_SIDES = (Side.H, Side.D, Side.A)


def _decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        parsed = Decimal(str(value))
    except (ValueError, ArithmeticError):
        return None
    return parsed if parsed.is_finite() else None


def _should_abstain(red_team: dict[str, Any] | None, judge: dict[str, Any] | None) -> bool:
    return (
        (isinstance(red_team, dict) and red_team.get("recommended_abstain") is True)
        or (
            isinstance(judge, dict)
            and judge.get("abstain_recommendation") is True
        )
    )


def place_llm_paper_bet(
    session: Session,
    *,
    match_id: uuid.UUID,
    stage: str,
    model_version: str,
    probabilities: dict[str, str],
    packet: dict[str, Any],
    red_team: dict[str, Any] | None,
    judge: dict[str, Any] | None,
) -> PaperBet | None:
    """Apply the deterministic EV/Kelly gate to an LLM ensemble prediction.

    The LLM only supplies probabilities. This function owns selection, staking,
    the independent LLM experiment/account and the paper-bet row. It never
    writes a bet when the market is missing, the edge is below 3%, Kelly is not
    positive, or the risk agents recommend abstention.
    """
    if _should_abstain(red_team, judge):
        return None

    market = packet.get("market")
    if not isinstance(market, dict):
        return None
    snapshot_id_raw = market.get("snapshot_id")
    odds_raw = market.get("odds")
    if not snapshot_id_raw or not isinstance(odds_raw, dict):
        return None

    line_status = market.get("line_status")
    pool_status = market.get("pool_status")
    if isinstance(line_status, dict) and any(
        line_status.get(side.value) != "AVAILABLE" for side in _SIDES
    ):
        return None
    if isinstance(pool_status, dict) and any(
        pool_status.get(side.value) != "SELLINGSTARTED" for side in _SIDES
    ):
        return None

    odds: dict[Side, Decimal] = {}
    for side in _SIDES:
        value = _decimal(odds_raw.get(side.value))
        if value is None or value < Decimal("1.01"):
            return None
        odds[side] = value

    probability_values: dict[Side, Decimal] = {}
    for side in _SIDES:
        value = _decimal(probabilities.get(side.value))
        if value is None or value < 0 or value > 1:
            return None
        probability_values[side] = value

    evaluations: list[tuple[Side, Decimal, Decimal]] = []
    for side in _SIDES:
        probability = probability_values[side]
        price = odds[side]
        ev = probability * price - Decimal(1)
        kelly = (probability * price - Decimal(1)) / (price - Decimal(1))
        evaluations.append((side, ev, kelly))
    selected_side, best_ev, best_kelly = max(evaluations, key=lambda item: item[1])

    if best_ev < MIN_EDGE or best_kelly <= 0:
        return None

    experiment = ensure_lane_experiment(
        session,
        lane="llm",
        label=LLM_EXPERIMENT_LABEL,
        model_version=model_version,
        strategy_version=LLM_STRATEGY_VERSION,
    )
    ledger = LedgerService(session, experiment_id=experiment.id)
    available = ledger.available_bankroll()
    stake = min(
        available * best_kelly * FRACTIONAL_KELLY,
        available * MAX_STAKE_FRACTION,
    ).quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP)
    if stake < MIN_STAKE:
        return None

    decision_at = ensure_utc(datetime.fromisoformat(str(packet["as_of"])))
    slot_key = f"llm:{experiment.id}:{match_id}:{stage}"
    intent_key = f"{slot_key}:{MarketType.HAD.value}:0.0:{selected_side.value}"
    return ledger.place_bet(
        PlaceBetRequest(
            match_id=match_id,
            market=MarketType.HAD,
            line_key="0.0",
            selection=selected_side,
            odds_decimal=odds[selected_side],
            stake=stake,
            analysis_run_key=f"{model_version}:{match_id}:{stage}",
            decision_slot_key=slot_key,
            bet_intent_key=intent_key,
            decision_at=decision_at,
            odds_snapshot_id=uuid.UUID(str(snapshot_id_raw)),
        )
    )
