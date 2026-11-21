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
