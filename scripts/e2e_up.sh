#!/usr/bin/env bash
# Build and run a local Dispatcharr AIO container for E2E tests.
#   ./scripts/e2e_up.sh          start (reuse existing container if present)
#   ./scripts/e2e_up.sh --reset  destroy container + volume first
set -euo pipefail

# `docker build ... .` below needs the repo root as its context, and the
# README's quick start invokes this as ./scripts/e2e_up.sh from anywhere.
cd "$(dirname "${BASH_SOURCE[0]}")/.."

NAME="${DISPATCHARR_E2E_CONTAINER:-dispatcharr-e2e}"
VOLUME="${DISPATCHARR_E2E_VOLUME:-dispatcharr-e2e-data}"
IMAGE="${DISPATCHARR_E2E_IMAGE:-dispatcharr-e2e:local}"
PORT="${DISPATCHARR_E2E_PORT:-9191}"

if [[ "${1:-}" == "--reset" ]]; then
  echo "Removing container and volume..."
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  docker volume rm "$VOLUME" >/dev/null 2>&1 || true
fi

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
  docker start "$NAME" >/dev/null
else
  # /data must be a mounted volume: the entrypoint has no fallback and
  # crashes on mktemp against a nonexistent directory.
  docker run -d --name "$NAME" \
    -p "${PORT}:9191" \
    -v "${VOLUME}:/data" \
    -e DISPATCHARR_ENV=aio \
    -e DISPATCHARR_LOG_LEVEL=info \
    "$IMAGE" >/dev/null
fi

echo -n "Waiting for the app"
for _ in $(seq 1 60); do
  if curl -sf -o /dev/null "http://localhost:${PORT}/api/accounts/initialize-superuser/"; then
    echo " — ready at http://localhost:${PORT}"
    exit 0
  fi
  echo -n "."
  sleep 5
done

echo " — never became ready. Container logs:"
docker logs "$NAME" || true
exit 1
