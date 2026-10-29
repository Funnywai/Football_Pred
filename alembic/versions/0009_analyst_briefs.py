"""Lineups-only analyst briefs for the B/C agents

Revision ID: 0009_analyst_briefs
Revises: 0008_agent_bets
Create Date: 2026-10-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_analyst_briefs"
down_revision: str | None = "0008_agent_bets"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "analyst_briefs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("matches.id"), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("facts", sa.JSON(), nullable=False),
        sa.Column("uncertainties", sa.JSON(), nullable=False),
        sa.Column("missing", sa.JSON(), nullable=False),
        sa.Column("trust_score", sa.Float(), nullable=True),
        sa.Column("raw_snapshot", sa.JSON(), nullable=False),
        sa.UniqueConstraint(
            "run_id", "match_id", "source", name="uq_analyst_briefs_run_match_source"
        ),
    )
    op.create_index("ix_analyst_briefs_run_id", "analyst_briefs", ["run_id"])
    op.create_index("ix_analyst_briefs_match_id", "analyst_briefs", ["match_id"])


def downgrade() -> None:
    op.drop_index("ix_analyst_briefs_match_id", table_name="analyst_briefs")
    op.drop_index("ix_analyst_briefs_run_id", table_name="analyst_briefs")
    op.drop_table("analyst_briefs")
