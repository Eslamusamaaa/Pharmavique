"""`pharmavique cache-invalidate`, and the relay subscriber that does the same on catalog events.

The shared read cache keys carry a data version; bumping it makes every stored answer unreadable
at once (they expire by themselves later). Run it after anything that changes what search and drug
pages answer without emitting a catalog event: the search reindex and the official-list loads. The
daily refresh does.
"""

import argparse
import logging
import sys
from collections.abc import Awaitable, Callable
from typing import Any

from pharmavique.bootstrap.settings import Settings, get_settings
from pharmavique.foundation.kv import RedisStore, StoreUnavailable, redis_client
from pharmavique.foundation.read_cache import ReadCache
from pharmavique.shared_kernel.events import StoredEvent

EXIT_OK = 0
EXIT_NO_REDIS = 4
_log = logging.getLogger(__name__)


def add_arguments(commands: Any) -> None:
    commands.add_parser(
        "cache-invalidate", help="make every cached search and drug-page answer stale"
    )


def open_store(settings: Settings) -> RedisStore | None:
    if settings.redis_url is None:
        return None
    return RedisStore(redis_client(settings.redis_url.get_secret_value(), timeout=2.0))


def invalidate_on_catalog_event(cache: ReadCache) -> Callable[[StoredEvent], Awaitable[None]]:
    """A relay subscriber. A store outage is logged and skipped: cached answers then live out their
    short expiry instead of blocking the other subscribers (alerts) from receiving the event."""

    async def handle(event: StoredEvent) -> None:
        if not event.event_type.startswith("catalog."):
            return
        try:
            await cache.invalidate_all()
        except StoreUnavailable:
            _log.warning("cache invalidation skipped: the shared store is unreachable")

    return handle


async def invalidate(args: argparse.Namespace) -> int:
    settings = get_settings()
    store = open_store(settings)
    if store is None:
        print(
            "set PHARMAVIQUE_REDIS_URL first (there is no shared cache to clear)", file=sys.stderr
        )
        return EXIT_NO_REDIS
    try:
        await ReadCache(store).invalidate_all()
        print("cache invalidated")
    except StoreUnavailable as error:
        print(f"could not reach the shared store: {error}", file=sys.stderr)
        return EXIT_NO_REDIS
    finally:
        await store.close()
    return EXIT_OK
