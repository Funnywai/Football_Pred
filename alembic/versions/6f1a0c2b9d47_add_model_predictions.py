"""add model predictions

Revision ID: 6f1a0c2b9d47
Revises: 458ef6d8882a
Create Date: 2026-11-02 18:10:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = '6f1a0c2b9d47'
down_revision: str | None = '458ef6d8882a'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'model_predictions',
        sa.Column('match_id', sa.Uuid(), nullable=False),
        sa.Column(
            'market',
            sa.Enum(
                'HAD', 'HDC', 'HIL',
                name='markettype',
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column('line_key', sa.String(length=24), nullable=False),
        sa.Column(
            'outcome',
            sa.Enum(
                'H', 'D', 'A', 'L',
                name='side',
                native_enum=False,
                length=8,
            ),
            nullable=False,
        ),
        sa.Column('probability', sa.Numeric(precision=8, scale=6), nullable=False),
        sa.Column(
            'score_distribution',
            sa.JSON().with_variant(
                postgresql.JSONB(astext_type='text'), 'postgresql'
            ),
            nullable=False,
        ),
        sa.Column(
            'return_distribution',
            sa.JSON().with_variant(
                postgresql.JSONB(astext_type='text'), 'postgresql'
            ),
            nullable=True,
        ),
        sa.Column('decision_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('model_version', sa.String(length=64), nullable=False),
        sa.Column('analysis_run_key', sa.String(length=256), nullable=False),
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
            name=op.f('fk_model_predictions_match_id_matches'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_model_predictions')),
        sa.UniqueConstraint(
            'analysis_run_key',
            'market',
            'line_key',
            'outcome',
            name=op.f('uq_model_predictions_analysis_run_key'),
        ),
    )
    op.create_index(
        op.f('ix_model_predictions_match_id'),
        'model_predictions',
        ['match_id'],
        unique=False,
    )
    op.create_index(
        'ix_model_predictions_match_id_decision_at',
        'model_predictions',
        ['match_id', 'decision_at'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        'ix_model_predictions_match_id_decision_at',
        table_name='model_predictions',
    )
    op.drop_index(
        op.f('ix_model_predictions_match_id'),
        table_name='model_predictions',
    )
    op.drop_table('model_predictions')
