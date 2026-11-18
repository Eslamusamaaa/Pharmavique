"""The walker is generic: these tests use plain strings as rows, not SFDA drug rows."""

import logging
from collections.abc import Sequence
from dataclasses import dataclass

import pytest

from pharmavique.ingestion.infrastructure.connectors.sfda_web.errors import CrawlError
from pharmavique.ingestion.infrastructure.connectors.sfda_web.list_walker import ListWalker


@dataclass(frozen=True)
class FakePage:
    rows: Sequence[str]
    current_page: int | None
    last_page: int | None


class Site:
    """A list of pages. `views[n]` is what fetches of page n return, in order (the last repeats)."""

    def __init__(self, views: dict[int, list[list[str]]], hint: int | None) -> None:
        self.views = {n: list(v) for n, v in views.items()}
        self.hint = hint
        self.fetches: list[tuple[int, int]] = []
        self.last = max(views)

    async def get(self, page_no: int, pass_no: int) -> FakePage:
        self.fetches.append((page_no, pass_no))
        shown = min(page_no, self.last)  # past the end the site clamps to its last page
        queue = self.views[shown]
        rows = queue.pop(0) if len(queue) > 1 else queue[0]
        return FakePage(rows, shown, self.hint)


def walker(site: Site, **overrides: int | None) -> ListWalker[str]:
    settings: dict[str, int | None] = {
        "max_pages": None,
        "max_list_pages": 100,
        "max_list_passes": 8,
        "list_patience": 3,
    }
    settings.update(overrides)
    return ListWalker[str](
        get_page=site.get,
        key_of=lambda row: row,
        max_pages=settings["max_pages"],
        max_list_pages=int(settings["max_list_pages"] or 0),
        max_list_passes=int(settings["max_list_passes"] or 0),
        list_patience=int(settings["list_patience"] or 0),
        log=logging.getLogger("test"),
    )


async def test_walks_to_the_page_the_pager_label_says_is_last() -> None:
    site = Site({0: [["a", "b"]], 1: [["c", "d"]], 2: [["e"]]}, hint=2)

    result = await walker(site).walk()

    assert sorted(result.known) == ["a", "b", "c", "d", "e"]
    assert (result.real_last, result.page_count, result.expected) == (2, 3, 5)
    assert [n for n, _ in site.fetches] == [0, 1, 2, 3]  # page 3 answers with page 2 again


async def test_unstable_edges_are_repaired_by_fetching_again_and_keeping_the_union() -> None:
    # page 1 first shows a shifted slice (b repeated, c lost), then the right one
    site = Site({0: [["a", "b"]], 1: [["b", "d"], ["c", "d"]], 2: [["e"]]}, hint=2)

    result = await walker(site).walk()

    assert sorted(result.known) == ["a", "b", "c", "d", "e"]
    assert result.passes == 2


async def test_it_gives_up_after_the_patience_runs_out_and_reports_the_gap() -> None:
    site = Site({0: [["a", "b"]], 1: [["b", "d"]], 2: [["e"]]}, hint=2)  # c never shows up

    result = await walker(site, list_patience=2).walk()

    assert "c" not in result.known
    assert result.expected == 5
    assert len(result.known) == 4
    assert result.passes == 3  # the first pass plus two with nothing new


async def test_a_limited_walk_does_not_try_to_repair() -> None:
    site = Site({0: [["a", "b"]], 1: [["b", "d"]], 2: [["e"]]}, hint=2)

    result = await walker(site, max_pages=2).walk()

    assert result.real_last is None
    assert result.expected is None
    assert result.passes == 1


async def test_an_end_far_before_the_pager_says_is_refused() -> None:
    site = Site({0: [["a"]], 1: [["b"]]}, hint=40)

    with pytest.raises(CrawlError, match="ends early"):
        await walker(site).walk()


async def test_a_list_that_never_ends_stops_at_the_page_cap() -> None:
    @dataclass
    class Endless:
        async def get(self, page_no: int, pass_no: int) -> FakePage:
            return FakePage([f"row{page_no}"], None, None)

    endless = Endless()
    w = ListWalker[str](
        get_page=endless.get,
        key_of=lambda row: row,
        max_pages=None,
        max_list_pages=5,
        max_list_passes=3,
        list_patience=2,
        log=logging.getLogger("test"),
    )

    with pytest.raises(CrawlError, match="more than 5"):
        await w.walk()


async def test_an_empty_page_inside_the_list_is_a_hole_skipped_and_recorded() -> None:
    # seen live on the feed list: page 119 answers "No Results Found", pages 118 and 120 are full
    site = Site({0: [["a", "b"]], 1: [[]], 2: [["e", "f"]], 3: [["g"]]}, hint=3)

    result = await walker(site).walk()

    assert sorted(result.known) == ["a", "b", "e", "f", "g"]
    assert result.holes == [1]
    assert result.real_last == 3


async def test_many_empty_pages_in_a_row_stop_the_walk() -> None:
    views: dict[int, list[list[str]]] = {
        0: [["a"]],
        1: [[]],
        2: [[]],
        3: [[]],
        4: [[]],
        5: [[]],
        6: [["z"]],
    }
    site = Site(views, hint=6)

    with pytest.raises(CrawlError, match="in a row"):
        await walker(site).walk()


async def test_a_hole_is_asked_for_again_in_the_repair_passes_and_filled_when_it_answers() -> None:
    # page 1 is empty the first time and has rows afterwards
    site = Site({0: [["a", "b"]], 1: [[], ["c", "d"]], 2: [["e"]]}, hint=2)

    result = await walker(site).walk()

    assert sorted(result.known) == ["a", "b", "c", "d", "e"]
    assert result.holes == []
