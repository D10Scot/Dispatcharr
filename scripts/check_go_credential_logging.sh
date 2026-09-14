#!/usr/bin/env bash
# The Go side of scripts/check_credential_logging.py: every error-typed
# argument to a formatting or logging call in relay/ passes through
# redact.Error or carries a `credential-logging: ok - <reason>` marker.
# relay/internal/credlint/check.go states the rule, its reach and its known
# gaps; this script only runs it from the module root, so the hook and
# go-tests.yml invoke one thing.
#
# Stdlib only, like the module it checks: `go run` builds the checker from
# the module's own source, so there is nothing to install and no version to
# pin.
set -euo pipefail

MODULE_ROOT="${1:-relay}"
cd "$MODULE_ROOT"
exec go run ./internal/credlint ./...
