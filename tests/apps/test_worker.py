import copy
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from apps.scheduler.main import _enqueue_settlement_scan, build_scheduler
from apps.worker.jobs import (
    OddsNotOfferedError,
    _decision_probability,
    _load_hkjc_result,
    _ucl_result_requires_gate,
    check_lineup,
    enqueue_due_match_triggers,
    ingest_trigger_odds,
    release_trigger_dedupe,
    run_calibration_report,
    run_daily_ingest,
    run_decision_reconciliation,
    run_lineup_check,
    run_match_trigger,
    run_recent_result_refresh,
    run_settlement_scan,
)
from packages.adapters.base import AdapterHTTPError, FetchResult, hash_text
from packages.db.base import Base
from packages.db.models import (
    Competition,
    DecisionLog,
    MarketLine,
    Match,
    ModelPrediction,
    OddsSnapshot,
    PaperBet,
    RawPayload,
    SourceFetchRun,
    Team,
)
from packages.domain.enums import (
    BetStatus,
    FetchRunStatus,
    MarketType,
    MatchStatus,
    Side,
    SnapshotKind,
    SourceStatus,
)
from packages.ingest.dry_run import DRY_RUN_FD_PAYLOAD
from packages.ingest.normalize import seed_competitions
from packages.ingest.pipeline import AdapterBundle
from packages.ingest.triggers import (
    TRIGGER_SCAN_INTERVAL,
    TRIGGER_SCAN_MISFIRE_GRACE,
    TRIGGER_SCAN_WINDOW,
)
from packages.models.poisson import HadPrediction
from packages.shared.config import Settings
from packages.shared.time import ensure_utc

FETCHED_AT = datetime(2026, 8, 15, 12, 45, tzinfo=UTC)
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "hkjc"
HAD_PAYLOAD = json.loads((FIXTURES / "had.json").read_text(encoding="utf-8"))
RESULTS_PAYLOAD = json.loads((FIXTURES / "results.json").read_text(encoding="utf-8"))

STANDARD_LINEUP_PAYLOAD = {
    "content": {
        "lineup": {
            "homeTeam": {
                "formation": "4-3-3",
                "starters": [{"id": 1, "name": "Home GK", "position": "GK"}],
                "subs": [],
            },
            "awayTeam": {
                "formation": "4-2-3-1",
                "starters": [{"id": 2, "name": "Away GK", "position": "GK"}],
                "subs": [],
            },
        }
    }
}


class _FakeFotMob:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def fetch_match_details(self, match_id: int) -> FetchResult:
        raw_text = json.dumps(self._payload, sort_keys=True)
        return FetchResult(
            source_name="fotmob",
            source_url=f"https://fixture.local/fotmob/{match_id}",
            fetched_at=FETCHED_AT,
            http_status=200,
            schema_version="api-v1",
            payload=self._payload,
            payload_hash=hash_text(raw_text),
            raw_text=raw_text,
        )


class _FakeFootballData:
    schema_version = "v4"

    def fetch_matches(
        self,
        competition_code: str,
        season_start_year: int,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> FetchResult:
        raw_text = json.dumps(DRY_RUN_FD_PAYLOAD, sort_keys=True)
        return FetchResult(
            source_name="football-data.org",
            source_url="https://fixture.local/football-data",
            fetched_at=FETCHED_AT,
            http_status=200,
            schema_version=self.schema_version,
            payload=DRY_RUN_FD_PAYLOAD,
            payload_hash=hash_text(raw_text),
            raw_text=raw_text,
        )


class _FinishedFootballData:
    schema_version = "v4"

    def fetch_matches(
        self,
        competition_code: str,
        season_start_year: int,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> FetchResult:
        payload = copy.deepcopy(DRY_RUN_FD_PAYLOAD)
        match = payload["matches"][0]
        match["status"] = "FINISHED"
        match["score"] = {
            "duration": "REGULAR",
            "fullTime": {"home": 2, "away": 1},
        }
        raw_text = json.dumps(payload, sort_keys=True)
        return FetchResult(
            source_name="football-data.org",
            source_url="https://fixture.local/football-data",
            fetched_at=FETCHED_AT,
            http_status=200,
            schema_version=self.schema_version,
            payload=payload,
            payload_hash=hash_text(raw_text),
            raw_text=raw_text,
        )


class _FailingFootballData:
    schema_version = "v4"

    def fetch_matches(
        self,
        competition_code: str,
        season_start_year: int,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> FetchResult:
        raise AdapterHTTPError("football-data unavailable")


def _fetch_result(source_name: str, payload: dict) -> FetchResult:
    raw_text = json.dumps(payload, sort_keys=True)
    return FetchResult(
        source_name=source_name,
        source_url=f"https://fixture.local/{source_name}",
        fetched_at=FETCHED_AT,
        http_status=200,
        schema_version="graphql-v1",
        payload=payload,
        payload_hash=hash_text(raw_text),
        raw_text=raw_text,
    )


class _FakeHkjc:
    schema_version = "graphql-v1"
    query_version = "test-v1"

    def fetch_market_odds(
        self,
        market: MarketType,
        match_source_id: str,
    ) -> FetchResult:
        return _fetch_result("hkjc", HAD_PAYLOAD)

    def fetch_match_results(
        self,
        match_source_id: str,
        *,
        match_date: date | None = None,
    ) -> FetchResult:
        return _fetch_result("hkjc", RESULTS_PAYLOAD)

    def fetch_scheduled_matches(
        self,
        start_date,
        end_date,
        *,
        start_index: int = 1,
        end_index: int = 100,
    ) -> FetchResult:
        return _fetch_result("hkjc", HAD_PAYLOAD)


class _NoOfferHkjc(_FakeHkjc):
    def fetch_market_odds(
        self,
        market: MarketType,
        match_source_id: str,
    ) -> FetchResult:
        payload = copy.deepcopy(HAD_PAYLOAD)
        for match in payload["data"]["matches"]:
            if match["id"] == match_source_id:
                match["foPools"][0]["status"] = "SUSPENDED"
        return _fetch_result("hkjc", payload)


class _FailingFotMob:
    def fetch_match_details(self, match_id: int) -> FetchResult:
        raise AdapterHTTPError("fotmob unavailable")


class _FailingScheduledHkjc:
    schema_version = "graphql-v1"
    query_version = "test-v1"

    def fetch_market_odds(
        self,
        market: MarketType,
        match_source_id: str,
    ) -> FetchResult:
        raise AdapterHTTPError("hkjc unavailable")

    def fetch_match_results(
        self,
        match_source_id: str,
        *,
        match_date: date | None = None,
    ) -> FetchResult:
        raise AdapterHTTPError("hkjc unavailable")

    def fetch_scheduled_matches(
        self,
        start_date,
        end_date,
        *,
        start_index: int = 1,
        end_index: int = 100,
    ) -> FetchResult:
        raise AdapterHTTPError("hkjc unavailable")


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.deleted: list[str] = []

    def set(self, key: str, value: str, nx: bool = False, ex: int | None = None) -> bool:
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def delete(self, key: str) -> None:
        self.deleted.append(key)
        self.values.pop(key, None)


class _FakeQueue:
    def __init__(self, redis: _FakeRedis, *, fail: bool = False) -> None:
        self.connection = redis
        self.fail = fail
        self.jobs: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def enqueue(self, *args: object, **kwargs: object) -> object:
        if self.fail:
            raise RuntimeError("enqueue unavailable")
        self.jobs.append((args, kwargs))
        return object()


class _NoopQueue:
    connection = None

    def enqueue(self, *args: object, **kwargs: object) -> None:
        return None


class _CapturingQueue:
    connection = None

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def enqueue(self, *args: object, **kwargs: object) -> None:
        self.calls.append((args, kwargs))


def _match(
    session,
    *,
    flags: tuple[str, ...] = (),
    source_match_ids: dict[str, str] | None = None,
) -> Match:
    match = Match(
        competition_id=uuid.uuid4(),
        season="2025/26",
        kickoff_at=datetime(2026, 8, 15, 14, 0, tzinfo=UTC),
        home_team_id=uuid.uuid4(),
        away_team_id=uuid.uuid4(),
        status="scheduled",
        source_match_ids=(
            {"fotmob": "123"} if source_match_ids is None else source_match_ids
        ),
        coverage_flags=list(flags),
    )
    session.add(match)
    session.flush()
    return match


def _scheduled_match(session, kickoff_at: datetime) -> Match:
    match = Match(
        competition_id=uuid.uuid4(),
        season="2025/26",
        kickoff_at=kickoff_at,
        home_team_id=uuid.uuid4(),
        away_team_id=uuid.uuid4(),
        status="scheduled",
        source_match_ids={},
        coverage_flags=[],
    )
    session.add(match)
    session.flush()
    return match


def test_run_daily_ingest_bootstraps_a_fresh_database(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        _env_file=None,
    )
    monkeypatch.setattr("apps.worker.jobs.get_settings", lambda: settings)
    monkeypatch.setattr(
        "apps.worker.jobs.build_adapters",
        lambda _settings: AdapterBundle(football_data=_FakeFootballData()),
    )
    monkeypatch.setattr("apps.worker.jobs.build_engine", lambda _url: engine)
    monkeypatch.setattr("apps.worker.jobs.build_session_factory", lambda _engine: factory)

    result = run_daily_ingest(season=2025, competitions=("EPL",))
    assert result["fixtures"] == 1
    assert result["hkjc_linked"] == 0
    assert result["leagues"] == {"EPL": 1}

    with factory() as session:
        assert session.query(Competition).filter_by(code="EPL").count() == 1
        assert session.query(Match).count() == 1
        assert session.query(RawPayload).count() == 1
        teams = {team.slug: team.football_data_id for team in session.query(Team)}
        assert teams == {"arsenal": 10, "chelsea": 20}
        match = session.query(Match).one()
        assert match.source_match_ids["football-data.org"] == "1001"
        run = session.query(SourceFetchRun).one()
        assert run.source_name == "football-data.org"
        assert run.status is FetchRunStatus.SUCCEEDED
        assert run.source_status is SourceStatus.CONDITIONAL
        assert run.schema_scope == "live smoke"
        assert run.field_scope == "EPL fixtures"
        assert run.licensing_check == "public/free tier"
        assert run.request_count == 1
        assert run.error_count == 0
        raw = session.query(RawPayload).one()
        assert raw.run_id == run.run_id
    engine.dispose()


def test_recent_result_refresh_finalises_a_live_match(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        _env_file=None,
    )
    now = datetime(2026, 8, 15, 16, 0, tzinfo=UTC)
    with factory() as setup:
        seed_competitions(setup)
        competition = setup.query(Competition).filter_by(code="UCL").one()
        home = Team(
            slug="arsenal",
            name="Arsenal",
            short_name="Arsenal",
            country="England",
            football_data_id=10,
        )
        away = Team(
            slug="chelsea",
            name="Chelsea",
            short_name="Chelsea",
            country="England",
            football_data_id=20,
        )
        setup.add_all([home, away])
        setup.flush()
        match = Match(
            competition_id=competition.id,
            season="2025/26",
            kickoff_at=datetime(2026, 8, 15, 14, 0, tzinfo=UTC),
            first_seen_at=datetime(2026, 8, 15, 12, 0, tzinfo=UTC),
            home_team_id=home.id,
            away_team_id=away.id,
            status=MatchStatus.LIVE,
            home_goals_90=1,
            away_goals_90=0,
            home_goals_final=1,
            away_goals_final=0,
            source_match_ids={"football-data.org": "1001"},
            coverage_flags=[],
        )
        setup.add(match)
        setup.commit()
        match_id = match.id
    monkeypatch.setattr("apps.worker.jobs.get_settings", lambda: settings)
    monkeypatch.setattr("apps.worker.jobs.build_engine", lambda _url: engine)
    monkeypatch.setattr("apps.worker.jobs.build_session_factory", lambda _engine: factory)
    monkeypatch.setattr(
        "apps.worker.jobs.build_adapters",
        lambda _settings: AdapterBundle(football_data=_FinishedFootballData()),
    )

    result = run_recent_result_refresh(now=now)
    assert result == {"fixtures": 1, "leagues": {"UCL": 1}}

    with factory() as verify:
        refreshed = verify.get(Match, match_id)
        assert refreshed is not None
        assert refreshed.status is MatchStatus.FINISHED
        assert refreshed.home_goals_90 == 2
        assert refreshed.away_goals_90 == 1
        run = verify.query(SourceFetchRun).one()
        assert run.field_scope == "recent UCL fixtures"
        assert run.status is FetchRunStatus.SUCCEEDED
    engine.dispose()


def test_run_daily_ingest_covers_all_domestic_leagues(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        _env_file=None,
    )
    monkeypatch.setattr("apps.worker.jobs.get_settings", lambda: settings)
    monkeypatch.setattr(
        "apps.worker.jobs.build_adapters",
        lambda _settings: AdapterBundle(football_data=_FakeFootballData()),
    )
    monkeypatch.setattr("apps.worker.jobs.build_engine", lambda _url: engine)
    monkeypatch.setattr("apps.worker.jobs.build_session_factory", lambda _engine: factory)

    result = run_daily_ingest(
        season=2025,
        competitions=("EPL", "LALIGA", "BUNDESLIGA", "SERIEA", "LIGUE1", "UCL"),
    )

    assert result["leagues"] == {
        "EPL": 1,
        "LALIGA": 1,
        "BUNDESLIGA": 1,
        "SERIEA": 1,
        "LIGUE1": 1,
        "UCL": 1,
    }
    engine.dispose()


def test_run_daily_ingest_keeps_fixtures_when_hkjc_fails(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        _env_file=None,
    )
    monkeypatch.setattr("apps.worker.jobs.get_settings", lambda: settings)
    monkeypatch.setattr(
        "apps.worker.jobs.build_adapters",
        lambda _settings: AdapterBundle(
            football_data=_FakeFootballData(),
            hkjc=_FailingScheduledHkjc(),
        ),
    )
    monkeypatch.setattr("apps.worker.jobs.build_engine", lambda _url: engine)
    monkeypatch.setattr("apps.worker.jobs.build_session_factory", lambda _engine: factory)

    result = run_daily_ingest(season=2025, competitions=("EPL",))
    assert result["fixtures"] == 1
    assert result["hkjc_linked"] == 0
    assert result["leagues"] == {"EPL": 1}

    with factory() as session:
        assert session.query(Match).count() == 1
        runs = {
            run.source_name: run for run in session.query(SourceFetchRun).all()
        }
        assert runs["football-data.org"].status is FetchRunStatus.SUCCEEDED
        assert runs["hkjc"].status is FetchRunStatus.FAILED
        assert runs["hkjc"].error_count == 1
        assert "hkjc unavailable" in (runs["hkjc"].error_summary or "")
        assert runs["hkjc"].field_scope == "multi-league fixtures"
    engine.dispose()


def test_run_daily_ingest_records_a_failed_football_data_run(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        _env_file=None,
    )
    monkeypatch.setattr("apps.worker.jobs.get_settings", lambda: settings)
    monkeypatch.setattr(
        "apps.worker.jobs.build_adapters",
        lambda _settings: AdapterBundle(football_data=_FailingFootballData()),
    )
    monkeypatch.setattr("apps.worker.jobs.build_engine", lambda _url: engine)
    monkeypatch.setattr("apps.worker.jobs.build_session_factory", lambda _engine: factory)

    with pytest.raises(AdapterHTTPError, match="football-data unavailable"):
        run_daily_ingest(season=2025)

    with factory() as session:
        run = session.query(SourceFetchRun).one()
        assert run.source_name == "football-data.org"
        assert run.status is FetchRunStatus.FAILED
        assert run.error_count == 1
        assert "football-data unavailable" in (run.error_summary or "")
        assert session.query(Match).count() == 0
    engine.dispose()


@pytest.mark.parametrize(
    ("trigger", "kind"),
    [
        ("T-24h", SnapshotKind.T24H),
        ("T-3h", SnapshotKind.T3H),
        ("T-30m", SnapshotKind.T30M),
        ("T-5m", SnapshotKind.T5M),
    ],
)
def test_ingest_trigger_odds_persists_had_snapshot(session, trigger, kind):
    match = _match(session, source_match_ids={"hkjc": "50079081"})
    now = datetime(2026, 8, 15, 13, 0, tzinfo=UTC)

    result = ingest_trigger_odds(
        session,
        match,
        trigger,
        AdapterBundle(hkjc=_FakeHkjc()),
        now=now,
    )

    assert result["status"] == "ingested"
    assert result["trigger"] == trigger
    assert result["snapshot_kind"] == kind.value
    assert result["line_count"] == 3
    snapshot = session.query(OddsSnapshot).one()
    assert snapshot.snapshot_kind is kind
    assert ensure_utc(snapshot.snapshot_at) == now
    assert session.query(MarketLine).count() == 3
    assert session.query(PaperBet).count() == 0
    run = session.query(SourceFetchRun).one()
    assert run.source_name == "hkjc"
    assert run.status is FetchRunStatus.SUCCEEDED
    assert run.field_scope == "HAD odds"
    raw = session.query(RawPayload).one()
    assert raw.run_id == run.run_id


def test_ingest_trigger_odds_reports_missing_hkjc_link(session):
    match = _match(session, source_match_ids={})

    result = ingest_trigger_odds(
        session,
        match,
        "T-24h",
        AdapterBundle(hkjc=_FakeHkjc()),
        now=datetime(2026, 8, 15, 13, 0, tzinfo=UTC),
    )

    assert result == {
        "status": "link_missing",
        "trigger": "T-24h",
        "snapshot_kind": SnapshotKind.T24H.value,
    }
    assert session.query(OddsSnapshot).count() == 0


def test_ingest_trigger_odds_reports_no_offer_for_suspended_pool(session):
    match = _match(session, source_match_ids={"hkjc": "50079081"})

    result = ingest_trigger_odds(
        session,
        match,
        "T-24h",
        AdapterBundle(hkjc=_NoOfferHkjc()),
        now=datetime(2026, 8, 15, 13, 0, tzinfo=UTC),
    )

    assert result["status"] == "no_offer"
    assert result["line_count"] == 0
    assert session.query(OddsSnapshot).count() == 1
    assert session.query(MarketLine).count() == 0


def test_ingest_trigger_odds_refuses_snapshot_after_kickoff(session):
    match = _match(session, source_match_ids={"hkjc": "50079081"})

    result = ingest_trigger_odds(
        session,
        match,
        "T-5m",
        AdapterBundle(hkjc=_FakeHkjc()),
        now=datetime(2026, 8, 15, 14, 0, tzinfo=UTC),
    )

    assert result == {
        "status": "after_kickoff",
        "trigger": "T-5m",
        "snapshot_kind": SnapshotKind.T5M.value,
    }
    assert session.query(OddsSnapshot).count() == 0


def test_t30_lineup_recheck_also_ingests_had_snapshot(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        _env_file=None,
    )
    with factory() as setup:
        match = _match(
            setup,
            source_match_ids={"fotmob": "123", "hkjc": "50079081"},
        )
        setup.commit()
        match_id = str(match.id)

    monkeypatch.setattr("apps.worker.jobs.get_settings", lambda: settings)
    monkeypatch.setattr("apps.worker.jobs.build_engine", lambda _url: engine)
    monkeypatch.setattr("apps.worker.jobs.build_session_factory", lambda _engine: factory)
    monkeypatch.setattr(
        "apps.worker.jobs.build_adapters",
        lambda _settings: AdapterBundle(
            fotmob=_FakeFotMob(STANDARD_LINEUP_PAYLOAD),
            hkjc=_FakeHkjc(),
        ),
    )
    monkeypatch.setattr(
        "apps.worker.jobs.utc_now",
        lambda: datetime(2026, 8, 15, 13, 0, tzinfo=UTC),
    )

    result = run_lineup_check(match_id, "T-30m")

    assert result["lineup"] == "confirmed"
    assert result["odds"] == "ingested"
    assert result["decision"] == "skipped"
    with factory() as verify:
        assert verify.query(OddsSnapshot).count() == 1
        assert verify.query(PaperBet).count() == 0
    engine.dispose()


def test_t30_epl_match_runs_decision_after_odds_ingest(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        _env_file=None,
    )
    with factory() as setup:
        competition = Competition(
            code="EPL",
            name="English Premier League",
            country="England",
            is_cup=False,
            football_data_code="PL",
        )
        home = Team(slug="home", name="Home", short_name="HOM", country="England")
        away = Team(slug="away", name="Away", short_name="AWY", country="England")
        setup.add_all([competition, home, away])
        setup.flush()
        match = Match(
            competition_id=competition.id,
            season="2025/26",
            kickoff_at=datetime(2026, 8, 15, 14, 0, tzinfo=UTC),
            first_seen_at=datetime(2026, 8, 15, 12, 0, tzinfo=UTC),
            home_team_id=home.id,
            away_team_id=away.id,
            status=MatchStatus.SCHEDULED,
            source_match_ids={"fotmob": "123", "hkjc": "50079081"},
            coverage_flags=[],
        )
        setup.add(match)
        setup.commit()
        match_id = str(match.id)

    prediction = HadPrediction(
        p_home=Decimal("0.20"),
        p_draw=Decimal("0.35"),
        p_away=Decimal("0.45"),
        score_distribution=MappingProxyType(
            {
                (0, 0): Decimal("0.20"),
                (1, 0): Decimal("0.20"),
                (0, 1): Decimal("0.45"),
                (1, 1): Decimal("0.15"),
            }
        ),
        tail_mass=Decimal(0),
        score_grid_max=1,
        tail_handling="grid_complete",
    )
    monkeypatch.setattr(
        "packages.decision.service.predict_had",
        lambda *_args, **_kwargs: prediction,
    )
    monkeypatch.setattr("apps.worker.jobs.get_settings", lambda: settings)
    monkeypatch.setattr("apps.worker.jobs.build_engine", lambda _url: engine)
    monkeypatch.setattr("apps.worker.jobs.build_session_factory", lambda _engine: factory)
    monkeypatch.setattr(
        "apps.worker.jobs.build_adapters",
        lambda _settings: AdapterBundle(
            fotmob=_FakeFotMob(STANDARD_LINEUP_PAYLOAD),
            hkjc=_FakeHkjc(),
        ),
    )
    monkeypatch.setattr(
        "apps.worker.jobs.utc_now",
        lambda: datetime(2026, 8, 15, 13, 0, tzinfo=UTC),
    )

    result = run_lineup_check(match_id, "T-30m")

    assert result["odds"] == "ingested"
    assert result["decision"] == "no_bet"
    with factory() as verify:
        assert verify.query(ModelPrediction).count() == 3
        assert verify.query(PaperBet).count() == 0
    engine.dispose()


def test_load_hkjc_result_persists_raw_result_before_parsing(session, monkeypatch):
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        _env_file=None,
    )
    match = _match(session, source_match_ids={"hkjc": "50078622"})
    monkeypatch.setattr(
        "apps.worker.jobs.build_adapters",
        lambda _settings: AdapterBundle(hkjc=_FakeHkjc()),
    )

    result = _load_hkjc_result(session, settings, match)

    assert result is not None
    assert (result.raw_home_result, result.raw_away_result) == (4, 1)
    raw = session.query(RawPayload).one()
    assert raw.source_name == "hkjc"
    assert raw.schema_version == "graphql-v1"
    assert raw.body == RESULTS_PAYLOAD
    run = session.query(SourceFetchRun).one()
    assert run.status is FetchRunStatus.SUCCEEDED
    assert run.field_scope == "match results"
    assert raw.run_id == run.run_id


def test_t75_lineup_check_confirms_and_clears_unconfirmed_flag(session):
    match = _match(session, flags=("lineup_unconfirmed", "lineup_link_missing"))
    status = check_lineup(
        match,
        "T-75m",
        AdapterBundle(fotmob=_FakeFotMob(STANDARD_LINEUP_PAYLOAD)),
    )
    assert status == "confirmed"
    assert "lineup_unconfirmed" not in match.coverage_flags
    assert "lineup_link_missing" not in match.coverage_flags


def test_lineup_gate_records_missing_fotmob_link(session):
    match = _match(session, source_match_ids={})
    status = check_lineup(
        match,
        "T-75m",
        AdapterBundle(fotmob=_FakeFotMob(STANDARD_LINEUP_PAYLOAD)),
    )
    assert status == "link_missing"
    assert "lineup_link_missing" in match.coverage_flags
    assert "lineup_unconfirmed" in match.coverage_flags


def test_t30_recheck_marks_lineup_unconfirmed_when_missing(session):
    match = _match(session)
    status = check_lineup(
        match,
        "T-30m",
        AdapterBundle(fotmob=_FakeFotMob({"content": {}})),
    )
    assert status == "unconfirmed"
    assert "lineup_unconfirmed" in match.coverage_flags


def test_lineup_check_rejects_a_non_lineup_trigger(session):
    match = _match(session)
    with pytest.raises(ValueError, match="not a lineup trigger"):
        check_lineup(
            match,
            "T-24h",
            AdapterBundle(fotmob=_FakeFotMob(STANDARD_LINEUP_PAYLOAD)),
        )


def test_ucl_result_gate_only_applies_to_knockout_matches():
    assert _ucl_result_requires_gate("UCL", 4) is False
    assert _ucl_result_requires_gate("UCL", 9) is True
    assert _ucl_result_requires_gate("UCL", None) is True
    assert _ucl_result_requires_gate("EPL", None) is False


def test_settlement_scan_settles_only_pending_matches_after_kickoff(
    session, monkeypatch
):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        _env_file=None,
    )
    with factory() as setup:
        match = _match(setup)
        setup.add(
            PaperBet(
                match_id=match.id,
                market=MarketType.HAD,
                line_key="0.0",
                selection=Side.H,
                odds_decimal=Decimal("2.00"),
                stake=Decimal("10.00"),
                bankroll_before=Decimal("10000.00"),
                placed_at=match.kickoff_at,
                status=BetStatus.PENDING,
                analysis_run_key="analysis",
                decision_slot_key="slot",
                bet_intent_key="intent",
                decision_at=match.kickoff_at,
            )
        )
        setup.commit()

    monkeypatch.setattr("apps.worker.jobs.get_settings", lambda: settings)
    monkeypatch.setattr("apps.worker.jobs.build_engine", lambda _url: engine)
    monkeypatch.setattr("apps.worker.jobs.build_session_factory", lambda _engine: factory)
    monkeypatch.setattr(
        "apps.worker.jobs.settle_match",
        lambda _match_id, **_kwargs: {"settled": 1},
    )

    result = run_settlement_scan(
        now=datetime(2026, 8, 15, 18, 0, tzinfo=UTC)
    )

    assert result == {"matches": 1, "settled": 1, "errors": 0}
    engine.dispose()


def test_decision_probability_reads_the_latest_matching_prediction(session):
    match = _match(session)
    decision_at = datetime(2026, 8, 15, 13, 30, tzinfo=UTC)
    bet = PaperBet(
        match_id=match.id,
        market=MarketType.HAD,
        line_key="0.0",
        selection=Side.H,
        odds_decimal=Decimal("2.00"),
        stake=Decimal("10.00"),
        bankroll_before=Decimal("10000.00"),
        placed_at=decision_at,
        status=BetStatus.PENDING,
        analysis_run_key="analysis",
        decision_slot_key="slot",
        bet_intent_key="intent",
        decision_at=decision_at,
    )
    prediction = ModelPrediction(
        match_id=match.id,
        market=MarketType.HAD,
        line_key="0.0",
        outcome=Side.H,
        probability=Decimal("0.550000"),
        score_distribution={},
        return_distribution=None,
        decision_at=decision_at,
        model_version="poisson-v1",
        analysis_run_key="analysis",
    )
    session.add_all([bet, prediction])
    session.flush()

    assert _decision_probability(session, bet) == Decimal("0.550000")


def test_run_decision_reconciliation_logs_a_scheduled_epl_match(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        _env_file=None,
    )
    now = datetime(2026, 8, 15, 13, 30, tzinfo=UTC)
    with factory() as setup:
        competition = Competition(
            code="EPL",
            name="English Premier League",
            country="England",
            is_cup=False,
            football_data_code="PL",
        )
        home = Team(slug="home", name="Home", short_name="HOM", country="England")
        away = Team(slug="away", name="Away", short_name="AWY", country="England")
        setup.add_all([competition, home, away])
        setup.flush()
        match = Match(
            competition_id=competition.id,
            season="2025/26",
            kickoff_at=now + timedelta(minutes=20),
            first_seen_at=now - timedelta(hours=1),
            home_team_id=home.id,
            away_team_id=away.id,
            status=MatchStatus.SCHEDULED,
            source_match_ids={},
            coverage_flags=[],
        )
        setup.add(match)
        setup.commit()
        match_id = match.id

    monkeypatch.setattr("apps.worker.jobs.get_settings", lambda: settings)
    monkeypatch.setattr("apps.worker.jobs.build_engine", lambda _url: engine)
    monkeypatch.setattr("apps.worker.jobs.build_session_factory", lambda _engine: factory)

    assert run_decision_reconciliation(now=now) == {"reconciled": 1, "errors": 0}

    with factory() as verify:
        log = verify.query(DecisionLog).one()
        assert log.match_id == match_id
        assert log.status == "skipped"
        assert log.prediction_count == 0
        assert log.reason.strip()
    engine.dispose()


def test_scheduler_includes_a_recent_result_refresh_job():
    scheduler = build_scheduler(queue=_NoopQueue())
    job = scheduler.get_job("recent-result-refresh")
    assert job is not None
    assert job.trigger.interval == timedelta(minutes=15)


def test_scheduler_includes_a_settlement_scan_job():
    scheduler = build_scheduler(queue=_NoopQueue())
    assert scheduler.get_job("settlement-scan") is not None


def test_settlement_scan_allows_the_rate_limited_result_pipeline():
    queue = _CapturingQueue()
    _enqueue_settlement_scan(queue)

    assert queue.calls == [
        (("apps.worker.jobs.run_settlement_scan",), {"job_timeout": 1800})
    ]


def test_scheduler_includes_a_decision_reconciliation_job():
    scheduler = build_scheduler(queue=_NoopQueue())
    job = scheduler.get_job("decision-reconciliation")
    assert job is not None
    assert job.trigger.interval == timedelta(minutes=5)


def test_scheduler_includes_a_weekly_calibration_report_job():
    scheduler = build_scheduler(queue=_NoopQueue())
    job = scheduler.get_job("calibration-report")
    assert job is not None
    assert job.trigger.interval == timedelta(days=7)


def test_run_calibration_report_defaults_to_the_current_month(monkeypatch):
    engine, _factory = _worker_runtime(monkeypatch)
    captured: dict[str, str] = {}

    def _fake_build(_session, *, time_block: str):
        captured["time_block"] = time_block
        return []

    monkeypatch.setattr("apps.worker.jobs.ensure_g1_versions", lambda _session: None)
    monkeypatch.setattr("apps.worker.jobs.build_calibration_report", _fake_build)

    assert run_calibration_report() == {"time_block": "2026-08", "metrics": 0}
    assert captured["time_block"] == "2026-08"
    assert run_calibration_report(time_block="2026-10") == {
        "time_block": "2026-10",
        "metrics": 0,
    }
    engine.dispose()


def test_scheduler_grace_covers_the_trigger_scan_interval():
    scheduler = build_scheduler(queue=_NoopQueue())
    daily = scheduler.get_job("daily-ingest")
    scan = scheduler.get_job("match-trigger-scan")
    grace = int(TRIGGER_SCAN_MISFIRE_GRACE.total_seconds())

    assert daily.misfire_grace_time == grace
    assert scan.misfire_grace_time == grace
    assert scan.trigger.interval == TRIGGER_SCAN_INTERVAL
    assert TRIGGER_SCAN_WINDOW >= TRIGGER_SCAN_INTERVAL + TRIGGER_SCAN_MISFIRE_GRACE


def test_enqueue_failure_releases_dedupe_key_for_retry(session):
    now = datetime(2026, 8, 15, 13, 30, tzinfo=UTC)
    match = _scheduled_match(session, now + timedelta(minutes=30))
    key = f"football:trigger:{match.id}:T-30m"
    redis = _FakeRedis()

    with pytest.raises(RuntimeError, match="enqueue unavailable"):
        enqueue_due_match_triggers(
            now=now,
            queue=_FakeQueue(redis, fail=True),
            session=session,
        )

    assert redis.values == {}
    assert redis.deleted == [key]

    queue = _FakeQueue(redis)
    assert enqueue_due_match_triggers(now=now, queue=queue, session=session) == 1
    assert len(queue.jobs) == 1
    args, kwargs = queue.jobs[0]
    assert args == ("apps.worker.jobs.run_lineup_check", str(match.id), "T-30m")
    assert kwargs["meta"] == {"dedupe_key": key}
    assert kwargs["on_failure"] is release_trigger_dedupe
    assert redis.values == {key: "1"}

    assert enqueue_due_match_triggers(now=now, queue=queue, session=session) == 0
    assert len(queue.jobs) == 1


def test_trigger_failure_callback_releases_the_dedupe_key():
    class _Job:
        def __init__(self) -> None:
            self.meta = {"dedupe_key": "football:trigger:match:T-30m"}

    redis = _FakeRedis()
    release_trigger_dedupe(_Job(), redis, RuntimeError, RuntimeError("boom"), None)
    assert redis.deleted == ["football:trigger:match:T-30m"]


def _worker_runtime(monkeypatch, *, fotmob=None, hkjc=None, now=None):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        _env_file=None,
    )
    monkeypatch.setattr("apps.worker.jobs.get_settings", lambda: settings)
    monkeypatch.setattr("apps.worker.jobs.build_engine", lambda _url: engine)
    monkeypatch.setattr("apps.worker.jobs.build_session_factory", lambda _engine: factory)
    monkeypatch.setattr(
        "apps.worker.jobs.build_adapters",
        lambda _settings: AdapterBundle(fotmob=fotmob, hkjc=hkjc),
    )
    monkeypatch.setattr(
        "apps.worker.jobs.utc_now",
        lambda: now or datetime(2026, 8, 15, 13, 0, tzinfo=UTC),
    )
    return engine, factory


def _seed_t30_match(factory, *, source_match_ids):
    with factory() as setup:
        match = _match(setup, source_match_ids=source_match_ids)
        setup.commit()
        return str(match.id)


def test_t30_no_offer_keeps_snapshot_and_log_before_raising(monkeypatch):
    engine, factory = _worker_runtime(
        monkeypatch,
        fotmob=_FakeFotMob(STANDARD_LINEUP_PAYLOAD),
        hkjc=_NoOfferHkjc(),
    )
    match_id = _seed_t30_match(
        factory,
        source_match_ids={"fotmob": "123", "hkjc": "50079081"},
    )

    with pytest.raises(OddsNotOfferedError):
        run_lineup_check(match_id, "T-30m")

    with factory() as verify:
        assert verify.query(SourceFetchRun).one().status is FetchRunStatus.SUCCEEDED
        assert verify.query(RawPayload).count() == 1
        assert verify.query(OddsSnapshot).count() == 1
        log = verify.query(DecisionLog).one()
        assert log.status == "skipped"
        assert log.reason.strip()
    engine.dispose()


def test_t30_odds_adapter_error_keeps_failed_run_and_log(monkeypatch):
    engine, factory = _worker_runtime(
        monkeypatch,
        fotmob=_FakeFotMob(STANDARD_LINEUP_PAYLOAD),
        hkjc=_FailingScheduledHkjc(),
    )
    match_id = _seed_t30_match(
        factory,
        source_match_ids={"fotmob": "123", "hkjc": "50079081"},
    )

    with pytest.raises(AdapterHTTPError, match="hkjc unavailable"):
        run_lineup_check(match_id, "T-30m")

    with factory() as verify:
        assert verify.query(SourceFetchRun).one().status is FetchRunStatus.FAILED
        log = verify.query(DecisionLog).one()
        assert log.status == "skipped"
        assert log.reason.strip()
    engine.dispose()


def test_t30_lineup_adapter_error_still_writes_a_log(monkeypatch):
    engine, factory = _worker_runtime(
        monkeypatch,
        fotmob=_FailingFotMob(),
        hkjc=_FakeHkjc(),
    )
    match_id = _seed_t30_match(
        factory,
        source_match_ids={"fotmob": "123", "hkjc": "50079081"},
    )

    with pytest.raises(AdapterHTTPError, match="fotmob unavailable"):
        run_lineup_check(match_id, "T-30m")

    with factory() as verify:
        log = verify.query(DecisionLog).one()
        assert log.status == "skipped"
    engine.dispose()


def test_t30_missing_hkjc_link_logs_and_does_not_raise(monkeypatch):
    engine, factory = _worker_runtime(
        monkeypatch,
        fotmob=_FakeFotMob(STANDARD_LINEUP_PAYLOAD),
        hkjc=_FakeHkjc(),
    )
    match_id = _seed_t30_match(factory, source_match_ids={"fotmob": "123"})

    result = run_lineup_check(match_id, "T-30m")

    assert result["odds"] == "link_missing"
    assert result["decision"] == "skipped"
    with factory() as verify:
        assert verify.query(DecisionLog).one().status == "skipped"
    engine.dispose()


def test_match_trigger_no_offer_keeps_audit_rows(monkeypatch):
    engine, factory = _worker_runtime(monkeypatch, hkjc=_NoOfferHkjc())
    match_id = _seed_t30_match(
        factory,
        source_match_ids={"hkjc": "50079081"},
    )

    with pytest.raises(OddsNotOfferedError):
        run_match_trigger(match_id, "T-24h")

    with factory() as verify:
        assert verify.query(SourceFetchRun).one().status is FetchRunStatus.SUCCEEDED
        assert verify.query(RawPayload).count() == 1
        assert verify.query(OddsSnapshot).count() == 1
        assert verify.query(DecisionLog).count() == 0
    engine.dispose()


def test_settlement_scan_isolates_per_match_errors(monkeypatch):
    engine, factory = _worker_runtime(monkeypatch)
    with factory() as setup:
        for slot in ("slot-a", "slot-b"):
            match = _match(setup)
            setup.add(
                PaperBet(
                    match_id=match.id,
                    market=MarketType.HAD,
                    line_key="0.0",
                    selection=Side.H,
                    odds_decimal=Decimal("2.00"),
                    stake=Decimal("10.00"),
                    bankroll_before=Decimal("10000.00"),
                    placed_at=match.kickoff_at,
                    status=BetStatus.PENDING,
                    analysis_run_key=slot,
                    decision_slot_key=slot,
                    bet_intent_key=slot,
                    decision_at=match.kickoff_at,
                )
            )
        setup.commit()

    calls = {"count": 0}

    def _fake_settle(_match_id, **_kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("settlement boom")
        return {"settled": 1}

    monkeypatch.setattr("apps.worker.jobs.settle_match", _fake_settle)

    result = run_settlement_scan(now=datetime(2026, 8, 15, 18, 0, tzinfo=UTC))

    assert result == {"matches": 2, "settled": 1, "errors": 1}
    engine.dispose()


def _seed_epl_match(factory, kickoff_at):
    with factory() as setup:
        competition = setup.query(Competition).filter_by(code="EPL").one_or_none()
        if competition is None:
            competition = Competition(
                code="EPL",
                name="English Premier League",
                country="England",
                is_cup=False,
                football_data_code="PL",
            )
            setup.add(competition)
            setup.flush()
        home = Team(
            slug=f"home-{uuid.uuid4().hex}",
            name="Home",
            short_name="HOM",
            country="England",
        )
        away = Team(
            slug=f"away-{uuid.uuid4().hex}",
            name="Away",
            short_name="AWY",
            country="England",
        )
        setup.add_all([home, away])
        setup.flush()
        match = Match(
            competition_id=competition.id,
            season="2025/26",
            kickoff_at=kickoff_at,
            first_seen_at=kickoff_at - timedelta(hours=2),
            home_team_id=home.id,
            away_team_id=away.id,
            status=MatchStatus.SCHEDULED,
            source_match_ids={},
            coverage_flags=[],
        )
        setup.add(match)
        setup.commit()
        return match.id


def test_reconciliation_isolates_per_match_errors(monkeypatch):
    engine, factory = _worker_runtime(monkeypatch)
    now = datetime(2026, 8, 15, 13, 30, tzinfo=UTC)
    _seed_epl_match(factory, now + timedelta(minutes=10))
    _seed_epl_match(factory, now + timedelta(minutes=20))

    calls = {"count": 0}

    def _fake_decide(*_args, **_kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("decision boom")

    monkeypatch.setattr("packages.decision.coverage.decide_match", _fake_decide)

    result = run_decision_reconciliation(now=now)

    assert result == {"reconciled": 1, "errors": 1}
    with factory() as verify:
        assert verify.query(DecisionLog).count() == 0
    engine.dispose()
