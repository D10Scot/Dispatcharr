---
name: worktree-per-change
description: Isolate every change in its own git worktree and branch off main, confirm the tree is unoccupied before writing, anchor every command to it, and remove the worktree when its PR merges or is abandoned. Use before editing any file in a shared repository, including a one-line docs fix, a plan, a spike, a fix round on an existing branch, and every subagent dispatch; and use it again at the end of the work for the tidy-up. Also reach for it when asked whether a worktree is free, when a command lands in the wrong directory, or when the checkout looks hijacked.
---

# Worktree per change

The checkout at the repository root is shared: by you across turns, by every concurrent agent, and by hooks and test containers that read a single mount. A change made in it is a change made in everyone's tree. One worktree per change, named for the change, is what keeps concurrent work from crossing streams and makes cleanup a one-line removal instead of a forensic exercise.

This project's names (the worktree directory, the shared test container, the hook that checks the mount) are in `references/project.md`. Read it once before the first step; it is the part that changes when this skill is ported to another repository.

## 1. Create

```bash
cd <repo-root> && git fetch origin && \
  git worktree add -b <type>/<id>-<slug> .worktrees/<id> origin/main && \
  git -C .worktrees/<id> rev-parse --short HEAD
```

Name the worktree after the change (a PR id, a plan stage, an issue number), not after yourself. Record the base SHA the branch was cut from: every later review is pinned to it and every plan anchor is re-grepped against it. A `/goal`, a multi-file change or anything unattended always gets a worktree. A genuinely one-file edit may take a branch in the root checkout only when no other agent is active in the repository; when in doubt, a worktree costs seconds.

## 2. Confirm the tree is unoccupied

Before writing into any worktree you did not create this turn (a handover, a fix round, a tree the orchestrator pointed you at), ask whether it is **occupied**, not whether it is clean. `git status` answers the wrong question: an agent in a measurement task writes no files, and an agent mid-edit has uncommitted changes with no author attached. Run all three:

```bash
cd <worktree> && git status --porcelain && git log --oneline -3
stat -f '%Sm %N' <the files you intend to touch>      # a modification younger than a few minutes is someone's in-flight edit
docker ps --filter name=<container the plan names>     # a measurement phase leaves only this trace
```

Any sign of occupation means the tree is occupied. Send your diff to the orchestrator to relay to the tree's owner rather than writing; that decision is not the writer's to weigh, because the writer cannot see what the other agent holds in flight. A tree that reads clean at one instant says nothing about a merge in progress.

## 3. Anchor every command

The shell's working directory is shared or correlated across concurrent sessions and moves without a `cd`, always toward the busier agent's tree. Prefix every command with `cd <absolute worktree> &&` or use absolute paths. A relative path resolves somewhere plausible and wrong, with nothing in `git status` to show for it.

Two git habits belong here because they fail silently in the same way:

- `set -o pipefail` on any pipeline whose status or emptiness you read; keep stderr, since a bad ref exits 128 and a pipe launders it to 0.
- Brace the ref in `git show "${ref}:path"`: zsh parses an unbraced `$ref:path` as a modifier and prints the tip commit's diff instead of the file.

## 4. Keep git pointed at your own tree

Never run `git --work-tree=`, `git --git-dir=`, `git config core.worktree`, or export `GIT_DIR`, `GIT_WORK_TREE` or `GIT_INDEX_FILE` into a command that runs a script or a test suite. A test fixture that does its own `git init` inherits those variables and writes into the shared `.git` (this happened: three scratch commits landed on local `main` and every git command in the root checkout started answering "must be run in a work tree"). A scratch repository is `git init`ed inside the scratch directory, and `git rev-parse --git-dir` is checked to print a scratch path before the first commit. For history at a SHA use `git worktree add --detach <scratch> <sha>` and remove it by path afterwards.

## 5. Tests and hooks

Edit-triggered hooks run in the harness's environment and read one shared mount, whatever the editing agent exported. Read `references/project.md` for how this project's hooks decide which tree they test and how to re-point or run your own container. Report a hook that refused because of a mount mismatch as "tests did not run through the hook; I ran <labels> myself" rather than as verified.

## 6. Tidy up

Completion criterion: `git worktree list` shows only live work, no local branch survives its merged PR, the root checkout is on `main` at the merge commit with nothing to commit, and every container, image and network you created is gone by name.

```bash
cd <repo-root> && git pull --ff-only origin main && \
  git worktree remove --force .worktrees/<id> && git branch -D <branch> && \
  git worktree prune && git worktree list
docker rm -f <your containers>; docker network rm <your network>; docker rmi <your image tag>
```

Run this when the PR merges or the work is abandoned. A worktree whose PR is still open stays until then: the merge gate may need a fix commit, and a reviewer may need to read the tree. When an orchestration ends with a PR still open, the branch is pushed, the worktree is left in place, and the report says so by path, so the next agent knows it is live rather than abandoned. A worktree left behind after its PR merged is the next agent's occupancy false positive.

## Orchestrating several agents

The orchestrator creates and destroys the worktrees, one per agent, named for the stage. Two agents never share a tree; post-handover edits to a document go through the tree's current owner. A statement about repository state is true when it was read, not when it is delivered: before ruling on a report, re-derive the state from the tree (`git log`, `grep -n` for the content the report claims landed). An agent that shows no worktree activity may be prototyping in a scratch export and committing once at the end; check the scratchpad and `ps` for long test runs before concluding it has stalled.
