#!/usr/bin/env bash
# Bring up (or restore) the warm backend test container. Idempotent.
#
# The repo is bind-mounted read-only, so the container always sees the live
# working tree — no sync step, and nothing the container does can write into
# your checkout. PostgreSQL's data dir is a named volume rather than a bind
# mount: PG will not run on a macOS bind mount, and keeping it in a volume
# means a container rebuild does not repay initdb.
set -euo pipefail

CONTAINER="${DISPATCHARR_TEST_CONTAINER:-dispatcharr-testrunner}"
DB_VOLUME="${DISPATCHARR_TEST_DB_VOLUME:-dispatcharr-hookdb}"
IMAGE="${DISPATCHARR_TEST_IMAGE:-ghcr.io/dispatcharr/dispatcharr:latest}"
REPO_ROOT="${CLAUDE_HOOK_REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"

docker info >/dev/null 2>&1 || {
  echo "Docker is not running. Start Docker Desktop, then re-run this script." >&2
  exit 1
}

# MEDIA_ROOT is BASE_DIR/"media" (settings.py:434) and several m3u/epg tests
# write there. The repo mount is read-only, so give /repo/media its own tmpfs —
# which needs the mountpoint to exist. media/ is gitignored (.gitignore:15).
mkdir -p "$REPO_ROOT/media"

echo "==> (re)creating ${CONTAINER}"
docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
docker volume create "$DB_VOLUME" >/dev/null
docker run -d --name "$CONTAINER" --entrypoint sleep \
  -v "$REPO_ROOT":/repo:ro -w /repo \
  -v "$DB_VOLUME":/var/tmp/hookdb \
  --tmpfs /repo/media:rw,size=512m \
  -e PYTHONDONTWRITEBYTECODE=1 \
  "$IMAGE" infinity >/dev/null

echo "==> starting redis + postgres"
docker exec -i "$CONTAINER" bash -s <<'INNER'
set -euo pipefail
cd /repo
export DISPATCHARR_ENV=aio PUID=1000 PGID=1000
export POSTGRES_DB=dispatcharr POSTGRES_USER=dispatch POSTGRES_PASSWORD=secret POSTGRES_PORT=5432
export POSTGRES_DIR=/var/tmp/hookdb POSTGRES_HOST=/var/run/postgresql
export PATH="/dispatcharrpy/bin:$PATH"
PG_VERSION="$(ls /usr/lib/postgresql/ | sort -V | tail -n 1)"
export PG_VERSION PG_BINDIR="/usr/lib/postgresql/${PG_VERSION}/bin"

redis-server --daemonize yes --protected-mode no --bind 127.0.0.1 --port 6379 >/dev/null 2>&1 || true

. /repo/docker/init/01-user-setup.sh >/dev/null 2>&1
chown "$PUID:$PGID" "$POSTGRES_DIR"; chmod 700 "$POSTGRES_DIR"
. /repo/docker/init/02-postgres.sh >/dev/null 2>&1
prepare_pg_socket_dir
PG_START_OUT="$(su - "$POSTGRES_USER" -c "$PG_BINDIR/pg_ctl -D ${POSTGRES_DIR} start -w -t 120 -o '-c port=${POSTGRES_PORT}'" 2>&1)" || {
  echo "postgres failed to start:" >&2
  echo "$PG_START_OUT" >&2
  tail -n 40 "${POSTGRES_DIR}"/log/*.log 2>/dev/null >&2 || true
  exit 1
}
ATTEMPTS=0
until su - "$POSTGRES_USER" -c "$PG_BINDIR/pg_isready -h ${POSTGRES_HOST} -p ${POSTGRES_PORT}" >/dev/null 2>&1; do
  ATTEMPTS=$((ATTEMPTS + 1))
  if [ "$ATTEMPTS" -ge 60 ]; then
    echo "postgres started but never became ready after 60s — log tail:" >&2
    tail -n 40 "${POSTGRES_DIR}"/log/*.log 2>/dev/null >&2 || true
    exit 1
  fi
  sleep 1
done
promote_app_role  >/dev/null 2>&1 || true
ensure_app_database >/dev/null 2>&1 || true
echo "redis:    $(redis-cli ping)"
echo "postgres: $(su - dispatch -c "$PG_BINDIR/pg_isready -h /var/run/postgresql -p 5432")"
INNER
echo "==> ready"
