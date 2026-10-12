from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


class Database:
    """Owns the async engine and session factory for one process."""

    def __init__(self, url: str, **engine_kwargs: object) -> None:
        self.engine: AsyncEngine = create_async_engine(url, pool_pre_ping=True, **engine_kwargs)
        self.session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self.engine, expire_on_commit=False
        )

    async def dispose(self) -> None:
        await self.engine.dispose()
