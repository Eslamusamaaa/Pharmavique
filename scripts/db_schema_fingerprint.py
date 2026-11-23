"""Read-only list of every constraint and index in the product schemas (nothing is written).

    PHARMAVIQUE_DATABASE_URL=... uv run python scripts/db_schema_fingerprint.py > fingerprint.txt

Run it on a database made by `alembic upgrade heads` and on the production one, then diff the two.
"""

import asyncio

from sqlalchemy import text

from pharmavique.bootstrap.settings import get_settings
from pharmavique.foundation.db.engine import create_engine

SCHEMAS = ("catalog", "search", "knowledge", "interactions", "identity", "watchlist", "analytics")


async def main() -> None:
    secret = get_settings().database_url
    assert secret is not None  # noqa: S101
    engine = create_engine(secret.get_secret_value())
    async with engine.connect() as conn:
        constraints = await conn.execute(
            text(
                "select 'C', n.nspname || '.' || c.relname, k.conname, k.contype::text"
                " from pg_constraint k join pg_class c on c.oid = k.conrelid"
                " join pg_namespace n on n.oid = c.relnamespace"
                " where n.nspname = any(:schemas) and k.contype in ('p', 'f', 'u', 'c')"
                " order by 2, 3"
            ),
            {"schemas": list(SCHEMAS)},
        )
        for row in constraints:
            print(*row)
        indexes = await conn.execute(
            text(
                "select 'I', schemaname || '.' || tablename, indexname, ''"
                " from pg_indexes where schemaname = any(:schemas) order by 2, 3"
            ),
            {"schemas": list(SCHEMAS)},
        )
        for row in indexes:
            print(*row)
        tables = await conn.execute(
            text(
                "select 'T', table_schema || '.' || table_name, '', ''"
                " from information_schema.tables where table_schema = any(:schemas)"
                " and table_type = 'BASE TABLE' order by 2"
            ),
            {"schemas": list(SCHEMAS)},
        )
        for row in tables:
            print(*row)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
