"""Builds the identity service and the email sender from settings (for the API and the CLI)."""

import hashlib

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pharmavique.bootstrap.settings import Settings
from pharmavique.foundation.clock import SystemClock
from pharmavique.foundation.email import ConsoleEmailSender, SmtpEmailSender
from pharmavique.identity.application.service import IdentityService
from pharmavique.identity.infrastructure.passwords import ScryptPasswordHasher
from pharmavique.identity.infrastructure.postgres import (
    PostgresCodeStore,
    PostgresSessionStore,
    PostgresUserRepository,
)
from pharmavique.identity.infrastructure.tokens import JwtAccessTokens
from pharmavique.shared_kernel.email import EmailSender


def build_email_sender(settings: Settings) -> EmailSender:
    if settings.email_backend == "smtp":
        if not settings.smtp_host:
            raise ValueError("set PHARMAVIQUE_SMTP_HOST to send email through SMTP")
        return SmtpEmailSender(
            settings.smtp_host,
            settings.smtp_port,
            settings.email_from,
            username=settings.smtp_username,
            password=settings.smtp_password.get_secret_value() if settings.smtp_password else None,
            starttls=settings.smtp_starttls,
        )
    return ConsoleEmailSender(production=settings.environment == "prod")


def code_key(jwt_secret: str) -> bytes:
    """The key that protects verification codes, derived so it differs from the signing key."""
    return hashlib.sha256(b"pharmavique-email-codes:" + jwt_secret.encode()).digest()


def build_identity(
    settings: Settings,
    factory: async_sessionmaker[AsyncSession],
    tokens: JwtAccessTokens,
) -> IdentityService:
    assert settings.jwt_secret is not None  # noqa: S101 - callers check this first
    return IdentityService(
        PostgresUserRepository(factory),
        PostgresSessionStore(factory),
        ScryptPasswordHasher(),
        tokens,
        SystemClock(),
        PostgresCodeStore(factory),
        code_key(settings.jwt_secret.get_secret_value()),
    )
