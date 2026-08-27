import { test, expect, expectTsAligned, TS_PACKET_SIZE } from '../../fixtures';

// Exemplar: byte-level assertions against an endless stream. Playwright's
// request fixture cannot do this — APIResponse.body() awaits full download
// and a live stream never finishes.
//
// This test exercises streamClient's own semantics, not Dispatcharr's proxy,
// so it hits the provider directly through `control` rather than routing
// through the product.

test('streamClient reads aligned TS packets from an endless stream', async ({
  upstream,
  streamClient,
}) => {
  const scenario = await upstream.scenario({ channels: 1, rate: 20 });

  // rate 20 so the test does not wait real time for real bitrate. Only a
  // test asserting on ffmpeg's speed= needs rate 1.
  await streamClient.open(upstream.toControl(upstream.streamUrl(scenario, 1)));

  const packets = await streamClient.readPackets(20);
  expect(packets.byteLength).toBe(20 * TS_PACKET_SIZE);
  expectTsAligned(packets);

  const collected = await streamClient.collectFor(1_000);
  expect(collected.byteLength).toBeGreaterThan(0);
});
