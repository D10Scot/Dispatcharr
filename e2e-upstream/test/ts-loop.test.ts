import { describe, it, expect } from 'vitest';
import {
  TS_PACKET_SIZE,
  pidOf,
  hasPayload,
  payloadOffset,
  payloadUnitStart,
  readPcrBase,
  readTimestamp,
} from '../src/ts.js';
import { LoopRewriter } from '../src/ts-loop.js';
import { makeSyntheticTs } from './helpers/synthetic-ts.js';

const PID = 0x0100;
const PACKETS = 8;
const STEP = 3600n; // 40 ms at 90 kHz
const LOOP_DURATION = STEP * BigInt(PACKETS);

function packetsOf(buffer: Buffer): Buffer[] {
  const out: Buffer[] = [];
  for (let at = 0; at < buffer.byteLength; at += TS_PACKET_SIZE) {
    out.push(buffer.subarray(at, at + TS_PACKET_SIZE));
  }
  return out;
}

/** Two loops of the same asset, pushed through one rewriter. */
function twoLoops(): Buffer[] {
  const asset = packetsOf(makeSyntheticTs({ packets: PACKETS, pid: PID, step: STEP }));
  const rewriter = new LoopRewriter(LOOP_DURATION);
  const out: Buffer[] = [];

  for (const packet of asset) out.push(rewriter.rewrite(packet));
  rewriter.advanceLoop();
  for (const packet of asset) out.push(rewriter.rewrite(packet));

  return out;
}

describe('LoopRewriter', () => {
  it('makes PTS strictly increase across the loop seam', () => {
    // The assertion that matters end to end. ffmpeg's mpegts muxer
    // regenerates CC and PCR, so through the default -c copy profile this is
    // the only decoder-free continuity evidence a test can read.
    const stamps = twoLoops()
      .filter((p) => payloadUnitStart(p) && hasPayload(p))
      .map((p) => readTimestamp(p, payloadOffset(p) + 9));

    for (let i = 1; i < stamps.length; i += 1) {
      expect(
        stamps[i] > stamps[i - 1],
        `PTS went backwards at packet ${i}: ${stamps[i - 1]} then ${stamps[i]}`
      ).toBe(true);
    }
  });

  it('makes DTS strictly increase across the loop seam', () => {
    const stamps = twoLoops()
      .filter((p) => payloadUnitStart(p) && hasPayload(p))
      .map((p) => readTimestamp(p, payloadOffset(p) + 14));

    for (let i = 1; i < stamps.length; i += 1) {
      expect(stamps[i] > stamps[i - 1]).toBe(true);
    }
  });

  it('makes PCR strictly increase across the loop seam', () => {
    const bases = twoLoops()
      .map((p) => readPcrBase(p))
      .filter((base): base is bigint => base !== null);

    for (let i = 1; i < bases.length; i += 1) {
      expect(bases[i] > bases[i - 1]).toBe(true);
    }
  });

  it('increments continuity counters by exactly one per PID, wrapping at 16', () => {
    const counters = twoLoops()
      .filter((p) => hasPayload(p) && pidOf(p) === PID)
      .map((p) => p[3] & 0x0f);

    for (let i = 1; i < counters.length; i += 1) {
      expect(counters[i]).toBe((counters[i - 1] + 1) & 0x0f);
    }
  });

  it('does not renumber null packets', () => {
    // PID 0x1FFF carries no continuity obligation. Renumbering it produces a
    // stream that fails strict analysers for no reason.
    const nullPacket = makeSyntheticTs({ packets: 1, pid: 0x1fff, step: 0n });
    const rewriter = new LoopRewriter(LOOP_DURATION);
    const before = nullPacket[3] & 0x0f;

    expect(rewriter.rewrite(nullPacket)[3] & 0x0f).toBe(before);
  });

  it('never mutates the packet it was given', () => {
    // The asset buffer is read once and shared by every connection. A
    // rewriter that mutated in place would corrupt it for everyone, and the
    // corruption would grow with each loop.
    const asset = makeSyntheticTs({ packets: 1, pid: PID, step: STEP });
    const original = Buffer.from(asset);
    const rewriter = new LoopRewriter(LOOP_DURATION);

    rewriter.advanceLoop();
    rewriter.rewrite(asset);

    expect(asset.equals(original)).toBe(true);
  });

  it('leaves the first loop byte-identical apart from continuity counters', () => {
    const asset = packetsOf(makeSyntheticTs({ packets: PACKETS, pid: PID, step: STEP }));
    const rewriter = new LoopRewriter(LOOP_DURATION);

    for (const packet of asset) {
      const rewritten = rewriter.rewrite(packet);
      // Byte 3 holds the counter; everything else is untouched at offset 0.
      expect(rewritten.subarray(0, 3).equals(packet.subarray(0, 3))).toBe(true);
      expect(rewritten.subarray(4).equals(packet.subarray(4))).toBe(true);
    }
  });
});
