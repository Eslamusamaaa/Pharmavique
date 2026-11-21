#!/usr/bin/env bash
# Restore data/db/*.dump (one file per schema) into the local Postgres (replaces what is there).
#
#   docker compose up -d db && bash scripts/db_restore.sh
#
# The extensions (pgvector, pg_trgm) are created first because the dumps hold only the schemas.
set -euo pipefail
cd "$(dirname "$0")/.."
test -f data/db/catalog.dump || { echo "data/db/*.dump not found (run scripts/db_snapshot.sh first)"; exit 1; }
docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "CREATE EXTENSION IF NOT EXISTS vector" -c "CREATE EXTENSION IF NOT EXISTS pg_trgm"'
for schema in public catalog search knowledge interactions; do
  test -f "data/db/$schema.dump" || { echo "skipping $schema (no dump)"; continue; }
  docker compose exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --no-privileges' < "data/db/$schema.dump"
  echo "restored $schema"
done
