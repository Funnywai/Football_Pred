"""Deterministic risk agent: paper-only staking decisions with a full audit trail.

Every candidate outcome is written to ``agent_decisions`` (both ``bet`` and
``no_bet``). The service never touches ``ledger_bets`` or ``shadow_ledger_bets``
and never places a real bet; the caller owns the commit.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import AgentDecision, League, Match, ModelVersion, Prediction, Season
from app.ml.dataset import load_hkjc_priors
from app.ml.features import MatchRow
from app.ml.models import TARGET_1X2
from app.ml.registry import STATUS_CHAMPION
from app.ml.value import kelly_fraction
from app.services.ledger import _size_stake

ACTION_BET = "bet"
ACTION_NO_BET = "no_bet"
AGENT_RISK = "risk"


class RiskRunSummary(NamedTuple):
    run_id: str
    matches_considered: int
    candidates_evaluated: int
    bets_allowed: int
    no_bets: int
    total_stake: float


class _CandidateFacts(NamedTuple):
    prior_available: bool
    outcome: str
    odds: float | None
    implied: float | None
    execution_edge: float | None
    kelly: float | None
    stake: float | None
    winner: str | None


def _verdict(facts: _CandidateFacts, settings: Settings) -> tuple[str, str]:
    if facts.winner is not None:
        return ACTION_NO_BET, f"one bet per match already selected outcome {facts.winner}"
    if not facts.prior_available:
        return ACTION_NO_BET, "no pre-kickoff HKJC HAD price for this match"
    if facts.odds is None or facts.implied is None:
        return ACTION_NO_BET, f"execution snapshot has no price for outcome {facts.outcome}"
    if facts.execution_edge is None:
        return ACTION_NO_BET, "execution edge unavailable"
    if facts.execution_edge <= 0:
        return ACTION_NO_BET, f"execution edge {facts.execution_edge:.4f} <= 0"
    if facts.kelly is None:
        return ACTION_NO_BET, "kelly fraction unavailable"
    if facts.kelly <= 0:
        return ACTION_NO_BET, f"kelly fraction {facts.kelly:.4f} <= 0"
    if facts.odds > settings.agent_max_odds:
        return ACTION_NO_BET, f"odds {facts.odds:.2f} above agent max {settings.agent_max_odds:.2f}"
    if facts.stake is None:
        return ACTION_NO_BET, f"stake below minimum HKD {settings.ledger_min_stake:.0f}"
    return ACTION_BET, f"bet: execution edge {facts.execution_edge:.4f}, kelly {facts.kelly:.4f}"


async def evaluate_risk(session: AsyncSession, settings: Settings) -> RiskRunSummary:
    """Evaluate champion 1x2 predictions for future matches, one decision per candidate.

    Candidates are ordered per match by prediction-time ``edge`` DESC then
    ``outcome`` ASC. The first candidate that passes every deterministic rule is
    the single ``bet`` for that match; all others are logged as ``no_bet`` with a
    specific reason. Execution prices come from the latest pre-kickoff HKJC HAD
    snapshot, exactly like the shadow ledger.
    """
    evaluated_at = datetime.now(UTC)
    run_id = str(uuid.uuid4())
    candidates = (
        (
            await session.execute(
                select(Prediction)
                .join(ModelVersion, ModelVersion.id == Prediction.model_version_id)
                .join(Match, Match.id == Prediction.match_id)
                .where(ModelVersion.status == STATUS_CHAMPION)
                .where(Prediction.target == TARGET_1X2)
                .where(Match.kickoff_time > evaluated_at)
                .order_by(
                    Prediction.match_id,
                    Prediction.edge.is_(None),
                    Prediction.edge.desc(),
                    Prediction.outcome.asc(),
                )
            )
        )
        .scalars()
        .all()
    )
    if not candidates:
        return RiskRunSummary(run_id, 0, 0, 0, 0, 0.0)

    by_match: dict[int, list[Prediction]] = {}
    for prediction in candidates:
        by_match.setdefault(prediction.match_id, []).append(prediction)

    fields = (
        await session.execute(
            select(Match, League.code, Season.label)
            .join(League, League.id == Match.league_id)
            .join(Season, Season.id == Match.season_id)
            .where(Match.id.in_(list(by_match)))
        )
    ).all()
    kickoff_by_match = {match.id: match.kickoff_time for match, _, _ in fields}
    match_rows = [
        MatchRow(
            match_id=match.id,
            kickoff_time=match.kickoff_time,
            home_team_id=match.home_team_id,
            away_team_id=match.away_team_id,
            league_code=code,
            season_label=label,
        )
        for match, code, label in fields
    ]
    priors = await load_hkjc_priors(session, match_rows, 0)

    bets_allowed = 0
    no_bets = 0
    total_stake = 0.0
    for match_id, predictions in by_match.items():
        prior = priors.get(match_id)
        if prior is not None and prior.had_odds and prior.had_probs:
            prior_available = True
            odds_by_outcome = prior.had_odds
            implied_by_outcome = prior.had_probs
        else:
            prior_available = False
            odds_by_outcome = None
            implied_by_outcome = None
        model_probs = {prediction.outcome: prediction.prob for prediction in predictions}
        kickoff = kickoff_by_match.get(match_id)
        winner: str | None = None
        for prediction in predictions:
            odds = odds_by_outcome.get(prediction.outcome) if odds_by_outcome else None
            implied = implied_by_outcome.get(prediction.outcome) if implied_by_outcome else None
            fraction = kelly_fraction(prediction.prob, odds) if odds is not None else None
            execution_edge = prediction.prob - implied if implied is not None else None
            stake = (
                _size_stake(settings.ledger_initial_bankroll, fraction, settings)
                if fraction is not None
                else None
            )
            action, reason = _verdict(
                _CandidateFacts(
                    prior_available=prior_available,
                    outcome=prediction.outcome,
                    odds=odds,
                    implied=implied,
                    execution_edge=execution_edge,
                    kelly=fraction,
                    stake=stake,
                    winner=winner,
                ),
                settings,
            )
            if action == ACTION_BET:
                winner = prediction.outcome
                bets_allowed += 1
                total_stake += stake or 0.0
            else:
                no_bets += 1
            session.add(
                AgentDecision(
                    run_id=run_id,
                    match_id=match_id,
                    model_version_id=prediction.model_version_id,
                    target=prediction.target,
                    outcome=prediction.outcome,
                    action=action,
                    stake=stake if action == ACTION_BET else None,
                    odds=odds,
                    edge=execution_edge,
                    signal_edge=prediction.edge,
                    confidence=None,
                    agent=AGENT_RISK,
                    reason=reason,
                    evaluated_at=evaluated_at,
                    input_snapshot={
                        "evaluated_at": evaluated_at.isoformat(),
                        "kickoff_time": kickoff.isoformat() if kickoff is not None else None,
                        "match_id": match_id,
                        "prediction_id": prediction.id,
                        "model_version_id": prediction.model_version_id,
                        "target": prediction.target,
                        "outcome": prediction.outcome,
                        "model_prob": prediction.prob,
                        "model_probs": model_probs,
                        "signal_edge": prediction.edge,
                        "prediction_implied_prob": prediction.implied_prob,
                        "execution_odds": odds,
                        "execution_implied_prob": implied,
                        "market_odds": odds_by_outcome,
                        "market_probs": implied_by_outcome,
                        "execution_edge": execution_edge,
                        "kelly_fraction": fraction,
                        "stake_fraction": (
                            None
                            if fraction is None
                            else fraction * settings.ledger_kelly_multiplier
                        ),
                        "stake": stake if action == ACTION_BET else None,
                    },
                )
            )
    await session.flush()
    return RiskRunSummary(
        run_id=run_id,
        matches_considered=len(by_match),
        candidates_evaluated=len(candidates),
        bets_allowed=bets_allowed,
        no_bets=no_bets,
        total_stake=total_stake,
    )
