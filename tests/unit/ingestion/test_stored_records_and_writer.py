"""Reading stored SFDA pages as records, and handing batches to the catalog (fake commands)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from pharmavique.catalog.contracts.commands import (
    ApplyCatalogChanges,
    ApplyCatalogChangesResult,
    RejectedSnapshot,
)
from pharmavique.ingestion.application.ports import FetchedPage
from pharmavique.ingestion.infrastructure.adapters.catalog_writer import CatalogWriter
from pharmavique.ingestion.infrastructure.connectors.sfda_web.store import SnapshotStore
from pharmavique.ingestion.infrastructure.connectors.sfda_web.stored_records import StoredRecords
from pharmavique.shared_kernel.currency import Currency
from pharmavique.shared_kernel.provenance import TrustLevel

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
SAR = Currency.owner_assumed("SAR")


def details_html(key: str, **extra: str) -> str:
    fields = {
        "Register Number": key,
        "Trade Name": f"TRADE-{key}",
        "Scientific Name": "ACMEDRONE",
        "Strength": "5",
        "Strength Unit": "mg",
        "Dosage Form": "Tablet",
        "Price": "9.5",
        **extra,
    }
    rows = "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in fields.items())
    return f"<table>{rows}</table>"


def arabic_html(key: str) -> str:
    return (
        f"<table><tr><th>رقم التسجيل</th><td>{key}</td></tr>"
        f"<tr><th>الاسم التجاري</th><td>اسم {key}</td></tr></table>"
    )


def save(store: SnapshotStore, language: str, key: str, html: str, at: datetime = NOW) -> None:
    url = f"https://example.test/{language}/details_data?id={key}"
    store.save_page(store.details_path(language, key), FetchedPage(url, 200, html, at))


def stored(tmp_path: Path) -> SnapshotStore:
    store = SnapshotStore(tmp_path, "run-1")
    save(store, "en", "k1", details_html("k1"))
    save(store, "ar", "k1", arabic_html("k1"))
    save(store, "en", "k2", details_html("k2"), NOW + timedelta(hours=1))
    return store


def test_stored_pages_become_records_with_both_languages(tmp_path: Path) -> None:
    records = list(StoredRecords(stored(tmp_path)).records())

    assert [r["key"] for r in records] == ["k1", "k2"]
    first = records[0]
    assert {f["label"]: f["value"] for f in first["en"]}["Trade Name"] == "TRADE-k1"
    assert {f["label"]: f["value"] for f in first["ar"]}["الاسم التجاري"] == "اسم k1"
    assert first["provenance"]["en_fetched_at"] == NOW.isoformat()


def test_a_drug_without_an_arabic_page_has_no_arabic_section(tmp_path: Path) -> None:
    second = list(StoredRecords(stored(tmp_path)).records())[1]

    assert second["ar"] is None


def test_unreadable_stored_pages_are_skipped(tmp_path: Path) -> None:
    store = stored(tmp_path)
    save(store, "en", "broken", "<html><body>Please verify you are human</body></html>")

    keys = [r["key"] for r in StoredRecords(store).records()]

    assert keys == ["k1", "k2"]


def test_keys_with_special_characters_survive_the_file_name_round_trip(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path, "run-1")
    save(store, "en", "1-585-09", details_html("1-585-09"))
    save(store, "en", "a/b c", details_html("a/b c"))

    keys = sorted(r["key"] for r in StoredRecords(store).records())

    assert keys == ["1-585-09", "a/b c"]


class FakeCommands:
    def __init__(self, result: ApplyCatalogChangesResult | None = None) -> None:
        self.commands: list[ApplyCatalogChanges] = []
        self._result = result

    async def apply_changes(self, command: ApplyCatalogChanges) -> ApplyCatalogChangesResult:
        self.commands.append(command)
        if self._result is not None:
            return self._result
        return ApplyCatalogChangesResult(
            added=len(command.snapshots),
            relisted=0,
            details_changed=0,
            price_changed=0,
            unchanged=0,
            rejected=(),
        )

    async def withdraw(self, command: Any) -> Any:  # pragma: no cover - not used here
        raise NotImplementedError


def writer(commands: FakeCommands) -> CatalogWriter:
    return CatalogWriter(
        commands,
        price_currency=SAR,
        snapshot_id="run-1",
        source_ref="https://example.test/en/drugs-list",
        fallback_time=NOW - timedelta(days=1),
    )


async def test_the_writer_maps_records_and_sends_one_command_per_batch(tmp_path: Path) -> None:
    commands = FakeCommands()
    records = list(StoredRecords(stored(tmp_path)).records())

    outcome = await writer(commands).apply(records)

    (command,) = commands.commands
    assert [s.register_number for s in command.snapshots] == ["k1", "k2"]
    assert command.snapshots[0].price is not None
    assert command.snapshots[0].price.amount == Decimal("9.5")
    assert outcome.added == 2


async def test_the_batch_provenance_names_the_source_the_run_and_the_latest_fetch(
    tmp_path: Path,
) -> None:
    commands = FakeCommands()
    records = list(StoredRecords(stored(tmp_path)).records())

    await writer(commands).apply(records)

    provenance = commands.commands[0].provenance
    assert provenance.source == "sfda-drugs-list-web"
    assert provenance.snapshot_id == "run-1"
    assert provenance.trust is TrustLevel.OFFICIAL
    assert provenance.source_ref == "https://example.test/en/drugs-list"
    assert provenance.fetched_at == NOW + timedelta(hours=1)


async def test_records_without_english_details_are_skipped_and_never_sent() -> None:
    commands = FakeCommands()
    empty: dict[str, Any] = {"key": "x", "list": {}, "en": None, "ar": None, "provenance": {}}

    outcome = await writer(commands).apply([empty])

    assert commands.commands == []
    assert outcome.skipped == ("x",)


async def test_rejections_and_odd_values_are_passed_back_not_hidden(tmp_path: Path) -> None:
    commands = FakeCommands(
        ApplyCatalogChangesResult(
            added=1,
            relisted=0,
            details_changed=0,
            price_changed=0,
            unchanged=0,
            rejected=(RejectedSnapshot("k2", "not a valid ATC code"),),
        )
    )
    store = stored(tmp_path)
    save(store, "en", "k3", details_html("k3", Price="free"))
    records = list(StoredRecords(store).records())

    outcome = await writer(commands).apply(records)

    assert outcome.rejected == (("k2", "not a valid ATC code"),)
    assert list(outcome.issues) == ["k3"]
