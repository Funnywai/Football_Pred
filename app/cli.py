import argparse
import asyncio
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.ledger import agent_abc_update, agent_ledger_update, agent_summary
from app.agents.risk import evaluate_risk
from app.config import Settings, configure_logging, get_settings
from app.data.leagues import seed_leagues
from app.db.models import League, Match, MatchStat, OddsSnapshot, Result, Season, Team
from app.db.session import Database
from app.ml.backtest import format_report, run_backtest
from app.ml.jobs import predict_upcoming, retrain
from app.providers.football_data.provider import FootballDataProvider, HistoricalMatchRecord
from app.services import reset as reset_service
from app.services.alias import TeamMatcher
from app.services.fixtures import season_bounds
from app.services.ledger import ledger_update, shadow_ledger_update, summary
from app.services.runs import track_run

DEFAULT_DIVISIONS = ["E0", "SP1", "I1", "D1", "F1"]

# football-data.co.uk publishes results/stats after the match; 24h is a conservative
# availability timestamp. Feature building additionally requires a 48h lead, so a
# match's stats never enter a feature row for a kickoff within 48h of that match.
STATS_AVAILABLE_AFTER = timedelta(hours=24)


async def backfill(
    session_factory: async_sessionmaker[AsyncSession],
    provider: FootballDataProvider,
    year_from: int,
    year_to: int,
    divisions: list[str],
) -> int:
    total = 0
    for year in range(year_from, year_to + 1):
        records = await provider.fetch_historical(year, divisions=divisions)
        total += await track_run(
            session_factory,
            "backfill_history",
            lambda session, recs=records: _upsert_history(session, recs),
        )
    return total


async def _upsert_history(session: AsyncSession, records: list[HistoricalMatchRecord]) -> int:
    count = 0
    for record in records:
        league = (
            await session.execute(select(League).where(League.code == record.league_code))
        ).scalar_one_or_none()
        if league is None:
            continue
        season = (
            await session.execute(
                select(Season).where(
                    Season.league_id == league.id, Season.label == record.season_label
                )
            )
        ).scalar_one_or_none()
        if season is None:
            start, end = season_bounds(record.season_label)
            season = Season(
                league_id=league.id,
                label=record.season_label,
                start_date=start,
                end_date=end,
            )
            session.add(season)
            await session.flush()
        home = await _resolve_team(session, record.home_team_name)
        away = await _resolve_team(session, record.away_team_name)
        match = (
            await session.execute(
                select(Match).where(
                    Match.season_id == season.id,
                    Match.home_team_id == home.id,
                    Match.away_team_id == away.id,
                    Match.kickoff_time == record.kickoff_time,
                )
            )
        ).scalar_one_or_none()
        if match is None:
            match = Match(
                season_id=season.id,
                league_id=league.id,
                hkjc_match_id=None,
                kickoff_time=record.kickoff_time,
                status="finished",
                home_team_id=home.id,
                away_team_id=away.id,
            )
            session.add(match)
            await session.flush()
        await _upsert_result(session, match, record)
        await _upsert_match_stats(session, match, record)
        existing = (
            await session.execute(
                select(OddsSnapshot).where(
                    OddsSnapshot.match_id == match.id,
                    OddsSnapshot.odds_type == "HAD",
                    OddsSnapshot.inplay.is_(False),
                    OddsSnapshot.snapshot_bucket == record.kickoff_time,
                )
            )
        ).scalar_one_or_none()
        payload = {"odds": record.odds}
        if existing is None:
            session.add(
                OddsSnapshot(
                    match_id=match.id,
                    captured_at=record.kickoff_time,
                    snapshot_bucket=record.kickoff_time,
                    source="football_data",
                    inplay=False,
                    odds_type="HAD",
                    payload=payload,
                )
            )
        else:
            existing.payload = payload
        count += 1
    return count


async def _upsert_result(
    session: AsyncSession, match: Match, record: HistoricalMatchRecord
) -> None:
    existing = (
        await session.execute(select(Result).where(Result.match_id == match.id))
    ).scalar_one_or_none()
    if existing is not None and existing.source == "hkjc":
        return
    if existing is None:
        session.add(
            Result(
                match_id=match.id,
                home_score=record.home_score,
                away_score=record.away_score,
                source="football_data",
                confirmed=True,
                confirmed_at=datetime.now(UTC),
            )
        )
    else:
        existing.home_score = record.home_score
        existing.away_score = record.away_score
        existing.source = "football_data"
        existing.confirmed = True
        existing.confirmed_at = datetime.now(UTC)
    await session.flush()


def _has_stats(record: HistoricalMatchRecord) -> bool:
    return any(
        value is not None
        for value in (
            record.home_shots,
            record.away_shots,
            record.home_sot,
            record.away_sot,
            record.home_xg,
            record.away_xg,
            record.home_corners,
            record.away_corners,
        )
    )


async def _upsert_match_stats(
    session: AsyncSession, match: Match, record: HistoricalMatchRecord
) -> None:
    if not _has_stats(record):
        return
    existing = (
        await session.execute(
            select(MatchStat).where(
                MatchStat.match_id == match.id, MatchStat.source == "football_data"
            )
        )
    ).scalar_one_or_none()
    available_at = record.kickoff_time + STATS_AVAILABLE_AFTER
    if existing is None:
        session.add(
            MatchStat(
                match_id=match.id,
                source="football_data",
                home_shots=record.home_shots,
                away_shots=record.away_shots,
                home_sot=record.home_sot,
                away_sot=record.away_sot,
                home_xg=record.home_xg,
                away_xg=record.away_xg,
                home_corners=record.home_corners,
                away_corners=record.away_corners,
                available_at=available_at,
            )
        )
    else:
        existing.home_shots = record.home_shots
        existing.away_shots = record.away_shots
        existing.home_sot = record.home_sot
        existing.away_sot = record.away_sot
        existing.home_xg = record.home_xg
        existing.away_xg = record.away_xg
        existing.home_corners = record.home_corners
        existing.away_corners = record.away_corners
        existing.available_at = available_at
    await session.flush()


async def _resolve_team(session: AsyncSession, name: str) -> Team:
    teams = (await session.execute(select(Team))).scalars().all()
    matched = TeamMatcher(teams).match(name)
    if matched is not None:
        return matched
    team = Team(name_en=name, name_ch=None, hkjc_team_id=None, aliases=[], external_ids={})
    session.add(team)
    await session.flush()
    return team


async def _run_backfill(args: argparse.Namespace) -> None:
    settings = get_settings()
    db = Database(settings.database_url)
    provider = FootballDataProvider(settings.football_data_base, divisions=args.divisions)
    try:
        async with db.session_factory() as session:
            await seed_leagues(session)
            await session.commit()
        total = await backfill(
            db.session_factory, provider, args.year_from, args.year_to, args.divisions
        )
        print(f"backfill complete: {total} matches upserted")
    finally:
        await provider.aclose()
        await db.dispose()


async def _run_seed_leagues() -> None:
    settings = get_settings()
    db = Database(settings.database_url)
    try:
        async with db.session_factory() as session:
            inserted = await seed_leagues(session)
            await session.commit()
        print(f"seed-leagues complete: {inserted} leagues inserted")
    finally:
        await db.dispose()


async def _run_retrain() -> None:
    settings = get_settings()
    db = Database(settings.database_url)
    try:
        promoted = await retrain(db.session_factory, settings)
        print(f"retrain complete: {promoted} champion(s) promoted")
    finally:
        await db.dispose()


async def _run_predict() -> None:
    settings = get_settings()
    db = Database(settings.database_url)
    try:
        written = await predict_upcoming(db.session_factory, settings)
        print(f"predict complete: {written} prediction(s) written")
    finally:
        await db.dispose()


async def _run_ledger() -> None:
    settings = get_settings()
    db = Database(settings.database_url)
    try:
        processed = await ledger_update(db.session_factory, settings)
        print(f"ledger complete: {processed} bet(s) settled or placed")
    finally:
        await db.dispose()


async def _run_shadow_ledger() -> None:
    settings = get_settings()
    db = Database(settings.database_url)
    try:
        processed = await shadow_ledger_update(db.session_factory, settings)
        print(f"shadow-ledger complete: {processed} bet(s) settled or placed")
    finally:
        await db.dispose()


async def _run_agent_ledger(args: argparse.Namespace) -> None:
    settings = get_settings()
    db = Database(settings.database_url)
    try:
        processed = await agent_ledger_update(db.session_factory, settings, args.variant)
        async with db.session_factory() as session:
            values = await agent_summary(session, settings, args.variant)
        print(
            f"agent-ledger complete: run recorded as agent_ledger_update, "
            f"{processed} bet(s) settled or placed"
        )
        print(
            f"agent book ({args.variant}): bets={values.n_bets} settled={values.n_settled} "
            f"open={values.n_open} bankroll={values.bankroll:.2f}"
        )
    finally:
        await db.dispose()


async def _run_agent_abc(args: argparse.Namespace) -> None:
    settings = get_settings()
    db = Database(settings.database_url)
    try:
        summary = await agent_abc_update(
            db.session_factory, settings, max_kickoff_minutes=args.window_minutes
        )
        decisions = summary.approved + summary.rejected
        print(
            f"agent-abc complete: run_id={summary.run_id} "
            f"matches={summary.matches_considered} candidates={summary.candidates} "
            f"briefs={summary.briefs} decisions={decisions} "
            f"approved={summary.approved} rejected={summary.rejected} "
            f"prefilters={summary.prefilters} llm_calls={summary.llm_calls} "
            f"a_only_placed={summary.a_only_placed} "
            f"bets_placed={summary.bets_placed} bets_settled={summary.bets_settled}"
        )
    finally:
        await db.dispose()


async def _run_agent_evaluate() -> None:
    settings = get_settings()
    db = Database(settings.database_url)
    try:
        async with db.session_factory() as session:
            result = await evaluate_risk(session, settings)
            await session.commit()
        print(
            f"agent-evaluate complete: run_id={result.run_id} "
            f"matches={result.matches_considered} candidates={result.candidates_evaluated} "
            f"bets={result.bets_allowed} no_bets={result.no_bets} "
            f"total_stake={result.total_stake:.0f}"
        )
    finally:
        await db.dispose()


def _print_reset_counts(title: str, counts: dict[str, int], names: tuple[str, ...]) -> None:
    print(title)
    for name in names:
        print(f"  {name}: {counts.get(name, 0)}")


def _print_artifact_note(settings: Settings) -> None:
    directory = settings.ml_artifact_dir
    count = reset_service.artifact_file_count(directory)
    print(f"  artifacts: {directory} ({count} file(s) remain; not deleted)")


async def _run_reset_paper(args: argparse.Namespace) -> None:
    settings = get_settings()
    execute = args.yes and not args.dry_run
    if args.backup and execute:
        try:
            reset_service.backup_database(settings.database_url, args.backup)
        except reset_service.ResetError as exc:
            raise SystemExit(f"reset-paper aborted: {exc}") from exc
        print(f"backup written to {args.backup}")
    elif args.backup:
        print(f"backup skipped in dry-run: {args.backup}")
    db = Database(settings.database_url)
    try:
        async with db.session_factory() as session:
            try:
                before = await summary(session, settings)
                plan = reset_service.ResetPlan(
                    include_history=args.include_history,
                    include_runs=args.include_runs,
                    keep_models=args.keep_models,
                )
                counts = await reset_service.inspect(
                    session,
                    include_history=args.include_history,
                    include_runs=args.include_runs,
                    keep_models=args.keep_models,
                )
                scoped = plan.scoped_tables()
                history = "delete" if args.include_history else "keep"
                runs = "delete" if args.include_runs else "keep"
                models = "keep" if args.keep_models else "delete"
                print("reset-paper plan" + ("" if execute else " (dry-run)"))
                print(f"  scope: history={history} runs={runs} models={models}")
                _print_reset_counts("  would delete:", counts, scoped)
                _print_reset_counts("  would keep:", counts, plan.kept_tables())
                print(
                    f"  bankroll: {before.bankroll:.2f} -> {settings.ledger_initial_bankroll:.2f}"
                )
                if not args.keep_models:
                    _print_artifact_note(settings)
                if not execute:
                    print("nothing deleted; pass --yes to execute")
                    return
                deleted = await reset_service.reset(
                    session,
                    settings,
                    include_history=args.include_history,
                    include_runs=args.include_runs,
                    keep_models=args.keep_models,
                )
                after = await summary(session, settings)
                remaining = await reset_service.inspect(
                    session,
                    include_history=args.include_history,
                    include_runs=args.include_runs,
                    keep_models=args.keep_models,
                )
                await session.commit()
                print("reset-paper executed")
                _print_reset_counts("  deleted:", deleted, scoped)
                _print_reset_counts("  remaining:", remaining, reset_service.ALL_TABLES)
                print(f"  bankroll: {before.bankroll:.2f} -> {after.bankroll:.2f}")
                if not args.keep_models:
                    _print_artifact_note(settings)
            except Exception as exc:
                await session.rollback()
                raise SystemExit(f"reset-paper failed: {exc}") from exc
    finally:
        await db.dispose()


async def _run_reset_shadow(args: argparse.Namespace) -> None:
    settings = get_settings()
    db = Database(settings.database_url)
    try:
        async with db.session_factory() as session:
            try:
                counts = await reset_service.inspect(session)
                count = counts.get("shadow_ledger_bets", 0)
                if not args.yes:
                    print(
                        f"reset-shadow plan (dry-run): {count} shadow ledger bet(s)"
                    )
                    print("nothing deleted; pass --yes to execute")
                    return
                deleted = await reset_service.reset_shadow(session)
                await session.commit()
                print(f"reset-shadow executed: {deleted} shadow ledger bet(s) deleted")
            except Exception as exc:
                await session.rollback()
                raise SystemExit(f"reset-shadow failed: {exc}") from exc
    finally:
        await db.dispose()


def _parse_iso(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


async def _run_backtest(args: argparse.Namespace) -> None:
    """Read-only backtest: no commit, no writes, no migrations."""
    settings = get_settings()
    db = Database(settings.database_url)
    try:
        async with db.session_factory() as session:
            report = await run_backtest(
                session,
                settings,
                months=args.months,
                target=args.target,
                since=_parse_iso(args.since),
                until=_parse_iso(args.until),
            )
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print(format_report(report))
    except ValueError as exc:
        raise SystemExit(f"backtest failed: {exc}") from exc
    finally:
        await db.dispose()


def main(argv: list[str] | None = None) -> None:
    configure_logging(get_settings().log_level)
    parser = argparse.ArgumentParser(prog="app.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    backfill_parser = subparsers.add_parser("backfill", help="Bulk-load football-data.co.uk history")
    backfill_parser.add_argument("--from", dest="year_from", type=int, required=True)
    backfill_parser.add_argument("--to", dest="year_to", type=int, default=datetime.now(UTC).year)
    backfill_parser.add_argument(
        "--divisions",
        type=lambda value: [part.strip() for part in value.split(",") if part.strip()],
        default=DEFAULT_DIVISIONS,
    )

    subparsers.add_parser("seed-leagues", help="Insert whitelisted leagues")
    subparsers.add_parser("retrain", help="Train a challenger now and promote it if it passes the gate")
    subparsers.add_parser("predict", help="Run the champion prediction pass now")
    subparsers.add_parser("ledger", help="Run the paper-ledger settle+place pass now")
    subparsers.add_parser(
        "shadow-ledger", help="Run the shadow-ledger settle+place pass now"
    )
    subparsers.add_parser(
        "agent-evaluate", help="Run one deterministic risk-agent pass (paper/audit only)"
    )
    agent_abc_parser = subparsers.add_parser(
        "agent-abc",
        help="Run one T-30 A+B+C pass and place abc paper bets (lineups-only B)",
    )
    agent_abc_parser.add_argument(
        "--window-minutes",
        type=int,
        default=45,
        help="Only evaluate matches kicking off within this many minutes (default 45)",
    )
    agent_ledger_parser = subparsers.add_parser(
        "agent-ledger",
        help="Settle and place the paper-only agent ledger for one variant",
    )
    agent_ledger_parser.add_argument(
        "--variant", choices=("a_only", "abc"), default="a_only"
    )

    reset_shadow_parser = subparsers.add_parser(
        "reset-shadow",
        help="Delete shadow ledger bets (dry-run unless --yes)",
    )
    reset_shadow_parser.add_argument(
        "--yes", action="store_true", help="Execute the reset"
    )

    reset_parser = subparsers.add_parser(
        "reset-paper",
        help="Reset paper/shadow ledger state (dry-run unless --yes)",
    )
    reset_parser.add_argument(
        "--dry-run", action="store_true", help="Print the plan only (default)"
    )
    reset_parser.add_argument("--yes", action="store_true", help="Execute the reset")
    reset_parser.add_argument(
        "--keep-models", action="store_true", help="Keep model_versions and artifacts"
    )
    reset_parser.add_argument(
        "--include-runs", action="store_true", help="Also delete ingestion_runs"
    )
    reset_parser.add_argument(
        "--include-history",
        action="store_true",
        help="Also delete odds_snapshots, results, and matches",
    )
    reset_parser.add_argument(
        "--backup", metavar="PATH", default=None, help="Run pg_dump to PATH before deleting"
    )

    backtest_parser = subparsers.add_parser(
        "backtest", help="Read-only backtest of the deployed 1x2 rule"
    )
    backtest_parser.add_argument("--months", type=int, default=24)
    backtest_parser.add_argument("--target", default="1x2")
    backtest_parser.add_argument("--since", default=None, help="ISO date/datetime lower bound")
    backtest_parser.add_argument("--until", default=None, help="ISO date/datetime upper bound")
    backtest_parser.add_argument("--json", action="store_true", help="Print JSON only")

    args = parser.parse_args(argv)
    if args.command == "backfill":
        asyncio.run(_run_backfill(args))
    elif args.command == "seed-leagues":
        asyncio.run(_run_seed_leagues())
    elif args.command == "retrain":
        asyncio.run(_run_retrain())
    elif args.command == "predict":
        asyncio.run(_run_predict())
    elif args.command == "ledger":
        asyncio.run(_run_ledger())
    elif args.command == "shadow-ledger":
        asyncio.run(_run_shadow_ledger())
    elif args.command == "agent-evaluate":
        asyncio.run(_run_agent_evaluate())
    elif args.command == "agent-abc":
        asyncio.run(_run_agent_abc(args))
    elif args.command == "agent-ledger":
        asyncio.run(_run_agent_ledger(args))
    elif args.command == "reset-shadow":
        asyncio.run(_run_reset_shadow(args))
    elif args.command == "reset-paper":
        asyncio.run(_run_reset_paper(args))
    elif args.command == "backtest":
        asyncio.run(_run_backtest(args))


if __name__ == "__main__":
    main()
