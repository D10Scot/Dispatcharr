#!/usr/bin/env bash
# Build and run a local Dispatcharr AIO container for E2E tests.
#   ./scripts/e2e_up.sh          start (reuse existing container if present)
#   ./scripts/e2e_up.sh --reset  destroy container + volume, then start fresh
#   ./scripts/e2e_up.sh --stop   stop the container, keep it and its data
#   ./scripts/e2e_up.sh --down   destroy container + volume, start nothing
#
# The container is published on 127.0.0.1 only. Post-bootstrap it holds a
# superuser whose password is committed to this repository in plain text
# (e2e/setup/credentials.ts), so it must not be reachable from the LAN.
set -euo pipefail

# Resolved to an absolute path *before* the cd below, because the usage text is
# printed by sed'ing this file. `BASH_SOURCE[0]` is whatever the caller typed,
# so after the cd a relative invocation from anywhere but the repo root stops
# resolving: `cd scripts && ./e2e_up.sh --oops` printed "sed: ./e2e_up.sh: No
# such file or directory", and — `set -e` being on — exited with sed's status 1
# rather than the intended 2, having never shown the usage block those branches
# exist for.
SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"

# `docker build ... .` below needs the repo root as its context, and the
# README's quick start invokes this as ./scripts/e2e_up.sh from anywhere.
cd "$(dirname "${BASH_SOURCE[0]}")/.."

NAME="${DISPATCHARR_E2E_CONTAINER:-dispatcharr-e2e}"
VOLUME="${DISPATCHARR_E2E_VOLUME:-dispatcharr-e2e-data}"
IMAGE="${DISPATCHARR_E2E_IMAGE:-dispatcharr-e2e:local}"
PORT="${DISPATCHARR_E2E_PORT:-9191}"
# Readiness polls, 5s apart. Overridable because CI boots a cold container on a
# slower runner than a developer's laptop; .github/workflows/e2e-tests.yml
# raises it to keep the budget it had when it hand-rolled this loop.
READY_ATTEMPTS="${DISPATCHARR_E2E_READY_ATTEMPTS:-60}"

NETWORK="${DISPATCHARR_E2E_NETWORK:-dispatcharr-e2e-net}"
UPSTREAM_NAME="${DISPATCHARR_E2E_UPSTREAM_CONTAINER:-e2e-upstream}"
UPSTREAM_IMAGE="${DISPATCHARR_E2E_UPSTREAM_IMAGE:-dispatcharr-e2e-upstream:local}"
UPSTREAM_PORT="${DISPATCHARR_E2E_UPSTREAM_PORT:-9402}"

destroy() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  docker rm -f "$UPSTREAM_NAME" >/dev/null 2>&1 || true
  docker volume rm "$VOLUME" >/dev/null 2>&1 || true
  docker network rm "$NETWORK" >/dev/null 2>&1 || true
}

# Every mode below is a whole-invocation choice, so a second argument is
# always a mistake — `--stop --reset` silently dropped the --reset, and
# `--reset --oops` silently ignored the typo, which is what the case below
# exists to prevent.
if [[ $# -gt 1 ]]; then
  echo "Expected at most one argument, got $#: $*" >&2
  sed -n '2,6p' "$SELF" >&2
  exit 2
fi

case "${1:-}" in
  '')
    ;;
  --reset)
    echo "Removing container and volume..."
    destroy
    ;;
  --stop)
    # Keeps the container and its data. `./scripts/e2e_up.sh` restarts it,
    # superuser and seeded rows intact.
    docker stop "$UPSTREAM_NAME" >/dev/null 2>&1 && echo "Stopped $UPSTREAM_NAME." \
      || echo "$UPSTREAM_NAME was not running."
    docker stop "$NAME" >/dev/null 2>&1 && echo "Stopped $NAME." \
      || echo "$NAME was not running."
    exit 0
    ;;
  --down)
    echo "Removing container and volume..."
    destroy
    echo "Removed $NAME and $VOLUME."
    exit 0
    ;;
  *)
    # Without this, a typo (`--rest`) silently starts a container instead.
    echo "Unknown argument: $1" >&2
    sed -n '2,6p' "$SELF" >&2
    exit 2
    ;;
esac

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "Building $IMAGE for the native architecture..."
  docker build -f docker/Dockerfile -t "$IMAGE" .
fi

# Container-name DNS works only on a user-defined network. The default bridge
# resolves nothing, which is the entire reason this network exists.
docker network inspect "$NETWORK" >/dev/null 2>&1 || docker network create "$NETWORK" >/dev/null

if ! docker image inspect "$UPSTREAM_IMAGE" >/dev/null 2>&1; then
  echo "Building $UPSTREAM_IMAGE..."
  docker build -f e2e-upstream/Dockerfile -t "$UPSTREAM_IMAGE" e2e-upstream
fi

if docker ps --format '{{.Names}}' | grep -qx "$UPSTREAM_NAME"; then
  : # already running
elif docker ps -a --format '{{.Names}}' | grep -qx "$UPSTREAM_NAME"; then
  docker start "$UPSTREAM_NAME" >/dev/null
else
  docker run -d --name "$UPSTREAM_NAME" \
    --network "$NETWORK" \
    -p "127.0.0.1:${UPSTREAM_PORT}:8080" \
    "$UPSTREAM_IMAGE" >/dev/null
fi

# Wait for the provider before starting Dispatcharr. Dispatcharr does not
# contact it at boot, so the ordering is not strictly required — but a test
# that fails because the provider was still starting is indistinguishable
# from one that fails because the provider is broken, and this removes that
# whole class of confusion.
echo -n "Waiting for the upstream provider"
for _ in $(seq 1 30); do
  if curl -sf -o /dev/null "http://127.0.0.1:${UPSTREAM_PORT}/scenarios"; then
    echo " — ready"
    break
  fi
  echo -n "."
  sleep 1
done

if docker ps --format '{{.Names}}' | grep -qx "$NAME"; then
  : # already running
elif docker ps -a --format '{{.Names}}' | grep -qx "$NAME"; then
  # Exists but stopped (Docker Desktop restart, host reboot, OOM kill) —
  # `docker ps` alone would miss this and fall through to `docker run`,
  # which then fails with "name is already in use".
  #
  # A pre-existing container keeps the port binding it was created with:
  # one created before this script bound to 127.0.0.1 is still published on
  # every interface. `--down` and start again to pick the new binding up.
  docker start "$NAME" >/dev/null
else
  # /data must be a mounted volume: the entrypoint has no fallback and
  # crashes on mktemp against a nonexistent directory.
  #
  # 127.0.0.1 is load-bearing, not cosmetic — see the header.
  docker run -d --name "$NAME" \
    --network "$NETWORK" \
    -p "127.0.0.1:${PORT}:9191" \
    -v "${VOLUME}:/data" \
    -e DISPATCHARR_ENV=aio \
    -e DISPATCHARR_LOG_LEVEL=info \
    "$IMAGE" >/dev/null
fi

echo -n "Waiting for the app"
for _ in $(seq 1 "$READY_ATTEMPTS"); do
  if curl -sf -o /dev/null "http://127.0.0.1:${PORT}/api/accounts/initialize-superuser/"; then
    echo " — ready at http://localhost:${PORT}"
    exit 0
  fi
  echo -n "."
  sleep 5
done

echo " — never became ready. Container logs:"
docker logs "$NAME" || true
exit 1
