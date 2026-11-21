"""`pharmavique notify-emails`: send each person one digest of their new alerts.

Run it after the outbox relay (the daily refresh does) or on its own schedule. Nothing is sent
unless the person confirmed their address and kept email notifications on. It prints how many
people were emailed and how many could not be reached; the exit code is 1 when sending failed.
"""

import argparse
import sys
from typing import Any
from uuid import UUID

from pharmavique.bootstrap.identity_wiring import build_email_sender
from pharmavique.bootstrap.notify_emails import MAX_ALERTS_PER_RUN, send_pending_digests
from pharmavique.bootstrap.settings import get_settings
from pharmavique.bootstrap.unsubscribe import make_token
from pharmavique.catalog.application.queries import ReadProductCardsHandler
from pharmavique.catalog.infrastructure.persistence.reader import SqlAlchemyProductReader
from pharmavique.foundation.clock import SystemClock
from pharmavique.foundation.db.engine import create_engine, create_session_factory
from pharmavique.identity.infrastructure.postgres import PostgresUserDirectory
from pharmavique.watchlist.infrastructure.postgres import PostgresWatchlistStore

EXIT_OK = 0
EXIT_SOME_FAILED = 1
EXIT_NOT_CONFIGURED = 4


def add_arguments(commands: Any) -> None:
    notify = commands.add_parser(
        "notify-emails", help="email each person one digest of their new alerts"
    )
    notify.add_argument("--limit", type=int, default=MAX_ALERTS_PER_RUN, help="alerts per run")


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    if settings.database_url is None or settings.jwt_secret is None:
        print("set PHARMAVIQUE_DATABASE_URL and PHARMAVIQUE_JWT_SECRET first", file=sys.stderr)
        return EXIT_NOT_CONFIGURED
    secret = settings.jwt_secret.get_secret_value()
    base = settings.public_url.rstrip("/")

    def unsubscribe_link(user_id: UUID) -> str | None:
        if not base.startswith("https://"):
            return None  # a link in an email must be https; without a public address, no link
        return f"{base}/v1/auth/unsubscribe?token={make_token(secret, user_id)}"

    engine = create_engine(settings.database_url.get_secret_value())
    try:
        factory = create_session_factory(engine)
        report = await send_pending_digests(
            PostgresWatchlistStore(factory),
            PostgresUserDirectory(factory),
            ReadProductCardsHandler(SqlAlchemyProductReader(factory)),
            build_email_sender(settings),
            SystemClock(),
            unsubscribe_link,
            args.limit,
        )
    finally:
        await engine.dispose()
    print(
        f"emailed {report.emailed} people ({report.alerts_sent} alerts), "
        f"skipped {report.skipped}, failed {report.failed}"
    )
    return EXIT_SOME_FAILED if report.failed else EXIT_OK
