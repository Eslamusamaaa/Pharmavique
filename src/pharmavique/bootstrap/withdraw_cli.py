"""`pharmavique sfda-withdraw-absent`: withdraw drugs that left the SFDA list, with safeguards.

The rule is in `ingestion.application.withdrawals`: a drug is withdrawn only after a complete run
and only when it was missing from the run before as well, and never in a larger batch than
`--max-withdrawals`. Run it after `sfda-load`, before the outbox relay, so the withdrawal alerts
are created in the same daily refresh. Use `--dry-run` to see the plan without changing anything.
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from pharmavique.bootstrap.settings import get_settings
from pharmavique.catalog.application.handlers import (
    ApplyCatalogChangesHandler,
    WithdrawProductsHandler,
)
from pharmavique.catalog.application.queries import ReadProductCardsHandler
from pharmavique.catalog.contracts.commands import WithdrawProducts
from pharmavique.catalog.infrastructure.persistence.reader import SqlAlchemyProductReader
from pharmavique.catalog.infrastructure.persistence.unit_of_work import SqlAlchemyCatalogUnitOfWork
from pharmavique.catalog.presentation.inprocess import InProcessCatalogCommands
from pharmavique.foundation.clock import SystemClock
from pharmavique.foundation.db.engine import create_engine, create_session_factory
from pharmavique.ingestion.application.withdrawals import plan_withdrawals
from pharmavique.ingestion.infrastructure.adapters.catalog_writer import SOURCE
from pharmavique.ingestion.infrastructure.connectors.sfda_web.store import SnapshotStore
from pharmavique.shared_kernel.market import Market
from pharmavique.shared_kernel.provenance import Provenance, TrustLevel

EXIT_OK = 0
EXIT_BLOCKED = 2  # nothing withdrawn because a safeguard held
EXIT_NO_INPUT = 4
_PAGE = 500
_LIST_URL = "https://www.sfda.gov.sa/en/drugs-list"


def add_arguments(commands: Any) -> None:
    withdraw = commands.add_parser(
        "sfda-withdraw-absent",
        help="withdraw drugs missing from two complete runs in a row (with safeguards)",
    )
    withdraw.add_argument("--out", default="data/sfda", help="folder of run snapshots")
    withdraw.add_argument("--run-id", required=True, help="the run just made")
    withdraw.add_argument("--baseline", required=True, help="the run it was compared with")
    withdraw.add_argument(
        "--max-withdrawals",
        type=int,
        default=50,
        help="most drugs withdrawn at once; more than this withdraws none (a guess to tune)",
    )
    withdraw.add_argument("--dry-run", action="store_true", help="print the plan, change nothing")


async def withdraw_absent(args: argparse.Namespace) -> int:
    settings = get_settings()
    if settings.database_url is None:
        print("set PHARMAVIQUE_DATABASE_URL first", file=sys.stderr)
        return EXIT_NO_INPUT
    run = SnapshotStore(Path(args.out), args.run_id)
    baseline = SnapshotStore(Path(args.out), args.baseline)
    manifest = run.load_manifest()
    if manifest is None or not run.run_dir.exists():
        print(f"no stored run {args.run_id} in {args.out}", file=sys.stderr)
        return EXIT_NO_INPUT
    baseline_records = baseline.read_records()
    if not baseline_records:
        print(f"baseline {args.baseline} has no records", file=sys.stderr)
        return EXIT_NO_INPUT

    seen_now = {str(r["key"]) for r in run.read_records()}
    seen_before = {str(r["key"]) for r in baseline_records}
    clock = SystemClock()
    engine = create_engine(settings.database_url.get_secret_value())
    try:
        factory = create_session_factory(engine)
        listed = await _listed_register_numbers(
            ReadProductCardsHandler(SqlAlchemyProductReader(factory))
        )
        plan = plan_withdrawals(
            listed=listed,
            seen_now=seen_now,
            seen_before=seen_before,
            run_is_clean=manifest.get("status") == "complete",
            max_withdrawals=args.max_withdrawals,
        )
        print(
            f"listed in the catalog: {len(listed)}; pending (missing once): {len(plan.pending)}; "
            f"to withdraw: {len(plan.to_withdraw)}"
        )
        for key in plan.pending[:20]:
            print(f"  pending {key}")
        for key in plan.to_withdraw[:20]:
            print(f"  withdraw {key}")
        if plan.blocked_reason is not None:
            print(f"blocked: {plan.blocked_reason}")
            return EXIT_BLOCKED
        if args.dry_run or not plan.to_withdraw:
            return EXIT_OK

        def unit_of_work() -> SqlAlchemyCatalogUnitOfWork:
            return SqlAlchemyCatalogUnitOfWork(factory)

        commands = InProcessCatalogCommands(
            ApplyCatalogChangesHandler(unit_of_work, clock),
            WithdrawProductsHandler(unit_of_work, clock),
        )
        finished = manifest.get("finished_at")
        result = await commands.withdraw(
            WithdrawProducts(
                market=Market.SA,
                register_numbers=plan.to_withdraw,
                provenance=Provenance(
                    source=SOURCE,
                    source_ref=_LIST_URL,
                    fetched_at=datetime.fromisoformat(finished) if finished else clock.now(),
                    snapshot_id=args.run_id,
                    trust=TrustLevel.OFFICIAL,
                ),
            )
        )
        print(
            f"withdrawn={result.withdrawn} already_withdrawn={result.already_withdrawn} "
            f"unknown={result.unknown}"
        )
    finally:
        await engine.dispose()
    return EXIT_OK


async def _listed_register_numbers(cards: ReadProductCardsHandler) -> set[str]:
    listed: set[str] = set()
    after: str | None = None
    while True:
        page = await cards.export_cards(Market.SA, after, _PAGE)
        listed.update(c.register_number for c in page.cards if c.listing_status == "listed")
        if page.next_after is None:
            return listed
        after = page.next_after
