"""Licensed pharmacies as the SFDA list gives them, and the city each one is in.

The list's address is only a city and a Saudi National Address short code (for example
`Jeddah - JJMA3817`): no street and no coordinates. The city is therefore the finest place we can
honestly attach to a pharmacy. The cities are typed by hand on SFDA's side, so the same city appears
under several spellings (`Khobar`, `alkhabar`, `الخبر`); the alias table below joins the spellings
that occur in the real list and nothing else. A city not in the table keeps its own spelling.
"""

import re
from dataclasses import dataclass

from pharmavique.shared_kernel.text import normalize_text

SHORT_CODE = re.compile(r"\b([A-Za-z]{4}\d{4})\b")
_EDGES = " -,.\t" + chr(0x2013) + chr(0x2014)  # hyphen, en dash and em dash around a city

# canonical city name -> the spellings seen in the SFDA list (compared after text normalization)
CITY_ALIASES: dict[str, tuple[str, ...]] = {
    "Riyadh": ("Riyadh", "Riyad", "الرياض"),
    "Jeddah": ("Jeddah",),
    "Mecca": ("Mecca",),
    "Medina": (
        "Medina",
        "Almadinat Al Munawara",
        "Al Madinat Al Munawara",
        "Al Madinat AlMunawara",
    ),
    "Taif": ("Taif",),
    "Thuwal": ("Thuwal", "Thul"),
    "Yanbu": ("Yanbu", "Yunbu"),
    "Khobar": ("Khobar", "alkhabar", "Alkhober", "Khober", "Kohber", "الخبر"),
    "Dammam": ("Dammam", "الدمام"),
    "Al-Ahsa": ("Al-Ahsa",),
    "Hofuf": ("Hofuf",),
    "Hafar Al-Batin": ("Hafar Al-Batin",),
    "Abha": ("Abha", "أبها"),
    "Khamis Mushait": ("Khamis Mushait", "Khamis Mushayt"),
    "Buraidah": ("Buraidah", "Buraydah"),
    "Alhafoof": ("Alhafoof",),
}
_BY_SPELLING: dict[str, str] = {
    normalize_text(spelling): canonical
    for canonical, spellings in CITY_ALIASES.items()
    for spelling in spellings
}


@dataclass(frozen=True, slots=True)
class ParsedAddress:
    city_raw: str | None
    short_code: str | None  # the national address short code, upper-cased


@dataclass(frozen=True, slots=True)
class City:
    key: str  # the normalized canonical name: stable, used to join the coordinates
    name: str  # the name to show


def parse_address(address: str | None) -> ParsedAddress:
    """Split `Jeddah - JJMA3817`, `Riyadh- RSNA6794`, a bare code or a bare city."""
    text = (address or "").strip()
    match = SHORT_CODE.search(text)
    code = match.group(1).upper() if match else None
    rest = SHORT_CODE.sub(" ", text).strip(_EDGES)
    return ParsedAddress(rest or None, code)


def canonical_city(city_raw: str | None) -> City | None:
    if not city_raw or not city_raw.strip():
        return None
    key = normalize_text(city_raw)
    if not key:
        return None
    name = _BY_SPELLING.get(key)
    if name is not None:
        return City(normalize_text(name), name)
    return City(key, city_raw.strip().title() if city_raw.isascii() else city_raw.strip())
