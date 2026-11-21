"""The Redis store and the read cache against the real Redis from docker compose."""

import asyncio
import uuid
from collections.abc import AsyncIterator

import pytest
from redis.asyncio import Redis
from redis.exceptions import RedisError

from pharmavique.bootstrap.settings import Settings
from pharmavique.foundation.kv import RedisStore, StoreUnavailable, redis_client
from pharmavique.foundation.read_cache import ReadCache

pytestmark = pytest.mark.integration


@pytest.fixture
async def store() -> AsyncIterator[RedisStore]:
    secret = Settings().redis_url
    if secret is None:
        pytest.skip("PHARMAVIQUE_REDIS_URL is not set (copy .env.example to .env)")
    client = redis_client(secret.get_secret_value(), timeout=1.0)
    try:
        await client.ping()
    except (OSError, RedisError) as error:
        await client.aclose()
        pytest.skip(f"Redis is not reachable ({error}); run `docker compose up -d redis`")
    yield RedisStore(client)
    await client.aclose()


@pytest.fixture
def key() -> str:
    return f"pv:test:{uuid.uuid4().hex}"


async def test_set_get_getdel_and_expiry(store: RedisStore, key: str) -> None:
    await store.set(key, b"value", 1)
    assert await store.get(key) == b"value"
    assert await store.getdel(key) == b"value"
    assert await store.get(key) is None
    await store.set(key, b"short", 1)
    await asyncio.sleep(1.3)
    assert await store.get(key) is None


async def test_a_window_counts_atomically_and_reports_the_time_left(
    store: RedisStore, key: str
) -> None:
    first = await store.window_hit(key, 30)
    second = await store.window_hit(key, 30)
    assert first[0] == 1
    assert second[0] == 2
    assert 1 <= second[1] <= 30
    await store.delete(key)


async def test_a_crowd_of_concurrent_hits_is_counted_exactly(store: RedisStore, key: str) -> None:
    results = await asyncio.gather(*(store.window_hit(key, 30) for _ in range(50)))
    assert sorted(count for count, _ in results) == list(range(1, 51))
    await store.delete(key)


async def test_the_read_cache_works_and_invalidates_on_redis(store: RedisStore) -> None:
    cache = ReadCache(store, version_cache_seconds=0)
    ns = f"t{uuid.uuid4().hex[:6]}"
    calls = 0

    async def compute() -> bytes:
        nonlocal calls
        calls += 1
        return b"body"

    assert await cache.fetch(ns, ["x"], compute) == (b"body", False)
    assert await cache.fetch(ns, ["x"], compute) == (b"body", True)
    await cache.invalidate_all()
    assert await cache.fetch(ns, ["x"], compute) == (b"body", False)
    assert calls == 2


async def test_an_unreachable_redis_raises_store_unavailable() -> None:
    client = Redis.from_url("redis://127.0.0.1:1/0", socket_timeout=0.2, socket_connect_timeout=0.2)
    store = RedisStore(client)
    with pytest.raises(StoreUnavailable):
        await store.get("anything")
    await client.aclose()
