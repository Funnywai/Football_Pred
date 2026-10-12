"""ML tables

Revision ID: 0002_ml_tables
Revises: 0001
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_ml_tables"
down_revision: str | None = "0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("target", sa.String(length=20), nullable=False),
        sa.Column("algorithm", sa.String(length=40), nullable=False),
        sa.Column("params", postgresql.JSONB(), nullable=False),
        sa.Column("metrics", postgresql.JSONB(), nullable=False),
        sa.Column("artifact_path", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_model_versions_target", "model_versions", ["target"])
    op.create_index(
        "uq_model_versions_champion_target",
        "model_versions",
        ["target"],
        unique=True,
        postgresql_where=sa.text("status = 'champion'"),
        sqlite_where=sa.text("status = 'champion'"),
    )

    op.create_table(
        "predictions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("matches.id"), nullable=False),
        sa.Column("target", sa.String(length=20), nullable=False),
        sa.Column("outcome", sa.String(length=10), nullable=False),
        sa.Column(
            "model_version_id", sa.Integer(), sa.ForeignKey("model_versions.id"), nullable=False
        ),
        sa.Column("prob", sa.Float(), nullable=False),
        sa.Column("implied_prob", sa.Float(), nullable=True),
        sa.Column("edge", sa.Float(), nullable=True),
        sa.Column("fair_odds", sa.Float(), nullable=False),
        sa.Column("market_odds", sa.Float(), nullable=True),
        sa.Column("recommended_fraction", sa.Float(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "match_id", "target", "outcome", "model_version_id", name="uq_predictions_natural"
        ),
    )
    op.create_index("ix_predictions_match_id", "predictions", ["match_id"])

    op.create_table(
        "match_features",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("matches.id"), nullable=False),
        sa.Column("feature_version", sa.String(length=40), nullable=False),
        sa.Column(
            "built_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("features", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("match_id", "feature_version", name="uq_match_features_natural"),
    )
    op.create_index("ix_match_features_match_id", "match_features", ["match_id"])


def downgrade() -> None:
    op.drop_index("ix_match_features_match_id", table_name="match_features")
    op.drop_table("match_features")
    op.drop_index("ix_predictions_match_id", table_name="predictions")
    op.drop_table("predictions")
    op.drop_index("uq_model_versions_champion_target", table_name="model_versions")
    op.drop_index("ix_model_versions_target", table_name="model_versions")
    op.drop_table("model_versions")
