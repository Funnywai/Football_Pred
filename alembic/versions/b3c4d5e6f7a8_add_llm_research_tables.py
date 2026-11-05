"""add llm research assistant tables

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-11-05 23:40:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b3c4d5e6f7a8"
down_revision: str | None = "a2b3c4d5e6f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_research_runs",
        sa.Column("match_id", sa.Uuid(), nullable=False),
        sa.Column("stage", sa.String(length=16), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_hash", sa.String(length=64), nullable=False),
        sa.Column("model_version", sa.String(length=64), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("report", sa.JSON(), nullable=True),
        sa.Column("probabilities", sa.JSON(), nullable=True),
        sa.Column("recommended_side", sa.String(length=8), nullable=True),
        sa.Column("recommended_stake_pct", sa.Numeric(8, 6), nullable=True),
        sa.Column("confidence", sa.Numeric(8, 6), nullable=True),
        sa.Column("abstain", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("risk", sa.JSON(), nullable=True),
        sa.Column("raw_response", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"], name=op.f("fk_llm_research_runs_match_id_matches"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_research_runs")),
        sa.UniqueConstraint("match_id", "stage", "evidence_hash", "model_version", name="uq_llm_research_runs_match_stage_evidence_model"),
    )
    op.create_index("ix_llm_research_runs_match_id_created_at", "llm_research_runs", ["match_id", "created_at"])
    op.create_table(
        "llm_research_findings",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("findings", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Numeric(8, 6), nullable=True),
        sa.Column("direction", sa.String(length=16), nullable=True),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("uncertainties", sa.JSON(), nullable=False),
        sa.Column("abstain", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("raw_response", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["llm_research_runs.id"], name=op.f("fk_llm_research_findings_run_id_llm_research_runs"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_research_findings")),
        sa.UniqueConstraint("run_id", "agent_id", name="uq_llm_research_findings_run_agent"),
    )
    op.create_index("ix_llm_research_findings_run_id", "llm_research_findings", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_llm_research_findings_run_id", table_name="llm_research_findings")
    op.drop_table("llm_research_findings")
    op.drop_index("ix_llm_research_runs_match_id_created_at", table_name="llm_research_runs")
    op.drop_table("llm_research_runs")
