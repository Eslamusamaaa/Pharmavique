"""Plain-file adapters: picture bytes in a folder, picture records in a JSON-lines file.

Good enough to run the whole picture pipeline from the command line before any database or object
storage is chosen; both sit behind ports, so replacing them changes nothing else.
"""

import json
import os
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from pharmavique.media.domain.images import ImageStatus, ProductImage
from pharmavique.shared_kernel.market import Market
from pharmavique.shared_kernel.provenance import Provenance, TrustLevel


class FileImageStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    async def save(self, key: str, data: bytes, content_type: str) -> None:
        relative = PurePosixPath(key)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ValueError(f"image key must stay inside the store folder: {key!r}")
        target = self._root.joinpath(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".tmp")
        temporary.write_bytes(data)
        os.replace(temporary, target)


def _to_json(image: ProductImage) -> dict[str, Any]:
    return {
        "market": image.market.value,
        "register_number": image.register_number,
        "image_url": image.image_url,
        "page_url": image.page_url,
        "query": image.query,
        "status": image.status.value,
        "score": image.score,
        "signals": list(image.signals),
        "content_hash": image.content_hash,
        "content_type": image.content_type,
        "size_bytes": image.size_bytes,
        "storage_key": image.storage_key,
        "provenance": {
            "source": image.provenance.source,
            "source_ref": image.provenance.source_ref,
            "fetched_at": image.provenance.fetched_at.isoformat(),
            "snapshot_id": image.provenance.snapshot_id,
            "trust": image.provenance.trust.value,
        },
    }


def _from_json(raw: dict[str, Any]) -> ProductImage:
    provenance = raw["provenance"]
    return ProductImage(
        market=Market(raw["market"]),
        register_number=raw["register_number"],
        image_url=raw["image_url"],
        page_url=raw["page_url"],
        query=raw["query"],
        status=ImageStatus(raw["status"]),
        score=raw["score"],
        signals=tuple(raw["signals"]),
        content_hash=raw["content_hash"],
        content_type=raw["content_type"],
        size_bytes=raw["size_bytes"],
        storage_key=raw["storage_key"],
        provenance=Provenance(
            provenance["source"],
            provenance["source_ref"],
            datetime.fromisoformat(provenance["fetched_at"]),
            provenance["snapshot_id"],
            TrustLevel(provenance["trust"]),
        ),
    )


class JsonlImageRepository:
    """Records appended to one file; read back into memory when the repository is created."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._images: list[ProductImage] = []
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    self._images.append(_from_json(json.loads(line)))
                except (ValueError, KeyError):
                    continue  # a half-written last line must not stop the run

    async def for_product(self, market: Market, register_number: str) -> list[ProductImage]:
        return [
            image
            for image in self._images
            if image.market is market and image.register_number == register_number
        ]

    async def products_with_hash(self, content_hash: str) -> int:
        return len({i.register_number for i in self._images if i.content_hash == content_hash})

    async def add(self, image: ProductImage) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(_to_json(image), ensure_ascii=False) + "\n")
        self._images.append(image)


class JsonlAttemptLog:
    """Which products a run has already worked on, with or without a result.

    A product with no picture is not asked about again on every cycle; the report lists the ones
    still missing so they can be handled another way.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._tried: set[tuple[str, str]] = set()
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(line)
                    self._tried.add((row["market"], row["register_number"]))
                except (ValueError, KeyError):
                    continue

    @property
    def tried_count(self) -> int:
        return len(self._tried)

    def was_tried(self, market: Market, register_number: str) -> bool:
        return (market.value, register_number) in self._tried

    def record(self, market: Market, register_number: str, *, stored: int, at: datetime) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "market": market.value,
            "register_number": register_number,
            "stored": stored,
            "at": at.isoformat(),
        }
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")
        self._tried.add((market.value, register_number))
