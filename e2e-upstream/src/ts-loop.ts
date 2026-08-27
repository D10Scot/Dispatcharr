import {
  NULL_PID,
  TS_PACKET_SIZE,
  hasPayload,
  payloadOffset,
  payloadUnitStart,
  pidOf,
  readPcrBase,
  readTimestamp,
  writePcrBase,
  writeTimestamp,
} from './ts.js';

/** 33 bits. Everything wraps here, at ~26.5 hours for a 90 kHz clock. */
const TIMESTAMP_MASK = 0x1ffffffffn;

/**
 * Serves one asset repeatedly as a single continuous stream.
 *
 * On each wrap, PTS, DTS and PCR are shifted forward by a whole loop duration
 * so they keep advancing, and continuity counters are renumbered from the
 * rewriter's own per-PID state rather than the asset's. Counters are rewritten
 * on every packet, not only at the seam: the source is already correct within
 * a loop, so this is a no-op there, and it means continuity has exactly one
 * owner instead of two that must agree.
 *
 * The 2^33 / 90 kHz wrap (~26.5 h) is left to happen. No E2E run is remotely
 * that long, and "fixing" it would mean tracking a discontinuity the product
 * has to handle anyway.
 */
export class LoopRewriter {
  private ccByPid = new Map<number, number>();
  private offset90k = 0n;
  private loopIndex = 0;

  constructor(private readonly loopDuration90k: bigint) {}

  advanceLoop(): void {
    this.loopIndex += 1;
    this.offset90k = (this.loopDuration90k * BigInt(this.loopIndex)) & TIMESTAMP_MASK;
  }

  rewrite(packet: Buffer): Buffer {
    // A copy, always: the asset buffer is read once and shared by every
    // connection, so mutating in place would corrupt it for everyone.
    const out = Buffer.from(packet);

    this.rewriteContinuity(out);
    this.rewritePcr(out);
    this.rewriteTimestamps(out);

    return out;
  }

  private rewriteContinuity(out: Buffer): void {
    const pid = pidOf(out);
    if (pid === NULL_PID) return;
    if (!hasPayload(out)) return;

    const next = ((this.ccByPid.get(pid) ?? 15) + 1) & 0x0f;
    this.ccByPid.set(pid, next);
    out[3] = (out[3] & 0xf0) | next;
  }

  private rewritePcr(out: Buffer): void {
    const base = readPcrBase(out);
    if (base === null) return;
    writePcrBase(out, (base + this.offset90k) & TIMESTAMP_MASK);
  }

  private rewriteTimestamps(out: Buffer): void {
    if (!payloadUnitStart(out)) return;

    const start = payloadOffset(out);
    if (start < 0) return;

    // A PES packet, not a PSI section: 00 00 01 start code.
    if (start + 9 > TS_PACKET_SIZE) return;
    if (out[start] !== 0x00 || out[start + 1] !== 0x00 || out[start + 2] !== 0x01) return;

    const flags = (out[start + 7] >> 6) & 0x03;
    if (flags === 0) return;

    const ptsAt = start + 9;
    if (ptsAt + 5 > TS_PACKET_SIZE) return;
    writeTimestamp(
      out,
      ptsAt,
      (readTimestamp(out, ptsAt) + this.offset90k) & TIMESTAMP_MASK,
      out[ptsAt] >> 4
    );

    // flags === 0b11 means PTS and DTS; 0b10 means PTS alone.
    if (flags !== 0b11) return;

    const dtsAt = start + 14;
    if (dtsAt + 5 > TS_PACKET_SIZE) return;
    writeTimestamp(
      out,
      dtsAt,
      (readTimestamp(out, dtsAt) + this.offset90k) & TIMESTAMP_MASK,
      out[dtsAt] >> 4
    );
  }
}
