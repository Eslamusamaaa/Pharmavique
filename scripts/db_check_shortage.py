"""Read-only look at how shortage rows are linked in the database (nothing is written).

PHARMAVIQUE_DATABASE_URL=... uv run python scripts/db_check_shortage.py 0207245466 1902244942
"""

import asyncio
import sys

from sqlalchemy import text

from pharmavique.bootstrap.settings import get_settings
from pharmavique.foundation.db.engine import create_engine


async def main(registers: list[str]) -> None:
    engine = create_engine(get_settings().database_url.get_secret_value())  # type: ignore[union-attr]
    async with engine.connect() as conn:
        print("delete rule of the links foreign keys:")
        rules = await conn.execute(
            text(
                "select constraint_name, delete_rule"
                " from information_schema.referential_constraints"
                " where constraint_name like 'fk_source_list_links%'"
            )
        )
        for row in rules:
            print("  ", tuple(row))
        counts = await conn.execute(
            text(
                "select list_name, confidence, count(*) from catalog.source_list_links"
                " where list_name like 'drug-shortage%' group by 1, 2 order by 1, 2"
            )
        )
        print("links by list and confidence:")
        for row in counts:
            print("  ", tuple(row))
        for register in registers:
            found = await conn.execute(
                text(
                    "select l.list_name, l.row_key, l.confidence, l.reason,"
                    " r.provenance_fetched_at, r.provenance_snapshot_id,"
                    " jsonb_array_length(r.detail)"
                    " from catalog.source_list_links l join catalog.source_list_rows r"
                    " on r.list_name = l.list_name and r.row_key = l.row_key"
                    " where l.register_number = :n and l.list_name like 'drug-shortage%'"
                ),
                {"n": register},
            )
            print(f"links of {register}:")
            for row in found:
                print("  ", tuple(row))
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
