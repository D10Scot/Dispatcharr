# G13 — DVR Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a recording actually fire. The fake upstream provider serves a stream, `run_recording` executes for the first time in this repository's history, ffmpeg writes HLS segments, the segments concatenate to an MKV, the `Recording` row transitions, and the recording plays back — plus recurring rules, the seven-member DVR WebSocket event family, and a bounded characterization of comskip's dispatch chain.

**Architecture:** One new Playwright project, `dvr`, running one worker with a 300 s per-test budget and its own CI matrix job (and therefore its own container). Everything is observed over HTTP: the `Recording` detail endpoint, `GET /api/channels/recordings/<id>/file/` with its Range support and its in-progress 302, `GET …/hls/index.m3u8` and its segments, the fake provider's connection log, and `/ws/`. **There is no `docker exec` in this goal** and no filesystem access from a test.

**Tech Stack:** TypeScript, Playwright 1.62.x, Node 24, the G1 fixture set (`api`, `seed`, `upstream`, `waitFor`, `ws`), the G2 fake provider, Docker.

**Spec:** `docs/superpowers/specs/2026-09-01-e2e-dvr-execution-design.md` — read it before Task 1. Every task below cites the decisions it implements.

**Base:** branch from `origin/main` at or after `45a33a4a` — the commit G11 landed on. G11 is a
hard prerequisite, not a preference: the tag guard is blocking and fails closed, and the settings
allowlist this plan edits does not exist before it.

**Why this goal matters to the extraction:** DVR is the product's only non-human client of the
relay. Read "Migration relevance" in the spec before Task 4 — it names which four rows are the
gate (1, 3, 4, 6), which two are ordinary regression coverage (5, 7), and which two a migration
branch is expected to rewrite rather than fix (2, 8).

## Global Constraints

Copied from the spec and the programme rules. Every task's requirements implicitly include this section.

- **Every recording this goal creates gets a `start_time` unique to the test, derived from the run token, never a rounded clock value.** `schedule_recording_task` calls `ClockedSchedule.objects.get_or_create(clocked_time=eta)`, and `ClockedSchedule.clocked_time` has no unique constraint (verified in-image). Two concurrent creates at an identical timestamp both INSERT and every later `get_or_create` for that timestamp raises `MultipleObjectsReturned` — the `IntervalSchedule` land mine (#7) in a second location, with no API that can delete the duplicate. **Do not provoke it.** (Spec D4, D10.)
- **`POST /api/channels/recordings/` must always carry a future `end_time`.** `RecordingSerializer.validate` 400s on a past one, and silently rewrites a past `start_time` to `now`.
- **Correlate every WebSocket wait.** `/ws/` is one broadcast group. `recording_updated`, `recording_extended`, `recording_cancelled` and `comskip_status` carry `recording_id` — predicate on it. `recording_started`, `recording_stopped` and `recording_ended` carry **only `channel`** — predicate on the seeded channel's generated name. A bare `waitForMessage(type)` is wrong in every case. (`e2e/fixtures/ws.ts` says so at length; spec D11.)
- **Every test cleans up in an `afterEach`, never at the end of the body.** Playwright tears a timed-out test down mid-`await`; body-level cleanup does not reliably run. A leaked ad-hoc recording poisons the *`frontend`* project through [#71](https://github.com/D10Scot/Dispatcharr/issues/71) and leaves a live `PeriodicTask` that fires hours later. (Spec D8.)
- **`e2e/fixtures/instance.ts` may not be imported.** It is confined to the two `lifecycle` projects — by its own header, and since G11 by `CONTAINER_LIFECYCLE` in `e2e/tests/guards/allowlist.ts`, which lists exactly those two specs. It destroys the shared container, network and provider. (Spec D2.)
- **Never assert a global count or an unfiltered list.** Scope every assertion to this test's own recording id, channel id or rule id. (Roadmap rule 4.)
- **Product defects are asserted correct, marked `test.fail()` with the defect named in a comment, and filed — never patched.** `gh issue create --repo D10Scot/Dispatcharr`; the explicit `--repo` flag is mandatory, because this checkout is a fork and `gh` without it files on upstream's public tracker. (Roadmap rule 5; spec D13.)
- **Every `test(` and `test.fail(` carries a tag, as an inline object literal second argument.** `test('title', { tag: '@contract' }, async ({ … }) => { … })`. `@contract` is the default and needs no justification. Rows 2 and 8 are `@characterization` and each carries a `// @characterization: <the fact it pins>` comment immediately above the `test(` call. **Do not hoist the details object to a `const`** — `e2e/tests/guards/tags.spec.ts` parses the call site, reports a by-reference details object as `unverifiable`, and fails closed with an empty `KNOWN_UNVERIFIABLE`. (`docs/adr/0002-e2e-test-taxonomy.md`; spec "Tags".)
- **No `docker exec`, no `child_process`, no `pgrep`, no `manage.py` anywhere under `e2e/tests/dvr/`.** `e2e/tests/guards/capabilities.spec.ts` polices exactly these against `CONTAINER_LIFECYCLE`, `SUBPROCESS`, `GREYBOX_REDIS` and `CONTAINER_INTROSPECTION` in `e2e/tests/guards/allowlist.ts`. G13 trips none of those four and must not need an entry on any of them. (`quarantine.spec.ts` no longer exists; G11 deleted it and moved its role here.) (Spec D5.)
- **`comskip.spec.ts` DOES need an allowlist entry, on `GLOBAL_SETTINGS_WRITE`.** It PATCHes `/api/core/settings/<id>/`, and `e2e/tests/guards/global-mutation.spec.ts` fails any such write from an unlisted file — it resolves URLs through module-level `const`s and template literals, so there is no way to write it that the guard does not see. Task 2 adds the entry with ADR-0003's three-part justification. (Spec D9, "The comskip decision".)
- **The typecheck hook is blocking.** Any edit to `e2e/**/*.ts` runs `tsc --noEmit` and blocks on failure. Run `cd e2e && npm ci` first or it degrades to a loud note.
- **The zizmor hook is blocking on every finding** in an edited `.github/workflows/*.yml`, legacy included. The workflows are at zero findings; keep them there. It fires on the `e2e-tests.yml` edit in Task 2.
- **Six shared files collide with G12, G14 and G15**, all additively: `e2e/playwright.config.ts`, `.github/workflows/e2e-tests.yml`, `e2e/tests/guards/allowlist.ts`, `e2e/package.json`, `e2e/COVERAGE.md`, `e2e/README.md`. Land them early (Task 2) to shrink the conflict window. The allowlist is compared with `toEqual`, so a rebase that drops G13's entry fails the `guards` job rather than passing silently.
- **Do not touch `e2e/fixtures/seed.ts` or `e2e/tests/frontend/dvr.spec.ts`.** G13 owns the latter as a lock and exercises it as a no-op (spec D7, D12).

## File Structure

**Created:**

| Path | Responsibility |
|---|---|
| `e2e/tests/dvr/helpers.ts` | `uniqueStartTime()`, `scheduleRecording()`, `waitForRecordingStatus()`, `readRecording()`, `MKV_MAGIC` |
| `e2e/tests/dvr/recording-execution.spec.ts` | Rows 1–2 — the flagship lifecycle, and the output-path characterization |
| `e2e/tests/dvr/recording-control.spec.ts` | Rows 3–4 — stop, extend |
| `e2e/tests/dvr/recording-events.spec.ts` | Rows 5–6 — `recording_cancelled`, both `was_in_progress` branches |
| `e2e/tests/dvr/recurring-rules.spec.ts` | Row 7 |
| `e2e/tests/dvr/comskip.spec.ts` | Row 8 — characterization, ordered last |

**Modified:**

| Path | Change |
|---|---|
| `e2e/playwright.config.ts` | Add the `dvr` project, after `frontend` and before `lifecycle` |
| `.github/workflows/e2e-tests.yml` | Add `"dvr"` to **both** JSON `projects` lists in the `changes` job |
| `e2e/tests/guards/allowlist.ts` | Add `tests/dvr/comskip.spec.ts` to `GLOBAL_SETTINGS_WRITE.allow` |
| `e2e/package.json` | Add `test:dvr`, and name it in the bare-`test` message |
| `e2e/fixtures/types.ts` | Add `RecurringRule`, additively at the end |
| `e2e/COVERAGE.md` | Eight rows, plus three gap rows |
| `e2e/README.md` | A `dvr` row in the Projects table, and `dvr` in the `## CI` section's account of the two `projects` lists |

---

### Task 1: File the two known defects before writing any test

The spec names two defects found while it was written. Both are filed first, so the tests that
work around them can cite issue numbers rather than prose, and so neither is quietly lost if the
implementation runs long. Implements spec D10 and D11.

**Files:** none — this task creates GitHub issues only.

- [ ] **Step 1: File the `ClockedSchedule` race**

Title: `Concurrent recordings at an identical start_time can permanently 500 that timestamp`.

Body must state, and be re-verified before filing:
- `schedule_recording_task` (`apps/channels/signals.py`) calls `ClockedSchedule.objects.get_or_create(clocked_time=eta)` from an `M3UAccount`-style `post_save` receiver on `Recording`.
- `ClockedSchedule.clocked_time` is a bare `DateTimeField`; the model's `Meta` declares no `constraints` and no `unique_together`. Verify by reading `django_celery_beat/models.py` inside a running container, e.g. `docker exec dispatcharr-e2e sed -n '/^class ClockedSchedule/,/^class /p' /dispatcharrpy/lib/python3.13/site-packages/django_celery_beat/models.py` — quote the output.
- `ATOMIC_REQUESTS` is off, so the window is a whole request wide.
- `ClockedSchedule.from_schedule` catches `MultipleObjectsReturned`; `schedule_recording_task` does not.
- Reachable from the product's own UI: `frontend/src/utils/forms/RecordingUtils.js`'s `createRoundedDate()` rounds `start_time` to a clock value, so two users scheduling the same broadcast produce identical timestamps.
- Same family as [#7](https://github.com/D10Scot/Dispatcharr/issues/7), which cost an agent an hour and four opaque failures. Narrower blast radius — one timestamp, not the whole container — but the same "no API can delete the duplicate row" property.
- Filed as a report, not a patch, per this programme's policy.

- [ ] **Step 2: File the WebSocket correlation gap**

Title: `Three of the seven DVR WebSocket events carry no recording_id`.

Body must tabulate all seven with their payload fields, cite `run_recording`, `RecordingViewSet.stop`, `RecordingViewSet.extend`, `RecordingViewSet.destroy` and `comskip_process_recording`, and note that `_stop_dvr_clients`'s own docstring says simultaneous recordings on one channel are a supported case — for which `recording_started`, `recording_stopped` and `recording_ended` are indistinguishable to any client, while the four siblings beside them are not.

- [ ] **Step 3: Label both `needs-triage` and record the numbers**

Both issues get the `needs-triage` label, matching every other finding this programme has filed. Record the two numbers; Tasks 3 and 5 cite them in test comments, and Task 10 cites them in `COVERAGE.md`.

**Verification:**
- [ ] `gh issue list --repo D10Scot/Dispatcharr --limit 5` shows both, on the fork and not upstream.

---

### Task 2: The `dvr` project, its CI job, and the shared-file edits

Lands every shared-file change in one commit, first, to shrink the rebase window against G12, G14 and G15. Implements spec D1 and D2.

**Files:**
- Modify: `e2e/playwright.config.ts`, `.github/workflows/e2e-tests.yml`, `e2e/tests/guards/allowlist.ts`, `e2e/package.json`, `e2e/README.md`

- [ ] **Step 1: Add the project**

`e2e/playwright.config.ts` declares ten projects at `45a33a4a`, in this order: `bootstrap`,
`guards`, `pristine`, `seeded`, `streaming`, `streaming-failover`, `streaming-greybox`,
`frontend`, `lifecycle`, `lifecycle-upgrade`. Insert `dvr` **after the `frontend` block and
before the `lifecycle` block** — `dvr` depends on `bootstrap` and shares the container, so it
belongs with the ordinary projects rather than after the two that destroy it. `frontend`'s block
ends with the same `use: { storageState: … }` line and the same "Required. `adminPage` is an alias
of `page`" comment reused below; `lifecycle`'s block opens with the comment "Owns its container's
lifecycle: restarts it mid-test. Must run alone".

```ts
{
  name: 'dvr',
  testDir: './tests/dvr',
  dependencies: ['bootstrap'],
  // 300s, matching the three streaming projects rather than `frontend`'s
  // 120s. Every row here waits out a real recording: beat's clock is a 5s
  // tick (`DEFAULT_MAX_INTERVAL` in django_celery_beat's schedulers, with
  // `beat_max_loop_interval` unset), `run_recording`'s own
  // `_first_segment_timeout` is 15s, and the shortest useful capture is 30s.
  // The headroom is what turns a wedged `run_recording` into a named wait
  // failure instead of a bare project timeout.
  timeout: 300_000,
  // One worker, and `fullyParallel` left unset so it inherits `false`.
  // Three independent reasons, any one of which is already this suite's
  // standard for serialising a project:
  //
  //  1. Every row writes under `/data/recordings` — a hard-coded literal in
  //     `_build_output_paths`, not a setting — and the finalisation step
  //     concatenates and remuxes there.
  //  2. `comskip.spec.ts` mutates the global `dvr_settings` CoreSettings row
  //     (`comskip_enabled`, `comskip_mode`) for the duration of its run. That
  //     is the same hazard `streaming-failover` serialises for
  //     (`proxy_settings.buffering_speed`) and `streaming-greybox` serialises
  //     for (`stream_settings.default_stream_profile`), and both of those
  //     blocks argue that serialising makes the race structurally impossible
  //     rather than merely documented. It does here too.
  //  3. A firing recording is a live-proxy client of its own channel, and
  //     rows assert the provider's live connection count. A second worker
  //     recording concurrently would not collide on the channel, but it would
  //     on the settings row above, and nothing would enforce the distinction.
  workers: 1,
  // Required. `adminPage` is an alias of `page`; the admin identity comes
  // from this line, not from the fixture.
  use: { storageState: 'playwright/.auth/admin.json' },
},
```

- [ ] **Step 2: Add `dvr` to the CI matrix — in the `changes` job, on both lines**

**The matrix is no longer a YAML list on the `test` job.** G11 moved it: the `changes` job's
"Decide whether the E2E suite needs to run, and at what breadth" step builds two JSON **strings**
in a `run:` block, and the `test` job consumes `fromJSON(needs.changes.outputs.projects)`. The
file says so in a comment directly above them — *"The matrix lives here rather than in the `test`
job so that full mode can extend it. A NEW PROJECT MUST BE ADDED TO BOTH LINES."*

Add `"dvr"` to both:

```sh
projects='["pristine","seeded","streaming","streaming-failover","streaming-greybox","lifecycle","frontend","dvr"]'
if [ "$full" = "true" ]; then
  projects='["pristine","seeded","streaming","streaming-failover","streaming-greybox","lifecycle","frontend","dvr","lifecycle-upgrade"]'
fi
```

Nothing else changes. The `test` job's own comment already records that each project gets its own
container — which is what gives `dvr` the isolation Step 1's reason 2 depends on — and its "Run
E2E tests" step passes the project name through the **`PLAYWRIGHT_PROJECT` env var**, not string
interpolation, deliberately: interpolating a value that no longer comes from a literal list is a
zizmor `template-injection` finding, and the comment above the step says so. Do not "simplify" it
back.

`guards` stays out of both lists. It needs no container and has its own job.

- [ ] **Step 3: Add the npm script**

`"test:dvr": "playwright test --project=dvr"` in `e2e/package.json`, alongside the existing per-project scripts. The bare-`test` script's message does enumerate populations — add `test:dvr` to it. Note that `e2e/README.md` says "pick one of the eight" while the script already lists nine; adding `dvr` makes ten, so fix the count word in the same edit as Step 4.

- [ ] **Step 4: Document the project, in two places**

In `e2e/README.md`'s **Projects** table (the `| Project | What it is for |` table), add a `dvr`
row after `frontend` and before `lifecycle`: what it covers, that it runs one worker, and that
**it must be run alone locally** — worded like `streaming-greybox`'s row, which is the closest
precedent (a project observing container-wide state that anything else running would disturb).
The two `lifecycle` rows say "Runs alone" for a stronger reason: they destroy the container.
`pristine`'s row does **not** state a run-alone rule, so do not claim it as precedent.

Then the **`## CI`** section, which since G11 describes the two `projects` lists rather than a
hardcoded matrix. It already carries the instruction — *"If you add another project to
`playwright.config.ts`, add it to both `projects` lists in that job"* — and enumerates the
projects the workflow runs. Add `dvr` to that enumeration so the section does not contradict the
workflow.

- [ ] **Step 5: Allowlist the comskip settings write**

In `e2e/tests/guards/allowlist.ts`, add `'tests/dvr/comskip.spec.ts'` to `GLOBAL_SETTINGS_WRITE.allow`, with a comment beside it in the shape the four existing entries use. ADR-0003 requires the diff to say three things, and all three belong in that comment:

- **Which group it writes** — `dvr_settings`, and only that row: `comskip_enabled` and `comskip_mode`, merged into a copy of the row's existing `value`.
- **Why nothing else reads it during the run** — the `dvr` project gets its own container in CI and is `workers: 1`, so no other test is executing while the flag is on. And unlike `proxy_settings`, whose group cache ADR-0003 warns can outlive the test that wrote it, `CoreSettings._get_group` invalidates `dvr_settings` on `post_save`, so the restore takes effect immediately rather than up to 300s later.
- **How teardown restores it** — an `afterEach` PATCHes the captured `value` dict back verbatim, every key of it. See Task 8 Step 2 for why "verbatim" is load-bearing.

Landing this entry in Task 2, before `comskip.spec.ts` exists, is deliberate: it is a shared file, and the guard's `toEqual` comparison means the entry is inert until the file appears — a stale entry would fail, but this one becomes live in Task 8 of the same PR.

**Verification:**
- [ ] `cd e2e && npx playwright test --list --project=dvr` exits 0 and lists nothing (the directory is empty).
- [ ] `cd e2e && npx tsc --noEmit` passes.
- [ ] The zizmor hook reports **zero findings** on the edited workflow. If it reports anything, fix it before moving on — this is a ratchet.
- [ ] `git diff --stat` shows five files, all additive.
- [ ] `cd e2e && npm run test:guards` is red on exactly one thing — `GLOBAL_SETTINGS_WRITE` naming a file that does not exist yet — and green again after Task 8. If it is red on anything else, Step 5 is wrong. (If a red `guards` job between tasks is unacceptable in your workflow, move Step 5 to the head of Task 8 instead; it is the same edit, and the only cost is a wider rebase window on a shared file.)

---

### Task 3: `helpers.ts` — the recording factory and its start-time rule

The one place D4's rule is enforced, and the shared vocabulary for five spec files. Implements spec D4 and D7.

**Files:**
- Create: `e2e/tests/dvr/helpers.ts`
- Modify: `e2e/fixtures/types.ts` (add `RecurringRule`)

**Interfaces produced:**
- `uniqueStartTime(offsetMs: number): string` — an ISO timestamp `offsetMs` from now, with sub-second entropy that no other test can collide with.
- `scheduleRecording(api, channelId, opts): Promise<Recording>` — POSTs to `/api/channels/recordings/`.
- `readRecording(api, id): Promise<Recording>` — typed detail read.
- `waitForRecordingStatus(waitFor, id, statuses, options): Promise<Recording>` — polls the detail endpoint until `custom_properties.status` is one of `statuses`.
- `MKV_MAGIC: Buffer` — `1A 45 DF A3`.

- [ ] **Step 1: Write the file header**

It must state, in prose a future author will read before copying a test:

- Why `uniqueStartTime` exists — the `ClockedSchedule` race from Task 1, by issue number, and that a rounded or shared timestamp reopens it. This is the single most important comment in the goal.
- That `end_time` must always be in the future, because `RecordingSerializer.validate` 400s otherwise and silently clamps a past `start_time` to `now`.
- That a recording created here MUST be deleted in an `afterEach`, with the #71 and stale-`PeriodicTask` consequences named.

- [ ] **Step 2: Implement `uniqueStartTime`**

Derive the sub-second component from the Playwright worker index plus a module-scoped monotonic counter, not from `Math.random()` — a deterministic offset makes a collision impossible rather than improbable, and makes a failure reproducible. Returns an ISO-8601 string with milliseconds, which DRF parses.

- [ ] **Step 3: Implement `scheduleRecording`**

```ts
type ScheduleOptions = { startInMs: number; durationMs: number };
```

POSTs `{ channel, start_time, end_time }` — and **no `custom_properties`**, because supplying a `program` dict would switch on the DVR pre/post offset padding in `RecordingSerializer.validate` and move the window out from under the test. Returns the created row via `api.json<Recording>`.

- [ ] **Step 4: Implement `waitForRecordingStatus`**

Built on `waitFor.resource<Recording>`, with a `describeLast` that reports the last-seen `custom_properties.status` and `interrupted_reason`. A timeout here must say *what state the recording was actually in*, or every firing failure reports the same useless elapsed time.

- [ ] **Step 5: Add the `RecurringRule` type**

At the end of `e2e/fixtures/types.ts`, matching `RecurringRecordingRuleSerializer`: `id`, `channel`, `days_of_week: number[]`, `start_time: string`, `end_time: string`, `enabled: boolean`, `name: string`, `start_date: string | null`, `end_date: string | null`. Cite the serializer in the doc comment, as every neighbouring type does.

**Verification:**
- [ ] `cd e2e && npx tsc --noEmit` passes.
- [ ] Nothing in `helpers.ts` imports `child_process`, `docker`, or `fixtures/instance`.

---

### Task 4: Row 1 — the flagship, and Row 2 — the output-path characterization

The goal's centre. First execution of `run_recording` under any test. Implements spec D3, D5, D6.

**Files:**
- Create: `e2e/tests/dvr/recording-execution.spec.ts`

- [ ] **Step 1: Set up the fixture and the `afterEach`**

`upstream.scenario()` with one explicit channel (id and name declared, per the suite's rule that an implicit catalogue is a collision), then `seed.upstreamChannel(scenario, { channelIds: [1] })`. Record the channel id and the recording id in module-scoped bindings **assigned the moment each resolves**, and delete both in an `afterEach` — the shape `dvr.spec.ts` and `plugins.spec.ts` document. Safe here because the project is `workers: 1` with `fullyParallel` inherited `false`.

- [ ] **Step 2: Schedule and wait for the fire**

`scheduleRecording(api, channel.id, { startInMs: 5_000, durationMs: 30_000 })`. Then, **before** waiting on the WebSocket, open the `ws` listener — a listener opened after the event has fired waits forever. Wait for `recording_started` with `where: (d) => d.channel === channel.name` (it carries nothing else — Task 1's second issue).

Budget the wait at 60 s and say why in a comment: 5 s until `start_time`, plus beat's 5 s worst-case tick, plus dispatch and DB sync, times a safety factor.

- [ ] **Step 3: Assert the in-flight state**

`waitForRecordingStatus(…, ['recording'])`. Then assert:
- `custom_properties.file_url === '/api/channels/recordings/<id>/hls/index.m3u8'` — the start transition, independent of `status`.
- `(await upstream.connections(scenario)).live === 1` — **this is the assertion that makes the test end to end.** DVR records `f"{base}/proxy/ts/stream/{channel.uuid}"`, so a live provider connection proves bytes flowed provider → `live_proxy` → ffmpeg.

- [ ] **Step 4: Assert in-progress playback**

- `GET /api/channels/recordings/<id>/file/` with `redirect: 'manual'` → **302**, `Location` ending `/hls/index.m3u8`.
- `GET` that playlist → body starts `#EXTM3U` and names at least one `seg_` entry. **Do not assert a segment count** — ffmpeg with `-c copy` ingests as fast as the proxy delivers, so the number of 4-second segments produced in 30 wall seconds is not fixed. `e2e-upstream/README.md` states the same rule for throughput generally.
- `GET` the first named segment → `expectTsAligned(buffer)`. These are raw MPEG-TS segments, so the existing assertion applies unchanged. This is the strongest single proof that `run_recording` wrote real video: the bytes come back out.

- [ ] **Step 5: Assert completion**

Wait for `recording_ended` (`where` on `channel.name` again), then `waitForRecordingStatus(…, ['completed'])`, budgeted at 90 s from the start of the wait — the capture window plus the concat and remux. Assert:
- `custom_properties.bytes_written > 0`
- `custom_properties.ended_at` is present
- `custom_properties.file_url === '/api/channels/recordings/<id>/file/'` — flipped back.

If `status` lands on `interrupted`, the assertion message must surface `custom_properties.interrupted_reason`; that field is the whole diagnostic budget for a failed first contact.

**This requirement is the goal's main contribution to the migration gate, so do not treat it as polish.** DVR builds its URL from `get_dvr_stream_base_url()` and a channel UUID. When the relay moves out of the Django process that base URL is wrong, and if the stream endpoint becomes the HMAC-signed URL `CLAUDE.md` intends, DVR has no way to mint one. Neither failure produces an error at the API: the recording is scheduled, dispatched and started, ffmpeg is refused, and `run_recording` gives up at `_first_segment_timeout` fifteen seconds later with `status: 'interrupted'`. Without `interrupted_reason` in the message, the most informative failure in the whole suite reads as a bare wait timeout. See the spec's "Migration relevance".

- [ ] **Step 6: Assert the finished file over HTTP**

- `GET /file/` → **200**, `content-type: video/x-matroska`, `content-length` > 0, `accept-ranges: bytes`.
- The body's first four bytes equal `MKV_MAGIC` (`1A 45 DF A3`, EBML). Not a length check — a format check, in the spirit of `logo-upload.spec.ts`'s `Buffer.equals`.
- `GET /file/` with `Range: bytes=0-1023` → **206**, `content-range: bytes 0-1023/<the size seen above>`, and a 1024-byte body.

- [ ] **Step 7: Row 2 — the output-path characterization**

A second `test()` in the same file, against a recording it creates itself (the flagship's is gone by then), declared as:

```ts
// @characterization: `library_root = '/data/recordings'` is a hard-coded literal in
// `_build_output_paths`, not a setting, and the path shape is the shipped default of
// `get_dvr_tv_fallback_template`. A deployment that relocates the library, or a change to
// the default templates, legitimately breaks this row.
test('the recording lands where the DVR templates say it should', { tag: '@characterization' }, async ({ … }) => {
```

The comment above the call is what ADR-0002 requires of every `@characterization` test — the guard checks the tag, not the comment, so nothing but review enforces it. The fact it pins: `library_root = '/data/recordings'` is a **hard-coded literal** in `_build_output_paths`, not a setting; and the shape asserted is the shipped default of `get_dvr_tv_fallback_template` (`TV_Shows/{show}/{start}.mkv`), taken because a recording with no EPG programme has `season == 0 and episode == 0`.

Assert, from `custom_properties` on the ordinary detail endpoint and **not** from the filesystem:
- `file_path` starts with `/data/recordings/`
- `file_path` matches `TV_Shows/<the channel's generated name>/<8 digits>_<6 digits>.mkv`
- `basename(_hls_dir) === '.dvr_<id>_hls'`

This row does not need the recording to complete — the paths are written at prime time, before ffmpeg starts — so it may assert as soon as `status === 'recording'` and then delete the recording. Doing so keeps it under 20 s.

**Verification:**
- [ ] `cd e2e && npm run test:dvr -- recording-execution` passes twice in a row against a fresh container.
- [ ] Deliberately break one link and confirm the failure names it: point the channel at a non-existent upstream URL and confirm the test fails at Step 3's `live === 1` or at Step 5 with `interrupted_reason`, not with a bare timeout.
- [ ] `GET /api/channels/recordings/` after the run returns no rows for the seeded channel — cleanup worked.

---

### Task 5: Rows 3 and 4 — stop and extend

The two control endpoints that reach into a running `run_recording`. Both exercise the main loop's DB re-read, which is the most extraction-sensitive part of the task.

**Files:**
- Create: `e2e/tests/dvr/recording-control.spec.ts`

- [ ] **Step 1: Row 3 — stop preserves `stopped`**

Fire a 45 s recording. At `status === 'recording'`, `POST /api/channels/recordings/<id>/stop/`.

Assert:
- the `recording_stopped` event arrives (`where` on `channel.name` — it carries nothing else);
- `status` settles on `stopped` and **stays** `stopped`. The trap is that `run_recording`'s finalisation block runs *after* the stop and re-reads the row; its documented priority is `stopped` > `completed` > `interrupted`. Poll for at least 15 s past the transition to prove `completed` never overwrites it — a single read immediately after the POST would pass even if the priority were broken.
- `custom_properties.stopped_at` is present.
- `GET /file/` serves a non-empty MKV for the partial capture, with the EBML magic. "Retaining the partial content for playback" is the endpoint's own docstring; nothing has ever checked it.
- A **second** `POST /stop/` returns **409** — the terminal-state guard, free on a row that already exists.

- [ ] **Step 2: Row 4 — extend moves the deadline**

Fire a 20 s recording. At `status === 'recording'`, `POST /api/channels/recordings/<id>/extend/` with `{ extra_minutes: 1 }`. **Minutes is the unit**: the endpoint 400s on anything ≤ 0, so 60 s is the smallest extension the product permits.

Assert:
- the `recording_extended` event arrives, correlated on `recording_id`, with `extra_minutes: 1`;
- the row's `end_time` is exactly 60 s later than the value posted at create time;
- **the recording is still `recording` ~15 s past its original end.** This is the only external proof that the main loop re-read `end_time` from the DB and raised its own deadline — the mechanism the endpoint's docstring describes and nothing observes.

Then `POST /stop/` rather than waiting out the extra minute, and let the `afterEach` clean up. Note in a comment that `extend` writes with a queryset `.update()` specifically to bypass the `pre_save` receiver that would otherwise revoke the task — so a test asserting on `task_id` here would be asserting the wrong thing.

- [ ] **Step 3: Add `test.describe.configure({ mode: 'serial' })` only if measurement shows it is needed**

The project is already `workers: 1` with `fullyParallel` inherited `false`, so tests within a file are already serial. Do not add a redundant directive; if a reviewer asks, the config comment is the answer.

**Verification:**
- [ ] `cd e2e && npm run test:dvr -- recording-control` passes twice in a row.
- [ ] The stop row genuinely discriminates: temporarily invert the priority assertion (expect `completed`) and confirm it fails.

---

### Task 6: Rows 5 and 6 — `recording_cancelled`, both branches

The event the goal definition names, and the destroy path's three unobserved side effects.

**Files:**
- Create: `e2e/tests/dvr/recording-events.spec.ts`

- [ ] **Step 1: Row 5 — cancelling an upcoming recording**

Schedule a recording far enough out that it cannot fire — an hour, not a minute — and **not** at a rounded timestamp (`uniqueStartTime`). `DELETE` it. Assert:
- `recording_cancelled` arrives, correlated on `recording_id`, with `was_in_progress: false`;
- the row 404s on the detail endpoint.

This row is fast (~10 s) and is the honest place for the `was_in_progress: false` branch: it needs no recording to fire.

- [ ] **Step 2: Row 6 — cancelling an in-flight recording**

Fire a 45 s recording. At `status === 'recording'`, `DELETE` it. Assert:
- `recording_cancelled` with `was_in_progress: true` — the branch `apps/channels/tests/test_recording_stop_cancel.py` asserts as a payload shape and has never exercised for real;
- the row is gone;
- **`GET /file/` now 404s.** `RecordingViewSet.file` 404s only when neither the MKV nor `_hls_dir` exists, so a 404 proves the backgrounded `_safe_remove` / `_safe_rmtree` teardown ran. `COVERAGE.md`'s existing G6 gap row records this file deletion as never observed; this closes that third of it. The teardown is backgrounded in a daemon thread, so poll for it rather than asserting once — 30 s is generous.
- `(await upstream.connections(scenario)).live === 0` — proves the DVR-client teardown reached `live_proxy` and released the upstream. Poll, for the same backgrounding reason.

- [ ] **Step 3: Record what this pair does not close**

A comment at the top of the file, and a `COVERAGE.md` gap row in Task 10: the destroy path's fourth side effect — deleting the `PeriodicTask` and `ClockedSchedule` via the `post_delete` receiver — remains unobserved, because neither model has a REST surface. Closing it would need `docker exec`, which spec D5 rules out. State it rather than let it look like an oversight.

**Verification:**
- [ ] `cd e2e && npm run test:dvr -- recording-events` passes twice in a row.
- [ ] Row 6's `live === 0` poll does not simply pass because the recording had already ended — assert `was_in_progress: true` came back from the cancel *before* polling, so the premise is guarded outside the assertion. (This is the premise-guard pattern G9/G10 established and G15 is backporting; apply it here rather than leaving G15 to.)

---

### Task 7: Row 7 — recurring rules

The one row that costs no wall clock, because the product materialises synchronously.

**Files:**
- Create: `e2e/tests/dvr/recurring-rules.spec.ts`

- [ ] **Step 1: Create the rule and assert the materialisation**

`POST /api/channels/recurring-rules/` with the seeded channel, `days_of_week: [0,1,2,3,4,5,6]`, and a fixed `start_time`/`end_time` clock window. `RecurringRecordingRuleViewSet.perform_create` calls `sync_recurring_rule_impl(rule.id, drop_existing=True)` **inline in the request**, so the rows exist by the time the 201 returns — no wait, no polling.

Assert, over `GET /api/channels/recordings/` filtered to this channel:
- between **13 and 14** rows carry `custom_properties.rule.id === rule.id`. The horizon is 14 days and today's slot is skipped when `start_dt <= now`, so the count is one of exactly two values — assert the range and say why in a comment, rather than pinning a number that flips depending on the hour the suite runs.
- every one of them has a `start_time` in the future (the `start_dt <= now` skip);
- every one of them falls on a weekday in the rule's set (all seven here, so this asserts the mapping is applied at all — a rule with a narrower set is the sharper test, but needs the timezone reasoning below);
- each carries `custom_properties.rule.days_of_week` and `custom_properties.status === 'scheduled'`.

- [ ] **Step 2: Handle the timezone honestly**

`sync_recurring_rule_impl` resolves its window in `CoreSettings.get_system_time_zone()`, not UTC. Do **not** mutate that global setting — it is exactly the shared-state hazard the project serialises for, and it would affect every other row. Instead: read the system time zone through the settings API and compute the expected weekday set in that zone. If that proves awkward, assert the weaker property (all seven weekdays are represented across the 14-day window) and record the narrower-day-set case as a `COVERAGE.md` gap rather than mutating a global.

- [ ] **Step 3: Assert the purge**

`DELETE` the rule. `perform_destroy` calls `purge_recurring_rule_impl` after the delete. Assert every row from Step 1 is gone, by id. This is also the row's own cleanup, so the `afterEach` only needs to handle a mid-test failure.

**Verification:**
- [ ] `cd e2e && npm run test:dvr -- recurring-rules` passes, in under 20 s.
- [ ] Run it twice back to back and confirm the second run is not perturbed by the first — the purge is complete.

---

### Task 8: Row 8 — comskip dispatch (characterization)

Ordered last, deliberately. Implements spec D9. **Read "The comskip decision" in the spec before writing a line of this.**

**Files:**
- Create: `e2e/tests/dvr/comskip.spec.ts`

- [ ] **Step 1: Write the header first**

Declared `test('comskip dispatch reaches a terminal state', { tag: '@characterization' }, async ({ … }) => …)`, with a `// @characterization: …` comment immediately above the call naming the fact it pins — that `comskip` compiled in `docker/DispatcharrBase` is on `PATH` in this image and an ini exists at one of three AIO paths.

The file header must say, before any code:
- what this test asserts — that the dispatch chain runs to a terminal state and emits its event;
- what it deliberately does **not** assert — anything about commercial detection, in those words;
- why detection is not constructible: `docker/comskip.ini` sets `detect_method=127` (all seven methods), and G2's asset is `testsrc` video with a burned-in frame counter plus a 440 Hz sine (`e2e-upstream/scripts/make-asset.sh`) — no logo, no black frames, no silence, no commercial structure. `comskip_process_recording` can only reach its `exit code 1` or `sum(commercials) <= 0.5` short-circuits.
- why it is `@characterization`: it asserts a binary compiled in `docker/DispatcharrBase` is on `PATH` in this image, and that an ini exists at one of three AIO paths.

- [ ] **Step 2: Flip the settings — read, merge, PATCH the whole dict, restore verbatim**

**This is not a one-field PATCH, and getting it wrong reschedules every upcoming recording in the container.** `CoreSettingsViewSet` is a plain `ModelViewSet` with no `lookup_field` override, and `value` is a JSONField that PATCH **replaces wholesale**. The sequence is:

1. `GET /api/core/settings/`, find the row whose `key === 'dvr_settings'`, keep its numeric `id` and a deep copy of its `value` — the pk is per-instance and must never be hard-coded.
2. `PATCH /api/core/settings/<id>/` with `{ value: { ...original, comskip_enabled: true, comskip_mode: 'mark' } }`.
3. In the `afterEach`, `PATCH` the **original dict back verbatim**.

Verified live on a booted instance: `dvr_settings.value` carries ten keys and **does not include `comskip_mode` or `comskip_hw_accel`** — those come from `_get_group`'s defaults — so `comskip_mode` must be added explicitly, and every other key must be carried through. Dropping keys is not benign: `CoreSettingsViewSet.update` compares `pre_offset_minutes` and `post_offset_minutes` old-vs-new and **reschedules every upcoming recording** when they differ, and an omitted key reads back as `None`, which differs from `0`. Say all of that in a comment.

`mark` rather than the `cut` default is belt-and-braces and must be commented as such: if the synthetic asset ever did trip a false-positive detection, `mark` leaves the MKV untouched, so no sibling row's file assertions can be disturbed.

The restore runs **unconditionally**, including on timeout — this is a global settings row, and leaving it on would run comskip after every subsequent recording in the container. Note in a comment that `CoreSettings._get_group` caches in **Redis** and invalidates on `post_save`, not process-locally, so the flip reaches the `dvr` and `celery` workers immediately and needs no settling delay (unlike `proxy_settings`, whose 10 s process-local cache G4's spec had to work around).

- [ ] **Step 3: Run a recording and wait for the terminal state**

Fire a 30 s recording. After `status === 'completed'`, wait for `comskip_status` correlated on `recording_id`, then poll `custom_properties.comskip.status` until it is one of `completed`, `error`, `skipped`.

Assert only that. Do not assert `commercials`, do not assert `skipped`, do not assert `mode`. If the terminal state is `error`, that is a **pass** for this test's stated scope — and the assertion message should print `custom_properties.comskip.reason` so a reader can see which reason it was.

Budget the wait at 120 s and comment why the ceiling matters: `comskip_process_recording` is **not** in `task_routes`, so it runs on the shared prefork `celery` worker (`--autoscale=6,1`), not the `dvr` thread pool.

- [ ] **Step 4: The escape hatch — exercise it rather than weaken the test**

If, after three clean runs, this row is slow (over ~150 s) or flaky:
1. Delete it.
2. **Remove `tests/dvr/comskip.spec.ts` from `GLOBAL_SETTINGS_WRITE.allow` in the same commit.** `capabilities.spec.ts` and `global-mutation.spec.ts` compare with `toEqual`, so a stale entry fails exactly as loudly as a missing one — deleting the test without the allowlist edit turns the `guards` job red. This is the mechanism working, not a nuisance.
3. Replace it with a `COVERAGE.md` row: `Comskip dispatch | gap`, whose note states that the chain from `CoreSettings.get_dvr_comskip_enabled()` through `comskip_process_recording` to `custom_properties.comskip` is unobserved, and why (runtime against a synthetic asset was unbounded / the shared prefork queue made it non-deterministic — whichever was measured).
4. Say so in the PR description.

**Do not** weaken the assertion until it cannot fail. A comskip test that passes because it asserts nothing is worth less than an honest gap row. This instruction is the point of ordering this task last.

**Verification:**
- [ ] Three consecutive runs of `cd e2e && npm run test:dvr -- comskip`, with the elapsed time of each recorded.
- [ ] After the run, `GET /api/core/settings/` shows the `dvr_settings` row's `value` is **byte-identical to what it was before** — not merely that `comskip_enabled` is `false`. A restore that dropped `pre_offset_minutes` would pass the weaker check and leave a trap for the next recording.
- [ ] Kill the test mid-run (Ctrl-C) and confirm the setting is *still* restored, or if it is not, say so in the PR: an `afterEach` does not survive a SIGINT, and the mitigation is that the project owns its container.
- [ ] `cd e2e && npm run test:guards` is green — the `GLOBAL_SETTINGS_WRITE` entry added in Task 2 Step 5 now matches a real file, and `tags.spec.ts` accepts this file's declaration.

---

### Task 9: Full-project run and defect triage

The task that expects to find things. Implements spec D13 and the "Risks" section's first bullet.

**Files:** whichever spec files the triage touches.

- [ ] **Step 1: Run the whole project, three times, against a fresh container each time**

```bash
./scripts/e2e_up.sh --reset && cd e2e && npm run test:dvr
```

Record wall clock per run. The spec estimates ~6 minutes; if it exceeds ~12, say so in the PR and propose a split rather than raising the workflow's 30-minute job timeout.

- [ ] **Step 2: Triage every failure**

For each, decide: test defect, or product defect?

- **Test defect** → fix the test.
- **Product defect** → the test asserts **correct** behaviour, is marked `test.fail()` with a comment naming the defect and its symbol, and an issue is filed with `gh issue create --repo D10Scot/Dispatcharr` and labelled `needs-triage`. **Never patch the product.**
- **Cannot be made to discriminate** → delete the test and add a `COVERAGE.md` gap row saying what is unobserved and why. This is a legitimate outcome and is preferable to a test that passes for the wrong reason.

Expect this step to produce work. `run_recording` is 1,139 lines with 47 `try` blocks, most of them swallowing to a log line, and this is its first execution under a test.

- [ ] **Step 3: Guard every `test.fail()` premise outside the inverted block**

Any `test.fail()` written here must follow the G9/G10 pattern the disposition records: the premise (the recording fired, the row exists, the endpoint answered) is asserted **outside** the inverted block, so a failed seed or a 500 cannot satisfy `test.fail()` as convincingly as the real defect. G15 is backporting this to pre-G9 sites; G13 must not create new ones needing it.

- [ ] **Step 4: Confirm the flake profile**

Every wait in this goal is on a state transition or an event that either happens or does not — there is no threshold to drift across, so a flake should present as a **timeout naming the last observed state**, never as a wrong result. Confirm that by reading each `describeLast`. If any wait can time out without saying what it last saw, fix it.

**Verification:**
- [ ] Three consecutive green full-project runs, or a written account of each remaining red with its issue number.
- [ ] `grep -rn "test.fail" e2e/tests/dvr/` — every hit has a comment naming a defect and an issue link, **and an inline `{ tag: … }` second argument**. `test.fail` is a tagged declaration like any other; the guard reads it the same way.
- [ ] `cd e2e && npm run test:guards` is green. This is the real check for the two greps below — it parses rather than scans, so it does not fire on prose and cannot be satisfied by moving a marker into a comment. Run the greps too, as a fast local signal:
- [ ] `grep -rEn "child_process|docker |pgrep|manage\.py" e2e/tests/dvr/` returns nothing.
- [ ] `grep -rn "instance" e2e/tests/dvr/` shows no destructured `instance` fixture — `CONTAINER_LIFECYCLE` would fail, and D2 forbids it.

---

### Task 10: `COVERAGE.md`, and the PR

Roadmap rule 3: the inventory moves with the tests, in the same PR.

**Files:**
- Modify: `e2e/COVERAGE.md`

- [ ] **Step 1: Add the eight rows**

Under a `DVR` section (new — the two existing DVR rows live under `Frontend` and stay there, because they are G6's and describe the page, not the execution path). Each row names G13 and its status. Rows 2 and 8 are marked as characterization in their notes as well as their tags.

- [ ] **Step 2: Add the gap rows, each with its reason**

1. **Comskip detection** — deferred, not missed. Reason: G2's asset has no commercial structure and comskip's `detect_method=127` cannot find one; constructing a fixture with synthetic breaks is a provider build, which the roadmap's non-goals already fence.
2. **A recurring rule's recording firing** — `sync_recurring_rule_impl` skips any slot where `start_dt <= now`, so the earliest is a day out; there is no bounded-time path.
3. **Series rules** (`SeriesRulesAPIView`, `evaluate_series_rules`) — EPG-programme-driven; names G14.

Also update the **existing** G6 gap row about `PeriodicTask`/`ClockedSchedule` to record what G13 *did* close (the file deletion and the `recording_cancelled` event, both now asserted in Task 6) and what it deliberately did not (the two beat rows, which have no REST surface — spec D5).

- [ ] **Step 3: Cross-reference the two issues from Task 1**

Both get a `COVERAGE.md` mention: the `ClockedSchedule` race as a **decision not to reproduce**, in the same shape `e2e/README.md` records G3's decision on #7 — not as a gap, because "we chose not to poison the container" is a decision, and calling it a gap invites the next author to close it.

- [ ] **Step 4: Open the PR**

Two commits, Conventional Commits, `docs(e2e):` for the spec/plan pair and `test(e2e):` for the implementation. PR body covers: what fires now that never fired before, the comskip decision and its one-line reasoning, the two issues filed in Task 1, anything Task 9's triage turned up, the project's measured wall clock, and **the `GLOBAL_SETTINGS_WRITE` allowlist entry with its ADR-0003 justification** — that argument belongs where a reviewer reads it, not only in the allowlist comment.

Also state which rows are the migration gate. The PR is the last place a future reader looks before the spec, and "rows 1, 3, 4 and 6 prove DVR still records through the relay; 2 and 8 are expected to need rewriting when the image or the topology changes" is one sentence.

**Verification:**
- [ ] `e2e/COVERAGE.md` has no `todo` row owned by G13.
- [ ] Every claim in the PR body is backed by a command whose output was actually read — no "should pass".
- [ ] The full `dvr` project is green in CI, in its own matrix job — which requires `"dvr"` to be in **both** `projects` lists in `e2e-tests.yml`'s `changes` job. A missing entry does not fail; it silently runs nothing.
- [ ] The `guards` job is green, covering the tag on all eight declarations and the one allowlist entry.
