import io

from alembic import command
from alembic.config import Config

EXPECTED_TABLES = [
    "leagues",
    "seasons",
    "teams",
    "matches",
    "odds_snapshots",
    "results",
    "ingestion_runs",
]


def test_offline_migration_creates_all_tables():
    cfg = Config("alembic.ini")
    cfg.output_buffer = io.StringIO()
    command.upgrade(cfg, "head", sql=True)
    sql = cfg.output_buffer.getvalue()
    for table in EXPECTED_TABLES:
        assert f"CREATE TABLE {table}" in sql
    assert "uq_odds_snapshots_bucket" in sql
    assert "uq_matches_natural" in sql
    assert "uq_results_match_id" in sql
