"""Keep the pictures of listings as files, and remember what happened to each one.

Revision ID: offers_0003
Revises: offers_0002
Create Date: 2026-11-23

`listing_image`: one row per picture we tried (listing, position, address, result). The file
itself lives on disk, named after its content (`sha256`), so the same picture used by two listings
is stored once. Nothing here is the registry's.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "offers_0003"
down_revision: str | None = "offers_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "offers"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.listing_image (
            listing_id bigint NOT NULL REFERENCES {SCHEMA}.listing (id) ON DELETE CASCADE,
            position smallint NOT NULL,
            url text NOT NULL,
            status text NOT NULL,
            file_path text,
            sha256 text,
            bytes integer,
            content_type text,
            fetched_at timestamptz NOT NULL,
            PRIMARY KEY (listing_id, position),
            CONSTRAINT ck_listing_image_status CHECK (
                status IN ('ok', 'gone', 'failed', 'not_an_image')
            ),
            CONSTRAINT ck_listing_image_file CHECK ((status = 'ok') = (file_path IS NOT NULL))
        )
        """
    )


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.listing_image")
