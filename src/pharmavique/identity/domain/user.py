"""Users, their roles and the rules for emails and passwords.

A role is what the person says they are (patient, pharmacist, company); it is not verified yet, so
it only selects which views and saved data they get, never access to another tenant's data. The
operator role cannot be chosen at sign-up: it is made by a command run on the server.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from pharmavique.shared_kernel.errors import DomainError, InvariantViolation
from pharmavique.shared_kernel.principal import Role

CODE_DIGITS = 6
CODE_TTL_MINUTES = 10
CODE_MAX_ATTEMPTS = 5
CODE_RESEND_SECONDS = 60
CODE_MAX_PER_HOUR = 5
MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 200
MAX_EMAIL_LENGTH = 254
SELF_SERVICE_ROLES = frozenset({Role.PATIENT, Role.PHARMACIST, Role.COMPANY})
TENANT_ROLES = frozenset({Role.PHARMACIST, Role.COMPANY})  # these own a tenant (pharmacy, company)

_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,189}\.[^@\s.]{2,}$")


class InvalidCredentials(DomainError):
    """The email or the password is wrong. Deliberately says nothing about which."""


class EmailTaken(DomainError):
    """An account with this email already exists."""


class EmailNotVerified(DomainError):
    """The password is right but the email address has not been confirmed yet."""


class InvalidCode(DomainError):
    """The verification code is wrong, expired or already used. Says nothing about which."""


class CodeLocked(DomainError):
    """Too many wrong codes: ask for a new one."""


class SessionRejected(DomainError):
    """The refresh token is unknown, expired or already used."""


def normalize_email(raw: str) -> str:
    email = raw.strip().lower()
    if len(email) > MAX_EMAIL_LENGTH or _EMAIL.match(email) is None:
        raise InvariantViolation("enter a valid email address")
    return email


def check_password(password: str, email: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise InvariantViolation(f"the password needs at least {MIN_PASSWORD_LENGTH} characters")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise InvariantViolation(f"the password is longer than {MAX_PASSWORD_LENGTH} characters")
    if password.strip().lower() == email:
        raise InvariantViolation("the password must not be the email")


@dataclass(frozen=True, slots=True)
class User:
    id: UUID
    email: str  # normalized: trimmed and lower case
    password_hash: str
    role: Role
    tenant_id: UUID | None  # pharmacists and companies have one; patients and operators do not
    created_at: datetime
    email_verified_at: datetime | None = None  # set when the person enters the emailed code
    email_notifications: bool = True  # may we email them about their saved medicines

    @property
    def verified(self) -> bool:
        return self.email_verified_at is not None
