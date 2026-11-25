"""Store every product's look-alike names, computed by the daily refresh.

Revision ID: search_0002
Revises: search_0001
Create Date: 2026-11-25

Building the name index on a fresh API instance took 2.6 s on Vercel; the daily refresh now computes
each product's look-alikes once and the API reads one row. Rows hold only names and register numbers
already in the catalog: nothing here points at the catalog's tables.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "search_0002"
down_revision: str | None = "search_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "search"


def upgrade() -> None:
    op.create_table(
        "similar_name",
        sa.Column("market", sa.String(2), primary_key=True),
        sa.Column("register_number", sa.Text(), primary_key=True),
        sa.Column("english", JSONB(), nullable=False),
        sa.Column("arabic", JSONB(), nullable=False),
        sa.Column(
            "built_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("similar_name", schema=SCHEMA)
