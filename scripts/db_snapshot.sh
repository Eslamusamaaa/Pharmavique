#!/usr/bin/env bash
# Save the whole database (every context's schema, with search terms and knowledge vectors) into
# data/db/pharmavique.dump, so another machine gets the same state without reloading or re-embedding.
#
#   bash scripts/db_snapshot.sh            # write data/db/pharmavique.dump
#   bash scripts/db_restore.sh             # on another machine, after `docker compose up -d db`
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data/db
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --compress=9 --no-owner --no-privileges' > data/db/pharmavique.dump
ls -l data/db/pharmavique.dump
