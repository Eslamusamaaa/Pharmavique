"""The Arq (Redis) side of the job queue: enqueue from the API, run in `pharmavique worker`.

Arq only moves the job id to a worker and enforces the timeout and the concurrency; the input, the
state and the result are the `JobRunner`'s (see `jobs.py`), so they stay small and short-lived.
"""

from collections.abc import Mapping
from typing import Any

from arq.connections import ArqRedis, RedisSettings, create_pool
from arq.worker import Worker, func

from pharmavique.foundation.jobs import JobRunner, JobStatus

TASK_NAME = "run_job"


def redis_settings(url: str) -> RedisSettings:
    return RedisSettings.from_dsn(url.replace("://localhost:", "://127.0.0.1:", 1))


class ArqJobQueue:
    def __init__(self, runner: JobRunner, pool: ArqRedis) -> None:
        self._runner = runner
        self._pool = pool

    @classmethod
    async def connect(cls, runner: JobRunner, url: str) -> "ArqJobQueue":
        settings = redis_settings(url)
        settings.conn_timeout = 1
        settings.conn_retries = 1
        return cls(runner, await create_pool(settings))

    async def submit(self, kind: str, meta: Mapping[str, Any], data: bytes) -> str:
        job_id = await self._runner.create(kind, meta, data)
        await self._pool.enqueue_job(TASK_NAME, job_id, _job_id=job_id)
        return job_id

    async def status(self, job_id: str) -> JobStatus | None:
        return await self._runner.status(job_id)

    async def depth(self) -> int:
        return int(await self._pool.zcard("arq:queue"))

    async def close(self) -> None:
        await self._pool.aclose()


def make_worker(
    runner: JobRunner, url: str, *, max_jobs: int, job_timeout: int, burst: bool = False
) -> Worker:
    """A worker that runs at most `max_jobs` at once and gives each job `job_timeout` seconds. It
    never retries: a scan costs a model call, and the caller can submit again."""

    async def run_job(ctx: dict[str, Any], job_id: str) -> None:
        await runner.run(job_id)

    return Worker(
        functions=[func(run_job, name=TASK_NAME)],
        redis_settings=redis_settings(url),
        max_jobs=max_jobs,
        job_timeout=job_timeout,
        max_tries=1,
        keep_result=0,
        handle_signals=False,
        burst=burst,
    )
