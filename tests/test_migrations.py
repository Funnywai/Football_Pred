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


def test_offline_migration_creates_match_stats() -> None:
    script = generate_offline_sql()
    assert "CREATE TABLE match_stats" in script
    assert "uq_match_stats_match_source" in script
    assert "ix_match_stats_match_id" in script


def test_offline_migration_creates_shadow_ledger_bets() -> None:
    script = generate_offline_sql()
    assert "CREATE TABLE shadow_ledger_bets" in script
    assert "uq_shadow_ledger_bets_match" in script
    assert "ix_shadow_ledger_bets_match_id" in script


def test_offline_migration_creates_agent_decisions() -> None:
    script = generate_offline_sql()
    assert "CREATE TABLE agent_decisions" in script
    assert "ix_agent_decisions_run_id" in script
    assert "ix_agent_decisions_match_id" in script
    assert "ix_agent_decisions_evaluated_at" in script
    assert "ix_agent_decisions_match_evaluated" in script


def test_offline_migration_creates_agent_bets() -> None:
    script = generate_offline_sql()
    assert "CREATE TABLE agent_bets" in script
    assert "uq_agent_bets_variant_match" in script
    assert "ix_agent_bets_run_id" in script
    assert "ix_agent_bets_match_id" in script


def test_offline_migration_creates_analyst_briefs() -> None:
    script = generate_offline_sql()
    assert "CREATE TABLE analyst_briefs" in script
    assert "uq_analyst_briefs_run_match_source" in script
    assert "ix_analyst_briefs_run_id" in script
    assert "ix_analyst_briefs_match_id" in script
