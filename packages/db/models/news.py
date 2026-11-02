from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from packages.db.base import (
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_type,
)
from packages.domain.enums import AvailabilityBasis


class NewsSignal(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "news_signals"

    source_name: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    source_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    availability_basis: Mapped[AvailabilityBasis] = mapped_column(
        enum_type(AvailabilityBasis, 32), nullable=False
    )
    evidence_grade: Mapped[AvailabilityBasis] = mapped_column(
        enum_type(AvailabilityBasis, 32), nullable=False
    )
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
