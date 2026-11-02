"""add calibration and versioning

Revision ID: b7d4e1c9a2f0
Revises: 4a7c9e2b1d63
Create Date: 2026-11-02 20:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b7d4e1c9a2f0"
down_revision: str | None = "4a7c9e2b1d63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json_column() -> sa.JSON:
    return sa.JSON().with_variant(
        postgresql.JSONB(astext_type="text"), "postgresql"
    )


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
    )


def upgrade() -> None:
    op.create_table(
        "model_versions",
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("family", sa.String(length=64), nullable=False),
        sa.Column("params", _json_column(), nullable=False),
        sa.Column("training_window", _json_column(), nullable=False),
        sa.Column("validation_metrics", _json_column(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'research'"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_model_versions")),
        sa.UniqueConstraint("version", name=op.f("uq_model_versions_version")),
    )

    op.create_table(
        "strategy_versions",
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("model_version", sa.String(length=64), nullable=False),
        sa.Column("policy_params", _json_column(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'research'"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_strategy_versions")),
        sa.UniqueConstraint("version", name=op.f("uq_strategy_versions_version")),
    )

    op.create_table(
        "weight_snapshots",
        sa.Column("strategy_version", sa.String(length=64), nullable=False),
        sa.Column("weights", _json_column(), nullable=False),
        sa.Column("reason", sa.String(length=512), nullable=False),
        sa.Column("evaluation_period", sa.String(length=64), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_weight_snapshots")),
    )
    op.create_index(
        op.f("ix_weight_snapshots_strategy_version"),
        "weight_snapshots",
        ["strategy_version"],
        unique=False,
    )

    op.create_table(
        "calibration_metrics",
        sa.Column("model_version", sa.String(length=64), nullable=False),
        sa.Column("strategy_version", sa.String(length=64), nullable=True),
        sa.Column("competition", sa.String(length=24), nullable=False),
        sa.Column("market", sa.String(length=16), nullable=False),
        sa.Column("time_block", sa.String(length=64), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("brier", sa.Numeric(precision=10, scale=6), nullable=True),
        sa.Column("log_loss", sa.Numeric(precision=10, scale=6), nullable=True),
        sa.Column("roi", sa.Numeric(precision=10, scale=6), nullable=True),
        sa.Column("clv", sa.Numeric(precision=10, scale=6), nullable=True),
        sa.Column("calibration", _json_column(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_calibration_metrics")),
        sa.UniqueConstraint(
            "model_version",
            "strategy_version",
            "competition",
            "market",
            "time_block",
            name=op.f("uq_calibration_metrics_period"),
        ),
    )
    op.create_index(
        op.f("ix_calibration_metrics_model_version"),
        "calibration_metrics",
        ["model_version"],
        unique=False,
    )
    op.create_index(
        op.f("ix_calibration_metrics_strategy_version"),
        "calibration_metrics",
        ["strategy_version"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_calibration_metrics_strategy_version"),
        table_name="calibration_metrics",
    )
    op.drop_index(
        op.f("ix_calibration_metrics_model_version"),
        table_name="calibration_metrics",
    )
    op.drop_table("calibration_metrics")
    op.drop_index(
        op.f("ix_weight_snapshots_strategy_version"),
        table_name="weight_snapshots",
    )
    op.drop_table("weight_snapshots")
    op.drop_table("strategy_versions")
    op.drop_table("model_versions")
