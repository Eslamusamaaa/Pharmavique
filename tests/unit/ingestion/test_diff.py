from collections.abc import Mapping

from hypothesis import given
from hypothesis import strategies as st

from pharmavique.ingestion.domain.diff import diff
from pharmavique.ingestion.domain.records import FieldChange, SourceRecord


def rec(key: str, **fields: str) -> SourceRecord:
    return SourceRecord(key, fields)


def snapshot(*records: SourceRecord) -> Mapping[str, SourceRecord]:
    return {r.key: r for r in records}


def test_identical_snapshots_have_no_changes() -> None:
    old = snapshot(rec("a", price="1"), rec("b", price="2"))

    result = diff(old, old)

    assert result.is_empty
    assert result.counts() == {"added": 0, "removed": 0, "changed": 0}


def test_new_keys_are_added_and_missing_keys_are_removed() -> None:
    old = snapshot(rec("a", price="1"), rec("b", price="2"))
    new = snapshot(rec("b", price="2"), rec("c", price="3"))

    result = diff(old, new)

    assert [r.key for r in result.added] == ["c"]
    assert [r.key for r in result.removed] == ["a"]
    assert result.changed == ()


def test_changed_value_is_reported_per_field() -> None:
    old = snapshot(rec("a", price="1", name="X"))
    new = snapshot(rec("a", price="2", name="X"))

    (change,) = diff(old, new).changed

    assert change.key == "a"
    assert change.changes == (FieldChange("price", "1", "2"),)


def test_field_that_appears_or_disappears_is_a_change_with_none() -> None:
    old = snapshot(rec("a", price="1", note="n"))
    new = snapshot(rec("a", price="1", extra="e"))

    (change,) = diff(old, new).changed

    assert change.changes == (
        FieldChange("extra", None, "e"),
        FieldChange("note", "n", None),
    )


def test_empty_string_is_different_from_a_missing_field() -> None:
    old = snapshot(rec("a", price="1"))
    new = snapshot(rec("a", price="1", note=""))

    (change,) = diff(old, new).changed

    assert change.changes == (FieldChange("note", None, ""),)


def test_results_are_sorted_by_key_so_reports_are_stable() -> None:
    old = snapshot(rec("m", v="1"), rec("z", v="1"), rec("b", v="1"))
    new = snapshot(rec("m", v="2"), rec("z", v="2"), rec("b", v="2"), rec("k"), rec("c"))

    result = diff(old, new)

    assert [r.key for r in result.added] == ["c", "k"]
    assert [c.key for c in result.changed] == ["b", "m", "z"]


field_values = st.dictionaries(
    st.sampled_from(["a", "b", "c", "d"]), st.sampled_from(["", "1", "2", "x"]), max_size=4
)
snapshots = st.dictionaries(
    st.sampled_from(["k1", "k2", "k3", "k4"]), field_values, max_size=4
).map(lambda d: {k: SourceRecord(k, v) for k, v in d.items()})


@given(snapshots)
def test_a_snapshot_never_differs_from_itself(old: dict[str, SourceRecord]) -> None:
    assert diff(old, old).is_empty


@given(snapshots, snapshots)
def test_additions_and_removals_mirror_when_inputs_are_swapped(
    old: dict[str, SourceRecord], new: dict[str, SourceRecord]
) -> None:
    forward = diff(old, new)
    backward = diff(new, old)

    assert [r.key for r in forward.added] == [r.key for r in backward.removed]
    assert [r.key for r in forward.removed] == [r.key for r in backward.added]
    assert [c.key for c in forward.changed] == [c.key for c in backward.changed]


@given(snapshots, snapshots)
def test_applying_the_reported_changes_to_old_gives_new(
    old: dict[str, SourceRecord], new: dict[str, SourceRecord]
) -> None:
    result = diff(old, new)
    rebuilt = {
        k: dict(v.fields) for k, v in old.items() if k not in {r.key for r in result.removed}
    }
    for record in result.added:
        rebuilt[record.key] = dict(record.fields)
    for change in result.changed:
        for item in change.changes:
            if item.new is None:
                rebuilt[change.key].pop(item.field, None)
            else:
                rebuilt[change.key][item.field] = item.new

    assert rebuilt == {k: dict(v.fields) for k, v in new.items()}
