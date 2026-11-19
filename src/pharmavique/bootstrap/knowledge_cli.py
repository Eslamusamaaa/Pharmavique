"""Build the knowledge chunks (ADR-006) from the stored official SFDA lists.

knowledge-build   read data/lists/<list>/<run>/ (records, detail pages, document texts), cut each
                  row into cited chunks and replace that list's chunks in Postgres (safe to repeat)
"""

import argparse
import sys
from pathlib import Path
from typing import Any

from pharmavique.bootstrap.ai import build_embedder
from pharmavique.bootstrap.settings import get_settings
from pharmavique.foundation.db.engine import create_engine, create_session_factory
from pharmavique.knowledge.application.build_chunks import BuildChunks
from pharmavique.knowledge.application.embed_chunks import EmbedChunks
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
            report = await use_case.run(name)
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
