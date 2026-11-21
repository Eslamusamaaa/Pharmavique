"""`pharmavique worker`: run background jobs (photo scans, assistant questions) from the queue.

Start as many workers as the load needs, on any machine that can reach the same Redis and database;
each runs `PHARMAVIQUE_JOB_MAX_CONCURRENCY` jobs at once. The API must run with
`PHARMAVIQUE_JOB_BACKEND=arq` to hand jobs to workers.
"""

import argparse
import sys
from typing import Any

from pharmavique.bootstrap import observability
from pharmavique.bootstrap.ai import build_assistant, build_scanner
from pharmavique.bootstrap.job_handlers import build_handlers
from pharmavique.bootstrap.settings import get_settings
from pharmavique.catalog.application.queries import ReadProductCardsHandler
from pharmavique.catalog.infrastructure.persistence.price_changes import (
    SqlAlchemyPriceChangeReader,
)
from pharmavique.catalog.infrastructure.persistence.reader import SqlAlchemyProductReader
from pharmavique.foundation.arq_jobs import make_worker
from pharmavique.foundation.db.engine import create_engine, create_session_factory
from pharmavique.foundation.jobs import JobRunner
from pharmavique.foundation.kv import RedisStore, redis_client
from pharmavique.search.application.handlers import SearchProductsHandler
from pharmavique.search.infrastructure.postgres import PostgresSearchIndex
from pharmavique.substitution.application.compare import CompareProductsHandler

EXIT_OK = 0
EXIT_NOT_CONFIGURED = 4


def add_arguments(commands: Any) -> None:
    commands.add_parser("worker", help="run background jobs (scans, assistant) from the queue")


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    if settings.database_url is None or settings.redis_url is None:
        print("set PHARMAVIQUE_DATABASE_URL and PHARMAVIQUE_REDIS_URL first", file=sys.stderr)
        return EXIT_NOT_CONFIGURED
    engine = create_engine(
        settings.database_url.get_secret_value(),
        pool_size=settings.job_max_concurrency,
        max_overflow=settings.job_max_concurrency,
    )
    store = RedisStore(redis_client(settings.redis_url.get_secret_value(), timeout=2.0))
    try:
        factory = create_session_factory(engine)
        search = SearchProductsHandler(PostgresSearchIndex(factory))
        catalog = ReadProductCardsHandler(
            SqlAlchemyProductReader(factory), SqlAlchemyPriceChangeReader(factory)
        )
        assistant = build_assistant(
            settings,
            factory,
            search=search,
            catalog=catalog,
            equivalence=CompareProductsHandler(),
            observer=observability.LoggingAssistantObserver(observability.Metrics()),
        )
        scanner = build_scanner(settings, search=search, catalog=catalog)
        handlers = build_handlers(scanner, assistant)
        if not handlers:
            print("no scan or assistant provider is configured: nothing to run", file=sys.stderr)
            return EXIT_NOT_CONFIGURED
        print(f"worker ready for: {', '.join(sorted(handlers))}")
        worker = make_worker(
            JobRunner(store, handlers),
            settings.redis_url.get_secret_value(),
            max_jobs=settings.job_max_concurrency,
            job_timeout=settings.job_timeout_seconds,
        )
        await worker.async_run()
    finally:
        await store.close()
        await engine.dispose()
    return EXIT_OK
