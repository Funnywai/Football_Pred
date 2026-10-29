import logging

from app.config import Settings, configure_logging


def test_settings_log_level_defaults_to_info():
    assert Settings(_env_file=None).log_level == "INFO"


def test_configure_logging_makes_info_visible():
    root = logging.getLogger()
    previous = root.level
    try:
        configure_logging("INFO")
        assert root.level == logging.INFO
        assert logging.getLogger("app.services.fixtures").isEnabledFor(logging.INFO)
    finally:
        root.setLevel(previous)


def test_defaults():
    settings = Settings(_env_file=None)
    assert settings.hkjc_graphql_url == "https://info.cld.hkjc.com/graphql/base/"
    assert settings.hkjc_referer == "https://bet.hkjc.com/"
    assert settings.hkjc_origin == "https://bet.hkjc.com"
    assert settings.sync_odds_interval == 600
    assert settings.sync_settle_interval == 900
    assert settings.hkjc_throttle_seconds == 1.5
    assert settings.odds_retention_days == 120
    assert settings.league_whitelist == ["EPL", "LALIGA", "SERIEA", "BUNDESLIGA", "LIGUE1", "UCL"]


def test_league_whitelist_parses_comma_separated_env(monkeypatch):
    monkeypatch.setenv("LEAGUE_WHITELIST", "epl, laliga ,ucl")
    settings = Settings(_env_file=None)
    assert settings.league_whitelist == ["EPL", "LALIGA", "UCL"]


def test_league_whitelist_accepts_json_list(monkeypatch):
    monkeypatch.setenv("LEAGUE_WHITELIST", '["EPL", "UCL"]')
    settings = Settings(_env_file=None)
    assert settings.league_whitelist == ["EPL", "UCL"]


def test_ml_defaults() -> None:
    settings = Settings(_env_file=None)
    assert settings.ml_enable is False
    assert settings.ml_1x2_model == "lightgbm"
    assert settings.ml_handicap_model == "lightgbm"
    assert settings.ml_value_edge_threshold == 0.02
    assert settings.ml_retrain_interval == 604800
    assert settings.ml_predict_lookahead_hours == 48
    assert settings.ml_min_train_rows == 500
    assert settings.ml_artifact_dir == "artifacts/ml"
    assert settings.ml_champion_margin == 0.0
    assert settings.ml_history_from_year == 2010


def test_ml_env_override(monkeypatch) -> None:
    monkeypatch.setenv("ML_ENABLE", "true")
    monkeypatch.setenv("ML_VALUE_EDGE_THRESHOLD", "0.05")
    monkeypatch.setenv("ML_RETRAIN_INTERVAL", "3600")
    settings = Settings(_env_file=None)
    assert settings.ml_enable is True
    assert settings.ml_value_edge_threshold == 0.05
    assert settings.ml_retrain_interval == 3600


def test_ml_prior_lead_default_and_env(monkeypatch) -> None:
    assert Settings(_env_file=None).ml_prior_lead_hours == 48
    monkeypatch.setenv("ML_PRIOR_LEAD_HOURS", "0")
    assert Settings(_env_file=None).ml_prior_lead_hours == 0


def test_ml_blend_defaults() -> None:
    settings = Settings(_env_file=None)
    assert settings.ml_blend_weight == 0.20
    assert settings.ml_exec_edge_buffer == 0.03


def test_ledger_defaults() -> None:
    settings = Settings(_env_file=None)
    assert settings.ledger_enable is True
    assert settings.shadow_ledger_enable is True
    assert settings.ledger_update_interval == 3600
    assert settings.ledger_initial_bankroll == 1000.0
    assert settings.ledger_kelly_multiplier == 0.5
    assert settings.ledger_max_stake_fraction == 0.05
    assert settings.ledger_min_stake == 10.0


def test_agent_defaults() -> None:
    settings = Settings(_env_file=None)
    assert settings.agent_max_odds == 5.0
    assert settings.striker_base_url == "https://mcp.strikerapi.com"
    assert settings.striker_timeout_seconds == 20.0
    assert settings.agent_llm_model == "deepseek-v4.1-flash"
    assert settings.agent_llm_temperature == 0.0
    assert settings.agent_llm_timeout_seconds == 30.0


def test_agent_env_override(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_MAX_ODDS", "3.5")
    assert Settings(_env_file=None).agent_max_odds == 3.5


def test_ledger_env_override(monkeypatch) -> None:
    monkeypatch.setenv("LEDGER_ENABLE", "false")
    monkeypatch.setenv("SHADOW_LEDGER_ENABLE", "false")
    monkeypatch.setenv("LEDGER_INITIAL_BANKROLL", "10000")
    monkeypatch.setenv("LEDGER_KELLY_MULTIPLIER", "0.25")
    settings = Settings(_env_file=None)
    assert settings.ledger_enable is False
    assert settings.shadow_ledger_enable is False
    assert settings.ledger_initial_bankroll == 10000.0
    assert settings.ledger_kelly_multiplier == 0.25
