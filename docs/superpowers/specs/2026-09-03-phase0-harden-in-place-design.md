# Phase 0 — Harden in Place

**Date:** 2026-09-03
**Status:** Accepted
**Parent:** *Splitting the Planes* (extraction proposal, artifact `149fb554`), § "Phase 0 · harden
in place". This spec is where that one-paragraph phase becomes a delivery.
**Predecessor:** the E2E programme (G1–G15), whose closing note in
`2026-09-01-e2e-programme-review-disposition.md` says: "when they land, the programme returns to
the extraction." All fifteen landed; the last was G14 (#143). This is the return.
**Verified at:** `origin/main` `cdc87a38` (G14). Line numbers drift; symbol names are the durable
half of every citation.

## Goal

The proposal defines Phase 0 as the work that makes the extraction safer without moving any
boundary: "none of this depends on the split, all of it makes the split safer, and it's worth
doing even if you stop here." It listed five items. One (`uv.lock`) is done. This spec delivers the
other four, plus one incident-grade item the proposal's companion due-diligence document raised
and `CLAUDE.md` carries under *Security*:

1. **The two CI label-routing defects** in `dispatcharr/test_discovery.py`.
2. **`npm ci` in the image build.**
3. **Provider credentials no longer logged.**
4. **A result aggregate per test workflow**, so every suite can be required.
5. **A release that cannot ship an untested commit**, and the Main ruleset requiring every
   aggregate.

The glossary (`CONTEXT.md`, § Programme terms) now defines **Phase 0** as exactly these five, and
**migration gate** and **result aggregate** as the mechanism items 4 and 5 build. Use those terms.

Deployment defaults the due-diligence document also flagged — the published Postgres port,
wildcard hosts/CORS/CSRF, plaintext XC passwords, the missing request timeout — are **not** Phase
0. They are recorded below under § Carried, not fixed, as constraints the extracted relay must
not recreate. Widening Phase 0 to include them is the scope creep `CLAUDE.md` names as the main
way this fork fails.

## Migration relevance

Every Phase 1 PR will be a `migration/**` branch that edits `apps/proxy/` and `docker/`. Each item
here decides what that PR's CI actually proves:

- **Routing (item 1).** Today a change to `live_proxy/server.py` selects only the live proxy's
  own 89 tests and skips the 420 in `apps.channels.tests`, which is where
  `test_ts_proxy_teardown.py` builds a real `ProxyServer` ten times. The commit hook inherits the
  same selection by design. Phase 1 edits that file constantly; without this fix its richest
  tests never run for it.
- **`npm ci` (item 2).** The image Phase 1 canaries must be built from the dependency set CI
  tested. Today it is not.
- **Credentials (item 3).** The relay's first design goal is that a channel UUID and a provider
  credential are secrets. A codebase that logs them at INFO cannot make that claim, and the
  relay's own logging will be written by copying the existing sites.
- **Aggregates and the gate (items 4, 5).** Today only `E2E result` is required. A Phase 1 PR that
  breaks every backend test still merges. The migration gate is the one job the E2E programme
  existed to build, and it is not wired up.

## Verified facts this design rests on

Checked against the tree and the repository settings on 2026-09-03.

**Ruleset.** One ruleset, `Main` (id 21229979), active: PR required, squash-only, deletion and
non-fast-forward blocked, `required_approving_review_count: 0`, required checks
`["E2E result"]` with `strict_required_status_checks_policy: true`. Classic branch protection
returns 404 — the ruleset is the only protection.

**Test workflows.**
- `backend-tests.yml`: `push`/`pull_request` on `main`, both with identical `paths:` filters.
  Jobs: `plan` (name `Plan test groups`, computes labels via `scripts/ci_backend_test_labels.py`,
  emits `has_tests`) and `test` (`name: ${{ matrix.label }}`, gated on `has_tests`). **No
  aggregate.** A docs-only PR produces no check run from this workflow at all.
- `frontend-tests.yml`: `push`/`pull_request` filtered to `frontend/**` and the workflow file.
  Single job `test`, no `name:`. Does not always trigger.
- `e2e-tests.yml`: `pull_request` unfiltered, so it always reports. `changes` job greps the diff;
  every heavy job is gated on `needs.changes.outputs.e2e == 'true'`. `E2E result`
  (`if: always()`): fail if `changes` did not succeed; pass if `e2e != 'true'` ("deliberately
  skipped"); otherwise `upstream`, `test` and `guards` must each be exactly `success`.
- `lifecycle-tests.yml`: `pull_request` unfiltered, always reports; `changes` job with a grep
  kept in lockstep with the push filter; `full` when the branch matches `migration/*`.
  `Lifecycle result` fails if `changes` failed, and otherwise **accepts `skipped`
  unconditionally** for every dependency — no required-flag early exit. Laxer than E2E.

**Routing.** `_PATH_ALIASES` (`dispatcharr/test_discovery.py:21-25`) holds three entries;
`apps/vod/` → `("apps.output",)` only. Aliases are tried before prefix matching and
short-circuit. `apps/proxy/live_proxy/server.py` matches no alias; the longest label prefix wins,
giving exactly `["apps.proxy.live_proxy.tests"]`. `apps/vod/tests/` holds 47 tests in 7 files and
is a discovered label (`apps.vod.tests`). **No test anywhere references
`labels_for_changed_paths`.** Whole backend suite: ~1,787 tests in ~34 s, so adding
`apps.channels.tests` to every proxy edit costs the commit gate roughly eight seconds.

**Dockerfile.** `docker/Dockerfile:18` copies `./frontend` (which includes the tracked 212 KB
`frontend/package-lock.json`; `.dockerignore` excludes only `**/node_modules`), then `:20-21`
runs `rm -rf node_modules || true; npm install --no-audit --progress=false`. Only the command is
wrong.

**Credential logging.** Five sites, all `logger.info`:
`apps/proxy/vod_proxy/views.py:628` (`request.get_full_path()` — Xtream paths carry the password)
and `:630` (`dict(request.headers)`); `apps/m3u/tasks.py:3084` (complete and transformed URL);
`apps/channels/tasks.py:1577` and `:1633` (DVR base and stream URL). The hook's advisory grep
(`.claude/hooks/run-affected-tests.sh:66-76`) already matches all five; it calls `note`, not
`block`.

**Release.** `release.yml` is `workflow_dispatch` only, never run. `prepare` bumps
`version.py` (`__version__ = '0.29.0'`), commits, and `git push origin main --tags`. **The Main
ruleset rejects that push**, so the workflow cannot complete as written. Nothing in it runs or
checks a test. `docker-build.yml` already publishes `:latest` and a full-SHA tag on every push to
`main`; `release.yml` is the only producer of a *versioned* tag and image, which Phase 2's
per-channel canary will want.

**Test homes.** Labels are discovered from `INSTALLED_APPS` plus the root `tests/` and
`core/tests/` packages. `dispatcharr/` is not an app: a test file placed there never runs in CI.
`tests/` is the existing home for cross-cutting tests of `dispatcharr/utils.py`
(`test_ip_lookup.py`). Any change under `dispatcharr/` is in `_SHARED_PATH_PREFIXES` and forces
the full label set.

## Decisions

Reached in a grilling session on 2026-09-03; each was put as a question with a recommendation and
the recommendation accepted.

| # | Decision | Why |
|---|---|---|
| **D1** | **Phase 0 is the proposal's four remaining items plus credential redaction. Deployment defaults are out, and recorded as relay constraints.** | The four make the extraction safer, the proposal's stated purpose. Credential logging is a five-line fix that turns a shared support log into an incident today and touches no relay code. Deployment defaults change what a default install does and deserve their own goal. |
| **D2** | **The fork is permanent. Upstream files are edited freely; no diff is shaped for rebase-ability.** | The fork has already diverged in CI, hooks, docs and the entire `e2e/` tree, and its purpose is a structural split upstream has not signed up for. The proposal asked for this decision before Phase 1; it is made here. |
| **D3** | **Six PRs in order: routing, `npm ci`, redaction, aggregates, release, ruleset. The first two on `migration/…` branches.** | Routing goes first because it changes what the commit gate runs for every PR after it. Routing and `npm ci` change what is tested or built and deserve the full run; the rest do not need a 40-minute CI cycle per push. The ruleset change is a settings action, last, because required check names must exist on `main` before they are required. |
| **D4** | **Routing is fixed in place: add `apps.vod` to the VOD alias, add `apps.channels` for `apps/proxy/live_proxy/` paths, and pin both with tests.** | Two known defects in a hand-written table, not a design flaw. A reverse-import map derived from the code would drag in the 367 cross-app import edges — a static-analysis project. Eight seconds per proxy edit is not worth a narrower prefix. |
| **D5** | **Redaction: two helpers in `dispatcharr/utils.py`, one for URLs and one for header mappings, masking with `***`. All five sites move to DEBUG through them.** | The lines exist because VOD and DVR URL construction is hard to debug; keep the diagnostic, remove the secret. `dispatcharr/utils.py` is importable from every site including the two Celery task modules. Deleting the lines loses the diagnostic; DEBUG without redaction leaks exactly when someone turns debug on to diagnose the problem those lines exist for. |
| **D6** | **The URL helper strips userinfo, masks query parameters named `password`, `username`, `token`, `api_key`, and masks the two credential segments in Xtream path shapes (`/live/<user>/<pass>/…`, `/movie/…`, `/series/…`, `/timeshift/…`). The header helper drops `Authorization`, `Cookie`, `X-Api-Key`. Tests in `tests/`, Hypothesis on the URL helper.** | Xtream credentials live in the path, not the query — a query-only redactor would pass the worst site. Hypothesis is already a dev dependency and URL parsing is where a redactor silently misses a shape. `tests/` is the only discovered home for tests of `dispatcharr/utils.py`. |
| **D7** | **The hook's credential grep becomes blocking when a matching log line does not call a redaction helper, and the same script runs in `lint.yml`.** | Blocking only on the unambiguous tokens would leave the DVR and M3U sites, which log URLs, uncaught. One shared script means the hook and CI cannot drift, and CI catches PRs not written through the hook. |
| **D8** | **Backend and frontend workflows drop their `paths:` triggers and gain a `Backend result` / `Frontend result` aggregate in the strict E2E shape. `Lifecycle result` is tightened to the same shape.** | A required check that never reports blocks the PR forever, so the workflow must always trigger and decide inside. Backend already has that decision (`plan`); frontend needs a `changes` job. One lax aggregate among four is the asymmetry that gets copied. |
| **D9** | **The Main ruleset requires all four aggregates; squash-only and the strict up-to-date policy stay.** | Strict up-to-date costs a re-run when PRs queue; it is what stops two green PRs merging into a red `main`, the failure that ends a single-maintainer project's trust in its CI. |
| **D10** | **Release is two steps: a normal PR bumps `version.py`; then a manual dispatch on `main` runs `verify`, which reads the required checks from the ruleset via the API, confirms each succeeded on the head SHA and that `version.py` matches the requested version, then tags, builds, signs and creates the release. The workflow commits nothing.** | The bump-and-push design is dead under the ruleset. Tag-only with a build-time version leaves the checked-in version permanently wrong. Reading the check list from the ruleset means the release trusts exactly the gate that exists and cannot drift from it. See ADR 0004. |
| **D11** | **The ruleset change is applied by API immediately after the aggregates PR merges, with the rule JSON shown first, and the command recorded here.** | Four check names; a reproducible command beats a UI walkthrough. |
| **D12** | **Documentation: this spec, per-PR corrections to `CLAUDE.md`, and one ADR (0004) covering the release and the ruleset as one decision.** | Several `CLAUDE.md` sections state these defects as present and would mislead the next session. The release trusting the gate instead of running tests is the one choice a future reader will question. |
| **D13** | **The carried constraints live in this spec until the Phase 1 spec is written, which lifts them into requirements.** | The list is small and its only consumer for weeks is the Phase 1 author. Issues would sit among forty product defects with nothing marking them as design constraints. |

## The six pull requests

Each PR corrects the `CLAUDE.md` lines that describe its defect as present (§ Documentation
lists them). Done criteria are per PR; Phase 0 is done when all six are merged and the ruleset
shows four required checks.

### PR 1 — routing (`migration/phase0-test-routing`)

- `_PATH_ALIASES`: `("apps/vod/", ("apps.vod", "apps.output"))`. Add an entry
  `("apps/proxy/live_proxy/", ("apps.proxy.live_proxy", "apps.channels"))` — the alias wins over
  prefix matching, so the live proxy's own label must be listed too. `_resolve_alias_labels`
  (`dispatcharr/test_discovery.py:151`) appends `.tests` to each alias app name and keeps it only
  if discovered, so both new entries resolve to existing labels — verified.
- New `tests/test_ci_test_routing.py`: for `apps/vod/views.py` the labels include
  `apps.vod.tests`; for `apps/proxy/live_proxy/server.py` they include `apps.channels.tests`;
  and, as a control, `apps/epg/tasks.py` still selects only `apps.epg.tests`. These are the first
  tests `labels_for_changed_paths` has had.
- **Done:** the label script prints both labels for each path; the commit hook, run on a staged
  `live_proxy/server.py` edit, runs `apps.channels.tests`; CI's `plan` job for the PR itself shows
  the expanded matrix.

### PR 2 — `npm ci` (`migration/phase0-npm-ci`)

- `docker/Dockerfile:20-21` → `RUN npm ci --no-audit --progress=false`. Drop the `rm -rf
  node_modules` line (`npm ci` removes it itself).
- **Done:** `docker-build.yml` green on the PR; the full-mode E2E run, which builds the AIO image
  from this Dockerfile, green.

### PR 3 — redaction (`fix/phase0-credential-redaction`)

- `dispatcharr/utils.py`: `redact_url(url: str) -> str`, `redact_headers(headers) -> dict`.
- Five sites → `logger.debug(..., redact_url(...))` / `redact_headers(...)`.
- `tests/test_redaction.py`: property tests that no input containing a userinfo, a listed query
  key, or an Xtream credential path shape survives unmasked; example tests for each of the five
  sites' actual shapes; a control that a credential-free URL is returned unchanged.
- `scripts/check_credential_logging.py` (the grep from the hook, plus "and does not call
  `redact_`" ), called by the hook with `block` and by a new `lint.yml` job over every `*.py` in
  the diff.
- **Done:** the script exits non-zero on the pre-fix tree and zero after; the hook blocks a
  deliberate re-introduction; `lint.yml` green.

### PR 4 — aggregates (`ci/phase0-result-aggregates`)

- `backend-tests.yml`: remove `paths:` from both triggers; add `backend-result` (`name: Backend
  result`, `needs: [plan, test]`, `if: always()`) with the E2E three-branch logic keyed on
  `needs.plan.outputs.has_tests`.
- `frontend-tests.yml`: remove `paths:`; add a `changes` job mirroring the removed filter; gate
  `test` on it; add `frontend-result` (`name: Frontend result`).
- `lifecycle-tests.yml`: rewrite `lifecycle-result` to the three-branch shape keyed on whatever
  `changes` emits, so a heavy job that is `skipped` on a required run fails.
- **Done:** a docs-only PR shows all four aggregates green with the heavy jobs skipped; this PR
  itself shows them green with the heavy jobs run; zizmor at zero findings on all three files.

### PR 5 — release (`ci/phase0-release-gate`)

- `release.yml`: `workflow_dispatch` input `version` (string). Job `verify`: refuse unless
  `github.ref == 'refs/heads/main'`; read `version.py` and compare; `GET
  /repos/{o}/{r}/rulesets/{id}` for the required check contexts, then `GET
  /repos/{o}/{r}/commits/{sha}/check-runs` and require each context's latest run to be `success`;
  refuse if the tag exists. Then `git tag -a v{version} {sha}` and push the tag only. The
  `prepare` job's bump, commit and push are deleted; `persist-credentials` goes back to `false`.
  `docker`, `create-manifest`, `sign-and-attest`, `create-release` keep their shape, building from
  the verified SHA.
- `docs/adr/0004-release-trusts-the-migration-gate.md` (in this PR or the spec PR, whichever
  lands first).
- **Done:** a dry dispatch against `main` with a mismatched version fails in `verify` with the
  reason; the workflow's push permission is limited to tags.

### PR 6 — ruleset (settings action, no diff)

After PR 4 merges and `main` has produced all four aggregate names:

```bash
gh api -X PUT repos/D10Scot/Dispatcharr/rulesets/21229979 --input ruleset.json
```

where `ruleset.json` is the current ruleset with `required_status_checks` set to `E2E result`,
`Lifecycle result`, `Backend result`, `Frontend result`, and `strict_required_status_checks_policy`
left `true`. Record the command and the before/after JSON in this spec's § Done log.

## Carried, not fixed

Constraints the extracted relay must satisfy. Each is a defect in the current product that Phase 0
deliberately does not fix; the Phase 1 spec lifts this table into its requirements.

| Constraint on the relay | The defect it must not recreate |
|---|---|
| The relay's own stores (PostgreSQL, Redis, or whatever replaces them) bind to loopback or an internal network by default, never `0.0.0.0`, and never with a default credential. | `docker/docker-compose.yml:191` publishes Postgres on `5436:5432` on all interfaces as `dispatch`/`secret`. |
| The relay validates `Host` and origin against configuration, with a deny-by-default posture that is not conditioned on a debug flag. | `dispatcharr/settings.py`: `ALLOWED_HOSTS = ["*"]`, `CORS_ALLOW_ALL_ORIGINS = True`, `CSRF_TRUSTED_ORIGINS = ["http://*", "https://*"]`, none conditioned on `DEBUG`. |
| Any credential the relay stores or compares (XC passwords, API keys, the HMAC key for signed stream URLs) is hashed or constant-time compared, never plaintext-equality. | XC passwords plaintext in `custom_properties["xc_password"]`, compared with `!=`; API keys looked up by plaintext value, unscoped. |
| The relay has a request timeout and a drain-on-shutdown from day one; these are a design input, not a later addition. | uWSGI runs with no `harakiri` (cannot be enabled while the relay shares the process with the API) and `die-on-term` with no drain, so every deploy drops every viewer. |
| The relay's stream endpoint is authorized by a Django-minted, short-lived, HMAC-signed URL validated statelessly; the channel UUID alone is not a capability. | `stream_ts` is `AllowAny`, gated only by the global `STREAMS` network ACL defaulting to `0.0.0.0/0`. |
| The relay's logging never emits a provider URL or a request header set except through the redaction helpers from PR 3. | The five sites PR 3 fixes — recorded here so the relay's authors copy the fixed shape, not the original. |

## Documentation

`CLAUDE.md` lines that state a Phase 0 defect as present, each corrected by the PR that fixes it:

- *Test hooks* and *Testing* — "The gate inherits the two routing defects … on purpose" and
  "**Two path-routing defects in `labels_for_changed_paths()`**" (PR 1).
- *Build reproducibility* — "**`docker/Dockerfile` still uses `npm install`**" (PR 2).
- *Known defects and traps › Security* — "Provider credentials logged at **INFO**" (PR 3;
  becomes a note that the sites are redacted and the hook blocks regressions).
- *Testing* — "the fork's **Main ruleset requires its checks on every PR**" and "`Lifecycle
  result` … must not join the Main ruleset until G12 leaves both bash suites green" (PR 4 and
  PR 6; the second sentence is already stale).
- *Testing* — "`release.yml` has never run — no releases" (PR 5; describe the two-step release).
- *Repository and direction* — add the Phase 0 spec beside the four investigation documents.

## Done log

Filled in as PRs merge: PR number, merge SHA, and for PR 6 the ruleset JSON before and after.

| Item | PR | Merged |
|---|---|---|
| Routing | | |
| `npm ci` | | |
| Redaction | | |
| Aggregates | | |
| Release | | |
| Ruleset | | |

## Risks

- **PR 4 changes what a green PR means for every open branch.** Removing the path filters makes
  the backend and frontend workflows run on every PR; the `plan` / `changes` jobs keep the heavy
  work skipped for unrelated diffs, so cost is one small job per workflow, not a suite run.
- **Requiring `Backend result` before it exists on `main` blocks every PR.** D3's ordering and
  D11's "after PR 4 merges" exist for exactly this. Verify the four names appear on a `main`
  run before applying PR 6.
- **The redaction helper is only as good as its shape list.** Hypothesis tests cover the shapes
  we know; a provider with a novel URL layout could still leak. The blocking grep is the second
  line: any new log site mentioning a URL must call the helper, so the shape list is the only
  place to fix.
- **`verify` reads the ruleset with `GITHUB_TOKEN`.** Reading rulesets on a public repo needs no
  extra scope; if the repo is ever made private, the job needs `metadata: read`, which the default
  token has. Confirm on the first dry run.
- **The strict up-to-date policy plus four required aggregates means a queued PR re-runs all
  four after each merge ahead of it.** For unrelated diffs the heavy jobs skip and the re-run is
  minutes; for a `migration/**` branch it is the full run. Accepted (D9).

## Non-goals — deliberately out of scope

- Everything under § Carried, not fixed.
- The remaining 18 of 31 dependencies without an exact pin in `pyproject.toml`; comskip from
  `refs/heads/master`; unversioned apt for Redis/PostgreSQL. `uv.lock` already pins the resolved
  set, which is the reproducibility the proposal asked for.
- A Python linter, formatter, type checker or pre-commit config.
- Fixing the full in-process test run's order dependence (`test_catchup_redirect.py`); CI never
  runs the suite in one process and the gate does not depend on it.
- Any fix to the p1 issues (#90, #103–#107) or the ready-for-agent backlog (#89, #94, #95,
  #100). Those go through the triage pipeline, not this spec.
- Any change under `apps/proxy/` beyond the two log sites in `apps/channels/tasks.py` and the two
  in `apps/proxy/vod_proxy/views.py`. Phase 0 moves no boundary.
