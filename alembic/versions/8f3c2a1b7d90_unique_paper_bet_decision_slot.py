"""unique paper bet decision slot

Revision ID: 8f3c2a1b7d90
Revises: 6f1a0c2b9d47
Create Date: 2026-11-02 18:45:00.000000

"""
from collections.abc import Sequence

from alembic import op

revision: str = "8f3c2a1b7d90"
down_revision: str | None = "6f1a0c2b9d47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_paper_bets_decision_slot_key",
        "paper_bets",
        ["decision_slot_key"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_paper_bets_decision_slot_key",
        "paper_bets",
        type_="unique",
    )
