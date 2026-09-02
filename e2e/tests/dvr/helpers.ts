import { test } from '@playwright/test';
import type { ApiClient, Recording, WaitOptions, Waiter } from '../../fixtures';

/**
 * The recording factory and its start-time rule, shared by every spec in
 * this project (`e2e/playwright.config.ts`'s `dvr` project, `workers: 1`,
 * `fullyParallel` left unset so it inherits `false` — the whole project runs
 * one test at a time).
 *
 * ---------------------------------------------------------------------------
 * Why `uniqueStartTime` exists
 * ---------------------------------------------------------------------------
 * `schedule_task_on_save` (`apps/channels/signals.py:337-386`, the
 * `Recording` `post_save` receiver) calls `schedule_recording_task`, which
 * does `ClockedSchedule.objects.get_or_create(clocked_time=eta)`
 * (`signals.py:271`). `get_or_create` is not race-proof against a `clocked_time`
 * two concurrent (or merely close-together) creates both resolve to: if two
 * `ClockedSchedule` rows ever exist for the exact same instant — nothing in
 * the schema stops that — a later `get_or_create` at that same instant raises
 * `MultipleObjectsReturned`. That exception lands inside `schedule_task_on_save`'s
 * own blanket `except Exception as e: ... print(...)` (`signals.py:383-386`),
 * so it is swallowed rather than raised: the `POST` to
 * `/api/channels/recordings/` still returns `201`, but `task_id` is left
 * `null` and the recording is never scheduled — and every later create that
 * lands on the same `clocked_time` repeats the same silent failure. Filed as
 * D10Scot/Dispatcharr#131 (the missing-`recording_id` gap this same signal
 * has is the separate D10Scot/Dispatcharr#132, not relevant here).
 *
 * `uniqueStartTime` exists to make that instant never repeat. A plain
 * `new Date(Date.now() + offsetMs).toISOString()` is not enough on its own:
 * V8's clock has limited resolution, so two calls microseconds apart inside
 * the same test can legitimately return the *same* millisecond, and any
 * future rounding of the result (down to the second, or the minute — exactly
 * what `RecordingUtils.js`'s `createRoundedDate()` does on the frontend, and
 * exactly what produced three collided "Custom Recording" rows during G6's
 * work, filed as D10Scot/Dispatcharr#71) would make an accidental collision
 * far *more* likely, not less. **Never round or truncate the string this
 * returns** — doing so reopens #131 with better odds than the un-rounded
 * form already carries.
 *
 * ---------------------------------------------------------------------------
 * `end_time` must always be in the future
 * ---------------------------------------------------------------------------
 * `RecordingSerializer.validate` (`apps/channels/serializers.py:756-810`)
 * treats `start_time` and `end_time` asymmetrically:
 *
 *  - `if end_time < now: raise ValidationError("End time must be in the
 *    future.")` (`:801-802`) — a past `end_time` is a hard `400`.
 *  - `if start_time < now: data["start_time"] = now` (`:804-806`) — a past
 *    `start_time` is **silently clamped** to the moment the request is
 *    validated, not rejected. A test that computes a deliberately-past
 *    `start_time` (the "currently playing" scenario `signals.py:364-369`
 *    schedules immediately) will never see that value echoed back — assert
 *    against `now`-ish, not against the value sent.
 *
 * `scheduleRecording` below never sends `custom_properties`, on purpose: a
 * `custom_properties.program` dict flips `RecordingSerializer.validate`'s
 * `is_epg_based` branch (`:770-797`), which shifts `start_time` earlier and
 * `end_time` later by the global DVR pre/post offsets
 * (`CoreSettings.get_dvr_pre_offset_minutes` / `get_dvr_post_offset_minutes`)
 * — silently moving the window this file's callers asked for out from under
 * them.
 *
 * ---------------------------------------------------------------------------
 * Every recording created here MUST be deleted in an `afterEach`
 * ---------------------------------------------------------------------------
 * `DELETE /api/channels/recordings/<id>/` is the only cleanup a caller needs:
 * `revoke_task_on_delete` (`signals.py:388-390`, a `post_delete` receiver)
 * calls `revoke_task()`, which deletes the row's `PeriodicTask` and, if
 * nothing else references it, its `ClockedSchedule` too (`signals.py:289-303`).
 * Skipping that cleanup has two independent costs, not one:
 *
 *  - **D10Scot/Dispatcharr#71** — `categorizeRecordings()`
 *    (`frontend/src/utils/pages/DVRUtils.js:63-73`) groups the DVR page's
 *    "Upcoming Recordings" list by `${program.tvg_id}|${program.title}`,
 *    which collapses to the literal string `'|'` for every ad-hoc recording
 *    with no EPG `program` — i.e. every recording this file creates. A
 *    leaked row here silently merges into the *next* run's card and hides
 *    it from the DOM, however unrelated in channel or time.
 *  - **A stale `PeriodicTask`/`ClockedSchedule` pair survives the test**,
 *    sitting in the database at its own `clocked_time` indefinitely. That
 *    directly widens the collision surface `uniqueStartTime` exists to
 *    avoid: every leaked row is one more `clocked_time` a later run's
 *    `get_or_create` can land on, compounding the #131 race across runs
 *    instead of containing it to one.
 *
 * A body-level `try`/`finally` is not enough on its own: Playwright tears a
 * timed-out test down mid-`await` without raising a catchable exception, so
 * code after the timeout point — including a `finally` block — does not
 * reliably run. Put the delete in `test.afterEach`, matching
 * `tests/frontend/dvr.spec.ts`'s own `afterEach` (Playwright's fixture
 * teardown, which runs on its own budget regardless of how the test body
 * ended).
 */

/**
 * Sub-second component assigned to the next `uniqueStartTime` call, combined
 * with the calling worker's index so two workers can never compute the same
 * millisecond by coincidence — see the file header for why this needs to be
 * deterministic rather than merely unlikely. `dvr` runs `workers: 1` today,
 * so `workerIndex` is always `0` in practice; the combination still costs
 * nothing and stops this file silently depending on that project setting
 * never changing.
 *
 * 100ms-wide slot per worker: comfortably supports the project's configured
 * `workers: 1` (and up to 10, should that ever change) before two workers'
 * slots could overlap, while still leaving room for hundreds of calls per
 * worker within one wall-clock second before the shared 0-999ms space wraps.
 */
const WORKER_SLOT_WIDTH_MS = 100;
let sequence = 0;

/**
 * An ISO-8601 timestamp `offsetMs` from now (negative for the past, e.g. to
 * build a "currently playing" recording), with sub-second entropy that no
 * other call — in this worker or, deterministically, any other — produces
 * for the same real millisecond. See the file header for the collision this
 * exists to prevent and why `Date.now()`'s own resolution is not enough.
 *
 * Always overrides the millisecond field rather than trusting the ambient
 * clock: this makes uniqueness a property of the counter, provable without
 * reference to timing, not a probabilistic property of the OS clock's actual
 * resolution.
 */
export function uniqueStartTime(offsetMs: number): string {
  const workerIndex = test.info().workerIndex;
  const slot = (workerIndex * WORKER_SLOT_WIDTH_MS + sequence) % 1000;
  sequence += 1;

  const date = new Date(Date.now() + offsetMs);
  date.setMilliseconds(slot);
  return date.toISOString();
}

/** Writable options for `scheduleRecording` — see the file header for why no `custom_properties` field exists here. */
export type ScheduleOptions = {
  /** Passed straight to `uniqueStartTime` — negative schedules a recording that started in the past. */
  startInMs: number;
  /** `end_time` is `start_time + durationMs`; must stay positive enough that `end_time` lands in the future (see the file header). */
  durationMs: number;
};

/**
 * Creates a `Recording` via `POST /api/channels/recordings/`
 * (`RecordingViewSet`, `apps/channels/api_urls.py`). Deliberately sends only
 * `channel`, `start_time` and `end_time` — see the file header for why a
 * `custom_properties` field is never added here.
 *
 * Callers own cleanup: register the returned row's `id` for deletion in a
 * `test.afterEach`, per the file header.
 */
export async function scheduleRecording(
  api: ApiClient,
  channelId: number,
  opts: ScheduleOptions
): Promise<Recording> {
  const start_time = uniqueStartTime(opts.startInMs);
  const end_time = new Date(Date.parse(start_time) + opts.durationMs).toISOString();

  const res = await api.post('/api/channels/recordings/', {
    channel: channelId,
    start_time,
    end_time,
  });
  return api.json<Recording>(res, `scheduleRecording(channel=${channelId})`);
}

/** Typed detail read of one `Recording` — `GET /api/channels/recordings/<id>/`. */
export async function readRecording(api: ApiClient, id: number): Promise<Recording> {
  const res = await api.get(`/api/channels/recordings/${id}/`);
  return api.json<Recording>(res, `readRecording(${id})`);
}

/**
 * `Recording.custom_properties.status` values this harness has verified
 * getting written, and where:
 *
 *  - `"scheduled"` — `sync_recurring_rule_impl` (`apps/channels/tasks.py:924`),
 *    for recordings a `RecurringRule` generates. An ad-hoc recording made by
 *    `scheduleRecording` above starts with **no** `status` key at all
 *    (`custom_properties` defaults to `{}`, and nothing in `RecordingViewSet`
 *    seeds one) until `run_recording` begins — waiting on `"scheduled"` for
 *    one of those will simply time out.
 *  - `"recording"` — `run_recording`, once the stream connects (`tasks.py:1461`).
 *  - `"completed"` / `"interrupted"` — `run_recording`, at teardown, mutually
 *    exclusive with each other (`tasks.py:2353-2360`).
 *  - `"stopped"` — the stop endpoint (`apps/channels/api_views.py:3559`),
 *    ahead of either of the two above.
 */
export type RecordingStatus = 'scheduled' | 'recording' | 'completed' | 'interrupted' | 'stopped';

/**
 * Polls the recording's detail endpoint until `custom_properties.status` is
 * one of `statuses`, and resolves with that body. Built on `waitFor.resource`
 * so it inherits its polling/timeout mechanics and needs no `ApiClient` of
 * its own — `Waiter` already holds the one the `waitFor` fixture was built
 * with (`fixtures/index.ts`: `new Waiter(api)`), the same `api` every other
 * call in a test already shares. The one thing this adds over calling
 * `waitFor.resource` directly is a `describeLast` naming the recording's
 * actual last-seen `status` and `interrupted_reason` (`tasks.py:2059`, only
 * present while `status` is `"interrupted"`) — a bare elapsed-time timeout
 * here would say nothing about which of "never started", "stuck recording"
 * or "failed for reason X" the suite actually hit, which is the difference
 * this whole project's `timeout: 300_000` exists to give a wait room to
 * report.
 *
 * `options.description`/`options.describeLast`, if supplied, override the
 * defaults below — same contract as every other `WaitOptions` consumer in
 * this harness.
 */
export async function waitForRecordingStatus(
  waitFor: Waiter,
  id: number,
  statuses: readonly RecordingStatus[],
  options: WaitOptions = {}
): Promise<Recording> {
  let lastSeen: Recording | undefined;

  return waitFor.resource<Recording>(
    `/api/channels/recordings/${id}/`,
    (body) => {
      lastSeen = body;
      const status = (body.custom_properties?.status as string | undefined) ?? undefined;
      return status !== undefined && (statuses as readonly string[]).includes(status);
    },
    {
      description: `recording ${id} to reach status in [${statuses.join(', ')}]`,
      describeLast: () => {
        if (!lastSeen) return undefined;
        const cp = lastSeen.custom_properties ?? {};
        const status = (cp as Record<string, unknown>).status ?? '(none)';
        const reason = (cp as Record<string, unknown>).interrupted_reason;
        return `status=${String(status)}${reason ? `, interrupted_reason=${String(reason)}` : ''}`;
      },
      ...options,
    }
  );
}

/**
 * The first four bytes of every Matroska/WebM file — the EBML magic number
 * — confirmed against `_build_output_paths`
 * (`apps/channels/tasks.py:1018-1084`), which always names a recording's
 * final output `*.mkv`. A `readRecording`'s file download starting with
 * these four bytes is the cheapest real evidence a spec can check that the
 * recorded artifact is an actual container file, not an empty or truncated
 * one.
 */
export const MKV_MAGIC = Buffer.from([0x1a, 0x45, 0xdf, 0xa3]);
