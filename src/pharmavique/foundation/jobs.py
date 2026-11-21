"""Background jobs for slow work (reading a photo, asking the assistant) behind one small port.

A request that would hold a connection for tens of seconds instead leaves a job and gets an id to
poll. That bounds how much slow work runs at once (the workers decide), lets any API instance accept
the request while another process does the work, and gives the caller a clear "still working" or
"failed" instead of a gateway timeout.

Input and state live in the shared key-value store:
- the input (for a scan, the photo) is written under a short expiry and **deleted the moment a
  worker takes it**, so a photo never outlives its processing;
- the state (`queued`, `running`, `done`, `failed`) and the result live under a short expiry too;
- a job nobody picked up in `QUEUE_TIMEOUT_SECONDS` reads as failed (`worker_unavailable`), so a
  stopped worker shows up as an honest error, and the caller can use the synchronous endpoint.

A handler raises `JobFailure(code)` for expected problems; the code is the only thing stored and
shown. Any other exception is stored as `internal_error`, never its text (it could hold health
data).
"""

import asyncio
import json
import secrets
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pharmavique.foundation.kv import KeyValueStore

QUEUE_TIMEOUT_SECONDS = 180
STATE_TTL_SECONDS = 900
INPUT_TTL_SECONDS = 600

State = Literal["queued", "running", "done", "failed"]


class JobFailure(Exception):
    """An expected failure with a short, safe code (for example `unreadable_image`)."""

    def __init__(self, code: str, status_hint: int = 422) -> None:
        super().__init__(code)
        self.code = code
        self.status_hint = status_hint


@dataclass(frozen=True, slots=True)
class JobInput:
    kind: str
    meta: Mapping[str, Any]
    data: bytes


@dataclass(frozen=True, slots=True)
class JobStatus:
    job_id: str
    kind: str
    state: State
    result: Mapping[str, Any] | None = None
    error: str | None = None


JobHandler = Callable[[JobInput], Awaitable[Mapping[str, Any]]]


class JobQueue(Protocol):
    async def submit(self, kind: str, meta: Mapping[str, Any], data: bytes) -> str: ...

    async def status(self, job_id: str) -> JobStatus | None: ...

    async def depth(self) -> int:
        """Jobs waiting for a worker (the API refuses new ones when it is too deep)."""
        ...


def _input_key(job_id: str) -> str:
    return f"pv:job:{job_id}:in"


def _state_key(job_id: str) -> str:
    return f"pv:job:{job_id}:state"


class JobRunner:
    """The part every queue shares: writing the input and the state, and running one job."""

    def __init__(
        self,
        store: KeyValueStore,
        handlers: Mapping[str, JobHandler],
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._store = store
        self._handlers = handlers
        self._clock = clock

    async def _write_state(
        self,
        job_id: str,
        kind: str,
        state: State,
        created: float,
        result: Mapping[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        record = {
            "kind": kind,
            "state": state,
            "created": created,
            "result": result,
            "error": error,
        }
        await self._store.set(_state_key(job_id), json.dumps(record).encode(), STATE_TTL_SECONDS)

    async def create(self, kind: str, meta: Mapping[str, Any], data: bytes) -> str:
        if kind not in self._handlers:
            raise ValueError(f"unknown job kind: {kind}")
        job_id = secrets.token_urlsafe(24)
        blob = json.dumps(dict(meta)).encode() + b"\n" + data
        await self._store.set(_input_key(job_id), blob, INPUT_TTL_SECONDS)
        await self._write_state(job_id, kind, "queued", self._clock())
        return job_id

    async def status(self, job_id: str) -> JobStatus | None:
        raw = await self._store.get(_state_key(job_id))
        if raw is None:
            return None
        record = json.loads(raw)
        state: State = record["state"]
        error: str | None = record.get("error")
        if state == "queued" and self._clock() - record["created"] > QUEUE_TIMEOUT_SECONDS:
            state, error = "failed", "worker_unavailable"
        return JobStatus(job_id, record["kind"], state, record.get("result"), error)

    async def run(self, job_id: str) -> None:
        """Take the input (deleting it), run the handler, store the outcome. Never raises."""
        raw = await self._store.get(_state_key(job_id))
        if raw is None:
            return
        record = json.loads(raw)
        kind, created = record["kind"], record["created"]
        blob = await self._store.getdel(_input_key(job_id))
        if blob is None:
            await self._write_state(job_id, kind, "failed", created, error="input_expired")
            return
        header, _, data = blob.partition(b"\n")
        await self._write_state(job_id, kind, "running", created)
        try:
            result = await self._handlers[kind](JobInput(kind, json.loads(header), data))
        except JobFailure as failure:
            await self._write_state(job_id, kind, "failed", created, error=failure.code)
        except asyncio.CancelledError:
            await self._write_state(job_id, kind, "failed", created, error="timed_out")
            raise
        except Exception:
            await self._write_state(job_id, kind, "failed", created, error="internal_error")
        else:
            await self._write_state(job_id, kind, "done", created, result=dict(result))


class InlineJobQueue:
    """Runs each job in this process right away. For tests, and for one process without Redis."""

    def __init__(self, runner: JobRunner) -> None:
        self._runner = runner
        self._tasks: set[asyncio.Task[None]] = set()

    async def submit(self, kind: str, meta: Mapping[str, Any], data: bytes) -> str:
        job_id = await self._runner.create(kind, meta, data)
        task = asyncio.ensure_future(self._runner.run(job_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job_id

    async def status(self, job_id: str) -> JobStatus | None:
        return await self._runner.status(job_id)

    async def depth(self) -> int:
        return 0

    async def drain(self) -> None:
        """Wait for running jobs (tests)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks))
