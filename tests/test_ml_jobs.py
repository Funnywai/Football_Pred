from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest
from ml_helpers import make_db, seed_context, seed_finished_match, seed_team
from sqlalchemy import select

from app.config import Settings
from app.db.models import ModelVersion
from app.ml.dataset import build_dataset
from app.ml.jobs import (
    PREDICT_JOB_ID,
    RETRAIN_JOB_ID,
    _blended_1x2,
    _economic_metrics,
    build_ml_scheduler,
    predict_upcoming,
    retrain,
)
from app.ml.models import TARGET_1X2, save_artifact, train_1x2
from app.ml.predict import blend_probs
from app.ml.registry import (
    STATUS_RETIRED,
    get_champion,
    maybe_promote,
    register_challenger,
)

HAD = {"lines": [{"combinations": [
    {"str": "H", "currentOdds": "2.1"}, {"str": "D", "currentOdds": "3.4"},
    {"str": "A", "currentOdds": "3.8"}]}]}
HDC = {"lines": [{"condition": "-0.5", "main": True, "combinations": [
    {"str": "H", "currentOdds": "2.0"}, {"str": "A", "currentOdds": "1.9"}]}]}


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, ml_enable=True, **overrides)


def test_build_ml_scheduler_registers_jobs() -> None:
    scheduler = build_ml_scheduler(_settings(), session_factory=None)
    ids = {job.id for job in scheduler.get_jobs()}
    assert PREDICT_JOB_ID in ids and RETRAIN_JOB_ID in ids


async def test_predict_upcoming_no_champion_is_noop(tmp_path) -> None:
    db = await make_db(tmp_path)
    try:
        count = await predict_upcoming(db.session_factory, _settings())
        assert count == 0
    finally:
        await db.dispose()


async def test_retrain_trains_registers_and_promotes(tmp_path) -> None:
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
            await session.commit()
        promoted = await retrain(db.session_factory, settings)
        assert promoted >= 1
        async with db.session_factory() as session:
            versions = (await session.execute(select(ModelVersion))).scalars().all()
            assert len(versions) >= 1
            champion = await get_champion(session, TARGET_1X2)
            assert champion is not None
    finally:
        await db.dispose()


def test_fresh_champion_metrics_returns_none_for_missing_artifact(tmp_path) -> None:
    import pandas as pd

    from app.ml.features import FEATURE_COLUMNS
    from app.ml.jobs import _fresh_champion_metrics

    frame = pd.DataFrame([{column: 0.0 for column in FEATURE_COLUMNS}])
    frame["label_1x2"] = ["H"]
    assert _fresh_champion_metrics(TARGET_1X2, "/nope.joblib", frame, {}, _settings()) is None


async def test_retrain_gates_on_fresh_champion_metrics(tmp_path) -> None:
    """A champion with great STORED metrics but a WORSE fresh evaluation must lose.

    The weak champion is trained on one-class labels (the rarest eval class), so its
    fresh evaluation is catastrophic while its stored metrics are fake-great. With
    stored metrics (brier 0.001) any challenger would lose, so a promotion proves the
    gate used the fresh champion metrics from the current window.

    This test proves the WIRING, not model quality: at 40 matches ``min_child_samples=30``
    blocks every split, so both models are constant predictors. The synthetic window has
    no market priors, so nothing can clear the economics of a real price; the bet-count
    floor is therefore switched off here to keep this a wiring test. The economics of the
    gate — including the floor — are covered in ``tests/test_ml_registry.py``.
    """
    db = await make_db(tmp_path)
    try:
        settings = Settings(
            _env_file=None,
            ml_enable=True,
            ml_min_train_rows=20,
            ml_history_from_year=2020,
            ml_artifact_dir=str(tmp_path / "artifacts"),
            ml_gate_min_real_bets=0,
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
                )
            await session.commit()

        # weak champion: one-class labels (rarest eval class), fake-great stored metrics.
        # Calibrating on the same one-class frame keeps the full-confidence prediction;
        # calibrating on dataset.calibration would collapse it to that frame's base rates.
        async with db.session_factory() as session:
            dataset = await build_dataset(session, settings)
            rare = dataset.eval["label_1x2"].value_counts().idxmin()
            weak_train = dataset.train.head(20).copy()
            weak_train["label_1x2"] = rare
            weak_model = train_1x2(weak_train, weak_train, dataset.eval)
            assert weak_model.metrics["brier"] > 1.0
            artifact = tmp_path / "weak.joblib"
            save_artifact(weak_model, artifact)
            weak = await register_challenger(
                session, TARGET_1X2, "lightgbm", {}, {"brier": 0.001}, str(artifact)
            )
            assert await maybe_promote(session, weak, 0.0)
            weak_id = weak.id
            await session.commit()

        promoted = await retrain(db.session_factory, settings)
        assert promoted >= 1
        async with db.session_factory() as session:
            champion = await get_champion(session, TARGET_1X2)
            assert champion is not None and champion.id != weak_id
            assert champion.metrics["brier"] < weak_model.metrics["brier"]
            assert "ece" in champion.metrics and "roi" in champion.metrics
            retired = await session.get(ModelVersion, weak_id)
            assert retired is not None and retired.status == STATUS_RETIRED
    finally:
        await db.dispose()


async def test_retrain_trains_handicap_when_only_its_labels_are_new(tmp_path) -> None:
    """With per-target datasets the handicap model trains even though its labels
    only sit in the newest slice; 1x2 must still be trained in the same run."""
    db = await make_db(tmp_path)
    try:
        async with db.session_factory() as session:
            league, season = await seed_context(session)
            home = await seed_team(session, "Home")
            away = await seed_team(session, "Away")
            for index in range(40):
                kickoff = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=index)
                await seed_finished_match(
                    session,
                    league,
                    season,
                    home,
                    away,
                    match_id_label=f"M{index}",
                    kickoff=kickoff,
                    home_score=2,
                    away_score=1,
                    had_payload=HAD,
                    hdc_payload=HDC if index >= 11 else None,
                    snapshot_at_offset_hours=-49,
                )
            await session.commit()
        async with db.session_factory() as session:
            promoted = await retrain(
                db.session_factory,
                _settings(ml_min_train_rows=5, ml_artifact_dir=str(tmp_path / "artifacts")),
            )
        async with db.session_factory() as session:
            versions = (await session.execute(select(ModelVersion))).scalars().all()
        assert promoted == 2
        assert {version.target for version in versions} == {"1x2", "handicap"}
        assert {version.status for version in versions} == {"champion"}
    finally:
        await db.dispose()


def _market_frame():
    return pd.DataFrame([{"market_home": 0.40, "market_draw": 0.30, "market_away": 0.30}])


def test_blended_1x2_matches_the_deployed_blend() -> None:
    probs = np.array([[0.5, 0.28, 0.22]])
    got = _blended_1x2(probs, _market_frame(), 0.2)
    expected = list(
        blend_probs(
            {"H": 0.5, "D": 0.28, "A": 0.22},
            {"H": 0.40, "D": 0.30, "A": 0.30},
            0.2,
        ).values()
    )
    assert np.allclose(got, [expected])


def test_blended_1x2_with_full_weight_returns_the_model_probs() -> None:
    probs = np.array([[0.5, 0.28, 0.22]])
    assert _blended_1x2(probs, _market_frame(), 1.0) == pytest.approx(probs)


def test_blended_1x2_without_a_market_prior_returns_the_model_probs() -> None:
    frame = pd.DataFrame([{"market_home": np.nan, "market_draw": 0.30, "market_away": 0.30}])
    probs = np.array([[0.5, 0.28, 0.22]])
    assert np.allclose(_blended_1x2(probs, frame, 0.2), probs)


def test_economic_metrics_reports_the_fair_and_the_real_price() -> None:
    settings = Settings(
        ml_value_edge_threshold=0.02,
        ml_exec_edge_buffer=0.0,
        ml_exec_overround=1.13,
    )
    served = np.array([[0.6, 0.3, 0.1]])
    market = np.array([[0.4, 0.35, 0.25]])
    real_price = 1.0 / (0.4 * 1.13)
    result = _economic_metrics(served, market, ["H"], settings)
    assert set(result) == {"roi", "n_bets", "roi_real", "n_bets_real"}
    assert result["roi"] == pytest.approx(1.5)
    assert result["n_bets"] == 1
    assert result["roi_real"] == pytest.approx(real_price - 1.0)
    assert result["n_bets_real"] == 1
