import math
from datetime import UTC, datetime, timedelta

from app.ml.features import (
    FEATURE_COLUMNS,
    MarketPrior,
    MatchRow,
    build_feature_rows,
    football_data_close_odds,
    hkjc_had_odds,
    hkjc_hdc_main,
)

HAD_PAYLOAD = {
    "lines": [
        {
            "combinations": [
                {"str": "H", "currentOdds": "2.10"},
                {"str": "D", "currentOdds": "3.40"},
                {"str": "A", "currentOdds": "3.80"},
            ]
        }
    ]
}
HDC_PAYLOAD = {
    "lines": [
        {"condition": "-1", "main": False,
         "combinations": [{"str": "H", "currentOdds": "2.0"}, {"str": "A", "currentOdds": "1.9"}]},
        {"condition": "-1.5", "main": True,
         "combinations": [{"str": "H", "currentOdds": "2.5"}, {"str": "A", "currentOdds": "1.6"}]},
    ]
}
FD_PAYLOAD = {
    "odds": {
        "B365": {"open": [2.0, 3.4, 3.6], "close": [2.05, 3.3, 3.7]},
        "PS": {"open": [2.1, 3.5, 3.9], "close": [2.15, 3.4, 4.0]},
    }
}


def _row(mid, ko, home, away, hs=None, as_=None, code="EPL", season="2026/27"):
    return MatchRow(
        match_id=mid, kickoff_time=ko, home_team_id=home, away_team_id=away,
        league_code=code, season_label=season, home_score=hs, away_score=as_,
    )


def _equal(a, b):
    assert a.keys() == b.keys()
    for key in a:
        av, bv = a[key], b[key]
        if isinstance(av, float) and math.isnan(av):
            assert isinstance(bv, float) and math.isnan(bv)
        else:
            assert av == bv


def test_payload_parsers() -> None:
    assert hkjc_had_odds(HAD_PAYLOAD) == {"H": 2.10, "D": 3.40, "A": 3.80}
    assert hkjc_hdc_main(HDC_PAYLOAD) == (-1.5, {"H": 2.5, "A": 1.6})
    assert football_data_close_odds(FD_PAYLOAD) == {"H": 2.15, "D": 3.4, "A": 4.0}
    assert hkjc_had_odds({}) is None
    assert football_data_close_odds({}) is None


def test_feature_row_has_all_columns() -> None:
    t = datetime(2026, 8, 1, tzinfo=UTC)
    rows = build_feature_rows([_row(1, t, 1, 2, hs=1, as_=0), _row(2, t + timedelta(days=3), 1, 3)])
    assert set(rows[0].features.keys()) == set(FEATURE_COLUMNS)
    assert rows[0].features["has_market_prior"] == 0.0


def test_no_future_leakage() -> None:
    t = datetime(2026, 8, 1, tzinfo=UTC)
    a = _row(1, t, 1, 2, hs=2, as_=0)
    b = _row(2, t + timedelta(days=7), 1, 3)
    c = _row(3, t + timedelta(days=14), 1, 4, hs=5, as_=5)
    with_future = {r.match_id: r.features for r in build_feature_rows([a, b, c])}
    without_future = {r.match_id: r.features for r in build_feature_rows([a, b])}
    _equal(with_future[2], without_future[2])


def test_same_kickoff_does_not_leak() -> None:
    t = datetime(2026, 8, 1, tzinfo=UTC)
    a = _row(1, t, 1, 2, hs=3, as_=0)
    b = _row(2, t, 1, 3, hs=0, as_=0)
    paired = {r.match_id: r.features for r in build_feature_rows([a, b])}
    solo = {r.match_id: r.features for r in build_feature_rows([b])}
    _equal(paired[2], solo[2])


def test_market_prior_features() -> None:
    t = datetime(2026, 8, 1, tzinfo=UTC)
    prior = MarketPrior(
        had_probs={"H": 0.5, "D": 0.3, "A": 0.2},
        hdc_line=-0.5,
        hdc_probs={"H": 0.55, "A": 0.45},
        source="hkjc",
    )
    rows = build_feature_rows([_row(1, t, 1, 2)], {1: prior})
    features = rows[0].features
    assert features["has_market_prior"] == 1.0
    assert features["market_home"] == 0.5
    assert features["has_hdc_prior"] == 1.0
    assert features["hdc_line"] == -0.5
