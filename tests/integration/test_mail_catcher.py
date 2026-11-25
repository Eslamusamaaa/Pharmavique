"""The real SMTP adapter against the local mail catcher (Mailpit), end to end over a socket.

Needs `docker compose --profile mail up -d mailpit`; the tests are skipped when it is not running.
The catcher accepts any message and keeps it for reading through its HTTP API, so nothing leaves
the machine.
"""

import re
import socket
from collections.abc import AsyncIterator
from uuid import uuid4

import httpx
import pytest

from pharmavique.foundation.email import SmtpEmailSender
from pharmavique.identity.application.messages import verification_email
from pharmavique.shared_kernel.email import EmailMessage

pytestmark = pytest.mark.integration

SMTP_PORT = 1025
API = "http://127.0.0.1:8025/api/v1"


def _catcher_is_running() -> bool:
    for port in (SMTP_PORT, 8025):
        with socket.socket() as probe:
            probe.settimeout(0.5)
            if probe.connect_ex(("127.0.0.1", port)) != 0:
                return False
    return True


@pytest.fixture(autouse=True)
def _need_the_catcher() -> None:
    if not _catcher_is_running():
        pytest.skip("start the mail catcher: docker compose --profile mail up -d mailpit")


@pytest.fixture
async def inbox() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(base_url=API, timeout=10) as client:
        yield client


def sender() -> SmtpEmailSender:
    return SmtpEmailSender(
        "127.0.0.1", SMTP_PORT, "Pharmavique <no-reply@localhost>", starttls=False
    )


async def messages_to(inbox: httpx.AsyncClient, address: str) -> list[dict[str, object]]:
    found = (await inbox.get("/search", params={"query": f"to:{address}"})).json()
    return list(found["messages"])


async def test_the_verification_email_reaches_the_catcher_with_its_code(
    inbox: httpx.AsyncClient,
) -> None:
    address = f"{uuid4().hex[:12]}@example.test"

    await sender().send(verification_email(address, "123456", 10))

    (message,) = await messages_to(inbox, address)
    assert "123456" in str(message["Subject"])
    body = (await inbox.get(f"/message/{message['ID']}")).json()
    assert "123456" in body["Text"]
    assert re.search(r"10", body["Text"])
    assert body["From"]["Address"] == "no-reply@localhost"


async def test_arabic_text_and_the_unsubscribe_header_survive_the_trip(
    inbox: httpx.AsyncClient,
) -> None:
    address = f"{uuid4().hex[:12]}@example.test"
    message = EmailMessage(
        to=address,
        subject="تنبيه من فارماڤيك",
        text="تغيّر سعر دواء من أدويتك المحفوظة.",
        unsubscribe_url="https://example.test/unsubscribe?t=abc",
    )

    await sender().send(message)

    (found,) = await messages_to(inbox, address)
    body = (await inbox.get(f"/message/{found['ID']}")).json()
    assert body["Subject"] == "تنبيه من فارماڤيك"
    assert "تغيّر سعر دواء" in body["Text"]
    headers = (await inbox.get(f"/message/{found['ID']}/headers")).json()
    assert headers["List-Unsubscribe"] == ["<https://example.test/unsubscribe?t=abc>"]
