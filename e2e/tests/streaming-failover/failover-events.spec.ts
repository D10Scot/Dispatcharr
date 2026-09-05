import { test, expect, readChannelStatus } from '../../fixtures';
import { lockedProfile } from '../streaming/helpers';

// Phase 1 PR 6: the relay stopped writing SystemEvent rows itself and
// started posting them to Django over /api/relay/events, which is also
// where the relay_event WebSocket push is emitted. Both halves are
// asserted here, because a batch that reaches the view but never pushes
// would still fill the events list and look correct.
//
// The design spec names `channel_failover`; a dead-air fault on this
// Proxy-profile channel empirically produces `stream_switch` instead,
// verified against a live pr6 stack. `channel_failover` is emitted from
// exactly one call site (`input/manager.py`'s buffering-timeout branch
// inside the ffmpeg stderr stats parser) and only runs when the profile
// spawns ffmpeg (the stats come from its stderr) — structurally
// unreachable for Proxy, the profile this project's
// `failover-dead-air.spec.ts` sibling also locks for the same reason.
// `update_url()` is what a dead-air-triggered `_try_next_stream()`
// actually calls, and it emits `stream_switch` — unchanged by Phase 1
// PR 6, which moved the call site's ORM write into `core/relay_events.py`
// without renaming the event. Asserting `channel_failover` here would
// time out forever.
test(
  'a dead-air failover is reported as an event and a relay_event push',
  { tag: '@contract' },
  async ({ upstream, seed, api, streamClient, ws }) => {
    const scenario = await upstream.scenario({
      channels: [
        { id: 1, name: 'P1 Events A', tvgId: 'p1-events-a.e2e', logo: null },
        { id: 2, name: 'P1 Events B', tvgId: 'p1-events-b.e2e', logo: null },
      ],
      rate: 20,
    });
    const proxy = await lockedProfile(api, 'Proxy');
    const { channel, streams } = await seed.upstreamChannel(scenario, {
      channelIds: [1, 2],
      streamProfileId: proxy.id,
    });

    await streamClient.open(`/proxy/ts/stream/${channel.uuid}`);
    await streamClient.readPackets(100);
    expect(
      (await readChannelStatus(api, channel.uuid)).stream_id,
      'should start on stream A'
    ).toBe(streams[0].id);

    await upstream.fault(scenario, 'dead-air', { channel: 1 });

    // The push. /ws/ is one broadcast group, so correlate on this
    // channel's own uuid — another spec's failover must not satisfy it.
    const pushed = ws.waitForMessage('relay_event', {
      where: (data) =>
        data.channel_id === channel.uuid && data.event === 'stream_switch',
      timeoutMs: 120_000,
    });

    await expect
      .poll(async () => (await readChannelStatus(api, channel.uuid)).stream_id, {
        timeout: 120_000,
        intervals: [2_000],
      })
      .toBe(streams[1].id);

    const message = await pushed;
    expect(message.data?.channel_id).toBe(channel.uuid);
    // Pins the push to the switch the poll above observed, not just any
    // stream_switch on this channel.
    expect(message.data?.stream_id).toBe(streams[1].id);
    expect(
      message.data,
      'the push is a field whitelist — no provider URL reaches a browser'
    ).not.toHaveProperty('new_url');

    // The row. Django wrote it, from the batch the relay posted.
    const events = await api.json<{
      events: Array<{ channel_id: string; details?: { stream_id?: number } }>;
    }>(
      await api.get('/api/core/system-events/?event_type=stream_switch&limit=100'),
      'system events after a dead-air failover'
    );
    expect(
      events.events.some(
        (event) =>
          event.channel_id === channel.uuid &&
          event.details?.stream_id === streams[1].id
      ),
      'stream_switch to stream B should be recorded for this channel'
    ).toBe(true);
  }
);
