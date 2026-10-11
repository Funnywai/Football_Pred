from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.config import Settings, get_settings
from app.db.session import Database
from app.providers.football_data.provider import FootballDataProvider
from app.providers.hkjc.client import HkjcGraphQLClient
from app.providers.hkjc.provider import HkjcProvider


def create_app(settings: Settings | None = None, db: Database | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        if not hasattr(app.state, "db"):
            app.state.db = Database(settings.database_url)
        hkjc_client = HkjcGraphQLClient(
            url=settings.hkjc_graphql_url,
            referer=settings.hkjc_referer,
            origin=settings.hkjc_origin,
            user_agent=settings.hkjc_user_agent,
            throttle_seconds=settings.hkjc_throttle_seconds,
        )
        app.state.hkjc_client = hkjc_client
        app.state.hkjc_provider = HkjcProvider(hkjc_client)
        app.state.football_data_provider = FootballDataProvider(settings.football_data_base)
        try:
            yield
        finally:
            await hkjc_client.aclose()
            await app.state.football_data_provider.aclose()
            if db is None:
                await app.state.db.dispose()

    app = FastAPI(title="Football Betting Agent — Data Layer", lifespan=lifespan)
    if db is not None:
        app.state.db = db
    app.include_router(router)
    return app
