/**
 * Parsers for the live HLS output's wire formats (Phase 4a-1b): the
 * multivariant and media playlists, and the ISO BMFF boxes of an init segment
 * and a media segment. Deliberately SHALLOW, like `parse.ts`: they read what
 * the `streaming` project's HLS specs assert on, and are not validators.
 *
 * Import from here directly (`../../fixtures/hls`); the harness index does not
 * re-export them, because only the HLS specs read them.
 */

import type { APIRequestContext } from '@playwright/test';

/**
 * `v1.<sid>.<mac>`: a 22-character base64url session id and a 43-character
 * base64url HMAC, 69 characters in all (spec § The media-session token).
 */
export const MEDIA_SESSION_TOKEN_RE = /^v1\.[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43}$/;

/* ------------------------------------------------------------------------ *
 * Playlists
 * ------------------------------------------------------------------------ */

/** An attribute list: `KEY=VALUE,KEY="quoted, value"`. Quotes are stripped. */
export function parseAttributes(list: string): Record<string, string> {
  const out: Record<string, string> = {};
  const pattern = /([A-Z0-9-]+)=("([^"]*)"|[^,]*)/g;
  for (let match = pattern.exec(list); match; match = pattern.exec(list)) {
    out[match[1]] = match[3] !== undefined ? match[3] : match[2];
  }
  return out;
}

export interface MultivariantMedia {
  groupId: string;
  name: string;
  channels: string | undefined;
  uri: string;
  attributes: Record<string, string>;
}

export interface MultivariantVariant {
  bandwidth: number;
  codecs: string;
  resolution: string | undefined;
  frameRate: string | undefined;
  audio: string | undefined;
  uri: string;
  attributes: Record<string, string>;
}

export interface Multivariant {
  media: MultivariantMedia[];
  variants: MultivariantVariant[];
  /** Every URI the playlist names, in document order. */
  uris: string[];
  text: string;
}

export function parseMultivariant(text: string): Multivariant {
  const lines = text.split(/\r?\n/);
  const media: MultivariantMedia[] = [];
  const variants: MultivariantVariant[] = [];
  const uris: string[] = [];
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (line.startsWith('#EXT-X-MEDIA:')) {
      const attributes = parseAttributes(line.slice('#EXT-X-MEDIA:'.length));
      media.push({
        groupId: attributes['GROUP-ID'] ?? '',
        name: attributes['NAME'] ?? '',
        channels: attributes['CHANNELS'],
        uri: attributes['URI'] ?? '',
        attributes,
      });
      if (attributes['URI']) uris.push(attributes['URI']);
    } else if (line.startsWith('#EXT-X-STREAM-INF:')) {
      const attributes = parseAttributes(line.slice('#EXT-X-STREAM-INF:'.length));
      const uri = lines[i + 1] ?? '';
      variants.push({
        bandwidth: Number(attributes['BANDWIDTH'] ?? '0'),
        codecs: attributes['CODECS'] ?? '',
        resolution: attributes['RESOLUTION'],
        frameRate: attributes['FRAME-RATE'],
        audio: attributes['AUDIO'],
        uri,
        attributes,
      });
      uris.push(uri);
    }
  }
  return { media, variants, uris, text };
}

/** The session token in a multivariant's URIs: `/hls/<token>/...`. */
export function tokenOf(multivariant: Multivariant): string {
  for (const uri of multivariant.uris) {
    const match = /^\/hls\/([^/]+)\//.exec(uri);
    if (match) return match[1];
  }
  throw new Error(`the multivariant names no /hls/<token>/ URI:\n${multivariant.text}`);
}

export interface MediaSegment {
  uri: string;
  seq: number;
  duration: number;
  programDateTime: string | undefined;
  discontinuity: boolean;
  /** The EXT-X-MAP URI in force for this segment. */
  map: string | undefined;
}

export interface MediaPlaylist {
  version: number | undefined;
  targetDuration: number | undefined;
  mediaSequence: number;
  discontinuitySequence: number;
  independentSegments: boolean;
  endlist: boolean;
  segments: MediaSegment[];
  text: string;
}

export function parseMediaPlaylist(text: string): MediaPlaylist {
  const lines = text.split(/\r?\n/);
  const playlist: MediaPlaylist = {
    version: undefined,
    targetDuration: undefined,
    mediaSequence: 0,
    discontinuitySequence: 0,
    independentSegments: false,
    endlist: false,
    segments: [],
    text,
  };
  let map: string | undefined;
  let pdt: string | undefined;
  let duration = 0;
  let discontinuity = false;
  for (const line of lines) {
    if (line.startsWith('#EXT-X-VERSION:')) playlist.version = Number(line.split(':')[1]);
    else if (line.startsWith('#EXT-X-TARGETDURATION:')) playlist.targetDuration = Number(line.split(':')[1]);
    else if (line.startsWith('#EXT-X-MEDIA-SEQUENCE:')) playlist.mediaSequence = Number(line.split(':')[1]);
    else if (line.startsWith('#EXT-X-DISCONTINUITY-SEQUENCE:')) playlist.discontinuitySequence = Number(line.split(':')[1]);
    else if (line === '#EXT-X-INDEPENDENT-SEGMENTS') playlist.independentSegments = true;
    else if (line === '#EXT-X-ENDLIST') playlist.endlist = true;
    else if (line === '#EXT-X-DISCONTINUITY') discontinuity = true;
    else if (line.startsWith('#EXT-X-MAP:')) map = parseAttributes(line.slice('#EXT-X-MAP:'.length))['URI'];
    else if (line.startsWith('#EXT-X-PROGRAM-DATE-TIME:')) pdt = line.slice('#EXT-X-PROGRAM-DATE-TIME:'.length);
    else if (line.startsWith('#EXTINF:')) duration = Number(line.slice('#EXTINF:'.length).split(',')[0]);
    else if (line !== '' && !line.startsWith('#')) {
      playlist.segments.push({
        uri: line,
        seq: playlist.mediaSequence + playlist.segments.length,
        duration,
        programDateTime: pdt,
        discontinuity,
        map,
      });
      pdt = undefined;
      discontinuity = false;
    }
  }
  return playlist;
}

/* ------------------------------------------------------------------------ *
 * ISO BMFF
 * ------------------------------------------------------------------------ */

export interface Box {
  type: string;
  offset: number;
  size: number;
}

function readBoxes(buffer: Buffer, start = 0, end = buffer.length): Box[] {
  const boxes: Box[] = [];
  let offset = start;
  while (offset + 8 <= end) {
    let size = buffer.readUInt32BE(offset);
    const type = buffer.toString('latin1', offset + 4, offset + 8);
    if (size === 0) size = end - offset;
    if (size < 8 || offset + size > end) {
      throw new Error(`a box "${type}" at ${offset} claims ${size} bytes in a ${end}-byte range`);
    }
    boxes.push({ type, offset, size });
    offset += size;
  }
  return boxes;
}

/** The top-level boxes of an init or media segment, in order. */
export function topLevelBoxes(buffer: Buffer): string[] {
  return readBoxes(buffer).map((box) => box.type);
}

function child(buffer: Buffer, parent: Box, type: string, headerBytes = 8): Box | undefined {
  return readBoxes(buffer, parent.offset + headerBytes, parent.offset + parent.size).find((b) => b.type === type);
}

function required(box: Box | undefined, what: string): Box {
  if (!box) throw new Error(`no ${what} box`);
  return box;
}

export interface InitSummary {
  /** `vide` or `soun`. */
  handler: string;
  timescale: number;
  trackId: number;
  /** Whether the track carries an edit list, which a served init must not. */
  hasEdts: boolean;
  /** The movie-extends default sample duration (trex), for fragments that leave it implicit. */
  defaultSampleDuration: number;
  /**
   * The video track's RFC 6381 codec string, read from the sample entry's
   * `avcC` (`avc1.` plus the profile, constraint and level bytes in hex) or
   * `hvcC` (`hvc1.<space+profile>.<compat>.<tier+level>.<constraints>`);
   * empty for a track that is neither.
   */
  codec: string;
}

/** The sample entry inside a track's stsd: `moov/trak/mdia/minf/stbl/stsd/<entry>`. */
function sampleEntry(buffer: Buffer, mdia: Box): Box | undefined {
  const minf = child(buffer, mdia, 'minf');
  const stbl = minf ? child(buffer, minf, 'stbl') : undefined;
  const stsd = stbl ? child(buffer, stbl, 'stsd') : undefined;
  if (!stsd) return undefined;
  // stsd is a FullBox (4) plus an entry count (4) after its 8-byte header.
  return readBoxes(buffer, stsd.offset + 16, stsd.offset + stsd.size)[0];
}

function videoCodec(buffer: Buffer, mdia: Box): string {
  const entry = sampleEntry(buffer, mdia);
  if (!entry) return '';
  // A VisualSampleEntry: 8-byte box header, 78 bytes of fixed fields, then child boxes.
  const avcC = child(buffer, entry, 'avcC', 86);
  if (avcC) {
    const hex = (i: number) => buffer.readUInt8(avcC.offset + 8 + i).toString(16).padStart(2, '0');
    return `${entry.type === 'avc3' ? 'avc3' : 'avc1'}.${hex(1)}${hex(2)}${hex(3)}`;
  }
  const hvcC = child(buffer, entry, 'hvcC', 86);
  if (hvcC) {
    const at = hvcC.offset + 8;
    const b1 = buffer.readUInt8(at + 1);
    const space = ['', 'A', 'B', 'C'][b1 >> 6];
    const profile = b1 & 0x1f;
    // The 32 profile-compatibility flags, bit-reversed, as hex without leading zeros.
    let compat = buffer.readUInt32BE(at + 2);
    let reversed = 0;
    for (let i = 0; i < 32; i++) {
      reversed = (reversed << 1) | (compat & 1);
      compat >>>= 1;
    }
    const tier = (b1 & 0x20) === 0 ? 'L' : 'H';
    const level = buffer.readUInt8(at + 12);
    const constraints = [...buffer.subarray(at + 6, at + 12)];
    while (constraints.length > 0 && constraints[constraints.length - 1] === 0) constraints.pop();
    const tail = constraints.map((c) => `.${c.toString(16).toUpperCase()}`).join('');
    return `hvc1.${space}${profile}.${(reversed >>> 0).toString(16).toUpperCase()}.${tier}${level}${tail}`;
  }
  return '';
}

export function initSummary(buffer: Buffer): InitSummary {
  const moov = required(readBoxes(buffer).find((b) => b.type === 'moov'), 'moov');
  const trak = required(child(buffer, moov, 'trak'), 'trak');
  const mdia = required(child(buffer, trak, 'mdia'), 'mdia');
  const mdhd = required(child(buffer, mdia, 'mdhd'), 'mdhd');
  const hdlr = required(child(buffer, mdia, 'hdlr'), 'hdlr');
  const version = buffer.readUInt8(mdhd.offset + 8);
  const timescale = buffer.readUInt32BE(mdhd.offset + 8 + (version === 1 ? 20 : 12));
  const handler = buffer.toString('latin1', hdlr.offset + 16, hdlr.offset + 20);

  const tkhd = required(child(buffer, trak, 'tkhd'), 'tkhd');
  const trackId = buffer.readUInt32BE(tkhd.offset + 8 + (buffer.readUInt8(tkhd.offset + 8) === 1 ? 20 : 12));

  let defaultSampleDuration = 0;
  const mvex = child(buffer, moov, 'mvex');
  const trex = mvex ? child(buffer, mvex, 'trex') : undefined;
  if (trex) defaultSampleDuration = buffer.readUInt32BE(trex.offset + 8 + 12);

  return {
    handler,
    timescale,
    trackId,
    hasEdts: child(buffer, trak, 'edts') !== undefined,
    defaultSampleDuration,
    codec: handler === 'vide' ? videoCodec(buffer, mdia) : '',
  };
}

export interface FragmentTiming {
  /** The first sample's decode time, in ticks of the track's timescale. */
  tfdt: number;
  /** One duration per sample, in ticks. */
  durations: number[];
}

/**
 * The `tfdt` and the sample durations of the first `moof` in a media segment,
 * falling back to the `tfhd` default and then the init's `trex` default for a
 * `trun` that leaves durations implicit.
 */
export function fragmentTiming(buffer: Buffer, init: InitSummary): FragmentTiming {
  const moof = required(readBoxes(buffer).find((b) => b.type === 'moof'), 'moof');
  const traf = required(child(buffer, moof, 'traf'), 'traf');
  const tfhd = required(child(buffer, traf, 'tfhd'), 'tfhd');
  const tfdt = required(child(buffer, traf, 'tfdt'), 'tfdt');
  const trun = required(child(buffer, traf, 'trun'), 'trun');

  const tfhdFlags = buffer.readUIntBE(tfhd.offset + 9, 3);
  let cursor = tfhd.offset + 16; // header, version+flags, track_ID
  if (tfhdFlags & 0x000001) cursor += 8;
  if (tfhdFlags & 0x000002) cursor += 4;
  const tfhdDuration = tfhdFlags & 0x000008 ? buffer.readUInt32BE(cursor) : undefined;

  const tfdtVersion = buffer.readUInt8(tfdt.offset + 8);
  const decodeTime =
    tfdtVersion === 1
      ? Number(buffer.readBigUInt64BE(tfdt.offset + 12))
      : buffer.readUInt32BE(tfdt.offset + 12);

  const trunFlags = buffer.readUIntBE(trun.offset + 9, 3);
  const count = buffer.readUInt32BE(trun.offset + 12);
  cursor = trun.offset + 16;
  if (trunFlags & 0x000001) cursor += 4;
  if (trunFlags & 0x000004) cursor += 4;
  const durations: number[] = [];
  for (let i = 0; i < count; i++) {
    let duration = tfhdDuration ?? init.defaultSampleDuration;
    if (trunFlags & 0x000100) {
      duration = buffer.readUInt32BE(cursor);
      cursor += 4;
    }
    if (trunFlags & 0x000200) cursor += 4;
    if (trunFlags & 0x000400) cursor += 4;
    if (trunFlags & 0x000800) cursor += 4;
    durations.push(duration);
  }
  return { tfdt: decodeTime, durations };
}

/* ------------------------------------------------------------------------ *
 * Requests
 * ------------------------------------------------------------------------ */

export interface HlsEntry {
  status: number;
  headers: Record<string, string>;
  multivariant: Multivariant;
  token: string;
}

/**
 * The entry request's own timeout, derived as the browser player's is
 * (frontend/src/utils/components/FloatingVideoUtils.js, HLS_ENTRY_TIMEOUT_MS):
 * the relay's next-source budget (14.1 s, relay/httpapi/stream.go's tuneBudget)
 * plus its entry wait (58 s: hls.SourceStartWait 15 s + the 43 s cold start,
 * issue #560) plus a 7.9 s margin, so a slow entry fails as the relay's own
 * 503 rather than as a request timeout. Under nginx's 300 s on the tune
 * locations.
 */
const ENTRY_TIMEOUT_MS = 14_100 + 58_000 + 7_900;

/**
 * An HLS tune: `path` is any of the three entry forms. Requires a 200 and
 * returns the parsed multivariant and its session token. A 503 (the relay's
 * own 58 s wait for the encoder's init segments ran out) is an error here,
 * not retried: a viewer's first tune failing is a finding, not noise.
 */
export async function enterHls(request: APIRequestContext, path: string): Promise<HlsEntry> {
  const response = await request.get(path, { timeout: ENTRY_TIMEOUT_MS });
  const text = await response.text();
  if (response.status() !== 200) {
    throw new Error(`an HLS entry at ${path} answered ${response.status()}, want 200: ${text.slice(0, 300)}`);
  }
  const multivariant = parseMultivariant(text);
  return {
    status: response.status(),
    headers: response.headers(),
    multivariant,
    token: tokenOf(multivariant),
  };
}

/** `DELETE /hls/<token>`: the explicit leave. Never throws on a refusal. */
export async function leaveHls(request: APIRequestContext, token: string): Promise<number> {
  const response = await request.delete(`/hls/${token}`);
  return response.status();
}

/**
 * Polls a rendition's media playlist until it lists at least `min` segments.
 * A 503 (no first segment yet) is retried; any other non-200 is an error.
 */
export async function waitForSegments(
  request: APIRequestContext,
  token: string,
  rendition: string,
  min: number,
  timeoutMs: number
): Promise<MediaPlaylist> {
  const deadline = Date.now() + timeoutMs;
  let last = 'no answer';
  while (Date.now() < deadline) {
    const response = await request.get(`/hls/${token}/${rendition}.m3u8`, { timeout: 30_000 });
    if (response.status() === 200) {
      const playlist = parseMediaPlaylist(await response.text());
      if (playlist.segments.length >= min) return playlist;
      last = `${playlist.segments.length} segments listed`;
    } else if (response.status() === 503) {
      last = '503';
    } else {
      throw new Error(`${rendition}.m3u8 answered ${response.status()}: ${(await response.text()).slice(0, 300)}`);
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`the ${rendition} playlist never listed ${min} segments within ${timeoutMs}ms (${last})`);
}
