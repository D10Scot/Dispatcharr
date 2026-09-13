#!/usr/bin/env bash
# The mechanical half of the phase's "no third-party Go dependencies" rule
# (spec § Stage 2c, "Third-party Go dependencies: none", line 1731).
#
# Two checks, because either alone has a hole. `go list -m all` prints the
# module graph, which is exactly one line in a zero-dependency module -- it
# catches a `require` that `go mod tidy` has resolved. The go.sum check
# catches the state between adding an import and tidying, where go.sum
# exists and the graph has not been rewritten yet.
#
# Also the backstop the spec names for 2c-1's un-mechanised PR-description
# precondition: a Postgres driver or a Redis client is a third-party module,
# so it fails here regardless of whether anyone read the punch list.
set -euo pipefail

MODULE_ROOT="${1:-relay}"
cd "$MODULE_ROOT"

EXPECTED="github.com/D10Scot/Dispatcharr/relay"

if [ -s go.sum ]; then
  echo "FAILED: ${MODULE_ROOT}/go.sum is non-empty. This module is stdlib-only;" >&2
  echo "        a go.sum means a third-party dependency was added." >&2
  echo "        Spec § Stage 2c: 'This is a rule to defend, not an accident.'" >&2
  exit 1
fi

GRAPH="$(go list -m all)"
if [ "$GRAPH" != "$EXPECTED" ]; then
  echo "FAILED: the module graph is not stdlib-only." >&2
  echo "        expected exactly: ${EXPECTED}" >&2
  echo "        got:" >&2
  printf '%s\n' "$GRAPH" | sed 's/^/          /' >&2
  exit 1
fi

echo "OK: ${MODULE_ROOT} depends on the standard library only."
