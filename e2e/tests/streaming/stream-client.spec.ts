import { test, expect, expectTsAligned } from '../../fixtures';
import { startStaticUpstream } from '../../support/static-upstream';

// Exemplar: byte-level assertions against an endless stream. Playwright's
// request fixture cannot do this — APIResponse.body() awaits full download
// and a live stream never finishes.
//
// The upstream here is throwaway scaffolding, replaced by G2's fake provider.
test('streamClient reads aligned TS packets from an endless stream', async ({
  streamClient,
}) => {
  const upstream = await startStaticUpstream(9401);

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
