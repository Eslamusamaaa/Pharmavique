"""Background jobs: input and state in the shared store, outcomes that never leak text."""

import asyncio
import json
from collections.abc import Mapping
from typing import Any

import pytest

from pharmavique.foundation.jobs import (
    QUEUE_TIMEOUT_SECONDS,
    InlineJobQueue,
    JobFailure,
    JobInput,
    JobRunner,
)
from pharmavique.foundation.kv import MemoryStore


class Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


async def echo(job: JobInput) -> Mapping[str, Any]:
    return {"length": len(job.data), "meta": dict(job.meta)}


async def unreadable(job: JobInput) -> Mapping[str, Any]:
    raise JobFailure("unreadable_image")


async def broken(job: JobInput) -> Mapping[str, Any]:
    raise RuntimeError("patient takes warfarin")  # must never be stored or shown


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def runner(store: MemoryStore, clock: Clock) -> JobRunner:
    return JobRunner(store, {"echo": echo, "unreadable": unreadable, "broken": broken}, clock=clock)


async def test_a_job_runs_and_its_result_can_be_read(runner: JobRunner) -> None:
    queue = InlineJobQueue(runner)
    job_id = await queue.submit("echo", {"kind": "box"}, b"12345")
    await queue.drain()

    status = await queue.status(job_id)
    assert status is not None
    assert status.state == "done"
    assert status.result == {"length": 5, "meta": {"kind": "box"}}


async def test_a_new_job_is_queued_until_a_worker_takes_it(runner: JobRunner) -> None:
    job_id = await runner.create("echo", {}, b"x")
    status = await runner.status(job_id)
    assert status is not None
    assert status.state == "queued"
    await runner.run(job_id)
    done = await runner.status(job_id)
    assert done is not None
    assert done.state == "done"


async def test_the_input_is_deleted_as_soon_as_a_worker_takes_it(
    runner: JobRunner, store: MemoryStore
) -> None:
    job_id = await runner.create("echo", {}, b"a photo")
    assert await store.get(f"pv:job:{job_id}:in") is not None
    await runner.run(job_id)
    assert await store.get(f"pv:job:{job_id}:in") is None


async def test_an_expected_failure_stores_only_its_code(runner: JobRunner) -> None:
    queue = InlineJobQueue(runner)
    job_id = await queue.submit("unreadable", {}, b"x")
    await queue.drain()
    status = await queue.status(job_id)
    assert status is not None
    assert (status.state, status.error, status.result) == ("failed", "unreadable_image", None)


async def test_an_unexpected_failure_never_stores_its_text(
    runner: JobRunner, store: MemoryStore
) -> None:
    queue = InlineJobQueue(runner)
    job_id = await queue.submit("broken", {}, b"x")
    await queue.drain()
    status = await queue.status(job_id)
    assert status is not None
    assert (status.state, status.error) == ("failed", "internal_error")
    stored = await store.get(f"pv:job:{job_id}:state")
    assert stored is not None
    assert b"warfarin" not in stored


async def test_a_job_nobody_picked_up_reads_as_failed(runner: JobRunner, clock: Clock) -> None:
    job_id = await runner.create("echo", {}, b"x")
    clock.now += QUEUE_TIMEOUT_SECONDS + 1
    status = await runner.status(job_id)
    assert status is not None
    assert (status.state, status.error) == ("failed", "worker_unavailable")


async def test_a_job_whose_input_expired_fails_cleanly(
    runner: JobRunner, store: MemoryStore
) -> None:
    job_id = await runner.create("echo", {}, b"x")
    await store.delete(f"pv:job:{job_id}:in")
    await runner.run(job_id)
    status = await runner.status(job_id)
    assert status is not None
    assert (status.state, status.error) == ("failed", "input_expired")


async def test_an_unknown_kind_is_refused_before_anything_is_stored(runner: JobRunner) -> None:
    with pytest.raises(ValueError, match="unknown job kind"):
        await runner.create("teleport", {}, b"x")


async def test_an_unknown_job_id_has_no_status(runner: JobRunner) -> None:
    assert await runner.status("nope") is None


async def test_running_a_job_twice_does_not_run_the_handler_twice(
    store: MemoryStore, clock: Clock
) -> None:
    calls = 0

    async def counting(job: JobInput) -> Mapping[str, Any]:
        nonlocal calls
        calls += 1
        return {}

    runner = JobRunner(store, {"count": counting}, clock=clock)
    job_id = await runner.create("count", {}, b"x")
    await asyncio.gather(runner.run(job_id), runner.run(job_id))
    assert calls == 1  # the second worker finds the input already taken


async def test_the_state_is_plain_json_with_no_input_inside(
    runner: JobRunner, store: MemoryStore
) -> None:
    job_id = await runner.create("echo", {"secret": "meta"}, b"photo-bytes")
    raw = await store.get(f"pv:job:{job_id}:state")
    assert raw is not None
    record = json.loads(raw)
    assert record["state"] == "queued"
    assert b"photo-bytes" not in raw
    assert b"meta" not in raw
