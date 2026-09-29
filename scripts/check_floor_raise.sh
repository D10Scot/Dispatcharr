#!/usr/bin/env bash
# Admits a declared, bounded rise of the Go coverage floor's `missing=` and
# nothing else (owner ruling R21, Phase 4 spec D20; CLAUDE.md § Testing).
#
#   scripts/check_floor_raise.sh <base-missing> <head-floor-file>
#
# NEW <= OLD passes silently. NEW > OLD passes only when the head floor carries
#   raise_from=<N>    N == OLD, so a declaration left by an earlier PR is useless
#   raise_listed=<M>  M a positive integer: the uncovered statements the PR body lists
# and NEW <= raise_from + raise_listed. Exit 0 = admitted, 1 = refused.
set -euo pipefail

if [ $# -ne 2 ]; then
  echo "usage: check_floor_raise.sh <base-missing> <head-floor-file>" >&2
  exit 2
fi
OLD="$1"
FLOOR="$2"

field() { grep -E "^$1=" "$FLOOR" | head -1 | cut -d= -f2- || true; }
# No leading zeros (bash arithmetic would read them as octal) and at most nine
# digits, so the sum below cannot overflow.
is_int() { [[ "$1" =~ ^(0|[1-9][0-9]{0,8})$ ]]; }

NEW="$(field missing)"
if ! is_int "$OLD" || ! is_int "$NEW"; then
  echo "floor missing= is not a decimal integer (base=[$OLD] head=[$NEW])"
  exit 1
fi
echo "floor: base=$OLD head=$NEW"
if [ "$NEW" -le "$OLD" ]; then
  exit 0
fi

echo "The floor was raised ($OLD -> $NEW): more missed statements are now permitted."
FROM="$(field raise_from)"
LISTED="$(field raise_listed)"
if ! is_int "$FROM"; then
  echo "A rise must be declared: raise_from=<base missing> is missing or not an integer ([$FROM])."
  exit 1
fi
if [ "$FROM" -ne "$OLD" ]; then
  echo "raise_from=$FROM does not equal the base floor's missing=$OLD: a stale declaration."
  exit 1
fi
if ! is_int "$LISTED" || [ "$LISTED" -le 0 ]; then
  echo "A rise must be declared: raise_listed=<positive integer> is missing or invalid ([$LISTED])."
  exit 1
fi
CAP=$((FROM + LISTED))
echo "raise_from=$FROM raise_listed=$LISTED cap=$CAP head=$NEW"
if [ "$NEW" -gt "$CAP" ]; then
  echo "missing=$NEW exceeds raise_from + raise_listed = $CAP: the rise is more than the PR lists."
  exit 1
fi
echo "Rise admitted: $((NEW - OLD)) statements, within the $LISTED the PR lists."
