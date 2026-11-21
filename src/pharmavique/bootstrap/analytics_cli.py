"""`pharmavique analytics-rebuild`: rebuild the company views' read model from the catalog.

The read model (`analytics.market_products`) is swapped in one transaction, so the API keeps
answering from the old rows until the new ones are complete. Run it after every catalog load; the
daily refresh does. The first run also marks the point from which the competitor radar counts.
"""

import argparse
import sys
from typing import Any

from pharmavique.analytics.application.service import AnalyticsService
from pharmavique.analytics.infrastructure.catalog_source import CatalogMarketSource
from pharmavique.analytics.infrastructure.postgres import PostgresAnalyticsStore
from pharmavique.bootstrap.settings import get_settings
from pharmavique.catalog.application.queries import ReadProductCardsHandler
from pharmavique.catalog.infrastructure.persistence.reader import SqlAlchemyProductReader
from pharmavique.foundation.clock import SystemClock
from pharmavique.foundation.db.engine import create_engine, create_session_factory
from pharmavique.shared_kernel.market import Market

EXIT_OK = 0
EXIT_NO_DATABASE = 4


def add_arguments(commands: Any) -> None:
    rebuild = commands.add_parser(
        "analytics-rebuild", help="rebuild the company views' read model from the catalog"
    )
    rebuild.add_argument("--market", default="SA", choices=[m.value for m in Market])


async def rebuild(args: argparse.Namespace) -> int:
    settings = get_settings()
    if settings.database_url is None:
        print("set PHARMAVIQUE_DATABASE_URL first", file=sys.stderr)
        return EXIT_NO_DATABASE
    engine = create_engine(settings.database_url.get_secret_value())
    try:
        factory = create_session_factory(engine)
        service = AnalyticsService(
            PostgresAnalyticsStore(factory),
            CatalogMarketSource(ReadProductCardsHandler(SqlAlchemyProductReader(factory))),
            SystemClock(),
        )
        count = await service.rebuild(Market(args.market))
        print(f"rebuilt the {args.market} read model: {count} products")
    finally:
        await engine.dispose()
    return EXIT_OK
