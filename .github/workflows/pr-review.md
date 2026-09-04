---
description: Review every non-draft pull request with Kimi K3 and leave inline comments; the Main ruleset requires this job and resolution of every thread before merge.
emoji: 🔍
on:
  pull_request:
    types: [opened, synchronize, reopened, ready_for_review]
  stop-after: "+90d"
# Drafts are skipped; ready_for_review re-triggers when the author flips it.
if: github.event.pull_request.draft == false
permissions:
  contents: read
  pull-requests: read
# Kimi K3 for the same reason issue-remediation uses it: it is on the api-proxy
# allowlist and has no cybersecurity classifier that kills security-adjacent
# review runs mid-turn (gpt-5.x does — HTTP 422).
model: kimi-k3
timeout-minutes: 20
features:
  group-concurrency-queue: false
concurrency:
  group: pr-review-${{ github.event.pull_request.number }}
  cancel-in-progress: true
tools:
  github:
    mode: gh-proxy
    toolsets: [context, repos, pull_requests]
network:
  allowed:
    - defaults
steps:
  - name: Stage the pull request context for the agent
    env:
      GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
      REPO: ${{ github.repository }}
      PR_NUMBER: ${{ github.event.pull_request.number }}
    run: |
      set -euo pipefail
      mkdir -p .pr-review
      gh pr view "$PR_NUMBER" --repo "$REPO" \
        --json number,title,body,baseRefName,headRefName,additions,deletions,changedFiles,files \
        > .pr-review/pr.json
      gh pr diff "$PR_NUMBER" --repo "$REPO" > .pr-review/pr.diff
      # Annotate every '+' and context line with its RIGHT-side (new file) line
      # number so inline comments land on lines that exist in the diff without
      # the agent having to count hunk offsets by hand.
      python3 - <<'PY'
      import re
      hunk = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
      out = []
      new = None
      for raw in open(".pr-review/pr.diff", encoding="utf-8", errors="replace"):
          line = raw.rstrip("\n")
          m = hunk.match(line)
          if line.startswith("diff --git"):
              new = None
              out.append(f"\n{line}")
              continue
          if m:
              new = int(m.group(1))
              out.append(line)
              continue
          if new is None or line.startswith(("---", "+++", "\\")):
              out.append(line)
              continue
          if line.startswith("-"):
              out.append(f"      {line}")
              continue
          out.append(f"{new:>6} {line}")
          new += 1
      open(".pr-review/pr.annotated.diff", "w", encoding="utf-8").write("\n".join(out) + "\n")
      PY
      wc -l .pr-review/pr.diff .pr-review/pr.annotated.diff
safe-outputs:
  create-pull-request-review-comment:
    max: 15
    side: "RIGHT"
  submit-pull-request-review:
    allowed-events: [COMMENT]
    footer: "if-body"
---

# Pull request review

You are the required reviewer for this pull request. Nothing merges to `main` until this run completes **and every review thread you open has been resolved by a human**, so each inline comment costs someone a decision. Post only comments worth that cost.

## Context (already staged — do not rediscover)

- `.pr-review/pr.json` — title, body, base/head branches, and the list of changed files.
- `.pr-review/pr.diff` — the raw unified diff.
- `.pr-review/pr.annotated.diff` — the same diff with the **RIGHT-side (new file) line number** prefixed to every added and context line. Use these numbers for inline comments; removed lines have no number and cannot be commented on.
- The checkout is the pull request's head. Read surrounding code from disk when the diff alone is not enough to judge a change; do not modify any files.
- `CLAUDE.md` at the repo root describes the architecture and, under **Known defects and traps**, defects that are *already present*. Do not report a pre-existing defect unless the diff touches or worsens it.

## What to look for, in priority order

1. **Security** — credentials or provider URLs reaching a log statement without `redact_url`/`redact_headers`; authorization removed or loosened (REST views are admin-only unless they opt down; `hide_adult_content` and `user_level` filters); secrets in source; new `FROM`/`uses:`/`COPY --from=` lines that are not digest- or SHA-pinned.
2. **Correctness** — logic errors, unhandled error paths, off-by-one and null cases, race conditions. In `apps/proxy` everything runs under gevent: a blocking call (`time.sleep` without gevent, synchronous `subprocess.Popen`, blocking sockets) stalls every stream on that worker and is a defect. No channel state may live in Python memory — four uWSGI workers.
3. **Data safety** — migrations shipped with model changes and reversible; no destructive migration on shared tables; settings writes are instance-wide.
4. **Tests** — behaviour changes with no test, or tests that would pass against the pre-change code. Tests must not set `CELERY_TASK_ALWAYS_EAGER` globally.
5. **Repo conventions** — DRF serializers for every endpoint (never raw dicts); frontend HTTP only through `frontend/src/api.js`; global state in Zustand stores, not React Context; no new UI libraries; no new dependencies without justification in the PR body.

Do **not** comment on formatting, naming preferences, or alternative designs of equal merit. Do not restate what the diff does.

## How to report

For each finding, call `create_pull_request_review_comment` with:

- `path` — the file path exactly as it appears in the diff.
- `line` — a RIGHT-side number taken from `.pr-review/pr.annotated.diff`. For a multi-line range also pass `start_line` (must be strictly less than `line`, same hunk).
- `body` — start with one of `**[blocking]**`, `**[should-fix]**`, or `**[question]**`, then state the problem, why it matters here, and the concrete fix or the evidence you need. Two to six sentences. Cite `file:line` for anything outside the commented range.

Combine related findings on the same lines into one comment. At most 15 comments; if you have more, keep the most severe and summarise the rest in the review body.

Then **always** call `submit_pull_request_review` exactly once with `event: COMMENT`, even when you found nothing. The body must contain:

- `Verdict: ready to merge` or `Verdict: changes needed` (changes needed if any comment is `[blocking]` or `[should-fix]`).
- A one-paragraph summary of what the change does and the risk you see in it.
- Counts by severity, and the summarised overflow findings if any.
- The exact phrase `Reviewed by kimi-k3 via gh-aw`.

## Rules

- Evidence only: quote the line or name the function you are judging. No generic advice, no speculative "consider" comments.
- If the diff is empty or purely documentation, submit the review with `Verdict: ready to merge` and no inline comments.
- Never approve, never request changes — the ruleset gates merge on thread resolution, not on your review event.
- Do not modify files, create branches, or open issues.
