import { test, expect, expectTsAligned, TS_PACKET_SIZE } from '../../fixtures';
import { lockedProfile } from './helpers';

/**
 * Time to first byte through nginx (Phase 1 PR 2).
 *
 * nginx's `/proxy/` location runs with `uwsgi_buffering off` (docker/nginx.conf,
 * CLAUDE.md § Architecture) specifically so a live TS response streams
 * straight through instead of being spooled to disk first.
 *
 * N = 10s is the CHOSEN ceiling, not a measurement: it's the spec's own
 * spooling-detection threshold (docs/superpowers/specs/2026-09-04-phase1-
 * process-split-design.md, PR 2), not a characterisation of normal
 * latency. Past it the assertion stops telling a live stream apart from
 * nginx spooling the whole response to disk before forwarding it, which is
 * the only failure this test exists to catch — a tighter N would buy
 * nothing that failure mode needs, since real TTFB (logged below) sits
 * nowhere near the ceiling. It must exist before PR 4 changes any nginx
 * routing and keep passing after it — nothing about this assertion depends
 * on which process answers the request.
 *
 * The measured elapsed time is logged unconditionally below; the
 * implementing PR copies that number, plus this 10s ceiling, into its
 * description per the spec's own instruction.
 */
const TTFB_CEILING_MS = 10_000;

test(
  'the first TS packet through nginx arrives within the TTFB ceiling',
  { tag: '@contract' },
  async ({ upstream, seed, api, streamClient }) => {
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

    console.log(`[ttfb] first TS packet through nginx (:9191): ${elapsedMs}ms (ceiling ${TTFB_CEILING_MS}ms)`);

    expect(packet.byteLength).toBe(TS_PACKET_SIZE);
    expectTsAligned(packet);
    expect(
      elapsedMs,
      `first TS packet took ${elapsedMs}ms through nginx; ceiling is ${TTFB_CEILING_MS}ms`
    ).toBeLessThanOrEqual(TTFB_CEILING_MS);
  }
);
