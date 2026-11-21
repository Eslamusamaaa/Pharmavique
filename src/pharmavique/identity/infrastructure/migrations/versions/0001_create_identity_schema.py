"""Create the identity schema: users and refresh tokens.

Revision ID: identity_0001
Revises:
Create Date: 2026-11-21

A user has one role and, for pharmacists and companies, a tenant id. The email is stored trimmed
and lower case and is unique. Refresh tokens are stored only as a hash and are deleted with their
user. Nothing here points at another context's tables.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "identity_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = ("identity",)
depends_on: str | Sequence[str] | None = None

SCHEMA = "identity"


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.users (
            id uuid PRIMARY KEY,
            email text NOT NULL,
            password_hash text NOT NULL,
            role text NOT NULL,
            tenant_id uuid,
            created_at timestamptz NOT NULL,
            CONSTRAINT uq_users_email UNIQUE (email),
            CONSTRAINT ck_users_email CHECK (email = lower(btrim(email))),
            CONSTRAINT ck_users_role CHECK (
                role IN ('patient', 'pharmacist', 'company', 'operator')
            ),
            CONSTRAINT ck_users_tenant CHECK (
                (role IN ('pharmacist', 'company')) = (tenant_id IS NOT NULL)
            )
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.refresh_tokens (
            token_hash text PRIMARY KEY,
            user_id uuid NOT NULL REFERENCES {SCHEMA}.users (id) ON DELETE CASCADE,
            expires_at timestamptz NOT NULL,
            used boolean NOT NULL DEFAULT false,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(f"CREATE INDEX ix_refresh_tokens_user ON {SCHEMA}.refresh_tokens (user_id)")


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.refresh_tokens")
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.users")
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA}")
