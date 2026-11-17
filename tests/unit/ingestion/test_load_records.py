"""The ingestion use case that moves stored source records into the catalog, tested on fakes."""

from collections.abc import Iterator, Mapping, Sequence
from typing import Any

import pytest

from pharmavique.ingestion.application.load_records import LoadRecordsIntoCatalog
from pharmavique.ingestion.application.ports import BatchOutcome


def record(key: str) -> dict[str, Any]:
    return {"key": key}


class ListSource:
    def __init__(self, keys: list[str]) -> None:
        self._keys = keys

    def records(self) -> Iterator[Mapping[str, Any]]:
        return iter(record(k) for k in self._keys)


class RecordingGateway:
    def __init__(self, outcomes: dict[str, BatchOutcome] | None = None) -> None:
        self.batches: list[list[str]] = []
        self._outcomes = outcomes or {}

    async def apply(self, records: Sequence[Mapping[str, Any]]) -> BatchOutcome:
        keys = [str(r["key"]) for r in records]
        self.batches.append(keys)
        merged = BatchOutcome(added=len(keys))
        for key in keys:
            if key in self._outcomes:
                return self._outcomes[key]
        return merged


async def test_records_are_sent_in_batches_of_the_requested_size() -> None:
    gateway = RecordingGateway()
    use_case = LoadRecordsIntoCatalog(gateway, batch_size=2)

    report = await use_case.run(ListSource(["a", "b", "c", "d", "e"]))

    assert gateway.batches == [["a", "b"], ["c", "d"], ["e"]]
    assert (report.batches, report.records) == (3, 5)


async def test_totals_add_up_across_batches() -> None:
    gateway = RecordingGateway(
        {
            "a": BatchOutcome(added=1, price_changed=1),
            "c": BatchOutcome(unchanged=2, details_changed=1, relisted=1),
        }
    )
    use_case = LoadRecordsIntoCatalog(gateway, batch_size=2)

    report = await use_case.run(ListSource(["a", "b", "c", "d"]))

    assert (report.added, report.price_changed) == (1, 1)
    assert (report.unchanged, report.details_changed, report.relisted) == (2, 1, 1)


async def test_skipped_rejected_and_odd_records_are_reported_not_hidden() -> None:
    gateway = RecordingGateway(
        {
            "a": BatchOutcome(
                skipped=("s1",),
                rejected=(("r1", "not a valid ATC code"),),
                issues={"i1": ("ingredient names and strengths do not line up",)},
            ),
            "c": BatchOutcome(skipped=("s2",), issues={"i2": ("price is not readable",)}),
        }
    )
    use_case = LoadRecordsIntoCatalog(gateway, batch_size=2)

    report = await use_case.run(ListSource(["a", "b", "c"]))

    assert report.skipped == 2
    assert report.rejected == (("r1", "not a valid ATC code"),)
    assert report.records_with_issues == 2


async def test_a_limit_stops_early() -> None:
    gateway = RecordingGateway()
    use_case = LoadRecordsIntoCatalog(gateway, batch_size=2)

    report = await use_case.run(ListSource(["a", "b", "c", "d", "e"]), limit=3)

    assert gateway.batches == [["a", "b"], ["c"]]
    assert report.records == 3


async def test_an_empty_source_sends_nothing() -> None:
    gateway = RecordingGateway()

    report = await LoadRecordsIntoCatalog(gateway).run(ListSource([]))

    assert gateway.batches == []
    assert (report.batches, report.records) == (0, 0)


def test_the_batch_size_must_be_at_least_one() -> None:
    with pytest.raises(ValueError, match="batch_size"):
        LoadRecordsIntoCatalog(RecordingGateway(), batch_size=0)
