"""What other contexts may use from `identity` (published language)."""

from typing import Protocol

from pharmavique.shared_kernel.principal import Principal


class TokenVerifier(Protocol):
    """Turns a bearer token into the caller, without a call to the identity database."""

    def verify_token(self, token: str) -> Principal | None: ...


__all__ = ["TokenVerifier"]
