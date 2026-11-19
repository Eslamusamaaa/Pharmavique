#!/usr/bin/env bash
# Restore data/db/pharmavique.dump into the local Postgres (replaces what is there).
#
#   docker compose up -d db && bash scripts/db_restore.sh
set -euo pipefail
cd "$(dirname "$0")/.."
test -f data/db/pharmavique.dump || { echo "data/db/pharmavique.dump not found"; exit 1; }
docker compose exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --no-privileges' < data/db/pharmavique.dump
echo "restored"
