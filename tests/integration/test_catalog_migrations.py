"""The migration and the SQLAlchemy models must describe the same tables, and be reversible."""

import asyncio
from collections.abc import Awaitable, Callable

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from pharmavique.catalog.infrastructure.persistence.models import SCHEMA, Base

pytestmark = pytest.mark.integration


async def _tables_and_columns(engine: AsyncEngine) -> dict[str, set[str]]:
    def read(connection: object) -> dict[str, set[str]]:
        inspector = inspect(connection)
        return {
            table: {column["name"] for column in inspector.get_columns(table, schema=SCHEMA)}
            for table in inspector.get_table_names(schema=SCHEMA)
        }

    async with engine.connect() as connection:
        return await connection.run_sync(read)


async def test_the_migrated_database_matches_the_models(engine: AsyncEngine) -> None:
    expected = {
        table.name: {c.name for c in table.columns} for table in Base.metadata.tables.values()
    }

    assert await _tables_and_columns(engine) == expected


async def test_the_partial_outbox_index_exists(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        rows = await connection.execute(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE schemaname = 'catalog' AND tablename = 'outbox'"
            )
        )
        definitions = [row[0] for row in rows]

    assert any("published_at IS NULL" in definition for definition in definitions)


async def test_a_second_upgrade_changes_nothing(
    migrated_url: URL, make_alembic_config: Callable[[URL], Config]
) -> None:
    await asyncio.to_thread(command.upgrade, make_alembic_config(migrated_url), "heads")


async def test_the_migration_can_be_undone_and_redone(
    fresh_database: Callable[[str], Awaitable[URL]],
    make_alembic_config: Callable[[URL], Config],
) -> None:
    url = await fresh_database("pharmavique_it_migrations")
    config = make_alembic_config(url)
    await asyncio.to_thread(command.upgrade, config, "heads")
    await asyncio.to_thread(command.downgrade, config, "base")

    engine = create_async_engine(url.render_as_string(hide_password=False))
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text(
                    "SELECT count(*) FROM information_schema.schemata WHERE schema_name = 'catalog'"
                )
            )
            assert result.scalar_one() == 0
    finally:
        await engine.dispose()

    await asyncio.to_thread(command.upgrade, config, "heads")
