"""`pharmavique offers-crawl` and `offers-report`: load a pharmacy's whole catalog and look at it.

The crawl writes to the database in PHARMAVIQUE_DATABASE_URL and refuses a database that is not on
this machine unless `--allow-remote` is given: a pharmacy catalog is large and Neon Free is small.
"""

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import text

from pharmavique.bootstrap.settings import get_settings
from pharmavique.foundation.db.engine import create_engine, create_session_factory
from pharmavique.offers.application.crawl import CrawlBudget, InitialLoad
from pharmavique.offers.application.images import DownloadImages
from pharmavique.offers.application.ports import FetchFailed, SourceBlocked
from pharmavique.offers.domain.model import RunStatus
from pharmavique.offers.infrastructure.config import load_retailers
from pharmavique.offers.infrastructure.fetch import USER_AGENT, PoliteFetcher
from pharmavique.offers.infrastructure.images import DiskImageSink, PostgresImageStore
from pharmavique.offers.infrastructure.parsing import decode, parse_product
from pharmavique.offers.infrastructure.persistence import PostgresListingStore
from pharmavique.offers.infrastructure.sitemap import SitemapReader

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_PARTIAL = 2
EXIT_STOPPED = 3
EXIT_NO_DATABASE = 4
EXIT_BAD_ARGUMENT = 5
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", ""}


def add_arguments(commands: Any) -> None:
    crawl = commands.add_parser(
        "offers-crawl",
        help="load every product of one pharmacy from its sitemaps (resumable, polite)",
    )
    crawl.add_argument("--retailer", required=True)
    crawl.add_argument("--config-dir", default="config/retailers")
    crawl.add_argument("--limit", type=int, help="at most N pages in this run (for a trial)")
    crawl.add_argument("--max-minutes", type=float, help="stop starting pages after M minutes")
    crawl.add_argument(
        "--allow-remote", action="store_true", help="write to a database that is not local"
    )
    images = commands.add_parser(
        "offers-images",
        help="download the main picture of every listing of one pharmacy (resumable)",
    )
    images.add_argument("--retailer", required=True)
    images.add_argument("--config-dir", default="config/retailers")
    images.add_argument("--folder", default="data/offers/images")
    images.add_argument("--limit", type=int, help="at most N pictures in this run (for a trial)")
    images.add_argument("--allow-remote", action="store_true")
    report = commands.add_parser("offers-report", help="what the pharmacies' catalogs hold now")
    report.add_argument("--retailer")


def _is_local(url: str) -> bool:
    return (urlparse(url.replace("+asyncpg", "")).hostname or "") in LOCAL_HOSTS


async def crawl(args: argparse.Namespace) -> int:
    secret = get_settings().database_url
    if secret is None:
        print("set PHARMAVIQUE_DATABASE_URL (see .env.example)", file=sys.stderr)
        return EXIT_NO_DATABASE
    if not args.allow_remote and not _is_local(secret.get_secret_value()):
        print(
            "the database is not on this machine; pass --allow-remote to write to it",
            file=sys.stderr,
        )
        return EXIT_BAD_ARGUMENT
    configs = load_retailers(Path(args.config_dir))
    config = configs.get(args.retailer)
    if config is None:
        print(
            f"no retailer {args.retailer!r}; known: {', '.join(sorted(configs))}", file=sys.stderr
        )
        return EXIT_BAD_ARGUMENT
    engine = create_engine(secret.get_secret_value())
    try:
        store = PostgresListingStore(create_session_factory(engine), config)
        async with httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT}, timeout=60, follow_redirects=True
        ) as client:
            try:
                fetcher = await PoliteFetcher.for_retailer(config, client)
                use = InitialLoad(
                    SitemapReader(config, fetcher),
                    fetcher,
                    store,
                    lambda html, url: parse_product(html, url, config),
                    lambda: datetime.now(UTC),
                    decode,
                )
                print(f"{config.name}: one request every {fetcher.interval:g} s", flush=True)
                report = await use.run(
                    CrawlBudget(
                        limit=args.limit,
                        max_seconds=None if args.max_minutes is None else args.max_minutes * 60,
                    )
                )
            except SourceBlocked as exc:
                print(f"stopped, the site refused: {exc}", file=sys.stderr)
                return EXIT_STOPPED
            except FetchFailed as exc:
                print(f"could not read the sitemap: {exc}", file=sys.stderr)
                return EXIT_FAILED
    finally:
        await engine.dispose()
    shown = dict(sorted(report.counters.items()))
    print(f"{config.name}: {report.status.value} {shown}")
    return {
        RunStatus.COMPLETE: EXIT_OK,
        RunStatus.PARTIAL: EXIT_PARTIAL,
        RunStatus.BLOCKED: EXIT_STOPPED,
        RunStatus.FAILED: EXIT_FAILED,
    }[report.status]


async def images(args: argparse.Namespace) -> int:
    secret = get_settings().database_url
    if secret is None:
        print("set PHARMAVIQUE_DATABASE_URL (see .env.example)", file=sys.stderr)
        return EXIT_NO_DATABASE
    if not args.allow_remote and not _is_local(secret.get_secret_value()):
        print(
            "the database is not on this machine; pass --allow-remote to write to it",
            file=sys.stderr,
        )
        return EXIT_BAD_ARGUMENT
    config = load_retailers(Path(args.config_dir)).get(args.retailer)
    if config is None:
        print(f"no retailer {args.retailer!r}", file=sys.stderr)
        return EXIT_BAD_ARGUMENT
    engine = create_engine(secret.get_secret_value())
    totals: dict[str, int] = {}
    try:
        store = PostgresImageStore(create_session_factory(engine), config.id)
        async with httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT}, timeout=60, follow_redirects=True
        ) as client:
            fetchers: dict[str, PoliteFetcher] = {}

            async def fetcher_for(host: str) -> PoliteFetcher:
                if host not in fetchers:
                    fetchers[host] = await PoliteFetcher.for_base(
                        f"https://{host}", config.min_interval, client
                    )
                return fetchers[host]

            use = DownloadImages(
                store, fetcher_for, DiskImageSink(Path(args.folder)), lambda: datetime.now(UTC)
            )
            budget = args.limit
            status = RunStatus.COMPLETE
            try:
                while budget is None or budget > 0:
                    batch = 500 if budget is None else min(500, budget)
                    done = await use.run(batch)
                    for key, value in done.counters.items():
                        if key != "remaining":
                            totals[key] = totals.get(key, 0) + value
                    if done.status is RunStatus.BLOCKED:
                        status = RunStatus.BLOCKED
                        break
                    if done.counters.get("remaining", 0) == 0:
                        break
                    if budget is not None:
                        budget -= batch
            except SourceBlocked as exc:
                print(f"stopped, the site refused: {exc}", file=sys.stderr)
                return EXIT_STOPPED
    finally:
        await engine.dispose()
    print(f"{config.name} pictures: {status.value} {dict(sorted(totals.items()))}")
    return EXIT_STOPPED if status is RunStatus.BLOCKED else EXIT_OK


async def report(args: argparse.Namespace) -> int:
    secret = get_settings().database_url
    if secret is None:
        print("set PHARMAVIQUE_DATABASE_URL (see .env.example)", file=sys.stderr)
        return EXIT_NO_DATABASE
    engine = create_engine(secret.get_secret_value())
    try:
        async with engine.connect() as connection:
            rows = await connection.execute(
                text(
                    """
                    SELECT l.retailer_id, count(*) AS listings,
                        count(*) FILTER (WHERE l.category = 'medicine') AS medicines,
                        count(*) FILTER (WHERE l.category = 'unclassified') AS unclassified,
                        count(*) FILTER (WHERE l.price_amount IS NOT NULL) AS with_price,
                        count(*) FILTER (WHERE cardinality(l.image_urls) > 0) AS with_image,
                        count(*) FILTER (WHERE l.barcode IS NOT NULL) AS with_barcode,
                        count(*) FILTER (WHERE t.listing_id IS NOT NULL) AS with_description,
                        count(*) FILTER (WHERE l.ingredients_text IS NOT NULL) AS with_ingredients
                    FROM offers.listing l LEFT JOIN offers.listing_text t ON t.listing_id = l.id
                    WHERE (CAST(:r AS text) IS NULL OR l.retailer_id = :r)
                    GROUP BY 1 ORDER BY 1
                    """
                ),
                {"r": args.retailer},
            )
            for row in rows:
                print(dict(row._mapping))
    finally:
        await engine.dispose()
    return EXIT_OK
