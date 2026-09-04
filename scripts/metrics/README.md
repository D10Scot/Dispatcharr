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
