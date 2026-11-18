"""Create the knowledge schema: cited chunks of official documents and their vectors (ADR-006).

Revision ID: knowledge_0001
Revises:
Create Date: 2026-11-18

Nothing here points at another context's tables. `embedding` is filled by the embedding job when a
provider key exists (1024 dimensions: BGE-M3, Qwen3-Embedding-0.6B and multilingual-e5-large all
use that size); `embedding_model` records which model made it, so vectors of two models never mix.
The HNSW index is created by the embedding job once vectors exist.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "knowledge_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = ("knowledge",)
depends_on: str | Sequence[str] | None = None

SCHEMA = "knowledge"


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.chunk (
            chunk_id text PRIMARY KEY,
            list_name text NOT NULL,
            row_key text NOT NULL,
            position integer NOT NULL,
            title text NOT NULL,
            text text NOT NULL,
            source_ref text NOT NULL,
            snapshot_id text NOT NULL,
            fetched_at timestamptz,
            trust text NOT NULL,
            ocr boolean NOT NULL DEFAULT false,
            published text,
            register_numbers text[] NOT NULL DEFAULT '{{}}',
            embedding vector(1024),
            embedding_model text,
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_chunk_trust CHECK (trust IN ('official', 'unofficial_unverified'))
        )
        """
    )
    op.execute(f"CREATE INDEX ix_chunk_list ON {SCHEMA}.chunk (list_name, row_key, position)")
    op.execute(f"CREATE INDEX ix_chunk_text_trgm ON {SCHEMA}.chunk USING gin (text gin_trgm_ops)")
    op.execute(f"CREATE INDEX ix_chunk_register ON {SCHEMA}.chunk USING gin (register_numbers)")


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.chunk")
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA}")
