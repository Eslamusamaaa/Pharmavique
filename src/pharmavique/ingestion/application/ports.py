"""Ports of the ingestion application layer."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class FetchedPage:
    url: str
    status: int
    html: str
    fetched_at: datetime


class PageFetcher(Protocol):
    """Fetches one web page politely (throttled). Adapters decide how, for example a browser."""

    async def fetch(self, url: str) -> FetchedPage: ...
