"""Picture commands: wire the SFDA products to the web picture pipeline (composition root).

    sfda-images-export    cache the stored SFDA products as one JSON line each (slow, once)
    sfda-images-queries   write the search phrases for a slice of products
    sfda-images           read the search results, check each page against the registry data,
                          download the pictures that pass, record them with their source

The search itself is not done here: results come from a file (`--results`) that any search runner
fills, so the search backend can change without touching the rest.
"""

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

from pharmavique.foundation.clock import SystemClock
from pharmavique.foundation.http.throttle import Throttle
from pharmavique.ingestion.infrastructure.connectors.sfda_web.mapping import map_records
from pharmavique.ingestion.infrastructure.connectors.sfda_web.store import SnapshotStore
from pharmavique.ingestion.infrastructure.connectors.sfda_web.stored_records import StoredRecords
from pharmavique.media.application.handlers import FindImagesReport, FindProductImagesHandler
from pharmavique.media.application.page_search import PageImageSearch
from pharmavique.media.domain.matching import ProductRef, build_queries
from pharmavique.media.infrastructure.files import FileImageStore, JsonlImageRepository
from pharmavique.media.infrastructure.search_file import FilePageSearch
from pharmavique.media.infrastructure.web import HttpImageDownloader, PoliteWeb, WebPageReader
from pharmavique.shared_kernel.currency import Currency
from pharmavique.shared_kernel.market import Market

EXIT_OK = 0
EXIT_NO_INPUT = 4
DEFAULT_PRODUCTS = "data/media/products.jsonl"
DEFAULT_USER_AGENT = "DrugRegistrySync/0.1 (polite research crawler; throttled; honours robots.txt)"


def add_arguments(commands: Any) -> None:
    export = commands.add_parser(
        "sfda-images-export", help="cache the stored SFDA products for the picture commands"
    )
    export.add_argument("--run-id", required=True, help="the SFDA crawl run to read")
    export.add_argument("--sfda-out", default="data/sfda")
    export.add_argument("--out", default=DEFAULT_PRODUCTS)

    queries = commands.add_parser(
        "sfda-images-queries", help="write the web search phrases for a slice of products"
    )
    _slice_options(queries)
    queries.add_argument("--out", default="data/media/queries.json")

    fetch = commands.add_parser(
        "sfda-images", help="check search results against the registry, download matching pictures"
    )
    _slice_options(fetch)
    fetch.add_argument("--results", required=True, help="JSON file: search phrase -> result pages")
    fetch.add_argument("--out", default="data/media", help="folder for pictures and records")
    fetch.add_argument("--run-id", help="id recorded as the snapshot of these pictures")
    fetch.add_argument("--max-images", type=int, default=3, help="pictures kept per product")
    fetch.add_argument("--delay", type=float, default=2.0, help="seconds between requests")
    fetch.add_argument("--jitter", type=float, default=1.0)
    fetch.add_argument("--user-agent", default=DEFAULT_USER_AGENT)


def _slice_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--products", default=DEFAULT_PRODUCTS)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=50)


def _strength(strength: str | None, unit: str | None) -> str | None:
    if not strength:
        return None
    plain = format(Decimal(strength).normalize(), "f")
    return f"{plain} {unit}".strip() if unit else plain


def load_product_refs(path: Path) -> list[ProductRef]:
    refs: list[ProductRef] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        ingredients = row.get("ingredients", [])
        strengths = tuple(
            text
            for text in (_strength(i.get("strength"), i.get("unit")) for i in ingredients)
            if text
        )
        refs.append(
            ProductRef(
                market=Market(row["market"]),
                register_number=row["register_number"],
                trade_name_en=row.get("trade_name_en"),
                trade_name_ar=row.get("trade_name_ar"),
                ingredient_names=tuple(i["name"] for i in ingredients),
                marketing_company=row.get("company"),
                strengths=strengths,
            )
        )
    return refs


def _slice(refs: Sequence[ProductRef], args: argparse.Namespace) -> list[ProductRef]:
    named = [r for r in refs if r.trade_name_en or r.trade_name_ar]
    return named[args.offset : args.offset + args.limit]


def _load_or_explain(path: Path) -> list[ProductRef] | None:
    if not path.exists():
        print(
            f"no products file at {path}: run "
            "`pharmavique sfda-images-export --run-id <crawl run>` first",
            file=sys.stderr,
        )
        return None
    return load_product_refs(path)


def _existing_file(path: Path) -> Path | None:
    return path if path.is_file() else None


def export_products(args: argparse.Namespace) -> int:
    store = SnapshotStore(Path(args.sfda_out), args.run_id)
    if not store.run_dir.exists():
        print(f"no stored crawl run at {store.run_dir}", file=sys.stderr)
        return EXIT_NO_INPUT
    batch = map_records(StoredRecords(store).records(), Currency.owner_assumed("SAR"))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        for snapshot in batch.snapshots:
            company = snapshot.marketing_company
            row = {
                "market": snapshot.market.value,
                "register_number": snapshot.register_number,
                "trade_name_en": snapshot.trade_name_en,
                "trade_name_ar": snapshot.trade_name_ar,
                "ingredients": [
                    {
                        "name": i.name,
                        "strength": str(i.strength) if i.strength else None,
                        "unit": i.unit,
                    }
                    for i in snapshot.ingredients
                ],
                "dosage_form_en": snapshot.dosage_form_en,
                "company": company.name if company else None,
            }
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"exported {len(batch.snapshots)} products to {out}")
    return EXIT_OK


def write_queries(args: argparse.Namespace) -> int:
    refs = _load_or_explain(Path(args.products))
    if refs is None:
        return EXIT_NO_INPUT
    chosen = _slice(refs, args)
    queries = {ref.register_number: list(build_queries(ref)) for ref in chosen}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(queries, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote search phrases for {len(chosen)} products to {out}")
    return EXIT_OK


async def fetch_images(args: argparse.Namespace) -> int:
    log = logging.getLogger("media.cli")
    refs = _load_or_explain(Path(args.products))
    if refs is None:
        return EXIT_NO_INPUT
    results = _existing_file(Path(args.results))
    if results is None:
        print(f"no search results file at {args.results}", file=sys.stderr)
        return EXIT_NO_INPUT

    out = Path(args.out)
    run_id = args.run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    totals = FindImagesReport()
    async with httpx.AsyncClient(timeout=40.0) as client:
        web = PoliteWeb(client, Throttle(args.delay, args.jitter), user_agent=args.user_agent)
        handler = FindProductImagesHandler(
            PageImageSearch(FilePageSearch(results), WebPageReader(web)),
            HttpImageDownloader(web),
            FileImageStore(out / "images"),
            JsonlImageRepository(out / "images.jsonl"),
            SystemClock(),
            run_id=run_id,
        )
        for ref in _slice(refs, args):
            report = await handler.handle(ref, args.max_images)
            log.info("%s %s: %s", ref.register_number, ref.trade_name_en, report)
            totals.queries += report.queries
            totals.candidates += report.candidates
            totals.rejected += report.rejected
            totals.download_failed += report.download_failed
            totals.duplicates += report.duplicates
            totals.stored += report.stored
        blocked = sorted(web.blocked_hosts)

    print(f"pictures stored: {totals.stored} | {totals}")
    if blocked:
        print(f"sites that blocked us and were left alone: {', '.join(blocked)}")
    return EXIT_OK
