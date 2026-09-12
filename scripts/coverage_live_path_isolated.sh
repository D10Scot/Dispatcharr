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

# A failing label must not delete the whole round. Under the previous
# `set -e` loop a single failing test in `liveproxy` -- the SECOND of three
# -- aborted before `channels` ran, before either docker cp, and before the
# combine: no measurement at all, and nothing saying which label died.
# Issue #266. The shape below is the sibling script's own (its no-argument
# path, coverage_live_path.sh:579-605): run every label, say which failed,
# say it BEFORE the figures, and never emit a floor-eligible number from an
# incomplete round.
declare -a FAILED=()
declare -a STATUS=()
for pair in "${PAIRS[@]}"; do
  suffix="${pair%%:*}"; label="${pair#*:}"
  c="${PREFIX}-${suffix}"
  rc=0
  docker exec "$c" bash -lc "export PATH=/dispatcharrpy/bin:\$PATH; export DJANGO_SECRET_KEY=$DJANGO_SECRET_KEY_FOR_EXEC; cd /repo && \
    rm -rf /tmp/rd && COVERAGE_LIVE_PATH_DATA_DIR=/tmp/rd \
    bash scripts/coverage_live_path.sh --label ${label}" || rc=$?
  STATUS+=("${suffix}=${rc}")
  if [ "$rc" -ne 0 ]; then
    FAILED+=("$label")
    # Still copy: a label that failed after tuning has already executed most
    # of its lines, so the partial data dir is useful for per-file
    # ATTRIBUTION even though its TOTAL is not quotable. If the label died
    # before coverage wrote anything, this cp fails and is not fatal.
    docker cp "${c}:/tmp/rd" "${OUT}/${suffix}" || true
  else
    docker cp "${c}:/tmp/rd" "${OUT}/${suffix}"
  fi
done

echo "coverage_live_path_isolated: labels: ${STATUS[*]}" >&2

if [ "${#FAILED[@]}" -gt 0 ]; then
  echo "coverage_live_path_isolated: label(s) failed: ${FAILED[*]}" >&2
  echo "coverage_live_path_isolated: THE FIGURES BELOW ARE INVALID -- a failed" >&2
  echo "coverage_live_path_isolated: label under-runs the suite and INFLATES" >&2
  echo "coverage_live_path_isolated: 'missing' the way a regression moves." >&2
  echo "coverage_live_path_isolated: use them for per-file attribution if you" >&2
  echo "coverage_live_path_isolated: must; never quote the total, never write a" >&2
  echo "coverage_live_path_isolated: floor from them. Discard the round." >&2
  echo "coverage_live_path_isolated: known flakes (#259): grep the label's log" >&2
  echo "coverage_live_path_isolated: for 'never observed the lead at all' or" >&2
  echo "coverage_live_path_isolated: 'too few distinct speeds' before" >&2
  echo "coverage_live_path_isolated: investigating coverage." >&2
  case "${1:---report}" in
    --write-floor|--gate)
      echo "coverage_live_path_isolated: refusing ${1} on an incomplete round." >&2
      exit 1
      ;;
  esac
fi

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
report_rc=0
docker exec "${PREFIX}-proxy" bash -lc "export PATH=/dispatcharrpy/bin:\$PATH; export DJANGO_SECRET_KEY=$DJANGO_SECRET_KEY_FOR_EXEC; \
  export COVERAGE_LIVE_PATH_ALLOW_REGRESSION='${COVERAGE_LIVE_PATH_ALLOW_REGRESSION:-}'; \
  export COVERAGE_LIVE_PATH_RUNS='${COVERAGE_LIVE_PATH_RUNS:-0}'; cd /repo && \
  bash scripts/coverage_live_path.sh ${1:---report} /tmp/combined" || report_rc=$?

if [ "${#FAILED[@]}" -gt 0 ]; then exit 1; fi
exit "$report_rc"
