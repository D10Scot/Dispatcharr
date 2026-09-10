#!/usr/bin/env bash
# Reproduce the CI coverage gate locally: one container per Django test label, the
# shape backend-tests.yml's matrix uses and the shape the isolation probe measured.
#
# The in-container script cannot do this by itself -- it runs INSIDE one container --
# so the per-label split lives here and the combine lives back in the script, over
# --combine-from, which preserves the shape-stamp check across the boundary.
#
# The block-level determinism this shape buys is real (64/64 in 10/10 isolated rounds
# against 5/11 shared, p=0.0124) and the TOTAL determinism it buys is NOT: spread 44
# isolated against 47 shared. Do not read this script as a variance fix.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${COVERAGE_ISOLATED_OUT:-/tmp/dispatcharr-coverage-isolated}"
PREFIX="${COVERAGE_ISOLATED_PREFIX:-dispatcharr-testrunner-2a7}"

# .claude/hooks/start-test-container.sh does not bake DJANGO_SECRET_KEY into the
# container's own environment -- every docker exec must carry it, or
# rest_framework_simplejwt's own settings import dies with "The SECRET_KEY setting
# must not be empty." before a single test runs. Override with your own value if the
# container was started with a different one.
DJANGO_SECRET_KEY_FOR_EXEC="${DJANGO_SECRET_KEY:-hook-test-secret}"

declare -a PAIRS=(
  "proxy:apps.proxy.tests"
  "liveproxy:apps.proxy.live_proxy.tests"
  "channels:apps.channels.tests"
)

rm -rf "$OUT"; mkdir -p "$OUT"
for pair in "${PAIRS[@]}"; do
  suffix="${pair%%:*}"; label="${pair#*:}"
  c="${PREFIX}-${suffix}"
  docker exec "$c" bash -lc "export PATH=/dispatcharrpy/bin:\$PATH; export DJANGO_SECRET_KEY=$DJANGO_SECRET_KEY_FOR_EXEC; cd /repo && \
    rm -rf /tmp/rd && COVERAGE_LIVE_PATH_DATA_DIR=/tmp/rd \
    bash scripts/coverage_live_path.sh --label ${label}"
  docker cp "${c}:/tmp/rd" "${OUT}/${suffix}"
done

# Combine and report in any one of them; the stamps travel with the data.
#
# The destination must be removed first: docker cp does not overwrite an existing
# directory's contents, it copies $OUT INSIDE it (/tmp/combined/dispatcharr-coverage-isolated/...)
# -- so a second run without this would leave the PREVIOUS run's .coverage.* files
# sitting alongside the new ones (unique per-process names, so nothing collides)
# while the .shape stamps (deterministic per-label names) get overwritten, and
# report() then refuses with "N data file(s) but M shape stamp(s)" for a reason that
# has nothing to do with the run just taken.
docker exec "${PREFIX}-proxy" rm -rf /tmp/combined
docker cp "$OUT" "${PREFIX}-proxy:/tmp/combined"
# docker exec starts a fresh shell in the container; nothing exported on the host
# reaches it unless named explicitly (same trap as DJANGO_SECRET_KEY above) -- so
# --write-floor's COVERAGE_LIVE_PATH_ALLOW_REGRESSION and COVERAGE_LIVE_PATH_RUNS
# overrides must be forwarded by name too, or a caller who sets them on the host
# gets silently ignored on the container side.
docker exec "${PREFIX}-proxy" bash -lc "export PATH=/dispatcharrpy/bin:\$PATH; export DJANGO_SECRET_KEY=$DJANGO_SECRET_KEY_FOR_EXEC; \
  export COVERAGE_LIVE_PATH_ALLOW_REGRESSION='${COVERAGE_LIVE_PATH_ALLOW_REGRESSION:-}'; \
  export COVERAGE_LIVE_PATH_RUNS='${COVERAGE_LIVE_PATH_RUNS:-0}'; cd /repo && \
  bash scripts/coverage_live_path.sh ${1:---report} /tmp/combined"
