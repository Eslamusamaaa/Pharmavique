"""Postgres repository for the Product aggregate.

Two guarantees: an update only succeeds if nobody changed the row since it was loaded (optimistic
concurrency on `version`), and price history is append-only (only new price points are inserted).
"""

from collections.abc import Sequence
from dataclasses import replace
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from pharmavique.catalog.application.ports import ConcurrentModification
from pharmavique.catalog.domain.product import ListingStatus, Product
from pharmavique.catalog.domain.values import PricePoint, ProductId
from pharmavique.catalog.infrastructure.persistence.models import PricePointRow, ProductRow
from pharmavique.catalog.infrastructure.persistence.serialization import (
    data_from_json,
    data_to_json,
)
from pharmavique.shared_kernel.currency import Currency, CurrencyBasis
from pharmavique.shared_kernel.market import Market
from pharmavique.shared_kernel.money import Money
from pharmavique.shared_kernel.provenance import Provenance, TrustLevel


def _provenance_values(prefix: str, provenance: Provenance) -> dict[str, Any]:
    return {
        f"{prefix}_source": provenance.source,
        f"{prefix}_source_ref": provenance.source_ref,
        f"{prefix}_fetched_at": provenance.fetched_at,
        f"{prefix}_snapshot_id": provenance.snapshot_id,
        f"{prefix}_trust": provenance.trust.value,
    }


def _provenance_from(row: ProductRow | PricePointRow) -> Provenance:
    return Provenance(
        row.provenance_source,
        row.provenance_source_ref,
        row.provenance_fetched_at,
        row.provenance_snapshot_id,
        TrustLevel(row.provenance_trust),
    )


def _row_values(product: Product) -> dict[str, Any]:
    price = product.data.price
    return {
        "version": product.version,
        "listing_status": product.listing_status.value,
        "status_changed_at": product.status_changed_at,
        "last_seen_at": product.last_seen_at,
        **_provenance_values("provenance", product.provenance),
        "data": data_to_json(product.data),
        "price_amount": price.amount if price else None,
        "price_currency_code": price.currency.code if price else None,
        "price_currency_basis": price.currency.basis.value if price else None,
    }


def _point_rows(product_id: ProductId, points: Sequence[PricePoint]) -> list[PricePointRow]:
    return [
        PricePointRow(
            market=product_id.market.value,
            register_number=product_id.register_number,
            amount=point.price.amount,
            currency_code=point.price.currency.code,
            currency_basis=point.price.currency.basis.value,
            effective_from=point.effective_from,
            **_provenance_values("provenance", point.provenance),
        )
        for point in points
    ]


def _to_point(row: PricePointRow) -> PricePoint:
    currency = Currency(row.currency_code, CurrencyBasis(row.currency_basis))
    return PricePoint(Money(row.amount, currency), row.effective_from, _provenance_from(row))


def _to_product(row: ProductRow, points: Sequence[PricePointRow]) -> Product:
    price: Money | None = None
    if row.price_amount is not None and row.price_currency_basis is not None:
        currency = Currency(row.price_currency_code, CurrencyBasis(row.price_currency_basis))
        price = Money(row.price_amount, currency)
    return Product(
        id=ProductId(Market(row.market), row.register_number),
        data=replace(data_from_json(row.data), price=price),
        listing_status=ListingStatus(row.listing_status),
        status_changed_at=row.status_changed_at,
        last_seen_at=row.last_seen_at,
        price_history=tuple(_to_point(p) for p in points),
        provenance=_provenance_from(row),
        version=row.version,
    )


class SqlAlchemyProductRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        # what each product looked like when loaded: (version, number of price points)
        self._loaded: dict[ProductId, tuple[int, int]] = {}

    async def get(self, product_id: ProductId) -> Product | None:
        key = (ProductRow.market == product_id.market.value) & (
            ProductRow.register_number == product_id.register_number
        )
        row = (
            await self._session.execute(
                select(ProductRow).where(key).execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        points = (
            (
                await self._session.execute(
                    select(PricePointRow)
                    .where(
                        PricePointRow.market == product_id.market.value,
                        PricePointRow.register_number == product_id.register_number,
                    )
                    .order_by(PricePointRow.effective_from, PricePointRow.id)
                )
            )
            .scalars()
            .all()
        )
        self._loaded[product_id] = (row.version, len(points))
        return _to_product(row, points)

    async def add(self, product: Product) -> None:
        self._session.add(
            ProductRow(
                market=product.id.market.value,
                register_number=product.id.register_number,
                **_row_values(product),
            )
        )
        await self._session.flush()  # the product row must exist before its price points
        self._session.add_all(_point_rows(product.id, product.price_history))
        await self._session.flush()
        self._loaded[product.id] = (product.version, len(product.price_history))

    async def save(self, product: Product) -> None:
        loaded = self._loaded.get(product.id)
        if loaded is None:
            raise ConcurrentModification(f"{product.id} was not loaded in this unit of work")
        loaded_version, loaded_points = loaded

        result = cast(
            "CursorResult[Any]",
            await self._session.execute(
                update(ProductRow)
                .where(
                    ProductRow.market == product.id.market.value,
                    ProductRow.register_number == product.id.register_number,
                    ProductRow.version == loaded_version,
                )
                .values(**_row_values(product))
            ),
        )
        if result.rowcount == 0:
            raise ConcurrentModification(f"{product.id} was changed by someone else")

        new_points = product.price_history[loaded_points:]
        if new_points:
            self._session.add_all(_point_rows(product.id, new_points))
            await self._session.flush()
        self._loaded[product.id] = (product.version, len(product.price_history))
