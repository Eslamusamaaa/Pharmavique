"""Create the analytics schema: the market read model and the registry change events.

Revision ID: analytics_0001
Revises:
Create Date: 2026-11-21

`market_products` is rebuilt from the catalog's published export (swapped in one transaction), so it
can be thrown away and rebuilt at any time. `market_events` keeps one row per integration event
(the event id is the key, so a re-delivered event adds nothing). Both hold public registry facts
only, never anything about a person, so there is no row-level security here.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "analytics_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = ("analytics",)
depends_on: str | Sequence[str] | None = None

SCHEMA = "analytics"


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.market_products (
            market text NOT NULL,
            register_number text NOT NULL,
            trade_name_en text,
            trade_name_ar text,
            ingredients jsonb NOT NULL,
            ingredient_names text[] NOT NULL,
            dosage_form text,
            marketing_company text,
            listing_status text NOT NULL,
            price_amount numeric(20, 6),
            price_currency_code text,
            price_currency_basis text,
            PRIMARY KEY (market, register_number),
            CONSTRAINT ck_market_products_status CHECK (listing_status IN ('listed', 'withdrawn'))
        )
        """
    )
    op.execute(
        f"CREATE INDEX ix_market_products_ingredients ON {SCHEMA}.market_products "
        "USING gin (ingredient_names)"
    )
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.market_events (
            event_id uuid PRIMARY KEY,
            market text NOT NULL,
            kind text NOT NULL,
            register_number text NOT NULL,
            occurred_at timestamptz NOT NULL,
            old_price numeric(20, 6),
            new_price numeric(20, 6),
            currency_code text,
            currency_basis text,
            CONSTRAINT ck_market_events_kind
                CHECK (kind IN ('added', 'relisted', 'withdrawn', 'price_changed'))
        )
        """
    )
    op.execute(
        f"CREATE INDEX ix_market_events_time ON {SCHEMA}.market_events (market, occurred_at DESC)"
    )
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.projection_meta (
            market text PRIMARY KEY,
            built_at timestamptz NOT NULL,
            first_built_at timestamptz NOT NULL,
            products integer NOT NULL
        )
        """
    )


def downgrade() -> None:
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
