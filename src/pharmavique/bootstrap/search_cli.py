"""Search commands (composition root: wires search to the catalog and to Postgres).

search-reindex   rebuild the search index from the catalog's product cards (safe to repeat)
similar-names-rebuild   store every product's look-alike names (daily refresh, safe to repeat)
search           look a name up (typed, misspelled, Arabic or English) and print what it finds
"""

import argparse
import sys
import time
from typing import Any

from pharmavique.bootstrap.settings import get_settings
from pharmavique.catalog.application.queries import ReadProductCardsHandler
from pharmavique.catalog.infrastructure.persistence.reader import SqlAlchemyProductReader
from pharmavique.foundation.db.engine import create_engine, create_session_factory
from pharmavique.search.application.handlers import RebuildIndexHandler, SearchProductsHandler
from pharmavique.search.application.similar_names import RebuildSimilarNames
from pharmavique.search.contracts.queries import SearchQuery
from pharmavique.search.infrastructure.catalog_source import CatalogNameSource, CatalogProductSource
from pharmavique.search.infrastructure.postgres import PostgresSearchIndex
from pharmavique.search.infrastructure.similar_names import PostgresSimilarNameStore
from pharmavique.shared_kernel.market import Market

EXIT_OK = 0
EXIT_NO_DATABASE = 4


def add_arguments(commands: Any) -> None:
    reindex = commands.add_parser(
        "search-reindex", help="rebuild the search index from the catalog (safe to repeat)"
    )
    reindex.add_argument("--market", default="SA", choices=[m.value for m in Market])
    reindex.add_argument("--page-size", type=int, default=500)

    similar = commands.add_parser(
        "similar-names-rebuild",
        help="compute and store every product's look-alike names (safe to repeat)",
    )
    similar.add_argument("--market", default="SA", choices=[m.value for m in Market])

    find = commands.add_parser("search", help="look a drug name up in the search index")
    find.add_argument("text", help="what to look for, for example 'panadool extra'")
    find.add_argument("--market", default="SA", choices=[m.value for m in Market])
    find.add_argument("--limit", type=int, default=10)
    find.add_argument("--include-withdrawn", action="store_true")


def _database_url() -> str | None:
    secret = get_settings().database_url
    if secret is None:
        print(
            "set PHARMAVIQUE_DATABASE_URL (see .env.example) and run `alembic upgrade heads` first",
            file=sys.stderr,
        )
        return None
    return secret.get_secret_value()


async def reindex(args: argparse.Namespace) -> int:
    url = _database_url()
    if url is None:
        return EXIT_NO_DATABASE
    engine = create_engine(url)
    try:
        session_factory = create_session_factory(engine)
        source = CatalogProductSource(
            ReadProductCardsHandler(SqlAlchemyProductReader(session_factory))
        )
        count = await RebuildIndexHandler(
            source, PostgresSearchIndex(session_factory), args.page_size
        ).rebuild(Market(args.market))
    finally:
        await engine.dispose()
    print(f"indexed {count} products for market {args.market}")
    return EXIT_OK


async def rebuild_similar_names(args: argparse.Namespace) -> int:
    url = _database_url()
    if url is None:
        return EXIT_NO_DATABASE
    engine = create_engine(url)
    started = time.perf_counter()
    try:
        session_factory = create_session_factory(engine)
        count = await RebuildSimilarNames(
            CatalogNameSource(SqlAlchemyProductReader(session_factory)),
            PostgresSimilarNameStore(session_factory),
        ).rebuild(Market(args.market))
    finally:
        await engine.dispose()
    seconds = time.perf_counter() - started
    print(f"stored the look-alike names of {count} products for {args.market} in {seconds:.0f} s")
    return EXIT_OK


async def lookup(args: argparse.Namespace) -> int:
    url = _database_url()
    if url is None:
        return EXIT_NO_DATABASE
    engine = create_engine(url)
    try:
        session_factory = create_session_factory(engine)
        market = Market(args.market)
        result = await SearchProductsHandler(PostgresSearchIndex(session_factory)).search(
            SearchQuery(args.text, market, args.limit, args.include_withdrawn)
        )
        cards = await ReadProductCardsHandler(SqlAlchemyProductReader(session_factory)).get_cards(
            market, [m.register_number for m in result.matches]
        )
    finally:
        await engine.dispose()
    by_number = {card.register_number: card for card in cards}
    if not result.matches:
        print("nothing found")
    for rank, match in enumerate(result.matches, 1):
        card = by_number.get(match.register_number)
        names = f"{card.trade_name_en or '-'} | {card.trade_name_ar or '-'}" if card else "?"
        why = ", ".join(f"{r.signal}#{r.rank} {r.score:.2f}" for r in match.reasons)
        ingredients = ", ".join(card.ingredient_names[:2]) if card else ""
        print(f"{rank:>2}. {match.register_number:<12} {names}  [{ingredients}]  ({why})")
    return EXIT_OK
