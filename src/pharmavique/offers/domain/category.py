"""Which kind of listing is this, from the retailer's own category path.

Never from the product name.

A listing is a `medicine` only when its category path says so. Anything the rules do not know is
`unclassified` and is never compared with the registry. These are starting word lists, tuned from
the
categories the first crawls really meet (the crawl reports the paths it could not classify).
"""

import re

from pharmavique.offers.domain.model import ListingCategory
from pharmavique.shared_kernel.text import normalize_text

__all__ = ["classify", "extract_pack_text"]

# Checked in this order: a vitamin inside "Medicines" is `other`, a skin cream inside it is a
# cosmetic.
_OTHER = (
    "vitamin", "supplement", "nutrition", "food", "baby milk", "formula", "herbal", "diet",
    "فيتامين", "مكملات", "مكمل", "تغذيه", "اغذيه", "حليب", "اعشاب", "رجيم",
)  # fmt: skip
_DEVICE = (
    "device", "equipment", "monitor", "thermometer", "blood pressure", "glucose meter", "nebuliz",
    "orthopedic", "brace", "wheelchair", "first aid", "medical supplies",
    "اجهزه", "جهاز", "معدات", "ميزان حراره", "قياس", "مستلزمات طبيه",
)  # fmt: skip
_COSMETIC = (
    "makeup", "make up", "skin care", "skincare", "hair", "beauty", "fragrance", "perfume",
    "cosmetic", "personal care", "deodorant", "shampoo", "nail", "lipstick", "sun care",
    "body care",
    "مكياج", "عنايه بالبشره", "بشره", "شعر", "عطور", "تجميل", "عنايه شخصيه", "مزيل", "شامبو",
)  # fmt: skip
_MEDICINE = (
    "medicine", "medication", "drug", "pharmaceutical", "prescription", "otc", "over the counter",
    "pain relief", "cough", "cold", "flu", "allergy", "antibiotic",
    "ادويه", "دواء", "الادويه", "ادوية", "مسكنات",
)  # fmt: skip

_PACK = re.compile(
    r"\b(\d+)\s*(tablets?|tabs?|capsules?|caps?|sachets?|ampoules?|vials?|ml|gm?|"
    r"قرص|أقراص|اقراص|كبسولة|كبسولات|مل|جم)(?![a-z])",
    re.IGNORECASE,
)


_START = r"(?<![a-z؀-ۿ])"
_END = r"(?![a-z؀-ۿ])"


def _has(words: tuple[str, ...], text: str, *, whole: bool = False) -> bool:
    """A word that starts a word of the text ("nebuliz" finds "nebulizer"); with `whole` it must
    be the whole word ("flu" must not find "fluoride")."""
    end = _END if whole else ""
    return any(re.search(_START + re.escape(w) + end, text) for w in words)


def classify(category_path: tuple[str, ...], name: str = "") -> ListingCategory:
    """The category of a listing; `name` is accepted so callers cannot be tempted to use it: it is
    ignored on purpose."""
    del name
    text = " ".join(normalize_text(part) for part in category_path)
    if not text.strip():
        return ListingCategory.UNCLASSIFIED
    if _has(_OTHER, text):
        return ListingCategory.OTHER
    if _has(_DEVICE, text):
        return ListingCategory.DEVICE
    if _has(_COSMETIC, text):
        return ListingCategory.COSMETIC
    if _has(_MEDICINE, text, whole=True):
        return ListingCategory.MEDICINE
    return ListingCategory.UNCLASSIFIED


def extract_pack_text(name: str) -> str | None:
    """ "24 tablets", "30 قرص", "120 ml": the first pack size a name writes, or None."""
    found = _PACK.search(name)
    if found is None:
        return None
    return f"{found.group(1)} {found.group(2).lower()}"
