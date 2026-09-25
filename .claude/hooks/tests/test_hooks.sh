#!/usr/bin/env bash
# Tests for the Claude Code test hooks themselves (.claude/hooks/).
#
# Runs the hook scripts DIRECTLY, with a synthetic stdin payload, against two
# throwaway git repos — never through the harness, and never against the
# live checkout. That is the point: the hooks that fire during a session are
# ${CLAUDE_PROJECT_DIR}/.claude/hooks/*, which is not necessarily the copy
# being edited, so "the hook fired and passed" proves nothing about an edit
# to a hook. Only an explicit invocation of the edited copy does.
#
# No Docker, no Django, no network. Needs bash, git, jq, python3.
#
# Probe: repo A has a staged file and no scripts/ci_backend_test_labels.py,
# so a gate that fires AND resolves its root to A reaches the label mapper,
# which fails, and says "could not map staged paths". A gate that does not
# fire, or resolves some other root (B is clean), prints nothing. So the
# presence of that sentence is the discriminator.
#
# Usage: bash .claude/hooks/tests/test_hooks.sh
#        HOOK_DIR=<dir> bash …   # test another copy of the hooks
set -uo pipefail

HOOK_DIR="${HOOK_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
GATE="$HOOK_DIR/pre-commit-tests.sh"
EDIT="$HOOK_DIR/run-affected-tests.sh"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
A="$TMP/repo-a"; B="$TMP/repo-b"
for r in "$A" "$B"; do
  git init -q "$r"
  git -C "$r" -c user.name=t -c user.email=t@t commit -q --allow-empty -m init
done
mkdir -p "$A/sub"
printf 'x\n' > "$A/staged.txt"
git -C "$A" add staged.txt
printf 'x\n' > "$A/edited.txt"
printf "x\n" > "$TMP/not-in-a-repo.txt"

PASS=0; FAIL=0
check() {  # check <name> <want-exit> <want-substring-or-EMPTY> <exit> <output>
  local name="$1" want_st="$2" want="$3" st="$4" out="$5" ok=1
  [ "$st" = "$want_st" ] || ok=0
  if [ "$want" = EMPTY ]; then [ -z "$out" ] || ok=0
  elif [ "$want" = NONOTE ]; then [[ "$out" != *systemMessage* ]] || ok=0
  else [[ "$out" == *"$want"* ]] || ok=0; fi
  if [ $ok = 1 ]; then PASS=$((PASS+1)); printf 'ok   %s\n' "$name"
  else FAIL=$((FAIL+1)); printf 'FAIL %s\n     want exit %s and %q\n     got  exit %s and %q\n' \
    "$name" "$want_st" "$want" "$st" "$out"; fi
}
# gate <cwd> <command> [env assignments…]: run the commit gate as PreToolUse would.
gate() {
  local cwd="$1" cmd="$2"; shift 2
  ( cd "$cwd" && jq -cn --arg c "$cmd" '{tool_input:{command:$c}}' \
      | env -u CLAUDE_HOOK_REPO_ROOT DISPATCHARR_TEST_CONTAINER=hooktest-absent "$@" bash "$GATE" 2>&1 )
}
# edit <file> [env assignments…]: run the edit hook as PostToolUse would.
edit() {
  local f="$1"; shift
  ( cd "$TMP" && jq -cn --arg f "$f" '{tool_input:{file_path:$f}}' \
      | env -u CLAUDE_HOOK_REPO_ROOT DISPATCHARR_TEST_CONTAINER=hooktest-absent "$@" bash "$EDIT" 2>&1 )
}
MAPPED="could not map staged paths"

# ---- #278: git -C <dir> commit ------------------------------------------
out="$(gate "$B" "git -C $A commit -m x")"; st=$?
check "test_git_dash_C_commit_is_gated_on_the_named_tree" 0 "$MAPPED" $st "$out"
out="$(gate "$B" "git -C $A -c user.name=x commit -m x")"; st=$?
check "test_git_dash_C_with_dash_c_options_is_gated" 0 "$MAPPED" $st "$out"
out="$(gate "$B" "git -C $A add staged.txt && git -C $A commit -m x")"; st=$?
check "test_git_dash_C_add_and_commit_in_one_call_is_blocked" 2 "COMMIT BLOCKED" $st "$out"
out="$(gate "$B" "cd $B && git -C $A commit -m x")"; st=$?
check "test_cd_then_git_dash_C_commit_is_refused_as_undetermined" 0 "cannot safely determine" $st "$out"
out="$(gate "$B" "git --git-dir=$A/.git commit -m x")"; st=$?
check "test_git_dir_commit_is_refused_as_undetermined" 0 "cannot safely determine" $st "$out"
# ---- unchanged behaviour ---------------------------------------------------
out="$(gate "$A" "git commit -m x")"; st=$?
check "control_plain_commit_is_gated_on_the_cwd" 0 "$MAPPED" $st "$out"
out="$(gate "$B" "cd $A && git commit -m x")"; st=$?
check "control_cd_and_commit_is_gated_on_the_cd_target" 0 "$MAPPED" $st "$out"
out="$(gate "$B" "git -C $A log --grep commit")"; st=$?
check "control_a_non_commit_git_command_is_ignored" 0 EMPTY $st "$out"
out="$(gate "$B" "ls -la")"; st=$?
check "control_a_non_git_command_is_ignored" 0 EMPTY $st "$out"
# ---- #279: a stale CLAUDE_HOOK_REPO_ROOT ------------------------------------
out="$(gate "$A" "git commit -m x" CLAUDE_HOOK_REPO_ROOT="$TMP/deleted-worktree")"; st=$?
check "test_gate_refuses_loudly_on_a_nonexistent_override" 0 "CLAUDE_HOOK_REPO_ROOT" $st "$out"
out="$(gate "$A" "git commit -m x" CLAUDE_HOOK_REPO_ROOT="$A/sub")"; st=$?
check "test_gate_refuses_loudly_on_an_override_that_is_not_a_root" 0 "is not its root" $st "$out"
out="$(gate "$B" "git commit -m x" CLAUDE_HOOK_REPO_ROOT="$A")"; st=$?
check "control_gate_honours_a_valid_override" 0 "$MAPPED" $st "$out"
out="$(edit "$A/edited.txt" CLAUDE_HOOK_REPO_ROOT="$TMP/deleted-worktree")"; st=$?
check "test_edit_hook_refuses_loudly_on_a_nonexistent_override" 0 "CLAUDE_HOOK_REPO_ROOT" $st "$out"
out="$(edit "$A/edited.txt" CLAUDE_HOOK_REPO_ROOT="$B")"; st=$?
check "test_edit_hook_refuses_loudly_on_a_file_outside_the_override" 0 "outside CLAUDE_HOOK_REPO_ROOT" $st "$out"
out="$(edit "$A/edited.txt")"; st=$?
check "control_edit_hook_is_quiet_on_a_file_no_check_covers" 0 EMPTY $st "$out"
out="$(edit "$A/edited.txt" CLAUDE_HOOK_REPO_ROOT="$A")"; st=$?
check "control_edit_hook_is_quiet_under_a_valid_override" 0 EMPTY $st "$out"
out="$(edit "$TMP/not-in-a-repo.txt")"; st=$?
check "control_edit_hook_is_quiet_outside_any_repo" 0 NONOTE $st "$out"

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
