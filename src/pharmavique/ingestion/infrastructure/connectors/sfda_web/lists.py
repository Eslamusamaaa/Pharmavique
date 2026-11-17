"""The official SFDA lists the generic list crawler knows about.

Paths come from SFDA's own "Information Lists" catalog, page counts from one probe request per
list on 2026-11-17 (docs/DATA_SOURCES.md, SA-3). The counts are only a sanity guide: the crawler
always trusts the pager it reads, never these numbers.
"""

from dataclasses import dataclass

GIANT_PAGES = 10_000  # lists with more pages than this are only crawled on request
# Passes 2 and 3 refetch only suspect pages; later passes sweep every page, which on a giant list
# would be days more. So giants stop after the targeted passes and report any gap that is left.
GIANT_MAX_PASSES = 3


@dataclass(frozen=True, slots=True)
class ListSpec:
    name: str  # short id, also the folder name
    path: str  # path of the list page on the SFDA site
    title: str
    probed_pages: int  # the pager's last page when probed; a guide, not a rule

    @property
    def source(self) -> str:
        return f"sfda-list-{self.name}"

    @property
    def is_giant(self) -> bool:
        return self.probed_pages > GIANT_PAGES

    @property
    def max_list_pages(self) -> int:
        """Hard stop if the list never seems to end: double what was probed, at least 100."""
        return max(self.probed_pages * 2, 100)

    def max_passes(self, wanted: int) -> int:
        return min(wanted, GIANT_MAX_PASSES) if self.is_giant else wanted

    def url(self, base_url: str, page: int) -> str:
        return f"{base_url}{self.path}?page={page}"


# Smallest and most valuable first, so a long queue yields useful data early.
SFDA_LISTS: tuple[ListSpec, ...] = (
    ListSpec("drug-shortage", "/en/currentlyInShortageList", "Drug Shortage List", 72),
    ListSpec("safety-labeling", "/en/drugs-safety-labeling", "Drugs Safety Labeling Updates", 26),
    ListSpec("safety-alert", "/en/safety_alert", "Safety Alert", 27),
    ListSpec(
        "unregistered-pharmaceuticals",
        "/en/unregistered-pharmaceuticals-lists",
        "Unregistered pharmaceuticals (Incentive Project List)",
        53,
    ),
    ListSpec("pharmacies", "/en/list_registered_pharmacies", "Licensed Pharmacies", 38),
    ListSpec("drug-approvals", "/en/new-sfda-drug-approvals", "New drug approvals", 46),
    ListSpec("drug-companies", "/en/drug-companies", "Drug Companies", 616),
    ListSpec("vet-drugs", "/en/vet-drugs", "Veterinary drugs", 136),
    ListSpec("cosmetic-ingredients", "/en/AllCosmeticList", "Cosmetic ingredients", 235),
    ListSpec("feed", "/en/feed-list", "Feed List", 2_081),
    ListSpec("medical-equipment", "/en/medical-equipment-list", "Medical Equipment List", 16_040),
    ListSpec("food-products", "/en/products", "Food products (Registered)", 150_480),
    ListSpec(
        "cosmetic-products",
        "/en/cosmetics-list",
        "Cosmetic products (Notification of marketing)",
        298_336,
    ),
)

_BY_NAME = {spec.name: spec for spec in SFDA_LISTS}


def get_list(name: str) -> ListSpec:
    try:
        return _BY_NAME[name]
    except KeyError:
        known = ", ".join(_BY_NAME)
        raise KeyError(f"unknown list {name!r}; known lists: {known}") from None
