"""Technical ports used by several contexts. Adapters live in `foundation`."""

from collections.abc import Mapping
from datetime import datetime, timedelta
from types import TracebackType
from typing import Protocol, Self


class Clock(Protocol):
    def now(self) -> datetime:
        """Current time as a timezone-aware datetime."""
        ...


class UnitOfWork(Protocol):
    """One transaction in one context. Never spans two contexts."""

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class JobQueue(Protocol):
    """Wake-up mechanism for background work. Job state itself lives in Postgres (ADR-002)."""

    async def enqueue(
        self,
        job_name: str,
        payload: Mapping[str, object],
        *,
        dedupe_key: str | None = None,
        defer_by: timedelta | None = None,
        job_timeout: timedelta | None = None,
    ) -> None: ...
