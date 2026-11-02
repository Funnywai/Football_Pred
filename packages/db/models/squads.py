from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from packages.db.base import (
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_type,
    json_type,
)
from packages.domain.enums import AvailabilityBasis, AvailabilityStatus, LineupType


class Lineup(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "lineups"
    __table_args__ = (
        UniqueConstraint(
            "match_id",
            "team_id",
            "lineup_type",
            "source",
            name="uq_lineups_match_team_type_source",
        ),
    )

    match_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), nullable=False
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False
    )
    lineup_type: Mapped[LineupType] = mapped_column(
        enum_type(LineupType, 16), nullable=False
    )
    formation: Mapped[str | None] = mapped_column(String(16))
    starters: Mapped[list[dict[str, object]]] = mapped_column(
        json_type(), default=list, nullable=False
    )
    subs: Mapped[list[dict[str, object]]] = mapped_column(
        json_type(), default=list, nullable=False
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(512))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    availability_basis: Mapped[AvailabilityBasis | None] = mapped_column(
        enum_type(AvailabilityBasis, 32)
    )
    evidence_grade: Mapped[AvailabilityBasis | None] = mapped_column(
        enum_type(AvailabilityBasis, 32)
    )
    inferred: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Availability(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "availability"
    __table_args__ = (
        UniqueConstraint(
            "match_id",
            "team_id",
            "player_id",
            "source",
            name="uq_availability_match_team_player_source",
        ),
    )

    match_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), nullable=False
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False
    )
    player_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("players.id", ondelete="SET NULL")
    )
    status: Mapped[AvailabilityStatus] = mapped_column(
        enum_type(AvailabilityStatus, 16), nullable=False
    )
    reason: Mapped[str | None] = mapped_column(String(256))
    expected_return: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(512))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    availability_basis: Mapped[AvailabilityBasis | None] = mapped_column(
        enum_type(AvailabilityBasis, 32)
    )
    evidence_grade: Mapped[AvailabilityBasis | None] = mapped_column(
        enum_type(AvailabilityBasis, 32)
    )
