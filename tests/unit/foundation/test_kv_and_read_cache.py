"""The shared key-value store (memory flavour) and the read cache built on it."""

import asyncio

import pytest

from pharmavique.foundation.kv import MemoryStore, StoreUnavailable
from pharmavique.foundation.read_cache import ReadCache


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def store(clock: Clock) -> MemoryStore:
    return MemoryStore(clock)


async def test_values_expire(store: MemoryStore, clock: Clock) -> None:
    await store.set("k", b"v", 10)
    assert await store.get("k") == b"v"
    clock.now += 11
    assert await store.get("k") is None


async def test_getdel_hands_a_value_out_once(store: MemoryStore) -> None:
    await store.set("k", b"v", 10)
    assert await store.getdel("k") == b"v"
    assert await store.getdel("k") is None


async def test_a_window_counts_hits_and_starts_again_after_it_ends(
    store: MemoryStore, clock: Clock
) -> None:
    assert await store.window_hit("w", 60) == (1, 60)
    clock.now += 20
    assert await store.window_hit("w", 60) == (2, 40)
    clock.now += 41
    assert await store.window_hit("w", 60) == (1, 60)


async def test_bump_counts_up_and_never_expires(store: MemoryStore, clock: Clock) -> None:
    assert await store.bump("v") == 1
    clock.now += 10_000
    assert await store.bump("v") == 2


async def test_a_switched_off_store_raises(store: MemoryStore) -> None:
    store.down = True
    with pytest.raises(StoreUnavailable):
        await store.get("k")


class Computer:
    def __init__(self, value: bytes = b"answer") -> None:
        self.calls = 0
        self.value = value
        self.gate: asyncio.Event | None = None

    async def __call__(self) -> bytes:
        self.calls += 1
        if self.gate is not None:
            await self.gate.wait()
        return self.value


async def test_the_second_request_is_served_from_the_cache(store: MemoryStore) -> None:
    cache = ReadCache(store)
    compute = Computer()

    first = await cache.fetch("search", ["q", "10"], compute)
    second = await cache.fetch("search", ["q", "10"], compute)

    assert first == (b"answer", False)
    assert second == (b"answer", True)
    assert compute.calls == 1


async def test_different_requests_do_not_share_an_entry(store: MemoryStore) -> None:
    cache = ReadCache(store)
    compute = Computer()
    await cache.fetch("search", ["a"], compute)
    await cache.fetch("search", ["b"], compute)
    await cache.fetch("page", ["a"], compute)
    assert compute.calls == 3


async def test_invalidating_makes_old_entries_unreadable(store: MemoryStore) -> None:
    cache = ReadCache(store)
    compute = Computer()
    await cache.fetch("search", ["q"], compute)
    await cache.invalidate_all()
    _, hit = await cache.fetch("search", ["q"], compute)
    assert hit is False
    assert compute.calls == 2


async def test_another_instance_notices_a_bump_after_the_short_version_cache(
    store: MemoryStore, clock: Clock
) -> None:
    mine = ReadCache(store, clock=clock)
    theirs = ReadCache(store, clock=clock)
    compute = Computer()
    await mine.fetch("search", ["q"], compute)
    await theirs.invalidate_all()
    assert (await mine.fetch("search", ["q"], compute))[1] is True  # still the cached version
    clock.now += 3
    assert (await mine.fetch("search", ["q"], compute))[1] is False


async def test_entries_expire_by_themselves(store: MemoryStore, clock: Clock) -> None:
    cache = ReadCache(store, ttl_seconds=100, clock=clock)
    compute = Computer()
    await cache.fetch("search", ["q"], compute)
    clock.now += 111  # past the longest jittered lifetime
    assert (await cache.fetch("search", ["q"], compute))[1] is False


async def test_an_outage_serves_from_the_source_and_never_fails(store: MemoryStore) -> None:
    seen: list[tuple[str, str]] = []
    cache = ReadCache(store, observer=lambda ns, result: seen.append((ns, result)))
    store.down = True
    compute = Computer()
    assert await cache.fetch("search", ["q"], compute) == (b"answer", False)
    assert seen == [("search", "error")]


async def test_a_failing_computation_is_not_stored(store: MemoryStore) -> None:
    cache = ReadCache(store)

    async def broken() -> bytes:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await cache.fetch("search", ["q"], broken)
    compute = Computer()
    assert (await cache.fetch("search", ["q"], compute))[1] is False
    assert compute.calls == 1


async def test_a_crowd_for_one_key_computes_once(store: MemoryStore) -> None:
    cache = ReadCache(store)
    compute = Computer()
    compute.gate = asyncio.Event()

    crowd = [asyncio.create_task(cache.fetch("search", ["q"], compute)) for _ in range(20)]
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    compute.gate.set()
    results = await asyncio.gather(*crowd)

    assert compute.calls == 1
    assert {value for value, _ in results} == {b"answer"}


async def test_outcomes_are_reported_to_the_observer(store: MemoryStore) -> None:
    seen: list[tuple[str, str]] = []
    cache = ReadCache(store, observer=lambda ns, result: seen.append((ns, result)))
    compute = Computer()
    await cache.fetch("page", ["1"], compute)
    await cache.fetch("page", ["1"], compute)
    assert seen == [("page", "miss"), ("page", "hit")]
