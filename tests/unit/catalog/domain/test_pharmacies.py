"""Pharmacy addresses and city spellings, as they really occur in the SFDA list."""

import pytest

from pharmavique.catalog.domain.pharmacies import canonical_city, parse_address
from pharmavique.shared_kernel.geo import distance_km, valid_coordinates


@pytest.mark.parametrize(
    ("address", "city", "code"),
    [
        ("Jeddah - JJMA3817", "Jeddah", "JJMA3817"),
        ("Buraidah- QBWE3846", "Buraidah", "QBWE3846"),
        ("RIYADH- RSNA6794", "RIYADH", "RSNA6794"),
        ("DMAI8220", None, "DMAI8220"),  # a bare code: no city
        ("al jouf", "al jouf", None),  # a bare city: no code
        ("الرياض", "الرياض", None),
        ("", None, None),
        (None, None, None),
        ("  Khobar  -  eedb3417 ", "Khobar", "EEDB3417"),
    ],
)
def test_an_address_is_split_into_city_and_short_code(
    address: str | None, city: str | None, code: str | None
) -> None:
    parsed = parse_address(address)
    assert (parsed.city_raw, parsed.short_code) == (city, code)


@pytest.mark.parametrize(
    "spelling",
    ["Khobar", "alkhabar", "Alkhober", "Khober", "Kohber", "الخبر", "KHOBAR"],
)
def test_the_spellings_of_one_city_join(spelling: str) -> None:
    city = canonical_city(spelling)
    assert city is not None
    assert (city.key, city.name) == ("khobar", "Khobar")


def test_riyadh_in_three_scripts_and_cases() -> None:
    keys = {canonical_city(s).key for s in ("Riyadh", "RIYADH", "الرياض", "Riyad")}  # type: ignore[union-attr]
    assert keys == {"riyadh"}


def test_the_medina_spellings_join() -> None:
    names = {
        canonical_city(s).name  # type: ignore[union-attr]
        for s in ("Medina", "Almadinat Al Munawara", "Al Madinat AlMunawara")
    }
    assert names == {"Medina"}


def test_an_unknown_city_keeps_its_own_spelling_and_is_not_merged() -> None:
    city = canonical_city("Al Rass")
    assert city is not None
    assert (city.key, city.name) == ("al rass", "Al Rass")
    other = canonical_city("Unaizah")
    assert other is not None
    assert other.key != city.key


def test_no_city_gives_no_city() -> None:
    assert canonical_city(None) is None
    assert canonical_city("   ") is None
    assert canonical_city("-") is None


def test_distance_between_two_points() -> None:
    # about 0.9 degrees of longitude at 24.7 N is roughly 91 km
    assert distance_km(24.7, 46.7, 24.7, 46.7) == pytest.approx(0.0, abs=1e-9)
    assert distance_km(0.0, 0.0, 0.0, 1.0) == pytest.approx(111.19, abs=0.1)
    assert distance_km(24.7, 46.7, 21.5, 39.2) == pytest.approx(distance_km(21.5, 39.2, 24.7, 46.7))


def test_coordinates_are_validated() -> None:
    assert valid_coordinates(24.7, 46.7)
    assert not valid_coordinates(91, 0)
    assert not valid_coordinates(0, 181)
    assert not valid_coordinates(float("nan"), 0)
