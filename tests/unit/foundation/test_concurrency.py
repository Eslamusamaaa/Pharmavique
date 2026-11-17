import asyncio

import pytest

from pharmavique.foundation.concurrency import map_concurrently


async def test_results_come_back_in_input_order_whatever_finishes_first() -> None:
    async def work(n: int) -> int:
        await asyncio.sleep(0.01 * (5 - n))
        return n * 10

    assert await map_concurrently(range(5), work, limit=5) == [0, 10, 20, 30, 40]


async def test_no_more_than_the_limit_run_at_once() -> None:
    running = 0
    peak = 0

    async def work(n: int) -> int:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1
        return n

    await map_concurrently(range(12), work, limit=3)

    assert peak == 3


async def test_a_failure_in_one_item_is_raised() -> None:
    async def work(n: int) -> int:
        if n == 2:
            raise RuntimeError("boom")
        return n

    with pytest.raises(RuntimeError, match="boom"):
        await map_concurrently(range(4), work, limit=2)
