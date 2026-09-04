# Engineering metrics dashboard — design

**Date:** 2026-09-04
**Status:** approved design, not yet planned or implemented
**Supersedes:** the M1/M2/M3 metrics work merged as PRs #40, #46 and #47 (2026-08-29)

## 1. Purpose

Two audiences, one page set:

1. **The maintainer, over the life of the migration.** Phase 0 is done; Phases 1–3 (extract the relay, optionally Go, remove Redis from the data path) will run for months. The dashboard must show, at any point, where each key number stands against its baseline and its target, and it must keep doing so without hand-feeding.
2. **An engineering team, once.** A short talk on migrating applications and working in codebases you don't understand. The talk needs before/after numbers at phase boundaries and a phase-by-phase narrative with the evidence attached.

Both are served by the same data. The design principle that follows from the maintainer's stated preference ("I'd rather have more data than less, we can always dispose of it"): **collect broadly and cheaply, keep everything, and let the front page do the curating.**

## 2. What exists and why it is being replaced

The current stack (see `scripts/metrics/README.md`, `dashboard/README.md`, `.github/workflows/metrics.yml`, `.github/workflows/pages.yml`) has the right bones and three defects that the design corrects rather than patches.

| Component | Keep | Change |
|---|---|---|
| `metrics-data` orphan branch as the only store, pure data | yes | add event dumps and a coverage family |
| Checkout-scanning collectors (`code_health`, `architecture`, `tests`) with per-commit backfill | yes | regression tests; no behaviour change |
| API-backed collectors (`security`, `delivery`, `agentic`) appending snapshot rows | no | become event-dump collectors (§4.2) |
| `dashboard/` (three views, one card per numeric key) | no | replaced by five pages over a build-time `site.json` (§6) |
| `pages.yml` copying JSONL into the site | partly | runs the build step instead of copying |
| Static GitHub Pages, no build step in the browser, vendored uPlot | yes | unchanged |

The three defects:

1. **The dashboard enumerates instead of curating.** It renders a card for every numeric leaf across every family — over a hundred tiles including each `loc_per_app` and each CI workflow — with no notion of which direction is good, no targets and no narrative.
2. **The pipeline has been broken since 2026-09-01.** `collect_delivery.py` parses `gh api --paginate` output as a single JSON document; multi-page responses are concatenated arrays and fail with `JSONDecodeError: Extra data`. `collect_all.py` runs collectors in sequence with `check=True`, so the failure also stops every family after it. The published site still shows 2026-08-29 data (49 e2e scenarios; the collector reports 249 today).
3. **"Not backfillable" is a false premise for the API families.** CodeQL alerts carry `created_at`, `fixed_at` and `dismissed_at`; pull requests and workflow runs carry timestamps; issues have label event timelines. Any "as of date D" number is derivable from the current full record set, back to when the data began (2026-08-23 for CodeQL). Snapshot-appending threw that history away.

Two gaps: backend coverage is `null` everywhere (no coverage configuration exists), and frontend coverage exists on four weekly rows only.

## 3. Architecture

Three layers with hard boundaries. Data flows one way.

```
collectors (CI)  ──►  metrics-data branch  ──►  build step (CI, Python)  ──►  site.json  ──►  static pages (browser)
                                     ▲
                      metrics/curated/*.yml (in main, agent-maintained)
```

- **Collectors** write only raw facts. They never compute a trend, a delta or a status.
- **The build step** is the only place any derived number is computed. It reads the branch and the curated files, validates both, and emits one `site.json`. Pure Python, stdlib plus PyYAML, unit-tested on fixtures, no Django.
- **The pages** are a small vanilla-JS renderer over `site.json`. They draw; they do not compute.

Every rule about what a metric means, which direction is good, and when a curated file is valid therefore lives in one tested Python package, and an agent can run the same validator CI runs.

## 4. Data layer

### 4.1 Snapshot families (unchanged shape)

`code_health.jsonl`, `architecture.jsonl`, `tests.jsonl`: one row per `(commit_sha, family)`, `{"timestamp", "commit_sha", "family", "metrics"}`, idempotent append, backfillable by detached worktree over first-parent commits since `fd413f0c`. Existing collectors and `backfill.py` are kept as they are, with regression tests added (§9).

One new snapshot family, **`coverage.jsonl`**, written only by the coverage job (§7):

```json
{"timestamp": "...", "commit_sha": "...", "family": "coverage",
 "metrics": {"backend_line_pct": 45.6, "backend_by_app": {"apps.proxy": 38.5, ...},
             "frontend_line_pct": 71.9, "backend_failed_labels": [],
             "backend_status": "ok" | "failed", "frontend_status": "ok" | "failed"}}
```

The backend suite runs one `coverage run -p` process per label and combines; the row carries
`backend_failed_labels` and `backend_status: "failed"` when any label failed, and still
reports the combined pct when `coverage combine` succeeded. The frontend side reports
`frontend_status: "failed"` with a null pct when vitest did not produce a summary. A red
day is a visible point, not a gap. Never backfilled.

### 4.2 Event dumps (new; replace the three API snapshot families)

Under `events/` on the branch, each file is the **full current record set** as returned by the GitHub API, overwritten on every run. Because each record carries its own timestamps, the build step derives any as-of-date series, and a re-run never duplicates history.

| File | Source | Fields kept per record |
|---|---|---|
| `events/codeql_alerts.json` | `/code-scanning/alerts?state=all` | number, state, created_at, fixed_at, dismissed_at, dismissed_reason, rule.id, rule.security_severity_level, tool.name, most_recent_instance.location.path |
| `events/pull_requests.json` | `/pulls?state=all` | number, title, created_at, merged_at, closed_at, user.login, user.type, head.ref, additions, deletions, changed_files, files' paths (for the product-vs-scaffolding split) |
| `events/workflow_runs.json` | `/actions/runs` | id, name, event, status, conclusion, created_at, updated_at, run_started_at, head_sha |
| `events/issues.json` | `/issues?state=all` + `/issues/{n}/timeline` | number, title, state, created_at, closed_at, labels, label events (labeled/unlabeled with timestamps) |
| `events/scorecard.json` | `https://api.securityscorecards.dev/projects/github.com/D10Scot/Dispatcharr` | date, score, checks[] |
| `events/dependabot_alerts.json` | `/dependabot/alerts?state=all` | as CodeQL, or `{"status": "not_permitted", "detail": "..."}` |
| `events/secret_scanning.json` | `/secret-scanning/alerts` | as CodeQL, or `{"status": "disabled" \| "not_permitted"}` |

Each dump carries a top-level `{"fetched_at", "repo", "records": [...]}` envelope, or a `{"fetched_at", "status", "detail"}` envelope when the source is unavailable. **"Not permitted" and "disabled" are recorded explicitly, never as `null`.** Today: Dependabot is 403 under `GITHUB_TOKEN` (a personal token works — a PAT secret is a follow-up, not part of this work); secret scanning is disabled at repo level (404).

Pagination uses `gh api --paginate --slurp` and flattens the page arrays. Because dumps are overwritten, records that fall off an API's retention window (GitHub keeps workflow runs for 90 days) would otherwise be lost, so each collector also maintains a **history sidecar**: any record not previously seen is appended to `events/history/<kind>.jsonl`, keyed by id. The build step reads the union of `events/<kind>.json` and its sidecar, the current record winning on conflict.

The old `security.jsonl`, `delivery.jsonl`, `agentic.jsonl` stay on the branch untouched for provenance and are no longer written. The branch README lists which files are live.

### 4.3 Cadence

| Trigger | What runs |
|---|---|
| push to `main` (existing path filter) | snapshot collectors (~5 s) |
| daily 06:00 UTC | snapshot collectors, event dumps, coverage job |
| `workflow_dispatch` | as daily; `backfill: true` runs the per-commit snapshot backfill |

The weekly schedule and the weekly-only frontend coverage step go away. Every series has at least one point per day.

### 4.4 Collector robustness

`collect_all.py` runs every family and records each outcome; it exits non-zero at the end if any family failed, after writing every family that succeeded. One broken collector can no longer starve the others.

## 5. Curated inputs and their maintenance contract

Three YAML files under `metrics/curated/`. All are validated by the build step, by a unit test, and by the local edit hook. An invalid edit fails the local hook, the commit gate, and the Pages build.

### 5.1 `catalogue.yml` — the metric catalogue

One entry per metric the dashboard may show. Anything a collector emits that is not catalogued is stored but never rendered, so **adding a metric means adding an entry.**

A snapshot-family entry points `path` at a JSON pointer into the row; a
`derived` entry names a `derivation` from `metrics/build/derive.py`'s
`DERIVATIONS` instead, with its arguments in `params` — the two are never
mixed on one entry:

```yaml
- id: e2e_scenarios
  family: tests                      # snapshot family, or "derived"
  path: /e2e_scenario_count          # JSON pointer into the row's metrics (snapshot families only)
  label: E2E scenarios
  unit: count                        # count | pct | seconds | days | score | lines | ratio
  direction: up                      # up | down | zero | info
  target: null                       # number or null
  group: safety_net                  # safety_net | security | extraction | delivery | agents
  headline: true
  since: 2026-08-19                  # first date the series is meaningful
  note: "Playwright test() call sites under e2e/tests/**/*.spec.ts, counted by regex; test.fail() pins count."

- id: codeql_open_critical_high
  family: derived                    # a "derived" entry has no `path`
  derivation: codeql_open_count      # a name in metrics/build/derive.py's DERIVATIONS
  params: {severities: [critical, high]}
  label: Open CodeQL critical + high
  unit: count
  direction: zero
  target: null
  group: security
  headline: true
  since: 2026-08-23
  note: "Open code-scanning alerts at security severity critical or high, as of each day."
```

Rules:
- `direction: zero` means the target is implicitly 0 and any nonzero value is bad (zizmor findings, boot-trap imports).
- `direction: info` renders neutral, never coloured (LOC per app, CI wall time).
- A PR that adds or renames a collector field, or a derivation, updates its catalogue entry in the same PR. A test asserts every `headline: true` entry resolves against the latest data.
- The counting rule for any count metric is stated in `note`. (Today two different counts of "e2e tests" exist — 249 by the collector's regex over `e2e/tests/**/*.spec.ts`, 312 by a broader grep — the catalogue pins one and says which.)

Initial headline set (twenty entries, four per group; the full catalogue is larger):

| Group | Headline metrics |
|---|---|
| Safety net | E2E scenarios; backend line coverage (target 60); frontend line coverage (target 75); known bugs pinned by a test (from the defect ledger, `pinned` count) |
| Security | open CodeQL critical+high (target 0); age in days of the oldest open critical/high (target < 30); OpenSSF Scorecard (target 8.0); open Scorecard findings (target 0) |
| Extraction readiness | reverse imports into `apps/proxy` (target 0 by end of Phase 1); import cycles (target 0); `models.py` module-level `live_proxy` imports (zero); `apps/proxy` ORM writes (target 0) |
| Delivery | trailing-30-day CI pass rate across required workflows; median E2E wall time; PR lead time p50; product-vs-scaffolding line ratio per merged PR (info) |
| Agent pipeline | open `needs-triage`; median time to triage (target < 3 days); PRs merged by agents in trailing 30 days; fixed defects (ledger `fixed` count) |

**Amendment (Part B):** the Security row's fourth headline is "open Scorecard
findings (target 0)", not "zizmor findings (zero)" as originally specified.
Nothing in this repo uploads a zizmor SARIF to GitHub's code-scanning API, so
no series exists for a zizmor-findings metric to read. `scorecard.yml`
uploads one SARIF finding per failing Scorecard check to the same
code-scanning API CodeQL uses, so the catalogue entry
(`scorecard_findings_open`) reuses the `codeql_open_count` derivation with
`params: {tools: [Scorecard]}` rather than adding a new derivation.

### 5.2 `milestones.yml`

Two top-level keys. `phases:` declares the phase timeline the Story page
walks; `milestones:` is one entry per event worth a line on a chart, each
naming the phase it belongs to.

```yaml
phases:
  - id: phase0                       # referenced by milestones[].phase and catalogue phases[].headline_ids
    label: Phase 0
    summary: "Harden in place: six small PRs in one day."   # two sentences max
    headline_ids: [codeql_open_critical_high, ci_pass_rate_required, defects_fixed]

milestones:
  - sha: 75a68555b931e7d088bfbbd859b35e6e27064312   # full; must be first-parent on main
    label: Phase 0 done
    kind: phase-done          # phase-start | phase-done | goal | incident | release
    phase: phase0             # a `phases[].id` declared above
    pr: 155
    summary: "All six Phase 0 items merged; the ruleset requires four result aggregates."
```

`date` is derived from the commit, never stored. Validation: `sha` is on `main` (first-parent), `pr` exists and is merged, `kind` in vocabulary, `phase` names a declared `phases[].id`, `label` ≤ 40 chars, `summary` one sentence; every `phases[].headline_ids` entry is a real `catalogue.yml` id.

**When an agent adds an entry:** a spec's Done log gets its final tick (`phase-done`), a goal's PR merges (`goal`), a release is tagged (`release`), a security incident is fixed (`incident`), a phase's spec is committed (`phase-start` — which also means declaring the phase itself under `phases:`, with `headline_ids` naming the two or three catalogue metrics it's meant to move). **Never** edit a past entry's `sha` or `kind`; correct `summary` or `label` freely.

The first version is seeded from the inventory in Appendix A (baseline, PR #2 guardrails, PR #4 supply chain, the fifteen e2e goals, the three metrics PRs, Phase 0 start/done).

### 5.3 `defects.yml` — the known-defect ledger

One entry per item in CLAUDE.md's "Known defects and traps".

```yaml
- id: unfenced-ownership-lease
  title: "Ownership lease is time-bounded, not fenced; add_chunk has no fencing token"
  area: correctness         # security | correctness | dead-code | operational
  severity: high            # critical | high | medium | low
  status: open              # open | pinned | carried | fixed
  source: null              # CLAUDE.md anchor; required for open when there is no issue yet
  issue: 61                 # required for open when there is no source, and for pinned
  test: null                # path; required for pinned
  fixed_in: null            # PR number; required for fixed
  carried_as: null          # spec section reference; required for carried
  first_seen: 2026-08-22
  status_changed: 2026-08-22
```

Status moves only forward along `open → pinned → fixed` or `open → carried`; `carried → fixed` is also allowed (a constraint that later gets a real fix). The validator checks the required-by-status fields — `open` needs `issue` **or** `source` (not both: a defect surfaced straight into CLAUDE.md before it ever got an issue points `source` at the CLAUDE.md heading instead), `pinned` needs `issue` **and** `test`, `carried` needs `carried_as`, `fixed` needs `fixed_in` — that `test` exists in the tree, that `fixed_in` is a merged PR, and that no status moves backward relative to the committed version on `main`.

**When an agent updates an entry:** a PR that closes the linked issue moves it to `fixed` with `fixed_in`; a `test.fail()` pin or backend test added for it moves it to `pinned` with `test`; a spec that lists it as a constraint the extracted relay must not recreate moves it to `carried` with `carried_as`. **Amendment (Part B):** the gh-aw `issue-remediation` workflow's prompt does not move the entry itself — its draft PR's body is written in the same step that creates the PR, before a PR number exists, and `fixed` requires `fixed_in`. Instead it adds a `Ledger: <defect id> -> fixed` line to the PR body, and the merger applies the ledger change (`status: fixed`, `fixed_in`, `status_changed`) by hand at merge time.

### 5.4 Where the contract lives

`docs/agents/metrics.md`: the three files and schemas, the per-file update triggers, the forward-only status rule, how to run the validator (`python -m metrics.build --validate-only`), how to preview the site, and what "not permitted" means. CLAUDE.md gets a pointer under *Agent skills* and one line in *Testing* for the new hook rule.

## 6. Build step

Package `metrics/build/` (moved out of `scripts/` so it can be imported and tested as a package; the collectors stay in `scripts/metrics/`). Invoked as:

```bash
python -m metrics.build --data <metrics-data checkout> --curated metrics/curated --out site/site.json
python -m metrics.build --validate-only --curated metrics/curated   # hook and commit gate
```

Four stages:

1. **Load and validate.** Read every snapshot family, every event dump plus its history sidecar, then the three curated files. Failures are collected and reported together; exit non-zero on any. Missing data is not an error: a family with no rows yields empty series so the site builds on day one.
2. **Derive.** Each derivation is a pure function of `(events, defects, day, params)`, named by its catalogue entry's `derivation` field and registered in `metrics/build/derive.py`'s `DERIVATIONS`. As implemented:
   - `codeql_open_count` — created ≤ D and not (fixed ≤ D or dismissed ≤ D)
   - `codeql_oldest_open_age_days`
   - `codeql_fixed_per_week`
   - `scorecard_score`, `scorecard_check` (params: `name`)
   - `ci_pass_rate_30d`, `ci_median_wall_time_30d` (params: `workflow(s)`)
   - `pr_lead_time_30d` (params: `quantile`, `author_type`) — human/agent heuristic as in `derive.py`'s `_is_agent` docstring
   - `prs_merged_30d` (params: `author_type`)
   - `pr_product_ratio_30d` — lines under `apps/` over all lines, per merged PR, rolling 30 days
   - `issues_open_by_label` (params: `label`), `issues_time_to_triage_median_30d`
   - `defects_by_status` (params: `status`)
3. **Align to a daily calendar.** Every series is resampled to one point per day from the baseline date to today, last value on or before that day (`forward_fill` in `metrics/build/calendar_.py` — a calendar helper used by every family and derivation, not itself a derivation with a catalogue entry). Per-commit resolution is kept as a second series for Explore.
4. **Emit `site.json`.**

```
meta:      built_at, baseline {sha, date}, freshness {family: last_real_point}, source_notes []
headline:  [ {id, label, unit, direction, target, group, now, at_baseline, at_prev_milestone,
              status: good|bad|neutral|stale, spark: [30 daily points]} ]
groups:    { group: [ {id, ..., daily: [[date, value]], commits: [[sha, date, value]]} ] }
phases:    [ {phase, label, start, end|null, summary, milestones: [...], headline_ids: [...]} ]
milestones:[ {sha, date, label, kind, phase, pr, summary} ]
defects:   { entries: [...], by_status_daily: [[date, {open, pinned, carried, fixed}]] }
compare:   { "<sha_a>..<sha_b>": [ {id, from, to, delta, good: true|false|null} ] }   # adjacent milestone pairs precomputed; arbitrary pairs computed client-side from groups
```

**Status rule** (used for tile colour and Compare's good/bad column): `good` when the value is at target, or has moved toward it since the previous milestone; `bad` when it has moved away, or is stalled with an unmet target; `neutral` for `info`; `stale` overrides both and shows a warning. Freshness is not one rule (R26/R27): the per-commit snapshot families (`code_health`, `architecture`, `tests`) are keyed by commit sha, not date, so they use the SHA rule — fresh iff a row exists for `main`'s current first-parent HEAD, since a quiet week with no new commit is healthy, not stale. The once-daily `coverage` family and every `derived` series have no such natural cadence to key off, so they use the 2-day age rule instead — stale when the series' last real point is older than 2 days (the daily cadence plus one missed run).

**Freshness is data.** Each series carries the timestamp of its last real point and every page shows it, so a broken collector is visible as "stale since" rather than a flat line.

## 7. Workflows

### 7.1 `metrics.yml`

Two jobs.

- `collect-and-append` (existing, reshaped): triggers per §4.3; runs snapshot collectors and, on schedule/dispatch, the event-dump collectors; `permissions: contents: write, security-events: read`, plus `actions: read`, `issues: read` and `pull-requests: read` for the event-dump collector (an explicit permissions block nulls every unlisted scope, and a listing 403 would be recorded as a silent `not_permitted`); commits and pushes to `metrics-data` under the existing `metrics-append` concurrency group.
- `coverage` (new, schedule and dispatch only): Postgres and Redis services as in `backend-tests.yml`; `scripts/ci_bootstrap_backend.sh`; each of the 16 labels runs as its own `coverage run -p` process via `scripts/ci_coverage_backend.sh` (Redis flushed between labels, mirroring CI's per-label isolation), results are combined, and a failed label is recorded in `backend_failed_labels` with `backend_status: failed` while the combined pct is still reported; `vitest run --coverage --coverage.reporter=json-summary`; writes one `coverage.jsonl` row. Runs after `collect-and-append` (`needs:`) so both push under the same concurrency group without racing.

### 7.2 `pages.yml`

Checks out `main` and `metrics-data`, installs PyYAML, runs `python -m metrics.build`, copies `dashboard/` static assets plus `site.json` into the site artifact, deploys. Triggers: push to `main` touching `dashboard/**`, `metrics/**` or the workflow; daily 06:15 UTC; dispatch. Stays unchained from `metrics.yml` (zizmor `dangerous-triggers`, documented in the file). A build failure fails the workflow, so an invalid curated file that slipped past local hooks is visible within a day.

Both workflows stay at zero zizmor findings, every `uses:` SHA-pinned via a tool, `persist-credentials: false` on every checkout.

### 7.3 Local hooks

`.claude/settings.json` `PostToolUse` gains rules for the metrics stack: an edit under `metrics/**` or `scripts/metrics/**` runs `scripts/run_metrics_tests.sh` (plain `unittest`, no `pytest`, no container) plus `python -m metrics.build --validate-only`; an edit under `dashboard/*.{js,html}` runs `vitest` against `frontend/vitest.dashboard.config.js`. A few seconds either way. `.claude/hooks/pre-commit-tests.sh` (the commit gate) picks up the same paths with its own grep over the staged file list — not through `scripts/ci_backend_test_labels.py`'s `_PATH_ALIASES`, which maps prefixes to Django test *labels* and so cannot express a plain-`unittest` or `vitest` runner.

## 8. Pages

Five static HTML files under `dashboard/`, one shared `app.js`, one `style.css`, vendored uPlot. Each reads `site.json` once. Single column under 800 px, dark theme via `prefers-color-scheme`, no framework.

- **Overview.** Phase strip across the top (phases as segments, milestones as dots, hover shows PR and summary, current phase highlighted). Below it, the five groups in order, each a row of four headline tiles. A tile shows label, value, one line of context (delta since baseline, or target and oldest-age, per catalogue), and the daily series drawn as a **soft** background area-plus-line (line opacity ≈ 0.35, fill ≈ 0.06) in the status colour: green good, red bad, blue neutral, grey stale with a warning glyph. The number stays in the foreground text colour. Footer: data-as-of per family, baseline SHA, commit count.
- **Story.** One section per phase in order: dates, the phase summary, its milestones with PR links, and a strip of the two or three headline charts that phase was meant to move with the phase window shaded. This page is the talk; the inventory in Appendix A seeds its first three sections.
- **Explore.** Every catalogued metric grouped the five ways, full history at per-commit resolution with milestone lines, a daily toggle, hover readout of value/commit/date, and the catalogue `note` under each title.
- **Compare.** Two milestone selectors (default baseline → latest). One table per group: metric, from, to, delta, good/bad. Print stylesheet hides the nav so a browser print is slide-ready. Replaces the current `?from=&to=` view.
- **Defects.** The ledger grouped by status, each row linking issue, test or fixing PR; a stacked daily bar of counts by status at the top.

## 9. Testing

- **Build step:** `metrics/build/tests/`, fixtures checked in (a small `metrics-data` tree with snapshot rows and one dump per kind; valid and invalid curated files); run via `python -m unittest discover` (`scripts/run_metrics_tests.sh build`), not `pytest` — no third-party test runner is a dependency of this stack. One test per derivation, one per validation rule, one end-to-end build asserting `site.json`'s shape against the catalogue.
- **Collectors:** event-dump collectors tested with a fake `gh` on `PATH` returning canned paginated output including the multi-page case that broke delivery; snapshot collectors get one regression test each against a tiny fixture checkout.
- **Curated files:** a test validates the real `metrics/curated/*.yml` against the current `main`, so the suite fails if a milestone SHA is wrong or a ledger `test` path no longer exists.
- **Pages:** a handful of vitest cases against a fixture `site.json` — each page renders, tiles colour by direction, Compare marks deltas correctly, stale warnings appear. No Playwright.
- **Workflows:** zizmor zero-findings ratchet; one manual dispatch of each after merge is the smoke test, and this spec says so rather than pretending CI proves them.

Everything runs on plain Python and Node, no Postgres or Docker, except the coverage job, which only its scheduled run exercises.

## 10. Migration and retirement

1. Land collectors and workflow changes first; dispatch once; confirm event dumps and a coverage row on the branch.
2. Land `metrics/curated/` seeded from Appendix A and CLAUDE.md, with `docs/agents/metrics.md`.
3. Land the build step and pages, replacing `dashboard/` wholesale; dispatch `pages.yml`; confirm the site at https://d10scot.github.io/Dispatcharr/.
4. Delete `scripts/metrics/collect_{security,delivery,agentic}.py` in favour of the event-dump collectors; leave the old JSONL files on the branch; update the branch README.
5. Add `.superpowers/` to `.gitignore` (brainstorm artefacts from this design session).

## 11. Out of scope

A Dependabot PAT secret; enabling secret scanning (repo settings); per-PR coverage on required checks; any metric that needs a running Dispatcharr instance; a self-hosted Grafana or any external service; an interactive slide deck (Compare's print view is the concession).

## Appendix A — inventory since `fd413f0c` (v0.29.0), for seeding `milestones.yml` and the Story page

Window 2026-08-22 → 2026-09-03. 67 first-parent commits, 64 merged PRs, +95,429 / −748 lines of which +485 / −31 under `apps/`.

| Metric | Baseline | 2026-09-03 |
|---|---|---|
| Test files (`test_*.py`, `*.test.jsx?`, `*.spec.ts`) | 335 | 434 |
| Playwright spec files / projects | 0 / 0 | 94 / 13 |
| E2E scenarios (collector rule) | 0 | 249 |
| Hypothesis property tests | 0 | 22 |
| Backend tests (AST count) | 1,787 | 1,860 |
| GitHub workflows | 9 | 20 (4 agentic) |
| zizmor findings | 101 | 0 |
| Specs / plans / ADRs | 0 | 18 / 15 / 4 |
| Issues on the fork (open) | 0 | 90 (81) |
| Known defects fixed / pinned / carried | – | 1 / ~12 / 6 |
| CodeQL open critical / high / medium / low | unscanned | 3 / 72 / 77 / 1 |
| OpenSSF Scorecard | unscored | 6.9 |
| `e2e/COVERAGE.md` rows done / known-bug / gap | – | 132 / 27 / 24 |

Themes and anchor PRs:

- **Investigation and documentation** (08-22 →): CLAUDE.md and CONTEXT.md as a verified defect map; corrected by #34, #39, #45, #122, #126 as the tests contradicted it; `claude-md-maintenance` (#38).
- **CI and supply chain** (08-22 → 08-28): #2 zizmor, 101 findings cleared, the silently-unrun 16th backend package found; #4 SHA/digest pinning, lint, vuln-scan, Scorecard, Renovate, CodeQL; #30, #35, #37 always-reporting required checks; #32 CodeQL ingest.
- **E2E programme G1–G15** (08-23 → 09-03): #1 first test; #5 G1 harness; #19 G2 fake provider; #33 G4 streaming data path; #43 G7 lifecycle; #77 G8 Xtream provider; #78 G3; #79 G6; #88 G5; #112 G9; #113 G10; #123/#124 G11 migration gate and taxonomy; #130 G12; #139 G15; #144 G13; #143 G14. ADRs 0001–0003.
- **Fuzzing and agentic workflows** (08-24 → 08-29): #8 fuzz campaign; #29 triage; #28 remediation; #36/#31 Hypothesis foundation; #52 model switch after classifier 422s.
- **Metrics** (08-29): #40 M1, #46 M3, #47 M2.
- **Phase 0** (09-03): #148 spec + ADR 0004; #150, #149, #154, #151, #152 the six items; #155 Done log. One product security fix (#154, credential redaction); six defects carried as constraints for the relay.
