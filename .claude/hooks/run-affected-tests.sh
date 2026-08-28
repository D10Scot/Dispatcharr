#!/usr/bin/env bash
# Claude Code PostToolUse hook — verify whatever file was just edited.
#
# Seven checks, all scoped to the edited file:
#
#   tests        *tests/test_*.py     run the whole package   (blocking)
#                frontend/*.test.jsx  run that file           (blocking)
#   migrations   */models.py          makemigrations --check  (blocking)
#   boot         live_proxy leaves    manage.py check         (blocking)
#   typecheck    e2e{,-upstream}/*.ts tsc --noEmit, that pkg  (blocking)
#   lint         frontend/*.js(x)     eslint that file        (advisory)
#   actions      workflows/action.yml zizmor, whole file      (blocking)
#   secrets      any *.py             credential-logging grep (advisory)
#
# All but zizmor and typecheck are deliberately independent of the repo's
# pre-existing backlog. Those two are ratchets: they hold the whole edited
# file (or package) clean, because there is nothing to tolerate — the
# workflow backlog was worked off, and both e2e packages typecheck clean.
#
# Backend work happens in a warm local container (see start-test-container.sh).
# Real PostgreSQL is required: a migration uses the PG-only `~` regex operator,
# so TEST_USE_SQLITE dies with "near \"~\": syntax error".
#
# Blocking failures exit 2, which feeds the output back to Claude. Advisory
# findings and "could not run" both exit 0 but are stated loudly — a silent
# skip is indistinguishable from a pass, which is this repo's existing CI
# failure mode.
set -uo pipefail

REPO_ROOT="${CLAUDE_HOOK_REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
CONTAINER="${DISPATCHARR_TEST_CONTAINER:-dispatcharr-testrunner}"
cd "$REPO_ROOT" || exit 0

FILE="$(jq -r '.tool_response.filePath // .tool_input.file_path // empty')"
[ -n "$FILE" ] || exit 0
case "$FILE" in
  "$REPO_ROOT"/*) REL="${FILE#"$REPO_ROOT"/}" ;;
  /*) exit 0 ;;
  *) REL="$FILE" ;;
esac
[ -f "$FILE" ] || exit 0

NOTES=()          # advisory, never blocks
BLOCK_TITLE=""
BLOCK_BODY=""

note()  { NOTES+=("$1"); }
block() { [ -n "$BLOCK_TITLE" ] || { BLOCK_TITLE="$1"; BLOCK_BODY="$2"; }; }

_container_up=""
container_ok() {
  [ -n "$_container_up" ] || {
    if docker exec "$CONTAINER" true >/dev/null 2>&1; then _container_up=yes; else _container_up=no; fi
  }
  [ "$_container_up" = yes ]
}
dexec() {
  docker exec \
    -e TEST_USE_SQLITE= -e POSTGRES_HOST=/var/run/postgresql \
    -e POSTGRES_DB=dispatcharr -e POSTGRES_USER=dispatch -e POSTGRES_PASSWORD=secret \
    -e REDIS_HOST=localhost -e REDIS_PORT=6379 -e REDIS_DB=0 \
    -e DJANGO_SECRET_KEY=hook-test-secret -e DISPATCHARR_LOG_LEVEL=WARNING \
    "$CONTAINER" /dispatcharrpy/bin/python "$@" 2>&1
}

# ---------------------------------------------------------------- secrets ---
# Provider credentials are currently logged at INFO (vod_proxy/views.py:628,
# m3u/tasks.py:3084) — Xtream URLs carry the password in the path. Advisory,
# because "is this line a leak" is a judgement call, not a rule.
if [[ "$REL" == *.py ]]; then
  HITS="$(grep -nE 'logger\.(info|debug|warning|error|exception)\(' "$FILE" 2>/dev/null \
          | grep -E 'request\.headers|request\.META|get_full_path|\bpassword\b|api_key|\btoken\b|_url\b|url\}' \
          | head -5)"
  [ -z "$HITS" ] || note "Possible credential logging in ${REL} — Xtream URLs carry the password in the path, and this repo already leaks them at INFO. Check these lines redact before logging:"$'\n'"${HITS}"
fi

# ------------------------------------------------------------- migrations ---
if [[ "$REL" == */models.py || "$REL" == models.py ]]; then
  MOD="${REL%/models.py}"; MOD="${MOD//\//.}"
  if container_ok; then
    OUT="$(dexec .claude/hooks/_pending_migrations.py "$MOD")"; ST=$?
    case $ST in
      0) ;;
      1) block "$MOD has model changes with no migration" \
               "$(printf '%s' "$OUT" | awk '/^Migrations for/{f=1} f' | head -20)"$'\n\n'"Generate it with: python manage.py makemigrations ${MOD##*.}" ;;
      *) note "Could not check migrations for ${MOD}: $(printf '%s' "$OUT" | tail -2)" ;;
    esac
  else
    note "Did NOT check migrations for ${MOD} — container '${CONTAINER}' is not running."
  fi
fi

# -------------------------------------------------------------- boot check ---
# apps/channels/models.py:6-7 imports these two leaf modules at module level, so
# one added import here stops Django booting for every migration and command.
case "$REL" in
  apps/proxy/live_proxy/constants.py|apps/proxy/live_proxy/redis_keys.py)
    if container_ok; then
      OUT="$(dexec manage.py check)"; [ $? -eq 0 ] ||
        block "django check failed after editing ${REL}" \
              "$(printf '%s' "$OUT" | grep -E 'Error|error:' | head -12)"$'\n\n'"apps/channels/models.py imports this module at module level; a cycle here breaks every management command."
    else
      note "Did NOT run 'manage.py check' after editing ${REL} — container '${CONTAINER}' is not running."
    fi
    ;;
esac

# -------------------------------------------------------------------- lint ---
# Advisory: 112 pre-existing errors across 76 files mean blocking would punish
# touching legacy code rather than improve new code. Flip note->block below if
# you would rather hold every edited file to a clean bill.
if [[ "$REL" == frontend/*.js || "$REL" == frontend/*.jsx ]] && [ -d frontend/node_modules ]; then
  OUT="$(cd frontend && npx eslint "${REL#frontend/}" 2>&1)"
  [ -z "$OUT" ] || note "eslint on ${REL} (CI has the linter commented out, so nothing else reports this):"$'\n'"$(printf '%s' "$OUT" | head -15)"
fi

# ----------------------------------------------------------------- actions ---
# zizmor's defaults already encode three rules this repo states by hand: a
# blanket hash-pin policy (unpinned-uses), persist-credentials (artipacked) and
# least-privilege permissions (excessive-permissions). No zizmor config is
# needed to get them, so there deliberately isn't one. Suppress a considered
# exception with a trailing '# zizmor: ignore[audit-name]' comment on the line.
#
# Blocking on every finding in the edited file, legacy included: the workflows
# carry a real backlog and the point is to clear it, so touching a file means
# leaving it clean. Add --min-severity=low below to stop informational findings
# from blocking.
#
# Exit codes: 0 clean, 14 findings, anything else means zizmor itself failed.
#
# Online audits are ON. impostor-commit is the reason: it catches a SHA that
# belongs to some other repository — a pin that looks genuine and isn't, which
# is the exact failure mode the pinning rule warns about, and which the offline
# run cannot see at all (verified: offline reports nothing on a cross-repo SHA).
# known-vulnerable-actions and stale-action-refs come with it. All three only
# have something to say about hash-pinned actions, so they find nothing until
# the pinning sweep lands — this is insurance for that work, not a win today.
#
# zizmor reads the token from the environment; gh keeps it in the keyring, so
# it has to be handed over explicitly. Passed as an env var rather than
# --gh-token so it never shows up in ps. No token means no online audits, which
# is said out loud rather than silently downgraded. ZIZMOR_HOOK_OFFLINE=1 opts
# out — deliberately not zizmor's own ZIZMOR_OFFLINE, which is a true/false flag
# this would collide with.
case "$REL" in
  .github/workflows/*.yml|.github/workflows/*.yaml|\
  .github/dependabot.yml|.github/dependabot.yaml|\
  action.yml|action.yaml|*/action.yml|*/action.yaml)
    if command -v zizmor >/dev/null 2>&1; then
      # Keep in sync with the pinned `version:` in actions-lint.yml — that's
      # the whole point of this check. A silent PATH mismatch here is worse
      # than no check: it lets local and CI disagree about what's clean.
      ZIZMOR_EXPECTED_VERSION="1.29.0"
      ZIZMOR_ACTUAL_VERSION="$(zizmor --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)"
      if [ -n "$ZIZMOR_ACTUAL_VERSION" ] && [ "$ZIZMOR_ACTUAL_VERSION" != "$ZIZMOR_EXPECTED_VERSION" ]; then
        note "zizmor on PATH is ${ZIZMOR_ACTUAL_VERSION}, but actions-lint.yml pins ${ZIZMOR_EXPECTED_VERSION} — local and CI findings can disagree. Run 'brew upgrade zizmor' (or reinstall to the pinned version)."
      fi
      ZFLAGS=(--no-progress --format=github)
      ZTOKEN="${GH_TOKEN:-${GITHUB_TOKEN:-}}"
      [ -n "$ZTOKEN" ] || ZTOKEN="$(gh auth token 2>/dev/null)"
      if [ "${ZIZMOR_HOOK_OFFLINE:-}" = 1 ]; then
        ZFLAGS+=(--no-online-audits)
      elif [ -z "$ZTOKEN" ]; then
        ZFLAGS+=(--no-online-audits)
        note "zizmor ran WITHOUT its online audits on ${REL} — no GitHub token (tried \$GH_TOKEN, \$GITHUB_TOKEN, 'gh auth token'). impostor-commit is the one that catches a SHA belonging to another repo, so a pin cannot be verified as genuine here. Run 'gh auth login' to restore it."
      fi
      # An empty GH_TOKEN is not the same as an unset one: zizmor rejects the
      # empty string outright, so unset it rather than pass it through.
      if [ -n "$ZTOKEN" ]; then
        OUT="$(GH_TOKEN="$ZTOKEN" zizmor "${ZFLAGS[@]}" "$REL" 2>&1)"; ST=$?
      else
        OUT="$(env -u GH_TOKEN -u GITHUB_TOKEN zizmor "${ZFLAGS[@]}" "$REL" 2>&1)"; ST=$?
      fi
      case $ST in
        0) ;;
        14) block "zizmor findings in ${REL}" \
                  "$(printf '%s\n' "$OUT" | grep '^::' | sed -E 's/^::[a-z]+ [^:]*::/  /')"$'\n\n'"Docs: https://docs.zizmor.sh/audits/ — 'zizmor --fix .github/workflows/' applies the safe fixes." ;;
        *) note "Did NOT lint ${REL} with zizmor (exit ${ST}): $(printf '%s' "$OUT" | tail -3)" ;;
      esac
    else
      note "Did NOT lint ${REL} — zizmor is not installed. Install it with 'brew install zizmor'."
    fi
    ;;
esac

# --------------------------------------------------------------- typecheck ---
# Blocking, unlike the eslint check above, and for the same reason zizmor
# blocks: `tsc --noEmit` exits 0 in both e2e packages today, so this is a
# ratchet rather than a punishment for touching legacy code.
#
# It matters more than its size suggests. Nothing else in this hook matches
# *.ts, and the pre-commit gate routes only backend labels and frontend/ — so
# without this, everything under e2e/ and e2e-upstream/ is edited with no
# automated check of any kind. A full Playwright run is far too slow for a
# hook; a typecheck is about a second and catches the class of mistake that
# otherwise surfaces as a CI failure ten minutes later.
case "$REL" in
  e2e/*.ts|e2e-upstream/*.ts)
    PKG_DIR="${REL%%/*}"
    if [ -d "$PKG_DIR/node_modules" ]; then
      OUT="$(cd "$PKG_DIR" && npm run --silent typecheck 2>&1)"
      if [ $? -ne 0 ]; then
        block "typecheck failed in ${PKG_DIR}/ after editing ${REL}" \
              "$(printf '%s' "$OUT" | grep -E 'error TS' | head -20)"
      fi
    else
      note "Did NOT typecheck ${REL} — ${PKG_DIR}/node_modules is missing. Run 'cd ${PKG_DIR} && npm ci'."
    fi
    ;;
esac

# ------------------------------------------------------------------- tests ---
case "$REL" in
  frontend/*.test.js|frontend/*.test.jsx)
    if [ -d frontend/node_modules ]; then
      OUT="$(cd frontend && npx vitest --run "${REL#frontend/}" 2>&1)"
      if [ $? -ne 0 ]; then
        block "tests for ${REL}" "$(printf '%s' "$OUT" | tail -40)"
      else
        printf '%s\n' "$OUT" | grep -E '^ +(Test Files|Tests)  ' | head -2
      fi
    else
      note "Did NOT run ${REL} — frontend/node_modules missing. Run 'cd frontend && npm install'."
    fi
    ;;
  *tests/test_*.py)
    PKG="${REL%/*}"; PKG="${PKG//\//.}"
    if container_ok; then
      # Redis is flushed first: outcomes depend on cache state left by previous
      # test *processes* (apps.timeshift.tests exits 0 warm, 1 flushed).
      # The whole package runs because that is what CI runs.
      docker exec "$CONTAINER" redis-cli flushall >/dev/null 2>&1
      OUT="$(dexec manage.py test --keepdb "$PKG" -v1)"
      if [ $? -ne 0 ]; then
        block "tests for ${PKG}" "$(printf '%s' "$OUT" | awk '/^(FAIL|ERROR):/{f=1} f' | head -50)"
      else
        printf '%s\n' "$OUT" | grep -E '^(Ran |OK)' | head -2
      fi
    else
      note "Did NOT run ${PKG} — container '${CONTAINER}' is not running. Backend tests were NOT verified; say so rather than describing the work as done. Start it with .claude/hooks/start-test-container.sh."
    fi
    ;;
esac

# ------------------------------------------------------------------ report ---
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
