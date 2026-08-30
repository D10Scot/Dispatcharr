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
 * seven candidates (verified at `apps/timeshift/helpers.py:485-488`):
 *
 *   %Y-%m-%d:%H-%M      PATH candidate 0, QUERY candidate 5
 *   %Y-%m-%d_%H-%M      PATH candidate 1, QUERY candidate 3
 *   %Y-%m-%d:%H:%M:%S   PATH candidate 2, QUERY candidate 6
 *   %Y-%m-%d %H:%M:%S   QUERY candidate 4 (SQL)
 *
 * The date separator, the time separator, and whether seconds are present
 * look like three independent choices, but they are not — only these four
 * combinations occur. A single regex that varied all three independently
 * would accept 12 shapes, eight of which no candidate builder ever emits
 * (e.g. `2026-08-29_14:00` or `2026-08-29 14-00`). That laxity would be a
 * silent regression: a future change to `build_timeshift_candidate_urls`
 * that emitted one of those hybrid shapes would be accepted here and the
 * test built on this parser would keep passing instead of catching it. So
 * each shape gets its own regex, tried in order, rather than one permissive
 * pattern.
 */
const CATCHUP_TIMESTAMP_SHAPES: RegExp[] = [
  /^(\d{4}-\d{2}-\d{2}):(\d{2})-(\d{2})$/, // %Y-%m-%d:%H-%M
  /^(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})$/, // %Y-%m-%d_%H-%M
  /^(\d{4}-\d{2}-\d{2}):(\d{2}):(\d{2}):(\d{2})$/, // %Y-%m-%d:%H:%M:%S
  /^(\d{4}-\d{2}-\d{2}) (\d{2}):(\d{2}):(\d{2})$/, // %Y-%m-%d %H:%M:%S
];

export const ACCEPTED_TIMESTAMP_SHAPES =
  '%Y-%m-%d:%H-%M, %Y-%m-%d_%H-%M, %Y-%m-%d:%H:%M:%S, %Y-%m-%d %H:%M:%S';

export function parseCatchupTimestamp(value: string): string | null {
  const trimmed = value.trim();
  for (const shape of CATCHUP_TIMESTAMP_SHAPES) {
    const match = shape.exec(trimmed);
    if (!match) continue;
    const [, date, hour, minute, second] = match;
    return `${date}T${hour}:${minute}:${second ?? '00'}`;
  }
  return null;
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
