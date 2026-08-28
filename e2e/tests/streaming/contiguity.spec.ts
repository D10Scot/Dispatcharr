import { test, expect } from '@playwright/test';
import { expectContiguous, videoPidOf, TS_PACKET_SIZE } from '../../fixtures';

/** Build `count` TS packets on `pid` with continuity counters from `startCc`. */
function synth(pid: number, count: number, startCc = 0, skipAt = -1): Buffer {
  const out = Buffer.alloc(count * TS_PACKET_SIZE);
  let cc = startCc;
  for (let i = 0; i < count; i++) {
    const off = i * TS_PACKET_SIZE;
    out[off] = 0x47;
    out[off + 1] = (pid >> 8) & 0x1f;
    out[off + 2] = pid & 0xff;
    if (i === skipAt) cc = (cc + 1) & 0x0f; // drop one, simulating a lost packet
    out[off + 3] = 0x10 | (cc & 0x0f); // payload only, no adaptation field
    cc = (cc + 1) & 0x0f;
  }
  return out;
}

test('expectContiguous accepts an unbroken counter run', () => {
  expect(() => expectContiguous(synth(0x0100, 40), 0x0100)).not.toThrow();
});

test('expectContiguous accepts a counter that wraps past 15', () => {
  expect(() => expectContiguous(synth(0x0100, 40, 13), 0x0100)).not.toThrow();
});

test('expectContiguous rejects a gap in the counter', () => {
  expect(() => expectContiguous(synth(0x0100, 40, 0, 20), 0x0100)).toThrow(
    /continuity/i
  );
});

test('videoPidOf picks the busiest non-null PID', () => {
  const mixed = Buffer.concat([synth(0x0100, 30), synth(0x1fff, 5)]);
  expect(videoPidOf(mixed)).toBe(0x0100);
});
