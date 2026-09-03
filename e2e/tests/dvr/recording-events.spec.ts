import { test, expect } from '../../fixtures';
import { scheduleRecording, waitForRecordingStatus, cleanupRecordingAndChannel } from './helpers';

/**
 * `recording_cancelled` — the destroy path's WebSocket event, and the three
 * side effects `RecordingViewSet.destroy` (`apps/channels/api_views.py:3776`)
 * runs after sending it. Its own docstring states the ordering
 * (`:3781-3789`):
 *
 *   1. Delete the DB record first — run_recording's cancellation guard
 *      (Recording.objects.filter(id=...).exists()) will now return False...
 *   2. Send recording_cancelled WebSocket immediately so the frontend
 *      removes the card without waiting for the slow DVR client teardown.
 *   3. Spawn a background thread to stop the DVR client and delete files.
 *
 * Row 5 is the `was_in_progress: false` branch — cancelling a recording
 * before it ever fires. Row 6 is `was_in_progress: true` — cancelling
 * in-flight — plus what that background thread does: releasing the
 * upstream connection and (see below) attempting to delete the recording's
 * files.
 *
 * `apps/channels/tests/test_recording_stop_cancel.py:125-161` asserts the
 * `was_in_progress` payload shape against a mocked `send_websocket_update`
 * for both branches, but never against a real `run_recording` — neither
 * branch has been exercised end to end before this file.
 *
 * Same cleanup shape as `recording-execution.spec.ts` / `recording-control.spec.ts`:
 * module-scoped bindings assigned the moment each id resolves, deleted in
 * `afterEach` (fixture teardown, which runs on its own budget regardless of
 * how the test body ended) rather than a body-level `try`/`finally`. Both
 * rows here delete their own recording as part of the test body — the
 * `afterEach`'s tolerance for an already-404 `DELETE` (see below) is what
 * makes that safe rather than a double-delete error. Safe as one shared pair
 * because the `dvr` project is `workers: 1` with `fullyParallel` inherited
 * `false` — the whole project runs one test at a time.
 *
 * ---------------------------------------------------------------------------
 * What this pair does NOT close
 * ---------------------------------------------------------------------------
 * Two of the destroy path's side effects have no REST surface and stay
 * unobserved here, both ultimately for the reason spec D5 already rules out
 * (`docker exec`):
 *
 *  1. Deleting the `PeriodicTask`/`ClockedSchedule` pair via the
 *     `post_delete` receiver `revoke_task_on_delete`
 *     (`apps/channels/signals.py:388-390`) — neither model has a REST
 *     surface, so their removal can't be checked by anything this harness
 *     is allowed to run. Already flagged as a gap in `COVERAGE.md`'s G6 row;
 *     Task 10 updates that row for what G13 does and doesn't add.
 *
 *  2. The actual disk removal — `_safe_remove(file_path)` /
 *     `_safe_rmtree(hls_dir)` (`api_views.py:3865-3882`), run from the
 *     background thread `destroy()` spawns at `:3941`. This one is a
 *     correction to the task brief, not a restatement of it: the brief's
 *     premise was that a post-cancel `GET .../file/` 404ing would prove that
 *     thread had run. It doesn't. `destroy()` deletes the `Recording` row
 *     SYNCHRONOUSLY, before the background thread even starts —
 *     `response = super().destroy(request, *args, **kwargs)` at `:3846`
 *     executes before `threading.Thread(target=_background_cancel,
 *     daemon=True).start()` at `:3941` — and `file()`'s (and `hls()`'s)
 *     very first line after permission checks is
 *     `get_object_or_404(Recording, pk=pk)` (`:3385`, `:3478`). So
 *     `GET .../file/` 404s the instant the `DELETE` response comes back,
 *     whether or not any file was ever removed from disk — polling it for
 *     up to 30s, as the brief specified, would still only ever observe the
 *     row being gone, on the very first poll. Row 6 below still asserts the
 *     404 (it's a real, correct piece of API behaviour worth pinning), but
 *     says so accurately in its own comment rather than claiming it as
 *     evidence of the file/HLS-dir teardown. There is no REST surface that
 *     reaches the filesystem independent of the `Recording` row, so — like
 *     the beat-schedule pair above — this is unobservable under D5's
 *     constraints, not merely unobserved. Flagged to the task's requester;
 *     Task 10's `COVERAGE.md` gap row should record this precisely, not as
 *     "closed".
 */
let channelIdToCleanup: number | undefined;
let recordingIdToCleanup: number | undefined;

test.afterEach(async ({ api }, testInfo) => {
  const recordingId = recordingIdToCleanup;
  const channelId = channelIdToCleanup;
  recordingIdToCleanup = undefined;
  channelIdToCleanup = undefined;
  // Both rows below delete their own recording as part of the test body
  // (that's the thing under test), so cleanupRecordingAndChannel's 404
  // tolerance is exercising the expected, already-cleaned-up case here, not
  // papering over a real cleanup failure.
  await cleanupRecordingAndChannel(
    api,
    testInfo,
    { recordingId, channelId },
    'recording-events.spec.ts'
  );
});

test(
  'cancelling an upcoming recording sends recording_cancelled with was_in_progress: false and 404s the row',
  { tag: '@contract' },
  async ({ upstream, seed, api, ws }) => {
    const scenario = await upstream.scenario({
      channels: [{ id: 1, name: 'G13 DVR Cancel Upcoming', tvgId: 'g13-dvr-cancel-upcoming.e2e', logo: null }],
    });
    const { channel } = await seed.upstreamChannel(scenario, { channelIds: [1] });
    channelIdToCleanup = channel.id;

    // An hour out — comfortably beyond anything this test's own timeout
    // budget could let fire — and via uniqueStartTime rather than a rounded
    // timestamp (see helpers.ts and D10Scot/Dispatcharr#131). This row needs
    // no recording to ever start: it is the honest place for the
    // was_in_progress: false branch, since nothing here races run_recording.
    const recording = await scheduleRecording(api, channel.id, {
      startInMs: 60 * 60 * 1000,
      durationMs: 60_000,
    });
    recordingIdToCleanup = recording.id;

    const deleteRes = await api.delete(`/api/channels/recordings/${recording.id}/`);
    expect(deleteRes.status(), `DELETE returned ${deleteRes.status()}: ${await deleteRes.text()}`).toBe(204);

    // destroy() sends this synchronously (api_views.py:3846-3858), well
    // before this test's DELETE call above even returns its response body,
    // so no poll is needed here — a bare wait is enough.
    const cancelledMsg = await ws.waitForMessage('recording_cancelled', {
      where: (data) => data.recording_id === recording.id,
      timeoutMs: 30_000,
    });
    expect(cancelledMsg.data?.channel).toBe(channel.name);
    expect(cancelledMsg.data?.was_in_progress).toBe(false);

    const detailRes = await api.get(`/api/channels/recordings/${recording.id}/`);
    expect(detailRes.status()).toBe(404);
  }
);

test(
  'cancelling an in-flight recording sends recording_cancelled with was_in_progress: true, removes the row, 404s the file endpoint and releases the upstream',
  { tag: '@contract' },
  async ({ upstream, seed, api, waitFor, ws, streamClient }) => {
    const scenario = await upstream.scenario({
      channels: [{ id: 1, name: 'G13 DVR Cancel In-Flight', tvgId: 'g13-dvr-cancel-inflight.e2e', logo: null }],
    });
    const { channel } = await seed.upstreamChannel(scenario, { channelIds: [1] });
    channelIdToCleanup = channel.id;

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

    // status flips to 'recording' at the very top of run_recording, before
    // FFmpeg is even spawned (helpers.ts, and recording-execution.spec.ts's
    // own comment on the same race). Cancelling immediately on that
    // transition would race FFmpeg's startup: if it never got as far as
    // connecting upstream, the live === 0 poll after cancelling below would
    // pass trivially — there was nothing live to release. Confirm a live
    // upstream connection AND a real HLS segment first, the same discipline
    // recording-control.spec.ts applies before stopping (its own comment
    // documents the ZERO-segment failure this avoids).
    const authHeaders = { Authorization: `Bearer ${await api.freshAccessToken()}` };
    let lastLiveCount: number | undefined;
    await waitFor.condition(
      async () => {
        const conns = await upstream.connections(scenario);
        lastLiveCount = conns.live;
        return conns.live === 1;
      },
      {
        timeoutMs: 20_000,
        description: `upstream scenario ${scenario.id} to show exactly 1 live connection for recording ${recording.id}`,
        describeLast: () => `last observed live=${lastLiveCount}`,
      }
    );
    let lastPlaylistBeforeCancel = '';
    await waitFor.condition(
      async () => {
        try {
          await streamClient.open(`/api/channels/recordings/${recording.id}/hls/index.m3u8`, {
            headers: authHeaders,
          });
          const playlist = (await streamClient.collectFor(2_000)).toString('utf8');
          lastPlaylistBeforeCancel = playlist;
          return playlist.startsWith('#EXTM3U') && /seg_\d+\.ts/.test(playlist);
        } finally {
          await streamClient.close();
        }
      },
      {
        timeoutMs: 30_000,
        description: `the HLS playlist for recording ${recording.id} to list at least one segment before cancelling`,
        describeLast: () =>
          lastPlaylistBeforeCancel
            ? `last playlist (${lastPlaylistBeforeCancel.length} bytes) starts=${lastPlaylistBeforeCancel.startsWith('#EXTM3U')}, hasSegment=${/seg_\d+\.ts/.test(lastPlaylistBeforeCancel)}`
            : '(no playlist body observed yet)',
      }
    );

    const deleteRes = await api.delete(`/api/channels/recordings/${recording.id}/`);
    expect(deleteRes.status(), `DELETE returned ${deleteRes.status()}: ${await deleteRes.text()}`).toBe(204);

    // Premise guard, checked BEFORE the live === 0 poll below: this proves
    // the recording was still genuinely 'recording' (not already ended on
    // its own — durationMs is 45s and the segment/connection waits above
    // leave well over half of that) at the moment it was cancelled, so the
    // upstream-release assertion after it cannot pass merely because the
    // recording had already finished by itself.
    const cancelledMsg = await ws.waitForMessage('recording_cancelled', {
      where: (data) => data.recording_id === recording.id,
      timeoutMs: 30_000,
    });
    expect(cancelledMsg.data?.channel).toBe(channel.name);
    expect(cancelledMsg.data?.was_in_progress).toBe(true);

    const detailRes = await api.get(`/api/channels/recordings/${recording.id}/`);
    expect(detailRes.status()).toBe(404);

    // GET /file/ 404s here, but — see the file-header comment — NOT
    // necessarily because the backgrounded _safe_remove/_safe_rmtree
    // teardown (api_views.py:3865-3882, spawned in a daemon thread at
    // :3941) has run yet. destroy() deletes the Recording row
    // synchronously, before that thread even starts, and file()'s first
    // line is get_object_or_404(Recording, pk=pk) (:3385) — so this 404 is
    // guaranteed the instant the DELETE above returned, independent of
    // whether any file was ever removed from disk. Asserted here as a real,
    // correct piece of API behaviour, not as proof of the disk-side
    // teardown.
    const fileRes = await api.get(`/api/channels/recordings/${recording.id}/file/`);
    expect(fileRes.status()).toBe(404);

    // upstream.connections is keyed by the provider scenario, not by the
    // Recording row, so THIS poll — unlike the /file/ read above — is real
    // evidence that the cancel path released the upstream, rather than
    // merely reflecting a row that is already gone. Not attributed to a
    // specific mechanism: `_stop_dvr_clients()` (api_views.py:3915, run from
    // the background thread via `_background_cancel` at :3910-3931) reaching
    // live_proxy and run_recording's own ~2s poll noticing the row is gone
    // (`_sc is None` at tasks.py:~1874-1889, which SIGINTs FFmpeg and exits
    // the loop) both release the same upstream connection, and there is no
    // way to tell from outside the container which one this run actually
    // saw. Backgrounded (at least one of the two paths is), so poll rather
    // than assert once.
    let lastLiveAfterCancel: number | undefined;
    await waitFor.condition(
      async () => {
        const conns = await upstream.connections(scenario);
        lastLiveAfterCancel = conns.live;
        return conns.live === 0;
      },
      {
        timeoutMs: 30_000,
        description: `upstream scenario ${scenario.id} to release its live connection after cancelling recording ${recording.id}`,
        describeLast: () => `last observed live=${lastLiveAfterCancel}`,
      }
    );
  }
);
