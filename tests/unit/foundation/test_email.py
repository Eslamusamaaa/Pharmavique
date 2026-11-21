"""The email message rules and the two senders."""

import smtplib
from types import TracebackType
from typing import Any, Self

import pytest

from pharmavique.foundation.email import ConsoleEmailSender, SmtpEmailSender
from pharmavique.shared_kernel.email import EmailError, EmailMessage
from pharmavique.shared_kernel.errors import InvariantViolation


class FakeSmtp:
    instances: list["FakeSmtp"] = []  # noqa: RUF012 - a test double records every connection

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host, self.port, self.timeout = host, port, timeout
        self.steps: list[str] = []
        self.sent: Any = None
        FakeSmtp.instances.append(self)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    def starttls(self, context: object) -> None:
        self.steps.append("starttls")

    def login(self, username: str, password: str) -> None:
        self.steps.append(f"login:{username}")

    def send_message(self, message: Any) -> None:
        self.steps.append("send")
        self.sent = message


class BrokenSmtp(FakeSmtp):
    def send_message(self, message: Any) -> None:
        raise smtplib.SMTPRecipientsRefused({"someone@example.com": (550, b"no such user")})


def test_a_line_break_in_the_recipient_or_subject_is_refused() -> None:
    with pytest.raises(InvariantViolation):
        EmailMessage("a@b.example\nBcc: x@y.example", "hi", "body")
    with pytest.raises(InvariantViolation):
        EmailMessage("a@b.example", "hi\r\nBcc: x@y.example", "body")


def test_the_recipient_must_look_like_an_address() -> None:
    with pytest.raises(InvariantViolation):
        EmailMessage("not-an-address", "hi", "body")


async def test_smtp_sends_over_starttls_with_login_and_a_text_and_html_body() -> None:
    FakeSmtp.instances.clear()
    sender = SmtpEmailSender(
        "smtp.example", 587, "Pharmavique <no-reply@pharmavique.example>",
        username="user", password="a-test-value", connect=FakeSmtp,  # type: ignore[arg-type]  # noqa: S106
    )  # fmt: skip
    await sender.send(EmailMessage("me@example.com", "Code", "123456", "<b>123456</b>"))

    (smtp,) = FakeSmtp.instances
    assert (smtp.host, smtp.port) == ("smtp.example", 587)
    assert smtp.steps == ["starttls", "login:user", "send"]
    assert smtp.sent["To"] == "me@example.com"
    assert smtp.sent["Subject"] == "Code"
    assert smtp.sent["From"].endswith("<no-reply@pharmavique.example>")
    assert smtp.sent.get_body(("plain",)).get_content().strip() == "123456"
    assert "<b>123456</b>" in smtp.sent.get_body(("html",)).get_content()


async def test_a_message_with_an_unsubscribe_link_carries_the_standard_headers() -> None:
    FakeSmtp.instances.clear()
    sender = SmtpEmailSender(
        "localhost",
        1025,
        "no-reply@pharmavique.example",
        starttls=False,
        connect=FakeSmtp,  # type: ignore[arg-type]
    )
    url = "https://pharmavique.example/v1/auth/unsubscribe?token=abc"
    await sender.send(EmailMessage("me@example.com", "Hi", "x", unsubscribe_url=url))

    sent = FakeSmtp.instances[0].sent
    assert sent["List-Unsubscribe"] == f"<{url}>"
    assert sent["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"


async def test_smtp_without_credentials_does_not_log_in() -> None:
    FakeSmtp.instances.clear()
    sender = SmtpEmailSender(
        "localhost",
        1025,
        "no-reply@pharmavique.example",
        starttls=False,
        connect=FakeSmtp,  # type: ignore[arg-type]
    )
    await sender.send(EmailMessage("me@example.com", "Hi", "x"))
    assert FakeSmtp.instances[0].steps == ["send"]


async def test_a_refusal_becomes_an_email_error_that_does_not_quote_the_address() -> None:
    sender = SmtpEmailSender(
        "smtp.example",
        587,
        "no-reply@pharmavique.example",
        connect=BrokenSmtp,  # type: ignore[arg-type]
    )
    with pytest.raises(EmailError) as caught:
        await sender.send(EmailMessage("someone@example.com", "Hi", "x"))
    assert "someone@example.com" not in str(caught.value)
    assert "SMTPRecipientsRefused" in str(caught.value)


async def test_a_connection_failure_is_an_email_error() -> None:
    def refuse(*args: object, **kwargs: object) -> smtplib.SMTP:
        raise ConnectionRefusedError

    sender = SmtpEmailSender("smtp.example", 587, "no-reply@pharmavique.example", connect=refuse)
    with pytest.raises(EmailError):
        await sender.send(EmailMessage("me@example.com", "Hi", "x"))


async def test_the_console_sender_prints_the_message() -> None:
    lines: list[str] = []
    await ConsoleEmailSender(write=lines.append).send(
        EmailMessage("me@example.com", "Code", "123456")
    )
    assert "123456" in lines[0]
    assert "me@example.com" in lines[0]


def test_the_console_sender_cannot_be_built_for_production() -> None:
    with pytest.raises(ValueError, match="production"):
        ConsoleEmailSender(production=True)


async def test_the_console_sender_prints_arabic_even_when_the_console_cannot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import io
    import sys

    class Cp1252Console:
        """A Windows console: text goes through cp1252 unless bytes are written directly."""

        def __init__(self) -> None:
            self.buffer = io.BytesIO()

        def write(self, text: str) -> int:
            text.encode("cp1252")  # raises UnicodeEncodeError for Arabic, like the real console
            return len(text)

        def flush(self) -> None:
            return None

    console = Cp1252Console()
    monkeypatch.setattr(sys, "stdout", console)

    await ConsoleEmailSender().send(EmailMessage("me@example.com", "رمز", "رمز التأكيد 123456"))

    assert "رمز التأكيد 123456" in console.buffer.getvalue().decode("utf-8")
