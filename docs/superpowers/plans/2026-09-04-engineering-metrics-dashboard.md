# Engineering Metrics Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the M1/M2/M3 metrics stack with a three-layer system: raw-fact collectors, a
tested Python build step that emits one `site.json`, and five static pages that render it.

**Architecture:** Collectors on `main` write per-commit snapshot rows and daily GitHub event
dumps to the `metrics-data` orphan branch. `python -m metrics.build` reads that branch plus
three agent-maintained YAML files under `metrics/curated/`, validates everything, derives
every series and delta, and writes `site.json`. `dashboard/` is vanilla ES-module JavaScript
over that file with vendored uPlot; it draws and never computes. Three PRs, one per part.

**Tech Stack:** Python 3.12+ stdlib + PyYAML 6.0.3 (build step), `gh` CLI 2.51+ (`--slurp`),
`coverage` 7.x, vitest 4 + jsdom (already in `frontend/`), uPlot 1.6.32 (already vendored),
GitHub Actions + Pages.

**Spec:** `docs/superpowers/specs/2026-09-04-engineering-metrics-dashboard-design.md`

## Global Constraints

- **Three PRs, three branches, each its own worktree off `main`** (CLAUDE.md "Isolation for
  new work"): Part A `metrics-data-layer`, Part B `metrics-build-step`, Part C
  `metrics-dashboard-pages`. Part B branches from `main` after A merges; C after B.
- **Stage and commit in separate Bash calls.** The commit gate matches on command text, so
  never put `git add` and `git commit` in one call, and write commit messages to a file with
  the Write tool and commit with `-F <file>` when the message contains those words.
- **Every `.py` edit is checked by `scripts/check_credential_logging.py`** (hook + `lint.yml`).
  Collectors log URLs: use `logging` only at DEBUG and never log a token or header. A log
  call naming a URL that is not a credential can be annotated
  `# credential-logging: ignore - <reason>`.
- **Every workflow edit must leave the file at zero zizmor findings.** Every `uses:` is a
  full 40-char SHA with a `# vX.Y.Z` trailing comment, resolved with
  `gh api repos/<owner>/<repo>/commits/<tag> --jq .sha`, never hand-typed. Every checkout has
  `persist-credentials: false`. Top-level `permissions: contents: read`.
- **Build-step and collector code must run on the bare runner's `python3` (3.12)**: no
  3.13-only syntax, no third-party imports except `yaml` in `metrics/build/`.
- **Collectors never compute a trend, delta or status.** Derivations live only in
  `metrics/build/derive.py`.
- **`gh` calls always pass `--repo` / an explicit `/repos/<owner>/<repo>` path.**
- **Baseline commit is `fd413f0cc4ab3131789a68fb31f1ae622ae7371a`** (v0.29.0).

### Spec amendments made by this plan (apply to the spec in the same PR that implements them)

1. **§4.1 coverage row (Part A, Task 5):** backend coverage runs each of the 16 labels as its
   own `coverage run -p` process and combines, mirroring CI's per-label isolation; the row
   carries `backend_failed_labels: [...]` and `backend_status: "failed"` when any label failed,
   but still reports the combined pct. The spec's "pct null on failure" would null every day
   the known order-dependent failures fire, which is every day.
2. **§5.1 catalogue schema (Part B, Task 9):** derived metrics use `family: derived` with
   `derivation: <name>` and `params: {...}` instead of overloading `path`.
3. **§5.2 milestones file (Part B, Task 9):** the file has two top-level keys, `phases:` (with
   `headline_ids` per phase, which the Story page needs and which cannot be derived) and
   `milestones:`.
4. **§5.3 defect ledger (Part B, Task 9):** an `open` entry needs `issue` **or** `source`
   (a CLAUDE.md heading anchor); half the listed defects have no issue yet and filing ten
   issues is not this work.

## File Structure

```
metrics/                                 NEW root package (Part B)
  __init__.py
  requirements.txt                       pyyaml==6.0.3, hash-pinned from uv.lock
  curated/catalogue.yml                  metric catalogue (agent-maintained)
  curated/milestones.yml                 phases + milestones (agent-maintained)
  curated/defects.yml                    known-defect ledger (agent-maintained)
  build/__init__.py
  build/__main__.py                      CLI: --data --curated --out | --validate-only
  build/gitinfo.py                       first-parent SHAs, commit dates, PR-merged check
  build/curated.py                       schemas + validators for the three YAML files
  build/load.py                          snapshot rows + event dumps (+ history sidecars)
  build/derive.py                        every derivation, pure functions
  build/calendar_.py                     daily resampling, forward fill, status rule (underscore: stdlib name clash)
  build/assemble.py                      assemble site.json (not site.py: stdlib name clash)
  build/tests/__init__.py
  build/tests/fixtures/data/...          tiny metrics-data tree
  build/tests/fixtures/curated/...       valid + invalid curated files
  build/tests/test_*.py                  one module per build module

scripts/metrics/                         collectors (Part A)
  _common.py                             unchanged
  _gh.py                                 MODIFY: --slurp + page flattening
  collect_all.py                         MODIFY: independent families, --only, external family
  collect_tests.py                       MODIFY: exclude metrics/ + scripts/, add coverage_md_rows
  collect_events.py                      NEW: event dumps + history sidecars
  coverage_summary.py                    NEW: coverage.json + vitest summary -> row metrics
  collect_security.py / collect_delivery.py / collect_agentic.py   DELETE
  README.md                              REWRITE
  tests/__init__.py, tests/_fake_gh.py, tests/test_*.py            NEW
scripts/ci_coverage_backend.sh           NEW: per-label coverage loop
scripts/ci_bootstrap_backend.sh          MODIFY: CI_BACKEND_RUNNER override
scripts/run_metrics_tests.sh             NEW: one entry point for both unittest suites
.coveragerc                              NEW
pyproject.toml, uv.lock                  MODIFY: add coverage
.github/workflows/metrics.yml            MODIFY: cadence, permissions, coverage job
.github/workflows/lint.yml               MODIFY: metrics-tests job
.claude/hooks/run-affected-tests.sh      MODIFY: metrics/ + scripts/metrics/ + dashboard/ rules
.claude/hooks/pre-commit-tests.sh        MODIFY: same paths -> run_metrics_tests.sh / dashboard tests

dashboard/                               REWRITE (Part C)
  index.html story.html explore.html compare.html defects.html
  app.js                                 boot: fetch site.json, dispatch to page
  lib/format.js lib/spark.js lib/compare.js lib/status.js lib/chart.js
  pages/overview.js pages/story.js pages/explore.js pages/compare.js pages/defects.js
  style.css
  vendor/uplot/                          unchanged
  tests/*.test.js, tests/fixtures/site.json
  README.md                              REWRITE
  data.js overview.js trends.js trends.html presentation.html presentation.js milestones.json   DELETE
frontend/vitest.dashboard.config.js      NEW
.github/workflows/pages.yml              MODIFY: run the build step
docs/agents/metrics.md                   NEW (Part B)
CLAUDE.md                                MODIFY: pointer + hook line (Part B)
.github/workflows/issue-remediation.md   MODIFY: ledger sentence (+ recompiled .lock.yml)
```

---

# Part A — Data layer (`metrics-data-layer`)

Setup for Part A:

```bash
cd /Users/dion/git/Dispatcharr
git fetch origin main
git worktree add ../Dispatcharr-metrics-a -b metrics-data-layer origin/main
cd ../Dispatcharr-metrics-a
```

### Task 1: One test entry point, wired into the hook, the commit gate and CI

The collector tests (Part A) and build-step tests (Part B) are plain `unittest`, run without
Django, Postgres or Docker. This task lands the runner and the wiring first so every later
task's tests run in all three places.

**Files:**
- Create: `scripts/run_metrics_tests.sh`
- Create: `scripts/metrics/tests/__init__.py` (empty)
- Modify: `.claude/hooks/run-affected-tests.sh` (the `tests` case block, before `*tests/test_*.py`)
- Modify: `.claude/hooks/pre-commit-tests.sh` (after the frontend block)
- Modify: `.github/workflows/lint.yml` (new job)

**Interfaces:**
- Produces: `scripts/run_metrics_tests.sh [collectors|build|all]` exits 0 on pass, 1 on
  failure, 3 when a suite directory does not exist yet (so Part A does not fail on the
  not-yet-existing `metrics/build/tests`).

- [ ] **Step 1: Write the runner**

```bash
#!/usr/bin/env bash
# Run the metrics unit tests: the collector suite (scripts/metrics/tests) and
# the build-step suite (metrics/build/tests). Both are plain unittest and need
# neither Django nor a database. Used by the PostToolUse hook, the commit
# gate and lint.yml, so the three can never disagree about what "passing" is.
#
# Interpreter: the project venv when present (it carries PyYAML), else python3.
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || exit 1

if [ -x .venv/bin/python ]; then PY=.venv/bin/python; else PY=python3; fi
WHICH="${1:-all}"
status=0
ran=0

run_suite() {
  local start="$1" top="$2"
  [ -d "$start" ] || return 3
  ran=1
  "$PY" -m unittest discover -s "$start" -t "$top" -v 2>&1 | tail -25
  return "${PIPESTATUS[0]}"
}

case "$WHICH" in
  collectors|all)
    run_suite scripts/metrics/tests scripts/metrics; rc=$?
    [ $rc -eq 3 ] || [ $rc -eq 0 ] || status=1
    ;;&
  build|all)
    run_suite metrics/build/tests metrics/build; rc=$?
    [ $rc -eq 3 ] || [ $rc -eq 0 ] || status=1
    ;;
  *) echo "usage: $0 [collectors|build|all]" >&2; exit 2 ;;
esac

[ $ran -eq 1 ] || { echo "no metrics test suites exist yet"; exit 3; }
exit $status
```

Note the `;;&` after the `collectors|all` arm: bash's "fall through and keep matching"
terminator, so `all` runs both arms.

- [ ] **Step 2: Make it executable and run it (expect exit 3: nothing to run yet)**

Run: `chmod +x scripts/run_metrics_tests.sh && scripts/run_metrics_tests.sh; echo "exit=$?"`
Expected: `no metrics test suites exist yet` and `exit=3`.

- [ ] **Step 3: Create the empty collector test package**

Run: `mkdir -p scripts/metrics/tests && : > scripts/metrics/tests/__init__.py`
Then: `scripts/run_metrics_tests.sh collectors; echo "exit=$?"` → `Ran 0 tests`, `exit=0`.

- [ ] **Step 4: Add the hook rule**

In `.claude/hooks/run-affected-tests.sh`, inside the final `# ---- tests ---` `case "$REL" in`,
insert this arm **before** the `*tests/test_*.py)` arm (bash takes the first match, and
`scripts/metrics/tests/test_x.py` would otherwise be sent to `manage.py test` in the container):

```bash
  metrics/*|scripts/metrics/*|scripts/run_metrics_tests.sh)
    # Plain unittest, no Django: the metrics collectors and the site build step.
    OUT="$(scripts/run_metrics_tests.sh all 2>&1)"; ST=$?
    case $ST in
      0) printf '%s\n' "$OUT" | grep -E '^(Ran |OK)' | head -2 ;;
      3) ;;
      *) block "metrics tests" "$(printf '%s' "$OUT" | tail -40)" ;;
    esac
    ;;
  dashboard/*.js|dashboard/*.html)
    if [ -d frontend/node_modules ]; then
      OUT="$(cd frontend && npx vitest --run --config vitest.dashboard.config.js 2>&1)"
      if [ $? -ne 0 ]; then
        block "dashboard tests" "$(printf '%s' "$OUT" | tail -40)"
      else
        printf '%s\n' "$OUT" | grep -E '^ +(Test Files|Tests)  ' | head -2
      fi
    else
      note "Did NOT run dashboard tests — frontend/node_modules missing. Run 'cd frontend && npm install'."
    fi
    ;;
```

Also update the header comment's table with two lines:

```
#   metrics      metrics/**, scripts/metrics/**   run_metrics_tests.sh   (blocking)
#   dashboard    dashboard/*.{js,html}   vitest (dashboard config)       (blocking)
```

- [ ] **Step 5: Add the commit-gate rule**

In `.claude/hooks/pre-commit-tests.sh`, after the `# ---------- frontend ----------` block and
before the `if [ ${#FAILED[@]} -gt 0 ]` report, add:

```bash
# ---------- metrics (collectors + build step, no Django) ----------
if printf '%s\n' "$PATHS" | grep -qE '^(metrics/|scripts/metrics/|scripts/run_metrics_tests\.sh)'; then
  OUT="$(scripts/run_metrics_tests.sh all 2>&1)"; ST=$?
  if [ $ST -ne 0 ] && [ $ST -ne 3 ]; then
    FAILED+=("metrics")
    REPORT+="$(printf '\n--- metrics ---\n%s\n' "$(printf '%s' "$OUT" | tail -30)")"
  fi
fi

# ---------- dashboard (vitest, dashboard config) ----------
if printf '%s\n' "$PATHS" | grep -q '^dashboard/'; then
  if [ -d frontend/node_modules ] && [ -f frontend/vitest.dashboard.config.js ]; then
    OUT="$(cd frontend && npx vitest --run --config vitest.dashboard.config.js 2>&1)"
    if [ $? -ne 0 ]; then
      FAILED+=("dashboard")
      REPORT+="$(printf '\n--- dashboard ---\n%s\n' "$(printf '%s' "$OUT" | grep -E 'FAIL|✗|Tests ' | head -20)")"
    fi
  else
    note "Commit gate: dashboard/ files are staged but the dashboard vitest config or frontend/node_modules is missing — dashboard tests were NOT run."
  fi
fi
```

- [ ] **Step 6: Add the CI job to `lint.yml`**

Append to `jobs:` in `.github/workflows/lint.yml`:

```yaml
  metrics-tests:
    name: metrics unit tests
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6.1.0
        with:
          persist-credentials: false

      - name: Install the build step's one dependency (hash-pinned)
        # metrics/requirements.txt appears in Part B; until then the file is
        # absent and this step is a no-op, which is why it is guarded.
        run: |
          if [ -f metrics/requirements.txt ]; then
            python3 -m pip install --require-hashes -r metrics/requirements.txt
          fi

      - name: Collector and build-step tests
        # Exit 3 means "no suite exists yet" (see scripts/run_metrics_tests.sh);
        # it is a pass here so the job can land before the suites do.
        run: |
          scripts/run_metrics_tests.sh all; rc=$?
          [ "$rc" -eq 3 ] && exit 0
          exit "$rc"
```

The hook lints the file with zizmor on save; it must report zero findings.

- [ ] **Step 7: Commit**

Write the message to a file with the Write tool, then:

```bash
git add scripts/run_metrics_tests.sh scripts/metrics/tests/__init__.py .claude/hooks/run-affected-tests.sh .claude/hooks/pre-commit-tests.sh .github/workflows/lint.yml
```

then, as a separate call, `git commit -F <msgfile>` with message
`ci(metrics): one unittest entry point for collectors and build step, wired into hook, gate and lint`.

### Task 2: `_gh.py` paginates correctly, proven with a fake `gh`

`gh api --paginate` prints one JSON document per page, concatenated. Once the fork crossed
100 PRs / 100 workflow runs (2026-09-01) `json.loads` started failing with `Extra data`.
`--slurp` (gh ≥ 2.51) wraps the pages in one array; this task adds it and flattens.

**Files:**
- Modify: `scripts/metrics/_gh.py`
- Create: `scripts/metrics/tests/_fake_gh.py`
- Create: `scripts/metrics/tests/test_gh.py`

**Interfaces:**
- Produces: `gh_api(repo, path, params=None, paginate=True, list_key=None) -> list | dict`.
  With `paginate=True` the result is always the **flattened list of records**: pages that
  are arrays are concatenated; pages that are objects with `list_key` (e.g. `workflow_runs`)
  have that key's arrays concatenated. With `paginate=False` the parsed single document.
- Produces: `fake_gh_env(tmp_dir, responses: dict[str, object]) -> dict[str, str]` in
  `_fake_gh.py`: returns an `env` with `PATH` prefixed by a directory containing a `gh`
  shim; `responses` maps a request path prefix to either one page (any JSON) or a list of
  pages (`{"pages": [...]}`), or `{"error": "HTTP 403: ..."}` to simulate failure.

- [ ] **Step 1: Write the fake `gh`**

`scripts/metrics/tests/_fake_gh.py`:

```python
"""A stand-in `gh` for collector tests.

Tests write a JSON responses file and put a `gh` shim on PATH that answers
`gh api [--paginate] [--slurp] <path>` from it. Everything else `gh` can do is
out of scope: the shim exits 64 on any other invocation so a test that reaches
a real `gh` subcommand fails loudly rather than hitting the network.

responses: { "<path-prefix>": <one page> | {"pages": [<page>, ...]} | {"error": "HTTP 403: nope"} }
The longest matching prefix wins. A request for a path with no match exits 64.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

SHIM = """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
if not args or args[0] != "api":
    sys.stderr.write("fake gh: unsupported invocation: %r\\n" % (args,))
    sys.exit(64)
paginate = "--paginate" in args
slurp = "--slurp" in args
path = next((a for a in args[1:] if a.startswith("/") or a.startswith("http")), None)
responses = json.load(open(os.environ["FAKE_GH_RESPONSES"]))
log = os.environ.get("FAKE_GH_LOG")
if log:
    with open(log, "a") as f:
        f.write(json.dumps(args) + "\\n")
match = max((k for k in responses if path is not None and path.split("?")[0].startswith(k)), key=len, default=None)
if match is None:
    sys.stderr.write("fake gh: no response for %s\\n" % path)
    sys.exit(64)
resp = responses[match]
if isinstance(resp, dict) and "error" in resp:
    sys.stderr.write("gh: %s (%s)\\n" % (resp["error"], resp["error"].split(":")[0]))
    sys.exit(1)
pages = resp["pages"] if isinstance(resp, dict) and "pages" in resp else [resp]
if paginate and slurp:
    print(json.dumps(pages))
elif paginate:
    for p in pages:
        print(json.dumps(p))
else:
    print(json.dumps(pages[0]))
"""


def fake_gh_env(tmp_dir: str | os.PathLike, responses: dict, log: bool = False) -> dict[str, str]:
    tmp = Path(tmp_dir)
    bin_dir = tmp / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    shim = bin_dir / "gh"
    shim.write_text(SHIM, encoding="utf-8")
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    responses_path = tmp / "responses.json"
    responses_path.write_text(json.dumps(responses), encoding="utf-8")
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["FAKE_GH_RESPONSES"] = str(responses_path)
    if log:
        env["FAKE_GH_LOG"] = str(tmp / "calls.log")
    return env


def calls(env: dict[str, str]) -> list[list[str]]:
    path = env.get("FAKE_GH_LOG")
    if not path or not Path(path).exists():
        return []
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line]
```

The shim writes the error text in the same `HTTP 403` shape real `gh` uses, so
`_extract_status` keeps working.

- [ ] **Step 2: Write the failing tests**

`scripts/metrics/tests/test_gh.py`:

```python
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from _fake_gh import fake_gh_env

HERE = Path(__file__).resolve().parent
COLLECTORS = HERE.parent


def run_gh_api(env, code):
    """Run a snippet against _gh.py in a subprocess so PATH (the fake gh) applies."""
    return subprocess.run(
        [sys.executable, "-c", "import sys; sys.path.insert(0, %r)\n%s" % (str(COLLECTORS), code)],
        env=env, capture_output=True, text=True, check=False,
    )


class GhApiTests(unittest.TestCase):
    def test_multi_page_array_is_flattened(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = fake_gh_env(tmp, {"/repos/o/r/pulls": {"pages": [[{"n": 1}, {"n": 2}], [{"n": 3}]]}})
            r = run_gh_api(env, "from _gh import gh_api; import json; print(json.dumps(gh_api('o/r', '/pulls')))")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.strip(), '[{"n": 1}, {"n": 2}, {"n": 3}]')

    def test_multi_page_object_with_list_key_is_flattened(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = fake_gh_env(tmp, {"/repos/o/r/actions/runs": {"pages": [
                {"total_count": 3, "workflow_runs": [{"id": 1}, {"id": 2}]},
                {"total_count": 3, "workflow_runs": [{"id": 3}]},
            ]}})
            r = run_gh_api(env, "from _gh import gh_api; import json; print(json.dumps(gh_api('o/r', '/actions/runs', list_key='workflow_runs')))")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.strip(), '[{"id": 1}, {"id": 2}, {"id": 3}]')

    def test_single_object_without_pagination(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = fake_gh_env(tmp, {"/repos/o/r": {"full_name": "o/r"}})
            r = run_gh_api(env, "from _gh import gh_api; import json; print(json.dumps(gh_api('o/r', '', paginate=False)))")
            self.assertEqual(r.stdout.strip(), '{"full_name": "o/r"}')

    def test_http_error_carries_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = fake_gh_env(tmp, {"/repos/o/r/dependabot/alerts": {"error": "HTTP 403: Resource not accessible by integration"}})
            r = run_gh_api(env, "from _gh import gh_api, GhApiError\ntry:\n    gh_api('o/r', '/dependabot/alerts')\nexcept GhApiError as e:\n    print(e.status)")
            self.assertEqual(r.stdout.strip(), "403")

    def test_slurp_flag_is_sent(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = fake_gh_env(tmp, {"/repos/o/r/pulls": [[]]}, log=True)
            run_gh_api(env, "from _gh import gh_api; gh_api('o/r', '/pulls')")
            from _fake_gh import calls
            self.assertIn("--slurp", calls(env)[0])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run to verify they fail**

Run: `scripts/run_metrics_tests.sh collectors`
Expected: `test_multi_page_array_is_flattened` and `test_slurp_flag_is_sent` FAIL (today's
`gh_api` never sends `--slurp`, and the fake prints concatenated pages, which `json.loads`
rejects with `Extra data`).

- [ ] **Step 4: Fix `gh_api`**

Replace the `gh_api` function in `scripts/metrics/_gh.py` with:

```python
def gh_api(
    repo: str,
    path: str,
    params: dict[str, str] | None = None,
    paginate: bool = True,
    list_key: str | None = None,
):
    """Call `gh api /repos/<repo><path>` and return parsed JSON.

    With ``paginate`` (the default) every page is fetched and the result is
    the flattened list of records: ``gh api --paginate --slurp`` returns one
    JSON array of pages, and each page is either an array (concatenated) or
    an object carrying the records under ``list_key`` (``workflow_runs``,
    ``workflows``...), whose arrays are concatenated. Without ``--slurp`` gh
    prints the pages back to back, which is one JSON document only while
    there is one page — the bug that stopped every collection after
    2026-09-01.

    Raises GhApiError with ``.status`` set on HTTP failure so callers can
    distinguish 403 (no access) from 404 (feature disabled).
    """
    full_path = f"/repos/{repo}{path}" if not path.startswith("http") else path
    if params:
        full_path += "?" + urllib.parse.urlencode(params)
    args = ["api", full_path, "--method", "GET"]
    if paginate:
        args += ["--paginate", "--slurp"]
    stdout = run_gh(*args)
    if not stdout.strip():
        return [] if paginate else {}
    doc = json.loads(stdout)
    if not paginate:
        return doc
    records: list = []
    for page in doc:
        if isinstance(page, list):
            records.extend(page)
        elif isinstance(page, dict):
            if list_key is None:
                raise GhApiError(f"paginated object page for {path} needs list_key (keys: {sorted(page)})")
            records.extend(page.get(list_key) or [])
    return records
```

Update the module docstring's third paragraph to say callers map 403/404 to explicit
`status` values rather than `null` (the event-dump collector in Task 3 does that).

- [ ] **Step 5: Run to verify they pass**

Run: `scripts/run_metrics_tests.sh collectors`
Expected: `Ran 5 tests`, `OK`.

- [ ] **Step 6: Commit**

```bash
git add scripts/metrics/_gh.py scripts/metrics/tests/_fake_gh.py scripts/metrics/tests/test_gh.py
```
Commit message: `fix(metrics): paginate gh api with --slurp and flatten pages`.

### Task 3: Event-dump collector with history sidecars

**Files:**
- Create: `scripts/metrics/collect_events.py`
- Create: `scripts/metrics/tests/test_collect_events.py`

**Interfaces:**
- Produces CLI: `collect_events.py --repo <owner/repo> --out-dir <dir> [--kinds a,b] [--runs-since-days 180]`.
  Writes `<dir>/events/<kind>.json` and appends to `<dir>/events/history/<kind>.jsonl`.
  Exit 0 when every kind wrote a file (including `not_permitted`/`disabled` envelopes);
  exit 1 if any kind raised.
- Produces the envelope shape consumed by `metrics/build/load.py` (Part B):
  `{"kind", "fetched_at", "repo", "status": "ok"|"not_permitted"|"disabled"|"error", "detail": str|null, "records": [...]}`.
  Every record has an `id` field (int or str) that is stable across fetches.
- Sidecar line shape: `{"id", "seen_at", "record"}`; on load the last line per id wins.

- [ ] **Step 1: Write the failing tests**

`scripts/metrics/tests/test_collect_events.py`:

```python
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from _fake_gh import calls, fake_gh_env

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "collect_events.py"

ALERT = {"number": 7, "state": "open", "created_at": "2026-08-23T16:00:55Z", "fixed_at": None,
         "dismissed_at": None, "dismissed_reason": None,
         "rule": {"id": "py/full-ssrf", "security_severity_level": "critical"},
         "tool": {"name": "CodeQL"}, "most_recent_instance": {"location": {"path": "apps/x.py"}}}
PR = {"number": 5, "title": "G1", "created_at": "2026-08-24T10:00:00Z", "merged_at": "2026-08-25T10:00:00Z",
      "closed_at": "2026-08-25T10:00:00Z", "user": {"login": "d", "type": "User"}, "head": {"ref": "e2e/g1"}}
PR_DETAIL = dict(PR, additions=100, deletions=5, changed_files=3)
PR_FILES = [{"filename": "apps/x.py"}, {"filename": "e2e/a.spec.ts"}, {"filename": "docs/b.md"}]
RUN = {"id": 11, "name": "E2E Tests", "event": "push", "status": "completed", "conclusion": "success",
       "created_at": "2026-08-29T08:00:00Z", "updated_at": "2026-08-29T08:05:00Z",
       "run_started_at": "2026-08-29T08:00:10Z", "head_sha": "abc"}
ISSUE = {"number": 9, "title": "bug", "state": "open", "created_at": "2026-08-27T00:00:00Z", "closed_at": None,
         "updated_at": "2026-08-28T00:00:00Z", "labels": [{"name": "needs-triage"}]}
ISSUE_PR = dict(ISSUE, number=10, pull_request={"url": "x"})
TIMELINE = [{"event": "labeled", "label": {"name": "needs-triage"}, "created_at": "2026-08-27T00:00:01Z"},
            {"event": "unlabeled", "label": {"name": "needs-triage"}, "created_at": "2026-08-28T00:00:00Z"}]


def responses():
    return {
        "/repos/o/r/code-scanning/alerts": {"pages": [[ALERT]]},
        "/repos/o/r/pulls/5/files": [PR_FILES],
        "/repos/o/r/pulls/5": PR_DETAIL,
        "/repos/o/r/pulls": {"pages": [[PR]]},
        "/repos/o/r/actions/runs": {"pages": [{"total_count": 1, "workflow_runs": [RUN]}]},
        "/repos/o/r/issues/9/timeline": {"pages": [TIMELINE]},
        "/repos/o/r/issues": {"pages": [[ISSUE, ISSUE_PR]]},
        "/repos/o/r/dependabot/alerts": {"error": "HTTP 403: Resource not accessible by integration"},
        "/repos/o/r/secret-scanning/alerts": {"error": "HTTP 404: Not Found"},
    }


def run(env, out, kinds):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", "o/r", "--out-dir", str(out), "--kinds", kinds, "--no-scorecard"],
        env=env, capture_output=True, text=True, check=False,
    )


def read(out, kind):
    return json.loads((Path(out) / "events" / f"{kind}.json").read_text())


class CollectEventsTests(unittest.TestCase):
    def test_codeql_dump_keeps_only_declared_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = fake_gh_env(tmp, responses())
            out = Path(tmp) / "data"
            r = run(env, out, "codeql_alerts")
            self.assertEqual(r.returncode, 0, r.stderr)
            dump = read(out, "codeql_alerts")
            self.assertEqual(dump["status"], "ok")
            rec = dump["records"][0]
            self.assertEqual(rec["id"], 7)
            self.assertEqual(rec["severity"], "critical")
            self.assertEqual(rec["rule_id"], "py/full-ssrf")
            self.assertEqual(rec["path"], "apps/x.py")
            self.assertNotIn("most_recent_instance", rec)

    def test_pull_request_dump_fetches_detail_and_files_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = fake_gh_env(tmp, responses(), log=True)
            out = Path(tmp) / "data"
            self.assertEqual(run(env, out, "pull_requests").returncode, 0)
            rec = read(out, "pull_requests")["records"][0]
            self.assertEqual(rec["additions"], 100)
            self.assertEqual(rec["files"], ["apps/x.py", "e2e/a.spec.ts", "docs/b.md"])
            self.assertEqual(rec["author"], "d")
            self.assertEqual(rec["author_type"], "User")
            self.assertEqual(rec["head_ref"], "e2e/g1")
            first = len([c for c in calls(env) if "/pulls/5" in " ".join(c)])
            self.assertEqual(run(env, out, "pull_requests").returncode, 0)
            second = len([c for c in calls(env) if "/pulls/5" in " ".join(c)])
            self.assertEqual(second, first, "merged PR detail must come from the sidecar on the second run")

    def test_workflow_runs_use_list_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = fake_gh_env(tmp, responses())
            out = Path(tmp) / "data"
            self.assertEqual(run(env, out, "workflow_runs").returncode, 0)
            rec = read(out, "workflow_runs")["records"][0]
            self.assertEqual(rec["id"], 11)
            self.assertEqual(rec["workflow"], "E2E Tests")

    def test_issues_skip_pull_requests_and_carry_label_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = fake_gh_env(tmp, responses())
            out = Path(tmp) / "data"
            self.assertEqual(run(env, out, "issues").returncode, 0)
            recs = read(out, "issues")["records"]
            self.assertEqual([r["id"] for r in recs], [9])
            self.assertEqual(recs[0]["labels"], ["needs-triage"])
            self.assertEqual(recs[0]["label_events"][1], {"event": "unlabeled", "label": "needs-triage", "at": "2026-08-28T00:00:00Z"})

    def test_forbidden_and_disabled_are_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = fake_gh_env(tmp, responses())
            out = Path(tmp) / "data"
            self.assertEqual(run(env, out, "dependabot_alerts,secret_scanning").returncode, 0)
            self.assertEqual(read(out, "dependabot_alerts")["status"], "not_permitted")
            self.assertEqual(read(out, "secret_scanning")["status"], "disabled")
            self.assertEqual(read(out, "dependabot_alerts")["records"], [])

    def test_history_sidecar_keeps_records_that_leave_the_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "data"
            env = fake_gh_env(tmp, responses())
            self.assertEqual(run(env, out, "workflow_runs").returncode, 0)
            gone = responses(); gone["/repos/o/r/actions/runs"] = {"pages": [{"total_count": 0, "workflow_runs": []}]}
            env = fake_gh_env(tmp, gone)
            self.assertEqual(run(env, out, "workflow_runs").returncode, 0)
            self.assertEqual(read(out, "workflow_runs")["records"], [])
            lines = (out / "events" / "history" / "workflow_runs.jsonl").read_text().splitlines()
            self.assertEqual(len(lines), 1)
            self.assertEqual(json.loads(lines[0])["record"]["id"], 11)

    def test_unchanged_record_is_not_appended_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "data"
            env = fake_gh_env(tmp, responses())
            run(env, out, "codeql_alerts"); run(env, out, "codeql_alerts")
            lines = (out / "events" / "history" / "codeql_alerts.jsonl").read_text().splitlines()
            self.assertEqual(len(lines), 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify they fail**

Run: `scripts/run_metrics_tests.sh collectors`
Expected: every `CollectEventsTests` test errors (script missing).

- [ ] **Step 3: Write the collector**

`scripts/metrics/collect_events.py`:

```python
#!/usr/bin/env python3
"""Event dumps: the full current record set of each GitHub-backed source.

Unlike the snapshot collectors, nothing here is a metric. Each kind is written
whole to events/<kind>.json on every run (overwritten), projected down to the
fields the build step needs, with a stable ``id`` per record. Because every
record carries its own timestamps, any "as of date D" number is derived at
build time (metrics/build/derive.py) — which is why these are not appended as
rows and why history reaches back to the data's own start rather than to the
first collection.

Records can fall off an API's retention window (GitHub keeps workflow runs
for 90 days), so each kind also keeps a history sidecar,
events/history/<kind>.jsonl: a record is appended there the first time it is
seen and again whenever its projected form changes. The build step reads the
union, current record winning.

Permission gaps are recorded, never hidden: a 403 writes status
"not_permitted", a 404 writes "disabled", any other failure "error" with the
message in ``detail`` and an empty record list. The exit code is 1 only if a
kind raised something other than GhApiError.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import urllib.request
from pathlib import Path

from _gh import GhApiError, gh_api

SCORECARD_URL = "https://api.securityscorecards.dev/projects/github.com/{repo}"


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------- sidecar ---

class Sidecar:
    """events/history/<kind>.jsonl — last line per id wins."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.records: dict[str, dict] = {}
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    self.records[str(row["id"])] = row["record"]

    def get(self, record_id) -> dict | None:
        return self.records.get(str(record_id))

    def absorb(self, records: list[dict], seen_at: str) -> int:
        """Append every record that is new or whose projection changed."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        appended = 0
        with self.path.open("a", encoding="utf-8") as f:
            for rec in records:
                key = str(rec["id"])
                if self.records.get(key) == rec:
                    continue
                self.records[key] = rec
                f.write(json.dumps({"id": rec["id"], "seen_at": seen_at, "record": rec}, sort_keys=True) + "\n")
                appended += 1
        return appended


# ---------------------------------------------------------- projections ---

def project_codeql(alert: dict) -> dict:
    rule = alert.get("rule") or {}
    loc = ((alert.get("most_recent_instance") or {}).get("location") or {})
    return {
        "id": alert["number"],
        "state": alert.get("state"),
        "created_at": alert.get("created_at"),
        "fixed_at": alert.get("fixed_at"),
        "dismissed_at": alert.get("dismissed_at"),
        "dismissed_reason": alert.get("dismissed_reason"),
        "rule_id": rule.get("id"),
        "severity": rule.get("security_severity_level"),
        "tool": (alert.get("tool") or {}).get("name"),
        "path": loc.get("path"),
    }


def project_pr(pr: dict, detail: dict | None, files: list[dict] | None) -> dict:
    user = pr.get("user") or {}
    return {
        "id": pr["number"],
        "title": pr.get("title"),
        "created_at": pr.get("created_at"),
        "merged_at": pr.get("merged_at"),
        "closed_at": pr.get("closed_at"),
        "author": user.get("login"),
        "author_type": user.get("type"),
        "head_ref": (pr.get("head") or {}).get("ref"),
        "additions": (detail or {}).get("additions"),
        "deletions": (detail or {}).get("deletions"),
        "changed_files": (detail or {}).get("changed_files"),
        "files": [f.get("filename") for f in (files or [])],
    }


def project_run(run: dict) -> dict:
    return {
        "id": run["id"],
        "workflow": run.get("name"),
        "event": run.get("event"),
        "status": run.get("status"),
        "conclusion": run.get("conclusion"),
        "created_at": run.get("created_at"),
        "updated_at": run.get("updated_at"),
        "run_started_at": run.get("run_started_at"),
        "head_sha": run.get("head_sha"),
    }


def project_issue(issue: dict, timeline: list[dict]) -> dict:
    events = [
        {"event": e["event"], "label": (e.get("label") or {}).get("name"), "at": e.get("created_at")}
        for e in timeline
        if e.get("event") in ("labeled", "unlabeled") and (e.get("label") or {}).get("name")
    ]
    return {
        "id": issue["number"],
        "title": issue.get("title"),
        "state": issue.get("state"),
        "created_at": issue.get("created_at"),
        "closed_at": issue.get("closed_at"),
        "updated_at": issue.get("updated_at"),
        "labels": [l.get("name") for l in (issue.get("labels") or [])],
        "label_events": events,
    }


# -------------------------------------------------------------- fetchers ---
# Each returns the projected record list. They may consult the sidecar to
# skip per-record detail calls for records that cannot change any more.

def fetch_codeql(repo: str, sidecar: Sidecar, opts) -> list[dict]:
    return [project_codeql(a) for a in gh_api(repo, "/code-scanning/alerts", {"state": "all", "per_page": "100"})]


def fetch_dependabot(repo: str, sidecar: Sidecar, opts) -> list[dict]:
    out = []
    for a in gh_api(repo, "/dependabot/alerts", {"state": "all", "per_page": "100"}):
        adv = a.get("security_advisory") or {}
        out.append({
            "id": a["number"], "state": a.get("state"), "created_at": a.get("created_at"),
            "fixed_at": a.get("fixed_at"), "dismissed_at": a.get("dismissed_at"),
            "severity": adv.get("severity"), "package": ((a.get("dependency") or {}).get("package") or {}).get("name"),
        })
    return out


def fetch_secret_scanning(repo: str, sidecar: Sidecar, opts) -> list[dict]:
    return [
        {"id": a["number"], "state": a.get("state"), "created_at": a.get("created_at"),
         "resolved_at": a.get("resolved_at"), "secret_type": a.get("secret_type")}
        for a in gh_api(repo, "/secret-scanning/alerts", {"state": "all", "per_page": "100"})
    ]


def fetch_pull_requests(repo: str, sidecar: Sidecar, opts) -> list[dict]:
    out = []
    for pr in gh_api(repo, "/pulls", {"state": "all", "per_page": "100"}):
        prior = sidecar.get(pr["number"])
        # A merged or closed PR's line counts and file list are final: reuse them.
        if prior and prior.get("closed_at") and prior.get("additions") is not None:
            out.append(project_pr(pr, prior, [{"filename": f} for f in prior.get("files", [])]))
            continue
        detail = gh_api(repo, f"/pulls/{pr['number']}", paginate=False)
        files = gh_api(repo, f"/pulls/{pr['number']}/files", {"per_page": "100"})
        out.append(project_pr(pr, detail, files))
    return out


def fetch_workflow_runs(repo: str, sidecar: Sidecar, opts) -> list[dict]:
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=opts.runs_since_days)).strftime("%Y-%m-%d")
    runs = gh_api(repo, "/actions/runs", {"created": f">={since}", "per_page": "100"}, list_key="workflow_runs")
    return [project_run(r) for r in runs]


def fetch_issues(repo: str, sidecar: Sidecar, opts) -> list[dict]:
    out = []
    for issue in gh_api(repo, "/issues", {"state": "all", "per_page": "100"}):
        if "pull_request" in issue:
            continue  # the issues endpoint lists PRs too
        prior = sidecar.get(issue["number"])
        if prior and prior.get("updated_at") == issue.get("updated_at"):
            out.append(dict(prior, labels=[l.get("name") for l in (issue.get("labels") or [])]))
            continue
        timeline = gh_api(repo, f"/issues/{issue['number']}/timeline", {"per_page": "100"})
        out.append(project_issue(issue, timeline))
    return out


def fetch_scorecard(repo: str, sidecar: Sidecar, opts) -> list[dict]:
    with urllib.request.urlopen(SCORECARD_URL.format(repo=repo), timeout=30) as resp:  # noqa: S310 - fixed https host
        doc = json.load(resp)
    return [{
        "id": doc.get("date"),
        "date": doc.get("date"),
        "score": doc.get("score"),
        "commit": (doc.get("repo") or {}).get("commit"),
        "checks": {c["name"]: c.get("score") for c in doc.get("checks", [])},
    }]


KINDS = {
    "codeql_alerts": fetch_codeql,
    "dependabot_alerts": fetch_dependabot,
    "secret_scanning": fetch_secret_scanning,
    "pull_requests": fetch_pull_requests,
    "workflow_runs": fetch_workflow_runs,
    "issues": fetch_issues,
    "scorecard": fetch_scorecard,
}


def collect_kind(kind: str, repo: str, out_dir: Path, opts) -> dict:
    events_dir = out_dir / "events"
    events_dir.mkdir(parents=True, exist_ok=True)
    sidecar = Sidecar(events_dir / "history" / f"{kind}.jsonl")
    fetched_at = now_iso()
    envelope = {"kind": kind, "fetched_at": fetched_at, "repo": repo, "status": "ok", "detail": None, "records": []}
    try:
        envelope["records"] = KINDS[kind](repo, sidecar, opts)
    except GhApiError as exc:
        envelope["status"] = {403: "not_permitted", 404: "disabled"}.get(exc.status, "error")
        envelope["detail"] = str(exc).splitlines()[0][:200]
    except Exception as exc:  # scorecard network errors and the like: recorded, not fatal
        envelope["status"] = "error"
        envelope["detail"] = f"{type(exc).__name__}: {exc}"[:200]
    if envelope["status"] == "ok":
        appended = sidecar.absorb(envelope["records"], fetched_at)
        print(f"{kind}: {len(envelope['records'])} records, {appended} new/changed in history", file=sys.stderr)
    else:
        print(f"{kind}: {envelope['status']} ({envelope['detail']})", file=sys.stderr)
    (events_dir / f"{kind}.json").write_text(json.dumps(envelope, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return envelope


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="D10Scot/Dispatcharr")
    parser.add_argument("--out-dir", type=Path, required=True, help="metrics-data checkout")
    parser.add_argument("--kinds", default=",".join(KINDS), help="comma-separated subset of: " + ", ".join(KINDS))
    parser.add_argument("--runs-since-days", type=int, default=180)
    parser.add_argument("--no-scorecard", action="store_true", help="skip the external Scorecard fetch (tests)")
    opts = parser.parse_args()

    kinds = [k.strip() for k in opts.kinds.split(",") if k.strip()]
    unknown = [k for k in kinds if k not in KINDS]
    if unknown:
        print(f"unknown kinds: {unknown}", file=sys.stderr)
        return 2
    if opts.no_scorecard:
        kinds = [k for k in kinds if k != "scorecard"]
    failures = 0
    for kind in kinds:
        try:
            collect_kind(kind, opts.repo, opts.out_dir, opts)
        except Exception as exc:  # a bug in this script, not an API outcome
            print(f"{kind}: collector crashed: {exc}", file=sys.stderr)
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run to verify they pass**

Run: `scripts/run_metrics_tests.sh collectors`
Expected: all `CollectEventsTests` pass. If `test_pull_request_dump_fetches_detail_and_files_once`
fails on the second-run assertion, the sidecar's `closed_at` check is the place to look: the
fixture PR has `closed_at` set.

- [ ] **Step 5: Run the real thing once, read-only, against the fork**

Run: `python3 scripts/metrics/collect_events.py --repo D10Scot/Dispatcharr --out-dir /tmp/events-smoke && ls -la /tmp/events-smoke/events && python3 -c "import json; d=json.load(open('/tmp/events-smoke/events/codeql_alerts.json')); print(d['status'], len(d['records']))"`
Expected: seven files, `codeql_alerts` `ok` with ~159 records, `dependabot_alerts` status
`not_permitted` only if your `gh` token lacks the scope (a PAT returns `ok`), `secret_scanning`
`disabled`.

- [ ] **Step 6: Commit**

```bash
git add scripts/metrics/collect_events.py scripts/metrics/tests/test_collect_events.py
```
Commit message: `feat(metrics): event dumps with history sidecars for CodeQL, PRs, runs, issues, Scorecard`.

### Task 4: `collect_tests.py` stops counting its own tests; `collect_all.py` runs every family independently

**Files:**
- Modify: `scripts/metrics/collect_tests.py`
- Modify: `scripts/metrics/collect_all.py`
- Create: `scripts/metrics/tests/test_collect_tests.py`
- Create: `scripts/metrics/tests/test_collect_all.py`

**Interfaces:**
- `collect_tests.py` output gains `coverage_md_rows: {"done": n, "known_bug": n, "todo": n}`
  parsed from `e2e/COVERAGE.md` table rows (`| ... | done |`), and never counts tests under
  `metrics/`, `scripts/`, `dashboard/`.
- `collect_all.py` gains `--only <family,...>`; a family whose script is `None` in `FAMILIES`
  (`coverage`) is written only when `--extra-metrics coverage=<path>` supplies its metrics;
  every family runs even if an earlier one failed; exit 1 at the end if any failed; the
  event dumps are **not** run here (the workflow calls `collect_events.py` separately).

- [ ] **Step 1: Write the failing tests**

`scripts/metrics/tests/test_collect_tests.py`:

```python
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "collect_tests.py"


def make_repo(tmp: Path) -> None:
    (tmp / "apps" / "x" / "tests").mkdir(parents=True)
    (tmp / "apps" / "x" / "tests" / "test_a.py").write_text("def test_one():\n    pass\n\ndef test_two():\n    pass\n")
    (tmp / "metrics" / "build" / "tests").mkdir(parents=True)
    (tmp / "metrics" / "build" / "tests" / "test_b.py").write_text("def test_not_counted():\n    pass\n")
    (tmp / "scripts" / "metrics" / "tests").mkdir(parents=True)
    (tmp / "scripts" / "metrics" / "tests" / "test_c.py").write_text("def test_not_counted_either():\n    pass\n")
    (tmp / "e2e").mkdir()
    (tmp / "e2e" / "COVERAGE.md").write_text(
        "| Area | Flow | Goal | Status |\n|---|---|---|---|\n"
        "| A | f1 | G1 | done |\n| A | f2 | G1 | known-bug |\n| B | f3 | G2 | todo |\n| B | f4 | G2 | done |\n"
    )


class CollectTestsTests(unittest.TestCase):
    def test_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_repo(Path(tmp))
            r = subprocess.run([sys.executable, str(SCRIPT), "--repo-root", tmp], capture_output=True, text=True, check=True)
            m = json.loads(r.stdout)
            self.assertEqual(m["backend_test_count"], 2)
            self.assertEqual(m["coverage_md_rows"], {"done": 2, "known_bug": 1, "todo": 1})

    def test_missing_coverage_md_is_zero_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run([sys.executable, str(SCRIPT), "--repo-root", tmp], capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(r.stdout)["coverage_md_rows"], {"done": 0, "known_bug": 0, "todo": 0})
```

`scripts/metrics/tests/test_collect_all.py`:

```python
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
COLLECT_ALL = SCRIPTS / "collect_all.py"


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def make_git_repo(tmp: Path) -> Path:
    repo = tmp / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init")
    return repo


class CollectAllTests(unittest.TestCase):
    def test_external_family_written_only_from_extra_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_git_repo(Path(tmp))
            extra = Path(tmp) / "cov.json"
            extra.write_text(json.dumps({"backend_line_pct": 45.6}))
            out = Path(tmp) / "out"
            r = subprocess.run([sys.executable, str(COLLECT_ALL), "--repo-root", str(repo), "--out-dir", str(out),
                                "--only", "coverage", "--extra-metrics", f"coverage={extra}"],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            row = json.loads((out / "coverage.jsonl").read_text().splitlines()[0])
            self.assertEqual(row["family"], "coverage")
            self.assertEqual(row["metrics"]["backend_line_pct"], 45.6)

    def test_external_family_without_extra_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_git_repo(Path(tmp))
            out = Path(tmp) / "out"
            r = subprocess.run([sys.executable, str(COLLECT_ALL), "--repo-root", str(repo), "--out-dir", str(out), "--only", "coverage"],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertFalse((out / "coverage.jsonl").exists())

    def test_one_failing_family_does_not_stop_the_others(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_git_repo(Path(tmp))
            out = Path(tmp) / "out"
            # A repo root that is a git repo but has no apps/ makes every checkout
            # collector emit zeros rather than fail, so force a failure by pointing
            # one family's script at a missing file via the override env used only
            # by this test.
            env = dict(__import__("os").environ, METRICS_COLLECTOR_OVERRIDE="architecture=/nonexistent.py")
            r = subprocess.run([sys.executable, str(COLLECT_ALL), "--repo-root", str(repo), "--out-dir", str(out),
                                "--only", "code_health,architecture,tests"], capture_output=True, text=True, env=env)
            self.assertEqual(r.returncode, 1)
            self.assertTrue((out / "code_health.jsonl").exists())
            self.assertTrue((out / "tests.jsonl").exists())
            self.assertFalse((out / "architecture.jsonl").exists())
            self.assertIn("architecture", r.stderr)
```

- [ ] **Step 2: Run to verify they fail**

Run: `scripts/run_metrics_tests.sh collectors`
Expected: `test_counts` fails on `backend_test_count` (3, the two decoys are counted) and on
the missing `coverage_md_rows`; the three `CollectAllTests` fail on unknown `--only`.

- [ ] **Step 3: Update `collect_tests.py`**

In `main()`, change the skip line to:

```python
        if rel.parts[0] in {"e2e", "e2e-upstream", "frontend", "metrics", "scripts", "dashboard"} or not is_test_path(rel):
            continue
```

Add before `emit(`:

```python
    coverage_md_rows = count_coverage_md_rows(root / "e2e" / "COVERAGE.md")
```

and the key `"coverage_md_rows": coverage_md_rows,` in the emitted dict. Add the function:

```python
COVERAGE_ROW_RE = re.compile(r"^\|.*\|\s*(done|known-bug|todo)\s*\|\s*$", re.M)


def count_coverage_md_rows(path: Path) -> dict[str, int]:
    """Status column of e2e/COVERAGE.md's table rows (the shared e2e worklist)."""
    counts = {"done": 0, "known_bug": 0, "todo": 0}
    if not path.is_file():
        return counts
    for status in COVERAGE_ROW_RE.findall(path.read_text(encoding="utf-8", errors="replace")):
        counts[status.replace("-", "_")] += 1
    return counts
```

Update the module docstring: add a bullet for `coverage_md_rows` and note the three excluded
top-level directories ("the metrics stack's own tests are not product tests").

- [ ] **Step 4: Update `collect_all.py`**

Replace `FAMILIES` and `API_FAMILIES`:

```python
# family -> collector script, or None for a family whose metrics arrive only
# via --extra-metrics (coverage: produced by the workflow's coverage job).
FAMILIES: dict[str, str | None] = {
    "code_health": "collect_code_health.py",
    "architecture": "collect_architecture.py",
    "tests": "collect_tests.py",
    "coverage": None,
}
```

Add the `--only` argument:

```python
    parser.add_argument(
        "--only",
        default="",
        help="Comma-separated family names to run (default: all in FAMILIES).",
    )
```

Replace the per-family loop with:

```python
    only = {f.strip() for f in args.only.split(",") if f.strip()}
    overrides = dict(
        item.split("=", 1) for item in os.environ.get("METRICS_COLLECTOR_OVERRIDE", "").split(",") if "=" in item
    )
    failures: list[str] = []
    for family, script in FAMILIES.items():
        if only and family not in only:
            continue
        if family in skip:
            print(f"skip {family}: excluded via --skip-families", file=sys.stderr)
            continue
        out_path = out_dir / f"{family}.jsonl"
        if sha in existing_keys(out_path):
            print(f"skip {family}: row for {sha[:12]} already present", file=sys.stderr)
            continue
        try:
            if script is None:
                if family not in extra_metrics:
                    print(f"skip {family}: external family, no --extra-metrics given", file=sys.stderr)
                    continue
                metrics = {}
            else:
                script_path = Path(overrides.get(family, str(scripts_dir / script)))
                result = subprocess.run(
                    [sys.executable, str(script_path), "--repo-root", str(repo_root)],
                    check=True, capture_output=True, text=True,
                )
                if result.stderr:
                    sys.stderr.write(result.stderr)
                metrics = json.loads(result.stdout)
        except (subprocess.CalledProcessError, OSError, json.JSONDecodeError) as exc:
            print(f"FAILED {family}: {exc}", file=sys.stderr)
            failures.append(family)
            continue
        if family in extra_metrics:
            metrics.update(extra_metrics[family])
        row = {"timestamp": timestamp, "commit_sha": sha, "family": family, "metrics": metrics}
        with out_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, sort_keys=True) + "\n")
        print(f"wrote {family} row for {sha[:12]}", file=sys.stderr)

    if failures:
        print(f"{len(failures)} famil{'y' if len(failures) == 1 else 'ies'} failed: {', '.join(failures)}", file=sys.stderr)
        return 1
    return 0
```

Add `import os` at the top, delete the `--repo` argument and `API_FAMILIES` (the API
families are gone; `backfill.py`'s `--skip-families security,delivery,agentic` becomes a
no-op and is removed from `backfill.py` in the same edit). Rewrite the module docstring's
"Two kinds of families" paragraph:

```
Families are checkout-scanning (stdlib AST/grep over --repo-root, safe in a
historical worktree) or external (coverage: no script, metrics arrive via
--extra-metrics from the workflow's coverage job). GitHub-backed data is not a
family any more — see collect_events.py.
```

- [ ] **Step 5: Run to verify they pass**

Run: `scripts/run_metrics_tests.sh collectors`
Expected: `OK`.

- [ ] **Step 6: Sanity-run the three snapshot collectors on the real checkout**

Run: `python3 scripts/metrics/collect_all.py --repo-root . --out-dir /tmp/snap-smoke && cat /tmp/snap-smoke/tests.jsonl`
Expected: three files; `backend_test_count` equals what `collect_tests.py` printed before
this task (1,860 at the time of writing — the decoy exclusion changes nothing yet because
`scripts/metrics/tests` holds only this task's tests... which it now excludes; the number must
**not** include them).

- [ ] **Step 7: Commit**

```bash
git add scripts/metrics/collect_tests.py scripts/metrics/collect_all.py scripts/metrics/backfill.py scripts/metrics/tests/test_collect_tests.py scripts/metrics/tests/test_collect_all.py
```
Commit message: `fix(metrics): run every family independently; count COVERAGE.md rows; never count the metrics stack's own tests`.

### Task 5: Backend and frontend coverage, summarised into one row

**Files:**
- Modify: `pyproject.toml` (add `coverage`), `uv.lock` (via `uv lock`)
- Create: `.coveragerc`
- Modify: `scripts/ci_bootstrap_backend.sh` (last line)
- Create: `scripts/ci_coverage_backend.sh`
- Create: `scripts/metrics/coverage_summary.py`
- Create: `scripts/metrics/tests/test_coverage_summary.py`

**Interfaces:**
- `ci_bootstrap_backend.sh` honours `CI_BACKEND_RUNNER` (a command string); default stays
  `python manage.py test --keepdb "$@"`.
- `ci_coverage_backend.sh` writes `/tmp/dispatcharr-coverage/backend-coverage.json`
  (`coverage json` output) and `/tmp/dispatcharr-coverage/backend-status.json`
  (`{"labels": [...], "failed_labels": [...]}`); exits 0 unless `coverage combine`/`json` fail.
- `coverage_summary.py --backend <coverage.json> --backend-status <status.json> --frontend <coverage-summary.json> --out <row.json>`
  writes the `coverage` family's metrics dict:
  `{"backend_line_pct", "backend_by_app": {app: pct}, "backend_status", "backend_failed_labels", "frontend_line_pct", "frontend_status"}`.
  A missing input file yields `null` pct and status `"failed"` for that side.

- [ ] **Step 1: Add `coverage` to the project dependencies**

Run: `uv add "coverage>=7.10"` then `uv lock --check`.
Expected: `pyproject.toml` gains the line under `dependencies` (next to `hypothesis`, with the
same comment rationale: no dev group yet), `uv.lock` updated. The base image installs from
this lockfile, so the coverage job's `SYNC_PYTHON_DEPS=true` picks it up before the base
image is rebuilt.

- [ ] **Step 2: Write `.coveragerc`**

```ini
# Backend coverage for the daily metrics job (scripts/ci_coverage_backend.sh).
# Not used by backend-tests.yml — required checks stay uninstrumented.
[run]
source = apps, core, dispatcharr
omit =
    */migrations/*
    */tests/*
    dispatcharr/settings*.py
    dispatcharr/asgi.py
    dispatcharr/wsgi.py
    dispatcharr/test_runner.py
    dispatcharr/test_discovery.py
parallel = True
data_file = /tmp/dispatcharr-coverage/.coverage

[report]
skip_empty = True

[json]
output = /tmp/dispatcharr-coverage/backend-coverage.json
```

- [ ] **Step 3: Let the bootstrap script run a different command**

Replace the last line of `scripts/ci_bootstrap_backend.sh`:

```bash
# CI_BACKEND_RUNNER lets the metrics coverage job reuse this bootstrap (the
# internal Postgres/Redis, the role and database setup) with its own runner.
# The default is what backend-tests.yml has always run.
if [ -n "${CI_BACKEND_RUNNER:-}" ]; then
  exec bash -c "$CI_BACKEND_RUNNER"
fi
exec python manage.py test --keepdb "$@"
```

- [ ] **Step 4: Write the coverage runner**

`scripts/ci_coverage_backend.sh`:

```bash
#!/usr/bin/env bash
# Run every backend test label under coverage, one process per label, then
# combine. Invoked through scripts/ci_bootstrap_backend.sh (CI_BACKEND_RUNNER)
# so Postgres/Redis are already up and PATH has /dispatcharrpy/bin.
#
# Per-label processes on purpose: CI runs each label in its own container and
# the full in-process run has a history of order-dependent failures
# (CLAUDE.md, Testing). Redis is flushed between labels for the same reason
# the local hook does it. A failed label is recorded, not fatal: the row
# still carries the combined coverage plus the list of labels that failed.
set -uo pipefail
OUT=/tmp/dispatcharr-coverage
rm -rf "$OUT"; mkdir -p "$OUT"

LABELS_JSON="$(FULL_SUITE=1 python scripts/ci_backend_test_labels.py < /dev/null)"
mapfile -t LABELS < <(python -c 'import json,sys; print("\n".join(json.load(sys.stdin)))' <<< "$LABELS_JSON")
echo "coverage over ${#LABELS[@]} labels"

FAILED=()
for L in "${LABELS[@]}"; do
  redis-cli -p "${REDIS_PORT:-6379}" flushall >/dev/null 2>&1 || true
  if ! python -m coverage run --rcfile=.coveragerc -p manage.py test --keepdb "$L" -v1; then
    echo "::warning::label $L failed under coverage"
    FAILED+=("$L")
  fi
done

python -m coverage combine --rcfile=.coveragerc || exit 1
python -m coverage json --rcfile=.coveragerc -o "$OUT/backend-coverage.json" || exit 1
python -m coverage report --rcfile=.coveragerc | tail -3

python - "$OUT/backend-status.json" "${LABELS[@]}" -- "${FAILED[@]}" <<'PY'
import json, sys
argv = sys.argv[1:]
out = argv[0]
split = argv.index("--")
labels, failed = argv[1:split], argv[split + 1:]
json.dump({"labels": labels, "failed_labels": failed}, open(out, "w"))
PY
echo "failed labels: ${FAILED[*]:-none}"
exit 0
```

Run: `chmod +x scripts/ci_coverage_backend.sh`.

`_SHARED_PATH_PREFIXES` in `dispatcharr/test_discovery.py` lists `scripts/ci_bootstrap_backend.sh`,
so committing this task's bootstrap change makes the commit gate run the full backend suite
(~34 s in the container). That is correct: the bootstrap is what CI runs.

- [ ] **Step 5: Write the failing summary tests**

`scripts/metrics/tests/test_coverage_summary.py`:

```python
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "coverage_summary.py"

BACKEND = {
    "totals": {"percent_covered": 45.678},
    "files": {
        "apps/proxy/a.py": {"summary": {"covered_lines": 10, "num_statements": 40}},
        "apps/proxy/b.py": {"summary": {"covered_lines": 30, "num_statements": 40}},
        "core/c.py": {"summary": {"covered_lines": 9, "num_statements": 10}},
        "dispatcharr/d.py": {"summary": {"covered_lines": 0, "num_statements": 10}},
    },
}
STATUS = {"labels": ["apps.proxy.tests", "core.tests"], "failed_labels": ["core.tests"]}
FRONTEND = {"total": {"lines": {"pct": 71.94}}}


def run(args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)


class CoverageSummaryTests(unittest.TestCase):
    def test_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            (t / "b.json").write_text(json.dumps(BACKEND)); (t / "s.json").write_text(json.dumps(STATUS)); (t / "f.json").write_text(json.dumps(FRONTEND))
            r = run(["--backend", str(t / "b.json"), "--backend-status", str(t / "s.json"), "--frontend", str(t / "f.json"), "--out", str(t / "row.json")])
            self.assertEqual(r.returncode, 0, r.stderr)
            row = json.loads((t / "row.json").read_text())
            self.assertEqual(row["backend_line_pct"], 45.68)
            self.assertEqual(row["backend_by_app"], {"apps.proxy": 50.0, "core": 90.0, "dispatcharr": 0.0})
            self.assertEqual(row["backend_status"], "failed")
            self.assertEqual(row["backend_failed_labels"], ["core.tests"])
            self.assertEqual(row["frontend_line_pct"], 71.94)
            self.assertEqual(row["frontend_status"], "ok")

    def test_missing_inputs_are_failed_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            r = run(["--backend", str(t / "nope.json"), "--backend-status", str(t / "nope2.json"), "--frontend", str(t / "nope3.json"), "--out", str(t / "row.json")])
            self.assertEqual(r.returncode, 0, r.stderr)
            row = json.loads((t / "row.json").read_text())
            self.assertIsNone(row["backend_line_pct"]); self.assertEqual(row["backend_status"], "failed")
            self.assertIsNone(row["frontend_line_pct"]); self.assertEqual(row["frontend_status"], "failed")
```

Run: `scripts/run_metrics_tests.sh collectors` → both error (script missing).

- [ ] **Step 6: Write `coverage_summary.py`**

```python
#!/usr/bin/env python3
"""Fold `coverage json` output and vitest's coverage-summary.json into the
`coverage` family's metrics dict (one row per daily run, never backfilled).

Per-app backend percentages are computed from file summaries, grouped by the
same keys code_health uses for loc_per_app (``apps.<name>``, ``core``,
``dispatcharr``). A missing or unreadable input reports ``null`` and status
"failed" rather than crashing: a red day must be a visible point.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def load(path: Path | None):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path else None
    except (OSError, ValueError) as exc:
        print(f"warning: could not read {path}: {exc}", file=sys.stderr)
        return None


def app_key(rel: str) -> str:
    parts = rel.split("/")
    if parts[0] == "apps" and len(parts) > 1:
        return f"apps.{parts[1]}"
    return parts[0]


def backend_metrics(cov: dict | None, status: dict | None) -> dict:
    if not cov:
        return {"backend_line_pct": None, "backend_by_app": {}, "backend_status": "failed",
                "backend_failed_labels": (status or {}).get("failed_labels", [])}
    covered: dict[str, int] = {}
    total: dict[str, int] = {}
    for rel, info in cov.get("files", {}).items():
        s = info.get("summary", {})
        k = app_key(rel)
        covered[k] = covered.get(k, 0) + s.get("covered_lines", 0)
        total[k] = total.get(k, 0) + s.get("num_statements", 0)
    by_app = {k: round(100.0 * covered[k] / total[k], 2) for k in sorted(total) if total[k]}
    failed = (status or {}).get("failed_labels", [])
    return {
        "backend_line_pct": round(cov.get("totals", {}).get("percent_covered", 0.0), 2),
        "backend_by_app": by_app,
        "backend_status": "failed" if failed or status is None else "ok",
        "backend_failed_labels": failed,
    }


def frontend_metrics(summary: dict | None) -> dict:
    pct = (((summary or {}).get("total") or {}).get("lines") or {}).get("pct")
    return {"frontend_line_pct": round(pct, 2) if isinstance(pct, (int, float)) else None,
            "frontend_status": "ok" if isinstance(pct, (int, float)) else "failed"}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--backend", type=Path)
    p.add_argument("--backend-status", type=Path)
    p.add_argument("--frontend", type=Path)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    row = {}
    row.update(backend_metrics(load(a.backend), load(a.backend_status)))
    row.update(frontend_metrics(load(a.frontend)))
    a.out.write_text(json.dumps(row, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(row), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 7: Run to verify they pass**

Run: `scripts/run_metrics_tests.sh collectors` → `OK`.

- [ ] **Step 8: Commit** (the gate runs the full backend suite because the bootstrap changed)

```bash
git add pyproject.toml uv.lock .coveragerc scripts/ci_bootstrap_backend.sh scripts/ci_coverage_backend.sh scripts/metrics/coverage_summary.py scripts/metrics/tests/test_coverage_summary.py
```
Commit message: `ci(metrics): per-label backend coverage runner and a coverage row summariser`.

### Task 6: `metrics.yml` — daily cadence, event dumps, coverage job

**Files:**
- Modify: `.github/workflows/metrics.yml` (rewrite)

- [ ] **Step 1: Rewrite the workflow**

Keep the existing SHA pins for `actions/checkout` and `actions/setup-node` (already in the
file and zizmor-clean). Replace the file with:

```yaml
name: Metrics

# Raw engineering-metrics facts for the dashboard (docs/superpowers/specs/
# 2026-09-04-engineering-metrics-dashboard-design.md, §4):
#   * per-commit snapshot rows (scripts/metrics/collect_all.py) on every push
#     to main that touches a measured path, and daily;
#   * daily event dumps of GitHub state (scripts/metrics/collect_events.py);
#   * a daily coverage row from a real backend + frontend suite run.
# Everything lands on the orphan `metrics-data` branch. Nothing here derives
# a trend or a status — that is the Pages build step's job.

on:
  schedule:
    - cron: '0 6 * * *' # daily, 06:00 UTC; pages.yml follows at 06:15
  push:
    branches:
      - main
    paths:
      - 'apps/**'
      - 'core/**'
      - 'dispatcharr/**'
      - 'frontend/**'
      - 'e2e/**'
      - 'scripts/**'
      - '.github/workflows/metrics.yml'
  workflow_dispatch:
    inputs:
      backfill:
        description: >-
          Run the snapshot backfill over every first-parent commit since
          fd413f0c instead of a single collection at HEAD (idempotent).
        type: boolean
        default: false

permissions:
  contents: read

# Both jobs push to metrics-data; the group serialises runs and `needs:`
# serialises the two jobs inside a run.
concurrency:
  group: metrics-append
  cancel-in-progress: false

jobs:
  collect-and-append:
    runs-on: ubuntu-latest
    permissions:
      contents: write # push to the metrics-data branch
      security-events: read # code-scanning alerts (collect_events.py)
    steps:
      - name: Checkout
        uses: actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6.1.0
        with:
          persist-credentials: false
          fetch-depth: 0 # backfill walks first-parent history

      - name: Prepare metrics-data worktree
        run: |
          if git fetch origin metrics-data; then
            git worktree add -B metrics-data metrics-data-wt FETCH_HEAD
          else
            git worktree add --orphan -b metrics-data metrics-data-wt
          fi

      - name: Snapshot collectors
        env:
          BACKFILL: ${{ inputs.backfill && '1' || '' }}
        run: |
          if [ -n "$BACKFILL" ]; then
            python3 scripts/metrics/backfill.py --repo-root . --out-dir metrics-data-wt --ref "$GITHUB_SHA"
          else
            python3 scripts/metrics/collect_all.py --repo-root . --out-dir metrics-data-wt \
              --only code_health,architecture,tests
          fi

      - name: Event dumps
        # Daily and on dispatch only: a push already gets a snapshot row and
        # the dumps are the same facts whatever commit triggered the run.
        if: github.event_name != 'push'
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: python3 scripts/metrics/collect_events.py --repo "$GITHUB_REPOSITORY" --out-dir metrics-data-wt

      - name: Commit and push
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          cd metrics-data-wt
          git add -A
          if git diff --cached --quiet; then
            echo "No new rows; nothing to push."
            exit 0
          fi
          git -c user.name="github-actions[bot]" \
              -c user.email="41898282+github-actions[bot]@users.noreply.github.com" \
              commit -m "metrics: append rows for ${GITHUB_SHA}"
          git push \
            "https://x-access-token:${GITHUB_TOKEN}@github.com/${GITHUB_REPOSITORY}.git" \
            HEAD:metrics-data

  coverage:
    # Daily and on dispatch: a real run of both suites under coverage. Never
    # on push — required checks stay uninstrumented and merges do not wait.
    needs: collect-and-append
    if: github.event_name != 'push'
    runs-on: ubuntu-latest
    permissions:
      contents: write # push the coverage row to metrics-data
      packages: read # pull the base image
    container:
      # The fork's own base image (see backend-tests.yml for why a digest pin
      # cannot apply to a deliberately floating own-built tag). Hard-coded
      # rather than resolved by a plan job: this workflow is fork-specific by
      # construction (it names the metrics-data branch and the Pages site).
      image: ghcr.io/d10scot/dispatcharr:base # zizmor: ignore[unpinned-images]
      credentials:
        username: ${{ github.actor }}
        password: ${{ secrets.GITHUB_TOKEN }}
      options: --entrypoint ""
    env:
      DISPATCHARR_ENV: aio
      DJANGO_SECRET_KEY: ci-test-secret-key
      POSTGRES_DB: dispatcharr
      POSTGRES_USER: dispatch
      POSTGRES_PASSWORD: secret
      DISPATCHARR_LOG_LEVEL: WARNING
      SYNC_PYTHON_DEPS: 'true' # picks up `coverage` before the base image is rebuilt
    steps:
      - name: Checkout
        uses: actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6.1.0
        with:
          persist-credentials: false

      - name: Backend suite under coverage
        env:
          GITHUB_WORKSPACE: ${{ github.workspace }}
          CI_BACKEND_RUNNER: bash scripts/ci_coverage_backend.sh
        run: bash scripts/ci_bootstrap_backend.sh

      - name: Setup Node.js
        uses: actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020 # v4.4.0
        with:
          node-version: '24'
          cache: 'npm'
          cache-dependency-path: './frontend/package-lock.json'

      - name: Frontend suite under coverage
        working-directory: frontend
        run: |
          npm ci
          npx vitest run --coverage --coverage.reporter=json-summary || echo "::warning::frontend suite failed under coverage"

      - name: Summarise
        run: |
          python3 scripts/metrics/coverage_summary.py \
            --backend /tmp/dispatcharr-coverage/backend-coverage.json \
            --backend-status /tmp/dispatcharr-coverage/backend-status.json \
            --frontend frontend/coverage/coverage-summary.json \
            --out /tmp/coverage-row.json

      - name: Append the coverage row and push
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          git config --global --add safe.directory "$GITHUB_WORKSPACE"
          git fetch origin metrics-data
          git worktree add -B metrics-data metrics-data-wt FETCH_HEAD
          python3 scripts/metrics/collect_all.py --repo-root . --out-dir metrics-data-wt \
            --only coverage --extra-metrics coverage=/tmp/coverage-row.json
          cd metrics-data-wt
          git add -A
          if git diff --cached --quiet; then echo "No coverage row; nothing to push."; exit 0; fi
          git -c user.name="github-actions[bot]" \
              -c user.email="41898282+github-actions[bot]@users.noreply.github.com" \
              commit -m "metrics: coverage row for ${GITHUB_SHA}"
          git push "https://x-access-token:${GITHUB_TOKEN}@github.com/${GITHUB_REPOSITORY}.git" HEAD:metrics-data
```

The hook lints on save. Expected: zero zizmor findings (the `unpinned-images` line carries
its ignore comment). If `actionlint` in `lint.yml` complains about `mapfile`/`python -`
constructs it does not — they are inside a script file, not a `run:` block.

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/metrics.yml
```
Commit message: `ci(metrics): daily cadence, event dumps, and a coverage job`.

### Task 7: Retire the API-snapshot collectors, rewrite the READMEs, amend the spec, open PR A

**Files:**
- Delete: `scripts/metrics/collect_security.py`, `collect_delivery.py`, `collect_agentic.py`
- Rewrite: `scripts/metrics/README.md`
- Modify: `docs/superpowers/specs/2026-09-04-engineering-metrics-dashboard-design.md` (§4.1 amendment 1)
- Modify (on the `metrics-data` branch, separate commit): `README.md`

- [ ] **Step 1: Delete the three collectors and check nothing imports them**

Run: `git rm scripts/metrics/collect_security.py scripts/metrics/collect_delivery.py scripts/metrics/collect_agentic.py && grep -rn 'collect_security\|collect_delivery\|collect_agentic' --include='*.py' --include='*.yml' --include='*.md' . | grep -v docs/superpowers`
Expected: no hits outside the spec/plan.

- [ ] **Step 2: Rewrite `scripts/metrics/README.md`**

```markdown
# Metrics collectors

Raw facts only. Every script here writes to the orphan `metrics-data` branch
via `.github/workflows/metrics.yml`; nothing here computes a trend, delta or
status — that is `metrics/build/` (the Pages build step). Field names are a
contract with `metrics/curated/catalogue.yml`: renaming one means updating
the catalogue in the same PR.

## Snapshot families (`collect_all.py`)

One JSONL row per `(commit_sha, family)`, idempotent append, backfillable per
first-parent commit with `backfill.py`:

- `code_health` — debt markers (bare/broad except, except-pass, function-local
  imports, os.environ reads, LOC per package).
- `architecture` — extraction-progress facts (cross-app import edges and
  cycles, apps/proxy ORM writes, reverse imports into proxy, the models.py
  boot-trap import count).
- `tests` — test counts as written (backend AST, frontend/e2e call sites,
  greybox subset, Hypothesis `@given`), plus `coverage_md_rows` from
  `e2e/COVERAGE.md`. Tests under `metrics/`, `scripts/`, `dashboard/` are
  the metrics stack's own and are never counted.
- `coverage` — external: written only by the workflow's daily coverage job
  through `--extra-metrics coverage=<row.json>` (`coverage_summary.py`).
  Never backfilled. `backend_status`/`frontend_status` are `failed` when a
  suite did not pass; the pct is still reported when it could be combined.

## Event dumps (`collect_events.py`)

`events/<kind>.json`, overwritten daily, plus `events/history/<kind>.jsonl`
sidecars so records that leave an API's window are kept. Kinds:
`codeql_alerts`, `dependabot_alerts`, `secret_scanning`, `pull_requests`,
`workflow_runs`, `issues`, `scorecard`. A permission gap is a `status` of
`not_permitted` (403) or `disabled` (404) in the envelope, never a null.
Dependabot is `not_permitted` under `GITHUB_TOKEN` today; a PAT would fix
it and is a repo-settings follow-up, not a code change.

## Running locally

```bash
scripts/run_metrics_tests.sh collectors                  # unit tests, no Django
python3 scripts/metrics/collect_all.py --repo-root . --out-dir /tmp/m --only code_health,architecture,tests
python3 scripts/metrics/collect_events.py --repo D10Scot/Dispatcharr --out-dir /tmp/m   # needs gh auth
```
```

- [ ] **Step 3: Amend the spec (§4.1)**

In the spec's §4.1 coverage paragraph, replace the sentence beginning "A failed suite
records" with:

> The backend suite runs one `coverage run -p` process per label and combines; the row carries
> `backend_failed_labels` and `backend_status: "failed"` when any label failed, and still
> reports the combined pct when `coverage combine` succeeded. The frontend side reports
> `frontend_status: "failed"` with a null pct when vitest did not produce a summary. A red
> day is a visible point, not a gap.

- [ ] **Step 4: Commit and open the PR**

```bash
git add -A scripts/metrics docs/superpowers/specs/2026-09-04-engineering-metrics-dashboard-design.md
```
Commit message: `chore(metrics): retire the API snapshot collectors; document the data layer`.

Push and open PR A with `gh pr create --repo D10Scot/Dispatcharr --base main --title "metrics: data layer — daily event dumps, coverage row, independent collectors (Part A)" --body-file <file>`.
The body lists the seven tasks, states that the pipeline has been failing since 2026-09-01
and why, and ends with the standard attribution trailer.

- [ ] **Step 5: After merge — update the data branch README and run the pipeline once**

```bash
git fetch origin metrics-data
git worktree add /tmp/metrics-data-wt origin/metrics-data
```
Edit `/tmp/metrics-data-wt/README.md`: under "Families", list `code_health`, `architecture`,
`tests`, `coverage` as live, add a section "Event dumps" pointing at `events/` and
`events/history/`, and a section "Retired" naming `security.jsonl`, `delivery.jsonl`,
`agentic.jsonl` as frozen on 2026-08-29 and no longer written. Commit on that worktree and
push to `metrics-data`.

Then: `gh workflow run metrics.yml --repo D10Scot/Dispatcharr` and watch with
`gh run watch --repo D10Scot/Dispatcharr`. Expected: both jobs green, the branch gains
`events/*.json`, `events/history/*.jsonl` and a `coverage.jsonl` row. If the coverage job
fails in the bootstrap, the base image may predate the `coverage` dependency: `SYNC_PYTHON_DEPS`
is `'true'` and should have installed it — check the "Syncing Python dependencies" log line.

---

# Part B — Curated inputs and the build step (`metrics-build-step`)

Setup: after PR A merges, `git worktree add ../Dispatcharr-metrics-b -b metrics-build-step origin/main`.

### Task 8: Package skeleton, hash-pinned requirement, git helpers

**Files:**
- Create: `metrics/__init__.py`, `metrics/build/__init__.py`, `metrics/build/tests/__init__.py` (all empty)
- Create: `metrics/requirements.txt`
- Create: `metrics/build/gitinfo.py`
- Create: `metrics/build/tests/test_gitinfo.py`, `metrics/build/tests/test_requirements.py`

**Interfaces:**
- `gitinfo.first_parent_shas(repo: Path, base: str, ref: str = "main") -> list[str]` (full SHAs,
  oldest first, base included).
- `gitinfo.commit_date(repo, sha) -> datetime` (author date, UTC-aware).
- `gitinfo.is_first_parent_on(repo, sha, base, ref) -> bool`.
- `gitinfo.pr_is_merged(repo_slug: str, number: int, gh=run_gh) -> bool | None` (`None` when
  `gh` is unavailable or errors; callers decide whether that is fatal).

- [ ] **Step 1: Skeleton and requirement**

Run:
```bash
mkdir -p metrics/build/tests && : > metrics/__init__.py && : > metrics/build/__init__.py && : > metrics/build/tests/__init__.py
python3 - <<'EOF'
import tomllib, pathlib
lock = tomllib.load(open("uv.lock", "rb"))
pkg = next(p for p in lock["package"] if p["name"] == "pyyaml")
lines = [f"pyyaml=={pkg['version']} \\"]
hashes = [pkg["sdist"]["hash"]] + [w["hash"] for w in pkg["wheels"]]
lines += [f"    --hash={h} \\" for h in hashes[:-1]] + [f"    --hash={hashes[-1]}"]
pathlib.Path("metrics/requirements.txt").write_text(
    "# The build step's one third-party dependency, hash-pinned from uv.lock\n"
    "# (metrics/build/tests/test_requirements.py keeps the two in step).\n"
    "# Install: python3 -m pip install --require-hashes -r metrics/requirements.txt\n" + "\n".join(lines) + "\n")
EOF
head -5 metrics/requirements.txt
```
Expected: `pyyaml==6.0.3 \` followed by 29 `--hash=sha256:...` lines.

- [ ] **Step 2: Write the failing tests**

`metrics/build/tests/test_requirements.py`:

```python
import re
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


class RequirementsPinTests(unittest.TestCase):
    def test_pyyaml_pin_matches_uv_lock(self):
        lock = tomllib.load((ROOT / "uv.lock").open("rb"))
        pkg = next(p for p in lock["package"] if p["name"] == "pyyaml")
        text = (ROOT / "metrics" / "requirements.txt").read_text()
        self.assertIn(f"pyyaml=={pkg['version']}", text)
        hashes = set(re.findall(r"--hash=(sha256:[0-9a-f]{64})", text))
        expected = {pkg["sdist"]["hash"]} | {w["hash"] for w in pkg["wheels"]}
        self.assertEqual(hashes, expected)
```

`metrics/build/tests/test_gitinfo.py`:

```python
import subprocess
import tempfile
import unittest
from datetime import timezone
from pathlib import Path

from gitinfo import commit_date, first_parent_shas, is_first_parent_on, pr_is_merged


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                          check=True, capture_output=True, text=True).stdout.strip()


def make_repo(tmp: Path) -> tuple[Path, list[str]]:
    repo = tmp / "r"; repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    shas = []
    for i in range(3):
        git(repo, "commit", "-q", "--allow-empty", "-m", f"c{i}", "--date", f"2026-08-{20 + i}T10:00:00+00:00")
        shas.append(git(repo, "rev-parse", "HEAD"))
    git(repo, "checkout", "-q", "-b", "side", shas[1])
    git(repo, "commit", "-q", "--allow-empty", "-m", "side")
    side = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", "-m", "merge side", "side")
    shas.append(git(repo, "rev-parse", "HEAD"))
    return repo, shas + [side]


class GitInfoTests(unittest.TestCase):
    def test_first_parent_walk(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, shas = make_repo(Path(tmp))
            self.assertEqual(first_parent_shas(repo, shas[0]), shas[:4])
            self.assertTrue(is_first_parent_on(repo, shas[3], shas[0]))
            self.assertFalse(is_first_parent_on(repo, shas[4], shas[0]), "a side-branch commit is not first-parent")

    def test_commit_date_is_utc_aware(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, shas = make_repo(Path(tmp))
            d = commit_date(repo, shas[1])
            self.assertEqual(d.tzinfo, timezone.utc)
            self.assertEqual((d.year, d.month, d.day), (2026, 8, 21))

    def test_pr_is_merged_uses_injected_runner(self):
        calls = []
        def fake(*args):
            calls.append(args); return '{"merged_at": "2026-09-01T00:00:00Z"}'
        self.assertTrue(pr_is_merged("o/r", 5, gh=fake))
        self.assertIn("/repos/o/r/pulls/5", calls[0])
        self.assertFalse(pr_is_merged("o/r", 6, gh=lambda *a: '{"merged_at": null}'))
        def broken(*a): raise OSError("no gh")
        self.assertIsNone(pr_is_merged("o/r", 7, gh=broken))
```

Run: `scripts/run_metrics_tests.sh build` → import errors for `gitinfo`, and the requirements
test passes (it only reads files).

- [ ] **Step 3: Write `gitinfo.py`**

```python
"""Git and GitHub facts the validators need, isolated so tests can inject a
fake `gh` and use a throwaway repo."""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from pathlib import Path


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def first_parent_shas(repo: Path, base: str, ref: str = "main") -> list[str]:
    """Full SHAs of base and every first-parent commit after it up to ref, oldest first."""
    base_full = _git(repo, "rev-parse", f"{base}^{{commit}}")
    later = _git(repo, "rev-list", "--first-parent", "--reverse", f"{base_full}..{ref}").splitlines()
    return [base_full] + [s for s in later if s]


def is_first_parent_on(repo: Path, sha: str, base: str, ref: str = "main") -> bool:
    try:
        full = _git(repo, "rev-parse", f"{sha}^{{commit}}")
    except subprocess.CalledProcessError:
        return False
    return full in first_parent_shas(repo, base, ref)


def commit_date(repo: Path, sha: str) -> dt.datetime:
    iso = _git(repo, "show", "-s", "--format=%aI", sha)
    return dt.datetime.fromisoformat(iso).astimezone(dt.timezone.utc)


def run_gh(*args: str) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


def pr_is_merged(repo_slug: str, number: int, gh=run_gh) -> bool | None:
    """True/False from the API; None when gh is unavailable or the call fails."""
    try:
        doc = json.loads(gh("api", f"/repos/{repo_slug}/pulls/{number}", "--method", "GET"))
    except (OSError, subprocess.CalledProcessError, ValueError):
        return None
    return bool(doc.get("merged_at"))
```

- [ ] **Step 4: Run to verify they pass**

Run: `scripts/run_metrics_tests.sh build` → `OK` (4 tests).

- [ ] **Step 5: Commit**

```bash
git add metrics
```
Commit message: `feat(metrics): build-step package skeleton, hash-pinned PyYAML, git helpers`.

### Task 9: Curated-file schemas and validators

**Files:**
- Create: `metrics/build/curated.py`
- Create: `metrics/build/tests/fixtures/curated/valid/{catalogue,milestones,defects}.yml`
- Create: `metrics/build/tests/test_curated.py`

**Interfaces:**
- `curated.load_curated(dir: Path) -> Curated` (dataclass: `catalogue: list[Metric]`,
  `phases: list[Phase]`, `milestones: list[Milestone]`, `defects: list[Defect]`).
- `curated.validate(c: Curated, *, repo: Path, base: str, ref: str, pr_checker=None, known_families: dict[str, set[str]] | None = None) -> list[str]`
  returns human-readable errors (empty means valid). `pr_checker(number) -> bool | None`;
  when `None`, PR checks are skipped (hook mode). `known_families` maps family → set of
  JSON pointers present in the latest row, used to check every `headline: true` snapshot
  entry resolves.
- Vocabularies (module constants): `DIRECTIONS = {"up","down","zero","info"}`,
  `UNITS = {"count","pct","seconds","days","score","lines","ratio"}`,
  `GROUPS = {"safety_net","security","extraction","delivery","agents"}`,
  `MILESTONE_KINDS = {"phase-start","phase-done","goal","incident","release"}`,
  `DEFECT_AREAS = {"security","correctness","dead-code","operational"}`,
  `DEFECT_STATUSES = ("open","pinned","carried","fixed")`,
  `DERIVATIONS` (set of derivation names, imported from `derive.DERIVATIONS` in Task 12; until
  then a literal set with the eleven names listed in Task 12).

- [ ] **Step 1: Write the valid fixtures**

`metrics/build/tests/fixtures/curated/valid/catalogue.yml`:

```yaml
- id: e2e_scenarios
  family: tests
  path: /e2e_scenario_count
  label: E2E scenarios
  unit: count
  direction: up
  target: null
  group: safety_net
  headline: true
  since: 2026-08-19
  note: "Playwright test() call sites under e2e/tests/**/*.spec.ts."
- id: codeql_open_critical_high
  family: derived
  derivation: codeql_open_count
  params: {severities: [critical, high]}
  label: Open CodeQL critical + high
  unit: count
  direction: zero
  target: null
  group: security
  headline: true
  since: 2026-08-23
  note: "Open code-scanning alerts with security severity critical or high."
- id: proxy_loc
  family: code_health
  path: /loc_per_app/apps.proxy
  label: apps/proxy lines
  unit: lines
  direction: info
  target: null
  group: extraction
  headline: false
  since: 2026-08-19
  note: "Non-blank Python lines under apps/proxy."
```

`metrics/build/tests/fixtures/curated/valid/milestones.yml`:

```yaml
phases:
  - id: investigate
    label: Investigate
    summary: "Read before writing: a verified defect map."
    headline_ids: [e2e_scenarios]
  - id: phase0
    label: Phase 0
    summary: "Harden in place."
    headline_ids: [codeql_open_critical_high]
milestones:
  - sha: BASE
    label: v0.29.0 baseline
    kind: phase-start
    phase: investigate
    pr: null
    summary: "Fork divergence point."
  - sha: SECOND
    label: PR 2
    kind: goal
    phase: phase0
    pr: 2
    summary: "A goal."
```

(`BASE` / `SECOND` are placeholders the test substitutes with SHAs from its throwaway repo.)

`metrics/build/tests/fixtures/curated/valid/defects.yml`:

```yaml
- id: unfenced-lease
  title: "Ownership lease is not fenced"
  area: correctness
  severity: high
  status: open
  source: "CLAUDE.md#known-defects-and-traps"
  issue: null
  test: null
  fixed_in: null
  carried_as: null
  first_seen: 2026-08-22
  status_changed: 2026-08-22
- id: m3u-quote
  title: "Unescaped quote in EXTINF"
  area: correctness
  severity: medium
  status: pinned
  source: null
  issue: 80
  test: e2e/tests/seeded/output-m3u.spec.ts
  fixed_in: null
  carried_as: null
  first_seen: 2026-08-29
  status_changed: 2026-08-30
```

- [ ] **Step 2: Write the failing tests**

`metrics/build/tests/test_curated.py`:

```python
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

from curated import load_curated, validate

FIX = Path(__file__).resolve().parent / "fixtures" / "curated" / "valid"


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                          check=True, capture_output=True, text=True).stdout.strip()


class CuratedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.repo = self.tmp / "repo"; self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "base"); self.base = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "second"); self.second = git(self.repo, "rev-parse", "HEAD")
        (self.repo / "e2e" / "tests" / "seeded").mkdir(parents=True)
        (self.repo / "e2e" / "tests" / "seeded" / "output-m3u.spec.ts").write_text("")
        self.curated = self.tmp / "curated"
        shutil.copytree(FIX, self.curated)
        m = (self.curated / "milestones.yml").read_text().replace("BASE", self.base).replace("SECOND", self.second)
        (self.curated / "milestones.yml").write_text(m)
        self.families = {"tests": {"/e2e_scenario_count"}, "code_health": {"/loc_per_app/apps.proxy"}}

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _errors(self, pr_checker=lambda n: True):
        c = load_curated(self.curated)
        return validate(c, repo=self.repo, base=self.base, ref="main", pr_checker=pr_checker, known_families=self.families)

    def _mutate(self, name, fn):
        p = self.curated / name
        doc = yaml.safe_load(p.read_text())
        fn(doc)
        p.write_text(yaml.safe_dump(doc, sort_keys=False))

    def test_valid_fixtures_have_no_errors(self):
        self.assertEqual(self._errors(), [])

    def test_catalogue_rejects_unknown_direction_and_group(self):
        self._mutate("catalogue.yml", lambda d: d[0].update(direction="sideways", group="misc"))
        errs = self._errors()
        self.assertTrue(any("direction" in e for e in errs)); self.assertTrue(any("group" in e for e in errs))

    def test_catalogue_headline_must_resolve_against_data(self):
        self._mutate("catalogue.yml", lambda d: d[0].update(path="/does_not_exist"))
        self.assertTrue(any("does not resolve" in e for e in self._errors()))

    def test_catalogue_derived_needs_known_derivation(self):
        self._mutate("catalogue.yml", lambda d: d[1].update(derivation="nope"))
        self.assertTrue(any("derivation" in e for e in self._errors()))

    def test_catalogue_ids_unique(self):
        self._mutate("catalogue.yml", lambda d: d[2].update(id="e2e_scenarios"))
        self.assertTrue(any("duplicate id" in e for e in self._errors()))

    def test_milestone_sha_must_be_first_parent_on_main(self):
        git(self.repo, "checkout", "-q", "-b", "side", self.base)
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "side"); side = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "checkout", "-q", "main")
        self._mutate("milestones.yml", lambda d: d["milestones"][1].update(sha=side))
        self.assertTrue(any("first-parent" in e for e in self._errors()))

    def test_milestone_pr_must_be_merged_when_checker_present(self):
        self.assertTrue(any("not merged" in e for e in self._errors(pr_checker=lambda n: False)))
        self.assertEqual(self._errors(pr_checker=None), [], "hook mode skips PR checks")

    def test_milestone_phase_must_exist_and_label_short(self):
        self._mutate("milestones.yml", lambda d: d["milestones"][1].update(phase="phase9", label="x" * 41))
        errs = self._errors()
        self.assertTrue(any("phase" in e for e in errs)); self.assertTrue(any("label" in e for e in errs))

    def test_phase_headline_ids_must_exist(self):
        self._mutate("milestones.yml", lambda d: d["phases"][0].update(headline_ids=["ghost"]))
        self.assertTrue(any("headline_ids" in e for e in self._errors()))

    def test_defect_status_required_fields(self):
        self._mutate("defects.yml", lambda d: d[1].update(test=None))
        self.assertTrue(any("pinned" in e and "test" in e for e in self._errors()))
        self._mutate("defects.yml", lambda d: d[0].update(source=None))
        self.assertTrue(any("open" in e and "issue" in e for e in self._errors()))

    def test_defect_test_path_must_exist(self):
        self._mutate("defects.yml", lambda d: d[1].update(test="e2e/tests/nope.spec.ts"))
        self.assertTrue(any("does not exist" in e for e in self._errors()))

    def test_defect_status_cannot_move_backwards(self):
        from curated import validate_transitions
        before = load_curated(self.curated)
        self._mutate("defects.yml", lambda d: d[1].update(status="open", test=None, issue=80))
        after = load_curated(self.curated)
        errs = validate_transitions(before.defects, after.defects)
        self.assertTrue(any("backward" in e for e in errs))
        self.assertEqual(validate_transitions(after.defects, before.defects), [])
```

Run: `scripts/run_metrics_tests.sh build` → import error for `curated`.

- [ ] **Step 3: Write `curated.py`**

```python
"""The three agent-maintained inputs and their validation.

Schemas are documented for humans and agents in docs/agents/metrics.md; this
module is the executable version. Validation returns every error at once so
one edit-run cycle fixes a whole file.
"""

from __future__ import annotations

import dataclasses as dc
import datetime as dt
from pathlib import Path
from typing import Any, Callable

import yaml

from gitinfo import is_first_parent_on

DIRECTIONS = {"up", "down", "zero", "info"}
UNITS = {"count", "pct", "seconds", "days", "score", "lines", "ratio"}
GROUPS = {"safety_net", "security", "extraction", "delivery", "agents"}
MILESTONE_KINDS = {"phase-start", "phase-done", "goal", "incident", "release"}
DEFECT_AREAS = {"security", "correctness", "dead-code", "operational"}
DEFECT_SEVERITIES = {"critical", "high", "medium", "low"}
DEFECT_STATUSES = ("open", "pinned", "carried", "fixed")
DERIVATIONS = {
    "codeql_open_count", "codeql_oldest_open_age_days", "codeql_fixed_per_week",
    "scorecard_score", "scorecard_check", "ci_pass_rate_30d", "ci_median_wall_time_30d",
    "pr_lead_time_30d", "pr_product_ratio_30d", "prs_merged_30d",
    "issues_open_by_label", "issues_time_to_triage_median_30d", "defects_by_status",
}
ALLOWED_TRANSITIONS = {("open", "pinned"), ("open", "carried"), ("open", "fixed"),
                       ("pinned", "fixed"), ("carried", "fixed")}


@dc.dataclass
class Metric:
    id: str
    family: str
    label: str
    unit: str
    direction: str
    group: str
    headline: bool
    since: dt.date
    note: str
    target: float | None = None
    path: str | None = None
    derivation: str | None = None
    params: dict = dc.field(default_factory=dict)


@dc.dataclass
class Phase:
    id: str
    label: str
    summary: str
    headline_ids: list[str]


@dc.dataclass
class Milestone:
    sha: str
    label: str
    kind: str
    phase: str
    summary: str
    pr: int | None = None


@dc.dataclass
class Defect:
    id: str
    title: str
    area: str
    severity: str
    status: str
    first_seen: dt.date
    status_changed: dt.date
    source: str | None = None
    issue: int | None = None
    test: str | None = None
    fixed_in: int | None = None
    carried_as: str | None = None


@dc.dataclass
class Curated:
    catalogue: list[Metric]
    phases: list[Phase]
    milestones: list[Milestone]
    defects: list[Defect]


def _build(cls, raw: dict, where: str, errors: list[str]):
    fields = {f.name for f in dc.fields(cls)}
    unknown = set(raw) - fields
    if unknown:
        errors.append(f"{where}: unknown fields {sorted(unknown)}")
    kwargs = {k: v for k, v in raw.items() if k in fields}
    for f in dc.fields(cls):
        if f.name not in kwargs and f.default is dc.MISSING and f.default_factory is dc.MISSING:
            errors.append(f"{where}: missing required field '{f.name}'")
            kwargs[f.name] = None
    try:
        return cls(**kwargs)
    except TypeError as exc:
        errors.append(f"{where}: {exc}")
        return None


def _read(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_curated(directory: Path) -> Curated:
    """Load the three files; raises ValueError listing structural problems."""
    errors: list[str] = []
    cat_raw = _read(directory / "catalogue.yml") or []
    ms_raw = _read(directory / "milestones.yml") or {}
    def_raw = _read(directory / "defects.yml") or []
    catalogue = [m for i, r in enumerate(cat_raw) if (m := _build(Metric, r, f"catalogue[{i}]", errors))]
    phases = [p for i, r in enumerate(ms_raw.get("phases", [])) if (p := _build(Phase, r, f"phases[{i}]", errors))]
    milestones = [m for i, r in enumerate(ms_raw.get("milestones", [])) if (m := _build(Milestone, r, f"milestones[{i}]", errors))]
    defects = [d for i, r in enumerate(def_raw) if (d := _build(Defect, r, f"defects[{i}]", errors))]
    if errors:
        raise ValueError("curated files are malformed:\n  " + "\n  ".join(errors))
    return Curated(catalogue, phases, milestones, defects)


def validate(
    c: Curated,
    *,
    repo: Path,
    base: str,
    ref: str = "main",
    pr_checker: Callable[[int], bool | None] | None = None,
    known_families: dict[str, set[str]] | None = None,
) -> list[str]:
    errors: list[str] = []
    ids: set[str] = set()
    for m in c.catalogue:
        w = f"catalogue '{m.id}'"
        if m.id in ids:
            errors.append(f"{w}: duplicate id")
        ids.add(m.id)
        if m.direction not in DIRECTIONS:
            errors.append(f"{w}: direction '{m.direction}' not in {sorted(DIRECTIONS)}")
        if m.unit not in UNITS:
            errors.append(f"{w}: unit '{m.unit}' not in {sorted(UNITS)}")
        if m.group not in GROUPS:
            errors.append(f"{w}: group '{m.group}' not in {sorted(GROUPS)}")
        if m.direction == "zero" and m.target not in (None, 0):
            errors.append(f"{w}: direction zero implies target 0")
        if not isinstance(m.since, dt.date):
            errors.append(f"{w}: since must be a date")
        if m.family == "derived":
            if m.derivation not in DERIVATIONS:
                errors.append(f"{w}: unknown derivation '{m.derivation}'")
        else:
            if not m.path or not m.path.startswith("/"):
                errors.append(f"{w}: path must be a JSON pointer starting with '/'")
            elif known_families is not None and m.headline:
                present = known_families.get(m.family)  # None: the family has no row yet (coverage before its first daily run)
                if present is not None and m.path not in present:
                    errors.append(f"{w}: headline path {m.family}{m.path} does not resolve against the latest row")

    phase_ids = {p.id for p in c.phases}
    for p in c.phases:
        missing = [h for h in p.headline_ids if h not in ids]
        if missing:
            errors.append(f"phase '{p.id}': headline_ids {missing} are not catalogue ids")

    for m in c.milestones:
        w = f"milestone '{m.label}'"
        if m.kind not in MILESTONE_KINDS:
            errors.append(f"{w}: kind '{m.kind}' not in {sorted(MILESTONE_KINDS)}")
        if m.phase not in phase_ids:
            errors.append(f"{w}: phase '{m.phase}' is not declared under phases:")
        if len(m.label or "") > 40:
            errors.append(f"{w}: label longer than 40 characters")
        if not isinstance(m.sha, str) or len(m.sha) != 40:
            errors.append(f"{w}: sha must be a full 40-character SHA")
        elif not is_first_parent_on(repo, m.sha, base, ref):
            errors.append(f"{w}: sha {m.sha[:12]} is not a first-parent commit on {ref} since {base[:12]}")
        if m.pr is not None and pr_checker is not None:
            merged = pr_checker(m.pr)
            if merged is False:
                errors.append(f"{w}: PR #{m.pr} is not merged")
            elif merged is None:
                errors.append(f"{w}: could not verify PR #{m.pr} (gh unavailable)")

    seen: set[str] = set()
    for d in c.defects:
        w = f"defect '{d.id}'"
        if d.id in seen:
            errors.append(f"{w}: duplicate id")
        seen.add(d.id)
        if d.area not in DEFECT_AREAS:
            errors.append(f"{w}: area '{d.area}' not in {sorted(DEFECT_AREAS)}")
        if d.severity not in DEFECT_SEVERITIES:
            errors.append(f"{w}: severity '{d.severity}' not in {sorted(DEFECT_SEVERITIES)}")
        if d.status not in DEFECT_STATUSES:
            errors.append(f"{w}: status '{d.status}' not in {DEFECT_STATUSES}")
        if d.status == "open" and d.issue is None and not d.source:
            errors.append(f"{w}: status open needs issue or source")
        if d.status == "pinned" and (d.issue is None or not d.test):
            errors.append(f"{w}: status pinned needs issue and test")
        if d.status == "fixed" and d.fixed_in is None:
            errors.append(f"{w}: status fixed needs fixed_in")
        if d.status == "carried" and not d.carried_as:
            errors.append(f"{w}: status carried needs carried_as")
        if d.test and not (repo / d.test).exists():
            errors.append(f"{w}: test path {d.test} does not exist")
        if d.fixed_in is not None and pr_checker is not None and pr_checker(d.fixed_in) is False:
            errors.append(f"{w}: fixed_in PR #{d.fixed_in} is not merged")
        for name in ("first_seen", "status_changed"):
            if not isinstance(getattr(d, name), dt.date):
                errors.append(f"{w}: {name} must be a date")
    return errors


def validate_transitions(before: list[Defect], after: list[Defect]) -> list[str]:
    """Status moves only forward (spec §5.3). `before` is the ledger on main."""
    errors = []
    prev = {d.id: d for d in before}
    for d in after:
        old = prev.get(d.id)
        if old and old.status != d.status and (old.status, d.status) not in ALLOWED_TRANSITIONS:
            errors.append(f"defect '{d.id}': status moved backward {old.status} -> {d.status}")
    return errors
```

- [ ] **Step 4: Run to verify they pass**

Run: `scripts/run_metrics_tests.sh build` → `OK`. If `yaml` is missing locally, run
`uv sync` first (PyYAML is a transitive dependency of the project).

- [ ] **Step 5: Commit**

```bash
git add metrics/build/curated.py metrics/build/tests/fixtures metrics/build/tests/test_curated.py
```
Commit message: `feat(metrics): schemas and validators for the catalogue, milestones and defect ledger`.

### Task 10: Seed the three curated files from the real repo

**Files:**
- Create: `metrics/curated/catalogue.yml`, `metrics/curated/milestones.yml`, `metrics/curated/defects.yml`
- Create: `metrics/build/tests/test_real_curated.py`

- [ ] **Step 1: Write the catalogue**

`metrics/curated/catalogue.yml` — every entry below; `headline: true` on exactly twenty.

```yaml
# Metric catalogue. Nothing renders unless it is listed here.
# Contract: docs/agents/metrics.md. Validated by metrics/build/curated.py.
# ---------------------------------------------------------------- safety net
- {id: e2e_scenarios, family: tests, path: /e2e_scenario_count, label: E2E scenarios, unit: count, direction: up, target: null, group: safety_net, headline: true, since: 2026-08-19,
   note: "Playwright test() call sites under e2e/tests/**/*.spec.ts, by regex; test.fail() pins count."}
- {id: backend_coverage, family: coverage, path: /backend_line_pct, label: Backend line coverage, unit: pct, direction: up, target: 60, group: safety_net, headline: true, since: 2026-09-05,
   note: "Daily: every backend label under coverage, combined. Status failed means a label failed that day."}
- {id: frontend_coverage, family: coverage, path: /frontend_line_pct, label: Frontend line coverage, unit: pct, direction: up, target: 75, group: safety_net, headline: true, since: 2026-09-05,
   note: "Daily vitest --coverage, total lines."}
- {id: defects_pinned, family: derived, derivation: defects_by_status, params: {status: pinned}, label: Known bugs pinned by a test, unit: count, direction: info, target: null, group: safety_net, headline: true, since: 2026-08-22,
   note: "Ledger entries with a failing test that asserts the bug (test.fail() or a backend test)."}
- {id: backend_tests, family: tests, path: /backend_test_count, label: Backend tests, unit: count, direction: up, target: null, group: safety_net, headline: false, since: 2026-08-19, note: "test_* functions in backend test files, by AST."}
- {id: frontend_tests, family: tests, path: /frontend_test_count, label: Frontend tests, unit: count, direction: up, target: null, group: safety_net, headline: false, since: 2026-08-19, note: "it()/test() call sites in frontend/**/*.test.{js,jsx}."}
- {id: property_tests, family: tests, path: /hypothesis_property_test_count, label: Hypothesis property tests, unit: count, direction: up, target: null, group: safety_net, headline: false, since: 2026-08-19, note: "@given-decorated backend tests."}
- {id: greybox_tests, family: tests, path: /e2e_greybox_test_count, label: Grey-box e2e tests, unit: count, direction: info, target: null, group: safety_net, headline: false, since: 2026-08-19, note: "Under tests/streaming-greybox/: rewritten or deleted in Phase 3."}
- {id: coverage_rows_done, family: tests, path: /coverage_md_rows/done, label: COVERAGE.md rows done, unit: count, direction: up, target: null, group: safety_net, headline: false, since: 2026-08-19, note: "e2e/COVERAGE.md rows with status done."}
- {id: coverage_rows_known_bug, family: tests, path: /coverage_md_rows/known_bug, label: COVERAGE.md rows known-bug, unit: count, direction: info, target: null, group: safety_net, headline: false, since: 2026-08-19, note: "Rows asserted correct with test.fail() and an issue."}
- {id: coverage_rows_todo, family: tests, path: /coverage_md_rows/todo, label: COVERAGE.md rows todo, unit: count, direction: down, target: 0, group: safety_net, headline: false, since: 2026-08-19, note: "Open rows in the shared e2e worklist."}
# ------------------------------------------------------------------ security
- {id: codeql_open_critical_high, family: derived, derivation: codeql_open_count, params: {severities: [critical, high]}, label: Open CodeQL critical + high, unit: count, direction: zero, target: null, group: security, headline: true, since: 2026-08-23,
   note: "Open code-scanning alerts (CodeQL tool) at security severity critical or high, as of each day."}
- {id: codeql_oldest_critical_high_days, family: derived, derivation: codeql_oldest_open_age_days, params: {severities: [critical, high]}, label: Oldest open critical/high, unit: days, direction: down, target: 30, group: security, headline: true, since: 2026-08-23,
   note: "Age in days of the oldest still-open critical or high alert."}
- {id: scorecard, family: derived, derivation: scorecard_score, params: {}, label: OpenSSF Scorecard, unit: score, direction: up, target: 8, group: security, headline: true, since: 2026-08-23,
   note: "Aggregate score from api.securityscorecards.dev; the repo publishes results weekly."}
- {id: scorecard_findings_open, family: derived, derivation: codeql_open_count, params: {tools: [Scorecard]}, label: Open Scorecard findings, unit: count, direction: down, target: 0, group: security, headline: true, since: 2026-08-23,
   note: "Open code-scanning alerts uploaded by scorecard.yml (one per failing check). zizmor findings are deliberately NOT uploaded as SARIF (actions-lint.yml), so the 101-to-0 ratchet is a milestone note, not a series."}
- {id: codeql_open_medium_low, family: derived, derivation: codeql_open_count, params: {severities: [medium, low]}, label: Open CodeQL medium + low, unit: count, direction: down, target: 0, group: security, headline: false, since: 2026-08-23, note: "Open CodeQL alerts at medium or low."}
- {id: codeql_fixed_per_week, family: derived, derivation: codeql_fixed_per_week, params: {}, label: CodeQL alerts fixed per week, unit: count, direction: up, target: null, group: security, headline: false, since: 2026-08-23, note: "Alerts whose fixed_at falls in the trailing 7 days."}
- {id: scorecard_branch_protection, family: derived, derivation: scorecard_check, params: {name: Branch-Protection}, label: Scorecard Branch-Protection, unit: score, direction: up, target: 10, group: security, headline: false, since: 2026-08-23, note: "One Scorecard check."}
- {id: scorecard_pinned_deps, family: derived, derivation: scorecard_check, params: {name: Pinned-Dependencies}, label: Scorecard Pinned-Dependencies, unit: score, direction: up, target: 10, group: security, headline: false, since: 2026-08-23, note: "One Scorecard check."}
# ---------------------------------------------------------------- extraction
- {id: reverse_imports_into_proxy, family: architecture, path: /reverse_imports_into_proxy, label: Reverse imports into apps/proxy, unit: count, direction: down, target: 0, group: extraction, headline: true, since: 2026-08-19,
   note: "Non-test import statements outside apps/proxy that import from it. Target 0 by the end of Phase 1."}
- {id: import_cycles, family: architecture, path: /import_cycles, label: Import cycles, unit: count, direction: down, target: 0, group: extraction, headline: true, since: 2026-08-19,
   note: "Strongly connected components of size > 1 in the cross-app import graph."}
- {id: models_boot_trap_imports, family: architecture, path: /models_module_level_live_proxy_imports, label: models.py boot-trap imports, unit: count, direction: zero, target: null, group: extraction, headline: true, since: 2026-08-19,
   note: "Module-level imports of apps.proxy.live_proxy in apps/channels/models.py; one more import there stops Django booting."}
- {id: proxy_orm_writes, family: architecture, path: /proxy_orm_writes, label: apps/proxy ORM writes, unit: count, direction: down, target: 0, group: extraction, headline: true, since: 2026-08-19,
   note: "ORM write calls in non-test apps/proxy code. Exactly one at baseline."}
- {id: cross_app_edges, family: architecture, path: /cross_app_import_edges, label: Cross-app import edges, unit: count, direction: down, target: null, group: extraction, headline: false, since: 2026-08-19, note: "Distinct (from_app, to_app) pairs."}
- {id: cross_app_statements, family: architecture, path: /cross_app_import_statements, label: Cross-app import statements, unit: count, direction: down, target: null, group: extraction, headline: false, since: 2026-08-19, note: "Import statements crossing an app boundary."}
- {id: function_local_imports, family: code_health, path: /function_local_imports, label: Function-local imports, unit: count, direction: down, target: null, group: extraction, headline: false, since: 2026-08-19, note: "Imports nested inside functions — the boot-cycle workaround, 602 in apps/ alone."}
- {id: proxy_loc, family: code_health, path: /loc_per_app/apps.proxy, label: apps/proxy lines, unit: lines, direction: info, target: null, group: extraction, headline: false, since: 2026-08-19, note: "Non-blank Python lines under apps/proxy."}
- {id: channels_loc, family: code_health, path: /loc_per_app/apps.channels, label: apps/channels lines, unit: lines, direction: info, target: null, group: extraction, headline: false, since: 2026-08-19, note: "Non-blank Python lines under apps/channels."}
- {id: bare_except, family: code_health, path: /bare_except, label: Bare except handlers, unit: count, direction: down, target: 0, group: extraction, headline: false, since: 2026-08-19, note: "except: with no type."}
- {id: except_pass, family: code_health, path: /except_pass_handlers, label: except-pass handlers, unit: count, direction: down, target: null, group: extraction, headline: false, since: 2026-08-19, note: "Handlers whose entire body is pass."}
- {id: os_environ_reads, family: code_health, path: /os_environ_reads, label: os.environ reads, unit: count, direction: down, target: null, group: extraction, headline: false, since: 2026-08-19, note: "Five ways to read configuration; this counts the raw one."}
# ------------------------------------------------------------------ delivery
- {id: ci_pass_rate_required, family: derived, derivation: ci_pass_rate_30d, params: {workflows: ["E2E Tests", "Backend Tests", "Frontend Tests", "Lifecycle Tests"]}, label: Required-check pass rate (30 d), unit: ratio, direction: up, target: 0.95, group: delivery, headline: true, since: 2026-08-23,
   note: "success / (success + failure) over completed runs of the four required workflows in the trailing 30 days."}
- {id: e2e_wall_time, family: derived, derivation: ci_median_wall_time_30d, params: {workflow: "E2E Tests"}, label: E2E median wall time (30 d), unit: seconds, direction: down, target: null, group: delivery, headline: true, since: 2026-08-23,
   note: "Median run duration of the E2E Tests workflow over the trailing 30 days."}
- {id: pr_lead_time_p50, family: derived, derivation: pr_lead_time_30d, params: {quantile: 0.5, author_type: all}, label: PR lead time p50 (30 d), unit: seconds, direction: down, target: null, group: delivery, headline: true, since: 2026-08-23,
   note: "Open-to-merge time of PRs merged in the trailing 30 days."}
- {id: product_ratio, family: derived, derivation: pr_product_ratio_30d, params: {}, label: Product share of merged lines (30 d), unit: ratio, direction: info, target: null, group: delivery, headline: true, since: 2026-08-23,
   note: "Lines under apps/ over all lines across PRs merged in the trailing 30 days. The migration story in one number: almost nothing touches the product."}
- {id: pr_lead_time_p90, family: derived, derivation: pr_lead_time_30d, params: {quantile: 0.9, author_type: all}, label: PR lead time p90 (30 d), unit: seconds, direction: down, target: null, group: delivery, headline: false, since: 2026-08-23, note: "Trailing 30 days."}
- {id: ci_pass_rate_all, family: derived, derivation: ci_pass_rate_30d, params: {workflows: []}, label: All-workflow pass rate (30 d), unit: ratio, direction: up, target: null, group: delivery, headline: false, since: 2026-08-23, note: "Every workflow, including agentic and scheduled ones."}
- {id: backend_wall_time, family: derived, derivation: ci_median_wall_time_30d, params: {workflow: "Backend Tests"}, label: Backend median wall time (30 d), unit: seconds, direction: down, target: null, group: delivery, headline: false, since: 2026-08-23, note: "Trailing 30 days."}
# -------------------------------------------------------------------- agents
- {id: needs_triage_open, family: derived, derivation: issues_open_by_label, params: {label: needs-triage}, label: Open needs-triage issues, unit: count, direction: down, target: 0, group: agents, headline: true, since: 2026-08-23,
   note: "Issues carrying needs-triage as of each day (from label events)."}
- {id: time_to_triage, family: derived, derivation: issues_time_to_triage_median_30d, params: {}, label: Median time to triage (30 d), unit: seconds, direction: down, target: 259200, group: agents, headline: true, since: 2026-08-23,
   note: "Creation to needs-triage removal, issues triaged in the trailing 30 days. Target 3 days."}
- {id: agent_prs_merged, family: derived, derivation: prs_merged_30d, params: {author_type: agent}, label: Agent PRs merged (30 d), unit: count, direction: info, target: null, group: agents, headline: true, since: 2026-08-23,
   note: "Bot authors or gh-aw branch patterns (copilot/, agentics/, *remediation*). A person driving Copilot CLI counts as human."}
- {id: defects_fixed, family: derived, derivation: defects_by_status, params: {status: fixed}, label: Known defects fixed, unit: count, direction: up, target: null, group: agents, headline: true, since: 2026-08-22,
   note: "Ledger entries with a merged fixing PR."}
- {id: ready_for_agent_open, family: derived, derivation: issues_open_by_label, params: {label: ready-for-agent}, label: Open ready-for-agent issues, unit: count, direction: info, target: null, group: agents, headline: false, since: 2026-08-23, note: "The remediation queue."}
- {id: human_prs_merged, family: derived, derivation: prs_merged_30d, params: {author_type: human}, label: Human PRs merged (30 d), unit: count, direction: info, target: null, group: agents, headline: false, since: 2026-08-23, note: "Everything not counted as agent."}
- {id: defects_open, family: derived, derivation: defects_by_status, params: {status: open}, label: Known defects open, unit: count, direction: down, target: 0, group: agents, headline: false, since: 2026-08-22, note: "Ledger entries with no test and no fix."}
- {id: defects_carried, family: derived, derivation: defects_by_status, params: {status: carried}, label: Known defects carried as constraints, unit: count, direction: info, target: null, group: agents, headline: false, since: 2026-08-22, note: "Written into a spec as something the extracted relay must not recreate."}
```

- [ ] **Step 2: Write the milestones**

`metrics/curated/milestones.yml`:

```yaml
# Phases and milestones. Contract: docs/agents/metrics.md.
# Every sha is a first-parent commit on main; never edit a past entry's sha or kind.
phases:
  - id: investigate
    label: Investigate
    summary: "Read before writing: CLAUDE.md and CONTEXT.md as a verified defect map, a supply-chain audit that cleared 101 zizmor findings and found a test package CI never ran."
    headline_ids: [scorecard_findings_open, backend_tests]
  - id: e2e
    label: E2E programme
    summary: "Fifteen goals, each a spec, plan, worktree and PR: a fake Xtream provider, then 249 Playwright scenarios across 13 projects; every defect found became a test.fail() pin, an issue and a COVERAGE.md row."
    headline_ids: [e2e_scenarios, coverage_rows_done, defects_pinned]
  - id: agents
    label: Agent pipeline
    summary: "Fuzz campaign, triage and remediation workflows on a label-driven pipeline; Hypothesis property tests as permanent output."
    headline_ids: [needs_triage_open, property_tests]
  - id: phase0
    label: Phase 0
    summary: "Harden in place: six small PRs in one day — test routing, lockfile install, credential redaction, a requireable result aggregate per suite, a release that trusts the migration gate."
    headline_ids: [codeql_open_critical_high, ci_pass_rate_required, defects_fixed]
  - id: phase1
    label: Phase 1
    summary: "Extract the relay boundary, still Python. Stopping here is a legitimate outcome."
    headline_ids: [reverse_imports_into_proxy, import_cycles, proxy_orm_writes]
milestones:
  - {sha: fd413f0cc4ab3131789a68fb31f1ae622ae7371a, label: v0.29.0 baseline, kind: phase-start, phase: investigate, pr: null, summary: "Fork divergence point from upstream Dispatcharr."}
  - {sha: 4ede0d70778abfa167001045b15153bf43fa2edc, label: zizmor + 16/16 packages, kind: goal, phase: investigate, pr: 2, summary: "Actions linting, 101 findings cleared, the silently missing 16th backend test package fixed."}
  - {sha: f902412da3bc5763c31af8c8771a6b671b1a1ebc, label: Supply-chain hardening, kind: goal, phase: investigate, pr: 4, summary: "SHA-pinned actions, digest-pinned images, lint, vuln-scan, Scorecard, Renovate, CodeQL."}
  - {sha: e1098206077f7d6c4e60a47133eb95c15dbd354e, label: First Playwright test, kind: phase-start, phase: e2e, pr: 1, summary: "One smoke test and a CI workflow."}
  - {sha: a0c99cddfabd26e32b65f17bb68129a986b35214, label: G1 harness, kind: goal, phase: e2e, pr: 5, summary: "Fixtures, project topology, storageState, WS queue, byte-level TS reading."}
  - {sha: c188aab6f7c593cccd8f4aadc316371f0ad0e2d5, label: G2 fake provider, kind: goal, phase: e2e, pr: 19, summary: "Playlist, EPG, paced TS loop, eight injectable faults."}
  - {sha: 6e71ca20376b01cd73945ee10fe006f22a30ac11, label: G4 streaming data path, kind: goal, phase: e2e, pr: 33, summary: "Eleven rows, three CI jobs, the grey-box Redis quarantine."}
  - {sha: dcdeae68166c3dfa9e8b9692ce70d8a461c32d00, label: G7 lifecycle, kind: goal, phase: e2e, pr: 43, summary: "Restart, upgrade-with-migrations, and 28 bash scenarios that ran nowhere."}
  - {sha: e1616ae69d4f6aba7f553543d7b5e9e8d0832e54, label: G8 Xtream provider, kind: goal, phase: e2e, pr: 77, summary: "The fake provider speaks Xtream Codes."}
  - {sha: 8d6db577f7280beed0e6ba8e40db362b83de6306, label: G3 sources and ingest, kind: goal, phase: e2e, pr: 78, summary: "M3U and EPG sources end to end."}
  - {sha: e8f70df96fe767d674f86ee9b4cd0bfb8540540f, label: G6 frontend surfaces, kind: goal, phase: e2e, pr: 79, summary: "Nine surfaces with page-level handles."}
  - {sha: 10c792d7cf5604b917f4053384acf1b53aff6f0b, label: G5 client outputs, kind: goal, phase: e2e, pr: 88, summary: "M3U, EPG, HDHR, Xtream and the authorization matrix."}
  - {sha: 25bf34844a8885a91c854e8117c67662586aa6db, label: G9 VOD and series, kind: goal, phase: e2e, pr: 112, summary: "VOD and series end to end."}
  - {sha: 76db0332a1586f22cfe715902c69d34589e921fb, label: G10 catch-up, kind: goal, phase: e2e, pr: 113, summary: "Catch-up and timeshift end to end."}
  - {sha: 4211cbb7968a349c32efbb84d96439811d42288a, label: G11 migration gate, kind: goal, phase: e2e, pr: 123, summary: "Six static guards, two ADRs, full-run CI on migration branches."}
  - {sha: 7a408c2b09e11314d6ae63309e0482b35964d243, label: G11 every test tagged, kind: goal, phase: e2e, pr: 124, summary: "@contract or @characterization on every test, enforced."}
  - {sha: 9808cad8be2175ee2d410a2c110e563e17c4b477, label: G12 bash suites green, kind: goal, phase: e2e, pr: 130, summary: "Triage the bash suites; deepen the lifecycle gate."}
  - {sha: e840f676f3aeedd1b938fbe76fbce32e7b107290, label: G15 hollow pins guarded, kind: goal, phase: e2e, pr: 139, summary: "Nine hollow-premise test.fail() pins guarded."}
  - {sha: 32e8ba0dedb3ec7d5894b818b7365baeeab76961, label: G13 DVR lifecycle, kind: goal, phase: e2e, pr: 144, summary: "Recording lifecycle through the real relay."}
  - {sha: cdc87a383842cd7b28d76cd851d4e45626853665, label: G14 coverage completions, kind: phase-done, phase: e2e, pr: 143, summary: "ACL 403s, EPG matching, bulk ops, M3U filters, WS events; the programme closes."}
  - {sha: 7f42b25e435ec25c5b1843da0b0dc31336727730, label: Fuzz campaign, kind: phase-start, phase: agents, pr: 8, summary: "One domain per run, typed prioritised issues."}
  - {sha: 908d312b123854676e9c7674b7a25e2a9f70f1c3, label: Issue triage workflow, kind: goal, phase: agents, pr: 29, summary: "Validate, dedupe, audit priority, route."}
  - {sha: ce15981f003e0515dd6ffb00b55d8fcd00340655, label: Issue remediation workflow, kind: goal, phase: agents, pr: 28, summary: "Reproduce first, second-model review, draft PR."}
  - {sha: b63e2cf9e2744d7961f74aef9d81c512d7da25e1, label: Hypothesis foundation, kind: goal, phase: agents, pr: 36, summary: "Property tests for TS realignment and log parsers."}
  - {sha: a6fc2b96142d008771edbea5232bcc60b619c609, label: Metrics collectors (M1), kind: goal, phase: agents, pr: 40, summary: "Collectors, history workflow, backfill."}
  - {sha: 0f41319ad6b0fd2cd943340f5cf2f3830b140dae, label: Phase 0 spec, kind: phase-start, phase: phase0, pr: 148, summary: "Six items and ADR 0004."}
  - {sha: 58bfba1e856e7db973b62a7e3c32b7e7bb40a97f, label: Credentials redacted, kind: incident, phase: phase0, pr: 154, summary: "Provider credentials no longer logged at INFO; regression guard in hook and CI."}
  - {sha: 75a68555b931e7d088bfbbd859b35e6e27064312, label: Phase 0 done, kind: phase-done, phase: phase0, pr: 155, summary: "All six items merged; the ruleset requires four result aggregates."}
```

- [ ] **Step 3: Write the defect ledger**

Before writing `pinned` entries, confirm each `test` path by grep, e.g.
`grep -ln '#82' e2e/tests/seeded/hdhr.spec.ts` — if a grep finds nothing, set that entry to
`open` with `source` instead. `metrics/curated/defects.yml`:

```yaml
# Known-defect ledger, one entry per item in CLAUDE.md "Known defects and traps".
# Status moves forward only: open -> pinned -> fixed, or open -> carried (-> fixed).
# Contract: docs/agents/metrics.md.
- {id: credentials-logged-at-info, title: "Provider credentials logged at INFO at five sites", area: security, severity: critical, status: fixed, source: "CLAUDE.md#known-defects-and-traps", issue: 89, test: null, fixed_in: 154, carried_as: null, first_seen: 2026-08-22, status_changed: 2026-09-03}
- {id: postgres-published-all-interfaces, title: "docker-compose.yml publishes Postgres on 5436:5432 as dispatch/secret", area: security, severity: high, status: carried, source: "CLAUDE.md#known-defects-and-traps", issue: null, test: null, fixed_in: null, carried_as: "docs/superpowers/specs/2026-09-03-phase0-harden-in-place-design.md#carried-not-fixed", first_seen: 2026-08-22, status_changed: 2026-09-03}
- {id: wildcard-hosts-cors-csrf, title: "ALLOWED_HOSTS=*, CORS_ALLOW_ALL_ORIGINS, CSRF_TRUSTED_ORIGINS wildcards unconditioned on DEBUG", area: security, severity: high, status: carried, source: "CLAUDE.md#known-defects-and-traps", issue: null, test: null, fixed_in: null, carried_as: "docs/superpowers/specs/2026-09-03-phase0-harden-in-place-design.md#carried-not-fixed", first_seen: 2026-08-22, status_changed: 2026-09-03}
- {id: xc-password-plaintext, title: "Xtream passwords plaintext in custom_properties, compared with !=; API keys looked up by plaintext value", area: security, severity: high, status: carried, source: "CLAUDE.md#known-defects-and-traps", issue: null, test: null, fixed_in: null, carried_as: "docs/superpowers/specs/2026-09-03-phase0-harden-in-place-design.md#carried-not-fixed", first_seen: 2026-08-22, status_changed: 2026-09-03}
- {id: stream-endpoint-allowany, title: "stream_ts is AllowAny gated only by a 0.0.0.0/0 STREAMS ACL; channel UUID is the secret", area: security, severity: medium, status: carried, source: "CLAUDE.md#auth--two-opposite-defaults", issue: null, test: null, fixed_in: null, carried_as: "docs/superpowers/specs/2026-09-03-phase0-harden-in-place-design.md#carried-not-fixed", first_seen: 2026-08-22, status_changed: 2026-09-03}
- {id: no-harakiri-no-drain, title: "die-on-term with no drain; no harakiri possible while the relay shares a process with the API", area: operational, severity: medium, status: carried, source: "CLAUDE.md#known-defects-and-traps", issue: null, test: null, fixed_in: null, carried_as: "docs/superpowers/specs/2026-09-03-phase0-harden-in-place-design.md#carried-not-fixed", first_seen: 2026-08-22, status_changed: 2026-09-03}
- {id: unfenced-ownership-lease, title: "Ownership lease is time-bounded, not fenced; add_chunk has no fencing token and the lease fails open", area: correctness, severity: high, status: open, source: "CLAUDE.md#known-defects-and-traps", issue: null, test: null, fixed_in: null, carried_as: null, first_seen: 2026-08-22, status_changed: 2026-08-22}
- {id: preemption-dead-code, title: "Channel preemption is dead code: _pick_channel_to_preempt exists, the return is commented out", area: dead-code, severity: low, status: open, source: "CLAUDE.md#known-defects-and-traps", issue: null, test: null, fixed_in: null, carried_as: null, first_seen: 2026-08-22, status_changed: 2026-08-22}
- {id: preferred-region-dead-read, title: "preferred-region read can never succeed at three sites; EPG matching runs with no regional weighting", area: correctness, severity: medium, status: open, source: "CLAUDE.md#known-defects-and-traps", issue: 140, test: null, fixed_in: null, carried_as: null, first_seen: 2026-08-22, status_changed: 2026-08-22}
- {id: scheduler-migration-reverses-broken, title: "epg/0007 and m3u/0006 reverse migrations are broken; 16 migrations have no reverse", area: correctness, severity: medium, status: open, source: "CLAUDE.md#known-defects-and-traps", issue: null, test: null, fixed_in: null, carried_as: null, first_seen: 2026-08-22, status_changed: 2026-08-22}
- {id: output-user-level-exact, title: "Channel-authorization filter uses user_level exactly instead of __lte in XC live categories", area: correctness, severity: medium, status: pinned, source: null, issue: 85, test: e2e/tests/seeded/xc-live.spec.ts, fixed_in: null, carried_as: null, first_seen: 2026-08-22, status_changed: 2026-08-30}
- {id: hidden-channel-streamable, title: "hide_adult_content not applied in live_proxy or timeshift views: unlistable channels are streamable", area: correctness, severity: medium, status: pinned, source: null, issue: 87, test: e2e/tests/streaming/hidden-channel-streamable.spec.ts, fixed_in: null, carried_as: null, first_seen: 2026-08-22, status_changed: 2026-08-28}
- {id: hidden-catchup-streamable, title: "hide_adult_content not applied on the catch-up path", area: correctness, severity: medium, status: pinned, source: null, issue: 95, test: e2e/tests/streaming/catchup-proxy-mode.spec.ts, fixed_in: null, carried_as: null, first_seen: 2026-08-30, status_changed: 2026-09-01}
- {id: hdhr-no-authorization, title: "HDHomeRun endpoints are AllowAny and never resolve a user", area: security, severity: medium, status: pinned, source: null, issue: 82, test: e2e/tests/seeded/hdhr.spec.ts, fixed_in: null, carried_as: null, first_seen: 2026-08-22, status_changed: 2026-08-30}
- {id: xc-account-enumeration, title: "player_api.php distinguishes an unknown username (404) from a wrong password (401)", area: security, severity: medium, status: pinned, source: null, issue: 84, test: e2e/tests/seeded/xc-auth.spec.ts, fixed_in: null, carried_as: null, first_seen: 2026-08-30, status_changed: 2026-08-30}
- {id: m3u-unescaped-quote, title: "Unescaped double quote in tvg-name/group-title breaks the EXTINF line", area: correctness, severity: medium, status: pinned, source: null, issue: 80, test: e2e/tests/seeded/output-m3u.spec.ts, fixed_in: null, carried_as: null, first_seen: 2026-08-30, status_changed: 2026-08-30}
- {id: channel-stopping-ttl-race, title: "Channel-stopping key written with 60s TTL on five paths and 30s on three", area: correctness, severity: medium, status: open, source: "CLAUDE.md#known-defects-and-traps", issue: null, test: null, fixed_in: null, carried_as: null, first_seen: 2026-08-22, status_changed: 2026-08-22}
- {id: max-stream-switches-unbounded, title: "MAX_STREAM_SWITCHES does not bound buffering-triggered switches", area: correctness, severity: medium, status: open, source: "CLAUDE.md#known-defects-and-traps", issue: null, test: null, fixed_in: null, carried_as: null, first_seen: 2026-08-22, status_changed: 2026-08-22}
- {id: fmp4-timeout-no-switch-exemption, title: "fMP4 generator's _is_timeout lacks the TS generator's url_switching exemption", area: correctness, severity: medium, status: open, source: "CLAUDE.md#known-defects-and-traps", issue: null, test: null, fixed_in: null, carried_as: null, first_seen: 2026-08-22, status_changed: 2026-08-22}
- {id: read-only-fields-misplaced, title: "read_only_fields on the serializer class instead of Meta: M3UAccount.locked is writable over the API", area: correctness, severity: low, status: open, source: null, issue: 15, test: null, fixed_in: null, carried_as: null, first_seen: 2026-08-24, status_changed: 2026-08-24}
- {id: interval-schedule-create-race, title: "M3U/EPG source creation 500s permanently after a concurrent-create race duplicates an IntervalSchedule", area: correctness, severity: high, status: open, source: null, issue: 7, test: null, fixed_in: null, carried_as: null, first_seen: 2026-08-24, status_changed: 2026-08-24}
- {id: hls-proxy-dead, title: "apps/proxy/hls_proxy (1,206 lines) is dead: no HLS output exists", area: dead-code, severity: low, status: open, source: "CLAUDE.md#known-defects-and-traps", issue: null, test: null, fixed_in: null, carried_as: null, first_seen: 2026-08-22, status_changed: 2026-08-22}
- {id: persistent-lock-dead, title: "dispatcharr/persistent_lock.py has no callers and a broken refresh()", area: dead-code, severity: low, status: open, source: "CLAUDE.md#known-defects-and-traps", issue: null, test: null, fixed_in: null, carried_as: null, first_seen: 2026-08-22, status_changed: 2026-08-22}
- {id: ffmpeg-survives-worker-death, title: "posix_spawn with no setsid/PDEATHSIG: a blocked ffmpeg survives worker death holding a provider slot", area: operational, severity: medium, status: open, source: "CLAUDE.md#known-defects-and-traps", issue: null, test: null, fixed_in: null, carried_as: null, first_seen: 2026-08-22, status_changed: 2026-08-22}
- {id: no-health-or-metrics, title: "No /healthz, readiness probe, metrics or structured logs", area: operational, severity: medium, status: open, source: "CLAUDE.md#known-defects-and-traps", issue: null, test: null, fixed_in: null, carried_as: null, first_seen: 2026-08-22, status_changed: 2026-08-22}
```

`#carried-not-fixed` is the slug of the Phase 0 spec's "Carried, not fixed" heading.

- [ ] **Step 4: Write the test that validates the real files against the real repo**

`metrics/build/tests/test_real_curated.py`:

```python
"""The committed curated files must validate against the committed repo.

Runs offline (no PR checks) so it works in the hook; the Pages build runs the
same validator online.
"""
import json
import subprocess
import unittest
from pathlib import Path

from curated import load_curated, validate

ROOT = Path(__file__).resolve().parents[3]
BASE = "fd413f0cc4ab3131789a68fb31f1ae622ae7371a"


def latest_family_pointers() -> dict[str, set[str]]:
    """Pointers present in the newest row of each family on origin/metrics-data, if fetched."""
    out: dict[str, set[str]] = {}
    for family in ("code_health", "architecture", "tests", "coverage"):
        r = subprocess.run(["git", "-C", str(ROOT), "show", f"origin/metrics-data:{family}.jsonl"], capture_output=True, text=True)
        if r.returncode != 0 or not r.stdout.strip():
            continue
        row = json.loads(r.stdout.strip().splitlines()[-1])
        out[family] = set(_pointers(row["metrics"]))
    return out


def _pointers(obj, prefix=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _pointers(v, f"{prefix}/{k}")
    else:
        yield prefix


class RealCuratedFilesTests(unittest.TestCase):
    def test_committed_files_validate(self):
        c = load_curated(ROOT / "metrics" / "curated")
        ref = "origin/main" if subprocess.run(["git", "-C", str(ROOT), "rev-parse", "-q", "--verify", "origin/main"], capture_output=True).returncode == 0 else "main"
        families = latest_family_pointers() or None  # None when the data branch is not fetched: skip resolution checks
        errors = validate(c, repo=ROOT, base=BASE, ref=ref, pr_checker=None, known_families=families)
        self.assertEqual(errors, [], "\n".join(errors))

    def test_exactly_twenty_headlines_four_per_group(self):
        c = load_curated(ROOT / "metrics" / "curated")
        heads = [m for m in c.catalogue if m.headline]
        self.assertEqual(len(heads), 20)
        per_group = {}
        for m in heads:
            per_group[m.group] = per_group.get(m.group, 0) + 1
        self.assertEqual(set(per_group.values()), {4}, per_group)
```

Milestone SHAs are validated as first-parent commits on `main` since the baseline; the
`coverage` family has no row until the daily job has run once, and `known_families` only
constrains headline entries whose family **has** a row, so a not-yet-existing family is fine.

- [ ] **Step 5: Run, then fix whatever the validator reports**

Run: `git fetch origin metrics-data main && scripts/run_metrics_tests.sh build`
Expected: `OK`. Typical first-run failures: a `test` path that does not exist (change that
defect to `open` + `source`), a `pr` on a milestone that is not first-parent (re-check the
SHA with `git log --first-parent --format='%H %s' fd413f0c..main | grep '(#N)'`).

- [ ] **Step 6: Commit**

```bash
git add metrics/curated metrics/build/tests/test_real_curated.py
```
Commit message: `feat(metrics): seed the catalogue, milestones and defect ledger`.

### Task 11: Loaders for snapshot rows and event dumps

**Files:**
- Create: `metrics/build/load.py`
- Create: `metrics/build/tests/fixtures/data/` (tiny metrics-data tree, listed below)
- Create: `metrics/build/tests/test_load.py`

**Interfaces:**
- `load.SnapshotRow` dataclass: `timestamp: datetime` (UTC), `commit_sha: str`, `family: str`, `metrics: dict`.
- `load.load_snapshots(data_dir: Path) -> dict[str, list[SnapshotRow]]` — every `*.jsonl` at the
  top level except the retired three (`security`, `delivery`, `agentic`), sorted by timestamp.
- `load.Dump` dataclass: `kind`, `fetched_at: datetime | None`, `status: str`, `detail: str | None`, `records: list[dict]`.
- `load.load_events(data_dir: Path) -> dict[str, Dump]` — union of `events/<kind>.json` and
  `events/history/<kind>.jsonl` (current record wins); a kind with only a sidecar yields
  status `"history_only"`; a kind with neither is absent from the dict.
- `load.pointer(metrics: dict, ptr: str)` — JSON-pointer lookup (`/a/b`), `None` if missing.
- `load.parse_ts(s: str) -> datetime` — ISO-8601 with `Z` or offset, returned UTC-aware.

- [ ] **Step 1: Write the fixture data**

`metrics/build/tests/fixtures/data/tests.jsonl` (two rows):

```
{"commit_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "family": "tests", "metrics": {"backend_test_count": 1787, "e2e_scenario_count": 0, "coverage_md_rows": {"done": 0, "known_bug": 0, "todo": 0}}, "timestamp": "2026-08-19T22:13:45Z"}
{"commit_sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "family": "tests", "metrics": {"backend_test_count": 1860, "e2e_scenario_count": 249, "coverage_md_rows": {"done": 132, "known_bug": 27, "todo": 24}}, "timestamp": "2026-09-03T21:09:00+00:00"}
```

`metrics/build/tests/fixtures/data/coverage.jsonl` (one row):

```
{"commit_sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "family": "coverage", "metrics": {"backend_line_pct": 45.6, "backend_by_app": {"apps.proxy": 38.5}, "backend_status": "ok", "backend_failed_labels": [], "frontend_line_pct": 71.9, "frontend_status": "ok"}, "timestamp": "2026-09-05T06:30:00+00:00"}
```

`metrics/build/tests/fixtures/data/security.jsonl` — one retired row, any content, to prove
it is ignored:

```
{"commit_sha": "cccc", "family": "security", "metrics": {"codeql_open_by_severity": {"high": 1}}, "timestamp": "2026-08-29T08:56:20+00:00"}
```

`metrics/build/tests/fixtures/data/events/codeql_alerts.json`:

```json
{"kind": "codeql_alerts", "fetched_at": "2026-09-05T06:05:00+00:00", "repo": "o/r", "status": "ok", "detail": null, "records": [
 {"id": 1, "state": "open", "created_at": "2026-08-23T16:00:00Z", "fixed_at": null, "dismissed_at": null, "dismissed_reason": null, "rule_id": "py/full-ssrf", "severity": "critical", "tool": "CodeQL", "path": "a.py"},
 {"id": 2, "state": "fixed", "created_at": "2026-08-28T19:12:00Z", "fixed_at": "2026-09-03T21:11:00Z", "dismissed_at": null, "dismissed_reason": null, "rule_id": "py/clear-text-logging-sensitive-data", "severity": "high", "tool": "CodeQL", "path": "b.py"},
 {"id": 3, "state": "dismissed", "created_at": "2026-08-23T16:00:00Z", "fixed_at": null, "dismissed_at": "2026-08-30T00:00:00Z", "dismissed_reason": "false positive", "rule_id": "py/path-injection", "severity": "high", "tool": "CodeQL", "path": "c.py"},
 {"id": 4, "state": "open", "created_at": "2026-08-23T16:00:00Z", "fixed_at": null, "dismissed_at": null, "dismissed_reason": null, "rule_id": "PinnedDependenciesID", "severity": "medium", "tool": "Scorecard", "path": ".github/workflows/x.yml"}
]}
```

`metrics/build/tests/fixtures/data/events/history/codeql_alerts.jsonl` — one line that only
exists in history (an alert that left the API), plus a stale version of id 1 that the current
dump must override:

```
{"id": 9, "seen_at": "2026-08-25T06:00:00+00:00", "record": {"id": 9, "state": "open", "created_at": "2026-08-24T00:00:00Z", "fixed_at": null, "dismissed_at": null, "dismissed_reason": null, "rule_id": "js/insecure-randomness", "severity": "high", "tool": "CodeQL", "path": "d.js"}}
{"id": 1, "seen_at": "2026-08-25T06:00:00+00:00", "record": {"id": 1, "state": "open", "created_at": "2026-08-23T16:00:00Z", "fixed_at": null, "dismissed_at": null, "dismissed_reason": null, "rule_id": "py/full-ssrf", "severity": "high", "tool": "CodeQL", "path": "a.py"}}
```

`metrics/build/tests/fixtures/data/events/pull_requests.json`:

```json
{"kind": "pull_requests", "fetched_at": "2026-09-05T06:05:00+00:00", "repo": "o/r", "status": "ok", "detail": null, "records": [
 {"id": 5, "title": "G1", "created_at": "2026-08-24T10:00:00Z", "merged_at": "2026-08-25T10:00:00Z", "closed_at": "2026-08-25T10:00:00Z", "author": "d", "author_type": "User", "head_ref": "e2e/g1", "additions": 900, "deletions": 10, "changed_files": 3, "files": ["apps/x.py", "e2e/a.spec.ts", "docs/b.md"]},
 {"id": 6, "title": "fix", "created_at": "2026-09-01T00:00:00Z", "merged_at": "2026-09-01T02:00:00Z", "closed_at": "2026-09-01T02:00:00Z", "author": "github-actions[bot]", "author_type": "Bot", "head_ref": "agentics/issue-remediation-9", "additions": 100, "deletions": 0, "changed_files": 1, "files": ["apps/y.py"]},
 {"id": 7, "title": "open", "created_at": "2026-09-04T00:00:00Z", "merged_at": null, "closed_at": null, "author": "d", "author_type": "User", "head_ref": "wip", "additions": null, "deletions": null, "changed_files": null, "files": []}
]}
```

`metrics/build/tests/fixtures/data/events/workflow_runs.json`:

```json
{"kind": "workflow_runs", "fetched_at": "2026-09-05T06:05:00+00:00", "repo": "o/r", "status": "ok", "detail": null, "records": [
 {"id": 11, "workflow": "E2E Tests", "event": "push", "status": "completed", "conclusion": "success", "created_at": "2026-08-29T08:00:00Z", "updated_at": "2026-08-29T08:06:00Z", "run_started_at": "2026-08-29T08:00:00Z", "head_sha": "x"},
 {"id": 12, "workflow": "E2E Tests", "event": "push", "status": "completed", "conclusion": "failure", "created_at": "2026-09-01T08:00:00Z", "updated_at": "2026-09-01T08:10:00Z", "run_started_at": "2026-09-01T08:00:00Z", "head_sha": "y"},
 {"id": 13, "workflow": "E2E Tests", "event": "push", "status": "completed", "conclusion": "cancelled", "created_at": "2026-09-02T08:00:00Z", "updated_at": "2026-09-02T08:01:00Z", "run_started_at": "2026-09-02T08:00:00Z", "head_sha": "z"},
 {"id": 14, "workflow": "Metrics", "event": "schedule", "status": "completed", "conclusion": "failure", "created_at": "2026-09-02T06:00:00Z", "updated_at": "2026-09-02T06:01:00Z", "run_started_at": "2026-09-02T06:00:00Z", "head_sha": "z"}
]}
```

`metrics/build/tests/fixtures/data/events/issues.json`:

```json
{"kind": "issues", "fetched_at": "2026-09-05T06:05:00+00:00", "repo": "o/r", "status": "ok", "detail": null, "records": [
 {"id": 9, "title": "bug", "state": "open", "created_at": "2026-08-27T00:00:00Z", "closed_at": null, "updated_at": "2026-08-28T00:00:00Z", "labels": ["ready-for-agent"], "label_events": [
   {"event": "labeled", "label": "needs-triage", "at": "2026-08-27T00:00:01Z"},
   {"event": "unlabeled", "label": "needs-triage", "at": "2026-08-29T00:00:00Z"},
   {"event": "labeled", "label": "ready-for-agent", "at": "2026-08-29T00:00:00Z"}]},
 {"id": 10, "title": "bug2", "state": "open", "created_at": "2026-09-03T00:00:00Z", "closed_at": null, "updated_at": "2026-09-03T00:00:00Z", "labels": ["needs-triage"], "label_events": [
   {"event": "labeled", "label": "needs-triage", "at": "2026-09-03T00:00:01Z"}]}
]}
```

`metrics/build/tests/fixtures/data/events/scorecard.json`:

```json
{"kind": "scorecard", "fetched_at": "2026-09-05T06:05:00+00:00", "repo": "o/r", "status": "ok", "detail": null, "records": [
 {"id": "2026-09-03T21:24:00Z", "date": "2026-09-03T21:24:00Z", "score": 6.9, "commit": "x", "checks": {"Branch-Protection": 4, "Pinned-Dependencies": 9}}
]}
```

`metrics/build/tests/fixtures/data/events/dependabot_alerts.json`:

```json
{"kind": "dependabot_alerts", "fetched_at": "2026-09-05T06:05:00+00:00", "repo": "o/r", "status": "not_permitted", "detail": "HTTP 403", "records": []}
```

- [ ] **Step 2: Write the failing tests**

`metrics/build/tests/test_load.py`:

```python
import datetime as dt
import unittest
from pathlib import Path

from load import load_events, load_snapshots, parse_ts, pointer

DATA = Path(__file__).resolve().parent / "fixtures" / "data"


class LoadTests(unittest.TestCase):
    def test_snapshots_sorted_and_retired_families_ignored(self):
        fams = load_snapshots(DATA)
        self.assertEqual(set(fams), {"tests", "coverage"})
        self.assertEqual([r.commit_sha[:1] for r in fams["tests"]], ["a", "b"])
        self.assertEqual(fams["tests"][0].timestamp.tzinfo, dt.timezone.utc)

    def test_pointer(self):
        m = load_snapshots(DATA)["tests"][1].metrics
        self.assertEqual(pointer(m, "/coverage_md_rows/done"), 132)
        self.assertIsNone(pointer(m, "/nope"))
        self.assertIsNone(pointer(m, "/coverage_md_rows/nope"))

    def test_events_union_current_wins(self):
        dumps = load_events(DATA)
        alerts = {r["id"]: r for r in dumps["codeql_alerts"].records}
        self.assertEqual(alerts[1]["severity"], "critical", "current dump overrides the stale history line")
        self.assertIn(9, alerts, "history-only record retained")
        self.assertEqual(dumps["codeql_alerts"].status, "ok")
        self.assertEqual(dumps["dependabot_alerts"].status, "not_permitted")
        self.assertNotIn("secret_scanning", dumps)

    def test_parse_ts(self):
        self.assertEqual(parse_ts("2026-08-23T16:00:00Z").tzinfo, dt.timezone.utc)
        self.assertEqual(parse_ts("2026-08-23T18:00:00+02:00").hour, 16)
```

Run: `scripts/run_metrics_tests.sh build` → import error for `load`.

- [ ] **Step 3: Write `load.py`**

```python
"""Read the metrics-data branch: snapshot rows and event dumps."""

from __future__ import annotations

import dataclasses as dc
import datetime as dt
import json
from pathlib import Path

RETIRED_FAMILIES = {"security", "delivery", "agentic"}


def parse_ts(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(dt.timezone.utc)


@dc.dataclass
class SnapshotRow:
    timestamp: dt.datetime
    commit_sha: str
    family: str
    metrics: dict


@dc.dataclass
class Dump:
    kind: str
    fetched_at: dt.datetime | None
    status: str
    detail: str | None
    records: list[dict]


def load_snapshots(data_dir: Path) -> dict[str, list[SnapshotRow]]:
    out: dict[str, list[SnapshotRow]] = {}
    for path in sorted(data_dir.glob("*.jsonl")):
        family = path.stem
        if family in RETIRED_FAMILIES:
            continue
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            raw = json.loads(line)
            rows.append(SnapshotRow(parse_ts(raw["timestamp"]), raw["commit_sha"], raw.get("family", family), raw["metrics"]))
        rows.sort(key=lambda r: r.timestamp)
        out[family] = rows
    return out


def load_events(data_dir: Path) -> dict[str, Dump]:
    events_dir = data_dir / "events"
    history_dir = events_dir / "history"
    kinds = {p.stem for p in events_dir.glob("*.json")} | {p.stem for p in history_dir.glob("*.jsonl")}
    out: dict[str, Dump] = {}
    for kind in sorted(kinds):
        merged: dict[str, dict] = {}
        sidecar = history_dir / f"{kind}.jsonl"
        if sidecar.is_file():
            for line in sidecar.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    merged[str(row["id"])] = row["record"]
        current = events_dir / f"{kind}.json"
        if current.is_file():
            env = json.loads(current.read_text(encoding="utf-8"))
            for rec in env.get("records", []):
                merged[str(rec["id"])] = rec
            out[kind] = Dump(kind, parse_ts(env["fetched_at"]) if env.get("fetched_at") else None,
                             env.get("status", "ok"), env.get("detail"), list(merged.values()))
        else:
            out[kind] = Dump(kind, None, "history_only", None, list(merged.values()))
    return out


def pointer(metrics: dict, ptr: str):
    node = metrics
    for part in ptr.strip("/").split("/"):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node
```

- [ ] **Step 4: Run to verify they pass**

Run: `scripts/run_metrics_tests.sh build` → `OK`.

- [ ] **Step 5: Commit**

```bash
git add metrics/build/load.py metrics/build/tests/fixtures/data metrics/build/tests/test_load.py
```
Commit message: `feat(metrics): loaders for snapshot rows and event dumps with history sidecars`.

### Task 12: Derivations

**Files:**
- Create: `metrics/build/derive.py`
- Create: `metrics/build/tests/test_derive.py`
- Modify: `metrics/build/curated.py` (`DERIVATIONS` now imported from `derive`)

**Interfaces:**
- Every derivation has the signature `fn(ctx: Context, day: date, params: dict) -> float | None`.
  `Context` is a dataclass: `events: dict[str, Dump]`, `defects: list[Defect]`.
- `derive.DERIVATIONS: dict[str, Callable]` maps the thirteen names to functions.
- Trailing windows are `(day - 30 days, day]`; "as of day" means at 23:59:59 UTC on that day.

- [ ] **Step 1: Write the failing tests**

`metrics/build/tests/test_derive.py`:

```python
import datetime as dt
import unittest
from pathlib import Path

from curated import Defect
from derive import DERIVATIONS, Context
from load import load_events

DATA = Path(__file__).resolve().parent / "fixtures" / "data"
D = dt.date


def ctx():
    defects = [
        Defect(id="a", title="a", area="correctness", severity="high", status="pinned", first_seen=D(2026, 8, 22), status_changed=D(2026, 8, 30), issue=1, test="x"),
        Defect(id="b", title="b", area="security", severity="high", status="fixed", first_seen=D(2026, 8, 22), status_changed=D(2026, 9, 3), fixed_in=154),
        Defect(id="c", title="c", area="security", severity="low", status="open", first_seen=D(2026, 8, 22), status_changed=D(2026, 8, 22), source="s"),
    ]
    return Context(events=load_events(DATA), defects=defects)


class DeriveTests(unittest.TestCase):
    def setUp(self):
        self.c = ctx()

    def d(self, name, day, **params):
        return DERIVATIONS[name](self.c, day, params)

    def test_codeql_open_count_as_of_dates(self):
        # ids 1,3,9 open on Aug 24 (2 created Aug 28); id 3 dismissed Aug 30; id 2 fixed Sep 3
        self.assertEqual(self.d("codeql_open_count", D(2026, 8, 22), severities=["critical", "high"]), 0)
        self.assertEqual(self.d("codeql_open_count", D(2026, 8, 24), severities=["critical", "high"]), 3)
        self.assertEqual(self.d("codeql_open_count", D(2026, 8, 29), severities=["critical", "high"]), 4)
        self.assertEqual(self.d("codeql_open_count", D(2026, 8, 31), severities=["critical", "high"]), 3)
        self.assertEqual(self.d("codeql_open_count", D(2026, 9, 4), severities=["critical", "high"]), 2)
        self.assertEqual(self.d("codeql_open_count", D(2026, 9, 4), tools=["Scorecard"]), 1)

    def test_codeql_oldest_open_age(self):
        self.assertEqual(self.d("codeql_oldest_open_age_days", D(2026, 9, 4), severities=["critical", "high"]), 12)
        self.assertIsNone(self.d("codeql_oldest_open_age_days", D(2026, 8, 22), severities=["critical"]))

    def test_codeql_fixed_per_week(self):
        self.assertEqual(self.d("codeql_fixed_per_week", D(2026, 9, 4)), 1)
        self.assertEqual(self.d("codeql_fixed_per_week", D(2026, 9, 12)), 0)

    def test_scorecard(self):
        self.assertEqual(self.d("scorecard_score", D(2026, 9, 4)), 6.9)
        self.assertIsNone(self.d("scorecard_score", D(2026, 9, 1)))
        self.assertEqual(self.d("scorecard_check", D(2026, 9, 4), name="Branch-Protection"), 4)

    def test_ci_pass_rate_ignores_cancelled(self):
        self.assertAlmostEqual(self.d("ci_pass_rate_30d", D(2026, 9, 4), workflows=["E2E Tests"]), 0.5)
        self.assertAlmostEqual(self.d("ci_pass_rate_30d", D(2026, 9, 4), workflows=[]), 1 / 3)
        self.assertIsNone(self.d("ci_pass_rate_30d", D(2026, 8, 20), workflows=["E2E Tests"]))

    def test_ci_median_wall_time(self):
        self.assertEqual(self.d("ci_median_wall_time_30d", D(2026, 9, 4), workflow="E2E Tests"), 480.0)

    def test_pr_lead_time_and_counts(self):
        self.assertEqual(self.d("pr_lead_time_30d", D(2026, 9, 4), quantile=0.5, author_type="all"), (86400 + 7200) / 2)
        self.assertEqual(self.d("pr_lead_time_30d", D(2026, 9, 4), quantile=0.5, author_type="agent"), 7200)
        self.assertEqual(self.d("prs_merged_30d", D(2026, 9, 4), author_type="agent"), 1)
        self.assertEqual(self.d("prs_merged_30d", D(2026, 9, 4), author_type="human"), 1)
        self.assertEqual(self.d("prs_merged_30d", D(2026, 8, 24), author_type="all"), 0)

    def test_pr_product_ratio(self):
        # PR5: 910 lines, 1 of 3 files under apps/ -> 303.3 product lines; PR6: 100 lines all apps/
        self.assertAlmostEqual(self.d("pr_product_ratio_30d", D(2026, 9, 4)), (910 / 3 + 100) / 1010, places=4)

    def test_issue_labels_as_of(self):
        self.assertEqual(self.d("issues_open_by_label", D(2026, 8, 28), label="needs-triage"), 1)
        self.assertEqual(self.d("issues_open_by_label", D(2026, 8, 30), label="needs-triage"), 0)
        self.assertEqual(self.d("issues_open_by_label", D(2026, 9, 4), label="needs-triage"), 1)
        self.assertEqual(self.d("issues_time_to_triage_median_30d", D(2026, 9, 4)), 2 * 86400)

    def test_defects_by_status(self):
        self.assertEqual(self.d("defects_by_status", D(2026, 9, 4), status="fixed"), 1)
        self.assertEqual(self.d("defects_by_status", D(2026, 9, 1), status="fixed"), 0)
        self.assertEqual(self.d("defects_by_status", D(2026, 9, 1), status="open"), 2, "b was open before it was fixed")
        self.assertEqual(self.d("defects_by_status", D(2026, 8, 21), status="open"), 0)
```

Run: `scripts/run_metrics_tests.sh build` → import error for `derive`.

- [ ] **Step 2: Write `derive.py`**

```python
"""Every derived series, as pure functions of (events, defects, day, params).

"As of day D" means at the last second of D (UTC). Trailing windows are
(D - N days, D]. Each function returns a number or None when there is no
data to speak of — None is a gap on the chart, never a zero.
"""

from __future__ import annotations

import dataclasses as dc
import datetime as dt
import statistics
from typing import Callable

from curated import Defect
from load import Dump, parse_ts

AGENT_BRANCH_MARKERS = ("copilot/", "agentics/", "remediation")


@dc.dataclass
class Context:
    events: dict[str, Dump]
    defects: list[Defect]

    def records(self, kind: str) -> list[dict]:
        dump = self.events.get(kind)
        return dump.records if dump else []


def end_of(day: dt.date) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(23, 59, 59), tzinfo=dt.timezone.utc)


def window(day: dt.date, days: int) -> tuple[dt.datetime, dt.datetime]:
    end = end_of(day)
    return end - dt.timedelta(days=days), end


def _ts(value) -> dt.datetime | None:
    return parse_ts(value) if value else None


def _quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    if q == 0.5:
        return statistics.median(values)
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))
    return ordered[idx]


# ------------------------------------------------------------------ CodeQL ---

def _alert_open_at(a: dict, at: dt.datetime) -> bool:
    created = _ts(a.get("created_at"))
    if created is None or created > at:
        return False
    for key in ("fixed_at", "dismissed_at"):
        t = _ts(a.get(key))
        if t is not None and t <= at:
            return False
    return True


def _alerts(ctx: Context, params: dict) -> list[dict]:
    tools = params.get("tools") or ["CodeQL"]
    sev = params.get("severities")
    return [a for a in ctx.records("codeql_alerts")
            if a.get("tool") in tools and (sev is None or a.get("severity") in sev)]


def codeql_open_count(ctx: Context, day: dt.date, params: dict):
    at = end_of(day)
    return sum(1 for a in _alerts(ctx, params) if _alert_open_at(a, at))


def codeql_oldest_open_age_days(ctx: Context, day: dt.date, params: dict):
    at = end_of(day)
    created = [_ts(a["created_at"]) for a in _alerts(ctx, params) if _alert_open_at(a, at)]
    if not created:
        return None
    return (at - min(created)).days


def codeql_fixed_per_week(ctx: Context, day: dt.date, params: dict):
    start, end = window(day, 7)
    return sum(1 for a in _alerts(ctx, params)
               if (t := _ts(a.get("fixed_at"))) is not None and start < t <= end)


# --------------------------------------------------------------- Scorecard ---

def _scorecard_at(ctx: Context, day: dt.date) -> dict | None:
    at = end_of(day)
    recs = [r for r in ctx.records("scorecard") if (t := _ts(r.get("date"))) is not None and t <= at]
    return max(recs, key=lambda r: r["date"]) if recs else None


def scorecard_score(ctx: Context, day: dt.date, params: dict):
    rec = _scorecard_at(ctx, day)
    return rec.get("score") if rec else None


def scorecard_check(ctx: Context, day: dt.date, params: dict):
    rec = _scorecard_at(ctx, day)
    if not rec:
        return None
    score = (rec.get("checks") or {}).get(params["name"])
    return None if score is None or score < 0 else score


# ---------------------------------------------------------------------- CI ---

def _verdict_runs(ctx: Context, day: dt.date, workflows: list[str]) -> list[dict]:
    start, end = window(day, 30)
    out = []
    for r in ctx.records("workflow_runs"):
        if workflows and r.get("workflow") not in workflows:
            continue
        if r.get("status") != "completed" or r.get("conclusion") not in ("success", "failure"):
            continue
        t = _ts(r.get("created_at"))
        if t is not None and start < t <= end:
            out.append(r)
    return out


def ci_pass_rate_30d(ctx: Context, day: dt.date, params: dict):
    runs = _verdict_runs(ctx, day, params.get("workflows") or [])
    if not runs:
        return None
    return sum(1 for r in runs if r["conclusion"] == "success") / len(runs)


def ci_median_wall_time_30d(ctx: Context, day: dt.date, params: dict):
    runs = _verdict_runs(ctx, day, [params["workflow"]])
    durations = [(_ts(r["updated_at"]) - _ts(r["run_started_at"])).total_seconds()
                 for r in runs if r.get("updated_at") and r.get("run_started_at")]
    return statistics.median(durations) if durations else None


# ---------------------------------------------------------------------- PRs ---

def _is_agent(pr: dict) -> bool:
    if (pr.get("author_type") or "").lower() == "bot":
        return True
    ref = pr.get("head_ref") or ""
    return ref.startswith(AGENT_BRANCH_MARKERS[:2]) or AGENT_BRANCH_MARKERS[2] in ref


def _merged_prs(ctx: Context, day: dt.date, author_type: str) -> list[dict]:
    start, end = window(day, 30)
    out = []
    for pr in ctx.records("pull_requests"):
        t = _ts(pr.get("merged_at"))
        if t is None or not (start < t <= end):
            continue
        agent = _is_agent(pr)
        if author_type == "agent" and not agent or author_type == "human" and agent:
            continue
        out.append(pr)
    return out


def pr_lead_time_30d(ctx: Context, day: dt.date, params: dict):
    prs = _merged_prs(ctx, day, params.get("author_type", "all"))
    leads = [(_ts(p["merged_at"]) - _ts(p["created_at"])).total_seconds() for p in prs if p.get("created_at")]
    return _quantile(leads, float(params.get("quantile", 0.5)))


def prs_merged_30d(ctx: Context, day: dt.date, params: dict):
    return len(_merged_prs(ctx, day, params.get("author_type", "all")))


def pr_product_ratio_30d(ctx: Context, day: dt.date, params: dict):
    product = total = 0.0
    for pr in _merged_prs(ctx, day, "all"):
        lines = (pr.get("additions") or 0) + (pr.get("deletions") or 0)
        files = pr.get("files") or []
        if not lines or not files:
            continue
        share = sum(1 for f in files if f.startswith("apps/")) / len(files)
        product += lines * share
        total += lines
    return product / total if total else None


# ------------------------------------------------------------------- issues ---

def _labels_at(issue: dict, at: dt.datetime) -> set[str]:
    labels: set[str] = set()
    events = sorted(issue.get("label_events") or [], key=lambda e: e["at"])
    if not events:
        return set(issue.get("labels") or [])
    for e in events:
        t = _ts(e["at"])
        if t is None or t > at:
            break
        if e["event"] == "labeled":
            labels.add(e["label"])
        else:
            labels.discard(e["label"])
    return labels


def issues_open_by_label(ctx: Context, day: dt.date, params: dict):
    at = end_of(day)
    label = params["label"]
    count = 0
    for issue in ctx.records("issues"):
        created = _ts(issue.get("created_at"))
        closed = _ts(issue.get("closed_at"))
        if created is None or created > at or (closed is not None and closed <= at):
            continue
        if label in _labels_at(issue, at):
            count += 1
    return count


def issues_time_to_triage_median_30d(ctx: Context, day: dt.date, params: dict):
    start, end = window(day, 30)
    samples = []
    for issue in ctx.records("issues"):
        created = _ts(issue.get("created_at"))
        removed = next((_ts(e["at"]) for e in sorted(issue.get("label_events") or [], key=lambda e: e["at"])
                        if e["event"] == "unlabeled" and e["label"] == "needs-triage"), None)
        if created and removed and start < removed <= end:
            samples.append((removed - created).total_seconds())
    return statistics.median(samples) if samples else None


# ------------------------------------------------------------------ defects ---

def defects_by_status(ctx: Context, day: dt.date, params: dict):
    wanted = params["status"]
    count = 0
    for d in ctx.defects:
        if day < d.first_seen:
            continue
        status = d.status if day >= d.status_changed else "open"
        if status == wanted:
            count += 1
    return count


DERIVATIONS: dict[str, Callable[[Context, dt.date, dict], float | None]] = {
    "codeql_open_count": codeql_open_count,
    "codeql_oldest_open_age_days": codeql_oldest_open_age_days,
    "codeql_fixed_per_week": codeql_fixed_per_week,
    "scorecard_score": scorecard_score,
    "scorecard_check": scorecard_check,
    "ci_pass_rate_30d": ci_pass_rate_30d,
    "ci_median_wall_time_30d": ci_median_wall_time_30d,
    "pr_lead_time_30d": pr_lead_time_30d,
    "prs_merged_30d": prs_merged_30d,
    "pr_product_ratio_30d": pr_product_ratio_30d,
    "issues_open_by_label": issues_open_by_label,
    "issues_time_to_triage_median_30d": issues_time_to_triage_median_30d,
    "defects_by_status": defects_by_status,
}
```

- [ ] **Step 3: Point `curated.DERIVATIONS` at the real registry**

In `curated.py` replace the literal `DERIVATIONS = {...}` with a lazy lookup to avoid an
import cycle (`derive` imports `Defect` from `curated`):

```python
def known_derivations() -> set[str]:
    from derive import DERIVATIONS  # local import: derive imports Defect from this module
    return set(DERIVATIONS)
```

and in `validate` use `if m.derivation not in known_derivations():`.

- [ ] **Step 4: Run to verify they pass**

Run: `scripts/run_metrics_tests.sh build` → `OK` (`test_curated` still passes with the lazy
lookup).

- [ ] **Step 5: Commit**

```bash
git add metrics/build/derive.py metrics/build/curated.py metrics/build/tests/test_derive.py
```
Commit message: `feat(metrics): thirteen pure derivations over event dumps and the defect ledger`.

### Task 13: Daily calendar, forward fill, status rule

**Files:**
- Create: `metrics/build/calendar.py`
- Create: `metrics/build/tests/test_calendar.py`

**Interfaces:**
- `calendar.daily_dates(start: date, end: date) -> list[date]` inclusive.
- `calendar.snapshot_series(rows: list[SnapshotRow], ptr: str) -> list[tuple[datetime, str, float]]`
  per-commit points `(timestamp, sha, value)`, skipping rows where the pointer is missing or
  non-numeric.
- `calendar.forward_fill(points: list[tuple[datetime, float]], dates: list[date]) -> list[float | None]`
  last value on or before each day's end, `None` before the first point.
- `calendar.status(direction, target, now, prev, stale) -> "good"|"bad"|"neutral"|"stale"`.
- `calendar.delta_is_good(direction, delta) -> bool | None`.
- `calendar.is_stale(last_real: datetime | None, today: date, max_age_days=2) -> bool`.

- [ ] **Step 1: Write the failing tests**

`metrics/build/tests/test_calendar.py`:

```python
import datetime as dt
import unittest

from calendar_ import daily_dates, delta_is_good, forward_fill, is_stale, snapshot_series, status
from load import SnapshotRow

UTC = dt.timezone.utc
D = dt.date


def ts(s):
    return dt.datetime.fromisoformat(s).replace(tzinfo=UTC)


class CalendarTests(unittest.TestCase):
    def test_daily_dates_inclusive(self):
        self.assertEqual(len(daily_dates(D(2026, 8, 30), D(2026, 9, 2))), 4)

    def test_snapshot_series_skips_missing(self):
        rows = [SnapshotRow(ts("2026-08-19T10:00"), "a" * 40, "tests", {"n": 1}),
                SnapshotRow(ts("2026-08-20T10:00"), "b" * 40, "tests", {"m": 2}),
                SnapshotRow(ts("2026-08-21T10:00"), "c" * 40, "tests", {"n": 3})]
        self.assertEqual([(s, v) for _, s, v in snapshot_series(rows, "/n")], [("a" * 40, 1), ("c" * 40, 3)])

    def test_forward_fill(self):
        pts = [(ts("2026-08-20T10:00"), 1.0), (ts("2026-08-22T23:00"), 2.0)]
        self.assertEqual(forward_fill(pts, daily_dates(D(2026, 8, 19), D(2026, 8, 23))), [None, 1.0, 1.0, 2.0, 2.0])

    def test_status_rule(self):
        self.assertEqual(status("down", 0, 0, 3, False), "good")        # at target
        self.assertEqual(status("down", 0, 2, 3, False), "good")        # moving toward
        self.assertEqual(status("down", 0, 4, 3, False), "bad")         # moving away
        self.assertEqual(status("down", 0, 3, 3, False), "bad")         # stalled, target unmet
        self.assertEqual(status("down", None, 3, 3, False), "neutral")  # stalled, no target
        self.assertEqual(status("up", 60, 45, 40, False), "good")
        self.assertEqual(status("up", 60, 61, 40, False), "good")
        self.assertEqual(status("zero", None, 1, 1, False), "bad")
        self.assertEqual(status("zero", None, 0, 1, False), "good")
        self.assertEqual(status("info", None, 5, 1, False), "neutral")
        self.assertEqual(status("down", 0, 2, None, False), "neutral")  # no previous point
        self.assertEqual(status("down", 0, 2, 3, True), "stale")
        self.assertEqual(status("down", 0, None, 3, False), "neutral")  # no current value

    def test_delta_is_good(self):
        self.assertTrue(delta_is_good("down", -2)); self.assertFalse(delta_is_good("down", 2))
        self.assertTrue(delta_is_good("up", 2)); self.assertTrue(delta_is_good("zero", -1))
        self.assertIsNone(delta_is_good("info", 2)); self.assertIsNone(delta_is_good("up", 0))

    def test_is_stale(self):
        self.assertFalse(is_stale(ts("2026-09-03T06:00"), D(2026, 9, 4)))
        self.assertTrue(is_stale(ts("2026-09-01T06:00"), D(2026, 9, 4)))
        self.assertTrue(is_stale(None, D(2026, 9, 4)))
```

The module is named `calendar_.py` (trailing underscore) because `calendar` is a stdlib
module and the test runner puts `metrics/build` first on `sys.path`. Update the File
Structure list accordingly.

Run: `scripts/run_metrics_tests.sh build` → import error for `calendar_`.

- [ ] **Step 2: Write `calendar_.py`**

```python
"""Daily resampling and the status rule (spec §6, stage 3 and the status rule)."""

from __future__ import annotations

import datetime as dt

from load import SnapshotRow, pointer

UTC = dt.timezone.utc


def daily_dates(start: dt.date, end: dt.date) -> list[dt.date]:
    return [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]


def snapshot_series(rows: list[SnapshotRow], ptr: str) -> list[tuple[dt.datetime, str, float]]:
    out = []
    for r in rows:
        v = pointer(r.metrics, ptr)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out.append((r.timestamp, r.commit_sha, float(v)))
    return out


def forward_fill(points: list[tuple[dt.datetime, float]], dates: list[dt.date]) -> list[float | None]:
    pts = sorted(points, key=lambda p: p[0])
    out: list[float | None] = []
    i = 0
    last: float | None = None
    for day in dates:
        end = dt.datetime.combine(day, dt.time(23, 59, 59), tzinfo=UTC)
        while i < len(pts) and pts[i][0] <= end:
            last = pts[i][1]
            i += 1
        out.append(last)
    return out


def _at_target(direction: str, target: float | None, value: float) -> bool:
    if direction == "zero":
        return value == 0
    if target is None:
        return False
    return value <= target if direction == "down" else value >= target


def status(direction: str, target: float | None, now: float | None, prev: float | None, stale: bool) -> str:
    if stale:
        return "stale"
    if direction == "info" or now is None:
        return "neutral"
    if _at_target(direction, target, now):
        return "good"
    if prev is None:
        return "neutral"
    toward = now < prev if direction in ("down", "zero") else now > prev
    away = now > prev if direction in ("down", "zero") else now < prev
    if toward:
        return "good"
    if away:
        return "bad"
    return "bad" if (target is not None or direction == "zero") else "neutral"


def delta_is_good(direction: str, delta: float) -> bool | None:
    if direction == "info" or delta == 0:
        return None
    return delta < 0 if direction in ("down", "zero") else delta > 0


def is_stale(last_real: dt.datetime | None, today: dt.date, max_age_days: int = 2) -> bool:
    if last_real is None:
        return True
    return (today - last_real.date()).days > max_age_days
```

- [ ] **Step 3: Run to verify they pass**

Run: `scripts/run_metrics_tests.sh build` → `OK`.

- [ ] **Step 4: Commit**

```bash
git add metrics/build/calendar_.py metrics/build/tests/test_calendar.py
```
Commit message: `feat(metrics): daily resampling, forward fill and the status rule`.

### Task 14: Assemble `site.json`; the CLI

**Files:**
- Create: `metrics/build/assemble.py`
- Create: `metrics/build/__main__.py`
- Create: `metrics/build/tests/test_site.py`

**Interfaces:**
- `site.build_site(data_dir: Path, curated: Curated, *, repo: Path, base: str, today: date, ref="main") -> dict`
  returns the `site.json` document (spec §6 stage 4). Sections: `meta`, `headline`, `groups`,
  `phases`, `milestones`, `defects`, `compare`.
- Series shape inside `groups`: `{"id", "label", "unit", "direction", "target", "group", "headline", "note",
  "daily": [[iso_date, value|null], ...], "commits": [[sha, iso_datetime, value], ...] | null,
  "last_real": iso_datetime|null, "stale": bool, "status": str, "now": value|null,
  "at_baseline": value|null, "at_prev_milestone": value|null}`.
- Headline shape: the same object plus `"spark": [30 values|null]`.
- `compare` keys: `"<sha_a>..<sha_b>"` for each adjacent pair of milestones **and** the pair
  `(baseline, latest)`; each value a list of `{"id", "group", "label", "unit", "direction", "from", "to", "delta", "good"}`.
- CLI: `python -m metrics.build --data DIR --curated DIR --out FILE [--repo PATH] [--base SHA] [--ref REF] [--today YYYY-MM-DD] [--check-prs]`
  and `python -m metrics.build --validate-only --curated DIR [--check-prs]`. Exit 0/1.

- [ ] **Step 1: Write the failing end-to-end test**

`metrics/build/tests/test_site.py`:

```python
import datetime as dt
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from assemble import build_site
from curated import load_curated

HERE = Path(__file__).resolve().parent
DATA = HERE / "fixtures" / "data"
CUR = HERE / "fixtures" / "curated" / "valid"
D = dt.date


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                          check=True, capture_output=True, text=True).stdout.strip()


class SiteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.repo = self.tmp / "repo"; self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "base", "--date", "2026-08-19T22:13:45+00:00"); self.base = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "second", "--date", "2026-09-03T21:09:00+00:00"); self.second = git(self.repo, "rev-parse", "HEAD")
        (self.repo / "e2e/tests/seeded").mkdir(parents=True); (self.repo / "e2e/tests/seeded/output-m3u.spec.ts").write_text("")
        self.cur = self.tmp / "curated"; shutil.copytree(CUR, self.cur)
        (self.cur / "milestones.yml").write_text((self.cur / "milestones.yml").read_text().replace("BASE", self.base).replace("SECOND", self.second))
        # The fixture data rows use aaaa.../bbbb... SHAs; rewrite them to the repo's so milestones line up.
        self.data = self.tmp / "data"; shutil.copytree(DATA, self.data)
        for f in ("tests.jsonl", "coverage.jsonl"):
            p = self.data / f
            p.write_text(p.read_text().replace("a" * 40, self.base).replace("b" * 40, self.second))
        self.curated = load_curated(self.cur)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def build(self, today=D(2026, 9, 5)):
        return build_site(self.data, self.curated, repo=self.repo, base=self.base, today=today)

    def test_meta_and_freshness(self):
        s = self.build()
        self.assertEqual(s["meta"]["baseline"]["sha"], self.base)
        self.assertEqual(s["meta"]["baseline"]["date"], "2026-08-19")
        self.assertIn("tests", s["meta"]["freshness"])
        self.assertTrue(any("dependabot" in n for n in s["meta"]["source_notes"]))

    def test_headline_tiles(self):
        s = self.build()
        by_id = {h["id"]: h for h in s["headline"]}
        e2e = by_id["e2e_scenarios"]
        self.assertEqual(e2e["now"], 249); self.assertEqual(e2e["at_baseline"], 0)
        self.assertEqual(len(e2e["spark"]), 30)
        self.assertEqual(e2e["status"], "good")
        cq = by_id["codeql_open_critical_high"]
        self.assertEqual(cq["now"], 2)
        self.assertEqual(cq["daily"][0], ["2026-08-19", None], "before `since` the series is a gap")
        self.assertEqual(cq["daily"][4], ["2026-08-23", 2], "ids 1 and 3 were created on Aug 23")
        self.assertNotIn("proxy_loc", by_id, "headline: false stays off the front page")

    def test_groups_have_every_catalogue_metric_with_commit_series_for_snapshots(self):
        s = self.build()
        ids = {m["id"] for g in s["groups"].values() for m in g}
        self.assertEqual(ids, {"e2e_scenarios", "codeql_open_critical_high", "proxy_loc"})
        e2e = next(m for m in s["groups"]["safety_net"] if m["id"] == "e2e_scenarios")
        self.assertEqual([c[2] for c in e2e["commits"]], [0, 249])
        cq = next(m for m in s["groups"]["security"] if m["id"] == "codeql_open_critical_high")
        self.assertIsNone(cq["commits"])

    def test_stale_series_is_flagged(self):
        s = self.build(today=D(2026, 9, 20))
        e2e = {h["id"]: h for h in s["headline"]}["e2e_scenarios"]
        self.assertTrue(e2e["stale"]); self.assertEqual(e2e["status"], "stale")

    def test_phases_and_compare(self):
        s = self.build()
        self.assertEqual([p["id"] for p in s["phases"]], ["investigate", "phase0"])
        self.assertEqual(s["phases"][0]["start"], "2026-08-19")
        key = f"{self.base}..{self.second}"
        self.assertIn(key, s["compare"])
        row = next(r for r in s["compare"][key] if r["id"] == "e2e_scenarios")
        self.assertEqual((row["from"], row["to"], row["delta"], row["good"]), (0, 249, 249, True))

    def test_defects_section(self):
        s = self.build()
        self.assertEqual(len(s["defects"]["entries"]), 2)
        last_day = s["defects"]["by_status_daily"][-1]
        self.assertEqual(last_day[1]["pinned"], 1)

    def test_cli_builds_and_validates(self):
        out = self.tmp / "site.json"
        r = subprocess.run([sys.executable, "-m", "metrics.build", "--data", str(self.data), "--curated", str(self.cur),
                            "--out", str(out), "--repo", str(self.repo), "--base", self.base, "--today", "2026-09-05"],
                           capture_output=True, text=True, cwd=str(HERE.parents[3]))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("headline", json.loads(out.read_text()))
        r = subprocess.run([sys.executable, "-m", "metrics.build", "--validate-only", "--curated", str(self.cur),
                            "--repo", str(self.repo), "--base", self.base], capture_output=True, text=True, cwd=str(HERE.parents[3]))
        self.assertEqual(r.returncode, 0, r.stderr)
```

The assembly module is `assemble.py`, not `site.py`: `site` is a stdlib module that the
interpreter imports at startup, and the test runner puts `metrics/build` first on `sys.path`.

Run: `scripts/run_metrics_tests.sh build` → import error for `assemble`.

- [ ] **Step 2: Write `assemble.py`**

```python
"""Assemble site.json from snapshots, event dumps and the curated files."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from calendar_ import daily_dates, delta_is_good, forward_fill, is_stale, snapshot_series, status
from curated import Curated, Metric
from derive import DERIVATIONS, Context
from gitinfo import commit_date
from load import load_events, load_snapshots

SPARK_POINTS = 30


def _iso(d: dt.date) -> str:
    return d.isoformat()


def _series_for(m: Metric, snapshots, ctx: Context, dates: list[dt.date]):
    """Return (daily values, commit points or None, last_real datetime or None)."""
    if m.family == "derived":
        fn = DERIVATIONS[m.derivation]
        daily = [fn(ctx, d, m.params) if d >= m.since else None for d in dates]
        kinds = _kinds_for(m.derivation)
        fetched = [ctx.events[k].fetched_at for k in kinds if k in ctx.events and ctx.events[k].fetched_at]
        last_real = max(fetched) if fetched else None
        return daily, None, last_real
    rows = snapshots.get(m.family, [])
    points = snapshot_series(rows, m.path)
    daily = forward_fill([(t, v) for t, _, v in points], dates)
    daily = [v if d >= m.since else None for d, v in zip(dates, daily)]
    commits = [[sha, t.isoformat(), v] for t, sha, v in points]
    last_real = points[-1][0] if points else None
    return daily, commits, last_real


def _kinds_for(derivation: str) -> list[str]:
    if derivation.startswith("codeql"):
        return ["codeql_alerts"]
    if derivation.startswith("scorecard"):
        return ["scorecard"]
    if derivation.startswith("ci_"):
        return ["workflow_runs"]
    if derivation.startswith("pr"):
        return ["pull_requests"]
    if derivation.startswith("issues"):
        return ["issues"]
    return []


def _value_at(daily: list, dates: list[dt.date], day: dt.date):
    if day < dates[0]:
        return None
    idx = min((day - dates[0]).days, len(dates) - 1)
    return daily[idx]


def build_site(data_dir: Path, curated: Curated, *, repo: Path, base: str, today: dt.date, ref: str = "main") -> dict:
    snapshots = load_snapshots(data_dir)
    events = load_events(data_dir)
    ctx = Context(events=events, defects=curated.defects)
    base_date = commit_date(repo, base).date()
    dates = daily_dates(base_date, today)

    milestones = []
    for m in curated.milestones:
        d = commit_date(repo, m.sha)
        milestones.append({"sha": m.sha, "date": _iso(d.date()), "label": m.label, "kind": m.kind,
                           "phase": m.phase, "pr": m.pr, "summary": m.summary})
    milestones.sort(key=lambda x: x["date"])
    milestone_days = [dt.date.fromisoformat(x["date"]) for x in milestones]

    groups: dict[str, list[dict]] = {}
    series_by_id: dict[str, dict] = {}
    for m in curated.catalogue:
        daily, commits, last_real = _series_for(m, snapshots, ctx, dates)
        stale = is_stale(last_real, today) if m.since <= today else False
        now = daily[-1]
        # "Previous milestone" is per metric: the last milestone strictly before this
        # series' newest real point, so a milestone that landed with the latest data
        # does not make every metric read as stalled.
        cutoff = last_real.date() if last_real else today
        prev_day = max((d for d in milestone_days if d < cutoff), default=None)
        prev = _value_at(daily, dates, prev_day) if prev_day else None
        entry = {
            "id": m.id, "label": m.label, "unit": m.unit, "direction": m.direction, "target": m.target,
            "group": m.group, "headline": m.headline, "note": m.note,
            "daily": [[_iso(d), v] for d, v in zip(dates, daily)],
            "commits": commits,
            "last_real": last_real.isoformat() if last_real else None,
            "stale": stale,
            "status": status(m.direction, m.target, now, prev, stale),
            "now": now,
            "at_baseline": next((v for v in daily if v is not None), None),
            "at_prev_milestone": prev,
        }
        groups.setdefault(m.group, []).append(entry)
        series_by_id[m.id] = entry

    headline = [dict(e, spark=[v for _, v in e["daily"][-SPARK_POINTS:]]) for e in series_by_id.values() if e["headline"]]

    phases = []
    for p in curated.phases:
        own = [x for x in milestones if x["phase"] == p.id]
        starts = [x["date"] for x in own if x["kind"] == "phase-start"] or [x["date"] for x in own]
        ends = [x["date"] for x in own if x["kind"] == "phase-done"]
        phases.append({"id": p.id, "label": p.label, "summary": p.summary, "headline_ids": p.headline_ids,
                       "start": min(starts) if starts else None, "end": max(ends) if ends else None, "milestones": own})

    def compare(sha_a: str, sha_b: str) -> list[dict]:
        rows = []
        for e in series_by_id.values():
            if not e["commits"]:
                continue
            by_sha = {c[0]: c[2] for c in e["commits"]}
            if sha_a not in by_sha or sha_b not in by_sha:
                continue
            delta = by_sha[sha_b] - by_sha[sha_a]
            rows.append({"id": e["id"], "group": e["group"], "label": e["label"], "unit": e["unit"], "direction": e["direction"],
                         "from": by_sha[sha_a], "to": by_sha[sha_b], "delta": delta, "good": delta_is_good(e["direction"], delta)})
        return rows

    compare_pairs = [(a["sha"], b["sha"]) for a, b in zip(milestones, milestones[1:])]
    latest_sha = None
    for rows in snapshots.values():
        if rows and (latest_sha is None or rows[-1].timestamp > latest_ts):
            latest_sha, latest_ts = rows[-1].commit_sha, rows[-1].timestamp
    if latest_sha and milestones and (milestones[0]["sha"], latest_sha) not in compare_pairs:
        compare_pairs.append((milestones[0]["sha"], latest_sha))
    compare_section = {f"{a}..{b}": compare(a, b) for a, b in compare_pairs}

    by_status_daily = [[_iso(d), {s: DERIVATIONS["defects_by_status"](ctx, d, {"status": s}) for s in ("open", "pinned", "carried", "fixed")}] for d in dates]
    defects = {"entries": [vars(d) | {"first_seen": _iso(d.first_seen), "status_changed": _iso(d.status_changed)} for d in curated.defects],
               "by_status_daily": by_status_daily}

    freshness = {fam: rows[-1].timestamp.isoformat() for fam, rows in snapshots.items() if rows}
    freshness.update({k: v.fetched_at.isoformat() for k, v in events.items() if v.fetched_at})
    notes = [f"{k}: {v.status}" + (f" ({v.detail})" if v.detail else "") for k, v in events.items() if v.status != "ok"]

    return {
        "meta": {"built_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "today": _iso(today),
                 "baseline": {"sha": base, "date": _iso(base_date)}, "freshness": freshness, "source_notes": notes,
                 "commit_count": sum(1 for _ in snapshots.get("tests", []))},
        "headline": headline,
        "groups": groups,
        "phases": phases,
        "milestones": milestones,
        "defects": defects,
        "compare": compare_section,
    }
```

- [ ] **Step 3: Write `__main__.py`**

```python
"""CLI: build site.json, or only validate the curated files."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # the package's modules import each other by bare name (tests do too)

from assemble import build_site  # noqa: E402
from curated import load_curated, validate  # noqa: E402
from gitinfo import pr_is_merged  # noqa: E402
from load import load_snapshots  # noqa: E402

BASE = "fd413f0cc4ab3131789a68fb31f1ae622ae7371a"
REPO_SLUG = "D10Scot/Dispatcharr"


def _pointers(obj, prefix=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _pointers(v, f"{prefix}/{k}")
    else:
        yield prefix


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m metrics.build", description=__doc__)
    p.add_argument("--curated", type=Path, default=Path("metrics/curated"))
    p.add_argument("--data", type=Path, help="metrics-data checkout (omit with --validate-only)")
    p.add_argument("--out", type=Path)
    p.add_argument("--repo", type=Path, default=Path("."))
    p.add_argument("--base", default=BASE)
    p.add_argument("--ref", default="main")
    p.add_argument("--today", default=None, help="YYYY-MM-DD (default: today UTC)")
    p.add_argument("--check-prs", action="store_true", help="verify milestone/fixed_in PRs are merged via gh")
    p.add_argument("--validate-only", action="store_true")
    a = p.parse_args(argv)

    try:
        curated = load_curated(a.curated)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    known = None
    if a.data:
        known = {fam: set(_pointers(rows[-1].metrics)) for fam, rows in load_snapshots(a.data).items() if rows}
    checker = (lambda n: pr_is_merged(REPO_SLUG, n)) if a.check_prs else None
    errors = validate(curated, repo=a.repo, base=a.base, ref=a.ref, pr_checker=checker, known_families=known)
    if errors:
        print("curated files invalid:\n  " + "\n  ".join(errors), file=sys.stderr)
        return 1
    if a.validate_only:
        print(f"ok: {len(curated.catalogue)} metrics, {len(curated.milestones)} milestones, {len(curated.defects)} defects")
        return 0
    if not a.data or not a.out:
        p.error("--data and --out are required unless --validate-only")
    today = dt.date.fromisoformat(a.today) if a.today else dt.datetime.now(dt.timezone.utc).date()
    site = build_site(a.data, curated, repo=a.repo, base=a.base, today=today, ref=a.ref)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(site, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"wrote {a.out} ({a.out.stat().st_size // 1024} KB, {len(site['headline'])} headline metrics)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run to verify they pass**

Run: `scripts/run_metrics_tests.sh build` → `OK`. Then a real build against the fetched data
branch:

```bash
git fetch origin metrics-data
rm -rf /tmp/md && git worktree add /tmp/md origin/metrics-data
python -m metrics.build --data /tmp/md --curated metrics/curated --out /tmp/site.json && python3 -c "import json; s=json.load(open('/tmp/site.json')); print([ (h['id'], h['now'], h['status']) for h in s['headline']])"
```
Expected: twenty tuples; `codeql_open_critical_high` shows today's real count; coverage
metrics show `stale`/`None` until the daily job has run once after PR A merged.

- [ ] **Step 5: Commit**

```bash
git add metrics/build/assemble.py metrics/build/__main__.py metrics/build/tests/test_site.py
```
Commit message: `feat(metrics): assemble site.json; python -m metrics.build CLI with --validate-only`.

### Task 15: The agent contract, CLAUDE.md pointers, remediation prompt, PR B

**Files:**
- Create: `docs/agents/metrics.md`
- Modify: `CLAUDE.md` (Agent skills list; Test hooks paragraph)
- Modify: `.github/workflows/issue-remediation.md` (one sentence) and recompile `.lock.yml`
- Modify: spec (amendments 2–4)

- [ ] **Step 1: Write `docs/agents/metrics.md`**

```markdown
# Engineering metrics: the curated files and how to keep them

The dashboard at https://d10scot.github.io/Dispatcharr/ renders `site.json`,
built by `python -m metrics.build` from the `metrics-data` branch plus three
YAML files under `metrics/curated/`. Collectors never judge; the build step
computes; the pages draw. **These three files are the only hand-maintained
inputs, and any agent working in this repo is expected to keep them current
under the rules below.** Design: `docs/superpowers/specs/2026-09-04-engineering-metrics-dashboard-design.md`.

## Validate before you commit

```bash
python -m metrics.build --validate-only --curated metrics/curated          # offline (hook, gate)
python -m metrics.build --validate-only --curated metrics/curated --check-prs   # online (Pages build)
scripts/run_metrics_tests.sh build                                          # the same validator + unit tests
```

The PostToolUse hook runs the offline form on every edit under `metrics/`;
the commit gate runs it for staged changes; `pages.yml` runs the online form
and fails the site build on any error. Errors are listed all at once.

## `catalogue.yml` — what may be rendered

One entry per metric. **Nothing renders unless it is here.** Fields:

| field | values | notes |
|---|---|---|
| `id` | snake_case, unique | referenced by `phases[].headline_ids` |
| `family` | `code_health` `architecture` `tests` `coverage` `derived` | snapshot family or `derived` |
| `path` | JSON pointer `/a/b` | snapshot families only; must resolve in the family's latest row when `headline: true` |
| `derivation` + `params` | a name in `metrics/build/derive.py` `DERIVATIONS` | `derived` only |
| `label`, `unit` | `count` `pct` `seconds` `days` `score` `lines` `ratio` | |
| `direction` | `up` `down` `zero` `info` | `zero`: any nonzero is bad; `info`: never coloured |
| `target` | number or `null` | `zero` implies 0 |
| `group` | `safety_net` `security` `extraction` `delivery` `agents` | |
| `headline` | bool | exactly twenty `true`, four per group (tested) |
| `since` | date | first day the series means anything |
| `note` | one sentence | the counting rule; shown under the chart |

**When to edit:** a PR that adds, renames or removes a collector field or a
derivation updates its entry in the same PR. To promote a metric to the
front page, demote another in the same group.

## `milestones.yml` — phases and the lines on the charts

Two keys. `phases:` — `id`, `label`, `summary` (two sentences max),
`headline_ids` (two or three catalogue ids the phase is meant to move).
`milestones:` — `sha` (full, first-parent on `main` since `fd413f0c`),
`label` (≤ 40 chars), `kind` (`phase-start` `phase-done` `goal` `incident`
`release`), `phase` (a declared phase id), `pr` (number or `null`), `summary`
(one sentence). `date` is derived from the commit; do not store it.

**When to add an entry:**
- a phase's spec is committed → `phase-start`
- a spec's Done log gets its final tick → `phase-done`
- a goal's PR merges → `goal`
- a release is tagged → `release`
- a security incident is fixed → `incident`

**Never** change a past entry's `sha` or `kind`; `label` and `summary` may be corrected.

## `defects.yml` — the known-defect ledger

One entry per item in CLAUDE.md "Known defects and traps". Fields: `id`
(stable slug), `title`, `area` (`security` `correctness` `dead-code`
`operational`), `severity` (`critical` `high` `medium` `low`), `status`,
`source` (CLAUDE.md anchor), `issue`, `test` (repo path), `fixed_in` (PR),
`carried_as` (spec anchor), `first_seen`, `status_changed` (dates).

| status | requires | meaning |
|---|---|---|
| `open` | `issue` **or** `source` | known, nothing asserts it |
| `pinned` | `issue` and `test` (path must exist) | a failing test asserts the bug (`test.fail()` or a backend test) |
| `carried` | `carried_as` | written into a spec as a constraint the extracted relay must not recreate |
| `fixed` | `fixed_in` (merged PR) | done |

Status moves forward only: `open → pinned → fixed`, `open → carried → fixed`,
`open → fixed`. The validator compares against `main` and rejects a backward
move.

**When to update:** a PR that closes the linked issue → `fixed` with
`fixed_in` and today's `status_changed`; a `test.fail()` pin or backend test
added for it → `pinned` with `test`; a spec that lists it as a carried
constraint → `carried`. A new CLAUDE.md defect entry gets a ledger entry in
the same PR.

## When a collector says "not permitted" or "disabled"

`events/<kind>.json` carries `status` and `detail`; the dashboard shows them
in the footer. `dependabot_alerts` is `not_permitted` under `GITHUB_TOKEN`
(a PAT with Dependabot read would fix it — repo settings, not code);
`secret_scanning` is `disabled` at repo level. Do not "fix" these by
returning zero.

## Preview the site locally

```bash
git fetch origin metrics-data && git worktree add /tmp/md origin/metrics-data
python -m metrics.build --data /tmp/md --curated metrics/curated --out dashboard/site.json
cd dashboard && python3 -m http.server 8123     # http://localhost:8123/
```
`dashboard/site.json` is gitignored.
```

- [ ] **Step 2: CLAUDE.md pointers**

Under `## Agent skills`, add after the "Domain docs" bullet:

```
- **Metrics dashboard**: three agent-maintained files under `metrics/curated/` (catalogue, milestones, defect ledger) feed https://d10scot.github.io/Dispatcharr/. A PR that closes a ledger issue, adds a `test.fail()` pin, merges a goal, or ticks a Done log updates them in the same PR. Validate with `python -m metrics.build --validate-only`. See `docs/agents/metrics.md`.
```

In `## Test hooks`, extend the list of checks with: `metrics/**` and `scripts/metrics/**`
(`scripts/run_metrics_tests.sh`, plain unittest, no container), `dashboard/*.{js,html}`
(vitest with `frontend/vitest.dashboard.config.js`).

- [ ] **Step 3: Remediation prompt**

In `.github/workflows/issue-remediation.md`, next to the line
`` - `Fixes #$ISSUE_NUMBER` on its own line `` add:

```
- If `metrics/curated/defects.yml` has an entry whose `issue` is this issue, set its `status` to `fixed`, `fixed_in` to the PR number (use the temporary id if the number is not known yet) and `status_changed` to today, in the same commit; `docs/agents/metrics.md` has the rules.
```

Recompile: `gh aw compile` (install with `gh extension install github/gh-aw` if missing).
Commit the `.md`, the regenerated `.lock.yml` and `.github/aw/actions-lock.json` together;
the hook lints the lock file with zizmor.

- [ ] **Step 4: Spec amendments 2–4**

Apply the three amendments listed under Global Constraints to §5.1, §5.2, §5.3 of the spec.

- [ ] **Step 5: Add `dashboard/site.json` to `.gitignore`, commit, open PR B**

```bash
git add docs/agents/metrics.md CLAUDE.md .github/workflows/issue-remediation.md .github/workflows/issue-remediation.lock.yml .github/aw/actions-lock.json docs/superpowers/specs/2026-09-04-engineering-metrics-dashboard-design.md .gitignore
```
Commit message: `docs(metrics): the agent contract for the curated files`.

PR B title: `metrics: curated inputs and the site build step (Part B)`.

---

# Part C — Pages (`metrics-dashboard-pages`)

Setup: after PR B merges, `git worktree add ../Dispatcharr-metrics-c -b metrics-dashboard-pages origin/main`,
then `cd frontend && npm ci` (vitest and jsdom come from there).

### Task 16: Vitest config, fixture `site.json`, and the pure helper modules

**Files:**
- Create: `frontend/vitest.dashboard.config.js`
- Create: `dashboard/tests/fixtures/site.json`
- Create: `dashboard/lib/format.js`, `dashboard/lib/spark.js`, `dashboard/lib/compare.js`
- Create: `dashboard/tests/format.test.js`, `dashboard/tests/spark.test.js`, `dashboard/tests/compare.test.js`
- Delete: `dashboard/data.js`, `overview.js`, `trends.js`, `trends.html`, `presentation.html`, `presentation.js`, `milestones.json`

**Interfaces:**
- `format.fmt(value, unit) -> string`: `null` → `"—"`; `pct` → `45.6%`; `ratio` → `95%`;
  `seconds` → `13m`, `2.4h`, `3.1d`; `days` → `12 d`; `score` → `6.9`; `count`/`lines` → `1,860`.
- `format.fmtDelta(delta, unit) -> string` with a leading sign (`+249`, `−0.4 pt` for pct).
- `format.shortSha(sha)`, `format.fmtDate(iso)` (`3 Sep`), `format.statusClass(status)` →
  `"good" | "bad" | "neutral" | "stale"`.
- `spark.paths(values, width, height) -> {line: string, area: string}`: SVG path data for a
  series with `null` gaps (a gap breaks the line and the area); empty or all-null → both `""`.
- `compare.rowsFor(site, fromSha, toSha) -> row[]`: the precomputed `site.compare[key]` when
  present, else computed from `site.groups[*].commits` with the same shape and `good` rule.
- `compare.deltaIsGood(direction, delta) -> true | false | null` (mirror of the Python rule).

- [ ] **Step 1: Delete the old dashboard files and write the vitest config**

Run: `git rm dashboard/data.js dashboard/overview.js dashboard/trends.js dashboard/trends.html dashboard/presentation.html dashboard/presentation.js dashboard/milestones.json`

`frontend/vitest.dashboard.config.js`:

```js
// Tests for the static metrics dashboard (../dashboard). Run from frontend/
// so vitest and jsdom resolve from this package's node_modules:
//   npx vitest --run --config vitest.dashboard.config.js
import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    root: '../dashboard',
    environment: 'jsdom',
    include: ['tests/**/*.test.js'],
    globals: true,
  },
});
```

- [ ] **Step 2: Write the fixture `site.json`**

`dashboard/tests/fixtures/site.json` — hand-written, small, the shape from Task 14:

```json
{
  "meta": {"built_at": "2026-09-05T06:20:00+00:00", "today": "2026-09-05",
           "baseline": {"sha": "fd413f0cc4ab3131789a68fb31f1ae622ae7371a", "date": "2026-08-19"},
           "freshness": {"tests": "2026-09-03T21:09:00+00:00", "codeql_alerts": "2026-09-05T06:05:00+00:00"},
           "source_notes": ["dependabot_alerts: not_permitted (HTTP 403)"], "commit_count": 67},
  "headline": [
    {"id": "e2e_scenarios", "label": "E2E scenarios", "unit": "count", "direction": "up", "target": null, "group": "safety_net", "headline": true,
     "note": "Playwright test() call sites.", "daily": [["2026-09-03", 200], ["2026-09-04", 249], ["2026-09-05", 249]],
     "commits": [["fd413f0cc4ab3131789a68fb31f1ae622ae7371a", "2026-08-19T22:13:45+00:00", 0], ["75a68555b931e7d088bfbbd859b35e6e27064312", "2026-09-03T21:09:00+00:00", 249]],
     "last_real": "2026-09-03T21:09:00+00:00", "stale": false, "status": "good", "now": 249, "at_baseline": 0, "at_prev_milestone": 200, "spark": [200, 249, 249]},
    {"id": "codeql_open_critical_high", "label": "Open CodeQL critical + high", "unit": "count", "direction": "zero", "target": null, "group": "security", "headline": true,
     "note": "Open alerts.", "daily": [["2026-09-03", 75], ["2026-09-04", 75], ["2026-09-05", 75]], "commits": null,
     "last_real": "2026-09-05T06:05:00+00:00", "stale": false, "status": "bad", "now": 75, "at_baseline": 75, "at_prev_milestone": 75, "spark": [75, 75, 75]},
    {"id": "backend_coverage", "label": "Backend line coverage", "unit": "pct", "direction": "up", "target": 60, "group": "safety_net", "headline": true,
     "note": "Daily.", "daily": [["2026-09-03", null], ["2026-09-04", null], ["2026-09-05", null]], "commits": [],
     "last_real": null, "stale": true, "status": "stale", "now": null, "at_baseline": null, "at_prev_milestone": null, "spark": [null, null, null]}
  ],
  "groups": {
    "safety_net": [
      {"id": "e2e_scenarios", "label": "E2E scenarios", "unit": "count", "direction": "up", "target": null, "group": "safety_net", "headline": true, "note": "Playwright test() call sites.",
       "daily": [["2026-09-03", 200], ["2026-09-04", 249], ["2026-09-05", 249]],
       "commits": [["fd413f0cc4ab3131789a68fb31f1ae622ae7371a", "2026-08-19T22:13:45+00:00", 0], ["75a68555b931e7d088bfbbd859b35e6e27064312", "2026-09-03T21:09:00+00:00", 249]],
       "last_real": "2026-09-03T21:09:00+00:00", "stale": false, "status": "good", "now": 249, "at_baseline": 0, "at_prev_milestone": 200},
      {"id": "backend_coverage", "label": "Backend line coverage", "unit": "pct", "direction": "up", "target": 60, "group": "safety_net", "headline": true, "note": "Daily.",
       "daily": [["2026-09-03", null], ["2026-09-04", null], ["2026-09-05", null]], "commits": [], "last_real": null, "stale": true, "status": "stale", "now": null, "at_baseline": null, "at_prev_milestone": null}
    ],
    "security": [
      {"id": "codeql_open_critical_high", "label": "Open CodeQL critical + high", "unit": "count", "direction": "zero", "target": null, "group": "security", "headline": true, "note": "Open alerts.",
       "daily": [["2026-09-03", 75], ["2026-09-04", 75], ["2026-09-05", 75]], "commits": null, "last_real": "2026-09-05T06:05:00+00:00", "stale": false, "status": "bad", "now": 75, "at_baseline": 75, "at_prev_milestone": 75}
    ],
    "extraction": [
      {"id": "reverse_imports_into_proxy", "label": "Reverse imports into apps/proxy", "unit": "count", "direction": "down", "target": 0, "group": "extraction", "headline": false, "note": "Imports.",
       "daily": [["2026-09-03", 24], ["2026-09-04", 24], ["2026-09-05", 24]],
       "commits": [["fd413f0cc4ab3131789a68fb31f1ae622ae7371a", "2026-08-19T22:13:45+00:00", 24], ["75a68555b931e7d088bfbbd859b35e6e27064312", "2026-09-03T21:09:00+00:00", 24]],
       "last_real": "2026-09-03T21:09:00+00:00", "stale": false, "status": "bad", "now": 24, "at_baseline": 24, "at_prev_milestone": 24}
    ]
  },
  "phases": [
    {"id": "investigate", "label": "Investigate", "summary": "Read before writing.", "headline_ids": ["e2e_scenarios"], "start": "2026-08-19", "end": null,
     "milestones": [{"sha": "fd413f0cc4ab3131789a68fb31f1ae622ae7371a", "date": "2026-08-19", "label": "v0.29.0 baseline", "kind": "phase-start", "phase": "investigate", "pr": null, "summary": "Fork point."}]},
    {"id": "phase0", "label": "Phase 0", "summary": "Harden in place.", "headline_ids": ["codeql_open_critical_high"], "start": "2026-09-03", "end": "2026-09-03",
     "milestones": [{"sha": "75a68555b931e7d088bfbbd859b35e6e27064312", "date": "2026-09-03", "label": "Phase 0 done", "kind": "phase-done", "phase": "phase0", "pr": 155, "summary": "All six items merged."}]}
  ],
  "milestones": [
    {"sha": "fd413f0cc4ab3131789a68fb31f1ae622ae7371a", "date": "2026-08-19", "label": "v0.29.0 baseline", "kind": "phase-start", "phase": "investigate", "pr": null, "summary": "Fork point."},
    {"sha": "75a68555b931e7d088bfbbd859b35e6e27064312", "date": "2026-09-03", "label": "Phase 0 done", "kind": "phase-done", "phase": "phase0", "pr": 155, "summary": "All six items merged."}
  ],
  "defects": {
    "entries": [
      {"id": "m3u-unescaped-quote", "title": "Unescaped quote in EXTINF", "area": "correctness", "severity": "medium", "status": "pinned", "source": null, "issue": 80, "test": "e2e/tests/seeded/output-m3u.spec.ts", "fixed_in": null, "carried_as": null, "first_seen": "2026-08-30", "status_changed": "2026-08-30"},
      {"id": "credentials-logged-at-info", "title": "Credentials logged at INFO", "area": "security", "severity": "critical", "status": "fixed", "source": null, "issue": 89, "test": null, "fixed_in": 154, "carried_as": null, "first_seen": "2026-08-22", "status_changed": "2026-09-03"}
    ],
    "by_status_daily": [["2026-09-03", {"open": 0, "pinned": 1, "carried": 0, "fixed": 1}], ["2026-09-04", {"open": 0, "pinned": 1, "carried": 0, "fixed": 1}], ["2026-09-05", {"open": 0, "pinned": 1, "carried": 0, "fixed": 1}]]
  },
  "compare": {
    "fd413f0cc4ab3131789a68fb31f1ae622ae7371a..75a68555b931e7d088bfbbd859b35e6e27064312": [
      {"id": "e2e_scenarios", "group": "safety_net", "label": "E2E scenarios", "unit": "count", "direction": "up", "from": 0, "to": 249, "delta": 249, "good": true},
      {"id": "reverse_imports_into_proxy", "group": "extraction", "label": "Reverse imports into apps/proxy", "unit": "count", "direction": "down", "from": 24, "to": 24, "delta": 0, "good": null}
    ]
  }
}
```

- [ ] **Step 3: Write the failing tests**

`dashboard/tests/format.test.js`:

```js
import { describe, expect, it } from 'vitest';
import { fmt, fmtDate, fmtDelta, shortSha, statusClass } from '../lib/format.js';

describe('fmt', () => {
  it('formats by unit', () => {
    expect(fmt(null, 'count')).toBe('—');
    expect(fmt(1860, 'count')).toBe('1,860');
    expect(fmt(45.678, 'pct')).toBe('45.7%');
    expect(fmt(0.9535, 'ratio')).toBe('95%');
    expect(fmt(778, 'seconds')).toBe('13m');
    expect(fmt(8640, 'seconds')).toBe('2.4h');
    expect(fmt(270000, 'seconds')).toBe('3.1d');
    expect(fmt(12, 'days')).toBe('12 d');
    expect(fmt(6.9, 'score')).toBe('6.9');
  });
  it('formats deltas with a sign', () => {
    expect(fmtDelta(249, 'count')).toBe('+249');
    expect(fmtDelta(-3, 'count')).toBe('−3');
    expect(fmtDelta(0.4, 'pct')).toBe('+0.4 pt');
    expect(fmtDelta(0, 'count')).toBe('±0');
  });
  it('helpers', () => {
    expect(shortSha('fd413f0cc4ab3131789a68fb31f1ae622ae7371a')).toBe('fd413f0c');
    expect(fmtDate('2026-09-03')).toBe('3 Sep');
    expect(statusClass('good')).toBe('good');
    expect(statusClass('weird')).toBe('neutral');
  });
});
```

`dashboard/tests/spark.test.js`:

```js
import { describe, expect, it } from 'vitest';
import { paths } from '../lib/spark.js';

describe('spark paths', () => {
  it('draws a line and a closed area', () => {
    const { line, area } = paths([0, 5, 10], 200, 60);
    expect(line).toMatch(/^M0,60/);
    expect(line).toMatch(/L200,0$/);
    expect(area).toMatch(/Z$/);
    expect(area).toContain('L200,60');
  });
  it('breaks at nulls and handles flat series', () => {
    const { line } = paths([1, null, 1], 100, 10);
    expect(line.match(/M/g)).toHaveLength(2);
    const flat = paths([3, 3, 3], 100, 10);
    expect(flat.line).toContain('M0,5');
  });
  it('is empty for no data', () => {
    expect(paths([], 100, 10)).toEqual({ line: '', area: '' });
    expect(paths([null, null], 100, 10)).toEqual({ line: '', area: '' });
  });
});
```

`dashboard/tests/compare.test.js`:

```js
import { describe, expect, it } from 'vitest';
import site from './fixtures/site.json';
import { deltaIsGood, rowsFor } from '../lib/compare.js';

const A = 'fd413f0cc4ab3131789a68fb31f1ae622ae7371a';
const B = '75a68555b931e7d088bfbbd859b35e6e27064312';

describe('compare', () => {
  it('uses the precomputed pair when present', () => {
    const rows = rowsFor(site, A, B);
    expect(rows.find((r) => r.id === 'e2e_scenarios').good).toBe(true);
  });
  it('computes from commit series for an arbitrary pair', () => {
    const rows = rowsFor(site, B, A);
    const e2e = rows.find((r) => r.id === 'e2e_scenarios');
    expect(e2e.delta).toBe(-249);
    expect(e2e.good).toBe(false);
    expect(rows.find((r) => r.id === 'codeql_open_critical_high')).toBeUndefined();
  });
  it('mirrors the python rule', () => {
    expect(deltaIsGood('down', -1)).toBe(true);
    expect(deltaIsGood('zero', 1)).toBe(false);
    expect(deltaIsGood('info', 1)).toBeNull();
    expect(deltaIsGood('up', 0)).toBeNull();
  });
});
```

Run: `cd frontend && npx vitest --run --config vitest.dashboard.config.js` → three files fail to
import.

- [ ] **Step 4: Write the three modules**

`dashboard/lib/format.js`:

```js
// Number, date and status formatting. Pure; no DOM.

const STATUSES = new Set(['good', 'bad', 'neutral', 'stale']);

export function fmt(value, unit) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  switch (unit) {
    case 'pct': return `${round(value, 1)}%`;
    case 'ratio': return `${Math.round(value * 100)}%`;
    case 'seconds': return fmtSeconds(value);
    case 'days': return `${Math.round(value)} d`;
    case 'score': return String(round(value, 1));
    default: return Number.isInteger(value) ? value.toLocaleString('en-GB') : String(round(value, 2));
  }
}

function fmtSeconds(s) {
  if (s < 3600) return `${Math.round(s / 60)}m`;
  if (s < 86400) return `${round(s / 3600, 1)}h`;
  return `${round(s / 86400, 1)}d`;
}

export function fmtDelta(delta, unit) {
  if (delta === null || delta === undefined) return '—';
  if (delta === 0) return '±0';
  const sign = delta > 0 ? '+' : '−';
  const abs = Math.abs(delta);
  if (unit === 'pct') return `${sign}${round(abs, 1)} pt`;
  if (unit === 'ratio') return `${sign}${Math.round(abs * 100)} pt`;
  return `${sign}${fmt(abs, unit)}`;
}

export function shortSha(sha) {
  return typeof sha === 'string' ? sha.slice(0, 8) : '';
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export function fmtDate(iso) {
  // Fixed abbreviations: ICU's en-GB short month is "Sept", which drifts by Node version.
  const d = new Date(`${iso.slice(0, 10)}T00:00:00Z`);
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}`;
}

export function statusClass(status) {
  return STATUSES.has(status) ? status : 'neutral';
}

function round(n, places) {
  const f = 10 ** places;
  return Math.round(n * f) / f;
}
```

`dashboard/lib/spark.js`:

```js
// SVG path data for the soft background trend on a tile. Pure; no DOM.
// A null breaks the line (a real gap), which is why the path can carry
// several M commands; the area follows the same segments.

export function paths(values, width, height) {
  const pts = values.map((v, i) => [i, v]).filter(([, v]) => v !== null && v !== undefined);
  if (pts.length === 0) return { line: '', area: '' };
  const n = Math.max(values.length - 1, 1);
  const vals = pts.map(([, v]) => v);
  const lo = Math.min(...vals);
  const hi = Math.max(...vals);
  const span = hi - lo || 1;
  const x = (i) => (values.length === 1 ? width : (i / n) * width);
  const y = (v) => (hi === lo ? height / 2 : height - ((v - lo) / span) * height);

  const segments = [];
  let current = [];
  values.forEach((v, i) => {
    if (v === null || v === undefined) {
      if (current.length) segments.push(current);
      current = [];
    } else {
      current.push([x(i), y(v)]);
    }
  });
  if (current.length) segments.push(current);

  const line = segments
    .map((seg) => seg.map(([px, py], j) => `${j === 0 ? 'M' : 'L'}${r(px)},${r(py)}`).join(' '))
    .join(' ');
  const area = segments
    .map((seg) => {
      const first = seg[0];
      const last = seg[seg.length - 1];
      const body = seg.map(([px, py], j) => `${j === 0 ? 'M' : 'L'}${r(px)},${r(py)}`).join(' ');
      return `${body} L${r(last[0])},${height} L${r(first[0])},${height} Z`;
    })
    .join(' ');
  return { line, area };
}

function r(n) {
  return Math.round(n * 100) / 100;
}
```

`dashboard/lib/compare.js`:

```js
// Milestone-to-milestone deltas. Uses the build step's precomputed pair when
// it exists, otherwise derives the same rows from per-commit series so any
// two milestones can be compared.

export function deltaIsGood(direction, delta) {
  if (direction === 'info' || delta === 0) return null;
  return direction === 'down' || direction === 'zero' ? delta < 0 : delta > 0;
}

export function rowsFor(site, fromSha, toSha) {
  const pre = site.compare && site.compare[`${fromSha}..${toSha}`];
  if (pre) return pre;
  const rows = [];
  for (const [group, metrics] of Object.entries(site.groups || {})) {
    for (const m of metrics) {
      if (!m.commits) continue;
      const bySha = Object.fromEntries(m.commits.map(([sha, , v]) => [sha, v]));
      if (!(fromSha in bySha) || !(toSha in bySha)) continue;
      const delta = bySha[toSha] - bySha[fromSha];
      rows.push({ id: m.id, group, label: m.label, unit: m.unit, direction: m.direction,
                  from: bySha[fromSha], to: bySha[toSha], delta, good: deltaIsGood(m.direction, delta) });
    }
  }
  return rows;
}
```

- [ ] **Step 5: Run to verify they pass**

Run: `cd frontend && npx vitest --run --config vitest.dashboard.config.js` → 3 files, all
tests pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/vitest.dashboard.config.js dashboard
```
Commit message: `feat(dashboard): vitest config, fixture site.json, pure format/spark/compare helpers; retire the old views`.

### Task 17: App boot, stylesheet, phase strip, tiles, and the Overview page

**Files:**
- Create: `dashboard/app.js`, `dashboard/lib/dom.js`, `dashboard/lib/status.js`
- Create: `dashboard/pages/overview.js`
- Create: `dashboard/index.html`
- Rewrite: `dashboard/style.css`
- Create: `dashboard/tests/overview.test.js`

**Interfaces:**
- `dom.h(tag, attrs, ...children) -> Element` (tiny element builder; `attrs.class`,
  `attrs.text`, `attrs.html` is **not** supported — text only, so page data can never inject
  markup), `dom.svg(tag, attrs, ...children)`.
- `status.tile(metric) -> Element` (`.tile.<status>` with `.l` label, `.v` value, `.d`
  context line, background `<svg>` from `spark.paths`), `status.phaseStrip(site) -> Element`,
  `status.footer(site) -> Element` (freshness per family + source notes),
  `status.contextLine(metric) -> string`.
- `overview.render(site, root)`; every page module exports `render(site, root)`.
- `app.boot(pageName)`: fetches `site.json` (relative, `cache: 'no-store'`), calls the page's
  `render`, and on failure writes an error paragraph into `main`.

- [ ] **Step 1: Write the failing test**

`dashboard/tests/overview.test.js`:

```js
import { beforeEach, describe, expect, it } from 'vitest';
import site from './fixtures/site.json';
import { render } from '../pages/overview.js';
import { contextLine, tile } from '../lib/status.js';

describe('overview', () => {
  let root;
  beforeEach(() => { document.body.innerHTML = '<main id="root"></main>'; root = document.getElementById('root'); });

  it('renders the phase strip, one tile per headline, grouped, and the footer', () => {
    render(site, root);
    expect(root.querySelectorAll('.phase').length).toBe(2);
    expect(root.querySelectorAll('.phase.cur').length).toBe(1);
    expect(root.querySelectorAll('.tile').length).toBe(3);
    const groups = [...root.querySelectorAll('.grp')].map((g) => g.textContent);
    expect(groups[0]).toBe('Safety net');
    expect(root.querySelector('.foot').textContent).toContain('dependabot_alerts: not_permitted');
  });

  it('colours tiles by status and shows the value and context', () => {
    render(site, root);
    const e2e = root.querySelector('[data-id="e2e_scenarios"]');
    expect(e2e.classList.contains('good')).toBe(true);
    expect(e2e.querySelector('.v').textContent).toBe('249');
    expect(e2e.querySelector('.d').textContent).toBe('+249 since baseline');
    expect(e2e.querySelector('svg path.line').getAttribute('d')).toMatch(/^M/);
    const cq = root.querySelector('[data-id="codeql_open_critical_high"]');
    expect(cq.classList.contains('bad')).toBe(true);
    expect(cq.querySelector('.d').textContent).toBe('target 0 · ±0 since baseline');
    const cov = root.querySelector('[data-id="backend_coverage"]');
    expect(cov.classList.contains('stale')).toBe(true);
    expect(cov.querySelector('.v').textContent).toBe('—');
    expect(cov.querySelector('.d').textContent).toContain('no data yet');
  });

  it('never injects markup from data', () => {
    const evil = { ...site.headline[0], label: '<img src=x onerror=alert(1)>' };
    const el = tile(evil);
    expect(el.querySelector('img')).toBeNull();
    expect(el.querySelector('.l').textContent).toContain('<img');
  });

  it('context line rules', () => {
    expect(contextLine({ unit: 'count', direction: 'up', target: null, now: 5, at_baseline: 2, stale: false, last_real: 'x' })).toBe('+3 since baseline');
    expect(contextLine({ unit: 'pct', direction: 'up', target: 60, now: 45.6, at_baseline: 45.6, stale: false, last_real: 'x' })).toBe('target 60% · ±0 since baseline');
    expect(contextLine({ unit: 'count', direction: 'up', target: null, now: null, at_baseline: null, stale: true, last_real: null })).toBe('no data yet');
    expect(contextLine({ unit: 'count', direction: 'up', target: null, now: 5, at_baseline: 2, stale: true, last_real: '2026-09-01T06:00:00+00:00' })).toBe('+3 since baseline · stale since 1 Sep');
  });
});
```

Run: `cd frontend && npx vitest --run --config vitest.dashboard.config.js` → import failures.

- [ ] **Step 2: Write `lib/dom.js`**

```js
// Minimal element builders. Text only: there is deliberately no way to set
// innerHTML from here, so nothing read from site.json can become markup.

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  apply(el, attrs);
  append(el, children);
  return el;
}

export function svg(tag, attrs = {}, ...children) {
  const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
  apply(el, attrs);
  append(el, children);
  return el;
}

function apply(el, attrs) {
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'text') el.textContent = String(v);
    else if (k === 'class') el.setAttribute('class', v);
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, String(v));
  }
}

function append(el, children) {
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    el.append(typeof c === 'string' ? document.createTextNode(c) : c);
  }
}
```

- [ ] **Step 3: Write `lib/status.js`**

```js
// Shared visual pieces: the headline tile, the phase strip, the footer.
import { h, svg } from './dom.js';
import { fmt, fmtDate, fmtDelta, shortSha, statusClass } from './format.js';
import { paths } from './spark.js';

export const GROUP_LABELS = {
  safety_net: 'Safety net', security: 'Security', extraction: 'Extraction readiness',
  delivery: 'Delivery', agents: 'Agent pipeline',
};
export const GROUP_ORDER = ['safety_net', 'security', 'extraction', 'delivery', 'agents'];

const SPARK_W = 200;
const SPARK_H = 60;

export function contextLine(m) {
  if (m.now === null || m.now === undefined) return 'no data yet';
  const parts = [];
  const target = m.direction === 'zero' ? 0 : m.target;
  if (target !== null && target !== undefined && m.direction !== 'info') parts.push(`target ${fmt(target, m.unit)}`);
  if (m.at_baseline !== null && m.at_baseline !== undefined) parts.push(`${fmtDelta(m.now - m.at_baseline, m.unit)} since baseline`);
  if (m.stale && m.last_real) parts.push(`stale since ${fmtDate(m.last_real)}`);
  return parts.join(' · ');
}

export function tile(m) {
  const cls = statusClass(m.status);
  const { line, area } = paths(m.spark || [], SPARK_W, SPARK_H);
  const bg = svg('svg', { viewBox: `0 0 ${SPARK_W} ${SPARK_H}`, preserveAspectRatio: 'none', 'aria-hidden': 'true' },
    area && svg('path', { class: 'area', d: area }),
    line && svg('path', { class: 'line', d: line }));
  return h('div', { class: `tile ${cls}`, 'data-id': m.id, title: m.note || '' },
    bg,
    h('div', { class: 'l', text: m.label }),
    h('div', { class: 'v', text: fmt(m.now, m.unit) }),
    h('div', { class: 'd', text: contextLine(m) }));
}

export function phaseStrip(site) {
  const today = site.meta.today;
  return h('div', { class: 'phases' }, site.phases.map((p) => {
    const done = p.end !== null && p.end !== undefined;
    const cur = !done && p.start && p.start <= today;
    const cls = `phase${done ? ' done' : ''}${cur ? ' cur' : ''}`;
    return h('div', { class: cls, title: p.summary },
      p.milestones.map((ms) => h('span', { class: `m ${ms.kind}`, title: `${ms.label}${ms.pr ? ` (#${ms.pr})` : ''}: ${ms.summary}` })),
      h('span', { class: 'name', text: p.label }),
      h('span', { class: 'muted', text: done ? `${fmtDate(p.start)} – ${fmtDate(p.end)}` : cur ? 'now' : '' }));
  }));
}

export function footer(site) {
  const fresh = Object.entries(site.meta.freshness || {}).map(([k, v]) => `${k} ${v.slice(0, 16).replace('T', ' ')}`).join(' · ');
  const notes = (site.meta.source_notes || []).join(' · ');
  return h('div', { class: 'foot' },
    h('span', { text: `Data as of: ${fresh || 'none'}${notes ? ` · ⚠ ${notes}` : ''}` }),
    h('span', { text: `baseline ${shortSha(site.meta.baseline.sha)} · ${site.meta.commit_count} commits · built ${site.meta.built_at.slice(0, 16).replace('T', ' ')} UTC` }));
}
```

- [ ] **Step 4: Write `pages/overview.js` and `app.js`**

`dashboard/pages/overview.js`:

```js
import { h } from '../lib/dom.js';
import { footer, GROUP_LABELS, GROUP_ORDER, phaseStrip, tile } from '../lib/status.js';

export function render(site, root) {
  root.replaceChildren();
  root.append(phaseStrip(site));
  const byGroup = {};
  for (const m of site.headline) (byGroup[m.group] ||= []).push(m);
  for (const g of GROUP_ORDER) {
    if (!byGroup[g]) continue;
    root.append(h('div', { class: 'grp', text: GROUP_LABELS[g] }));
    root.append(h('div', { class: 'tiles' }, byGroup[g].map(tile)));
  }
  root.append(footer(site));
}
```

`dashboard/app.js`:

```js
// Boot: fetch site.json once and hand it to the page named in <main data-page>.
import * as overview from './pages/overview.js';
import * as story from './pages/story.js';
import * as explore from './pages/explore.js';
import * as compare from './pages/compare.js';
import * as defects from './pages/defects.js';
import { h } from './lib/dom.js';

const PAGES = { overview, story, explore, compare, defects };

export async function boot(pageName) {
  const root = document.querySelector('main');
  try {
    const res = await fetch('site.json', { cache: 'no-store' });
    if (!res.ok) throw new Error(`site.json: HTTP ${res.status}`);
    const site = await res.json();
    PAGES[pageName].render(site, root, new URLSearchParams(window.location.search));
  } catch (err) {
    root.replaceChildren(h('p', { class: 'error', text: `Could not load the dashboard data: ${err.message}. The Pages build may not have run yet.` }));
  }
}

if (typeof document !== 'undefined' && document.querySelector('main[data-page]')) {
  boot(document.querySelector('main').dataset.page);
}
```

Until Tasks 18–19 land, create `pages/story.js`, `pages/explore.js`, `pages/compare.js`,
`pages/defects.js` each containing only `export function render(site, root) { root.textContent = 'coming in the next task'; }`
so `app.js` imports resolve.

- [ ] **Step 5: Write `index.html` and `style.css`**

`dashboard/index.html`:

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="color-scheme" content="light dark" />
<title>Dispatcharr fork · engineering metrics</title>
<link rel="stylesheet" href="vendor/uplot/uPlot.min.css" />
<link rel="stylesheet" href="style.css" />
</head>
<body>
<header>
  <h1>Dispatcharr fork metrics</h1>
  <nav>
    <a href="index.html" class="active">Overview</a>
    <a href="story.html">Story</a>
    <a href="explore.html">Explore</a>
    <a href="compare.html">Compare</a>
    <a href="defects.html">Defects</a>
  </nav>
</header>
<main data-page="overview"><p class="empty">Loading…</p></main>
<script src="vendor/uplot/uPlot.iife.min.js"></script>
<script type="module" src="app.js"></script>
</body>
</html>
```

`dashboard/style.css` (complete replacement):

```css
:root {
  --bg: #fafafa; --panel: #fff; --border: #e5e7eb; --text: #1f2937; --muted: #6b7280;
  --accent: #1d4ed8; --good: #15803d; --bad: #b91c1c; --stale: #6b7280;
  font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
}
@media (prefers-color-scheme: dark) {
  :root { --bg: #0f1115; --panel: #171a21; --border: #2a2f3a; --text: #e6e8eb; --muted: #9aa3b2;
          --accent: #4da3ff; --good: #4ade80; --bad: #f87171; --stale: #9aa3b2; }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); }
header { padding: .9rem 1.5rem; border-bottom: 1px solid var(--border); display: flex; align-items: baseline; gap: 1.5rem; }
header h1 { font-size: 1.05rem; margin: 0; }
nav a { color: var(--muted); text-decoration: none; margin-right: 1rem; font-size: .9rem; }
nav a.active, nav a:hover { color: var(--accent); }
main { padding: 1.25rem 1.5rem; max-width: 1200px; margin: 0 auto; }
.empty, .error { color: var(--muted); font-style: italic; }

/* phase strip */
.phases { display: flex; gap: 0; margin: .5rem 0 1.25rem; }
.phase { flex: 1; border-top: 3px solid var(--muted); position: relative; padding: .5rem .25rem 0 0; font-size: .8rem; color: var(--muted); }
.phase.done { border-top-color: var(--good); }
.phase.cur { border-top-color: var(--accent); color: var(--text); }
.phase .name { display: block; font-weight: 600; }
.phase .m { position: absolute; top: -7px; width: 10px; height: 10px; border-radius: 50%; background: var(--panel); border: 2px solid var(--muted); }
.phase .m:nth-of-type(1) { left: 0; } .phase .m:nth-of-type(2) { left: 14px; } .phase .m:nth-of-type(3) { left: 28px; }
.phase .m:nth-of-type(4) { left: 42px; } .phase .m:nth-of-type(5) { left: 56px; } .phase .m:nth-of-type(n+6) { display: none; }
.phase .m.phase-done, .phase .m.release { border-color: var(--good); background: var(--good); }
.phase .m.incident { border-color: var(--bad); }

/* groups and tiles */
.grp { margin: 1rem 0 .4rem; font-size: .7rem; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); font-weight: 700; }
.tiles { display: grid; grid-template-columns: repeat(4, 1fr); gap: .75rem; }
@media (max-width: 900px) { .tiles { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 520px) { .tiles { grid-template-columns: 1fr; } }
.tile { position: relative; overflow: hidden; background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: .7rem .85rem; min-height: 104px; }
.tile svg { position: absolute; left: 0; right: 0; bottom: 0; width: 100%; height: 66%; pointer-events: none; }
.tile .area { fill: var(--accent); fill-opacity: .06; }
.tile .line { fill: none; stroke: var(--accent); stroke-opacity: .35; stroke-width: 1.5; vector-effect: non-scaling-stroke; }
.tile.good .area { fill: var(--good); } .tile.good .line { stroke: var(--good); }
.tile.bad .area { fill: var(--bad); } .tile.bad .line { stroke: var(--bad); }
.tile.stale .area { fill: var(--stale); } .tile.stale .line { stroke: var(--stale); stroke-dasharray: 3 3; }
.tile .l, .tile .v, .tile .d { position: relative; }
.tile .l { font-size: .78rem; color: var(--muted); }
.tile .v { font-size: 1.7rem; font-weight: 700; line-height: 1.2; }
.tile .d { font-size: .76rem; color: var(--muted); }
.tile.good .d { color: var(--good); } .tile.bad .d { color: var(--bad); }
.tile.stale .d::before { content: "⚠ "; }

/* charts, tables, story */
.chart-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(420px, 1fr)); gap: 1rem; }
@media (max-width: 520px) { .chart-grid { grid-template-columns: 1fr; } }
.chart-block { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: .6rem .75rem; }
.chart-block h3 { font-size: .85rem; margin: 0 0 .1rem; font-weight: 600; }
.chart-block .note { font-size: .74rem; color: var(--muted); margin: 0 0 .4rem; }
.chart-block .plot { min-height: 160px; }
.toolbar { display: flex; gap: .75rem; align-items: center; margin: .5rem 0 1rem; font-size: .85rem; color: var(--muted); }
.toolbar select, .toolbar button { font: inherit; padding: .2rem .4rem; }
table { border-collapse: collapse; width: 100%; margin-bottom: 1.5rem; font-size: .88rem; }
th, td { border-bottom: 1px solid var(--border); padding: .35rem .5rem; text-align: left; }
th { color: var(--muted); font-weight: 500; font-size: .74rem; text-transform: uppercase; letter-spacing: .05em; }
td.n { text-align: right; font-variant-numeric: tabular-nums; }
td.good { color: var(--good); } td.bad { color: var(--bad); }
.story-phase { margin: 0 0 2rem; padding-top: .5rem; border-top: 1px solid var(--border); }
.story-phase h2 { font-size: 1.05rem; margin: .25rem 0; }
.story-phase .when { color: var(--muted); font-size: .8rem; }
.story-phase ul { padding-left: 1.2rem; font-size: .88rem; }
.foot { margin-top: 1.25rem; font-size: .72rem; color: var(--muted); display: flex; justify-content: space-between; gap: 1rem; flex-wrap: wrap; }
.status-bar { display: flex; height: 14px; border-radius: 4px; overflow: hidden; margin: .5rem 0 1rem; }
.status-bar span { display: block; height: 100%; }
.status-bar .open { background: var(--bad); } .status-bar .pinned { background: var(--accent); } .status-bar .carried { background: var(--muted); } .status-bar .fixed { background: var(--good); }
@media print { header, .toolbar { display: none; } main { max-width: none; padding: 0; } body { background: #fff; color: #000; } }
```

- [ ] **Step 6: Run to verify they pass**

Run: `cd frontend && npx vitest --run --config vitest.dashboard.config.js` → all pass.

- [ ] **Step 7: Commit**

```bash
git add dashboard
```
Commit message: `feat(dashboard): boot, styles, phase strip, status tiles and the Overview page`.

### Task 18: Charts, the Explore page, the Story page

**Files:**
- Create: `dashboard/lib/chart.js`
- Create: `dashboard/pages/explore.js`, `dashboard/pages/story.js` (replace the stubs)
- Create: `dashboard/explore.html`, `dashboard/story.html`
- Create: `dashboard/tests/explore.test.js`, `dashboard/tests/story.test.js`

**Interfaces:**
- `chart.seriesFor(metric, mode) -> {xs: number[], ys: (number|null)[], labels: string[]}` where
  `mode` is `"daily"` or `"commits"`; `xs` are unix seconds; `labels` are `sha` short forms for
  commits and empty strings for daily. Pure.
- `chart.milestoneMarks(site, xs) -> {x: number, label: string}[]` (milestones whose date falls
  within the series' x-range). Pure.
- `chart.mount(el, metric, mode, site) -> uPlot | null` — draws with `window.uPlot` when
  present (browser) and returns `null` otherwise (tests), after writing a `.plot` div with
  `data-points="<n>"` so tests can assert what would be drawn.
- `chart.block(metric, mode, site) -> Element` — `.chart-block` with `h3` label, `.note`,
  the `.plot`.

- [ ] **Step 1: Write the failing tests**

`dashboard/tests/explore.test.js`:

```js
import { beforeEach, describe, expect, it } from 'vitest';
import site from './fixtures/site.json';
import { milestoneMarks, seriesFor } from '../lib/chart.js';
import { render } from '../pages/explore.js';

describe('chart helpers', () => {
  it('builds a daily series with gaps and a commit series', () => {
    const m = site.groups.safety_net[0];
    const daily = seriesFor(m, 'daily');
    expect(daily.xs.length).toBe(3);
    expect(daily.ys).toEqual([200, 249, 249]);
    const commits = seriesFor(m, 'commits');
    expect(commits.ys).toEqual([0, 249]);
    expect(commits.labels).toEqual(['fd413f0c', '75a68555']);
    expect(seriesFor(site.groups.security[0], 'commits').xs).toEqual([]);
    expect(seriesFor(site.groups.safety_net[1], 'daily').ys).toEqual([null, null, null]);
  });
  it('places milestone marks inside the x-range only', () => {
    const m = site.groups.safety_net[0];
    expect(milestoneMarks(site, seriesFor(m, 'commits').xs).map((x) => x.label)).toEqual(['v0.29.0 baseline', 'Phase 0 done']);
    expect(milestoneMarks(site, seriesFor(m, 'daily').xs).map((x) => x.label)).toEqual(['Phase 0 done']);
  });
});

describe('explore page', () => {
  let root;
  beforeEach(() => { document.body.innerHTML = '<main id="root"></main>'; root = document.getElementById('root'); });
  it('renders every catalogued metric grouped, with note and mode toggle', () => {
    render(site, root, new URLSearchParams(''));
    expect(root.querySelectorAll('.chart-block').length).toBe(4);
    expect([...root.querySelectorAll('.grp')].map((g) => g.textContent)).toEqual(['Safety net', 'Security', 'Extraction readiness']);
    expect(root.querySelector('[data-id="e2e_scenarios"] .note').textContent).toBe('Playwright test() call sites.');
    expect(root.querySelector('[data-id="e2e_scenarios"] .plot').dataset.points).toBe('2');
    expect(root.querySelector('[data-id="codeql_open_critical_high"] .plot').dataset.points).toBe('3');
  });
  it('honours ?mode=daily', () => {
    render(site, root, new URLSearchParams('mode=daily'));
    expect(root.querySelector('[data-id="e2e_scenarios"] .plot').dataset.points).toBe('3');
  });
});
```

`dashboard/tests/story.test.js`:

```js
import { beforeEach, describe, expect, it } from 'vitest';
import site from './fixtures/site.json';
import { render } from '../pages/story.js';

describe('story page', () => {
  let root;
  beforeEach(() => { document.body.innerHTML = '<main id="root"></main>'; root = document.getElementById('root'); });
  it('renders one section per phase with dates, summary, milestones and headline charts', () => {
    render(site, root);
    const phases = root.querySelectorAll('.story-phase');
    expect(phases.length).toBe(2);
    expect(phases[0].querySelector('h2').textContent).toBe('Investigate');
    expect(phases[0].querySelector('.when').textContent).toBe('from 19 Aug');
    expect(phases[1].querySelector('.when').textContent).toBe('3 Sep – 3 Sep');
    expect(phases[1].querySelector('li').textContent).toContain('Phase 0 done');
    expect(phases[1].querySelector('li a').getAttribute('href')).toBe('https://github.com/D10Scot/Dispatcharr/pull/155');
    expect(phases[0].querySelectorAll('.chart-block').length).toBe(1);
    expect(phases[1].querySelector('.chart-block h3').textContent).toBe('Open CodeQL critical + high');
  });
});
```

Run: `cd frontend && npx vitest --run --config vitest.dashboard.config.js` → failures in the
two new files.

- [ ] **Step 2: Write `lib/chart.js`**

```js
// uPlot wrappers plus the pure series builders the tests exercise.
import { h } from './dom.js';
import { shortSha } from './format.js';

const DAY = 86400;

function unix(iso) {
  return Math.floor(new Date(iso.length === 10 ? `${iso}T00:00:00Z` : iso).getTime() / 1000);
}

export function seriesFor(metric, mode) {
  if (mode === 'commits') {
    const commits = metric.commits || [];
    return { xs: commits.map((c) => unix(c[1])), ys: commits.map((c) => c[2]), labels: commits.map((c) => shortSha(c[0])) };
  }
  const daily = metric.daily || [];
  return { xs: daily.map((d) => unix(d[0])), ys: daily.map((d) => d[1]), labels: daily.map(() => '') };
}

export function milestoneMarks(site, xs) {
  if (xs.length === 0) return [];
  const first = Math.min(...xs);
  const lo = first - (first % DAY); // milestones carry a date, not a time: compare from the day's start
  const hi = Math.max(...xs) + DAY - 1;
  return (site.milestones || [])
    .map((m) => ({ x: unix(m.date), label: m.label }))
    .filter((m) => m.x >= lo && m.x <= hi);
}

export function mount(el, metric, mode, site) {
  const { xs, ys, labels } = seriesFor(metric, mode);
  const plot = h('div', { class: 'plot', 'data-points': String(xs.length) });
  el.append(plot);
  if (typeof window === 'undefined' || !window.uPlot || xs.length === 0) return null;
  const marks = milestoneMarks(site, xs);
  const opts = {
    width: Math.max(el.clientWidth - 24, 320),
    height: 160,
    scales: { x: { time: true } },
    axes: [{ grid: { show: false } }, { size: 56 }],
    series: [
      { label: mode === 'commits' ? 'commit' : 'day', value: (u, v, sidx, idx) => labels[idx] || new Date(v * 1000).toISOString().slice(0, 10) },
      { label: metric.label, stroke: cssVar('--accent'), width: 1.5, spanGaps: false, points: { show: mode === 'commits' } },
    ],
    hooks: {
      draw: [(u) => {
        const ctx = u.ctx;
        ctx.save();
        ctx.strokeStyle = cssVar('--muted');
        ctx.setLineDash([4, 4]);
        for (const m of marks) {
          const x = u.valToPos(m.x, 'x', true);
          ctx.beginPath(); ctx.moveTo(x, u.bbox.top); ctx.lineTo(x, u.bbox.top + u.bbox.height); ctx.stroke();
        }
        ctx.restore();
      }],
    },
  };
  return new window.uPlot(opts, [xs, ys], plot);
}

export function block(metric, mode, site) {
  const el = h('div', { class: 'chart-block', 'data-id': metric.id },
    h('h3', { text: metric.label }),
    h('p', { class: 'note', text: metric.note || '' }));
  mount(el, metric, mode, site);
  return el;
}

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#4da3ff';
}
```

- [ ] **Step 3: Write the two pages and their HTML**

`dashboard/pages/explore.js`:

```js
import { block } from '../lib/chart.js';
import { h } from '../lib/dom.js';
import { footer, GROUP_LABELS, GROUP_ORDER } from '../lib/status.js';

export function render(site, root, params = new URLSearchParams('')) {
  const mode = params.get('mode') === 'daily' ? 'daily' : 'commits';
  root.replaceChildren();
  root.append(h('div', { class: 'toolbar' },
    h('span', { text: 'Resolution:' }),
    h('a', { href: '?mode=commits', text: 'per commit', class: mode === 'commits' ? 'active' : '' }),
    h('a', { href: '?mode=daily', text: 'daily', class: mode === 'daily' ? 'active' : '' }),
    h('span', { text: '· dashed lines are milestones' })));
  for (const g of GROUP_ORDER) {
    const metrics = site.groups[g] || [];
    if (metrics.length === 0) continue;
    root.append(h('div', { class: 'grp', text: GROUP_LABELS[g] }));
    // Derived series have no per-commit points; show them daily whatever the toggle says.
    root.append(h('div', { class: 'chart-grid' }, metrics.map((m) => block(m, m.commits ? mode : 'daily', site))));
  }
  root.append(footer(site));
}
```

`dashboard/pages/story.js`:

```js
import { block } from '../lib/chart.js';
import { h } from '../lib/dom.js';
import { fmtDate } from '../lib/format.js';
import { footer } from '../lib/status.js';

const PR_URL = 'https://github.com/D10Scot/Dispatcharr/pull/';

export function render(site, root) {
  root.replaceChildren();
  const byId = Object.fromEntries(Object.values(site.groups).flat().map((m) => [m.id, m]));
  for (const p of site.phases) {
    const when = p.end ? `${fmtDate(p.start)} – ${fmtDate(p.end)}` : p.start ? `from ${fmtDate(p.start)}` : 'not started';
    const section = h('section', { class: 'story-phase', id: p.id },
      h('h2', { text: p.label }),
      h('div', { class: 'when', text: when }),
      h('p', { text: p.summary }),
      h('ul', {}, p.milestones.map((m) => h('li', {},
        `${fmtDate(m.date)} · ${m.label}`,
        m.pr ? [' (', h('a', { href: `${PR_URL}${m.pr}`, text: `#${m.pr}` }), ')'] : null,
        ` — ${m.summary}`))),
      h('div', { class: 'chart-grid' }, p.headline_ids.filter((id) => byId[id]).map((id) => block(byId[id], 'daily', site))));
    root.append(section);
  }
  root.append(footer(site));
}
```

`dashboard/explore.html` and `dashboard/story.html`: copies of `index.html` with the
`<title>` suffix, the matching `nav a.active`, and `<main data-page="explore">` /
`<main data-page="story">`.

Ideally milestone shading of the phase window on Story charts would use uPlot's `bands`;
the dashed milestone lines already mark the window's edges, which is enough for a first
version and keeps `chart.js` to one drawing hook.

- [ ] **Step 4: Run to verify they pass**

Run: `cd frontend && npx vitest --run --config vitest.dashboard.config.js` → all pass.

- [ ] **Step 5: Commit**

```bash
git add dashboard
```
Commit message: `feat(dashboard): uPlot charts with milestone lines; Explore and Story pages`.

### Task 19: Compare and Defects pages

**Files:**
- Create: `dashboard/pages/compare.js`, `dashboard/pages/defects.js` (replace stubs)
- Create: `dashboard/compare.html`, `dashboard/defects.html`
- Create: `dashboard/tests/compare-page.test.js`, `dashboard/tests/defects.test.js`

- [ ] **Step 1: Write the failing tests**

`dashboard/tests/compare-page.test.js`:

```js
import { beforeEach, describe, expect, it } from 'vitest';
import site from './fixtures/site.json';
import { render } from '../pages/compare.js';

const A = 'fd413f0cc4ab3131789a68fb31f1ae622ae7371a';
const B = '75a68555b931e7d088bfbbd859b35e6e27064312';

describe('compare page', () => {
  let root;
  beforeEach(() => { document.body.innerHTML = '<main id="root"></main>'; root = document.getElementById('root'); });
  it('defaults to baseline -> latest milestone and marks deltas', () => {
    render(site, root, new URLSearchParams(''));
    const selects = root.querySelectorAll('select');
    expect(selects[0].value).toBe(A); expect(selects[1].value).toBe(B);
    const rows = [...root.querySelectorAll('tbody tr')];
    expect(rows.length).toBe(2);
    const e2e = rows.find((r) => r.textContent.includes('E2E scenarios'));
    expect(e2e.querySelector('td.delta').classList.contains('good')).toBe(true);
    expect(e2e.querySelector('td.delta').textContent).toBe('+249');
    const rev = rows.find((r) => r.textContent.includes('Reverse imports'));
    expect(rev.querySelector('td.delta').textContent).toBe('±0');
  });
  it('accepts ?from=&to= and groups rows', () => {
    render(site, root, new URLSearchParams(`from=${B}&to=${A}`));
    expect(root.querySelector('tbody tr td.delta').textContent).toBe('−249');
    expect([...root.querySelectorAll('th.group')].map((t) => t.textContent)).toEqual(['Safety net', 'Extraction readiness']);
  });
});
```

`dashboard/tests/defects.test.js`:

```js
import { beforeEach, describe, expect, it } from 'vitest';
import site from './fixtures/site.json';
import { render } from '../pages/defects.js';

describe('defects page', () => {
  let root;
  beforeEach(() => { document.body.innerHTML = '<main id="root"></main>'; root = document.getElementById('root'); });
  it('groups entries by status and links issue, test and PR', () => {
    render(site, root);
    expect([...root.querySelectorAll('h2')].map((x) => x.textContent)).toEqual(['Pinned by a test (1)', 'Fixed (1)']);
    const pinned = root.querySelector('#status-pinned tbody tr');
    expect(pinned.querySelector('a[href="https://github.com/D10Scot/Dispatcharr/issues/80"]')).not.toBeNull();
    expect(pinned.querySelector('a[href$="e2e/tests/seeded/output-m3u.spec.ts"]')).not.toBeNull();
    const fixed = root.querySelector('#status-fixed tbody tr');
    expect(fixed.querySelector('a[href="https://github.com/D10Scot/Dispatcharr/pull/154"]')).not.toBeNull();
    const bar = root.querySelector('.status-bar');
    expect(bar.querySelector('.pinned').style.width).toBe('50%');
    expect(bar.querySelector('.fixed').style.width).toBe('50%');
  });
});
```

- [ ] **Step 2: Write the pages**

`dashboard/pages/compare.js`:

```js
import { rowsFor } from '../lib/compare.js';
import { h } from '../lib/dom.js';
import { fmt, fmtDate, fmtDelta, shortSha } from '../lib/format.js';
import { footer, GROUP_LABELS, GROUP_ORDER } from '../lib/status.js';

export function render(site, root, params = new URLSearchParams('')) {
  const ms = site.milestones;
  const from = params.get('from') || ms[0].sha;
  const to = params.get('to') || ms[ms.length - 1].sha;
  root.replaceChildren();
  const select = (name, value) => h('select', { name, onchange: (e) => navigate(e.target.form) },
    ms.map((m) => h('option', { value: m.sha, selected: m.sha === value ? 'selected' : null, text: `${fmtDate(m.date)} · ${m.label} (${shortSha(m.sha)})` })));
  const form = h('form', { class: 'toolbar', method: 'get' }, h('span', { text: 'From' }), select('from', from), h('span', { text: 'to' }), select('to', to),
    h('button', { type: 'submit', text: 'Compare' }), h('button', { type: 'button', text: 'Print', onclick: () => window.print() }));
  root.append(form);

  const rows = rowsFor(site, from, to);
  const table = h('table', {}, h('thead', {}, h('tr', {},
    h('th', { text: 'Metric' }), h('th', { text: `at ${shortSha(from)}` }), h('th', { text: `at ${shortSha(to)}` }), h('th', { text: 'Delta' }))));
  const body = h('tbody');
  for (const g of GROUP_ORDER) {
    const inGroup = rows.filter((r) => r.group === g);
    if (inGroup.length === 0) continue;
    body.append(h('tr', {}, h('th', { class: 'group', colspan: '4', text: GROUP_LABELS[g] })));
    for (const r of inGroup) {
      const cls = r.good === true ? 'good' : r.good === false ? 'bad' : '';
      body.append(h('tr', {}, h('td', { text: r.label }), h('td', { class: 'n', text: fmt(r.from, r.unit) }),
        h('td', { class: 'n', text: fmt(r.to, r.unit) }), h('td', { class: `n delta ${cls}`, text: fmtDelta(r.delta, r.unit) })));
    }
  }
  if (rows.length === 0) body.append(h('tr', {}, h('td', { colspan: '4', class: 'empty', text: 'No snapshot metric has a value at both commits.' })));
  table.append(body);
  root.append(table, footer(site));
}

function navigate(form) {
  if (typeof window === 'undefined') return;
  const q = new URLSearchParams(new FormData(form));
  window.location.search = `?${q}`;
}
```

`dashboard/pages/defects.js`:

```js
import { h } from '../lib/dom.js';
import { fmtDate } from '../lib/format.js';
import { footer } from '../lib/status.js';

const REPO = 'https://github.com/D10Scot/Dispatcharr';
const ORDER = [['open', 'Open'], ['pinned', 'Pinned by a test'], ['carried', 'Carried as a constraint'], ['fixed', 'Fixed']];

export function render(site, root) {
  root.replaceChildren();
  const latest = site.defects.by_status_daily[site.defects.by_status_daily.length - 1];
  const counts = latest ? latest[1] : { open: 0, pinned: 0, carried: 0, fixed: 0 };
  const total = Object.values(counts).reduce((a, b) => a + b, 0) || 1;
  root.append(h('div', { class: 'status-bar', title: ORDER.map(([k, l]) => `${l}: ${counts[k]}`).join(' · ') },
    ORDER.map(([k]) => h('span', { class: k, style: `width:${(100 * counts[k]) / total}%` }))));
  for (const [status, label] of ORDER) {
    const entries = site.defects.entries.filter((d) => d.status === status);
    if (entries.length === 0) continue;
    root.append(h('h2', { text: `${label} (${entries.length})` }));
    root.append(h('table', { id: `status-${status}` }, h('thead', {}, h('tr', {},
      h('th', { text: 'Defect' }), h('th', { text: 'Area' }), h('th', { text: 'Severity' }), h('th', { text: 'Evidence' }), h('th', { text: 'Since' }))),
      h('tbody', {}, entries.map((d) => h('tr', {},
        h('td', { text: d.title }), h('td', { text: d.area }), h('td', { text: d.severity }),
        h('td', {}, evidence(d)), h('td', { text: fmtDate(d.status_changed) }))))));
  }
  root.append(footer(site));
}

function evidence(d) {
  const links = [];
  if (d.issue) links.push(h('a', { href: `${REPO}/issues/${d.issue}`, text: `#${d.issue}` }));
  if (d.test) links.push(h('a', { href: `${REPO}/blob/main/${d.test}`, text: d.test.split('/').pop() }));
  if (d.fixed_in) links.push(h('a', { href: `${REPO}/pull/${d.fixed_in}`, text: `PR #${d.fixed_in}` }));
  if (d.carried_as) links.push(h('a', { href: `${REPO}/blob/main/${d.carried_as}`, text: 'spec' }));
  if (!links.length && d.source) links.push(h('a', { href: `${REPO}/blob/main/${d.source}`, text: 'CLAUDE.md' }));
  return links.flatMap((l, i) => (i ? [' · ', l] : [l]));
}
```

`dashboard/compare.html`, `dashboard/defects.html`: copies of `index.html` with the matching
title suffix, `nav a.active` and `data-page`.

- [ ] **Step 3: Run to verify they pass**

Run: `cd frontend && npx vitest --run --config vitest.dashboard.config.js` → all pass. If the
`style.width` assertion fails with `50%` vs `50.00%`, format the width with `Math.round`.

- [ ] **Step 4: Preview against real data**

```bash
git fetch origin metrics-data && rm -rf /tmp/md && git worktree add /tmp/md origin/metrics-data
python -m metrics.build --data /tmp/md --curated metrics/curated --out dashboard/site.json
(cd dashboard && python3 -m http.server 8123)
```
Open http://localhost:8123/ and walk all five pages in light and dark mode. `dashboard/site.json`
is gitignored (Task 15).

- [ ] **Step 5: Commit**

```bash
git add dashboard
```
Commit message: `feat(dashboard): Compare (print-friendly) and Defects pages`.

### Task 20: `pages.yml` runs the build step; README; open PR C; verify the live site

**Files:**
- Modify: `.github/workflows/pages.yml` (the `build` job's steps)
- Rewrite: `dashboard/README.md`

- [ ] **Step 1: Replace the `Assemble site` step**

In `.github/workflows/pages.yml`, keep the two checkouts, replace the `Assemble site` step
with these three, and add `metrics/**` and `scripts/run_metrics_tests.sh` to the `push`
`paths:` list. Change the schedule to `'15 6 * * *'` (daily, after the 06:00 metrics run) and
update the header comment's "weekly" wording.

```yaml
      - name: Install the build step's one dependency (hash-pinned)
        working-directory: main
        run: python3 -m pip install --require-hashes -r metrics/requirements.txt

      - name: Validate curated files online and build site.json
        # --check-prs needs the API; GITHUB_TOKEN is enough for merged-state reads.
        working-directory: main
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          set -euo pipefail
          python3 -m metrics.build --validate-only --curated metrics/curated --check-prs
          python3 -m metrics.build --data ../metrics-data --curated metrics/curated --out "$RUNNER_TEMP/site/site.json"

      - name: Assemble site
        id: assemble
        run: |
          set -euo pipefail
          site="$RUNNER_TEMP/site"
          cp -r main/dashboard/. "$site/"
          rm -rf "$site/tests"
          {
            echo "site_dir<<SITE_DIR_EOF"
            echo "$site"
            echo "SITE_DIR_EOF"
          } >> "$GITHUB_OUTPUT"
```

The `build` job needs `fetch-depth: 0` on the `main` checkout (milestone SHAs are validated
as first-parent commits since the baseline) — add it to that checkout step. Zero zizmor
findings on save.

- [ ] **Step 2: Rewrite `dashboard/README.md`**

```markdown
# Engineering metrics dashboard

Static pages over one `site.json`, published to GitHub Pages by
`.github/workflows/pages.yml`. The pages draw; they never compute. Every
number comes from `python -m metrics.build` (see `docs/agents/metrics.md`
and the design spec it points to).

- `index.html` Overview — phase strip, twenty headline tiles in five groups,
  freshness footer. A tile's background is the daily series in the status
  colour (good / bad / neutral / stale).
- `story.html` — one section per phase: dates, summary, milestones with PR
  links, the headline charts that phase was meant to move.
- `explore.html` — every catalogued metric, per-commit (default) or daily
  (`?mode=daily`), milestone lines.
- `compare.html` — two milestones, one delta table per group; `?from=&to=`;
  print-friendly.
- `defects.html` — the known-defect ledger by status.

`app.js` boots the page named in `<main data-page>`; `lib/` holds pure
helpers (format, spark paths, compare rows) and the shared visual pieces;
`pages/` one module per page; `vendor/uplot/` the vendored chart library
(hash-pinned, see its README). No build step, no framework, ES modules.

## Tests and preview

```bash
cd frontend && npx vitest --run --config vitest.dashboard.config.js
git fetch origin metrics-data && git worktree add /tmp/md origin/metrics-data
python -m metrics.build --data /tmp/md --curated metrics/curated --out dashboard/site.json
cd dashboard && python3 -m http.server 8123
```
```

- [ ] **Step 3: Commit and open PR C**

```bash
git add .github/workflows/pages.yml dashboard/README.md
```
Commit message: `ci(pages): build site.json with the metrics build step; daily publish`.
PR C title: `metrics: the dashboard pages over site.json (Part C)`.

- [ ] **Step 4: After merge — dispatch and verify the live site**

```bash
gh workflow run pages.yml --repo D10Scot/Dispatcharr
gh run watch --repo D10Scot/Dispatcharr
curl -s https://d10scot.github.io/Dispatcharr/site.json | python3 -c "import json,sys; s=json.load(sys.stdin); print(s['meta']['built_at'], len(s['headline']), s['meta']['source_notes'])"
```
Expected: a fresh `built_at`, `20`, and the Dependabot note. Open the five pages in a
browser; the Overview must show today's CodeQL count and `stale` only on series that are
genuinely behind (coverage until its first daily run).

---

## Self-review against the spec

- §2 defects: Task 2 (pagination), Task 4 (independent families), Task 16 (dashboard
  replaced), Task 3 (backfillable history via event dumps).
- §4.1–4.4 data layer: Tasks 3–7. §4.2 sidecars: Task 3. Cadence: Task 6.
- §5 curated files + contract: Tasks 9, 10, 15. Validators in hook/gate/CI: Tasks 1, 20.
- §6 build step: Tasks 11–14; every listed derivation exists in Task 12's registry and the
  catalogue (Task 10) references only those names.
- §7 workflows: Tasks 6 and 20; hook rules: Task 1.
- §8 pages: Tasks 17 (Overview), 18 (Story, Explore), 19 (Compare, Defects). Soft-contrast
  tile background per the brainstorm: Task 17 CSS (`fill-opacity .06`, `stroke-opacity .35`).
- §9 testing: unit tests in every task; the fake `gh` in Task 2; real-file validation in
  Task 10; vitest without Playwright in Tasks 16–19.
- §10 migration order: Parts A → B → C, retirements in Tasks 7 and 16, `.superpowers/` was
  ignored with the spec commit.
- Not covered by design: the Dependabot PAT and secret-scanning toggle (spec §11).

