"""`pharmavique outbox-relay`: deliver the catalog's integration events to their subscribers.

Two subscribers listen: the watchlist turns price changes, withdrawals and relistings into alerts
for the people who saved those medicines, and the analytics read model keeps them for the
competitor radar. Run it next to the API (it loops) or after a
refresh with `--once`. Delivery is at least once and the subscribers are idempotent, so running two
relays or stopping one in the middle is safe.
"""

import argparse
import sys
from typing import Any

from pharmavique.analytics.application.service import AnalyticsService
from pharmavique.analytics.infrastructure.catalog_source import CatalogMarketSource
from pharmavique.analytics.infrastructure.postgres import PostgresAnalyticsStore
from pharmavique.bootstrap.settings import get_settings
from pharmavique.catalog.application.queries import ReadProductCardsHandler
from pharmavique.catalog.infrastructure.persistence.outbox import SqlAlchemyOutboxPublisher
from pharmavique.catalog.infrastructure.persistence.reader import SqlAlchemyProductReader
from pharmavique.foundation.clock import SystemClock
from pharmavique.foundation.db.engine import create_engine, create_session_factory
from pharmavique.foundation.events.relay import OutboxRelay
from pharmavique.watchlist.application.service import WatchlistService
from pharmavique.watchlist.infrastructure.postgres import PostgresWatchlistStore

EXIT_OK = 0
EXIT_NO_DATABASE = 4


def add_arguments(commands: Any) -> None:
    relay = commands.add_parser(
        "outbox-relay", help="deliver the catalog's events (alerts) to their subscribers"
    )
    relay.add_argument("--once", action="store_true", help="deliver what is waiting, then stop")
    relay.add_argument("--interval", type=float, default=5.0, help="seconds between rounds")
    relay.add_argument("--batch", type=int, default=200)


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    if settings.database_url is None:
        print("set PHARMAVIQUE_DATABASE_URL first", file=sys.stderr)
        return EXIT_NO_DATABASE
    engine = create_engine(settings.database_url.get_secret_value())
    try:
        factory = create_session_factory(engine)
        watchlist = WatchlistService(PostgresWatchlistStore(factory), SystemClock())
        analytics = AnalyticsService(
            PostgresAnalyticsStore(factory),
            CatalogMarketSource(ReadProductCardsHandler(SqlAlchemyProductReader(factory))),
            SystemClock(),
        )
        relay = OutboxRelay(
            [SqlAlchemyOutboxPublisher(factory)], [watchlist.on_event, analytics.on_event]
        )
        if args.once:
            delivered = await relay.run_until_empty(args.batch)
            print(f"delivered {delivered} events")
        else:
            await relay.run_forever(args.interval, args.batch)
    finally:
        await engine.dispose()
    return EXIT_OK
