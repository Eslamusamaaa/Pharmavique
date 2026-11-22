"""Build the knowledge chunks (ADR-006) from the stored official SFDA lists.

knowledge-build   read data/lists/<list>/<run>/ (records, detail pages, document texts), cut each
                  row into cited chunks and replace that list's chunks in Postgres (safe to repeat);
                  with --additive it only adds, for a run that holds just the new rows
knowledge-new-rows  from a daily list run, write a small run with only the rows that have no chunks
                  yet, so their documents can be fetched and added without touching the rest
"""

import argparse
import sys
from pathlib import Path
from typing import Any

from pharmavique.bootstrap.ai import build_embedder
from pharmavique.bootstrap.settings import get_settings
from pharmavique.foundation.db.engine import create_engine, create_session_factory
from pharmavique.ingestion.infrastructure.connectors.sfda_web.store import SnapshotStore
from pharmavique.knowledge.application.build_chunks import BuildChunks
from pharmavique.knowledge.application.embed_chunks import EmbedChunks
from pharmavique.knowledge.application.new_rows import new_rows
from pharmavique.knowledge.infrastructure.list_documents import StoredListDocuments
from pharmavique.knowledge.infrastructure.postgres import PostgresChunkStore, PostgresChunkVectors

EXIT_OK = 0
EXIT_NO_DATABASE = 4

# Lists whose text the assistant may quote (owner's phase 2 scope, 2026-11-18).
KNOWLEDGE_LISTS = ("dhpc", "safety-alert", "drugs-circulars", "rmm", "safety-labeling")


def add_arguments(commands: Any) -> None:
    build = commands.add_parser(
        "knowledge-build",
        help="cut stored official SFDA documents into cited chunks in Postgres (safe to repeat)",
    )
    build.add_argument("--lists", help="comma separated list names (default: the knowledge lists)")
    build.add_argument("--run-id", default="lists-1")
    build.add_argument("--root", default="data/lists")
    build.add_argument(
        "--additive",
        action="store_true",
        help="add the run's chunks and keep every other chunk (the run holds only new rows)",
    )

    rows = commands.add_parser(
        "knowledge-new-rows",
        help="write a run with only the rows of a daily list run that have no chunks yet",
    )
    rows.add_argument("--lists", help="comma separated list names (default: the knowledge lists)")
    rows.add_argument("--run-id", required=True, help="the daily list run to read")
    rows.add_argument("--into", required=True, help="the run to write, for example know-20261122")
    rows.add_argument("--root", default="data/lists")

    embed = commands.add_parser(
        "knowledge-embed",
        help="give every knowledge chunk a vector from the embedding model (safe to repeat)",
    )
    embed.add_argument("--batch-size", type=int, default=32)
    embed.add_argument("--limit", type=int, help="embed at most N chunks (for a trial)")


async def build(args: argparse.Namespace) -> int:
    secret = get_settings().database_url
    if secret is None:
        print(
            "set PHARMAVIQUE_DATABASE_URL (see .env.example) and run `alembic upgrade heads` first",
            file=sys.stderr,
        )
        return EXIT_NO_DATABASE
    names = args.lists.split(",") if args.lists else list(KNOWLEDGE_LISTS)
    engine = create_engine(secret.get_secret_value())
    try:
        use_case = BuildChunks(
            StoredListDocuments(Path(args.root), args.run_id),
            PostgresChunkStore(create_session_factory(engine)),
        )
        for name in names:
            report = await (use_case.run_additive(name) if args.additive else use_case.run(name))
            print(
                f"{name}: {report.documents} documents, {report.chunks} chunks "
                f"({report.ocr_chunks} from OCR), {report.empty} without text"
            )
    finally:
        await engine.dispose()
    return EXIT_OK


async def embed(args: argparse.Namespace) -> int:
    settings = get_settings()
    if settings.database_url is None:
        print("set PHARMAVIQUE_DATABASE_URL first", file=sys.stderr)
        return EXIT_NO_DATABASE
    embedder = build_embedder(settings)
    if embedder is None:
        print("set PHARMAVIQUE_OPENROUTER_API_KEY to embed", file=sys.stderr)
        return EXIT_NO_DATABASE
    engine = create_engine(settings.database_url.get_secret_value())
    try:
        vectors = PostgresChunkVectors(create_session_factory(engine))
        report = await EmbedChunks(vectors, embedder, args.batch_size).run(args.limit)
    finally:
        await engine.dispose()
    stopped = f" (stopped: {report.stopped_by})" if report.stopped_by else ""
    print(f"{report.model}: {report.embedded} chunks embedded{stopped}")
    return EXIT_OK if report.stopped_by is None else EXIT_NO_DATABASE


def _keys_of_earlier_runs(root: Path, name: str, skip: str) -> set[str]:
    """Rows of the baseline run and of every earlier new-rows run: they were already handled, also
    when their document gave no text and so left no chunk."""
    keys: set[str] = set()
    folder = root / name
    if not folder.is_dir():
        return keys
    for run in folder.iterdir():
        if (
            run.is_dir()
            and run.name != skip
            and (run.name == "lists-1" or run.name.startswith("know-"))
        ):
            keys.update(str(r["key"]) for r in SnapshotStore(folder, run.name).read_records())
    return keys


async def new_rows_run(args: argparse.Namespace) -> int:
    secret = get_settings().database_url
    if secret is None:
        print("set PHARMAVIQUE_DATABASE_URL first", file=sys.stderr)
        return EXIT_NO_DATABASE
    names = args.lists.split(",") if args.lists else list(KNOWLEDGE_LISTS)
    root = Path(args.root)
    engine = create_engine(secret.get_secret_value())
    total = 0
    try:
        store = PostgresChunkStore(create_session_factory(engine))
        for name in names:
            daily = SnapshotStore(root / name, args.run_id).read_records()
            known = await store.row_keys(name) | _keys_of_earlier_runs(root, name, args.into)
            fresh = new_rows(daily, known)
            if fresh:
                SnapshotStore(root / name, args.into).write_records(fresh)
            total += len(fresh)
            print(f"{name}: {len(fresh)} new of {len(daily)} rows")
    finally:
        await engine.dispose()
    print(f"total new rows: {total}")
    return EXIT_OK
