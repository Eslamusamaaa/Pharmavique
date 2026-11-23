"""Put back the keys and indexes a database may have lost in an interrupted restore.

Revision ID: catalog_0006
Revises: catalog_0005
Create Date: 2026-11-23

The production database (Neon) was filled from a restore that stopped before its last section:
the tables and rows were there, the primary keys, foreign keys and indexes of the catalog schema
were not. Without them a table can hold a row twice, and deleting a list's rows left every old
link behind, so shortage links kept piling up.

On a database that has them this changes nothing. On one that lacks them it deletes the extra
copies of a row (one is kept), the rows whose parent is not there, and then adds what
`catalog_0001` to `catalog_0003` define. There is nothing to undo: the keys and indexes belong to
those revisions, whose downgrades drop the tables.
"""

# ruff: noqa: S608 (the SQL is built from the constants below, never from input)
from collections.abc import Sequence

from alembic import op

revision: str = "catalog_0006"
down_revision: str | None = "catalog_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, constraint, key columns)
PRIMARY_KEYS = (
    ("products", "products_pkey", "market, register_number"),
    ("price_history", "price_history_pkey", "id"),
    ("outbox", "outbox_pkey", "id"),
    ("source_list_rows", "source_list_rows_pkey", "list_name, row_key"),
    ("source_list_links", "source_list_links_pkey", "list_name, row_key, market, register_number"),
    ("product_pictures", "product_pictures_pkey", "market, register_number"),
)
# (child table, constraint, child columns, parent table, parent columns)
FOREIGN_KEYS = (
    (
        "price_history",
        "fk_price_history_product",
        "market, register_number",
        "products",
        "market, register_number",
    ),
    (
        "product_pictures",
        "fk_product_pictures_product",
        "market, register_number",
        "products",
        "market, register_number",
    ),
    (
        "source_list_links",
        "fk_source_list_links_row",
        "list_name, row_key",
        "source_list_rows",
        "list_name, row_key",
    ),
    (
        "source_list_links",
        "fk_source_list_links_product",
        "market, register_number",
        "products",
        "market, register_number",
    ),
)
INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_outbox_unpublished ON catalog.outbox (occurred_at)"
    " WHERE published_at IS NULL",
    "CREATE INDEX IF NOT EXISTS ix_price_history_product_time ON catalog.price_history"
    " (market, register_number, effective_from)",
    "CREATE INDEX IF NOT EXISTS ix_source_list_links_product ON catalog.source_list_links"
    " (market, register_number)",
)


def _missing(table: str, name: str) -> str:
    return (
        "NOT EXISTS (SELECT 1 FROM pg_constraint"
        f" WHERE conname = '{name}' AND conrelid = 'catalog.{table}'::regclass)"
    )


def upgrade() -> None:
    for table, name, columns in PRIMARY_KEYS:
        same = " AND ".join(f"a.{c.strip()} = b.{c.strip()}" for c in columns.split(","))
        op.execute(
            f"""
            DO $$ BEGIN
              IF to_regclass('catalog.{table}') IS NOT NULL AND {_missing(table, name)} THEN
                DELETE FROM catalog.{table} a USING catalog.{table} b
                  WHERE a.ctid < b.ctid AND {same};
                ALTER TABLE catalog.{table} ADD CONSTRAINT {name} PRIMARY KEY ({columns});
              END IF;
            END $$
            """
        )
    for child, name, child_columns, parent, parent_columns in FOREIGN_KEYS:
        orphan = " AND ".join(
            f"p.{p.strip()} = c.{c.strip()}"
            for c, p in zip(child_columns.split(","), parent_columns.split(","), strict=True)
        )
        op.execute(
            f"""
            DO $$ BEGIN
              IF to_regclass('catalog.{child}') IS NOT NULL AND {_missing(child, name)} THEN
                DELETE FROM catalog.{child} c WHERE NOT EXISTS
                  (SELECT 1 FROM catalog.{parent} p WHERE {orphan});
                ALTER TABLE catalog.{child} ADD CONSTRAINT {name}
                  FOREIGN KEY ({child_columns}) REFERENCES catalog.{parent} ({parent_columns})
                  ON DELETE CASCADE;
              END IF;
            END $$
            """
        )
    for statement in INDEXES:
        op.execute(statement)


def downgrade() -> None:
    """Nothing to undo: see the module text."""
