"""Currency with an explicit "unconfirmed" state.

The brief forbids assuming currencies or price units: a market's currency is only confirmed when
its source documents it. Until then the currency is `unconfirmed` and carries no code.
"""

import re
from dataclasses import dataclass
from typing import Self

from pharmavique.shared_kernel.errors import InvariantViolation

_CODE = re.compile(r"[A-Z]{3}")


@dataclass(frozen=True, slots=True)
class Currency:
    code: str | None

    def __post_init__(self) -> None:
        if self.code is not None and not _CODE.fullmatch(self.code):
            raise InvariantViolation(
                f"currency code must be 3 uppercase letters, got {self.code!r}"
            )

    @classmethod
    def confirmed(cls, code: str) -> Self:
        return cls(code)

    @classmethod
    def unconfirmed(cls) -> Self:
        return cls(None)

    @property
    def is_confirmed(self) -> bool:
        return self.code is not None
