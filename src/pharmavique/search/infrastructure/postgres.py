"""PostgreSQL search index: exact and fuzzy lookups over the `search` schema with pg_trgm.

It must rank like the in-memory index (the reference): a name scores its trigram similarity to the
query, the ingredients text scores 0.9 of it, a product scores its best term. Two known small
differences: Postgres keeps similarities as 4-byte floats, and pg_trgm splits a word at a dot
("0.5") where the pure-Python copy does not. Names and queries are normalized the same way on both
sides (`shared_kernel.text.normalize_text`), so neither shows up for ordinary drug names.
"""

from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pharmavique.search.application.ports import IndexHit
from pharmavique.search.domain.documents import ProductKey, SearchDocument
from pharmavique.search.infrastructure.memory import INGREDIENT_WEIGHT
from pharmavique.shared_kernel.market import Market

_UPSERT_PRODUCT = text(
    "INSERT INTO search.product (market, register_number, withdrawn) "
    "VALUES (:market, :register_number, :withdrawn) "
    "ON CONFLICT (market, register_number) DO UPDATE SET withdrawn = EXCLUDED.withdrawn"
)
_DELETE_TERMS = text(
    "DELETE FROM search.term WHERE market = :market AND register_number = :register_number"
)
_INSERT_TERM = text(
    "INSERT INTO search.term (market, register_number, kind, text) "
    "VALUES (:market, :register_number, :kind, :text)"
)
_FIND_EXACT = text(
    "SELECT market, register_number FROM search.product "
    "WHERE market = :market AND lower(register_number) = lower(:register_number) "
    "AND (:include_withdrawn OR NOT withdrawn) ORDER BY register_number"
)
_FIND_SIMILAR = text(
    """
    SELECT t.register_number,
           max(similarity(t.text, :query)
               * CASE WHEN t.kind = 'ingredient' THEN :ingredient_weight ELSE 1.0 END) AS score
    FROM search.term t
    JOIN search.product p ON p.market = t.market AND p.register_number = t.register_number
    WHERE t.market = :market
      AND t.text % :query
      AND (:include_withdrawn OR NOT p.withdrawn)
    GROUP BY t.register_number
    HAVING max(similarity(t.text, :query)
               * CASE WHEN t.kind = 'ingredient' THEN :ingredient_weight ELSE 1.0 END) >= :min_score
    ORDER BY score DESC, t.register_number ASC
    LIMIT :limit
    """
)


class PostgresSearchIndex:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def upsert(self, documents: Sequence[SearchDocument]) -> None:
        if not documents:
            return
        products = [
            {
                "market": d.key.market.value,
                "register_number": d.key.register_number,
                "withdrawn": d.withdrawn,
            }
            for d in documents
        ]
        keys = [{"market": p["market"], "register_number": p["register_number"]} for p in products]
        terms = [
            {**key, "kind": kind, "text": value}
            for document, key in zip(documents, keys, strict=True)
            for kind, value in _terms_of(document)
        ]
        async with self._session_factory() as session, session.begin():
            await session.execute(_UPSERT_PRODUCT, products)
            await session.execute(_DELETE_TERMS, keys)
            if terms:
                await session.execute(_INSERT_TERM, terms)

    async def find_exact(
        self, market: Market, register_number: str, include_withdrawn: bool
    ) -> list[IndexHit]:
        async with self._session_factory() as session:
            rows = await session.execute(
                _FIND_EXACT,
                {
                    "market": market.value,
                    "register_number": register_number.strip(),
                    "include_withdrawn": include_withdrawn,
                },
            )
            return [IndexHit(ProductKey(Market(r[0]), r[1]), 1.0) for r in rows]

    async def find_similar(
        self,
        market: Market,
        text_: str,
        limit: int,
        min_score: float,
        include_withdrawn: bool,
    ) -> list[IndexHit]:
        async with self._session_factory() as session, session.begin():
            # the `%` operator uses this threshold; scores below it could not reach `min_score`
            await session.execute(
                text("SELECT set_config('pg_trgm.similarity_threshold', :value, true)"),
                {"value": str(max(min(min_score, 1.0), 0.0))},
            )
            rows = await session.execute(
                _FIND_SIMILAR,
                {
                    "market": market.value,
                    "query": text_,
                    "limit": limit,
                    "min_score": min_score,
                    "include_withdrawn": include_withdrawn,
                    "ingredient_weight": INGREDIENT_WEIGHT,
                },
            )
            return [IndexHit(ProductKey(market, r[0]), float(r[1])) for r in rows]


def _terms_of(document: SearchDocument) -> list[tuple[str, str]]:
    terms = [("name", name) for name in document.names if name]
    if document.ingredients:
        terms.append(("ingredient", document.ingredients))
    return terms
