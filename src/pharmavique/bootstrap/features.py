"""Feature flags: each new feature can be switched off from the environment without a deploy.

A flag is `PHARMAVIQUE_FEATURE_<NAME>` (true or false). Features are on by default once their
tests pass (owner's decision, 2026-11-25); setting a flag to false in Vercel switches the feature
off on the next request to a new instance. A route guarded by `require_feature` answers 404 when
its feature is off, as if it did not exist, and the app reads `/v1/features` to hide its screens.
"""

from collections.abc import Callable, Coroutine
from functools import lru_cache
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic_settings import BaseSettings, SettingsConfigDict


class Features(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PHARMAVIQUE_FEATURE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Public page of data sources, trust grades and last updates (Phase 0, item 7).
    sources_page: bool = True
    # The assistant, scans and voice need a signed-in account (Phase 0, item 1).
    login_for_ai: bool = True
    # Signed-in assistant conversations are saved, listed, searched and shared (Phase 1, ADR-022).
    chat_history: bool = True

    def as_dict(self) -> dict[str, bool]:
        return {name: bool(getattr(self, name)) for name in type(self).model_fields}


@lru_cache
def get_features() -> Features:
    return Features()


def require_feature(name: str) -> Callable[..., Coroutine[Any, Any, None]]:
    """A dependency that answers 404 while the feature `name` is switched off."""
    if name not in Features.model_fields:
        raise ValueError(f"unknown feature: {name}")

    async def check(features: Annotated[Features, Depends(get_features)]) -> None:
        if not getattr(features, name):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")

    return check


router = APIRouter(tags=["features"])


@router.get("/v1/features", summary="Which features are switched on")
async def list_features(
    request: Request, features: Annotated[Features, Depends(get_features)]
) -> dict[str, bool]:
    # `shelf_scan` predates these flags (PHARMAVIQUE_SHELF_SCAN_ENABLED); the app reads it here too.
    return {"shelf_scan": bool(request.app.state.shelf_scan_enabled), **features.as_dict()}
