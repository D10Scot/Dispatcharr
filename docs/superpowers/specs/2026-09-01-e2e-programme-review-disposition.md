# E2E Programme Review — Disposition and Goals G11–G15

**Date:** 2026-09-01
**Status:** Accepted. All five goals specced — see "Goal status" below.
**Corrected:** 2026-09-01, after G12–G15's specs verified its claims against the tree. Every
change is marked **[corrected]** with the evidence, alongside the original claim, so a reader
who remembers the first version can see what moved and why.
**Parent:** `2026-08-23-e2e-coverage-roadmap-design.md`
**Verified at:** `origin/main` `5679a143`, plus the two open PRs
[#112](https://github.com/D10Scot/Dispatcharr/pull/112) (G9, `test/e2e-vod-series`) and
[#113](https://github.com/D10Scot/Dispatcharr/pull/113) (G10, `test/e2e-catchup-timeshift`).
Line numbers drift; symbol names are the durable half of every citation.

An external review of the ten-goal programme arrived 2026-09-01. Its overall verdict: the
programme is genuinely good — honest coverage ledger, `test.fail()` pinning real bugs, byte-level
TS assertions — but roughly 55% of the 144 tests verify product behaviour, and a handful of
structural issues would undermine it **as a migration gate**, which is the one job the
`CLAUDE.md` extraction plan needs it for.

Every item in the review was verified against the tree before being accepted. This document
records the disposition — accepted, already resolved, or refuted, each with evidence — so no
future goal re-litigates a refuted item or re-builds a resolved one, and defines the five goals
(G11–G15) that carry the accepted items. Per the roadmap's convention, goals are *defined* here
and *specced* when dispatched.

## Disposition

### Accepted — carried by a goal below

| Review item | Verified as | Goal |
|---|---|---|
| The quarantine guard polices only `greybox/redis` imports; `child_process`, `docker`, `pgrep` elsewhere are unguarded | Correct. `tests/streaming-greybox/quarantine.spec.ts` scans for the string `greybox/redis` only. `node:child_process` is imported today by `output-profile-sharing.spec.ts` (allowlisted quarantine) *and* would be accepted silently in any new spec | G11 |
| No tagged split between a portable black-box contract and implementation characterization | Correct. The split exists de facto (project boundaries: `streaming-greybox`, `lifecycle`) but nothing states it per-test, and lifecycle specs mix portable assertions (rows survive restart) with AIO-image characterization (`showmigrations`, container env) | G11 |
| CI gives a migration branch incomplete signal: `lifecycle-upgrade` is a Playwright project absent from `e2e-tests.yml`'s matrix; `lifecycle-tests.yml` is path-filtered so a pure-code rewrite PR skips it | Correct, with a nuance the review missed: the `changes` filter passes for **any** `apps/`, `core/`, `dispatcharr/` or `frontend/` change, so ordinary product PRs already get the seven-project matrix. The genuine holes are exactly `lifecycle-upgrade` and `lifecycle-tests.yml`'s jobs | G11 |
| `durable-state.ts` asserts scalar rows only; relation loss would survive an upgrade unnoticed | Correct. Seven rows, each by id and scalar fields (`e2e/tests/lifecycle/durable-state.ts`); no channel↔stream link, no profile membership, no programme rows, no XC credential round-trip, no VOD rows, no recording | G12 |
| DVR beyond schedule/list/cancel is uncovered | Correct. `dvr.spec.ts` never lets a recording fire; `COVERAGE.md`'s own G6 rows say so, and `run_recording` (1,139 lines, 47 `try` blocks) has never executed under any test | G13 |
| Backup restore, non-zero refresh intervals, ACL 403 negatives, EPG fuzzy matching, plugin run lifecycle, bulk ops, M3U profiles, product WS events | Correct, and all but the WS events were already ledgered as owned todos (`COVERAGE.md` rows for restore and refresh-interval name G7; the G3 row names fuzzy matching a deliberate gap) | G12 / G14 |
| Older `test.fail()` pins can stay red for the wrong reason | Correct. `m3u-ingest.spec.ts`'s #15 pin and `hdhr.spec.ts`'s #82 pin sit entirely inside the inverted block: a failed seed or a 500 satisfies `test.fail()` as convincingly as the real defect. G9/G10 already ship the fix pattern (premise guarded *outside* the inverted block — `8386825c`, `c1858c42`); it needs backporting | G15 |
| `render.spec.ts` is smoke-only | True and by design — it is the wiring proof over `api.js`/`WebSocket.jsx`, and eight of the nine surfaces have their own interaction specs (`users` 16 interactions, `dvr` 15, `connect` 12, `plugins` 8, `settings` 4). The real residue: `stats` (0 interactions), `guide` (1), `backups` (1) | G15 |
| `xc-output.spec.ts` XMLTV check lacks well-formedness | Correct as far as it goes: `parseXmltv` is deliberately shallow (documented in `fixtures/parse.ts`), and the suite already owns the right tool — `expectWellFormedXml` (browser `DOMParser`), used by `output-epg.spec.ts` and `hdhr.spec.ts` but not `xc-output.spec.ts`. **[corrected]**:
a two-line fix, not one — the target test destructures only `seed` and `request`, so it needs
`adminPage` added, giving a request-only test a browser context | G15 |
| Failover tests should assert stream identity post-switch | Partially. `failover-dead-air.spec.ts` *does* assert identity — `stream_id` flips to `streams[1].id` via channel status — but at the control plane; the bytes read afterwards are asserted aligned, not attributed to stream B. **[corrected]**, now answered by G15's spec and measured rather than assumed: a marker PID
injected in `LoopRewriter.rewrite` survives the locked **Proxy** profile byte-for-byte and does
**not** survive the FFmpeg profile (13 injected packets in, 0 out; PIDs remapped, PAT/PMT
rewritten). All three specs that would carry the assertion run Proxy, so it is feasible — but
it is `e2e-upstream/src/` work outside G15's fixed file list, so it is recorded as a COVERAGE
gap rather than built | G15 |
| Status-only assertions in `api-fixture`/`authorization` specs; the fake provider's contract is unversioned (`e2e-upstream` sits at `1.0.0` with no contract doc); the frontend `data-testid` contract and shared-state mutation rules live in prose | Accepted for audit/enforcement respectively | G15 / G11 |

### Already resolved — the review predates the fix

- **"G9 (VOD) and G10 (catch-up) are spec'd but unbuilt."** Stale — and now doubly so: both
  have merged (#112 as `25bf3484`, #113 as `76db0332`), discharging the wave-5 ordering
  constraint they created. Both are built and open as
  PRs #112 (3,642 insertions; Range/seek, XC actions against a real catalogue, three pinned
  range defects incl. #64) and #113 (2,157 insertions; the seven-candidate cascade with shapes
  asserted on the provider's *logged requests*, per-account format cache, provider timezone,
  redirect layouts). Both e2e CI runs green on 2026-09-01. Merging them is programme state, not
  a new goal.
- **"Fix the stale catch-up-parser row in COVERAGE.md."** Fixed in #113: the row now records
  that G8's own PR replaced the permissive regex with one-regex-per-shape
  (`CATCHUP_TIMESTAMP_SHAPES`) plus an exhaustive twelve-combination test, and flipped to done.
- **"Catch-up specs assert only `bytes[0] === 0x47`."** Mostly resolved in #113, which uses
  `expectTsAligned` throughout. Two residual first-byte-only sites remain
  (`catchup-path-layout.spec.ts`, one site in `catchup-cascade.spec.ts`) → G15.
- **"G5's VOD test is shape-only and vacuous on an empty catalogue."** True of G5 in isolation
  and said so in its own comments; superseded by #112, which runs the same actions against a
  real catalogue.

### Refuted — do not act on these

- **"Logo upload compares byte *length* not bytes."** Wrong. `logo-upload.spec.ts` compares the
  full body with `Buffer.equals` against `logoPayload(logo.name)`, under a comment explicitly
  rejecting same-length matching.
- **"Replace `m3u-ingest.spec.ts`'s source-text assertion with a behavioural test."** Rejected.
  The assertion guards `upstreamM3UAccount()` still calling
  `waitForCreateTimeGroupRefreshToSettle()` — a fixture-internal race defence whose removal was
  *demonstrated by mutation* to pass every behavioural test in the seeded project. That is the
  exact situation `quarantine.spec.ts` exists for, and the test's own comment records the
  mutation check. A behavioural replacement was tried and shown vacuous; the source-scan stays.
- **"`lifecycle-tests.yml` has never actually run in CI."** Half wrong, and **[corrected]**
  twice by G12's spec. It runs on every qualifying push and on schedule, and every such run is
  red — but the reviewer was right about pull requests, for a reason neither side had found:
  the `suites` job carries `if: github.event_name != 'pull_request'` (`lifecycle-tests.yml:134`),
  a gate independent of the path filter. **The two bash suites have therefore never run in CI
  on a pull request at all**, so the green runs on G7's own PR skipped both.

  The failure figures were wrong too: "8 of 126" and "7 of 12" are *assertion* counts. The
  scenario counts are **8 failed assertions across 4 of 20** puid-pgid scenarios and **7 of 8**
  tls-postgres scenarios. So are the causes: the puid failures are **three distinct causes,
  none of them a live ownership bug** (a dead premise — `:latest` is no longer a pre-PUID
  image; a suite still testing a feature `7e221720` deliberately removed; and an intermittent
  timeout), and the TLS failures are **one cause seven times** — `mktemp -d` creates 0700 and
  the container reads `/certs` as UID 1000, invisible on Docker Desktop. A permanently red
  workflow provides no signal at all; triaging it to green is G12's first task.
- **"The suite isn't black-box enough to survive a migration"** — overstated as a general claim.
  Redis key shapes and `docker exec`/`pgrep` are confined to the one allowlisted
  `streaming-greybox` spec and its guard; `manage.py showmigrations` and docker control are
  confined to the `lifecycle` projects' own machinery (`fixtures/instance.ts`), which manages
  containers because its subject *is* the container. What is accepted from this item is its
  actionable residue: the guard's narrow scope and the missing per-test taxonomy (both G11).

## The five goals

Definitions only; each is specced when dispatched, and each inherits every rule in the parent
roadmap ("Rules binding every goal", the `test.fail()` bug policy, COVERAGE.md updates in the
same PR). G12–G15 additionally apply G11's tag taxonomy to every test they add or touch.

**G11 — Migration-gate contract.** The migration merge gate, made explicit and enforced.
(1) A per-test taxonomy — `@contract` for portable black-box tests that must survive any
rewrite preserving behaviour, `@characterization` for tests deliberately coupled to this
implementation (AIO layout, Redis shapes, process names, `showmigrations`) — recorded in an ADR
stating what each tag promises, applied across all 144+ tests, with the default being
`@contract` and every `@characterization` annotation justifying itself in a comment.
(2) The quarantine guard generalised: the same source-scan pattern extended to police
`child_process` / `docker` / `pgrep` / `manage.py` usage anywhere under `e2e/tests/**` against
an explicit allowlist, so a grey-box escape hatch cannot be added silently.
(3) A run-everything CI mode: one mechanism (branch pattern, PR label, or `workflow_dispatch`
input — the spec decides) that ignores the `changes` path filter, adds the `lifecycle-upgrade`
project to the `e2e-tests.yml` matrix, and runs `lifecycle-tests.yml`'s jobs, documented as
**required on migration branches**.
(4) The frontend `data-testid` contract and the shared-instance mutation rules promoted from
prose (`e2e/README.md`, `helpers.ts` comments) to an ADR plus an enforced guard in the
`quarantine.spec.ts` mould.

**G12 — Lifecycle depth.** The single most migration-critical suite, deepened.
(1) Triage the fifteen red bash-suite scenarios to product defect vs suite/CI-environment
defect, file or fix accordingly, and leave `lifecycle-tests.yml` green so it has signal.
(2) Extend `durable-state.ts` from seven scalar rows to the relations a migration would lose
silently: channel↔stream links, Channel Profile memberships, EPG programme rows for the seeded
source, an XC user whose credentials still authenticate post-event, VOD movie/series/episode
rows, a scheduled recording, and a logo file — each by id, asserted after both restart and
upgrade. (3) Backup restore end to end, on the isolated instance the COVERAGE.md row already
prescribes. (4) Non-zero `refresh_interval` / celery-beat scheduling on an isolated instance,
closing the G3 D10 cost the ledger records, including the `bootstrap`-only pre-warm rule (#7).

**G13 — DVR execution.** A recording that actually fires: the fake provider serves the stream,
`run_recording` executes, the file lands and is observable, the recording row transitions, and
the recording plays back; recurring rules; the `recording_cancelled` WebSocket event and its
siblings. Whether comskip is exercised or characterized-and-deferred is the spec's call — it
must say which, in writing.

**G14 — Coverage completions.** The remaining accepted gaps, scoped tightly: EPG fuzzy
matching / `set-names-from-epg` characterization against the fake XMLTV (Schedules Direct stays
out — a live external service, per the roadmap's non-goals); blocked-network ACL 403 negatives
(**[corrected]**: specified here "on an isolated instance"; G14's spec showed none is needed —
`get_client_ip` honours a client-supplied `X-Real-IP`, the peer being the Docker bridge inside
the default trusted set, and nginx neither sets nor strips it on the `uwsgi_pass` routes, so a
403 is reachable on the shared `seeded` project with zero settings writes, deleting an
isolated-instance project and a CI job from wave 6. The shared `XC_API` ACL is still why G5
could only test the 401 half);
settings with behavioural effect beyond User-Agent persistence; plugin install-from-zip → run →
task-fires lifecycle; channel bulk operations and reordering; M3U filters, profiles and server
groups; product WebSocket events beyond the harness's own `ws-fixture` — **[corrected]**, and
this one bites: `core/utils.py:log_system_event` sends **no** WebSocket message at all. It
writes a `SystemEvent` row and fans out to Connect. So `apps/connect/models.py:SUPPORTED_EVENTS`
is the wrong map for this sub-area, and a spec written from it would wait on events the product
never sends; the WebSocket vocabulary is a separate, larger set sent via
`core/utils.py:send_websocket_update`.

**G15 — Test-quality remediation.** One PR of small verified fixes: premise guards backported
to every pre-G9 `test.fail()` site (audit all of them; #15 and #82 are confirmed instances) — **[corrected]** with the audit's
result: **20** `test.fail()` pins exist on `main` at `76db0332`, of which **9 need a guard and
11 are already safe**. All three pins G10 shipped are already guarded, two by siblings titled
"row 8 premise:" / "row 13 premise:", so the pattern is already house standard for new work and
the debt is entirely pre-G9;
real interactions for `stats`, `guide` and `backups`; `expectWellFormedXml` in
`xc-output.spec.ts`; the two residual first-byte-only TS assertions (the `catchup-cascade` one
lands after #113 merges); post-switch byte attribution in the failover specs if the TS pattern
can carry a per-stream marker (spec decides, and says so either way); an audit of status-only
assertions in `api-fixture`/`authorization` specs; a versioned contract doc for `e2e-upstream`
recording its known quirks (no calendar validation, no time-addressable archive) so consumer
goals cite a version, not a memory.

## Goal status

All five are specced. Each spec verified this document's claims against the tree and corrected
what it found; those corrections are folded in above.

| Goal | Spec and plan | PR |
|---|---|---|
| G11 | `2026-09-01-e2e-migration-gate-design.md` | — (wave 5, lands first) |
| G12 | `2026-09-01-e2e-lifecycle-depth-design.md` | #116 |
| G13 | `2026-09-01-e2e-dvr-execution-design.md` | #115 |
| G14 | `2026-09-01-e2e-coverage-completions-design.md` | #118 |
| G15 | `2026-09-01-e2e-test-quality-remediation-design.md` | #117 |

Two goal-level questions this document left to a spec are now decided, in writing:

- **G13, comskip:** characterized-and-deferred. Detection is not constructible against G2's
  asset — `docker/comskip.ini` sets `detect_method=127`, and a `testsrc` pattern with a 440 Hz
  sine has no logo, no black frames, no silence and no commercial structure, so only the
  short-circuit paths are reachable. G13 tests the dispatch chain instead and asserts nothing
  about commercials.
- **G15, per-stream TS markers:** feasible under Proxy, impossible under FFmpeg, deliberately
  not built. See the corrected entry above.

## Sequencing

Wave 5 is G11 alone: it rewrites annotations across every spec file, so nothing else should be
in flight. Wave 6 is G12–G15 in parallel — disjoint subjects and, deliberately, disjoint files
(G13 owns `dvr.spec.ts`; G14 owns `settings`/`plugins`; G15's file list is fixed above and
overlaps neither). PRs #112 and #113 merge before wave 5.

## Non-goals

- Re-running the refuted items above.
- Comskip fidelity beyond what G13's spec explicitly commits to.
- Schedules Direct against the live service.
- Any change to the product itself: the bug policy is unchanged — test goals file, they do not fix.
- Widening into a general quality programme. These five goals exist to make the suite a
  trustworthy migration gate; when they land, the programme returns to the extraction.
