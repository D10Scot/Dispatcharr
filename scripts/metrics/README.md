# Engineering metrics collectors

Stdlib-only (mostly) scripts that emit one JSON object per "metric family",
appended as JSONL rows to the orphan `metrics-data` branch by
`.github/workflows/metrics.yml` (weekly + on push to `main` + manual
backfill). See `CLAUDE.md` and the M1/M2 planning docs for the overall
architecture. This file is the stable field contract for downstream
consumers (the M3 dashboard) — family/field names here should not change
without updating this file in the same PR.

Row shape (all families): `{"timestamp": <ISO-8601 UTC>, "commit_sha": <sha>,
"family": <name>, "metrics": {...}}`, one line per run, appended to
`<family>.jsonl`. Appends are idempotent on `(commit_sha, family)`.

## Checkout-scanning families (M1)

Run against `--repo-root`, stdlib-only (AST/grep over the working tree), and
backfillable against any historical commit via `backfill.py`.

- **code_health** (`collect_code_health.py`): debt markers — bare/broad
  except handlers, function-local imports, `os.environ` reads, LOC per app.
- **architecture** (`collect_architecture.py`): extraction-progress facts —
  cross-app import edges/cycles, `apps/proxy` ORM writes, reverse imports
  into proxy, the models.py boot-cycle-trap import count.
- **tests** (`collect_tests.py`): test counts by kind (backend/frontend/e2e/
  greybox/hypothesis-property). `coverage` (backend) stays `null` —
  deferred, needs a Postgres matrix run. `frontend_coverage_pct` is **not**
  produced by this script; see "Weekly-only frontend coverage" below.

## GitHub-API-backed families (M2)

Run against `--repo <owner/repo>` via the `gh` CLI (network + `GITHUB_TOKEN`
required). **Not backfillable** — they report live repo/API state (open
alert counts, trailing-30-day CI/PR stats), not a fact attributable to a
specific historical commit, so `backfill.py` explicitly skips them
(`--skip-families security,delivery,agentic`). Their series starts at
whatever commit_sha happens to be HEAD the first time `collect_all.py` runs
each one — every row still carries the `_notes` field explaining this.

- **security** (`collect_security.py`):
  - `codeql_open_by_severity` / `codeql_open_by_language`: open code-scanning
    alert counts, keyed by CodeQL's `security_severity_level` or language pack.
  - `dependabot_open_by_severity`: open Dependabot alert counts by severity,
    or `null` if the endpoint is forbidden for this repo.
  - `secret_scanning_open_count`: open secret-scanning alerts, or `null`
    when the feature is disabled (currently the case for this repo) or
    inaccessible.
- **delivery** (`collect_delivery.py`), trailing 30-day window:
  - `ci_by_workflow`: `{workflow_name: {run_count, pass_rate,
    median_duration_seconds}}` for every workflow with completed runs in
    the window.
  - `pr_lead_time_seconds` / `pr_lead_time_by_author_type`: `{median, p90,
    count}` open→merge time for merged PRs, overall and split into
    `human`/`agent` buckets. See the module docstring for the exact
    human/agent heuristic (bot logins + gh-aw branch-name patterns count as
    agent; a person driving Copilot CLI interactively still counts as
    human).
- **agentic** (`collect_agentic.py`):
  - `issues_by_label`: `{open, closed}` counts for each of the five triage
    labels (`needs-triage`, `needs-info`, `ready-for-agent`,
    `ready-for-human`, `wontfix`) plus `fuzzing`. A label with zero issues
    (or that doesn't exist yet) reports `{"open": 0, "closed": 0}`, not an
    error.
  - `median_time_to_triage_seconds`: median seconds from issue creation to
    `needs-triage` label removal, scanned over the most recent 200 issues
    (see docstring for why it's capped). `null` if no issue has ever had the
    label removed.

## Weekly-only frontend coverage

`collect_tests.py` stays execution-free (cheap, backfillable) on purpose, so
frontend coverage is **not** computed there. Instead, on `schedule`-triggered
runs only, `metrics.yml` separately runs `vitest run --coverage
--coverage.reporter=json-summary`, extracts `total.lines.pct` from
`coverage-summary.json`, and merges it into the `tests` family row via
`collect_all.py --extra-metrics tests=<path-to-json>` — so the
`frontend_coverage_pct` field is present only on weekly rows, absent on
push-triggered rows (a gap the dashboard must handle, e.g. by
forward-filling or only plotting weekly points for that one series).

Backend coverage remains fully deferred (needs a Postgres test-matrix run);
`collect_tests.py`'s `coverage` field stays `null` with a note.

## Running locally

```bash
# checkout-scanning families only
python3 scripts/metrics/collect_all.py --repo-root . --out-dir /tmp/metrics-out \
  --skip-families security,delivery,agentic

# everything, including the GitHub API families (needs `gh auth login`)
python3 scripts/metrics/collect_all.py --repo-root . --out-dir /tmp/metrics-out \
  --repo D10Scot/Dispatcharr

# any single collector directly
python3 scripts/metrics/collect_security.py --repo D10Scot/Dispatcharr
```
