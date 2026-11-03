from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Response
from redis import Redis
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from apps.api.dashboard import router as dashboard_router
from apps.api.llm_lab import router as llm_router
from packages.db.session import build_engine
from packages.shared.config import Settings, get_settings


def create_app(
    settings: Settings | None = None,
    redis_client: Any | None = None,
) -> FastAPI:
    resolved = settings or get_settings()
    app = FastAPI(title="Football Pred API", version="0.1.0")
    engine = build_engine(resolved.database_url)
    app.state.settings = resolved
    app.state.engine = engine
    app.state.session_factory = sessionmaker(
        bind=engine, expire_on_commit=False
    )
    app.state.redis = redis_client
    app.include_router(dashboard_router)
    app.include_router(llm_router)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz(response: Response) -> dict[str, str]:
        checks: dict[str, str] = {}
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            checks["database"] = "up"
        except Exception:  # noqa: BLE001 - any failure means not ready
            checks["database"] = "down"
        if redis_client is not None:
            try:
                redis_client.ping()
                checks["redis"] = "up"
            except Exception:  # noqa: BLE001 - any failure means not ready
                checks["redis"] = "down"
        if "down" in checks.values():
            response.status_code = 503
            return {"status": "unavailable", **checks}
        return {"status": "ok", **checks}

    return app


app = create_app(
    redis_client=Redis.from_url(get_settings().redis_url),
)
