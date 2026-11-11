#!/usr/bin/env bash
# Tests scripts/check_go_deps.sh (ADR 0011). Run by go-tests.yml's `build` job,
# not lint.yml: it needs the Go toolchain.
#
# Every case builds a throwaway module under mktemp -d. Third-party modules are
# local directories reached by `replace`, so no case touches the network, and
# the child environment is built from an allowlist (never by removing known-bad
# variables): a missing go or a stray GOFLAGS cannot fall through to the host's.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="${CHECK_GO_DEPS:-$HERE/../check_go_deps.sh}"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
fail=0

GO_BIN="$(command -v go)" || { echo "FAIL: no go on PATH; the cases cannot run"; exit 1; }
GOCACHE_DIR="$(go env GOCACHE)"
GOMODCACHE_DIR="$(go env GOMODCACHE)"
CASE_PATH="$(dirname "$GO_BIN"):/usr/bin:/bin"

# run_env <dir> <command...>: the allowlisted child environment.
run_env() {
  local dir="$1"; shift
  ( cd "$dir" && env -i PATH="$CASE_PATH" HOME="$TMP/home" GOCACHE="$GOCACHE_DIR" \
      GOMODCACHE="$GOMODCACHE_DIR" GOTOOLCHAIN=local GOPROXY=off GOFLAGS= \
      GOSUMDB=off GOWORK=off LANG=C "$@" )
}

# Positively assert the child resolves the same go before any case runs.
mkdir -p "$TMP/home"
resolved="$(run_env "$TMP" bash -c 'command -v go')"
if [ "$resolved" != "$GO_BIN" ]; then
  echo "FAIL: the case environment resolves go to '$resolved', want '$GO_BIN'"; exit 1
fi

# mkmod <name> <module-path> <main-imports...>: a module at $TMP/<name> whose
# main imports the given packages. Prints nothing.
mkmod() {
  local name="$1" modpath="$2"; shift 2
  local dir="$TMP/$name"
  mkdir -p "$dir"
  run_env "$dir" go mod init "$modpath" >/dev/null 2>&1 || { echo "FAIL: go mod init $name"; exit 1; }
  {
    echo "package main"; echo
    if [ "$#" -gt 0 ]; then
      echo "import ("; for imp in "$@"; do echo "	_ \"$imp\""; done; echo ")"; echo
    fi
    echo "func main() {}"
  } > "$dir/main.go"
}

# mkdep <name> <module-path> [package-subdir]: a local module to replace to.
mkdep() {
  local name="$1" modpath="$2" sub="${3:-}"
  local dir="$TMP/$name"
  mkdir -p "$dir/$sub"
  printf 'module %s\n\ngo 1.21\n' "$modpath" > "$dir/go.mod"
  printf 'package %s\n' "$(basename "${sub:-$name}")" > "$dir/$sub/x.go"
}

# require <name> <module-path> <dep-dir-name>
require() {
  local dir="$TMP/$1"
  printf '\nrequire %s v0.0.0\n\nreplace %s => ../%s\n' "$2" "$2" "$3" >> "$dir/go.mod"
}

allow() { printf '%b' "$2" > "$TMP/$1/go.allowed-deps"; }

# expect <want-exit> <name> <module-dir-name> [output-substring]
expect() {
  local want="$1" name="$2" dir="$3" sub="${4:-}" out rc
  out="$(run_env "$TMP" bash "$SCRIPT" "$TMP/$dir" 2>&1)"; rc=$?
  if [ "$rc" -ne "$want" ] || { [ -n "$sub" ] && [[ "$out" != *"$sub"* ]]; }; then
    echo "FAIL $name: expected exit $want, got $rc; output: $out"; fail=1
  else
    echo "ok   $name"
  fi
}

# 1. Clean: standard library only, empty allowlist.
mkmod clean example.com/clean fmt
allow clean '# nothing allowed\n'
expect 0 "clean module" clean "OK:"

# 2. A direct requirement the allowlist does not name.
mkdep dep example.org/dep
mkmod unlisted example.com/unlisted example.org/dep
require unlisted example.org/dep dep
allow unlisted ''
expect 1 "unlisted direct requirement" unlisted "example.org/dep"

# 3. The same requirement, listed.
mkmod listed example.com/listed example.org/dep
require listed example.org/dep dep
allow listed '# one dependency\nexample.org/dep\n'
expect 0 "listed requirement" listed "OK:"

# 4. An allowlist line go.mod does not require.
mkmod stale example.com/stale fmt
allow stale 'example.org/gone\n'
expect 1 "stale allowlist line" stale "example.org/gone"

# 5. database/sql linked.
mkmod sql example.com/sql database/sql
allow sql ''
expect 1 "linked database/sql" sql "database/sql"

# 6. A linked package with a redis path segment (listed, so only the ban fires).
mkdep redis example.org/redis
mkmod redisuser example.com/redisuser example.org/redis
require redisuser example.org/redis redis
allow redisuser 'example.org/redis\n'
expect 1 "linked redis-named package" redisuser "links a database or Redis package"

# 7. Positive control: database/sql/driver alone is intentionally NOT banned
# (an interface package the OTel SDK's uuid dependency imports; it opens nothing).
mkmod driveronly example.com/driveronly database/sql/driver
allow driveronly ''
expect 0 "database/sql/driver alone passes" driveronly "OK:"

exit "$fail"
