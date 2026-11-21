"""Create the interactions schema: recorded drug-drug interactions from outside sources.

Revision ID: interactions_0001
Revises:
Create Date: 2026-11-21

One row per pair of ingredients and source. Both names are normalized keys and `ingredient_a`
sorts before `ingredient_b` in byte order (as Python sorts), so a pair is stored once. Nothing
here points at another context's tables: products are matched to these keys by name, in code.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "interactions_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = ("interactions",)
depends_on: str | Sequence[str] | None = None

SCHEMA = "interactions"


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.pair (
            ingredient_a text NOT NULL,
            ingredient_b text NOT NULL,
            severity text NOT NULL,
            source text NOT NULL,
            source_ref text NOT NULL,
            snapshot_id text NOT NULL,
            fetched_at timestamptz NOT NULL,
            trust text NOT NULL,
            PRIMARY KEY (ingredient_a, ingredient_b, source),
            CONSTRAINT ck_pair_order CHECK (
                ingredient_a COLLATE "C" < ingredient_b COLLATE "C"
            ),
            CONSTRAINT ck_pair_severity CHECK (
                severity IN ('major', 'moderate', 'minor', 'unknown')
            ),
            CONSTRAINT ck_pair_trust CHECK (trust IN ('official', 'unofficial_unverified'))
        )
        """
    )
    op.execute(f"CREATE INDEX ix_pair_b ON {SCHEMA}.pair (ingredient_b)")


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.pair")
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA}")
