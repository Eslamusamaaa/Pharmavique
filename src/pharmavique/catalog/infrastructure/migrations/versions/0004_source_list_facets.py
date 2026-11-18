"""Clean filter values (facets) of list rows.

Revision ID: catalog_0004
Revises: catalog_0003
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "catalog_0004"
down_revision: str | None = "catalog_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "catalog"


def upgrade() -> None:
    op.add_column(
        "source_list_rows",
        sa.Column(
            "facets",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("source_list_rows", "facets", schema=SCHEMA)
