"""Create the offers schema: online pharmacy listings, prices, matches and crawl accounting.

Revision ID: offers_0001
Revises:
Create Date: 2026-11-23

Design: docs/PHARMACY_SCRAPING_PLAN.md section 2.2 (ADR-019). No foreign key leaves this schema:
`register_number` is plain text, resolved through the catalog's contracts. The current price and
availability sit on `listing`; their history is append-only in `price_point` and
`availability_change`, written only when the value changes. Descriptions are stored once per
distinct text and only for matched and possible medicine listings (plan section 2.2).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "offers_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = ("offers",)
depends_on: str | Sequence[str] | None = None

SCHEMA = "offers"


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.retailer (
            id text PRIMARY KEY,
            name text NOT NULL,
            base_url text NOT NULL,
            platform text NOT NULL,
            market text NOT NULL,
            currency text,
            status text NOT NULL DEFAULT 'candidate',
            paused_reason text,
            config_hash text,
            validated_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_retailer_status CHECK (
                status IN ('candidate', 'validated', 'active', 'paused', 'blocked', 'retired')
            )
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.listing (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            retailer_id text NOT NULL REFERENCES {SCHEMA}.retailer (id),
            source_id text NOT NULL,
            url text NOT NULL,
            name_en text,
            name_ar text,
            brand text,
            category text NOT NULL DEFAULT 'unclassified',
            category_path text,
            ingredients_text text,
            dosage_form_text text,
            pack_text text,
            barcode text,
            image_urls text[] NOT NULL DEFAULT '{{}}',
            status text NOT NULL DEFAULT 'active',
            status_changed_at timestamptz NOT NULL DEFAULT now(),
            missed_runs smallint NOT NULL DEFAULT 0,
            gone_runs smallint NOT NULL DEFAULT 0,
            first_seen_at timestamptz NOT NULL DEFAULT now(),
            last_seen_at timestamptz NOT NULL DEFAULT now(),
            source_lastmod timestamptz,
            etag text,
            last_modified text,
            content_hash bytea,
            tier smallint NOT NULL DEFAULT 2,
            price_amount numeric(12, 2),
            price_currency text,
            price_observed_at timestamptz,
            availability text NOT NULL DEFAULT 'unknown',
            availability_observed_at timestamptz,
            CONSTRAINT uq_listing_source UNIQUE (retailer_id, source_id),
            CONSTRAINT uq_listing_url UNIQUE (url),
            CONSTRAINT ck_listing_category CHECK (
                category IN ('medicine', 'cosmetic', 'device', 'other', 'unclassified')
            ),
            CONSTRAINT ck_listing_status CHECK (
                status IN ('active', 'unavailable', 'missing', 'discontinued')
            ),
            CONSTRAINT ck_listing_availability CHECK (
                availability IN ('in_stock', 'out_of_stock', 'unknown')
            ),
            CONSTRAINT ck_listing_tier CHECK (tier IN (1, 2)),
            CONSTRAINT ck_listing_price CHECK (price_amount IS NULL OR price_amount > 0)
        )
        """
    )
    op.execute(f"CREATE INDEX ix_listing_retailer_status ON {SCHEMA}.listing (retailer_id, status)")
    op.execute(
        f"CREATE INDEX ix_listing_watch ON {SCHEMA}.listing (retailer_id, tier, price_observed_at)"
    )
    op.execute(
        f"CREATE INDEX ix_listing_barcode ON {SCHEMA}.listing (barcode) WHERE barcode IS NOT NULL"
    )
    op.execute(
        f"""
        CREATE INDEX ix_listing_medicine ON {SCHEMA}.listing (retailer_id)
        WHERE category = 'medicine' AND status = 'active'
        """
    )
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.price_point (
            listing_id bigint NOT NULL REFERENCES {SCHEMA}.listing (id) ON DELETE CASCADE,
            observed_at timestamptz NOT NULL,
            amount numeric(12, 2) NOT NULL,
            currency text,
            PRIMARY KEY (listing_id, observed_at),
            CONSTRAINT ck_price_point_amount CHECK (amount > 0)
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.availability_change (
            listing_id bigint NOT NULL REFERENCES {SCHEMA}.listing (id) ON DELETE CASCADE,
            observed_at timestamptz NOT NULL,
            availability text NOT NULL,
            PRIMARY KEY (listing_id, observed_at),
            CONSTRAINT ck_availability_change CHECK (
                availability IN ('in_stock', 'out_of_stock', 'unknown')
            )
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.price_month (
            listing_id bigint NOT NULL REFERENCES {SCHEMA}.listing (id) ON DELETE CASCADE,
            month date NOT NULL,
            min_amount numeric(12, 2) NOT NULL,
            max_amount numeric(12, 2) NOT NULL,
            last_amount numeric(12, 2) NOT NULL,
            points integer NOT NULL,
            PRIMARY KEY (listing_id, month)
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.description_text (
            hash bytea PRIMARY KEY,
            text text NOT NULL,
            language text,
            CONSTRAINT ck_description_text CHECK (length(btrim(text)) > 0)
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.listing_text (
            listing_id bigint PRIMARY KEY REFERENCES {SCHEMA}.listing (id) ON DELETE CASCADE,
            description_hash bytea NOT NULL REFERENCES {SCHEMA}.description_text (hash),
            observed_at timestamptz NOT NULL
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.listing_match (
            listing_id bigint PRIMARY KEY REFERENCES {SCHEMA}.listing (id) ON DELETE CASCADE,
            register_number text,
            status text NOT NULL,
            evidence jsonb NOT NULL DEFAULT '{{}}',
            matcher_version smallint NOT NULL,
            decided_at timestamptz NOT NULL DEFAULT now(),
            reviewed_by text,
            reviewed_at timestamptz,
            CONSTRAINT ck_listing_match_status CHECK (
                status IN ('matched', 'possible', 'needs_review', 'no_match', 'not_applicable')
            ),
            CONSTRAINT ck_listing_match_register CHECK (
                (status IN ('matched', 'possible')) = (register_number IS NOT NULL)
            )
        )
        """
    )
    op.execute(
        f"""
        CREATE INDEX ix_listing_match_register ON {SCHEMA}.listing_match (register_number)
        WHERE status IN ('matched', 'possible')
        """
    )
    op.execute(
        f"""
        CREATE INDEX ix_listing_match_review ON {SCHEMA}.listing_match (decided_at)
        WHERE status = 'needs_review'
        """
    )
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.match_conflict (
            listing_id bigint NOT NULL REFERENCES {SCHEMA}.listing (id) ON DELETE CASCADE,
            register_number text NOT NULL,
            reason text NOT NULL,
            PRIMARY KEY (listing_id, register_number),
            CONSTRAINT ck_match_conflict_reason CHECK (
                reason IN ('ingredients', 'strength', 'form')
            )
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.price_anomaly (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            listing_id bigint NOT NULL REFERENCES {SCHEMA}.listing (id) ON DELETE CASCADE,
            observed_at timestamptz NOT NULL,
            old_amount numeric(12, 2),
            new_amount numeric(12, 2),
            rule text NOT NULL,
            state text NOT NULL DEFAULT 'quarantined',
            resolved_at timestamptz,
            CONSTRAINT ck_price_anomaly_state CHECK (
                state IN ('quarantined', 'confirmed', 'rejected')
            )
        )
        """
    )
    op.execute(
        f"""
        CREATE INDEX ix_price_anomaly_open ON {SCHEMA}.price_anomaly (listing_id)
        WHERE state = 'quarantined'
        """
    )
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.scrape_run (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            retailer_id text NOT NULL REFERENCES {SCHEMA}.retailer (id),
            job_type text NOT NULL,
            shard smallint NOT NULL DEFAULT 0,
            started_at timestamptz NOT NULL,
            finished_at timestamptz,
            status text NOT NULL,
            requests integer NOT NULL DEFAULT 0,
            discovered integer NOT NULL DEFAULT 0,
            new integer NOT NULL DEFAULT 0,
            changed integer NOT NULL DEFAULT 0,
            unchanged integer NOT NULL DEFAULT 0,
            failed integer NOT NULL DEFAULT 0,
            missing_price integer NOT NULL DEFAULT 0,
            bad_images integer NOT NULL DEFAULT 0,
            completeness numeric(4, 3),
            error_classes jsonb NOT NULL DEFAULT '{{}}',
            cursor jsonb,
            CONSTRAINT ck_scrape_run_job CHECK (
                job_type IN ('discover', 'update', 'price', 'availability')
            ),
            CONSTRAINT ck_scrape_run_status CHECK (
                status IN ('complete', 'partial', 'failed', 'blocked')
            )
        )
        """
    )
    op.execute(
        f"""
        CREATE INDEX ix_scrape_run_retailer ON {SCHEMA}.scrape_run
            (retailer_id, job_type, started_at DESC)
        """
    )


def downgrade() -> None:
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
