---
name: pr-merge-gate
description: Take a pull request from draft to merged without bypassing anything - branch up to date, marked ready, the review bot's passing verdict and/or every review thread actioned and resolved, every CI check green on the head SHA, squash merge, post-merge housekeeping. Use whenever a PR exists and the next step is to push it through, mark it ready, get it merged, land it, or clear its threads; whenever a PR's CI is red, missing, cancelled or rate-limited; and whenever several PRs are queued for merge and need ordering.
---

# PR merge gate

A PR merges when three things are true at once on its head SHA: the branch is up to date with its base, every required check is green, and the review bot has given its passing verdict and/or every review thread has been actioned and resolved (both, when both exist). Nothing here bypasses a check, and no merge takes `--admin`. The value of the gate is that a merged commit on main is one that was reviewed and tested exactly as it landed.

Read `references/project.md` for this repository's names: the bot, how many times it reviews a PR and what its passing verdict says, the ruleset, the required checks, the worktree directory, the known flakes. It is the part that changes when the skill is ported.

## 1. Before marking ready: mergeable, then up to date

```bash
gh pr view <n> --repo <owner/repo> --json mergeable,mergeStateStatus,isDraft,headRefOid
```

A `CONFLICTING` or `DIRTY` PR gets **no workflow runs at all**, because the platform cannot build the merge ref; waiting on its CI waits forever. Have the branch's owner merge the base branch and resolve conflicts first. A `BEHIND` PR is updated **before** it is marked ready (`gh pr update-branch`): an update pushed right after `ready` cancels the review bot's run on the head it was about to review.

Check the body for closing keywords with `--json closingIssuesReferences`, which reads them the way the platform will. The PR that lands a fix carries one `Closes #N.` per issue it fixes, whatever files it touches; a PR that only describes a future fix (a plan, a memo, a spec) carries none, because the platform closes the issue on merge whatever the PR changed. An issue named in passing ("fixed #299" in a sentence) counts as a keyword too, so reword it. A stacked PR whose base is another PR is retargeted to main **before** its parent merges; deleting the parent's branch closes every child.

## 2. Mark ready and confirm the review run fires

A PR reaches this gate as a draft that has passed its internal review (`plan-review-fix` or `implement-review-escalate`); `references/project.md` says why it was held as a draft until now. Marking it ready is the first write this gate makes:

```bash
gh pr ready <n> --repo <owner/repo>
```

Within a few minutes a review-bot run should appear for the head SHA. When none appears, force a `synchronize` with `gh pr update-branch` or close and reopen the PR. `references/project.md` says whether the bot reviews once per PR or on every push, and how to make it review again; that fact decides how a later fix commit is checked.

## 3. Wait in the foreground, then read the result

Poll from a single Bash call with a long timeout and a sleep between polls of at least two minutes (the API budget is shared by every agent in the session); a background monitor that goes idle is never resumed. Read the run's conclusion, then the failed job's log before deciding anything:

- **Cancelled** is not failed. Re-run it.
- **A known flake** (a login throttle, a rate-limited bot step, a timing-sensitive spec) is re-run once with `gh run rerun <id> --failed`, and the occurrence is recorded on the flake's issue. A failure that reads as a flake but has no issue yet (a registry reset, a network error in a build step) gets one filed before the re-run, with the run id and the log line, so the next occurrence has somewhere to be counted. A second failure on the same PR is a finding, not a flake.
- **A real failure** goes back through `implement-review-escalate` as a fix round; a fix that widens a tolerance or lowers a count to get green is refused there.
- **A rate-limited bot step** (its required check fails on an API quota) recovers with `gh run rerun <id> --failed` after the quota resets.

## 4. Action and resolve every thread

For each review thread: verify the claim against the tree first (`git show "${sha}:path"`, a grep across branches, the actual return value), then fix it with a commit or answer it with `file:line` evidence that it is wrong. A bot's claim about what the code does has been wrong before, and a blocking finding accepted unverified costs a commit that may itself be wrong. A fix commit moves the head, so the checks run again; whether the bot reviews again is a project fact, and where it does not, the fix is checked by hand. Then resolve the thread:

```bash
gh api graphql -f query='mutation { resolveReviewThread(input:{threadId:"<id>"}) { thread { isResolved } } }'
```

Thread ids come from the PR's `reviewThreads` connection. Resolving without actioning defeats the ruleset that requires resolution; a thread is resolved when its point is met or refuted, never to clear the count.

## 5. Read the verdict

```bash
gh api repos/<owner/repo>/pulls/<n>/reviews --jq '.[] | select(.user.login=="<bot>") | .body' | grep -i 'Verdict:'
```

The passing verdict named in `references/project.md` satisfies the gate; any other verdict means the threads it opened are the work list. When there are no threads and the verdict is ready, and every check is green, merge.

## 6. Merge one at a time

```bash
gh pr merge <n> --repo <owner/repo> --squash --delete-branch --auto
```

Auto-merge fires when the last check lands. When main moves again after the bot has reviewed, update the branch with a **merge** of main, never a rebase or force-push: the bot's review is pinned to the commits it read, and a bot that declines to review the same PR twice is only sound while those commits are still in the branch. After any such update, show the diff of the PR's own files against the last reviewed SHA to be empty before letting the merge proceed; if it is not empty, the bot's review no longer covers the head and its review is dismissed to force a fresh one. Keep exactly **one** queued PR up to date at a time: every merge invalidates every other queued branch (the ruleset requires up-to-date), and updating N branches at once fires N bot runs, which can exhaust the bot's API quota and fail its required check on every one of them. A serial driver (update the next PR only after the previous one merges) is the shape that works.

Confirm the merge, then watch the push runs on main for the merge commit:

```bash
gh pr view <n> --repo <owner/repo> --json state,mergeCommit --jq '"\(.state) \(.mergeCommit.oid[0:8])"'
gh run list --repo <owner/repo> --branch main --json name,status,conclusion,headSha --jq '.[] | select(.headSha|startswith("<sha>"))'
```

## 7. Housekeeping

Pull main in the root checkout, remove the worktree and branch (`worktree-per-change` § 6), verify each issue the PR was meant to close is closed, and, after merging a PR that was meant to close nothing, list issues closed in the last few minutes and reopen any the merge closed by keyword. Update the ledger row to `MERGED <sha>`.

Completion criterion: the PR is `MERGED`, every push run that fired on main for the merge commit is green, the worktree and branch are gone, and every issue it names has the state its body promised.
