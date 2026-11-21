"""What the analytics read model needs from the outside."""

from collections.abc import AsyncIterator, Sequence
from datetime import datetime
from typing import Protocol

from pharmavique.analytics.domain.market import MarketProduct
from pharmavique.analytics.domain.radar import MarketEvent, ProjectionStatus, RadarItem
from pharmavique.shared_kernel.market import Market


class MarketSource(Protocol):
    """Every product of a market, in pages (the catalog, through its published contract)."""

    def pages(self, market: Market, page_size: int) -> AsyncIterator[Sequence[MarketProduct]]: ...


class AnalyticsStore(Protocol):
    async def replace_products(
        self, market: str, products: Sequence[MarketProduct], built_at: datetime
    ) -> None:
        """Swap the market's rows for these in one transaction (readers never see half)."""
        ...

    async def products_with_ingredient(
        self, market: str, ingredient: str, limit: int
    ) -> list[MarketProduct]: ...

    async def add_event(self, event: MarketEvent) -> bool:
        """Keep the event; False when this event id was already kept (re-delivery)."""
        ...

    async def radar(
        self, market: str, ingredient: str | None, since: datetime, limit: int
    ) -> list[RadarItem]: ...

    async def first_built_at(self, market: str) -> datetime | None: ...

    async def status(self, market: str, now: datetime) -> ProjectionStatus: ...
