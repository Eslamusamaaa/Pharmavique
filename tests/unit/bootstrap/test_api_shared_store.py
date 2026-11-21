"""The shared store at work in the API: cached answers, one rate limit for all instances."""

from collections.abc import Sequence

import httpx

from pharmavique.bootstrap.api import create_app
from pharmavique.catalog.contracts.queries import CardPage, ProductCard
from pharmavique.foundation.kv import MemoryStore
from pharmavique.search.application.handlers import SearchProductsHandler
from pharmavique.search.domain.documents import ProductKey, ProductToIndex, build_document
from pharmavique.search.infrastructure.memory import InMemorySearchIndex
from pharmavique.shared_kernel.market import Market

CARD = ProductCard(
    market=Market.SA,
    register_number="1-100",
    trade_name_en="PANADOL EXTRA TAB",
    trade_name_ar=None,
    ingredient_names=("PARACETAMOL",),
    dosage_form_en="Tablet",
    dosage_form_ar=None,
    marketing_company="ACME",
    manufacturers=(),
    atc_codes=(),
    listing_status="listed",
    authorization_status=None,
    marketing_status=None,
)


class CountingCatalog:
    def __init__(self) -> None:
        self.lookups = 0

    async def get_cards(
        self, market: Market, register_numbers: Sequence[str]
    ) -> tuple[ProductCard, ...]:
        self.lookups += 1
        return tuple(c for c in (CARD,) if c.register_number in register_numbers)

    async def export_cards(self, market: Market, after: str | None, limit: int) -> CardPage:
        raise NotImplementedError


async def make_app(
    store: MemoryStore | None,
    rate_limit_per_minute: int | None = None,
    heavy_rate_limit_per_minute: int | None = None,
    trusted_proxy_hops: int | None = None,
) -> tuple[httpx.AsyncClient, CountingCatalog]:
    index = InMemorySearchIndex()
    await index.upsert(
        [
            build_document(
                ProductToIndex(
                    key=ProductKey(CARD.market, CARD.register_number),
                    trade_name_en=CARD.trade_name_en,
                    trade_name_ar=None,
                    ingredient_names=CARD.ingredient_names,
                    marketing_company=CARD.marketing_company,
                    withdrawn=False,
                )
            )
        ]
    )
    catalog = CountingCatalog()
    app = create_app(
        search=SearchProductsHandler(index),
        catalog=catalog,
        store=store,
        rate_limit_per_minute=rate_limit_per_minute,
        heavy_rate_limit_per_minute=heavy_rate_limit_per_minute,
        trusted_proxy_hops=trusted_proxy_hops,
    )
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    return client, catalog


async def test_the_second_identical_search_is_served_from_the_cache() -> None:
    client, catalog = await make_app(MemoryStore())
    async with client:
        first = await client.get("/v1/search", params={"q": "panadol"})
        second = await client.get("/v1/search", params={"q": "panadol"})

    assert first.status_code == second.status_code == 200
    assert first.headers["x-cache"] == "miss"
    assert second.headers["x-cache"] == "hit"
    assert second.json() == first.json()
    assert catalog.lookups == 1
    assert "max-age" in second.headers["cache-control"]


async def test_a_different_query_is_not_served_the_other_answer() -> None:
    client, _ = await make_app(MemoryStore())
    async with client:
        await client.get("/v1/search", params={"q": "panadol"})
        other = await client.get("/v1/search", params={"q": "panadol", "limit": 5})

    assert other.headers["x-cache"] == "miss"


async def test_a_missing_drug_is_not_cached() -> None:
    client, catalog = await make_app(MemoryStore())
    async with client:
        first = await client.get("/v1/products/9-999")
        second = await client.get("/v1/products/9-999")

    assert first.status_code == second.status_code == 404
    assert catalog.lookups == 2


async def test_a_found_drug_is_cached() -> None:
    client, catalog = await make_app(MemoryStore())
    async with client:
        await client.get("/v1/products/1-100")
        again = await client.get("/v1/products/1-100")

    assert again.headers["x-cache"] == "hit"
    assert catalog.lookups == 1


async def test_answers_still_work_when_the_store_is_down() -> None:
    store = MemoryStore()
    store.down = True
    client, catalog = await make_app(store)
    async with client:
        first = await client.get("/v1/search", params={"q": "panadol"})
        second = await client.get("/v1/search", params={"q": "panadol"})

    assert first.status_code == second.status_code == 200
    assert catalog.lookups == 2  # nothing cached, nothing failed


async def test_without_a_store_there_is_no_cache_header_and_nothing_breaks() -> None:
    client, _ = await make_app(None)
    async with client:
        response = await client.get("/v1/search", params={"q": "panadol"})

    assert response.status_code == 200
    assert "x-cache" not in response.headers


async def test_the_rate_limit_is_counted_in_the_shared_store_so_instances_agree() -> None:
    store = MemoryStore()
    one, _ = await make_app(store, rate_limit_per_minute=3, heavy_rate_limit_per_minute=0)
    two, _ = await make_app(store, rate_limit_per_minute=3, heavy_rate_limit_per_minute=0)
    async with one, two:
        codes = [
            (await one.get("/metrics")).status_code,
            (await two.get("/metrics")).status_code,
            (await one.get("/metrics")).status_code,
            (await two.get("/metrics")).status_code,  # the fourth call overall, on the other one
        ]

    assert codes == [200, 200, 200, 429]


async def test_the_rate_limit_falls_back_to_a_local_count_when_the_store_is_down() -> None:
    store = MemoryStore()
    store.down = True
    client, _ = await make_app(store, rate_limit_per_minute=2, heavy_rate_limit_per_minute=0)
    async with client:
        codes = [(await client.get("/metrics")).status_code for _ in range(3)]

    assert codes == [200, 200, 429]


async def test_behind_a_trusted_proxy_only_the_entry_our_proxy_appended_counts() -> None:
    client, _ = await make_app(
        None, rate_limit_per_minute=1, heavy_rate_limit_per_minute=0, trusted_proxy_hops=1
    )
    async with client:
        a1 = await client.get("/metrics", headers={"X-Forwarded-For": "1.1.1.1, 10.0.0.1"})
        a2 = await client.get("/metrics", headers={"X-Forwarded-For": "9.9.9.9, 10.0.0.1"})
        a3 = await client.get("/metrics", headers={"X-Forwarded-For": "7.7.7.7, 10.0.0.1"})

    # the entry the balancer appended is the last one, so all three calls share one count
    assert [a1.status_code, a2.status_code, a3.status_code] == [200, 429, 429]


async def test_a_forged_forwarded_header_does_not_help_a_caller_escape_the_limit() -> None:
    client, _ = await make_app(
        None, rate_limit_per_minute=1, heavy_rate_limit_per_minute=0, trusted_proxy_hops=1
    )
    async with client:
        first = await client.get("/metrics", headers={"X-Forwarded-For": "1.1.1.1, 10.0.0.5"})
        second = await client.get("/metrics", headers={"X-Forwarded-For": "2.2.2.2, 10.0.0.5"})

    assert second.status_code == 429
    assert first.status_code == 200


async def test_the_voice_link_store_is_shared() -> None:
    from pharmavique.voice.infrastructure.audio_cache import SharedAudioStore

    store = MemoryStore()
    one, two = SharedAudioStore(store), SharedAudioStore(store)
    key = await one.put(b"audio-bytes", "audio/mpeg")

    assert await two.take(key) == (b"audio-bytes", "audio/mpeg")
    assert await one.take(key) is None  # handed out once


async def test_the_voice_link_store_survives_an_outage_on_one_instance() -> None:
    from pharmavique.voice.infrastructure.audio_cache import SharedAudioStore

    store = MemoryStore()
    store.down = True
    audio = SharedAudioStore(store)
    key = await audio.put(b"x", "audio/wav")

    assert await audio.take(key) == (b"x", "audio/wav")
