from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from packages.db.base import (
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_type,
    json_type,
)
from packages.domain.enums import AvailabilityBasis, MatchStatus


class Competition(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "competitions"

    code: Mapped[str] = mapped_column(String(24), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    country: Mapped[str] = mapped_column(String(64), nullable=False)
    is_cup: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    understat_slug: Mapped[str | None] = mapped_column(String(32))
    football_data_code: Mapped[str] = mapped_column(String(8), nullable=False)


class Team(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "teams"

    slug: Mapped[str] = mapped_column(String(96), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    short_name: Mapped[str] = mapped_column(String(48), nullable=False)
    country: Mapped[str] = mapped_column(String(64), nullable=False)
    understat_id: Mapped[str | None] = mapped_column(String(32))
    fotmob_id: Mapped[int | None] = mapped_column(Integer)
    football_data_id: Mapped[int | None] = mapped_column(Integer)


class Player(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "players"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("teams.id", ondelete="SET NULL")
    )
    position: Mapped[str | None] = mapped_column(String(32))
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    fotmob_id: Mapped[int | None] = mapped_column(Integer, unique=True)
    understat_id: Mapped[str | None] = mapped_column(String(32))
    fpl_id: Mapped[int | None] = mapped_column(Integer, unique=True)


class Match(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "matches"
    __table_args__ = (
        UniqueConstraint(
            "competition_id",
            "season",
            "home_team_id",
            "away_team_id",
            "kickoff_at",
            name="uq_matches_natural_key",
        ),
    )

    competition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("competitions.id", ondelete="RESTRICT"), nullable=False
    )
    season: Mapped[str] = mapped_column(String(9), nullable=False)
    kickoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    home_team_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False
    )
    away_team_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[MatchStatus] = mapped_column(enum_type(MatchStatus, 24), nullable=False)
    matchday: Mapped[int | None] = mapped_column(Integer)
    home_goals_90: Mapped[int | None] = mapped_column(Integer)
    away_goals_90: Mapped[int | None] = mapped_column(Integer)
    home_goals_final: Mapped[int | None] = mapped_column(Integer)
    away_goals_final: Mapped[int | None] = mapped_column(Integer)
    result_available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_availability_basis: Mapped[AvailabilityBasis | None] = mapped_column(
        enum_type(AvailabilityBasis, 32)
    )
    result_evidence_grade: Mapped[AvailabilityBasis | None] = mapped_column(
        enum_type(AvailabilityBasis, 32)
    )
    source_match_ids: Mapped[dict[str, str]] = mapped_column(
        json_type(), default=dict, nullable=False
    )
    coverage_flags: Mapped[list[str]] = mapped_column(
        json_type(), default=list, nullable=False
    )
