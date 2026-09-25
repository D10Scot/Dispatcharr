import { test, expect, StreamStatusError } from '../../fixtures';
import {
  scheduleRecording,
  waitForRecordingStatus,
  cleanupRecordingAndChannel,
  MKV_MAGIC,
} from './helpers';

/**
 * D10Scot/Dispatcharr#178: no DVR spec had ever recorded a
 * `hidden_from_output` channel. Every other `dvr` spec records an ordinary
 * channel, which an anonymous request may stream on its own — so all of
 * them would still pass even if `_dvr_build_ffmpeg_cmd`
 * (`apps/channels/tasks.py:1203-1248`) stopped sending
 * `X-Dispatcharr-Internal: <token>` (from `internal_principal_token()`,
 * `apps/channels/tasks.py:1785`) on the FFmpeg request it builds. In AIO,
 * `get_dvr_stream_base_url()` (`apps/channels/tasks.py:1359-1395`) routes
 * that request through nginx on `DISPATCHARR_PORT`, so it meets the same
 * authorize hop (`apps/proxy/authorize.py`) an anonymous tune does — the
 * DVR only gets through because it carries the internal principal, not
 * because the channel is streamable to anyone.
 *
 * This spec proves the premise first — the channel really is refused to an
 * anonymous request — then proves the recording captures real bytes anyway,
 * which is only possible if the DVR's own request carried a principal the
 * hop accepted. Without the premise half, a passing recording would prove
 * nothing: the channel might simply not have been hidden.
 *
 * Follows `recording-execution.spec.ts`'s flagship shape end to end
 * (scenario, schedule, poll for a live upstream connection, poll for
 * `completed`, read the finished file) and its cleanup shape (module-scoped
 * ids assigned the moment each resolves, deleted in `test.afterEach` rather
 * than a body-level `try`/`finally` — see that file's header for why: a
 * timed-out test is torn down mid-`await` by Playwright with nothing after
 * that point, a `finally` block included, guaranteed to run, but fixture
 * teardown always does). Safe as one shared pair of bindings because the
 * `dvr` project is `workers: 1` with `fullyParallel` inherited `false` — the
 * whole project runs one test at a time, so no other test's `afterEach` can
 * ever observe this test's write.
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
    'recording-hidden-channel.spec.ts'
  );
});

test(
  'a recording of a channel hidden from output still captures bytes, because the DVR is the internal principal',
  { tag: '@contract' },
  async ({ upstream, seed, api, waitFor, streamClient }) => {
    const scenario = await upstream.scenario({
      channels: [{ id: 1, name: 'H4 DVR Hidden', tvgId: 'h4-dvr-hidden.e2e', logo: null }],
    });
    const { channel } = await seed.upstreamChannel(scenario, {
      channelIds: [1],
      channel: { hidden_from_output: true },
    });
    channelIdToCleanup = channel.id;
    // Premise: the hop refuses this channel to anyone without a principal.
    // Without this, a successful recording below would prove nothing about
    // the internal-principal header at all.
    await expectRefused(
      streamClient,
      `/proxy/ts/stream/${channel.uuid}`,
      403,
      'the channel must be hidden, or a successful recording proves nothing'
    );

    const recording = await scheduleRecording(api, channel.id, {
      startInMs: 5_000,
      durationMs: 30_000,
    });
    recordingIdToCleanup = recording.id;

    // Bytes flowed provider -> the relay -> FFmpeg: the flagship's own
    // proof (recording-execution.spec.ts:104-125), reused unchanged here.
    // The budget is wider than the flagship's own 20s because this spec
    // does not wait on `custom_properties.status === 'recording'` first —
    // it polls straight from schedule time: 5s to start, plus beat's own
    // worst-case 5s tick, plus FFmpeg's `_first_segment_timeout` of 15s,
    // plus margin.
    let lastLiveCount: number | undefined;
    await waitFor.condition(
      async () => {
        const conns = await upstream.connections(scenario);
        lastLiveCount = conns.live;
        return conns.live === 1;
      },
      {
        timeoutMs: 60_000,
        description: `upstream scenario ${scenario.id} to show exactly 1 live connection for recording ${recording.id}`,
        describeLast: () => `last observed live=${lastLiveCount}`,
      }
    );

    const finished = await waitForRecordingStatus(waitFor, recording.id, ['completed', 'interrupted']);
    const finishedCp = (finished.custom_properties ?? {}) as Record<string, unknown>;
    expect(
      finishedCp.status,
      `recording ${recording.id} ended as '${finishedCp.status}': ` +
        `interrupted_reason=${finishedCp.interrupted_reason ?? '(none)'}`
    ).toBe('completed');

    // Then the finished file, exactly as the flagship reads it.
    const authHeaders = { Authorization: `Bearer ${await api.freshAccessToken()}` };
    await streamClient.open(`/api/channels/recordings/${recording.id}/file/`, {
      headers: authHeaders,
    });
    expect(streamClient.status).toBe(200);
    expect(streamClient.headers?.get('content-type')).toBe('video/x-matroska');
    const fileSize = Number(streamClient.headers?.get('content-length'));
    expect(fileSize).toBeGreaterThan(0);
    const headBytes = await streamClient.readBytes(4);
    expect(headBytes).toEqual(MKV_MAGIC);
    await streamClient.close();
  }
);

/**
 * Open `path` and require an exact refusal status.
 *
 * Copied locally from `tests/streaming/authorize-matrix.spec.ts` rather than
 * imported across projects (the `dvr` and `streaming` Playwright projects
 * do not share test modules) — only a `StreamStatusError` of exactly
 * `status` counts. A reset, a DNS failure, a 500 or a different 4xx
 * rethrows, so a broken fixture fails the test instead of reading as "the
 * product refused it".
 */
async function expectRefused(
  streamClient: { open: (p: string, o?: { headers?: Record<string, string> }) => Promise<void>; close: () => Promise<void> },
  path: string,
  status: number,
  message: string,
  headers?: Record<string, string>
): Promise<void> {
  let refused = false;
  try {
    await streamClient.open(path, headers ? { headers } : {});
  } catch (error) {
    if (!(error instanceof StreamStatusError) || error.status !== status) throw error;
    refused = true;
  }
  try {
    expect(refused, message).toBe(true);
  } finally {
    // Abort whatever was opened, so a failing run does not leave an
    // upstream connection held for the rest of the project.
    await streamClient.close();
  }
}
