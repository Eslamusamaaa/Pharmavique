"""Compare a restored database with the one it was restored from (read-only, nothing is written).

    uv run python scripts/restore_drill.py "<production direct address>" "<restored branch address>"

Prints, per table in the product schemas, the row count on each side and whether they match, then
the migration versions on each side. Used by the restore drill in docs/RUNBOOK.md. Exits 1 when a
table or the migration versions differ. Row counts are exact (`count(*)`), so run it on the direct
(unpooled) addresses and expect a few seconds per large table.
"""

import asyncio
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from pharmavique.foundation.db.engine import create_engine
from pharmavique.foundation.db.url import to_asyncpg_url

SCHEMAS = (
    "catalog",
    "search",
    "knowledge",
    "interactions",
    "identity",
    "watchlist",
    "analytics",
    "offers",
)


async def _counts(engine: AsyncEngine) -> tuple[dict[str, int], list[str]]:
    async with engine.connect() as conn:
        tables = await conn.execute(
            text(
                "select table_schema || '.' || table_name from information_schema.tables"
                " where table_schema = any(:schemas) and table_type = 'BASE TABLE' order by 1"
            ),
            {"schemas": list(SCHEMAS)},
        )
        counts: dict[str, int] = {}
        for (name,) in tables:
            schema, table = name.split(".", 1)
            # names come from the catalog query above, quoted as identifiers
            query = f'select count(*) from "{schema}"."{table}"'  # noqa: S608
            counts[name] = int((await conn.execute(text(query))).scalar_one())
        versions = await conn.execute(text("select version_num from public.alembic_version"))
        return counts, sorted(row[0] for row in versions)


async def main(source_url: str, restored_url: str) -> int:
    source = create_engine(to_asyncpg_url(source_url), pool_size=1, max_overflow=0)
    restored = create_engine(to_asyncpg_url(restored_url), pool_size=1, max_overflow=0)
    try:
        (left, left_versions), (right, right_versions) = await asyncio.gather(
            _counts(source), _counts(restored)
        )
    finally:
        await source.dispose()
        await restored.dispose()
    differences = 0
    print(f"{'table':55} {'source':>10} {'restored':>10}")
    for name in sorted(set(left) | set(right)):
        a, b = left.get(name), right.get(name)
        mark = "" if a == b else "  <- differs"
        differences += a != b
        shown = ["-" if count is None else str(count) for count in (a, b)]
        print(f"{name:55} {shown[0]:>10} {shown[1]:>10}{mark}")
    same_versions = left_versions == right_versions
    print(f"\nmigrations source:   {', '.join(left_versions)}")
    print(f"migrations restored: {', '.join(right_versions)}")
    print(f"\n{differences} table(s) differ; migrations {'match' if same_versions else 'differ'}")
    return 0 if differences == 0 and same_versions else 1


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    sys.exit(asyncio.run(main(sys.argv[1], sys.argv[2])))
