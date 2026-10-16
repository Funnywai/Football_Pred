import math
from datetime import UTC, datetime, timedelta

import pytest
from ml_helpers import make_db, seed_context, seed_finished_match, seed_team

from app.config import Settings
from app.ml.dataset import build_dataset
from app.ml.features import FEATURE_COLUMNS, FeatureRow, MarketPrior
from app.ml.models import TARGET_1X2, save_artifact, train_1x2
from app.ml.predict import (
    Champion,
    UpcomingMatch,
    blend_probs,
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


def test_build_prediction_rows_stores_blended_prob() -> None:
    kickoff = datetime(2026, 8, 1, tzinfo=UTC)
    upcoming = UpcomingMatch(1, kickoff, 1, 2, "EPL", "2026/27")
    prior = MarketPrior(
        had_probs={"H": 0.40, "D": 0.35, "A": 0.25},
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
        blend_weight=0.5,
        exec_edge_buffer=0.03,
        probs_1x2={"H": 0.50, "D": 0.30, "A": 0.20},
    )
    home = next(r for r in rows if r.outcome == "H")
    # w=0.5 geometric mean: sqrt(0.50*0.40)=0.44721360, sqrt(0.30*0.35)=0.32403703,
    # sqrt(0.20*0.25)=0.22360680; normalised -> 0.44952531 / 0.32571203 / 0.22476266
    assert home.prob == pytest.approx(0.44952531, abs=1e-6)
    assert home.implied_prob == 0.40
    assert home.edge == pytest.approx(0.04952531, abs=1e-6)
    assert home.fair_odds == pytest.approx(1.0 / 0.44952531, abs=1e-6)
    assert home.recommended_fraction > 0


def test_build_prediction_rows_buffer_blocks_thin_edge() -> None:
    kickoff = datetime(2026, 8, 1, tzinfo=UTC)
    upcoming = UpcomingMatch(1, kickoff, 1, 2, "EPL", "2026/27")
    prior = MarketPrior(
        had_probs={"H": 0.40, "D": 0.30, "A": 0.30},
        had_odds={"H": 2.2, "D": 3.3, "A": 3.3},
    )
    champion = Champion(version=type("V", (), {"id": 7})(), model=None)
    probs = {"H": 0.46, "D": 0.29, "A": 0.25}
    blocked = build_prediction_rows(
        upcoming,
        _feature_row(1, kickoff),
        champion_1x2=champion,
        champion_handicap=None,
        prior=prior,
        threshold=0.02,
        blend_weight=1.0,
        exec_edge_buffer=0.03,
        probs_1x2=probs,
    )
    home = next(r for r in blocked if r.outcome == "H")
    assert home.edge > 0.02
    assert home.prob * home.market_odds <= 1.03
    assert home.recommended_fraction == 0.0
    # without the buffer the same bet clears kelly > 0 (p*odds = 1.012 > 1.0)
    unbuffered = build_prediction_rows(
        upcoming,
        _feature_row(1, kickoff),
        champion_1x2=champion,
        champion_handicap=None,
        prior=prior,
        threshold=0.02,
        blend_weight=1.0,
        exec_edge_buffer=0.0,
        probs_1x2=probs,
    )
    assert next(r for r in unbuffered if r.outcome == "H").recommended_fraction > 0


def test_build_prediction_rows_buffer_allows_clear_edge() -> None:
    kickoff = datetime(2026, 8, 1, tzinfo=UTC)
    upcoming = UpcomingMatch(1, kickoff, 1, 2, "EPL", "2026/27")
    prior = MarketPrior(
        had_probs={"H": 0.40, "D": 0.30, "A": 0.30},
        had_odds={"H": 2.2, "D": 3.3, "A": 3.3},
    )
    champion = Champion(version=type("V", (), {"id": 7})(), model=None)
    rows = build_prediction_rows(
        upcoming,
        _feature_row(1, kickoff),
        champion_1x2=champion,
        champion_handicap=None,
        prior=prior,
        threshold=0.02,
        blend_weight=1.0,
        exec_edge_buffer=0.03,
        probs_1x2={"H": 0.50, "D": 0.28, "A": 0.22},
    )
    home = next(r for r in rows if r.outcome == "H")
    assert home.prob * home.market_odds > 1.03
    assert home.recommended_fraction > 0


def test_build_prediction_rows_buffer_uses_blended_prob() -> None:
    # model H=0.55 clears the buffer on its own (0.55*2.2=1.21) but the blended
    # H=0.41325848 does not (0.90917 <= 1.03) -> the buffer must use the blend.
    kickoff = datetime(2026, 8, 1, tzinfo=UTC)
    upcoming = UpcomingMatch(1, kickoff, 1, 2, "EPL", "2026/27")
    prior = MarketPrior(
        had_probs={"H": 0.38, "D": 0.31, "A": 0.31},
        had_odds={"H": 2.2, "D": 3.3, "A": 3.3},
    )
    champion = Champion(version=type("V", (), {"id": 7})(), model=None)
    rows = build_prediction_rows(
        upcoming,
        _feature_row(1, kickoff),
        champion_1x2=champion,
        champion_handicap=None,
        prior=prior,
        threshold=0.02,
        blend_weight=0.2,
        exec_edge_buffer=0.03,
        probs_1x2={"H": 0.55, "D": 0.25, "A": 0.20},
    )
    home = next(r for r in rows if r.outcome == "H")
    assert home.edge > 0.02
    assert home.prob * home.market_odds <= 1.03
    assert home.recommended_fraction == 0.0


def test_build_prediction_rows_missing_prior_uses_model_prob() -> None:
    kickoff = datetime(2026, 8, 1, tzinfo=UTC)
    upcoming = UpcomingMatch(1, kickoff, 1, 2, "EPL", "2026/27")
    champion = Champion(version=type("V", (), {"id": 7})(), model=None)
    probs = {"H": 0.50, "D": 0.30, "A": 0.20}
    for prior in (None, MarketPrior()):
        rows = build_prediction_rows(
            upcoming,
            _feature_row(1, kickoff),
            champion_1x2=champion,
            champion_handicap=None,
            prior=prior,
            threshold=0.02,
            blend_weight=0.2,
            exec_edge_buffer=0.03,
            probs_1x2=probs,
        )
        assert {r.outcome: r.prob for r in rows} == probs
        assert all(r.implied_prob is None and r.edge is None for r in rows)
        assert all(r.recommended_fraction == 0.0 for r in rows)


def test_blend_probs_weight_zero_returns_prior() -> None:
    model = {"H": 0.50, "D": 0.30, "A": 0.20}
    prior = {"H": 0.40, "D": 0.35, "A": 0.25}
    blended = blend_probs(model, prior, 0.0)
    assert blended["H"] == pytest.approx(0.40, abs=1e-9)
    assert blended["D"] == pytest.approx(0.35, abs=1e-9)
    assert blended["A"] == pytest.approx(0.25, abs=1e-9)


def test_blend_probs_weight_one_returns_model() -> None:
    model = {"H": 0.50, "D": 0.30, "A": 0.20}
    prior = {"H": 0.40, "D": 0.35, "A": 0.25}
    assert blend_probs(model, prior, 1.0) == model


def test_blend_probs_intermediate_matches_geometric_mean() -> None:
    # w=0.5 -> p_blend ∝ sqrt(p_model × p_prior), normalised:
    # H sqrt(0.50×0.40)=0.44721360, D sqrt(0.30×0.35)=0.32403703,
    # A sqrt(0.20×0.25)=0.22360680; sum 0.99485743
    # -> 0.44952531 / 0.32571203 / 0.22476266
    model = {"H": 0.50, "D": 0.30, "A": 0.20}
    prior = {"H": 0.40, "D": 0.35, "A": 0.25}
    blended = blend_probs(model, prior, 0.5)
    assert blended["H"] == pytest.approx(0.44952531, abs=1e-6)
    assert blended["D"] == pytest.approx(0.32571203, abs=1e-6)
    assert blended["A"] == pytest.approx(0.22476266, abs=1e-6)


def test_blend_probs_missing_prior_falls_back_to_model() -> None:
    model = {"H": 0.50, "D": 0.30, "A": 0.20}
    assert blend_probs(model, None, 0.2) == model
    assert blend_probs(model, {"H": 0.4, "D": 0.6}, 0.2) == model


def test_build_prediction_rows_handicap_uses_blend_and_buffer() -> None:
    kickoff = datetime(2026, 8, 1, tzinfo=UTC)
    upcoming = UpcomingMatch(1, kickoff, 1, 2, "EPL", "2026/27")
    prior = MarketPrior(
        hdc_line=-0.5,
        hdc_probs={"H": 0.45, "A": 0.55},
        hdc_odds={"H": 2.0, "A": 1.8},
    )
    champion = Champion(version=type("V", (), {"id": 7})(), model=None)
    rows = build_prediction_rows(
        upcoming,
        _feature_row(1, kickoff),
        champion_1x2=None,
        champion_handicap=champion,
        prior=prior,
        threshold=0.02,
        blend_weight=0.5,
        exec_edge_buffer=0.03,
        probs_handicap={"H": 0.60, "A": 0.40},
    )
    home = next(r for r in rows if r.outcome == "H")
    # w=0.5 geometric mean: sqrt(0.60*0.45)=0.51961524, sqrt(0.40*0.55)=0.46904158
    # sum=0.98865682 -> H=0.52557696
    assert home.prob == pytest.approx(0.52557696, abs=1e-6)
    assert home.implied_prob == 0.45
    assert home.edge == pytest.approx(0.07557696, abs=1e-6)
    assert home.recommended_fraction > 0
