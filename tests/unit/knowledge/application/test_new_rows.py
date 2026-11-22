"""Which rows of a daily list run still need their documents fetched and cut into chunks."""

from pharmavique.knowledge.application.new_rows import new_rows


def row(key: str) -> dict[str, object]:
    return {"key": key, "list": [], "provenance": {}}


def test_only_rows_that_no_run_and_no_chunk_has_seen_are_new() -> None:
    rows = [row("a"), row("b"), row("c")]

    assert [r["key"] for r in new_rows(rows, known={"a", "c"})] == ["b"]


def test_the_order_of_the_run_is_kept() -> None:
    rows = [row("z"), row("m"), row("a")]

    assert [r["key"] for r in new_rows(rows, known=set())] == ["z", "m", "a"]


def test_a_row_that_appears_twice_in_the_run_is_taken_once() -> None:
    rows = [row("a"), row("a"), row("b")]

    assert [r["key"] for r in new_rows(rows, known=set())] == ["a", "b"]


def test_nothing_is_new_when_everything_is_known() -> None:
    assert new_rows([row("a")], known={"a", "b"}) == []
