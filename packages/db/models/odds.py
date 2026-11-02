from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from packages.db.base import (
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_type,
)
from packages.domain.enums import AvailabilityBasis, MarketType, Side, SnapshotKind


class OddsSnapshot(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "odds_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "match_id",
            "market",
            "snapshot_kind",
            "snapshot_at",
            name="uq_odds_snapshots_match_market_kind_at",
        ),
    )

    match_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), nullable=False
    )
    market: Mapped[MarketType] = mapped_column(enum_type(MarketType, 16), nullable=False)
    snapshot_kind: Mapped[SnapshotKind] = mapped_column(
        enum_type(SnapshotKind, 16), nullable=False
    )
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_update_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    query_version: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    raw_payload_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("raw_payloads.id", ondelete="SET NULL")
    )
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)


class MarketLine(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "market_lines"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_id",
            "condition_raw",
            "side",
            name="uq_market_lines_snapshot_condition_side",
        ),
    )

    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("odds_snapshots.id", ondelete="CASCADE"), nullable=False
    )
    odds_type: Mapped[MarketType] = mapped_column(
        enum_type(MarketType, 16), nullable=False
    )
    condition_raw: Mapped[str] = mapped_column(String(24), nullable=False)
    line_index: Mapped[int] = mapped_column(Integer, nullable=False)
    side: Mapped[Side] = mapped_column(enum_type(Side, 8), nullable=False)
    odds_decimal: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    pool_status: Mapped[str] = mapped_column(String(32), nullable=False)
    line_status: Mapped[str] = mapped_column(String(32), nullable=False)
    is_main: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    offer_early_settlement: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    source_update_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    availability_basis: Mapped[AvailabilityBasis | None] = mapped_column(
        enum_type(AvailabilityBasis, 32)
    )
