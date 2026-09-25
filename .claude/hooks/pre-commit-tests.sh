#!/usr/bin/env bash
# Gate `git commit` on the tests covering whatever is being committed.
#
# Wired two ways, sharing this one script:
#   * Claude Code PreToolUse hook on Bash(git commit*) — fires when Claude commits.
#   * .git/hooks/pre-commit (optional) — fires when a human commits.
# Detected via $1 == "--git-hook", which skips the stdin payload parse.
#
# Backend labels come from the repo's OWN mapping (scripts/ci_backend_test_labels.py),
# so this gate runs exactly what CI would run for the same diff. Sharing the one
# function rather than keeping a second copy is the point: the gate cannot disagree
# with CI, and a routing fix reaches both at once.
#
# Exit 2 blocks the commit. Infrastructure problems (Docker down) do NOT block —
# they warn loudly, because a gate that fails closed on infra just gets bypassed.
set -uo pipefail

# shellcheck source=_hook_common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_hook_common.sh"

CONTAINER="${DISPATCHARR_TEST_CONTAINER:-dispatcharr-testrunner}"

CD_ANCHOR=""
# gate_note_exit <message>: say it in the PreToolUse JSON shape the rest of
# this script uses for warnings, then let the command through. Used before
# the WARNINGS machinery below exists.
gate_note_exit() {
  jq -cn --arg m "$1" '{systemMessage:$m,hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$m}}'
  exit 0
}
if [ "${1:-}" = "--git-hook" ]; then
  CMD="git commit"
else
  CMD="$(jq -r '.tool_input.command // empty')"
  # Issue #278: settings.json used to filter on `Bash(git commit*)` and this
  # line on the literal substring "git commit", so `git -C <dir> commit`
  # matched neither and committed with no gate at all. settings.json now
  # filters on `Bash(git *)` -- every git subcommand, and the harness runs the
  # hook anyway on a command it cannot parse -- and this regex decides: `git`, then
  # any global options (`-C <dir>`, `-c k=v`, `--git-dir=...`, `--no-pager`,
  # ...), then `commit` as a whole word. `git log --grep commit` does not
  # match: `log` is not an option.
  GIT_GLOBAL='([[:space:]]+(-[Cc][[:space:]]+[^[:space:]]+|--(git-dir|work-tree|namespace)([[:space:]]+|=)[^[:space:]]+|--?[A-Za-z][-A-Za-z]*))*'
  COMMIT_RE="(^|[;&|(\`[:space:]])git${GIT_GLOBAL}[[:space:]]+commit([[:space:]]|\$)"
  [[ "$CMD" =~ $COMMIT_RE ]] || exit 0
  # Everything up to and including the matched `git ... commit`.
  UPTO="${CMD%%"${BASH_REMATCH[0]}"*}${BASH_REMATCH[0]}"

  # A Bash call that stages and commits in one invocation (`git add x && git
  # commit`, or the same with `git -C <dir>` on either half) cannot be seen
  # correctly by this hook: PreToolUse fires BEFORE the command executes, so
  # any index/working-tree inspection here reflects state from *before* the
  # `git add` ran too — there is no script-side fix for that, only refusing
  # to guess. Checked before the directory forms below, because it is
  # refused whichever tree the commit lands in.
  ADD_RE="(^|[;&|(\`[:space:]])git${GIT_GLOBAL}[[:space:]]+add([[:space:]]|\$)"
  if [[ "$CMD" == *"git add"* || "$CMD" =~ $ADD_RE ]]; then
    printf 'COMMIT BLOCKED — this command stages files with `git add` and commits in the same Bash call. PreToolUse hooks run before the command executes, so this gate cannot see what gets staged and would silently skip verification.\n\nRun `git add <files>` as its own Bash call, then `git commit` as a separate call.\n' >&2
    exit 2
  fi

  # A plain `git commit` runs inside the worktree it commits to, and the cwd
  # this script inherits already IS that worktree — but PreToolUse fires
  # BEFORE the command executes, so for `cd <dir> && git commit …` the
  # inherited cwd is wherever the PREVIOUS command left it, not <dir>. That is
  # the exact defect class issue #258 fixed for this script's own path,
  # relocated to the inherited cwd instead. Measured: a commit landing in a
  # tree that staged a live_proxy test derived apps.epg.tests from the stale
  # cwd instead. Handle only the documented, anchored simple forms —
  # `cd <dir> && git commit` and (#278) `git -C <dir> commit`, optionally with
  # `-c k=v` options — and refuse to guess at anything more complex (multiple
  # `cd`s, `--git-dir`, a `;` before the `cd`, etc.) since general shell
  # parsing isn't safe here.
  if [[ "$CMD" =~ ^[[:space:]]*cd[[:space:]]+([^[:space:]]+)[[:space:]]*\&\&[[:space:]]*git[[:space:]]+commit ]]; then
    CD_ANCHOR="${BASH_REMATCH[1]}"
  elif [[ "$CMD" =~ ^[[:space:]]*git[[:space:]]+-C[[:space:]]+([^[:space:]]+)([[:space:]]+-c[[:space:]]+[^[:space:]]+)*[[:space:]]+commit([[:space:]]|$) ]]; then
    CD_ANCHOR="${BASH_REMATCH[1]}"
  elif [[ "$UPTO" == *"cd "* || "$UPTO" == *"pushd "* || "$UPTO" == *"-C "* \
          || "$UPTO" == *"--git-dir"* || "$UPTO" == *"--work-tree"* ]]; then
    gate_note_exit "Commit gate: this command changes directory or repository before \`git commit\` in a form other than the documented \`cd <dir> && git commit\` or \`git -C <dir> commit\` (PreToolUse fires before the command runs, so this hook cannot safely determine which tree the commit will land in). Backend/frontend tests were NOT run for this commit."
  fi
  CD_ANCHOR="${CD_ANCHOR%\'}"; CD_ANCHOR="${CD_ANCHOR#\'}"
  CD_ANCHOR="${CD_ANCHOR%\"}"; CD_ANCHOR="${CD_ANCHOR#\"}"
fi

# A `git commit` runs inside the worktree it commits to (and a native
# `.git/hooks/pre-commit` is itself invoked with cwd at the worktree root), so
# the cwd this script inherits is the right anchor for the plain form — NOT
# this script's own location, which under CLAUDE_PROJECT_DIR is the main
# checkout regardless of which worktree is committing (issue #258). For the
# two anchored forms, CD_ANCHOR (parsed above) is used instead; anything else
# already exited above. Resolved before any `cd` below.
#
# Issue #279: a stale CLAUDE_HOOK_REPO_ROOT (status 2) used to end here in a
# silent `exit 0`. It now says so; status 1 (the anchor is in no git repo at
# all) stays quiet, because there is nothing to gate.
RR_ERR_FILE="$(mktemp)"
REPO_ROOT="$(hook_repo_root "${CD_ANCHOR:-.}" 2>"$RR_ERR_FILE")"
RR_ST=$?
RR_ERR="$(cat "$RR_ERR_FILE")"; rm -f "$RR_ERR_FILE"
if [ $RR_ST -eq 2 ]; then
  gate_note_exit "Commit gate: ${RR_ERR} Tests were NOT run for this commit. Unset CLAUDE_HOOK_REPO_ROOT, or point it at a worktree root."
elif [ $RR_ST -ne 0 ]; then
  exit 0
fi
cd "$REPO_ROOT" || gate_note_exit "Commit gate: could not cd into ${REPO_ROOT}. Tests were NOT run for this commit."

WARNINGS=()
note() { WARNINGS+=("$1"); }

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
  elif MISMATCH_OUT="$(hook_container_mismatch "$CONTAINER" "$REPO_ROOT")"; [ $? -eq 1 ]; then
    # Warn, don't block: this script's own header says infra problems warn
    # rather than block (line 14), and blocking here can wedge a legitimate
    # commit — with several worktrees sharing one container, the agent NOT
    # currently holding it could never commit, while the message tells it not
    # to re-point (CLAUDE.md's worktree-occupancy rule says only the agent
    # that owns the tree, or a human, should run start-test-container.sh).
    # Same class as "container not running" above: either way no backend
    # test ran, so both get the same treatment. The PostToolUse hook's
    # block() on this same check is unaffected — a single edit can't wedge
    # a whole worktree's commits the way the gate can.
    EDITED_ROOT="$(printf '%s' "$MISMATCH_OUT" | sed -n 1p)"
    MOUNT_SRC="$(printf '%s' "$MISMATCH_OUT" | sed -n 2p)"
    note "$(printf 'Commit gate: backend tests did NOT run — container '"'"'%s'"'"' is bind-mounted at:\n  %s\nbut this commit is happening in:\n  %s\nRunning tests now would check the right label against the WRONG tree, so they were skipped instead. The commit was NOT verified. Re-point the container (only if another agent is not currently using it — see CLAUDE.md'"'"'s worktree-occupancy rule):\n  cd %s && .claude/hooks/start-test-container.sh' "$CONTAINER" "$MOUNT_SRC" "$EDITED_ROOT" "$EDITED_ROOT")"
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

# ---------- go ----------
# The whole module on commit, not just the edited package: this mirrors what
# go-tests.yml runs, and the same rule the backend gate follows (CI runs the
# whole package, so the gate does too).
#
# The module root is derived from the STAGED PATH by walking up for go.mod,
# not assumed to be "$REPO_ROOT/relay" — Ruling R4, same reasoning as
# run-go-checks.sh. $REPO_ROOT here is already correct as of #280 (the gate
# anchors on its cwd, or on a parsed `cd <dir> &&` prefix), so this is not
# compensating for a bad root; it is declining the separate assumption that
# the module sits at a fixed place under it.
GO_ROOTS="$(printf '%s\n' "$PATHS" | grep '\.go$' | while read -r p; do
  d="$(dirname "$REPO_ROOT/$p")"
  while [ "$d" != "/" ] && [ ! -f "$d/go.mod" ]; do d="$(dirname "$d")"; done
  [ -f "$d/go.mod" ] && printf '%s\n' "$d"
done | sort -u)"
if [ -n "$GO_ROOTS" ]; then
  if ! command -v go >/dev/null 2>&1; then
    note "Commit gate: Go files are staged but go is not on PATH — the Go tests were NOT run. The commit was NOT verified."
  else
    while read -r GR; do
      [ -n "$GR" ] || continue
      OUT="$(cd "$GR" && go build ./... 2>&1 && go vet ./... 2>&1 && go test -race ./... 2>&1)"
      if [ $? -ne 0 ]; then
        FAILED+=("go:${GR##*/}")
        REPORT+="$(printf '\n--- go %s ---\n%s\n' "$GR" "$(printf '%s' "$OUT" | grep -Ev '^(ok|\?)' | head -30)")"
      fi
    done <<< "$GO_ROOTS"
  fi
fi

# ---------- metrics (collectors + build step, no Django) ----------
if printf '%s\n' "$PATHS" | grep -qE '^(metrics/|scripts/metrics/|scripts/run_metrics_tests\.sh)'; then
  OUT="$(scripts/run_metrics_tests.sh all 2>&1)"; ST=$?
  if [ $ST -ne 0 ]; then
    FAILED+=("metrics")
    REPORT+="$(printf '\n--- metrics ---\n%s\n' "$(printf '%s' "$OUT" | tail -30)")"
  fi
  if [ -f metrics/build/__main__.py ]; then
    if [ -x .venv/bin/python ]; then PY=.venv/bin/python; else PY=python3; fi
    VOUT="$("$PY" -m metrics.build --validate-only --curated metrics/curated 2>&1)"
    if [ $? -ne 0 ]; then
      FAILED+=("metrics validate-only")
      REPORT+="$(printf '\n--- metrics validate-only ---\n%s\n' "$(printf '%s' "$VOUT" | tail -40)")"
    fi
  fi
fi

# ---------- dashboard (vitest, dashboard config) ----------
if printf '%s\n' "$PATHS" | grep -q '^dashboard/'; then
  if [ -d frontend/node_modules ] && [ -f frontend/vitest.dashboard.config.js ]; then
    OUT="$(cd frontend && npx vitest --run --config vitest.dashboard.config.js 2>&1)"
    if [ $? -ne 0 ]; then
      FAILED+=("dashboard")
      REPORT+="$(printf '\n--- dashboard ---\n%s\n' "$(printf '%s' "$OUT" | grep -E 'FAIL|✗|Tests ' | head -20)")"
    fi
  else
    note "Commit gate: dashboard/ files are staged but the dashboard vitest config or frontend/node_modules is missing — dashboard tests were NOT run."
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
