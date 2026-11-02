from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from packages.db.base import (
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_type,
    json_type,
)
from packages.domain.enums import FetchRunStatus, SourceStatus


class RawPayload(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "raw_payloads"

    source_name: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    source_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    body: Mapped[dict[str, object]] = mapped_column(json_type(), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(64))
    http_status: Mapped[int | None] = mapped_column(Integer)
    run_id: Mapped[str | None] = mapped_column(String(64))


class SourceFetchRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "source_fetch_runs"

    run_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    source_name: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[FetchRunStatus] = mapped_column(
        enum_type(FetchRunStatus, 16), nullable=False
    )
    request_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_summary: Mapped[str | None] = mapped_column(String(1024))
    params: Mapped[dict[str, object]] = mapped_column(json_type(), default=dict, nullable=False)
    source_status: Mapped[SourceStatus] = mapped_column(
        enum_type(SourceStatus, 16), default=SourceStatus.CONDITIONAL, nullable=False
    )
    verification_date: Mapped[date | None] = mapped_column(Date)
    schema_scope: Mapped[str | None] = mapped_column(String(256))
    field_scope: Mapped[str | None] = mapped_column(String(256))
    test_evidence_ref: Mapped[str | None] = mapped_column(String(512))
    licensing_check: Mapped[str | None] = mapped_column(String(512))
