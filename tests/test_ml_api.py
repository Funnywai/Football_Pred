
import httpx
from ml_helpers import make_db

from app.api.main import create_app
from app.config import Settings


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
