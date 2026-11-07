from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from packages.adapters.base import AdapterHTTPError, FetchResult, hash_text
from packages.adapters.open_meteo import OpenMeteoAdapter
from packages.db.base import Base
from packages.db.models import Competition, EvidenceRecord, Match, Team
from packages.ingest.evidence import collect_match_evidence
from packages.ingest.pipeline import AdapterBundle
from packages.shared.config import Settings

KICKOFF = datetime(2026, 11, 7, 12, 30, tzinfo=UTC)


def _session():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)()


def _seed(session, *, home_slug: str = "everton"):
    competition = Competition(
        code="EPL",
        name="English Premier League",
        country="England",
        is_cup=False,
        football_data_code="PL",
    )
    home = Team(
        slug=home_slug, name="Everton FC", short_name="EVE", country="England"
    )
    away = Team(
        slug="coventry-city-fc",
        name="Coventry City FC",
        short_name="COV",
        country="England",
    )
    session.add_all([competition, home, away])
    session.flush()
    match = Match(
        competition_id=competition.id,
        season="2026/27",
        kickoff_at=KICKOFF,
        home_team_id=home.id,
        away_team_id=away.id,
        status="scheduled",
        source_match_ids={},
        coverage_flags=[],
    )
    session.add(match)
    session.flush()
    return match


def _settings() -> Settings:
    return Settings(
        database_url="sqlite+pysqlite:///:memory:",
        _env_file=None,
        news_feed_urls="",
    )


class _FakeWeather:
    def fetch_hourly(self, latitude, longitude, start_date, end_date):
        payload = {
            "hourly": {
                "time": [
                    "2026-11-07T12:00",
                    "2026-11-07T13:00",
                ],
                "temperature_2m": [10.5, 11.0],
                "precipitation": [0.0, 0.2],
                "wind_speed_10m": [12.0, 13.0],
            }
        }
        raw = json.dumps(payload, sort_keys=True)
        return FetchResult(
            source_name="open-meteo",
            source_url="https://fixture.local/weather",
            fetched_at=datetime(2026, 11, 7, 10, 0, tzinfo=UTC),
            http_status=200,
            schema_version="v1",
            payload=payload,
            payload_hash=hash_text(raw),
            raw_text=raw,
        )

    def parse_hourly(self, payload):
        return OpenMeteoAdapter.parse_hourly(payload)

    def nearest_to_kickoff(self, points, kickoff_at):
        return OpenMeteoAdapter.nearest_to_kickoff(points, kickoff_at)


def test_collect_match_evidence_stores_weather_from_curated_venue():
    engine, session = _session()
    try:
        match = _seed(session)
        status = collect_match_evidence(
            session,
            match,
            AdapterBundle(weather=_FakeWeather()),
            _settings(),
        )
        assert status["weather"] == "present"
        record = (
            session.query(EvidenceRecord)
            .filter(EvidenceRecord.kind == "weather")
            .one()
        )
        assert record.payload["venue"]["city"] == "Liverpool"
        assert record.payload["temperature_c"] == "10.5"
    finally:
        session.close()
        engine.dispose()


def test_collect_match_evidence_reports_missing_venue_coordinates():
    engine, session = _session()
    try:
        match = _seed(session, home_slug="no-venue-team")
        status = collect_match_evidence(
            session,
            match,
            AdapterBundle(weather=_FakeWeather()),
            _settings(),
        )
        assert status["weather"] == "missing:venue_not_curated"
        assert session.query(EvidenceRecord).filter(
            EvidenceRecord.kind == "weather"
        ).count() == 0
    finally:
        session.close()
        engine.dispose()


class _FailingUnderstat:
    def __init__(self) -> None:
        self.calls = 0

    def fetch_league(self, competition_code, season_start_year):
        self.calls += 1
        raise AdapterHTTPError("ssl handshake timed out")

    def parse_team_seasons(self, html):
        raise AssertionError("parse must not run when fetch fails")


def test_collect_match_evidence_retries_xg_and_reports_error(monkeypatch):
    monkeypatch.setattr("packages.ingest.evidence._XG_RETRY_SECONDS", 0.0)

    class _FailingFotMobXG:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def fetch_league_fixtures(self, competition_code, season_start_year):
            raise AdapterHTTPError("fotmob unavailable")

        def close(self) -> None:
            pass

    monkeypatch.setattr(
        "packages.ingest.evidence.FotMobAdapter", _FailingFotMobXG
    )
    engine, session = _session()
    try:
        match = _seed(session)
        understat = _FailingUnderstat()
        status = collect_match_evidence(
            session,
            match,
            AdapterBundle(understat=understat),
            _settings(),
        )
        assert understat.calls == 2
        assert status["xg"].startswith("error:")
    finally:
        session.close()
        engine.dispose()


def test_collect_match_evidence_falls_back_to_fotmob_xg(monkeypatch):

    from packages.adapters.fotmob import FotMobAdapter as RealFotMobAdapter

    monkeypatch.setattr("packages.ingest.evidence._XG_RETRY_SECONDS", 0.0)

    class _FakeFotMobXG:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def fetch_league_fixtures(self, competition_code, season_start_year):
            payload = {
                "table": [
                    {
                        "data": {
                            "table": {
                                "xg": [
                                    {
                                        "name": "Everton",
                                        "teamId": 1,
                                        "played": 10,
                                        "xg": 12.5,
                                        "xgConceded": 9.5,
                                    },
                                    {
                                        "name": "Coventry City",
                                        "teamId": 2,
                                        "played": 10,
                                        "xg": 8.0,
                                        "xgConceded": 15.0,
                                    },
                                ]
                            }
                        }
                    }
                ]
            }
            return FetchResult(
                source_name="fotmob",
                source_url="https://fixture.local/fotmob/league",
                fetched_at=datetime(2026, 11, 7, 10, 0, tzinfo=UTC),
                http_status=200,
                schema_version="api-v1",
                payload=payload,
                payload_hash=hash_text(json.dumps(payload, sort_keys=True)),
                raw_text=json.dumps(payload, sort_keys=True),
            )

        @staticmethod
        def parse_team_xg(payload):
            return RealFotMobAdapter.parse_team_xg(payload)

        def close(self) -> None:
            pass

    monkeypatch.setattr(
        "packages.ingest.evidence.FotMobAdapter", _FakeFotMobXG
    )
    engine, session = _session()
    try:
        match = _seed(session)
        status = collect_match_evidence(
            session,
            match,
            AdapterBundle(understat=_FailingUnderstat()),
            _settings(),
        )
        assert status["xg"] == "present:fotmob"
        record = (
            session.query(EvidenceRecord)
            .filter(EvidenceRecord.kind == "xg")
            .one()
        )
        assert record.source_name == "fotmob"
        teams = {row["team"] for row in record.payload["teams"]}
        assert teams == {"Everton", "Coventry City"}
    finally:
        session.close()
        engine.dispose()
