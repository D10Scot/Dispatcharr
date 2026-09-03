import { test, expect } from '../../fixtures';
import type { ApiClient, Recording } from '../../fixtures';
import { scheduleRecording, waitForRecordingStatus, cleanupRecordingAndChannel } from './helpers';

/**
 * Row 8 (spec D9): the comskip dispatch chain — `CoreSettings.get_dvr_comskip_enabled()`
 * (`core/models.py`) → `run_recording`'s post-process branch (`apps/channels/tasks.py:2452-2456`)
 * → `comskip_process_recording.delay()` → a `comskip_status` websocket event → a terminal
 * `custom_properties.comskip.status` on the `Recording` row.
 *
 * ---------------------------------------------------------------------------
 * What this test asserts
 * ---------------------------------------------------------------------------
 * That the dispatch chain runs end to end and reaches a terminal state: after
 * a completed recording, `comskip_process_recording` is actually invoked, it
 * emits its `comskip_status` websocket event correlated on `recording_id`, and
 * `Recording.custom_properties.comskip.status` settles on one of `completed`,
 * `error` or `skipped`.
 *
 * ---------------------------------------------------------------------------
 * What this test deliberately does NOT assert
 * ---------------------------------------------------------------------------
 * Anything about commercial detection. It does not assert `commercials`
 * (a count of detected commercial breaks), does not assert `skipped` (whether
 * comskip decided there was nothing to cut), and does not assert `mode`. An
 * `error` terminal state is a PASS for this test's stated scope — the
 * assertion message below prints `custom_properties.comskip.reason` so a
 * reader can see which reason it was, but no reason is treated as a failure.
 *
 * ---------------------------------------------------------------------------
 * Why detection is not constructible against this suite's asset
 * ---------------------------------------------------------------------------
 * `docker/comskip.ini` sets `detect_method=127` — the bitwise-OR of all seven
 * detection methods comskip has, so nothing is disabled that could otherwise
 * be tuned around. G2's synthetic asset
 * (`e2e-upstream/scripts/make-asset.sh`) is `lavfi testsrc` video with a
 * burned-in frame-number counter, plus a constant 440 Hz sine wave — no
 * station logo, no black frames, no silence, no aspect-ratio change, no
 * scene-cut structure: none of the signal every comskip detection method
 * looks for. `comskip_process_recording` (`apps/channels/tasks.py:2758-3023`)
 * can therefore only ever reach one of two outcomes against this asset: exit
 * code 1 ("no commercials detected", `:2858-2865`) or a non-empty EDL whose
 * total marked duration is `<= 0.5`s, which the `sum(commercials) <= 0.5`
 * short-circuit at `:2941` also treats as "no commercials". Both paths
 * persist `custom_properties.comskip.status = "completed"` with
 * `skipped: true`. A `detect_method` that could be defeated by omission would
 * make this asset's "no commercial structure" property untestable; 127
 * removes that escape hatch, which is why the ini is quoted here rather than
 * assumed.
 *
 * ---------------------------------------------------------------------------
 * Why `@characterization`, not `@contract`
 * ---------------------------------------------------------------------------
 * This test's premise depends on two facts about the DEPLOYMENT rather than
 * the PRODUCT: that a `comskip` binary compiled in `docker/DispatcharrBase`
 * (built from source into `/usr/local/bin/comskip`, see that file's builder
 * stage) is on `PATH` inside this image, and that an ini exists at one of the
 * three paths `comskip_process_recording` tries in order — a caller-supplied
 * `CoreSettings.get_dvr_comskip_custom_path()` (empty here), then
 * `/etc/comskip/comskip.ini` (not shipped by this image), then
 * `/app/docker/comskip.ini` (present: `docker/Dockerfile`'s `COPY . /app`
 * places the whole repo, `docker/comskip.ini` included, at that exact path —
 * the one this container actually resolves). A different image build that
 * dropped the comskip binary, or relocated the ini past all three
 * candidates, would legitimately break this test without the *product*
 * having changed at all. See `docs/adr/0002-e2e-test-taxonomy.md`.
 *
 * ---------------------------------------------------------------------------
 * The settings flip: read, merge, PATCH the whole dict, restore verbatim
 * ---------------------------------------------------------------------------
 * `CoreSettingsViewSet` (`core/api_views.py`) is a plain `ModelViewSet` with
 * no `lookup_field` override — addressed by numeric row `id`, never by `key`
 * — and `value` is a `JSONField` that `PATCH` replaces WHOLESALE, not merged
 * server-side. `dvr_settings` on a booted instance carries ten keys and does
 * NOT include `comskip_mode` or `comskip_hw_accel` — both come only from
 * `CoreSettings.get_dvr_settings()`'s defaults dict (`core/models.py:614-629`)
 * when the stored row omits them — so `comskip_mode` must be added
 * explicitly here rather than assumed present, and every other key from the
 * original row must be carried through unmodified. Dropping a key is not
 * benign: `CoreSettingsViewSet.update` (`core/api_views.py:110-143`) diffs
 * `pre_offset_minutes` and `post_offset_minutes` old-vs-new and calls
 * `reschedule_upcoming_recordings_for_offset_change` whenever either
 * differs — an omitted key reads back as `undefined`/`None` on the far side,
 * which differs from `0`, so a partial PATCH here would reschedule every
 * upcoming recording in the shared container as a side effect of this test.
 *
 * `comskip_mode: 'mark'` rather than the `'cut'` default is belt-and-braces:
 * if the synthetic asset ever did trip a false-positive detection despite
 * `detect_method=127`'s exhaustive search finding nothing to work with
 * today, `mark` (`apps/channels/tasks.py:2953-2961`) leaves the MKV
 * untouched — no ffmpeg concat/remux runs, no file is replaced — so no
 * sibling row's file-shape assertions (`recording-execution.spec.ts`) can
 * ever be disturbed by this file running earlier in the same `dvr` project.
 *
 * The restore in `afterEach` below runs UNCONDITIONALLY, including on a
 * timeout: this is a global settings row, and leaving `comskip_enabled` on
 * would run comskip after every subsequent recording in this shared
 * container. Unlike `proxy_settings` (a 10s PROCESS-LOCAL cache on top of the
 * Redis one, `apps/proxy/config.py`, which `failover-buffering.spec.ts` has
 * to sleep out before starting a channel), `CoreSettings._get_group`
 * invalidates the whole group in REDIS via a `post_save` receiver
 * (`core/signals.py:11-15`, `CoreSettings.invalidate_group_cache`) — every
 * worker reads through that cache, so the flip (and the restore) reaches the
 * `dvr` and `celery` workers immediately, with no settling delay needed
 * before scheduling the recording below.
 *
 * The `dvr` project is `workers: 1` (`playwright.config.ts`) partly for this
 * exact reason — see that project's block comment, which names this file —
 * so nothing else in this shared container reads `dvr_settings` mid-flip.
 *
 * See `docs/adr/0003-e2e-frontend-and-shared-state-contract.md` for why the
 * rule is "any write to `/api/core/settings/`" rather than a key list, and
 * `tests/guards/allowlist.ts`'s `GLOBAL_SETTINGS_WRITE` entry for this file
 * for the same three-part argument in the form that guard enforces.
 */

const CORE_SETTINGS_PATH = '/api/core/settings/';
const DVR_SETTINGS_KEY = 'dvr_settings'; // core/models.py:202

/** `custom_properties.comskip.status` values that end this test's wait — see the file header for why. */
const COMSKIP_TERMINAL_STATUSES = ['completed', 'error', 'skipped'] as const;

interface CoreSettingsRow {
  id: number;
  key: string;
  value: Record<string, unknown>;
}

async function readDvrSettingsRow(api: ApiClient): Promise<CoreSettingsRow> {
  const rows = await api.json<CoreSettingsRow[]>(await api.get(CORE_SETTINGS_PATH), 'core settings');
  const row = rows.find((r) => r.key === DVR_SETTINGS_KEY);
  expect(row, `the "${DVR_SETTINGS_KEY}" CoreSettings row should exist`).toBeDefined();
  return row!;
}

// Module-scoped, assigned the moment each value resolves, cleared in
// `afterEach` — the same shape `recording-execution.spec.ts` uses and
// explains: Playwright tears a timed-out test down mid-`await`, with nothing
// after that point (a body-level `try`/`finally` included) guaranteed to
// run, but fixture teardown always does. That matters more here than in any
// sibling spec: a timeout must still restore `dvr_settings`, not just the
// recording/channel it created. Safe as shared module state because the
// `dvr` project is `workers: 1` with `fullyParallel` inherited `false` — one
// test runs at a time, so no other test's `afterEach` can ever observe this
// test's write.
let settingsRowIdToRestore: number | undefined;
let originalDvrSettingsValue: Record<string, unknown> | undefined;
let channelIdToCleanup: number | undefined;
let recordingIdToCleanup: number | undefined;

test.afterEach(async ({ api }, testInfo) => {
  const rowId = settingsRowIdToRestore;
  const original = originalDvrSettingsValue;
  const recordingId = recordingIdToCleanup;
  const channelId = channelIdToCleanup;
  settingsRowIdToRestore = undefined;
  originalDvrSettingsValue = undefined;
  recordingIdToCleanup = undefined;
  channelIdToCleanup = undefined;

  // The settings restore runs first and is attempted regardless of whether
  // the recording/channel cleanup below succeeds — see the file header for
  // why leaving `dvr_settings` mutated is the worst outcome this file can
  // produce on a shared container.
  let restoreError: unknown;
  if (rowId !== undefined && original !== undefined) {
    try {
      await api.patch(`${CORE_SETTINGS_PATH}${rowId}/`, { value: original });
    } catch (err) {
      restoreError = err;
    }
  }

  // Calls the shared helper for the recording/channel half — see
  // helpers.ts's own doc comment for its 404 tolerance and non-masking
  // shape. That ordering (settings restore first, unconditional; recording/
  // channel cleanup second) is preserved here, not delegated wholesale,
  // because leaving `dvr_settings` mutated is the worse of the two failure
  // modes on a shared container and must never be skipped or reordered
  // behind the recording/channel cleanup.
  let cleanupError: unknown;
  try {
    await cleanupRecordingAndChannel(
      api,
      testInfo,
      { recordingId, channelId },
      'comskip.spec.ts'
    );
  } catch (err) {
    cleanupError = err;
  }

  if (restoreError !== undefined) {
    // Loudest possible failure: a mutated global row on a container two
    // other agent sessions share. Never swallowed, regardless of how the
    // test itself or the recording/channel cleanup went.
    console.error(
      'comskip.spec.ts: FAILED TO RESTORE dvr_settings — the shared container ' +
        `is left with comskip settings mutated. row id=${rowId}, intended ` +
        `value=${JSON.stringify(original)}.`
    );
    if (cleanupError !== undefined) {
      // Otherwise discarded silently: restoreError below is what actually
      // fails the test and takes priority, but a recording/channel cleanup
      // failure alongside it is still real evidence, not noise to drop.
      console.error(
        'comskip.spec.ts: the recording/channel cleanup ALSO failed, ' +
          'alongside the settings restore failure above. Cleanup error:',
        cleanupError
      );
    }
    throw restoreError;
  }
  if (cleanupError !== undefined) {
    // cleanupRecordingAndChannel already applies its own non-masking check
    // (testInfo.status) and swallows-and-logs rather than throwing when that
    // applies, so a defined cleanupError here always means the test itself
    // passed and this failure should propagate.
    throw cleanupError;
  }
});

// @characterization: `comskip` compiled in `docker/DispatcharrBase` is on
// `PATH` in this image, and an ini exists at one of three AIO paths this
// container resolves to `/app/docker/comskip.ini` — see the file header for
// both facts, quoted from source.
test('comskip dispatch reaches a terminal state', { tag: '@characterization' }, async ({
  upstream,
  seed,
  api,
  waitFor,
  ws,
}) => {
  const row = await readDvrSettingsRow(api);
  const original = row.value;

  // A prior run that timed out before its `afterEach` completed would leave
  // `dvr_settings` dirty at comskip_enabled=true — catch that here rather
  // than silently baking a bad "original" into this run's own restore. Same
  // shape as failover-buffering.spec.ts / vod-redirect-profile.spec.ts.
  expect(
    original.comskip_enabled,
    'a previous run left dvr_settings dirty with comskip_enabled=true'
  ).not.toBe(true);

  settingsRowIdToRestore = row.id;
  originalDvrSettingsValue = original;

  // Whole-dict PATCH, comskip_mode added explicitly — see the file header's
  // "The settings flip" section for why both are load-bearing.
  await api.patch(`${CORE_SETTINGS_PATH}${row.id}/`, {
    value: { ...original, comskip_enabled: true, comskip_mode: 'mark' },
  });

  // No settling delay before scheduling the recording below — verified
  // against source, not assumed: CoreSettings._get_group's cache is
  // invalidated in Redis by a post_save receiver (core/signals.py:11-15),
  // reaching every worker immediately, unlike proxy_settings' 10s
  // process-local cache. See the file header.

  const scenario = await upstream.scenario({
    channels: [{ id: 1, name: 'G13 Comskip Dispatch', tvgId: 'g13-comskip-dispatch.e2e', logo: null }],
  });
  const { channel } = await seed.upstreamChannel(scenario, { channelIds: [1] });
  channelIdToCleanup = channel.id;

  const recording = await scheduleRecording(api, channel.id, {
    startInMs: 5_000,
    durationMs: 30_000,
  });
  recordingIdToCleanup = recording.id;

  // `ws` is already subscribed to the `updates` group before the test body
  // runs (the fixture awaits `connection_established` at setup), so this
  // wait cannot miss the event even though it is registered after
  // `scheduleRecording` above — same reasoning recording-execution.spec.ts
  // documents. `recording_started` carries only `channel`
  // (D10Scot/Dispatcharr#132), never `recording_id`, so correlate on the
  // seeded channel's generated name.
  await ws.waitForMessage('recording_started', {
    where: (data) => data.channel === channel.name,
    timeoutMs: 60_000,
  });

  // Budget: the 30s capture window, plus post-recording concat/remux, plus
  // headroom over recording-execution.spec.ts's own 90s budget for the same
  // wait — this row asserts nothing about the recording itself, so it moves
  // straight to polling `status` rather than also waiting on the
  // `recording_ended` websocket event first.
  const finished = await waitForRecordingStatus(waitFor, recording.id, ['completed', 'interrupted'], {
    timeoutMs: 90_000,
  });
  const finishedCp = (finished.custom_properties ?? {}) as Record<string, unknown>;
  expect(
    finishedCp.status,
    `recording ${recording.id} ended as '${finishedCp.status}', not 'completed' — ` +
      `interrupted_reason=${finishedCp.interrupted_reason ?? '(none)'} — the comskip dispatch ` +
      "this test targets only fires from run_recording's normal-completion tail " +
      '(apps/channels/tasks.py:2452-2456), so an interrupted recording never reaches it'
  ).toBe('completed');

  // The dispatch chain itself. `comskip_process_recording` is NOT in
  // `dispatcharr/celery.py`'s `task_routes` (which routes only
  // `run_recording` to the `dvr` queue) — it runs on the shared prefork
  // `celery` worker (`--autoscale=6,1`), a queue this suite does not own the
  // way it owns `dvr`. 120s budget accounts for that shared queue's
  // scheduling latency, not comskip's own runtime against a 30s clip.
  await ws.waitForMessage('comskip_status', {
    where: (data) => data.recording_id === recording.id,
    timeoutMs: 120_000,
  });

  // Poll the REST resource for the persisted terminal state rather than
  // trust the websocket payload's own `status` field: `comskip_process_recording`
  // (apps/channels/tasks.py:2758-3023) sends `_ws('skipped', ...)` on the
  // exit-code-1 branch (:2858-2865) and the sum<=0.5 branch (:2941-2951), but
  // BOTH persist `custom_properties.comskip.status = "completed"` (with
  // `skipped: true`) — the websocket event's status and the persisted status
  // disagree by construction on those two branches, which this asset's lack
  // of commercial structure makes the most likely outcome. The websocket
  // wait above is the correlation signal that dispatch actually happened for
  // THIS recording; this poll is the actual assertion target.
  let lastComskip: Record<string, unknown> | undefined;
  const settled = await waitFor.resource<Recording>(
    `/api/channels/recordings/${recording.id}/`,
    (body) => {
      const cp = (body.custom_properties ?? {}) as Record<string, unknown>;
      const comskip = cp.comskip as Record<string, unknown> | undefined;
      lastComskip = comskip;
      return (
        typeof comskip?.status === 'string' &&
        (COMSKIP_TERMINAL_STATUSES as readonly string[]).includes(comskip.status)
      );
    },
    {
      timeoutMs: 30_000,
      description: `recording ${recording.id}'s custom_properties.comskip.status to reach a terminal state`,
      describeLast: () => `last observed comskip=${lastComskip ? JSON.stringify(lastComskip) : '(absent)'}`,
    }
  );
  const finalCp = (settled.custom_properties ?? {}) as Record<string, unknown>;
  const finalComskip = finalCp.comskip as Record<string, unknown> | undefined;

  // Assert only the terminal state — never `commercials`, `skipped` or
  // `mode`. `error` is a PASS for this test's scope; the message below
  // prints `reason` so a reader can see which one without the test failing
  // over it.
  expect(
    finalComskip?.status,
    `comskip.status='${finalComskip?.status}' is not one of ` +
      `${COMSKIP_TERMINAL_STATUSES.join('/')} — reason=${finalComskip?.reason ?? '(none)'}, ` +
      `full comskip=${JSON.stringify(finalComskip)}`
  ).toEqual(expect.stringMatching(new RegExp(`^(${COMSKIP_TERMINAL_STATUSES.join('|')})$`)));
});
