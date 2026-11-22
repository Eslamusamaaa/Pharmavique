"""The alert digest email: who gets one, what it says, and when an alert counts as handled."""

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from pharmavique.bootstrap.digest_email import MAX_LINES, build_digest
from pharmavique.bootstrap.notify_emails import DigestReport, send_pending_digests
from pharmavique.bootstrap.unsubscribe import make_token, read_token
from pharmavique.catalog.contracts.queries import CardPage, ProductCard
from pharmavique.identity.contracts import Contact
from pharmavique.shared_kernel.email import EmailError, EmailMessage
from pharmavique.shared_kernel.errors import InvariantViolation
from pharmavique.shared_kernel.market import Market
from pharmavique.watchlist.domain.model import Alert, AlertKind

NOW = datetime(2026, 11, 22, 9, 0, tzinfo=UTC)
SECRET = "s" * 40


def alert(
    user: UUID,
    register: str = "1",
    kind: AlertKind = AlertKind.PRICE_CHANGED,
    **details: str,
) -> Alert:
    return Alert(
        id=uuid4(), user_id=user, kind=kind, register_number=register, event_id=uuid4(),
        occurred_at=NOW, details=details or {"old_price": "5", "new_price": "6.5"},
        created_at=NOW, read_at=None,
    )  # fmt: skip


class Store:
    def __init__(self, pending: list[Alert]) -> None:
        self.pending = pending
        self.handled: set[UUID] = set()

    async def pending_email_alerts(self, limit: int) -> list[Alert]:
        return [a for a in self.pending if a.id not in self.handled][:limit]

    async def mark_emailed(self, alert_ids: Iterable[UUID], at: datetime) -> None:
        self.handled |= set(alert_ids)


class Directory:
    def __init__(self, contacts: dict[UUID, Contact]) -> None:
        self.contacts_by = contacts

    async def contacts(self, user_ids: Iterable[UUID]) -> dict[UUID, Contact]:
        return {u: self.contacts_by[u] for u in user_ids if u in self.contacts_by}


class Catalog:
    async def get_cards(
        self, market: Market, register_numbers: Sequence[str]
    ) -> tuple[ProductCard, ...]:
        names = {"1": "PANADOL EXTRA", "2": "BRUFEN 400"}
        return tuple(
            ProductCard(
                market=Market.SA,
                register_number=n,
                trade_name_en=names[n],
                trade_name_ar=None,
                ingredient_names=(),
                dosage_form_en=None,
                dosage_form_ar=None,
                marketing_company=None,
                manufacturers=(),
                atc_codes=(),
                listing_status="listed",
                authorization_status=None,
                marketing_status=None,
            )
            for n in register_numbers
            if n in names
        )

    async def export_cards(self, market: Market, after: str | None, limit: int) -> CardPage:
        raise NotImplementedError


class Sender:
    def __init__(self, fail_for: set[str] | None = None) -> None:
        self.sent: list[EmailMessage] = []
        self.fail_for = fail_for or set()

    async def send(self, message: EmailMessage) -> None:
        if message.to in self.fail_for:
            raise EmailError("down")
        self.sent.append(message)


class Clock:
    def now(self) -> datetime:
        return NOW


def link(user: UUID) -> str | None:
    return f"https://pharmavique.example/v1/auth/unsubscribe?token={make_token(SECRET, user)}"


async def run(store: Store, directory: Directory, sender: Sender) -> DigestReport:
    return await send_pending_digests(store, directory, Catalog(), sender, Clock(), link)


async def test_one_email_per_person_with_every_alert_in_it_and_the_alerts_marked() -> None:
    ana, omar = uuid4(), uuid4()
    store = Store([alert(ana, "1"), alert(ana, "2", AlertKind.WITHDRAWN), alert(omar, "1")])
    sender = Sender()

    report = await run(
        store,
        Directory({ana: Contact("ana@example.com", True), omar: Contact("omar@example.com", True)}),
        sender,
    )

    assert (report.emailed, report.alerts_sent, report.skipped, report.failed) == (2, 3, 0, 0)
    assert sorted(m.to for m in sender.sent) == ["ana@example.com", "omar@example.com"]
    to_ana = next(m for m in sender.sent if m.to == "ana@example.com")
    assert "PANADOL EXTRA" in to_ana.text
    assert "BRUFEN 400" in to_ana.text
    assert len(store.handled) == 3
    assert await store.pending_email_alerts(10) == []  # a second run sends nothing


async def test_a_person_who_turned_email_off_gets_nothing_but_their_alerts_are_handled() -> None:
    ana = uuid4()
    store = Store([alert(ana)])
    sender = Sender()

    report = await run(store, Directory({ana: Contact("ana@example.com", False)}), sender)

    assert sender.sent == []
    assert report.skipped == 1
    assert len(store.handled) == 1  # not read again on every run


async def test_an_unconfirmed_or_unknown_address_gets_nothing() -> None:
    ghost = uuid4()
    store = Store([alert(ghost)])
    sender = Sender()

    report = await run(store, Directory({}), sender)  # the directory only lists confirmed ones

    assert sender.sent == []
    assert report.skipped == 1


async def test_a_failed_send_leaves_the_alerts_for_the_next_run_and_does_not_stop_the_others() -> (
    None
):
    ana, omar = uuid4(), uuid4()
    store = Store([alert(ana), alert(omar)])
    sender = Sender(fail_for={"ana@example.com"})
    directory = Directory(
        {ana: Contact("ana@example.com", True), omar: Contact("omar@example.com", True)}
    )

    report = await run(store, directory, sender)

    assert (report.emailed, report.failed) == (1, 1)
    assert report.failed_users == [ana]
    assert [a.user_id for a in await store.pending_email_alerts(10)] == [ana]
    sender.fail_for.clear()  # the mail server is back
    again = await run(store, directory, sender)
    assert again.emailed == 1
    assert await store.pending_email_alerts(10) == []


async def test_nothing_waiting_is_a_quiet_run() -> None:
    sender = Sender()
    report = await run(Store([]), Directory({}), sender)
    assert (report.emailed, report.skipped, report.failed) == (0, 0, 0)
    assert sender.sent == []


def test_the_digest_says_what_changed_and_never_what_to_do() -> None:
    user = uuid4()
    message = build_digest(
        "ana@example.com",
        [
            alert(user, "1", old_price="5", new_price="6.5", currency_code="SAR"),
            alert(user, "2", AlertKind.WITHDRAWN),
        ],
        {"1": "PANADOL EXTRA", "2": "BRUFEN 400"},
        "https://pharmavique.example/u",
    )

    assert "PANADOL EXTRA" in message.text
    assert "5 → 6.5 SAR" in message.text
    assert "انسحب من سجل الهيئة" in message.text
    assert "was withdrawn from the SFDA registry" in message.text
    assert "not medical advice" in message.text
    for advice in ("stop taking", "switch to", "اوقف", "بدّل", "غيّر الدواء"):
        assert advice not in message.text.lower()
    assert message.unsubscribe_url == "https://pharmavique.example/u"
    assert "https://pharmavique.example/u" in message.text
    assert "2 " in message.subject


def test_a_price_in_an_assumed_currency_is_marked_as_assumed() -> None:
    message = build_digest(
        "a@example.com",
        [alert(uuid4(), "1", old_price="5", new_price="6", currency_basis="owner_assumption")],
        {"1": "X"},
        None,
    )
    assert "افتراض" in message.text
    assert "assumed" in message.text


def test_a_long_digest_is_capped_and_points_to_the_app() -> None:
    user = uuid4()
    many = [alert(user, "1") for _ in range(MAX_LINES + 5)]
    message = build_digest("a@example.com", many, {"1": "X"}, None)
    assert message.text.count("PANADOL") == 0
    assert message.text.count("- X: ") == MAX_LINES * 2
    assert "5 more in the app" in message.text


def test_without_a_public_address_the_email_points_to_the_app_instead_of_a_link() -> None:
    message = build_digest("a@example.com", [alert(uuid4())], {"1": "X"}, None)
    assert message.unsubscribe_url is None
    assert "Account" in message.text


def test_an_unsubscribe_link_must_be_https() -> None:
    with pytest.raises(InvariantViolation):
        EmailMessage("a@example.com", "s", "t", unsubscribe_url="http://example.com/u")
    with pytest.raises(InvariantViolation):
        EmailMessage("a@example.com", "s", "t", unsubscribe_url="https://x.example/u\nBcc: z@z.z")


def test_an_unsubscribe_token_names_one_account_and_cannot_be_forged() -> None:
    user = uuid4()
    token = make_token(SECRET, user)

    assert read_token(SECRET, token) == user
    assert read_token("another secret entirely", token) is None
    assert (
        read_token(SECRET, make_token(SECRET, uuid4()).split(".")[0] + "." + token.split(".")[1])
        is None
    )
    assert read_token(SECRET, "garbage") is None
    assert read_token(SECRET, "") is None
    assert read_token(SECRET, "nothex." + "0" * 32) is None
