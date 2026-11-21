"""The read model behind the company views: rebuilt from the catalog, kept current by events.

The market map and the gaps come from the products table as of the last rebuild. The radar comes
from the integration events seen since the first rebuild; an event older than that first rebuild is
already part of the state and is not counted, so the first load never floods the radar.
"""

from datetime import timedelta
from decimal import Decimal
from typing import Any

from pharmavique.analytics.application.ports import AnalyticsStore, MarketSource
from pharmavique.analytics.domain.market import (
    Gaps,
    MarketMap,
    MarketProduct,
    build_market_map,
    find_gaps,
)
from pharmavique.analytics.domain.radar import (
    ChangeKind,
    MarketEvent,
    ProjectionStatus,
    RadarItem,
)
from pharmavique.shared_kernel.errors import InvariantViolation
from pharmavique.shared_kernel.events import StoredEvent
from pharmavique.shared_kernel.market import Market
from pharmavique.shared_kernel.ports import Clock

PAGE = 2000
MAX_PRODUCTS = 5000
MAX_DAYS = 365
_KINDS = {
    "catalog.ProductAdded": ChangeKind.ADDED,
    "catalog.ProductRelisted": ChangeKind.RELISTED,
    "catalog.ProductWithdrawn": ChangeKind.WITHDRAWN,
    "catalog.PriceChanged": ChangeKind.PRICE_CHANGED,
}


def _amount(price: Any) -> str | None:
    if not price:
        return None
    try:
        return format(Decimal(str(price["amount"])), "f")
    except (KeyError, ArithmeticError):
        return None


class AnalyticsService:
    def __init__(self, store: AnalyticsStore, source: MarketSource, clock: Clock) -> None:
        self._store = store
        self._source = source
        self._clock = clock

    async def rebuild(self, market: Market) -> int:
        """Re-read every product from the catalog and swap the read model. Returns the count."""
        products: list[MarketProduct] = []
        async for page in self._source.pages(market, PAGE):
            products.extend(page)
        await self._store.replace_products(market.value, products, self._clock.now())
        return len(products)

    async def on_event(self, event: StoredEvent) -> None:
        kind = _KINDS.get(event.event_type)
        if kind is None:
            return
        market = str(event.payload.get("market", ""))
        first = await self._store.first_built_at(market)
        if first is None or event.occurred_at < first:
            return
        old = event.payload.get("old_price")
        new = event.payload.get("new_price")
        shown = new or old or {}
        priced = kind is ChangeKind.PRICE_CHANGED
        await self._store.add_event(
            MarketEvent(
                event_id=event.event_id,
                market=market,
                kind=kind,
                register_number=str(event.payload["register_number"]),
                occurred_at=event.occurred_at,
                old_price=_amount(old) if priced else None,
                new_price=_amount(new) if priced else None,
                currency_code=shown.get("currency_code") if priced else None,
                currency_basis=shown.get("currency_basis") if priced else None,
            )
        )

    @staticmethod
    def _name(ingredient: str) -> str:
        name = ingredient.strip()
        if len(name) < 2 or len(name) > 120:
            raise InvariantViolation("enter an active ingredient name")
        return name

    async def market_map(self, market: Market, ingredient: str) -> MarketMap:
        name = self._name(ingredient)
        rows = await self._store.products_with_ingredient(market.value, name.upper(), MAX_PRODUCTS)
        return build_market_map(name, rows)

    async def gaps(self, market: Market, ingredient: str, thin_at: int) -> Gaps:
        name = self._name(ingredient)
        rows = await self._store.products_with_ingredient(market.value, name.upper(), MAX_PRODUCTS)
        return find_gaps(name, rows, thin_at)

    async def radar(
        self, market: Market, ingredient: str | None, days: int, limit: int
    ) -> list[RadarItem]:
        if not 1 <= days <= MAX_DAYS:
            raise InvariantViolation(f"days must be between 1 and {MAX_DAYS}")
        name = self._name(ingredient).upper() if ingredient else None
        since = self._clock.now() - timedelta(days=days)
        return await self._store.radar(market.value, name, since, limit)

    async def status(self, market: Market) -> ProjectionStatus:
        return await self._store.status(market.value, self._clock.now())
