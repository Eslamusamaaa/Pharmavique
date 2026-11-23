"""Where pictures live: files named after their content, and the table that remembers each one."""

import hashlib
from datetime import datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pharmavique.offers.application.images import PendingImage

__all__ = ["DiskImageSink", "PostgresImageStore"]

_EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
    "image/avif": "avif",
    "image/svg+xml": "svg",
}


class DiskImageSink:
    def __init__(self, root: Path) -> None:
        self._root = root

    def save(self, retailer_id: str, content: bytes, content_type: str) -> tuple[str, str]:
        digest = hashlib.sha256(content).hexdigest()
        extension = _EXTENSIONS.get(content_type, "bin")
        relative = f"{retailer_id}/{digest[:2]}/{digest}.{extension}"
        target = self._root / relative
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        return relative, digest


class PostgresImageStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], retailer_id: str) -> None:
        self._session_factory = session_factory
        self._retailer_id = retailer_id

    async def pending_images(self, limit: int) -> list[PendingImage]:
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    """
                    SELECT l.id, l.image_urls[1] AS url
                    FROM offers.listing l
                    LEFT JOIN offers.listing_image i ON i.listing_id = l.id AND i.position = 0
                    WHERE l.retailer_id = :r AND cardinality(l.image_urls) > 0
                        AND i.listing_id IS NULL
                    ORDER BY l.id LIMIT :n
                    """
                ),
                {"r": self._retailer_id, "n": limit},
            )
            return [PendingImage(row.id, 0, self._retailer_id, row.url) for row in result]

    async def record(
        self,
        image: PendingImage,
        status: str,
        file_path: str | None,
        sha256: str | None,
        size: int | None,
        content_type: str | None,
        now: datetime,
    ) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(
                text(
                    """
                    INSERT INTO offers.listing_image (listing_id, position, url, status, file_path,
                        sha256, bytes, content_type, fetched_at)
                    VALUES (:id, :pos, :url, :status, :path, :sha, :size, :type, :now)
                    ON CONFLICT (listing_id, position) DO UPDATE SET url = EXCLUDED.url,
                        status = EXCLUDED.status, file_path = EXCLUDED.file_path,
                        sha256 = EXCLUDED.sha256, bytes = EXCLUDED.bytes,
                        content_type = EXCLUDED.content_type, fetched_at = EXCLUDED.fetched_at
                    """
                ),
                {
                    "id": image.listing_id,
                    "pos": image.position,
                    "url": image.url,
                    "status": status,
                    "path": file_path,
                    "sha": sha256,
                    "size": size,
                    "type": content_type,
                    "now": now,
                },
            )
