"""Rows of the official SFDA lists and their links to catalog products.

Revision ID: catalog_0002
Revises: catalog_0001
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "catalog_0002"
down_revision: str | None = "catalog_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "catalog"


def upgrade() -> None:
    op.create_table(
        "source_list_rows",
        sa.Column("list_name", sa.Text(), primary_key=True),
        sa.Column("row_key", sa.Text(), primary_key=True),
        sa.Column("entity_key", sa.Text(), nullable=False),
        sa.Column("link", sa.Text(), nullable=True),
        sa.Column("cells", postgresql.JSONB(), nullable=False),
        sa.Column("list_page", sa.Integer(), nullable=False),
        sa.Column("provenance_source", sa.Text(), nullable=False),
        sa.Column("provenance_source_ref", sa.Text(), nullable=False),
        sa.Column("provenance_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provenance_snapshot_id", sa.Text(), nullable=False),
        sa.Column("provenance_trust", sa.String(32), nullable=False),
        schema=SCHEMA,
    )
    op.create_table(
        "source_list_links",
        sa.Column("list_name", sa.Text(), primary_key=True),
        sa.Column("row_key", sa.Text(), primary_key=True),
        sa.Column("market", sa.String(2), primary_key=True),
        sa.Column("register_number", sa.Text(), primary_key=True),
        sa.Column("confidence", sa.String(16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["list_name", "row_key"],
            [f"{SCHEMA}.source_list_rows.list_name", f"{SCHEMA}.source_list_rows.row_key"],
            ondelete="CASCADE",
            name="fk_source_list_links_row",
        ),
        sa.ForeignKeyConstraint(
            ["market", "register_number"],
            [f"{SCHEMA}.products.market", f"{SCHEMA}.products.register_number"],
            ondelete="CASCADE",
            name="fk_source_list_links_product",
        ),
        sa.CheckConstraint("confidence in ('matched', 'possible')", name="ck_source_list_links"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_source_list_links_product",
        "source_list_links",
        ["market", "register_number"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index("ix_source_list_links_product", table_name="source_list_links", schema=SCHEMA)
    op.drop_table("source_list_links", schema=SCHEMA)
    op.drop_table("source_list_rows", schema=SCHEMA)
