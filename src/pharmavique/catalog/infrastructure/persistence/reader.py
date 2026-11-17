"""Read-only Postgres access for the catalog's queries (no unit of work, no price history)."""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pharmavique.catalog.application.ports import StoredProduct
from pharmavique.catalog.domain.product import ListingStatus
from pharmavique.catalog.domain.values import ProductId
from pharmavique.catalog.infrastructure.persistence.models import ProductRow
from pharmavique.catalog.infrastructure.persistence.serialization import data_from_json
from pharmavique.shared_kernel.market import Market


def _stored(row: ProductRow) -> StoredProduct:
    return StoredProduct(
        id=ProductId(Market(row.market), row.register_number),
        data=data_from_json(row.data),
        listing_status=ListingStatus(row.listing_status),
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
