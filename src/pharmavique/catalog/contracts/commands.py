"""Commands other contexts may send to the catalog (published language).

Plain frozen dataclasses made of shared-kernel types and primitives: no catalog internals, no
framework. Ingestion translates its source into `ProductSnapshot`; the catalog never sees SFDA's
page layout.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from pharmavique.shared_kernel.market import Market
from pharmavique.shared_kernel.money import Money
from pharmavique.shared_kernel.provenance import Provenance


@dataclass(frozen=True, slots=True)
class IngredientLineDto:
    name: str
    strength: Decimal | None = None
    unit: str | None = None


@dataclass(frozen=True, slots=True)
class PartyDto:
    name: str
    country: str | None = None


@dataclass(frozen=True, slots=True)
class ProductSnapshot:
    """What the source says about one product at one moment. `None` means "not stated"."""

    market: Market
    register_number: str
    trade_name_en: str | None
    trade_name_ar: str | None
    ingredients: tuple[IngredientLineDto, ...]
    dosage_form_en: str | None
    dosage_form_ar: str | None
    route_en: str | None = None
    route_ar: str | None = None
    package_size: Decimal | None = None
    package_size_unit: str | None = None
    package_type: str | None = None
    package_count: int | None = None
    legal_status: str | None = None
    product_control: str | None = None
    distribution_site: str | None = None
    authorization_status: str | None = None
    marketing_status: str | None = None
    atc_codes: tuple[str, ...] = ()
    shelf_life: str | None = None
    storage_conditions_en: str | None = None
    storage_conditions_ar: str | None = None
    manufacturers: tuple[PartyDto, ...] = ()
    marketing_company: PartyDto | None = None
    agents: tuple[str, ...] = ()
    description_code: str | None = None
    price: Money | None = None


@dataclass(frozen=True, slots=True)
class ApplyCatalogChanges:
    """Bring these products up to date. Idempotent: sending the same batch twice changes nothing."""

    snapshots: tuple[ProductSnapshot, ...]
    provenance: Provenance


@dataclass(frozen=True, slots=True)
class RejectedSnapshot:
    register_number: str
    reason: str


@dataclass(frozen=True, slots=True)
class ApplyCatalogChangesResult:
    added: int
    relisted: int
    details_changed: int
    price_changed: int
    unchanged: int
    rejected: tuple[RejectedSnapshot, ...]


@dataclass(frozen=True, slots=True)
class WithdrawProducts:
    """These products are confirmed gone from the source's list. Idempotent."""

    market: Market
    register_numbers: tuple[str, ...]
    provenance: Provenance


@dataclass(frozen=True, slots=True)
class WithdrawProductsResult:
    withdrawn: int
    already_withdrawn: int
    unknown: int


class CatalogCommands(Protocol):
    async def apply_changes(self, command: ApplyCatalogChanges) -> ApplyCatalogChangesResult: ...

    async def withdraw(self, command: WithdrawProducts) -> WithdrawProductsResult: ...
