#!/usr/bin/env bash
# Build and run a local Dispatcharr AIO container for E2E tests.
#   ./scripts/e2e_up.sh             start (reuse existing container if present)
#   ./scripts/e2e_up.sh --reset     destroy container + volume, then start fresh
#   ./scripts/e2e_up.sh --recreate  destroy the container, keep the volume, start fresh
#   ./scripts/e2e_up.sh --stop      stop the container, keep it and its data
#   ./scripts/e2e_up.sh --down      destroy container + volume, start nothing
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
# Only takes effect on an actual build -- the `docker image inspect` guard
# below skips it whenever $IMAGE already exists, same caveat as $IMAGE
# itself. docker/Dockerfile's REPO_OWNER build-arg resolves which :base to
# pull from, and its own default (dispatcharr, i.e. upstream) is wrong for
# this fork: upstream's :base has no supervisord once Phase 1 PR 1 lands,
# and never will.
REPO_OWNER="${DISPATCHARR_E2E_REPO_OWNER:-d10scot}"
PORT="${DISPATCHARR_E2E_PORT:-9191}"
# Readiness polls, 5s apart. Overridable because CI boots a cold container on a
# slower runner than a developer's laptop; .github/workflows/e2e-tests.yml
# raises it to keep the budget it had when it hand-rolled this loop.
READY_ATTEMPTS="${DISPATCHARR_E2E_READY_ATTEMPTS:-60}"

NETWORK="${DISPATCHARR_E2E_NETWORK:-dispatcharr-e2e-net}"
# _UPSTREAM_CONTAINER and _UPSTREAM_PORT start the provider under another
# name and port. The provider is told its name (UPSTREAM_INTERNAL_ORIGIN,
# below), so its playlists point at a host this stack's network resolves.
# Playwright must be told too: E2E_UPSTREAM_CONTROL_URL and
# E2E_UPSTREAM_INTERNAL_URL (e2e/fixtures/upstream.ts). check_scope refuses
# a mismatch between the two sides when both are set.
UPSTREAM_NAME="${DISPATCHARR_E2E_UPSTREAM_CONTAINER:-e2e-upstream}"
UPSTREAM_IMAGE="${DISPATCHARR_E2E_UPSTREAM_IMAGE:-dispatcharr-e2e-upstream:local}"
UPSTREAM_PORT="${DISPATCHARR_E2E_UPSTREAM_PORT:-9402}"

# One network per line. A Go template over the map's keys, never a grep of
# {{json .NetworkSettings.Networks}}: each real endpoint object carries a
# dozen nested keys, and a line grep for names matches them (#261's review).
# A stopped container still lists its attachments. A missing one exits 1
# with `no such object` on stderr and one blank line on stdout, which the
# sed strips, so it yields no names here.
container_networks() {
  docker inspect -f '{{range $n, $_ := .NetworkSettings.Networks}}{{println $n}}{{end}}' \
    "$1" 2>/dev/null | sed '/^$/d' || true
}

# The provider's networks other than this stack's. Non-empty means another
# stack still uses it (#168). Captured, not piped into grep -q: under
# pipefail a grep -q that exits early can SIGPIPE the writer and report 141.
upstream_other_networks() {
  container_networks "$UPSTREAM_NAME" \
    | grep -vxF -e "$NETWORK" -e bridge -e host -e none || true
}

# A container created before $NETWORK existed (or created with `--network`
# pointed elsewhere) gets reused as-is by the branches below, and
# container-name DNS then silently fails until someone runs `--down` — a
# real hour-waster on a dev machine that already had a same-named container.
# Attach it to the network on every start rather than only at `docker run`.
ensure_on_network() {
  local container="$1" nets
  nets="$(container_networks "$container")"
  if ! printf '%s\n' "$nets" | grep -qxF "$NETWORK"; then
    docker network connect "$NETWORK" "$container" >/dev/null 2>&1 || true
  fi
}

# A provider still attached to another stack's network is shared, not ours
# alone (#168): removing it here would break every sibling stack. Disconnect
# it from this stack's network and leave it running instead; only remove it
# outright when this stack was its last user.
destroy() {
  local others
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  others="$(upstream_other_networks)"
  if [[ -n "$others" ]]; then
    echo "Leaving $UPSTREAM_NAME running for:" $others
    docker network disconnect "$NETWORK" "$UPSTREAM_NAME" >/dev/null 2>&1 || true
  else
    docker rm -f "$UPSTREAM_NAME" >/dev/null 2>&1 || true
  fi
  docker volume rm "$VOLUME" >/dev/null 2>&1 || true
  docker network rm "$NETWORK" >/dev/null 2>&1 || true
}

# Every mode below is a whole-invocation choice, so a second argument is
# always a mistake — `--stop --reset` silently dropped the --reset, and
# `--reset --oops` silently ignored the typo, which is what the case below
# exists to prevent.
if [[ $# -gt 1 ]]; then
  echo "Expected at most one argument, got $#: $*" >&2
  sed -n '2,7p' "$SELF" >&2
  exit 2
fi

# A second stack is safe only if it is scoped completely (#187). Every
# variable below defaults independently, so a half-exported shell used to act
# on a mix of a private stack and the shared one. Strings, not arrays: under
# set -u, bash < 4.4 (macOS /bin/bash is 3.2) treats an empty "${a[@]}" as
# unbound.
check_scope() {
  local v set_names="" missing="" problems=""
  for v in DISPATCHARR_E2E_CONTAINER DISPATCHARR_E2E_VOLUME DISPATCHARR_E2E_NETWORK; do
    if [[ -n "${!v:-}" ]]; then set_names+=" $v"; else missing+=" $v"; fi
  done
  if [[ -n "$set_names" && -n "$missing" ]]; then
    problems+="  set:${set_names}; also required:${missing}"$'\n'
  fi
  if [[ -n "$set_names" && -z "${DISPATCHARR_E2E_PORT:-}" ]]; then
    problems+="  a scoped stack needs DISPATCHARR_E2E_PORT too"$'\n'
  fi
  local up_c=0 up_p=0
  [[ -n "${DISPATCHARR_E2E_UPSTREAM_CONTAINER:-}" ]] && up_c=1
  [[ -n "${DISPATCHARR_E2E_UPSTREAM_PORT:-}" ]] && up_p=1
  if (( up_c != up_p )); then
    problems+="  DISPATCHARR_E2E_UPSTREAM_CONTAINER and _UPSTREAM_PORT go together"$'\n'
  fi
  # The reverse of the check above: a private provider with no scoped stack
  # is the #187 failure class in the other direction. Without this, setting
  # only the two upstream variables leaves every stack variable defaulted to
  # the shared app container, and --down/--reset then destroy it and its
  # volume -- not the provider's business to protect, but a private provider
  # is only ever wanted alongside a private stack, so require one.
  if (( up_c == 1 || up_p == 1 )) && [[ -z "$set_names" ]]; then
    problems+="  a private provider needs a scoped stack: set DISPATCHARR_E2E_CONTAINER, _VOLUME, _NETWORK and _PORT"$'\n'
  fi
  local host port
  if [[ -n "${E2E_UPSTREAM_INTERNAL_URL:-}" ]]; then
    host="${E2E_UPSTREAM_INTERNAL_URL#*://}"; host="${host%%[:/]*}"
    [[ "$host" == "$UPSTREAM_NAME" ]] ||
      problems+="  E2E_UPSTREAM_INTERNAL_URL names '$host' but the provider is '$UPSTREAM_NAME'"$'\n'
  fi
  if [[ -n "${E2E_UPSTREAM_CONTROL_URL:-}" ]]; then
    port="${E2E_UPSTREAM_CONTROL_URL##*:}"; port="${port%%/*}"
    [[ "$port" == "$UPSTREAM_PORT" ]] ||
      problems+="  E2E_UPSTREAM_CONTROL_URL uses port '$port' but the provider publishes '$UPSTREAM_PORT'"$'\n'
  fi
  if [[ -n "$problems" ]]; then
    echo "Refusing a partially scoped stack (see e2e/README.md, 'Running a second stack'):" >&2
    printf '%s' "$problems" >&2
    exit 2
  fi
}
check_scope

case "${1:-}" in
  '')
    ;;
  --reset)
    echo "Removing container and volume..."
    destroy
    ;;
  --recreate)
    # New container, same volume. No other mode expresses an upgrade: --stop
    # keeps the container and therefore the image snapshot it was created
    # from, and --reset/--down destroy the volume the upgrade is meant to
    # carry forward.
    #
    # The volume, the network and the provider container are deliberately
    # left standing — none of them is what is being replaced, and destroy()
    # would take the provider down with them.
    #
    # Load-bearing, and the reason this mode is not optional: the app-container
    # reuse branches at the bottom of this script key on container *name*
    # only, never on image id (unlike the provider, which is recreated when
    # UPSTREAM_IMAGE_ID moves). Without this, setting DISPATCHARR_E2E_IMAGE
    # and re-running silently keeps serving the old image.
    #
    # `docker stop` before `rm -f`, not `rm -f` alone. `rm -f` is SIGKILL, so
    # none of `entrypoint.sh`'s TERM/INT trap runs — no `pg_ctl stop -m
    # immediate`, no cleanup — and the "upgrade" would then start from a
    # crash-recovered volume. PostgreSQL is crash-safe, so this is about the
    # test being representative of a real upgrade rather than about
    # corruption; `--stop` above already goes through SIGTERM, and the two
    # modes disagreeing on how a container goes down is the kind of difference
    # that later explains an unreproducible result.
    echo "Removing container $NAME (keeping volume $VOLUME)..."
    docker stop "$NAME" >/dev/null 2>&1 || true
    docker rm -f "$NAME" >/dev/null 2>&1 || true
    ;;
  --stop)
    # Keeps the container and its data. `./scripts/e2e_up.sh` restarts it,
    # superuser and seeded rows intact.
    if [[ -n "$(upstream_other_networks)" ]]; then
      echo "Leaving $UPSTREAM_NAME running: another stack's network is attached to it."
    else
      docker stop "$UPSTREAM_NAME" >/dev/null 2>&1 && echo "Stopped $UPSTREAM_NAME." \
        || echo "$UPSTREAM_NAME was not running."
    fi
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
    sed -n '2,7p' "$SELF" >&2
    exit 2
    ;;
esac

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "Building $IMAGE for the native architecture..."
  docker build -f docker/Dockerfile --build-arg REPO_OWNER="$REPO_OWNER" -t "$IMAGE" .
fi

# Container-name DNS works only on a user-defined network. The default bridge
# resolves nothing, which is the entire reason this network exists.
docker network inspect "$NETWORK" >/dev/null 2>&1 || docker network create "$NETWORK" >/dev/null

# Unlike the 3.6 GB AIO image above, this one is small and builds in
# seconds, so it is rebuilt on every invocation rather than only when
# absent. A build-if-absent provider image went stale silently — a routes
# change in e2e-upstream/src/ never reached a container built from the
# cached tag, surfacing as unexplained 404s with no indication the image
# was the problem.
#
# CI opts out with DISPATCHARR_E2E_SKIP_UPSTREAM_BUILD: the `build` job
# already built and saved this image alongside the AIO one specifically so
# every consumer tests the same artifact (the same reason the AIO image
# below is build-if-absent rather than always rebuilt here). Rebuilding it
# again per test job would mean up to four different provider images in one
# run — ffmpeg is deliberately unpinned, so those builds are not guaranteed
# to produce the same asset — and the image under test would no longer be
# the one the artifact carried.
if [[ -n "${DISPATCHARR_E2E_SKIP_UPSTREAM_BUILD:-}" ]]; then
  echo "Skipping $UPSTREAM_IMAGE build (DISPATCHARR_E2E_SKIP_UPSTREAM_BUILD set) — using the loaded artifact."
else
  echo "Building $UPSTREAM_IMAGE..."
  # --provenance=false: buildx's default provenance attestation embeds a
  # build timestamp, so two back-to-back builds with an entirely cache-hit
  # Dockerfile still get different image ids — which would defeat the id
  # comparison below on every single invocation, not just the ones that
  # actually changed something. This is a disposable local dev image, not a
  # distributed artifact, so there is nothing here for provenance to attest
  # to.
  docker build --provenance=false -f e2e-upstream/Dockerfile -t "$UPSTREAM_IMAGE" e2e-upstream
fi

# Rebuilding the tag above is not enough on its own: an already-created
# container (running or stopped) keeps the image snapshot it was created
# from, so `docker start`-ing it or leaving it running serves the old
# image regardless of what the tag now points at. Recreate the container
# whenever the tag has moved, so the rebuild actually reaches it — this is
# the most common dev loop of all (edit provider code, re-run the script
# with the stack already up). Only when the ids match is the running
# container left alone, which keeps the fast path when nothing changed.
# The provider has no volume, so recreating it costs nothing but a restart.
UPSTREAM_IMAGE_ID="$(docker image inspect -f '{{.Id}}' "$UPSTREAM_IMAGE")"
# A recreated provider is shared state, same as destroy() above: record every
# network besides ours before it is removed, so it can be reattached to every
# stack it served rather than only to this one (#168). Their scenarios are
# lost regardless — the registry is an in-memory Map — hence the warning.
PRIOR_NETWORKS=""
if EXISTING_IMAGE_ID="$(docker inspect -f '{{.Image}}' "$UPSTREAM_NAME" 2>/dev/null)" \
    && [[ "$EXISTING_IMAGE_ID" != "$UPSTREAM_IMAGE_ID" ]]; then
  PRIOR_NETWORKS="$(upstream_other_networks)"
  echo "Recreating $UPSTREAM_NAME: the image moved."
  if [[ -n "$PRIOR_NETWORKS" ]]; then
    echo "  Other stacks use it (" $PRIOR_NETWORKS "). They keep the provider but lose every scenario they had created."
  fi
  docker rm -f "$UPSTREAM_NAME" >/dev/null
fi

if docker ps --format '{{.Names}}' | grep -qx "$UPSTREAM_NAME"; then
  : # already running, same image
elif docker ps -a --format '{{.Names}}' | grep -qx "$UPSTREAM_NAME"; then
  docker start "$UPSTREAM_NAME" >/dev/null
else
  # -e UPSTREAM_INTERNAL_ORIGIN: told its own name, so a renamed provider's
  # playlists point at a host this stack's network can resolve (the #168
  # comment) instead of the default's literal `e2e-upstream`. A provider
  # created before this change keeps its old environment until it is
  # recreated -- run with --down or --recreate to pick it up.
  docker run -d --name "$UPSTREAM_NAME" \
    --network "$NETWORK" \
    -p "127.0.0.1:${UPSTREAM_PORT}:8080" \
    -e UPSTREAM_INTERNAL_ORIGIN="http://${UPSTREAM_NAME}:8080" \
    "$UPSTREAM_IMAGE" >/dev/null
fi
ensure_on_network "$UPSTREAM_NAME"
for n in $PRIOR_NETWORKS; do
  docker network inspect "$n" >/dev/null 2>&1 && docker network connect "$n" "$UPSTREAM_NAME" >/dev/null 2>&1 || true
done

# Wait for the provider before starting Dispatcharr. Dispatcharr does not
# contact it at boot, so the ordering is not strictly required — but it
# removes the ordering hazard: without this, a test that fails because the
# provider was still starting would be indistinguishable from one that fails
# because the provider is broken. It does not, on its own, make a
# crash-looping provider visible — that's what the exit below is for.
echo -n "Waiting for the upstream provider"
for _ in $(seq 1 30); do
  if curl -sf -o /dev/null "http://127.0.0.1:${UPSTREAM_PORT}/scenarios"; then
    echo " — ready"
    break
  fi
  # Same reasoning as the app loop below: a container that has exited will
  # never answer, so say so now rather than after the full budget.
  if [[ "$(docker inspect -f '{{.State.Running}}' "$UPSTREAM_NAME" 2>/dev/null)" != "true" ]]; then
    echo " — container exited. Logs:"
    docker logs "$UPSTREAM_NAME" 2>&1 | tail -n 100 || true
    exit 1
  fi
  echo -n "."
  sleep 1
done

if ! curl -sf -o /dev/null "http://127.0.0.1:${UPSTREAM_PORT}/scenarios"; then
  echo " — never became ready. Container logs:"
  docker logs "$UPSTREAM_NAME" || true
  exit 1
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
  # get_client_ip() (dispatcharr/utils.py) trusts only loopback peers by
  # default (#182): the peer nginx sees on a uwsgi_pass location is the
  # e2e network's own bridge gateway, not the client, so
  # network-acl.spec.ts's spoofed-X-Real-IP tests need that gateway trusted
  # explicitly — exactly what a deployment behind a reverse proxy does.
  GATEWAY="$(docker network inspect "$NETWORK" -f '{{(index .IPAM.Config 0).Gateway}}')"
  if [[ -z "$GATEWAY" ]]; then
    echo "Could not resolve the gateway address of network '$NETWORK'." >&2
    exit 1
  fi

  # /data must be a mounted volume: the entrypoint has no fallback and
  # crashes on mktemp against a nonexistent directory.
  #
  # 127.0.0.1 is load-bearing, not cosmetic — see the header.
  #
  # A container created before this change keeps its old environment; run
  # with --down or --recreate to pick up DISPATCHARR_TRUSTED_PROXIES.
  docker run -d --name "$NAME" \
    --network "$NETWORK" \
    -p "127.0.0.1:${PORT}:9191" \
    -v "${VOLUME}:/data" \
    -e DISPATCHARR_ENV=aio \
    -e DISPATCHARR_LOG_LEVEL=info \
    -e DISPATCHARR_TRUSTED_PROXIES="$GATEWAY" \
    "$IMAGE" >/dev/null
fi
ensure_on_network "$NAME"

echo -n "Waiting for the app"
for _ in $(seq 1 "$READY_ATTEMPTS"); do
  if curl -sf -o /dev/null "http://127.0.0.1:${PORT}/api/accounts/initialize-superuser/"; then
    echo " — ready at http://localhost:${PORT}"
    exit 0
  fi
  # A crashed container never answers, and polling it for the full budget is
  # the difference between a 5-second failure with a traceback and a silent
  # ten-minute wall of dots. `docker/entrypoint.sh` runs under `set -e` and
  # does `manage.py migrate --noinput` before uWSGI starts, so a migration that
  # fails on a carried-forward volume exits the container immediately — and
  # there is no `--restart` policy, so it stays exited. That is exactly the
  # failure `--recreate` exists to surface, so noticing it fast matters most
  # here.
  if [[ "$(docker inspect -f '{{.State.Running}}' "$NAME" 2>/dev/null)" != "true" ]]; then
    echo " — container exited. Logs:"
    docker logs "$NAME" 2>&1 | tail -n 100 || true
    exit 1
  fi
  echo -n "."
  sleep 5
done

echo " — never became ready. Container logs:"
docker logs "$NAME" || true
exit 1
