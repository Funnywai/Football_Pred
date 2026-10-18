import math
from datetime import UTC, datetime, timedelta

from app.ml.features import (
    FEATURE_COLUMNS,
    FEATURE_VERSION,
    MarketPrior,
    MatchRow,
    build_feature_rows,
    football_data_close_odds,
    hkjc_had_odds,
    hkjc_hdc_main,
)

STATS_COLUMNS = [
    "sot_for_home",
    "sot_against_home",
    "sot_for_away",
    "sot_against_away",
    "sot_diff_for",
    "sot_diff_against",
    "shot_accuracy_home",
    "shot_accuracy_away",
]

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


def _stats_row(
    mid,
    ko,
    home,
    away,
    *,
    hs,
    as_,
    home_shots,
    away_shots,
    home_sot,
    away_sot,
    available_at,
    code="EPL",
    season="2026/27",
):
    return MatchRow(
        match_id=mid,
        kickoff_time=ko,
        home_team_id=home,
        away_team_id=away,
        league_code=code,
        season_label=season,
        home_score=hs,
        away_score=as_,
        home_shots=home_shots,
        away_shots=away_shots,
        home_sot=home_sot,
        away_sot=away_sot,
        stats_available_at=available_at,
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


def test_feature_version_is_v2_and_stats_columns_present() -> None:
    assert FEATURE_VERSION == "v2"
    for column in STATS_COLUMNS:
        assert column in FEATURE_COLUMNS


def test_stats_features_are_nan_without_history() -> None:
    t = datetime(2026, 8, 1, tzinfo=UTC)
    rows = build_feature_rows([_row(1, t, 1, 2)])
    for column in STATS_COLUMNS:
        assert math.isnan(rows[0].features[column])


def test_stats_are_used_only_when_available_48h_before_kickoff() -> None:
    t = datetime(2026, 8, 1, tzinfo=UTC)
    played = _stats_row(
        1,
        t,
        1,
        2,
        hs=2,
        as_=0,
        home_shots=12,
        away_shots=8,
        home_sot=6,
        away_sot=2,
        available_at=t + timedelta(hours=24),
    )
    included = _row(2, t + timedelta(days=3), 1, 3)
    excluded = _row(3, t + timedelta(days=1), 1, 4)
    features = {r.match_id: r.features for r in build_feature_rows([played, included, excluded])}
    assert features[2]["sot_for_home"] == 6.0
    assert features[2]["sot_against_home"] == 2.0
    assert features[2]["shot_accuracy_home"] == 0.5
    assert math.isnan(features[3]["sot_for_home"])
    assert math.isnan(features[3]["shot_accuracy_home"])


def test_stats_features_use_both_teams_and_diffs() -> None:
    t = datetime(2026, 8, 1, tzinfo=UTC)
    first = _stats_row(
        1,
        t,
        1,
        2,
        hs=2,
        as_=0,
        home_shots=10,
        away_shots=20,
        home_sot=4,
        away_sot=8,
        available_at=t + timedelta(hours=24),
    )
    second = _stats_row(
        2,
        t + timedelta(days=3),
        2,
        1,
        hs=1,
        as_=1,
        home_shots=14,
        away_shots=6,
        home_sot=7,
        away_sot=3,
        available_at=t + timedelta(days=3, hours=24),
    )
    target = _row(3, t + timedelta(days=6), 1, 2)
    features = {r.match_id: r.features for r in build_feature_rows([first, second, target])}[3]
    assert features["sot_for_home"] == 3.5
    assert features["sot_against_home"] == 7.5
    assert features["sot_for_away"] == 7.5
    assert features["sot_against_away"] == 3.5
    assert features["sot_diff_for"] == -4.0
    assert features["sot_diff_against"] == 4.0


def test_shot_accuracy_skips_zero_shot_matches() -> None:
    t = datetime(2026, 8, 1, tzinfo=UTC)
    first = _stats_row(
        1,
        t,
        1,
        2,
        hs=1,
        as_=0,
        home_shots=10,
        away_shots=5,
        home_sot=5,
        away_sot=1,
        available_at=t + timedelta(hours=24),
    )
    second = _stats_row(
        2,
        t + timedelta(days=1),
        1,
        3,
        hs=0,
        as_=0,
        home_shots=0,
        away_shots=4,
        home_sot=0,
        away_sot=2,
        available_at=t + timedelta(days=1, hours=24),
    )
    target = _row(3, t + timedelta(days=4), 1, 4)
    features = {r.match_id: r.features for r in build_feature_rows([first, second, target])}[3]
    assert features["shot_accuracy_home"] == 0.5
    assert features["sot_for_home"] == 2.5


def test_stats_window_uses_last_ten_matches() -> None:
    t = datetime(2026, 8, 1, tzinfo=UTC)
    rows = [
        _stats_row(
            index + 1,
            t + timedelta(days=index * 3),
            1,
            2,
            hs=1,
            as_=0,
            home_shots=10,
            away_shots=10,
            home_sot=index,
            away_sot=0,
            available_at=t + timedelta(days=index * 3, hours=24),
        )
        for index in range(12)
    ]
    target = _row(100, t + timedelta(days=36), 1, 3)
    features = {r.match_id: r.features for r in build_feature_rows([*rows, target])}[100]
    assert features["sot_for_home"] == 6.5


def test_stats_do_not_change_v1_features() -> None:
    t = datetime(2026, 8, 1, tzinfo=UTC)
    played = _stats_row(
        1,
        t,
        1,
        2,
        hs=2,
        as_=0,
        home_shots=12,
        away_shots=8,
        home_sot=6,
        away_sot=2,
        available_at=t + timedelta(hours=24),
    )
    target = _row(2, t + timedelta(days=3), 1, 3)
    with_stats = {r.match_id: r.features for r in build_feature_rows([played, target])}
    without_stats = {
        r.match_id: r.features
        for r in build_feature_rows([_row(1, t, 1, 2, hs=2, as_=0), target])
    }
    v1_columns = [column for column in FEATURE_COLUMNS if column not in STATS_COLUMNS]
    _equal(
        {column: with_stats[2][column] for column in v1_columns},
        {column: without_stats[2][column] for column in v1_columns},
    )


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
