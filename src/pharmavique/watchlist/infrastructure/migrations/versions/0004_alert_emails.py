"""Remember which alerts were already emailed, so a digest never repeats one.

Revision ID: watchlist_0004
Revises: watchlist_0003
Create Date: 2026-11-22

`emailed_at` is set when an alert has been handled by the email digest: sent in a digest, or skipped
because the person turned email off. The in-app inbox ignores it. The existing row-level security
policy already limits every row to its owner (or to the system handler that sends the digest).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "watchlist_0004"
down_revision: str | None = "watchlist_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "watchlist"


def upgrade() -> None:
    op.execute(f"ALTER TABLE {SCHEMA}.alerts ADD COLUMN emailed_at timestamptz")
    # alerts that exist today were never meant for the digest: do not send a backlog
    op.execute(f"UPDATE {SCHEMA}.alerts SET emailed_at = now()")  # noqa: S608
    op.execute(
        f"CREATE INDEX ix_alerts_not_emailed ON {SCHEMA}.alerts (created_at) "
        "WHERE emailed_at IS NULL"
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {SCHEMA}.ix_alerts_not_emailed")
    op.execute(f"ALTER TABLE {SCHEMA}.alerts DROP COLUMN emailed_at")
