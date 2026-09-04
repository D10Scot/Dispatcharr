import { test, expect, expectTsAligned, TS_PACKET_SIZE } from '../../fixtures';
import { lockedProfile } from './helpers';

/**
 * Liveness/routing guard across the relay split (Phase 1 PR 2).
 *
 * This is NOT a spooling detector: at this scenario's `rate: 20`, buffered
 * nginx (a `proxy_buffering`/`uwsgi_buffering`-style default buffer, 4k or
 * 8k) would still forward well inside a 10s window, so a 10s pass here
 * cannot tell an unbuffered response apart from a briefly-buffered one — see
 * tests/streaming-greybox/nginx-stream-buffering.spec.ts, which pins the
 * directive statically. What this test does verify: a live channel answers
 * with a valid, 188-byte-aligned TS packet within 10s through whichever
 * process serves `/proxy/ts/stream/<uuid>` — nginx today, and unchanged
 * after PR 4 gives that route its own nginx location, since nothing about
 * this assertion depends on which process answers the request. It must
 * exist before that routing changes and keep passing after it.
 *
 * The measured elapsed time is logged unconditionally below; the
 * implementing PR copies that number, plus this 10s ceiling, into its
 * description per the spec's own instruction.
 */
const LIVENESS_CEILING_MS = 10_000;

test(
  'the first TS packet arrives within the liveness ceiling',
  { tag: '@contract' },
  async ({ upstream, seed, api, streamClient, baseURL }) => {
    const scenario = await upstream.scenario({
      channels: [{ id: 1, name: 'G4 TTFB', tvgId: 'g4-ttfb.e2e', logo: null }],
      rate: 20,
    });
    const proxy = await lockedProfile(api, 'Proxy');
    const { channel } = await seed.upstreamChannel(scenario, {
      channelIds: [1],
      streamProfileId: proxy.id,
    });

    const started = Date.now();
    await streamClient.open(`/proxy/ts/stream/${channel.uuid}`);
    const packet = await streamClient.readPackets(1);
    const elapsedMs = Date.now() - started;

    console.log(`[ttfb] first TS packet via ${baseURL}: ${elapsedMs}ms (ceiling ${LIVENESS_CEILING_MS}ms)`);

    expect(packet.byteLength).toBe(TS_PACKET_SIZE);
    expectTsAligned(packet);
    expect(
      elapsedMs,
      `first TS packet took ${elapsedMs}ms; ceiling is ${LIVENESS_CEILING_MS}ms`
    ).toBeLessThanOrEqual(LIVENESS_CEILING_MS);
  }
);

// The spooling detector for nginx's /proxy/ location lives in
// tests/streaming-greybox/nginx-stream-buffering.spec.ts as a static
// configuration assertion, not here. A dead-air-based behavioural attempt at
// it (armed before the channel opens, timed against Dispatcharr's own
// keep-alive packets) was tried and dropped: a from-open dead-air connection
// gates its first keep-alive behind `channel_init_grace_period` (60s
// default, `apps/proxy/config.py`), not the faster dead-air failover
// watchdog, so no ceiling under a minute could discriminate buffered nginx
// from Dispatcharr's own unrelated initialization delay. See that spec's
// header for the full trace.
