"""Say what each emailed code is for: confirming the address, or choosing a new password.

Revision ID: identity_0004
Revises: identity_0003
Create Date: 2026-11-26

Codes that exist already were all sent to confirm an address, so they become `verify`. A new code
retires only the earlier codes of its own purpose, and one purpose's code never works for the other
(the purpose is also part of the code's keyed hash).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "identity_0004"
down_revision: str | None = "identity_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "identity"


def upgrade() -> None:
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.email_codes
            ADD COLUMN purpose text NOT NULL DEFAULT 'verify',
            ADD CONSTRAINT ck_email_codes_purpose CHECK (purpose IN ('verify', 'reset'))
        """
    )
    op.execute(f"DROP INDEX IF EXISTS {SCHEMA}.ix_email_codes_user")
    op.execute(
        f"CREATE INDEX ix_email_codes_user ON {SCHEMA}.email_codes "
        "(user_id, purpose, created_at DESC)"
    )


def downgrade() -> None:
    op.execute(f"DELETE FROM {SCHEMA}.email_codes WHERE purpose = 'reset'")  # noqa: S608
    op.execute(f"DROP INDEX IF EXISTS {SCHEMA}.ix_email_codes_user")
    op.execute(
        f"CREATE INDEX ix_email_codes_user ON {SCHEMA}.email_codes (user_id, created_at DESC)"
    )
    op.execute(
        f"ALTER TABLE {SCHEMA}.email_codes DROP CONSTRAINT ck_email_codes_purpose, "
        "DROP COLUMN purpose"
    )
