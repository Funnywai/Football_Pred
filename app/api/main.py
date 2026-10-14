from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.ops import router as ops_router
from app.api.routes import router
from app.config import Settings, configure_logging, get_settings
from app.db.session import Database
from app.providers.football_data.provider import FootballDataProvider
from app.providers.hkjc.client import HkjcGraphQLClient
from app.providers.hkjc.provider import HkjcProvider
from app.scheduler import build_scheduler


def create_app(settings: Settings | None = None, db: Database | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

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
        scheduler = None
        if settings.enable_scheduler:
            scheduler = build_scheduler(
                settings,
                app.state.db.session_factory,
                app.state.hkjc_provider,
                app.state.football_data_provider,
            )
            scheduler.start()
        app.state.scheduler = scheduler
        try:
            yield
        finally:
            if scheduler is not None:
                scheduler.shutdown(wait=False)
            await hkjc_client.aclose()
            await app.state.football_data_provider.aclose()
            if db is None:
                await app.state.db.dispose()

    app = FastAPI(title="Football Betting Agent — Data Layer", lifespan=lifespan)
    if db is not None:
        app.state.db = db
    app.state.settings = settings
    app.include_router(router)
    app.include_router(ops_router)
    return app
