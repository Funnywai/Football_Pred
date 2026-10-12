from datetime import UTC, datetime, timedelta

from ml_helpers import make_db, seed_context, seed_finished_match, seed_team

from app.config import Settings
from app.ml.dataset import build_dataset
from app.ml.models import TARGET_1X2, save_artifact, train_1x2
from app.ml.predict import load_champion, load_upcoming_matches, predict_match, upsert_predictions
from app.ml.registry import maybe_promote, register_challenger

HAD = {"lines": [{"combinations": [
    {"str": "H", "currentOdds": "2.1"}, {"str": "D", "currentOdds": "3.4"},
    {"str": "A", "currentOdds": "3.8"}]}]}
HDC = {"lines": [{"condition": "-0.5", "main": True, "combinations": [
    {"str": "H", "currentOdds": "2.0"}, {"str": "A", "currentOdds": "1.9"}]}]}


async def test_end_to_end_train_then_predict(tmp_path) -> None:
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
            for index in range(60):
                await seed_finished_match(
                    session, league, season, teams[index % 6], teams[(index + 1) % 6],
                    match_id_label=f"M{index}", kickoff=base + timedelta(days=index),
                    home_score=index % 4, away_score=(index + 1) % 3,
                    had_payload=HAD, hdc_payload=HDC,
                )
            # one upcoming, unplayed match
            upcoming_match = await seed_finished_match(
                session, league, season, teams[0], teams[1],
                match_id_label="M_UP", kickoff=base + timedelta(days=90),
                home_score=0, away_score=0,
            )
            upcoming_match.status = "scheduled"
            await session.commit()

        # train a champion directly (bypasses the weekly job)
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
            assert champion is not None
            now = base + timedelta(days=89)
            upcoming = await load_upcoming_matches(session, settings, now)
            assert len(upcoming) == 1
            rows = await predict_match(session, upcoming[0], champion, None, settings)
            assert {row.outcome for row in rows} == {"H", "D", "A"}
            written = await upsert_predictions(session, rows)
            assert written == 3
            await session.commit()
        async with db.session_factory() as session:
            from sqlalchemy import select

            from app.db.models import Prediction

            stored = (await session.execute(select(Prediction))).scalars().all()
            assert len(stored) == 3
    finally:
        await db.dispose()
