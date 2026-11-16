"""Command line entry point: `uv run pharmavique <command>`.

Commands
    sfda-scrape   crawl the public SFDA registered-drugs list (resumable, polite)
"""

import argparse
import asyncio
import logging
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import httpx

from pharmavique.foundation.clock import SystemClock
from pharmavique.foundation.http.robots import RobotsPolicy
from pharmavique.foundation.http.throttle import Throttle
from pharmavique.ingestion.infrastructure.connectors.sfda_web.crawler import (
    CrawlConfig,
    CrawlError,
    SfdaCrawler,
)
from pharmavique.ingestion.infrastructure.connectors.sfda_web.playwright_fetcher import (
    PlaywrightPageFetcher,
)
from pharmavique.ingestion.infrastructure.connectors.sfda_web.store import SnapshotStore

DEFAULT_BASE_URL = "https://www.sfda.gov.sa"
# Generic on purpose: it says what the client is without naming a person or project.
DEFAULT_USER_AGENT = "DrugRegistrySync/0.1 (polite research crawler; throttled; honours robots.txt)"

EXIT_OK = 0
EXIT_PARTIAL = 2
EXIT_STOPPED = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pharmavique")
    commands = parser.add_subparsers(dest="command", required=True)

    scrape = commands.add_parser("sfda-scrape", help="crawl the public SFDA registered-drugs list")
    scrape.add_argument("--out", default="data/sfda", help="folder for run snapshots")
    scrape.add_argument("--run-id", help="reuse an existing run id to resume it")
    scrape.add_argument("--base-url", default=DEFAULT_BASE_URL)
    scrape.add_argument("--max-pages", type=int, help="only crawl this many list pages (sample)")
    scrape.add_argument("--max-details", type=int, help="only fetch details for this many drugs")
    scrape.add_argument("--delay", type=float, default=1.5, help="seconds between requests")
    scrape.add_argument("--jitter", type=float, default=0.5, help="extra random seconds, 0 to N")
    scrape.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    scrape.add_argument("--enable-js", action="store_true", help="run page JavaScript")
    scrape.add_argument("--headed", action="store_true", help="show the browser window")
    return parser


async def _load_robots(base_url: str, user_agent: str) -> RobotsPolicy:
    async with httpx.AsyncClient(
        headers={"User-Agent": user_agent}, timeout=30.0, follow_redirects=True
    ) as client:
        response = await client.get(f"{base_url}/robots.txt")
    if response.status_code == 404:
        return RobotsPolicy.from_text("", user_agent)
    response.raise_for_status()
    return RobotsPolicy.from_text(response.text, user_agent)


def _configure_logging(run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(sys.stderr), logging.FileHandler(run_dir / "crawl.log")],
        force=True,
    )


async def _sfda_scrape(args: argparse.Namespace) -> int:
    run_id = args.run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    store = SnapshotStore(Path(args.out), run_id)
    _configure_logging(store.run_dir)
    log = logging.getLogger("sfda.cli")
    log.info("run %s, output %s", run_id, store.run_dir)

    robots = await _load_robots(args.base_url, args.user_agent)
    config = CrawlConfig(
        base_url=args.base_url,
        max_pages=args.max_pages,
        max_details=args.max_details,
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
            manifest = await crawler.run()
        except CrawlError as exc:
            log.error("crawl stopped: %s (run %s can be resumed with --run-id)", exc, run_id)
            return EXIT_STOPPED

    log.info("finished with status %s: %s", manifest["status"], manifest.get("counts"))
    return EXIT_OK if manifest["status"] == "complete" else EXIT_PARTIAL


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "sfda-scrape":
        return asyncio.run(_sfda_scrape(args))
    raise AssertionError(f"unhandled command {args.command!r}")  # pragma: no cover


if __name__ == "__main__":
    raise SystemExit(main())
