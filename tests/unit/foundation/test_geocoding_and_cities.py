"""The polite one-time city geocoder and the command that fills in missing city points."""

from datetime import UTC, datetime
from typing import ClassVar

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


class RegionSource:
    """Three Aseer cities and one whose name also exists near Riyadh."""

    async def pharmacies(self, market: Market) -> tuple[Pharmacy, ...]:
        def p(name: str, city: str, region: str) -> Pharmacy:
            return Pharmacy(
                Market.SA, name, None, region, city.casefold(), city, None, city, "ref", NOW,
                "official",
            )  # fmt: skip

        return (
            p("1", "Abha", "Aseer Province"),
            p("2", "Bisha", "Aseer Province"),
            p("3", "Khamis Mushait", "Aseer Province"),
            p("4", "Al-Namas", "Aseer Province"),
            p("5", "Riyadh", "Riyadh"),
        )

    async def city_locations(self, market: Market) -> tuple[CityLocation, ...]:
        return ()


class PointGeocoder:
    POINTS: ClassVar[dict[str, tuple[float, float]]] = {
        "Abha": (18.22, 42.50),
        "Bisha": (20.00, 42.60),
        "Khamis Mushait": (18.30, 42.73),
        "Al-Namas": (24.62, 46.55),  # a place of the same name near Riyadh: wrong region
        "Riyadh": (24.64, 46.72),
    }

    async def city(self, name: str) -> Geocoded | None:
        lat, lon = self.POINTS[name.split(",")[0]]
        return Geocoded(lat, lon, name, "ref")


async def test_a_point_far_from_the_other_cities_of_its_region_is_not_saved() -> None:
    saved: list[CityLocation] = []

    async def save(location: CityLocation) -> None:
        saved.append(location)

    report = await locate_cities(RegionSource(), save, PointGeocoder(), Clock(), Market.SA)

    assert {s.city for s in saved} == {"Abha", "Bisha", "Khamis Mushait", "Riyadh"}
    assert [name for name, _ in report.suspect] == ["Al-Namas"]
    assert report.suspect[0][1] > 500  # kilometres from where its region's other cities are
    assert report.unresolved == []


async def test_a_region_with_one_city_cannot_be_checked_and_is_kept() -> None:
    saved: list[CityLocation] = []

    async def save(location: CityLocation) -> None:
        saved.append(location)

    await locate_cities(RegionSource(), save, PointGeocoder(), Clock(), Market.SA)
    assert "Riyadh" in {s.city for s in saved}


async def test_cities_that_already_have_a_point_are_not_looked_up_again() -> None:
    saved: list[CityLocation] = []

    async def save(location: CityLocation) -> None:
        saved.append(location)

    fake = FakeGeocoder()
    report = await locate_cities(Source(known=("riyadh",)), save, fake, Clock(), Market.SA)

    assert "Riyadh, Saudi Arabia" not in fake.asked
    assert report.already == 1
