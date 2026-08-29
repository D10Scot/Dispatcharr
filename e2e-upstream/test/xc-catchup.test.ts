import { describe, it, expect } from 'vitest';
import {
  CatchupDecodeError,
  parseCatchupPath,
  parseCatchupQuery,
  parseCatchupTimestamp,
} from '../src/xc/catchup.js';

describe('parseCatchupTimestamp', () => {
  it('accepts all four shapes build_timeshift_candidate_urls emits', () => {
    // apps/timeshift/helpers.py: three PATH shapes then four QUERY shapes,
    // drawn from these four strftime formats. A provider that recognises only
    // one silently turns the cascade into "the first shape wins", which is
    // the exact behaviour G10 exists to test.
    for (const value of [
      '2026-08-29:14-00',      // %Y-%m-%d:%H-%M      (PATH, and QUERY colon-dash)
      '2026-08-29_14-00',      // %Y-%m-%d_%H-%M      (PATH, and QUERY underscore)
      '2026-08-29:14:00:00',   // %Y-%m-%d:%H:%M:%S   (PATH, and QUERY colon-seconds)
      '2026-08-29 14:00:00',   // %Y-%m-%d %H:%M:%S   (QUERY SQL)
    ]) {
      expect(parseCatchupTimestamp(value)).toBe('2026-08-29T14:00:00');
    }
  });

  it('returns null for anything else', () => {
    expect(parseCatchupTimestamp('yesterday')).toBeNull();
    expect(parseCatchupTimestamp('1756476000')).toBeNull();
  });
});

describe('parseCatchupPath', () => {
  it('reads the PATH layout segments', () => {
    const request = parseCatchupPath('/timeshift/user/pass/65/2026-08-29:14-00/7.ts')!;
    expect(request).toMatchObject({
      layout: 'path',
      username: 'user',
      password: 'pass',
      durationMinutes: 65,
      start: '2026-08-29:14-00',
      startIso: '2026-08-29T14:00:00',
      streamId: 7,
    });
  });

  it('URL-decodes credentials', () => {
    // build_timeshift_url_format_b quotes username and password with safe=''.
    const request = parseCatchupPath('/timeshift/us%40er/p%2Fss/60/2026-08-29:14-00/1.ts')!;
    expect(request.username).toBe('us@er');
    expect(request.password).toBe('p/ss');
  });

  it('returns undefined for a non-catch-up path', () => {
    expect(parseCatchupPath('/live/user/pass/1.ts')).toBeUndefined();
  });

  it('throws CatchupDecodeError naming the field on a malformed percent-escape', () => {
    // Same class of bug as the /live/ and /movie|series/ routes: a bad
    // escape must 400 naming the field, never 500 with no log entry.
    expect(() => parseCatchupPath('/timeshift/%zz/pass/65/2026-08-29:14-00/1.ts')).toThrow(
      CatchupDecodeError
    );
    try {
      parseCatchupPath('/timeshift/%zz/pass/65/2026-08-29:14-00/1.ts');
      expect.unreachable();
    } catch (error) {
      expect(error).toBeInstanceOf(CatchupDecodeError);
      expect((error as CatchupDecodeError).field).toBe('username');
    }

    try {
      parseCatchupPath('/timeshift/user/%zz/65/2026-08-29:14-00/1.ts');
      expect.unreachable();
    } catch (error) {
      expect((error as CatchupDecodeError).field).toBe('password');
    }

    try {
      parseCatchupPath('/timeshift/user/pass/65/%zz/1.ts');
      expect.unreachable();
    } catch (error) {
      expect((error as CatchupDecodeError).field).toBe('start');
    }
  });
});

describe('parseCatchupQuery', () => {
  it('reads the QUERY layout parameters, including an SQL timestamp with a space', () => {
    // build_timeshift_url_format_a interpolates `start` raw — only username
    // and password are quoted — so the SQL shape arrives percent-encoded by
    // requests. URLSearchParams decodes it; splitting on '+' would not.
    const url = new URL(
      'http://h/s/x/streaming/timeshift.php?username=user&password=pass&stream=7&start=2026-08-29%2014%3A00%3A00&duration=65'
    );
    expect(parseCatchupQuery(url)).toMatchObject({
      layout: 'query',
      username: 'user',
      password: 'pass',
      streamId: 7,
      startIso: '2026-08-29T14:00:00',
      durationMinutes: 65,
    });
  });

  it('returns undefined when a required parameter is missing', () => {
    expect(parseCatchupQuery(new URL('http://h/x?username=user'))).toBeUndefined();
  });
});
