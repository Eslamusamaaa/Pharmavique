"""An operator verifies or rejects pharmacist and company accounts (ADR-020).

Revision ID: identity_0003
Revises: identity_0002
Create Date: 2026-11-25

`role_review` is `not_needed` for patients and operators and starts `pending` for pharmacists and
companies; existing professional accounts wait for review too (their role was never checked). The
operator's reason, shown to the person, is `role_review_note`. A partial index serves the waiting
list.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "identity_0003"
down_revision: str | None = "identity_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "identity"


def upgrade() -> None:
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.users
            ADD COLUMN role_review text NOT NULL DEFAULT 'not_needed',
            ADD COLUMN role_reviewed_at timestamptz,
            ADD COLUMN role_review_note text
        """
    )
    op.execute(
        f"UPDATE {SCHEMA}.users SET role_review = 'pending' "  # noqa: S608
        "WHERE role IN ('pharmacist', 'company')"
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.users
            ADD CONSTRAINT ck_users_role_review CHECK (
                role_review IN ('not_needed', 'pending', 'verified', 'rejected')
                AND (role IN ('pharmacist', 'company')) = (role_review <> 'not_needed')
            )
        """
    )
    op.execute(
        f"CREATE INDEX ix_users_role_review_pending ON {SCHEMA}.users (created_at) "
        "WHERE role_review = 'pending'"
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {SCHEMA}.ix_users_role_review_pending")
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.users
            DROP CONSTRAINT IF EXISTS ck_users_role_review,
            DROP COLUMN role_review_note,
            DROP COLUMN role_reviewed_at,
            DROP COLUMN role_review
        """
    )
