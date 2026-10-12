
from ml_helpers import make_db

from app.config import Settings
from app.ml.jobs import PREDICT_JOB_ID, RETRAIN_JOB_ID, build_ml_scheduler, predict_upcoming


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
