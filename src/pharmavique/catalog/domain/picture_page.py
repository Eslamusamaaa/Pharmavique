"""Whether a shop page a picture came from is about another product than the registered one.

The picture mapping compared the text on the box with the registry; some boxes passed while the
shop page itself names another variant of the brand ("بانادول اكسترا" for PANADOL 500, "QUETTA XR
400 mg" for QUETTA 25 mg). The page address says so, and such a picture is not shown.
"""

import re
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from urllib.parse import unquote, urlparse

# Words that make another product of a brand, in the spellings shop addresses use.
_VARIANT = {
    "extra": "extra", "اكسترا": "extra", "إكسترا": "extra",
    "plus": "plus", "بلس": "plus", "بلص": "plus", "بلوس": "plus",
    "night": "night", "نايت": "night", "cold": "cold", "كولد": "cold", "flu": "flu",
    "sinus": "sinus", "سينوس": "sinus", "advance": "advance", "ادفانس": "advance",
    "أدفانس": "advance", "junior": "junior", "جونيور": "junior", "forte": "forte",
    "فورت": "forte", "فورتي": "forte", "kids": "kids", "baby": "baby", "بيبي": "baby",
    "max": "max", "ماكس": "max", "duo": "duo", "rapid": "rapid", "soluble": "soluble",
    "zero": "zero", "زيرو": "zero", "xr": "release", "sr": "release", "mr": "release",
    "xl": "release", "retard": "release", "ريتارد": "release", "odt": "odt",
    "effervescent": "effervescent", "فوار": "effervescent", "hct": "hct", "amlo": "amlo",
}  # fmt: skip
_WORD = re.compile(r"[a-z؀-ۿ]+")
_AMOUNT = re.compile(r"(\d+(?:[.,]\d+)?)\s*-?\s*(mg|mcg|g|gm|ملجم|مجم|جم)(?![a-z])")
# In an address a decimal point becomes a dash or disappears: "12-5-mg" is 12.5 mg, "05-mg" 0.5 mg.
_PAGE_AMOUNT = re.compile(r"(?:(\d+)\s+)?(\d+)\s*(mg|mcg|g|gm|ملجم|مجم|جم)(?![a-z])")
_TO_MG = {"mg": Decimal(1), "ملجم": Decimal(1), "مجم": Decimal(1), "mcg": Decimal("0.001"),
          "g": Decimal(1000), "gm": Decimal(1000), "جم": Decimal(1000)}  # fmt: skip


def _variants(text: str) -> set[str]:
    return {_VARIANT[w] for w in _WORD.findall(text.lower()) if w in _VARIANT}


def _amounts(text: str) -> set[Decimal]:
    found: set[Decimal] = set()
    for number, unit in _AMOUNT.findall(text.lower()):
        try:
            found.add((Decimal(number.replace(",", ".")) * _TO_MG[unit]).normalize())
        except InvalidOperation:
            continue
    return found


def _page_amounts(slug: str) -> list[set[Decimal]]:
    """Each amount on the page with the readings an address allows for it."""
    found: list[set[Decimal]] = []
    for before, number, unit in _PAGE_AMOUNT.findall(slug.lower()):
        scale = _TO_MG[unit]
        readings = {Decimal(number) * scale}
        if before:
            readings.add(Decimal(f"{before}.{number}") * scale)
        if len(number) > 1 and number.startswith("0"):
            readings.add(Decimal(f"0.{number[1:]}") * scale)
        found.append({r.normalize() for r in readings})
    return found


def _decimal(text: str) -> Decimal | None:
    try:
        return Decimal(text).normalize()
    except (InvalidOperation, ValueError):
        return None


def page_names_another_product(
    page: str | None, trade_names: Iterable[str | None], strengths: Iterable[str]
) -> bool:
    """True when the page address names a variant word ("forte", "xr", "اكسترا") the product's
    names do not have, or only strengths the product does not have (in mg)."""
    if not page:
        return False
    # the whole path: some shops put the name before an id ("/ar/بانادول-اكسترا-24-قرص/p174944527")
    slug = unquote(urlparse(page).path).replace("-", " ").replace("/", " ")
    names = " ".join(name for name in trade_names if name)
    if _variants(slug) - _variants(names):
        return True
    on_page = _page_amounts(slug)
    ours = _amounts(names) | {d for s in strengths if (d := _decimal(s)) is not None}
    return bool(on_page) and not any(readings & ours for readings in on_page)
