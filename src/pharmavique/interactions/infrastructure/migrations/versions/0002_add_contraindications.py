"""Add drug-disease contraindications (what a drug's label says it must not be used with).

Revision ID: interactions_0002
Revises: interactions_0001
Create Date: 2026-11-21

One row per ingredient key, disease and source, with the label text it came from and its
provenance. Nothing here points at another context's tables.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "interactions_0002"
down_revision: str | None = "interactions_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "interactions"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.contraindication (
            ingredient text NOT NULL,
            disease text NOT NULL,
            disease_id text NOT NULL DEFAULT '',
            label_text text NOT NULL DEFAULT '',
            source text NOT NULL,
            source_ref text NOT NULL,
            snapshot_id text NOT NULL,
            fetched_at timestamptz NOT NULL,
            trust text NOT NULL,
            PRIMARY KEY (ingredient, disease, source),
            CONSTRAINT ck_contraindication_trust CHECK (
                trust IN ('official', 'unofficial_unverified')
            )
        )
        """
    )


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.contraindication")
