import json
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.models import IngestionRun, Match, Result, Team
from app.providers.base import Provider, ResultRecord
from app.services.alias import TeamMatcher
from app.services.runs import flag_manual_review, track_run

logger = logging.getLogger(__name__)

HKJC_LOOKBACK_DAYS = 2
FALLBACK_AFTER_HOURS = 4
MANUAL_REVIEW_AFTER_HOURS = 48
FALLBACK_LOOKBACK_DAYS = 7
NON_DATA_QUALITY_STATUSES = ("postponed", "cancelled", "abandoned")


class ResultReconciler:
    """Settles finished matches: HKJC first, football-data fallback, then a 48h manual-review flag."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        hkjc_provider: Provider,
        fallback_provider: Provider,
        settings: Settings,
    ) -> None:
        self._session_factory = session_factory
        self._hkjc = hkjc_provider
        self._fallback = fallback_provider
        self._settings = settings

    async def run(self, now: datetime | None = None) -> int:
        moment = now or datetime.now(UTC)
        hkjc_count = 0
        fallback_count = 0
        try:
            hkjc_count = await self._reconcile_hkjc(moment)
        except Exception:
            logger.exception("HKJC reconciliation failed; continuing with fallback")
        try:
            fallback_count = await self._reconcile_fallback(moment)
        except Exception:
            logger.exception("Fallback reconciliation failed; continuing with manual review")
        try:
            await self._flag_unresolved(moment)
        except Exception:
            logger.exception("Manual-review flagging failed")
        return hkjc_count + fallback_count

    async def _reconcile_hkjc(self, now: datetime) -> int:
        date_from = (now - timedelta(days=HKJC_LOOKBACK_DAYS)).date()
        records = await self._hkjc.fetch_results(date_from, now.date())
        return await track_run(
            self._session_factory,
            "settle_results_hkjc",
            lambda session: self._upsert_hkjc(session, records),
        )

    async def _upsert_hkjc(self, session: AsyncSession, records: list[ResultRecord]) -> int:
        count = 0
        for record in records:
            if record.match_hkjc_id is None:
                continue
            match = (
                await session.execute(
                    select(Match).where(Match.hkjc_match_id == record.match_hkjc_id)
                )
            ).scalar_one_or_none()
            if match is None:
                continue
            await self._upsert_result(
                session,
                match,
                record,
                source="hkjc",
                confirmed=True,
                ttl_corner=record.ttl_corner,
            )
            count += 1
        return count

    async def _reconcile_fallback(self, now: datetime) -> int:
        cutoff = now - timedelta(hours=FALLBACK_AFTER_HOURS)
        async with self._session_factory() as session:
            candidates = (
                await session.execute(
                    select(Match.id)
                    .outerjoin(Result, Result.match_id == Match.id)
                    .where(Result.id.is_(None), Match.kickoff_time < cutoff)
                )
            ).scalars().all()
        if not candidates:
            return 0
        date_from = (now - timedelta(days=FALLBACK_LOOKBACK_DAYS)).date()
        records = await self._fallback.fetch_results(date_from, now.date())
        return await track_run(
            self._session_factory,
            "settle_results_fallback",
            lambda session: self._upsert_fallback(session, records, list(candidates)),
        )

    async def _upsert_fallback(
        self, session: AsyncSession, records: list[ResultRecord], candidate_ids: list[int]
    ) -> int:
        teams = (await session.execute(select(Team))).scalars().all()
        matcher = TeamMatcher(teams)
        candidates = (
            await session.execute(select(Match).where(Match.id.in_(candidate_ids)))
        ).scalars().all()
        count = 0
        for record in records:
            if record.match_date is None or record.home_team_name is None or record.away_team_name is None:
                continue
            home = matcher.match(record.home_team_name)
            away = matcher.match(record.away_team_name)
            if home is None or away is None:
                continue
            for match in candidates:
                if match.home_team_id != home.id or match.away_team_id != away.id:
                    continue
                if abs((match.kickoff_time.date() - record.match_date).days) > 1:
                    continue
                existing = (
                    await session.execute(select(Result).where(Result.match_id == match.id))
                ).scalar_one_or_none()
                if existing is not None and existing.source == "hkjc":
                    continue
                await self._upsert_result(
                    session,
                    match,
                    record,
                    source="football_data",
                    confirmed=False,
                    ttl_corner=None,
                )
                count += 1
                break
        return count

    async def _upsert_result(
        self,
        session: AsyncSession,
        match: Match,
        record: ResultRecord,
        source: str,
        confirmed: bool,
        ttl_corner: int | None,
    ) -> None:
        existing = (
            await session.execute(select(Result).where(Result.match_id == match.id))
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                Result(
                    match_id=match.id,
                    home_score=record.home_score,
                    away_score=record.away_score,
                    ttl_corner=ttl_corner,
                    source=source,
                    confirmed=confirmed,
                    payout_confirmed=record.payout_confirmed,
                    confirmed_at=datetime.now(UTC) if confirmed else None,
                    raw=record.raw,
                )
            )
        else:
            existing.home_score = record.home_score
            existing.away_score = record.away_score
            existing.ttl_corner = ttl_corner
            existing.source = source
            existing.confirmed = confirmed
            existing.payout_confirmed = record.payout_confirmed
            if confirmed:
                existing.confirmed_at = datetime.now(UTC)
            existing.raw = record.raw
        await session.flush()

    async def _flag_unresolved(self, now: datetime) -> None:
        cutoff = now - timedelta(hours=MANUAL_REVIEW_AFTER_HOURS)
        async with self._session_factory() as session:
            unresolved = (
                await session.execute(
                    select(Match.id)
                    .outerjoin(Result, Result.match_id == Match.id)
                    .where(
                        Result.id.is_(None),
                        Match.kickoff_time < cutoff,
                        Match.status.not_in(NON_DATA_QUALITY_STATUSES),
                    )
                )
            ).scalars().all()
            latest = (
                await session.execute(
                    select(IngestionRun)
                    .where(IngestionRun.job == "manual_review")
                    .order_by(IngestionRun.id.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        current_ids = set(unresolved)
        if latest is not None and latest.error:
            try:
                stored_ids = set(json.loads(latest.error).get("unresolved_match_ids", []))
            except (ValueError, TypeError, AttributeError):
                stored_ids = None
            if stored_ids is not None and stored_ids == current_ids:
                return
        await flag_manual_review(self._session_factory, "manual_review", list(unresolved))
