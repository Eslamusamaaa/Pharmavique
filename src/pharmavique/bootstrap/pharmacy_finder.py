"""Which licensed pharmacies are near a place, honestly: by city.

The SFDA list gives each pharmacy a city and a national-address short code, never coordinates. A
city has one point (found once by a geocoder), so the distance here is to the city's centre, never
to a pharmacy. This module only orders and filters; it says nothing about stock or opening hours.
"""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from pharmavique.catalog.contracts.queries import CityLocation, Pharmacy
from pharmavique.shared_kernel.geo import distance_km


@dataclass(frozen=True, slots=True)
class CityGroup:
    city_key: str
    city: str
    region: str | None  # the region most of the city's pharmacies list
    pharmacies: tuple[Pharmacy, ...]
    latitude: float | None
    longitude: float | None
    distance_km: float | None  # to the city centre; None when asked without a position


@dataclass(frozen=True, slots=True)
class Nearby:
    groups: tuple[CityGroup, ...]  # cities within the radius, nearest first
    nearest_outside: CityGroup | None  # the nearest city beyond the radius, if none was inside
    without_city: int  # pharmacies whose address has no usable city (never placed)
    without_point: int  # pharmacies in a city that has no point yet


def _region_of(pharmacies: Sequence[Pharmacy]) -> str | None:
    counts: dict[str, int] = defaultdict(int)
    for p in pharmacies:
        if p.region:
            counts[p.region] += 1
    return max(counts, key=lambda r: (counts[r], r)) if counts else None


def city_groups(
    pharmacies: Iterable[Pharmacy], locations: Iterable[CityLocation]
) -> list[CityGroup]:
    """Every city that has at least one pharmacy, with its point when it has one."""
    points = {loc.city_key: loc for loc in locations}
    by_city: dict[str, list[Pharmacy]] = defaultdict(list)
    for p in pharmacies:
        if p.city_key is not None:
            by_city[p.city_key].append(p)
    groups = []
    for key, rows in by_city.items():
        point = points.get(key)
        groups.append(
            CityGroup(
                city_key=key,
                city=rows[0].city or key,
                region=_region_of(rows),
                pharmacies=tuple(sorted(rows, key=lambda p: (p.name.casefold(), p.address))),
                latitude=point.latitude if point else None,
                longitude=point.longitude if point else None,
                distance_km=None,
            )
        )
    return sorted(groups, key=lambda g: (-len(g.pharmacies), g.city))


def _at(group: CityGroup, distance: float) -> CityGroup:
    return CityGroup(
        group.city_key,
        group.city,
        group.region,
        group.pharmacies,
        group.latitude,
        group.longitude,
        round(distance, 1),
    )


def nearby(
    pharmacies: Sequence[Pharmacy],
    locations: Sequence[CityLocation],
    latitude: float,
    longitude: float,
    radius_km: float,
) -> Nearby:
    groups = city_groups(pharmacies, locations)
    placed = [
        _at(g, distance_km(latitude, longitude, g.latitude, g.longitude))
        for g in groups
        if g.latitude is not None and g.longitude is not None
    ]
    placed.sort(key=lambda g: (g.distance_km if g.distance_km is not None else 0.0, g.city))
    inside = tuple(g for g in placed if (g.distance_km or 0.0) <= radius_km)
    outside = next((g for g in placed if (g.distance_km or 0.0) > radius_km), None)
    return Nearby(
        groups=inside,
        nearest_outside=None if inside else outside,
        without_city=sum(1 for p in pharmacies if p.city_key is None),
        without_point=sum(
            len(g.pharmacies) for g in groups if g.latitude is None or g.longitude is None
        ),
    )
