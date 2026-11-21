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
class PriceChange:
    """The last time the registered price changed: from what, to what, and when (from our own
    snapshots, so it only exists once two different prices have been recorded)."""

    old: PriceDetail
    new: PriceDetail
    changed_at: datetime


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
    price_change: PriceChange | None = None


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


@dataclass(frozen=True, slots=True)
class DetailsPage:
    items: tuple[ProductDetails, ...]
    next_after: str | None  # pass as `after` to get the next page; None after the last page


class CatalogDetailsExport(Protocol):
    """Every product in full (ingredients, strengths, price), for other contexts' read models."""

    async def export_details(self, market: Market, after: str | None, limit: int) -> DetailsPage:
        """Products of the market in register-number order, `limit` at a time."""
        ...


@dataclass(frozen=True, slots=True)
class ListQuality:
    """How one official list is loaded and how well its rows are linked to products."""

    list_name: str
    rows: int
    linked_matched: int  # rows with at least one `matched` link
    linked_possible: int  # rows whose best link is only `possible`
    unlinked: int  # rows with no link (many lists are not about drugs at all)
    last_fetched_at: datetime | None


@dataclass(frozen=True, slots=True)
class CatalogQualityStats:
    """Counts of what is missing in the catalog. Products are those listed unless stated."""

    market: Market
    products: int
    listed: int
    withdrawn: int
    listed_without_price: int
    listed_without_ingredients: int
    listed_with_missing_strength: int  # some ingredient has no strength
    listed_without_manufacturer: int
    listed_with_real_picture: int
    listed_with_generated_picture: int
    listed_without_picture: int
    lists: tuple[ListQuality, ...]


class CatalogQuality(Protocol):
    async def quality_stats(self, market: Market) -> CatalogQualityStats: ...


@dataclass(frozen=True, slots=True)
class Pharmacy:
    """A licensed pharmacy from the SFDA list. The list gives a city and a national-address short
    code, never a street or coordinates, so `city` is the finest place known."""

    market: Market
    name: str
    phone: str | None
    region: str | None
    city_key: str | None  # the normalized canonical city; None when the address has no city
    city: str | None
    short_code: str | None
    address: str  # exactly as the source wrote it
    source_ref: str
    fetched_at: datetime | None
    trust: str


@dataclass(frozen=True, slots=True)
class CityLocation:
    """Where a city is (one point), found once by a geocoder, never typed in by hand."""

    market: Market
    city_key: str
    city: str
    latitude: float
    longitude: float
    source: str
    source_ref: str
    fetched_at: datetime
    trust: str  # a geocoder is not an official source: "unofficial_unverified"


class CatalogPharmacies(Protocol):
    async def pharmacies(self, market: Market) -> tuple[Pharmacy, ...]: ...

    async def city_locations(self, market: Market) -> tuple[CityLocation, ...]: ...


class CatalogIngredients(Protocol):
    """The active ingredient names the catalog knows, for pickers and allergy entry."""

    async def find_ingredients(self, market: Market, prefix: str, limit: int) -> tuple[str, ...]:
        """Ingredient names starting with `prefix` (case-insensitive), alphabetical."""
        ...

    async def is_ingredient(self, market: Market, name: str) -> bool:
        """Whether some product has an ingredient with this name (case-insensitive)."""
        ...
