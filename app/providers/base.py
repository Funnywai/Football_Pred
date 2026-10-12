from datetime import date, datetime
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field, model_validator


class LeagueRecord(BaseModel):
    code: str
    name_en: str
    name_ch: str | None = None
    country: str | None = None
    hkjc_tourn_id: str | None = None


class FixtureRecord(BaseModel):
    source: str
    league_name: str
    hkjc_tourn_id: str | None = None
    hkjc_match_id: str | None = None
    kickoff_time: datetime
    status: str = "scheduled"
    home_team_name_en: str
    home_team_name_ch: str | None = None
    home_team_hkjc_id: str | None = None
    away_team_name_en: str
    away_team_name_ch: str | None = None
    away_team_hkjc_id: str | None = None
    venue: str | None = None
    round: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class OddsRecord(BaseModel):
    match_hkjc_id: str
    odds_type: str
    inplay: bool = False
    captured_at: datetime
    payload: dict[str, Any]


class ResultRecord(BaseModel):
    match_hkjc_id: str | None = None
    match_date: date | None = None
    home_team_name: str | None = None
    away_team_name: str | None = None
    home_score: int
    away_score: int
    ttl_corner: int | None = None
    source: str
    confirmed: bool = False
    payout_confirmed: bool = False
    raw: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _require_identity(self) -> "ResultRecord":
        has_hkjc = self.match_hkjc_id is not None
        has_external = (
            self.match_date is not None
            and self.home_team_name is not None
            and self.away_team_name is not None
        )
        if not has_hkjc and not has_external:
            raise ValueError(
                "ResultRecord requires match_hkjc_id or (match_date, home_team_name, away_team_name)"
            )
        return self


@runtime_checkable
class Provider(Protocol):
    name: str

    async def fetch_leagues(self) -> list[LeagueRecord]: ...

    async def fetch_fixtures(self, date_from: date, date_to: date) -> list[FixtureRecord]: ...

    async def fetch_odds(self, fixtures: list[FixtureRecord]) -> list[OddsRecord]: ...

    async def fetch_results(self, date_from: date, date_to: date) -> list[ResultRecord]: ...
