import json
import uuid
from datetime import UTC, date, datetime
from pathlib import Path

from packages.adapters.base import FetchResult, hash_text
from packages.db.models import Match, RawPayload
from packages.domain.enums import MarketType, MatchStatus, SnapshotKind
from packages.ingest.dry_run import DRY_RUN_FD_PAYLOAD
from packages.ingest.normalize import seed_competitions
from packages.ingest.pipeline import AdapterBundle, IngestPipeline

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "hkjc"
HAD_PAYLOAD = json.loads((FIXTURES / "had.json").read_text(encoding="utf-8"))
FETCHED_AT = datetime(2026, 11, 1, 0, 0, tzinfo=UTC)


def _result(source_name: str, payload: dict) -> FetchResult:
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


class _FakeFootballData:
    schema_version = "v4"

    def fetch_matches(
        self,
        competition_code: str,
        season_start_year: int,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> FetchResult:
        return _result("football-data.org", DRY_RUN_FD_PAYLOAD)


class _FakeHkjc:
    schema_version = "graphql-v1"
    query_version = "test-v1"

    def fetch_scheduled_matches(
        self,
        start_date: date,
        end_date: date,
        *,
        start_index: int = 1,
        end_index: int = 100,
    ) -> FetchResult:
        return _result("hkjc", HAD_PAYLOAD)

    def fetch_market_odds(
        self,
        market: MarketType,
        match_source_id: str,
    ) -> FetchResult:
        return _result("hkjc", HAD_PAYLOAD)

    def fetch_match_results(
        self,
        match_source_id: str,
        *,
        match_date: date | None = None,
    ) -> FetchResult:
        raise AssertionError("pipeline tests must not fetch results")


def test_ingest_fixtures_uses_the_supplied_run_id(session):
    seed_competitions(session)
    pipeline = IngestPipeline(
        session,
        AdapterBundle(football_data=_FakeFootballData()),
    )

    count = pipeline.ingest_fixtures(
        "EPL",
        2025,
        bootstrap_teams=True,
        run_id="fixtures-run",
    )

    assert count == 1
    raw = session.query(RawPayload).one()
    assert raw.source_name == "football-data.org"
    assert raw.run_id == "fixtures-run"


def test_link_hkjc_uses_the_supplied_run_id(session):
    seed_competitions(session)
    pipeline = IngestPipeline(session, AdapterBundle(hkjc=_FakeHkjc()))

    _ = pipeline.link_hkjc(
        "EPL",
        date(2026, 11, 1),
        date(2026, 11, 7),
        run_id="link-run",
    )

    raw = session.query(RawPayload).one()
    assert raw.source_name == "hkjc"
    assert raw.run_id == "link-run"


def test_ingest_hkjc_odds_uses_the_supplied_run_id(session):
    match = Match(
        competition_id=uuid.uuid4(),
        season="2026/27",
        kickoff_at=datetime(2026, 11, 1, 18, 0, tzinfo=UTC),
        home_team_id=uuid.uuid4(),
        away_team_id=uuid.uuid4(),
        status=MatchStatus.SCHEDULED,
        source_match_ids={"hkjc": "50079081"},
        coverage_flags=[],
    )
    session.add(match)
    session.flush()
    pipeline = IngestPipeline(session, AdapterBundle(hkjc=_FakeHkjc()))

    snapshot, lines = pipeline.ingest_hkjc_odds(
        match,
        MarketType.HAD,
        SnapshotKind.T24H,
        datetime(2026, 11, 1, 12, 0, tzinfo=UTC),
        run_id="odds-run",
    )

    assert len(lines) == 3
    assert snapshot.run_id == "odds-run"
    raw = session.query(RawPayload).one()
    assert raw.run_id == "odds-run"
