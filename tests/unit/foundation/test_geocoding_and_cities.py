"""The polite one-time city geocoder and the command that fills in missing city points."""

from datetime import UTC, datetime

import httpx

from pharmavique.bootstrap.places_cli import locate_cities
from pharmavique.catalog.contracts.queries import CityLocation, Pharmacy
from pharmavique.foundation.geocoding import USER_AGENT, Geocoded, NominatimGeocoder
from pharmavique.foundation.http.throttle import Throttle
from pharmavique.shared_kernel.market import Market

NOW = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)


def geocoder(handler: httpx.MockTransport) -> tuple[NominatimGeocoder, list[float]]:
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    ticks = iter(range(0, 1000))
    throttle = Throttle(1.0, now=lambda: float(next(ticks)) * 0.1, sleep=sleep, rand=lambda: 0.0)
    return NominatimGeocoder(httpx.AsyncClient(transport=handler), throttle), slept


def answer(lat: str, lon: str) -> httpx.MockTransport:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"lat": lat, "lon": lon, "display_name": "Somewhere, SA"}])

    return httpx.MockTransport(respond)


async def test_a_city_inside_saudi_arabia_is_found_with_the_request_it_came_from() -> None:
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200, json=[{"lat": "24.71", "lon": "46.67", "display_name": "Riyadh"}]
        )

    found, _ = geocoder(httpx.MockTransport(respond))
    result = await found.city("Riyadh, Saudi Arabia")

    assert result is not None
    assert (result.latitude, result.longitude) == (24.71, 46.67)
    assert "nominatim" in result.source_ref
    assert seen[0].headers["user-agent"] == USER_AGENT
    assert seen[0].url.params["countrycodes"] == "sa"
    assert seen[0].url.params["q"] == "Riyadh, Saudi Arabia"


async def test_the_user_agent_names_the_project_and_no_person() -> None:
    assert "Pharmavique" in USER_AGENT
    assert "@" not in USER_AGENT


async def test_a_result_outside_the_country_box_is_refused() -> None:
    found, _ = geocoder(answer("48.85", "2.35"))  # Paris
    assert await found.city("Medina") is None


async def test_no_result_is_none() -> None:
    found, _ = geocoder(httpx.MockTransport(lambda r: httpx.Response(200, json=[])))
    assert await found.city("Nowhere") is None


async def test_requests_are_spaced_by_the_throttle() -> None:
    found, slept = geocoder(answer("24.7", "46.7"))
    await found.city("a")
    await found.city("b")
    assert slept  # the second request waited


def pharmacy(name: str, city: str | None) -> Pharmacy:
    return Pharmacy(
        Market.SA, name, None, None, city.casefold() if city else None, city, None,
        city or "", "ref", NOW, "official",
    )  # fmt: skip


class Source:
    def __init__(self, known: tuple[str, ...] = ()) -> None:
        self.known = known

    async def pharmacies(self, market: Market) -> tuple[Pharmacy, ...]:
        return (
            pharmacy("a", "Riyadh"),
            pharmacy("b", "Riyadh"),
            pharmacy("c", "Atlantis"),
            pharmacy("d", "Jeddah"),
            pharmacy("e", None),
        )

    async def city_locations(self, market: Market) -> tuple[CityLocation, ...]:
        return tuple(
            CityLocation(market, k, k.title(), 1.0, 1.0, "x", "r", NOW, "unofficial_unverified")
            for k in self.known
        )


class FakeGeocoder:
    def __init__(self) -> None:
        self.asked: list[str] = []

    async def city(self, name: str) -> Geocoded | None:
        self.asked.append(name)
        if name.startswith("Atlantis"):
            return None
        return Geocoded(24.0, 46.0, name, f"https://nominatim.example/search?q={name}")


class Clock:
    def now(self) -> datetime:
        return NOW


async def test_each_city_is_looked_up_once_and_the_unplaceable_are_listed_not_guessed() -> None:
    saved: list[CityLocation] = []

    async def save(location: CityLocation) -> None:
        saved.append(location)

    fake = FakeGeocoder()
    report = await locate_cities(Source(), save, fake, Clock(), Market.SA)

    assert sorted(fake.asked) == [
        "Atlantis, Saudi Arabia", "Jeddah, Saudi Arabia", "Riyadh, Saudi Arabia",
    ]  # fmt: skip
    assert sorted(report.located) == ["Jeddah", "Riyadh"]
    assert report.unresolved == ["Atlantis"]
    assert {s.city_key for s in saved} == {"jeddah", "riyadh"}
    assert all(s.trust == "unofficial_unverified" for s in saved)
    assert all(s.source == "openstreetmap-nominatim" for s in saved)


async def test_cities_that_already_have_a_point_are_not_looked_up_again() -> None:
    saved: list[CityLocation] = []

    async def save(location: CityLocation) -> None:
        saved.append(location)

    fake = FakeGeocoder()
    report = await locate_cities(Source(known=("riyadh",)), save, fake, Clock(), Market.SA)

    assert "Riyadh, Saudi Arabia" not in fake.asked
    assert report.already == 1
