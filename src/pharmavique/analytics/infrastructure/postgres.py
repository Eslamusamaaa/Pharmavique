"""PostgreSQL store over the `analytics` schema."""

import json
from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Row, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pharmavique.analytics.domain.market import IngredientLine, MarketProduct
from pharmavique.analytics.domain.radar import (
    ChangeKind,
    MarketEvent,
    ProjectionStatus,
    RadarItem,
)

_CHUNK = 1000
_WEEK = timedelta(days=7)


def _plain(value: Decimal | None) -> str | None:
    return None if value is None else format(value.normalize(), "f")


def _product(row: Row[Any]) -> MarketProduct:
    return MarketProduct(
        market=row.market,
        register_number=row.register_number,
        trade_name_en=row.trade_name_en,
        trade_name_ar=row.trade_name_ar,
        ingredients=tuple(
            IngredientLine(i["name"], i.get("strength"), i.get("unit")) for i in row.ingredients
        ),
        dosage_form=row.dosage_form,
        marketing_company=row.marketing_company,
        listing_status=row.listing_status,
        price_amount=row.price_amount,
        price_currency_code=row.price_currency_code,
        price_currency_basis=row.price_currency_basis,
    )


def _event(row: Row[Any]) -> MarketEvent:
    return MarketEvent(
        event_id=row.event_id,
        market=row.market,
        kind=ChangeKind(row.kind),
        register_number=row.register_number,
        occurred_at=row.occurred_at,
        old_price=_plain(row.old_price),
        new_price=_plain(row.new_price),
        currency_code=row.currency_code,
        currency_basis=row.currency_basis,
    )


class PostgresAnalyticsStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def replace_products(
        self, market: str, products: Sequence[MarketProduct], built_at: datetime
    ) -> None:
        insert = text(
            """
            INSERT INTO analytics.market_products (
              market, register_number, trade_name_en, trade_name_ar, ingredients,
              ingredient_names, dosage_form, marketing_company, listing_status,
              price_amount, price_currency_code, price_currency_basis
            ) VALUES (
              :market, :register_number, :trade_name_en, :trade_name_ar,
              CAST(:ingredients AS jsonb), CAST(:ingredient_names AS text[]), :dosage_form,
              :marketing_company, :listing_status, :price_amount, :price_currency_code,
              :price_currency_basis
            )
            """
        )
        async with self._session_factory() as session, session.begin():
            await session.execute(
                text("DELETE FROM analytics.market_products WHERE market = :market"),
                {"market": market},
            )
            for start in range(0, len(products), _CHUNK):
                await session.execute(
                    insert,
                    [
                        {
                            "market": p.market,
                            "register_number": p.register_number,
                            "trade_name_en": p.trade_name_en,
                            "trade_name_ar": p.trade_name_ar,
                            "ingredients": json.dumps(
                                [
                                    {"name": i.name, "strength": i.strength, "unit": i.unit}
                                    for i in p.ingredients
                                ]
                            ),
                            "ingredient_names": list(p.combination),
                            "dosage_form": p.dosage_form,
                            "marketing_company": p.marketing_company,
                            "listing_status": p.listing_status,
                            "price_amount": p.price_amount,
                            "price_currency_code": p.price_currency_code,
                            "price_currency_basis": p.price_currency_basis,
                        }
                        for p in products[start : start + _CHUNK]
                    ],
                )
            await session.execute(
                text(
                    """
                    INSERT INTO analytics.projection_meta
                      (market, built_at, first_built_at, products)
                    VALUES (:market, :built_at, :built_at, :products)
                    ON CONFLICT (market) DO UPDATE
                      SET built_at = EXCLUDED.built_at, products = EXCLUDED.products
                    """
                ),
                {"market": market, "built_at": built_at, "products": len(products)},
            )

    async def products_with_ingredient(
        self, market: str, ingredient: str, limit: int
    ) -> list[MarketProduct]:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT * FROM analytics.market_products
                        WHERE market = :market AND ingredient_names @> CAST(:names AS text[])
                        ORDER BY register_number
                        LIMIT :limit
                        """
                    ),
                    {"market": market, "names": [ingredient], "limit": limit},
                )
            ).all()
        return [_product(row) for row in rows]

    async def add_event(self, event: MarketEvent) -> bool:
        async with self._session_factory() as session, session.begin():
            result = await session.execute(
                text(
                    """
                    INSERT INTO analytics.market_events (
                      event_id, market, kind, register_number, occurred_at,
                      old_price, new_price, currency_code, currency_basis
                    ) VALUES (
                      :event_id, :market, :kind, :register_number, :occurred_at,
                      :old_price, :new_price, :currency_code, :currency_basis
                    ) ON CONFLICT (event_id) DO NOTHING RETURNING event_id
                    """
                ),
                {
                    "event_id": event.event_id,
                    "market": event.market,
                    "kind": event.kind.value,
                    "register_number": event.register_number,
                    "occurred_at": event.occurred_at,
                    "old_price": Decimal(event.old_price) if event.old_price else None,
                    "new_price": Decimal(event.new_price) if event.new_price else None,
                    "currency_code": event.currency_code,
                    "currency_basis": event.currency_basis,
                },
            )
            return result.first() is not None

    async def radar(
        self, market: str, ingredient: str | None, since: datetime, limit: int
    ) -> list[RadarItem]:
        names = None if ingredient is None else [ingredient]
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT e.*, p.trade_name_en, p.trade_name_ar, p.marketing_company,
                               p.ingredient_names
                        FROM analytics.market_events e
                        LEFT JOIN analytics.market_products p
                          ON p.market = e.market AND p.register_number = e.register_number
                        WHERE e.market = :market AND e.occurred_at >= :since
                          AND (CAST(:names AS text[]) IS NULL
                               OR p.ingredient_names @> CAST(:names AS text[]))
                        ORDER BY e.occurred_at DESC, e.event_id
                        LIMIT :limit
                        """
                    ),
                    {"market": market, "since": since, "names": names, "limit": limit},
                )
            ).all()
        return [
            RadarItem(
                event=_event(row),
                trade_name_en=row.trade_name_en,
                trade_name_ar=row.trade_name_ar,
                marketing_company=row.marketing_company,
                ingredients=tuple(row.ingredient_names or ()),
            )
            for row in rows
        ]

    async def first_built_at(self, market: str) -> datetime | None:
        async with self._session_factory() as session:
            value = await session.scalar(
                text("SELECT first_built_at FROM analytics.projection_meta WHERE market = :m"),
                {"m": market},
            )
        return value if isinstance(value, datetime) else None

    async def status(self, market: str, now: datetime) -> ProjectionStatus:
        async with self._session_factory() as session:
            meta = (
                await session.execute(
                    text(
                        "SELECT products, built_at, first_built_at "
                        "FROM analytics.projection_meta WHERE market = :m"
                    ),
                    {"m": market},
                )
            ).first()
            events = await session.scalar(
                text(
                    "SELECT count(*) FROM analytics.market_events "
                    "WHERE market = :m AND occurred_at >= :since"
                ),
                {"m": market, "since": now - _WEEK},
            )
        count = int(events or 0)
        if meta is None:
            return ProjectionStatus(0, None, None, count)
        return ProjectionStatus(meta.products, meta.built_at, meta.first_built_at, count)
