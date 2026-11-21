#!/usr/bin/env bash
# Save the whole database into data/db/, one file per schema, so another machine gets the same
# state without reloading, re-embedding or re-indexing. One file per schema keeps every file well
# under GitHub's 100 MB limit (knowledge holds the vectors and is the largest). `public.dump`
# holds only the migration version table (the extensions are created by db_restore.sh).
#
#   bash scripts/db_snapshot.sh            # write data/db/<schema>.dump
#   bash scripts/db_restore.sh             # on another machine, after `docker compose up -d db`
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data/db
dump() {  # dump <file name> <pg_dump selector, for example --schema=catalog>
  docker compose exec -T db sh -c "pg_dump -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" $2 --format=custom --compress=9 --no-owner --no-privileges" > "data/db/$1.dump"
}
dump public --table=public.alembic_version
for schema in catalog search knowledge interactions; do
  dump "$schema" "--schema=$schema"
done
ls -l data/db
for f in data/db/*.dump; do
  size=$(wc -c < "$f")
  if [ "$size" -gt 95000000 ]; then echo "WARNING: $f is over 95 MB; GitHub refuses files over 100 MB" >&2; fi
done
