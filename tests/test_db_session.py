from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UtcDateTime
from app.db.session import Database


class _Stamp(Base):
    __tablename__ = "stamps"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)


async def test_database_roundtrip_returns_aware_utc(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    try:
        async with db.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with db.session_factory() as session:
            session.add(_Stamp(at=datetime(2026, 10, 12, 12, 0, tzinfo=UTC)))
            await session.commit()
        async with db.session_factory() as session:
            row = (await session.execute(select(_Stamp))).scalar_one()
            assert row.at == datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
            assert row.at.tzinfo is not None
    finally:
        await db.dispose()


async def test_utc_datetime_normalizes_naive_input(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    try:
        async with db.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with db.session_factory() as session:
            session.add(_Stamp(at=datetime(2026, 10, 12, 12, 0)))
            await session.commit()
        async with db.session_factory() as session:
            row = (await session.execute(select(_Stamp))).scalar_one()
            assert row.at == datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
    finally:
        await db.dispose()
