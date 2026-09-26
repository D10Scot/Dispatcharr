---
name: plan-review-fix
description: Produce a spec, design, implementation plan or amendment through a plan → independent review → fix → re-review loop, on opus or fable, with every review pinned to a commit SHA, until the reviewer passes it. Use whenever asked to write, draft, amend or "put together" a plan, spec, design doc, migration plan, or any document a subagent will later execute, and before implementation starts on any multi-step change, even when the request only says "plan this out" or "how should we approach X".
---

# Plan, review, fix

A plan is executed later by an agent with no memory of the conversation that produced it, so a gap in the plan becomes a gap in the code, found one PR later at ten times the cost. The loop below puts an independent reviewer between the planner and the implementer and keeps looping until the reviewer passes the document. Nothing is executed unreviewed.

Read `references/project.md` for this repository's names (where plans live, which models are available, the PR mechanics). It is the only part that changes when the skill is ported.

## Roles and models

- **Planner** writes the document. Run it on `opus` or `fable`, never `sonnet`: `references/project.md` records why (every sonnet plan draft here failed its first review and was rewritten on opus).
- **Reviewer** is a separate agent on the strongest reviewing model the project allows; `references/project.md` names the reviewer cadence (which rounds get the strongest model, and that a security-adjacent change gets it from round one). It verifies against the tree and pushes back with `file:line` evidence; it is told not to comply with a claim because the document makes it.
- **Orchestrator** neither writes nor reviews. Its context is reserved for coordination: dispatching, pinning SHAs, relaying findings, ruling on disputes.

**Getting reports back.** A subagent's hand-back reaches you only while you are still running; an orchestrator that ends its turn with a subagent in flight gets "the spawning agent is no longer running" and the report is stranded. So every dispatch names you and says: "report by SendMessage to <your name or agent id> as well as by hand-back", and you treat the message as the delivery that resumes you. Record which channel each report arrived on (hand-back, message, or recovered from the file it was told to write), so a stranded report is a fact rather than a feeling. If you are yourself a subagent, spawn without a `name` (a subagent cannot spawn named teammates) and address your agents by the id the spawn returned.

## 1. Dispatch the planner

Give it: its own worktree and branch (`worktree-per-change`), the base SHA, the authority it plans against (the spec, the issue list, the rulings that override defaults), the output path, and the review it will face. Ask for a plan whose every anchor is re-grepped against the base SHA and whose appendices are byte-exact diff hunks against that SHA rather than prose, since an implementer applies an appendix and cannot re-derive one. A planner may prototype in a scratch export to measure rather than guess; that makes it invisible to worktree checks for hours, so allow it a long silence before concluding it has stalled.

The planner commits, pushes, opens the PR and reports the head SHA; `references/project.md` says whether the PR opens as a draft and when it is marked ready, since that depends on how the project's review bot behaves. A plan describes a future fix and does not make one, so its body carries no closing keyword: GitHub closes the issue on merge whatever the PR changed, and the keyword belongs to the PR that lands the fix. Check with:

```bash
gh pr view <n> --repo <owner/repo> --json closingIssuesReferences --jq '.closingIssuesReferences | length'   # must print 0; it reads every form the platform honours
```

## 2. Freeze and verify the tip

Before dispatching the reviewer, tell the planner: "freeze whatever you have; no amend, reset or commit until findings arrive." A freeze is an instruction to hold still, never a SHA to match: naming a SHA in a hold invites the worker to *make* the branch match it, and the branch then moves in both directions with an identical tree. Then read the tip yourself:

```bash
git -C <worktree> log --oneline -3 && git -C <worktree> status --porcelain
```

A completion report is a claim, not evidence. Messages cross constantly, so a report describes the state when it was written; the tree is the state now.

## 3. Dispatch the reviewer, pinned to a SHA

The dispatch names the PR, the head SHA, the base SHA, the authority to review against, and the output path. The reviewer reads the document with `git show "${sha}:path"` (braced: an unbraced `$sha:path` in zsh prints the tip commit's diff instead), never from a working tree, which is whatever the branch is now. Its output is `PASS` or a numbered findings list, each with a severity (`blocking`, `should-fix`, `nit`), a `file:line`, what is wrong, why, and the fix. `PASS` is written only when no blocking or should-fix finding exists; "PASS with one should-fix" is a mislabelled failed round and is counted as one. A claim it cannot verify is stated as unverified, not asserted.

Ask the reviewer for the plan's break-checks and evidence, not only its prose: a plan that names a portable function as its "wrong edit", or an oracle that predates a merged change, reads well and fails the implementer. Cross-plan prototyping (writing one plan against another's assumptions) has found real gaps in plans that had already passed; treat a passed plan as reopenable.

## 4. Relay findings with the SHA expected

The first line of the relay names the SHA you expect the planner to be at: "you are at `<sha>`; if not, say so before doing anything." Three SHAs are in play during a fix round (the reviewer's, yours, and whatever the planner pushed since) and this line is what pins them together. When messages cross, send one superseding message that restates the whole final state rather than a third incremental patch.

A disputed finding is checked at the reviewed SHA (`git show "${sha}:path"`), never in a checkout, and the ruling quotes the `file:line` you read. Before ruling that a change "preserves prior behaviour", read the prior code at the base SHA and name its condition in the ruling; a ruling reasoned from a summary has inverted the old rule before.

## 5. Fix round and re-review

The planner fixes, pushes, reports the new SHA; the branch freezes again; the same reviewer re-checks the findings against the new SHA (a full re-read on round one, a targeted re-check on later rounds unless the diff is large). A round **fails** when it returns a blocking or should-fix finding; a round that returns only nits passes, the nits are applied in one commit, and the reviewer confirms that commit with a targeted re-check rather than a new round. Count the failed rounds. After the second failed round, escalate: the review moves to the strongest reviewing model if it was not already there and a fresh reviewer reads the branch cold; a planner that keeps missing the same class of finding moves to `fable`.

The SHA the plan is "good at" is the last SHA a reviewer passed. Any commit after that PASS, however small, moves the branch off the reviewed state and gets a targeted re-check before the plan is handed on; a one-line wording change committed after PASS and called final is how an unreviewed plan reaches an implementer. A fixer that agrees with every finding is a signal to test, not to trust; ask it for the `grep -n` of the shipped file where a report says "added and verified", since a change verified in scratch and never copied into the document has happened.

Completion criterion: the reviewer's last output is `PASS` against the SHA now at the branch tip, and the PR body carries no closing keyword.

## 6. Hand off

The passed plan goes to `pr-merge-gate` for the merge, then to `implement-review-escalate` for execution. Record the passing SHA where the implementer will read it: an implementation reviewed against a plan is reviewed against the plan at that SHA.
