"""The public "last update and sources" page and the trust grade on interaction answers."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
import pytest

from pharmavique.bootstrap.api import create_app
from pharmavique.bootstrap.features import Features, get_features
from pharmavique.bootstrap.sources_status import SourceStat

FETCHED = datetime(2026, 11, 24, 3, 0, tzinfo=UTC)


class Status:
    async def read(self) -> dict[str, SourceStat]:
        return {
            "sfda-drugs": SourceStat(records=9144, last_updated=FETCHED),
            "ddinter-2.0": SourceStat(
                records=234757, last_updated=datetime(2026, 11, 21, tzinfo=UTC)
            ),
        }


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(source_status=Status(), rate_limit_per_minute=0)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def test_the_page_is_public_and_says_what_each_source_is(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/sources")

    assert response.status_code == 200
    body = response.json()
    assert "not medical advice" in body["disclaimer"]
    sources = {s["id"]: s for s in body["sources"]}
    assert sources["sfda-drugs"]["grade"] == "official_sa"
    assert sources["openfda-labels"]["grade"] == "official_foreign"
    assert sources["ddinter-2.0"]["grade"] == "unverified"
    assert sources["medic"]["grade"] == "unverified"
    assert sources["ddinter-2.0"]["grade_label_ar"] == "غير موثّق"


async def test_known_updates_are_shown_and_unknown_ones_stay_unknown(
    client: httpx.AsyncClient,
) -> None:
    sources = {s["id"]: s for s in (await client.get("/v1/sources")).json()["sources"]}

    assert sources["sfda-drugs"]["records"] == 9144
    assert sources["sfda-drugs"]["last_updated"].startswith("2026-11-24T03:00")
    # nothing was read for MeDIC: unknown, never zero and never "now"
    assert sources["medic"]["records"] is None
    assert sources["medic"]["last_updated"] is None


async def test_the_page_lists_the_three_grades(client: httpx.AsyncClient) -> None:
    grades = (await client.get("/v1/sources")).json()["grades"]
    assert [g["grade"] for g in grades] == ["official_sa", "official_foreign", "unverified"]
    assert all(g["label_ar"] and g["meaning_ar"] for g in grades)


async def test_without_a_database_the_page_still_answers_with_unknowns() -> None:
    app = create_app(rate_limit_per_minute=0)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        body = (await c.get("/v1/sources")).json()
    assert all(s["last_updated"] is None and s["records"] is None for s in body["sources"])


async def test_with_the_feature_off_the_page_does_not_exist() -> None:
    app = create_app(source_status=Status(), rate_limit_per_minute=0)
    app.dependency_overrides[get_features] = lambda: Features(_env_file=None, sources_page=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        assert (await c.get("/v1/sources")).status_code == 404
