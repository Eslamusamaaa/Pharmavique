"""Signed "unsubscribe" links for notification emails.

The link names one account and is signed with a key derived from the server secret, so nobody can
make a link for someone else's account. It only ever switches that account's email notifications
off; it grants nothing else and does not expire (an old email must keep working).
"""

import hashlib
import hmac
from uuid import UUID


def _key(secret: str) -> bytes:
    return hashlib.sha256(b"pharmavique-unsubscribe:" + secret.encode()).digest()


def make_token(secret: str, user_id: UUID) -> str:
    payload = user_id.hex
    signature = hmac.new(_key(secret), payload.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{payload}.{signature}"


def read_token(secret: str, token: str) -> UUID | None:
    payload, _, signature = token.partition(".")
    expected = hmac.new(_key(secret), payload.encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        return UUID(hex=payload)
    except ValueError:
        return None
