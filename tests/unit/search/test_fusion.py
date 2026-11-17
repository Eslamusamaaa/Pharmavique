"""Fusion merges ranked lists from several signals into one explainable ranking."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pharmavique.search.domain.fusion import SignalHit, fuse


def hits(signal: str, *keys: str) -> list[SignalHit]:
    return [
        SignalHit(signal=signal, key=key, rank=i, score=1.0 / i) for i, key in enumerate(keys, 1)
    ]


def test_an_item_ranked_well_by_two_signals_beats_one_ranked_first_by_only_one() -> None:
    fuzzy = hits("fuzzy", "a", "b", "c")
    semantic = hits("semantic", "b", "c", "d")

    result = fuse([fuzzy, semantic])

    assert [r.key for r in result][:2] == ["b", "c"]  # both signals agree on these
    assert {r.key for r in result} == {"a", "b", "c", "d"}


def test_each_result_explains_which_signals_found_it_and_at_what_rank() -> None:
    result = fuse([hits("fuzzy", "a", "b"), hits("semantic", "b")])

    by_key = {r.key: r for r in result}
    assert {(s.signal, s.rank) for s in by_key["b"].hits} == {("fuzzy", 2), ("semantic", 1)}
    assert [s.signal for s in by_key["a"].hits] == ["fuzzy"]


def test_exact_matches_always_come_first_in_their_own_order() -> None:
    fuzzy = hits("fuzzy", "x", "y")
    exact = hits("exact", "z")

    result = fuse([fuzzy, exact], first={"exact"})

    assert [r.key for r in result] == ["z", "x", "y"]
    assert result[0].exact


def test_weights_let_one_signal_count_more() -> None:
    fuzzy = hits("fuzzy", "a", "b")
    semantic = hits("semantic", "b", "a")

    assert fuse([fuzzy, semantic])[0].key == "a"  # tie on score, "a" has the better best rank
    assert fuse([fuzzy, semantic], weights={"semantic": 3.0})[0].key == "b"


def test_ties_are_broken_the_same_way_every_time() -> None:
    result_1 = fuse([hits("s1", "b", "a"), hits("s2", "a", "b")])
    result_2 = fuse([hits("s2", "a", "b"), hits("s1", "b", "a")])

    assert [r.key for r in result_1] == [r.key for r in result_2]


def test_limit_cuts_the_list_and_nothing_gives_nothing() -> None:
    assert [r.key for r in fuse([hits("s", "a", "b", "c")], limit=2)] == ["a", "b"]
    assert fuse([]) == []
    assert fuse([[]]) == []


def test_a_nonpositive_k_is_refused() -> None:
    with pytest.raises(ValueError, match="k must be positive"):
        fuse([hits("s", "a")], k=0)


@given(
    st.lists(st.lists(st.sampled_from("abcdef"), unique=True, max_size=6), max_size=4),
)
def test_every_input_key_appears_once_and_scores_never_increase_down_the_list(
    lists: list[list[str]],
) -> None:
    result = fuse([hits(f"s{i}", *keys) for i, keys in enumerate(lists)])

    assert sorted(r.key for r in result) == sorted({k for keys in lists for k in keys})
    scores = [r.score for r in result]
    assert scores == sorted(scores, reverse=True)
