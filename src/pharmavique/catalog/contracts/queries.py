"""What other contexts may read from the catalog (published language).

A `ProductCard` is a flat, read-only summary of one product: enough to search for it, show it in a
list and decide whether to open it. It never carries domain objects. `search` builds its own
projection from cards and can rebuild it at any time from `export_cards`.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from pharmavique.shared_kernel.market import Market

MAX_EXPORT_PAGE = 10_000


@dataclass(frozen=True, slots=True)
class ProductCard:
    market: Market
    register_number: str
    trade_name_en: str | None
    trade_name_ar: str | None
    ingredient_names: tuple[str, ...]
    dosage_form_en: str | None
    dosage_form_ar: str | None
    marketing_company: str | None
    manufacturers: tuple[str, ...]
    atc_codes: tuple[str, ...]
    listing_status: str  # "listed" or "withdrawn"; withdrawn products are still exported
    authorization_status: str | None  # as the source wrote it
    marketing_status: str | None  # as the source wrote it


@dataclass(frozen=True, slots=True)
class CardPage:
    cards: tuple[ProductCard, ...]
    next_after: str | None  # pass as `after` to get the next page; None after the last page


class CatalogQueries(Protocol):
    async def get_cards(
        self, market: Market, register_numbers: Sequence[str]
    ) -> tuple[ProductCard, ...]:
        """Cards for these products. Unknown register numbers are simply absent."""
        ...

    async def export_cards(self, market: Market, after: str | None, limit: int) -> CardPage:
        """Every product of the market in register-number order, `limit` at a time."""
        ...
