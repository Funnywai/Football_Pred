"""Closing-line value records

Revision ID: 0004_clv_records
Revises: 0003_ledger_bets
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_clv_records"
down_revision: str | None = "0003_ledger_bets"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "clv_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "prediction_id",
            sa.Integer(),
            sa.ForeignKey("predictions.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("matches.id"), nullable=False),
        sa.Column(
            "model_version_id", sa.Integer(), sa.ForeignKey("model_versions.id"), nullable=False
        ),
        sa.Column("target", sa.String(length=20), nullable=False),
        sa.Column("outcome", sa.String(length=10), nullable=False),
        sa.Column("model_prob", sa.Float(), nullable=False),
        sa.Column("closing_prob", sa.Float(), nullable=False),
        sa.Column("closing_odds", sa.Float(), nullable=True),
        sa.Column("edge", sa.Float(), nullable=False),
        sa.Column("beat", sa.Boolean(), nullable=False),
        sa.Column("is_value", sa.Boolean(), nullable=False),
        sa.Column("label", sa.String(length=10), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column(
            "computed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_clv_records_match_id", "clv_records", ["match_id"])
    op.create_index("ix_clv_records_model_version_id", "clv_records", ["model_version_id"])
    op.create_index(
        "ix_clv_records_model_version_computed",
        "clv_records",
        ["model_version_id", "computed_at"],
    )
    op.create_index(
        "ix_clv_records_source_computed", "clv_records", ["source", "computed_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_clv_records_source_computed", table_name="clv_records")
    op.drop_index("ix_clv_records_model_version_computed", table_name="clv_records")
    op.drop_index("ix_clv_records_model_version_id", table_name="clv_records")
    op.drop_index("ix_clv_records_match_id", table_name="clv_records")
    op.drop_table("clv_records")
