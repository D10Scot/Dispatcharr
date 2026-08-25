import { test, expect, expectTsAligned } from '../../fixtures';
import { startStaticUpstream } from '../../support/static-upstream';

// Exemplar: byte-level assertions against an endless stream. Playwright's
// request fixture cannot do this — APIResponse.body() awaits full download
// and a live stream never finishes.
//
// The upstream here is throwaway scaffolding, replaced by G2's fake provider.
// Base port for the throwaway upstream. The worker index is added to it: this
// project runs more than one worker, and a second spec copying this exemplar —
// which is what an exemplar is for — would otherwise collide on the port about
// half the time. startStaticUpstream fails fast on a conflict rather than
// silently reading the other worker's stream, but a hard failure is still a
// failure. Derive the port; never hardcode one.
const UPSTREAM_BASE_PORT = 9401;

test('streamClient reads aligned TS packets from an endless stream', async ({
  streamClient,
}, testInfo) => {
  const upstream = await startStaticUpstream(
    UPSTREAM_BASE_PORT + testInfo.workerIndex
  );

  try {
    await streamClient.open(`${upstream.url}/loop.ts`);

    const packets = await streamClient.readPackets(20);
    expect(packets.length).toBe(20 * 188);
    expectTsAligned(packets);

    const collected = await streamClient.collectFor(1_000);
    expect(collected.byteLength).toBeGreaterThan(0);
  } finally {
    await streamClient.close();
    await upstream.close();
  }
});
