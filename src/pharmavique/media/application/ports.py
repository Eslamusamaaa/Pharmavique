"""Ports of the media application layer. Adapters live in `infrastructure`."""

from dataclasses import dataclass
from typing import Protocol

from pharmavique.media.domain.images import ProductImage
from pharmavique.media.domain.matching import ImageCandidate
from pharmavique.shared_kernel.market import Market


@dataclass(frozen=True, slots=True)
class DownloadedImage:
    data: bytes
    content_type: str


class ImageSearch(Protocol):
    """Web image search. The real adapter uses an image-search API under its terms of use."""

    async def search(self, query: str, limit: int) -> list[ImageCandidate]: ...


class ImageDownloader(Protocol):
    """Fetches one image politely (throttled, robots.txt respected). `None` when it cannot."""

    async def download(self, url: str) -> DownloadedImage | None: ...


class ImageStore(Protocol):
    """Object storage for the picture bytes."""

    async def save(self, key: str, data: bytes, content_type: str) -> None: ...


class ImageRepository(Protocol):
    async def for_product(self, market: Market, register_number: str) -> list[ProductImage]: ...

    async def products_with_hash(self, content_hash: str) -> int:
        """How many different products already carry exactly this picture."""
        ...

    async def add(self, image: ProductImage) -> None: ...
