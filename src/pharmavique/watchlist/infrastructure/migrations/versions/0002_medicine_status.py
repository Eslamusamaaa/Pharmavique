"""Let a person mark a saved medicine as one they took before, so the list is a history.

Revision ID: watchlist_0002
Revises: watchlist_0001
Create Date: 2026-11-21

`status` is the person's own record: `current` (they take it now) or `past` (they took it before).
Only current medicines raise alerts and are compared with a new drug. Existing rows are current.
Row-level security is unchanged: the table policy already limits every row to its owner.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "watchlist_0002"
down_revision: str | None = "watchlist_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "watchlist"


def upgrade() -> None:
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.saved_medicines
            ADD COLUMN status text NOT NULL DEFAULT 'current',
            ADD COLUMN status_changed_at timestamptz,
            ADD CONSTRAINT ck_saved_medicines_status CHECK (status IN ('current', 'past'))
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.saved_medicines
            DROP CONSTRAINT ck_saved_medicines_status,
            DROP COLUMN status_changed_at,
            DROP COLUMN status
        """
    )
