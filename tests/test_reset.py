"""Tests for the scoped, dry-run-first paper-ledger reset."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.cli import main
from app.config import Settings
from app.db.base import Base
from app.db.models import (
    ClvRecord,
    IngestionRun,
    LedgerBet,
    Match,
    MatchFeature,
    ModelVersion,
    OddsSnapshot,
    Prediction,
    Result,
)
from app.db.session import Database
from app.services.ledger import summary
from app.services.reset import reset
from tests.ml_helpers import make_db, seed_context, seed_finished_match, seed_team

KICKOFF = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
SETTINGS = Settings.model_construct()


async def _seed(db: Database) -> None:
    async with db.session_factory() as session:
        league, season = await seed_context(session)
        home = await seed_team(session, "Home")
        away = await seed_team(session, "Away")
        match = await seed_finished_match(
            session,
            league,
            season,
            home,
            away,
            match_id_label="M1",
            kickoff=KICKOFF,
            home_score=2,
            away_score=1,
            had_payload={"lines": []},
        )
        version = ModelVersion(
            target="1x2",
            algorithm="lightgbm",
            params={},
            metrics={},
            artifact_path="/tmp/m1.joblib",
            status="champion",
        )
        session.add(version)
        await session.flush()
        prediction = Prediction(
            match_id=match.id,
            target="1x2",
            outcome="H",
            model_version_id=version.id,
            prob=0.5,
            fair_odds=2.0,
        )
        session.add(prediction)
        await session.flush()
        session.add(
            ClvRecord(
                prediction_id=prediction.id,
                match_id=match.id,
                model_version_id=version.id,
                target="1x2",
                outcome="H",
                model_prob=0.5,
                closing_prob=0.48,
                closing_odds=2.1,
                edge=0.02,
                beat=True,
                is_value=True,
                source="hkjc",
            )
        )
        session.add(MatchFeature(match_id=match.id, feature_version="v1", features={}))
        session.add(
            LedgerBet(
                match_id=match.id,
                target="1x2",
                outcome="H",
                model_version_id=version.id,
                odds=2.1,
                stake=15.0,
                bankroll_at_place=1000.0,
                kelly_multiplier=0.5,
                status="won",
                payout=31.5,
                profit=16.5,
            )
        )
        session.add(IngestionRun(job="test", started_at=KICKOFF, status="success"))
        await session.commit()


async def _count(db: Database, model: type[Base]) -> int:
    async with db.session_factory() as session:
        stmt = select(func.count()).select_from(model)
        return int((await session.execute(stmt)).scalar_one())


async def _run_reset(db: Database, **kwargs: bool) -> dict[str, int]:
    async with db.session_factory() as session:
        deleted = await reset(session, SETTINGS, **kwargs)
        await session.commit()
    return deleted


def _patch_cli(monkeypatch: pytest.MonkeyPatch, db: Database) -> None:
    monkeypatch.setattr("app.cli.Database", lambda _url: db)
    monkeypatch.setattr("app.cli.get_settings", lambda: SETTINGS)


def test_cli_default_is_dry_run_and_deletes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = asyncio.run(make_db(tmp_path))
    try:
        asyncio.run(_seed(db))
        _patch_cli(monkeypatch, db)
        main(["reset-paper"])
        out = capsys.readouterr().out
        assert "reset-paper plan (dry-run)" in out
        assert "would delete:" in out
        assert "ledger_bets: 1" in out
        assert "predictions: 1" in out
        assert "nothing deleted; pass --yes to execute" in out
        assert asyncio.run(_count(db, LedgerBet)) == 1
        assert asyncio.run(_count(db, Prediction)) == 1
        assert asyncio.run(_count(db, Match)) == 1
    finally:
        asyncio.run(db.dispose())


def test_cli_yes_executes_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = asyncio.run(make_db(tmp_path))
    try:
        asyncio.run(_seed(db))
        _patch_cli(monkeypatch, db)
        main(["reset-paper", "--yes"])
        out = capsys.readouterr().out
        assert "reset-paper executed" in out
        assert asyncio.run(_count(db, LedgerBet)) == 0
        assert asyncio.run(_count(db, Prediction)) == 0
        assert asyncio.run(_count(db, Match)) == 1
    finally:
        asyncio.run(db.dispose())


async def test_default_reset_deletes_ml_and_bet_state_but_keeps_history(
    tmp_path: Path,
) -> None:
    db = await make_db(tmp_path)
    try:
        await _seed(db)
        deleted = await _run_reset(
            db, include_history=False, include_runs=False, keep_models=False
        )
        assert deleted == {
            "clv_records": 1,
            "ledger_bets": 1,
            "predictions": 1,
            "match_features": 1,
            "model_versions": 1,
        }
        for model in (ClvRecord, LedgerBet, Prediction, MatchFeature, ModelVersion):
            assert await _count(db, model) == 0
        for model in (Match, Result, OddsSnapshot, IngestionRun):
            assert await _count(db, model) == 1
    finally:
        await db.dispose()


async def test_keep_models_preserves_model_versions(tmp_path: Path) -> None:
    db = await make_db(tmp_path)
    try:
        await _seed(db)
        deleted = await _run_reset(
            db, include_history=False, include_runs=False, keep_models=True
        )
        assert "model_versions" not in deleted
        assert await _count(db, ModelVersion) == 1
        for model in (Prediction, LedgerBet, MatchFeature):
            assert await _count(db, model) == 0
    finally:
        await db.dispose()


async def test_include_history_deletes_matches_results_and_odds(tmp_path: Path) -> None:
    db = await make_db(tmp_path)
    try:
        await _seed(db)
        deleted = await _run_reset(
            db, include_history=True, include_runs=False, keep_models=False
        )
        assert deleted["odds_snapshots"] == 1
        assert deleted["results"] == 1
        assert deleted["matches"] == 1
        assert await _count(db, OddsSnapshot) == 0
        assert await _count(db, Result) == 0
        assert await _count(db, Match) == 0
        assert await _count(db, IngestionRun) == 1
    finally:
        await db.dispose()


async def test_include_runs_deletes_ingestion_runs(tmp_path: Path) -> None:
    db = await make_db(tmp_path)
    try:
        await _seed(db)
        deleted = await _run_reset(
            db, include_history=False, include_runs=True, keep_models=False
        )
        assert deleted["ingestion_runs"] == 1
        assert await _count(db, IngestionRun) == 0
        assert await _count(db, Match) == 1
    finally:
        await db.dispose()


async def test_bankroll_resets_to_initial_after_bets_deleted(tmp_path: Path) -> None:
    db = await make_db(tmp_path)
    try:
        await _seed(db)
        async with db.session_factory() as session:
            before = await summary(session, SETTINGS)
        assert before.bankroll == pytest.approx(1016.5)
        await _run_reset(db, include_history=False, include_runs=False, keep_models=False)
        async with db.session_factory() as session:
            after = await summary(session, SETTINGS)
        assert after.bankroll == pytest.approx(SETTINGS.ledger_initial_bankroll)
        assert after.n_bets == 0
    finally:
        await db.dispose()


async def test_reset_is_idempotent(tmp_path: Path) -> None:
    db = await make_db(tmp_path)
    try:
        await _seed(db)
        first = await _run_reset(
            db, include_history=False, include_runs=False, keep_models=False
        )
        second = await _run_reset(
            db, include_history=False, include_runs=False, keep_models=False
        )
        assert first["ledger_bets"] == 1
        assert second["ledger_bets"] == 0
        assert second["predictions"] == 0
        assert second["model_versions"] == 0
    finally:
        await db.dispose()


def test_backup_failure_aborts_without_deleting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = asyncio.run(make_db(tmp_path))
    try:
        asyncio.run(_seed(db))
        _patch_cli(monkeypatch, db)

        def _fail(*_args: object, **_kwargs: object) -> None:
            raise FileNotFoundError("pg_dump")

        monkeypatch.setattr("app.services.reset.subprocess.run", _fail)
        with pytest.raises(SystemExit) as excinfo:
            main(["reset-paper", "--yes", "--backup", str(tmp_path / "backup.sql")])
        assert "pg_dump" in str(excinfo.value)
        assert asyncio.run(_count(db, LedgerBet)) == 1
        assert asyncio.run(_count(db, Prediction)) == 1
        assert asyncio.run(_count(db, Match)) == 1
    finally:
        asyncio.run(db.dispose())
