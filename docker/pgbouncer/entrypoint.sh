#!/bin/sh
# Writes pgbouncer.ini and the user list from environment variables, then runs PgBouncer.
# Transaction pooling with protocol-level prepared statements (PgBouncer 1.21+), which asyncpg uses.
set -eu
: "${DB_HOST:?set DB_HOST}"
: "${DB_USER:?set DB_USER}"
: "${DB_PASSWORD:?set DB_PASSWORD}"
: "${DB_NAME:?set DB_NAME}"

cat > /etc/pgbouncer/pgbouncer.ini <<INI
[databases]
${DB_NAME} = host=${DB_HOST} port=${DB_PORT:-5432} dbname=${DB_NAME}

[pgbouncer]
listen_addr = 0.0.0.0
listen_port = 6432
auth_type = scram-sha-256
auth_file = /etc/pgbouncer/userlist.txt
pool_mode = transaction
max_prepared_statements = ${MAX_PREPARED_STATEMENTS:-200}
default_pool_size = ${DEFAULT_POOL_SIZE:-20}
max_client_conn = ${MAX_CLIENT_CONN:-1000}
server_tls_sslmode = ${SERVER_TLS_SSLMODE:-prefer}
ignore_startup_parameters = extra_float_digits
admin_users = ${DB_USER}
unix_socket_dir =
INI

# Plain password in a file only this container can read; PgBouncer hashes it for SCRAM.
printf '"%s" "%s"\n' "$DB_USER" "$DB_PASSWORD" > /etc/pgbouncer/userlist.txt
chmod 600 /etc/pgbouncer/userlist.txt

exec pgbouncer /etc/pgbouncer/pgbouncer.ini
