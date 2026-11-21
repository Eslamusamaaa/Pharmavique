"""The job queue on real Redis with a real Arq worker: submit, run elsewhere, poll."""

import asyncio
from collections.abc import Mapping
from typing import Any

import pytest
from redis.exceptions import RedisError

from pharmavique.bootstrap.settings import Settings
from pharmavique.foundation.arq_jobs import ArqJobQueue, make_worker
from pharmavique.foundation.jobs import JobFailure, JobInput, JobRunner
from pharmavique.foundation.kv import RedisStore, redis_client

pytestmark = pytest.mark.integration


async def echo(job: JobInput) -> Mapping[str, Any]:
    return {"length": len(job.data)}


async def refuse(job: JobInput) -> Mapping[str, Any]:
    raise JobFailure("invalid_image")


@pytest.fixture
async def url() -> str:
    secret = Settings().redis_url
    if secret is None:
        pytest.skip("PHARMAVIQUE_REDIS_URL is not set (copy .env.example to .env)")
    value = secret.get_secret_value()
    client = redis_client(value, timeout=1.0)
    try:
        await client.ping()
    except (OSError, RedisError) as error:
        pytest.skip(f"Redis is not reachable ({error}); run `docker compose up -d redis`")
    finally:
        await client.aclose()
    return value


async def test_a_job_submitted_by_the_api_is_run_by_a_worker_and_polled_by_id(url: str) -> None:
    store = RedisStore(redis_client(url, timeout=2.0))
    runner = JobRunner(store, {"echo": echo, "refuse": refuse})
    queue = await ArqJobQueue.connect(runner, url)
    try:
        ok = await queue.submit("echo", {}, b"a photo")
        bad = await queue.submit("refuse", {}, b"x")
        waiting = await queue.status(ok)
        assert waiting is not None
        assert waiting.state == "queued"
        assert await queue.depth() >= 2

        worker = make_worker(runner, url, max_jobs=4, job_timeout=30, burst=True)
        await asyncio.wait_for(worker.async_run(), timeout=30)

        done = await queue.status(ok)
        failed = await queue.status(bad)
        assert done is not None
        assert (done.state, done.result) == ("done", {"length": 7})
        assert failed is not None
        assert (failed.state, failed.error) == ("failed", "invalid_image")
        assert await store.get(f"pv:job:{ok}:in") is None  # the input is gone after processing
    finally:
        await queue.close()
        await store.close()
