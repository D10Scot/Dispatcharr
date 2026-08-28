---
description: Verify CLAUDE.md's factual claims against the current code and open a draft PR fixing anything stale.
emoji: 📖
on:
  schedule: weekly
  workflow_dispatch:
  stop-after: "+90d"
permissions:
  contents: read
  issues: read
  pull-requests: read
model: gpt-5.6-sol
timeout-minutes: 30
features:
  group-concurrency-queue: false
concurrency:
  group: claude-md-maintenance
  cancel-in-progress: false
tools:
  github:
    mode: gh-proxy
    toolsets: [default]
network:
  allowed:
    - defaults
steps:
  - name: Stage the change window since CLAUDE.md was last touched
    id: stage_context
    env:
      GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
      REPO: ${{ github.repository }}
    run: |
      set -euo pipefail
      python3 - <<'PY'
      import json, os, subprocess, sys

      repo = os.environ["REPO"]

      def run(*args):
          return subprocess.run(args, check=True, capture_output=True, text=True).stdout

      def noop(message):
          path = os.environ.get("GH_AW_SAFE_OUTPUTS")
          if path:
              with open(path, "a") as f:
                  f.write(json.dumps({"type": "noop", "message": message}) + "\n")
          print(f"noop: {message}")
          sys.exit(0)

      # One maintenance PR at a time: if a previous run's PR is still open,
      # this run has nothing to add that a human hasn't already seen.
      prs = json.loads(run("gh", "pr", "list", "--repo", repo, "--state", "open",
                           "--search", "[claude-md] in:title", "--json", "number,title"))
      stale_prs = [p for p in prs if p["title"].startswith("[claude-md]")]
      if stale_prs:
          noop(f"Maintenance PR #{stale_prs[0]['number']} is still open; review it first")

      last = run("git", "log", "-1", "--format=%H", "--", "CLAUDE.md").strip()
      if not last:
          noop("CLAUDE.md has no history; nothing to maintain")

      commits = run("git", "log", "--oneline", "--no-merges", f"{last}..HEAD").strip()
      if not commits:
          noop("No commits since CLAUDE.md was last updated; nothing can have drifted")

      changed = run("git", "diff", "--name-only", f"{last}..HEAD").strip()

      os.makedirs(".claude-md-context", exist_ok=True)
      with open(".claude-md-context/commits.txt", "w") as f:
          f.write(f"# Commits since CLAUDE.md was last touched ({last[:10]}):\n")
          f.write(commits + "\n")
      with open(".claude-md-context/changed-files.txt", "w") as f:
          f.write(changed + "\n")

      n = len(commits.splitlines())
      with open(os.environ["GITHUB_ENV"], "a") as env:
          env.write(f"DOC_LAST_COMMIT={last}\n")
          env.write(f"COMMITS_SINCE={n}\n")
      print(f"{n} commits since {last[:10]}; context staged in .claude-md-context/")
      PY
safe-outputs:
  create-pull-request:
    title-prefix: "[claude-md] "
    draft: true
    max: 1
    if-no-changes: "error"
  noop:
    report-as-issue: false
---

# CLAUDE.md maintenance

CLAUDE.md is this repository's agent onboarding document. It is dense with
factual claims — file paths, behaviours, defect lists, workflow inventories,
counts — and every claim was verified against the code at some commit. Code
moves; the document drifts. Your job is to find and fix the drift.

## Environment (already prepared — do not rediscover)

- The repository is checked out at HEAD.
- `$DOC_LAST_COMMIT` is the last commit that touched CLAUDE.md; `$COMMITS_SINCE`
  commits have landed since (environment variables; `echo` them if needed).
- `.claude-md-context/commits.txt` lists those commits; `.claude-md-context/changed-files.txt`
  lists every path they changed. Read both first — they scope your verification.
- This run is **read-only on everything except CLAUDE.md**. Do not run tests,
  install anything, or modify any other file.

## Procedure

### 1. Scope

Read CLAUDE.md in full, then the staged context. Build a checklist of claims
to verify, in two tiers:

- **Tier 1 — touched areas (verify every affected claim).** For each changed
  path, find every CLAUDE.md statement that describes it: file existence,
  behaviour, wiring ("referenced nowhere", "wired into no workflow"), counts,
  and entries in "Known defects and traps" naming that path.
- **Tier 2 — cheap global invariants (verify all, every run).** Claims that
  re-derive in one command regardless of what changed: the workflow inventory
  (`ls .github/workflows/`), existence of files the doc calls dead or missing
  (`hls_proxy/`, `entrypoint.aio.sh`, `persistent_lock.py`, `renovate.json`,
  absence of `.github/zizmor.yml`), the `npm install` vs `npm ci` claim in
  `docker/Dockerfile`, and the docs the "Agent skills" section points at
  (`docs/agents/*.md`, `CONTEXT.md`, `docs/adr/`).

### 2. Verify

Check each claim with file reads and grep against the checkout. Standards:

- A claim is **stale** only when the code contradicts it — never because you
  couldn't find confirmation quickly. When unsure, leave the claim alone.
- Defect entries in "Known defects and traps" are load-bearing warnings.
  Remove or soften one **only** when you can cite the specific commit or
  current code that fixes it, and say so in the PR body. If the defect merely
  moved, update the location.
- Line numbers: the doc's convention is that line numbers drift. Where a cited
  line number is now wrong, prefer dropping it (the path plus symbol name is
  enough) over chasing the new number.
- Counts and statistics (LOC, test counts, coverage) are approximations by
  convention. Update one only if it is now wrong by enough to mislead
  (roughly ±20% or a changed order of magnitude); otherwise leave it.

### 3. Edit

Apply your verified corrections to CLAUDE.md, preserving its character:

- Keep the voice: dense, imperative, evidence-first. Every sentence earns its
  tokens. Where a correction lets you also tighten wording, do — this doc has
  a standing goal of maximal information per token.
- Add a new claim only when the change window introduced something a future
  agent must know (a new workflow, a new test suite, a removed subsystem) —
  and only what you verified yourself.
- Never weaken a security warning, a "do not" instruction, or an intent
  statement (the phased-extraction plan, scope discipline) without code-level
  evidence that it no longer applies.
- Diff scope is CLAUDE.md **only**. Do not stage or modify any other file;
  `.claude-md-context/` must not appear in the diff.

### 4. Outcome

- **Nothing stale found** → do not create a PR. Emit `noop` with a one-line
  summary of what you verified. A run that confirms the doc is accurate is a
  success, not a failure.
- **Corrections made** → create one draft PR. The body must contain:
  - a table of every claim checked: claim → verdict (`accurate` / `stale` /
    `removed`) → evidence (file:symbol or commit SHA you verified against)
  - for each edit, one sentence on why
  - the commit range examined (`$DOC_LAST_COMMIT..HEAD`)

## Rules

- Report only checks you actually ran, against evidence you actually read.
  Never claim a verification you did not perform.
- One PR per run at most; if the change window is enormous, prioritise Tier 2
  plus the most safety-relevant Tier 1 claims and say in the PR body what was
  not checked.
- If the staged context files are missing, stop with `noop` explaining that —
  do not reconstruct them yourself.
