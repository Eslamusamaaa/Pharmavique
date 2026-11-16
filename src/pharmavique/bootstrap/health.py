"""Liveness endpoint. Readiness (Postgres/Redis checks) arrives with the DB layer in Phase 1."""

from importlib.metadata import PackageNotFoundError, version
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from pharmavique.bootstrap.settings import Settings, get_settings

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
