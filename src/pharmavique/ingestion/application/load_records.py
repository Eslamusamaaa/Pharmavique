"""Use case: move stored source records into the catalog in batches.

Safe to repeat: the catalog applies each batch idempotently, so loading the same records again
changes nothing. Problems are counted and reported (skipped, rejected, odd values), never hidden.
"""

from dataclasses import dataclass
from itertools import islice

from pharmavique.ingestion.application.ports import CatalogGateway, RecordSource


@dataclass(frozen=True, slots=True)
class LoadReport:
    batches: int
    records: int
    added: int
    relisted: int
    details_changed: int
    price_changed: int
    unchanged: int
    skipped: int
    rejected: tuple[tuple[str, str], ...]
    records_with_issues: int


class LoadRecordsIntoCatalog:
    def __init__(self, gateway: CatalogGateway, batch_size: int = 200) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        self._gateway = gateway
        self._batch_size = batch_size

    async def run(self, source: RecordSource, limit: int | None = None) -> LoadReport:
        records = iter(source.records())
        if limit is not None:
            records = islice(records, limit)

        batches = total = added = relisted = details = prices = unchanged = skipped = odd = 0
        rejected: list[tuple[str, str]] = []

        while batch := list(islice(records, self._batch_size)):
            outcome = await self._gateway.apply(batch)
            batches += 1
            total += len(batch)
            added += outcome.added
            relisted += outcome.relisted
            details += outcome.details_changed
            prices += outcome.price_changed
            unchanged += outcome.unchanged
            skipped += len(outcome.skipped)
            rejected.extend(outcome.rejected)
            odd += len(outcome.issues)

        return LoadReport(
            batches=batches,
            records=total,
            added=added,
            relisted=relisted,
            details_changed=details,
            price_changed=prices,
            unchanged=unchanged,
            skipped=skipped,
            rejected=tuple(rejected),
            records_with_issues=odd,
        )
