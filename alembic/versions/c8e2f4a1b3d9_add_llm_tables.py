"""add llm ensemble tables

Revision ID: c8e2f4a1b3d9
Revises: b7d4e1c9a2f0
Create Date: 2026-11-04 02:20:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c8e2f4a1b3d9"
down_revision: str | None = "b7d4e1c9a2f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json_column() -> sa.JSON:
    return sa.JSON().with_variant(postgresql.JSONB(astext_type="text"), "postgresql")


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
    )


def upgrade() -> None:
    op.create_table(
        "llm_evidence_packets",
        sa.Column("match_id", sa.Uuid(), nullable=False),
        sa.Column("stage", sa.String(length=16), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("packet_hash", sa.String(length=64), nullable=False),
        sa.Column("packet", _json_column(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"], name=op.f("fk_llm_evidence_packets_match_id_matches"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_evidence_packets")),
        sa.UniqueConstraint("match_id", "stage", "packet_hash", name="uq_llm_evidence_packets_match_stage_hash"),
    )
    op.create_index("ix_llm_evidence_packets_match_id", "llm_evidence_packets", ["match_id"])

    op.create_table(
        "llm_agent_runs",
        sa.Column("packet_id", sa.Uuid(), nullable=False),
        sa.Column("match_id", sa.Uuid(), nullable=False),
        sa.Column("stage", sa.String(length=16), nullable=False),
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("prompt_name", sa.String(length=64), nullable=False),
        sa.Column("prompt_sha256", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("raw_response", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"], name=op.f("fk_llm_agent_runs_match_id_matches"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["packet_id"], ["llm_evidence_packets.id"], name=op.f("fk_llm_agent_runs_packet_id_llm_evidence_packets"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_agent_runs")),
    )
    op.create_index("ix_llm_agent_runs_match_id_created_at", "llm_agent_runs", ["match_id", "created_at"])
    op.create_index("ix_llm_agent_runs_packet_id", "llm_agent_runs", ["packet_id"])

    op.create_table(
        "llm_agent_outputs",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("match_id", sa.Uuid(), nullable=False),
        sa.Column("stage", sa.String(length=16), nullable=False),
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("probabilities", _json_column(), nullable=False),
        sa.Column("confidence", sa.Numeric(8, 6), nullable=False),
        sa.Column("data_quality", sa.Numeric(8, 6), nullable=False),
        sa.Column("abstain", sa.Boolean(), nullable=False),
        sa.Column("output", _json_column(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"], name=op.f("fk_llm_agent_outputs_match_id_matches"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["llm_agent_runs.id"], name=op.f("fk_llm_agent_outputs_run_id_llm_agent_runs"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_agent_outputs")),
        sa.UniqueConstraint("run_id", name="uq_llm_agent_outputs_run_id"),
    )
    op.create_index("ix_llm_agent_outputs_match_id", "llm_agent_outputs", ["match_id"])

    op.create_table(
        "llm_ensemble_predictions",
        sa.Column("match_id", sa.Uuid(), nullable=False),
        sa.Column("stage", sa.String(length=16), nullable=False),
        sa.Column("packet_id", sa.Uuid(), nullable=False),
        sa.Column("probabilities", _json_column(), nullable=False),
        sa.Column("weights", _json_column(), nullable=False),
        sa.Column("active_agents", _json_column(), nullable=False),
        sa.Column("red_team", _json_column(), nullable=True),
        sa.Column("judge", _json_column(), nullable=True),
        sa.Column("model_version", sa.String(length=64), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"], name=op.f("fk_llm_ensemble_predictions_match_id_matches"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["packet_id"], ["llm_evidence_packets.id"], name=op.f("fk_llm_ensemble_predictions_packet_id_llm_evidence_packets"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_ensemble_predictions")),
    )
    op.create_index("ix_llm_ensemble_predictions_match_id_created_at", "llm_ensemble_predictions", ["match_id", "created_at"])
    op.create_index("ix_llm_ensemble_predictions_packet_id", "llm_ensemble_predictions", ["packet_id"])


def downgrade() -> None:
    op.drop_table("llm_ensemble_predictions")
    op.drop_table("llm_agent_outputs")
    op.drop_table("llm_agent_runs")
    op.drop_table("llm_evidence_packets")
