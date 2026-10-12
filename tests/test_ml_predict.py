from datetime import UTC, datetime

from app.ml.features import FEATURE_COLUMNS, FeatureRow, MarketPrior
from app.ml.predict import Champion, UpcomingMatch, build_prediction_rows


def _feature_row(match_id, kickoff):
    return FeatureRow(
        match_id=match_id, kickoff_time=kickoff, features={c: 0.0 for c in FEATURE_COLUMNS}
    )


def test_build_prediction_rows_marks_value() -> None:
    kickoff = datetime(2026, 8, 1, tzinfo=UTC)
    upcoming = UpcomingMatch(1, kickoff, 1, 2, "EPL", "2026/27")
    prior = MarketPrior(
        had_probs={"H": 0.40, "D": 0.30, "A": 0.30},
        had_odds={"H": 2.5, "D": 3.3, "A": 3.3},
        hdc_line=-0.5,
        hdc_probs={"H": 0.45, "A": 0.55},
        hdc_odds={"H": 2.0, "A": 1.8},
    )
    champion = Champion(version=type("V", (), {"id": 7})(), model=None)
    rows = build_prediction_rows(
        upcoming,
        _feature_row(1, kickoff),
        champion_1x2=champion,
        champion_handicap=None,
        prior=prior,
        threshold=0.02,
        probs_1x2={"H": 0.5, "D": 0.28, "A": 0.22},
    )
    home = next(r for r in rows if r.outcome == "H")
    assert home.implied_prob == 0.40
    assert home.edge > 0
    assert home.recommended_fraction > 0
    assert home.fair_odds == 2.0
