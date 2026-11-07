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


def _add_team(session, name: str, slug: str) -> Team:
    team = Team(slug=slug, name=name, short_name=slug[:3].upper(), country="England")
    session.add(team)
    session.flush()
    return team


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


def test_link_hkjc_matches_resolves_short_hkjc_team_name(session):
    competition, _, _ = _seed_epl(session)
    everton = _add_team(session, "Everton FC", "everton")
    coventry = _add_team(session, "Coventry City FC", "coventry-city-fc")
    match = _add_match(session, competition, everton, coventry)

    linked = link_hkjc_matches(
        session,
        [_scheduled(home_name="Everton", away_name="Coventry")],
    )

    assert linked == 1
    assert match.source_match_ids["hkjc"] == "50078674"


def test_link_hkjc_matches_resolves_provider_short_names_by_tokens(session):
    seed_competitions(session)
    competition = session.query(Competition).filter(Competition.code == "SERIEA").one()
    atalanta = _add_team(session, "Atalanta BC", "atalanta-bc")
    bologna = _add_team(session, "Bologna FC 1909", "bologna-fc-1909")
    match = _add_match(session, competition, atalanta, bologna)

    linked = link_hkjc_matches(
        session,
        [
            _scheduled(
                match_source_id="50072541-1",
                tournament_code="SERIEA",
                home_name="Atalanta",
                away_name="Bologna",
            )
        ],
        competition_code="SERIEA",
    )

    assert linked == 1
    assert match.source_match_ids["hkjc"] == "50072541-1"


def test_link_hkjc_matches_uses_opponent_to_disambiguate_short_name(session):
    seed_competitions(session)
    competition = session.query(Competition).filter(Competition.code == "LALIGA").one()
    sevilla = _add_team(session, "Sevilla FC", "sevilla")
    alaves = _add_team(session, "Deportivo Alavés", "alaves")
    sociedad = _add_team(
        session, "Real Sociedad de Fútbol", "real-sociedad-de-futbol"
    )
    la_coruna = _add_team(
        session, "RC Deportivo La Coruña", "rc-deportivo-la-coruna"
    )
    target = _add_match(session, competition, sevilla, alaves)
    _add_match(session, competition, sociedad, la_coruna)

    linked = link_hkjc_matches(
        session,
        [
            _scheduled(
                match_source_id="50072540-1",
                tournament_code="LALIGA",
                home_name="Sevilla",
                away_name="Deportivo",
            )
        ],
        competition_code="LALIGA",
    )

    assert linked == 1
    assert target.source_match_ids["hkjc"] == "50072540-1"


def test_link_hkjc_matches_skips_ambiguous_short_name(session, caplog):
    competition, _, _ = _seed_epl(session)
    everton = _add_team(session, "Everton FC", "everton")
    man_united = _add_team(session, "Manchester United FC", "manchester-united")
    newcastle = _add_team(session, "Newcastle United FC", "newcastle-united")
    _add_match(session, competition, man_united, everton)
    _add_match(session, competition, newcastle, everton)

    with caplog.at_level("WARNING"):
        linked = link_hkjc_matches(
            session,
            [_scheduled(home_name="United", away_name="Everton")],
        )

    assert linked == 0
    assert "ambiguous" in caplog.text.casefold()


def test_link_hkjc_matches_logs_unresolved_team_names(session, caplog):
    competition, home, away = _seed_epl(session)
    _add_match(session, competition, home, away)

    with caplog.at_level("WARNING"):
        linked = link_hkjc_matches(
            session,
            [_scheduled(home_name="Unknown FC")],
        )

    assert linked == 0
    assert "Unknown FC" in caplog.text


def test_link_fotmob_matches_links_provider_fixture(session):
    from packages.adapters.fotmob import FotMobFixture
    from packages.ingest.linking import link_fotmob_matches

    competition, home, away = _seed_epl(session)
    match = _add_match(session, competition, home, away)

    fixtures = [
        FotMobFixture(
            fixture_id=5795511,
            kickoff_at=KICKOFF,
            home_name="Tottenham",
            away_name="Crystal Palace",
        )
    ]
    assert link_fotmob_matches(session, fixtures, competition_code="EPL") == 1
    assert match.source_match_ids["fotmob"] == "5795511"


def test_link_fotmob_matches_is_idempotent(session):
    from packages.adapters.fotmob import FotMobFixture
    from packages.ingest.linking import link_fotmob_matches

    competition, home, away = _seed_epl(session)
    match = _add_match(session, competition, home, away)
    fixtures = [
        FotMobFixture(
            fixture_id=5795511,
            kickoff_at=KICKOFF,
            home_name="Tottenham",
            away_name="Crystal Palace",
        )
    ]
    assert link_fotmob_matches(session, fixtures, competition_code="EPL") == 1
    assert link_fotmob_matches(session, fixtures, competition_code="EPL") == 0
    assert match.source_match_ids["fotmob"] == "5795511"


def test_link_fotmob_matches_ignores_spanish_articles(session):
    from packages.adapters.fotmob import FotMobFixture
    from packages.ingest.linking import link_fotmob_matches

    seed_competitions(session)
    competition = session.query(Competition).filter(Competition.code == "LALIGA").one()
    coruna = _add_team(session, "RC Deportivo La Coruña", "rc-deportivo-la-coruna")
    elche = _add_team(session, "Elche CF", "elche-cf")
    match = _add_match(session, competition, coruna, elche)

    linked = link_fotmob_matches(
        session,
        [
            FotMobFixture(
                fixture_id=5868014,
                kickoff_at=KICKOFF,
                home_name="Deportivo A Coruña",
                away_name="Elche",
            )
        ],
        competition_code="LALIGA",
    )

    assert linked == 1
    assert match.source_match_ids["fotmob"] == "5868014"
