import logging
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.ml.jobs import build_ml_scheduler
from app.providers.base import Provider
from app.services.ledger import ledger_update
from app.services.odds import OddsSync, compact_odds_snapshots, prune_odds_snapshots
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
    if settings.ml_enable:
        build_ml_scheduler(settings, session_factory, scheduler=scheduler)
    if settings.ledger_enable:
        scheduler.add_job(
            ledger_update,
            "interval",
            seconds=settings.ledger_update_interval,
            args=[session_factory, settings],
            id="ledger_update",
            max_instances=1,
            coalesce=True,
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
        await compact_odds_snapshots(session_factory, settings.ml_prior_lead_hours)
    except Exception:
        logger.exception("compact_odds job failed")
    try:
        await prune_odds_snapshots(session_factory, settings.odds_retention_days)
    except Exception:
        logger.exception("prune_odds job failed")
