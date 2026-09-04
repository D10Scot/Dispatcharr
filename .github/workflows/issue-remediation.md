---
description: Pick the highest-priority open bug issue, reproduce it, fix it, pass an independent model review, and open a draft PR.
emoji: 🔧
on:
  schedule: daily
  workflow_dispatch:
    inputs:
      issue_number:
        description: Force a specific issue number (skips priority selection)
        required: false
        default: ""
        type: string
  stop-after: "+90d"
permissions:
  contents: read
  issues: read
  pull-requests: read
# Kimi K3 main agent: gpt-5.6-sol hits OpenAI's cybersecurity classifier
# (HTTP 422) when reproducing security findings. The reviewer sub-agent below
# stays on claude-sonnet-5.
model: kimi-k3
timeout-minutes: 60
features:
  group-concurrency-queue: false
concurrency:
  group: issue-remediation
  cancel-in-progress: false
tools:
  github:
    mode: gh-proxy
    toolsets: [default]
network:
  allowed:
    - defaults
    - python
    - node
steps:
  - name: Select highest-priority eligible issue
    id: select_issue
    env:
      GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
      FORCED_ISSUE: ${{ github.event.inputs.issue_number }}
      REPO: ${{ github.repository }}
    run: |
      set -euo pipefail
      python3 - <<'PY'
      import json, os, random, subprocess, sys

      repo = os.environ["REPO"]
      forced = (os.environ.get("FORCED_ISSUE") or "").strip()

      def gh(*args):
          return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout

      def noop(message):
          path = os.environ.get("GH_AW_SAFE_OUTPUTS")
          if path:
              with open(path, "a") as f:
                  f.write(json.dumps({"type": "noop", "message": message}) + "\n")
          print(f"noop: {message}")
          sys.exit(0)

      def has_open_fix_pr(number):
          """True if an open PR already targets this issue (closing reference)."""
          query = """
          query($owner: String!, $name: String!, $number: Int!) {
            repository(owner: $owner, name: $name) {
              issue(number: $number) {
                closedByPullRequestsReferences(first: 10, includeClosedPrs: false) {
                  totalCount
                }
              }
            }
          }"""
          owner, name = repo.split("/")
          out = gh("api", "graphql", "-f", f"query={query}",
                   "-f", f"owner={owner}", "-f", f"name={name}",
                   "-F", f"number={number}")
          refs = json.loads(out)["data"]["repository"]["issue"]["closedByPullRequestsReferences"]
          return refs["totalCount"] > 0

      if forced:
          raw = gh("issue", "view", forced, "--repo", repo,
                   "--json", "number,title,state,labels,url")
          issue = json.loads(raw)
          if issue["state"] != "OPEN":
              noop(f"Forced issue #{forced} is not open")
          selected = issue
          priority = next((l["name"] for l in issue["labels"]
                           if l["name"].startswith("priority:")), "unlabeled")
      else:
          raw = gh("issue", "list", "--repo", repo, "--state", "open",
                   "--limit", "200", "--json", "number,title,labels,url")
          issues = json.loads(raw)
          excluded = {"wontfix", "needs-info"}
          tiers = {}
          for issue in issues:
              names = {l["name"] for l in issue["labels"]}
              if names & excluded:
                  continue
              # Only triaged issues: the triage workflow must have routed it
              # to the agent (and removed needs-triage) before we pick it up.
              if "ready-for-agent" not in names:
                  continue
              prio = sorted(n for n in names if n.startswith("priority:p"))
              if not prio:
                  continue
              tiers.setdefault(prio[0], []).append(issue)
          if not tiers:
              noop("No open ready-for-agent issues carry a priority:p* label (excluding wontfix/needs-info)")

          selected, priority = None, None
          for prio in sorted(tiers):  # p0 < p1 < p2 < p3 lexically
              candidates = [i for i in tiers[prio] if not has_open_fix_pr(i["number"])]
              if candidates:
                  # Random among same-priority ties, seeded per run for a debuggable log.
                  rng = random.Random(int(os.environ.get("GITHUB_RUN_ID", "0")))
                  selected, priority = rng.choice(candidates), prio
                  break
          if selected is None:
              noop("Every priority-labelled issue already has an open fix PR")

      num = selected["number"]
      # Full issue body + comments, staged in the workspace so the agent
      # reads a file instead of spending tool calls on the GitHub API.
      context = gh("issue", "view", str(num), "--repo", repo, "--comments")
      os.makedirs(".issue-context", exist_ok=True)
      with open(f".issue-context/issue-{num}.md", "w") as f:
          f.write(context)

      with open(os.environ["GITHUB_ENV"], "a") as env:
          env.write(f"ISSUE_NUMBER={num}\n")
          env.write(f"ISSUE_PRIORITY={priority}\n")
          env.write(f"ISSUE_URL={selected['url']}\n")
      print(f"Selected #{num} ({priority}): {selected['title']}")
      PY
  - name: Set up Python 3.13
    if: env.ISSUE_NUMBER != ''
    uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0
    with:
      python-version: "3.13"
  - name: Set up uv
    if: env.ISSUE_NUMBER != ''
    uses: astral-sh/setup-uv@v10.0.1
    with:
      enable-cache: true
      cache-suffix: issue-remediation
  - name: Install backend dependencies into .venv
    if: env.ISSUE_NUMBER != ''
    run: |
      set -euo pipefail
      uv sync --locked --no-install-project --no-dev --python "$(command -v python)"
      DJANGO_SECRET_KEY=issue-remediation TEST_USE_SQLITE=1 DJANGO_SETTINGS_MODULE=dispatcharr.settings_test \
        .venv/bin/python -c "import django; django.setup(); print('django', django.get_version(), 'ok')"
  - name: Stage Redis binaries for the agent sandbox
    if: env.ISSUE_NUMBER != ''
    run: |
      set -euo pipefail
      if ! command -v redis-server >/dev/null 2>&1; then
        sudo apt-get update -qq
        sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends redis-server redis-tools
      fi
      mkdir -p .fuzz-env/bin
      cp "$(command -v redis-server)" "$(command -v redis-cli)" .fuzz-env/bin/
      .fuzz-env/bin/redis-server --version
  - name: Export runtime environment for the agent
    if: env.ISSUE_NUMBER != ''
    run: |
      set -euo pipefail
      {
        echo "DJANGO_SECRET_KEY=issue-remediation"
        echo "TEST_USE_SQLITE=1"
        echo "DISPATCHARR_LOG_LEVEL=WARNING"
      } >> "$GITHUB_ENV"
safe-outputs:
  create-pull-request:
    title-prefix: "[issue-fix] "
    draft: true
    max: 1
    if-no-changes: "error"
  add-comment:
    target: "*"
    max: 2
  add-labels:
    target: "*"
    allowed: [needs-info, needs-triage]
    max: 1
  noop:
    report-as-issue: false
---

# Issue remediation

## Environment (already prepared — do not rediscover)

- All backend Python deps are installed in `.venv` (from `uv.lock`). Do not pip/uv install anything.
- `DJANGO_SECRET_KEY`, `TEST_USE_SQLITE=1`, and `DISPATCHARR_LOG_LEVEL=WARNING` are already exported. Tests use SQLite; Postgres is not available. PG-only tests self-skip.
- Start Redis once before running tests:
  `./.fuzz-env/bin/redis-server --daemonize yes --port 6379 --save '' --appendonly no && ./.fuzz-env/bin/redis-cli flushall`
- Run tests with: `.venv/bin/python manage.py test <label>` — never pass `--settings`.

## Assigned issue (chosen deterministically — do not pick a different one)

- Issue: `$ISSUE_NUMBER` (priority `$ISSUE_PRIORITY`) — `$ISSUE_URL` (environment variables; `echo` them if needed)
- The full issue body and all comments are already staged at `.issue-context/issue-$ISSUE_NUMBER.md`. Read that file first; do not re-fetch the issue from the API.

## Workflow

Work through these phases in order. Do not skip the reproduction phase.

### 1. Reproduce

Reproduce the reported problem before changing any code. If the issue contains a repro harness (look for a `<details>` block), run it verbatim. Otherwise write a minimal failing Django test that demonstrates the defect.

- **Reproduced** → keep the failing test/repro output as evidence and continue.
- **Cannot reproduce** (after a genuine attempt, including on the exact code paths the issue names) → do NOT guess a fix. Post one comment on issue `$ISSUE_NUMBER` explaining exactly what you ran and what you observed, apply the `needs-info` label to it, then stop with `noop`.
- If infrastructure needed for reproduction is unavailable in this runtime, say so in the comment — never claim a check ran when it didn't.

### 2. Fix

Make the smallest correct change that fixes the root cause. Follow repo conventions: DRF serializers for endpoints, migrations shipped with model changes, no new dependencies, no credentials or URLs-with-passwords in log statements. Do not edit files under `.github/workflows/`.

Convert your reproduction into a permanent regression test committed with the fix, unless an equivalent test already exists.

### 3. Verify (mirrors the repo's commit gate — all of it is required)

1. Collect changed paths: `git diff --name-only` (plus any untracked files you added).
2. Map them to test labels exactly as CI does: `.venv/bin/python scripts/ci_backend_test_labels.py <changed paths...>` (prints a JSON list).
3. Flush Redis (`./.fuzz-env/bin/redis-cli flushall`), then run every returned label: `.venv/bin/python manage.py test <labels...>`. All must pass, including your new regression test.
4. If you changed any `models.py`: `.venv/bin/python manage.py makemigrations --check --dry-run` must report no pending migrations.
5. If you changed anything under `frontend/`: `cd frontend && npm ci && npm test` must pass.
6. Re-run your original reproduction and confirm it no longer fails.

If verification fails and you cannot converge after a few focused attempts, stop: post a comment on the issue summarising your findings, partial diagnosis, and what blocked you — that is a useful outcome; a broken PR is not.

### 4. Independent review (gate before any PR)

Once verification passes, invoke the `remediation-reviewer` sub-agent (it runs on a different model). Tell it only: the issue number, a one-sentence summary of the fix, and that the change set is the current uncommitted diff — it reads the diff itself. It returns findings classified `MAJOR` (correctness, security, data loss, missed root cause, missing/inadequate regression test, repo-convention violation) or `MINOR` (style, naming, optional hardening, non-blocking suggestions).

- **MAJOR findings** → address every one (return to phase 2/3: fix, then re-verify), then invoke the reviewer again on the updated diff. At most **2** remediation cycles after the first review.
- If MAJOR findings remain after the second cycle → do NOT create a PR. Post one comment on issue `$ISSUE_NUMBER` with the fix diff summary, the outstanding MAJOR findings, and why they weren't resolved, then stop.
- **No MAJOR findings** → proceed to phase 5. Carry any MINOR findings forward.

### 5. Pull request

Create one draft PR containing the fix and regression test, with `temporary_id: aw_fix_pr`. The body must include:

- `Fixes #$ISSUE_NUMBER` on its own line
- If `metrics/curated/defects.yml` has an entry whose `issue` is this issue, set its `status` to `fixed`, `fixed_in` to the PR number (use the temporary id if the number is not known yet) and `status_changed` to today, in the same commit; `docs/agents/metrics.md` has the rules.
- what was wrong (root cause, files/lines)
- how the fix works
- reproduction evidence: failing output before, passing output after
- exact verification commands run and their results
- the review verdict (reviewer model, cycles used, "no major findings")

If the reviewer reported MINOR findings you did not action, post one additional comment targeting the new PR (`item_number: "#aw_fix_pr"`) listing each recommendation and, per item, one sentence on why it was deferred in this run (out of scope for the issue, risk/benefit, etc.). If there were no unactioned MINOR findings, post no PR comment.

## Rules

- One issue per run; scope the diff to that issue only. No drive-by refactoring.
- Report only evidence you actually obtained. If a check did not run, say so.
- Never skip the review phase, and never create a PR with unresolved MAJOR findings.
- If the run nears timeout, prefer a complete comment on the issue over an unverified PR.

## agent: `remediation-reviewer`

---
description: Independent second-model reviewer for remediation diffs
model: claude-sonnet-5
---

You are an independent code reviewer for the Dispatcharr repository. You did not write the change under review; judge it on evidence only.

Input: an issue number and a one-line fix summary. The change set is the current uncommitted working-tree diff — inspect it with `git diff` and `git status` (include untracked test files). The issue context is staged at `.issue-context/issue-<number>.md`.

Review for, in priority order:

1. Does the change actually fix the root cause described in the issue, or only a symptom?
2. Correctness regressions: edge cases, error paths, concurrency (this repo runs under gevent — blocking calls in `apps/proxy` are defects), resource leaks.
3. Security: credentials in logs, auth checks bypassed, injection.
4. Regression test: present, committed with the fix, and would it genuinely fail on the pre-fix code?
5. Repo conventions: DRF serializers for endpoints, migrations with model changes, no new dependencies, diff scoped to the one issue.

Output exactly this format and nothing else:

```
VERDICT: APPROVED | CHANGES_REQUIRED
MAJOR:
- <finding with file:line and why it blocks> (or "none")
MINOR:
- <suggestion with file:line and rationale> (or "none")
```

MAJOR is reserved for findings that make the PR wrong to merge as-is. Style preferences, optional hardening, and alternative approaches of equal merit are MINOR. Do not modify any files. Be specific; no generic advice.

## end agent: `remediation-reviewer`
