# Project skills

Skills under this directory load into every Claude Code session on this repository. Each is a directory with a `SKILL.md` (frontmatter `name` and `description`, then the instructions) and optional `references/`.

## Porting a skill to another repository

The process skills here (`worktree-per-change`, `plan-review-fix`, `implement-review-escalate`, `pr-merge-gate`) are written in two layers so they travel:

- `SKILL.md` is generic: the steps, the reasons, the completion criteria. It names no repository, bot, container or path.
- `references/project.md` is this repository's specifics: the worktree directory, the review bot and its verdict text, the ruleset's required checks, the test container and how hooks find it, the gates with no headroom, the known flakes.

To install one elsewhere, copy the skill directory into that repository's `.claude/skills/` and rewrite `references/project.md` for it; leave `SKILL.md` alone unless the process itself differs. A `SKILL.md` that starts naming project facts is a sign the split has drifted; move the fact into `references/project.md`.

`playwright-cli` is a tool skill and carries no project layer.
