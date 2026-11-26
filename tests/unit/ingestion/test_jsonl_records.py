"""A crawl's `records.jsonl` as a record source, for when the raw pages are not on this machine."""

import json
from pathlib import Path

from pharmavique.ingestion.infrastructure.connectors.sfda_web.store import SnapshotStore
from pharmavique.ingestion.infrastructure.connectors.sfda_web.stored_records import (
    ChangedRecords,
    JsonlRecords,
)


def record(key: str, en: bool = True) -> dict[str, object]:
    return {
        "key": key,
        "list": {"trade_name": f"TRADE-{key}"},
        "en": [{"label": "Register Number", "value": key}] if en else None,
        "ar": None,
        "provenance": {"en_fetched_at": "2026-11-17T07:56:01+00:00", "trust": "official"},
    }


def write(tmp_path: Path, *records: dict[str, object]) -> SnapshotStore:
    store = SnapshotStore(tmp_path, "run-1")
    store.records_path.parent.mkdir(parents=True)
    lines = [json.dumps(r) for r in records]
    store.records_path.write_text("\n".join(lines) + "\n\n", encoding="utf-8")
    return store


def test_every_record_with_english_details_is_read_in_file_order(tmp_path: Path) -> None:
    store = write(tmp_path, record("k2"), record("k1"))

    keys = [r["key"] for r in JsonlRecords(store).records()]

    assert keys == ["k2", "k1"]


def test_records_without_english_details_are_passed_over(tmp_path: Path) -> None:
    store = write(tmp_path, record("k1"), record("k2", en=False))

    keys = [r["key"] for r in JsonlRecords(store).records()]

    assert keys == ["k1"]


def test_keys_to_skip_are_left_out(tmp_path: Path) -> None:
    store = write(tmp_path, record("k1"), record("k2"))

    keys = [r["key"] for r in JsonlRecords(store).records(skip={"k1"})]

    assert keys == ["k2"]


def test_a_run_without_records_file_yields_nothing(tmp_path: Path) -> None:
    assert list(JsonlRecords(SnapshotStore(tmp_path, "missing")).records()) == []


# ---- load only what changed since the run that was last loaded (Neon bills every byte read) -----


def run(tmp_path: Path, run_id: str, *records: dict[str, object]) -> SnapshotStore:
    store = SnapshotStore(tmp_path, run_id)
    store.records_path.parent.mkdir(parents=True, exist_ok=True)
    store.records_path.write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
    )
    return store


def changed(**fields: object) -> dict[str, object]:
    base = record("k1")
    return {**base, **fields}


def test_a_record_identical_to_the_last_loaded_run_is_left_out(tmp_path: Path) -> None:
    run(tmp_path, "old", record("k1"), record("k2"))
    new = run(tmp_path, "new", record("k1"), record("k2"))

    assert list(ChangedRecords(JsonlRecords(new), SnapshotStore(tmp_path, "old")).records()) == []


def test_a_new_drug_and_a_changed_drug_are_loaded(tmp_path: Path) -> None:
    run(tmp_path, "old", record("k1"))
    new = run(
        tmp_path,
        "new",
        changed(list={"trade_name": "RENAMED"}),
        record("k2"),
    )

    keys = [
        r["key"]
        for r in ChangedRecords(JsonlRecords(new), SnapshotStore(tmp_path, "old")).records()
    ]

    assert keys == ["k1", "k2"]


def test_a_new_fetch_time_alone_is_not_a_change(tmp_path: Path) -> None:
    run(tmp_path, "old", record("k1"))
    new = run(tmp_path, "new", changed(provenance={"en_fetched_at": "2026-11-26T01:00:00+00:00"}))

    assert list(ChangedRecords(JsonlRecords(new), SnapshotStore(tmp_path, "old")).records()) == []


def test_arabic_details_that_changed_are_a_change(tmp_path: Path) -> None:
    run(tmp_path, "old", record("k1"))
    new = run(tmp_path, "new", changed(ar=[{"label": "السعر", "value": "12"}]))

    assert (
        len(list(ChangedRecords(JsonlRecords(new), SnapshotStore(tmp_path, "old")).records())) == 1
    )


def test_without_the_earlier_run_every_record_is_loaded(tmp_path: Path) -> None:
    new = run(tmp_path, "new", record("k1"), record("k2"))

    found = ChangedRecords(JsonlRecords(new), SnapshotStore(tmp_path, "missing")).records()

    assert [r["key"] for r in found] == ["k1", "k2"]


def test_the_skip_list_still_applies(tmp_path: Path) -> None:
    new = run(tmp_path, "new", record("k1"), record("k2"))

    found = ChangedRecords(JsonlRecords(new), SnapshotStore(tmp_path, "missing")).records({"k1"})

    assert [r["key"] for r in found] == ["k2"]
