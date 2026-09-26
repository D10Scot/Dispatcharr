---
name: implement-review-escalate
description: Execute a plan section or a bug fix with a sonnet implementer in its own worktree, review the result with an independent reviewer pinned to a commit SHA, run fix rounds, and escalate the reviewer after two failed rounds; enforces the test-modification rule and break-check evidence throughout. Use whenever implementing from a plan, fixing an issue, dispatching an implementer or reviewer subagent, reviewing an implementation PR, or judging a report that says tests were changed, a test went red before the fix, or "verified"; use it even for a change that looks small enough to skip review.
---

# Implement, review, escalate

Code that lands unreviewed is code whose tests may have been reshaped until green. This loop gives every implementation an independent reviewer who verifies against the tree at a pinned SHA, and it escalates model strength when the loop stalls instead of looping forever. The orchestrator coordinates and rules; it neither implements nor reviews.

Read `references/project.md` for this repository's names: the test commands, the gates with no headroom, the PR mechanics. It is the part that changes when the skill is ported.

## Roles and models

- **Implementer** on `sonnet`: an agent writing code against a plan that already exists. Escalate it to `opus` when it is stuck or reports short.
- **Reviewer** is a separate agent on the strongest reviewing model the project allows; `references/project.md` names the reviewer cadence (which rounds get the strongest model, and that a security-adjacent change gets it from round one). It is told to verify findings against the code and push back with `file:line` evidence rather than comply.
- **Orchestrator** relays, pins SHAs, rules on disputes, counts rounds.

**Getting reports back.** A subagent's hand-back reaches you only while you are still running; an orchestrator that ends its turn with a subagent in flight gets "the spawning agent is no longer running" and the report is stranded. Every dispatch therefore names you and says "report by SendMessage to <your name or agent id> as well as by hand-back", and the message is the delivery that resumes you. Record in the ledger which channel each report arrived on (hand-back, message, or recovered from the file it was told to write), so a stranded report is a fact rather than a feeling. If you are yourself a subagent, spawn without a `name` (a subagent cannot spawn named teammates) and address your agents by the id the spawn returned.

## 1. Dispatch the implementer

The dispatch names: its worktree and branch (`worktree-per-change`), the base SHA, the plan section or issue that is its authority, any ruling that overrides the plan, the file list that bounds its scope, the report path, and these rules.

- **Anchor every command** to the worktree; `set -o pipefail` on any pipeline whose status is read; brace `git show "${ref}:path"`.
- **Re-grep every anchor** the plan gives, since plan line numbers were opened at the plan's seed SHA.
- **Test-modification rule.** A test changes only when the behaviour it pins is the thing being changed, and every such change is listed in the report with its before and after assertion. A test that pins a defect is flipped to pin the fix and shown red before the fix and green after. Widen a window rather than lower a count; a tolerance is never loosened and an assertion never deleted to make a run green. New behaviour gets a new test named after the defect.
- **Break-check evidence is observed, never written from expectation.** Apply the plan's named wrong edit, run the one test, record the failure message verbatim, confirm the message names the mechanism rather than a side effect of the edit, revert. If a test the plan says is red at base is green at base, stop and report: a fixture reshaped until the test passes pins nothing.
- **Run the tests the way CI runs them** (per `references/project.md`), once without any cached database, and every gate the change touches. If the test infrastructure is down, say the tests did not run.
- **Commit hygiene:** stage and commit in separate calls; write the message to a file and commit with `-F`; append fix commits after pushing rather than rewriting history.
- **Open the PR** against main with the plan's PR description filled in. The PR that fixes an issue closes it, whatever files it touches: one `Closes #N.` per issue, verified with `gh pr view <n> --json closingIssuesReferences` (a single "Closes #A, #B and #C" links only #A). A docs-only change that fixes a docs-drift issue still carries the keyword; only a plan or memo describing a future fix carries none. `references/project.md` says whether the PR opens as a draft and who marks it ready.
- **Stop and report** when the plan and the tree disagree in a way the plan did not anticipate, when a prerequisite cannot be obtained, when a planned red test is green, or when an unrelated test fails. Stopping costs a message; improvising costs a review round.
- **Scope:** no file outside the section's list; adjacent problems go under follow-ups in the report.
- **Wait in the foreground** for any CI or run you must watch (a Bash call with a long timeout and a sleep loop); an agent that arms a background monitor and goes idle is not resumed.

Ask for a report in this shape: branch, head SHA, PR number, files changed; tests run (label, count, seconds, cache-free run yes/no; gates and their results); break-check table (edit → test → verbatim message); test changes (file, before, after, reason); deviations and stops; follow-ups noticed.

## 2. Freeze, verify, dispatch the reviewer

Tell the implementer to freeze ("no amend, reset or commit until findings arrive"; a freeze is not a SHA to match). Read the tip yourself with `git -C <worktree> log --oneline -3`; a report describes the state when it was written. Then dispatch the reviewer with the PR, the head SHA, the base SHA, the plan section, the report path and the output path.

The reviewer verifies every claim against `git show "${sha}:path"` and `git diff <base>..<sha>`, never a working tree, and checks:

1. The diff matches the plan section's tasks and appendices; every deviation is justified and correct.
2. The test-modification rule: changes only where the pinned behaviour changed; flipped pins shown red-before and green-after; no widened tolerance, lowered count or deleted assertion.
3. Break-check messages name the mechanism, not a side effect of the edit.
4. Tests the plan says are red at base are red at base (spot-check at least one, in a scratch export or by reasoning from the diff).
5. No file outside the section's list; no drive-by fixes.
6. Every gate the change touches passes with the evidence shown.
7. The docs, matrices and ledgers the section requires are present and accurate.
8. The user's rulings named in the dispatch are honoured over the plan's default.
9. The PR body closes the right issues, with placeholders filled.

Output: `PASS` or numbered findings with severity (`blocking`, `should-fix`, `nit`), `file:line`, what, why, the fix. `PASS` is written only when no blocking or should-fix finding exists; a reviewer that writes "PASS with one should-fix" has mislabelled a failed round, and the orchestrator counts it as failed regardless of the label. A finding it cannot verify is stated as unverified.

## 3. Relay, rule, fix

The first line of the relay names the SHA you expect the implementer to be at: "you are at `<sha>`; if not, say so before doing anything." A disputed finding is settled by reading the reviewed SHA yourself and quoting the `file:line`; a ruling reasoned from a summary, or from a bot's framing, has inverted the code's actual condition before. Before ruling that a change "preserves prior behaviour", read the prior code at the base SHA and name its condition. When messages cross, one superseding message restates the whole final state.

A fixer that agrees with every finding is a signal to test, not to trust. Where a report says "added and verified", ask for the `grep -n` of the shipped file, since a change verified in scratch and never copied into the branch has happened.

When a reviewer shows that a new assertion claims something the code does not guarantee, the ruling goes by reachability: if the failing case can reach production (a cached value, a sibling code path, a caller that passes the value), the fix goes into the code and the assertion stays; the test is narrowed only when the path is genuinely outside the change's scope, and then the report names the path and why. Narrowing the test is the cheaper edit and the one that hides a defect.

## 4. Re-review and escalate

Round two: same reviewer, new SHA, targeted re-check of the findings plus anything the fix touched. A round **fails** when it returns a blocking or should-fix finding. A round that returns only nits passes: the nits are applied in one commit and the reviewer confirms that commit with a targeted re-check, not a new round, and a nit the implementer disputes with evidence is left as it is. After the second failed round, the review escalates to the strongest reviewing model if it was not already there, and a fresh reviewer reads the branch cold; if the implementer is the one stalling, it moves to `opus`. Count failed rounds explicitly in the ledger so escalation is a rule rather than a feeling.

Completion criterion: the reviewer's last output is `PASS` against the SHA at the branch tip (a commit after the PASS, however small, gets its targeted re-check first), every test change is accounted for in the report, and every break-check row carries an observed message. Then hand the PR to `pr-merge-gate`, with the worktree left in place until it merges.
