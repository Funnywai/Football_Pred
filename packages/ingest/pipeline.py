from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from typing import ClassVar, Protocol, runtime_checkable

from sqlalchemy.orm import Session

from packages.adapters.base import FetchResult
from packages.adapters.football_data_co_uk import FootballDataCoUkAdapter
from packages.adapters.football_data_org import FootballDataOrgAdapter
from packages.adapters.fotmob import FotMobAdapter
from packages.adapters.hkjc import HkjcAdapter
from packages.adapters.open_meteo import OpenMeteoAdapter
from packages.adapters.rss_news import RssNewsAdapter
from packages.adapters.understat import UnderstatAdapter
from packages.db.models import MarketLine, Match, OddsSnapshot
from packages.domain.enums import MarketType, SnapshotKind
from packages.ingest.aliases import ensure_team
from packages.ingest.linking import link_hkjc_matches
from packages.ingest.normalize import (
    get_competition,
    normalize_fixture,
    normalize_hkjc_snapshot,
    upsert_match,
)
from packages.ingest.raw_store import persist_raw_payload
from packages.shared.config import Settings

# The deterministic EPL+HAD pipeline is never gated by LLM shadow cost caps.
# A future cost cap may stop shadow agents only; ingestion and official paper
# decisions must keep running.


class PipelineError(Exception):
    """Raised when a pipeline run cannot proceed."""


class FootballDataFetcher(Protocol):
    schema_version: str

    def fetch_matches(
        self,
        competition_code: str,
        season_start_year: int,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> FetchResult: ...


@runtime_checkable
class HkjcMarketFetcher(Protocol):
    schema_version: ClassVar[str]
    query_version: str

    def fetch_market_odds(
        self,
        market: MarketType,
        match_source_id: str,
    ) -> FetchResult: ...


@runtime_checkable
class HkjcResultFetcher(Protocol):
    schema_version: ClassVar[str]

    def fetch_match_results(self, match_source_id: str) -> FetchResult: ...


@runtime_checkable
class HkjcScheduledFetcher(Protocol):
    schema_version: ClassVar[str]

    def fetch_scheduled_matches(
        self,
        start_date: date,
        end_date: date,
        *,
        start_index: int | None = None,
        end_index: int | None = None,
    ) -> FetchResult: ...


@runtime_checkable
class HkjcOddsFetcher(HkjcMarketFetcher, HkjcResultFetcher, Protocol):
    def fetch_scheduled_matches(
        self,
        start_date: date,
        end_date: date,
        *,
        start_index: int | None = None,
        end_index: int | None = None,
    ) -> FetchResult: ...


class FotMobLineupFetcher(Protocol):
    def fetch_match_details(self, match_id: int) -> FetchResult: ...


@dataclass
class AdapterBundle:
    football_data: FootballDataFetcher | None = None
    understat: UnderstatAdapter | None = None
    fotmob: FotMobLineupFetcher | None = None
    hkjc: HkjcMarketFetcher | None = None
    news: RssNewsAdapter | None = None
    weather: OpenMeteoAdapter | None = None
    history: FootballDataCoUkAdapter | None = None


def build_adapters(settings: Settings) -> AdapterBundle:
    return AdapterBundle(
        football_data=FootballDataOrgAdapter(
            api_key=settings.football_data_org_api_key or ""
        ),
        understat=UnderstatAdapter(),
        fotmob=FotMobAdapter(),
        hkjc=HkjcAdapter(
            queries_dir=settings.hkjc_queries_dir,
            query_version=settings.hkjc_query_version,
            graphql_url=settings.hkjc_graphql_url,
        ),
        news=RssNewsAdapter(),
        weather=OpenMeteoAdapter(),
        history=FootballDataCoUkAdapter(),
    )


class IngestPipeline:
    def __init__(self, session: Session, adapters: AdapterBundle) -> None:
        self._session: Session = session
        self._adapters: AdapterBundle = adapters

    def ingest_fixtures(
        self,
        competition_code: str,
        season_start_year: int,
        *,
        bootstrap_teams: bool = False,
        run_id: str | None = None,
    ) -> int:
        if self._adapters.football_data is None:
            raise PipelineError("football-data.org adapter is not configured")
        competition = get_competition(self._session, competition_code)
        result = self._adapters.football_data.fetch_matches(
            competition_code,
            season_start_year,
        )
        _ = persist_raw_payload(
            self._session,
            result,
            schema_version=self._adapters.football_data.schema_version,
            run_id=run_id or uuid.uuid4().hex,
        )
        matches = FootballDataOrgAdapter.parse_matches(result.payload)
        if bootstrap_teams:
            for dto in matches:
                _ = ensure_team(
                    self._session,
                    dto.home_team_name,
                    country=competition.country,
                    football_data_id=dto.home_team_source_id,
                )
                _ = ensure_team(
                    self._session,
                    dto.away_team_name,
                    country=competition.country,
                    football_data_id=dto.away_team_source_id,
                )
        for dto in matches:
            fixture = normalize_fixture(self._session, dto, competition.id)
            _ = upsert_match(self._session, fixture)
        return len(matches)

    def link_hkjc_many(
        self,
        competition_codes: Iterable[str],
        start_date: date,
        end_date: date,
        *,
        run_id: str | None = None,
    ) -> dict[str, int]:
        hkjc = self._adapters.hkjc
        if hkjc is None:
            raise PipelineError("HKJC adapter is not configured")
        if not isinstance(hkjc, HkjcScheduledFetcher):
            raise PipelineError("HKJC scheduled match fetching is not configured")
        result = hkjc.fetch_scheduled_matches(start_date, end_date)
        _ = persist_raw_payload(
            self._session,
            result,
            schema_version=hkjc.schema_version,
            run_id=run_id or uuid.uuid4().hex,
        )
        scheduled = HkjcAdapter.parse_scheduled_matches(result.payload)
        return {
            code: link_hkjc_matches(
                self._session,
                scheduled,
                competition_code=code,
            )
            for code in competition_codes
        }

    def link_hkjc(
        self,
        competition_code: str,
        start_date: date,
        end_date: date,
        *,
        run_id: str | None = None,
    ) -> int:
        return self.link_hkjc_many(
            (competition_code,),
            start_date,
            end_date,
            run_id=run_id,
        )[competition_code]

    def ingest_hkjc_odds(
        self,
        match: Match,
        market: MarketType,
        snapshot_kind: SnapshotKind,
        snapshot_at: datetime,
        *,
        run_id: str,
    ) -> tuple[OddsSnapshot, list[MarketLine]]:
        """Persist one HKJC odds snapshot.

        Data layers may ingest HAD, HDC and HIL. The G1 decision layer only
        creates paper bets for HAD; the ledger rejects every other market.
        """
        if self._adapters.hkjc is None:
            raise PipelineError("HKJC adapter is not configured")
        source_match_id = (match.source_match_ids or {}).get("hkjc")
        if source_match_id is None:
            raise PipelineError("match has no hkjc source id")
        result = self._adapters.hkjc.fetch_market_odds(market, source_match_id)
        raw = persist_raw_payload(
            self._session,
            result,
            schema_version=self._adapters.hkjc.schema_version,
            run_id=run_id,
        )
        payload = HkjcAdapter.parse_market_odds(
            result.payload,
            market,
            source_match_id,
        )
        return normalize_hkjc_snapshot(
            self._session,
            match_id=match.id,
            market=market,
            payload=payload,
            snapshot_kind=snapshot_kind,
            snapshot_at=snapshot_at,
            query_version=self._adapters.hkjc.query_version,
            raw_payload_id=raw.id,
            payload_hash=result.payload_hash,
            run_id=run_id,
        )
