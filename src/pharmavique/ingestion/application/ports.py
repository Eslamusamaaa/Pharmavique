"""Ports of the ingestion application layer."""

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class FetchedPage:
    url: str
    status: int
    html: str
    fetched_at: datetime


class PageFetcher(Protocol):
    """Fetches one web page politely (throttled). Adapters decide how, for example a browser."""

    async def fetch(self, url: str) -> FetchedPage: ...


@dataclass(frozen=True, slots=True)
class BatchOutcome:
    """What the catalog did with one batch of source records."""

    added: int = 0
    relisted: int = 0
    details_changed: int = 0
    price_changed: int = 0
    unchanged: int = 0
    skipped: tuple[str, ...] = ()  # records with no usable details, by key
    rejected: tuple[tuple[str, str], ...] = ()  # (key, reason) the catalog refused
    issues: Mapping[str, tuple[str, ...]] = field(default_factory=dict)  # odd values kept as-is


class RecordSource(Protocol):
    """Where stored source records come from (for example a crawl snapshot on disk)."""

    def records(self) -> Iterator[Mapping[str, Any]]: ...


class CatalogGateway(Protocol):
    """Hands a batch of source records to the catalog, in the catalog's own terms."""

    async def apply(self, records: Sequence[Mapping[str, Any]]) -> BatchOutcome: ...
