from app.config import Settings


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
