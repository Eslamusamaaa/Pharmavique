"""Remember addresses that are not products, and keep every counter of a crawl run.

Revision ID: offers_0002
Revises: offers_0001
Create Date: 2026-11-23

`skipped_url`: an address judged not to be a product page (a category, a brand page, a page that is
gone), so a resumed or repeated crawl does not fetch it again.
`scrape_run.counters`: all counters of a run (requests, new, changed, failed, per-category counts,
what was left).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "offers_0002"
down_revision: str | None = "offers_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "offers"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.skipped_url (
            retailer_id text NOT NULL REFERENCES {SCHEMA}.retailer (id),
            url text NOT NULL,
            reason text NOT NULL,
            seen_at timestamptz NOT NULL,
            PRIMARY KEY (retailer_id, url),
            CONSTRAINT ck_skipped_url_reason CHECK (
                reason IN ('not_a_product', 'gone', 'duplicate_url')
            )
        )
        """
    )
    op.execute(f"ALTER TABLE {SCHEMA}.scrape_run ADD COLUMN counters jsonb NOT NULL DEFAULT '{{}}'")


def downgrade() -> None:
    op.execute(f"ALTER TABLE {SCHEMA}.scrape_run DROP COLUMN IF EXISTS counters")
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.skipped_url")
