from datetime import UTC, datetime, timedelta

from ml_helpers import make_db, seed_context, seed_finished_match, seed_team
from sqlalchemy import select

from app.config import Settings
from app.db.models import ModelVersion
from app.ml.dataset import build_dataset
from app.ml.jobs import (
    PREDICT_JOB_ID,
    RETRAIN_JOB_ID,
    build_ml_scheduler,
    predict_upcoming,
    retrain,
)
from app.ml.models import TARGET_1X2, save_artifact, train_1x2
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
    assert _fresh_champion_metrics(TARGET_1X2, "/nope.joblib", frame, {}) is None


async def test_retrain_gates_on_fresh_champion_metrics(tmp_path) -> None:
    """A champion with great STORED metrics but a WORSE fresh evaluation must lose.

    The weak champion is trained on one-class labels (the rarest eval class), so its
    fresh evaluation is catastrophic while its stored metrics are fake-great. With
    stored metrics (brier 0.001) any challenger would lose, so a promotion proves the
    gate used the fresh champion metrics from the current window.
    """
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
            retired = await session.get(ModelVersion, weak_id)
            assert retired is not None and retired.status == STATUS_RETIRED
    finally:
        await db.dispose()
