"""Find where a city is, once, politely (OpenStreetMap's Nominatim, one request a second).

Used offline by `pharmavique geocode-cities` for the few dozen city names in the pharmacy list,
never per user request, and it sends a city name only: nothing about a person. A clear
User-Agent and a throttle follow Nominatim's usage policy. A result outside the expected country
box is refused, so a same-named place abroad cannot be taken for the city.
"""

from dataclasses import dataclass

import httpx

from pharmavique.foundation.http.throttle import Throttle

NOMINATIM = "https://nominatim.openstreetmap.org"
USER_AGENT = "Pharmavique/0.1 (drug information prototype; one-time city lookup)"
# a loose box around Saudi Arabia: latitude 16 to 33, longitude 34 to 56
SAUDI_BOX = (16.0, 33.0, 34.0, 56.0)


@dataclass(frozen=True, slots=True)
class Geocoded:
    latitude: float
    longitude: float
    display_name: str
    source_ref: str  # the exact request, so the result can be checked


class NominatimGeocoder:
    def __init__(
        self,
        client: httpx.AsyncClient,
        throttle: Throttle,
        base_url: str = NOMINATIM,
        box: tuple[float, float, float, float] = SAUDI_BOX,
        country_code: str = "sa",
    ) -> None:
        self._client = client
        self._throttle = throttle
        self._base_url = base_url
        self._box = box
        self._country = country_code

    async def city(self, name: str) -> Geocoded | None:
        await self._throttle.wait()
        params = {
            "q": name,
            "countrycodes": self._country,
            "format": "jsonv2",
            "limit": "1",
            "accept-language": "en",
        }
        response = await self._client.get(
            f"{self._base_url}/search", params=params, headers={"User-Agent": USER_AGENT}
        )
        response.raise_for_status()
        results = response.json()
        if not results:
            return None
        found = results[0]
        latitude, longitude = float(found["lat"]), float(found["lon"])
        south, north, west, east = self._box
        if not (south <= latitude <= north and west <= longitude <= east):
            return None
        return Geocoded(latitude, longitude, str(found.get("display_name", "")), str(response.url))
