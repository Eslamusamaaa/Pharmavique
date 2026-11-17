"""Create the catalog schema: products, price history and outbox.

Revision ID: catalog_0001
Revises:
Create Date: 2026-11-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "catalog_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = ("catalog",)
depends_on: str | Sequence[str] | None = None

SCHEMA = "catalog"


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    op.create_table(
        "products",
        sa.Column("market", sa.String(2), primary_key=True),
        sa.Column("register_number", sa.Text(), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("listing_status", sa.String(16), nullable=False),
        sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provenance_source", sa.Text(), nullable=False),
        sa.Column("provenance_source_ref", sa.Text(), nullable=False),
        sa.Column("provenance_fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provenance_snapshot_id", sa.Text(), nullable=False),
        sa.Column("provenance_trust", sa.String(32), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column("price_amount", sa.Numeric(20, 6), nullable=True),
        sa.Column("price_currency_code", sa.String(3), nullable=True),
        sa.Column("price_currency_basis", sa.String(32), nullable=True),
        sa.CheckConstraint("listing_status in ('listed', 'withdrawn')", name="ck_products_status"),
        schema=SCHEMA,
    )

    op.create_table(
        "price_history",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("market", sa.String(2), nullable=False),
        sa.Column("register_number", sa.Text(), nullable=False),
        sa.Column("amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("currency_code", sa.String(3), nullable=True),
        sa.Column("currency_basis", sa.String(32), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provenance_source", sa.Text(), nullable=False),
        sa.Column("provenance_source_ref", sa.Text(), nullable=False),
        sa.Column("provenance_fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provenance_snapshot_id", sa.Text(), nullable=False),
        sa.Column("provenance_trust", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(
            ["market", "register_number"],
            [f"{SCHEMA}.products.market", f"{SCHEMA}.products.register_number"],
            ondelete="CASCADE",
            name="fk_price_history_product",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_price_history_product_time",
        "price_history",
        ["market", "register_number", "effective_from"],
        schema=SCHEMA,
    )

    op.create_table(
        "outbox",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_outbox_unpublished",
        "outbox",
        ["occurred_at"],
        schema=SCHEMA,
        postgresql_where=sa.text("published_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_outbox_unpublished", table_name="outbox", schema=SCHEMA)
    op.drop_table("outbox", schema=SCHEMA)
    op.drop_index("ix_price_history_product_time", table_name="price_history", schema=SCHEMA)
    op.drop_table("price_history", schema=SCHEMA)
    op.drop_table("products", schema=SCHEMA)
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA}")
