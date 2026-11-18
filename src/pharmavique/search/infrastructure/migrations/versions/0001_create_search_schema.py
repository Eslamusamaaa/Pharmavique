"""Create the search schema: the products search can find and the terms it finds them by.

Revision ID: search_0001
Revises:
Create Date: 2026-11-18

`search` keeps its own projection, rebuilt from the catalog's published product cards, so nothing
here points at the catalog's tables. Each product has terms (its normalized names, and its
ingredients joined into one text); a trigram index on the terms makes the fuzzy lookup fast.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "search_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = ("search",)
depends_on: str | Sequence[str] | None = None

SCHEMA = "search"


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    op.create_table(
        "product",
        sa.Column("market", sa.String(2), primary_key=True),
        sa.Column("register_number", sa.Text(), primary_key=True),
        sa.Column("withdrawn", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema=SCHEMA,
    )

    op.create_table(
        "term",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("market", sa.String(2), nullable=False),
        sa.Column("register_number", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.CheckConstraint("kind in ('name', 'ingredient')", name="ck_term_kind"),
        sa.ForeignKeyConstraint(
            ["market", "register_number"],
            [f"{SCHEMA}.product.market", f"{SCHEMA}.product.register_number"],
            ondelete="CASCADE",
            name="fk_term_product",
        ),
        schema=SCHEMA,
    )
    op.create_index("ix_term_product", "term", ["market", "register_number"], schema=SCHEMA)
    op.execute(f"CREATE INDEX ix_term_text_trgm ON {SCHEMA}.term USING gin (text gin_trgm_ops)")


def downgrade() -> None:
    op.drop_table("term", schema=SCHEMA)
    op.drop_table("product", schema=SCHEMA)
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA}")
