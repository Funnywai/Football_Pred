"""Paper-only agent ledger bets

Revision ID: 0008_agent_bets
Revises: 0007_agent_decisions
Create Date: 2026-10-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_agent_bets"
down_revision: str | None = "0007_agent_decisions"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_bets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("matches.id"), nullable=False),
        sa.Column(
            "model_version_id", sa.Integer(), sa.ForeignKey("model_versions.id"), nullable=False
        ),
        sa.Column("target", sa.String(length=20), nullable=False),
        sa.Column("outcome", sa.String(length=10), nullable=False),
        sa.Column("variant", sa.String(length=10), nullable=False),
        sa.Column("line", sa.Float(), nullable=True),
        sa.Column("odds", sa.Float(), nullable=False),
        sa.Column("stake", sa.Float(), nullable=False),
        sa.Column("bankroll_at_place", sa.Float(), nullable=False),
        sa.Column("edge", sa.Float(), nullable=True),
        sa.Column("kelly_multiplier", sa.Float(), nullable=False),
        sa.Column("result_source", sa.String(length=20), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column(
            "placed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payout", sa.Float(), nullable=True),
        sa.Column("profit", sa.Float(), nullable=True),
        sa.UniqueConstraint("variant", "match_id", name="uq_agent_bets_variant_match"),
    )
    op.create_index("ix_agent_bets_run_id", "agent_bets", ["run_id"])
    op.create_index("ix_agent_bets_match_id", "agent_bets", ["match_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_bets_match_id", table_name="agent_bets")
    op.drop_index("ix_agent_bets_run_id", table_name="agent_bets")
    op.drop_table("agent_bets")
