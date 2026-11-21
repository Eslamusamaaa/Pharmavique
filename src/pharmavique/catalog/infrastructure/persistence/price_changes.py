"""Read the last price change of a product, and the ingredient names of the catalog."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pharmavique.catalog.application.ports import PricePair
from pharmavique.shared_kernel.market import Market

_LAST_TWO = text(
    """
    SELECT amount, currency_code, currency_basis, effective_from
    FROM catalog.price_history
    WHERE market = :market AND register_number = :register
    ORDER BY effective_from DESC, id DESC
    LIMIT 2
    """
)
_FIND = text(
    """
    SELECT DISTINCT upper(line.value ->> 'name') AS name
    FROM catalog.products p, jsonb_array_elements(p.data -> 'ingredients') AS line(value)
    WHERE p.market = :market AND upper(line.value ->> 'name') LIKE :pattern ESCAPE '\\'
    ORDER BY name
    LIMIT :n
    """
)
_EXISTS = text(
    """
    SELECT 1
    FROM catalog.products p, jsonb_array_elements(p.data -> 'ingredients') AS line(value)
    WHERE p.market = :market AND upper(line.value ->> 'name') = upper(:name)
    LIMIT 1
    """
)


def _like_prefix(prefix: str) -> str:
    escaped = prefix.upper().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return escaped + "%"


class SqlAlchemyPriceChangeReader:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def last_change(self, market: Market, register_number: str) -> PricePair | None:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    _LAST_TWO, {"market": market.value, "register": register_number}
                )
            ).all()
        if len(rows) < 2:
            return None
        new, old = rows
        if (new.amount, new.currency_code) == (old.amount, old.currency_code):
            return None  # the same price recorded again is not a change
        return PricePair(
            old.amount,
            old.currency_code,
            old.currency_basis,
            new.amount,
            new.currency_code,
            new.currency_basis,
            new.effective_from,
        )


class SqlAlchemyIngredientReader:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def find_ingredients(self, market: Market, prefix: str, limit: int) -> tuple[str, ...]:
        async with self._session_factory() as session:
            rows = await session.execute(
                _FIND, {"market": market.value, "pattern": _like_prefix(prefix.strip()), "n": limit}
            )
            return tuple(r.name for r in rows if r.name)

    async def is_ingredient(self, market: Market, name: str) -> bool:
        if not name.strip():
            return False
        async with self._session_factory() as session:
            row = (
                await session.execute(_EXISTS, {"market": market.value, "name": name.strip()})
            ).first()
        return row is not None
