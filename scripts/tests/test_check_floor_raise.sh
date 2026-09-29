#!/usr/bin/env bash
# Tests scripts/check_floor_raise.sh. Run by lint.yml's `floor-raise-tests` job.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="${CHECK_FLOOR_RAISE:-$HERE/../check_floor_raise.sh}"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
fail=0

# expect <want-exit> <name> <old> <floor-body> [output-substring]
expect() {
  local want="$1" name="$2" old="$3" body="$4" sub="${5:-}" out rc
  printf '%b' "$body" > "$TMP/floor"
  out="$(bash "$SCRIPT" "$old" "$TMP/floor" 2>&1)"; rc=$?
  if [ "$rc" -ne "$want" ] || { [ -n "$sub" ] && [[ "$out" != *"$sub"* ]]; }; then
    echo "FAIL $name: exit $rc (want $want), output: $out"; fail=1
  else
    echo "ok   $name"
  fi
}

expect 0 "unchanged"                     589 'missing=589\n'
expect 0 "lowered"                       589 'missing=500\n'
expect 0 "declared rise within cap"      589 'missing=687\nraise_from=589\nraise_listed=147\n' "Rise admitted"
expect 0 "rise exactly at cap"           589 'missing=736\nraise_from=589\nraise_listed=147\n'
expect 1 "no declaration"                589 'missing=687\n' "must be declared"
expect 1 "stale raise_from"              589 'missing=687\nraise_from=500\nraise_listed=200\n' "stale"
expect 1 "rise over the cap"             589 'missing=737\nraise_from=589\nraise_listed=147\n' "exceeds"
expect 1 "raise_listed zero"             589 'missing=687\nraise_from=589\nraise_listed=0\n' "positive integer"
expect 1 "raise_listed not an integer"   589 'missing=687\nraise_from=589\nraise_listed=9x\n' "raise_listed"
expect 1 "raise_from missing"            589 'missing=687\nraise_listed=147\n' "raise_from"
expect 1 "head missing= garbage"         589 'missing=<MAX>\n' "not a decimal"
expect 1 "key only in a comment"         589 'missing=700\n# raise_from=589\n# raise_listed=147\n' "must be declared"
expect 1 "duplicate missing, higher first" 589 'missing=9000\nmissing=589\n' "must be declared"
expect 0 "duplicate raise_listed, first wins" 589 'missing=700\nraise_from=589\nraise_listed=147\nraise_listed=1\n'
expect 1 "duplicate raise_listed, first is small" 589 'missing=700\nraise_from=589\nraise_listed=1\nraise_listed=147\n' "exceeds"
expect 1 "raise_from leading zero"        589 'missing=687\nraise_from=0589\nraise_listed=147\n' "raise_from"
expect 1 "raise_listed leading zero"      589 'missing=687\nraise_from=589\nraise_listed=0147\n' "positive integer"
expect 1 "raise_listed overflow"          589 'missing=687\nraise_from=589\nraise_listed=99999999999999999999\n' "positive integer"

exit "$fail"
