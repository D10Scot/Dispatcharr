import path from 'node:path';
import { test, expect, expectTsAligned } from '../../fixtures';
import type { Fixtures } from '../../fixtures';
import { scheduleRecording, waitForRecordingStatus, MKV_MAGIC } from './helpers';

/**
 * The goal's centre: the first execution of `run_recording`
 * (`apps/channels/tasks.py`, ~1,100 lines) under any test in this
 * repository. Row 1 drives the whole lifecycle — scheduled, fires,
 * in-progress HLS playback, completion, finished MKV over HTTP — and Row 2
 * pins the output-path shape `_build_output_paths` writes. Row 2 is two
 * `test()` declarations, not one: a passing premise plus a `test.fail()` —
 * see the comment above the `test.fail()` for the product defect that split
 * it, discovered verifying the brief's assumption against source.
 *
 * Both rows follow `dvr.spec.ts`'s cleanup shape: module-scoped bindings
 * assigned the moment each id resolves, deleted in `afterEach` rather than
 * a body-level `try`/`finally` — a timed-out test is torn down mid-`await`
 * by Playwright with nothing after that point (a `finally` block included)
 * guaranteed to run, but fixture teardown always does. Safe as one shared
 * pair of bindings because the `dvr` project is `workers: 1` with
 * `fullyParallel` inherited `false` — the whole project runs one test at a
 * time, so no other test's `afterEach` can ever observe this test's write.
 *
 * `Recording.channel` is `on_delete=CASCADE` (`apps/channels/models.py:1161`),
 * so deleting the channel alone would remove the recording too — but the
 * recording is deleted explicitly and first, matching `helpers.ts`'s own
 * rule (`DELETE .../recordings/<id>/` is what triggers
 * `revoke_task_on_delete`, tearing down the `PeriodicTask`/`ClockedSchedule`
 * pair) rather than relying on a cascade side effect to do it.
 */
let channelIdToCleanup: number | undefined;
let recordingIdToCleanup: number | undefined;

test.afterEach(async ({ api }, testInfo) => {
  const recordingId = recordingIdToCleanup;
  const channelId = channelIdToCleanup;
  recordingIdToCleanup = undefined;
  channelIdToCleanup = undefined;
  if (recordingId === undefined && channelId === undefined) return;

  try {
    if (recordingId !== undefined) {
      const res = await api.delete(`/api/channels/recordings/${recordingId}/`);
      if (res.status() !== 204 && res.status() !== 404) {
        throw new Error(`recording cleanup failed: DELETE returned ${res.status()}`);
      }
    }
    if (channelId !== undefined) {
      const res = await api.delete(`/api/channels/channels/${channelId}/`);
      if (res.status() !== 204 && res.status() !== 404) {
        throw new Error(`channel cleanup failed: DELETE returned ${res.status()}`);
      }
    }
  } catch (cleanupError) {
    // Same non-masking shape dvr.spec.ts/plugins.spec.ts settled on: a
    // cleanup failure must not replace an already-failing test's real cause.
    if (testInfo.status !== 'passed') {
      console.error(
        'recording-execution.spec.ts: cleanup failed after an in-flight test ' +
          'failure — not overwriting it. Cleanup error:',
        cleanupError
      );
      return;
    }
    throw cleanupError;
  }
});

/** Escapes regex metacharacters in a generated channel name for use inside `new RegExp(...)`. */
function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

test('a scheduled recording fires, plays back in progress, completes and is served as an MKV over HTTP', { tag: '@contract' }, async ({
  upstream,
  seed,
  api,
  waitFor,
  ws,
  streamClient,
}) => {
  const scenario = await upstream.scenario({
    channels: [{ id: 1, name: 'G13 DVR Flagship', tvgId: 'g13-dvr-flagship.e2e', logo: null }],
  });
  const { channel } = await seed.upstreamChannel(scenario, { channelIds: [1] });
  // Assigned the moment it resolves — see the file header for why this lives
  // outside the test body rather than in a body-level try/finally.
  channelIdToCleanup = channel.id;

  const recording = await scheduleRecording(api, channel.id, {
    startInMs: 5_000,
    durationMs: 30_000,
  });
  recordingIdToCleanup = recording.id;

  // `ws` is already subscribed to the `updates` group before the test body
  // runs — the fixture awaits `connection_established` at setup — so this
  // wait cannot miss the event even though it is registered after
  // `scheduleRecording` above. `recording_started` carries only `channel`
  // (D10Scot/Dispatcharr#132), never `recording_id`, so correlate on the
  // seeded channel's generated name.
  //
  // Budget: 5s until start_time, plus beat's own worst-case tick (5s,
  // django_celery_beat's DatabaseScheduler default max loop interval),
  // plus Celery dispatch and DB sync, times a safety factor.
  await ws.waitForMessage('recording_started', {
    where: (data) => data.channel === channel.name,
    timeoutMs: 60_000,
  });

  // Step 3: in-flight state.
  const inFlight = await waitForRecordingStatus(waitFor, recording.id, ['recording']);
  expect(inFlight.custom_properties?.file_url).toBe(
    `/api/channels/recordings/${recording.id}/hls/index.m3u8`
  );

  // `custom_properties.status` flips to 'recording' at the very top of
  // `run_recording` (tasks.py:~1460-1463) — before `_build_output_paths`,
  // before `get_dvr_stream_base_url()`, and before FFmpeg is even spawned.
  // So the upstream connection can genuinely lag the status flip by up to
  // several seconds while FFmpeg starts and connects (`_first_segment_timeout`
  // gives it up to 15s). A bare single read of `connections()` right after
  // the status wait would therefore be a flake, not a detector — poll it,
  // the same reasoning single-client.spec.ts documents for `total_bytes`.
  //
  // This is the assertion that makes the test end to end: DVR records
  // `f"{base}/proxy/ts/stream/{channel.uuid}"` (tasks.py:1632), so a live
  // provider connection proves bytes flowed provider -> live_proxy -> FFmpeg.
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

  // Step 4: in-progress playback.
  const authHeaders = { Authorization: `Bearer ${await api.freshAccessToken()}` };

  await streamClient.open(`/api/channels/recordings/${recording.id}/file/`, {
    redirect: 'manual',
    headers: authHeaders,
  });
  expect(streamClient.status).toBe(302);
  expect(streamClient.headers?.get('location')).toMatch(/\/hls\/index\.m3u8$/);
  await streamClient.close();

  // `os.path.isdir(hls_dir)` (what the redirect above depends on) is true
  // moments after status flips to 'recording' — well before FFmpeg is even
  // spawned. But `hls_dir/index.m3u8` is only written once FFmpeg's HLS
  // muxer actually starts producing output, which lags the upstream
  // connection (live === 1, confirmed above) by however long FFmpeg takes to
  // spawn, connect and mux its first output — confirmed empirically against
  // this container: a bare GET immediately after live === 1 404s
  // intermittently ("HLS file not found: index.m3u8",
  // apps/channels/api_views.py:3504), and the *playlist* can exist with zero
  // segments listed before the first hls_time=4s segment closes. Poll for
  // both — endpoint availability and a first segment — rather than one bare
  // read racing FFmpeg's startup, the same reasoning single-client.spec.ts
  // documents for polling total_bytes.
  let playlist = '';
  let segmentMatch: RegExpMatchArray | null = null;
  await waitFor.condition(
    async () => {
      await streamClient.open(`/api/channels/recordings/${recording.id}/hls/index.m3u8`, {
        headers: authHeaders,
      });
      const playlistBytes = await streamClient.collectFor(3_000);
      await streamClient.close();
      playlist = playlistBytes.toString('utf8');
      segmentMatch = playlist.match(/https?:\/\/\S*seg_\d+\.ts\S*/);
      return playlist.startsWith('#EXTM3U') && segmentMatch !== null;
    },
    {
      timeoutMs: 30_000,
      description:
        `the HLS playlist for recording ${recording.id} to list at least one ` +
        `segment (FFmpeg's HLS muxer, hls_time=4s, lags the upstream connection)`,
    }
  );
  expect(playlist.startsWith('#EXTM3U')).toBe(true);
  // Deliberately no segment-count assertion beyond "at least one": with
  // `-c copy`, FFmpeg ingests as fast as the proxy delivers, so how many
  // 4-second segments a 30 wall second capture produces is not fixed
  // (e2e-upstream/README.md states the same rule for throughput generally).
  expect(segmentMatch, `playlist named no seg_ entry:\n${playlist}`).toBeTruthy();
  const segmentUrl = segmentMatch![0];

  await streamClient.open(segmentUrl, { headers: authHeaders });
  const segmentLength = Number(streamClient.headers?.get('content-length'));
  expect(segmentLength).toBeGreaterThan(0);
  // The strongest single proof that run_recording wrote real video: these are
  // raw MPEG-TS segments (FFmpeg -c copy into the HLS muxer), so the same
  // alignment assertion the live streaming specs use applies unchanged.
  const segmentBytes = await streamClient.readBytes(segmentLength);
  expectTsAligned(segmentBytes);
  await streamClient.close();

  // Step 5: completion.
  await ws.waitForMessage('recording_ended', {
    where: (data) => data.channel === channel.name,
    timeoutMs: 90_000,
  });
  // Budget: the 30s capture window plus the post-recording concat/remux —
  // by the time `recording_ended` fires, the final `status` write has
  // already landed (tasks.py:2332-2361 runs, then the group_send at
  // :2440-2446), so this second wait should resolve near-instantly; it
  // exists to make a stuck concat step name itself rather than time out
  // silently against the ws wait above.
  const finished = await waitForRecordingStatus(waitFor, recording.id, ['completed', 'interrupted'], {
    timeoutMs: 90_000,
  });
  const finishedCp = (finished.custom_properties ?? {}) as Record<string, unknown>;
  // If this lands on 'interrupted', the message surfaces interrupted_reason
  // — the whole diagnostic budget for a failed first contact (see the
  // Migration relevance note in the spec: a relay moved out of the Django
  // process makes get_dvr_stream_base_url() wrong, FFmpeg gets refused, and
  // run_recording gives up after _first_segment_timeout with no error at the
  // API — interrupted_reason is the only thing that would still name it).
  expect(
    finishedCp.status,
    `recording ${recording.id} ended as '${finishedCp.status}': ` +
      `interrupted_reason=${finishedCp.interrupted_reason ?? '(none)'}`
  ).toBe('completed');
  expect(finishedCp.bytes_written).toBeGreaterThan(0);
  expect(finishedCp.ended_at).toBeTruthy();
  expect(finishedCp.file_url).toBe(`/api/channels/recordings/${recording.id}/file/`);

  // Step 6: the finished file over HTTP.
  await streamClient.open(`/api/channels/recordings/${recording.id}/file/`, {
    headers: authHeaders,
  });
  expect(streamClient.status).toBe(200);
  expect(streamClient.headers?.get('content-type')).toBe('video/x-matroska');
  const fileSize = Number(streamClient.headers?.get('content-length'));
  expect(fileSize).toBeGreaterThan(0);
  expect(streamClient.headers?.get('accept-ranges')).toBe('bytes');
  // A format check, not a length check — the first four bytes are the EBML
  // magic number every Matroska file begins with.
  const headBytes = await streamClient.readBytes(4);
  expect(headBytes).toEqual(MKV_MAGIC);
  await streamClient.close();

  await streamClient.open(`/api/channels/recordings/${recording.id}/file/`, {
    headers: { ...authHeaders, Range: 'bytes=0-1023' },
  });
  expect(streamClient.status).toBe(206);
  expect(streamClient.headers?.get('content-range')).toBe(`bytes 0-1023/${fileSize}`);
  const rangeBytes = await streamClient.readBytes(1024);
  expect(rangeBytes.byteLength).toBe(1024);
  await streamClient.close();
});

/**
 * Schedules and primes a fresh recording, waits for it to reach 'recording',
 * and returns its `custom_properties`. Shared by the premise test and the
 * `test.fail()` below — both need the identical setup, and duplicating it
 * would let the two drift apart on exactly the fixture shape the defect
 * comment depends on.
 *
 * The row's own recording, created fresh — the flagship's is already gone by
 * the time either of these run (module-scoped `afterEach` deletes it, and
 * this project is `workers: 1` / serial, so there is no reuse race, only
 * sequencing). The spec's own inventory suggested reusing the flagship's
 * recording; that is impossible once cleanup runs between tests, so this row
 * schedules and owns its own.
 *
 * The output paths are written at prime time, before FFmpeg starts — this
 * row does not need the recording to complete, so it asserts as soon as
 * status flips to 'recording' and lets `afterEach` delete it. Keeps each row
 * under 20s.
 */
async function primeOutputPathRecording(
  fixtures: Pick<Fixtures, 'upstream' | 'seed' | 'api' | 'waitFor' | 'ws'>,
  channelName: string
): Promise<{ channelName: string; cp: Record<string, unknown>; recordingId: number }> {
  const { upstream, seed, api, waitFor, ws } = fixtures;
  const scenario = await upstream.scenario({
    channels: [{ id: 1, name: channelName, tvgId: `${channelName.toLowerCase().replace(/\s+/g, '-')}.e2e`, logo: null }],
  });
  const { channel } = await seed.upstreamChannel(scenario, { channelIds: [1] });
  channelIdToCleanup = channel.id;

  const recording = await scheduleRecording(api, channel.id, {
    startInMs: 5_000,
    durationMs: 30_000,
  });
  recordingIdToCleanup = recording.id;

  await ws.waitForMessage('recording_started', {
    where: (data) => data.channel === channel.name,
    timeoutMs: 60_000,
  });

  const inFlight = await waitForRecordingStatus(waitFor, recording.id, ['recording']);
  return {
    channelName: channel.name,
    cp: (inFlight.custom_properties ?? {}) as Record<string, unknown>,
    recordingId: recording.id,
  };
}

// Guards the premise the test.fail() below depends on, from OUTSIDE the
// inverted block: test.fail() is satisfied by ANY failure inside it, so no
// assertion in that body can guard its own premise. This row is unaffected
// by the defect the test.fail() pins (see its comment) — it stays green on
// its own, so a change that broke library_root, the fallback filename shape,
// or the HLS working-directory naming would surface HERE, not be swallowed
// as "the pin still fails".
//
// @characterization: `library_root = '/data/recordings'` is a hard-coded
// literal in `_build_output_paths`, not a setting, and the filename shape is
// the shipped default of `get_dvr_tv_fallback_template`. A deployment that
// relocates the library, or a change to the default templates, legitimately
// breaks this row.
test('row 2 premise: an ad-hoc recording writes its fallback file under /data/recordings/TV_Shows with a timestamp filename', { tag: '@characterization' }, async ({
  upstream,
  seed,
  api,
  waitFor,
  ws,
}) => {
  const { cp, recordingId } = await primeOutputPathRecording(
    { upstream, seed, api, waitFor, ws },
    'G13 DVR Output Path Premise'
  );

  const filePath = cp.file_path as string | undefined;
  expect(filePath, `custom_properties.file_path missing: ${JSON.stringify(cp)}`).toBeTruthy();
  expect(filePath!.startsWith('/data/recordings/')).toBe(true);
  // `{start}` is `start_time.strftime('%Y%m%d_%H%M%S')` — 8 digits, an
  // underscore, 6 digits. Deliberately not anchored on a `{show}` segment —
  // see the test.fail() below for why that part is contested, not premised.
  expect(filePath).toMatch(/^\/data\/recordings\/TV_Shows\/(?:[^/]+\/)?\d{8}_\d{6}\.mkv$/);

  const hlsDir = cp._hls_dir as string | undefined;
  expect(hlsDir, `custom_properties._hls_dir missing: ${JSON.stringify(cp)}`).toBeTruthy();
  expect(path.basename(hlsDir!)).toBe(`.dvr_${recordingId}_hls`);
});

// @characterization: `library_root = '/data/recordings'` is a hard-coded literal in
// `_build_output_paths`, not a setting, and the path shape is the shipped default of
// `get_dvr_tv_fallback_template`. A deployment that relocates the library, or a change to
// the default templates, legitimately breaks this row.
test.fail('the recording lands where the DVR templates say it should', { tag: '@characterization' }, async ({
  upstream,
  seed,
  api,
  waitFor,
  ws,
}) => {
  // KNOWN BUG, not filed yet — the controller will file it. `_build_output_paths`'s
  // show/title derivation (apps/channels/tasks.py:1032-1033) reads:
  //
  //   show = _safe_name(program.get('title') if isinstance(program, dict) else channel.name)
  //
  // `program` is always `cp.get("program") or {}` (tasks.py:1469) — an empty
  // dict is still a dict, so `isinstance(program, dict)` is True even when
  // `program` is `{}`, and the `else channel.name` branch is DEAD CODE: it is
  // unreachable for every ad-hoc recording with no EPG match, which is
  // exactly the case this row and the flagship both exercise.
  // `program.get('title')` on `{}` is `None`; `_safe_name(None)` returns `""`
  // (tasks.py:976, `s = s or ""`); the fallback template
  // `TV_Shows/{show}/{start}.mkv` then formats to `TV_Shows//<start>.mkv`,
  // and `os.path.normpath` (tasks.py:1090) silently collapses the empty path
  // segment to `TV_Shows/<start>.mkv`. Every ad-hoc recording with no EPG
  // match therefore loses the per-channel/show subdirectory the `{show}`
  // placeholder in `tv_fallback_template` exists to provide — confirmed
  // empirically against this container (both via this row and via a
  // hand-built recording against a manually created channel: channel
  // "manual-debug-channel" produced
  // file_path "/data/recordings/TV_Shows/20260902_121459.mkv", with no
  // channel-name segment at all).
  //
  // This asserts the CORRECT value per the template's own stated intent, not
  // the buggy one — never invert this to match the bug, which would lock the
  // defect in.
  const { cp, channelName } = await primeOutputPathRecording(
    { upstream, seed, api, waitFor, ws },
    'G13 DVR Output Path'
  );

  const filePath = cp.file_path as string | undefined;
  expect(filePath, `custom_properties.file_path missing: ${JSON.stringify(cp)}`).toBeTruthy();
  // FAILS TODAY: the actual value has no channelName segment (see the defect
  // comment above) — `/data/recordings/TV_Shows/<start>.mkv`.
  expect(filePath).toMatch(
    new RegExp(`^/data/recordings/TV_Shows/${escapeRegExp(channelName)}/\\d{8}_\\d{6}\\.mkv$`)
  );
});
