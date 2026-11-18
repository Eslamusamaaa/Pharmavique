"""The Postgres search index against the real database, checked against the in-memory reference."""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pharmavique.foundation.db.engine import create_engine, create_session_factory
from pharmavique.search.domain.documents import ProductKey, ProductToIndex, build_document
from pharmavique.search.infrastructure.memory import InMemorySearchIndex
from pharmavique.search.infrastructure.postgres import PostgresSearchIndex
from pharmavique.shared_kernel.market import Market

pytestmark = pytest.mark.integration


def product(
    number: str,
    name_en: str | None,
    name_ar: str | None = None,
    ingredients: tuple[str, ...] = (),
    withdrawn: bool = False,
) -> ProductToIndex:
    return ProductToIndex(
        key=ProductKey(Market.SA, number),
        trade_name_en=name_en,
        trade_name_ar=name_ar,
        ingredient_names=ingredients,
        marketing_company=None,
        withdrawn=withdrawn,
    )


CATALOG = [
    product("1-100", "PANADOL", "بانادول", ("PARACETAMOL",)),
    product("1-101", "PANADOL EXTRA", "بانادول اكسترا", ("PARACETAMOL", "CAFFEINE")),
    product("1-200", "PANTOLOC", "بانتولوك", ("PANTOPRAZOLE",)),
    product("1-300", "AUGMENTIN", "اوجمنتين", ("AMOXICILLIN", "CLAVULANIC ACID")),
    product("1-301", "AMOXIL", None, ("AMOXICILLIN",)),
    product("1-400", "OLD DRUG", None, ("ACMEDRONE",), withdrawn=True),
    product("1-500", "BRUFEN", "بروفين", ("IBUPROFEN",)),
]


@pytest.fixture
async def session_factory(migrated_url: URL) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(migrated_url.render_as_string(hide_password=False))
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE search.term, search.product CASCADE"))
    yield create_session_factory(engine)
    await engine.dispose()


async def both(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[PostgresSearchIndex, InMemorySearchIndex]:
    postgres, memory = PostgresSearchIndex(session_factory), InMemorySearchIndex()
    documents = [build_document(p) for p in CATALOG]
    await postgres.upsert(documents)
    await memory.upsert(documents)
    return postgres, memory


async def test_an_exact_register_number_finds_its_product_ignoring_case_and_spaces(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    postgres, _ = await both(session_factory)

    hits = await postgres.find_exact(Market.SA, " 1-300 ", include_withdrawn=False)

    assert [h.key.register_number for h in hits] == ["1-300"]
    assert hits[0].score == 1.0


async def test_withdrawn_products_are_hidden_unless_asked_for(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    postgres, _ = await both(session_factory)

    assert await postgres.find_exact(Market.SA, "1-400", include_withdrawn=False) == []
    shown = await postgres.find_similar(Market.SA, "old drug", 10, 0.2, include_withdrawn=True)
    hidden = await postgres.find_similar(Market.SA, "old drug", 10, 0.2, include_withdrawn=False)
    assert [h.key.register_number for h in shown][:1] == ["1-400"]
    assert "1-400" not in [h.key.register_number for h in hidden]


@pytest.mark.parametrize(
    "query",
    ["panadool", "panadol extra", "بنادول", "بانادول اكسترا", "amoxicillin", "brufen", "augmentin"],
)
async def test_the_ranking_matches_the_in_memory_reference(
    session_factory: async_sessionmaker[AsyncSession], query: str
) -> None:
    postgres, memory = await both(session_factory)

    from_postgres = await postgres.find_similar(Market.SA, query, 10, 0.2, include_withdrawn=False)
    from_memory = await memory.find_similar(Market.SA, query, 10, 0.2, include_withdrawn=False)

    assert [h.key for h in from_postgres] == [h.key for h in from_memory]
    for pg_hit, mem_hit in zip(from_postgres, from_memory, strict=True):
        assert pg_hit.score == pytest.approx(mem_hit.score, abs=1e-4)


async def test_a_misspelled_name_still_finds_the_product(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    postgres, _ = await both(session_factory)

    hits = await postgres.find_similar(Market.SA, "panadool", 5, 0.2, include_withdrawn=False)

    assert hits[0].key.register_number == "1-100"


async def test_upserting_again_replaces_the_old_names(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    postgres, _ = await both(session_factory)
    await postgres.upsert([build_document(product("1-500", "NUROFEN", None, ("IBUPROFEN",)))])

    old = await postgres.find_similar(Market.SA, "brufen", 5, 0.5, include_withdrawn=False)
    new = await postgres.find_similar(Market.SA, "nurofen", 5, 0.5, include_withdrawn=False)

    assert "1-500" not in [h.key.register_number for h in old]
    assert new[0].key.register_number == "1-500"


async def test_the_other_market_and_the_limit_are_respected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    postgres, _ = await both(session_factory)

    assert await postgres.find_similar(Market.EG, "panadol", 5, 0.2, include_withdrawn=False) == []
    assert len(await postgres.find_similar(Market.SA, "pan", 1, 0.2, include_withdrawn=False)) == 1


async def test_an_empty_batch_changes_nothing(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    postgres, _ = await both(session_factory)

    await postgres.upsert([])

    assert await postgres.find_exact(Market.SA, "1-100", include_withdrawn=False)
