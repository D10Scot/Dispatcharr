#!/usr/bin/env bash
# Gate `git commit` on the tests covering whatever is being committed.
#
# Wired two ways, sharing this one script:
#   * Claude Code PreToolUse hook on Bash(git commit*) — fires when Claude commits.
#   * .git/hooks/pre-commit (optional) — fires when a human commits.
# Detected via $1 == "--git-hook", which skips the stdin payload parse.
#
# Backend labels come from the repo's OWN mapping (scripts/ci_backend_test_labels.py),
# so this gate runs exactly what CI would run for the same diff — including its two
# known routing defects, which is deliberate: the gate should not disagree with CI.
#
# Exit 2 blocks the commit. Infrastructure problems (Docker down) do NOT block —
# they warn loudly, because a gate that fails closed on infra just gets bypassed.
set -uo pipefail

REPO_ROOT="${CLAUDE_HOOK_REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
CONTAINER="${DISPATCHARR_TEST_CONTAINER:-dispatcharr-testrunner}"
cd "$REPO_ROOT" || exit 0

if [ "${1:-}" = "--git-hook" ]; then
  CMD="git commit"
else
  CMD="$(jq -r '.tool_input.command // empty')"
  case "$CMD" in *"git commit"*) ;; *) exit 0 ;; esac
fi

WARNINGS=()
note() { WARNINGS+=("$1"); }

# A Bash call that stages and commits in one invocation (`git add x && git
# commit`) cannot be seen correctly by this hook: PreToolUse fires BEFORE the
# command executes, so any index/working-tree inspection here reflects state
# from *before* the `git add` ran too — there is no script-side fix for that,
# only refusing to guess. Force the two steps apart so the gate can see what
# is actually being committed.
if [[ "$CMD" == *"git add"* ]]; then
  printf 'COMMIT BLOCKED — this command stages files with `git add` and commits in the same Bash call. PreToolUse hooks run before the command executes, so this gate cannot see what gets staged and would silently skip verification.\n\nRun `git add <files>` as its own Bash call, then `git commit` as a separate call.\n' >&2
  exit 2
fi

# `git commit -a` bypasses the index, so compare against HEAD in that case.
case "$CMD" in
  *" -a"*|*"--all"*) PATHS="$(git diff --name-only HEAD)" ;;
  *)                 PATHS="$(git diff --cached --name-only)" ;;
esac
# An explicit-pathspec commit (`git commit -m x file.py`) commits that file's
# current content regardless of whether it was ever staged, which can leave
# $PATHS empty even though real changes are being committed. Union in every
# locally modified/untracked path (as of before this command, same caveat as
# above) so the gate can't be bypassed by how the commit is invoked — this
# widens scope slightly (an unrelated dirty file gets tested too) but that is
# the safe direction to err in.
PATHS="$(printf '%s\n%s\n' "$PATHS" "$(git status --porcelain --untracked-files=all | cut -c4-)" | sed '/^$/d' | sort -u)"
[ -n "$PATHS" ] || exit 0

FAILED=()
REPORT=""

# ---------- backend ----------
MAPPER_OUT="$(printf '%s\n' "$PATHS" | python3 scripts/ci_backend_test_labels.py 2>&1)"
MAPPER_ST=$?
if [ $MAPPER_ST -ne 0 ]; then
  note "Commit gate: could not map staged paths to backend test labels — scripts/ci_backend_test_labels.py exited ${MAPPER_ST}. Backend tests were NOT verified for this commit."$'\n'"${MAPPER_OUT}"
  LABELS=""
else
  LABELS="$(printf '%s' "$MAPPER_OUT" | jq -r '.[]?' 2>/dev/null)"
fi
if [ -n "$LABELS" ]; then
  if ! docker exec "$CONTAINER" true >/dev/null 2>&1; then
    note "Commit gate: backend tests did NOT run — container '${CONTAINER}' is not running (start it with .claude/hooks/start-test-container.sh). The commit was NOT verified."
  else
    while read -r L; do
      [ -n "$L" ] || continue
      docker exec "$CONTAINER" redis-cli flushall >/dev/null 2>&1
      OUT="$(docker exec \
        -e TEST_USE_SQLITE= -e POSTGRES_HOST=/var/run/postgresql \
        -e POSTGRES_DB=dispatcharr -e POSTGRES_USER=dispatch -e POSTGRES_PASSWORD=secret \
        -e REDIS_HOST=localhost -e REDIS_PORT=6379 -e REDIS_DB=0 \
        -e DJANGO_SECRET_KEY=hook-test-secret -e DISPATCHARR_LOG_LEVEL=WARNING \
        "$CONTAINER" /dispatcharrpy/bin/python manage.py test --keepdb "$L" -v1 2>&1)"
      if [ $? -ne 0 ]; then
        FAILED+=("$L")
        REPORT+="$(printf '\n--- %s ---\n%s\n' "$L" "$(printf '%s' "$OUT" | awk '/^(FAIL|ERROR):/{f=1} f' | head -25)")"
      fi
    done <<< "$LABELS"
  fi
fi

# ---------- frontend ----------
if printf '%s\n' "$PATHS" | grep -q '^frontend/'; then
  if [ -d frontend/node_modules ]; then
    OUT="$(cd frontend && npx vitest --run 2>&1)"
    if [ $? -ne 0 ]; then
      FAILED+=("frontend")
      REPORT+="$(printf '\n--- frontend ---\n%s\n' "$(printf '%s' "$OUT" | grep -E 'FAIL|✗|Tests ' | head -20)")"
    fi
  else
    note "Commit gate: frontend files are staged but frontend/node_modules is missing — frontend tests were NOT run. Run 'cd frontend && npm install'."
  fi
fi

if [ ${#FAILED[@]} -gt 0 ]; then
  printf 'COMMIT BLOCKED — tests failing for: %s\n%s\n\nFix these, or if the failure pre-existed this change, say so explicitly rather than committing over it.\n' \
    "${FAILED[*]}" "$REPORT" >&2
  [ ${#WARNINGS[@]} -eq 0 ] || printf '\n%s\n' "${WARNINGS[@]}" >&2
  exit 2
fi
if [ ${#WARNINGS[@]} -gt 0 ]; then
  MSG="$(printf '%s\n\n' "${WARNINGS[@]}")"
  jq -cn --arg m "$MSG" '{systemMessage:$m,hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$m}}'
fi
exit 0
