"""Outbound adapter: hands batches of source records to the catalog through its contracts.

This module is one of the allow-listed edges between contexts (see `pyproject.toml`, contract
`context-independence`). It speaks only the catalog's published language.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from pharmavique.catalog.contracts.commands import ApplyCatalogChanges, CatalogCommands
from pharmavique.ingestion.application.ports import BatchOutcome
from pharmavique.ingestion.infrastructure.connectors.sfda_web.mapping import map_records
from pharmavique.shared_kernel.currency import Currency
from pharmavique.shared_kernel.provenance import Provenance, TrustLevel

SOURCE = "sfda-drugs-list-web"


class CatalogWriter:
    """Implements the `CatalogGateway` port."""

    def __init__(
        self,
        commands: CatalogCommands,
        *,
        price_currency: Currency,
        snapshot_id: str,
        source_ref: str,
        fallback_time: datetime,
    ) -> None:
        self._commands = commands
        self._price_currency = price_currency
        self._snapshot_id = snapshot_id
        self._source_ref = source_ref
        self._fallback_time = fallback_time

    async def apply(self, records: Sequence[Mapping[str, Any]]) -> BatchOutcome:
        batch = map_records(records, self._price_currency)
        if not batch.snapshots:
            return BatchOutcome(skipped=batch.skipped, issues=batch.issues)

        provenance = Provenance(
            source=SOURCE,
            source_ref=self._source_ref,
            fetched_at=self._latest_fetch(records),
            snapshot_id=self._snapshot_id,
            trust=TrustLevel.OFFICIAL,
        )
        result = await self._commands.apply_changes(
            ApplyCatalogChanges(batch.snapshots, provenance)
        )
        return BatchOutcome(
            added=result.added,
            relisted=result.relisted,
            details_changed=result.details_changed,
            price_changed=result.price_changed,
            unchanged=result.unchanged,
            skipped=batch.skipped,
            rejected=tuple((r.register_number, r.reason) for r in result.rejected),
            issues=batch.issues,
        )

    def _latest_fetch(self, records: Sequence[Mapping[str, Any]]) -> datetime:
        times = [
            datetime.fromisoformat(stamp)
            for record in records
            if (stamp := record.get("provenance", {}).get("en_fetched_at"))
        ]
        return max(times) if times else self._fallback_time
