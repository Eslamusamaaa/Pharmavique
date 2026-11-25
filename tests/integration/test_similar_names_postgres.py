"""The stored look-alike names against the real database."""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pharmavique.foundation.db.engine import create_engine, create_session_factory
from pharmavique.search.application.ports import StoredSimilarNames
from pharmavique.search.domain.lasa import LasaMatch
from pharmavique.search.infrastructure.similar_names import PostgresSimilarNameStore
from pharmavique.shared_kernel.market import Market

MATCH = LasaMatch("2", "PANADOLE", 0.75, "high", ("sounds_alike", "spelled_alike"))
ARABIC = LasaMatch("2", "بنادوول", 0.6, "medium", ("spelled_alike",))


@pytest.fixture
async def store(migrated_url: URL) -> AsyncIterator[PostgresSimilarNameStore]:
    engine = create_engine(migrated_url.render_as_string(hide_password=False))
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE search.similar_name"))
    factory: async_sessionmaker[AsyncSession] = create_session_factory(engine)
    yield PostgresSimilarNameStore(factory)
    await engine.dispose()


async def test_a_stored_product_comes_back_equal(store: PostgresSimilarNameStore) -> None:
    await store.replace(
        Market.SA, [StoredSimilarNames("1", (MATCH,), (ARABIC,)), StoredSimilarNames("3", (), ())]
    )

    assert await store.find(Market.SA, "1") == StoredSimilarNames("1", (MATCH,), (ARABIC,))
    assert await store.find(Market.SA, "3") == StoredSimilarNames("3", (), ())
    assert await store.find(Market.SA, "9") is None


async def test_a_rebuild_replaces_every_row_of_the_market(store: PostgresSimilarNameStore) -> None:
    await store.replace(Market.SA, [StoredSimilarNames("1", (MATCH,), ())])
    await store.replace(Market.EG, [StoredSimilarNames("1", (), ())])

    await store.replace(Market.SA, [StoredSimilarNames("5", (), ())])

    assert await store.find(Market.SA, "1") is None  # gone from the catalog: gone from here
    assert await store.find(Market.SA, "5") == StoredSimilarNames("5", (), ())
    assert await store.find(Market.EG, "1") is not None  # another market is left alone
