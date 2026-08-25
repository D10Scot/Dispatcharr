import { test, expect, UpstreamClient } from '../../fixtures';

// toControl() is a safety property, not a convenience: it must never pass an
// unrecognised URL through, because that is how a test would end up making a
// real outbound request to whatever the URL happens to name. These cases are
// pure string/URL logic — no provider or network needed — so they instantiate
// UpstreamClient directly rather than going through the `upstream` fixture.

test.describe('UpstreamClient.toControl', () => {
  test('rewrites a URL under the internal origin to the control origin', () => {
    const client = new UpstreamClient('http://127.0.0.1:9402', 'http://e2e-upstream:8080');
    expect(client.toControl('http://e2e-upstream:8080/s/abc/stream/1.ts?chain=1')).toBe(
      'http://127.0.0.1:9402/s/abc/stream/1.ts?chain=1'
    );
  });

  test('throws on a URL that is a string prefix of the internal base but a different origin', () => {
    const client = new UpstreamClient('http://127.0.0.1:9402', 'http://e2e-upstream:8080');
    // `startsWith('http://e2e-upstream:8080')` would accept this — the
    // credentials-looking prefix reads as userinfo, so the actual origin is
    // http://evil.com. Comparing parsed origins must reject it.
    expect(() => client.toControl('http://e2e-upstream:8080@evil.com/x')).toThrow(
      /expected a URL under/
    );
  });

  test('is unaffected by a trailing slash on the configured internal base', () => {
    // A base with a trailing slash must not eat the leading '/' of the
    // rewritten path — a bug a string-slice implementation is prone to but
    // origin-based parsing (extracting pathname/search/hash from the parsed
    // URL) is not.
    const client = new UpstreamClient('http://127.0.0.1:9402', 'http://e2e-upstream:8080/');
    expect(client.toControl('http://e2e-upstream:8080/s/abc/playlist.m3u')).toBe(
      'http://127.0.0.1:9402/s/abc/playlist.m3u'
    );
  });

  test('throws on a URL under a different host entirely', () => {
    const client = new UpstreamClient('http://127.0.0.1:9402', 'http://e2e-upstream:8080');
    expect(() => client.toControl('http://example.com/foo')).toThrow(/expected a URL under/);
  });
});
