import uuid
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from packages.adapters.football_data_org import FootballDataMatch
from packages.adapters.hkjc import HkjcAdapter
from packages.db.models import Competition, MarketLine, Match, OddsSnapshot, Team
from packages.domain.enums import (
    AvailabilityBasis,
    MarketType,
    MatchStatus,
    Side,
    SnapshotKind,
)
from packages.domain.errors import DomainError, UnresolvedTeamError
from packages.ingest.aliases import canonical_team_slug, resolve_team_id
from packages.ingest.normalize import (
    get_competition,
    normalize_fixture,
    normalize_hkjc_snapshot,
    season_label,
    seed_competitions,
    upsert_match,
)
from packages.shared.time import ensure_utc

HAD_PAYLOAD: dict[str, object] = {
    "data": {
        "matches": [
            {
                "id": "HK-1001",
                "matchDate": "2026-08-15+08:00",
                "foPools": [
                    {
                        "oddsType": "HAD",
                        "status": "SELLINGSTARTED",
                        "updateAt": "2026-08-15T12:29:00Z",
                        "lines": [
                            {
                                "condition": "0.0",
                                "status": "AVAILABLE",
                                "main": True,
                                "combinations": [
                                    {
                                        "str": "H",
                                        "status": "AVAILABLE",
                                        "offerEarlySettlement": "Offer",
                                        "currentOdds": "2.05",
                                    },
                                    {
                                        "str": "D",
                                        "status": "AVAILABLE",
                                        "offerEarlySettlement": "Offer",
                                        "currentOdds": "3.40",
                                    },
                                    {
                                        "str": "A",
                                        "status": "AVAILABLE",
                                        "offerEarlySettlement": "Offer",
                                        "currentOdds": "3.80",
                                    },
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    }
}


def _dto(
    *,
    status: MatchStatus = MatchStatus.SCHEDULED,
    home_team_name: str = "Arsenal",
    home_goals_90: int | None = None,
    away_goals_90: int | None = None,
    home_goals_final: int | None = None,
    away_goals_final: int | None = None,
) -> FootballDataMatch:
    return FootballDataMatch(
        source_match_id=1001,
        competition_code="PL",
        season_start_year=2025,
        kickoff_at=datetime(2026, 8, 15, 14, 0, tzinfo=UTC),
        status=status,
        matchday=1,
        home_team_source_id=10,
        home_team_name=home_team_name,
        away_team_source_id=20,
        away_team_name="Chelsea",
        home_goals_90=home_goals_90,
        away_goals_90=away_goals_90,
        home_goals_final=home_goals_final,
        away_goals_final=away_goals_final,
    )


def _seed_teams(session) -> None:
    session.add_all(
        [
            Team(slug="arsenal", name="Arsenal", short_name="ARS", country="England"),
            Team(slug="chelsea", name="Chelsea", short_name="CHE", country="England"),
        ]
    )
    session.flush()


def _seed_match(session) -> Match:
    match = Match(
        competition_id=uuid.uuid4(),
        season="2025/26",
        kickoff_at=datetime(2026, 8, 15, 14, 0, tzinfo=UTC),
        home_team_id=uuid.uuid4(),
        away_team_id=uuid.uuid4(),
        status=MatchStatus.SCHEDULED,
        source_match_ids={"hkjc": "HK-1001"},
        coverage_flags=[],
    )
    session.add(match)
    session.flush()
    return match


def test_seed_competitions_is_idempotent(session):
    seed_competitions(session)
    seed_competitions(session)
    assert session.query(Competition).count() == 6


def test_seed_competitions_sets_provider_metadata(session):
    seed_competitions(session)
    epl = get_competition(session, "EPL")
    ucl = get_competition(session, "UCL")
    assert epl.football_data_code == "PL"
    assert epl.understat_slug == "EPL"
    assert epl.is_cup is False
    assert ucl.football_data_code == "CL"
    assert ucl.understat_slug is None
    assert ucl.is_cup is True


def test_get_competition_rejects_unknown_code(session):
    seed_competitions(session)
    with pytest.raises(DomainError):
        get_competition(session, "UNKNOWN")


def test_canonical_team_slug_uses_alias_table():
    assert canonical_team_slug("Man City") == "manchester-city"
    assert canonical_team_slug("Paris SG") == "paris-saint-germain"
    assert canonical_team_slug("Some Team FC") == "some-team-fc"


def test_canonical_team_slug_normalizes_accents():
    assert canonical_team_slug("Bayern München") == "bayern-munich"
    assert canonical_team_slug("FC Zürich") == "fc-zurich"


def test_canonical_team_slug_maps_epl_provider_names_to_hkjc_names():
    assert canonical_team_slug("Tottenham Hotspur FC") == "tottenham"
    assert canonical_team_slug("Crystal Palace FC") == "crystal-palace"
    assert canonical_team_slug("AFC Bournemouth") == "afc-bournemouth"
    assert canonical_team_slug("Brighton & Hove Albion FC") == "brighton-hove-albion"
    assert canonical_team_slug("Wolverhampton Wanderers FC") == "wolverhampton-wanderers"
    assert canonical_team_slug("Liverpool FC") == "liverpool"
    assert canonical_team_slug("Man Utd") == "manchester-united"
    assert canonical_team_slug("Leeds") == "leeds-united"


def test_canonical_team_slug_is_case_and_whitespace_insensitive():
    assert canonical_team_slug(" man city ") == "manchester-city"
    assert canonical_team_slug("psg") == "paris-saint-germain"


def test_canonical_team_slug_maps_ucl_provider_names_to_hkjc_names():
    assert canonical_team_slug("Club Atlético de Madrid") == "atletico-madrid"
    assert canonical_team_slug("Atletico Madrid") == "atletico-madrid"
    assert canonical_team_slug("FC Internazionale Milano") == "inter-milan"
    assert canonical_team_slug("Inter Milan") == "inter-milan"
    assert canonical_team_slug("Manchester United FC") == "manchester-united"
    assert canonical_team_slug("Manchester Utd") == "manchester-united"
    assert canonical_team_slug("Paris Saint-Germain FC") == "paris-saint-germain"
    assert canonical_team_slug("Paris Saint Germain") == "paris-saint-germain"
    assert canonical_team_slug("Sporting Clube de Portugal") == "sporting-cp"
    assert canonical_team_slug("Sporting") == "sporting-cp"
    assert canonical_team_slug("Club Brugge KV") == "club-brugge"
    assert canonical_team_slug("Bruges") == "club-brugge"


def test_canonical_team_slug_maps_hkjc_exonyms_to_stored_slugs():
    assert canonical_team_slug("Cologne") == "1-fc-koln"
    assert canonical_team_slug("Bilbao") == "athletic-bilbao"
    assert canonical_team_slug("Rennes") == "stade-rennais-fc-1901"
    assert canonical_team_slug("Gladbach") == "borussia-monchengladbach"


def test_canonical_team_slug_rejects_blank_name():
    with pytest.raises(ValueError):
        canonical_team_slug("   ")


def test_resolve_team_id_uses_canonical_slug(session):
    _seed_teams(session)
    arsenal = session.query(Team).filter_by(slug="arsenal").one()
    assert resolve_team_id(session, "Arsenal") == arsenal.id
    with pytest.raises(UnresolvedTeamError):
        resolve_team_id(session, "Unknown FC")


def test_season_label_formats_start_and_end_years():
    assert season_label(2025) == "2025/26"


def test_normalize_and_upsert_fixture(session):
    seed_competitions(session)
    _seed_teams(session)
    competition = get_competition(session, "EPL")
    fixture = normalize_fixture(session, _dto(), competition.id)
    match = upsert_match(session, fixture)
    assert match.season == "2025/26"
    assert match.source_match_ids == {"football-data.org": "1001"}
    again = upsert_match(session, fixture)
    assert again.id == match.id
    assert session.query(Match).count() == 1


def test_upsert_match_updates_existing_fixture(session):
    seed_competitions(session)
    _seed_teams(session)
    competition = get_competition(session, "EPL")
    match = upsert_match(session, normalize_fixture(session, _dto(), competition.id))

    finished = normalize_fixture(
        session,
        _dto(
            status=MatchStatus.FINISHED,
            home_goals_90=2,
            away_goals_90=1,
            home_goals_final=2,
            away_goals_final=1,
        ),
        competition.id,
    )
    updated = upsert_match(session, finished)
    assert updated.id == match.id
    assert updated.status == MatchStatus.FINISHED
    assert updated.home_goals_90 == 2
    assert updated.away_goals_90 == 1
    assert updated.home_goals_final == 2
    assert updated.away_goals_final == 1
    assert updated.result_available_at is not None
    assert updated.result_availability_basis is AvailabilityBasis.OBSERVED_SNAPSHOT
    assert session.query(Match).count() == 1


def test_upsert_match_does_not_downgrade_a_finished_result(session):
    seed_competitions(session)
    _seed_teams(session)
    competition = get_competition(session, "EPL")
    finished = normalize_fixture(
        session,
        _dto(
            status=MatchStatus.FINISHED,
            home_goals_90=2,
            away_goals_90=1,
            home_goals_final=2,
            away_goals_final=1,
        ),
        competition.id,
    )
    match = upsert_match(session, finished)

    stale = normalize_fixture(
        session,
        _dto(status=MatchStatus.LIVE),
        competition.id,
    )
    updated = upsert_match(session, stale)

    assert updated.id == match.id
    assert updated.status is MatchStatus.FINISHED
    assert updated.home_goals_90 == 2
    assert updated.away_goals_90 == 1


def test_upsert_match_keeps_result_availability_timestamp_once(session):
    seed_competitions(session)
    _seed_teams(session)
    competition = get_competition(session, "EPL")
    match = upsert_match(session, normalize_fixture(session, _dto(), competition.id))
    assert match.result_available_at is None
    finished = normalize_fixture(
        session,
        _dto(
            status=MatchStatus.FINISHED,
            home_goals_90=2,
            away_goals_90=1,
            home_goals_final=2,
            away_goals_final=1,
        ),
        competition.id,
    )
    updated = upsert_match(session, finished)
    observed = updated.result_available_at
    assert observed is not None
    assert updated.result_availability_basis is AvailabilityBasis.OBSERVED_SNAPSHOT
    _ = upsert_match(session, finished)
    assert updated.result_available_at == observed


def test_upsert_match_updates_rescheduled_kickoff_instead_of_duplicating(session):
    seed_competitions(session)
    _seed_teams(session)
    competition = get_competition(session, "EPL")
    original = upsert_match(session, normalize_fixture(session, _dto(), competition.id))
    original.source_match_ids = {
        **(original.source_match_ids or {}),
        "hkjc": "HK-1001",
    }
    session.flush()

    rescheduled_at = datetime(2026, 8, 16, 19, 45, tzinfo=UTC)
    updated = upsert_match(
        session,
        normalize_fixture(
            session, replace(_dto(), kickoff_at=rescheduled_at), competition.id
        ),
    )

    assert updated.id == original.id
    assert session.query(Match).count() == 1
    assert ensure_utc(updated.kickoff_at) == rescheduled_at
    assert updated.source_match_ids["hkjc"] == "HK-1001"
    assert updated.source_match_ids["football-data.org"] == "1001"


def test_upsert_match_selects_the_nearest_existing_kickoff(session):
    seed_competitions(session)
    _seed_teams(session)
    competition = get_competition(session, "EPL")
    first = upsert_match(session, normalize_fixture(session, _dto(), competition.id))
    second = Match(
        competition_id=competition.id,
        season="2025/26",
        kickoff_at=datetime(2026, 8, 20, 20, 0, tzinfo=UTC),
        home_team_id=first.home_team_id,
        away_team_id=first.away_team_id,
        status=MatchStatus.SCHEDULED,
        source_match_ids={"cup-leg": "2"},
        coverage_flags=[],
    )
    session.add(second)
    session.flush()

    target = datetime(2026, 8, 20, 20, 15, tzinfo=UTC)
    updated = upsert_match(
        session,
        normalize_fixture(
            session, replace(_dto(), kickoff_at=target), competition.id
        ),
    )

    assert updated.id == second.id
    assert session.query(Match).count() == 2
    assert ensure_utc(updated.kickoff_at) == target
    assert updated.source_match_ids["cup-leg"] == "2"
    assert ensure_utc(first.kickoff_at) == datetime(2026, 8, 15, 14, 0, tzinfo=UTC)


def test_upsert_match_keeps_same_teams_in_different_seasons_distinct(session):
    seed_competitions(session)
    _seed_teams(session)
    competition = get_competition(session, "EPL")
    first = upsert_match(session, normalize_fixture(session, _dto(), competition.id))
    second = upsert_match(
        session,
        normalize_fixture(
            session,
            replace(_dto(), season_start_year=2026),
            competition.id,
        ),
    )

    assert first.id != second.id
    assert session.query(Match).filter_by(season="2025/26").count() == 1
    assert session.query(Match).filter_by(season="2026/27").count() == 1
    assert session.query(Match).count() == 2


def test_upsert_match_sets_first_seen_at_only_once(session):
    seed_competitions(session)
    _seed_teams(session)
    competition = get_competition(session, "EPL")
    fixture = normalize_fixture(session, _dto(), competition.id)
    match = upsert_match(session, fixture)
    assert match.first_seen_at is not None
    first_seen = match.first_seen_at
    upsert_match(session, fixture)
    assert match.first_seen_at == first_seen


def test_normalize_fixture_rejects_unknown_team(session):
    seed_competitions(session)
    competition = get_competition(session, "EPL")
    with pytest.raises(UnresolvedTeamError):
        normalize_fixture(
            session,
            _dto(home_team_name="Unknown FC"),
            competition.id,
        )


def test_normalize_hkjc_snapshot_is_idempotent(session):
    match = _seed_match(session)
    parsed = HkjcAdapter.parse_market_odds(HAD_PAYLOAD, MarketType.HAD)
    snapshot, lines = normalize_hkjc_snapshot(
        session,
        match_id=match.id,
        market=MarketType.HAD,
        payload=parsed,
        snapshot_kind=SnapshotKind.T30M,
        snapshot_at=datetime(2026, 8, 15, 12, 30, tzinfo=UTC),
        query_version="test-v1",
        raw_payload_id=None,
        payload_hash="a" * 64,
        run_id="run-1",
    )
    assert len(lines) == 3
    assert snapshot.market == MarketType.HAD
    assert snapshot.snapshot_kind == SnapshotKind.T30M
    assert snapshot.query_version == "test-v1"
    assert snapshot.payload_hash == "a" * 64
    assert snapshot.run_id == "run-1"
    assert snapshot.source_update_at is not None
    assert ensure_utc(snapshot.source_update_at) == datetime(
        2026, 8, 15, 12, 29, tzinfo=UTC
    )
    assert {line.side for line in lines} == {Side.H, Side.D, Side.A}
    home_line = next(line for line in lines if line.side == Side.H)
    assert home_line.odds_decimal == Decimal("2.05")
    assert home_line.is_main is True

    again, again_lines = normalize_hkjc_snapshot(
        session,
        match_id=match.id,
        market=MarketType.HAD,
        payload=parsed,
        snapshot_kind=SnapshotKind.T30M,
        snapshot_at=datetime(2026, 8, 15, 12, 30, tzinfo=UTC),
        query_version="test-v1",
        raw_payload_id=None,
        payload_hash="a" * 64,
        run_id="run-1",
    )
    assert again.id == snapshot.id
    assert len(again_lines) == 3
    assert session.query(OddsSnapshot).count() == 1
    assert session.query(MarketLine).count() == 3


def test_normalize_hkjc_snapshot_rejects_blank_query_version(session):
    match = _seed_match(session)
    parsed = HkjcAdapter.parse_market_odds(HAD_PAYLOAD, MarketType.HAD)
    with pytest.raises(ValueError):
        normalize_hkjc_snapshot(
            session,
            match_id=match.id,
            market=MarketType.HAD,
            payload=parsed,
            snapshot_kind=SnapshotKind.T30M,
            snapshot_at=datetime(2026, 8, 15, 12, 30, tzinfo=UTC),
            query_version="   ",
            raw_payload_id=None,
            payload_hash="a" * 64,
            run_id="run-1",
        )
