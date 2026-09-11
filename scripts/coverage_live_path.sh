#!/usr/bin/env bash
# Gate 2's measurement (Phase 2 spec, § Stage 2a > Gate 2): statement coverage
# over apps/proxy/live_proxy/** plus the ten Phase 1 boundary modules.
#
#   scripts/coverage_live_path.sh                       run all three labels, then report
#   scripts/coverage_live_path.sh --label <label>       run one label, leave its data file
#   scripts/coverage_live_path.sh --report [dir]        combine and report; over <dir> if given
#   scripts/coverage_live_path.sh --combine-from <dir>  combine data collected elsewhere, then report
#   scripts/coverage_live_path.sh --gate [dir]           compare against scripts/coverage_live_path.floor
#   scripts/coverage_live_path.sh --write-floor [dir]    write the floor from this run (refuses a regression)
#   scripts/coverage_live_path.sh --write-floor --shape-only [dir]
#                                                         re-baseline shape/modules/module_count/rcfile
#                                                         ONLY -- leaves statements/missing/percent/
#                                                         measured/runs byte-identical. For a module-list
#                                                         or rcfile-only move where `missing` did not
#                                                         change; see coverage_live_path.floor's own
#                                                         HOW TO MOVE THIS FLOOR for which kind of move
#                                                         this is and is not for.
#
# [dir] on --report/--gate/--write-floor is scripts/coverage_live_path_isolated.sh's
# combined data directory (one .coverage.* + one .shape file per label, gathered from
# separate containers) -- omit it to report/gate/write-floor over whatever is already
# in $COVERAGE_LIVE_PATH_DATA_DIR, as a bare in-container run leaves it.
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
# per-container/v1 (2a-7): the gate now runs one label per CONTAINER rather
# than one label per process within a shared container -- the shape
# backend-tests.yml's matrix already uses, and the shape stage 2a's isolation
# probe measured. A floor written under per-label/v2 must be refused rather
# than compared against a per-container/v1 run: that is what the shape guard
# below is for, and this is the first time it earns its keep.
SHAPE_ID="per-container/v1-${COVERAGE_CORE}"

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

combine_from() {
  local src="$1"
  [ -d "$src" ] || { echo "coverage_live_path: no such directory: $src" >&2; return 1; }
  rm -rf "$COVERAGE_LIVE_PATH_DATA_DIR"; mkdir -p "$SHAPE_DIR"
  # Each per-label run produced its own data dir with a .coverage.* file and a
  # matching .shape stamp. Copying both preserves the existing stamp check across
  # the container boundary: report() still refuses data it cannot account for.
  find "$src" -name '.coverage.*' -exec cp {} "$COVERAGE_LIVE_PATH_DATA_DIR/" \;
  find "$src" -name '*.shape'     -exec cp {} "$SHAPE_DIR/" \;
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

FLOOR_FILE="$REPO_ROOT/scripts/coverage_live_path.floor"
# The floor's module-list evidence: one repo-relative path per line, sorted,
# sha256-hashed (first 12 hex chars) into the floor file's `modules=` field.
# `modules=` is the fast equality check; this file is what lets a --gate
# mismatch NAME the files that moved instead of just showing two hashes.
# Written by --write-floor alongside FLOOR_FILE; committed together.
MODULES_FILE="$REPO_ROOT/scripts/coverage_live_path.floor.modules"

# Reads the figures report() just wrote, rather than re-deriving them, so --gate and
# --write-floor can never drift from what a bare run prints.
read_totals() {
  python - "$COVERAGE_LIVE_PATH_DATA_DIR/live-path.json" <<'PY'
import json, sys
t = json.load(open(sys.argv[1]))["totals"]
print(t["num_statements"], t["missing_lines"], f'{t["percent_covered"]:.2f}')
PY
}

# The resolved module list IS the denominator's real identity -- num_statements
# moves whenever a statement is added to or removed from an ALREADY-INCLUDED
# module (measured: one three-line function added to control_plane.py took it
# 124 -> 127 statements), not only when scripts/coverage_live_path.coveragerc's
# include list changes. Comparing statements for equality would therefore fire
# on ordinary code changes to files already in scope, not just on scope
# changes -- static, via PythonParser; no 2a PR ever tripped it in practice,
# because every one added only test files, which the rcfile omits, so the
# denominator never moved. The bug was latent, not observed -- and latent is
# reason enough: 2b's first PR touches control_plane.py, relay_serializers.py
# and relay_views.py directly. So the shape guard hashes the FILE SET
# (report()'s JSON `files` keys, which are repo-relative paths matching the
# rcfile's include entries) instead.
# Prints "<hash> <count>" on the first line, then the sorted list, one path per
# line -- the same list --write-floor commits to MODULES_FILE and gate() diffs
# against it on a mismatch.
read_modules() {
  python - "$COVERAGE_LIVE_PATH_DATA_DIR/live-path.json" <<'PY'
import hashlib, json, sys

path = sys.argv[1]
try:
    with open(path) as fh:
        files = sorted(json.load(fh)["files"].keys())
except FileNotFoundError:
    print(f"coverage_live_path: read_modules: {path} does not exist.", file=sys.stderr)
    print("coverage_live_path: read_modules: report() must run first and produce it.", file=sys.stderr)
    sys.exit(1)
except json.JSONDecodeError as exc:
    print(f"coverage_live_path: read_modules: {path} is not valid JSON: {exc}", file=sys.stderr)
    sys.exit(1)
except KeyError:
    print(f"coverage_live_path: read_modules: {path} has no \"files\" key -- not a "
          f"coverage json report, or written by an incompatible coverage version.", file=sys.stderr)
    sys.exit(1)
digest = hashlib.sha256("\n".join(files).encode()).hexdigest()[:12]
print(f"{digest} {len(files)}")
for f in files:
    print(f)
PY
}

# Hashes a plain-text, one-path-per-line file the SAME way read_modules()
# hashes coverage's JSON `files` list: sort the non-blank lines and sha256
# the newline-joined result, truncated to 12 hex chars. Used to verify
# MODULES_FILE against the floor's modules= field on every gate() run,
# independent of the current coverage data -- FLOOR_FILE and MODULES_FILE
# are written in two separate steps by write_floor() and can drift if one
# write fails and the other doesn't, or if a hand-edit touches only one.
# Prints "<hash> <count>".
hash_file_list() {
  python - "$1" <<'PY'
import hashlib, sys
with open(sys.argv[1]) as fh:
    files = sorted(line.strip() for line in fh if line.strip())
digest = hashlib.sha256("\n".join(files).encode()).hexdigest()[:12]
print(f"{digest} {len(files)}")
PY
}

# Hashes the rcfile's raw BYTES (not its resolved file set). `modules` answers
# "did the set of files in scope change"; this answers "did the measurement
# DEFINITION change even when it didn't" -- an `exclude_lines` addition or a
# narrower `[report] omit` can shrink the denominator (and correspondingly
# lower `missing`, since an excluded line is neither covered nor missed)
# without adding or removing a single file from `modules`'s hash. That is the
# cheapest possible way to make the ratchet easier, and a file-set hash alone
# is blind to it. Prints a bare 12-hex-char digest.
rc_hash() {
  python - "$RC" <<'PY'
import hashlib, sys
print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest()[:12])
PY
}

floor_value() { grep -E "^$1=" "$FLOOR_FILE" | head -1 | cut -d= -f2-; }

gate() {
  local stmts missing pct f_shape f_stmts f_missing f_modules f_rcfile
  local modules_out modules_hash modules_count modules_list
  local companion_hash companion_count rc_hash_now
  read -r stmts missing pct < <(read_totals) || return 1
  f_shape="$(floor_value shape)"; f_stmts="$(floor_value statements)"
  f_missing="$(floor_value missing)"; f_modules="$(floor_value modules)"
  f_rcfile="$(floor_value rcfile)"

  if [ "$f_shape" != "$SHAPE_ID" ]; then
    echo "coverage_live_path: floor was written under shape '$f_shape'; this run is '$SHAPE_ID'." >&2
    echo "coverage_live_path: these are not comparable. Re-baseline deliberately with --write-floor." >&2
    return 1
  fi

  # A floor file with no `modules=`/`rcfile=` field predates one or both of
  # these checks. Treating an empty read as "no field to disagree with, so
  # pass" would silently turn a real shape guard into a no-op -- the exact
  # emptiness-as-success trap CLAUDE.md warns about for git queries, and it
  # applies here too: fail loud and say why, rather than pass quietly on a
  # floor that cannot answer.
  if [ -z "$f_modules" ] || [ -z "$f_rcfile" ]; then
    echo "coverage_live_path: floor is missing modules= and/or rcfile= (written before" >&2
    echo "coverage_live_path: one or both checks existed). Refusing to guess whether they" >&2
    echo "coverage_live_path: match -- re-baseline with --write-floor to add them." >&2
    return 1
  fi

  # S1: MODULES_FILE and the floor's modules= are written in two separate
  # steps by write_floor() and can drift -- a failed write, an interrupted
  # one, or a hand-edit touching only one of the pair. Verify the companion
  # matches the floor's own claim about it BEFORE trusting the companion for
  # anything below, on every run, independent of whether this run's own
  # module list matches. A missing companion is refused for the same reason:
  # a `modules=` hash with no evidence file behind it cannot be diffed for
  # names on a future mismatch, silently degrading to "hash mismatch, no
  # detail" exactly when detail matters most.
  if [ ! -f "$MODULES_FILE" ]; then
    echo "coverage_live_path: $MODULES_FILE is missing." >&2
    echo "coverage_live_path: the floor's modules= field has no evidence file to verify itself" >&2
    echo "coverage_live_path: against, or to name files from on a future mismatch. Re-baseline" >&2
    echo "coverage_live_path: with --write-floor to regenerate it." >&2
    return 1
  fi
  read -r companion_hash companion_count < <(hash_file_list "$MODULES_FILE") || return 1
  if [ "$companion_hash" != "$f_modules" ]; then
    echo "coverage_live_path: $MODULES_FILE ($companion_hash, $companion_count files) does not" >&2
    echo "coverage_live_path: match the floor's own modules=$f_modules field." >&2
    echo "coverage_live_path: the two are written in separate steps by --write-floor and have" >&2
    echo "coverage_live_path: drifted -- this is a bug in how the floor was written, not a" >&2
    echo "coverage_live_path: coverage finding. Re-run --write-floor to regenerate both together," >&2
    echo "coverage_live_path: or restore the companion from the commit that set modules=$f_modules." >&2
    return 1
  fi

  modules_out="$(read_modules)" || return 1
  modules_hash="$(printf '%s' "$modules_out" | head -1 | cut -d' ' -f1)"
  modules_count="$(printf '%s' "$modules_out" | head -1 | cut -d' ' -f2)"
  modules_list="$(printf '%s' "$modules_out" | tail -n +2)"

  if [ "$f_modules" != "$modules_hash" ]; then
    echo "coverage_live_path: the module list moved: floor $f_modules ($(floor_value module_count) files)," >&2
    echo "coverage_live_path: this run $modules_hash ($modules_count files)." >&2
    echo "coverage_live_path: added:" >&2
    # hash_file_list() above sorted MODULES_FILE's lines before hashing, but comm
    # reads the file AS WRITTEN and needs its own sortedness, not the hash's --
    # a hand-reordered companion with the same set of lines still passes the hash
    # (S1's check compares sorted content) and would then misalign this diff if
    # fed to comm unsorted. Re-sort here, under the same C locale as $modules_list,
    # so a reordered-but-otherwise-correct companion still diffs cleanly.
    LC_ALL=C comm -13 <(LC_ALL=C sort "$MODULES_FILE") <(printf '%s\n' "$modules_list") | sed 's/^/coverage_live_path:   + /' >&2
    echo "coverage_live_path: removed:" >&2
    LC_ALL=C comm -23 <(LC_ALL=C sort "$MODULES_FILE") <(printf '%s\n' "$modules_list") | sed 's/^/coverage_live_path:   - /' >&2
    echo "coverage_live_path: that is a finding, not a regression. Re-baseline with --write-floor" >&2
    echo "coverage_live_path: and say in the PR why the module list moved." >&2
    return 1
  fi

  # S3: `modules` hashes WHICH files are in scope; it is blind to a change in
  # HOW they're measured that touches no file's membership -- an
  # exclude_lines addition or an omit narrowing can move `statements` (and
  # correspondingly `missing`, since an excluded line is neither covered nor
  # missed) without moving the file set. Hash the rcfile's own bytes to catch
  # that. This check runs AFTER the modules check on purpose: editing the
  # rcfile's include list changes both the file set and the rcfile's bytes,
  # and the modules check above gives the more useful, file-named diagnosis
  # for that (by far the common case) -- this one only has anything to add
  # when modules matched anyway, i.e. the measurement DEFINITION moved while
  # the file set did not.
  rc_hash_now="$(rc_hash)" || return 1
  if [ "$f_rcfile" != "$rc_hash_now" ]; then
    echo "coverage_live_path: scripts/coverage_live_path.coveragerc's bytes changed: floor" >&2
    echo "coverage_live_path: $f_rcfile, this run $rc_hash_now -- even though the module list" >&2
    echo "coverage_live_path: (checked above) did not move. Likely an exclude_lines or omit edit:" >&2
    echo "coverage_live_path: either can move the denominator without changing which files are in" >&2
    echo "coverage_live_path: scope. Diff the rcfile against the commit that set modules=$f_modules" >&2
    echo "coverage_live_path: to see what changed." >&2
    echo "coverage_live_path: that is a finding, not a regression. Re-baseline with --write-floor" >&2
    echo "coverage_live_path: and say in the PR why the measurement definition moved." >&2
    return 1
  fi

  # `statements` is recorded provenance, not compared: it moves with any edit
  # to an already-included module (see read_modules() above), so it cannot be
  # the shape check -- `modules` and `rcfile` above are. Printed here for
  # information only.
  echo "coverage_live_path: denominator: floor $f_stmts statements  this run $stmts statements (informational -- modules=/rcfile= above are the shape checks)"
  # `missing` is the ratchet -- a MAXIMUM. It is the correct invariant under a
  # moving denominator: new COVERED code leaves it unchanged, new UNCOVERED
  # code raises it (and correctly fails below), deleted dead code lowers it.
  # It needs no denominator-equality check to mean what it claims.
  echo "coverage_live_path: floor missing=$f_missing  this run missing=$missing  coverage ${pct}%"
  if [ "$missing" -gt "$f_missing" ]; then
    echo "coverage_live_path: GATE FAILED -- $(( missing - f_missing )) more missed statements than the floor." >&2
    echo "coverage_live_path: the floor is the worst of >=12 runs on the tree that set it, so this is" >&2
    echo "coverage_live_path: outside the measured spread: a finding to investigate, not noise." >&2
    echo "coverage_live_path: attribute it per FILE and then per LINE before widening anything --" >&2
    echo "coverage_live_path: diff live-path.json's per-file missing_lines, do not difference totals." >&2
    return 1
  fi
  if [ "$missing" -lt "$f_missing" ]; then
    echo "coverage_live_path: $(( f_missing - missing )) FEWER missed than the floor. The floor is not"
    echo "coverage_live_path: lowered automatically -- run --write-floor in the PR that earned it."
  fi
  return 0
}

# $1, if "1", is --shape-only: writes shape/modules/module_count/rcfile ONLY and
# leaves statements/missing/percent/measured/runs byte-identical. See
# coverage_live_path.floor's HOW TO MOVE THIS FLOOR for which kind of move this is
# for. This is NOT the override that "HOW TO MOVE" step 4 declined: that request was
# to accept an explicit `missing` VALUE, which has to thread through the regression
# check below (which run's figure counts as "worse than the floor"?) and the percent
# computation (recomputed against which value?) -- real machinery, declined on
# purpose. --shape-only writes FEWER fields instead, so neither question has
# anywhere to attach: it never touches `missing` or `percent` at all, and the
# regression check below is skipped entirely rather than answered.
write_floor() {
  local shape_only="${1:-}"
  # Explicit empty defaults, not bare `local stmts missing pct old`: this
  # script runs under `set -u`, which (confirmed on this bash) treats a
  # `local` declared with no value as UNSET, not empty -- and --shape-only
  # skips the read_totals() call below entirely, so stmts/missing/pct must
  # already be defined empty strings before they're read again (both in the
  # "worse floor" check, guarded by shape_only, and unconditionally as
  # arguments to the python call further down).
  local stmts="" missing="" pct="" old=""
  # The repo is bind-mounted read-only inside the standard test-hook container
  # (CLAUDE.md, Test hooks), so a plain `python ... open(path, "w")` a few lines
  # below would die with `OSError: [Errno 30] Read-only file system` -- a trace
  # that names Python, not the actual problem. Check first and say what is wrong
  # and what to do about it: run this from a writable checkout (a maintainer's own
  # clone, or a scratch container with /repo mounted rw), not from the read-only
  # dev container --gate itself runs from every day.
  if [ ! -w "$FLOOR_FILE" ]; then
    echo "coverage_live_path: $FLOOR_FILE is not writable from here." >&2
    echo "coverage_live_path: this is very likely the read-only /repo mount the standard" >&2
    echo "coverage_live_path: test-hook container uses (CLAUDE.md, Test hooks) -- --gate reads" >&2
    echo "coverage_live_path: fine from there, but --write-floor needs a writable checkout:" >&2
    echo "coverage_live_path: your own clone, or a scratch container with /repo mounted rw." >&2
    return 1
  fi

  if [ -z "$shape_only" ]; then
    read -r stmts missing pct < <(read_totals) || return 1
    old="$(floor_value missing)"
    if [ "$missing" -gt "$old" ] && [ "${COVERAGE_LIVE_PATH_ALLOW_REGRESSION:-}" != "1" ]; then
      echo "coverage_live_path: refusing to write a WORSE floor ($old -> $missing)." >&2
      echo "coverage_live_path: a floor may rise only in the PR that earns and explains the rise, and" >&2
      echo "coverage_live_path: may never simply be edited down. If the module list or the rcfile" >&2
      echo "coverage_live_path: changed and missing did NOT, use --write-floor --shape-only instead --" >&2
      echo "coverage_live_path: it never writes missing/percent/measured/runs, so this check has" >&2
      echo "coverage_live_path: nothing to refuse. COVERAGE_LIVE_PATH_ALLOW_REGRESSION=1 is for a" >&2
      echo "coverage_live_path: genuine, explained ratchet increase only -- say why in the PR." >&2
      return 1
    fi
  fi
  # --shape-only takes no measurement of `missing` at all (read_totals() is not
  # even called above), which is the point: there is no new ratchet figure to
  # compare, refuse, or accidentally accept, because none is being written.

  local modules_out modules_hash modules_count rc_hash_now
  modules_out="$(read_modules)" || return 1
  modules_hash="$(printf '%s' "$modules_out" | head -1 | cut -d' ' -f1)"
  modules_count="$(printf '%s' "$modules_out" | head -1 | cut -d' ' -f2)"
  rc_hash_now="$(rc_hash)" || return 1

  # S1 fix: write the new module list to a TEMP file first and only `mv` it
  # over MODULES_FILE once the floor's own Python write below has succeeded.
  # The previous order wrote MODULES_FILE first and FLOOR_FILE second, so a
  # failure partway through the Python write (a bad substitution, a disk
  # error) left the companion already updated to the NEW list while the
  # floor's modules= field still held the OLD hash -- silently inconsistent,
  # and gate()'s companion-consistency check above exists precisely to catch
  # that inconsistency happening again. This ordering makes it not happen:
  # if the floor write fails, MODULES_FILE is untouched and matches the floor
  # that IS on disk; if it succeeds, both move together.
  local modules_tmp="${MODULES_FILE}.tmp.$$"
  printf '%s\n' "$modules_out" | tail -n +2 > "$modules_tmp" || {
    rm -f "$modules_tmp"
    echo "coverage_live_path: failed writing $modules_tmp; aborting before touching the floor." >&2
    return 1
  }

  # S2 fix: re.sub cannot ADD a key that isn't already a `key=...` line in the
  # floor file -- it can only replace an existing one. A floor written before
  # this PR (or before any future new field) has no such line, so the old
  # code silently substituted nothing, then printed a "floor written" success
  # message for a write that had not happened, and the very next --gate saw
  # the same missing field and failed identically: a loop with a false
  # success message at its start. re.subn's match count tells the difference
  # between "replaced" and "line didn't exist"; when it didn't, APPEND the
  # key=value line instead, so every field this call intends to write is
  # always present in the file afterward, regardless of what the file had
  # before. shape_only controls WHICH fields that set is -- the four shape
  # fields always, the five measurement fields (statements included) only on
  # a plain --write-floor.
  if ! python - "$FLOOR_FILE" "$SHAPE_ID" "$modules_hash" "$modules_count" "$rc_hash_now" \
    "$shape_only" "$stmts" "$missing" "$pct" "${COVERAGE_LIVE_PATH_RUNS:-0}" <<'PY'
import re, sys, datetime
path, shape, modules, module_count, rcfile, shape_only, stmts, missing, pct, runs = sys.argv[1:11]
src = open(path).read()

def set_field(src, k, v):
    # count=1: reachable only by a deliberate hand edit (this script never
    # produces a duplicate key= line itself), but re.subn's default replaces
    # EVERY match, not just the first -- against a floor hand-edited into
    # having two `k=` lines, that would silently coerce both to the same new
    # value rather than leaving the duplication visible. One substitution,
    # at the first line, is the honest behaviour for a file this function
    # otherwise treats as one-key-per-line.
    new_src, n = re.subn(rf"(?m)^{k}=.*$", f"{k}={v}", src, count=1)
    if n:
        return new_src
    if src and not src.endswith("\n"):
        src += "\n"
    return src + f"{k}={v}\n"

fields = [("shape", shape), ("modules", modules), ("module_count", module_count), ("rcfile", rcfile)]
if not shape_only:
    fields += [
        ("statements", stmts), ("missing", missing), ("percent", pct),
        ("measured", datetime.date.today().isoformat()), ("runs", runs),
    ]
for k, v in fields:
    src = set_field(src, k, v)
open(path, "w").write(src)
if shape_only:
    print(f"coverage_live_path: floor shape re-baselined -- shape {shape} modules {modules} "
          f"({module_count} files) rcfile {rcfile}; statements/missing/percent/measured/runs left untouched")
else:
    print(f"coverage_live_path: floor written -- statements {stmts} missing {missing} coverage {pct}% "
          f"modules {modules} ({module_count} files) rcfile {rcfile}")
PY
  then
    rm -f "$modules_tmp"
    echo "coverage_live_path: floor write failed; $MODULES_FILE left untouched." >&2
    return 1
  fi

  # Only now, after the floor write succeeded, does the companion move --
  # see the comment above modules_tmp.
  mv "$modules_tmp" "$MODULES_FILE"
}

case "${1:-}" in
  --report)
    # An optional trailing directory lets scripts/coverage_live_path_isolated.sh's
    # default mode (${1:---report}) call through uniformly with --gate/--write-floor,
    # which both take the same optional dir below.
    if [ $# -eq 2 ]; then combine_from "$2" || exit 1; fi
    report; exit $?
    ;;
  --label)
    [ $# -eq 2 ] || { echo "usage: $0 --label <django-test-label>" >&2; exit 2; }
    run_label "$2"; exit $?
    ;;
  --combine-from)
    [ $# -eq 2 ] || { echo "usage: $0 --combine-from <dir>" >&2; exit 2; }
    combine_from "$2" || exit 1
    report; exit $?
    ;;
  --gate)
    if [ $# -eq 2 ]; then combine_from "$2" || exit 1; fi
    report >/dev/null || exit 1
    gate
    exit $?
    ;;
  --write-floor)
    shift
    shape_only=""
    if [ "${1:-}" = "--shape-only" ]; then shape_only=1; shift; fi
    if [ $# -eq 1 ]; then
      combine_from "$1" || exit 1
    elif [ $# -gt 1 ]; then
      echo "usage: $0 --write-floor [--shape-only] [dir]" >&2
      exit 2
    fi
    report >/dev/null || exit 1
    write_floor "$shape_only"
    exit $?
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
    echo "usage: $0 [--label <label> | --report | --combine-from <dir> | --gate [dir] | --write-floor [--shape-only] [dir]]" >&2
    exit 2
    ;;
esac
