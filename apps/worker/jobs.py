from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from rq import Queue, Retry
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.adapters.base import (
    AdapterError,
    AdapterSchemaError,
    FetchResult,
    MinIntervalRateLimiter,
)
from packages.adapters.fotmob import FotMobAdapter
from packages.adapters.hkjc import HkjcAdapter, HkjcMatchResult
from packages.db.models import (
    Availability,
    Competition,
    Lineup,
    MarketLine,
    Match,
    ModelPrediction,
    OddsSnapshot,
    PaperBet,
    Player,
)
from packages.db.session import build_engine, build_session_factory, session_scope
from packages.decision.coverage import (
    run_decision_reconciliation as reconcile_decisions,
)
from packages.decision.service import decide_match
from packages.domain.enums import (
    AvailabilityBasis,
    BetStatus,
    CoverageFlag,
    FetchRunStatus,
    LineupType,
    MarketType,
    MatchStatus,
    SnapshotKind,
    SourceStatus,
)
from packages.feedback.service import (
    build_calibration_report,
    ensure_g1_versions,
)
from packages.ingest.linking import link_fotmob_matches
from packages.ingest.normalize import get_competition, seed_competitions
from packages.ingest.pipeline import (
    AdapterBundle,
    HkjcResultFetcher,
    IngestPipeline,
    build_adapters,
)
from packages.ingest.raw_store import (
    finish_fetch_run,
    persist_raw_payload,
    start_fetch_run,
)
from packages.ingest.triggers import (
    LINEUP_RECHECK_TRIGGER,
    TRIGGER_SCAN_WINDOW,
    TRIGGER_SNAPSHOT_KINDS,
    due_triggers,
    trigger_action,
)
from packages.ledger.service import LedgerService
from packages.shared.config import Settings, get_settings
from packages.shared.time import ensure_utc, utc_now

logger = logging.getLogger(__name__)

HONG_KONG = ZoneInfo("Asia/Hong_Kong")
_TRIGGER_DEDUPE_TTL_SECONDS = 6 * 60 * 60
_LINEUP_ACTIONS = frozenset({"lineup_check", "lineup_recheck_decision"})
DATA_COMPETITIONS: tuple[str, ...] = (
    "EPL",
    "LALIGA",
    "BUNDESLIGA",
    "SERIEA",
    "LIGUE1",
    "UCL",
)
_TRIGGER_RETRY = Retry(max=3, interval=[60, 300, 900])
_RECENT_RESULT_WINDOW = timedelta(hours=18)
_FOTMOB_LINK_HORIZON = timedelta(days=7)
_FOTMOB_LINK_LIMITER_SECONDS = 20.0

def _run_source_fetch[T](
    session: Session,
    *,
    source_name: str,
    params: dict[str, object],
    operation: Callable[[str], T],
    field_scope: str,
    test_evidence_ref: str,
) -> T:
    run_id = uuid.uuid4().hex
    run = start_fetch_run(
        session,
        source_name=source_name,
        run_id=run_id,
        params=params,
    )
    run.source_status = SourceStatus.CONDITIONAL
    run.schema_scope = "live smoke"
    run.field_scope = field_scope
    run.test_evidence_ref = test_evidence_ref
    run.licensing_check = "public/free tier"
    try:
        result = operation(run_id)
    except Exception as exc:
        finish_fetch_run(
            session,
            run,
            status=FetchRunStatus.FAILED,
            request_count=1,
            error_count=1,
            error_summary=str(exc)[:1024],
        )
        # The caller re-raises, so persist the FAILED audit row here or the
        # surrounding session_scope rollback would discard it.
        session.commit()
        raise
    finish_fetch_run(
        session,
        run,
        status=FetchRunStatus.SUCCEEDED,
        request_count=1,
        error_count=0,
    )
    return result


class OddsNotOfferedError(RuntimeError):
    """The requested HKJC pool is not selling yet; retry the trigger job."""


def season_start_year(now: datetime | None = None) -> int:
    """European season labelled by its starting year (July boundary in HKT)."""
    local = ensure_utc(now or utc_now()).astimezone(HONG_KONG)
    return local.year if local.month >= 7 else local.year - 1


def run_daily_ingest(
    season: int | None = None,
    competitions: tuple[str, ...] = DATA_COMPETITIONS,
) -> dict[str, object]:
    settings = get_settings()
    engine = build_engine(settings.database_url)
    factory = build_session_factory(engine)
    with session_scope(factory) as session:
        seed_competitions(session)
        adapters = build_adapters(settings)
        pipeline = IngestPipeline(session, adapters)
        year = season if season is not None else season_start_year()
        fixtures_by_league: dict[str, int] = {}
        fixture_failures: list[Exception] = []
        for competition_code in competitions:
            try:
                fixtures_by_league[competition_code] = _run_source_fetch(
                    session,
                    source_name="football-data.org",
                    params={
                        "competition_code": competition_code,
                        "season_start_year": year,
                    },
                    operation=lambda run_id, code=competition_code: pipeline.ingest_fixtures(
                        code,
                        year,
                        bootstrap_teams=True,
                        run_id=run_id,
                    ),
                    field_scope=f"{competition_code} fixtures",
                    test_evidence_ref="tests/adapters/test_football_data_org.py",
                )
            except Exception as exc:
                # Commit the FAILED source run, keep ingesting the other
                # competitions, and keep the HKJC linking step below alive.
                session.commit()
                fixture_failures.append(exc)
                logger.exception(
                    "fixture ingest failed for %s; continuing with other competitions",
                    competition_code,
                )
        linked_by_league: dict[str, int] = {}
        if adapters.hkjc is not None:
            today_hkt = utc_now().astimezone(HONG_KONG).date()
            end_hkt = today_hkt + timedelta(days=7)
            try:
                linked_by_league = _run_source_fetch(
                    session,
                    source_name="hkjc",
                    params={
                        "operation": "scheduled_matches",
                        "start_date": today_hkt.isoformat(),
                        "end_date": end_hkt.isoformat(),
                    },
                    operation=lambda run_id: pipeline.link_hkjc_many(
                        competitions,
                        today_hkt,
                        end_hkt,
                        run_id=run_id,
                    ),
                    field_scope="multi-league fixtures",
                    test_evidence_ref="tests/adapters/test_hkjc.py",
                )
            except AdapterError:
                linked_by_league = {code: 0 for code in competitions}
        total_fixtures = sum(fixtures_by_league.values())
        total_linked = sum(linked_by_league.values())
        if fixture_failures:
            # Persist the successful HKJC linking before surfacing the failure.
            session.commit()
            raise fixture_failures[0]
        return {
            "fixtures": total_fixtures,
            "hkjc_linked": total_linked,
            "leagues": fixtures_by_league,
            "hkjc_by_league": linked_by_league,
        }


def run_recent_result_refresh(now: datetime | None = None) -> dict[str, object]:
    """Refresh fixtures that kicked off recently but are still not final.

    The daily 06:00 HKT ingest can catch a match while it is still live; without
    a follow-up read the database keeps that stale status (and hides the result)
    until the next day. This job re-reads only competitions with an unresolved
    match in the recent window, so it is cheap and cannot touch unrelated
    upcoming fixtures.
    """
    current = ensure_utc(now or utc_now())
    settings = get_settings()
    engine = build_engine(settings.database_url)
    factory = build_session_factory(engine)
    with session_scope(factory) as session:
        seed_competitions(session)
        recent_start = current - _RECENT_RESULT_WINDOW
        codes = list(
            session.scalars(
                select(Competition.code)
                .join(Match, Match.competition_id == Competition.id)
                .where(
                    Match.kickoff_at < current,
                    Match.kickoff_at >= recent_start,
                    Match.status.in_(
                        (MatchStatus.SCHEDULED, MatchStatus.LIVE)
                    ),
                )
                .distinct()
                .order_by(Competition.code)
            ).all()
        )
        if not codes:
            return {"fixtures": 0, "leagues": {}}

        adapters = build_adapters(settings)
        pipeline = IngestPipeline(session, adapters)
        year = season_start_year(current)
        date_from = recent_start.date().isoformat()
        date_to = current.date().isoformat()
        fixtures_by_league: dict[str, int] = {}
        failures: list[Exception] = []
        for competition_code in codes:
            try:
                fixtures_by_league[competition_code] = _run_source_fetch(
                    session,
                    source_name="football-data.org",
                    params={
                        "competition_code": competition_code,
                        "season_start_year": year,
                        "date_from": date_from,
                        "date_to": date_to,
                    },
                    operation=lambda run_id, code=competition_code: pipeline.ingest_fixtures(
                        code,
                        year,
                        date_from=date_from,
                        date_to=date_to,
                        run_id=run_id,
                    ),
                    field_scope=f"recent {competition_code} fixtures",
                    test_evidence_ref="tests/apps/test_worker.py",
                )
            except Exception as exc:
                session.commit()
                failures.append(exc)
                logger.exception(
                    "recent result refresh failed for %s; continuing", competition_code
                )
        if failures:
            session.commit()
            raise failures[0]
    return {"fixtures": sum(fixtures_by_league.values()), "leagues": fixtures_by_league}


def _build_fotmob_link_adapter() -> FotMobAdapter:
    return FotMobAdapter(limiter=MinIntervalRateLimiter(_FOTMOB_LINK_LIMITER_SECONDS))


def _link_fotmob_league(
    session: Session,
    adapter: FotMobAdapter,
    competition_code: str,
    season_year: int,
) -> int:
    fetched = adapter.fetch_league_fixtures(competition_code, season_year)
    fixtures = FotMobAdapter.parse_league_fixtures(fetched.payload)
    return link_fotmob_matches(
        session, fixtures, competition_code=competition_code
    )


def run_fotmob_link(now: datetime | None = None) -> dict[str, object]:
    """Link upcoming fixtures to FotMob ids so lineup checks can run."""
    current = ensure_utc(now or utc_now())
    settings = get_settings()
    engine = build_engine(settings.database_url)
    factory = build_session_factory(engine)
    with session_scope(factory) as session:
        seed_competitions(session)
        year = season_start_year(current)
        horizon = current + _FOTMOB_LINK_HORIZON
        missing: dict[str, int] = {}
        for competition_code in DATA_COMPETITIONS:
            competition = get_competition(session, competition_code)
            rows = session.scalars(
                select(Match).where(
                    Match.competition_id == competition.id,
                    Match.status == MatchStatus.SCHEDULED,
                    Match.kickoff_at >= current,
                    Match.kickoff_at <= horizon,
                )
            ).all()
            unlinked = [
                match for match in rows if "fotmob" not in (match.source_match_ids or {})
            ]
            if unlinked:
                missing[competition_code] = len(unlinked)
        if not missing:
            return {"linked": {}, "errors": {}, "missing": {}}

        adapter = _build_fotmob_link_adapter()
        linked: dict[str, int] = {}
        errors: dict[str, str] = {}
        try:
            for competition_code in missing:
                try:
                    linked[competition_code] = _run_source_fetch(
                        session,
                        source_name="fotmob",
                        params={
                            "operation": "league_fixtures",
                            "competition_code": competition_code,
                            "season_start_year": year,
                        },
                        operation=lambda run_id, code=competition_code: _link_fotmob_league(
                            session, adapter, code, year
                        ),
                        field_scope=f"{competition_code} fotmob fixtures",
                        test_evidence_ref="tests/adapters/test_fotmob.py",
                    )
                except AdapterError as exc:
                    errors[competition_code] = str(exc)
                    logger.warning(
                        "fotmob fixture link failed for %s: %s",
                        competition_code,
                        exc,
                    )
        finally:
            adapter.close()
        return {"linked": linked, "errors": errors, "missing": missing}



def ingest_trigger_odds(
    session: Session,
    match: Match,
    trigger: str,
    adapters: AdapterBundle,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    _ = trigger_action(trigger)
    try:
        snapshot_kind = TRIGGER_SNAPSHOT_KINDS[trigger]
    except KeyError as exc:
        raise ValueError(f"{trigger} has no odds snapshot") from exc
    snapshot_at = ensure_utc(now or utc_now())
    if snapshot_at >= ensure_utc(match.kickoff_at):
        return {
            "status": "after_kickoff",
            "trigger": trigger,
            "snapshot_kind": snapshot_kind.value,
        }
    if (match.source_match_ids or {}).get("hkjc") is None:
        return {
            "status": "link_missing",
            "trigger": trigger,
            "snapshot_kind": snapshot_kind.value,
        }
    hkjc_match_id = str((match.source_match_ids or {})["hkjc"])
    pipeline = IngestPipeline(session, adapters)
    snapshot, lines = _run_source_fetch(
        session,
        source_name="hkjc",
        params={
            "operation": "market_odds",
            "market": MarketType.HAD.value,
            "match_source_id": hkjc_match_id,
        },
        operation=lambda run_id: pipeline.ingest_hkjc_odds(
            match,
            MarketType.HAD,
            snapshot_kind,
            snapshot_at,
            run_id=run_id,
        ),
        field_scope="HAD odds",
        test_evidence_ref="tests/adapters/test_hkjc.py",
    )
    return {
        "status": "ingested" if lines else "no_offer",
        "trigger": trigger,
        "snapshot_kind": snapshot_kind.value,
        "snapshot_id": str(snapshot.id),
        "line_count": len(lines),
    }


def run_match_trigger(match_id: str, trigger: str) -> dict[str, object]:
    _ = trigger_action(trigger)
    settings = get_settings()
    engine = build_engine(settings.database_url)
    factory = build_session_factory(engine)
    with session_scope(factory) as session:
        match = session.get(Match, uuid.UUID(match_id))
        if match is None:
            raise ValueError(f"unknown match {match_id}")
        try:
            result = ingest_trigger_odds(
                session,
                match,
                trigger,
                build_adapters(settings),
            )
        except Exception:
            session.commit()
            raise
        if result["status"] == "no_offer":
            session.commit()
            raise OddsNotOfferedError(f"{match_id} {trigger} HKJC pool not offered")
        return result


def _set_flag(match: Match, flag: CoverageFlag, *, present: bool) -> None:
    flags = [value for value in (match.coverage_flags or []) if value != flag.value]
    if present:
        flags.append(flag.value)
    match.coverage_flags = flags


def _set_lineup_flag(match: Match, *, confirmed: bool) -> None:
    _set_flag(match, CoverageFlag.LINEUP_UNCONFIRMED, present=not confirmed)


def _persist_lineups(
    session: Session,
    match: Match,
    lineups: list,
    *,
    source_url: str,
    now: datetime,
) -> None:
    for lineup in lineups:
        team_id = (
            match.home_team_id
            if lineup.team_side == "home"
            else match.away_team_id
        )
        row = session.scalar(
            select(Lineup).where(
                Lineup.match_id == match.id,
                Lineup.team_id == team_id,
                Lineup.lineup_type == lineup.lineup_type,
                Lineup.source == "fotmob",
            )
        )
        if row is None:
            row = Lineup(
                match_id=match.id,
                team_id=team_id,
                lineup_type=lineup.lineup_type,
                source="fotmob",
                starters=[],
                subs=[],
                inferred=lineup.inferred,
                fetched_at=now,
            )
            session.add(row)
        row.formation = lineup.formation
        row.starters = [
            {
                "source_player_id": player.source_player_id,
                "name": player.name,
                "position": player.position,
            }
            for player in lineup.starters
        ]
        row.subs = [
            {
                "source_player_id": player.source_player_id,
                "name": player.name,
                "position": player.position,
            }
            for player in lineup.subs
        ]
        row.inferred = lineup.inferred
        row.source_url = source_url
        row.fetched_at = now
        row.available_at = now
        row.availability_basis = AvailabilityBasis.PROVIDER_POINT_IN_TIME
        row.evidence_grade = AvailabilityBasis.PROVIDER_POINT_IN_TIME
    session.flush()


def _player_id_for_unavailable(
    session: Session,
    team_id: uuid.UUID,
    *,
    source_player_id: int | None,
    name: str,
) -> uuid.UUID | None:
    if source_player_id is not None:
        player = session.scalar(
            select(Player).where(Player.fotmob_id == source_player_id)
        )
        if player is None:
            player = Player(
                name=name or f"FotMob {source_player_id}",
                team_id=team_id,
                fotmob_id=source_player_id,
            )
            session.add(player)
            session.flush()
        elif player.team_id is None:
            player.team_id = team_id
        return player.id
    if not name:
        return None
    player = session.scalar(
        select(Player).where(Player.team_id == team_id, Player.name == name)
    )
    if player is None:
        player = Player(name=name, team_id=team_id)
        session.add(player)
        session.flush()
    return player.id


def _persist_unavailable(
    session: Session,
    match: Match,
    rows: list,
    *,
    source_url: str,
    now: datetime,
) -> None:
    for item in rows:
        team_id = (
            match.home_team_id if item.team_side == "home" else match.away_team_id
        )
        player_id = _player_id_for_unavailable(
            session,
            team_id,
            source_player_id=item.source_player_id,
            name=item.name,
        )
        conditions = [
            Availability.match_id == match.id,
            Availability.team_id == team_id,
            Availability.source == "fotmob",
        ]
        if player_id is None:
            conditions.append(Availability.player_id.is_(None))
        else:
            conditions.append(Availability.player_id == player_id)
        row = session.scalar(select(Availability).where(*conditions))
        if row is None:
            row = Availability(
                match_id=match.id,
                team_id=team_id,
                player_id=player_id,
                status=item.status,
                source="fotmob",
                fetched_at=now,
            )
            session.add(row)
        row.status = item.status
        row.reason = item.reason
        row.expected_return = item.expected_return
        row.source_url = source_url
        row.fetched_at = now
        row.available_at = now
        row.availability_basis = AvailabilityBasis.PROVIDER_POINT_IN_TIME
        row.evidence_grade = AvailabilityBasis.PROVIDER_POINT_IN_TIME
    session.flush()


def check_lineup(
    session: Session,
    match: Match,
    trigger: str,
    adapters: AdapterBundle,
) -> str:
    """Apply the T-75m lineup gate or the T-30m recheck to one match.

    HAD is not lineup-dependent in G1, so the result is recorded as a coverage
    flag instead of vetoing the paper bet.
    """
    action = trigger_action(trigger)
    if action not in _LINEUP_ACTIONS:
        raise ValueError(f"{trigger} is not a lineup trigger")
    source_id = (match.source_match_ids or {}).get("fotmob")
    if source_id is None:
        _set_flag(match, CoverageFlag.LINEUP_LINK_MISSING, present=True)
        _set_lineup_flag(match, confirmed=False)
        return "link_missing"
    _set_flag(match, CoverageFlag.LINEUP_LINK_MISSING, present=False)
    if adapters.fotmob is None:
        _set_lineup_flag(match, confirmed=False)
        return "unavailable"
    fetched = adapters.fotmob.fetch_match_details(int(source_id))
    try:
        lineups = FotMobAdapter.parse_lineups(fetched.payload, LineupType.STANDARD)
    except AdapterSchemaError:
        lineups = []
    try:
        unavailable = FotMobAdapter.parse_unavailable(fetched.payload)
    except AdapterSchemaError:
        unavailable = []
    now = utc_now()
    _persist_lineups(
        session, match, lineups, source_url=fetched.source_url, now=now
    )
    _persist_unavailable(
        session, match, unavailable, source_url=fetched.source_url, now=now
    )
    sides = {lineup.team_side for lineup in lineups}
    confirmed = {"home", "away"}.issubset(sides)
    _set_lineup_flag(match, confirmed=confirmed)
    return "confirmed" if confirmed else "unconfirmed"


def run_lineup_check(match_id: str, trigger: str) -> dict[str, str]:
    settings = get_settings()
    engine = build_engine(settings.database_url)
    factory = build_session_factory(engine)
    with session_scope(factory) as session:
        match = session.get(Match, uuid.UUID(match_id))
        if match is None:
            raise ValueError(f"unknown match {match_id}")
        adapters = build_adapters(settings)
        is_decision_trigger = trigger == LINEUP_RECHECK_TRIGGER
        try:
            status = check_lineup(session, match, trigger, adapters)
        except AdapterError:
            if is_decision_trigger:
                _ = decide_match(session, match, None, now=utc_now())
                session.commit()
            raise
        result = {"match_id": match_id, "trigger": trigger, "lineup": status}
        if not is_decision_trigger:
            return result

        try:
            odds_result = ingest_trigger_odds(session, match, trigger, adapters)
        except AdapterError:
            _ = decide_match(session, match, None, now=utc_now())
            session.commit()
            raise

        odds_status = str(odds_result["status"])
        result["odds"] = odds_status
        if odds_status in {"link_missing", "after_kickoff"}:
            _ = decide_match(session, match, None, now=utc_now())
            result["decision"] = "skipped"
            return result
        if odds_status == "no_offer":
            snapshot = _load_snapshot(session, odds_result.get("snapshot_id"))
            _ = decide_match(session, match, snapshot, now=utc_now())
            session.commit()
            raise OddsNotOfferedError(f"{match_id} {trigger} HKJC pool not offered")

        snapshot = _load_snapshot(session, odds_result.get("snapshot_id"))
        decision = decide_match(session, match, snapshot, now=utc_now())
        result["decision"] = decision.status
        return result


def _load_snapshot(session: Session, snapshot_id: object) -> OddsSnapshot | None:
    if snapshot_id is None:
        return None
    return session.get(OddsSnapshot, uuid.UUID(str(snapshot_id)))


def _claim_trigger(connection: object | None, key: str) -> bool:
    setter = getattr(connection, "set", None)
    if setter is None:
        return True
    return bool(setter(key, "1", nx=True, ex=_TRIGGER_DEDUPE_TTL_SECONDS))


def _release_trigger(connection: object | None, key: str) -> None:
    deleter = getattr(connection, "delete", None)
    if deleter is not None:
        deleter(key)


def release_trigger_dedupe(
    job: object,
    connection: object,
    exc_type: object,
    exc_value: object,
    traceback: object,
) -> None:
    """RQ failure callback: allow a failed trigger job to be enqueued again."""
    meta = getattr(job, "meta", None) or {}
    key = meta.get("dedupe_key")
    if key:
        _release_trigger(connection, key)


def _enqueue_trigger(
    queue: Queue,
    function_path: str,
    match_id: str,
    trigger: str,
    dedupe_key: str,
) -> None:
    connection = getattr(queue, "connection", None)
    try:
        _ = queue.enqueue(
            function_path,
            match_id,
            trigger,
            meta={"dedupe_key": dedupe_key},
            on_failure=release_trigger_dedupe,
            retry=_TRIGGER_RETRY,
        )
    except Exception:
        _release_trigger(connection, dedupe_key)
        raise


def _enqueue_due_triggers(
    session: Session,
    current: datetime,
    queue: Queue,
) -> int:
    connection = getattr(queue, "connection", None)
    enqueued = 0
    matches = session.execute(
        select(Match).where(
            Match.status == MatchStatus.SCHEDULED,
            Match.kickoff_at > current,
            Match.kickoff_at <= current + timedelta(hours=25),
        )
    ).scalars()
    for match in matches:
        for trigger in due_triggers(
            current,
            match.kickoff_at,
            window=TRIGGER_SCAN_WINDOW,
        ):
            dedupe_key = f"football:trigger:{match.id}:{trigger}"
            if not _claim_trigger(connection, dedupe_key):
                continue
            function_path = (
                "apps.worker.jobs.run_lineup_check"
                if trigger_action(trigger) in _LINEUP_ACTIONS
                else "apps.worker.jobs.run_match_trigger"
            )
            _enqueue_trigger(
                queue,
                function_path,
                str(match.id),
                trigger,
                dedupe_key,
            )
            enqueued += 1
    return enqueued


def enqueue_due_match_triggers(
    now: datetime | None = None,
    queue: Queue | None = None,
    *,
    session: Session | None = None,
) -> int:
    """Enqueue every match trigger that fell inside the scan window."""
    current = ensure_utc(now or utc_now())
    if queue is None:
        from apps.worker.main import build_queue

        queue = build_queue()
    if session is not None:
        return _enqueue_due_triggers(session, current, queue)
    settings = get_settings()
    engine = build_engine(settings.database_url)
    factory = build_session_factory(engine)
    with session_scope(factory) as opened:
        return _enqueue_due_triggers(opened, current, queue)


def _fetch_and_persist_result(
    session: Session,
    hkjc: HkjcResultFetcher,
    source_id: str,
    match_date: date,
    run_id: str,
) -> FetchResult:
    fetched = hkjc.fetch_match_results(source_id, match_date=match_date)
    _ = persist_raw_payload(
        session,
        fetched,
        schema_version=hkjc.schema_version,
        run_id=run_id,
    )
    return fetched


def _load_hkjc_result(
    session: Session,
    settings: Settings,
    match: Match,
    hkjc: HkjcResultFetcher | None = None,
) -> HkjcMatchResult | None:
    source_id = (match.source_match_ids or {}).get("hkjc")
    if source_id is None:
        return None
    if hkjc is None:
        hkjc = build_adapters(settings).hkjc
    if not isinstance(hkjc, HkjcResultFetcher):
        return None
    fetched = _run_source_fetch(
        session,
        source_name="hkjc",
        params={"operation": "match_results", "match_source_id": source_id},
        operation=lambda run_id: _fetch_and_persist_result(
            session,
            hkjc,
            source_id,
            ensure_utc(match.kickoff_at).astimezone(HONG_KONG).date(),
            run_id,
        ),
        field_scope="match results",
        test_evidence_ref="tests/adapters/test_hkjc.py",
    )
    return HkjcAdapter.parse_match_results(fetched.payload, source_id)


def _closing_odds(
    session: Session,
    bet: PaperBet,
) -> tuple[Decimal | None, uuid.UUID | None]:
    row = session.execute(
        select(MarketLine.odds_decimal, MarketLine.snapshot_id)
        .join(OddsSnapshot, OddsSnapshot.id == MarketLine.snapshot_id)
        .where(
            OddsSnapshot.match_id == bet.match_id,
            OddsSnapshot.market == bet.market,
            OddsSnapshot.snapshot_kind == SnapshotKind.T5M,
            MarketLine.condition_raw == bet.line_key,
            MarketLine.side == bet.selection,
        )
        .order_by(OddsSnapshot.snapshot_at.desc())
        .limit(1)
    ).first()
    if row is None:
        return None, None
    return Decimal(str(row[0])), row[1]


def _decision_probability(session: Session, bet: PaperBet) -> Decimal | None:
    row = session.execute(
        select(ModelPrediction.probability)
        .where(
            ModelPrediction.match_id == bet.match_id,
            ModelPrediction.market == bet.market,
            ModelPrediction.line_key == bet.line_key,
            ModelPrediction.outcome == bet.selection,
            ModelPrediction.decision_at <= bet.decision_at,
        )
        .order_by(ModelPrediction.decision_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        return None
    return Decimal(str(row))


def _ucl_result_requires_gate(
    competition_code: str | None,
    matchday: int | None,
) -> bool:
    """UCL league-phase matches cannot go to extra time.

    ``matchday`` 1-8 is the league phase, where a draw is final after 90
    minutes. Knockout matches (no matchday) remain behind the semantics gate.
    """
    if competition_code != "UCL":
        return False
    return not (matchday is not None and 1 <= matchday <= 8)


def settle_match(
    match_id: str,
    *,
    hkjc: HkjcResultFetcher | None = None,
) -> dict[str, int]:
    settings = get_settings()
    engine = build_engine(settings.database_url)
    factory = build_session_factory(engine)
    with session_scope(factory) as session:
        match = session.get(Match, uuid.UUID(match_id))
        if match is None:
            raise ValueError(f"unknown match {match_id}")
        result = _load_hkjc_result(session, settings, match, hkjc)
        if result is None:
            return {"settled": 0}
        competition = session.get(Competition, match.competition_id)
        goals = HkjcAdapter.goals_90_from_result(
            result,
            settings.hkjc_result_semantics,
            is_ucl=_ucl_result_requires_gate(
                competition.code if competition is not None else None,
                match.matchday,
            ),
        )
        if goals is None:
            return {"settled": 0}
        refunded = HkjcAdapter.refunded_markets(result)
        bets = list(
            session.execute(
                select(PaperBet).where(
                    PaperBet.match_id == match.id,
                    PaperBet.status == BetStatus.PENDING,
                )
            ).scalars()
        )
        for bet in bets:
            ledger = LedgerService(
                session,
                initial_bankroll=settings.initial_bankroll,
                fee_rate=settings.fee_rate,
                experiment_id=bet.experiment_id,
            )
            closing_odds, closing_snapshot_id = _closing_odds(session, bet)
            _ = ledger.settle_paper_bet(
                bet.id,
                home_goals_90=goals[0],
                away_goals_90=goals[1],
                refunded_markets=refunded,
                payout_confirmed=result.payout_confirmed,
                hk_result_ref=result.match_source_id,
                closing_odds=closing_odds,
                final_probability=_decision_probability(session, bet),
                closing_odds_snapshot_id=closing_snapshot_id,
            )
        return {"settled": len(bets)}


def run_settlement_scan(now: datetime | None = None) -> dict[str, int]:
    current = ensure_utc(now or utc_now())
    settings = get_settings()
    engine = build_engine(settings.database_url)
    factory = build_session_factory(engine)
    with session_scope(factory) as session:
        match_ids = list(
            session.execute(
                select(PaperBet.match_id)
                .join(Match, Match.id == PaperBet.match_id)
                .where(
                    PaperBet.status == BetStatus.PENDING,
                    Match.kickoff_at <= current - timedelta(hours=2),
                )
                .distinct()
            ).scalars()
        )
    adaptive_hkjc = HkjcAdapter(
        queries_dir=settings.hkjc_queries_dir,
        query_version=settings.hkjc_query_version,
        graphql_url=settings.hkjc_graphql_url,
    )
    settled = 0
    errors = 0
    try:
        for match_id in match_ids:
            try:
                settled += settle_match(str(match_id), hkjc=adaptive_hkjc)["settled"]
            except Exception:  # noqa: BLE001 - isolate one match from the batch
                errors += 1
    finally:
        adaptive_hkjc.close()
    return {"matches": len(match_ids), "settled": settled, "errors": errors}


def run_decision_reconciliation(now: datetime | None = None) -> dict[str, int]:
    """Fill any T-30m decision logs that the trigger flow missed."""
    current = ensure_utc(now or utc_now())
    settings = get_settings()
    engine = build_engine(settings.database_url)
    factory = build_session_factory(engine)
    with session_scope(factory) as session:
        summary = reconcile_decisions(session, now=current)
    return {"reconciled": summary.reconciled, "errors": summary.errors}


def run_calibration_report(time_block: str | None = None) -> dict[str, object]:
    """Record calibration metrics for settled paper bets; never promotes.

    The default block is the current UTC month, so weekly runs within a month
    upsert the same rows instead of creating a new bucket per run.
    """
    settings = get_settings()
    engine = build_engine(settings.database_url)
    factory = build_session_factory(engine)
    label = time_block or utc_now().strftime("%Y-%m")
    with session_scope(factory) as session:
        ensure_g1_versions(session)
        metrics = build_calibration_report(session, time_block=label)
    return {"time_block": label, "metrics": len(metrics)}


__all__ = [
    "check_lineup",
    "enqueue_due_match_triggers",
    "ingest_trigger_odds",
    "release_trigger_dedupe",
    "run_calibration_report",
    "run_daily_ingest",
    "run_decision_reconciliation",
    "run_fotmob_link",
    "run_lineup_check",
    "run_match_trigger",
    "run_recent_result_refresh",
    "run_settlement_scan",
    "season_start_year",
    "settle_match",
]
