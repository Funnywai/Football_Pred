import asyncio

from sqlalchemy import select

from app.cli import main
from app.config import Settings
from app.db.base import Base
from app.db.models import IngestionRun
from app.db.session import Database


def _make_db(tmp_path) -> Database:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'cli.db'}")

    async def _create() -> None:
        async with db.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create())
    return db


def _patch_cli(monkeypatch, db: Database) -> None:
    monkeypatch.setattr("app.cli.Database", lambda url: db)
    monkeypatch.setattr("app.cli.get_settings", lambda: Settings(_env_file=None))


def _jobs(db: Database) -> list[str]:
    async def _query() -> list[str]:
        async with db.session_factory() as session:
            rows = (await session.execute(select(IngestionRun))).scalars().all()
            return [row.job for row in rows]

    return asyncio.run(_query())


def test_cli_predict_without_champion_is_noop(tmp_path, monkeypatch, capsys):
    db = _make_db(tmp_path)
    try:
        _patch_cli(monkeypatch, db)
        main(["predict"])
        assert "predict complete: 0 prediction(s) written" in capsys.readouterr().out
        assert _jobs(db) == ["ml_predict"]
    finally:
        asyncio.run(db.dispose())


def test_cli_retrain_without_history_is_noop(tmp_path, monkeypatch, capsys):
    db = _make_db(tmp_path)
    try:
        _patch_cli(monkeypatch, db)
        main(["retrain"])
        assert "retrain complete: 0 champion(s) promoted" in capsys.readouterr().out
        assert _jobs(db) == ["ml_retrain"]
    finally:
        asyncio.run(db.dispose())


def test_cli_ledger_without_bets_is_noop(tmp_path, monkeypatch, capsys):
    db = _make_db(tmp_path)
    try:
        _patch_cli(monkeypatch, db)
        main(["ledger"])
        assert "ledger complete: 0 bet(s) settled or placed" in capsys.readouterr().out
        assert _jobs(db) == ["ledger_update"]
    finally:
        asyncio.run(db.dispose())
