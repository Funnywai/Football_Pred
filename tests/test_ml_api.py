from datetime import UTC, datetime

import httpx
from ml_helpers import make_db, seed_context, seed_finished_match, seed_team

from app.api.main import create_app
from app.config import Settings
from app.db.models import ModelVersion, Prediction


async def _client(db):
    app = create_app(Settings(_env_file=None), db=db)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_list_models_empty(tmp_path) -> None:
    db = await make_db(tmp_path)
    try:
        async with await _client(db) as client:
            response = await client.get("/models")
            assert response.status_code == 200
            assert response.json() == []
    finally:
        await db.dispose()


async def test_list_predictions_empty(tmp_path) -> None:
    db = await make_db(tmp_path)
    try:
        async with await _client(db) as client:
            response = await client.get("/predictions")
            assert response.status_code == 200
            assert response.json() == []
    finally:
        await db.dispose()


async def test_list_predictions_defaults_to_champion_only(tmp_path) -> None:
    db = await make_db(tmp_path)
    try:
        async with db.session_factory() as session:
            league, season = await seed_context(session)
            home = await seed_team(session, "Home")
            away = await seed_team(session, "Away")
            match = await seed_finished_match(
                session, league, season, home, away,
                match_id_label="M1", kickoff=datetime(2026, 8, 1, 18, 0, tzinfo=UTC),
                home_score=2, away_score=1,
            )
            champion = ModelVersion(
                target="1x2", algorithm="lightgbm", params={}, metrics={},
                artifact_path="champion.joblib", status="champion",
            )
            retired = ModelVersion(
                target="1x2", algorithm="lightgbm", params={}, metrics={},
                artifact_path="retired.joblib", status="retired",
            )
            session.add_all([champion, retired])
            await session.flush()
            champion_id, retired_id = champion.id, retired.id
            session.add_all(
                [
                    Prediction(
                        match_id=match.id, target="1x2", outcome="H",
                        model_version_id=champion_id, prob=0.5, fair_odds=2.0,
                    ),
                    Prediction(
                        match_id=match.id, target="1x2", outcome="H",
                        model_version_id=retired_id, prob=0.4, fair_odds=2.5,
                    ),
                ]
            )
            await session.commit()
        async with await _client(db) as client:
            default = await client.get("/predictions")
            assert default.status_code == 200
            assert [row["model_version_id"] for row in default.json()] == [champion_id]
            full = await client.get("/predictions", params={"champion_only": "false"})
            assert full.status_code == 200
            assert {row["model_version_id"] for row in full.json()} == {champion_id, retired_id}
    finally:
        await db.dispose()
