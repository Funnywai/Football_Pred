"""Shadow paper ledger bets table

Revision ID: 0006_shadow_ledger_bets
Revises: 0005_match_stats
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_shadow_ledger_bets"
down_revision: str | None = "0005_match_stats"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shadow_ledger_bets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("matches.id"), nullable=False),
        sa.Column("target", sa.String(length=20), nullable=False),
        sa.Column("outcome", sa.String(length=10), nullable=False),
        sa.Column(
            "model_version_id", sa.Integer(), sa.ForeignKey("model_versions.id"), nullable=False
        ),
        sa.Column("line", sa.Float(), nullable=True),
        sa.Column("odds", sa.Float(), nullable=False),
        sa.Column("stake", sa.Float(), nullable=False),
        sa.Column("bankroll_at_place", sa.Float(), nullable=False),
        sa.Column("edge", sa.Float(), nullable=True),
        sa.Column("kelly_multiplier", sa.Float(), nullable=False),
        sa.Column("result_source", sa.String(length=20), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "placed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payout", sa.Float(), nullable=True),
        sa.Column("profit", sa.Float(), nullable=True),
        sa.UniqueConstraint("match_id", name="uq_shadow_ledger_bets_match"),
    )
    op.create_index("ix_shadow_ledger_bets_match_id", "shadow_ledger_bets", ["match_id"])


def downgrade() -> None:
    op.drop_index("ix_shadow_ledger_bets_match_id", table_name="shadow_ledger_bets")
    op.drop_table("shadow_ledger_bets")
