#!/usr/bin/env bash
# The Go relay's coverage ratchet -- Gate 2's counterpart for `relay/`
# (Phase 2 spec, § Stage 2c, the 2c-9 row; § Testing, "then 2c-9's Go
# equivalent").
#
#   scripts/coverage_relay_go.sh --measure [dir]   run the suite, write the profile
#   scripts/coverage_relay_go.sh --report  [dir]   parse and print, no comparison
#   scripts/coverage_relay_go.sh --gate    [dir]   compare against the floor
#   scripts/coverage_relay_go.sh --write-floor [dir]
#   scripts/coverage_relay_go.sh --write-floor --shape-only [dir]
#
# [dir] defaults to $COVERAGE_RELAY_GO_DATA_DIR, else /tmp/dispatcharr-coverage-relay-go.
# --measure needs the Go toolchain; --report/--gate/--write-floor need only
# awk, sha256sum (or shasum) and the two files --measure left behind, which is
# why CI can gate on a bare runner from a downloaded artifact.
#
# WHAT IS MEASURED, and why it is not `./...`. The denominator is exactly the
# packages the SHIPPED BINARY LINKS -- `go list -deps .` from the module root,
# ten of them today. relay/internal/relaytest and relay/internal/credlint are
# in the module and in neither: the first is the Go counterpart of
# apps/proxy/live_proxy/tests/harness/ and the second is a lint tool run by
# `go run`, and scripts/coverage_live_path.coveragerc omits both kinds on the
# Python side (`omit = */tests/*`; no script under scripts/ is in its module
# list). The rule is "what the relay ships", decided by kind, and it is
# derived mechanically rather than listed by hand so it cannot rot -- but the
# derived list is hashed into the floor, so GROWING it is still a deliberate
# re-baseline and never a silent denominator move.
#
# The numbers this distinction is worth, measured 2026-09-15 on a635190c:
# the whole module is 4,463 statements / 1,172 missing / 73.74%; the ten linked
# packages are 3,696 / 587 / 84.12%. The two excluded packages are 767
# statements of which 585 are missing -- HALF the module's shortfall is test
# scaffolding and a lint tool. Stated here rather than in a PR description
# because a reader who runs `go test -cover ./...` and sees 74% must be able to
# find out in one place why this gate says 84%.
#
# PER-PACKAGE, NOT -coverpkg. `go test -cover` instruments only the package
# under test, so a package's figure comes from its OWN tests; `-coverpkg`
# counts a package as covered when any other package's test walks through it.
# Both were measured on the same tree and the same denominator: per-package
# 587 missing, -coverpkg 316 -- a 271-statement, 7.33-point difference that is
# entirely code executed by a neighbour's tests. Per-package is kept because
# the gate's stated purpose (spec D7) is catching a subtle regression, which
# needs an ASSERTION over the code, not an execution of it, and an assertion
# lives in the package's own tests. A -coverpkg profile is refused outright
# below rather than silently accepted: it repeats every block once per test
# binary, so the parse would still produce a plausible number.
#
# -race IS PART OF THE SHAPE. The concurrency model changes from
# gevent-cooperative to OS-thread-parallel goroutines in this phase, and
# `-race` is what makes a data race visible. It also changes timing, which
# changes which branches run, which is where this gate's run-to-run spread
# comes from. A figure measured without it is not comparable with one measured
# with it, in either direction -- the same argument scripts/coverage_live_path.sh
# makes about COVERAGE_CORE -- so the mode string below names it.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

MODULE_DIR="$REPO_ROOT/relay"
FLOOR="$REPO_ROOT/scripts/coverage_relay_go.floor"
FLOOR_PACKAGES="$REPO_ROOT/scripts/coverage_relay_go.floor.packages"
GOMOD="$MODULE_DIR/go.mod"

DATA_DIR="${COVERAGE_RELAY_GO_DATA_DIR:-/tmp/dispatcharr-coverage-relay-go}"
PROFILE_NAME="relay.coverprofile"
PACKAGES_NAME="relay.packages"

# Bumped whenever WHAT IS MEASURED or HOW changes -- the package-selection
# rule, the test command, the cover mode. A floor written under one shape is
# refused against a run under another rather than compared, because the two
# numbers are incomparable rather than better or worse.
SHAPE_ID="go-race-per-package/v1"

say() { echo "coverage_relay_go: $*"; }
die() { echo "coverage_relay_go: $*" >&2; exit 1; }

# sha256, first 12 hex chars, of stdin. Linux has sha256sum; macOS has shasum.
sha12() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum | cut -c1-12
  else
    shasum -a 256 | cut -c1-12
  fi
}

sha12_file() { sha12 < "$1"; }

# ---------------------------------------------------------------- measure ---

measure() {
  local dir="$1"
  command -v go >/dev/null 2>&1 || die "--measure needs the Go toolchain on PATH."
  rm -rf "$dir"; mkdir -p "$dir"

  # The package list is derived FIRST and from `go list -deps .`, the same
  # question scripts/check_go_stdlib_only.sh asks: what does the binary link?
  # Written before the tests run so a failing suite still leaves evidence of
  # what the scope was.
  ( cd "$MODULE_DIR" && go list -deps . ) \
    | grep '^github.com/D10Scot/Dispatcharr/relay' \
    | LC_ALL=C sort > "$dir/$PACKAGES_NAME" \
    || die "could not list the binary's dependencies."
  [ -s "$dir/$PACKAGES_NAME" ] || die "the binary's dependency list came back empty."

  say "measuring $(wc -l < "$dir/$PACKAGES_NAME" | tr -d ' ') linked packages under $SHAPE_ID"
  # -count=1 is NOT decoration. `go test` caches a package's result, coverage
  # profile included, and replays it verbatim -- so a local twelve-round census
  # without this flag is one run reported twelve times, with a spread of zero
  # and a floor that has measured nothing. It costs nothing in CI (a fresh
  # runner has a cold cache) and is what makes a local census real.
  if ! ( cd "$MODULE_DIR" && CGO_ENABLED=1 go test -count=1 -race -covermode=atomic \
           -coverprofile="$dir/$PROFILE_NAME" ./... ); then
    # A failed suite does not DEGRADE this measurement, it INVALIDATES it: the
    # statements a dead package would have covered are counted as missed, which
    # moves the number the way a regression moves. The profile is removed so a
    # later --gate cannot read it by accident. (Same rule, same reason, as
    # scripts/coverage_live_path.floor's "a failed label invalidates a
    # measurement rather than degrading it".)
    rm -f "$dir/$PROFILE_NAME"
    die "the Go suite failed; the profile was discarded. Fix the tests, then measure again."
  fi
  say "profile: $dir/$PROFILE_NAME"
}

# ------------------------------------------------------------------ parse ---

# Reads $dir and prints one line:  <statements> <missing> <packages_hash> <package_count>
# plus, on stderr, the per-package table. Dies on every shape problem it can see.
parse() {
  local dir="$1"
  local profile="$dir/$PROFILE_NAME"
  local packages="$dir/$PACKAGES_NAME"

  [ -f "$profile" ]  || die "no profile at $profile -- run --measure first (or download the CI artifact)."
  [ -f "$packages" ] || die "no package list at $packages -- it is written by --measure alongside the profile."

  local mode
  mode="$(head -1 "$profile")"
  case "$mode" in
    "mode: atomic") : ;;
    *) die "the profile's first line is [$mode], expected [mode: atomic]. -covermode is part of the shape." ;;
  esac

  # Everything below is one awk pass so the per-package table and the totals
  # cannot disagree about what was counted.
  awk -v packages="$packages" '
    BEGIN {
      while ((getline pkg < packages) > 0) { if (pkg != "") inscope[pkg] = 1 }
      close(packages)
    }
    NR == 1 { next }
    NF != 3 { printf "MALFORMED %d %s\n", NR, $0 > "/dev/stderr"; bad++; next }
    {
      block = $1; n = $2 + 0; c = $3 + 0
      if (block in seen) { dup++; dupblock = block }
      seen[block] = 1
      pkg = block
      sub(/\/[^\/]*$/, "", pkg)          # drop "/file.go:1.2,3.4"
      present[pkg] = 1
      if (!(pkg in inscope)) { outn[pkg] += n; next }
      tot[pkg] += n
      if (c > 0) cov[pkg] += n
    }
    END {
      if (bad)  { print "PARSE_ERROR malformed-lines " bad; exit }
      if (dup)  { print "PARSE_ERROR duplicate-block " dupblock; exit }
      for (pkg in inscope) if (!(pkg in present)) { missingpkg = missingpkg " " pkg }
      if (missingpkg != "") { print "PARSE_ERROR absent-package" missingpkg; exit }
      for (pkg in tot) {
        statements += tot[pkg]; covered += cov[pkg]
        printf "  %7d %7d  %6.2f%%  %s\n", tot[pkg], tot[pkg] - cov[pkg], 100 * cov[pkg] / tot[pkg], pkg > "/dev/stderr"
      }
      for (pkg in outn) printf "  ~out of scope, not counted: %s, %d statements\n", pkg, outn[pkg] > "/dev/stderr"
      printf "TOTALS %d %d\n", statements, statements - covered
    }
  ' "$profile" > "$DATA_DIR/.totals" 2> "$DATA_DIR/.table"
  # Sorted here rather than in awk: `for (k in array)` has no defined order,
  # and a table whose rows move between runs makes two reports look different
  # when only their line order changed.
  LC_ALL=C sort "$DATA_DIR/.table" >&2

  local line; line="$(cat "$DATA_DIR/.totals")"
  case "$line" in
    "PARSE_ERROR duplicate-block "*)
      die "the profile repeats block ${line#PARSE_ERROR duplicate-block }.
        That is what a -coverpkg profile looks like: every block appears once per
        test binary. This gate's shape is per-package (-cover, no -coverpkg);
        re-measure with --measure." ;;
    "PARSE_ERROR absent-package"*)
      die "these linked packages are in the scope list but have NO block in the profile:${line#PARSE_ERROR absent-package}
        A package that compiled and ran always contributes blocks, so this means
        the profile is incomplete -- a partial or failed run. Measure again; do
        not gate on it." ;;
    "PARSE_ERROR malformed-lines"*)
      die "the profile has ${line#PARSE_ERROR malformed-lines } line(s) that are not 'block n count'." ;;
    "TOTALS "*) : ;;
    *) die "could not parse the profile at all (awk said [$line])." ;;
  esac

  local statements missing
  statements="$(echo "$line" | awk '{print $2}')"
  missing="$(echo "$line" | awk '{print $3}')"
  local pkg_hash pkg_count
  pkg_hash="$(sha12_file "$packages")"
  pkg_count="$(grep -c . "$packages")"
  echo "$statements $missing $pkg_hash $pkg_count"
}

percent_of() { awk -v s="$1" -v m="$2" 'BEGIN { printf "%.2f", (s == 0) ? 0 : 100 * (s - m) / s }'; }

# ----------------------------------------------------------------- report ---

report() {
  local dir="$1" parsed
  parsed="$(parse "$dir")" || exit 1
  set -- $parsed
  say "shape=$SHAPE_ID  packages=$4  statements=$1  missing=$2  coverage=$(percent_of "$1" "$2")%"
}

# ------------------------------------------------------------------- gate ---

floor_field() { grep -E "^$1=" "$FLOOR" | head -1 | cut -d= -f2-; }

gate() {
  local dir="$1" parsed
  parsed="$(parse "$dir")" || exit 1
  set -- $parsed
  local statements="$1" missing="$2" pkg_hash="$3" pkg_count="$4"
  local percent; percent="$(percent_of "$statements" "$missing")"

  if [ ! -f "$FLOOR" ]; then
    # The documented bootstrap, expected EXACTLY ONCE: on the PR that
    # introduces the floor, whose census draws are taken through this branch.
    # It cannot be used to disable the gate later, because go-tests.yml's
    # "Refuse a floor edited downward" step fails when the BASE ref carries a
    # floor and the head does not -- absence is forgiven only when the base is
    # also absent.
    say "NO FLOOR at $FLOOR -- this run is a census draw, not a gate."
    say "this run statements=$statements missing=$missing coverage=$percent% packages=$pkg_hash ($pkg_count)"
    return 0
  fi

  # Checked against the floor's own hash on EVERY run, independent of the
  # current data: --write-floor writes the two files in separate steps, so they
  # can drift, and a drifted companion makes a future mismatch message name the
  # wrong files.
  local companion_hash; companion_hash="$(sha12_file "$FLOOR_PACKAGES")"
  local floor_packages; floor_packages="$(floor_field packages)"
  if [ "$companion_hash" != "$floor_packages" ]; then
    echo "coverage_relay_go: GATE FAILED -- $FLOOR_PACKAGES does not match the floor's packages= hash." >&2
    echo "        floor packages=$floor_packages  companion file=$companion_hash" >&2
    echo "        The two are written in separate steps by --write-floor and have drifted." >&2
    exit 1
  fi

  local floor_shape; floor_shape="$(floor_field shape)"
  if [ "$floor_shape" != "$SHAPE_ID" ]; then
    echo "coverage_relay_go: GATE FAILED -- shape mismatch: floor \"$floor_shape\", this run \"$SHAPE_ID\"." >&2
    echo "        Two shapes measure different things; the numbers are incomparable, not better or worse." >&2
    exit 1
  fi

  if [ "$pkg_hash" != "$floor_packages" ]; then
    echo "coverage_relay_go: GATE FAILED -- the linked package set changed." >&2
    echo "        floor packages=$floor_packages ($(floor_field package_count))  this run=$pkg_hash ($pkg_count)" >&2
    diff <(cat "$FLOOR_PACKAGES") "$dir/$PACKAGES_NAME" | sed 's/^/          /' >&2 || true
    echo "        A package entering or leaving the binary moves the denominator. Re-baseline" >&2
    echo "        deliberately with --write-floor --shape-only if missing is unchanged." >&2
    exit 1
  fi

  local gomod_hash; gomod_hash="$(sha12_file "$GOMOD")"
  local floor_gomod; floor_gomod="$(floor_field gomod)"
  if [ "$gomod_hash" != "$floor_gomod" ]; then
    echo "coverage_relay_go: GATE FAILED -- relay/go.mod changed (floor $floor_gomod, now $gomod_hash)." >&2
    echo "        go.mod fixes the toolchain the measurement ran under and the module's" >&2
    echo "        dependency set -- the Go counterpart of the Python gate's rcfile hash." >&2
    echo "        Re-baseline with --write-floor --shape-only if missing is unchanged." >&2
    exit 1
  fi

  local floor_missing; floor_missing="$(floor_field missing)"
  # A floor whose `missing` is not a decimal integer must FAIL LOUDLY, not fall
  # through. `[ "$missing" -gt "<MAX>" ]` does not error out of the script: bash
  # prints "integer expected", the test exits 2, the `if` is false, and the gate
  # says GATE PASSED on a floor it could not read. That is this whole file's own
  # failure mode -- a check that is green because it could not look -- and the
  # placeholder case is real: the floor template ships `missing=<MAX>` for a
  # campaign to fill in, so an unfilled template would otherwise gate nothing.
  case "$floor_missing" in
    ""|*[!0-9]*)
      echo "coverage_relay_go: GATE FAILED -- the floor's missing= is [$floor_missing], not a decimal integer." >&2
      echo "        An unfilled template placeholder looks exactly like this. A floor that cannot be" >&2
      echo "        read cannot be compared, and a gate that cannot compare must not report green." >&2
      exit 1 ;;
  esac
  say "denominator: floor $(floor_field statements) statements  this run $statements statements"
  say "floor missing=$floor_missing  this run missing=$missing  coverage $percent%"
  if [ "$missing" -gt "$floor_missing" ]; then
    echo "coverage_relay_go: GATE FAILED -- $((missing - floor_missing)) more missed statements than the floor." >&2
    echo "        \`missing\` is a MAXIMUM and lower is better, set from the WORST of >=12 CI" >&2
    echo "        draws. A draw above it is a finding to investigate, not noise: attribute it" >&2
    echo "        per package and then per BLOCK -- diff the uncovered block sets, never" >&2
    echo "        difference the totals -- against a green run's profile." >&2
    echo "        If it is the documented flap exceeding its recorded envelope, the fix is a" >&2
    echo "        re-measurement PR of its own (see $FLOOR's HOW TO MOVE THIS FLOOR), never a" >&2
    echo "        floor bump on the PR that happened to draw it. See issue #312 for the Python" >&2
    echo "        gate's worked instance of exactly this." >&2
    exit 1
  fi
  say "GATE PASSED."
}

# ------------------------------------------------------------ write-floor ---

write_floor() {
  local dir="$1" shape_only="$2" parsed
  parsed="$(parse "$dir")" || exit 1
  set -- $parsed
  local statements="$1" missing="$2" pkg_hash="$3" pkg_count="$4"
  local gomod_hash; gomod_hash="$(sha12_file "$GOMOD")"

  if [ -e "$FLOOR" ] && [ ! -w "$FLOOR" ]; then
    die "$FLOOR is not writable from here -- run --write-floor from a writable checkout."
  fi

  # A floor that does not exist yet is created whole, with a stub header the
  # PR that sets it replaces with its own census. A floor that DOES exist is
  # edited FIELD BY FIELD and its prose is never touched: this file's header
  # carries the campaign, the flappy-block census and the HOW TO MOVE THIS
  # FLOOR procedure, and a tool that rewrote the file wholesale would delete
  # all of it on every re-baseline. (scripts/coverage_live_path.sh makes the
  # same distinction, for the same reason.)
  if [ ! -f "$FLOOR" ]; then
    cat > "$FLOOR" <<EOF
# The Go relay's ratchet floor. See docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md
# (Stage 2c, the 2c-9 row) and docs/superpowers/plans/2026-09-13-phase2-2c9-go-coverage-gate.md.
#
# REPLACE THIS STUB with the campaign that earned the number below: every CI
# draw in order, max/min/spread/n, the stopping rule, and a HOW TO MOVE THIS
# FLOOR section. A floor with no provenance cannot be audited.
#
# Written by:  scripts/coverage_relay_go.sh --write-floor
# Enforced by: scripts/coverage_relay_go.sh --gate  (go-tests.yml, job coverage)
EOF
    say "created $FLOOR with a stub header -- replace it with the campaign."
  else
    local old; old="$(floor_field missing)"
    if [ "$shape_only" = "no" ] && [ -n "$old" ] && [ "$missing" -gt "$old" ]; then
      die "refusing to write a WORSE floor ($old -> $missing).
        A floor may rise only in a PR that earns and explains the rise, and may never
        simply be edited down. If the package set or go.mod changed and missing did
        NOT, use --write-floor --shape-only: it never writes missing/percent/measured/
        runs, so this check has nothing to refuse."
    fi
  fi

  # The companion is written to a TEMP file and moved into place only after
  # every floor field has been written, so a failure partway through cannot
  # leave the companion holding the NEW list while packages= still holds the
  # OLD hash -- the exact inconsistency gate()'s companion check exists to
  # catch. Same ordering, same reason, as the Python gate's own S1 fix.
  local tmp_packages="${FLOOR_PACKAGES}.tmp.$$"
  cp "$dir/$PACKAGES_NAME" "$tmp_packages" || die "could not stage $tmp_packages."

  set_field shape          "$SHAPE_ID"
  set_field packages       "$pkg_hash"
  set_field package_count  "$pkg_count"
  set_field gomod          "$gomod_hash"
  if [ "$shape_only" = "no" ]; then
    set_field statements "$statements"
    set_field missing    "$missing"
    set_field percent    "$(percent_of "$statements" "$missing")"
    set_field measured   "$(date -u +%Y-%m-%d)"
    set_field runs       1
  fi

  mv "$tmp_packages" "$FLOOR_PACKAGES"

  if [ "$shape_only" = "yes" ]; then
    say "re-baselined shape/packages/package_count/gomod only; missing unchanged at $(floor_field missing)."
  else
    say "wrote $FLOOR from THIS RUN (missing=$missing, runs=1)."
    say "A campaign must then hand-edit missing to max(runs), recompute percent, and set runs."
  fi
}

# set_field replaces `key=...` in the floor, or APPENDS it when no such line
# exists. Appending matters: a floor written before a field existed has no line
# to substitute, and a substitution that matches nothing would report success
# for a write that never happened -- then fail identically on the next --gate.
set_field() {
  local key="$1" value="$2"
  if grep -qE "^${key}=" "$FLOOR"; then
    local tmp; tmp="$(mktemp)"
    awk -v k="$key" -v v="$value" '
      $0 ~ "^" k "=" { print k "=" v; next } { print }
    ' "$FLOOR" > "$tmp" && mv "$tmp" "$FLOOR"
  else
    printf '%s=%s\n' "$key" "$value" >> "$FLOOR"
  fi
}

# ------------------------------------------------------------------- main ---

MODE=""
SHAPE_ONLY="no"
DIR=""
while [ $# -gt 0 ]; do
  case "$1" in
    --measure|--report|--gate|--write-floor) MODE="$1" ;;
    --shape-only) SHAPE_ONLY="yes" ;;
    -*) die "unknown option $1" ;;
    *) DIR="$1" ;;
  esac
  shift
done
[ -n "$MODE" ] || die "one of --measure, --report, --gate, --write-floor is required."
[ "$SHAPE_ONLY" = "no" ] || [ "$MODE" = "--write-floor" ] || die "--shape-only is only for --write-floor."

DATA_DIR="${DIR:-$DATA_DIR}"
mkdir -p "$DATA_DIR"

case "$MODE" in
  --measure)     measure "$DATA_DIR" ;;
  --report)      report "$DATA_DIR" ;;
  --gate)        gate "$DATA_DIR" ;;
  --write-floor) write_floor "$DATA_DIR" "$SHAPE_ONLY" ;;
esac
