from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
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
    json_type,
)
from packages.domain.enums import MarketType, Side


class ModelPrediction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__: str = "model_predictions"
    __table_args__: tuple[UniqueConstraint, Index] = (
        UniqueConstraint(
            "analysis_run_key",
            "market",
            "line_key",
            "outcome",
            name="uq_model_predictions_analysis_run_key",
        ),
        Index(
            "ix_model_predictions_match_id_decision_at",
            "match_id",
            "decision_at",
        ),
    )

    match_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    market: Mapped[MarketType] = mapped_column(enum_type(MarketType, 16), nullable=False)
    line_key: Mapped[str] = mapped_column(String(24), nullable=False)
    outcome: Mapped[Side] = mapped_column(enum_type(Side, 8), nullable=False)
    probability: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    score_distribution: Mapped[dict[str, str]] = mapped_column(
        json_type(), nullable=False
    )
    return_distribution: Mapped[dict[str, str] | None] = mapped_column(json_type())
    decision_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    analysis_run_key: Mapped[str] = mapped_column(String(256), nullable=False)
