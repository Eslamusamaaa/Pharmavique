"""Walk every page of an SFDA list, coping with the site's quirks.

Two quirks of the real site shape this, found while crawling the drugs list:
- past its last page the site does not answer "empty": it answers the last page again, with the
  pager label of that last page. A label lower than the page asked for therefore means "the list
  ended";
- the list order is unstable. Fetching the same page again often shows different rows near its
  edges, so one row can appear on two pages while another appears on none. Fetching again and
  keeping the union of everything seen converges on the full list.

The walker is generic: it only needs a way to get a page, and a key for each row.
"""

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from pharmavique.ingestion.infrastructure.connectors.sfda_web.errors import CrawlError

_HINT_TOLERANCE = 5  # the pager's "last page" link has been seen off by a few pages
_MAX_HOLES_IN_A_ROW = 5  # more empty pages than this in a row means the site is failing
_TARGETED_PASSES = 3  # passes 2 and 3 refetch suspect pages only; later passes sweep every page


class PageLike[R](Protocol):
    @property
    def rows(self) -> Sequence[R]: ...

    @property
    def current_page(self) -> int | None: ...

    @property
    def last_page(self) -> int | None: ...


@dataclass(slots=True)
class WalkResult[R]:
    known: dict[str, tuple[R, int]]  # key -> (row, page where it was first seen)
    pages: dict[int, tuple[R, ...]]  # the latest view of every page
    real_last: int | None  # index of the last real page, None when the walk was limited
    passes: int
    hint: int | None  # the last page the pager of page 0 claimed
    duplicates: list[str] = field(default_factory=list)
    total_rows: int = 0
    expected: int | None = None  # rows the list should hold, None when it cannot be known
    holes: list[int] = field(default_factory=list)  # pages inside the list that stayed empty

    @property
    def page_count(self) -> int:
        return (self.real_last + 1) if self.real_last is not None else len(self.pages)


def classify_page(
    page: PageLike[Any], page_no: int, hint: int | None
) -> Literal["page", "hole", "end"]:
    """What `page` is: a page of rows, a hole in the list, or the sign that the list ended.

    Past the end the site answers the last page again, with the label of that last page (lower
    than the page asked for), or a page with no rows. An empty page *inside* the list is a hole in
    the site's own data (seen live: one page of the feed list, between two full ones), not the
    end. The site answering an earlier page again far before the pager's last page is an error.
    """
    clamped = page.current_page is not None and page.current_page < page_no
    if not (clamped or not page.rows):
        return "page"
    if hint is not None and page_no < hint - _HINT_TOLERANCE:
        if clamped:
            raise CrawlError(f"the list ends early at page {page_no} but the pager says {hint}")
        return "hole"
    if not clamped and hint is not None and page_no <= hint:
        return "hole"
    return "end"


class ListWalker[R]:
    def __init__(
        self,
        *,
        get_page: Callable[[int, int], Awaitable[PageLike[R]]],
        key_of: Callable[[R], str],
        max_pages: int | None,
        max_list_pages: int,
        max_list_passes: int,
        list_patience: int,
        log: logging.Logger,
    ) -> None:
        self._get_page = get_page
        self._key_of = key_of
        self._max_pages = max_pages
        self._max_list_pages = max_list_pages
        self._max_list_passes = max_list_passes
        self._list_patience = list_patience
        self._log = log

    async def walk(self) -> WalkResult[R]:
        pages: dict[int, tuple[R, ...]] = {}
        hint: int | None = None
        real_last: int | None = None
        holes: list[int] = []
        holes_in_a_row = 0
        page_no = 0

        while self._max_pages is None or page_no < self._max_pages:
            if page_no >= self._max_list_pages:
                raise CrawlError(f"the list has more than {self._max_list_pages} pages")
            parsed = await self._get_page(page_no, 1)
            if page_no == 0:
                hint = parsed.last_page
            kind = classify_page(parsed, page_no, hint)
            if kind == "end":
                real_last = page_no - 1
                break
            if kind == "hole":
                holes.append(page_no)
                holes_in_a_row += 1
                if holes_in_a_row >= _MAX_HOLES_IN_A_ROW:
                    raise CrawlError(
                        f"{holes_in_a_row} empty pages in a row at page {page_no}: "
                        "the site may be failing"
                    )
                page_no += 1
                continue
            holes_in_a_row = 0
            pages[page_no] = tuple(parsed.rows)
            if page_no % 20 == 0:
                self._log.info("list page %s of %s", page_no, hint)
            page_no += 1

        known: dict[str, tuple[R, int]] = {}
        duplicates: list[str] = []
        for number in sorted(pages):
            for row in pages[number]:
                key = self._key_of(row)
                if key in known:
                    duplicates.append(key)
                else:
                    known[key] = (row, number)

        passes = 1
        expected: int | None = None
        if self._max_pages is None and real_last is not None:
            passes = await self._repair(pages, known, real_last, holes)
            expected = self._expected_total(pages, real_last)
            if len(known) < expected:
                self._log.warning(
                    "the list shows %s rows but %s were expected; see the manifest",
                    len(known),
                    expected,
                )

        return WalkResult(
            known=known,
            pages=pages,
            real_last=real_last,
            passes=passes,
            hint=hint,
            duplicates=duplicates,
            total_rows=sum(len(page) for page in pages.values()),
            expected=expected,
            holes=holes,
        )

    async def _repair(
        self,
        pages: dict[int, tuple[R, ...]],
        known: dict[str, tuple[R, int]],
        real_last: int,
        holes: list[int],
    ) -> int:
        """Fetch pages again and keep the union of everything seen. Returns the passes used.

        Passes 2 and 3 target pages that look wrong; later passes sweep every page, because a
        skipped row leaves no duplicate to point at. It stops when nothing is missing, after
        `list_patience` passes in a row that found nothing new, or at `max_list_passes`.
        """
        passes = 1
        idle = 0
        while passes < self._max_list_passes:
            if len(known) >= self._expected_total(pages, real_last):
                break
            suspects = self._suspect_pages(pages)
            targets = (suspects if passes < _TARGETED_PASSES and suspects else set(pages)) | set(
                holes
            )
            passes += 1
            self._log.info(
                "repair pass %s: fetching %s list pages again (%s of %s rows known)",
                passes,
                len(targets),
                len(known),
                self._expected_total(pages, real_last),
            )
            gained = 0
            for number in sorted(targets):
                parsed = await self._get_page(number, passes)
                if parsed.current_page is not None and parsed.current_page != number:
                    continue  # the site answered with a different page; ignore it
                if number in holes:
                    if not parsed.rows:
                        continue  # still a hole
                    holes.remove(number)  # it answers now
                pages[number] = tuple(parsed.rows)
                for row in parsed.rows:
                    key = self._key_of(row)
                    if key not in known:
                        known[key] = (row, number)
                        gained += 1
            idle = idle + 1 if gained == 0 else 0
            if idle >= self._list_patience:
                break
        return passes

    @staticmethod
    def _expected_total(pages: dict[int, tuple[R, ...]], real_last: int) -> int:
        """Rows the list should hold: full pages (sized like page 0) plus the last page."""
        return len(pages[0]) * real_last + len(pages[real_last])

    def _suspect_pages(self, pages: dict[int, tuple[R, ...]]) -> set[int]:
        """Pages to fetch again: one that repeats the page before, or shares rows with another."""
        suspects: set[int] = set()
        first_seen: dict[str, int] = {}
        previous: tuple[str, ...] | None = None
        for number in sorted(pages):
            keys = tuple(self._key_of(row) for row in pages[number])
            if previous is not None and keys == previous:
                suspects.add(number)
            for key in keys:
                if key in first_seen and first_seen[key] != number:
                    suspects.update({number, first_seen[key]})
                else:
                    first_seen.setdefault(key, number)
            previous = keys
        return suspects
