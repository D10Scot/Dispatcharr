#!/usr/bin/env bash
# Shared helpers for the Claude Code test hooks (PostToolUse: run-affected-tests.sh;
# PreToolUse: pre-commit-tests.sh). Meant to be `source`d, not executed.
#
# Issue #258: both hooks used to derive REPO_ROOT from their OWN path
# (`dirname "${BASH_SOURCE[0]}"`). settings.json invokes them as
# "${CLAUDE_PROJECT_DIR:-.}/.claude/hooks/<script>.sh", and in this fork's
# multi-worktree setup CLAUDE_PROJECT_DIR is pinned to the MAIN checkout for
# every agent session regardless of which worktree it actually works in — so
# the script's own path, and therefore the old REPO_ROOT, was always the main
# checkout even when the edited file (or the `git commit`) was in a worktree.
# The label then got computed relative to the wrong root (e.g.
# ".worktrees.fix-258.apps.proxy.tests" — not a real Django label), the run
# errored, and the hook reported FAILED regardless of the real outcome. See
# CLAUDE.md's "Test hooks" section for the fork's rules this file follows
# (never interpret a silenced git query; `git show`'s zsh `:` trap doesn't
# apply here since this is plain `rev-parse`, not `show "$ref:path"`).

# hook_repo_root <anchor-dir>
#   Prints the repo root the calling hook should `cd` into and derive its
#   Django label / staged-path diff relative to, and returns 0.
#
#   CLAUDE_HOOK_REPO_ROOT always wins — the documented escape hatch for
#   manual and test runs (see CLAUDE.md) — but only once it is verified to
#   be a worktree root; otherwise returns 2 with the reason on stderr.
#
#   Otherwise resolves `git -C <anchor-dir> rev-parse --show-toplevel`, which
#   follows wherever <anchor-dir> actually lives: for a linked worktree, git
#   reports that worktree's own root, never the main checkout's. The caller
#   picks the anchor: the PostToolUse hook anchors on the EDITED FILE's own
#   directory (the edit may be nowhere near this script); the PreToolUse
#   commit gate anchors on "." for a plain `git commit` (its inherited cwd
#   already IS the worktree it commits to), or on a parsed `cd <dir> &&`
#   prefix when the command has one — PreToolUse fires BEFORE the command
#   runs, so the inherited cwd is stale for that form and cannot be trusted
#   as-is (see pre-commit-tests.sh for the narrow parsing and its refusal on
#   anything more complex).
#
#   On failure (anchor isn't inside any git repo), prints git's own stderr —
#   never swallowed, per CLAUDE.md's rule against interpreting a silenced git
#   query — and returns 1 with nothing on stdout. This is a plain
#   `rev-parse`, not `git show "$ref:path"`, so zsh's history-modifier trap
#   for a bare "$var:path" expansion does not apply here.
hook_repo_root() {
  local anchor="${1:-.}"
  if [ -n "${CLAUDE_HOOK_REPO_ROOT:-}" ]; then
    # Issue #279: the override used to be printed verbatim. A stale value
    # (a deleted worktree, a typo, a subdirectory) then failed the caller's
    # `cd` and the hook exited 0 with no output -- a silent pass. Validate it
    # the same way the anchor is validated below, and require the override
    # to BE a worktree root, not merely something inside one: a
    # subdirectory would resolve, and every label derived relative to it
    # would be wrong. Return 2 -- distinct from 1, "the anchor is in no
    # repo", which is a legitimate nothing-to-do -- so callers can refuse
    # loudly for this case alone.
    local o_out o_st o_top o_want
    o_out="$(git -C "$CLAUDE_HOOK_REPO_ROOT" rev-parse --show-toplevel 2>&1)"
    o_st=$?
    if [ $o_st -ne 0 ]; then
      printf 'CLAUDE_HOOK_REPO_ROOT=%s is not a git worktree: %s\n' "$CLAUDE_HOOK_REPO_ROOT" "$o_out" >&2
      return 2
    fi
    o_top="$(hook_canon_path "$o_out")"
    o_want="$(hook_canon_path "$CLAUDE_HOOK_REPO_ROOT")"
    if [ -z "$o_top" ] || [ "$o_top" != "$o_want" ]; then
      printf 'CLAUDE_HOOK_REPO_ROOT=%s is inside the worktree %s but is not its root\n' "$CLAUDE_HOOK_REPO_ROOT" "$o_out" >&2
      return 2
    fi
    printf '%s\n' "$CLAUDE_HOOK_REPO_ROOT"
    return 0
  fi
  local out st
  out="$(git -C "$anchor" rev-parse --show-toplevel 2>&1)"
  st=$?
  if [ $st -ne 0 ]; then
    printf '%s\n' "$out" >&2
    return 1
  fi
  printf '%s\n' "$out"
  return 0
}

# hook_canon_path <path>
#   Resolves symlinks so two spellings of the same directory compare equal
#   (e.g. a bind-mount Source vs. a worktree path that differ only through a
#   /private prefix on macOS). Prints nothing and implicitly "fails" (empty
#   stdout) if <path> doesn't exist or isn't a directory.
hook_canon_path() {
  ( cd "$1" 2>/dev/null && pwd -P )
}

# hook_container_mismatch <container> <repo-root>
#   The hooks run tests INSIDE $container, which bind-mounts exactly one
#   worktree at /repo (start-test-container.sh). A correctly-derived
#   REPO_ROOT (the fix above) does not by itself guarantee the shared
#   container is mounted at THAT worktree — with several worktrees active,
#   CLAUDE.md says to re-point it at whichever tree is being edited, and nothing
#   stops that from lagging. Running tests anyway would check the right
#   Django label against the wrong tree and report a plausible-but-meaningless
#   PASS or FAIL — worse than today's loud, honest FAILED. This lets the
#   caller detect that and refuse loudly instead, naming both paths, rather
#   than silently re-pointing the shared container itself: another agent may
#   hold it (CLAUDE.md's worktree-occupancy rule), so only a human or the
#   agent that owns that worktree should run start-test-container.sh.
#
#   Prints nothing and returns 0 when the container has no mount to check
#   (not running, or `docker inspect` itself failed) — the caller's own
#   container-reachability check is what handles that case; this function
#   only judges a container it can see is running.
#
#   On an actual mismatch, prints two lines — "<canon-repo-root>" then
#   "<canon-mount-source>" — and returns 1. Returns 0 with no output when
#   they match.
hook_container_mismatch() {
  local container="$1" repo_root="$2"
  local mount_src
  # Filtered by Destination, not position. `docker inspect`'s .Mounts list
  # serialises from a Go map, so its order is NOT stable across calls — a
  # plain `head -1` (the original version of this line) picks whichever mount
  # happened to serialise first. Measured on the real container: 27/30 calls
  # put /repo first, 3/30 put the dispatcharr-hookdb volume first instead
  # (reviewer's own independent run: 26/30 vs 4/30 — same order of magnitude,
  # consistent with genuinely random Go map iteration rather than a fixed
  # ratio). When the volume wins, its /var/lib/docker/volumes/... source
  # doesn't exist on the host running this hook (macOS), hook_canon_path on
  # it returns empty, and the guard two lines below silently declines to
  # judge — the mismatch check passes even when the container IS mounted
  # elsewhere. Naming the actual mount point this container is always started
  # with (start-test-container.sh's `-w /repo`) makes the selection
  # deterministic regardless of map iteration order: re-measured filtered at
  # 30/30 correct, 0/30 wrong (reviewer's own run: 150/150).
  mount_src="$(docker inspect "$container" \
    --format '{{range .Mounts}}{{if eq .Destination "/repo"}}{{.Source}}{{"\n"}}{{end}}{{end}}' \
    2>/dev/null | head -1)"
  [ -n "$mount_src" ] || return 0
  local canon_mount canon_root
  canon_mount="$(hook_canon_path "$mount_src")"
  canon_root="$(hook_canon_path "$repo_root")"
  [ -n "$canon_mount" ] && [ -n "$canon_root" ] || return 0
  if [ "$canon_mount" != "$canon_root" ]; then
    printf '%s\n%s\n' "$canon_root" "$canon_mount"
    return 1
  fi
  return 0
}
