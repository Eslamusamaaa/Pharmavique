"""Read-only Postgres access for the catalog's queries (no unit of work, no price history)."""

from collections.abc import Sequence
from dataclasses import replace

from sqlalchemy import ColumnElement, cast, func, literal, literal_column, select
from sqlalchemy.dialects.postgresql import ARRAY, aggregate_order_by
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.types import Text

from pharmavique.catalog.application.ports import StoredProduct
from pharmavique.catalog.domain.product import ListingStatus
from pharmavique.catalog.domain.values import ProductId
from pharmavique.catalog.infrastructure.persistence.models import ProductRow
from pharmavique.catalog.infrastructure.persistence.serialization import data_from_json
from pharmavique.shared_kernel.currency import Currency, CurrencyBasis
from pharmavique.shared_kernel.market import Market
from pharmavique.shared_kernel.money import Money
from pharmavique.shared_kernel.provenance import Provenance, TrustLevel


def _stored(row: ProductRow) -> StoredProduct:
    price: Money | None = None
    if row.price_amount is not None and row.price_currency_basis is not None:
        currency = Currency(row.price_currency_code, CurrencyBasis(row.price_currency_basis))
        price = Money(row.price_amount, currency)
    return StoredProduct(
        id=ProductId(Market(row.market), row.register_number),
        data=replace(data_from_json(row.data), price=price),
        listing_status=ListingStatus(row.listing_status),
        provenance=Provenance(
            row.provenance_source,
            row.provenance_source_ref,
            row.provenance_fetched_at,
            row.provenance_snapshot_id,
            TrustLevel(row.provenance_trust),
        ),
    )


def _ingredient_names_key() -> ColumnElement[list[str]]:
    """The product's ingredient names, upper-cased and sorted, as a text array (SQL)."""
    item = func.jsonb_array_elements(ProductRow.data["ingredients"]).table_valued("value")
    name = func.upper(item.c.value.op("->>")(literal_column("'name'")))
    return (
        select(func.array_agg(aggregate_order_by(name, name))).select_from(item).scalar_subquery()
    )


class SqlAlchemyProductReader:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get_many(
        self, market: Market, register_numbers: Sequence[str]
    ) -> list[StoredProduct]:
        if not register_numbers:
            return []
        statement = (
            select(ProductRow)
            .where(
                ProductRow.market == market.value,
                ProductRow.register_number.in_(list(register_numbers)),
            )
            .order_by(ProductRow.register_number)
        )
        async with self._session_factory() as session:
            rows = (await session.execute(statement)).scalars().all()
        return [_stored(row) for row in rows]

    async def page(self, market: Market, after: str | None, limit: int) -> list[StoredProduct]:
        statement = select(ProductRow).where(ProductRow.market == market.value)
        if after is not None:
            statement = statement.where(ProductRow.register_number > after)
        statement = statement.order_by(ProductRow.register_number).limit(limit)
        async with self._session_factory() as session:
            rows = (await session.execute(statement)).scalars().all()
        return [_stored(row) for row in rows]

    async def with_ingredient_set(
        self, market: Market, names: Sequence[str], limit: int
    ) -> list[StoredProduct]:
        wanted = sorted(name.upper() for name in names)
        statement = (
            select(ProductRow)
            .where(
                ProductRow.market == market.value,
                _ingredient_names_key() == cast(literal(wanted, ARRAY(Text)), ARRAY(Text)),
            )
            .order_by(ProductRow.price_amount.asc().nulls_last(), ProductRow.register_number)
            .limit(limit)
        )
        async with self._session_factory() as session:
            rows = (await session.execute(statement)).scalars().all()
        return [_stored(row) for row in rows]
