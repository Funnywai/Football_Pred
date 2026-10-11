import logging
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.providers.base import Provider
from app.services.odds import OddsSync, prune_odds_snapshots
from app.services.results import ResultReconciler

logger = logging.getLogger(__name__)


def build_scheduler(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    hkjc_provider: Provider,
    fallback_provider: Provider,
) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        _sync_odds_job,
        "interval",
        seconds=settings.sync_odds_interval,
        id="sync_odds",
        max_instances=1,
        coalesce=True,
        args=[settings, session_factory, hkjc_provider],
    )
    scheduler.add_job(
        _settle_results_job,
        "interval",
        seconds=settings.sync_settle_interval,
        id="settle_results",
        max_instances=1,
        coalesce=True,
        args=[settings, session_factory, hkjc_provider, fallback_provider],
    )
    scheduler.add_job(
        _prune_odds_job,
        "cron",
        hour=4,
        minute=0,
        id="prune_odds",
        max_instances=1,
        coalesce=True,
        args=[settings, session_factory],
    )
    return scheduler


async def _sync_odds_job(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    provider: Provider,
) -> None:
    today = datetime.now(UTC).date()
    try:
        await OddsSync(session_factory, provider, settings).run(today, today + timedelta(days=3))
    except Exception:
        logger.exception("sync_odds job failed")


async def _settle_results_job(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    hkjc_provider: Provider,
    fallback_provider: Provider,
) -> None:
    try:
        await ResultReconciler(session_factory, hkjc_provider, fallback_provider, settings).run()
    except Exception:
        logger.exception("settle_results job failed")


async def _prune_odds_job(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    try:
        await prune_odds_snapshots(session_factory, settings.odds_retention_days)
    except Exception:
        logger.exception("prune_odds job failed")
