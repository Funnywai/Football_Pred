"""add decision logs

Revision ID: 4a7c9e2b1d63
Revises: 8f3c2a1b7d90
Create Date: 2026-11-02 19:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = '4a7c9e2b1d63'
down_revision: str | None = '8f3c2a1b7d90'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'decision_logs',
        sa.Column('match_id', sa.Uuid(), nullable=False),
        sa.Column('decision_slot_key', sa.String(length=256), nullable=False),
        sa.Column('snapshot_id', sa.Uuid(), nullable=True),
        sa.Column('decision_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('reason', sa.String(length=512), nullable=False),
        sa.Column('model_version', sa.String(length=64), nullable=True),
        sa.Column('prediction_count', sa.Integer(), nullable=False),
        sa.Column('paper_bet_id', sa.Uuid(), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ['match_id'],
            ['matches.id'],
            name=op.f('fk_decision_logs_match_id_matches'),
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['snapshot_id'],
            ['odds_snapshots.id'],
            name=op.f('fk_decision_logs_snapshot_id_odds_snapshots'),
            ondelete='SET NULL',
        ),
        sa.ForeignKeyConstraint(
            ['paper_bet_id'],
            ['paper_bets.id'],
            name=op.f('fk_decision_logs_paper_bet_id_paper_bets'),
            ondelete='SET NULL',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_decision_logs')),
        sa.UniqueConstraint(
            'decision_slot_key',
            name=op.f('uq_decision_logs_decision_slot_key'),
        ),
    )
    op.create_index(
        op.f('ix_decision_logs_match_id'),
        'decision_logs',
        ['match_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_decision_logs_match_id'), table_name='decision_logs')
    op.drop_table('decision_logs')
