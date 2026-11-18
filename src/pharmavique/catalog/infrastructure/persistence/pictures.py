"""Postgres store for the picture of each product (real shop picture or generated card)."""

from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import delete, insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pharmavique.catalog.infrastructure.persistence.models import ProductPictureRow

_CHUNK = 1000
_CONTENT_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                  ".webp": "image/webp", ".gif": "image/gif", ".svg": "image/svg+xml"}  # fmt: skip


def content_type_of(path: str) -> str:
    suffix = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return _CONTENT_TYPES.get(suffix, "application/octet-stream")


class SqlAlchemyPictureStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def replace_all(self, market: str, rows: Iterable[Mapping[str, Any]]) -> int:
        """Replace the pictures of a market with `rows` (mapping rows). Rows of drugs that are not
        in the catalog are skipped. Returns how many were stored."""
        from sqlalchemy import select

        from pharmavique.catalog.infrastructure.persistence.models import ProductRow

        async with self._session_factory() as session, session.begin():
            known = set(
                (
                    await session.execute(
                        select(ProductRow.register_number).where(ProductRow.market == market)
                    )
                )
                .scalars()
                .all()
            )
            values = [
                {
                    "market": market,
                    "register_number": row["register_number"],
                    "kind": row["picture_kind"],
                    "file_path": row["picture"],
                    "content_type": content_type_of(row["picture"]),
                    "status": row.get("picture_status"),
                    "verification": row["picture_check"],
                    "form_group": row.get("placeholder_form"),
                    "source_page": row.get("source_page"),
                    "source_image_url": row.get("source_image_url"),
                    "trust": row.get("trust"),
                }
                for row in rows
                if row["register_number"] in known
            ]
            await session.execute(
                delete(ProductPictureRow).where(ProductPictureRow.market == market)
            )
            for start in range(0, len(values), _CHUNK):
                await session.execute(insert(ProductPictureRow), values[start : start + _CHUNK])
            return len(values)
