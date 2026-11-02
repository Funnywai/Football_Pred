from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from packages.db.base import (
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_type,
)
from packages.domain.enums import (
    BetStatus,
    MarketType,
    ReservationStatus,
    SettlementSource,
    Side,
)


class PaperBet(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "paper_bets"
    __table_args__ = (
        UniqueConstraint(
            "decision_slot_key",
            name="uq_paper_bets_decision_slot_key",
        ),
    )

    match_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("matches.id", ondelete="RESTRICT"), nullable=False
    )
    market: Mapped[MarketType] = mapped_column(enum_type(MarketType, 16), nullable=False)
    line_key: Mapped[str] = mapped_column(String(24), nullable=False)
    selection: Mapped[Side] = mapped_column(enum_type(Side, 8), nullable=False)
    odds_decimal: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    stake: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    bankroll_before: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    placed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    odds_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("odds_snapshots.id", ondelete="SET NULL")
    )
    closing_odds_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("odds_snapshots.id", ondelete="SET NULL")
    )
    status: Mapped[BetStatus] = mapped_column(enum_type(BetStatus, 32), nullable=False)
    analysis_run_key: Mapped[str] = mapped_column(String(256), index=True, nullable=False)
    decision_slot_key: Mapped[str] = mapped_column(String(256), index=True, nullable=False)
    bet_intent_key: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    decision_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Settlement(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "settlements"

    paper_bet_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("paper_bets.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    result_status: Mapped[BetStatus] = mapped_column(
        enum_type(BetStatus, 32), nullable=False
    )
    payout: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    payout_unrounded: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)
    clv: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    brier_score: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    settled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    hk_result_ref: Mapped[str | None] = mapped_column(String(128))
    provisional: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source: Mapped[SettlementSource] = mapped_column(
        enum_type(SettlementSource, 32), nullable=False
    )


class BankrollAccount(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "bankroll_accounts"

    account_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    bankroll_balance: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    reserved_stake: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal(0), nullable=False
    )


class BankrollReservation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "bankroll_reservations"

    bet_intent_key: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[ReservationStatus] = mapped_column(
        enum_type(ReservationStatus, 16), nullable=False
    )
