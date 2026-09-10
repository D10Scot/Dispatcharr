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
# shape either. THIS GUARD STANDS, unaffected by everything below it.
#
# THE TRACER CORE IS PART OF THE SHAPE TOO, for the same reason the per-label
# vs. single-process split is: coverage's default C tracer (settrace-based)
# loses every statement that executes immediately after a greenlet switch --
# verified directly on this branch, not taken on report. A scratch test drove
# a real stand-in replay through input/manager.py's _read_stderr, which calls
# gevent.sleep(0) once per read to yield the hub (:940), then checked Redis
# for ffmpeg_speed -- written only if _parse_ffmpeg_stats (:962, inside the
# post-sleep loop) genuinely ran. It was there ('2.87'), independent of any
# tracer, while the SAME test run under the C tracer marked lines 942-985
# entirely missed. Re-run with COVERAGE_CORE=sysmon (Python's sys.monitoring,
# CPython 3.12+ -- this repo requires >=3.13, so both the hook image and CI's
# dynamically-resolved base image carry it) recovered exactly that block. The
# opposite fix, `concurrency = gevent`, is wrong: this test process is not
# gevent-monkey-patched (dispatcharr/gevent_patch.py is imported only by the
# uWSGI ini files), so gevent mode stops tracing the relay's plain OS threads
# altogether and reports FEWER statements covered, not more. sysmon is
# therefore the correct tracer for this measurement, not merely a different
# one, and is set here rather than left to the caller's environment.
export COVERAGE_CORE=sysmon
#
# What does NOT hold: that the measurement is exactly reproducible within the
# shape. It was, for a suite with no tune in it -- and still is: the clean-tree
# baseline this script reproduces (7,978 statements / 3,977 missing / 50.15%,
# no harness test in the labels yet) has no process in it to race. Stage 2a
# ends that by construction. Once a real tune is in the suite, `missing` is
# the one figure here that does not reproduce, and a comment that says
# otherwise is wrong the moment a test spawns a process. Measured on one tree,
# 2026-09-10, across twelve runs under sysmon (adopted above): `missing`
# 3,115-3,178 (63 statements), same 7,978 denominator every time. Adopting
# sysmon WIDENED the observed spread rather than narrowing it (a prior
# C-tracer measurement, before sysmon, saw 3,202-3,221 -- 19 statements) --
# expected, not a regression: the C tracer's systematic loss after a greenlet
# switch was ALSO flattening the difference between "the relay's own
# background housekeeping fired during this run" and "it did not", so
# recovering the lost statements makes existing timing variance more visible,
# not larger in kind. Per-file attribution under sysmon traces the spread to
# the SAME already-known sources, now fully counted rather than partially
# dropped: input/manager.py's stderr-reader-thread join (:1739-1767),
# services/channel_service.py's mark_channel_stopping (:28-49), and
# server.py's cleanup-thread sweep that calls it (_coordinated_stop_channel,
# :1257, reached from check_inactive_channels, :1855, and inline at
# :1998/:2042) -- not to this script, not to the harness, and not the spec's
# +/-70-statement BETWEEN-SHAPES band, which is a different phenomenon and an
# order of magnitude smaller than what is measured here. THAT NUMBER IS A
# MEASUREMENT, NOT A PROMISE: it describes one tree on
# one day, and nothing here asserts it holds on the next one. Sizing a
# tolerance from it is 2a-7's job, on its own evidence against its own tree --
# deliberately not this script's, which carries no tolerance number of its
# own to go stale.
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
# Bumped whenever the rcfile's denominator OR the tracer core changes, so a
# stale data directory from before either change is refused rather than
# silently combined. v2 adds the tracer core to the shape itself -- a floor
# written under one core and compared under the other is exactly the
# un-meetable-floor failure this guard exists to prevent (see the tracer-core
# note above), so the core name is part of the id, not a separate check.
SHAPE_ID="per-label/v2-${COVERAGE_CORE}"

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
      local recorded
      recorded="$(cut -d' ' -f1 "$stamp" 2>/dev/null || echo '?')"
      echo "coverage_live_path: refusing to report -- $stamp was written as shape '$recorded', this run is '$SHAPE_ID' (tracer core: ${COVERAGE_CORE})." >&2
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
    # A failed label is announced BEFORE the figures, not after them. The old
    # order printed a clean-looking total and only then said a label had died,
    # and a total taken over a short suite is wrong in the direction that
    # flatters nobody: a tree measured with `hypothesis` missing reported 3,230
    # missing where the same tree with it present reported 3,169 — the two
    # property-test modules fail to IMPORT, the label reports errors, and 61
    # statements they would have covered are silently counted as missed. The
    # exit code was always right; the risk is a reader copying the number above
    # it. So say it first, and label the figures.
    if [ "${#failed[@]}" -gt 0 ]; then
      echo "coverage_live_path: label(s) failed under coverage: ${failed[*]}" >&2
      echo "coverage_live_path: THE FIGURES BELOW ARE INVALID — a failed label" >&2
      echo "coverage_live_path: under-runs the suite and inflates 'missing'." >&2
      echo "coverage_live_path: fix the failure and re-measure; do not quote these." >&2
      report || true
      exit 1
    fi
    report; rc=$?
    exit $rc
    ;;
  *)
    echo "usage: $0 [--label <django-test-label> | --report]" >&2; exit 2
    ;;
esac
