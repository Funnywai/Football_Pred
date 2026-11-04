from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from packages.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class DecisionLog(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__: str = "decision_logs"

    experiment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ledger_experiments.id", ondelete="SET NULL"), index=True
    )
    match_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    decision_slot_key: Mapped[str] = mapped_column(
        String(256), unique=True, nullable=False
    )
    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("odds_snapshots.id", ondelete="SET NULL")
    )
    decision_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    model_version: Mapped[str | None] = mapped_column(String(64))
    prediction_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    paper_bet_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("paper_bets.id", ondelete="SET NULL")
    )
