"""Tables of the catalog context. They live in their own Postgres schema, `catalog`.

Nothing outside this context reads or joins these tables; other contexts use the published
contracts and events (ADR-001, ARCHITECTURE.md section 4.6).
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA = "catalog"


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA)


class ProductRow(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("listing_status in ('listed', 'withdrawn')", name="ck_products_status"),
    )

    market: Mapped[str] = mapped_column(String(2), primary_key=True)
    register_number: Mapped[str] = mapped_column(Text, primary_key=True)
    version: Mapped[int] = mapped_column(Integer)
    listing_status: Mapped[str] = mapped_column(String(16))
    status_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    provenance_source: Mapped[str] = mapped_column(Text)
    provenance_source_ref: Mapped[str] = mapped_column(Text)
    provenance_fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    provenance_snapshot_id: Mapped[str] = mapped_column(Text)
    provenance_trust: Mapped[str] = mapped_column(String(32))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    price_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    price_currency_code: Mapped[str | None] = mapped_column(String(3), nullable=True)
    price_currency_basis: Mapped[str | None] = mapped_column(String(32), nullable=True)


class PricePointRow(Base):
    """Append-only price history. Rows are only ever inserted."""

    __tablename__ = "price_history"
    __table_args__ = (
        ForeignKeyConstraint(
            ["market", "register_number"],
            [f"{SCHEMA}.products.market", f"{SCHEMA}.products.register_number"],
            ondelete="CASCADE",
            name="fk_price_history_product",
        ),
        Index("ix_price_history_product_time", "market", "register_number", "effective_from"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    market: Mapped[str] = mapped_column(String(2))
    register_number: Mapped[str] = mapped_column(Text)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    currency_code: Mapped[str | None] = mapped_column(String(3), nullable=True)
    currency_basis: Mapped[str] = mapped_column(String(32))
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    provenance_source: Mapped[str] = mapped_column(Text)
    provenance_source_ref: Mapped[str] = mapped_column(Text)
    provenance_fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    provenance_snapshot_id: Mapped[str] = mapped_column(Text)
    provenance_trust: Mapped[str] = mapped_column(String(32))


class SourceListRowRow(Base):
    """One row of an official SFDA list, as the site showed it, with its provenance."""

    __tablename__ = "source_list_rows"

    list_name: Mapped[str] = mapped_column(Text, primary_key=True)
    row_key: Mapped[str] = mapped_column(Text, primary_key=True)
    entity_key: Mapped[str] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(Text, nullable=True)
    cells: Mapped[list[Any]] = mapped_column(JSONB)
    list_page: Mapped[int] = mapped_column(Integer)
    provenance_source: Mapped[str] = mapped_column(Text)
    provenance_source_ref: Mapped[str] = mapped_column(Text)
    provenance_fetched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    provenance_snapshot_id: Mapped[str] = mapped_column(Text)
    provenance_trust: Mapped[str] = mapped_column(String(32))


class SourceListLinkRow(Base):
    """A list row linked to a product, with how sure the link is (`matched` or `possible`)."""

    __tablename__ = "source_list_links"
    __table_args__ = (
        ForeignKeyConstraint(
            ["list_name", "row_key"],
            [f"{SCHEMA}.source_list_rows.list_name", f"{SCHEMA}.source_list_rows.row_key"],
            ondelete="CASCADE",
            name="fk_source_list_links_row",
        ),
        ForeignKeyConstraint(
            ["market", "register_number"],
            [f"{SCHEMA}.products.market", f"{SCHEMA}.products.register_number"],
            ondelete="CASCADE",
            name="fk_source_list_links_product",
        ),
        CheckConstraint("confidence in ('matched', 'possible')", name="ck_source_list_links"),
        Index("ix_source_list_links_product", "market", "register_number"),
    )

    list_name: Mapped[str] = mapped_column(Text, primary_key=True)
    row_key: Mapped[str] = mapped_column(Text, primary_key=True)
    market: Mapped[str] = mapped_column(String(2), primary_key=True)
    register_number: Mapped[str] = mapped_column(Text, primary_key=True)
    confidence: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(Text)


class OutboxRow(Base):
    """Integration events waiting to be delivered, written in the same transaction as the change."""

    __tablename__ = "outbox"
    __table_args__ = (
        Index(
            "ix_outbox_unpublished",
            "occurred_at",
            postgresql_where=text("published_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    event_type: Mapped[str] = mapped_column(Text)
    schema_version: Mapped[int] = mapped_column(Integer)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
