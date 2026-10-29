from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UtcDateTime


def _json_type() -> JSONB:
    return JSONB().with_variant(JSON, "sqlite")


def _string_array_type() -> ARRAY:
    return ARRAY(Text).with_variant(JSON, "sqlite")


class League(Base):
    __tablename__ = "leagues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name_en: Mapped[str] = mapped_column(String(120), nullable=False)
    name_ch: Mapped[str | None] = mapped_column(String(120))
    country: Mapped[str | None] = mapped_column(String(60))
    hkjc_tourn_id: Mapped[str | None] = mapped_column(String(40), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    seasons: Mapped[list["Season"]] = relationship(back_populates="league")


class Season(Base):
    __tablename__ = "seasons"
    __table_args__ = (UniqueConstraint("league_id", "label", name="uq_seasons_league_label"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id"), nullable=False)
    label: Mapped[str] = mapped_column(String(20), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)

    league: Mapped[League] = relationship(back_populates="seasons")


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name_en: Mapped[str] = mapped_column(String(120), nullable=False)
    name_ch: Mapped[str | None] = mapped_column(String(120))
    hkjc_team_id: Mapped[str | None] = mapped_column(String(40), unique=True)
    aliases: Mapped[list[str]] = mapped_column(_string_array_type(), nullable=False, default=list)
    external_ids: Mapped[dict] = mapped_column(_json_type(), nullable=False, default=dict)


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (
        UniqueConstraint(
            "season_id",
            "home_team_id",
            "away_team_id",
            "kickoff_time",
            name="uq_matches_natural",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"), nullable=False)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id"), nullable=False)
    hkjc_match_id: Mapped[str | None] = mapped_column(String(40), unique=True)
    kickoff_time: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="scheduled")
    home_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    away_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    venue: Mapped[str | None] = mapped_column(String(160))
    round: Mapped[str | None] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    season: Mapped[Season] = relationship()
    league: Mapped[League] = relationship()
    home_team: Mapped[Team] = relationship(foreign_keys=[home_team_id])
    away_team: Mapped[Team] = relationship(foreign_keys=[away_team_id])
    result: Mapped["Result | None"] = relationship(back_populates="match", uselist=False)


class OddsSnapshot(Base):
    __tablename__ = "odds_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "match_id",
            "odds_type",
            "inplay",
            "snapshot_bucket",
            name="uq_odds_snapshots_bucket",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), nullable=False, index=True)
    captured_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    snapshot_bucket: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    inplay: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    odds_type: Mapped[str] = mapped_column(String(8), nullable=False)
    payload: Mapped[dict] = mapped_column(_json_type(), nullable=False)

    match: Mapped[Match] = relationship()


class Result(Base):
    __tablename__ = "results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), unique=True, nullable=False)
    home_score: Mapped[int] = mapped_column(Integer, nullable=False)
    away_score: Mapped[int] = mapped_column(Integer, nullable=False)
    ttl_corner: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    payout_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    raw: Mapped[dict] = mapped_column(_json_type(), nullable=False, default=dict)

    match: Mapped[Match] = relationship(back_populates="result")


class MatchStat(Base):
    """Per-match shot statistics from an external source.

    ``available_at`` is the leakage guard: a feature row may only use this match's
    stats when ``available_at <= kickoff - 48h``. football-data.co.uk publishes
    after the match, so the backfill stores ``kickoff + 24h`` conservatively.
    """

    __tablename__ = "match_stats"
    __table_args__ = (
        UniqueConstraint("match_id", "source", name="uq_match_stats_match_source"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_id: Mapped[int] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    home_shots: Mapped[int | None] = mapped_column(Integer)
    away_shots: Mapped[int | None] = mapped_column(Integer)
    home_sot: Mapped[int | None] = mapped_column(Integer)
    away_sot: Mapped[int | None] = mapped_column(Integer)
    home_corners: Mapped[int | None] = mapped_column(Integer)
    away_corners: Mapped[int | None] = mapped_column(Integer)
    home_xg: Mapped[float | None] = mapped_column(Float)
    away_xg: Mapped[float | None] = mapped_column(Float)
    available_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, server_default=func.now()
    )


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job: Mapped[str] = mapped_column(String(40), nullable=False)
    started_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    records_upserted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text)


class ModelVersion(Base):
    __tablename__ = "model_versions"
    __table_args__ = (
        Index(
            "uq_model_versions_champion_target",
            "target",
            unique=True,
            postgresql_where=text("status = 'champion'"),
            sqlite_where=text("status = 'champion'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    algorithm: Mapped[str] = mapped_column(String(40), nullable=False)
    params: Mapped[dict] = mapped_column(_json_type(), nullable=False, default=dict)
    metrics: Mapped[dict] = mapped_column(_json_type(), nullable=False, default=dict)
    artifact_path: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="challenger")
    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, server_default=func.now()
    )
    promoted_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class Prediction(Base):
    __tablename__ = "predictions"
    __table_args__ = (
        UniqueConstraint(
            "match_id", "target", "outcome", "model_version_id", name="uq_predictions_natural"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), nullable=False, index=True)
    target: Mapped[str] = mapped_column(String(20), nullable=False)
    outcome: Mapped[str] = mapped_column(String(10), nullable=False)
    model_version_id: Mapped[int] = mapped_column(
        ForeignKey("model_versions.id"), nullable=False
    )
    prob: Mapped[float] = mapped_column(Float, nullable=False)
    implied_prob: Mapped[float | None] = mapped_column(Float, nullable=True)
    edge: Mapped[float | None] = mapped_column(Float, nullable=True)
    fair_odds: Mapped[float] = mapped_column(Float, nullable=False)
    market_odds: Mapped[float | None] = mapped_column(Float, nullable=True)
    recommended_fraction: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, server_default=func.now()
    )


class MatchFeature(Base):
    __tablename__ = "match_features"
    __table_args__ = (
        UniqueConstraint("match_id", "feature_version", name="uq_match_features_natural"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), nullable=False, index=True)
    feature_version: Mapped[str] = mapped_column(String(40), nullable=False)
    built_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, server_default=func.now()
    )
    features: Mapped[dict] = mapped_column(_json_type(), nullable=False, default=dict)


class ClvRecord(Base):
    """Closing-line value for one prediction, computed after kickoff.

    One row per prediction (unique ``prediction_id``); ``label`` stays nullable
    until a confirmed result exists, so CLV can be recorded before settlement.
    """

    __tablename__ = "clv_records"
    __table_args__ = (
        Index("ix_clv_records_model_version_computed", "model_version_id", "computed_at"),
        Index("ix_clv_records_source_computed", "source", "computed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    prediction_id: Mapped[int] = mapped_column(
        ForeignKey("predictions.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), nullable=False, index=True)
    model_version_id: Mapped[int] = mapped_column(
        ForeignKey("model_versions.id"), nullable=False, index=True
    )
    target: Mapped[str] = mapped_column(String(20), nullable=False)
    outcome: Mapped[str] = mapped_column(String(10), nullable=False)
    model_prob: Mapped[float] = mapped_column(Float, nullable=False)
    closing_prob: Mapped[float] = mapped_column(Float, nullable=False)
    closing_odds: Mapped[float | None] = mapped_column(Float, nullable=True)
    edge: Mapped[float] = mapped_column(Float, nullable=False)
    beat: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_value: Mapped[bool] = mapped_column(Boolean, nullable=False)
    label: Mapped[str | None] = mapped_column(String(10), nullable=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, server_default=func.now()
    )


class LedgerBet(Base):
    __tablename__ = "ledger_bets"
    __table_args__ = (
        UniqueConstraint("match_id", "target", "outcome", name="uq_ledger_bets_natural"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), nullable=False, index=True)
    target: Mapped[str] = mapped_column(String(20), nullable=False)
    outcome: Mapped[str] = mapped_column(String(10), nullable=False)
    model_version_id: Mapped[int] = mapped_column(
        ForeignKey("model_versions.id"), nullable=False
    )
    line: Mapped[float | None] = mapped_column(Float, nullable=True)
    odds: Mapped[float] = mapped_column(Float, nullable=False)
    stake: Mapped[float] = mapped_column(Float, nullable=False)
    bankroll_at_place: Mapped[float] = mapped_column(Float, nullable=False)
    edge: Mapped[float | None] = mapped_column(Float, nullable=True)
    kelly_multiplier: Mapped[float] = mapped_column(Float, nullable=False)
    result_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    placed_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, server_default=func.now()
    )
    settled_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    payout: Mapped[float | None] = mapped_column(Float, nullable=True)
    profit: Mapped[float | None] = mapped_column(Float, nullable=True)


class AgentDecision(Base):
    """Paper-only audit trail for every deterministic agent candidate.

    One row is written per candidate outcome (both ``bet`` and ``no_bet``), so a
    later A/B/C/D comparison can reconstruct exactly what the agent saw and why
    it acted. ``input_snapshot`` carries the timestamped inputs; nothing here is
    a real bet and no ledger row is ever created by the risk agent.
    """

    __tablename__ = "agent_decisions"
    __table_args__ = (
        Index("ix_agent_decisions_match_evaluated", "match_id", "evaluated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), nullable=False, index=True)
    model_version_id: Mapped[int] = mapped_column(
        ForeignKey("model_versions.id"), nullable=False
    )
    target: Mapped[str] = mapped_column(String(20), nullable=False)
    outcome: Mapped[str] = mapped_column(String(10), nullable=False)
    action: Mapped[str] = mapped_column(String(10), nullable=False)
    stake: Mapped[float | None] = mapped_column(Float, nullable=True)
    odds: Mapped[float | None] = mapped_column(Float, nullable=True)
    edge: Mapped[float | None] = mapped_column(Float, nullable=True)
    signal_edge: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    agent: Mapped[str] = mapped_column(
        String(20), nullable=False, default="risk", server_default="risk"
    )
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    input_snapshot: Mapped[dict] = mapped_column(_json_type(), nullable=False, default=dict)
    evaluated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, server_default=func.now(), index=True
    )


class AgentBet(Base):
    """Paper-only agent ledger, kept apart from production and shadow books.

    One bet per ``(variant, match_id)`` so the A-only baseline and the later
    A+B+C treatment can be compared on the same matches and prices. ``run_id``
    points back at the ``agent_decisions`` run that produced the bet.
    """

    __tablename__ = "agent_bets"
    __table_args__ = (
        UniqueConstraint("variant", "match_id", name="uq_agent_bets_variant_match"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), nullable=False, index=True)
    model_version_id: Mapped[int] = mapped_column(
        ForeignKey("model_versions.id"), nullable=False
    )
    target: Mapped[str] = mapped_column(String(20), nullable=False)
    outcome: Mapped[str] = mapped_column(String(10), nullable=False)
    variant: Mapped[str] = mapped_column(String(10), nullable=False)
    line: Mapped[float | None] = mapped_column(Float, nullable=True)
    odds: Mapped[float] = mapped_column(Float, nullable=False)
    stake: Mapped[float] = mapped_column(Float, nullable=False)
    bankroll_at_place: Mapped[float] = mapped_column(Float, nullable=False)
    edge: Mapped[float | None] = mapped_column(Float, nullable=True)
    kelly_multiplier: Mapped[float] = mapped_column(Float, nullable=False)
    result_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    placed_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, server_default=func.now()
    )
    settled_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    payout: Mapped[float | None] = mapped_column(Float, nullable=True)
    profit: Mapped[float | None] = mapped_column(Float, nullable=True)


class AnalystBrief(Base):
    """Lineups-only B analyst snapshot for one run and match.

    One row per ``(run_id, match_id, source)`` keeps the exact facts, gaps, and
    raw provider payload the C decision agent used. This table is audit data
    only; it never carries an execution price or a real bet.
    """

    __tablename__ = "analyst_briefs"
    __table_args__ = (
        UniqueConstraint("run_id", "match_id", "source", name="uq_analyst_briefs_run_match_source"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, server_default=func.now()
    )
    facts: Mapped[dict[str, object]] = mapped_column(
        _json_type(), nullable=False, default=dict
    )
    uncertainties: Mapped[list[str]] = mapped_column(
        _json_type(), nullable=False, default=list
    )
    missing: Mapped[list[str]] = mapped_column(_json_type(), nullable=False, default=list)
    trust_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_snapshot: Mapped[dict[str, object]] = mapped_column(
        _json_type(), nullable=False, default=dict
    )


class ShadowLedgerBet(Base):
    """Paper-only shadow book: at most one bet per match, never mixed with production."""

    __tablename__ = "shadow_ledger_bets"
    __table_args__ = (
        UniqueConstraint("match_id", name="uq_shadow_ledger_bets_match"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), nullable=False, index=True)
    target: Mapped[str] = mapped_column(String(20), nullable=False)
    outcome: Mapped[str] = mapped_column(String(10), nullable=False)
    model_version_id: Mapped[int] = mapped_column(
        ForeignKey("model_versions.id"), nullable=False
    )
    line: Mapped[float | None] = mapped_column(Float, nullable=True)
    odds: Mapped[float] = mapped_column(Float, nullable=False)
    stake: Mapped[float] = mapped_column(Float, nullable=False)
    bankroll_at_place: Mapped[float] = mapped_column(Float, nullable=False)
    edge: Mapped[float | None] = mapped_column(Float, nullable=True)
    kelly_multiplier: Mapped[float] = mapped_column(Float, nullable=False)
    result_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    placed_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, server_default=func.now()
    )
    settled_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    payout: Mapped[float | None] = mapped_column(Float, nullable=True)
    profit: Mapped[float | None] = mapped_column(Float, nullable=True)
