"""Load the stored official SFDA lists into the catalog and link them to products.

sfda-lists-load   read data/lists/<list>/<run>/records.jsonl and replace that list in Postgres
                  (safe to repeat), then print how many rows linked to a drug and how surely
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from pharmavique.bootstrap.settings import get_settings
from pharmavique.catalog.application.list_loading import (
    ListLoadReport,
    LoadSourceList,
    SourceListRow,
)
from pharmavique.catalog.infrastructure.persistence.source_lists import SqlAlchemySourceListStore
from pharmavique.foundation.db.engine import create_engine, create_session_factory

EXIT_OK = 0
EXIT_NO_DATABASE = 4

# The lists the product uses (owner's decision, 2026-11-18).
PRODUCT_LISTS = (
    "safety-labeling",
    "safety-alert",
    "drug-shortage",
    "drug-shortage-resolved",
    "drug-approvals",
    "drug-companies",
    "pharmacies",
)


def add_arguments(commands: Any) -> None:
    load = commands.add_parser(
        "sfda-lists-load",
        help="load stored SFDA lists into the catalog and link them to drugs (safe to repeat)",
    )
    load.add_argument(
        "--lists", help="comma separated list names (default: the six the product uses)"
    )
    load.add_argument("--run-id", default="lists-1")
    load.add_argument("--root", default="data/lists")


def read_details(run_dir: Path) -> dict[str, tuple[tuple[str, str], ...]]:
    """What was fetched behind a list's rows: detail pages (`details.jsonl`) and the text of
    downloaded documents (`texts.jsonl`, as a `Document text` pair). Empty when nothing was."""
    found: dict[str, tuple[tuple[str, str], ...]] = {}
    details = run_dir / "details.jsonl"
    if details.exists():
        for line in details.read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                found[record["key"]] = tuple((d["label"], d["value"]) for d in record["detail"])
    texts = run_dir / "texts.jsonl"
    if texts.exists():
        for line in texts.read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                pairs = (("Document text", record["text"]), ("Document", record["source_ref"]))
                found[record["key"]] = found.get(record["key"], ()) + pairs
    return found


def read_rows(path: Path) -> list[SourceListRow]:
    details = read_details(path.parent)
    rows: list[SourceListRow] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        provenance = record["provenance"]
        fetched = provenance.get("fetched_at")
        rows.append(
            SourceListRow(
                key=record["key"],
                entity_key=record["entity_key"],
                link=record.get("link"),
                cells=tuple((cell["label"], cell["value"]) for cell in record["list"]),
                list_page=record["list_page"],
                source=provenance["source"],
                source_ref=provenance["source_ref"],
                snapshot_id=provenance["snapshot_id"],
                fetched_at=datetime.fromisoformat(fetched) if fetched else None,
                trust=provenance["trust"],
                detail=details.get(record["key"], ()),
            )
        )
    return rows


def describe(report: ListLoadReport) -> str:
    return (
        f"{report.list_name}: {report.rows} rows, {report.rows_with_links} linked to drugs "
        f"(matched links {report.matched_links}, possible links {report.possible_links})"
    )


async def load(args: argparse.Namespace) -> int:
    secret = get_settings().database_url
    if secret is None:
        print(
            "set PHARMAVIQUE_DATABASE_URL (see .env.example) and run `alembic upgrade heads` first",
            file=sys.stderr,
        )
        return EXIT_NO_DATABASE
    names = args.lists.split(",") if args.lists else list(PRODUCT_LISTS)
    engine = create_engine(secret.get_secret_value())
    try:
        loader = LoadSourceList(SqlAlchemySourceListStore(create_session_factory(engine)))
        for name in names:
            path = Path(args.root) / name / args.run_id / "records.jsonl"
            if not path.exists():
                print(f"{name}: no stored records at {path}", file=sys.stderr)
                continue
            print(describe(await loader.run(name, read_rows(path))))
    finally:
        await engine.dispose()
    return EXIT_OK
