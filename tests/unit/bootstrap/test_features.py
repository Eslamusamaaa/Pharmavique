"""Feature flags: every new feature can be switched off from the environment without a deploy."""

from collections.abc import AsyncIterator
from typing import Annotated

import httpx
import pytest
from fastapi import Depends, FastAPI

from pharmavique.bootstrap.api import create_app
from pharmavique.bootstrap.features import Features, get_features, require_feature


def test_features_are_on_by_default() -> None:
    features = Features(_env_file=None)
    assert all(features.as_dict().values())


def test_a_feature_is_switched_off_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PHARMAVIQUE_FEATURE_SOURCES_PAGE", "false")
    assert Features(_env_file=None).as_dict()["sources_page"] is False


def test_an_unknown_feature_name_is_a_programming_error() -> None:
    with pytest.raises(ValueError, match="unknown feature"):
        require_feature("no_such_feature")


def _app_with_guarded_route(features: Features) -> FastAPI:
    app = FastAPI()

    @app.get("/guarded")
    async def guarded(
        _: Annotated[None, Depends(require_feature("sources_page"))],
    ) -> dict[str, str]:
        return {"ok": "yes"}

    app.dependency_overrides[get_features] = lambda: features
    return app


async def test_a_switched_off_feature_answers_404() -> None:
    app = _app_with_guarded_route(Features(_env_file=None, sources_page=False))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/guarded")
    assert response.status_code == 404


async def test_a_switched_on_feature_answers() -> None:
    app = _app_with_guarded_route(Features(_env_file=None, sources_page=True))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/guarded")
    assert response.status_code == 200


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = create_app()
    app.dependency_overrides[get_features] = lambda: Features(_env_file=None, sources_page=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def test_the_app_can_read_which_features_are_on(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/features")
    assert response.status_code == 200
    body = response.json()
    assert body["sources_page"] is False
