from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class TeamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name_en: str
    name_ch: str | None = None


class MatchOut(BaseModel):
    id: int
    league_code: str
    league_name: str
    kickoff_time: datetime
    status: str
    home_team: TeamOut
    away_team: TeamOut
    venue: str | None = None
    round: str | None = None
    hkjc_match_id: str | None = None


class OddsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    odds_type: str
    inplay: bool
    source: str
    captured_at: datetime
    snapshot_bucket: datetime
    payload: dict[str, Any]


class ResultOut(BaseModel):
    match_id: int
    home_score: int
    away_score: int
    ttl_corner: int | None = None
    source: str
    confirmed: bool
    payout_confirmed: bool
    confirmed_at: datetime | None = None
    kickoff_time: datetime
    league_code: str
    home_team: TeamOut
    away_team: TeamOut


class PredictionOut(BaseModel):
    id: int
    match_id: int
    target: str
    outcome: str
    model_version_id: int
    prob: float
    implied_prob: float | None
    edge: float | None
    fair_odds: float
    market_odds: float | None
    recommended_fraction: float | None
    kickoff_time: datetime
    league_code: str
    home_team: str
    away_team: str


class ModelOut(BaseModel):
    id: int
    target: str
    algorithm: str
    status: str
    metrics: dict
    artifact_path: str
    created_at: datetime
    promoted_at: datetime | None


class BetOut(BaseModel):
    id: int
    match_id: int
    target: str
    outcome: str
    model_version_id: int
    line: float | None
    odds: float
    stake: float
    bankroll_at_place: float
    edge: float | None
    kelly_multiplier: float
    status: str
    placed_at: datetime
    settled_at: datetime | None
    payout: float | None
    profit: float | None
    kickoff_time: datetime
    league_code: str
    home_team: str
    away_team: str


class BetSummary(BaseModel):
    initial_bankroll: float
    bankroll: float
    n_bets: int
    n_settled: int
    n_open: int
    stakes_total: float
    open_stakes: float
    realized_profit: float
    roi: float
    yield_pct: float


class EquityPointOut(BaseModel):
    t: datetime | None
    bankroll: float
