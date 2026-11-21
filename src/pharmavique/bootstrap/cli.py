"""Command line entry point: `pharmavique <command>`.

Commands
    sfda-scrape   full crawl of the public SFDA registered-drugs list (resumable, polite)
    sfda-update   cheap refresh: only new and changed drugs are refetched, then a change report
    sfda-diff     compare two stored runs offline
    sfda-lists    crawl the other official SFDA lists (shortages, pharmacies, companies, ...)
    sfda-images-export / sfda-images-queries / sfda-images    find and store product pictures
    search-reindex / search    build the search index from the catalog and look names up
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from pharmavique.bootstrap import (
    analytics_cli,
    cache_cli,
    identity_cli,
    images,
    interactions_cli,
    knowledge_cli,
    labels_cli,
    lists_cli,
    pictures_cli,
    relay_cli,
    search_cli,
    worker_cli,
)
from pharmavique.bootstrap.settings import get_settings
from pharmavique.catalog.application.handlers import (
    ApplyCatalogChangesHandler,
    WithdrawProductsHandler,
)
from pharmavique.catalog.infrastructure.persistence.unit_of_work import SqlAlchemyCatalogUnitOfWork
from pharmavique.catalog.presentation.inprocess import InProcessCatalogCommands
from pharmavique.foundation.clock import SystemClock
from pharmavique.foundation.db.engine import create_engine, create_session_factory
from pharmavique.foundation.http.robots import RobotsPolicy
from pharmavique.foundation.http.throttle import Throttle
from pharmavique.ingestion.application.load_records import LoadRecordsIntoCatalog
from pharmavique.ingestion.domain.diff import diff
from pharmavique.ingestion.domain.records import ChangeSet
from pharmavique.ingestion.infrastructure.adapters.catalog_writer import CatalogWriter
from pharmavique.ingestion.infrastructure.connectors.sfda_web.crawler import (
    CrawlConfig,
    CrawlError,
    SfdaCrawler,
)
from pharmavique.ingestion.infrastructure.connectors.sfda_web.errors import SourceBlocked
from pharmavique.ingestion.infrastructure.connectors.sfda_web.list_crawler import (
    ListCrawlConfig,
    ListCrawler,
)
from pharmavique.ingestion.infrastructure.connectors.sfda_web.list_details import (
    ListDetailCrawler,
)
from pharmavique.ingestion.infrastructure.connectors.sfda_web.list_files import (
    ListFileCrawler,
)
from pharmavique.ingestion.infrastructure.connectors.sfda_web.list_stream import (
    StreamingListCrawler,
)
from pharmavique.ingestion.infrastructure.connectors.sfda_web.lists import (
    SFDA_LISTS,
    ListSpec,
    get_list,
)
from pharmavique.ingestion.infrastructure.connectors.sfda_web.pdf_ocr_windows import (
    windows_image_ocr,
    windows_pdf_ocr,
)
from pharmavique.ingestion.infrastructure.connectors.sfda_web.pdf_text import (
    extract_all,
    ocr_empty_texts,
    ocr_image_texts,
)
from pharmavique.ingestion.infrastructure.connectors.sfda_web.playwright_fetcher import (
    PlaywrightPageFetcher,
)
from pharmavique.ingestion.infrastructure.connectors.sfda_web.records import to_source_records
from pharmavique.ingestion.infrastructure.connectors.sfda_web.report import (
    changes_to_json,
    render_markdown,
)
from pharmavique.ingestion.infrastructure.connectors.sfda_web.store import SnapshotStore
from pharmavique.ingestion.infrastructure.connectors.sfda_web.stored_records import (
    JsonlRecords,
    StoredRecords,
)
from pharmavique.shared_kernel.currency import Currency

# Owner's decision (2026-11-17): SFDA prices are SAR. The pages do not state a currency, so the
# basis is recorded as an assumption and shown as such. Change it here if SFDA documents otherwise.
SA_PRICE_CURRENCY = Currency.owner_assumed("SAR")

DEFAULT_BASE_URL = "https://www.sfda.gov.sa"
# Generic on purpose: it says what the client is without naming a person or project.
DEFAULT_USER_AGENT = "DrugRegistrySync/0.1 (polite research crawler; throttled; honours robots.txt)"
DEFAULT_RECHECK = 300

EXIT_OK = 0
EXIT_PARTIAL = 2
EXIT_STOPPED = 3
EXIT_NO_BASELINE = 4


def _add_fetch_options(parser: argparse.ArgumentParser, default_out: str = "data/sfda") -> None:
    parser.add_argument("--out", default=default_out, help="folder for run snapshots")
    parser.add_argument("--run-id", help="run id (reuse an existing one to resume it)")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--delay", type=float, default=1.5, help="seconds between requests")
    parser.add_argument("--jitter", type=float, default=0.5, help="extra random seconds, 0 to N")
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    parser.add_argument("--enable-js", action="store_true", help="run page JavaScript")
    parser.add_argument("--headed", action="store_true", help="show the browser window")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pharmavique")
    commands = parser.add_subparsers(dest="command", required=True)

    scrape = commands.add_parser("sfda-scrape", help="full crawl of the public SFDA list")
    _add_fetch_options(scrape)
    scrape.add_argument("--max-pages", type=int, help="only crawl this many list pages (sample)")
    scrape.add_argument("--max-details", type=int, help="only fetch details for this many drugs")

    update = commands.add_parser("sfda-update", help="refresh only what changed, then report")
    _add_fetch_options(update)
    update.add_argument("--baseline", help="run id to compare with (default: the latest complete)")
    update.add_argument(
        "--recheck",
        type=int,
        default=DEFAULT_RECHECK,
        help="also re-fetch the details of this many drugs, oldest first",
    )

    compare = commands.add_parser("sfda-diff", help="compare two stored runs (no network)")
    compare.add_argument("old", help="older run id")
    compare.add_argument("new", help="newer run id")
    compare.add_argument("--out", default="data/sfda")
    compare.add_argument("--limit", type=int, default=200, help="rows per section in the report")

    lists = commands.add_parser(
        "sfda-lists", help="crawl the other official SFDA lists, one after another (resumable)"
    )
    _add_fetch_options(lists, default_out="data/lists")
    lists.add_argument("--lists", help="comma-separated list names (default: all but the giants)")
    lists.add_argument(
        "--include-giant",
        action="store_true",
        help="also crawl the three giant lists (days of polite crawling each)",
    )
    lists.add_argument("--max-pages", type=int, help="only crawl this many pages per list (sample)")
    lists.add_argument("--show", action="store_true", help="print the known lists and stop")

    details = commands.add_parser(
        "sfda-list-details",
        help="fetch the detail pages of list rows that link to one (approvals, shortages)",
    )
    _add_fetch_options(details, default_out="data/lists")
    details.add_argument("--lists", default="drug-approvals,drug-shortage")
    details.add_argument("--list-run-id", default="lists-1", help="the list run to read links from")

    files = commands.add_parser(
        "sfda-list-files",
        help="download the documents (PDFs) that list rows link to, e.g. the safety alerts",
    )
    _add_fetch_options(files, default_out="data/lists")
    files.add_argument("--lists", default="safety-alert")
    files.add_argument("--list-run-id", default="lists-1", help="the list run to read links from")

    texts = commands.add_parser(
        "sfda-list-texts", help="read the text of the downloaded PDFs of a list (no network)"
    )
    texts.add_argument("--out", default="data/lists")
    texts.add_argument("--lists", default="safety-alert")
    texts.add_argument("--list-run-id", default="lists-1")

    ocr = commands.add_parser(
        "sfda-list-ocr",
        help="read scanned PDFs (no text layer) with the Windows OCR; no network, safe to repeat",
    )
    ocr.add_argument("--out", default="data/lists")
    ocr.add_argument("--lists", default="dhpc")
    ocr.add_argument("--list-run-id", default="lists-1")

    images.add_arguments(commands)
    search_cli.add_arguments(commands)
    lists_cli.add_arguments(commands)
    interactions_cli.add_arguments(commands)
    identity_cli.add_arguments(commands)
    relay_cli.add_arguments(commands)
    analytics_cli.add_arguments(commands)
    cache_cli.add_arguments(commands)
    worker_cli.add_arguments(commands)
    labels_cli.add_arguments(commands)
    knowledge_cli.add_arguments(commands)
    pictures_cli.add_arguments(commands)

    load = commands.add_parser(
        "sfda-load", help="load a stored run into the catalog database (safe to repeat)"
    )
    load.add_argument("--run-id", required=True, help="the crawl run to load")
    load.add_argument("--out", default="data/sfda")
    load.add_argument("--batch-size", type=int, default=200)
    load.add_argument("--limit", type=int, help="load only the first N drugs (for a trial)")
    load.add_argument(
        "--from-records",
        action="store_true",
        help="read the run's records.jsonl instead of its stored pages (pages not on this machine)",
    )
    return parser


# ---- small synchronous helpers (file system) ---------------------------------------------------
def _latest_file(root: Path) -> Path:
    return root / "latest.json"


def _read_latest(root: Path) -> str | None:
    path = _latest_file(root)
    if not path.exists():
        return None
    return str(json.loads(path.read_text(encoding="utf-8"))["run_id"])


def _write_latest(root: Path, run_id: str, finished_at: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    payload = {"run_id": run_id, "finished_at": finished_at}
    temporary = _latest_file(root).with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(temporary, _latest_file(root))


def _configure_logging(run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(sys.stderr), logging.FileHandler(run_dir / "crawl.log")],
        force=True,
    )


def _new_run_id(prefix: str = "") -> str:
    return prefix + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _display_names(*record_sets: list[dict[str, Any]]) -> dict[str, str]:
    names: dict[str, str] = {}
    for records in record_sets:
        for record in records:
            names[record["key"]] = record["list"].get("trade_name", "")
    return names


def _write_reports(
    run_dir: Path,
    result: ChangeSet,
    names: dict[str, str],
    old_run: str,
    new_run: str,
) -> None:
    report = changes_to_json(result, names, old_run=old_run, new_run=new_run)
    (run_dir / "changes.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    markdown = render_markdown(result, names, old_run=old_run, new_run=new_run)
    (run_dir / "changes.md").write_text(markdown, encoding="utf-8")


# ---- network -----------------------------------------------------------------------------------
async def _load_robots(
    base_url: str,
    user_agent: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    attempts: int = 4,
) -> RobotsPolicy:
    """Download robots.txt, retrying connection errors: a crawl must not die on a brief reset."""
    async with httpx.AsyncClient(
        headers={"User-Agent": user_agent},
        timeout=30.0,
        follow_redirects=True,
        transport=transport,
    ) as client:
        for attempt in range(1, attempts + 1):
            try:
                response = await client.get(f"{base_url}/robots.txt")
                break
            except httpx.TransportError:
                if attempt == attempts:
                    raise
                await sleep(10.0 * attempt)
    if response.status_code == 404:
        return RobotsPolicy.from_text("", user_agent)
    response.raise_for_status()
    return RobotsPolicy.from_text(response.text, user_agent)


async def _crawl(
    args: argparse.Namespace,
    store: SnapshotStore,
    baseline: dict[str, dict[str, Any]] | None,
) -> tuple[int, dict[str, Any] | None]:
    """Run a full crawl (no baseline) or an update (with a baseline)."""
    log = logging.getLogger("sfda.cli")
    robots = await _load_robots(args.base_url, args.user_agent)
    config = CrawlConfig(
        base_url=args.base_url,
        max_pages=getattr(args, "max_pages", None),
        max_details=getattr(args, "max_details", None),
        user_agent=args.user_agent,
    )
    clock = SystemClock()
    async with PlaywrightPageFetcher(
        user_agent=args.user_agent,
        throttle=Throttle(args.delay, args.jitter),
        clock=clock,
        java_script=args.enable_js,
        headless=not args.headed,
    ) as fetcher:
        crawler = SfdaCrawler(
            fetcher=fetcher, store=store, robots=robots, clock=clock, config=config
        )
        try:
            manifest = (
                await crawler.run()
                if baseline is None
                else await crawler.update(baseline, args.recheck)
            )
        except CrawlError as exc:
            log.error("crawl stopped: %s (run %s can be resumed with --run-id)", exc, store.run_id)
            return EXIT_STOPPED, None
    log.info("finished with status %s: %s", manifest["status"], manifest.get("counts"))
    return (EXIT_OK if manifest["status"] == "complete" else EXIT_PARTIAL), manifest


# ---- commands ----------------------------------------------------------------------------------
async def _sfda_scrape(args: argparse.Namespace) -> int:
    root = Path(args.out)
    store = SnapshotStore(root, args.run_id or _new_run_id())
    _configure_logging(store.run_dir)
    logging.getLogger("sfda.cli").info("run %s, output %s", store.run_id, store.run_dir)

    code, manifest = await _crawl(args, store, baseline=None)
    if manifest is not None and manifest["status"] == "complete":
        _write_latest(root, store.run_id, manifest["finished_at"])
    return code


async def _sfda_update(args: argparse.Namespace) -> int:
    root = Path(args.out)
    baseline_id = args.baseline or _read_latest(root)
    if baseline_id is None:
        print("no baseline run: run `pharmavique sfda-scrape` to completion first", file=sys.stderr)
        return EXIT_NO_BASELINE
    baseline_records = SnapshotStore(root, baseline_id).read_records()
    if not baseline_records:
        print(f"baseline run {baseline_id} has no records", file=sys.stderr)
        return EXIT_NO_BASELINE

    store = SnapshotStore(root, args.run_id or _new_run_id("upd-"))
    _configure_logging(store.run_dir)
    logging.getLogger("sfda.cli").info(
        "update %s against baseline %s (%s drugs)", store.run_id, baseline_id, len(baseline_records)
    )

    code, manifest = await _crawl(args, store, baseline={r["key"]: r for r in baseline_records})
    if manifest is None:
        return code

    new_records = store.read_records()
    result = diff(to_source_records(baseline_records), to_source_records(new_records))
    names = _display_names(baseline_records, new_records)
    _write_reports(store.run_dir, result, names, baseline_id, store.run_id)
    counts = result.counts()
    print(
        f"changes since {baseline_id}: added={counts['added']} removed={counts['removed']} "
        f"changed={counts['changed']} (report: {store.run_dir / 'changes.md'})"
    )
    if manifest["status"] == "complete":
        _write_latest(root, store.run_id, manifest["finished_at"])
    return code


def _selected_lists(args: argparse.Namespace) -> list[ListSpec]:
    if args.lists:
        return [get_list(name.strip()) for name in args.lists.split(",") if name.strip()]
    return [spec for spec in SFDA_LISTS if args.include_giant or not spec.is_giant]


async def _sfda_lists(args: argparse.Namespace) -> int:
    if args.show:
        for spec in SFDA_LISTS:
            size = "giant" if spec.is_giant else "normal"
            print(f"{spec.name:30} {spec.probed_pages:>8} pages  {size:6} {spec.path}")
        return EXIT_OK
    try:
        specs = _selected_lists(args)
    except KeyError as exc:
        print(exc.args[0], file=sys.stderr)
        return EXIT_NO_BASELINE

    root = Path(args.out)
    run_id = args.run_id or _new_run_id()
    log = logging.getLogger("sfda.cli")
    robots = await _load_robots(args.base_url, args.user_agent)
    clock = SystemClock()
    config = ListCrawlConfig(
        base_url=args.base_url, max_pages=args.max_pages, user_agent=args.user_agent
    )
    code = EXIT_OK
    async with PlaywrightPageFetcher(
        user_agent=args.user_agent,
        throttle=Throttle(args.delay, args.jitter),
        clock=clock,
        java_script=args.enable_js,
        headless=not args.headed,
    ) as fetcher:
        for spec in specs:
            store = SnapshotStore(
                root / spec.name, run_id, shard_size=1000 if spec.is_giant else None
            )
            _configure_logging(store.run_dir)
            manifest = store.load_manifest()
            if manifest is not None and manifest.get("status") == "complete":
                log.info("%s is already complete in run %s, skipping", spec.name, run_id)
                continue
            log.info("list %s (run %s, output %s)", spec.name, run_id, store.run_dir)
            crawl_class = StreamingListCrawler if spec.is_giant else ListCrawler
            crawler = crawl_class(
                spec=spec, fetcher=fetcher, store=store, robots=robots, clock=clock, config=config
            )
            try:
                manifest = await crawler.run()
            except SourceBlocked as exc:
                log.error("the site blocked the crawl: %s; stopping the whole queue", exc)
                return EXIT_STOPPED
            except CrawlError as exc:
                log.error("%s stopped: %s (resume with --run-id %s)", spec.name, exc, run_id)
                code = EXIT_PARTIAL
                continue
            log.info("%s finished with status %s", spec.name, manifest["status"])
            if manifest["status"] != "complete":
                code = EXIT_PARTIAL
    return code


def _sfda_diff(args: argparse.Namespace) -> int:
    root = Path(args.out)
    old = SnapshotStore(root, args.old).read_records()
    new = SnapshotStore(root, args.new).read_records()
    if not old or not new:
        print("one of the runs has no records", file=sys.stderr)
        return EXIT_NO_BASELINE
    result = diff(to_source_records(old), to_source_records(new))
    print(
        render_markdown(
            result, _display_names(old, new), old_run=args.old, new_run=args.new, limit=args.limit
        )
    )
    return EXIT_OK


async def _sfda_load(args: argparse.Namespace) -> int:
    secret = get_settings().database_url
    if secret is None:
        print(
            "set PHARMAVIQUE_DATABASE_URL (see .env.example) and run `alembic upgrade heads` first",
            file=sys.stderr,
        )
        return EXIT_NO_BASELINE
    store = SnapshotStore(Path(args.out), args.run_id)
    if not store.run_dir.exists():
        print(f"no stored run at {store.run_dir}", file=sys.stderr)
        return EXIT_NO_BASELINE

    engine = create_engine(secret.get_secret_value())
    try:
        session_factory = create_session_factory(engine)
        clock = SystemClock()

        def unit_of_work() -> SqlAlchemyCatalogUnitOfWork:
            return SqlAlchemyCatalogUnitOfWork(session_factory)

        commands = InProcessCatalogCommands(
            ApplyCatalogChangesHandler(unit_of_work, clock),
            WithdrawProductsHandler(unit_of_work, clock),
        )
        writer = CatalogWriter(
            commands,
            price_currency=SA_PRICE_CURRENCY,
            snapshot_id=args.run_id,
            source_ref=f"{DEFAULT_BASE_URL}/en/drugs-list",
            fallback_time=clock.now(),
        )
        report = await LoadRecordsIntoCatalog(writer, args.batch_size).run(
            JsonlRecords(store) if args.from_records else StoredRecords(store), args.limit
        )
    finally:
        await engine.dispose()

    print(
        f"loaded {report.records} drugs in {report.batches} batches: "
        f"added={report.added} relisted={report.relisted} details_changed={report.details_changed} "
        f"price_changed={report.price_changed} unchanged={report.unchanged}"
    )
    print(
        f"skipped (no usable details)={report.skipped} rejected={len(report.rejected)} "
        f"records with unreadable values kept as text={report.records_with_issues}"
    )
    for key, reason in report.rejected[:10]:
        print(f"  rejected {key}: {reason}")
    return EXIT_OK


async def _sfda_list_details(args: argparse.Namespace) -> int:
    log = logging.getLogger("sfda.cli")
    robots = await _load_robots(args.base_url, args.user_agent)
    clock = SystemClock()
    async with PlaywrightPageFetcher(
        user_agent=args.user_agent,
        throttle=Throttle(args.delay, args.jitter),
        clock=clock,
        java_script=args.enable_js,
        headless=not args.headed,
    ) as fetcher:
        crawler = ListDetailCrawler(fetcher=fetcher, robots=robots, base_url=args.base_url)
        for name in args.lists.split(","):
            run_dir = Path(args.out) / name / args.list_run_id
            records = SnapshotStore(Path(args.out) / name, args.list_run_id).read_records()
            if not records:
                print(f"{name}: no stored records in {run_dir}", file=sys.stderr)
                continue
            try:
                counts = await crawler.run(records, run_dir / "details.jsonl")
            except SourceBlocked as exc:
                log.error("details of %s stopped: %s", name, exc)
                return EXIT_STOPPED
            log.info("details of %s: %s", name, counts)
            print(f"{name}: {counts}")
    return EXIT_OK


async def _sfda_list_files(args: argparse.Namespace) -> int:
    log = logging.getLogger("sfda.cli")
    robots = await _load_robots(args.base_url, args.user_agent)
    async with httpx.AsyncClient(
        headers={"User-Agent": args.user_agent}, timeout=60.0, follow_redirects=True
    ) as client:
        crawler = ListFileCrawler(
            client=client,
            robots=robots,
            throttle=Throttle(args.delay, args.jitter),
            base_url=args.base_url,
        )
        for name in args.lists.split(","):
            run_dir = Path(args.out) / name / args.list_run_id
            records = SnapshotStore(Path(args.out) / name, args.list_run_id).read_records()
            if not records:
                print(f"{name}: no stored records in {run_dir}", file=sys.stderr)
                continue
            try:
                counts = await crawler.run(records, run_dir / "files", run_dir / "files.jsonl")
            except SourceBlocked as exc:
                log.error("files of %s stopped: %s", name, exc)
                return EXIT_STOPPED
            log.info("files of %s: %s", name, counts)
            print(f"{name}: {counts}")
    return EXIT_OK


def _sfda_list_texts(args: argparse.Namespace) -> int:
    for name in args.lists.split(","):
        run_dir = Path(args.out) / name / args.list_run_id
        index = run_dir / "files.jsonl"
        if not index.exists():
            print(f"{name}: no downloaded files at {index}", file=sys.stderr)
            continue
        counts = extract_all(index, run_dir / "files", run_dir / "texts.jsonl")
        print(f"{name}: {counts}")
    return EXIT_OK


def _sfda_list_ocr(args: argparse.Namespace) -> int:
    for name in args.lists.split(","):
        run_dir = Path(args.out) / name / args.list_run_id
        texts = run_dir / "texts.jsonl"
        if not texts.exists():
            print(
                f"{name}: no extracted texts at {texts}; run sfda-list-texts first", file=sys.stderr
            )
            continue
        counts = ocr_empty_texts(texts, run_dir / "files", windows_pdf_ocr)
        print(f"{name} scanned PDFs: {counts}")
        index = run_dir / "files.jsonl"
        if index.exists():
            pictures = ocr_image_texts(index, run_dir / "files", texts, windows_image_ocr)
            print(f"{name} pictures: {pictures}")
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    if args.command == "sfda-scrape":
        return asyncio.run(_sfda_scrape(args))
    if args.command == "sfda-update":
        return asyncio.run(_sfda_update(args))
    if args.command == "sfda-lists":
        return asyncio.run(_sfda_lists(args))
    if args.command == "search-reindex":
        return asyncio.run(search_cli.reindex(args))
    if args.command == "search":
        return asyncio.run(search_cli.lookup(args))
    if args.command == "sfda-images-export":
        return images.export_products(args)
    if args.command == "sfda-images-queries":
        return images.write_queries(args)
    if args.command == "sfda-images":
        return asyncio.run(images.fetch_images(args))
    if args.command == "sfda-images-sitemaps":
        return asyncio.run(images.collect_sitemaps(args))
    if args.command == "sfda-images-sync":
        return asyncio.run(images.sync_images(args))
    if args.command == "sfda-images-verify":
        return images.run_verify(args)
    if args.command == "sfda-images-map":
        return images.run_map(args)
    if args.command == "sfda-images-restore":
        return asyncio.run(images.restore_images(args))
    if args.command == "sfda-images-report":
        return images.report_coverage(args)
    if args.command == "sfda-diff":
        return _sfda_diff(args)
    if args.command == "sfda-list-texts":
        return _sfda_list_texts(args)
    if args.command == "sfda-list-ocr":
        return _sfda_list_ocr(args)
    if args.command == "sfda-list-files":
        return asyncio.run(_sfda_list_files(args))
    if args.command == "sfda-list-details":
        return asyncio.run(_sfda_list_details(args))
    if args.command == "sfda-pictures-load":
        return asyncio.run(pictures_cli.load(args))
    if args.command == "sfda-lists-load":
        return asyncio.run(lists_cli.load(args))
    if args.command == "outbox-relay":
        return asyncio.run(relay_cli.run(args))
    if args.command == "worker":
        return asyncio.run(worker_cli.run(args))
    if args.command == "cache-invalidate":
        return asyncio.run(cache_cli.invalidate(args))
    if args.command == "analytics-rebuild":
        return asyncio.run(analytics_cli.rebuild(args))
    if args.command == "create-operator":
        return asyncio.run(identity_cli.create_operator(args))
    if args.command == "interactions-load-medic":
        return asyncio.run(interactions_cli.load_medic(args))
    if args.command == "interactions-load":
        return asyncio.run(interactions_cli.load(args))
    if args.command == "knowledge-labels":
        return asyncio.run(labels_cli.labels(args))
    if args.command == "knowledge-build":
        return asyncio.run(knowledge_cli.build(args))
    if args.command == "knowledge-embed":
        return asyncio.run(knowledge_cli.embed(args))
    if args.command == "sfda-load":
        return asyncio.run(_sfda_load(args))
    raise AssertionError(f"unhandled command {args.command!r}")  # pragma: no cover


if __name__ == "__main__":
    raise SystemExit(main())
