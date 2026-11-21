"""Signed access tokens (JWT, HS256). Short-lived and stateless.

The token carries only what other contexts need to know about the caller: the user id, the role and
the tenant. It carries no email and no health data.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt

from pharmavique.shared_kernel.principal import Principal, Role

ACCESS_MINUTES = 15
_ISSUER = "pharmavique"
_ALGORITHM = "HS256"
MIN_SECRET_LENGTH = 32


class JwtAccessTokens:
    def __init__(self, secret: str) -> None:
        if len(secret) < MIN_SECRET_LENGTH:
            raise ValueError(f"the signing secret needs at least {MIN_SECRET_LENGTH} characters")
        self._secret = secret

    def issue(self, principal: Principal, now: datetime) -> tuple[str, int]:
        lifetime = timedelta(minutes=ACCESS_MINUTES)
        claims = {
            "iss": _ISSUER,
            "sub": str(principal.user_id),
            "role": sorted(r.value for r in principal.roles)[0],
            "tenant": str(principal.tenant_id) if principal.tenant_id else None,
            "iat": int(now.timestamp()),
            "exp": int((now + lifetime).timestamp()),
            "jti": uuid4().hex,
        }
        return jwt.encode(claims, self._secret, algorithm=_ALGORITHM), int(lifetime.total_seconds())

    def verify(self, token: str, now: datetime) -> Principal | None:
        try:
            claims = jwt.decode(
                token,
                self._secret,
                algorithms=[_ALGORITHM],
                issuer=_ISSUER,
                options={"require": ["exp", "iat", "sub", "role"], "verify_exp": False},
            )
            if int(claims["exp"]) <= int(now.astimezone(UTC).timestamp()):
                return None  # checked against our clock, not the library's, so tests can set it
            tenant = claims.get("tenant")
            return Principal(
                UUID(claims["sub"]),
                UUID(tenant) if tenant else None,
                frozenset({Role(claims["role"])}),
            )
        except (jwt.PyJWTError, ValueError, KeyError):
            return None

    def verify_token(self, token: str) -> Principal | None:
        """The `TokenVerifier` contract: verify against the current time."""
        return self.verify(token, datetime.now(UTC))
