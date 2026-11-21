"""A pharmacist's shelf list: the medicines they confirmed after scanning a shelf.

Revision ID: watchlist_0003
Revises: watchlist_0002
Create Date: 2026-11-21

One row per pharmacist and medicine (`user_id` has no foreign key: the account lives in the identity
schema). Row-level security is on and forced with the same rule as the other tables: a transaction
sees only its own rows, or every row when it sets `app.system` (the alert handler). The list says
which medicines a pharmacist told us they shelve; it holds no counts and says nothing about stock.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "watchlist_0003"
down_revision: str | None = "watchlist_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "watchlist"
VISIBLE = (
    "user_id::text = current_setting('app.user_id', true) "
    "OR current_setting('app.system', true) = 'on'"
)


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.shelf_items (
            user_id uuid NOT NULL,
            register_number text NOT NULL,
            added_at timestamptz NOT NULL,
            PRIMARY KEY (user_id, register_number)
        )
        """
    )
    op.execute(f"CREATE INDEX ix_shelf_items_register ON {SCHEMA}.shelf_items (register_number)")
    op.execute(f"ALTER TABLE {SCHEMA}.shelf_items ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {SCHEMA}.shelf_items FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY own_rows ON {SCHEMA}.shelf_items USING ({VISIBLE}) WITH CHECK ({VISIBLE})"
    )


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.shelf_items")
