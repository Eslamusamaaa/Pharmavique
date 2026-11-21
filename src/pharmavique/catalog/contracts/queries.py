"""What other contexts may read from the catalog (published language).

A `ProductCard` is a flat, read-only summary of one product: enough to search for it, show it in a
list and decide whether to open it. It never carries domain objects. `search` builds its own
projection from cards and can rebuild it at any time from `export_cards`.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
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
    legal_status: str | None = None  # as the source wrote it, for example "OTC" or "Prescription"


@dataclass(frozen=True, slots=True)
class IngredientDetail:
    name: str
    strength: str | None  # as a plain decimal string; None when the source gives none
    unit: str | None


@dataclass(frozen=True, slots=True)
class PriceDetail:
    amount: Decimal
    currency_code: str | None
    currency_basis: str  # "source_stated", "owner_assumption" or "unconfirmed"; always shown


@dataclass(frozen=True, slots=True)
class Maker:
    name: str
    country: str | None


@dataclass(frozen=True, slots=True)
class ProductDetails:
    """Everything the drug page shows about one product, with its provenance.

    Values are as the source states them; `None` means "not stated", never a default.
    """

    card: ProductCard
    ingredients: tuple[IngredientDetail, ...]
    route_en: str | None
    route_ar: str | None
    package_type: str | None
    package_size: int | None
    legal_status: str | None
    distribution_site: str | None
    shelf_life: str | None  # the source states no unit
    storage_en: str | None
    storage_ar: str | None
    marketing_company_country: str | None
    manufacturers: tuple[Maker, ...]
    price: PriceDetail | None
    source: str | None
    source_ref: str | None
    fetched_at: datetime | None
    trust: str | None


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


class CatalogDetails(Protocol):
    """The drug page's read side: one product in full, and products with its ingredients."""

    async def get_details(self, market: Market, register_number: str) -> ProductDetails | None:
        """The full detail view of one product, or None when it is not in the catalog."""
        ...

    async def same_ingredients(
        self, market: Market, register_number: str, limit: int
    ) -> tuple[ProductDetails, ...]:
        """Other products with exactly the same set of active ingredient names.

        Same names only: whether they are interchangeable is decided by `substitution`.
        """
        ...


@dataclass(frozen=True, slots=True)
class ListItem:
    """One row of an official SFDA list that is linked to a product, as the site showed it.

    `confidence` says how sure the link is: `matched` (name and substance agree) or `possible`
    (a person should check). Cells and detail are the site's own label and value pairs.
    """

    list_name: str
    confidence: str
    reason: str
    cells: tuple[tuple[str, str], ...]
    detail: tuple[tuple[str, str], ...]
    facets: tuple[tuple[str, str], ...]
    link: str | None
    source_ref: str
    fetched_at: datetime | None
    trust: str


class CatalogListItems(Protocol):
    """The list rows (shortages, safety notices) linked to one product."""

    async def list_items(
        self, market: Market, register_number: str, list_names: Sequence[str]
    ) -> tuple[ListItem, ...]:
        """Linked rows of these lists, `matched` links first. Empty when none are linked."""
        ...
