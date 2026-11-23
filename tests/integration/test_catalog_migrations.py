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


DAMAGE = """
ALTER TABLE catalog.source_list_links DROP CONSTRAINT fk_source_list_links_row;
ALTER TABLE catalog.source_list_links DROP CONSTRAINT fk_source_list_links_product;
ALTER TABLE catalog.price_history DROP CONSTRAINT fk_price_history_product;
ALTER TABLE catalog.product_pictures DROP CONSTRAINT fk_product_pictures_product;
ALTER TABLE catalog.source_list_links DROP CONSTRAINT source_list_links_pkey;
ALTER TABLE catalog.source_list_rows DROP CONSTRAINT source_list_rows_pkey;
ALTER TABLE catalog.product_pictures DROP CONSTRAINT product_pictures_pkey;
ALTER TABLE catalog.price_history DROP CONSTRAINT price_history_pkey;
ALTER TABLE catalog.outbox DROP CONSTRAINT outbox_pkey;
ALTER TABLE catalog.products DROP CONSTRAINT products_pkey;
DROP INDEX catalog.ix_source_list_links_product;
DROP INDEX catalog.ix_price_history_product_time;
DROP INDEX catalog.ix_outbox_unpublished;
"""

ROW = (
    "INSERT INTO catalog.source_list_rows (list_name, row_key, entity_key, cells, detail, facets,"
    " list_page, provenance_source, provenance_source_ref, provenance_snapshot_id,"
    " provenance_trust) VALUES ('drug-shortage', 'K#1', 'K', '[]', '[]', '{}', 0, 's', 'r', 'run',"
    " 'official')"
)
PRODUCT = (
    "INSERT INTO catalog.products (market, register_number, version, listing_status,"
    " status_changed_at, last_seen_at, provenance_source, provenance_source_ref,"
    " provenance_fetched_at, provenance_snapshot_id, provenance_trust, data) VALUES"
    " ('SA', '1', 1, 'listed', now(), now(), 's', 'r', now(), 'run', 'official', '{}')"
)
PRICE = (
    "INSERT INTO catalog.price_history (id, market, register_number, amount, currency_basis,"
    " effective_from, provenance_source, provenance_source_ref, provenance_fetched_at,"
    " provenance_snapshot_id, provenance_trust) VALUES (7, 'SA', '1', {amount}, 'x', now(), 's',"
    " 'r', now(), 'run', 'official')"
)
LINK = (
    "INSERT INTO catalog.source_list_links (list_name, row_key, market, register_number,"
    " confidence, reason) VALUES ('drug-shortage', '{key}', 'SA', '1', 'possible', 'x')"
)


async def test_a_database_restored_without_its_constraints_is_repaired(
    fresh_database: Callable[[str], Awaitable[URL]],
    make_alembic_config: Callable[[URL], Config],
) -> None:
    # Neon's catalog schema came out of an interrupted restore without keys and indexes: rows
    # twice, links to rows and products that are not there. The migration puts it right.
    url = await fresh_database("pharmavique_it_repair")
    config = make_alembic_config(url)
    await asyncio.to_thread(command.upgrade, config, "catalog_0005")
    engine = create_async_engine(url.render_as_string(hide_password=False))
    try:
        async with engine.begin() as connection:
            for statement in DAMAGE.strip().split(";\n"):
                if statement.strip():
                    await connection.execute(text(statement))
            await connection.execute(text(PRODUCT))
            await connection.execute(text(PRICE.format(amount=5)))
            await connection.execute(text(PRICE.format(amount=6)))  # a different price, same id
            await connection.execute(text(ROW))
            await connection.execute(text(ROW))  # the same row twice
            await connection.execute(text(LINK.format(key="K#1")))
            await connection.execute(text(LINK.format(key="gone")))  # a row that is not there
        await asyncio.to_thread(command.upgrade, config, "catalog@head")
        async with engine.connect() as connection:
            kinds = await connection.execute(
                text(
                    "SELECT conname FROM pg_constraint WHERE conrelid::regclass::text"
                    " LIKE 'catalog.%' AND contype IN ('p', 'f')"
                )
            )
            names = {row[0] for row in kinds}
            rows = await connection.execute(text("SELECT count(*) FROM catalog.source_list_rows"))
            links = await connection.execute(text("SELECT count(*) FROM catalog.source_list_links"))
            prices = await connection.execute(
                text("SELECT count(*), count(DISTINCT id) FROM catalog.price_history")
            )
            indexes = await connection.execute(
                text(
                    "SELECT indexname FROM pg_indexes WHERE schemaname = 'catalog'"
                    " AND indexname LIKE 'ix_%'"
                )
            )
            index_names = {row[0] for row in indexes}
        assert {
            "products_pkey",
            "price_history_pkey",
            "outbox_pkey",
            "source_list_rows_pkey",
            "source_list_links_pkey",
            "product_pictures_pkey",
            "fk_source_list_links_row",
            "fk_source_list_links_product",
            "fk_price_history_product",
            "fk_product_pictures_product",
        } <= names
        assert {
            "ix_source_list_links_product",
            "ix_price_history_product_time",
            "ix_outbox_unpublished",
        } <= index_names
        assert rows.scalar_one() == 1
        assert links.scalar_one() == 1  # the link to a row that is not there is gone
        assert tuple(prices.one()) == (2, 2)  # both prices kept, with different ids
    finally:
        await engine.dispose()
