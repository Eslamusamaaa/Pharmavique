"""PostgreSQL store over the `offers` schema (one retailer per store).

A price that looks wrong is held back (`price_anomaly`), the old price stays. The current price
and availability live on `listing`; `price_point` and `availability_change` get a row only when
the value changes. Descriptions are stored once per distinct text.
"""

import hashlib
import json
from datetime import datetime
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pharmavique.offers.application.ports import SaveResult
from pharmavique.offers.domain.anomaly import check_price
from pharmavique.offers.domain.lifecycle import status_after_seen
from pharmavique.offers.domain.model import (
    Availability,
    JobType,
    ListingCategory,
    ListingStatus,
    RunStatus,
)
from pharmavique.offers.domain.page import ParsedProduct
from pharmavique.offers.infrastructure.config import RetailerConfig

__all__ = ["PostgresListingStore"]

_EXISTING = text(
    """
    SELECT id, price_amount, price_currency, availability, content_hash
    FROM offers.listing WHERE retailer_id = :r AND source_id = :s
    """
)
_INSERT = text(
    """
    INSERT INTO offers.listing (retailer_id, source_id, url, name_en, name_ar, brand, category,
        category_path, ingredients_text, dosage_form_text, pack_text, barcode, image_urls, status,
        status_changed_at, first_seen_at, last_seen_at, content_hash, price_amount, price_currency,
        price_observed_at, availability, availability_observed_at)
    VALUES (:r, :s, :url, :name_en, :name_ar, :brand, :category, :path, :ingredients, :form, :pack,
        :barcode, CAST(:images AS text[]), :status, :now, :now, :now, :hash, :price, :currency,
        CASE WHEN CAST(:price AS numeric) IS NULL THEN NULL ELSE CAST(:now AS timestamptz) END,
        :availability, :now)
    RETURNING id
    """
)
_UPDATE_DETAILS = text(
    """
    UPDATE offers.listing SET url = :url,
        name_en = COALESCE(:name_en, name_en), name_ar = COALESCE(:name_ar, name_ar),
        brand = :brand, category = :category, category_path = :path,
        ingredients_text = :ingredients, dosage_form_text = :form, pack_text = :pack,
        barcode = :barcode, image_urls = CAST(:images AS text[]), content_hash = :hash
    WHERE id = :id
    """
)
_TOUCH = text(
    """
    UPDATE offers.listing SET last_seen_at = :now, missed_runs = 0, gone_runs = 0,
        status = :status,
        status_changed_at = CASE WHEN status <> :status THEN :now ELSE status_changed_at END
    WHERE id = :id
    """
)
_SET_PRICE = text(
    """
    UPDATE offers.listing SET price_amount = :price, price_currency = :currency,
        price_observed_at = :now WHERE id = :id
    """
)
_SET_AVAILABILITY = text(
    "UPDATE offers.listing SET availability = :a, availability_observed_at = :now WHERE id = :id"
)
_PRICE_POINT = text(
    """
    INSERT INTO offers.price_point (listing_id, observed_at, amount, currency)
    VALUES (:id, :now, :price, :currency) ON CONFLICT DO NOTHING
    """
)
_AVAILABILITY_POINT = text(
    """
    INSERT INTO offers.availability_change (listing_id, observed_at, availability)
    VALUES (:id, :now, :a) ON CONFLICT DO NOTHING
    """
)
_ANOMALY = text(
    """
    INSERT INTO offers.price_anomaly (listing_id, observed_at, old_amount, new_amount, rule)
    VALUES (:id, :now, :old, :new, :rule)
    """
)
_DESCRIPTION = text(
    """
    INSERT INTO offers.description_text (hash, text, language) VALUES (:h, :t, :lang)
    ON CONFLICT (hash) DO NOTHING
    """
)
_LISTING_TEXT = text(
    """
    INSERT INTO offers.listing_text (listing_id, description_hash, observed_at)
    VALUES (:id, :h, :now)
    ON CONFLICT (listing_id) DO UPDATE SET description_hash = EXCLUDED.description_hash,
        observed_at = EXCLUDED.observed_at
    """
)


def _status(product: ParsedProduct) -> str:
    cannot_buy = product.availability is Availability.OUT_OF_STOCK
    return status_after_seen(ListingStatus.ACTIVE, False if cannot_buy else None).value


class PostgresListingStore:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], retailer: RetailerConfig
    ) -> None:
        self._session_factory = session_factory
        self._retailer = retailer

    async def ensure_retailer(self) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(
                text(
                    """
                    INSERT INTO offers.retailer (id, name, base_url, platform, market, currency,
                        status)
                    VALUES (:id, :name, :url, :platform, :market, :currency, 'active')
                    ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name,
                        base_url = EXCLUDED.base_url, platform = EXCLUDED.platform,
                        market = EXCLUDED.market
                    """
                ),
                {
                    "id": self._retailer.id,
                    "name": self._retailer.name,
                    "url": self._retailer.base_url,
                    "platform": self._retailer.platform,
                    "market": self._retailer.market,
                    "currency": self._retailer.currency,
                },
            )

    async def known_urls(self) -> set[str]:
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    """
                    SELECT url FROM offers.listing WHERE retailer_id = :r
                    UNION SELECT url FROM offers.skipped_url WHERE retailer_id = :r
                    """
                ),
                {"r": self._retailer.id},
            )
            return {row[0] for row in result}

    async def skip(self, url: str, reason: str, now: datetime) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(
                text(
                    """
                    INSERT INTO offers.skipped_url (retailer_id, url, reason, seen_at)
                    VALUES (:r, :url, :reason, :now)
                    ON CONFLICT (retailer_id, url) DO UPDATE SET reason = EXCLUDED.reason,
                        seen_at = EXCLUDED.seen_at
                    """
                ),
                {"r": self._retailer.id, "url": url, "reason": reason, "now": now},
            )

    def _fields(self, product: ParsedProduct, category: ListingCategory) -> dict[str, object]:
        english = product.language == "en"
        return {
            "r": self._retailer.id,
            "s": product.source_id,
            "url": product.url,
            "name_en": product.name if english else None,
            "name_ar": None if english else product.name,
            "brand": product.brand,
            "category": category.value,
            "path": " > ".join(product.category_path) or None,
            "ingredients": product.ingredients_text,
            "form": product.dosage_form_text,
            "pack": product.pack_text,
            "barcode": product.barcode,
            "images": list(product.image_urls),
            "status": _status(product),
            "hash": product.details_hash,
            "price": product.price_amount,
            "currency": product.currency,
            "availability": product.availability.value,
        }

    async def save(
        self, product: ParsedProduct, category: ListingCategory, now: datetime
    ) -> SaveResult:
        try:
            async with self._session_factory() as session, session.begin():
                return await self._save(session, product, category, now)
        except IntegrityError:
            await self.skip(product.url, "duplicate_url", now)
            return SaveResult(False, False, False, False)

    async def _save(
        self,
        session: AsyncSession,
        product: ParsedProduct,
        category: ListingCategory,
        now: datetime,
    ) -> SaveResult:
        fields = self._fields(product, category)
        existing = (
            await session.execute(_EXISTING, {"r": self._retailer.id, "s": product.source_id})
        ).first()
        if existing is None:
            listing_id = (await session.execute(_INSERT, {**fields, "now": now})).scalar_one()
            if product.price_amount is not None:
                await session.execute(
                    _PRICE_POINT,
                    {
                        "id": listing_id,
                        "now": now,
                        "price": product.price_amount,
                        "currency": product.currency,
                    },
                )
            await session.execute(
                _AVAILABILITY_POINT, {"id": listing_id, "now": now, "a": product.availability.value}
            )
            await self._description(session, listing_id, product, now)
            return SaveResult(
                new=True, price_changed=False, details_changed=False, quarantined=False
            )

        listing_id = existing.id
        details_changed = bytes(existing.content_hash or b"") != product.details_hash
        if details_changed:
            await session.execute(_UPDATE_DETAILS, {**fields, "id": listing_id})
            await self._description(session, listing_id, product, now)
        await session.execute(_TOUCH, {"id": listing_id, "now": now, "status": fields["status"]})
        price_changed = quarantined = False
        new_price = product.price_amount
        if new_price is not None:
            old: Decimal | None = existing.price_amount
            verdict = check_price(old, new_price, existing.price_currency, product.currency)
            if verdict.action == "accept" and old != new_price:
                await session.execute(
                    _SET_PRICE,
                    {
                        "id": listing_id,
                        "now": now,
                        "price": new_price,
                        "currency": product.currency,
                    },
                )
                await session.execute(
                    _PRICE_POINT,
                    {
                        "id": listing_id,
                        "now": now,
                        "price": new_price,
                        "currency": product.currency,
                    },
                )
                price_changed = True
            elif verdict.action in ("quarantine", "hold_currency"):
                await session.execute(
                    _ANOMALY,
                    {
                        "id": listing_id,
                        "now": now,
                        "old": old,
                        "new": new_price,
                        "rule": verdict.rule,
                    },
                )
                quarantined = True
        if existing.availability != product.availability.value:
            await session.execute(
                _SET_AVAILABILITY, {"id": listing_id, "now": now, "a": product.availability.value}
            )
            await session.execute(
                _AVAILABILITY_POINT, {"id": listing_id, "now": now, "a": product.availability.value}
            )
        return SaveResult(False, price_changed, details_changed, quarantined)

    @staticmethod
    async def _description(
        session: AsyncSession, listing_id: int, product: ParsedProduct, now: datetime
    ) -> None:
        if not product.description:
            return
        digest = hashlib.sha256(product.description.encode("utf-8")).digest()[:16]
        await session.execute(
            _DESCRIPTION, {"h": digest, "t": product.description, "lang": product.language}
        )
        await session.execute(_LISTING_TEXT, {"id": listing_id, "h": digest, "now": now})

    async def start_run(self, job: JobType, now: datetime) -> int:
        async with self._session_factory() as session, session.begin():
            result = await session.execute(
                text(
                    """
                    INSERT INTO offers.scrape_run (retailer_id, job_type, started_at, status)
                    VALUES (:r, :job, :now, 'partial') RETURNING id
                    """
                ),
                {"r": self._retailer.id, "job": job.value, "now": now},
            )
            return int(result.scalar_one())

    async def finish_run(
        self, run_id: int, status: RunStatus, counters: dict[str, int], now: datetime
    ) -> None:
        discovered = counters.get("discovered", 0)
        completeness = (
            Decimal(discovered - counters.get("remaining", 0)) / Decimal(discovered)
            if discovered
            else None
        )
        async with self._session_factory() as session, session.begin():
            await session.execute(
                text(
                    """
                    UPDATE offers.scrape_run SET finished_at = :now, status = :status,
                        requests = :requests, discovered = :discovered, new = :new,
                        changed = :changed, unchanged = :unchanged, failed = :failed,
                        missing_price = :missing_price, completeness = :completeness,
                        counters = CAST(:counters AS jsonb)
                    WHERE id = :id
                    """
                ),
                {
                    "id": run_id,
                    "now": now,
                    "status": status.value,
                    "requests": counters.get("requests", 0),
                    "discovered": discovered,
                    "new": counters.get("new", 0),
                    "changed": counters.get("changed", 0),
                    "unchanged": counters.get("unchanged", 0),
                    "failed": counters.get("failed", 0),
                    "missing_price": counters.get("missing_price", 0),
                    "completeness": None if completeness is None else round(completeness, 3),
                    "counters": json.dumps(counters),
                },
            )
