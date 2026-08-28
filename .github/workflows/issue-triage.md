---
description: Triage one needs-triage issue per run — validate, dedupe, audit priority, and route it.
emoji: 🏷️
on:
  issues:
    types: [opened, reopened]
  schedule: daily
  workflow_dispatch:
    inputs:
      issue_number:
        description: Force a specific issue number (skips selection)
        required: false
        default: ""
        type: string
  stop-after: "+90d"
permissions:
  contents: read
  issues: read
  pull-requests: read
model: gpt-5.4-mini
timeout-minutes: 20
features:
  group-concurrency-queue: false
concurrency:
  group: issue-triage
  cancel-in-progress: false
tools:
  github:
    mode: gh-proxy
    toolsets: [default]
network:
  allowed:
    - defaults
steps:
  - name: Select issue to triage
    id: select_issue
    env:
      GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
      EVENT_ISSUE: ${{ github.event.issue.number }}
      FORCED_ISSUE: ${{ github.event.inputs.issue_number }}
      REPO: ${{ github.repository }}
    run: |
      set -euo pipefail
      python3 - <<'PY'
      import json, os, subprocess, sys

      repo = os.environ["REPO"]

      def gh(*args):
          return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout

      def noop(message):
          path = os.environ.get("GH_AW_SAFE_OUTPUTS")
          if path:
              with open(path, "a") as f:
                  f.write(json.dumps({"type": "noop", "message": message}) + "\n")
          print(f"noop: {message}")
          sys.exit(0)

      # Event payload first, then a forced dispatch input, then the oldest
      # open needs-triage issue as the scheduled-sweep backstop.
      target = (os.environ.get("EVENT_ISSUE") or "").strip() \
            or (os.environ.get("FORCED_ISSUE") or "").strip()

      if target:
          raw = gh("issue", "view", target, "--repo", repo,
                   "--json", "number,title,state,labels,url")
          issue = json.loads(raw)
          if issue["state"] != "OPEN":
              noop(f"Issue #{target} is not open; nothing to triage")
          names = {l["name"] for l in issue["labels"]}
          if "needs-triage" not in names:
              noop(f"Issue #{target} does not carry needs-triage; already triaged")
      else:
          raw = gh("issue", "list", "--repo", repo, "--state", "open",
                   "--label", "needs-triage", "--limit", "200",
                   "--json", "number,title,labels,url,createdAt")
          issues = json.loads(raw)
          if not issues:
              noop("No open issues labelled needs-triage")
          issue = min(issues, key=lambda i: i["createdAt"])  # oldest first

      num = issue["number"]
      priority = next((l["name"] for l in issue["labels"]
                       if l["name"].startswith("priority:")), "none")

      # Full issue body + comments, staged in the workspace so the agent
      # reads a file instead of spending tool calls on the GitHub API.
      context = gh("issue", "view", str(num), "--repo", repo, "--comments")
      os.makedirs(".issue-context", exist_ok=True)
      with open(f".issue-context/issue-{num}.md", "w") as f:
          f.write(context)

      with open(os.environ["GITHUB_ENV"], "a") as env:
          env.write(f"ISSUE_NUMBER={num}\n")
          env.write(f"ISSUE_PRIORITY={priority}\n")
          env.write(f"ISSUE_URL={issue['url']}\n")
      print(f"Selected #{num} (reporter priority: {priority}): {issue['title']}")
      PY
safe-outputs:
  add-comment:
    target: "*"
    max: 1
  add-labels:
    target: "*"
    allowed:
      - ready-for-agent
      - ready-for-human
      - needs-info
      - wontfix
      - priority:p0
      - priority:p1
      - priority:p2
      - priority:p3
    max: 2
  remove-labels:
    target: "*"
    allowed:
      - needs-triage
      - priority:p0
      - priority:p1
      - priority:p2
      - priority:p3
    max: 2
  noop:
    report-as-issue: false
---

# Issue triage

## Environment (already prepared — do not rediscover)

- The issue under triage is `$ISSUE_NUMBER` — `$ISSUE_URL`, reporter-assigned priority `$ISSUE_PRIORITY` (environment variables; `echo` them if needed).
- Its full body and all comments are already staged at `.issue-context/issue-$ISSUE_NUMBER.md`. Read that file first; do not re-fetch the issue from the API.
- The repository is checked out. Triage is **read-only on code**: verify claims with file reads and grep in the checkout. Do not run tests, install anything, or modify any file.
- Triage exactly this one issue. Do not select a different one.

## Decision procedure

Work through these checks in order; the first terminal verdict wins. Steps 1–3 each end the triage with `wontfix`; steps 4–6 combine.

1. **Validity.** Cross-check every claimed file, line, and function against the actual code in the checkout — fuzz reporters sometimes hallucinate symbols or cite stale line numbers. Line drift alone is not invalidity: if the described defect exists nearby, treat the claim as valid and note the real location. If the report does not describe a real defect in the current code → comment explaining exactly what you checked and why it is invalid, add `wontfix`.
2. **Duplicate.** Search existing issues, open **and** closed, for the same root cause (search by symptom, file, and function names — titles differ between reports of the same defect). If a duplicate exists → comment linking the original issue, add `wontfix`. Do not close the issue; a human closes duplicates.
3. **Known or deliberate.** Check the "Known defects and traps" section of `CLAUDE.md` in the repo root. If the finding is already documented there, or is documented deliberate behaviour (e.g. the VOD stream-counter lock bypass), it is not new → comment citing the relevant entry, add `wontfix`.
4. **Priority audit.** Validate the reporter's `priority:p*` label against this rubric **and** against how likely the trigger is in normal operation (default config, realistic usage):
   - `priority:p0` — crash, data loss, or security impact in the default configuration
   - `priority:p1` — user-visible breakage or corruption under realistic conditions
   - `priority:p2` — reliability/performance risk needing an unusual trigger
   - `priority:p3` — minor issue or test gap

   If the label is wrong, remove the old `priority:p*` label and add the correct one, with one sentence of reasoning in your comment. If it is right (or absent and unjudgeable), leave it alone and say so.
5. **Actionability.** A remediation agent needs a runnable reproduction (look for a `<details>` repro-harness block) and named affected paths. If essentials are missing → comment listing exactly what is needed, add `needs-info`, and skip step 6.
6. **Routing.** If the fix is mechanically within an agent's reach (localised code change, clear repro, no design decisions) → add `ready-for-agent`. If it requires architectural or design judgment — anything touching the ownership-lease design, the cross-process state model, or security-posture decisions → add `ready-for-human`.

**Every outcome** ends by removing `needs-triage`.

## Rules

- Report only checks you actually ran, against evidence you actually read. Never claim a code cross-check, duplicate search, or CLAUDE.md lookup you did not perform.
- Do not modify code, do not create pull requests, do not close issues.
- If the staged context file is missing or unreadable, stop with `noop` explaining that — do not guess.

## Output contract

Emit exactly:

1. **One comment** on issue `$ISSUE_NUMBER` summarising the verdict: which checks ran, the evidence (file:line references you verified, duplicate issue numbers, CLAUDE.md entries), the priority decision with its one-sentence rationale, and the routing outcome. Keep it under ~300 words.
2. **The label operations** that implement the verdict: at most two `add-labels` (routing/verdict label, plus a corrected priority label if step 4 changed it) and at most two `remove-labels` (`needs-triage` always; the old `priority:p*` label only on a priority swap).

Nothing else.
