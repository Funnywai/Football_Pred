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
