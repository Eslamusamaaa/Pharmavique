"""Fetch the detail page behind each row of an SFDA list that links to one.

Two lists keep their real content on a detail page, not in the list table: `drug-approvals` (the
approved use, which the table only labels) and `drug-shortage` (the trade names affected). The
rules are the same as for the list crawls: robots.txt first, polite pace, stop at once on a block,
a page that does not parse is never kept, and a rerun skips what is already stored.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, Tag

from pharmavique.foundation.http.robots import RobotsPolicy
from pharmavique.ingestion.application.ports import PageFetcher
from pharmavique.ingestion.infrastructure.connectors.sfda_web.errors import (
    FetchFailed,
    NotFound,
)
from pharmavique.ingestion.infrastructure.connectors.sfda_web.parser import ParseError
from pharmavique.ingestion.infrastructure.connectors.sfda_web.polite_fetch import PoliteFetch


@dataclass(frozen=True, slots=True)
class DetailPage:
    pairs: tuple[tuple[str, str], ...]  # (label, value) in page order


def _text(cell: Tag) -> str:
    lines = (line.strip() for line in cell.get_text("\n").splitlines())
    return "\n".join(line for line in lines if line)


def parse_detail_page(html: str) -> DetailPage:
    """The label/value pairs of a detail page.

    A page with a table: a two-cell row is a pair (`Trade name`, `Hyrimoz`); a one-cell row takes
    the table's header as its label (`SFDA Approved Use`). A page without one is a content page
    (a recall, a risk-minimization item): its title, date, labelled fields and attachment links.
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if table is not None:
        return _table_pairs(table)
    return _node_pairs(soup)


def _table_pairs(table: Tag) -> DetailPage:
    header = ""
    pairs: list[tuple[str, str]] = []
    for row in table.find_all("tr"):
        cells = row.find_all(["td", "th"])
        has_data = row.find("td") is not None
        if not has_data:
            header = _text(cells[0]) if cells else header
        elif len(cells) >= 2:
            pairs.append((_text(cells[0]), _text(cells[1])))
        elif header:
            pairs.append((header, _text(cells[0])))
    kept = [(label, value) for label, value in pairs if value]
    if not kept:
        raise ParseError("the detail table has no values")
    return DetailPage(tuple(kept))


def _node_pairs(soup: BeautifulSoup) -> DetailPage:
    scope = soup.find("main") or soup
    pairs: list[tuple[str, str]] = []
    title = scope.find("h2")
    if title is not None and _text(title):
        pairs.append(("Title", _text(title)))
    content = scope.select_one(".node__content")
    if content is None:
        raise ParseError("no content on the detail page")
    for field in content.select(".field"):
        classes: list[str] = list(field.get("class") or [])
        label_tag = field.select_one(".field__label")
        if "field--name-field-file-media" in classes:
            pairs.extend(("Attachment", str(a["href"])) for a in field.select("a[href]"))
            continue
        # a field with a hidden label (the body) is its own item
        own_item = "field__item" in classes or "field__items" in classes
        value_tag = field if own_item else field.select_one(".field__item, .field__items")
        value = _text(value_tag) if value_tag is not None else ""
        if not value:
            continue
        label = _text(label_tag) if label_tag is not None else "Body"
        pairs.append((label, value))
    if len(pairs) < 2:
        raise ParseError("the detail page has no labelled fields")
    return DetailPage(tuple(pairs))


class ListDetailCrawler:
    def __init__(
        self,
        *,
        fetcher: PageFetcher,
        robots: RobotsPolicy,
        base_url: str,
        retries: int = 3,
        retry_wait: float = 30.0,
        sleep: Any = None,
    ) -> None:
        extra = {} if sleep is None else {"sleep": sleep}
        self._polite = PoliteFetch(fetcher, robots, retries=retries, retry_wait=retry_wait, **extra)
        self._base_url = base_url
        self._log = logging.getLogger("sfda.list.details")

    async def run(self, records: list[dict[str, Any]], out_path: Path) -> dict[str, int]:
        """Fetch the detail of every record with a link; returns counts. Safe to repeat."""
        done = _stored_keys(out_path)
        counts = {"stored_before": len(done), "fetched": 0, "failed": 0}
        pending = [r for r in records if r.get("link") and r["key"] not in done]
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("a", encoding="utf-8") as out:
            for index, record in enumerate(pending, start=1):
                url = f"{self._base_url}{record['link']}"
                try:
                    page, parsed = await self._polite.fetch_valid(url, parse_detail_page)
                except (FetchFailed, NotFound) as exc:
                    counts["failed"] += 1
                    self._log.warning("no detail for %s: %s", record["key"], exc)
                    continue
                out.write(
                    json.dumps(
                        {
                            "key": record["key"],
                            "link": record["link"],
                            "detail": [{"label": a, "value": b} for a, b in parsed.pairs],
                            "source_ref": url,
                            "fetched_at": page.fetched_at.isoformat(),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                out.flush()
                counts["fetched"] += 1
                if index % 50 == 0:
                    self._log.info("details %s of %s", index, len(pending))
        return counts


def _stored_keys(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {
        json.loads(line)["key"]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
