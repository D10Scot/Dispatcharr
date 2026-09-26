# Project skills

Skills under this directory load into every Claude Code session on this repository. Each is a directory with a `SKILL.md` (frontmatter `name` and `description`, then the instructions) and optional `references/` and `evals/`.

## The four process skills

They encode how work is done here, and they chain: a change starts in `worktree-per-change`, a plan goes through `plan-review-fix`, an implementation through `implement-review-escalate`, and every PR through `pr-merge-gate`.

- `worktree-per-change`: one worktree and branch per change, occupancy checks before writing into a shared tree, anchored commands, tidy-up when the PR merges.
- `plan-review-fix`: plan → independent review pinned to a SHA → fix → re-review until PASS, on opus/fable; the "good at" SHA is the last PASS.
- `implement-review-escalate`: sonnet implementer → independent review pinned to a SHA → fix rounds → escalation after two failed rounds; the test-modification rule and break-check evidence.
- `pr-merge-gate`: branch up to date, marked ready, the review bot's verdict and/or every thread actioned and resolved, every check green, squash merge, post-merge housekeeping.

Every PR from the plan and implement skills opens as a **draft** and stays one until its internal review passes; `pr-merge-gate` marks it ready. The reason is the review bot's once-per-PR behaviour, stated in the plan, implement and merge-gate skills' `references/project.md`.

When a skill and CLAUDE.md disagree, the skill rules and CLAUDE.md is corrected to match it (the user's ruling, 2026-09-26).

## Porting a skill to another repository

Each process skill is written in two layers so it travels:

- `SKILL.md` is generic: the steps, the reasons, the completion criteria. It names no repository, bot, container or path.
- `references/project.md` is this repository's specifics: the worktree directory, the review bot and its verdict text, the ruleset's required checks, the test container and how hooks find it, the gates with no headroom, the known flakes, whether PRs open as drafts.

To install one elsewhere, copy the skill directory into that repository's `.claude/skills/` and rewrite `references/project.md` for it; leave `SKILL.md` alone unless the process itself differs. A `SKILL.md` that starts naming project facts is a sign the split has drifted; move the fact into `references/project.md`.

`evals/evals.json` holds the test prompts each skill was evaluated with (two iterations, with-skill against a CLAUDE.md-only baseline, 2026-09-25); keep them when porting and rewrite the repository-specific details.

`playwright-cli` is a tool skill and carries no project layer.
