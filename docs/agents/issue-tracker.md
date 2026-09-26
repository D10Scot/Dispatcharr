# Issue tracker: GitHub

Issues and specs for this repo live as GitHub issues. Use the `gh` CLI for all operations.

## Which repo — read this before any gh command

Issues live on the **fork**, `D10Scot/Dispatcharr`. Never the upstream.

`gh repo set-default` is now pinned to the fork, but **always pass
`--repo D10Scot/Dispatcharr` explicitly anyway.** Do not rely on inference.

Why this matters: `D10Scot/Dispatcharr` is a fork of `Dispatcharr/Dispatcharr`. Before
2026-08-23 this clone had no default set, so `gh` fell back to the parent and resolved to the
upstream public project — 256 open issues, other people's tracker. `CLAUDE.md` sets upstream's
git push URL to the literal string `DISABLED` to prevent pushes going the wrong way, but `gh`
does not read git push URLs, so that guard does not cover issue creation.

A fresh clone, a new worktree, or a cleared gh config restores the bad default. The explicit
`--repo` flag is the only thing that survives all three.

Issues were disabled on the fork until 2026-08-23 (`has_issues: false`, GitHub's default for
forks) and were enabled as part of this setup.

## Conventions

- **Create an issue**: `gh issue create --repo D10Scot/Dispatcharr --title "..." --body "..."`. Use a heredoc for multi-line bodies.
- **Read an issue**: `gh issue view <number> --repo D10Scot/Dispatcharr --comments`, filtering comments by `jq` and also fetching labels.
- **List issues**: `gh issue list --repo D10Scot/Dispatcharr --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'` with appropriate `--label` and `--state` filters.
- **Comment on an issue**: `gh issue comment <number> --repo D10Scot/Dispatcharr --body "..."`
- **Apply / remove labels**: `gh issue edit <number> --repo D10Scot/Dispatcharr --add-label "..."` / `--remove-label "..."`
- **Close**: `gh issue close <number> --repo D10Scot/Dispatcharr --comment "..."`

## Closing keywords close issues whatever the PR changes

GitHub honours a keyword — `close`/`closes`/`closed`, `fix`/`fixes`/`fixed`,
`resolve`/`resolves`/`resolved`, case-insensitive and optionally followed by a colon — immediately
followed by `#N`, `owner/repo#N`, or a full issue URL. **A keyword in the PR body links the issue,
and the merge closes it. A keyword in a commit message closes the issue once that commit reaches
the default branch (`main` here), without linking the PR. On a PR that targets any other branch
the keywords are ignored.** Each issue needs its own keyword: a single `Closes #A, #B and #C`
links only #A. Full reference:
https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/linking-a-pull-request-to-an-issue

This repository's squash-merge setting builds the merge commit message from the **branch's own
commit messages**, not the PR body — confirmed via
`gh api repos/D10Scot/Dispatcharr --jq '{squash_merge_commit_title, squash_merge_commit_message}'`
(`COMMIT_OR_PR_TITLE` / `COMMIT_MESSAGES`). A keyword sitting only in a commit message closes the
issue exactly as one in the PR body does, so check both before marking a PR ready.

On 2026-09-24 ten docs-only PRs (#343-#354) carried fix plans that quoted each future fix's draft
PR description, and merging them closed thirteen issues as completed with nothing fixed; every
one had to be reopened by hand. **The dividing line is "describes a future fix" versus "is the
fix," not "docs-only" versus "code."** A plan, spec or memo describing work not yet done carries
no keyword — name the issue as `#N (planned in PR X)` instead — but a docs change that itself
fixes a docs-drift issue is a fix and carries one `Closes #N.` per issue it fixes (PR #501's docs
fix for issue 476 is the precedent).

- Check what GitHub will actually link, not a hand-rolled body grep — it reads every form the
  platform honours:
  `gh pr view <number> --repo D10Scot/Dispatcharr --json closingIssuesReferences --jq
  '.closingIssuesReferences | length'` — must print `0` before marking ready a PR that only
  describes a future fix. That field doesn't preview a keyword sitting only in a commit message,
  so also check those directly (misses the full-URL form, which a commit message rarely uses):
  `git log --format=%B main..HEAD | grep -inE '\b(close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved)\b:? *([[:alnum:]_.-]+/[[:alnum:]_.-]+)?#[0-9]+'`
- After merging a PR meant to close nothing, list what actually closed around that time —
  `--state closed` with no time filter orders by creation and misses older issues a merge can
  still close:
  `gh issue list --repo D10Scot/Dispatcharr --state closed --search "closed:>=<merge time, ISO 8601>" --limit 200 --json number,closedAt,title`.
  Reopen anything the merge closed, with a comment saying which PR did it.

See `.claude/skills/plan-review-fix/SKILL.md`, `.claude/skills/implement-review-escalate/SKILL.md`
and `.claude/skills/pr-merge-gate/SKILL.md` (and each one's `references/project.md`) for how this
rule fits into the plan → implement → merge cadence.

## Pull requests as a triage surface

**PRs as a request surface: no.** _(Set to `yes` if this repo treats external PRs as feature requests; `/triage` reads this flag.)_

When set to `yes`, PRs run through the same labels and states as issues, using the `gh pr` equivalents:

- **Read a PR**: `gh pr view <number> --repo D10Scot/Dispatcharr --comments`, and `gh pr diff <number> --repo D10Scot/Dispatcharr` for the diff.
- **List external PRs for triage**: `gh pr list --repo D10Scot/Dispatcharr --state open --json number,title,body,labels,author,authorAssociation,comments` then keep only `authorAssociation` of `CONTRIBUTOR`, `FIRST_TIME_CONTRIBUTOR`, or `NONE` (drop `OWNER`/`MEMBER`/`COLLABORATOR`).
- **Comment / label / close**: `gh pr comment <number> --repo D10Scot/Dispatcharr`, `gh pr edit <number> --repo D10Scot/Dispatcharr --add-label`/`--remove-label`, `gh pr close <number> --repo D10Scot/Dispatcharr`.
- **Review threads** (not exposed by `gh pr view`): read them with `gh api graphql`, and resolve one with the `resolveReviewThread` mutation on its thread id. This matters on every PR here, not only on triage: the Main ruleset turns on `required_review_thread_resolution`, so a PR merges only once every thread the review bot opened is resolved, and no `gh pr` subcommand lists them.

  List the unresolved threads on a PR, newest comment first:

  ```bash
  gh api graphql -f query='
    query($owner: String!, $name: String!, $number: Int!) {
      repository(owner: $owner, name: $name) {
        pullRequest(number: $number) {
          reviewThreads(first: 100) {
            nodes {
              id
              isResolved
              path
              line
              comments(first: 1) { nodes { author { login } body } }
            }
          }
        }
      }
    }' -f owner=D10Scot -f name=Dispatcharr -F number=<pr> \
    --jq '.data.repository.pullRequest.reviewThreads.nodes[]
          | select(.isResolved | not)
          | {id, path, line, first: .comments.nodes[0].body}'
  ```

  `-f` sends a string and `-F` infers a type, so `number` must use `-F` or the API rejects it as a
  `String!` where an `Int!` was declared. Then resolve one by its `id` (a `PRRT_`-prefixed node
  id, not a number):

  ```bash
  gh api graphql -f query='
    mutation($threadId: ID!) {
      resolveReviewThread(input: {threadId: $threadId}) {
        thread { id isResolved }
      }
    }' -f threadId=<PRRT_…>
  ```

  Resolve a thread only after acting on it. `unresolveReviewThread` takes the same input and
  reopens one.

GitHub shares one number space across issues and PRs, so a bare `#42` may be either: resolve with `gh pr view 42 --repo D10Scot/Dispatcharr` and fall back to `gh issue view 42 --repo D10Scot/Dispatcharr`.

## When a skill says "publish to the issue tracker"

Create a GitHub issue on `D10Scot/Dispatcharr`.

## When a skill says "fetch the relevant ticket"

Run `gh issue view <number> --repo D10Scot/Dispatcharr --comments`.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a single issue with **child** issues as tickets.

- **Map**: a single issue labelled `wayfinder:map`, holding the Notes / Decisions-so-far / Fog body. `gh issue create --repo D10Scot/Dispatcharr --label wayfinder:map`.
- **Child ticket**: an issue linked to the map as a GitHub sub-issue (`gh api` on the sub-issues endpoint). Where sub-issues aren't enabled, add the child to a task list in the map body and put `Part of #<map>` at the top of the child body. Labels: `wayfinder:<type>` (`research`/`prototype`/`grilling`/`task`). Once claimed, the ticket is assigned to the driving dev.
- **Blocking**: GitHub's **native issue dependencies**, the canonical, UI-visible representation. Add an edge with `gh api --method POST repos/D10Scot/Dispatcharr/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>`, where `<blocker-db-id>` is the blocker's numeric **database id** (`gh api repos/D10Scot/Dispatcharr/issues/<n> --jq .id`, _not_ the `#number` or `node_id`). GitHub reports `issue_dependencies_summary.blocked_by` (open blockers only, the live gate). Where dependencies aren't available, fall back to a `Blocked by: #<n>, #<n>` line at the top of the child body. A ticket is unblocked when every blocker is closed.
- **Frontier query**: list the map's open children (`gh issue list --repo D10Scot/Dispatcharr --state open`, scoped to the map's sub-issues / task list), drop any with an open blocker (`issue_dependencies_summary.blocked_by > 0`, or an open issue in the `Blocked by` line) or an assignee; first in map order wins.
- **Claim**: `gh issue edit <n> --repo D10Scot/Dispatcharr --add-assignee @me`, the session's first write.
- **Resolve**: `gh issue comment <n> --repo D10Scot/Dispatcharr --body "<answer>"`, then `gh issue close <n> --repo D10Scot/Dispatcharr`, then append a context pointer (gist + link) to the map's Decisions-so-far.
