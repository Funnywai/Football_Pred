from app.providers.hkjc.queries import (
    DEFAULT_ODDS_TYPES,
    FOOTBALL_MATCHES_QUERY,
    HISTORIC_FOOTBALL_MATCH_DETAILS_QUERY,
    HISTORIC_FOOTBALL_MATCHES_QUERY,
    ODDS_TYPE_BATCHES,
)


def test_football_matches_query_shape():
    assert "query matchList(" in FOOTBALL_MATCHES_QUERY
    assert "matches(startIndex: $startIndex" in FOOTBALL_MATCHES_QUERY
    assert "fbOddsTypes: $fbOddsTypesM" in FOOTBALL_MATCHES_QUERY
    assert "foPools(fbOddsTypes: $fbOddsTypes)" in FOOTBALL_MATCHES_QUERY
    assert "runningResult" in FOOTBALL_MATCHES_QUERY


def test_historic_matches_query_uses_match_result_with_pagination():
    assert "query matchResults(" in HISTORIC_FOOTBALL_MATCHES_QUERY
    assert "matchResult(startDate: $startDate, endDate: $endDate, startIndex: $startIndex,endIndex: $endIndex" in HISTORIC_FOOTBALL_MATCHES_QUERY
    assert "payoutConfirmed" in HISTORIC_FOOTBALL_MATCHES_QUERY
    assert "ttlCornerResult" in HISTORIC_FOOTBALL_MATCHES_QUERY


def test_historic_details_query_requests_payout_pools():
    assert "query matchResultDetails(" in HISTORIC_FOOTBALL_MATCH_DETAILS_QUERY
    assert "matchResult(matchId: $matchId)" in HISTORIC_FOOTBALL_MATCH_DETAILS_QUERY
    assert "resultOnly: true" in HISTORIC_FOOTBALL_MATCH_DETAILS_QUERY
    assert "winOrd" in HISTORIC_FOOTBALL_MATCH_DETAILS_QUERY


def test_odds_type_batches_cover_spec_types_and_respect_cap():
    assert DEFAULT_ODDS_TYPES == ["HAD", "HDC", "HIL", "CRS"]
    assert len(ODDS_TYPE_BATCHES) == 2
    for batch in ODDS_TYPE_BATCHES:
        assert 0 < len(batch) <= 4
    flattened = [t for batch in ODDS_TYPE_BATCHES for t in batch]
    assert flattened == ["HAD", "HDC", "HIL", "CRS", "HHA", "CHD", "CHL"]
