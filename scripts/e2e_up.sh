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

# `docker build ... .` below needs the repo root as its context, and the
# README's quick start invokes this as ./scripts/e2e_up.sh from anywhere.
cd "$(dirname "${BASH_SOURCE[0]}")/.."

NAME="${DISPATCHARR_E2E_CONTAINER:-dispatcharr-e2e}"
VOLUME="${DISPATCHARR_E2E_VOLUME:-dispatcharr-e2e-data}"
IMAGE="${DISPATCHARR_E2E_IMAGE:-dispatcharr-e2e:local}"
PORT="${DISPATCHARR_E2E_PORT:-9191}"

destroy() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  docker volume rm "$VOLUME" >/dev/null 2>&1 || true
}

# Every mode below is a whole-invocation choice, so a second argument is
# always a mistake — `--stop --reset` silently dropped the --reset, and
# `--reset --oops` silently ignored the typo, which is what the case below
# exists to prevent.
if [[ $# -gt 1 ]]; then
  echo "Expected at most one argument, got $#: $*" >&2
  sed -n '2,6p' "${BASH_SOURCE[0]}" >&2
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
    sed -n '2,6p' "${BASH_SOURCE[0]}" >&2
    exit 2
    ;;
esac

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "Building $IMAGE for the native architecture..."
  docker build -f docker/Dockerfile -t "$IMAGE" .
fi

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
    -p "127.0.0.1:${PORT}:9191" \
    -v "${VOLUME}:/data" \
    -e DISPATCHARR_ENV=aio \
    -e DISPATCHARR_LOG_LEVEL=info \
    "$IMAGE" >/dev/null
fi

echo -n "Waiting for the app"
for _ in $(seq 1 60); do
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
