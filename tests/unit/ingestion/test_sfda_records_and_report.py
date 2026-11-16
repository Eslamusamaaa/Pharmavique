from collections.abc import Mapping
from typing import Any

from pharmavique.ingestion.domain.diff import diff
from pharmavique.ingestion.domain.records import SourceRecord
from pharmavique.ingestion.infrastructure.connectors.sfda_web.records import (
    to_source_record,
    to_source_records,
)
from pharmavique.ingestion.infrastructure.connectors.sfda_web.report import (
    changes_to_json,
    render_markdown,
)


def raw(key: str, price: str = "9.5", **extra: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "key": key,
        "list": {"trade_name": f"T-{key}", "price": price, "list_page": 7},
        "en": [
            {"label": "Register Number", "value": key},
            {"label": "Price", "value": price},
            {"label": "Price", "value": "dup"},
        ],
        "ar": [{"label": "السعر", "value": price}],
        "provenance": {"en_fetched_at": "2026-01-01T00:00:00+00:00"},
    }
    record.update(extra)
    return record


def test_flattening_prefixes_fields_by_section_and_language() -> None:
    record = to_source_record(raw("k1"))

    assert record.key == "k1"
    assert record.fields["list.trade_name"] == "T-k1"
    assert record.fields["en.Register Number"] == "k1"
    assert record.fields["ar.السعر"] == "9.5"


def test_page_number_and_provenance_are_not_part_of_the_comparison() -> None:
    fields = to_source_record(raw("k1")).fields

    assert "list.list_page" not in fields
    assert not any(name.startswith("provenance") for name in fields)


def test_repeated_labels_get_a_numbered_suffix_instead_of_overwriting() -> None:
    fields = to_source_record(raw("k1")).fields

    assert fields["en.Price"] == "9.5"
    assert fields["en.Price#2"] == "dup"


def test_a_missing_language_section_just_has_no_fields() -> None:
    fields = to_source_record(raw("k1", ar=None)).fields

    assert not any(name.startswith("ar.") for name in fields)


def test_records_are_indexed_by_key() -> None:
    records = to_source_records([raw("k1"), raw("k2")])

    assert sorted(records) == ["k1", "k2"]


def changes(old: list[dict[str, Any]], new: list[dict[str, Any]]) -> tuple[Any, Mapping[str, Any]]:
    new_records = to_source_records(new)
    names = {r["key"]: r["list"]["trade_name"] for r in new + old}
    return diff(to_source_records(old), new_records), names


def test_json_report_lists_every_change_with_old_and_new_values() -> None:
    result, names = changes([raw("a"), raw("gone")], [raw("a", price="12"), raw("fresh")])

    report = changes_to_json(result, names, old_run="r1", new_run="r2")

    assert report["old_run"] == "r1"
    assert report["counts"] == {"added": 1, "removed": 1, "changed": 1}
    assert [x["key"] for x in report["added"]] == ["fresh"]
    assert [x["key"] for x in report["removed"]] == ["gone"]
    changed = report["changed"][0]
    assert changed["key"] == "a"
    assert {"field": "list.price", "old": "9.5", "new": "12"} in changed["changes"]


def test_markdown_report_highlights_price_changes_and_says_when_nothing_changed() -> None:
    result, names = changes([raw("a")], [raw("a", price="12")])
    text = render_markdown(result, names, old_run="r1", new_run="r2")

    assert "Price changes" in text
    assert "T-a" in text
    assert "9.5" in text
    assert "12" in text

    empty, names = changes([raw("a")], [raw("a")])
    assert "No changes" in render_markdown(empty, names, old_run="r1", new_run="r2")


def test_markdown_report_caps_long_lists_and_says_so() -> None:
    old: list[dict[str, Any]] = []
    new = [raw(f"k{i:03d}") for i in range(30)]
    result, names = changes(old, new)

    text = render_markdown(result, names, old_run="r1", new_run="r2", limit=10)

    assert "30 added" in text
    assert "20 more" in text


def test_a_source_record_type_is_what_the_diff_works_on() -> None:
    assert isinstance(to_source_record(raw("k1")), SourceRecord)
