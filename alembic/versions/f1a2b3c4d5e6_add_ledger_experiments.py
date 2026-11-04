"""add ledger experiments for ROI baselines

Revision ID: f1a2b3c4d5e6
Revises: c8e2f4a1b3d9
Create Date: 2026-11-05 00:10:00.000000
"""
from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: str | None = "c8e2f4a1b3d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ledger_experiments",
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("model_version", sa.String(length=64), nullable=False),
        sa.Column("strategy_version", sa.String(length=32), nullable=False),
        sa.Column("initial_bankroll", sa.Numeric(14, 2), nullable=False),
        sa.Column("account_id", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_legacy", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ledger_experiments")),
        sa.UniqueConstraint("account_id", name=op.f("uq_ledger_experiments_account_id")),
    )

    op.add_column("paper_bets", sa.Column("experiment_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_paper_bets_experiment_id_ledger_experiments"),
        "paper_bets",
        "ledger_experiments",
        ["experiment_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_paper_bets_experiment_id",
        "paper_bets",
        ["experiment_id"],
        unique=False,
    )

    op.add_column("decision_logs", sa.Column("experiment_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_decision_logs_experiment_id_ledger_experiments"),
        "decision_logs",
        "ledger_experiments",
        ["experiment_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_decision_logs_experiment_id",
        "decision_logs",
        ["experiment_id"],
        unique=False,
    )

    # Existing production rows belong to the initial baseline experiment.
    baseline_id = uuid.uuid4()
    now = datetime.now(UTC)
    op.execute(
        sa.text(
            """
            INSERT INTO ledger_experiments
                (id, label, model_version, strategy_version, initial_bankroll,
                 account_id, is_active, is_legacy, created_at, updated_at)
            VALUES
                (:id, 'baseline', 'poisson-v1', 'g1', 10000.00,
                 'paper', true, true, :now, :now)
            """
        ).bindparams(id=baseline_id, now=now)
    )
    op.execute(
        sa.text(
            "UPDATE paper_bets SET experiment_id = :id WHERE experiment_id IS NULL"
        ).bindparams(id=baseline_id)
    )
    op.execute(
        sa.text(
            "UPDATE decision_logs SET experiment_id = :id WHERE experiment_id IS NULL"
        ).bindparams(id=baseline_id)
    )


def downgrade() -> None:
    op.drop_index("ix_decision_logs_experiment_id", table_name="decision_logs")
    op.drop_constraint(
        op.f("fk_decision_logs_experiment_id_ledger_experiments"),
        "decision_logs",
        type_="foreignkey",
    )
    op.drop_column("decision_logs", "experiment_id")

    op.drop_index("ix_paper_bets_experiment_id", table_name="paper_bets")
    op.drop_constraint(
        op.f("fk_paper_bets_experiment_id_ledger_experiments"),
        "paper_bets",
        type_="foreignkey",
    )
    op.drop_column("paper_bets", "experiment_id")

    op.drop_table("ledger_experiments")
