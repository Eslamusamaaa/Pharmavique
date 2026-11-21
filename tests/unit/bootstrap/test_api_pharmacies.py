"""Licensed pharmacies by city: nearest first, never a stock claim, position never kept."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
import pytest

from pharmavique.bootstrap.api import create_app
from pharmavique.bootstrap.pharmacy_finder import nearby
from pharmavique.catalog.contracts.queries import CityLocation, Pharmacy
from pharmavique.foundation.kv import MemoryStore
from pharmavique.shared_kernel.market import Market

NOW = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)


def pharmacy(name: str, city: str | None, region: str | None = "Riyadh") -> Pharmacy:
    key = city.casefold() if city else None
    return Pharmacy(
        market=Market.SA,
        name=name,
        phone="0111111111",
        region=region,
        city_key=key,
        city=city,
        short_code="RSNA6794",
        address=f"{city} - RSNA6794" if city else "RSNA6794",
        source_ref="https://sfda.example/pharmacies?page=0",
        fetched_at=NOW,
        trust="official",
    )


def point(city: str, latitude: float, longitude: float) -> CityLocation:
    return CityLocation(
        Market.SA, city.casefold(), city, latitude, longitude, "nominatim", "ref", NOW,
        "unofficial_unverified",
    )  # fmt: skip


PHARMACIES = (
    pharmacy("Al Dawaa 1", "Riyadh"),
    pharmacy("Nahdi 2", "Riyadh"),
    pharmacy("Care 3", "Kharj", "Riyadh"),
    pharmacy("Sea 4", "Jeddah", "Mecca"),
    pharmacy("Lost 5", None),
    pharmacy("Far 6", "Najran", "Najran"),  # no point for this city yet
)
LOCATIONS = (
    point("Riyadh", 24.71, 46.67),
    point("Kharj", 24.15, 47.30),
    point("Jeddah", 21.54, 39.17),
)
RIYADH = (24.72, 46.68)


class Source:
    def __init__(self) -> None:
        self.reads = 0

    async def pharmacies(self, market: Market) -> tuple[Pharmacy, ...]:
        self.reads += 1
        return PHARMACIES

    async def city_locations(self, market: Market) -> tuple[CityLocation, ...]:
        return LOCATIONS


def test_cities_come_nearest_first_with_the_distance_to_their_centre() -> None:
    result = nearby(PHARMACIES, LOCATIONS, *RIYADH, radius_km=100)
    assert [g.city for g in result.groups] == ["Riyadh", "Kharj"]
    assert result.groups[0].distance_km is not None
    assert result.groups[0].distance_km < 2
    assert 60 < (result.groups[1].distance_km or 0) < 90


def test_the_nearest_outside_city_is_named_only_when_no_city_is_inside() -> None:
    result = nearby(PHARMACIES, LOCATIONS, 21.5, 39.2, radius_km=50)
    assert [g.city for g in result.groups] == ["Jeddah"]
    assert result.nearest_outside is None

    desert = nearby(PHARMACIES, LOCATIONS, 27.0, 42.0, radius_km=10)
    assert desert.groups == ()
    assert desert.nearest_outside is not None


def test_pharmacies_that_cannot_be_placed_are_counted_not_hidden() -> None:
    result = nearby(PHARMACIES, LOCATIONS, *RIYADH, radius_km=100)
    assert result.without_city == 1
    assert result.without_point == 1  # the Najran pharmacy


@pytest.fixture
async def client() -> AsyncIterator[tuple[httpx.AsyncClient, Source]]:
    source = Source()
    app = create_app(
        pharmacies=source,
        store=MemoryStore(),
        rate_limit_per_minute=0,
        heavy_rate_limit_per_minute=0,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c, source


async def test_nearby_answers_by_city_without_claiming_stock(
    client: tuple[httpx.AsyncClient, Source],
) -> None:
    c, _ = client
    response = await c.post(
        "/v1/pharmacies/nearby",
        json={"latitude": RIYADH[0], "longitude": RIYADH[1], "radius_km": 100},
    )
    body = response.json()
    assert response.status_code == 200
    assert body["precision"] == "city"
    assert [x["city"] for x in body["cities"]] == ["Riyadh", "Kharj"]
    first = body["cities"][0]["pharmacies"][0]
    assert first["trust"] == "official"
    assert first["address"] == "Riyadh - RSNA6794"
    assert "stock" in body["note"]
    assert "centre" in body["note"]
    assert body["pharmacies_without_a_city"] == 1
    assert body["pharmacies_in_cities_without_a_point"] == 1


async def test_the_position_is_not_cached_or_kept(
    client: tuple[httpx.AsyncClient, Source],
) -> None:
    c, _ = client
    response = await c.post(
        "/v1/pharmacies/nearby", json={"latitude": RIYADH[0], "longitude": RIYADH[1]}
    )
    assert response.headers["cache-control"] == "no-store"
    assert "x-cache" not in response.headers
    assert str(RIYADH[0]) not in str(response.url)  # it travels in the body, not the URL


@pytest.mark.parametrize(
    "body",
    [
        {"latitude": 91, "longitude": 0},
        {"latitude": 0, "longitude": 181},
        {"latitude": 24.7},
        {"latitude": 24.7, "longitude": 46.7, "radius_km": 0},
        {"latitude": 24.7, "longitude": 46.7, "radius_km": 5000},
    ],
)
async def test_a_bad_position_is_refused(
    client: tuple[httpx.AsyncClient, Source], body: dict[str, float]
) -> None:
    c, _ = client
    assert (await c.post("/v1/pharmacies/nearby", json=body)).status_code == 422


async def test_the_list_of_pharmacies_is_loaded_once_not_per_request(
    client: tuple[httpx.AsyncClient, Source],
) -> None:
    c, source = client
    for _ in range(3):
        await c.post("/v1/pharmacies/nearby", json={"latitude": 24.7, "longitude": 46.7})
    assert source.reads == 1


async def test_cities_list_says_which_have_a_point(
    client: tuple[httpx.AsyncClient, Source],
) -> None:
    c, _ = client
    body = (await c.get("/v1/pharmacies/cities")).json()
    by_key = {x["city_key"]: x for x in body["cities"]}
    assert by_key["riyadh"] == {
        "city_key": "riyadh",
        "city": "Riyadh",
        "region": "Riyadh",
        "pharmacies": 2,
        "located": True,
    }
    assert by_key["najran"]["located"] is False
    assert "lost 5" not in str(body).casefold()  # a pharmacy with no city is not in a city


async def test_search_without_a_position_by_city_region_or_name(
    client: tuple[httpx.AsyncClient, Source],
) -> None:
    c, _ = client
    by_city = (await c.get("/v1/pharmacies", params={"city": "riyadh"})).json()
    by_region = (await c.get("/v1/pharmacies", params={"region": "mecca"})).json()
    by_name = (await c.get("/v1/pharmacies", params={"q": "nahdi"})).json()
    assert [r["name"] for r in by_city["results"]] == ["Al Dawaa 1", "Nahdi 2"]
    assert [r["name"] for r in by_region["results"]] == ["Sea 4"]
    assert [r["name"] for r in by_name["results"]] == ["Nahdi 2"]
    assert by_city["total"] == 2
    assert "stock" in by_city["note"]


async def test_without_a_database_the_pharmacies_say_so() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="http://test"
    ) as c:
        response = await c.post("/v1/pharmacies/nearby", json={"latitude": 24.7, "longitude": 46.7})
    assert response.status_code == 503
