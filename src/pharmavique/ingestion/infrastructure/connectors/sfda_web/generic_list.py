"""Parse any SFDA table list (shortage, pharmacies, companies, veterinary, ...).

All the lists share one layout: a server-rendered table with a header row, 10 rows per page and a
`?page=N` pager. Column names are taken from the page itself, never guessed. A page that is not
shaped like a list raises `ParseError`, so a block page can never be mistaken for "no rows". The one
exception is the site's own "No Results Found" heading, which is what a page past the end shows.
"""

import hashlib
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse

from bs4 import BeautifulSoup, Tag

from pharmavique.ingestion.infrastructure.connectors.sfda_web.parser import (
    ParseError,
    current_page_of,
    last_page_of,
)

# A cell that holds only a link to a row's detail page or file, not data.
_ACTION_LABELS = frozenset({"details", "download", "view", "more", "التفاصيل", "عرض", "تحميل"})


def _clean(text: str) -> str:
    return " ".join(text.split())


def _row_key(cells: tuple[tuple[str, str], ...], link: str | None) -> str:
    if link:
        parsed = urlparse(link)
        ids = parse_qs(parsed.query).get("id")
        if ids and ids[0].strip():
            return unquote(ids[0]).strip()
        if parsed.path:
            return parsed.path
    joined = "\x1f".join(value for _, value in cells)
    return "h:" + hashlib.sha1(joined.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class GenericRow:
    cells: tuple[tuple[str, str], ...]  # (header, text) in column order, action columns left out
    link: str | None  # the link in the row (details page, node or file), exactly as written

    @property
    def key(self) -> str:
        """Identity: the id of its details link, else its link path, else a content hash."""
        return _row_key(self.cells, self.link)


@dataclass(frozen=True, slots=True)
class GenericPage:
    headers: tuple[str, ...]
    rows: tuple[GenericRow, ...]
    last_page: int | None
    current_page: int | None


def parse_generic_page(html: str) -> GenericPage:
    soup = BeautifulSoup(html, "html.parser")
    for table in soup.find_all("table"):
        header_cells = table.find_all("th")
        if not header_cells:
            continue
        headers = tuple(
            _clean(th.get_text(" ")) or f"col{index}" for index, th in enumerate(header_cells, 1)
        )
        rows = tuple(_row(tr, headers) for tr in table.find_all("tr") if tr.find("td") is not None)
        data_headers = tuple(h for h in headers if not _is_action_header(h, rows))
        return GenericPage(
            headers=data_headers,
            rows=rows,
            last_page=last_page_of(soup),
            current_page=current_page_of(soup),
        )
    if _is_no_results_page(soup):
        return GenericPage(headers=(), rows=(), last_page=None, current_page=None)
    raise ParseError("no table with a header row was found")


def _is_no_results_page(soup: BeautifulSoup) -> bool:
    """The site's own "No Results Found" heading: what a page number past the end shows.

    Only that exact heading counts, so a block or error page is never read as "the list ended".
    """
    return any(
        _clean(heading.get_text(" ")).lower() == "no results found"
        for heading in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])
    )


def _is_action_header(header: str, rows: tuple[GenericRow, ...]) -> bool:
    return not rows and header.lower() in _ACTION_LABELS


def _row(tr: Tag, headers: tuple[str, ...]) -> GenericRow:
    cells = tr.find_all("td")
    if len(cells) != len(headers):
        raise ParseError(f"row has {len(cells)} cells, expected {len(headers)}")

    data: list[tuple[str, str]] = []
    link: str | None = None
    for header, cell in zip(headers, cells, strict=True):
        anchor = cell.find("a", href=True)
        text = _clean(cell.get_text(" "))
        is_action = isinstance(anchor, Tag) and text.lower() in _ACTION_LABELS
        if isinstance(anchor, Tag) and link is None:
            link = str(anchor["href"])
        if not is_action:
            data.append((header, text))
    return GenericRow(cells=tuple(data), link=link)
