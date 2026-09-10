#!/usr/bin/env bash
# Gate 2's measurement (Phase 2 spec, § Stage 2a > Gate 2): statement coverage
# over apps/proxy/live_proxy/** plus the ten Phase 1 boundary modules.
#
#   scripts/coverage_live_path.sh                  run all three labels, then report
#   scripts/coverage_live_path.sh --label <label>  run one label, leave its data file
#   scripts/coverage_live_path.sh --report         combine and report what is there
#
# Postgres and Redis must already be up. In CI that means running through
# scripts/ci_bootstrap_backend.sh with CI_BACKEND_RUNNER; locally it means the
# hook container (.claude/hooks/start-test-container.sh).
#
# THE MEASUREMENT SHAPE IS PART OF THE NUMBER, and this script enforces it.
# One process per test label is what backend-tests.yml runs. A single process
# running the same labels reports about 68 FEWER missed statements: the relay's
# daemon threads (server.py's cleanup loop and event listener, ClientManager's
# heartbeat) keep looping while unrelated tests run, and coverage credits lines
# no test asserts. A floor computed from that shape could never be met by the
# per-label pipeline meant to enforce it, so this script refuses to report over
# any data file it did not stamp itself -- and 2a-7's floor comparison hangs off
# the same check, so a floor can never be written or compared against a foreign
# shape either. Within this shape the measurement is exactly reproducible: the
# spec's +/-70-statement thread-timing band applies BETWEEN shapes, not between
# runs of this one, so this script has no tolerance and needs none.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# The three labels whose tests reach the modules in the denominator. Hard-coded
# rather than derived: the spec names exactly these, and a 16-label control run
# at a948cd8a moved live_proxy by zero statements.
LABELS=(apps.proxy.tests apps.proxy.live_proxy.tests apps.channels.tests)

export COVERAGE_LIVE_PATH_DATA_DIR="${COVERAGE_LIVE_PATH_DATA_DIR:-/tmp/dispatcharr-coverage-live-path}"
RC="$REPO_ROOT/scripts/coverage_live_path.coveragerc"
SHAPE_DIR="$COVERAGE_LIVE_PATH_DATA_DIR/shape"
# Bumped whenever the rcfile's denominator changes, so a stale data directory
# from before the change is refused instead of silently combined.
SHAPE_ID="per-label/v1"

run_label() {
  local label="$1"
  mkdir -p "$SHAPE_DIR"
  redis-cli -p "${REDIS_PORT:-6379}" flushall >/dev/null 2>&1 || true
  python -m coverage run --rcfile="$RC" manage.py test --keepdb "$label" -v1
  local rc=$?
  # Stamp AFTER the run: a label that died before coverage wrote its data file
  # must not leave a stamp claiming data that is not there.
  echo "$SHAPE_ID $label" > "$SHAPE_DIR/$(printf '%s' "$label" | tr '.' '_').shape"
  return $rc
}

report() {
  shopt -s nullglob
  local data=("$COVERAGE_LIVE_PATH_DATA_DIR"/.coverage.*)
  local stamps=("$SHAPE_DIR"/*.shape)
  shopt -u nullglob

  if [ "${#data[@]}" -eq 0 ]; then
    echo "coverage_live_path: no coverage data in $COVERAGE_LIVE_PATH_DATA_DIR" >&2
    echo "coverage_live_path: run this script with no arguments, or once per label with --label." >&2
    return 1
  fi
  if [ "${#stamps[@]}" -ne "${#data[@]}" ]; then
    echo "coverage_live_path: refusing to report -- ${#data[@]} data file(s) but ${#stamps[@]} shape stamp(s)." >&2
    echo "coverage_live_path: this script only reports over data it produced itself; see the measurement shape note at the top of this file." >&2
    return 1
  fi
  local stamp
  for stamp in "${stamps[@]}"; do
    if ! grep -q "^$SHAPE_ID " "$stamp"; then
      echo "coverage_live_path: refusing to report -- $stamp is not measurement shape '$SHAPE_ID'." >&2
      return 1
    fi
  done

  # combine CONSUMES the .coverage.* files, so a second `--report` over the same
  # directory finds no data and says so. Correct for the default run, which
  # reports once; 2a-7's CI wiring must likewise combine exactly once per job.
  python -m coverage combine --rcfile="$RC" >/dev/null || return 1
  python -m coverage report --rcfile="$RC" || return 1
  python -m coverage json --rcfile="$RC" -o "$COVERAGE_LIVE_PATH_DATA_DIR/live-path.json" >/dev/null || return 1
  python - "$COVERAGE_LIVE_PATH_DATA_DIR/live-path.json" <<'PY'
import json, sys
totals = json.load(open(sys.argv[1]))["totals"]
print(
    f'coverage_live_path: statements {totals["num_statements"]}  '
    f'missing {totals["missing_lines"]}  '
    f'coverage {totals["percent_covered"]:.2f}%'
)
PY
}

case "${1:-}" in
  --report)
    report; exit $?
    ;;
  --label)
    [ $# -eq 2 ] || { echo "usage: $0 --label <django-test-label>" >&2; exit 2; }
    run_label "$2"; exit $?
    ;;
  "")
    rm -rf "$COVERAGE_LIVE_PATH_DATA_DIR"
    mkdir -p "$SHAPE_DIR"
    failed=()
    for label in "${LABELS[@]}"; do
      run_label "$label" || failed+=("$label")
    done
    report; rc=$?
    if [ "${#failed[@]}" -gt 0 ]; then
      echo "coverage_live_path: label(s) failed under coverage: ${failed[*]}" >&2
      exit 1
    fi
    exit $rc
    ;;
  *)
    echo "usage: $0 [--label <django-test-label> | --report]" >&2; exit 2
    ;;
esac
