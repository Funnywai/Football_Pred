"""Champion serving: build features, predict, upsert prediction rows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import exp, isinf, isnan, log

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import League, Match, MatchFeature, ModelVersion, Prediction, Season
from app.ml.dataset import load_market_priors, load_training_rows
from app.ml.features import FEATURE_VERSION, FeatureRow, MarketPrior, MatchRow, build_feature_rows
from app.ml.labels import is_whole_or_half
from app.ml.models import (
    CALIBRATION_EPSILON,
    TARGET_1X2,
    TARGET_HANDICAP,
    TrainedModel,
    load_artifact,
    predict_proba,
)
from app.ml.registry import get_champion
from app.ml.value import edge, fair_odds, is_value, kelly_fraction

OUTCOMES_1X2 = ("H", "D", "A")
OUTCOMES_HANDICAP = ("H", "A")

_LOG_EPSILON = 1e-12


@dataclass
class Champion:
    version: ModelVersion
    model: TrainedModel | None


@dataclass(frozen=True)
class UpcomingMatch:
    match_id: int
    kickoff_time: datetime
    home_team_id: int
    away_team_id: int
    league_code: str
    season_label: str


async def load_champion(session: AsyncSession, target: str) -> Champion | None:
    version = await get_champion(session, target)
    if version is None:
        return None
    return Champion(version=version, model=load_artifact(version.artifact_path))


async def load_upcoming_matches(
    session: AsyncSession, settings: Settings, now: datetime
) -> list[UpcomingMatch]:
    horizon = now + timedelta(hours=settings.ml_predict_lookahead_hours)
    stmt = (
        select(Match, League.code, Season.label)
        .join(League, League.id == Match.league_id)
        .join(Season, Season.id == Match.season_id)
        .where(Match.status == "scheduled")
        .where(Match.kickoff_time >= now)
        .where(Match.kickoff_time <= horizon)
        .where(League.code.in_(settings.league_whitelist))
        .order_by(Match.kickoff_time, Match.id)
    )
    return [
        UpcomingMatch(
            match_id=match.id,
            kickoff_time=match.kickoff_time,
            home_team_id=match.home_team_id,
            away_team_id=match.away_team_id,
            league_code=code,
            season_label=season_label,
        )
        for match, code, season_label in (await session.execute(stmt)).all()
    ]


def blend_probs(
    model_probs: dict[str, float],
    prior_probs: dict[str, float] | None,
    weight: float,
) -> dict[str, float]:
    """Blend model probabilities toward the de-vigged market prior in logit space.

    ``p_blend = softmax(w * log(p_model) + (1 - w) * log(p_prior))`` over the
    shared outcomes, i.e. a weighted geometric mean. Probabilities are clamped
    away from zero before the log and re-normalised after the softmax. When the
    prior is missing (or does not cover every model outcome) or ``weight >= 1``,
    the pure model probabilities are returned unchanged.
    """
    if (
        prior_probs is None
        or weight >= 1.0
        or any(outcome not in prior_probs for outcome in model_probs)
    ):
        return dict(model_probs)
    logits = {
        outcome: weight * log(max(model_probs[outcome], _LOG_EPSILON))
        + (1.0 - weight) * log(max(prior_probs[outcome], _LOG_EPSILON))
        for outcome in model_probs
    }
    peak = max(logits.values())
    weights = {outcome: exp(value - peak) for outcome, value in logits.items()}
    total = sum(weights.values())
    return {outcome: value / total for outcome, value in weights.items()}


def _rows_for(
    upcoming: UpcomingMatch,
    champion: Champion,
    target: str,
    prob_map: dict[str, float],
    prior: MarketPrior | None,
    threshold: float,
    blend_weight: float,
    exec_edge_buffer: float,
) -> list[Prediction]:
    prior_probs: dict[str, float] | None = None
    if target == TARGET_1X2 and prior is not None:
        prior_probs = prior.had_probs
    elif target == TARGET_HANDICAP and prior is not None:
        prior_probs = prior.hdc_probs
    blended_map = blend_probs(prob_map, prior_probs, blend_weight)
    rows: list[Prediction] = []
    for outcome in prob_map:
        blended_prob = blended_map[outcome]
        fair_prob = market_odds = None
        if target == TARGET_1X2 and prior is not None and prior.had_probs is not None:
            fair_prob = prior.had_probs.get(outcome)
            market_odds = (prior.had_odds or {}).get(outcome)
        elif target == TARGET_HANDICAP and prior is not None and prior.hdc_probs is not None:
            fair_prob = prior.hdc_probs.get(outcome)
            market_odds = (prior.hdc_odds or {}).get(outcome)
        edge_value = edge(blended_prob, fair_prob) if fair_prob is not None else None
        fraction = 0.0
        if (
            market_odds is not None
            and edge_value is not None
            and is_value(edge_value, threshold)
            and blended_prob * market_odds > 1.0 + exec_edge_buffer
        ):
            fraction = kelly_fraction(blended_prob, market_odds)
        rows.append(
            Prediction(
                match_id=upcoming.match_id,
                target=target,
                outcome=outcome,
                model_version_id=champion.version.id,
                prob=blended_prob,
                implied_prob=fair_prob,
                edge=edge_value,
                fair_odds=fair_odds(max(blended_prob, CALIBRATION_EPSILON)),
                market_odds=market_odds,
                recommended_fraction=fraction,
            )
        )
    return rows


def build_prediction_rows(
    upcoming: UpcomingMatch,
    feature_row: FeatureRow,
    champion_1x2: Champion | None,
    champion_handicap: Champion | None,
    prior: MarketPrior | None,
    threshold: float,
    blend_weight: float = 1.0,
    exec_edge_buffer: float = 0.0,
    probs_1x2: dict[str, float] | None = None,
    probs_handicap: dict[str, float] | None = None,
) -> list[Prediction]:
    """Build prediction rows. ``probs_*`` may be supplied directly (tests) or are
    computed from the champion models when omitted. ``blend_weight`` mixes the
    model toward the de-vigged prior (1.0 = pure model) and ``exec_edge_buffer``
    is the safety margin required on ``prob * market_odds`` before staking."""
    rows: list[Prediction] = []
    if champion_1x2 is not None:
        if probs_1x2 is None:
            assert champion_1x2.model is not None
            values = predict_proba(champion_1x2.model, [feature_row.features])[0]
            probs_1x2 = {outcome: float(values[i]) for i, outcome in enumerate(OUTCOMES_1X2)}
        rows.extend(
            _rows_for(
                upcoming,
                champion_1x2,
                TARGET_1X2,
                probs_1x2,
                prior,
                threshold,
                blend_weight,
                exec_edge_buffer,
            )
        )
    if champion_handicap is not None and prior is not None and prior.hdc_line is not None:
        if not is_whole_or_half(prior.hdc_line):
            return rows
        if probs_handicap is None:
            assert champion_handicap.model is not None
            home_prob = float(predict_proba(champion_handicap.model, [feature_row.features])[0])
            probs_handicap = {"H": home_prob, "A": 1.0 - home_prob}
        rows.extend(
            _rows_for(
                upcoming,
                champion_handicap,
                TARGET_HANDICAP,
                probs_handicap,
                prior,
                threshold,
                blend_weight,
                exec_edge_buffer,
            )
        )
    return rows


async def upsert_predictions(session: AsyncSession, rows: list[Prediction]) -> int:
    count = 0
    for row in rows:
        existing = (
            await session.execute(
                select(Prediction).where(
                    Prediction.match_id == row.match_id,
                    Prediction.target == row.target,
                    Prediction.outcome == row.outcome,
                    Prediction.model_version_id == row.model_version_id,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(row)
        else:
            existing.prob = row.prob
            existing.implied_prob = row.implied_prob
            existing.edge = row.edge
            existing.fair_odds = row.fair_odds
            existing.market_odds = row.market_odds
            existing.recommended_fraction = row.recommended_fraction
        count += 1
    await session.flush()
    return count


def _json_safe(features: dict[str, float]) -> dict[str, float | None]:
    """Store NaN/Inf as null: JSON has no NaN/Infinity token and Postgres rejects both
    for JSONB, while the feature builder uses NaN to mark a missing market prior."""
    return {
        key: None if isinstance(value, float) and (isnan(value) or isinf(value)) else value
        for key, value in features.items()
    }


async def upsert_feature(session: AsyncSession, match_id: int, features: dict[str, float]) -> None:
    payload = _json_safe(features)
    existing = (
        await session.execute(
            select(MatchFeature).where(
                MatchFeature.match_id == match_id,
                MatchFeature.feature_version == FEATURE_VERSION,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(
            MatchFeature(match_id=match_id, feature_version=FEATURE_VERSION, features=payload)
        )
    else:
        existing.features = payload
        existing.built_at = datetime.now(UTC)
    await session.flush()


async def predict_upcoming_matches(
    session: AsyncSession,
    upcoming: list[UpcomingMatch],
    champion_1x2: Champion | None,
    champion_handicap: Champion | None,
    settings: Settings,
) -> list[Prediction]:
    """Predict every upcoming match from one history load and one feature pass.

    ``build_feature_rows`` applies results only after each kickoff group, so a
    match at kickoff k sees strictly-earlier state even though ``history`` was
    loaded up to the latest upcoming kickoff.
    """
    if not upcoming:
        return []
    target_rows = [
        MatchRow(
            match_id=match.match_id,
            kickoff_time=match.kickoff_time,
            home_team_id=match.home_team_id,
            away_team_id=match.away_team_id,
            league_code=match.league_code,
            season_label=match.season_label,
        )
        for match in upcoming
    ]
    max_kickoff = max(match.kickoff_time for match in upcoming)
    history = await load_training_rows(session, settings, before=max_kickoff)
    priors = await load_market_priors(session, target_rows, settings.ml_prior_lead_hours)
    feature_rows = {
        row.match_id: row for row in build_feature_rows([*history, *target_rows], priors)
    }
    rows: list[Prediction] = []
    for match in upcoming:
        feature_row = feature_rows[match.match_id]
        await upsert_feature(session, match.match_id, feature_row.features)
        rows.extend(
            build_prediction_rows(
                match,
                feature_row,
                champion_1x2,
                champion_handicap,
                priors[match.match_id],
                settings.ml_value_edge_threshold,
                settings.ml_blend_weight,
                settings.ml_exec_edge_buffer,
            )
        )
    return rows


async def predict_match(
    session: AsyncSession,
    upcoming: UpcomingMatch,
    champion_1x2: Champion | None,
    champion_handicap: Champion | None,
    settings: Settings,
) -> list[Prediction]:
    target_row = MatchRow(
        match_id=upcoming.match_id,
        kickoff_time=upcoming.kickoff_time,
        home_team_id=upcoming.home_team_id,
        away_team_id=upcoming.away_team_id,
        league_code=upcoming.league_code,
        season_label=upcoming.season_label,
    )
    history = await load_training_rows(session, settings, before=upcoming.kickoff_time)
    prior = (await load_market_priors(session, [target_row], settings.ml_prior_lead_hours))[
        upcoming.match_id
    ]
    feature_rows = build_feature_rows([*history, target_row], {upcoming.match_id: prior})
    feature_row = next(row for row in feature_rows if row.match_id == upcoming.match_id)
    await upsert_feature(session, upcoming.match_id, feature_row.features)
    return build_prediction_rows(
        upcoming,
        feature_row,
        champion_1x2,
        champion_handicap,
        prior,
        settings.ml_value_edge_threshold,
        settings.ml_blend_weight,
        settings.ml_exec_edge_buffer,
    )
