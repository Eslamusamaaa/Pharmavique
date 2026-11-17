"""One catalog transaction: repository and outbox share a session and commit together."""

from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pharmavique.catalog.infrastructure.persistence.outbox import SqlAlchemyOutbox
from pharmavique.catalog.infrastructure.persistence.repository import SqlAlchemyProductRepository


class SqlAlchemyCatalogUnitOfWork:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self._products: SqlAlchemyProductRepository | None = None
        self._outbox: SqlAlchemyOutbox | None = None

    async def __aenter__(self) -> Self:
        self._session = self._session_factory()
        self._products = SqlAlchemyProductRepository(self._session)
        self._outbox = SqlAlchemyOutbox(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        session = self._require_session()
        try:
            if exc is not None:
                await session.rollback()
        finally:
            await session.close()

    @property
    def products(self) -> SqlAlchemyProductRepository:
        if self._products is None:
            raise RuntimeError("enter the unit of work first: `async with uow:`")
        return self._products

    @property
    def outbox(self) -> SqlAlchemyOutbox:
        if self._outbox is None:
            raise RuntimeError("enter the unit of work first: `async with uow:`")
        return self._outbox

    async def commit(self) -> None:
        await self._require_session().commit()

    async def rollback(self) -> None:
        await self._require_session().rollback()

    def _require_session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("enter the unit of work first: `async with uow:`")
        return self._session
