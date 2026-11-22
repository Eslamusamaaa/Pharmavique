#!/usr/bin/env bash
# Copy the data of the local development database into a REMOTE Postgres such as Neon, table by
# table and in small pieces, with a retry per piece. A long single transfer to a remote host over
# the internet is dropped now and then ("SSL error: unexpected eof"); a piece of a few megabytes
# is not, and a piece that fails is simply sent again (each piece is one statement, all or nothing).
#
# Run the migrations on the remote first (`uv run alembic upgrade heads` with PHARMAVIQUE_DATABASE_URL
# pointing at it): the migrations make the tables and indexes, this script only fills them. It does
# not touch `public.alembic_version` and copies nothing of the identity, watchlist and analytics
# schemas (people's data stays where it is; analytics is rebuilt with `pharmavique analytics-rebuild`).
#
#   export NEON_DIRECT_URL='postgresql://user:password@ep-xxx.eu-central-1.aws.neon.tech/neondb?sslmode=require'
#   docker compose up -d db && bash scripts/db_copy_remote.sh
#
# NEON_DIRECT_URL is the DIRECT (not pooled) address. It is passed to the container through its
# environment and never printed. The rows these schemas hold on the remote are emptied first, so
# running the script twice gives the same result.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${NEON_DIRECT_URL:?set NEON_DIRECT_URL to the direct connection address of the remote database}"
case "$NEON_DIRECT_URL" in
  *-pooler.*) echo "NEON_DIRECT_URL is a pooled address (-pooler); use the direct one" >&2; exit 1 ;;
esac
SCHEMAS="'catalog','search','knowledge','interactions'"
CHUNK_BYTES="${CHUNK_BYTES:-3000000}"
RETRIES="${RETRIES:-5}"

local_sql() { docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -v ON_ERROR_STOP=1 -c "$1"' sh "$1"; }
remote_sql() { docker compose exec -T -e REMOTE_URL="$NEON_DIRECT_URL" db sh -c 'psql "$REMOTE_URL" -At -v ON_ERROR_STOP=1 -c "$1"' sh "$1"; }

remote_sql "CREATE EXTENSION IF NOT EXISTS vector" >/dev/null
remote_sql "CREATE EXTENSION IF NOT EXISTS pg_trgm" >/dev/null

tables=$(local_sql "select table_schema || '.' || table_name from information_schema.tables where table_schema in ($SCHEMAS) and table_type = 'BASE TABLE' order by 1")
for table in $tables; do
  remote_sql "TRUNCATE TABLE $table CASCADE" >/dev/null
done

for table in $tables; do
  rows=$(local_sql "select count(*) from $table")
  [ "$rows" -eq 0 ] && { echo "$table: empty"; continue; }
  bytes=$(local_sql "select pg_relation_size('$table'::regclass) + coalesce(pg_total_relation_size(reltoastrelid), 0) from pg_class where oid = '$table'::regclass")
  per_row=$(( bytes / rows + 1 ))
  step=$(( CHUNK_BYTES / per_row ))
  [ "$step" -lt 100 ] && step=100
  offset=0
  while [ "$offset" -lt "$rows" ]; do
    for attempt in $(seq 1 "$RETRIES"); do
      if docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -q -c "$1"' sh \
           "\copy (select * from $table order by ctid offset $offset limit $step) to stdout" \
         | docker compose exec -T -e REMOTE_URL="$NEON_DIRECT_URL" db sh -c 'psql "$REMOTE_URL" -q -v ON_ERROR_STOP=1 -c "$1"' sh \
           "\copy $table from stdin"; then
        break
      fi
      [ "$attempt" -eq "$RETRIES" ] && { echo "$table: piece at row $offset failed $RETRIES times" >&2; exit 1; }
      sleep 3
    done
    offset=$(( offset + step ))
  done
  echo "$table: $rows rows copied"
done

echo "--- row counts, local then remote"
local_sql "select table_schema || '.' || table_name from information_schema.tables where table_schema in ($SCHEMAS) and table_type = 'BASE TABLE' order by 1" >/dev/null
for table in $tables; do
  echo "$table $(local_sql "select count(*) from $table") $(remote_sql "select count(*) from $table")"
done
