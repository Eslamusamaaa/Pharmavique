"""Fixtures for tests that need the real Postgres from docker compose.

They read PHARMAVIQUE_DATABASE_URL (from the environment or the git-ignored .env) and create
throwaway databases next to it, so the development database is never touched. When no database
is configured or reachable, the tests are skipped with a clear reason.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from pharmavique.bootstrap.settings import Settings
from pharmavique.foundation.db.engine import create_engine, create_session_factory

ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE = "pharmavique_it"


def _configured_url() -> URL:
    secret = Settings().database_url
    if secret is None:
        pytest.skip("PHARMAVIQUE_DATABASE_URL is not set (copy .env.example to .env)")
    return make_url(secret.get_secret_value())


async def _recreate(admin_url: URL, name: str) -> None:
    admin = create_async_engine(admin_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as connection:
            await connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
            await connection.execute(text(f'CREATE DATABASE "{name}"'))
    except OSError as error:
        pytest.skip(f"Postgres is not reachable ({error}); run `docker compose up -d db`")
    finally:
        await admin.dispose()


def alembic_config(url: URL) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    rendered = url.render_as_string(hide_password=False).replace("%", "%%")
    config.set_main_option("sqlalchemy.url", rendered)
    return config


@pytest.fixture(scope="session")
def make_alembic_config() -> Callable[[URL], Config]:
    return alembic_config


@pytest.fixture(scope="session")
def fresh_database() -> Callable[[str], Awaitable[URL]]:
    """Returns an async function that makes an empty database and returns its URL."""
    base = _configured_url()

    async def make(name: str) -> URL:
        await _recreate(base, name)
        return base.set(database=name)

    return make


@pytest.fixture(scope="session")
def migrated_url() -> URL:
    base = _configured_url()
    asyncio.run(_recreate(base, TEST_DATABASE))
    url = base.set(database=TEST_DATABASE)
    command.upgrade(alembic_config(url), "heads")
    return url


@pytest.fixture
async def engine(migrated_url: URL) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(migrated_url.render_as_string(hide_password=False))
    async with engine.begin() as connection:
        await connection.execute(
            text("TRUNCATE catalog.outbox, catalog.price_history, catalog.products CASCADE")
        )
    yield engine
    await engine.dispose()


@pytest.fixture
async def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(engine)
