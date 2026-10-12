import math
from datetime import UTC, datetime, timedelta

from ml_helpers import make_db, seed_context, seed_finished_match, seed_team

from app.config import Settings
from app.ml.dataset import build_dataset
from app.ml.features import FEATURE_COLUMNS, FeatureRow, MarketPrior
from app.ml.models import TARGET_1X2, save_artifact, train_1x2
from app.ml.predict import (
    Champion,
    UpcomingMatch,
    build_prediction_rows,
    load_champion,
    predict_match,
    predict_upcoming_matches,
)
from app.ml.registry import maybe_promote, register_challenger

HAD = {"lines": [{"combinations": [
    {"str": "H", "currentOdds": "2.1"}, {"str": "D", "currentOdds": "3.4"},
    {"str": "A", "currentOdds": "3.8"}]}]}
HDC = {"lines": [{"condition": "-0.5", "main": True, "combinations": [
    {"str": "H", "currentOdds": "2.0"}, {"str": "A", "currentOdds": "1.9"}]}]}


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


def test_build_prediction_rows_floors_fair_odds_for_zero_prob() -> None:
    kickoff = datetime(2026, 8, 1, tzinfo=UTC)
    upcoming = UpcomingMatch(1, kickoff, 1, 2, "EPL", "2026/27")
    prior = MarketPrior(
        had_probs={"H": 0.40, "D": 0.30, "A": 0.30},
        had_odds={"H": 2.5, "D": 3.3, "A": 3.3},
    )
    champion = Champion(version=type("V", (), {"id": 7})(), model=None)
    rows = build_prediction_rows(
        upcoming,
        _feature_row(1, kickoff),
        champion_1x2=champion,
        champion_handicap=None,
        prior=prior,
        threshold=0.02,
        probs_1x2={"H": 0.0, "D": 0.5, "A": 0.5},
    )
    home = next(r for r in rows if r.outcome == "H")
    assert home.prob == 0.0
    assert math.isfinite(home.fair_odds)


async def test_predict_upcoming_matches_equals_per_match_predictions(tmp_path) -> None:
    db = await make_db(tmp_path)
    try:
        settings = Settings(
            _env_file=None,
            ml_enable=True,
            ml_min_train_rows=20,
            ml_history_from_year=2020,
            ml_artifact_dir=str(tmp_path / "artifacts"),
        )
        base = datetime(2026, 8, 1, 15, 0, tzinfo=UTC)
        async with db.session_factory() as session:
            league, season = await seed_context(session)
            teams = [await seed_team(session, f"T{i}") for i in range(6)]
            for index in range(40):
                await seed_finished_match(
                    session, league, season, teams[index % 6], teams[(index + 1) % 6],
                    match_id_label=f"M{index}", kickoff=base + timedelta(days=index),
                    home_score=index % 4, away_score=(index + 1) % 3,
                    had_payload=HAD, hdc_payload=HDC,
                )
            # a finished match between the two upcoming kickoffs: the batched
            # history load sees it, but the earlier upcoming match must not.
            await seed_finished_match(
                session, league, season, teams[2], teams[3],
                match_id_label="M_BETWEEN", kickoff=base + timedelta(days=62),
                home_score=1, away_score=1, had_payload=HAD, hdc_payload=HDC,
            )
            specs = []
            for index in range(2):
                match = await seed_finished_match(
                    session, league, season, teams[index], teams[index + 1],
                    match_id_label=f"UP{index}", kickoff=base + timedelta(days=60 + index * 5),
                    home_score=0, away_score=0,
                )
                match.status = "scheduled"
                specs.append((match.id, match.kickoff_time, match.home_team_id, match.away_team_id))
            await session.commit()
        async with db.session_factory() as session:
            dataset = await build_dataset(session, settings)
            model = train_1x2(dataset.train, dataset.calibration, dataset.eval)
            artifact = tmp_path / "champ.joblib"
            save_artifact(model, artifact)
            version = await register_challenger(
                session, TARGET_1X2, "lightgbm", {}, model.metrics, str(artifact)
            )
            await maybe_promote(session, version, 0.0)
            await session.commit()
        async with db.session_factory() as session:
            champion = await load_champion(session, TARGET_1X2)
            upcoming = [
                UpcomingMatch(match_id, kickoff, home_id, away_id, "EPL", "2026/27")
                for match_id, kickoff, home_id, away_id in specs
            ]
            batched = await predict_upcoming_matches(session, upcoming, champion, None, settings)
            assert len(batched) == 6
            assert all(math.isfinite(row.fair_odds) for row in batched)
            reference = []
            for match in upcoming:
                reference.extend(await predict_match(session, match, champion, None, settings))
            assert {(r.match_id, r.outcome): r.prob for r in batched} == {
                (r.match_id, r.outcome): r.prob for r in reference
            }
    finally:
        await db.dispose()
