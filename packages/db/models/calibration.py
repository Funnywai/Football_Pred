from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from packages.db.base import (
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    json_type,
)


class ModelVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__: str = "model_versions"

    version: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    family: Mapped[str] = mapped_column(String(64), nullable=False)
    params: Mapped[dict[str, object]] = mapped_column(
        json_type(), default=dict, nullable=False
    )
    training_window: Mapped[dict[str, object]] = mapped_column(
        json_type(), default=dict, nullable=False
    )
    validation_metrics: Mapped[dict[str, object]] = mapped_column(
        json_type(), default=dict, nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), default="research", nullable=False)


class StrategyVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__: str = "strategy_versions"

    version: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_params: Mapped[dict[str, object]] = mapped_column(
        json_type(), default=dict, nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), default="research", nullable=False)


class WeightSnapshot(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__: str = "weight_snapshots"

    strategy_version: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    weights: Mapped[dict[str, object]] = mapped_column(
        json_type(), default=dict, nullable=False
    )
    reason: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    evaluation_period: Mapped[str | None] = mapped_column(String(64))


class CalibrationMetric(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__: str = "calibration_metrics"
    __table_args__: tuple[UniqueConstraint, ...] = (
        UniqueConstraint(
            "model_version",
            "strategy_version",
            "competition",
            "market",
            "time_block",
            name="uq_calibration_metrics_period",
        ),
    )

    model_version: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    strategy_version: Mapped[str | None] = mapped_column(String(64), index=True)
    competition: Mapped[str] = mapped_column(String(24), nullable=False)
    market: Mapped[str] = mapped_column(String(16), nullable=False)
    time_block: Mapped[str] = mapped_column(String(64), nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    brier: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    log_loss: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    roi: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    clv: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    calibration: Mapped[list[dict[str, object]]] = mapped_column(
        json_type(), default=list, nullable=False
    )
