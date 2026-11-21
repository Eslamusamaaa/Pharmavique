"""One point per city, found by a geocoder, to say which pharmacies are near a person.

Revision ID: catalog_0005
Revises: catalog_0004
Create Date: 2026-11-21

The SFDA pharmacy list has a city and a national-address short code for each pharmacy and nothing
finer, so a city is the finest place we can attach to one. Each row keeps where the point came from
and when; it is `unofficial_unverified`, because a geocoder is not an official source.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "catalog_0005"
down_revision: str | None = "catalog_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "catalog"


def upgrade() -> None:
    op.create_table(
        "city_locations",
        sa.Column("market", sa.String(2), primary_key=True),
        sa.Column("city_key", sa.Text(), primary_key=True),
        sa.Column("city", sa.Text(), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trust", sa.String(32), nullable=False),
        sa.CheckConstraint("latitude between -90 and 90", name="ck_city_locations_lat"),
        sa.CheckConstraint("longitude between -180 and 180", name="ck_city_locations_lon"),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("city_locations", schema=SCHEMA)
