import { test, expect } from '../../fixtures';
import {
  scheduleRecording,
  readRecording,
  waitForRecordingStatus,
  cleanupRecordingAndChannel,
  MKV_MAGIC,
} from './helpers';

/**
 * The two control endpoints that reach into a running `run_recording`:
 * `POST .../stop/` and `POST .../extend/` (`RecordingViewSet`,
 * `apps/channels/api_views.py:3539` and `:3610`). Both exercise the main
 * loop's DB re-read every ~2s — the most extraction-sensitive part of the
 * DVR execution path, since a relay moved out of the Django process still
 * needs that poll to see a write this process just made.
 *
 * Same cleanup shape as `recording-execution.spec.ts`: module-scoped
 * bindings assigned the moment each id resolves, deleted in `afterEach`
 * rather than a body-level `try`/`finally` (a timed-out test is torn down
 * mid-`await` with no guaranteed `finally`, but fixture teardown always
 * runs). Safe as one shared pair because the `dvr` project is `workers: 1`
 * with `fullyParallel` inherited `false` (see `playwright.config.ts`'s own
 * comment on the project) — no other test's `afterEach` can observe this
 * test's write. Not repeating `test.describe.configure({ mode: 'serial' })`
 * here for the same reason: it would be a redundant directive on top of a
 * project that already runs one test at a time.
 */
let channelIdToCleanup: number | undefined;
let recordingIdToCleanup: number | undefined;

test.afterEach(async ({ api }, testInfo) => {
  const recordingId = recordingIdToCleanup;
  const channelId = channelIdToCleanup;
  recordingIdToCleanup = undefined;
  channelIdToCleanup = undefined;
  await cleanupRecordingAndChannel(
    api,
    testInfo,
    { recordingId, channelId },
    'recording-control.spec.ts'
  );
});

/**
 * `end_time`/`new_end_time` round-trip through Python's `.isoformat()`
 * (`+00:00`, microsecond precision) on the wire but through
 * `Date.prototype.toISOString()` (`Z`, millisecond precision) once parsed
 * here. `Date.parse` truncates the same way on both sides of any comparison
 * in this file, so normalizing both operands through this function before
 * comparing is what makes `toBe` exact rather than a source of flake from
 * format mismatch.
 */
function normalizeIso(value: string): string {
  return new Date(Date.parse(value)).toISOString();
}

test('stopping an in-flight recording preserves stopped and keeps the partial MKV', { tag: '@contract' }, async ({
  upstream,
  seed,
  api,
  waitFor,
  ws,
  streamClient,
}) => {
  const scenario = await upstream.scenario({
    channels: [{ id: 1, name: 'G13 DVR Stop', tvgId: 'g13-dvr-stop.e2e', logo: null }],
  });
  const { channel } = await seed.upstreamChannel(scenario, { channelIds: [1] });
  channelIdToCleanup = channel.id;

  // 45s gives ample margin over the 15s post-stop stability window below —
  // run_recording's main loop detects "stopped" on its own ~2s poll cycle
  // and breaks out well before any natural end_time, so the recording's
  // nominal duration only needs to outlast the test, not the stop.
  const recording = await scheduleRecording(api, channel.id, {
    startInMs: 5_000,
    durationMs: 45_000,
  });
  recordingIdToCleanup = recording.id;

  await ws.waitForMessage('recording_started', {
    where: (data) => data.channel === channel.name,
    timeoutMs: 60_000,
  });

  await waitForRecordingStatus(waitFor, recording.id, ['recording']);

  // Wait for at least one real HLS segment before stopping. `status`
  // flips to 'recording' at the very top of run_recording
  // (tasks.py:~1460-1463), before FFmpeg is even spawned — stopping
  // immediately on that transition (as first attempted here) raced FFmpeg's
  // startup and produced a recording with ZERO completed hls_time=4s
  // segments. `_build_output_paths`' concat step finds nothing to concat in
  // that case ("no HLS segments found. Nothing to concat", tasks.py:~2330)
  // and never writes file_path, which made the /file/ poll below time out
  // permanently (a real empty capture, not a transient race) on first
  // contact. Confirming a segment exists first guarantees the partial MKV
  // this row is actually testing for has real content to be built from.
  const authHeaders = { Authorization: `Bearer ${await api.freshAccessToken()}` };
  let lastPlaylistBeforeStop = '';
  await waitFor.condition(
    async () => {
      try {
        await streamClient.open(`/api/channels/recordings/${recording.id}/hls/index.m3u8`, {
          headers: authHeaders,
        });
        const playlist = (await streamClient.collectFor(2_000)).toString('utf8');
        lastPlaylistBeforeStop = playlist;
        return playlist.startsWith('#EXTM3U') && /seg_\d+\.ts/.test(playlist);
      } finally {
        await streamClient.close();
      }
    },
    {
      timeoutMs: 30_000,
      description: `the HLS playlist for recording ${recording.id} to list at least one segment before stopping`,
      describeLast: () =>
        lastPlaylistBeforeStop
          ? `last playlist (${lastPlaylistBeforeStop.length} bytes) starts=${lastPlaylistBeforeStop.startsWith('#EXTM3U')}, hasSegment=${/seg_\d+\.ts/.test(lastPlaylistBeforeStop)}`
          : '(no playlist body observed yet)',
    }
  );

  // Registered before the stop call, not after: `recording_ended` is sent
  // once, well after the stop (finalisation can take up to ~22s — see the
  // margin derivation in the extend test below), and `waitForMessage`
  // resolves on it whenever this promise is awaited, so opening the listener
  // here removes any window, even in principle, in which the event could be
  // missed while this test does other work in between.
  const recordingEndedPromise = ws.waitForMessage('recording_ended', {
    where: (data) => data.channel === channel.name,
    timeoutMs: 60_000,
  });

  const stopRes = await api.post(`/api/channels/recordings/${recording.id}/stop/`, {});
  expect(stopRes.status(), `POST /stop/ returned ${stopRes.status()}: ${await stopRes.text()}`).toBe(200);

  // "carries nothing else" — api_views.py:3572-3576 sends only
  // {success, type: "recording_stopped", channel}, no recording_id.
  await ws.waitForMessage('recording_stopped', {
    where: (data) => data.channel === channel.name,
    timeoutMs: 30_000,
  });

  const afterStop = await readRecording(api, recording.id);
  const stopCp = (afterStop.custom_properties ?? {}) as Record<string, unknown>;
  expect(stopCp.status).toBe('stopped');
  expect(stopCp.stopped_at, `custom_properties.stopped_at missing: ${JSON.stringify(stopCp)}`).toBeTruthy();

  // The trap this row exists to catch: run_recording's finalisation block
  // runs AFTER the stop and calls recording_obj.refresh_from_db() before
  // deciding the final status (tasks.py:2337-2338). Its own comment states
  // the priority in exactly these words (tasks.py:2347-2350):
  //
  //   # Final status priority: stopped > completed > interrupted.
  //   # "stopped" is set by the stop endpoint before stream teardown, so
  //   # refresh_from_db() above guarantees it is visible here.
  //
  // A single read immediately after the POST would pass even if that
  // priority were broken (e.g. if the `elif not interrupted: cp["status"]
  // = "completed"` branch at :2354-2355 ran unconditionally) — the
  // finalisation block would not have executed yet. This poll is a
  // best-effort heuristic, not the airtight check: 15s can close before
  // finalisation runs (worst case ~22s — see the extend test's margin
  // derivation below), so it narrows the race without closing it. The
  // deterministic check follows below, keyed on `recording_ended` itself.
  const STABILITY_WINDOW_MS = 15_000;
  const POLL_INTERVAL_MS = 2_000;
  const stabilityDeadline = Date.now() + STABILITY_WINDOW_MS;
  let pollCount = 0;
  while (Date.now() < stabilityDeadline) {
    await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
    pollCount += 1;
    const polled = await readRecording(api, recording.id);
    const polledCp = (polled.custom_properties ?? {}) as Record<string, unknown>;
    expect(
      polledCp.status,
      `recording ${recording.id} left 'stopped' for '${polledCp.status}' on stability poll ` +
        `#${pollCount} — the finalisation priority (stopped > completed > interrupted, ` +
        `tasks.py:2347-2360) was violated: ${JSON.stringify(polledCp)}`
    ).toBe('stopped');
  }
  expect(pollCount, 'stability loop ran zero polls — STABILITY_WINDOW_MS/POLL_INTERVAL_MS math is wrong').toBeGreaterThan(0);

  // The airtight check: `recording_ended` is broadcast (tasks.py:2437-2446)
  // only after run_recording's finalisation block calls
  // `recording_obj.save(update_fields=["custom_properties"])` — the exact
  // write the priority comment above describes — and that send site runs
  // unconditionally after the save, in the stopped path exactly like every
  // other break reason: the `if db_status_now == "stopped":` branch just
  // above it only pops `interrupted_reason`, it does not skip the save or
  // the notify that follow. Once this resolves, that write is guaranteed
  // visible, closing the race the stability poll above can only narrow.
  const endedMsg = await recordingEndedPromise;
  expect(endedMsg.data?.channel).toBe(channel.name);
  const afterEnded = await readRecording(api, recording.id);
  const endedCp = (afterEnded.custom_properties ?? {}) as Record<string, unknown>;
  expect(endedCp.status).toBe('stopped');
  expect(
    endedCp.ended_at,
    `custom_properties.ended_at missing after recording_ended: ${JSON.stringify(endedCp)}`
  ).toBeTruthy();

  // "Retaining the partial content for playback" is file()'s own docstring
  // (api_views.py:3376-3381) — nothing before this row checked it. The
  // concat/remux that produces file_path runs after the stop, so /file/
  // 302s to the HLS playlist until it lands (api_views.py:3392-3399); poll
  // rather than read once. Reuses the authHeaders built above.
  let mkvHead: Buffer | undefined;
  let mkvSize: number | undefined;
  let lastFileStatus: number | undefined;
  let lastFileContentType: string | null | undefined;
  await waitFor.condition(
    async () => {
      try {
        await streamClient.open(`/api/channels/recordings/${recording.id}/file/`, {
          headers: authHeaders,
        });
        lastFileStatus = streamClient.status;
        lastFileContentType = streamClient.headers?.get('content-type');
        const isMkv =
          streamClient.status === 200 &&
          streamClient.headers?.get('content-type') === 'video/x-matroska';
        if (isMkv) {
          mkvSize = Number(streamClient.headers?.get('content-length'));
          mkvHead = await streamClient.readBytes(4);
        }
        return isMkv;
      } finally {
        await streamClient.close();
      }
    },
    {
      timeoutMs: 30_000,
      description: `GET /file/ for recording ${recording.id} to serve the finished partial MKV (concat/remux runs after the stop)`,
      describeLast: () =>
        lastFileStatus === undefined
          ? '(no response observed yet)'
          : `last observed status=${lastFileStatus}, content-type=${lastFileContentType ?? '(none)'}`,
    }
  );
  expect(mkvSize, 'partial MKV content-length missing or unparsable').toBeGreaterThan(0);
  expect(mkvHead).toEqual(MKV_MAGIC);

  // The terminal-state guard (api_views.py:3549-3554) checks
  // `current_status in {"completed", "interrupted", "failed"}` — "stopped"
  // is deliberately NOT in that set, so a second stop is idempotent (200),
  // not a 409. Confirmed both by reading the guard directly and by the
  // existing unit test `test_stop_idempotent_on_already_stopped`
  // (apps/channels/tests/test_recording_stop_cancel.py:118-121), which
  // asserts exactly this. The task brief for this row assumed a 409 here;
  // this asserts the real, already-tested contract instead.
  const secondStopRes = await api.post(`/api/channels/recordings/${recording.id}/stop/`, {});
  expect(
    secondStopRes.status(),
    `second POST /stop/ returned ${secondStopRes.status()}: ${await secondStopRes.text()}`
  ).toBe(200);
  const afterSecondStop = await readRecording(api, recording.id);
  expect((afterSecondStop.custom_properties as Record<string, unknown>)?.status).toBe('stopped');
});

test('extending an in-flight recording moves its deadline past the original end', { tag: '@contract' }, async ({
  upstream,
  seed,
  api,
  waitFor,
  ws,
}) => {
  const scenario = await upstream.scenario({
    channels: [{ id: 1, name: 'G13 DVR Extend', tvgId: 'g13-dvr-extend.e2e', logo: null }],
  });
  const { channel } = await seed.upstreamChannel(scenario, { channelIds: [1] });
  channelIdToCleanup = channel.id;

  const recording = await scheduleRecording(api, channel.id, {
    startInMs: 5_000,
    durationMs: 20_000,
  });
  recordingIdToCleanup = recording.id;
  const originalEndTime = recording.end_time;

  await ws.waitForMessage('recording_started', {
    where: (data) => data.channel === channel.name,
    timeoutMs: 60_000,
  });

  await waitForRecordingStatus(waitFor, recording.id, ['recording']);

  // Minutes is the unit (api_views.py:3627): extend() 400s on anything <= 0
  // (:3631-3635), so 60s — one minute — is the smallest extension the
  // product permits.
  const extendRes = await api.post(`/api/channels/recordings/${recording.id}/extend/`, {
    extra_minutes: 1,
  });
  expect(
    extendRes.status(),
    `POST /extend/ returned ${extendRes.status()}: ${await extendRes.text()}`
  ).toBe(200);

  const expectedEndTime = normalizeIso(new Date(Date.parse(originalEndTime) + 60_000).toISOString());

  const extendedMsg = await ws.waitForMessage('recording_extended', {
    where: (data) => data.recording_id === recording.id,
    timeoutMs: 30_000,
  });
  expect(extendedMsg.data?.extra_minutes).toBe(1);
  expect(normalizeIso(extendedMsg.data?.new_end_time as string)).toBe(expectedEndTime);

  // extend() writes end_time via a queryset .update() specifically to
  // bypass the Recording pre_save receiver (api_views.py:3638-3644,
  // "Use queryset .update() to bypass pre_save/post_save signals. This
  // avoids the pre_save signal revoking the scheduled/running Celery
  // task."). A .update() call never fires pre_save/post_save, so nothing
  // here touches task_id, and asserting on it would be asserting a signal
  // that was deliberately routed around, not one this endpoint runs.
  const afterExtend = await readRecording(api, recording.id);
  expect(normalizeIso(afterExtend.end_time)).toBe(expectedEndTime);

  // The only external proof that run_recording's own ~2s poll loop
  // re-read end_time from the DB and raised its deadline
  // (api_views.py:3612-3615's docstring: "The running task re-reads
  // end_time every ~2 s and adjusts its deadline dynamically") is that the
  // recording is still going well past where the ORIGINAL end_time would
  // have ended it. A single read is NOT enough, though — and the gap
  // between "reaches end_time" and "status stops reading 'recording'" has
  // two components, only one of which is bounded:
  //
  //  1. BOUNDED, 10s: the main loop's `if now >= end_timestamp:` branch
  //     (tasks.py:1859-1870) sends FFmpeg SIGINT and does
  //     `ffmpeg_proc.wait(timeout=10)` inline — `_dvr_ensure_ffmpeg_exited`
  //     (tasks.py:1286-1297) is NOT this component; by the time it runs
  //     (tasks.py:1946, right before the loop's `break`) the process has
  //     already exited from the wait above and it early-returns.
  //  2. UNBOUNDED: after the loop breaks, the HLS→MKV concat/remux runs as
  //     a *synchronous* `subprocess.run()` with no `timeout=` kwarg
  //     (`_dvr_build_hls_concat_cmd`, tasks.py:1226-1246, invoked at
  //     tasks.py:2155-2158; the MP4-intermediate fallback path,
  //     tasks.py:2189-2196 and :2202-2211, is two more such calls). Nothing
  //     bounds how long that ffmpeg process can run. A viewer-wait loop
  //     (tasks.py:2268-2297, polling a Redis heartbeat with a 4-HOUR safety
  //     cap) and a Redis stream-stats fetch (tasks.py:2364-2414) follow
  //     before the final synchronous save that writes `status`
  //     (tasks.py:2427-2436) — smaller, sequential costs on top, though
  //     neither test in this file ever requests an HLS `.ts` segment (only
  //     `.m3u8`, or nothing), so the viewer heartbeat key this harness
  //     produces is never set and that loop returns immediately here.
  //
  // Fix round 1 used +25s (2.5x the 10s bounded component alone) and ran an
  // inversion check (extend() skipped) to prove the margin actually
  // discriminates. That run failed at poll #11 — ~22s into the
  // DISCRIMINATION poll loop, whose clock started right after
  // `waitForRecordingStatus(['recording'])` above, i.e. at recording START,
  // not at end_time (round 1's loop began immediately after that call, with
  // no extend-related work between them once extend() was skipped). The
  // failure was read at the time as "~22s past the original end", crediting
  // the unbounded remux with consuming it — a misread: the inversion
  // payload itself says otherwise. `ended_at 2026-09-02 13:02:40.109543` vs.
  // the original `end_time 2026-09-02T13:02:39.100000Z` puts the real
  // finalisation at ≈ +1.0s past end (container-naive `datetime.now()` is
  // UTC; `started_at 2026-09-02 13:02:19.126560` matches the
  // `20260902_130219.mkv` filename) — so the actual flip was ≈ +2s past end,
  // and the remux itself ran in ≈ 1s, not 22.
  //
  // +40s is kept, but derived rather than measured: worst case is ≈2s for
  // the natural-end path to be noticed + the 10s inline SIGINT grace
  // (component 1 above, tasks.py:1859-1870) + up to another 10s in
  // `_dvr_ensure_ffmpeg_exited` if that inline wait also times out
  // (tasks.py:1286-1297) ≈ 22s, on top of the unbounded concat/remux
  // (component 2 above) measured at ≈1s in every run so far. 40s is
  // therefore generous margin against that bound, not a number derived from
  // the ~22s observation — that observation measured something else
  // entirely. Still comfortably inside the 60s extension (20s of headroom
  // remains before the real new deadline).
  const DISCRIMINATION_MARGIN_MS = 40_000;
  const POLL_INTERVAL_MS = 2_000;
  const discriminationTargetMs = Date.parse(originalEndTime) + DISCRIMINATION_MARGIN_MS;
  let pollCount = 0;
  while (Date.now() < discriminationTargetMs) {
    const remaining = discriminationTargetMs - Date.now();
    await new Promise((resolve) => setTimeout(resolve, Math.min(POLL_INTERVAL_MS, remaining)));
    pollCount += 1;
    const polled = await readRecording(api, recording.id);
    const polledCp = (polled.custom_properties ?? {}) as Record<string, unknown>;
    expect(
      polledCp.status,
      `recording ${recording.id} was '${polledCp.status}' on discrimination poll #${pollCount}, ` +
        `before reaching ${DISCRIMINATION_MARGIN_MS}ms past its ORIGINAL end_time (${originalEndTime}) ` +
        `— extend()'s docstring claims the running task re-reads end_time and raises its ` +
        `deadline; this is the only external check of that: ${JSON.stringify(polledCp)}`
    ).toBe('recording');
  }
  expect(
    pollCount,
    'discrimination poll ran zero iterations — DISCRIMINATION_MARGIN_MS/POLL_INTERVAL_MS math is wrong'
  ).toBeGreaterThan(0);

  // Stop rather than waiting out the extra minute; afterEach deletes the row.
  const stopRes = await api.post(`/api/channels/recordings/${recording.id}/stop/`, {});
  expect(stopRes.status()).toBe(200);
});
