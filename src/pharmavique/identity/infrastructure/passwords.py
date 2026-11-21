"""Password hashing with scrypt from the standard library (no extra dependency).

The stored form is `scrypt$n$r$p$salt$hash` (salt and hash in url-safe base64), so the cost can be
raised later and old hashes still verify. Hashing is CPU and memory heavy on purpose, so it runs in
a worker thread and never blocks the event loop.
"""

import asyncio
import base64
import hashlib
import hmac
import secrets

_N = 2**15
_R = 8
_P = 1
_KEY_LENGTH = 32
_SALT_LENGTH = 16
_MAX_MEMORY = 128 * 1024 * 1024


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(
        password.encode(), salt=salt, n=n, r=r, p=p, dklen=_KEY_LENGTH, maxmem=_MAX_MEMORY
    )


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(_SALT_LENGTH)
    return f"scrypt${_N}${_R}${_P}${_b64(salt)}${_b64(_derive(password, salt, _N, _R, _P))}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, expected = stored.split("$")
        if scheme != "scrypt":
            return False
        actual = _derive(password, _unb64(salt), int(n), int(r), int(p))
        return hmac.compare_digest(actual, _unb64(expected))
    except ValueError:
        return False


class ScryptPasswordHasher:
    async def hash(self, password: str) -> str:
        return await asyncio.to_thread(hash_password, password)

    async def verify(self, password: str, stored: str) -> bool:
        return await asyncio.to_thread(verify_password, password, stored)
