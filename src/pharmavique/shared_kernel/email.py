"""An email to send, and the port that sends it. Adapters live in `foundation`."""

from dataclasses import dataclass
from typing import Protocol

from pharmavique.shared_kernel.errors import InvariantViolation


class EmailError(Exception):
    """The mail server could not be reached or refused the message."""


@dataclass(frozen=True, slots=True)
class EmailMessage:
    to: str
    subject: str
    text: str
    html: str | None = None
    unsubscribe_url: str | None = None  # sent as List-Unsubscribe so mail apps show a button

    def __post_init__(self) -> None:
        # a line break in a header value would let a caller add headers (or recipients)
        for value in (self.to, self.subject):
            if "\r" in value or "\n" in value:
                raise InvariantViolation("an email address or subject cannot contain a line break")
        if self.unsubscribe_url and (
            "\r" in self.unsubscribe_url
            or "\n" in self.unsubscribe_url
            or not self.unsubscribe_url.startswith("https://")
        ):
            raise InvariantViolation("the unsubscribe link must be a single https address")
        if "@" not in self.to:
            raise InvariantViolation("the recipient is not an email address")


class EmailSender(Protocol):
    async def send(self, message: EmailMessage) -> None:
        """Send the message or raise `EmailError`."""
        ...
