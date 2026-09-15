#!/bin/sh
# The container HEALTHCHECK. Spec D6 pairs the Go relay's /healthz with one,
# and 2c-1 deliberately did not add it -- "a probe wired to a /readyz that is
# a static 200 would report healthy through every real failure the probe
# exists to catch."
#
# ROLE-AWARE, because the image runs four different program sets. relay-go is
# started by the `all`, `all-dev` and `relay` rungs only (see
# docker/supervisord/*.conf); an `api` or `worker` container has no relay-go
# to probe, and probing one anyway would mark every such container unhealthy
# for ever.
#
# The role is read from the file entrypoint.sh writes AFTER it resolves the
# default, not from the environment: HEALTHCHECK runs as a fresh process with
# the container's env, which carries DISPATCHARR_ROLE only when the operator
# set it explicitly. The env var is the fallback, and an unreadable role is
# treated as "not a relay" -- a healthcheck must never fail because it could
# not work out what to check.
set -eu

ROLE_FILE=/run/dispatcharr-role
if [ -r "$ROLE_FILE" ]; then
    ROLE="$(cat "$ROLE_FILE")"
else
    ROLE="${DISPATCHARR_ROLE:-}"
fi

case "$ROLE" in
    all | relay) ;;
    *) exit 0 ;;
esac

PORT="${DISPATCHARR_RELAY_GO_PORT:-5658}"
exec curl -fsS --max-time 3 -o /dev/null "http://127.0.0.1:${PORT}/healthz"
