import { readFileSync } from 'node:fs';
import type { ServerResponse } from 'node:http';

export interface FiniteAsset {
  bytes: Buffer;
  contentType: string;
}

export type RangeResult =
  | { kind: 'full' }
  | { kind: 'partial'; start: number; end: number }
  | { kind: 'unsatisfiable' };

const SINGLE_BYTE_RANGE = /^bytes=(\d*)-(\d*)$/;

/**
 * Parses a single `bytes=` range against a known length.
 *
 * Anything this does not understand — another unit, a multi-range header, a
 * bare `bytes=-` — returns `full`, per RFC 9110's "ignore a Range you cannot
 * satisfy". Answering 416 to a multi-range request would be a *fault*, and
 * this provider models faults explicitly rather than by accident; Dispatcharr
 * never sends a multi-range request either way.
 */
export function parseRange(header: string | undefined, length: number): RangeResult {
  if (!header) return { kind: 'full' };
  const match = SINGLE_BYTE_RANGE.exec(header.trim());
  if (!match) return { kind: 'full' };

  const [, rawStart, rawEnd] = match;
  if (rawStart === '' && rawEnd === '') return { kind: 'full' };

  if (rawStart === '') {
    const suffix = Number(rawEnd);
    // `bytes=-0` asks for the last zero bytes, which is unsatisfiable rather
    // than empty — and is the one suffix case a naive `length - suffix`
    // silently turns into "the whole file".
    if (suffix === 0) return { kind: 'unsatisfiable' };
    return { kind: 'partial', start: Math.max(0, length - suffix), end: length - 1 };
  }

  const start = Number(rawStart);
  if (start >= length) return { kind: 'unsatisfiable' };
  const end = rawEnd === '' ? length - 1 : Math.min(Number(rawEnd), length - 1);
  if (end < start) return { kind: 'unsatisfiable' };
  return { kind: 'partial', start, end };
}

export function loadFiniteAsset(path: string, contentType: string): FiniteAsset {
  return { bytes: readFileSync(path), contentType };
}

export interface ServeOptions {
  rangeHeader?: string;
  /** Set by the `range-unsupported` fault: answer 200 with the whole body, no Accept-Ranges. */
  ignoreRange?: boolean;
  head?: boolean;
}

/**
 * Serves a finite asset, honouring Range. Returns the status sent, so the
 * caller logs what actually happened rather than what it intended.
 *
 * `Accept-Ranges` and `Content-Length` are not cosmetic here:
 * `apps/proxy/vod_proxy/multi_worker_connection_manager.py` learns the file
 * size from `Content-Range`, falling back to `Content-Length`, and emits
 * `Accept-Ranges`/`Content-Range` to its own client only once it knows that
 * size. A provider without them produces a VOD response with no seek
 * metadata at all — which is exactly what `streamLoop`'s endless asset does,
 * deliberately, and exactly what this asset exists to stop doing.
 */
export function serveFiniteAsset(
  res: ServerResponse,
  asset: FiniteAsset,
  options: ServeOptions = {}
): number {
  const length = asset.bytes.byteLength;
  const range = options.ignoreRange
    ? ({ kind: 'full' } as const)
    : parseRange(options.rangeHeader, length);

  if (range.kind === 'unsatisfiable') {
    // No Content-Type on the 416 branch: this is what the brief specifies,
    // and stream_vod (apps/proxy/vod_proxy) infers its client-facing
    // Content-Type from the provider's response only when one is present, so
    // omitting it here is a deliberate part of the fixture rather than an
    // oversight.
    res.writeHead(416, { 'Content-Range': `bytes */${length}`, 'Content-Length': 0 });
    res.end();
    return 416;
  }

  if (range.kind === 'partial') {
    const body = asset.bytes.subarray(range.start, range.end + 1);
    res.writeHead(206, {
      'Content-Type': asset.contentType,
      'Content-Length': body.byteLength,
      'Content-Range': `bytes ${range.start}-${range.end}/${length}`,
      'Accept-Ranges': 'bytes',
    });
    if (options.head) res.end();
    else res.end(body);
    return 206;
  }

  res.writeHead(200, {
    'Content-Type': asset.contentType,
    'Content-Length': length,
    // Omitted under `ignoreRange`: a provider that will not serve 206 does
    // not advertise that it will.
    ...(options.ignoreRange ? {} : { 'Accept-Ranges': 'bytes' }),
  });
  if (options.head) res.end();
  else res.end(asset.bytes);
  return 200;
}
