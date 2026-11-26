"""Liveness (`/health`) and readiness (`/ready`) endpoints.

`/health` only says the process answers. `/ready` says this instance can serve traffic: the
database answers a trivial query and, when one is set, the shared store answers. Each check has a
short timeout and the answer never carries connection strings or error text. Without a database
the instance is ready in dev (the data routes answer 503 by design) and not ready in prod.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from importlib.metadata import PackageNotFoundError, version
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from pharmavique.bootstrap.settings import Settings, get_settings
from pharmavique.foundation.kv import KeyValueStore

router = APIRouter(tags=["health"])


def _package_version() -> str:
    try:
        return version("pharmavique")
    except PackageNotFoundError:  # running from a source tree without installation
        return "0.0.0+unknown"


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str
    environment: str


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
async def health(settings: Annotated[Settings, Depends(get_settings)]) -> HealthResponse:
    return HealthResponse(
        status="ok",
        service="pharmavique",
        version=_package_version(),
        environment=settings.environment,
    )


CHECK_TIMEOUT_SECONDS = 5.0  # a Neon compute waking from idle answers in about 1-3 s
_READY_PROBE_KEY = "pv:ready-probe"
_log = logging.getLogger(__name__)

CheckResult = Literal["ok", "failed", "not_configured"]


class ReadyResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: dict[str, CheckResult]


async def _run(name: str, check: Callable[[], Awaitable[object]] | None) -> CheckResult:
    if check is None:
        return "not_configured"
    try:
        await asyncio.wait_for(check(), timeout=CHECK_TIMEOUT_SECONDS)
    except Exception as error:
        # the type only: messages can carry hosts or credentials
        _log.warning("ready check failed", extra={"check": name, "error": type(error).__name__})
        return "failed"
    return "ok"


@router.get(
    "/ready",
    response_model=ReadyResponse,
    summary="Readiness probe",
    responses={503: {"model": ReadyResponse, "description": "A required dependency is down."}},
)
async def ready(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> JSONResponse:
    database_ping: Callable[[], Awaitable[object]] | None = request.app.state.database_ping
    store: KeyValueStore | None = request.app.state.kv
    database, shared_store = await asyncio.gather(
        _run("database", database_ping),
        _run("shared_store", None if store is None else lambda: store.get(_READY_PROBE_KEY)),
    )
    failed = "failed" in (database, shared_store) or (
        database == "not_configured" and settings.environment == "prod"
    )
    body = ReadyResponse(
        status="not_ready" if failed else "ready",
        checks={"database": database, "shared_store": shared_store},
    )
    return JSONResponse(body.model_dump(), status_code=503 if failed else 200)
