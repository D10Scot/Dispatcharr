import { readFileSync } from 'node:fs';
import {
  TS_PACKET_SIZE,
  hasPayload,
  payloadOffset,
  payloadUnitStart,
  readPcrBase,
  readTimestamp,
} from './ts.js';

export interface LoadedAsset {
  bytes: Buffer;
  loopDuration90k: bigint;
  durationSeconds: number;
  /** Bytes per second at rate 1 — what pacing multiplies. */
  byteRate: number;
}

/**
 * Derives the loop duration from the asset itself rather than trusting a
 * configured value. `make-asset.sh` builds with an unpinned ffmpeg, so the
 * packet count and duration can drift between rebuilds; measuring at load
 * time removes the chance of the build script and the server disagreeing,
 * and a duration that is too short makes the seam jump backwards, which
 * breaks the one property every streaming test depends on.
 *
 * The result is the observed span plus one average sample interval, so the
 * next loop's first timestamp lands strictly after this loop's last.
 */
export function measureLoop(bytes: Buffer): {
  loopDuration90k: bigint;
  durationSeconds: number;
} {
  if (bytes.byteLength % TS_PACKET_SIZE !== 0) {
    throw new Error(
      `asset is ${bytes.byteLength} bytes, not a whole number of 188-byte TS packets`
    );
  }

  const stamps: bigint[] = [];

  for (let at = 0; at < bytes.byteLength; at += TS_PACKET_SIZE) {
    const packet = bytes.subarray(at, at + TS_PACKET_SIZE);

    const pcr = readPcrBase(packet);
    if (pcr !== null) stamps.push(pcr);

    if (!payloadUnitStart(packet) || !hasPayload(packet)) continue;
    const start = payloadOffset(packet);
    if (start < 0 || start + 14 > TS_PACKET_SIZE) continue;
    if (packet[start] !== 0x00 || packet[start + 1] !== 0x00 || packet[start + 2] !== 0x01) {
      continue;
    }
    if (((packet[start + 7] >> 6) & 0x03) === 0) continue;
    stamps.push(readTimestamp(packet, start + 9));
  }

  if (stamps.length < 2) {
    throw new Error('asset carries no timestamps; it cannot be looped continuously');
  }

  let min = stamps[0];
  let max = stamps[0];
  for (const stamp of stamps) {
    if (stamp < min) min = stamp;
    if (stamp > max) max = stamp;
  }

  const span = max - min;
  // BigInt division truncates, so a sample count exceeding the span in
  // ticks would otherwise yield 0n here, making loopDuration90k === span
  // instead of strictly greater — the seam would stop advancing. Not
  // reachable with the real ~60s asset, but every consumer downstream
  // trusts this value to be positive, so it's floored rather than left as
  // a landmine.
  const step = span / BigInt(stamps.length - 1) || 1n;
  const loopDuration90k = span + step;

  return {
    loopDuration90k,
    durationSeconds: Number(loopDuration90k) / 90_000,
  };
}

export function loadAsset(path: string): LoadedAsset {
  const bytes = readFileSync(path);
  const { loopDuration90k, durationSeconds } = measureLoop(bytes);

  return {
    bytes,
    loopDuration90k,
    durationSeconds,
    byteRate: bytes.byteLength / durationSeconds,
  };
}
