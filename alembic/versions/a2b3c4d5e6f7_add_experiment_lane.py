"""add lane to ledger experiments

Revision ID: a2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-11-05 00:25:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a2b3c4d5e6f7"
down_revision: str | None = "f1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ledger_experiments",
        sa.Column(
            "lane",
            sa.String(length=16),
            nullable=False,
            server_default="deterministic",
        ),
    )
    op.execute(
        sa.text("UPDATE ledger_experiments SET lane = 'deterministic' WHERE lane IS NULL")
    )


def downgrade() -> None:
    op.drop_column("ledger_experiments", "lane")
