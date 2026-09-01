# G13 — DVR Execution

**Date:** 2026-09-01
**Status:** Draft, ready for review
**Wave:** 6 (parallel with G12, G14, G15; after G11)
**Parent:** `2026-08-23-e2e-coverage-roadmap-design.md`
**Goal definition:** `2026-09-01-e2e-programme-review-disposition.md`, "G13 — DVR execution"
**Verified at:** `origin/main` `cf95410e0c49a144d6935fbaa4d903a722ea25ed`
(`docs(e2e): disposition the external programme review, define G11–G15`, #114). Line numbers
drift; symbol names are the durable half of every citation, and every claim below was read out of
the tree — or out of the running `dispatcharr-e2e` container — this session.

**Depends on G11.** G11 defines the `@contract` / `@characterization` tag taxonomy and its ADR.
G13 *applies* that taxonomy and does not define it. Which of G13's tests carry which tag, and
why, is stated under "Tags" below; if G11 has not landed when G13 is implemented, G13 applies the
tags as the disposition document words them and G11's ADR reconciles the wording.

**Siblings in flight.** G12, G14 and G15 run in parallel. G13 collides with them on five shared
files, all additively: `e2e/playwright.config.ts` (G13 adds one project),
`.github/workflows/e2e-tests.yml` (its matrix), `e2e/package.json` (one script),
`e2e/COVERAGE.md` and `e2e/README.md`. Whoever lands second rebases through them, and the
workflow edit re-runs the zizmor hook, which blocks on **every** finding in the edited file — the
workflows are at zero findings and must stay there. G13 deliberately touches **neither
`e2e/fixtures/seed.ts` nor `e2e/tests/frontend/`** (see D7 and D12), which removes it from the two
conflict surfaces most likely to be busy.

## Goal

Make a recording actually fire, end to end: the fake upstream provider serves the stream,
`run_recording` executes, the file lands and is observable, the `Recording` row transitions
through its real states, and the recording plays back — plus recurring rules and the
`recording_cancelled` WebSocket event and its siblings.

`run_recording` (`apps/channels/tasks.py`, `run_recording`) is 1,139 lines with 47 `try` blocks
and **has never executed under any test in this repository's history** (confirmed below). It
spawns ffmpeg, records Dispatcharr's *own* live proxy output back into itself over HTTP, writes
HLS segments to a container filesystem, concatenates them to an MKV, and serves that MKV back
over a Range-capable endpoint. Every one of those steps is unobserved today. That is the point of
the goal: not DVR CRUD — G6 already proved that — but the execution path.

## Current state

`e2e/tests/frontend/dvr.spec.ts` (G6, 301 lines, one test) schedules a recording through the DVR
page's `DateTimePicker`s, asserts the row through `GET /api/channels/recordings/`, asserts the
card renders, and cancels it. It is deliberately built so the recording **never fires**: G6's D7
advances both pickers a month and picks the 15th precisely because
`getSingleFormDefaults()` would otherwise create a recording `run_recording` fires.

`e2e/COVERAGE.md` has exactly two DVR rows, both `done` and both G6's: the schedule/list/cancel
row, and a long **Gap** row recording that scheduling creates three objects — the `Recording`, a
`PeriodicTask` named `dvr-recording-<id>`, and a `ClockedSchedule` — with no DB cascade between
them and no REST surface on two of the three, and that `RecordingViewSet.destroy`'s three further
side effects (file deletion, the `recording_cancelled` WebSocket event, the backgrounded DVR-client
teardown) are never observed.

Backend unit coverage exists and is real but stops short of execution:
`apps/channels/tests/test_recording_scheduling.py`, `test_recording_pipeline.py`,
`test_recording_stop_cancel.py` and `test_recording_metadata.py` assert `run_recording`'s early
returns, inspect its source for a skip list, and assert WebSocket payload shapes — by patching,
inspecting and constructing, never by running it. Nothing in the repository spawns ffmpeg for a
recording.

## Verified facts this design rests on

Cited by symbol or filename. Two rows were read out of the running `dispatcharr-e2e` container's
site-packages rather than the repo, and say so.

| Fact | Source | Consequence |
|---|---|---|
| A `Recording` is dispatched by **django-celery-beat**, not `apply_async(countdown=…)`: `schedule_recording_task` creates a `ClockedSchedule` at the start time and a one-off `PeriodicTask` named `dvr-recording-<id>` whose `task` is `apps.channels.tasks.run_recording`, wired by the `post_save` receiver `schedule_task_on_save` | `apps/channels/signals.py`, `schedule_recording_task`, `schedule_task_on_save`, `_dvr_task_name` | The recording fires on beat's clock, not on a countdown. A test schedules by writing `start_time` and waits — there is no trigger endpoint to call |
| Beat's tick is **5 seconds**: `DatabaseScheduler.__init__` sets `max_interval = kwargs.get('max_interval') or self.app.conf.beat_max_loop_interval or DEFAULT_MAX_INTERVAL`, and `DEFAULT_MAX_INTERVAL = 5  # seconds`. Nothing in `dispatcharr/settings.py` or `dispatcharr/celery.py` sets `beat_max_loop_interval` | `django_celery_beat/schedulers.py`, read inside the running `dispatcharr-e2e` container (`django-celery-beat` 2.9.0, pinned in `uv.lock`); grep for `beat_max_loop_interval` across `dispatcharr/` returns nothing | **Worst-case dispatch latency is ~5 s plus one DB sync.** That is what makes a bounded-time firing test possible at all, and it is the number every wait budget below is derived from. See D3 |
| `run_recording` is routed to the **`dvr`** queue by `app.conf.task_routes`; `docker/uwsgi.ini` runs that queue as `celery -A dispatcharr worker -Q dvr -n dvr@%%h --pool=threads --concurrency=20`, separate from the prefork `celery` worker (`--autoscale=6,1`) | `dispatcharr/celery.py`, `task_routes`; `docker/uwsgi.ini` | A recording cannot be starved by M3U/EPG work, and twenty can run at once. G13 never runs more than one, but the isolation is why a single-worker project is not a throughput problem |
| **`comskip_process_recording` is *not* routed to `dvr`.** `task_routes` names only `run_recording` | `dispatcharr/celery.py`, `task_routes` | Comskip runs on the shared prefork `celery` worker alongside M3U refreshes. That is one of the two reasons the comskip row is bounded and ordered last. See D9 |
| DVR records **Dispatcharr's own live proxy**, not the provider directly: `stream_url = f"{base}/proxy/ts/stream/{channel.uuid}"`, where `base` is `get_dvr_stream_base_url()` → `http://127.0.0.1:5656` in AIO | `apps/channels/tasks.py`, `run_recording`, `get_dvr_stream_base_url` | A firing recording is a **live-proxy client**. `upstream.connections()` therefore proves the bytes originated at the fake provider and traversed `live_proxy` — G13 gets a free end-to-end assertion G4 had to construct |
| ffmpeg is spawned with plain `subprocess.Popen`, `-c copy`, `-f hls`, `-hls_time 4`, `-hls_list_size 0`, writing `seg_%05d.ts` plus `index.m3u8` into a hidden `.dvr_<id>_hls` directory | `apps/channels/tasks.py`, `_dvr_build_ffmpeg_cmd`, `run_recording`, `_build_output_paths` | A segment lands roughly every 4 media-seconds. This is a real subprocess — the second place in the suite that spawns one, after G4's ffmpeg Stream Profile row |
| `_first_segment_timeout = 15.0` and `_stall_timeout = 60.0` are local constants in `run_recording`'s HLS loop | `apps/channels/tasks.py`, `run_recording` | A recording shorter than ~15 s cannot distinguish "worked" from "the stream never arrived". The floor on a firing test's duration is set here. See D3 |
| At end of stream the segments are concatenated to the final container: `_dvr_build_hls_concat_cmd` builds an `ffmpeg -f concat -c copy` command, with an HLS→MP4→MKV fallback path | `apps/channels/tasks.py`, `_dvr_build_hls_concat_cmd`, `run_recording` | The MKV is materialised only at the end. `custom_properties.remux_success` records which path won |
| The library root is the **hard-coded literal** `library_root = '/data/recordings'` — not a setting, not an env var | `apps/channels/tasks.py`, `_build_output_paths` | Any assertion on the output path is coupled to the AIO layout. That is what makes the layout row `@characterization`. See "Tags" |
| For a recording with no EPG programme, `_build_output_paths` takes the TV **fallback** template, whose default is `TV_Shows/{show}/{start}.mkv` with `show` falling back to `channel.name` and `start` formatted `%Y%m%d_%H%M%S` | `apps/channels/tasks.py`, `_build_output_paths`, `_parse_epg_tv_movie_info`; `core/models.py`, `get_dvr_tv_fallback_template` | The final path is predictable from the seeded channel's generated name and the recording's start time, with no EPG dependency |
| `RecordingViewSet.file` serves the finished file over HTTP: `Content-Type: video/x-matroska` for `.mkv`, `Content-Length`, `Accept-Ranges: bytes`, and a real `206` with `Content-Range` for a `bytes=` request. When no MKV exists yet but `_hls_dir` does, it **302s to `/api/channels/recordings/<id>/hls/index.m3u8`**; when neither exists it 404s | `apps/channels/api_views.py`, `RecordingViewSet.file` | **The output file is fully observable over HTTP.** No `docker exec`, no filesystem access, no grey box. This is the single most important fact in this design. See D5 |
| `RecordingViewSet.hls` serves `index.m3u8` and the `seg_*.ts` segments, for in-progress *and* completed recordings, under `RECORDING_PLAYBACK_AUTHENTICATORS` with `AllowAny` at the DRF layer and `_user_can_play_recording` enforcing an authenticated principal | `apps/channels/api_views.py`, `RecordingViewSet.hls`, `RecordingViewSet.get_permissions`, `_user_can_play_recording` | In-progress playback is observable too, and the segments are raw MPEG-TS, so `expectTsAligned` applies to them directly |
| `custom_properties.status` moves `scheduled` → `recording` → one of `completed` / `stopped` / `interrupted`, with an explicit priority in the finalisation block: `stopped` wins over `completed`, `completed` over `interrupted` | `apps/channels/tasks.py`, `run_recording` (final metadata save); `apps/channels/api_views.py`, `RecordingViewSet.stop` | The row transition is a first-class assertion surface, on the ordinary REST detail endpoint |
| `custom_properties.file_url` is rewritten twice: to `/api/channels/recordings/<id>/hls/index.m3u8` when the recording starts, and back to `/api/channels/recordings/<id>/file/` when it ends | `apps/channels/tasks.py`, `run_recording` | The `file_url` flip is a cheap, exact proof of the start and end transitions, independent of `status` |
| The DVR WebSocket family has **seven** members, and **three of them carry no `recording_id`**: `recording_started`, `recording_stopped` and `recording_ended` are all `{"success": True, "type": …, "channel": channel.name}`. The other four do carry one — `recording_updated` (`recording_id`), `recording_extended` (`recording_id`, `new_end_time`, `extra_minutes`, `channel`), `recording_cancelled` (`recording_id`, `channel`, `was_in_progress`), `comskip_status` (`recording_id`, `status`) | `apps/channels/tasks.py`, `run_recording`, `comskip_process_recording`; `apps/channels/api_views.py`, `RecordingViewSet.stop`, `RecordingViewSet.extend`, `RecordingViewSet.destroy` | `/ws/` is one broadcast group (`e2e/fixtures/ws.ts` says so at length), so those three can only be correlated by **channel name** — which `seed.channel()`'s generated name makes unique. The inconsistency inside one seven-event family is also a product defect worth filing. See D11 |
| The Connect system-event vocabulary is a fixed dict of 17 entries and contains `recording_start` / `recording_end` — **not** `recording_cancelled`, which exists only as a WebSocket event | `apps/connect/models.py`, `SUPPORTED_EVENTS`; `core/utils.py`, `log_system_event` | The disposition's phrase "the `recording_cancelled` event and its siblings in `apps/connect/models.py:3–21`" conflates two vocabularies. G13 tests the **WebSocket** family (`recording_started`/`updated`/`ended`/`cancelled`/`comskip_status`); the Connect subscription surface is G14's `product WebSocket events` row, not G13's |
| A recurring rule materialises **synchronously inside the create request**: `RecurringRecordingRuleViewSet.perform_create` calls `sync_recurring_rule_impl(rule.id, drop_existing=True)` directly, not `.delay()` | `apps/channels/api_views.py`, `RecurringRecordingRuleViewSet.perform_create` | The recurring-rule row needs no wait at all. `maintain_recurring_recordings` runs hourly and is irrelevant to a test |
| `sync_recurring_rule_impl` walks a **14-day** horizon, skips any slot where `start_dt <= now`, and stamps each created row with `custom_properties.rule.id` | `apps/channels/tasks.py`, `sync_recurring_rule_impl` | A seven-day rule yields 13 or 14 rows, deterministically, and each is attributable to its rule. The `start_dt <= now` skip is also why a recurring rule's recording **cannot** be made to fire in a test — the earliest is a day out. See Non-goals |
| `RecordingViewSet.extend` takes **`extra_minutes`, a positive whole number of minutes**, 400s on anything else, and writes the new `end_time` with a queryset `.update()` specifically to bypass the `pre_save` receiver that would otherwise revoke the task. `RecordingViewSet.stop` writes `status: "stopped"` synchronously before backgrounding the teardown, and returns **409** if the status is already `completed`, `interrupted` or `failed` | `apps/channels/api_views.py`, `RecordingViewSet.extend`, `RecordingViewSet.stop`; `apps/channels/signals.py`, `revoke_old_task_on_update` | 60 s is the smallest extension the product permits, which sets row 4's arithmetic. The 409 is a free negative assertion on the same recording row 3 already owns |
| `RecordingSerializer.validate` rewrites a past `start_time` to `now` and rejects a past `end_time` with a 400. Pre/post offsets are applied **only** when `custom_properties.program` is a dict | `apps/channels/serializers.py`, `RecordingSerializer.validate`; `core/models.py`, `get_dvr_pre_offset_minutes` | An ad-hoc recording (no `program`) gets no offset padding, so its window is exactly what the test posted. A test must always post a future `end_time` |
| `CoreSettings._get_group` caches in **Redis**, invalidated by `CoreSettings` `post_save`/`post_delete` signals — not process-locally | `core/models.py`, `_get_group`, `_update_group`, `group_cache_key` | Unlike `proxy_settings` (G4's risk note: a 10 s process-local cache across four uWSGI workers), a DVR settings write is visible to the `dvr` and `celery` workers immediately. The comskip row needs no settling delay |
| The DVR settings row is written through `CoreSettingsViewSet`, a plain `ModelViewSet` over `CoreSettings` rows with **no `lookup_field` override**, so it is addressed by numeric pk and found by `key`. Its `value` is a JSONField that a `PATCH` **replaces wholesale, not merges**. On a booted E2E instance the `dvr_settings` row exists and its `value` is `{tv_template, series_rules, movie_template, comskip_enabled, tv_fallback_dir, pre_offset_minutes, comskip_custom_path, post_offset_minutes, tv_fallback_template, movie_fallback_template}` — note that **`comskip_mode` and `comskip_hw_accel` are absent**, supplied only by `_get_group`'s defaults | `core/api_views.py`, `CoreSettingsViewSet`; `core/models.py`, `get_dvr_settings`; read live from `dispatcharr-e2e` this session | The comskip row must read the row, merge its two keys into a copy of `value`, PATCH the **whole** dict, and restore the original verbatim. Dropping keys is not benign: `CoreSettingsViewSet.update` compares `pre_offset_minutes`/`post_offset_minutes` old-vs-new and **reschedules every upcoming recording** when they differ — and an omitted key reads back as `None`, which differs from `0` |
| `schedule_recording_task` calls `ClockedSchedule.objects.get_or_create(clocked_time=eta)`, and `ClockedSchedule.clocked_time` is a bare `DateTimeField` with `unique=False`; the model's `Meta` declares no `constraints` and no `unique_together` | `apps/channels/signals.py`, `schedule_recording_task`; `django_celery_beat/models.py`, `ClockedSchedule`, read inside the running container | **This is the `IntervalSchedule` land mine (#7) in a second location.** Two concurrent creates with an identical `start_time` both INSERT; every later `get_or_create` for that timestamp raises `MultipleObjectsReturned`, and unlike `ClockedSchedule.from_schedule` — which catches it — `schedule_recording_task` does not. See D10 |
| `e2e/fixtures/instance.ts` is quarantined to the two `lifecycle` projects and nothing else: it stops, replaces and destroys the shared container, and `e2e_up.sh`'s `destroy()` takes the shared network and the provider container with it | `e2e/fixtures/instance.ts`, header; `e2e/README.md` | G13 may not use it. Isolation must come from the project/CI-job topology instead. See D1 |
| Every Playwright project gets **its own container** in CI: `e2e-tests.yml`'s matrix runs one job per project and each calls `scripts/e2e_up.sh` — the workflow says so in a comment ("Each project gets its own container") | `.github/workflows/e2e-tests.yml` | A new project *is* the isolation mechanism this suite already has. Adding one costs a matrix entry, not a new mechanism |
| `run_recording` has never been executed by a test: `test_recording_scheduling.py` asserts its early returns, `test_recording_pipeline.py` **inspects its source** for a recovery skip list, `test_recording_stop_cancel.py` asserts the race guard and the `recording_cancelled` payload shape, `test_recording_metadata.py` asserts a `recording_updated` payload | `apps/channels/tests/test_recording_*.py` | Confirms the disposition's claim. Everything below row 1 is genuinely first contact |
| A leaked ad-hoc recording is actively hazardous to the `frontend` project: `categorizeRecordings()` keys "Upcoming Recordings" on `${program.tvg_id}|${program.title}`, which is `'\|'` for every recording with no EPG programme, so leaked rows collapse into one card and hide each other | `frontend/src/utils/pages/DVRUtils.js`, `categorizeRecordings`; filed as [#71](https://github.com/D10Scot/Dispatcharr/issues/71); `e2e/tests/frontend/dvr.spec.ts` header | G13 creates ad-hoc recordings by the handful. Cleanup is not hygiene here, it is a cross-project obligation. See D8 |

### On issues #70 and #71

The dispatch brief names both as "existing DVR issues". Checked against the tracker:

- **[#71](https://github.com/D10Scot/Dispatcharr/issues/71) is DVR** — the `categorizeRecordings()`
  grouping collapse, found while building G6's `dvr.spec.ts`. G13's tests **do not cover it**, and
  should not: it is a frontend rendering defect on the *Upcoming* list, and G13's subject is
  recordings that have left "Upcoming" and started. Covering it would mean a second browser test in
  a project that has no browser. It stays G6's `test.fail()`-free documented finding, and G13
  inherits only the *obligation* it created — clean up every ad-hoc recording (D8).
- **[#70](https://github.com/D10Scot/Dispatcharr/issues/70) is not DVR.** It is
  `_refresh_single_m3u_account_impl` reporting `Status.SUCCESS` after a swallowed
  `sync_auto_channels()` exception — an M3U ingest defect from G3, in the same family as #56, #59
  and #60. G13 neither covers nor inherits it. Recorded here so the brief's pairing is not carried
  forward as fact by a later goal.

## Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | **One new Playwright project, `dvr`: `workers: 1`, `fullyParallel: false`, `timeout: 300_000`, `dependencies: ['bootstrap']`, `storageState: admin.json`, and one new CI matrix job** | Three independent reasons, each of which alone is the house standard for a serialised project. (a) **Wall clock**: a firing recording costs ~60–90 s. `frontend`'s 120 s budget is already derived — its comment says so — from the backups poll and the Stats page, and would not hold; `seeded`'s is 30 s. (b) **Shared filesystem**: every recording writes under `/data/recordings`, and the finalisation step concatenates and remuxes there. (c) **A global `CoreSettings` mutation**: the comskip row flips `dvr_settings.comskip_enabled`, which is exactly the hazard `streaming-failover` serialises for (`proxy_settings.buffering_speed`) and `streaming-greybox` serialises for (`stream_settings.default_stream_profile`). Both of those projects' config comments argue that serialising makes the race *structurally impossible instead of merely documented*; that argument applies here unchanged. The CI matrix gives the project its own container for free, which is what makes (b) and (c) safe rather than merely serialised |
| D2 | **`e2e/fixtures/instance.ts` is not used, and G13 does not need an isolated instance beyond its own CI job** | `instance.ts` is quarantined to the `lifecycle` projects by its own header, and using it would put a container-destroying fixture in a fourth project. G13's isolation requirement is "nothing else is writing `/data/recordings` or the DVR settings row at the same time", which one matrix job plus `workers: 1` delivers exactly. Locally the project must be run alone, the same rule `pristine`, `streaming-greybox` and `lifecycle` already carry in `e2e/README.md` |
| D3 | **A recording fires in bounded time by being scheduled a few seconds out and running for 30 s of real time. No clock manipulation of any kind** | Every number is derived, not picked. Beat's tick is 5 s (verified in-image), so `start_time = now + 5 s` is dispatched by `now + ~10 s` worst case. `_first_segment_timeout` is 15 s and `hls_time` is 4 s, so a 30 s window clears the first-segment gate with 2× margin and yields several segments plus a concat. Nothing is faked: there is no `libfaketime` in the image, no clock fixture in the suite, and `run_recording` reads `time.time()` in a dozen places — a faked clock would be a second product under test. A test that waits 45 real seconds inside a 300 s budget is cheaper than any mechanism that avoids waiting |
| D4 | **The `start_time` of every recording G13 creates is unique to the test, derived from the run token, and never a rounded clock value** | D10's defect makes an identical `start_time` across two concurrent creates a container-poisoning race. G13 must not provoke it — the same call G3 made on #7, for the same reason: no assertion is worth poisoning the shared instance for every remaining test. Uniqueness is cheap and the helper enforces it in one place |
| D5 | **The output file is observed over HTTP, through `GET /api/channels/recordings/<id>/file/`. There is no `docker exec` anywhere in this goal** | `RecordingViewSet.file` already serves the finished MKV with `Content-Type`, `Content-Length`, `Accept-Ranges` and real `206`/`Content-Range` handling, 302s to the HLS playlist while the recording is in progress, and 404s when there is nothing. That is a complete observation surface: existence, size, container format (the EBML magic `1A 45 DF A3` in the first four bytes), seekability, and the in-progress/finished distinction — all black box, all portable across the relay extraction. Shelling into the container would buy only the directory listing, at the cost of a `@characterization` tag on the goal's flagship row and a new entry in the allowlist G11 is building. **The one thing HTTP cannot reach is the `PeriodicTask`/`ClockedSchedule` pair**, which has no REST surface; G13 does not close that gap and `COVERAGE.md`'s existing G6 row continues to record it |
| D6 | **The firing flagship is one test covering one recording's whole lifecycle, not three tests covering three facts** | Start, in-progress playback and completion are phases of one behaviour and cannot be observed independently without paying for three recordings. G4's multi-client row establishes the shape: drive one subject, assert at each transition. Splitting would triple the project's wall clock to prove nothing more |
| D7 | **The recording factory lives in `e2e/tests/dvr/helpers.ts`, not in `e2e/fixtures/seed.ts`** | It is DVR-project-specific, and it must carry D4's start-time rule in its own header where the next author will read it. Keeping it out of `seed.ts` also keeps G13 off the one fixture file G12 and G14 are most likely to be editing in the same wave. G6 made the opposite-direction version of this call (D6: no `seed.ts` changes at all) for a related reason |
| D8 | **Every test deletes its recordings and its channel in an `afterEach`, not at the end of the body** | Playwright does not raise a catchable exception on timeout — it tears the test function down mid-`await`, so a body-level cleanup does not reliably run. `dvr.spec.ts` and `plugins.spec.ts` both document this and both moved to `afterEach`. Here it matters more than usual: a leaked ad-hoc recording poisons the *`frontend` project's* DVR test through #71, and a leaked recording with a future `start_time` also leaves a live `PeriodicTask` that will fire against the container hours later |
| D9 | **Comskip is characterized-and-deferred: its detection is not exercised, its dispatch chain is, in exactly one `@characterization` test, ordered last** | Stated in full under "The comskip decision" below, because the goal definition requires this in writing |
| D10 | **The `ClockedSchedule` race is filed as an issue and deliberately not reproduced** | It is a genuine, previously unfiled defect of the same family as [#7](https://github.com/D10Scot/Dispatcharr/issues/7), and it is reachable from the product's own UI, because `RecordingUtils.js`'s `createRoundedDate()` rounds `start_time` to a clock value — two users scheduling "the 8 pm show" produce byte-identical timestamps. But provoking it leaves a duplicate row that no API can delete and that 500s every subsequent recording create at that timestamp. `e2e/README.md` already records that G3 made this exact call on #7 and that `COVERAGE.md` carries it as a decision, not a gap. G13 does the same |
| D11 | **The missing `recording_id` on `recording_started` / `recording_stopped` / `recording_ended` is filed as an issue, and the tests correlate on the seeded channel's generated name in the meantime** | `ws.ts` is explicit that a bare type match on a shared broadcast resolves on whoever's event arrived first, and requires a `where` predicate for any type a parallel test can produce. Those three events give a test nothing to predicate on but `channel`. `seed.channel()`'s generated name carries run-token entropy, so it is a sound correlator — but the product's own `_stop_dvr_clients` docstring says simultaneous recordings on one channel are a supported case, and for two such recordings these three events are indistinguishable to any client, while the four siblings beside them in the same family are not. That is a defect, not a test inconvenience |
| D12 | **G13 owns `e2e/tests/frontend/dvr.spec.ts` and does not modify it** | Ownership in wave 6 is a lock, not an obligation. The file's job is the DVR *page's* wiring, which it already proves; the `recording_cancelled` event belongs in the `dvr` project, where both the `was_in_progress: true` and `false` branches are reachable and neither costs a browser. Declaring the no-op explicitly is what keeps G14 and G15 out of the file and keeps G13's rebase surface at five files |
| D13 | **Product defects are asserted correct, marked `test.fail()` with the defect named in a comment, and filed — never patched.** Issues go to `gh issue create --repo D10Scot/Dispatcharr`, with the explicit `--repo` flag, always | Roadmap rule 5. This checkout is a fork whose `gh` resolves to upstream's public tracker without the flag. G13 expects to find more than the two defects named above — 1,139 lines with 47 `try` blocks running for the first time is the highest-yield surface in the programme — and the plan reserves a task for triaging whatever the first green run turns up |
| D14 | **No test asserts a global count or an unfiltered list** | Roadmap rule 4. Every recording is looked up by its own id or by its own channel id; the recurring-rule row counts only rows carrying its own `rule.id` |

## The comskip decision

The goal definition requires this in writing, so: **G13 does not exercise comskip's commercial
detection. It ships one `@characterization` test of comskip's dispatch chain, and records the
detection gap in `COVERAGE.md` as a deliberate deferral rather than an oversight.**

What comskip is here, verified. The binary is compiled from `refs/heads/master` in
`docker/DispatcharrBase` and installed to `/usr/local/bin/comskip`, so it *is* present in the
image under test. `run_recording`'s tail reads `CoreSettings.get_dvr_comskip_enabled()` and calls
`comskip_process_recording.delay(recording_id)`. That task resolves the binary with
`shutil.which("comskip")`, selects an ini from the DVR custom path, then `/etc/comskip/comskip.ini`,
then `/app/docker/comskip.ini`, runs it, and writes a terminal `custom_properties.comskip.status`
plus a `comskip_status` WebSocket event carrying `recording_id`.

Why detection cannot be exercised. `docker/comskip.ini` sets `detect_method=127` — all seven
methods: black frame, logo, silence, scene change, aspect ratio, closed captions and uniform
frame. G2's TS asset is synthetic `testsrc`-family video with a burned-in frame counter and a
constant tone (`e2e-upstream/scripts/make-asset.sh`, described in `e2e-upstream/README.md`, "The
asset"). It has no logo, no black frames, no silence, and no commercial structure of any kind.
Comskip run against it can only report no commercials — which `comskip_process_recording` handles
at two separate short-circuits (exit code 1, and `sum(commercials) <= 0.5`), both writing
`{"status": "completed", "skipped": true}` and returning before any re-mux. **A test that asserts
commercials were detected is not constructible from the assets this programme has**, and building
one would mean growing G2 a second asset with synthetic commercial breaks — a provider build, not
a test. The roadmap's non-goals already fence that: *"Comskip fidelity beyond what G13's spec
explicitly commits to."* This spec commits to none of it.

Why dispatch is still worth one test. The chain above is *Dispatcharr's* code, not comskip's, and
every link in it is something the relay extraction could break: a settings read, a Celery dispatch
to a differently-configured queue, a `which` lookup against the image's contents, an ini-path
cascade, a `custom_properties` write, and a WebSocket event. None of it is observed today. One
test proves the chain runs to a terminal state and emits its event, and asserts **nothing** about
how many commercials were found — its header says so in those words.

What that test does, precisely. It PATCHes the DVR settings group to `comskip_enabled: true` and
`comskip_mode: "mark"`, runs a 30 s recording, waits for a `comskip_status` event correlated on
`recording_id`, and asserts `custom_properties.comskip.status` reaches a value in
`{completed, error, skipped}`. `mark` is chosen deliberately over the `cut` default as
belt-and-braces: if the synthetic asset ever *did* trip a false-positive detection, `mark` leaves
the MKV untouched, so the sibling rows' file assertions cannot be disturbed by it. An `afterEach`
restores `comskip_enabled: false`.

Its two risks, and the escape hatch. Comskip's runtime on a 30 s synthetic MKV is not known ahead
of time, and it runs on the **shared prefork `celery` worker**, not the `dvr` queue — so a
pathological run would occupy one of six autoscale slots. The test is therefore ordered last in
the plan and bounded by an explicit wait budget. **If it proves slow or flaky in practice, it is
downgraded to a `COVERAGE.md` gap rather than made tolerant**; a comskip test that passes because
its assertion was weakened until it could not fail is worth less than an honest row saying comskip
dispatch is unobserved. That instruction is in the plan, not just here.

## Project topology

```
bootstrap ──→ dvr   (new)   ~6 min   1 worker   timeout 300_000
```

One new project, one new CI matrix job, its own container. `workers: 1` and `fullyParallel: false`
for the three reasons in D1. `timeout: 300_000` matches the three streaming projects; no row here
is expected to approach it, and the headroom is what turns a wedged `run_recording` into a named
wait failure rather than a bare project timeout.

Locally the project must be run alone — it mutates the DVR settings row and `/data/recordings`
container-wide — the same rule `e2e/README.md` already states for `pristine`,
`streaming-greybox` and the two `lifecycle` projects. The implementation plan adds `dvr` to that
list.

## Test inventory

Estimates are wall clock for the row, including its recording. Project total ≈ 6 minutes.

| # | Row | File | Tag | Mechanism | Est. |
|---|---|---|---|---|---|
| 1 | **A scheduled recording fires, plays back in progress, and completes** (flagship) | `recording-execution.spec.ts` | `@contract` | Seed an upstream channel; POST a recording at `now + 5 s` for 30 s. Wait for `recording_started` (correlated on the channel's generated name — D11). Poll the detail endpoint to `status === 'recording'` and assert `file_url` is the HLS endpoint. Assert `upstream.connections().live === 1`, proving the bytes came from the fake provider through `live_proxy`. `GET /file/` with `redirect: 'manual'` → 302 to `/hls/index.m3u8`; `GET` that playlist → `#EXTM3U` naming `seg_00000.ts`; `GET` that segment → `expectTsAligned`. Wait for `recording_ended`; poll to `status === 'completed'`; assert `bytes_written > 0`, `ended_at` present, and `file_url` flipped back to `/file/`. Then `GET /file/` → 200, `Content-Type: video/x-matroska`, `Content-Length > 0`, first four bytes `1A 45 DF A3`; and `Range: bytes=0-1023` → 206 with `Content-Range: bytes 0-1023/<size>` | 90 s |
| 2 | **The recording's on-disk layout follows the DVR templates** | `recording-execution.spec.ts` | `@characterization` | Against row 1's completed recording — no second recording. Assert `custom_properties.file_path` starts with `/data/recordings/`, matches the TV-fallback shape `TV_Shows/<channel name>/<YYYYmmdd_HHMMSS>.mkv`, and that `_hls_dir`'s basename is `.dvr_<id>_hls`. Both strings come back on the ordinary detail endpoint; no filesystem access | 2 s |
| 3 | **Stopping an in-flight recording preserves `stopped`** | `recording-control.spec.ts` | `@contract` | Fire a 45 s recording; at `status === 'recording'`, `POST /<id>/stop/`. Assert the `recording_stopped` event, that `status` settles on `stopped` and is **not** overwritten by `completed` — the finalisation block's documented priority — and that `/file/` still serves a non-empty MKV for the partial capture. Then assert a second `POST /stop/` returns **409**, the terminal-state guard | 60 s |
| 4 | **Extending an in-flight recording moves its deadline** | `recording-control.spec.ts` | `@contract` | Fire a 20 s recording; at `status === 'recording'`, `POST /<id>/extend/` with `extra_minutes: 1` — the endpoint's unit is whole minutes and it 400s on anything ≤ 0, so 60 s is the smallest extension the product allows. Assert the `recording_extended` event and that the row's `end_time` grew by exactly 60 s, then assert the recording is **still** `recording` ~15 s past its *original* end, which is the only external proof that the main loop re-read `end_time` from the DB and raised its own deadline. Stop it rather than waiting out the extra minute | 55 s |
| 5 | **`recording_cancelled` on an upcoming recording** | `recording-events.spec.ts` | `@contract` | Schedule a recording far enough out that it cannot fire; `DELETE` it; assert a `recording_cancelled` event correlated on `recording_id` with `was_in_progress: false`, and that the row is gone | 10 s |
| 6 | **`recording_cancelled` on an in-flight recording** | `recording-events.spec.ts` | `@contract` | Fire a 45 s recording; at `status === 'recording'`, `DELETE` it; assert `recording_cancelled` with `was_in_progress: true`, that the row is gone, and that `/file/` now 404s — the destroy path's file teardown, which `COVERAGE.md`'s G6 gap row records as never observed. Also assert the provider's live connection count falls back to 0, proving the backgrounded DVR-client teardown reached `live_proxy` | 60 s |
| 7 | **A recurring rule materialises and purges its recordings** | `recurring-rules.spec.ts` | `@contract` | `POST /api/channels/recurring-rules/` for the seeded channel with all seven weekdays and a fixed clock window. `perform_create` materialises synchronously, so assert immediately: between 13 and 14 rows carrying `custom_properties.rule.id === rule.id` (14-day horizon; today's slot is skipped if already past), every one on a weekday in the rule's set, every `start_time` in the future. Then `DELETE` the rule and assert every one of those rows is gone | 8 s |
| 8 | **Comskip dispatch reaches a terminal state** | `comskip.spec.ts` | `@characterization` | As set out under "The comskip decision". Ordered last; downgraded to a `COVERAGE.md` gap rather than weakened if it proves slow or flaky | 90 s |

Rows 1–2 share one recording; rows 3, 4, 6 and 8 each pay for their own. Row 5 pays for none.

**None of these rows exists in `COVERAGE.md` today.** All eight are added in the same PR as the
tests, per roadmap rule 3, together with two new gap rows: comskip detection (D9) and the
recurring-rule recording that cannot be made to fire (Non-goals).

## Files created and touched

**Created:**

| Path | Responsibility |
|---|---|
| `e2e/tests/dvr/helpers.ts` | `scheduleRecording()`, `waitForRecordingStatus()`, `uniqueStartTime()` (D4's rule lives in its header), `MKV_MAGIC` |
| `e2e/tests/dvr/recording-execution.spec.ts` | Rows 1–2 |
| `e2e/tests/dvr/recording-control.spec.ts` | Rows 3–4 |
| `e2e/tests/dvr/recording-events.spec.ts` | Rows 5–6 |
| `e2e/tests/dvr/recurring-rules.spec.ts` | Row 7 |
| `e2e/tests/dvr/comskip.spec.ts` | Row 8 |

**Modified:**

| Path | Change |
|---|---|
| `e2e/playwright.config.ts` | Add the `dvr` project, with D1's three reasons in the comment |
| `.github/workflows/e2e-tests.yml` | Add `dvr` to the matrix. Zizmor must stay at zero findings |
| `e2e/package.json` | Add `test:dvr` |
| `e2e/fixtures/types.ts` | Add `RecurringRule`; extend nothing else. Additive, at the end |
| `e2e/COVERAGE.md` | Eight new rows plus two gap rows |
| `e2e/README.md` | Document the `dvr` project and add it to the "run it alone" list |

**Explicitly not touched:** `e2e/fixtures/seed.ts` (D7), `e2e/tests/frontend/dvr.spec.ts` (D12),
anything under `e2e/tests/lifecycle/`, `e2e/tests/settings*`, `e2e/tests/plugins*` — G12's, G14's
and G15's files.

## Tags

G13 applies G11's taxonomy; it does not define it.

**`@contract` — rows 1, 3, 4, 5, 6, 7.** Every assertion in these rows is an HTTP status, an HTTP
header, a JSON field on a documented REST endpoint, a WebSocket event payload, or MPEG-TS packet
alignment. None of them names a container path, a process, a Redis key or an image's contents. A
relay extraction that preserves DVR behaviour keeps all six green; one that breaks it turns them
red for a nameable reason. These are the rows that make G13 a migration gate rather than a
regression suite.

**`@characterization` — rows 2 and 8.** Row 2 asserts `/data/recordings/…` — a hard-coded literal
in `_build_output_paths`, not a setting — and the shape of the shipped default DVR templates.
Row 8 asserts that a binary compiled in `docker/DispatcharrBase` is on `PATH` inside this image
and that an ini exists at one of three AIO paths. Both are deliberately coupled to *this*
deployment, both would be legitimately rewritten by a change to the image or the settings
defaults, and both justify themselves in a comment at the top of the test, as G11 requires.

## Non-goals

- **Comskip detection fidelity.** See D9 and "The comskip decision". Recorded as a `COVERAGE.md`
  gap with its reason.
- **A recurring rule's recording actually firing.** `sync_recurring_rule_impl` skips any slot where
  `start_dt <= now`, so the earliest materialised recording is at least a day out. There is no
  bounded-time path to it, and forcing one would mean writing a `Recording` row directly and
  calling it a recurring rule. Recorded as a gap.
- **Series rules** (`/api/channels/series-rules/`, `SeriesRulesAPIView`, `evaluate_series_rules`).
  The goal definition says "recurring rules"; series rules match against real EPG programme data,
  which is G3's ingest surface and G14's fuzzy-matching subject. Recorded as a gap naming G14.
- **The Connect subscription surface for `recording_start` / `recording_end`.** Those are
  `SUPPORTED_EVENTS` entries fanned out to webhooks by `log_system_event`, a different vocabulary
  from the WebSocket events G13 asserts. G14 owns product Connect events.
- **Closing `COVERAGE.md`'s existing `PeriodicTask` / `ClockedSchedule` gap.** Neither has a REST
  surface, so closing it needs `docker exec` or a product change; D5 rules out the first and D13
  rules out the second.
- **Recording recovery after a restart** (`recover_recordings_on_startup`). Restarting the
  container is `instance.ts`'s territory and G12's subject; a DVR row there would need the
  fixture D2 forbids.
- **Multiple simultaneous recordings on one channel**, and DVR under the connection-limit fault.
  Both are load-shaped, and the roadmap's non-goals rule out load testing. The `recording_id`
  correlation defect D11 files is what a future goal would need fixed first.
- **Fixing any product defect.** Assert correct, `test.fail()`, file the issue with `--repo`.

## Risks

- **`run_recording` is 1,139 lines running for the first time, and is expected to yield defects.**
  Two are already named (D10, D11) and will be filed before implementation starts. The plan
  reserves a task after the first full green attempt for triaging whatever else the run surfaces:
  each becomes a test asserting correct behaviour, marked `test.fail()` with the defect named, and
  an issue. The failure mode to guard against is the opposite one — quietly weakening an assertion
  until a buggy path passes. If a row cannot be made to discriminate, it becomes a documented gap.
- **The firing rows are the most likely to flake, and their flake is a timeout, not a wrong
  result.** Every wait is on a status transition or a WebSocket event that either happens or does
  not; there is no threshold to drift across. The mitigations are D3's derived budgets and a
  `describeLast` on every `waitFor.condition` so a timeout names what it last observed rather than
  reporting a bare elapsed time.
- **ffmpeg's ingest rate is not wall-clock-locked.** The provider paces at `rate` (default 1) but
  `-c copy` ingests as fast as bytes arrive, so the number of 4-second segments produced in 30 wall
  seconds is not fixed. No row asserts a segment count — row 1 asserts the playlist names at least
  one segment and that the segment is TS-aligned. `e2e-upstream/README.md` states the same rule for
  throughput generally: *"Don't assert on throughput in any test."*
- **The `dvr` project's wall clock grows with every row added.** At ~6 minutes it sits between
  `streaming` (~4) and `streaming-failover` (~7) and inside the workflow's 30-minute job timeout.
  A future goal adding DVR rows should split the project rather than let one job drift toward the
  ceiling, the way G4 split `streaming` into three.
- **Five shared files collide with G12, G14 and G15.** Every edit is additive and small. The
  workflow edit re-runs the blocking zizmor hook on the whole file; the workflows are at zero
  findings and G13 must leave them there.
- **G11 is a hard dependency for the tag taxonomy only.** If G11 slips, G13's tests still run —
  the tags are text in test titles — but the ADR that gives them meaning would not exist yet. G13
  should land after G11, and says so; it should not block on it if the wave reorders.
