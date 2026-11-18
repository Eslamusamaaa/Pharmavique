"""Load the picture mapping (data/media/mapping.jsonl) into the catalog database.

sfda-pictures-load   one row per drug: a real shop picture, or a generated card marked as such
                     (safe to repeat; replaces the market's pictures)
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from pharmavique.bootstrap.settings import get_settings
from pharmavique.catalog.infrastructure.persistence.pictures import SqlAlchemyPictureStore
from pharmavique.foundation.db.engine import create_engine, create_session_factory

EXIT_OK = 0
EXIT_NO_DATABASE = 4
EXIT_NO_INPUT = 3


def add_arguments(commands: Any) -> None:
    load = commands.add_parser(
        "sfda-pictures-load", help="load the picture of every drug into the catalog database"
    )
    load.add_argument("--mapping", default="data/media/mapping.jsonl")
    load.add_argument("--market", default="SA")


def _read_mapping(path: Path) -> list[dict[str, Any]] | None:
    if not path.is_file():
        return None
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


async def load(args: argparse.Namespace) -> int:
    secret = get_settings().database_url
    if secret is None:
        print(
            "set PHARMAVIQUE_DATABASE_URL (see .env.example) and run `alembic upgrade heads` first",
            file=sys.stderr,
        )
        return EXIT_NO_DATABASE
    rows = _read_mapping(Path(args.mapping))
    if rows is None:
        print(
            f"no mapping at {args.mapping}: run `pharmavique sfda-images-map` first",
            file=sys.stderr,
        )
        return EXIT_NO_INPUT
    engine = create_engine(secret.get_secret_value())
    try:
        stored = await SqlAlchemyPictureStore(create_session_factory(engine)).replace_all(
            args.market, rows
        )
    finally:
        await engine.dispose()
    kinds: dict[str, int] = {}
    for row in rows:
        kinds[row["picture_kind"]] = kinds.get(row["picture_kind"], 0) + 1
    print(f"{len(rows)} drugs in the mapping, {stored} stored (in the catalog); {kinds}")
    return EXIT_OK
