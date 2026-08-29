export type CatchupLayout = 'path' | 'query';

export interface CatchupRequest {
  layout: CatchupLayout;
  username: string;
  password: string;
  streamId: number;
  /** Exactly as sent, so a test can assert on the shape as well as the instant. */
  start: string;
  /** Canonical `YYYY-MM-DDTHH:MM:SS`, or null when the shape was not recognised. */
  startIso: string | null;
  durationMinutes: number;
}

/**
 * The four timestamp shapes `build_timeshift_candidate_urls` emits across its
 * seven candidates:
 *
 *   %Y-%m-%d:%H-%M      PATH candidate 0, QUERY candidate 5
 *   %Y-%m-%d_%H-%M      PATH candidate 1, QUERY candidate 3
 *   %Y-%m-%d:%H:%M:%S   PATH candidate 2, QUERY candidate 6
 *   %Y-%m-%d %H:%M:%S   QUERY candidate 4 (SQL)
 *
 * One regex covers all four: the date, then `:`/`_`/space, then the hour, then
 * `-`/`:`, then the minute, then optionally the same separator and seconds.
 */
const CATCHUP_TIMESTAMP = /^(\d{4}-\d{2}-\d{2})[:_ ](\d{2})[-:](\d{2})(?:[-:](\d{2}))?$/;

export const ACCEPTED_TIMESTAMP_SHAPES =
  '%Y-%m-%d:%H-%M, %Y-%m-%d_%H-%M, %Y-%m-%d:%H:%M:%S, %Y-%m-%d %H:%M:%S';

export function parseCatchupTimestamp(value: string): string | null {
  const match = CATCHUP_TIMESTAMP.exec(value.trim());
  if (!match) return null;
  const [, date, hour, minute, second] = match;
  return `${date}T${hour}:${minute}:${second ?? '00'}`;
}

const CATCHUP_PATH = /^\/timeshift\/([^/]+)\/([^/]+)\/([^/]+)\/([^/]+)\/(\d+)\.ts$/;

/**
 * `decodeURIComponent` throws `URIError` on a malformed percent-escape (a
 * lone `%` or `%ZZ`). The `/live/` and `/movie|series/` routes already hit
 * this once each — a hand-built test URL with a bad escape 500ing with no
 * log entry, fixed by naming the offending field instead. Same shape here:
 * three path segments (`username`, `password`, `start`) go through
 * `decodeURIComponent`, so the same guard applies to all three. Thrown, not
 * swallowed to `undefined` — a malformed escape is a scenario author's typo
 * on an otherwise-matching catch-up path, not "this isn't a catch-up
 * request", so it must not silently fall through to the generic 404.
 */
export class CatchupDecodeError extends Error {
  constructor(
    public readonly field: string,
    public readonly value: string
  ) {
    super(`'${field}' path segment '${value}' is not validly percent-encoded`);
  }
}

function decodeField(field: string, raw: string): string {
  try {
    return decodeURIComponent(raw);
  } catch {
    throw new CatchupDecodeError(field, raw);
  }
}

export function parseCatchupPath(subPath: string): CatchupRequest | undefined {
  const match = CATCHUP_PATH.exec(subPath);
  if (!match) return undefined;
  const [, rawUsername, rawPassword, duration, rawStart, streamId] = match;
  const username = decodeField('username', rawUsername);
  const password = decodeField('password', rawPassword);
  const start = decodeField('start', rawStart);
  return {
    layout: 'path',
    username,
    password,
    streamId: Number(streamId),
    start,
    startIso: parseCatchupTimestamp(start),
    durationMinutes: Number(duration),
  };
}

export function parseCatchupQuery(url: URL): CatchupRequest | undefined {
  const username = url.searchParams.get('username');
  const password = url.searchParams.get('password');
  const stream = url.searchParams.get('stream');
  const start = url.searchParams.get('start');
  if (username === null || password === null || stream === null || start === null) {
    return undefined;
  }
  return {
    layout: 'query',
    username,
    password,
    // `Number('')` is `0`, not `NaN` — an empty `?stream=` would otherwise
    // match a scenario channel with `id: 0` instead of resolving to no
    // channel at all. `router.ts`'s `parseRequiredId` guards the same
    // hazard for `vod_id`/`series_id`; inlined here (not imported) because
    // `router.ts` imports from this module, and the reverse import would be
    // a cycle. Not reachable from Dispatcharr, which always interpolates a
    // real `stream_id`, but the PATH layout's `(\d+)` already excludes it
    // for free, so QUERY shouldn't be the odd one out.
    streamId: /^\d+$/.test(stream) ? Number(stream) : NaN,
    start,
    startIso: parseCatchupTimestamp(start),
    durationMinutes: Number(url.searchParams.get('duration') ?? '0'),
  };
}
