"""Deterministic agent decision audit trail

Revision ID: 0007_agent_decisions
Revises: 0006_shadow_ledger_bets
Create Date: 2026-10-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_agent_decisions"
down_revision: str | None = "0006_shadow_ledger_bets"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("matches.id"), nullable=False),
        sa.Column(
            "model_version_id", sa.Integer(), sa.ForeignKey("model_versions.id"), nullable=False
        ),
        sa.Column("target", sa.String(length=20), nullable=False),
        sa.Column("outcome", sa.String(length=10), nullable=False),
        sa.Column("action", sa.String(length=10), nullable=False),
        sa.Column("stake", sa.Float(), nullable=True),
        sa.Column("odds", sa.Float(), nullable=True),
        sa.Column("edge", sa.Float(), nullable=True),
        sa.Column("signal_edge", sa.Float(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("agent", sa.String(length=20), nullable=False, server_default="risk"),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("input_snapshot", sa.JSON(), nullable=False),
        sa.Column(
            "evaluated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_agent_decisions_run_id", "agent_decisions", ["run_id"])
    op.create_index("ix_agent_decisions_match_id", "agent_decisions", ["match_id"])
    op.create_index("ix_agent_decisions_evaluated_at", "agent_decisions", ["evaluated_at"])
    op.create_index(
        "ix_agent_decisions_match_evaluated", "agent_decisions", ["match_id", "evaluated_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_agent_decisions_match_evaluated", table_name="agent_decisions")
    op.drop_index("ix_agent_decisions_evaluated_at", table_name="agent_decisions")
    op.drop_index("ix_agent_decisions_match_id", table_name="agent_decisions")
    op.drop_index("ix_agent_decisions_run_id", table_name="agent_decisions")
    op.drop_table("agent_decisions")
