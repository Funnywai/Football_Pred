"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-12

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "leagues",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("name_en", sa.String(length=120), nullable=False),
        sa.Column("name_ch", sa.String(length=120), nullable=True),
        sa.Column("country", sa.String(length=60), nullable=True),
        sa.Column("hkjc_tourn_id", sa.String(length=40), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.UniqueConstraint("code", name="uq_leagues_code"),
        sa.UniqueConstraint("hkjc_tourn_id", name="uq_leagues_hkjc_tourn_id"),
    )
    op.create_table(
        "seasons",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("league_id", sa.Integer(), sa.ForeignKey("leagues.id"), nullable=False),
        sa.Column("label", sa.String(length=20), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.UniqueConstraint("league_id", "label", name="uq_seasons_league_label"),
    )
    op.create_table(
        "teams",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name_en", sa.String(length=120), nullable=False),
        sa.Column("name_ch", sa.String(length=120), nullable=True),
        sa.Column("hkjc_team_id", sa.String(length=40), nullable=True),
        sa.Column(
            "aliases",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "external_ids",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.UniqueConstraint("hkjc_team_id", name="uq_teams_hkjc_team_id"),
    )
    op.create_table(
        "matches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("season_id", sa.Integer(), sa.ForeignKey("seasons.id"), nullable=False),
        sa.Column("league_id", sa.Integer(), sa.ForeignKey("leagues.id"), nullable=False),
        sa.Column("hkjc_match_id", sa.String(length=40), nullable=True),
        sa.Column("kickoff_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="scheduled"),
        sa.Column("home_team_id", sa.Integer(), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("away_team_id", sa.Integer(), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("venue", sa.String(length=160), nullable=True),
        sa.Column("round", sa.String(length=60), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("hkjc_match_id", name="uq_matches_hkjc_match_id"),
        sa.UniqueConstraint(
            "season_id",
            "home_team_id",
            "away_team_id",
            "kickoff_time",
            name="uq_matches_natural",
        ),
    )
    op.create_table(
        "odds_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("matches.id"), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot_bucket", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("inplay", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("odds_type", sa.String(length=8), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint(
            "match_id",
            "odds_type",
            "inplay",
            "snapshot_bucket",
            name="uq_odds_snapshots_bucket",
        ),
    )
    op.create_index("ix_odds_snapshots_match_id", "odds_snapshots", ["match_id"])
    op.create_table(
        "results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("matches.id"), nullable=False),
        sa.Column("home_score", sa.Integer(), nullable=False),
        sa.Column("away_score", sa.Integer(), nullable=False),
        sa.Column("ttl_corner", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("confirmed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "payout_confirmed", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "raw",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.UniqueConstraint("match_id", name="uq_results_match_id"),
    )
    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job", sa.String(length=40), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("records_upserted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("ingestion_runs")
    op.drop_table("results")
    op.drop_index("ix_odds_snapshots_match_id", table_name="odds_snapshots")
    op.drop_table("odds_snapshots")
    op.drop_table("matches")
    op.drop_table("teams")
    op.drop_table("seasons")
    op.drop_table("leagues")
