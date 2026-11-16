"""Fakes that must satisfy the ports; mypy checks the conformance, pytest checks the behavior."""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

from pharmavique.shared_kernel.ports import Clock, JobQueue


class FixedClock:
    def __init__(self, moment: datetime) -> None:
        self._moment = moment

    def now(self) -> datetime:
        return self._moment


class RecordingQueue:
    def __init__(self) -> None:
        self.jobs: list[tuple[str, Mapping[str, object], str | None]] = []

    async def enqueue(
        self,
        job_name: str,
        payload: Mapping[str, object],
        *,
        dedupe_key: str | None = None,
        defer_by: timedelta | None = None,
        job_timeout: timedelta | None = None,
    ) -> None:
        self.jobs.append((job_name, payload, dedupe_key))


def test_fixed_clock_satisfies_clock_port() -> None:
    clock: Clock = FixedClock(datetime(2026, 1, 1, tzinfo=UTC))

    assert clock.now().utcoffset() is not None


async def test_recording_queue_satisfies_job_queue_port() -> None:
    queue: JobQueue = RecordingQueue()

    await queue.enqueue("recognize", {"upload_id": "u1"}, dedupe_key="u1")

    assert isinstance(queue, RecordingQueue)
    assert queue.jobs == [("recognize", {"upload_id": "u1"}, "u1")]
