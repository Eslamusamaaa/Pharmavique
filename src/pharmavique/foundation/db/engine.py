"""Async SQLAlchemy engine and session factory."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine(
    url: str, *, echo: bool = False, pool_size: int = 5, max_overflow: int = 10
) -> AsyncEngine:
    return create_async_engine(
        url, echo=echo, pool_pre_ping=True, pool_size=pool_size, max_overflow=max_overflow
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # expire_on_commit=False: objects stay readable after the transaction ends
    return async_sessionmaker(engine, expire_on_commit=False)


async def ping_database(engine: AsyncEngine) -> None:
    """One trivial query; raises when the database cannot be reached."""
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
