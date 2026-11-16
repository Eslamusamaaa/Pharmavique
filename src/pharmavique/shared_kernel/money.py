"""Money: a non-negative decimal amount plus its (possibly unconfirmed) currency."""

from dataclasses import dataclass
from decimal import Decimal

from pharmavique.shared_kernel.currency import Currency
from pharmavique.shared_kernel.errors import InvariantViolation


@dataclass(frozen=True, slots=True)
class Money:
    amount: Decimal
    currency: Currency

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal):
            raise InvariantViolation("money amount must be a Decimal, never a float")
        if not self.amount.is_finite():
            raise InvariantViolation("money amount must be finite")
        if self.amount < 0:
            raise InvariantViolation("money amount must not be negative")
