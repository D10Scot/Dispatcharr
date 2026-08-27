import { describe, it, expect } from 'vitest';
import { measureLoop } from '../src/asset.js';
import { makeSyntheticTs } from './helpers/synthetic-ts.js';

const STEP = 3600n; // 40 ms at 90 kHz
const PACKETS = 10;

// makeSyntheticTs emits a PTS on every packet but a PCR only every fourth
// (index % 4 === 0 → indices 0, 4, 8 for PACKETS=10), so measureLoop sees 13
// stamps, not 2 * PACKETS or PACKETS. Pinned by direct computation rather
// than asserted as a round number:
//   PTS values:  0, 3600, ..., 32400            (10 samples)
//   PCR values:  0, 14400, 28800                (3 samples, duplicates of PTS)
//   span  = max - min                = 32400
//   step  = span / (13 - 1)          = 2700
//   total = span + step              = 35100
const EXPECTED_LOOP_DURATION_90K = 35100n;
const EXPECTED_DURATION_SECONDS = 0.39;

describe('measureLoop', () => {
  it('reports a duration one step longer than the span between first and last timestamp', () => {
    // Strictly longer than the span, or the next loop's first timestamp
    // equals this loop's last and PTS stops strictly increasing — which is
    // exactly the discontinuity the seam rewriter exists to prevent.
    const bytes = makeSyntheticTs({ packets: PACKETS, pid: 0x0100, step: STEP });
    const { loopDuration90k } = measureLoop(bytes);

    expect(loopDuration90k).toBe(EXPECTED_LOOP_DURATION_90K);
  });

  it('converts the duration to seconds against the 90 kHz clock', () => {
    const bytes = makeSyntheticTs({ packets: PACKETS, pid: 0x0100, step: STEP });
    expect(measureLoop(bytes).durationSeconds).toBeCloseTo(EXPECTED_DURATION_SECONDS, 5);
  });

  it('throws by name on a buffer that is not a whole number of packets', () => {
    const bytes = makeSyntheticTs({ packets: 2, pid: 0x0100, step: STEP }).subarray(0, 300);
    expect(() => measureLoop(bytes)).toThrow(/188/);
  });

  it('throws by name when no timestamps are present at all', () => {
    // An asset with no PTS and no PCR cannot be looped continuously, and
    // failing at load is far better than emitting a stream whose seam
    // silently jumps backwards.
    const bytes = Buffer.alloc(188 * 4, 0xff);
    for (let at = 0; at < bytes.byteLength; at += 188) {
      bytes[at] = 0x47;
      bytes[at + 3] = 0x10; // payload only, no adaptation field, no PES
    }
    expect(() => measureLoop(bytes)).toThrow(/no timestamps/i);
  });
});
