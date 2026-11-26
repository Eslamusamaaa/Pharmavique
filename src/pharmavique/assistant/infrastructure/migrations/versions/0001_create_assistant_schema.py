"""Create the assistant schema: saved conversations and their messages (ADR-022).

Revision ID: assistant_0001
Revises:
Create Date: 2026-11-26

Every row belongs to one person (`user_id`; no foreign key, the person lives in the identity
schema). Row-level security is on and forced, as in the watchlist schema: a query sees only the rows
whose `user_id` equals the transaction's `app.user_id`, or every row when it sets `app.system` to
'on' (reading a share link by its token). With neither set, nothing is visible.

`title_key` and `text_key` hold the normalized text that search compares (Arabic letter forms,
diacritics, digits). A message's `position` keeps the order in which it was added.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "assistant_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = ("assistant",)
depends_on: str | Sequence[str] | None = None

SCHEMA = "assistant"
TABLES = ("conversations", "messages")
VISIBLE = (
    "user_id::text = current_setting('app.user_id', true) "
    "OR current_setting('app.system', true) = 'on'"
)


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.conversations (
            id uuid PRIMARY KEY,
            user_id uuid NOT NULL,
            level text NOT NULL,
            title text NOT NULL,
            title_key text NOT NULL,
            title_source text NOT NULL,
            pinned boolean NOT NULL DEFAULT false,
            questions integer NOT NULL DEFAULT 0,
            created_at timestamptz NOT NULL,
            updated_at timestamptz NOT NULL,
            share_token text,
            shared_at timestamptz,
            shared_copy jsonb,
            CONSTRAINT uq_conversations_share_token UNIQUE (share_token),
            CONSTRAINT ck_conversations_level
                CHECK (level IN ('patient', 'pharmacist', 'clinical')),
            CONSTRAINT ck_conversations_title_source
                CHECK (title_source IN ('question', 'model', 'person'))
        )
        """
    )
    op.execute(
        f"CREATE INDEX ix_conversations_list ON {SCHEMA}.conversations "
        "(user_id, level, pinned DESC, updated_at DESC)"
    )
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.messages (
            id uuid PRIMARY KEY,
            conversation_id uuid NOT NULL
                REFERENCES {SCHEMA}.conversations (id) ON DELETE CASCADE,
            user_id uuid NOT NULL,
            position bigint GENERATED ALWAYS AS IDENTITY,
            role text NOT NULL,
            text text NOT NULL,
            text_key text NOT NULL,
            status text NOT NULL,
            payload jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            created_at timestamptz NOT NULL,
            CONSTRAINT ck_messages_role CHECK (role IN ('user', 'assistant')),
            CONSTRAINT ck_messages_status CHECK (status IN ('ok', 'pending', 'failed'))
        )
        """
    )
    op.execute(
        f"CREATE INDEX ix_messages_conversation ON {SCHEMA}.messages (conversation_id, position)"
    )
    for table in TABLES:
        op.execute(f"ALTER TABLE {SCHEMA}.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {SCHEMA}.{table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY own_rows ON {SCHEMA}.{table} USING ({VISIBLE}) WITH CHECK ({VISIBLE})"
        )


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.messages")
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.conversations")
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA}")
