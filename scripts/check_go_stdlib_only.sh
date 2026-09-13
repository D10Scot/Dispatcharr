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

# Spec § Stage 2c's second invariant: "The Go binary links no Redis client."
#
# The module-graph check above catches an IMPORTED one and nothing else. This
# catches the shape it cannot: a Redis client written inside this module, in
# the standard library, which is entirely possible and would satisfy every
# other gate in this repo.
#
# `go list -deps` and not a text scan, and the difference is not style. The
# invariant is about what the BINARY LINKS, and a text scan cannot tell that
# from a comment: several files in relay/ legitimately name Redis while
# explaining what D2 deleted, and `redis_chunk_ttl` is a settings key that is
# on the wire and CANNOT be renamed, because D5 is strict parity and a
# settings key is visible in the UI. A grep would need an exclusion list, and
# an exclusion that names one string is an exclusion somebody widens.
if go list -deps ./... | grep -qiE '(^|/)redis'; then
  echo "FAILED: ${MODULE_ROOT} links a package named for Redis." >&2
  echo "        Spec § Stage 2c: 'The Go binary links no Redis client.'" >&2
  echo "        D2 puts the ring buffer in process memory; the live path" >&2
  echo "        reaches no Redis at all, in any form." >&2
  go list -deps ./... | grep -iE '(^|/)redis' | sed 's/^/          /' >&2
  exit 1
fi

echo "OK: ${MODULE_ROOT} depends on the standard library only."
