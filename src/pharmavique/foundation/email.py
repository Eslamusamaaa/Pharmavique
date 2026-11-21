"""Email senders: SMTP for real mail (any provider), and a console one for development.

SMTP uses the standard library in a worker thread, so a slow mail server never blocks the event
loop, and it needs no extra dependency: any provider that offers SMTP works (the choice of provider
is the owner's, Q-38). The password comes from the environment only.
"""

import asyncio
import smtplib
import ssl
from collections.abc import Callable
from email.message import EmailMessage as MimeMessage
from email.utils import formatdate, make_msgid

from pharmavique.shared_kernel.email import EmailError, EmailMessage


class SmtpEmailSender:
    def __init__(
        self,
        host: str,
        port: int,
        sender: str,
        username: str | None = None,
        password: str | None = None,
        starttls: bool = True,
        timeout: float = 15.0,
        connect: Callable[..., smtplib.SMTP] = smtplib.SMTP,
    ) -> None:
        self._host = host
        self._port = port
        self._sender = sender
        self._username = username
        self._password = password
        self._starttls = starttls
        self._timeout = timeout
        self._connect = connect

    def _mime(self, message: EmailMessage) -> MimeMessage:
        mime = MimeMessage()
        mime["From"] = self._sender
        mime["To"] = message.to
        mime["Subject"] = message.subject
        mime["Date"] = formatdate(localtime=False)
        mime["Message-ID"] = make_msgid(domain=self._sender.rsplit("@", 1)[-1].strip("> "))
        if message.unsubscribe_url:
            mime["List-Unsubscribe"] = f"<{message.unsubscribe_url}>"
            mime["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
        mime.set_content(message.text)
        if message.html:
            mime.add_alternative(message.html, subtype="html")
        return mime

    def _send_now(self, message: EmailMessage) -> None:
        mime = self._mime(message)
        with self._connect(self._host, self._port, timeout=self._timeout) as server:
            if self._starttls:
                server.starttls(context=ssl.create_default_context())
            if self._username and self._password:
                server.login(self._username, self._password)
            server.send_message(mime)

    async def send(self, message: EmailMessage) -> None:
        try:
            await asyncio.to_thread(self._send_now, message)
        except (smtplib.SMTPException, OSError) as error:
            # the error text can quote the recipient; keep only its type
            raise EmailError(f"could not send the email ({type(error).__name__})") from error


class ConsoleEmailSender:
    """Prints the email instead of sending it. For development only: it shows the message (a
    verification code included), so it refuses to be built for a production deployment."""

    def __init__(self, write: Callable[[str], None] = print, production: bool = False) -> None:
        if production:
            raise ValueError("the console email sender must not be used in production")
        self._write = write

    async def send(self, message: EmailMessage) -> None:
        self._write(f"--- email to {message.to}: {message.subject}\n{message.text}\n---")
