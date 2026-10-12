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


def generate_offline_sql() -> str:
    cfg = Config("alembic.ini")
    cfg.output_buffer = io.StringIO()
    command.upgrade(cfg, "head", sql=True)
    return cfg.output_buffer.getvalue()


def test_offline_migration_creates_all_tables():
    sql = generate_offline_sql()
    for table in EXPECTED_TABLES:
        assert f"CREATE TABLE {table}" in sql
    assert "uq_odds_snapshots_bucket" in sql
    assert "uq_matches_natural" in sql
    assert "uq_results_match_id" in sql


def test_offline_migration_creates_ml_tables() -> None:
    script = generate_offline_sql()
    for table in ("model_versions", "predictions", "match_features"):
        assert f"CREATE TABLE {table}" in script
    assert "uq_predictions_natural" in script
    assert "uq_match_features_natural" in script
    assert "uq_model_versions_champion_target" in script


def test_offline_migration_creates_ledger_bets() -> None:
    script = generate_offline_sql()
    assert "CREATE TABLE ledger_bets" in script
    assert "uq_ledger_bets_natural" in script
