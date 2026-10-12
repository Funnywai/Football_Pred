from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from app.providers.base import (
    FixtureRecord,
    LeagueRecord,
    OddsRecord,
    Provider,
    ResultRecord,
)


class _DummyProvider:
    name = "dummy"

    async def fetch_leagues(self) -> list[LeagueRecord]:
        return []

    async def fetch_fixtures(self, date_from: date, date_to: date) -> list[FixtureRecord]:
        return []

    async def fetch_odds(self, fixtures: list[FixtureRecord]) -> list[OddsRecord]:
        return []

    async def fetch_results(self, date_from: date, date_to: date) -> list[ResultRecord]:
        return []


def test_dummy_provider_satisfies_protocol():
    assert isinstance(_DummyProvider(), Provider)


def test_result_record_requires_identity():
    with pytest.raises(ValidationError):
        ResultRecord(home_score=1, away_score=0, source="hkjc")


def test_result_record_accepts_hkjc_identity():
    record = ResultRecord(
        match_hkjc_id="M1", home_score=1, away_score=0, source="hkjc", confirmed=True
    )
    assert record.ttl_corner is None
    assert record.payout_confirmed is False


def test_result_record_accepts_date_identity():
    record = ResultRecord(
        match_date=date(2026, 10, 11),
        home_team_name="Man Utd",
        away_team_name="Liverpool",
        home_score=2,
        away_score=1,
        source="football_data",
    )
    assert record.confirmed is False


def test_fixture_record_defaults():
    record = FixtureRecord(
        source="hkjc",
        league_name="English Premier League",
        kickoff_time=datetime(2026, 10, 12, 19, 30, tzinfo=UTC),
        home_team_name_en="Manchester United",
        away_team_name_en="Liverpool",
    )
    assert record.status == "scheduled"
    assert record.raw == {}
    assert record.hkjc_match_id is None
