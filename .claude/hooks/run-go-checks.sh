#!/usr/bin/env bash
# Claude Code PostToolUse hook — verify the Go module a just-edited .go file
# belongs to.
#
# Four checks, all blocking, all scoped to that module:
#
#   build        go build ./...          the whole module
#   vet          go vet ./...            the whole module
#   lint         golangci-lint run       the whole module, zero findings
#   credlint     go run ./internal/credlint ./...   the whole module, zero findings
#   tests        go test -race ./<pkg>   the edited file's package only
#
# Zero lint findings is a ratchet, the same rule as zizmor's: the module
# starts clean and touching a file means leaving it clean. -race is not
# optional (spec § Testing): this phase moves the relay from gevent's single
# OS thread to parallel goroutines, so a data race becomes possible for the
# first time, and -race is the cheapest check for exactly that class.
#
# THE MODULE ROOT COMES FROM THE EDITED FILE'S OWN PATH, by walking up for
# go.mod — the same anchor _hook_common.sh's hook_repo_root() uses, resolving
# a different thing. That helper returns the REPO root; `go build ./...` needs
# the MODULE root, which is <repo>/relay and is defined by where go.mod sits,
# not by where .git does. Hence the walk rather than a call.
#
# CLAUDE_HOOK_REPO_ROOT is deliberately NOT honoured here, unlike
# hook_repo_root() -- a review found that starting the go.mod WALK there
# breaks it silently: the variable is meant to pin the REPO root, which has
# no go.mod (relay/ does), so the walk climbs from the repo root to "/",
# MODULE_ROOT ends up empty, and the script exits 0 with no output at all --
# the exact "silent skip indistinguishable from a pass" this header warns
# against, verified with a real compile error present and the override set.
# The module root is a property of the file, not of the session, and this
# script has no lever to override that.
#
# hook_container_mismatch() is deliberately NOT used: these checks run on the
# host, with no container and no bind mount, so there is nothing for it to
# judge. Its absence here is a decision, not an omission.
#
# Blocking failures exit 2, which feeds the output back to Claude. "Could not
# run" exits 0 but is stated loudly — a silent skip is indistinguishable from
# a pass.
set -uo pipefail

# shellcheck source=_hook_common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_hook_common.sh"

GOLANGCI_EXPECTED_VERSION="2.13.2"

INPUT="$(cat)"
FILE="$(printf '%s' "$INPUT" | jq -r '.tool_response.filePath // .tool_input.file_path // empty')"
[ -n "$FILE" ] || exit 0
case "$FILE" in *.go) ;; *) exit 0 ;; esac
[ -f "$FILE" ] || exit 0

# Claude Code hands the hook an absolute path, exactly as the merged
# run-affected-tests.sh assumes when it does `dirname "$FILE"`. No
# relative-path branch: it would be dead code, and if it ever fired it would
# resolve against the working directory this repo documents as unreliable
# across concurrent sessions — the one input a hook must never trust.
#
# hook_canon_path resolves symlinks (pwd -P), so a /private-prefixed macOS
# spelling and a plain one compare equal in the prefix strip below. PKG_DIR
# is always the edited file's own directory, and the go.mod walk always
# starts there -- see the header comment for why no override is honoured.
PKG_DIR="$(hook_canon_path "$(dirname "$FILE")")"
[ -n "$PKG_DIR" ] || exit 0

# Walk up for go.mod. The module root is a property of the file, not of the
# session.
MODULE_ROOT="$PKG_DIR"
while [ ! -f "$MODULE_ROOT/go.mod" ]; do
  [ "$MODULE_ROOT" = "/" ] && { MODULE_ROOT=""; break; }
  MODULE_ROOT="$(dirname "$MODULE_ROOT")"
done
if [ -z "$MODULE_ROOT" ]; then
  exit 0   # a .go file outside any module; nothing to check
fi

NOTES=()
BLOCK_TITLE=""
BLOCK_BODY=""
note()  { NOTES+=("$1"); }
block() { [ -n "$BLOCK_TITLE" ] || { BLOCK_TITLE="$1"; BLOCK_BODY="$2"; }; }

if ! command -v go >/dev/null 2>&1; then
  note "Did NOT check ${FILE##*/} — go is not on PATH. The Go module was NOT verified; say so rather than describing the work as done."
else
  OUT="$(cd "$MODULE_ROOT" && go build ./... 2>&1)"
  if [ $? -ne 0 ]; then
    block "go build failed in ${MODULE_ROOT}" "$(printf '%s' "$OUT" | head -30)"
  else
    OUT="$(cd "$MODULE_ROOT" && go vet ./... 2>&1)"
    if [ $? -ne 0 ]; then
      block "go vet failed in ${MODULE_ROOT}" "$(printf '%s' "$OUT" | head -30)"
    else
      # The edited file's own package, relative to the module root. The whole
      # module runs on commit; per-edit this is the fast, scoped check.
      # Both sides went through hook_canon_path, so the prefix strip is
      # comparing like with like. A file at the module root strips to "",
      # and "./" is a valid package spec for it.
      PKG="./${PKG_DIR#"$MODULE_ROOT"/}"
      [ "$PKG" = "./$PKG_DIR" ] && PKG="./..."
      OUT="$(cd "$MODULE_ROOT" && go test -race "$PKG" 2>&1)"
      if [ $? -ne 0 ]; then
        block "go test -race ${PKG} failed" "$(printf '%s' "$OUT" | grep -Ev '^(ok|\?)' | head -40)"
      else
        printf '%s\n' "$OUT" | grep -E '^(ok|---|PASS|FAIL)' | head -3
      fi
    fi
  fi
fi

if [ -z "$BLOCK_TITLE" ]; then
  # The credential-logging guard, the Go side of scripts/
  # check_credential_logging.py: zero findings is a ratchet like the
  # linter's. Run through the same script go-tests.yml runs, so the two
  # cannot disagree. It is built from the module's own source by `go run`,
  # so there is nothing to install and no version to pin.
  OUT="$(cd "$MODULE_ROOT" && go run ./internal/credlint ./... 2>&1)"
  if [ $? -ne 0 ]; then
    block "credential-logging findings in ${MODULE_ROOT}" \
          "$(printf '%s' "$OUT" | head -30)"$'\n\n'"Every error-typed log or format argument passes through redact.Error, or carries '// credential-logging: ok - <reason>'. relay/internal/credlint/check.go states the rule."
  fi
fi

if [ -z "$BLOCK_TITLE" ]; then
  if command -v golangci-lint >/dev/null 2>&1; then
    # Keep in sync with the pinned `version:` in go-tests.yml — that is the
    # whole point of this check. A silent version mismatch is worse than no
    # check: it lets local and CI disagree about what is clean.
    ACTUAL="$(golangci-lint --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)"
    if [ -n "$ACTUAL" ] && [ "$ACTUAL" != "$GOLANGCI_EXPECTED_VERSION" ]; then
      note "golangci-lint on PATH is ${ACTUAL}, but go-tests.yml pins ${GOLANGCI_EXPECTED_VERSION} — local and CI findings can disagree. Bump both together."
    fi
    OUT="$(cd "$MODULE_ROOT" && golangci-lint run ./... 2>&1)"
    if [ $? -ne 0 ]; then
      block "golangci-lint findings in ${MODULE_ROOT}" \
            "$(printf '%s' "$OUT" | head -30)"$'\n\n'"Zero findings is a ratchet here, the same rule as zizmor's for workflows."
    fi
  else
    note "Did NOT lint ${MODULE_ROOT} — golangci-lint is not installed. Install it with 'brew install golangci-lint'."
  fi
fi

if [ ${#NOTES[@]} -gt 0 ]; then
  MSG="$(printf '%s\n\n' "${NOTES[@]}")"
  jq -cn --arg m "$MSG" '{systemMessage:$m,hookSpecificOutput:{hookEventName:"PostToolUse",additionalContext:$m}}'
fi
if [ -n "$BLOCK_TITLE" ]; then
  printf 'FAILED: %s\nFix this before continuing; do not describe the work as done.\n\n%s\n' \
    "$BLOCK_TITLE" "$BLOCK_BODY" >&2
  exit 2
fi
exit 0
