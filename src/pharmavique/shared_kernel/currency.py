"""Currency that says how we know it.

The brief forbids assuming currencies or price units silently. A currency therefore carries its
basis: stated by the source, assumed by the project owner (a recorded decision, shown as such),
or unconfirmed (no code at all).
"""

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Self

from pharmavique.shared_kernel.errors import InvariantViolation

_CODE = re.compile(r"[A-Z]{3}")


class CurrencyBasis(StrEnum):
    SOURCE_STATED = "source_stated"
    OWNER_ASSUMPTION = "owner_assumption"
    UNCONFIRMED = "unconfirmed"


@dataclass(frozen=True, slots=True)
class Currency:
    code: str | None
    basis: CurrencyBasis = CurrencyBasis.UNCONFIRMED

    def __post_init__(self) -> None:
        if self.code is None:
            if self.basis is not CurrencyBasis.UNCONFIRMED:
                raise InvariantViolation("a currency without a code can only be unconfirmed")
            return
        if self.basis is CurrencyBasis.UNCONFIRMED:
            raise InvariantViolation("a currency with a code needs a basis other than unconfirmed")
        if not _CODE.fullmatch(self.code):
            raise InvariantViolation(
                f"currency code must be 3 uppercase letters, got {self.code!r}"
            )

    @classmethod
    def confirmed(cls, code: str) -> Self:
        """The source itself states this currency."""
        return cls(code, CurrencyBasis.SOURCE_STATED)

    @classmethod
    def owner_assumed(cls, code: str) -> Self:
        """The source does not state it; the project owner decided it. Always shown as such."""
        return cls(code, CurrencyBasis.OWNER_ASSUMPTION)

    @classmethod
    def unconfirmed(cls) -> Self:
        return cls(None, CurrencyBasis.UNCONFIRMED)

    @property
    def is_confirmed(self) -> bool:
        return self.basis is CurrencyBasis.SOURCE_STATED
