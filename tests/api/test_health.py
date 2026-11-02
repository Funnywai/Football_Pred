from fastapi.testclient import TestClient

from apps.api.main import create_app
from packages.shared.config import Settings


def _settings(database_url: str = "sqlite+pysqlite:///:memory:") -> Settings:
    return Settings(database_url=database_url, _env_file=None)


def test_health_and_ready_endpoints():
    app = create_app(_settings())
    client = TestClient(app)
    assert client.get("/healthz").json() == {"status": "ok"}
    response = client.get("/readyz")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["database"] == "up"


def test_readyz_fails_when_database_is_down():
    app = create_app(
        _settings("sqlite+pysqlite:////nonexistent-football-pred/state.db")
    )
    response = TestClient(app).get("/readyz")
    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "unavailable"
    assert payload["database"] == "down"


class _HealthyRedis:
    def __init__(self) -> None:
        self.pinged = False

    def ping(self):
        self.pinged = True
        return True


class _BrokenRedis:
    def ping(self):
        raise ConnectionError("redis unavailable")


def test_readyz_reports_redis_up_when_configured():
    redis_client = _HealthyRedis()
    app = create_app(_settings(), redis_client=redis_client)
    response = TestClient(app).get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "up", "redis": "up"}
    assert redis_client.pinged is True


def test_readyz_returns_503_when_redis_is_down():
    app = create_app(_settings(), redis_client=_BrokenRedis())
    response = TestClient(app).get("/readyz")
    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "unavailable"
    assert payload["database"] == "up"
    assert payload["redis"] == "down"
