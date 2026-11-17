"""Bounded concurrency for batch jobs."""

import asyncio
from collections.abc import Awaitable, Callable, Iterable


async def map_concurrently[T, R](
    items: Iterable[T], work: Callable[[T], Awaitable[R]], *, limit: int
) -> list[R]:
    """Run `work` on every item, at most `limit` at a time; results keep the input order.

    The first failure is raised once the running items have finished, so nothing is left
    half-cancelled.
    """
    if limit < 1:
        raise ValueError("limit must be at least 1")
    gate = asyncio.Semaphore(limit)

    async def guarded(item: T) -> R:
        async with gate:
            return await work(item)

    outcomes = await asyncio.gather(*(guarded(item) for item in items), return_exceptions=True)
    results: list[R] = []
    for outcome in outcomes:
        if isinstance(outcome, BaseException):
            raise outcome
        results.append(outcome)
    return results
