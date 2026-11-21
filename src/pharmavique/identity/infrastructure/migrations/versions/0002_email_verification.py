"""Confirm an email address with a code, and let people switch email notifications off.

Revision ID: identity_0002
Revises: identity_0001
Create Date: 2026-11-22

`email_verified_at` is set when the person enters the code that was emailed to them. Accounts that
already exist were made before the rule, so they count as confirmed from their creation (otherwise
they could no longer sign in). `email_codes` keeps only a keyed hash of each code, with its expiry
and the number of wrong tries; codes are deleted with their user.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "identity_0002"
down_revision: str | None = "identity_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "identity"


def upgrade() -> None:
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.users
            ADD COLUMN email_verified_at timestamptz,
            ADD COLUMN email_notifications boolean NOT NULL DEFAULT true
        """
    )
    op.execute(f"UPDATE {SCHEMA}.users SET email_verified_at = created_at")  # noqa: S608
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.email_codes (
            id uuid PRIMARY KEY,
            user_id uuid NOT NULL REFERENCES {SCHEMA}.users (id) ON DELETE CASCADE,
            code_hash text NOT NULL,
            expires_at timestamptz NOT NULL,
            created_at timestamptz NOT NULL,
            attempts integer NOT NULL DEFAULT 0,
            consumed_at timestamptz
        )
        """
    )
    op.execute(
        f"CREATE INDEX ix_email_codes_user ON {SCHEMA}.email_codes (user_id, created_at DESC)"
    )


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.email_codes")
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.users
            DROP COLUMN email_notifications,
            DROP COLUMN email_verified_at
        """
    )
