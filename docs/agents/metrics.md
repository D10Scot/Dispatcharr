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

The thirteen derivations currently in `metrics/build/derive.py` `DERIVATIONS`:
`codeql_open_count`, `codeql_oldest_open_age_days`, `codeql_fixed_per_week`,
`scorecard_score`, `scorecard_check`, `ci_pass_rate_30d`,
`ci_median_wall_time_30d`, `pr_lead_time_30d`, `prs_merged_30d`,
`pr_product_ratio_30d`, `issues_open_by_label`,
`issues_time_to_triage_median_30d`, `defects_by_status`. `forward_fill` is a
calendar helper (`metrics/build/calendar_.py`), not a derivation — it has no
`catalogue.yml` entry of its own.

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
the same PR. Do this only when the PR number is already known (it usually
is — GitHub assigns one as soon as the PR opens, before merge). The
gh-aw `issue-remediation` workflow can't: it generates its draft PR's body
in the same step that creates the PR, before a number exists, so `fixed_in`
would have nothing to point at. It instead adds a `Ledger: <defect id> ->
fixed` line to the PR body, and whoever merges sets `status`, `fixed_in`
and `status_changed` by hand at merge time.

**A `wontfix`-labelled issue keeps its ledger status.** Triage can close an
issue as `wontfix` without ever fixing it (for example #87
`hidden-channel-streamable`, #7 `interval-schedule-create-race`). That is not
one of the four ledger statuses — do not invent a new one. Leave the entry's
`status` exactly where it was (typically `open` or `pinned`, sitting there
indefinitely) and add a clause to `title` saying the linked issue was closed
`wontfix` and why (`Defect` has no `note` field — an unknown field is
rejected by the validator), so a reader of the ledger isn't left assuming
someone is still going to act on it.

## When a collector says "not permitted" or "disabled"

`events/<kind>.json` carries `status` and `detail`; the dashboard shows them
in the footer. Under the `GITHUB_TOKEN` this workflow runs with, both
`dependabot_alerts` and `secret_scanning` currently come back `not_permitted`
(GitHub's API returns 403 for both — a PAT with Dependabot read would fix
`dependabot_alerts`; that is a repo-settings change, not a code change).
`disabled` is the other status value a collector can report: GitHub returns
404 rather than 403 when the feature itself is off for the repo, as opposed
to merely unreachable with this token. Do not "fix" either case by returning
zero.

## Preview the site locally

```bash
git fetch origin metrics-data && git worktree add /tmp/md origin/metrics-data
python -m metrics.build --data /tmp/md --curated metrics/curated --out dashboard/site.json
cd dashboard && python3 -m http.server 8123     # http://localhost:8123/
```
`dashboard/site.json` is a preview artefact only: it is gitignored and must never be
committed. The pages fetch `site.json` relative to themselves, which is why the preview
builds it in-tree; the deployed site never contains a committed copy — `pages.yml` builds a
fresh one into the site artifact at deploy time. Do not "fix" the `.gitignore` entry.
