#!/bin/bash
# Waits for PostgreSQL and Redis to be reachable, then execs the given
# command — the real uwsgi invocation for api-uwsgi, the real celery
# invocation for the three Celery programs, and from PR 4 relay-uwsgi.
#
# supervisord's priority= only orders the SIGNAL each program receives, at
# both start and stop (Supervisor.runforever sorts the process groups by
# priority; ordered_stop_groups_phase_1 walks them in reverse). It is not a
# readiness barrier, so a program that needs a store to be reachable has to
# wait for it here rather than rely on start order.
#
# Runs after setpriv, i.e. as the program's own unprivileged user, so it
# must not need root: pg_isready and a Redis PING are all it does.
set -euo pipefail

until "$PG_BINDIR/pg_isready" -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -q; do
    echo "wait-for-stores: waiting for PostgreSQL at ${POSTGRES_HOST}:${POSTGRES_PORT}..."
    sleep 1
done

# Wait-only after D15 — no flag needed, and nothing here may flush.
# Exits 1 after REDIS_WAIT_RETRIES x REDIS_WAIT_INTERVAL (default 30 x 2s),
# which under set -e fails the program and lets supervisord's
# startretries=20 back off and try again.
python3 /app/scripts/wait_for_redis.py

exec "$@"
