import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import {
  TS_PACKET_SIZE,
  hasPayload,
  payloadOffset,
  payloadUnitStart,
  readPcrBase,
  readTimestamp,
} from './ts.js';

/**
 * Every looping TS asset a scenario channel may name (`ChannelSpec.asset`).
 * `loop` is the 60 s H.264 + AAC loop every scenario served before Phase
 * 4a-0, and stays the default. The other six are 4a-0's codec fixtures, each
 * built and shape-checked by `scripts/make-asset.sh <out> <name>` at image
 * build time; CONTRACT.md states each one's shape. `test/asset-names.test.ts`
 * holds this list, make-asset.sh's variants and the Dockerfile's build loop
 * to one set, so a name the door accepts is always a file the image has.
 */
export const ASSET_NAMES = [
  'loop',
  'mpeg2-576i-mp2',
  'h264-1080i-aac-ac3',
  'hevc-aac',
  'h264-gop10-aac',
  'h264-eac3',
  'h264-noaudio',
] as const;

export type AssetName = (typeof ASSET_NAMES)[number];

export const DEFAULT_ASSET: AssetName = 'loop';

export function isAssetName(value: unknown): value is AssetName {
  return typeof value === 'string' && (ASSET_NAMES as readonly string[]).includes(value);
}

/**
 * Where `name` lives on disk. `loop` keeps its own variable,
 * `UPSTREAM_ASSET`, which predates the others and which every existing test
 * sets; the rest are `<name>.ts` under `UPSTREAM_ASSET_DIR`. Both default to
 * the image's `/app/assets`, where the Dockerfile puts them.
 */
export function assetPath(name: AssetName, env: NodeJS.ProcessEnv = process.env): string {
  if (name === DEFAULT_ASSET) return env.UPSTREAM_ASSET ?? '/app/assets/loop.ts';
  return join(env.UPSTREAM_ASSET_DIR ?? '/app/assets', `${name}.ts`);
}

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
