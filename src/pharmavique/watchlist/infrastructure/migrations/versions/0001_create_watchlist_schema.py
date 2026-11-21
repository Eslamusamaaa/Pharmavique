"""Create the watchlist schema: saved medicines, allergies and alerts, one person each.

Revision ID: watchlist_0001
Revises:
Create Date: 2026-11-21

Every row belongs to one person (`user_id`; there is no foreign key because the person lives in the
identity context's schema). Row-level security is on and forced, so a query only sees rows whose
`user_id` equals the `app.user_id` setting of the transaction, or every row when the transaction
sets `app.system` to 'on' (event handlers). With neither set, no rows are visible: it fails closed.

Row-level security does not apply to superusers or to roles with BYPASSRLS, so the application must
connect as an ordinary role in production.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "watchlist_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = ("watchlist",)
depends_on: str | Sequence[str] | None = None

SCHEMA = "watchlist"
TABLES = ("saved_medicines", "allergies", "alerts")
VISIBLE = (
    "user_id::text = current_setting('app.user_id', true) "
    "OR current_setting('app.system', true) = 'on'"
)


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.saved_medicines (
            user_id uuid NOT NULL,
            register_number text NOT NULL,
            added_at timestamptz NOT NULL,
            PRIMARY KEY (user_id, register_number)
        )
        """
    )
    op.execute(
        f"CREATE INDEX ix_saved_medicines_register ON {SCHEMA}.saved_medicines (register_number)"
    )
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.allergies (
            user_id uuid NOT NULL,
            key text NOT NULL,
            ingredient text NOT NULL,
            added_at timestamptz NOT NULL,
            PRIMARY KEY (user_id, key)
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.alerts (
            id uuid PRIMARY KEY,
            user_id uuid NOT NULL,
            kind text NOT NULL,
            register_number text NOT NULL,
            event_id uuid NOT NULL,
            occurred_at timestamptz NOT NULL,
            details jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            created_at timestamptz NOT NULL,
            read_at timestamptz,
            CONSTRAINT uq_alerts_user_event UNIQUE (user_id, event_id),
            CONSTRAINT ck_alerts_kind CHECK (kind IN ('price_changed', 'withdrawn', 'relisted'))
        )
        """
    )
    op.execute(f"CREATE INDEX ix_alerts_user_time ON {SCHEMA}.alerts (user_id, occurred_at DESC)")
    for table in TABLES:
        op.execute(f"ALTER TABLE {SCHEMA}.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {SCHEMA}.{table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY own_rows ON {SCHEMA}.{table} USING ({VISIBLE}) WITH CHECK ({VISIBLE})"
        )


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.{table}")
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA}")
