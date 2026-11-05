import json
from datetime import UTC, date, datetime
from pathlib import Path

from packages.adapters.base import FetchResult, hash_text
from packages.adapters.hkjc import HkjcAdapter, HkjcScheduledMatch
from packages.db.models import Competition, Match, RawPayload, Team
from packages.domain.enums import MatchStatus
from packages.ingest.linking import link_hkjc_matches
from packages.ingest.normalize import seed_competitions
from packages.ingest.pipeline import AdapterBundle, IngestPipeline

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "hkjc"
HAD_PAYLOAD = json.loads((FIXTURES / "had.json").read_text(encoding="utf-8"))
FETCHED_AT = datetime(2026, 11, 1, 0, 0, tzinfo=UTC)
KICKOFF = datetime(2026, 10, 31, 17, 30, tzinfo=UTC)


class _FakeScheduledHkjc:
    schema_version = "graphql-v1"
    query_version = "test-v1"

    def __init__(self) -> None:
        self.calls: list[tuple[date, date]] = []

    def fetch_scheduled_matches(
        self,
        start_date: date,
        end_date: date,
        *,
        start_index: int = 1,
        end_index: int = 100,
    ) -> FetchResult:
        self.calls.append((start_date, end_date))
        raw_text = json.dumps(HAD_PAYLOAD, sort_keys=True)
        return FetchResult(
            source_name="hkjc",
            source_url="https://fixture.local/hkjc/scheduled",
            fetched_at=FETCHED_AT,
            http_status=200,
            schema_version=self.schema_version,
            payload=HAD_PAYLOAD,
            payload_hash=hash_text(raw_text),
            raw_text=raw_text,
        )

    def fetch_market_odds(self, market: object, match_source_id: str) -> FetchResult:
        raise AssertionError("linking must not fetch odds")

    def fetch_match_results(
        self,
        match_source_id: str,
        *,
        match_date: date | None = None,
    ) -> FetchResult:
        raise AssertionError("linking must not fetch results")


def _seed_epl(session) -> tuple[Competition, Team, Team]:
    seed_competitions(session)
    competition = (
        session.query(Competition).filter(Competition.code == "EPL").one()
    )
    home = Team(
        slug="tottenham",
        name="Tottenham",
        short_name="TOT",
        country="England",
    )
    away = Team(
        slug="crystal-palace",
        name="Crystal Palace",
        short_name="CRY",
        country="England",
    )
    session.add_all([home, away])
    session.flush()
    return competition, home, away


def _add_match(
    session,
    competition: Competition,
    home: Team,
    away: Team,
    *,
    kickoff_at: datetime = KICKOFF,
    source_match_ids: dict[str, str] | None = None,
) -> Match:
    match = Match(
        competition_id=competition.id,
        season="2026/27",
        kickoff_at=kickoff_at,
        home_team_id=home.id,
        away_team_id=away.id,
        status=MatchStatus.SCHEDULED,
        source_match_ids=(
            {"football-data.org": "999"}
            if source_match_ids is None
            else source_match_ids
        ),
        coverage_flags=[],
    )
    session.add(match)
    session.flush()
    return match


def _scheduled(
    *,
    match_source_id: str = "50078674",
    tournament_code: str | None = "EPL",
    home_name: str = "Tottenham",
    away_name: str = "Crystal Palace",
    kickoff_at: datetime = KICKOFF,
) -> HkjcScheduledMatch:
    return HkjcScheduledMatch(
        match_source_id=match_source_id,
        kickoff_at=kickoff_at,
        home_name=home_name,
        away_name=away_name,
        tournament_code=tournament_code,
        status="FIRSTHALF",
    )


def test_link_hkjc_matches_merges_source_id_and_is_idempotent(session):
    competition, home, away = _seed_epl(session)
    match = _add_match(session, competition, home, away)

    assert link_hkjc_matches(session, [_scheduled()]) == 1
    assert match.source_match_ids == {
        "football-data.org": "999",
        "hkjc": "50078674",
    }
    assert link_hkjc_matches(session, [_scheduled()]) == 0


def test_link_hkjc_matches_skips_other_tournaments_and_unresolved_teams(session):
    competition, home, away = _seed_epl(session)
    match = _add_match(session, competition, home, away)

    assert link_hkjc_matches(session, [_scheduled(tournament_code="RPL")]) == 0
    assert link_hkjc_matches(session, [_scheduled(home_name="Unknown FC")]) == 0
    assert match.source_match_ids == {"football-data.org": "999"}
    assert session.query(Team).count() == 2


def test_link_hkjc_matches_picks_the_closest_kickoff(session):
    competition, home, away = _seed_epl(session)
    closest = _add_match(
        session,
        competition,
        home,
        away,
        kickoff_at=datetime(2026, 10, 31, 17, 30, tzinfo=UTC),
    )
    _ = _add_match(
        session,
        competition,
        home,
        away,
        kickoff_at=datetime(2026, 10, 31, 18, 30, tzinfo=UTC),
    )

    scheduled = _scheduled(
        match_source_id="50078675",
        kickoff_at=datetime(2026, 10, 31, 17, 45, tzinfo=UTC),
    )
    assert link_hkjc_matches(session, [scheduled]) == 1
    assert closest.source_match_ids["hkjc"] == "50078675"


def test_pipeline_link_hkjc_fetches_persists_and_links(session):
    competition, home, away = _seed_epl(session)
    match = _add_match(session, competition, home, away)
    hkjc = _FakeScheduledHkjc()
    pipeline = IngestPipeline(session, AdapterBundle(hkjc=hkjc))

    linked = pipeline.link_hkjc("EPL", date(2026, 11, 1), date(2026, 11, 7))

    assert linked == 1
    assert hkjc.calls == [(date(2026, 11, 1), date(2026, 11, 7))]
    assert match.source_match_ids["hkjc"] == "50078674"
    assert session.query(RawPayload).count() == 1
    raw = session.query(RawPayload).one()
    assert raw.source_name == "hkjc"
    scheduled = HkjcAdapter.parse_scheduled_matches(raw.body)
    assert len(scheduled) == 5


def test_link_hkjc_matches_ignores_unrelated_matches(session):
    competition, home, away = _seed_epl(session)
    _add_match(
        session,
        competition,
        home,
        away,
        kickoff_at=datetime(2026, 10, 31, 17, 30, tzinfo=UTC),
    )
    unrelated_competition = Competition(
        code="LALIGA-X",
        name="Other League",
        country="Spain",
        is_cup=False,
        football_data_code="PD",
    )
    session.add(unrelated_competition)
    session.flush()
    other = Match(
        competition_id=unrelated_competition.id,
        season="2026/27",
        kickoff_at=KICKOFF,
        home_team_id=home.id,
        away_team_id=away.id,
        status=MatchStatus.SCHEDULED,
        source_match_ids={"football-data.org": "other"},
        coverage_flags=[],
    )
    session.add(other)
    session.flush()

    assert link_hkjc_matches(session, [_scheduled()]) == 1
    assert "hkjc" not in (other.source_match_ids or {})
