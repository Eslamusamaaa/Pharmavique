"""Read-only count of what migration catalog_0006 would delete (nothing is written).

PHARMAVIQUE_DATABASE_URL=... uv run python scripts/db_damage_report.py
"""

# ruff: noqa: S608 (table and column names come from the constants above, never from input)
import asyncio

from sqlalchemy import text

from pharmavique.bootstrap.settings import get_settings
from pharmavique.foundation.db.engine import create_engine

KEYS = {
    "products": "market, register_number",
    "price_history": "id",
    "outbox": "id",
    "source_list_rows": "list_name, row_key",
    "source_list_links": "list_name, row_key, market, register_number",
    "product_pictures": "market, register_number",
}
ORPHANS = {
    "price_history -> products": (
        "catalog.price_history c", "catalog.products p", "p.market = c.market"
        " AND p.register_number = c.register_number"
    ),
    "product_pictures -> products": (
        "catalog.product_pictures c", "catalog.products p", "p.market = c.market"
        " AND p.register_number = c.register_number"
    ),
    "links -> rows": (
        "catalog.source_list_links c", "catalog.source_list_rows p", "p.list_name = c.list_name"
        " AND p.row_key = c.row_key"
    ),
    "links -> products": (
        "catalog.source_list_links c", "catalog.products p", "p.market = c.market"
        " AND p.register_number = c.register_number"
    ),
}  # fmt: skip


async def main() -> None:
    secret = get_settings().database_url
    assert secret is not None  # noqa: S101
    engine = create_engine(secret.get_secret_value())
    async with engine.connect() as conn:
        for table, columns in KEYS.items():
            total = (await conn.execute(text(f"select count(*) from catalog.{table}"))).scalar_one()
            distinct = (
                await conn.execute(
                    text(
                        f"select count(*) from (select 1 from catalog.{table} group by {columns}) d"
                    )
                )
            ).scalar()
            print(
                f"{table}: {total} rows, {distinct} distinct keys, extra copies {total - distinct}"
            )
        for name, (child, parent, condition) in ORPHANS.items():
            count = (
                await conn.execute(
                    text(
                        f"select count(*) from {child} where not exists"
                        f" (select 1 from {parent} where {condition})"
                    )
                )
            ).scalar()
            print(f"orphans {name}: {count}")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
