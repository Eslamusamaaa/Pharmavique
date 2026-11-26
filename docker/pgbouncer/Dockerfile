# PgBouncer in front of Postgres for the self-hosted (Docker) deployment. Neon already pools on its
# own `-pooler` address, so this is only used after a move off Neon (docs/RUNBOOK.md).
FROM alpine:3.21

RUN apk add --no-cache pgbouncer postgresql17-client \
    && adduser -D -H -u 10002 pgbouncer \
    && mkdir -p /etc/pgbouncer /var/run/pgbouncer \
    && chown -R pgbouncer:pgbouncer /etc/pgbouncer /var/run/pgbouncer

COPY --chmod=0755 entrypoint.sh /entrypoint.sh

USER pgbouncer
EXPOSE 6432
HEALTHCHECK --interval=10s --timeout=3s --retries=5 CMD pg_isready -h 127.0.0.1 -p 6432 || exit 1
ENTRYPOINT ["/entrypoint.sh"]
