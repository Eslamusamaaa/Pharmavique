"""Email each person one digest of the alerts about their saved medicines.

Joins three contexts without any of them knowing the others: the watchlist (the alerts waiting), the
identity directory (confirmed addresses of people who allow email) and the catalog (medicine names).
One email per person per run however many alerts they have. An alert is marked handled only after
its email was accepted by the mail server, or when the person does not want email; if sending
fails the alerts stay and the next run tries again. The in-app inbox is not touched.
"""

import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from uuid import UUID

from pharmavique.bootstrap.digest_email import build_digest
from pharmavique.catalog.contracts.queries import CatalogQueries
from pharmavique.identity.contracts import UserDirectory
from pharmavique.shared_kernel.email import EmailError, EmailSender
from pharmavique.shared_kernel.market import Market
from pharmavique.shared_kernel.ports import Clock
from pharmavique.watchlist.application.ports import AlertEmailStore
from pharmavique.watchlist.domain.model import Alert

_log = logging.getLogger(__name__)
MAX_ALERTS_PER_RUN = 5000


@dataclass
class DigestReport:
    emailed: int = 0  # people who got a digest
    alerts_sent: int = 0
    skipped: int = 0  # people who do not want email, or whose address is not confirmed
    failed: int = 0  # people whose email could not be sent; their alerts wait for the next run
    failed_users: list[UUID] = field(default_factory=list)


async def send_pending_digests(
    store: AlertEmailStore,
    directory: UserDirectory,
    catalog: CatalogQueries,
    sender: EmailSender,
    clock: Clock,
    unsubscribe_link: Callable[[UUID], str | None],
    limit: int = MAX_ALERTS_PER_RUN,
) -> DigestReport:
    report = DigestReport()
    pending = await store.pending_email_alerts(limit)
    if not pending:
        return report
    by_user: dict[UUID, list[Alert]] = defaultdict(list)
    for alert in pending:
        by_user[alert.user_id].append(alert)
    contacts = await directory.contacts(by_user)
    cards = await catalog.get_cards(Market.SA, sorted({a.register_number for a in pending}))
    names = {
        c.register_number: c.trade_name_en or c.trade_name_ar or c.register_number for c in cards
    }

    for user_id, alerts in by_user.items():
        ids = [a.id for a in alerts]
        contact = contacts.get(user_id)
        if contact is None or not contact.notify:
            await store.mark_emailed(ids, clock.now())  # handled: they do not want email
            report.skipped += 1
            continue
        message = build_digest(contact.email, alerts, names, unsubscribe_link(user_id))
        try:
            await sender.send(message)
        except EmailError as error:
            _log.warning("a digest could not be sent: %s", error)
            report.failed += 1
            report.failed_users.append(user_id)
            continue
        await store.mark_emailed(ids, clock.now())
        report.emailed += 1
        report.alerts_sent += len(alerts)
    return report
