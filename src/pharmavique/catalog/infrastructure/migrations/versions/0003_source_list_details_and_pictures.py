"""Detail pages of list rows, and the picture of each product.

Revision ID: catalog_0003
Revises: catalog_0002
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "catalog_0003"
down_revision: str | None = "catalog_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "catalog"


def upgrade() -> None:
    op.add_column(
        "source_list_rows",
        sa.Column(
            "detail",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "product_pictures",
        sa.Column("market", sa.String(2), primary_key=True),
        sa.Column("register_number", sa.Text(), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("content_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=True),
        sa.Column("verification", sa.String(32), nullable=False),
        sa.Column("form_group", sa.String(32), nullable=True),
        sa.Column("source_page", sa.Text(), nullable=True),
        sa.Column("source_image_url", sa.Text(), nullable=True),
        sa.Column("trust", sa.String(32), nullable=True),
        sa.ForeignKeyConstraint(
            ["market", "register_number"],
            [f"{SCHEMA}.products.market", f"{SCHEMA}.products.register_number"],
            ondelete="CASCADE",
            name="fk_product_pictures_product",
        ),
        sa.CheckConstraint("kind in ('real', 'generated')", name="ck_product_pictures_kind"),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("product_pictures", schema=SCHEMA)
    op.drop_column("source_list_rows", "detail", schema=SCHEMA)
