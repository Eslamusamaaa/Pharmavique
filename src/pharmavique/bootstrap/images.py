"""Picture commands: wire the SFDA products to the web picture pipeline (composition root).

    sfda-images-export    cache the stored SFDA products as one JSON line each (slow, once)
    sfda-images-queries   write the search phrases for a slice of products
    sfda-images-sitemaps  collect the page addresses of Saudi pharmacy sites (once)
    sfda-images           find each drug's page (sitemaps or a results file), check it against
                          the registry data, download the picture that passes, record its source
    sfda-images-report    coverage: which drugs have a picture, which have none

The search itself is not done here: results come from a file (`--results`) that any search runner
fills, so the search backend can change without touching the rest.
"""

import argparse
import asyncio
import json
import logging
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

from pharmavique.foundation.clock import SystemClock
from pharmavique.foundation.concurrency import map_concurrently
from pharmavique.foundation.http.throttle import Throttle
from pharmavique.ingestion.infrastructure.connectors.sfda_web.mapping import map_records
from pharmavique.ingestion.infrastructure.connectors.sfda_web.store import SnapshotStore
from pharmavique.ingestion.infrastructure.connectors.sfda_web.stored_records import StoredRecords
from pharmavique.media.application.handlers import FindImagesReport, FindProductImagesHandler
from pharmavique.media.application.page_search import PageImageSearch, PageSearch
from pharmavique.media.domain.matching import ProductRef, build_queries
from pharmavique.media.domain.verification import PictureVerdict, verify_picture
from pharmavique.media.infrastructure.files import (
    FileImageStore,
    JsonlAttemptLog,
    JsonlImageRepository,
)
from pharmavique.media.infrastructure.search_file import FilePageSearch
from pharmavique.media.infrastructure.sitemaps import SitemapCollector, SitemapPageSearch
from pharmavique.media.infrastructure.web import HttpImageDownloader, PoliteWeb, WebPageReader
from pharmavique.shared_kernel.currency import Currency
from pharmavique.shared_kernel.market import Market

EXIT_OK = 0
EXIT_NO_INPUT = 4
DEFAULT_PRODUCTS = "data/media/products.jsonl"
# Saudi pharmacy sites whose robots.txt allows crawling and that publish sitemaps (checked
# 2026-11-17). Sites that blocked us (Boots, Dawi, Desertcart, Danube) are left out on purpose.
DEFAULT_SHOPS = {
    "lifepharmacy": "https://www.lifepharmacy.com/__sitemap__/en-SA.xml",
    "unitedpharmacy": "https://unitedpharmacy.sa/sitemap_en.xml",
    "rafpharmacy": "https://rafpharmacy.com/sitemap.xml",
    "aljawaher": "https://aljawaher.online/sitemap.xml",
    "nahdi": "https://www.nahdionline.com/sitemap_index_en.xml",
    "medon": "https://medononline.com/sitemap.xml",
    "ibrand": "https://ibrand.com.sa/ar/sitemap.xml",
}
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
    source = fetch.add_mutually_exclusive_group(required=True)
    source.add_argument("--results", help="JSON file: search phrase -> result pages")
    source.add_argument("--sitemaps", help="folder of collected sitemap files (*.jsonl)")
    fetch.add_argument("--retry", action="store_true", help="also work products tried before")
    fetch.add_argument("--concurrency", type=int, default=6, help="products worked at once")
    fetch.add_argument("--pages-per-query", type=int, default=3, help="pages read per phrase")
    fetch.add_argument("--out", default="data/media", help="folder for pictures and records")
    fetch.add_argument("--run-id", help="id recorded as the snapshot of these pictures")
    fetch.add_argument("--max-images", type=int, default=3, help="pictures kept per product")
    fetch.add_argument("--delay", type=float, default=2.0, help="seconds between requests")
    fetch.add_argument("--jitter", type=float, default=1.0)
    fetch.add_argument("--user-agent", default=DEFAULT_USER_AGENT)

    maps = commands.add_parser(
        "sfda-images-sitemaps", help="collect the page addresses of the pharmacy sites"
    )
    maps.add_argument("--out", default="data/media/sitemaps")
    maps.add_argument(
        "--shop", action="append", help="name=sitemap-url (repeat); default: the built-in list"
    )
    maps.add_argument("--delay", type=float, default=2.0)
    maps.add_argument("--jitter", type=float, default=1.0)
    maps.add_argument("--user-agent", default=DEFAULT_USER_AGENT)

    sync = commands.add_parser(
        "sfda-images-sync",
        help="keep pictures in step with a running SFDA crawl until the crawl ends",
    )
    sync.add_argument("--run-id", required=True, help="the SFDA crawl run to follow")
    sync.add_argument("--sfda-out", default="data/sfda")
    sync.add_argument("--sitemaps", required=True, help="folder of collected sitemap files")
    sync.add_argument("--out", default="data/media")
    sync.add_argument("--interval", type=int, default=600, help="seconds between cycles")
    sync.add_argument("--max-images", type=int, default=2)
    sync.add_argument("--concurrency", type=int, default=6)
    sync.add_argument("--pages-per-query", type=int, default=3)
    sync.add_argument("--delay", type=float, default=2.0)
    sync.add_argument("--jitter", type=float, default=1.0)
    sync.add_argument("--user-agent", default=DEFAULT_USER_AGENT)

    verify = commands.add_parser(
        "sfda-images-verify",
        help="read the text on each stored picture (Windows OCR) and check it is the right drug",
    )
    verify.add_argument("--products", default=DEFAULT_PRODUCTS)
    verify.add_argument("--out", default="data/media")
    verify.add_argument("--batch-size", type=int, default=100)

    mapping = commands.add_parser(
        "sfda-images-map", help="write the final drug-to-picture mapping and its summary"
    )
    mapping.add_argument("--products", default=DEFAULT_PRODUCTS)
    mapping.add_argument("--out", default="data/media")

    report = commands.add_parser(
        "sfda-images-report", help="how many drugs have a picture; write the list of those without"
    )
    report.add_argument("--products", default=DEFAULT_PRODUCTS)
    report.add_argument("--out", default="data/media")


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


def _product_row(snapshot: Any) -> dict[str, Any]:
    company = snapshot.marketing_company
    return {
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


def _known_register_numbers(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    known: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            known.add(json.loads(line)["register_number"])
        except (ValueError, KeyError):
            continue
    return known


def export_new_products(store: SnapshotStore, out: Path) -> int:
    """Append the stored drugs that are not in `out` yet; pages already exported are not read."""
    known = _known_register_numbers(out)
    batch = map_records(StoredRecords(store).records(skip=known), Currency.owner_assumed("SAR"))
    fresh = [s for s in batch.snapshots if s.register_number not in known]
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as handle:
        for snapshot in fresh:
            handle.write(json.dumps(_product_row(snapshot), ensure_ascii=False) + "\n")
    return len(fresh)


def export_products(args: argparse.Namespace) -> int:
    store = SnapshotStore(Path(args.sfda_out), args.run_id)
    if not store.run_dir.exists():
        print(f"no stored crawl run at {store.run_dir}", file=sys.stderr)
        return EXIT_NO_INPUT
    out = Path(args.out)
    added = export_new_products(store, out)
    print(f"exported {added} new products to {out} ({len(_known_register_numbers(out))} in all)")
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


def _configure_logging(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(sys.stderr), logging.FileHandler(out / "run.log")],
        force=True,
    )


def _page_search(args: argparse.Namespace) -> PageSearch | None:
    if args.sitemaps:
        files = sorted(Path(args.sitemaps).glob("*.jsonl"))
        if not files:
            print(
                f"no sitemap files in {args.sitemaps}: "
                "run `pharmavique sfda-images-sitemaps` first",
                file=sys.stderr,
            )
            return None
        return SitemapPageSearch(files)
    results = _existing_file(Path(args.results))
    if results is None:
        print(f"no search results file at {args.results}", file=sys.stderr)
        return None
    return FilePageSearch(results)


async def fetch_images(args: argparse.Namespace) -> int:
    refs = _load_or_explain(Path(args.products))
    if refs is None:
        return EXIT_NO_INPUT
    page_search = _page_search(args)
    if page_search is None:
        return EXIT_NO_INPUT

    out = Path(args.out)
    _configure_logging(out)
    log = logging.getLogger("media.cli")
    run_id = args.run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    chosen = _slice(refs, args)
    totals = FindImagesReport()
    done = 0
    attempts = JsonlAttemptLog(out / "attempts.jsonl")
    async with httpx.AsyncClient(timeout=40.0) as client:
        web = PoliteWeb(
            client, lambda: Throttle(args.delay, args.jitter), user_agent=args.user_agent
        )
        handler = FindProductImagesHandler(
            PageImageSearch(page_search, WebPageReader(web)),
            HttpImageDownloader(web),
            FileImageStore(out / "images"),
            JsonlImageRepository(out / "images.jsonl"),
            SystemClock(),
            run_id=run_id,
            results_per_query=args.pages_per_query,
        )

        async def work(ref: ProductRef) -> FindImagesReport:
            nonlocal done
            if not args.retry and attempts.was_tried(ref.market, ref.register_number):
                done += 1
                return FindImagesReport()
            missed_before = web.incidents
            report = await handler.handle(ref, args.max_images)
            if report.stored or web.incidents == missed_before:
                attempts.record(
                    ref.market, ref.register_number, stored=report.stored, at=SystemClock().now()
                )
            # else: a site was blocked or cooling down meanwhile, so "no picture" would be a
            # guess. The drug stays untried and is worked again on the next cycle.
            done += 1
            if done % 25 == 0 or done == len(chosen):
                log.info("%s of %s products worked; last: %s", done, len(chosen), report)
            return report

        for report in await map_concurrently(chosen, work, limit=args.concurrency):
            totals.queries += report.queries
            totals.candidates += report.candidates
            totals.rejected += report.rejected
            totals.download_failed += report.download_failed
            totals.duplicates += report.duplicates
            totals.generic += report.generic
            totals.stored += report.stored
        blocked = sorted(web.blocked_hosts)

    print(f"pictures stored: {totals.stored} | {totals}")
    if blocked:
        print(f"sites that blocked us and were left alone: {', '.join(blocked)}")
    return EXIT_OK


async def collect_sitemaps(args: argparse.Namespace) -> int:
    shops = dict(DEFAULT_SHOPS)
    if args.shop:
        shops = dict(item.split("=", 1) for item in args.shop)
    out = Path(args.out)
    async with httpx.AsyncClient(timeout=60.0) as client:
        web = PoliteWeb(
            client, lambda: Throttle(args.delay, args.jitter), user_agent=args.user_agent
        )
        collector = SitemapCollector(web)
        for name, url in shops.items():
            count = await collector.collect(url, out / f"{name}.jsonl")
            print(f"{name}: {count} page addresses")
        blocked = sorted(web.blocked_hosts)
    if blocked:
        print(f"sites that blocked us and were left alone: {', '.join(blocked)}")
    return EXIT_OK


def report_coverage(args: argparse.Namespace) -> int:
    refs = _load_or_explain(Path(args.products))
    if refs is None:
        return EXIT_NO_INPUT
    named = [r for r in refs if r.trade_name_en or r.trade_name_ar]
    best: dict[str, str] = {}
    images_file = Path(args.out) / "images.jsonl"
    if images_file.is_file():
        for line in images_file.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            number, status = row["register_number"], row["status"]
            good = status in ("matched", "confirmed")
            if good or number not in best:
                best[number] = "matched" if good else "needs_review"
    matched = sum(1 for r in named if best.get(r.register_number) == "matched")
    review = sum(1 for r in named if best.get(r.register_number) == "needs_review")
    missing = [r for r in named if r.register_number not in best]
    (Path(args.out) / "missing.json").write_text(
        json.dumps(
            [
                {
                    "register_number": r.register_number,
                    "trade_name_en": r.trade_name_en,
                    "trade_name_ar": r.trade_name_ar,
                    "ingredients": list(r.ingredient_names),
                    "strengths": list(r.strengths),
                }
                for r in missing
            ],
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(
        f"{len(named)} products ({len(refs) - len(named)} without any name) | "
        f"matched: {matched} | only needs_review: {review} | no picture: {len(missing)}"
    )
    return EXIT_OK


def _crawl_status(store: SnapshotStore) -> str | None:
    manifest = store.load_manifest()
    return None if manifest is None else str(manifest.get("status"))


async def sync_images(args: argparse.Namespace) -> int:
    """Follow a running SFDA crawl: each cycle exports the newly stored drugs and finds pictures
    for them, until the crawl is no longer running (one last cycle runs after it ends)."""
    store = SnapshotStore(Path(args.sfda_out), args.run_id)
    if not store.run_dir.exists():
        print(f"no stored crawl run at {store.run_dir}", file=sys.stderr)
        return EXIT_NO_INPUT
    out = Path(args.out)
    products = out / "products.jsonl"
    _configure_logging(out)
    log = logging.getLogger("media.sync")
    cycle = 0
    while True:
        cycle += 1
        status = _crawl_status(store)  # read first: the cycle after the crawl ends is the last
        added = export_new_products(store, products)
        log.info("cycle %s: crawl is %s, %s new drugs", cycle, status, added)
        fetch_args = argparse.Namespace(
            products=str(products),
            sitemaps=args.sitemaps,
            results=None,
            offset=0,
            limit=1_000_000,
            out=args.out,
            run_id=f"sync-{args.run_id}",
            max_images=args.max_images,
            retry=False,
            concurrency=args.concurrency,
            pages_per_query=args.pages_per_query,
            delay=args.delay,
            jitter=args.jitter,
            user_agent=args.user_agent,
        )
        await fetch_images(fetch_args)
        report_coverage(argparse.Namespace(products=str(products), out=args.out))
        if status != "running":
            log.info("the crawl is %s: last cycle done", status)
            return EXIT_OK
        await asyncio.sleep(args.interval)


OcrReader = Callable[[list[Path]], dict[Path, str | None]]
_OCR_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "ocr_windows.ps1"


def windows_ocr(paths: list[Path]) -> dict[Path, str | None]:
    """Read the text of pictures with the OCR engine built into Windows; None when one fails."""
    shell = shutil.which("powershell.exe")
    if shell is None:
        raise RuntimeError("the Windows OCR needs powershell.exe, which was not found")
    with tempfile.TemporaryDirectory() as folder:
        listing = Path(folder) / "files.txt"
        output = Path(folder) / "out.jsonl"
        listing.write_text("\n".join(str(p.resolve()) for p in paths), encoding="utf-8")
        subprocess.run(  # noqa: S603 - fixed command, our own script, paths from our own files
            [
                shell, "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", str(_OCR_SCRIPT), "-List", str(listing), "-Out", str(output),
            ],
            check=True,
            capture_output=True,
        )  # fmt: skip
        found: dict[Path, str | None] = {}
        if output.is_file():
            for line in output.read_text(encoding="utf-8-sig").splitlines():
                row = json.loads(line)
                found[Path(row["file"]).resolve()] = None if row.get("error") else row["text"]
    return {p: found.get(p.resolve()) for p in paths}


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def verify_pictures(
    products: Path, media: Path, ocr: OcrReader, *, batch_size: int = 100
) -> Counter[str]:
    """Read every stored picture not yet verified and judge it against its own drug."""
    refs = {r.register_number: r for r in load_product_refs(products)}
    done = {row["storage_key"] for row in _jsonl(media / "verification.jsonl")}
    pending = [r for r in _jsonl(media / "images.jsonl") if r["storage_key"] not in done]
    counts: Counter[str] = Counter()
    log = logging.getLogger("media.verify")
    with (media / "verification.jsonl").open("a", encoding="utf-8") as handle:
        for start in range(0, len(pending), batch_size):
            batch = pending[start : start + batch_size]
            texts = ocr([media / "images" / row["storage_key"] for row in batch])
            for row in batch:
                text = texts.get(media / "images" / row["storage_key"])
                ref = refs.get(row["register_number"])
                signals: tuple[str, ...]
                if text is None or ref is None:
                    verdict, signals, shown = PictureVerdict.NOT_CONFIRMED, ("ocr_error",), ""
                else:
                    check = verify_picture(ref, text)
                    verdict, signals, shown = check.verdict, check.signals, text[:300]
                counts[verdict.value] += 1
                handle.write(
                    json.dumps(
                        {
                            "storage_key": row["storage_key"],
                            "register_number": row["register_number"],
                            "verdict": verdict.value,
                            "signals": list(signals),
                            "ocr_text": shown,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
            handle.flush()
            log.info(
                "%s of %s pictures verified", min(start + batch_size, len(pending)), len(pending)
            )
    return counts


def run_verify(args: argparse.Namespace) -> int:
    products = Path(args.products)
    if not products.is_file() or not _OCR_SCRIPT.is_file():
        print("needs the products file and scripts/ocr_windows.ps1", file=sys.stderr)
        return EXIT_NO_INPUT
    out = Path(args.out)
    _configure_logging(out)
    counts = verify_pictures(products, out, windows_ocr, batch_size=args.batch_size)
    print("verified now: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return EXIT_OK


_CHECK_RANK = {
    "confirmed": 0,
    "likely": 1,
    "unchecked": 2,
    "not_confirmed": 3,
    "strength_conflict": 4,
}
_STATUS_RANK = {"confirmed": 0, "matched": 1, "needs_review": 2, "rejected": 3}


def build_mapping(products: Path, media: Path) -> dict[str, int]:
    """One row per drug: its names, ingredients and the best picture found, with how it was
    checked. Drugs with no picture are in the file too (`picture_check` is `no_picture`)."""
    refs = [r for r in load_product_refs(products) if r.trade_name_en or r.trade_name_ar]
    checks = {row["storage_key"]: row["verdict"] for row in _jsonl(media / "verification.jsonl")}
    by_drug: dict[str, list[dict[str, Any]]] = {}
    for image in _jsonl(media / "images.jsonl"):
        by_drug.setdefault(image["register_number"], []).append(image)

    def rank(image: dict[str, Any]) -> tuple[int, int, float]:
        check = checks.get(image["storage_key"], "unchecked")
        return (_CHECK_RANK[check], _STATUS_RANK.get(image["status"], 9), -image["score"])

    summary = {"drugs": len(refs), "with_picture": 0, "confirmed": 0, "unverified": 0, "missing": 0}
    with (media / "mapping.jsonl").open("w", encoding="utf-8") as handle:
        for ref in refs:
            candidates = by_drug.get(ref.register_number, [])
            best = min(candidates, key=rank) if candidates else None
            check = "no_picture" if best is None else checks.get(best["storage_key"], "unchecked")
            row = {
                "market": ref.market.value,
                "register_number": ref.register_number,
                "trade_name_en": ref.trade_name_en,
                "trade_name_ar": ref.trade_name_ar,
                "scientific_names": list(ref.ingredient_names),
                "strengths": list(ref.strengths),
                "company": ref.marketing_company,
                "picture": None if best is None else str(media / "images" / best["storage_key"]),
                "picture_status": None if best is None else best["status"],
                "picture_check": check,
                "source_page": None if best is None else best["page_url"],
                "source_image_url": None if best is None else best["image_url"],
                "trust": None if best is None else best["provenance"]["trust"],
            }
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            if best is None:
                summary["missing"] += 1
            else:
                summary["with_picture"] += 1
                summary["confirmed" if check == "confirmed" else "unverified"] += 1
    return summary


def run_map(args: argparse.Namespace) -> int:
    products = Path(args.products)
    if not products.is_file():
        print(f"no products file at {products}", file=sys.stderr)
        return EXIT_NO_INPUT
    summary = build_mapping(products, Path(args.out))
    print(
        f"{summary['drugs']} drugs | with a picture: {summary['with_picture']} "
        f"(confirmed by the text on the box: {summary['confirmed']}, "
        f"not confirmed: {summary['unverified']}) | no picture: {summary['missing']}"
    )
    return EXIT_OK
