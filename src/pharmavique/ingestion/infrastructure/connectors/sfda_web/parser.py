"""Pure HTML parsing for the SFDA public drugs list and drug details pages.

Nothing here does I/O. Field names come from the page itself: the list columns are matched by
their header text and the details fields keep the label exactly as the page shows it (in English
or Arabic). A page that does not look as expected raises `ParseError`, so a block page, a CAPTCHA
or a layout change can never be mistaken for "no data".
"""

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup, Tag


class ParseError(Exception):
    """The page is not shaped like an SFDA list or details page."""


@dataclass(frozen=True, slots=True)
class ListRow:
    scientific_name: str
    trade_name: str
    strength: str
    dosage_form: str
    price: str
    details_href: str
    registration_key: str  # the `id` parameter of the details link


@dataclass(frozen=True, slots=True)
class ListPage:
    rows: tuple[ListRow, ...]
    last_page: int | None  # highest `?page=N` seen in the pager, if any
    current_page: int | None = None  # 0-based index of the active pager item, if there is one


@dataclass(frozen=True, slots=True)
class DetailField:
    label: str
    lines: tuple[str, ...]

    @property
    def value(self) -> str:
        return "\n".join(self.lines)


@dataclass(frozen=True, slots=True)
class DetailsPage:
    fields: tuple[DetailField, ...]


# Header text (lower-cased) accepted for each column. The site spells "Dosage" as "Doesage".
_COLUMNS: dict[str, tuple[str, ...]] = {
    "scientific_name": ("scientific name",),
    "trade_name": ("trade name",),
    "strength": ("strength",),
    "dosage_form": ("dosage form", "doesage form"),
    "price": ("price",),
    "details": ("details",),
}
_PAGER_HREF = re.compile(r"(?:^|[?&])page=(\d+)(?:&|$)")


def _clean(text: str) -> str:
    return " ".join(text.split())


def _column_indexes(headers: list[str]) -> dict[str, int] | None:
    lowered = [h.lower() for h in headers]
    indexes: dict[str, int] = {}
    for name, candidates in _COLUMNS.items():
        found = next((i for i, h in enumerate(lowered) if h in candidates), None)
        if found is None:
            return None
        indexes[name] = found
    return indexes


def _registration_key(href: str) -> str:
    ids = parse_qs(urlparse(href).query).get("id")
    if not ids or not ids[0].strip():
        raise ParseError(f"details link has no id parameter: {href!r}")
    return ids[0].strip()


def parse_list_page(html: str) -> ListPage:
    soup = BeautifulSoup(html, "html.parser")

    for table in soup.find_all("table"):
        header_cells = table.find_all("th")
        headers = [_clean(th.get_text(" ")) for th in header_cells]
        indexes = _column_indexes(headers)
        if indexes is None:
            continue
        rows = tuple(_list_row(tr, indexes, len(headers)) for tr in _data_rows(table))
        return ListPage(rows=rows, last_page=last_page_of(soup), current_page=current_page_of(soup))

    raise ParseError("no table with the expected drug list columns was found")


def _data_rows(table: Tag) -> list[Tag]:
    return [tr for tr in table.find_all("tr") if tr.find("td") is not None]


def _list_row(tr: Tag, indexes: dict[str, int], column_count: int) -> ListRow:
    cells = tr.find_all("td")
    if len(cells) != column_count:
        raise ParseError(f"list row has {len(cells)} cells, expected {column_count}")

    anchor = cells[indexes["details"]].find("a", href=True)
    if not isinstance(anchor, Tag):
        raise ParseError("list row has no details link")
    href = str(anchor["href"])

    def text(name: str) -> str:
        return _clean(cells[indexes[name]].get_text(" "))

    return ListRow(
        scientific_name=text("scientific_name"),
        trade_name=text("trade_name"),
        strength=text("strength"),
        dosage_form=text("dosage_form"),
        price=text("price"),
        details_href=href,
        registration_key=_registration_key(href),
    )


def current_page_of(soup: BeautifulSoup) -> int | None:
    """The page the pager marks as active (shown 1-based on the site, returned 0-based)."""
    item = soup.select_one("li.page-item.active")
    if item is None:
        return None
    digits = re.search(r"\d+", item.get_text())
    return int(digits.group(0)) - 1 if digits else None


def last_page_of(soup: BeautifulSoup) -> int | None:
    pages = []
    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"])
        if "details_data" in href:
            continue
        match = _PAGER_HREF.search(href)
        if match:
            pages.append(int(match.group(1)))
    return max(pages) if pages else None


def parse_details_page(html: str) -> DetailsPage:
    soup = BeautifulSoup(html, "html.parser")
    fields: list[DetailField] = []

    for tr in soup.find_all("tr"):
        th = tr.find("th")
        td = tr.find("td")
        if not isinstance(th, Tag) or not isinstance(td, Tag):
            continue
        label = _clean(th.get_text(" "))
        if not label:
            continue
        lines = tuple(line for line in (_clean(s) for s in td.get_text("\n").split("\n")) if line)
        fields.append(DetailField(label=label, lines=lines))

    if not fields:
        raise ParseError("no label/value rows were found on the details page")
    return DetailsPage(fields=tuple(fields))
