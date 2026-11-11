#!/usr/bin/env bash
# The relay's dependency rule (ADR 0011, observability spec D2). Replaced
# scripts/check_go_stdlib_only.sh. Three checks, each printing what it found:
#
#   1. The module's DIRECT requirements equal relay/go.allowed-deps, in both
#      directions. Indirect modules follow from the direct ones and are
#      covered by govulncheck, OSV-Scanner, Trivy and Grype instead.
#   2. The packages the shipped binary LINKS (`go list -deps .`, the question
#      scripts/coverage_relay_go.sh also asks) include no database/sql and no
#      Redis or Postgres driver. database/sql/driver is NOT banned: it is an
#      interface package that github.com/google/uuid (linked by the OTel SDK)
#      imports for its Value method, and it opens nothing.
#   3. go.mod and go.sum are tidy, the state the old script's empty-go.sum
#      check existed to catch.
set -euo pipefail

MODULE_ROOT="${1:-relay}"
cd "$MODULE_ROOT"

ALLOWLIST="go.allowed-deps"
[ -f "$ALLOWLIST" ] || { echo "FAILED: ${MODULE_ROOT}/${ALLOWLIST} is missing (ADR 0011)." >&2; exit 1; }

MAIN="$(go list -m)"
status=0

# The query is its own statement so a failure of `go list` exits non-zero under
# set -e; only the filter may be empty (grep -v exits 1 on no output).
module_paths="$(go list -m -f '{{if not .Indirect}}{{.Path}}{{end}}' all)"
direct="$(printf '%s\n' "$module_paths" | grep -vxF "$MAIN" | LC_ALL=C sort -u || true)"
allowed="$(grep -vE '^[[:space:]]*(#|$)' "$ALLOWLIST" | LC_ALL=C sort -u || true)"
unexpected="$(LC_ALL=C comm -23 <(printf '%s\n' "$direct" | sed '/^$/d') <(printf '%s\n' "$allowed" | sed '/^$/d'))"
missing="$(LC_ALL=C comm -13 <(printf '%s\n' "$direct" | sed '/^$/d') <(printf '%s\n' "$allowed" | sed '/^$/d'))"
if [ -n "$unexpected" ]; then
  echo "FAILED: direct requirements not in ${MODULE_ROOT}/${ALLOWLIST} (ADR 0011):" >&2
  printf '%s\n' "$unexpected" | sed 's/^/          /' >&2
  status=1
fi
if [ -n "$missing" ]; then
  echo "FAILED: ${MODULE_ROOT}/${ALLOWLIST} names modules go.mod does not require directly:" >&2
  printf '%s\n' "$missing" | sed 's/^/          /' >&2
  status=1
fi

linked="$(go list -deps .)"
banned="$(printf '%s\n' "$linked" | grep -iE '^database/sql$|(^|/)redis|^github\.com/(lib/pq|jackc/|go-sql-driver/|mattn/go-sqlite3)' || true)"
if [ -n "$banned" ]; then
  echo "FAILED: ${MODULE_ROOT} links a database or Redis package (ADR 0011):" >&2
  printf '%s\n' "$banned" | sed 's/^/          /' >&2
  status=1
fi

if ! tidy="$(go mod tidy -diff 2>&1)"; then
  echo "FAILED: go.mod/go.sum are not tidy; run 'go mod tidy' in ${MODULE_ROOT}:" >&2
  printf '%s\n' "$tidy" | sed 's/^/          /' >&2
  status=1
fi

[ "$status" -eq 0 ] && echo "OK: ${MODULE_ROOT}'s direct requirements match ${ALLOWLIST}, and it links no database or Redis package."
exit "$status"
